// Écrans de la montre (cf. Theme.swift et les maquettes). Un écran = une chose à
// faire ; états toujours ÉCRITS (pas seulement colorés).
import SwiftUI

struct ContentView: View {
    @EnvironmentObject var client: RemoteClient
    @ObservedObject private var replies = ReplyCenter.shared

    var body: some View {
        Group {
            // Hors connexion, seul l'accueil (mis en cache) reste affiché : un ready-check
            // ou une sélection seraient périmés.
            if let state = client.state, client.connected || state.screen == "default" {
                switch state.screen {
                case "queue": QueueView(queue: state.queue)
                case "champselect":
                    // Choix de départ d'abord (tant qu'aucun n'est demandé), puis le banc.
                    if let choices = state.champselect?.choices, !choices.isEmpty, client.pendingChamp == nil {
                        ChoiceView(choices: choices, timer: state.champselect?.timer)
                    } else {
                        ChampSelectView(select: state.champselect)
                    }
                default: HomeView(state: state)
                }
            } else {
                ConnectingView()
            }
        }
        .overlay(alignment: .top) {
            if client.state != nil && !client.connected && client.state?.screen != "default" {
                Label("connexion…", systemImage: "antenna.radiowaves.left.and.right")
                    .font(.system(size: 11, weight: .semibold)).foregroundStyle(Theme.muted)
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(Theme.raised, in: Capsule())
            }
        }
        .overlay(alignment: .bottom) {
            if let message = client.message {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(.system(size: 13, weight: .semibold))
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 10).padding(.vertical, 6)
                    .background(Theme.raised, in: Capsule())
            }
        }
        .sheet(item: $replies.target) { target in ReplyView(target: target) }   // « Répondre… »
        .task { client.start() }
    }
}

/// Première connexion : durée écoulée et dernière erreur (pour diagnostiquer la lenteur).
struct ConnectingView: View {
    @EnvironmentObject var client: RemoteClient

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            VStack(spacing: 8) {
                ProgressView().tint(Theme.accent)
                Text("Connexion au Pi…").font(.system(size: 14)).foregroundStyle(Theme.muted)
                let seconds = Int(context.date.timeIntervalSince(client.connectingSince))
                Text(([seconds >= 2 ? "\(seconds) s" : nil, client.lastError].compactMap { $0 })
                        .joined(separator: " · "))
                    .font(.system(size: 11)).foregroundStyle(Color(white: 0.56)).monospacedDigit()
            }
        }
    }
}

// MARK: - Accueil

/// Accueil : « Jouer » (comme sur le Pi), sinon le lobby ; invitation reçue en plein écran.
struct HomeView: View {
    @EnvironmentObject var client: RemoteClient
    let state: RemoteState
    @State private var confirmQuit = false
    @State private var showSettings = false

    /// Pi joint (état frais) ET PC connecté au Pi : sans le 1er, l'état affiché est
    /// celui du cache et on ne sait rien du PC.
    private var online: Bool { client.connected && state.agent == true }
    private var status: (text: String, filled: Bool) {
        if !client.connected { return (client.lastError ?? "connexion au Pi…", false) }
        return state.agent == true ? ("PC connecté", true) : ("PC hors ligne", false)
    }

    var body: some View {
        if online, let invitation = state.home?.invitation, state.screen == "default" {
            InvitationView(invitation: invitation)
        } else if online, let lobby = state.home?.lobby, state.screen == "default" {
            LobbyView(lobby: lobby)
        } else if online, state.home?.playBusy == true {
            LaunchingView(status: state.home?.playStatus ?? "…")
        } else {
            VStack(spacing: 8) {
                HStack {
                    Button { showSettings = true } label: {
                        Image(systemName: "gearshape.fill").font(.system(size: 15))
                            .foregroundStyle(Theme.accent)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Réglages")
                    Text("LolRemote").font(.system(size: 15, weight: .semibold)).foregroundStyle(Theme.accent)
                    Spacer()
                    Label(status.text, systemImage: status.filled ? "circle.fill" : "circle")
                        .font(.system(size: 11)).foregroundStyle(Theme.muted)
                        .labelStyle(DotLabelStyle())
                        .lineLimit(1).minimumScaleFactor(0.6)
                }
                .padding(.horizontal, 6)
                Spacer(minLength: 0)
                if !client.connected {
                    ProgressView().tint(Theme.accent)
                    Text("Connexion au Pi…").font(.system(size: 14)).foregroundStyle(Theme.muted)
                } else if !online {
                    Text("Allume le PC pour jouer").font(.system(size: 14)).foregroundStyle(Theme.muted)
                } else if state.screen == "lol" || state.screen == "postgame" {
                    Image(systemName: "gamecontroller.fill").font(.system(size: 30)).foregroundStyle(Theme.accent)
                    Text(state.screen == "lol" ? "En partie" : "Fin de partie")
                        .font(.system(size: 18, weight: .bold))
                } else {
                    Button { client.send(["action": "play"]) } label: {
                        HStack(spacing: 10) {
                            Image(systemName: "play.fill").font(.system(size: 24))
                            VStack(alignment: .leading, spacing: 1) {
                                Text("Jouer").font(.system(size: 19, weight: .bold))
                                Text(playSubtitle).font(.system(size: 12, weight: .medium))
                                    .lineLimit(1).minimumScaleFactor(0.7)
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.horizontal, 14)
                    }
                    .buttonStyle(PrimaryButtonStyle(height: 72))
                    .disabled(client.busy)
                    if let status = state.home?.playStatus, !status.isEmpty {
                        Text(status).font(.system(size: 12)).foregroundStyle(Theme.muted)   // message final
                    }
                    if state.home?.client == true {
                        Button { confirmQuit = true } label: {
                            Label("Fermer League", systemImage: "power")
                        }
                        .buttonStyle(SecondaryButtonStyle(height: 32))
                        .disabled(client.busy)
                    }
                }
                Spacer(minLength: 0)
                LatencyFooter()
            }
            .sheet(isPresented: $showSettings) { SettingsView() }
            .confirmationDialog("Fermer League ?", isPresented: $confirmQuit) {
                Button("Fermer League", role: .destructive) { client.send(["action": "quit_client"]) }
                Button("Annuler", role: .cancel) {}
            } message: {
                Text("Le client se ferme proprement (comme sa croix).")
            }
        }
    }

    private var playSubtitle: String {
        let friend = state.home?.playInvite ?? ""
        return friend.isEmpty ? "ARAM Chaos" : "ARAM Chaos + \(friend)"
    }
}

/// Lancement en cours : étape écrite + Annuler.
struct LaunchingView: View {
    @EnvironmentObject var client: RemoteClient
    let status: String

    var body: some View {
        VStack(spacing: 8) {
            ScreenHeader(title: "Lancement")
            Spacer(minLength: 0)
            ProgressView().tint(Theme.accent).scaleEffect(1.6).frame(height: 44)
            Text(status).font(.system(size: 16, weight: .semibold)).multilineTextAlignment(.center)
            Spacer(minLength: 0)
            Button { client.send(["action": "play_cancel"]) } label: {
                Label("Annuler", systemImage: "xmark")
            }
            .buttonStyle(SecondaryButtonStyle(height: 42))
        }
    }
}

/// Invitation reçue : plein écran, Rejoindre / Refuser.
struct InvitationView: View {
    @EnvironmentObject var client: RemoteClient
    let invitation: Invitation

    var body: some View {
        VStack(spacing: 6) {
            Spacer(minLength: 0)
            Avatar(name: invitation.from ?? "?", size: 42)
            Text("\(invitation.from ?? "?") t'invite").font(.system(size: 16, weight: .bold))
                .multilineTextAlignment(.center).lineLimit(2)
            if let queue = invitation.queueName, !queue.isEmpty {
                Text(queue).font(.system(size: 12)).foregroundStyle(Theme.muted)
            }
            Spacer(minLength: 0)
            Button { client.send(["action": "invite_accept", "invitationId": invitation.id]) } label: {
                Label("Rejoindre", systemImage: "checkmark")
            }
            .buttonStyle(PrimaryButtonStyle(height: 44))
            .doubleTapAction()
            Button { client.send(["action": "invite_decline", "invitationId": invitation.id]) } label: {
                Label("Refuser", systemImage: "xmark")
            }
            .buttonStyle(SecondaryButtonStyle(height: 36))
        }
        .disabled(client.busy)
    }
}

// MARK: - Lobby

struct LobbyView: View {
    @EnvironmentObject var client: RemoteClient
    let lobby: Lobby
    @State private var choosingFriend = false

    private var count: Int { (lobby.members ?? []).count }

    var body: some View {
        VStack(spacing: 6) {
            ScrollView {
                VStack(spacing: 5) {
                    ScreenHeader(title: lobby.queueName ?? "Lobby", trailing: "\(count)/5")
                    ForEach(lobby.members ?? [], id: \.self) { member in
                        HStack(spacing: 8) {
                            Avatar(name: member.name)
                            (Text(member.name).font(.system(size: 13, weight: .medium))
                             + Text(member.isSelf == true ? " (toi)" : "").font(.system(size: 13))
                                .foregroundColor(Theme.muted))
                                .lineLimit(1)
                            Spacer(minLength: 0)
                            if member.isLeader == true {
                                Text("chef").font(.system(size: 10, weight: .semibold))   // écrit, pas une couleur
                                    .foregroundStyle(Theme.ink)
                                    .padding(.horizontal, 5).padding(.vertical, 1)
                                    .background(Theme.accent, in: RoundedRectangle(cornerRadius: 5))
                            }
                        }
                        .padding(.horizontal, 8).frame(minHeight: 32)
                        .background(Theme.card, in: RoundedRectangle(cornerRadius: 12))
                    }
                    ForEach(lobby.invites ?? [], id: \.self) { invite in
                        HStack(spacing: 8) {
                            Circle().strokeBorder(Color(white: 0.4), style: StrokeStyle(lineWidth: 1.5, dash: [3]))
                                .frame(width: 22, height: 22)
                            Text(invite.name).font(.system(size: 13)).foregroundStyle(Color(white: 0.78)).lineLimit(1)
                            Spacer(minLength: 0)
                            Text("invité…").font(.system(size: 11)).foregroundStyle(Theme.muted)
                        }
                        .padding(.horizontal, 8).frame(minHeight: 32)
                        .overlay(RoundedRectangle(cornerRadius: 12)
                            .strokeBorder(Theme.raised, style: StrokeStyle(lineWidth: 1.5, dash: [4])))
                    }
                    if !(lobby.friends ?? []).isEmpty {
                        Button { choosingFriend = true } label: {
                            HStack(spacing: 8) {
                                Image(systemName: "plus.circle.fill").font(.system(size: 20))
                                Text("Inviter un ami").font(.system(size: 13, weight: .semibold))
                                Spacer(minLength: 0)
                            }
                            .foregroundStyle(Theme.accent)
                            .padding(.horizontal, 8).frame(minHeight: 32)
                            .overlay(RoundedRectangle(cornerRadius: 12)
                                .strokeBorder(Theme.raised, style: StrokeStyle(lineWidth: 1.5, dash: [4])))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            Button { client.send(["action": "leave_lobby"]) } label: {
                Label(lobby.isLeader == true ? "Fermer le lobby" : "Quitter le lobby", systemImage: "xmark")
            }
            .buttonStyle(SecondaryButtonStyle(height: 30))
            .disabled(client.busy)
            if lobby.isLeader == true {
                Button { client.send(["action": "start_queue"]) } label: {
                    Label(lobby.canStart == true ? "Lancer la partie" : "Pas encore possible",
                          systemImage: "play.fill")
                }
                .buttonStyle(PrimaryButtonStyle(height: 42))
                .doubleTapAction()
                .disabled(client.busy || lobby.canStart != true)
                .opacity(lobby.canStart == true ? 1 : 0.5)
            } else {
                Text("Le chef lance la partie").font(.system(size: 12)).foregroundStyle(Theme.muted)
            }
        }
        .sheet(isPresented: $choosingFriend) {
            FriendPicker(friends: lobby.friends ?? []) { friend in
                client.send(["action": "invite", "summonerId": friend.summonerId])
                choosingFriend = false
            }
        }
    }
}

/// Liste des amis invitables : l'ami par défaut en tête, en bouton accent.
struct FriendPicker: View {
    let friends: [Friend]
    let pick: (Friend) -> Void

    var body: some View {
        ScrollView {
            VStack(spacing: 5) {
                ScreenHeader(title: "Inviter")
                ForEach(friends) { friend in
                    Button { pick(friend) } label: {
                        HStack(spacing: 8) {
                            if friend.isDefault == true {
                                Image(systemName: "star.fill").font(.system(size: 14))
                            }
                            VStack(alignment: .leading, spacing: 0) {
                                Text(friend.name).font(.system(size: 14, weight: friend.isDefault == true ? .bold : .medium))
                                    .lineLimit(1)
                                Text((friend.isDefault == true ? "par défaut · " : "") + (friend.status ?? ""))
                                    .font(.system(size: 11))
                                    .foregroundStyle(friend.isDefault == true ? Theme.ink : Theme.muted)
                            }
                            Spacer(minLength: 0)
                        }
                        .foregroundStyle(friend.isDefault == true ? Theme.ink : .white)
                        .padding(.horizontal, 10).frame(minHeight: 38)
                        .background(friend.isDefault == true ? Theme.accent : Theme.card,
                                    in: RoundedRectangle(cornerRadius: 13))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}

// MARK: - File

struct QueueView: View {
    @EnvironmentObject var client: RemoteClient
    let queue: QueueInfo?

    var body: some View {
        if queue?.state == "readycheck" {
            ReadyCheckView(queue: queue)
        } else {
            VStack(spacing: 6) {
                ScreenHeader(title: "En file")
                Spacer(minLength: 0)
                Text(clock(queue?.timeInQueue ?? 0))
                    .font(.system(size: 50, weight: .semibold)).monospacedDigit()
                if let estimated = queue?.estimated, estimated > 0 {
                    Text("estimé \(clock(estimated))").font(.system(size: 12)).foregroundStyle(Theme.muted)
                }
                Spacer(minLength: 0)
                Button { client.send(["action": "cancel_queue"]) } label: {
                    Label("Quitter la file", systemImage: "xmark")
                }
                .buttonStyle(SecondaryButtonStyle(height: 40))
                .disabled(client.busy)
            }
        }
    }

    private func clock(_ seconds: Int) -> String {
        String(format: "%d:%02d", seconds / 60, seconds % 60)
    }
}

/// Partie trouvée : anneau qui se vide, Accepter énorme, Refuser plus petit.
struct ReadyCheckView: View {
    @EnvironmentObject var client: RemoteClient
    let queue: QueueInfo?
    private let window = 10.0     // durée d'un ready-check (s)

    var body: some View {
        let remaining = queue?.remaining ?? 0
        VStack(spacing: 6) {
            Spacer(minLength: 0)
            CountdownRing(fraction: Double(remaining) / window, label: "\(remaining)")
            switch client.pendingResponse ?? queue?.response {
            case "Accepted":
                Label("Acceptée", systemImage: "checkmark.circle.fill")
                    .font(.system(size: 17, weight: .bold)).foregroundStyle(Theme.accent)
                Text("en attente des autres").font(.system(size: 12)).foregroundStyle(Theme.muted)
                Spacer(minLength: 0)
            case "Declined":
                Label("Refusée", systemImage: "xmark.circle.fill").font(.system(size: 17, weight: .bold))
                Spacer(minLength: 0)
            default:
                Text("Partie trouvée !").font(.system(size: 17, weight: .bold))
                Spacer(minLength: 0)
                Button { client.accept(true) } label: { Label("Accepter", systemImage: "checkmark") }
                    .buttonStyle(PrimaryButtonStyle(height: 46))
                    .doubleTapAction()
                Button { client.accept(false) } label: { Label("Refuser", systemImage: "xmark") }
                    .buttonStyle(SecondaryButtonStyle(height: 32))
            }
        }
        .disabled(client.busy)
    }
}

// MARK: - Sélection

/// Début de sélection : 2-3 champions proposés, on en touche un (verrouillé aussitôt).
struct ChoiceView: View {
    @EnvironmentObject var client: RemoteClient
    let choices: [Champ]
    let timer: SelectTimer?

    var body: some View {
        VStack(spacing: 6) {
            ScreenHeader(title: "Choisis", trailing: timer?.left.map { "\($0) s" } ?? "")
            Spacer(minLength: 0)
            HStack(spacing: 8) {
                ForEach(choices) { champ in
                    Button { client.pick(champ) } label: {
                        VStack(spacing: 5) {
                            ChampIcon(championId: champ.championId, size: choices.count > 2 ? 50 : 70)
                            Text(champ.label)   // nom toujours écrit
                                .font(.system(size: 13, weight: .semibold)).lineLimit(1).minimumScaleFactor(0.6)
                        }
                        .frame(maxWidth: .infinity).padding(.vertical, 8)
                        .background(Theme.card, in: RoundedRectangle(cornerRadius: 17))
                    }
                    .buttonStyle(.plain)
                }
            }
            Spacer(minLength: 0)
            Text("l'autre ira sur le banc").font(.system(size: 11)).foregroundStyle(Theme.muted)
        }
        .disabled(client.busy)
    }
}

/// Sélection : ton champion en grand, puis le banc en grille de 3.
struct ChampSelectView: View {
    @EnvironmentObject var client: RemoteClient
    @EnvironmentObject var icons: IconStore
    let select: ChampSelect?

    private let columns = Array(repeating: GridItem(.flexible(), spacing: 4), count: 3)
    /// Champion affiché : la demande en cours d'abord (optimiste), sinon le réel.
    private var me: Champ? { client.pendingChamp ?? select?.me }
    private var iconIds: [Int] { [select?.me?.championId ?? 0] + (select?.bench ?? []).map(\.championId) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 9) {
                    ChampIcon(championId: me?.championId ?? 0, size: 40)
                        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.accent, lineWidth: 2).padding(-3))
                    VStack(alignment: .leading, spacing: 1) {
                        Text(me.flatMap { $0.championId > 0 ? $0.label : nil } ?? "…")
                            .font(.system(size: 16, weight: .bold)).lineLimit(1).minimumScaleFactor(0.7)
                        if let timer = select?.timer {
                            Text("\(timer.phase ?? "") · \(timer.left ?? 0) s")
                                .font(.system(size: 11)).foregroundStyle(Theme.muted).monospacedDigit()
                        }
                    }
                }
                .padding(.horizontal, 6)
                if let rerolls = select?.rerolls, rerolls > 0 {
                    Button { client.send(["action": "reroll"]) } label: {
                        Label("Relancer (\(rerolls))", systemImage: "dice.fill")
                    }
                    .buttonStyle(SecondaryButtonStyle(height: 32))
                }
                let bench = select?.bench ?? []
                Text(bench.isEmpty ? "BANC VIDE" : "BANC · touche pour prendre")
                    .font(.system(size: 10, weight: .semibold)).foregroundStyle(Theme.muted)
                    .padding(.horizontal, 6)
                LazyVGrid(columns: columns, spacing: 6) {
                    ForEach(bench) { champ in
                        Button { client.swap(champ) } label: {
                            VStack(spacing: 3) {
                                ChampIcon(championId: champ.championId, size: 46)
                                Text(champ.label)   // nom toujours écrit (pas que l'image)
                                    .font(.system(size: 10, weight: .medium)).lineLimit(1).minimumScaleFactor(0.6)
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

// MARK: - Éléments communs

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
                Theme.raised
            }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: size * 0.22))
        .task(id: championId) { icons.load(championId) }
    }
}

/// « réseau X ms · action Y ms » (diagnostic de lenteur), discret en bas de l'accueil.
struct LatencyFooter: View {
    @EnvironmentObject var client: RemoteClient

    var body: some View {
        VStack(spacing: 1) {
            if client.latencyMs != nil || client.actionMs != nil {
                Text([client.latencyMs.map { "réseau \($0) ms" }, client.actionMs.map { "action \($0) ms" }]
                        .compactMap { $0 }.joined(separator: " · "))
                    .monospacedDigit()
            }
        }
        .font(.system(size: 10)).foregroundStyle(Color(white: 0.56))
    }
}

/// Pastille + texte (statut du PC) : le texte porte l'information, la pastille l'appuie.
struct DotLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 4) {
            configuration.icon.font(.system(size: 7)).foregroundStyle(Theme.accent)
            configuration.title
        }
    }
}
