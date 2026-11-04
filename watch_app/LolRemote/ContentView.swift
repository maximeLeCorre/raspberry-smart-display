// Écrans de la montre. États toujours ÉCRITS (pas seulement colorés).
import SwiftUI

struct ContentView: View {
    @EnvironmentObject var client: RemoteClient

    var body: some View {
        Group {
            if let state = client.state, client.connected {
                switch state.screen {
                case "queue": QueueView(queue: state.queue)
                case "champselect": ChampSelectView(select: state.champselect)
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
                switch queue?.response {
                case "Accepted": Text("✓ Acceptée").font(.headline)
                case "Declined": Text("✗ Refusée").font(.headline)
                default:
                    HStack {
                        Button("Accepter") { client.send(["action": "accept"]) }
                            .tint(.green)
                        Button("Refuser") { client.send(["action": "decline"]) }
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

    var body: some View {
        List {
            Section {
                Text(select?.me?.championName.isEmpty == false ? select!.me!.championName : "…")
                    .font(.headline)
                if let timer = select?.timer {
                    Text("\(timer.phase ?? "") \(timer.left ?? 0) s")
                        .font(.footnote).foregroundStyle(.secondary).monospacedDigit()
                }
                if let rerolls = select?.rerolls, rerolls > 0 {
                    Button("Relancer (\(rerolls))") { client.send(["action": "reroll"]) }
                }
            }
            Section("Banc") {
                let bench = select?.bench ?? []
                if bench.isEmpty {
                    Text("(vide)").foregroundStyle(.secondary)
                }
                ForEach(bench) { champ in
                    Button(champ.label) {
                        client.send(["action": "swap", "championId": champ.championId])
                    }
                }
            }
        }
        .disabled(client.busy)
    }
}
