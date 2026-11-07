// Écrans de la montre. États toujours ÉCRITS (pas seulement colorés).
import SwiftUI

struct ContentView: View {
    @EnvironmentObject var client: RemoteClient

    var body: some View {
        Group {
            if let state = client.state, client.connected {
                switch state.screen {
                case "queue": QueueView(queue: state.queue)
                case "champselect":
                    // Choix de départ d'abord (tant qu'aucun n'est demandé), puis le banc.
                    if let choices = state.champselect?.choices, !choices.isEmpty, client.pendingChamp == nil {
                        ChoiceView(choices: choices, timer: state.champselect?.timer)
                    } else {
                        ChampSelectView(select: state.champselect)
                    }
                default: IdleView(state: state)
                }
            } else {
                VStack(spacing: 8) {
                    ProgressView()
                    Text("Connexion au Pi…").font(.footnote)
                }
            }
        }
        .overlay(alignment: .bottom) {
            if let message = client.message {
                Text(message)
                    .font(.footnote)
                    .multilineTextAlignment(.center)
                    .padding(6)
                    .background(.red.opacity(0.85), in: RoundedRectangle(cornerRadius: 8))
            }
        }
        .task { client.start() }
    }
}

struct IdleView: View {
    @EnvironmentObject var client: RemoteClient
    let state: RemoteState

    private var label: String {
        switch state.screen {
        case "lol": return "En partie"
        case "postgame": return "Fin de partie"
        default: return "Au menu"
        }
    }

    var body: some View {
        VStack(spacing: 6) {
            Text(state.agent == true ? "PC connecté" : "PC hors ligne").font(.headline)
            if state.agent == true { Text(label).foregroundStyle(.secondary) }
            // Mesures (diagnostic de lenteur) : Pi → montre et aller-retour d'une action.
            if client.latencyMs != nil || client.actionMs != nil {
                Text([client.latencyMs.map { "réseau \($0) ms" }, client.actionMs.map { "action \($0) ms" }]
                        .compactMap { $0 }.joined(separator: " · "))
                    .font(.system(size: 11)).foregroundStyle(.secondary).monospacedDigit()
            }
        }
    }
}

struct QueueView: View {
    @EnvironmentObject var client: RemoteClient
    let queue: QueueInfo?

    var body: some View {
        if queue?.state == "readycheck" {
            VStack(spacing: 8) {
                Text("Partie trouvée !").font(.headline)
                Text("\(queue?.remaining ?? 0) s").font(.title2).monospacedDigit()
                switch client.pendingResponse ?? queue?.response {
                case "Accepted": Text("✓ Acceptée").font(.headline)
                case "Declined": Text("✗ Refusée").font(.headline)
                default:
                    HStack {
                        Button("Accepter") { client.accept(true) }
                            .tint(.green)
                        Button("Refuser") { client.accept(false) }
                            .tint(.red)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(client.busy)
                }
            }
        } else {
            VStack(spacing: 6) {
                Text("En file").font(.headline)
                Text("\(queue?.timeInQueue ?? 0) s").font(.title3).monospacedDigit()
                if let estimated = queue?.estimated, estimated > 0 {
                    Text("estimé \(estimated) s").font(.footnote).foregroundStyle(.secondary)
                }
            }
        }
    }
}

struct ChampSelectView: View {
    @EnvironmentObject var client: RemoteClient
    let select: ChampSelect?

    @EnvironmentObject var icons: IconStore
    private let columns = [GridItem(.adaptive(minimum: 52), spacing: 6)]

    /// Champion affiché : la demande en cours d'abord (optimiste), sinon le réel.
    private var me: Champ? { client.pendingChamp ?? select?.me }
    private var iconIds: [Int] { [select?.me?.championId ?? 0] + (select?.bench ?? []).map(\.championId) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    ChampIcon(championId: me?.championId ?? 0, size: 44)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(me.flatMap { $0.championId > 0 ? $0.label : nil } ?? "…")
                            .font(.headline).lineLimit(1).minimumScaleFactor(0.7)
                        if let timer = select?.timer {
                            Text("\(timer.phase ?? "") \(timer.left ?? 0) s")
                                .font(.footnote).foregroundStyle(.secondary).monospacedDigit()
                        }
                    }
                }
                if let rerolls = select?.rerolls, rerolls > 0 {
                    Button("Relancer (\(rerolls))") { client.send(["action": "reroll"]) }
                }
                Text("Banc").font(.footnote).foregroundStyle(.secondary)
                let bench = select?.bench ?? []
                if bench.isEmpty {
                    Text("(vide)").foregroundStyle(.secondary)
                }
                LazyVGrid(columns: columns, spacing: 8) {
                    ForEach(bench) { champ in
                        Button {
                            client.swap(champ)
                        } label: {
                            VStack(spacing: 2) {
                                ChampIcon(championId: champ.championId, size: 48)
                                Text(champ.label)   // nom toujours écrit (pas que l'image)
                                    .font(.system(size: 10)).lineLimit(1).minimumScaleFactor(0.6)
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
        .disabled(client.busy)
        // Toutes les icônes demandées d'un coup (pas au fil du défilement).
        .task(id: iconIds) { for id in iconIds { icons.load(id) } }
    }
}

/// Début de sélection : 2-3 champions proposés, on en touche un (verrouillé aussitôt).
struct ChoiceView: View {
    @EnvironmentObject var client: RemoteClient
    let choices: [Champ]
    let timer: SelectTimer?

    var body: some View {
        VStack(spacing: 6) {
            Text("Choisis ton champion").font(.headline).lineLimit(1).minimumScaleFactor(0.7)
            if let left = timer?.left {
                Text("\(left) s").font(.footnote).foregroundStyle(.secondary).monospacedDigit()
            }
            HStack(spacing: 8) {
                ForEach(choices) { champ in
                    Button { client.pick(champ) } label: {
                        VStack(spacing: 3) {
                            ChampIcon(championId: champ.championId, size: choices.count > 2 ? 52 : 64)
                            Text(champ.label)   // nom toujours écrit
                                .font(.system(size: 11)).lineLimit(1).minimumScaleFactor(0.6)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .disabled(client.busy)
    }
}

/// Icône carrée du champion (servie par le Pi) ; case grise en attendant.
struct ChampIcon: View {
    @EnvironmentObject var icons: IconStore
    let championId: Int
    let size: CGFloat

    var body: some View {
        Group {
            if let image = icons.images[championId] {
                Image(uiImage: image).resizable().scaledToFill()
            } else {
                Color.gray.opacity(0.3)
            }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .task(id: championId) { icons.load(championId) }
    }
}
