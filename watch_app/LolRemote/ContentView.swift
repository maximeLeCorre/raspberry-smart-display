// Écrans de la montre (cf. Theme.swift et les maquettes). Un écran = une chose à
// faire ; états toujours ÉCRITS (pas seulement colorés).
import SwiftUI
import WatchKit

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
                case "lol": GameView(game: state.game)
                case "postgame": PostGameView(post: state.postgame)
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

/// Accueil = menu en liste (une ligne par destination, défilable à la couronne) ;
/// invitation reçue, lobby, lancement ou reconnexion en plein écran.
struct HomeView: View {
    @EnvironmentObject var client: RemoteClient
    let state: RemoteState
    @State private var confirmQuit = false

    /// Pi joint (état frais) ET PC connecté au Pi : sans le 1er, l'état affiché est
    /// celui du cache et on ne sait rien du PC.
    private var online: Bool { client.connected && state.agent == true }
    private var home: Home? { state.home }
    private var status: (text: String, filled: Bool) {
        if !client.connected { return (client.lastError ?? "connexion au Pi…", false) }
        return state.agent == true ? ("PC connecté", true) : ("PC hors ligne", false)
    }

    var body: some View {
        if online, home?.reconnect == true, state.screen == "default" {
            ReconnectView()
        } else if online, let invitation = home?.invitation, state.screen == "default" {
            InvitationView(invitation: invitation)
        } else if online, let lobby = home?.lobby, state.screen == "default" {
            LobbyView(lobby: lobby)
        } else if online, home?.playBusy == true {
            LaunchingView(status: home?.playStatus ?? "…")
        } else {
            NavigationStack { menu }
        }
    }

    private var menu: some View {
        ScrollView {
            VStack(spacing: 6) {
                HStack {
                    Text("LolRemote").font(.system(size: 15, weight: .semibold)).foregroundStyle(Theme.accent)
                    Spacer()
                    Label(status.text, systemImage: status.filled ? "circle.fill" : "circle")
                        .font(.system(size: 11)).foregroundStyle(Theme.muted)
                        .labelStyle(DotLabelStyle())
                        .lineLimit(1).minimumScaleFactor(0.6)
                }
                .padding(.horizontal, 6)
                if !client.connected {
                    ProgressView().tint(Theme.accent).padding(.vertical, 8)
                } else if !online {
                    Text("Allume le PC pour jouer").font(.system(size: 14)).foregroundStyle(Theme.muted)
                        .padding(.vertical, 8)
                } else {
                    Button { client.send(["action": "play"]) } label: {
                        HStack(spacing: 10) {
                            Image(systemName: "play.fill").font(.system(size: 18))
                            VStack(alignment: .leading, spacing: 1) {
                                Text("Jouer").font(.system(size: 17, weight: .bold))
                                Text(playSubtitle).font(.system(size: 11, weight: .semibold))
                                    .lineLimit(1).minimumScaleFactor(0.7)
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.horizontal, 12)
                    }
                    .buttonStyle(PrimaryButtonStyle(height: 52))
                    .doubleTapAction()
                    .disabled(client.busy)
                    if let status = home?.playStatus, !status.isEmpty {
                        Text(status).font(.system(size: 12)).foregroundStyle(Theme.muted)   // message final
                    }
                    if let friends = home?.friends {
                        NavigationLink { FriendsView() } label: {
                            MenuRow(icon: "person.2.fill", title: "Amis",
                                    value: "\(friends.filter { $0.free == true }.count) dispo")
                        }
                        .buttonStyle(.plain)
                    }
                    if let rewards = home?.rewards {
                        NavigationLink { RewardsView() } label: {
                            MenuRow(icon: "gift.fill", title: "Récompenses",
                                    value: rewards.count == 0 ? "aucune" : "",
                                    badge: rewards.count > 0 ? "\(rewards.count)" : nil)
                        }
                        .buttonStyle(.plain)
                    }
                    if home?.client == true {
                        Button { confirmQuit = true } label: {
                            MenuRow(icon: "power", title: "Fermer League", dimmed: true)
                        }
                        .buttonStyle(.plain)
                        .disabled(client.busy)
                    }
                }
                NavigationLink { SettingsView() } label: {
                    MenuRow(icon: "gearshape.fill", title: "Réglages", dimmed: true)
                }
                .buttonStyle(.plain)
                LatencyFooter().padding(.top, 2)
            }
        }
        .confirmationDialog("Fermer League ?", isPresented: $confirmQuit) {
            Button("Fermer League", role: .destructive) { client.send(["action": "quit_client"]) }
            Button("Annuler", role: .cancel) {}
        } message: {
            Text("Le client se ferme proprement (comme sa croix).")
        }
    }

    private var playSubtitle: String {
        let queue = home?.playQueue ?? ""
        let friends = home?.playInvite ?? ""
        let base = queue.isEmpty ? "Lobby" : queue
        return friends.isEmpty ? base : "\(base) + \(friends)"
    }
}

/// Ligne du menu : icône, titre, valeur (ou pastille chiffrée) à droite.
struct MenuRow: View {
    let icon: String
    let title: String
    var value: String = ""
    var badge: String? = nil
    var dimmed = false

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon).font(.system(size: 15))
                .foregroundStyle(dimmed ? Theme.muted : Theme.accent).frame(width: 20)
            Text(title).font(.system(size: 15, weight: .medium)).lineLimit(1)
            Spacer(minLength: 4)
            if let badge {
                Text(badge).font(.system(size: 11, weight: .bold)).foregroundStyle(Theme.ink)
                    .padding(.horizontal, 6).padding(.vertical, 1)
                    .background(Theme.accent, in: RoundedRectangle(cornerRadius: 5))
            } else if !value.isEmpty {
                Text(value).font(.system(size: 12)).foregroundStyle(Theme.muted).lineLimit(1)
            }
        }
        .padding(.horizontal, 10)
        .frame(maxWidth: .infinity, minHeight: 44)
        .background(Theme.card, in: RoundedRectangle(cornerRadius: 14))
        .contentShape(Rectangle())
    }
}

/// Le jeu a planté pendant une partie : la rejoindre depuis le poignet.
struct ReconnectView: View {
    @EnvironmentObject var client: RemoteClient

    var body: some View {
        VStack(spacing: 6) {
            ScreenHeader(title: "Jeu fermé")
            Spacer(minLength: 0)
            Image(systemName: "arrow.clockwise").font(.system(size: 26, weight: .semibold))
                .foregroundStyle(Theme.accent)
                .frame(width: 58, height: 58).background(Theme.card, in: Circle())
            Text("La partie continue sans toi").font(.system(size: 15, weight: .bold))
                .multilineTextAlignment(.center)
            Spacer(minLength: 0)
            Button { client.send(["action": "reconnect"]) } label: {
                Label("Reconnecter", systemImage: "arrow.clockwise")
            }
            .buttonStyle(PrimaryButtonStyle(height: 46))
            .doubleTapAction()
            .disabled(client.busy)
        }
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

// MARK: - Fin de partie

/// Résultat d'abord (victoire/défaite écrite, score), puis Honorer et Retour au lobby.
struct PostGameView: View {
    @EnvironmentObject var client: RemoteClient
    let post: PostGame?
    @State private var showHonor = false

    private var result: GameResult? { post?.result }
    private var votesLeft: Int { post?.honor?.votesLeft ?? 0 }

    var body: some View {
        VStack(spacing: 5) {
            ScreenHeader(title: "Fin de partie", trailing: result?.mode ?? "")
            Spacer(minLength: 0)
            switch result?.win {
            case true?: Text("VICTOIRE").font(.system(size: 26, weight: .heavy)).kerning(1)
            case false?: Text("DÉFAITE").font(.system(size: 26, weight: .heavy)).kerning(1)
            case nil: Text("Résultat en attente…").font(.system(size: 15, weight: .semibold))
            }
            if let duration = result?.duration, duration > 0 {
                Text(clock(duration)).font(.system(size: 11)).foregroundStyle(Theme.muted).monospacedDigit()
            }
            if let kda = result?.kda, kda.count == 3 {
                HStack(spacing: 8) {
                    if let id = result?.championId, id > 0 { ChampIcon(championId: id, size: 32) }
                    Text("\(kda[0])/\(kda[1])/\(kda[2])").font(.system(size: 20, weight: .bold)).monospacedDigit()
                }
                .padding(.top, 4)
            }
            Spacer(minLength: 0)
            if post?.honor != nil {
                Button { showHonor = true } label: {
                    Label(votesLeft > 0 ? "Honorer · \(votesLeft) vote\(votesLeft > 1 ? "s" : "")" : "Honneurs donnés",
                          systemImage: "heart")
                }
                .buttonStyle(SecondaryButtonStyle(height: 32))
            }
            Button { client.send(["action": "play_again"]) } label: {
                Label("Retour au lobby", systemImage: "arrow.uturn.backward")
            }
            .buttonStyle(PrimaryButtonStyle(height: 40))
            .doubleTapAction()
            .disabled(client.busy)
        }
        .sheet(isPresented: $showHonor) { HonorView() }
    }
}

/// Honorer des joueurs (cœur, comme le client) ; lit l'état courant du client.
struct HonorView: View {
    @EnvironmentObject var client: RemoteClient
    @State private var pending: Set<String> = []      // honorés, en attente de l'état du Pi

    private var honor: Honor? { client.state?.postgame?.honor }
    private var votesLeft: Int { max(0, (honor?.votesLeft ?? 0) - pending.count) }

    var body: some View {
        ScrollView {
            VStack(spacing: 5) {
                ScreenHeader(title: "Honorer", trailing: "\(votesLeft) vote\(votesLeft > 1 ? "s" : "")")
                if let honor {
                    group("Ton équipe", honor.allies)
                    if !honor.opponents.isEmpty { group("Adversaires", honor.opponents) }
                } else {
                    Text("Honneurs plus disponibles").font(.system(size: 12)).foregroundStyle(Theme.muted)
                }
            }
        }
        .onChange(of: client.message) { _, message in if message != nil { pending.removeAll() } }  // refusé
    }

    @ViewBuilder
    private func group(_ title: String, _ players: [HonorPlayer]) -> some View {
        Text(title).font(.system(size: 11, weight: .semibold)).foregroundStyle(Theme.muted)
            .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 6)
        ForEach(players, id: \.puuid) { player in
            let honored = player.honored || pending.contains(player.puuid)
            HStack(spacing: 8) {
                ChampIcon(championId: player.championId, size: 26)
                VStack(alignment: .leading, spacing: 0) {
                    Text(player.name).font(.system(size: 13, weight: .medium)).lineLimit(1)
                    if let champion = player.championName, !champion.isEmpty {
                        Text(champion).font(.system(size: 10)).foregroundStyle(Theme.muted).lineLimit(1)
                    }
                }
                Spacer(minLength: 0)
                if honored {
                    Label("honoré", systemImage: "heart.fill")            // écrit, pas qu'une couleur
                        .font(.system(size: 11, weight: .semibold)).foregroundStyle(Theme.accent)
                } else if votesLeft > 0 {
                    Button {
                        pending.insert(player.puuid)
                        client.send(["action": "honor", "puuid": player.puuid])
                    } label: {
                        Image(systemName: "heart").font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(Theme.ink)
                            .frame(width: 34, height: 28)
                            .background(Theme.accent, in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Honorer \(player.name)")
                    .disabled(client.busy)
                }
            }
            .padding(.horizontal, 8).frame(minHeight: 36)
            .background(Theme.card, in: RoundedRectangle(cornerRadius: 12))
        }
    }
}

// MARK: - En partie

/// Vivant : K/D/A et écarts écrits. Mort : réapparition (décomptée ici) et or à
/// dépenser. Vibration 3 s avant la réapparition.
struct GameView: View {
    let game: Game?

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            let now = context.date.timeIntervalSince1970
            if let game, game.kda != nil {
                if game.dead == true, let at = game.respawnAt, at > now {
                    DeadView(game: game, remaining: Int((at - now).rounded(.up)), now: now)
                } else {
                    AliveView(game: game, now: now)
                }
            } else {
                VStack(spacing: 8) {
                    Image(systemName: "gamecontroller.fill").font(.system(size: 30)).foregroundStyle(Theme.accent)
                    Text("En partie").font(.system(size: 18, weight: .bold))
                }
            }
        }
        .task(id: game?.respawnAt) { await warnBeforeRespawn() }
    }

    private func warnBeforeRespawn() async {
        guard game?.dead == true, let at = game?.respawnAt else { return }
        let wait = at - 3 - Date().timeIntervalSince1970
        guard wait > 0 else { return }
        try? await Task.sleep(nanoseconds: UInt64(wait * 1_000_000_000))
        if !Task.isCancelled { WKInterfaceDevice.current().play(.directionUp) }
    }
}

private struct AliveView: View {
    let game: Game
    let now: Double

    var body: some View {
        VStack(spacing: 5) {
            ScreenHeader(title: "\(game.champion ?? "") · niv. \(game.level ?? 0)",
                         trailing: elapsed(game.startedAt, now))
            if let kda = game.kda, kda.count == 3 {
                Text("\(kda[0])/\(kda[1])/\(kda[2])").font(.system(size: 36, weight: .heavy)).monospacedDigit()
                Text("tués / morts / assists").font(.system(size: 10)).foregroundStyle(Theme.muted)
            }
            if let kills = game.kills, kills.count == 2 {
                GapRow(title: "Kills", value: "\(kills[0]) – \(kills[1])", gap: signed(kills[0] - kills[1]))
            }
            if let gap = game.goldGap {
                GapRow(title: "Or (estimé)", value: "", gap: signedGold(gap))
            }
            Spacer(minLength: 0)
            if let gap = game.goldGap {
                Text(gap > 0 ? "en avance" : gap < 0 ? "en retard" : "à égalité")
                    .font(.system(size: 11)).foregroundStyle(Theme.muted)
            }
        }
    }
}

private struct DeadView: View {
    let game: Game
    let remaining: Int
    let now: Double
    @State private var total = 1.0     // durée de la mort, vue à son début (anneau)

    var body: some View {
        VStack(spacing: 5) {
            ScreenHeader(title: "Mort", trailing: elapsed(game.startedAt, now))
            Spacer(minLength: 0)
            CountdownRing(fraction: Double(remaining) / total, label: "\(remaining)", size: 88)
            Text("réapparition").font(.system(size: 10)).foregroundStyle(Theme.muted)
            Spacer(minLength: 0)
            if let gold = game.gold {
                GapRow(title: "Or à dépenser", value: "", gap: "\(gold)")
            }
            if let kills = game.kills, kills.count == 2 {
                Text("Kills \(kills[0]) – \(kills[1])" + (game.goldGap.map { " · Or \(signedGold($0))" } ?? ""))
                    .font(.system(size: 11)).foregroundStyle(Theme.muted).lineLimit(1).minimumScaleFactor(0.7)
            }
        }
        .onAppear { total = max(1, Double(remaining)) }
        .onChange(of: game.respawnAt) { _, _ in total = max(1, Double(remaining)) }
    }
}

/// Ligne « titre … valeur  ▲ +5 » : l'écart porte toujours son signe écrit.
private struct GapRow: View {
    let title: String
    let value: String
    let gap: String

    var body: some View {
        HStack(spacing: 6) {
            Text(title).font(.system(size: 12))
            Spacer(minLength: 4)
            if !value.isEmpty { Text(value).font(.system(size: 12, weight: .bold)).monospacedDigit() }
            Text(gap).font(.system(size: 12, weight: .semibold)).foregroundStyle(Theme.accent).monospacedDigit()
        }
        .padding(.horizontal, 9).frame(minHeight: 32)
        .background(Theme.card, in: RoundedRectangle(cornerRadius: 12))
    }
}

/// « ▲ +5 », « ▼ −3 », « = 0 ».
func signed(_ value: Int) -> String {
    value > 0 ? "▲ +\(value)" : value < 0 ? "▼ −\(-value)" : "= 0"
}

/// Or : « ▲ +1,2k », « ▼ −800 ».
func signedGold(_ value: Int) -> String {
    let size = abs(value)
    let text = size >= 1000 ? String(format: "%.1fk", Double(size) / 1000).replacingOccurrences(of: ".", with: ",")
                            : "\(size)"
    return value > 0 ? "▲ +\(text)" : value < 0 ? "▼ −\(text)" : "= 0"
}

/// Durée « m:ss ».
func clock(_ seconds: Int) -> String {
    String(format: "%d:%02d", seconds / 60, seconds % 60)
}

/// Temps de jeu depuis `startedAt` (epoch s), « m:ss ».
func elapsed(_ startedAt: Double?, _ now: Double) -> String {
    guard let startedAt, startedAt > 0 else { return "" }
    return clock(max(0, Int(now - startedAt)))
}

// MARK: - Lobby

/// Lobby : chaque joueur avec son état écrit ; le chef entouré en jaune ET écrit
/// « chef ». Quitter (rond) à gauche de Lancer.
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
                        let leader = member.isLeader == true
                        HStack(spacing: 8) {
                            Text(String(member.name.prefix(1)).uppercased())
                                .font(.system(size: 11, weight: .bold))
                                .foregroundStyle(leader ? Theme.ink : .white)
                                .frame(width: 22, height: 22)
                                .background(leader ? Theme.leader : Color(white: 0.23), in: Circle())
                            VStack(alignment: .leading, spacing: 0) {
                                Text(member.name + (member.isSelf == true ? " (toi)" : ""))
                                    .font(.system(size: 13, weight: .medium)).lineLimit(1)
                                Text(leader ? "chef · prêt" : "prêt")
                                    .font(.system(size: 10, weight: leader ? .semibold : .regular))
                                    .foregroundStyle(leader ? Theme.leader : Theme.muted)
                            }
                            Spacer(minLength: 0)
                            if !leader {
                                Image(systemName: "checkmark").font(.system(size: 11, weight: .bold))
                                    .foregroundStyle(Theme.accent).accessibilityHidden(true)
                            }
                        }
                        .padding(.horizontal, 8).frame(minHeight: 36)
                        .background(Theme.card, in: RoundedRectangle(cornerRadius: 12))
                        .overlay(RoundedRectangle(cornerRadius: 12)
                            .strokeBorder(leader ? Theme.leader : .clear, lineWidth: 2))
                    }
                    ForEach(lobby.invites ?? [], id: \.self) { invite in
                        HStack(spacing: 8) {
                            Circle().strokeBorder(Color(white: 0.4), style: StrokeStyle(lineWidth: 1.5, dash: [3]))
                                .frame(width: 22, height: 22)
                            Text(invite.name).font(.system(size: 13)).foregroundStyle(Color(white: 0.82)).lineLimit(1)
                            Spacer(minLength: 0)
                            Text("invité, pas encore là").font(.system(size: 10)).foregroundStyle(Theme.muted)
                                .lineLimit(1).minimumScaleFactor(0.7)
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
            HStack(spacing: 6) {
                Button { client.send(["action": "leave_lobby"]) } label: {
                    Image(systemName: "xmark").font(.system(size: 15, weight: .bold))
                        .foregroundStyle(.white)
                        .frame(width: 42, height: 42)
                        .background(Theme.raised, in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(lobby.isLeader == true ? "Fermer le lobby" : "Quitter le lobby")
                .disabled(client.busy)
                launch
            }
        }
        .sheet(isPresented: $choosingFriend) {
            FriendPicker(friends: lobby.friends ?? []) { friend in
                client.send(["action": "invite", "summonerId": friend.summonerId])
                choosingFriend = false
            }
        }
    }

    /// Lancer (chef), ou pourquoi on ne peut pas : pénalité de file, pas chef.
    @ViewBuilder private var launch: some View {
        if let ends = lobby.penaltyEnds, ends > Date().timeIntervalSince1970 {
            TimelineView(.periodic(from: .now, by: 1)) { context in
                let left = max(0, Int(ends - context.date.timeIntervalSince1970))
                Text("File bloquée · \(clock(left))").font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Theme.muted).monospacedDigit()
                    .frame(maxWidth: .infinity, minHeight: 42)
                    .background(Theme.card, in: Capsule())
            }
        } else if lobby.isLeader == true {
            Button { client.send(["action": "start_queue"]) } label: {
                Label(lobby.canStart == true ? "Lancer" : "Pas encore", systemImage: "play.fill")
            }
            .buttonStyle(PrimaryButtonStyle(height: 42))
            .doubleTapAction()
            .disabled(client.busy || lobby.canStart != true)
            .opacity(lobby.canStart == true ? 1 : 0.5)
        } else {
            Text("Le chef lance").font(.system(size: 12)).foregroundStyle(Theme.muted)
                .frame(maxWidth: .infinity, minHeight: 42)
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
}

/// Partie trouvée : anneau qui se vide, Accepter seul en gros ; Refuser en
/// simple lien dessous (impossible à toucher par erreur).
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
                    .buttonStyle(PrimaryButtonStyle(height: 50))
                    .doubleTapAction()
                Button("Refuser") { client.accept(false) }
                    .buttonStyle(.plain)
                    .font(.system(size: 13, weight: .semibold))
                    .padding(.vertical, 2)
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
