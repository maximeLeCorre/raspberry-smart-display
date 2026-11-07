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

/// Accueil : état du PC, bouton « Jouer une ARAM Chaos » (comme sur le Pi),
/// puis le lobby (joueurs présents, invitations) et « Lancer la partie ».
struct IdleView: View {
    @EnvironmentObject var client: RemoteClient
    let state: RemoteState

    private var inGame: String? {
        switch state.screen {
        case "lol": return "En partie"
        case "postgame": return "Fin de partie"
        default: return nil
        }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 6) {
                Text(state.agent == true ? "PC connecté" : "PC hors ligne").font(.headline)
                if state.agent == true {
                    if let invitation = state.home?.invitation, inGame == nil {
                        InvitationSection(invitation: invitation)
                    }
                    if let inGame {
                        Text(inGame).foregroundStyle(.secondary)
                    } else if let lobby = state.home?.lobby {
                        LobbySection(lobby: lobby)
                    } else {
                        PlaySection(home: state.home)
                    }
                    if let status = state.home?.playStatus, !status.isEmpty, state.home?.playBusy != true {
                        Text(status).font(.footnote).foregroundStyle(.secondary)   // message final
                    }
                }
                // Mesures (diagnostic de lenteur) : Pi → montre et aller-retour d'une action.
                if client.latencyMs != nil || client.actionMs != nil {
                    Text([client.latencyMs.map { "réseau \($0) ms" }, client.actionMs.map { "action \($0) ms" }]
                            .compactMap { $0 }.joined(separator: " · "))
                        .font(.system(size: 11)).foregroundStyle(.secondary).monospacedDigit()
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct InvitationSection: View {
    @EnvironmentObject var client: RemoteClient
    let invitation: Invitation

    var body: some View {
        Text("Invitation de \(invitation.from ?? "?")").font(.headline).lineLimit(2)
        if let queue = invitation.queueName, !queue.isEmpty {
            Text(queue).font(.footnote).foregroundStyle(.secondary)
        }
        HStack {
            Button("Accepter") { client.send(["action": "invite_accept", "invitationId": invitation.id]) }
                .tint(.green)
            Button("Refuser") { client.send(["action": "invite_decline", "invitationId": invitation.id]) }
                .tint(.red)
        }
        .buttonStyle(.borderedProminent)
        .disabled(client.busy)
    }
}

struct PlaySection: View {
    @EnvironmentObject var client: RemoteClient
    let home: Home?

    var body: some View {
        if home?.playBusy == true {
            Text(home?.playStatus ?? "…").font(.footnote)
            Button("Annuler") { client.send(["action": "play_cancel"]) }
                .tint(.red)
        } else {
            Button("Jouer une ARAM Chaos") { client.send(["action": "play"]) }
                .tint(.green)
                .disabled(client.busy)
        }
    }
}

struct LobbySection: View {
    @EnvironmentObject var client: RemoteClient
    let lobby: Lobby
    @State private var choosingFriend = false

    var body: some View {
        Text(lobby.queueName ?? "Lobby").font(.footnote).foregroundStyle(.secondary)
        ForEach(lobby.members ?? [], id: \.self) { member in
            HStack {
                Text(member.name + (member.isSelf == true ? " (toi)" : ""))
                    .lineLimit(1).minimumScaleFactor(0.7)
                Spacer()
                if member.isLeader == true {
                    Text("chef").font(.caption2).foregroundStyle(.secondary)   // écrit, pas une couleur
                }
            }
        }
        ForEach(lobby.invites ?? [], id: \.self) { invite in
            Text("\(invite.name) : invité…").font(.footnote).foregroundStyle(.secondary)
        }
        // Invitations : l'ami par défaut en un appui, sinon la liste des amis en ligne.
        if let friend = lobby.friends?.first(where: { $0.isDefault == true }) {
            Button("Inviter \(friend.name)") { invite(friend) }
                .disabled(client.busy)
        }
        if !(lobby.friends ?? []).isEmpty {
            Button("Inviter un ami…") { choosingFriend = true }
                .sheet(isPresented: $choosingFriend) {
                    List(lobby.friends ?? []) { friend in
                        Button {
                            invite(friend)
                            choosingFriend = false
                        } label: {
                            VStack(alignment: .leading) {
                                Text(friend.name).lineLimit(1)
                                Text(friend.status ?? "").font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
        }
        if lobby.isLeader == true {
            Button("Lancer la partie") { client.send(["action": "start_queue"]) }
                .tint(.green)
                .disabled(client.busy || lobby.canStart != true)
            if lobby.canStart != true {
                Text("Lancement pas encore possible").font(.caption2).foregroundStyle(.secondary)
            }
        } else {
            Text("Le chef lance la partie").font(.footnote).foregroundStyle(.secondary)
        }
    }

    private func invite(_ friend: Friend) {
        client.send(["action": "invite", "summonerId": friend.summonerId])
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
                Button("Quitter la file") { client.send(["action": "cancel_queue"]) }
                    .disabled(client.busy)
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
