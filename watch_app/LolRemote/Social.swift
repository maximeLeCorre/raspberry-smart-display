// Friends (list, detail, message), followed friends and Play button settings
// (stored on the Pi, which notifies even with the app closed), rewards.
// Every screen reads the client's CURRENT state, not a copy taken when it opened.
import SwiftUI
import WatchKit

// MARK: - Amis

/// Connected friends with their written state; the Pi sorts the available ones first.
struct FriendsView: View {
    @EnvironmentObject var client: RemoteClient

    private var friends: [OnlineFriend] { client.state?.home?.friends ?? [] }

    var body: some View {
        ScrollView {
            VStack(spacing: 5) {
                ScreenHeader(title: "Amis", trailing: "\(friends.count) en ligne")
                if friends.isEmpty {
                    Text("Aucun ami connecté").font(.system(size: 13)).foregroundStyle(Theme.muted)
                        .padding(.top, 10)
                }
                ForEach(friends) { friend in
                    NavigationLink { FriendDetailView(riotId: friend.riotId, initial: friend) } label: {
                        FriendRow(friend: friend)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}

struct FriendRow: View {
    let friend: OnlineFriend

    var body: some View {
        HStack(spacing: 8) {
            Avatar(name: friend.name, size: 24)
            VStack(alignment: .leading, spacing: 0) {
                Text(friend.name).font(.system(size: 13, weight: .semibold)).lineLimit(1)
                FriendState(friend: friend).font(.system(size: 10.5)).foregroundStyle(Theme.muted)
            }
            Spacer(minLength: 0)
            if friend.followed == true {
                Image(systemName: "bell.fill").font(.system(size: 12)).foregroundStyle(Theme.accent)
                    .accessibilityLabel("suivi")
            }
        }
        .padding(.horizontal, 9).frame(minHeight: 40)
        .background(Theme.card, in: RoundedRectangle(cornerRadius: 12))
    }
}

/// "en partie · 23 min" (minutes recomputed), otherwise the state as is.
struct FriendState: View {
    let friend: OnlineFriend

    var body: some View {
        TimelineView(.everyMinute) { context in
            Text(text(context.date))
        }
    }

    private func text(_ now: Date) -> String {
        guard friend.inGame == true, let since = friend.since, since > 0 else { return friend.state }
        let minutes = max(0, Int(now.timeIntervalSince1970 - since) / 60)
        return "\(friend.state) · \(minutes) min"
    }
}

/// Friend detail: main action depends on their state, then Message and Follow.
struct FriendDetailView: View {
    @EnvironmentObject var client: RemoteClient
    let riotId: String
    let initial: OnlineFriend
    @State private var writing = false

    private var friend: OnlineFriend {
        client.state?.home?.friends?.first { $0.riotId == riotId } ?? initial
    }
    private var follow: Follow? { client.state?.settings?.follows?.first { $0.riotId.lowercased() == riotId.lowercased() } }

    var body: some View {
        ScrollView {
            VStack(spacing: 6) {
                ScreenHeader(title: friend.name)
                Avatar(name: friend.name, size: 46)
                Text(friend.state.prefix(1).uppercased() + String(friend.state.dropFirst()))
                    .font(.system(size: 14, weight: .bold))
                if let mode = friend.mode, !mode.isEmpty {
                    Text(mode).font(.system(size: 11)).foregroundStyle(Theme.muted)
                }
                primary
                HStack(spacing: 6) {
                    Button { writing = true } label: { Label("Message", systemImage: "mic.fill") }
                        .buttonStyle(SecondaryButtonStyle(height: 34))
                        .disabled(friend.pid.isEmpty)
                    NavigationLink { FollowDetailView(riotId: riotId) } label: {
                        Label("Suivi", systemImage: follow == nil ? "bell" : "bell.fill")
                    }
                    .buttonStyle(SecondaryButtonStyle(height: 34))
                }
            }
        }
        .sheet(isPresented: $writing) {
            ReplyView(target: ReplyTarget(conversationId: friend.pid, from: friend.name, starters: true))
        }
    }

    @ViewBuilder private var primary: some View {
        if friend.free == true {
            Button { client.send(["action": "play", "invite": [riotId]]) } label: {
                Label("Jouer ensemble", systemImage: "play.fill")
            }
            .buttonStyle(PrimaryButtonStyle(height: 42))
            .doubleTapAction()
            .disabled(client.busy)
        } else if friend.inGame == true {
            if follow?.leave == true {
                Label("Prévenu à sa sortie", systemImage: "bell.fill")
                    .font(.system(size: 13, weight: .semibold)).foregroundStyle(Theme.accent)
                    .frame(maxWidth: .infinity, minHeight: 42)
                    .background(Theme.card, in: Capsule())
            } else {
                Button {
                    client.send(["action": "set_follow", "riotId": riotId, "online": follow?.online ?? false,
                                 "leave": true, "enter": follow?.enter ?? false])
                } label: {
                    Label("Me prévenir à sa sortie", systemImage: "bell.fill")
                }
                .buttonStyle(PrimaryButtonStyle(height: 42))
                .doubleTapAction()
                .disabled(client.busy)
            }
        }
    }
}

// MARK: - Amis suivis

/// What notifies for this friend; everything off = unfollowed.
struct FollowDetailView: View {
    @EnvironmentObject var client: RemoteClient
    @Environment(\.dismiss) private var dismiss
    let riotId: String
    @State private var online = false
    @State private var leave = false
    @State private var enter = false
    @State private var loaded = false

    private var name: String { riotId.components(separatedBy: "#").first ?? riotId }

    var body: some View {
        List {
            Section {
                toggle("Se connecte", $online)
                toggle("Sort de partie", $leave)
                toggle("Entre en partie", $enter)
            } footer: {
                Text("Notification sur la montre, même app fermée (PC allumé, client ouvert).")
            }
            if online || leave || enter {
                Button("Ne plus suivre", role: .destructive) {
                    online = false; leave = false; enter = false
                    save()
                    dismiss()
                }
            }
        }
        .navigationTitle(name)
        .onAppear {
            guard !loaded else { return }
            loaded = true
            let follow = client.state?.settings?.follows?.first { $0.riotId.lowercased() == riotId.lowercased() }
            online = follow?.online ?? false
            leave = follow?.leave ?? false
            enter = follow?.enter ?? false
        }
    }

    private func toggle(_ title: String, _ value: Binding<Bool>) -> some View {
        Toggle(isOn: Binding(get: { value.wrappedValue }, set: { value.wrappedValue = $0; save() })) {
            VStack(alignment: .leading, spacing: 0) {
                Text(title)
                Text(value.wrappedValue ? "activé" : "désactivé")       // written, not just the switch
                    .font(.system(size: 11)).foregroundStyle(value.wrappedValue ? Theme.accent : Theme.muted)
            }
        }
    }

    private func save() {
        client.send(["action": "set_follow", "riotId": riotId, "online": online, "leave": leave, "enter": enter])
    }
}

/// Followed friends and what notifies for each; add one among connected friends.
struct FollowsView: View {
    @EnvironmentObject var client: RemoteClient

    private var follows: [Follow] { client.state?.settings?.follows ?? [] }

    var body: some View {
        List {
            Section {
                ForEach(follows) { follow in
                    NavigationLink { FollowDetailView(riotId: follow.riotId) } label: {
                        VStack(alignment: .leading, spacing: 0) {
                            Text(follow.name)
                            Text(follow.summary).font(.system(size: 11)).foregroundStyle(Theme.muted)
                        }
                    }
                }
                NavigationLink { AddFollowView() } label: {
                    Label("Ajouter un ami", systemImage: "plus.circle.fill").foregroundStyle(Theme.accent)
                }
            } footer: {
                Text(follows.isEmpty ? "Aucun ami suivi." : "Touche un ami pour changer ce qui notifie.")
            }
        }
        .navigationTitle("Amis suivis")
    }
}

/// Connected friends not followed yet (the list comes from the open League client).
struct AddFollowView: View {
    @EnvironmentObject var client: RemoteClient
    @Environment(\.dismiss) private var dismiss

    private var candidates: [OnlineFriend] {
        (client.state?.home?.friends ?? []).filter { $0.followed != true }
    }

    var body: some View {
        List {
            Section {
                ForEach(candidates) { friend in
                    Button {
                        client.send(["action": "set_follow", "riotId": friend.riotId,
                                     "online": true, "leave": true, "enter": false])
                        dismiss()
                    } label: {
                        VStack(alignment: .leading, spacing: 0) {
                            Text(friend.name)
                            Text(friend.state).font(.system(size: 11)).foregroundStyle(Theme.muted)
                        }
                    }
                }
            } footer: {
                Text(candidates.isEmpty ? "Ouvre League sur le PC : seuls les amis connectés sont listés."
                                        : "Suivi : connexion + sortie de partie (modifiable ensuite).")
            }
        }
        .navigationTitle("Ajouter")
    }
}

// MARK: - Bouton Jouer

/// Queue and friends invited by the Play button (watch and Pi). Saved on every change.
struct PlayConfigView: View {
    @EnvironmentObject var client: RemoteClient
    @State private var queueId = 2400
    @State private var invites: [String] = []
    @State private var loaded = false

    private var queues: [QueueOption] { client.state?.settings?.queues ?? [] }
    /// Already chosen friends + friends connected to the game (mobile cannot play).
    private var candidates: [String] {
        let online = (client.state?.home?.friends ?? []).filter { $0.state != "sur mobile" }.map(\.riotId)
        var seen = Set<String>()
        return (invites + online).filter { seen.insert(shortName($0).lowercased()).inserted }
    }

    var body: some View {
        List {
            Section("Mode") {
                Picker("Mode", selection: Binding(get: { queueId }, set: { queueId = $0; save() })) {
                    ForEach(queues) { Text($0.name).tag($0.id) }
                }
            }
            Section {
                ForEach(candidates, id: \.self) { riotId in
                    let chosen = invites.contains(riotId)
                    Button {
                        if chosen { invites.removeAll { $0 == riotId } } else if invites.count < 4 { invites.append(riotId) }
                        save()
                    } label: {
                        HStack {
                            Text(shortName(riotId))
                            Spacer()
                            Text(chosen ? "✓ invité" : "non").font(.system(size: 12, weight: chosen ? .bold : .regular))
                                .foregroundStyle(chosen ? Theme.accent : Theme.muted)
                        }
                    }
                }
            } header: {
                Text("Inviter automatiquement")
            } footer: {
                Text("4 amis au plus. Seuls les amis connectés (et ceux déjà choisis) sont listés.")
            }
        }
        .navigationTitle("Bouton Jouer")
        .onAppear {
            guard !loaded else { return }
            loaded = true
            queueId = client.state?.settings?.queueId ?? 2400
            invites = client.state?.settings?.invites ?? []
        }
    }

    private func save() {
        client.send(["action": "set_play", "queueId": queueId, "invites": invites])
    }
}

/// "Name#TAG" -> "Name".
func shortName(_ riotId: String) -> String {
    riotId.components(separatedBy: "#").first ?? riotId
}

// MARK: - Récompenses

/// One by one (take, or choose) or all at once; event passes only as a whole.
struct RewardsView: View {
    @EnvironmentObject var client: RemoteClient
    @State private var taken: Set<String> = []     // requested, waiting for the Pi's state

    private var rewards: Rewards? { client.state?.home?.rewards }

    var body: some View {
        VStack(spacing: 6) {
            ScrollView {
                VStack(spacing: 5) {
                    ScreenHeader(title: "Récompenses", trailing: "\(rewards?.count ?? 0)")
                    if (rewards?.count ?? 0) == 0 {
                        Text("Rien à récupérer").font(.system(size: 13)).foregroundStyle(Theme.muted)
                            .padding(.top, 10)
                    }
                    ForEach(rewards?.grants ?? []) { grant in grantRow(grant) }
                    ForEach(rewards?.events ?? []) { event in
                        HStack(spacing: 8) {
                            Image(systemName: "gift.fill").foregroundStyle(Theme.accent)
                            VStack(alignment: .leading, spacing: 0) {
                                Text(event.name).font(.system(size: 12, weight: .semibold)).lineLimit(1)
                                Text("\(event.count) récompense\(event.count > 1 ? "s" : "") · en bloc")
                                    .font(.system(size: 10)).foregroundStyle(Theme.muted)
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.horizontal, 9).frame(minHeight: 40)
                        .background(Theme.card, in: RoundedRectangle(cornerRadius: 12))
                    }
                }
            }
            if (rewards?.count ?? 0) > 0 {
                Button { client.send(["action": "reward_claim_all"]) } label: {
                    Label("Tout récupérer", systemImage: "gift.fill")
                }
                .buttonStyle(PrimaryButtonStyle(height: 40))
                .doubleTapAction()
                .disabled(client.busy)
            }
        }
        .onChange(of: client.message) { _, message in if message != nil { taken.removeAll() } }  // refused
    }

    @ViewBuilder private func grantRow(_ grant: RewardGrant) -> some View {
        let first = grant.options.first
        HStack(spacing: 8) {
            Image(systemName: "gift").foregroundStyle(Theme.accent)
            VStack(alignment: .leading, spacing: 0) {
                Text(grant.options.count > 1 ? "\(grant.options.count) choix" : (first?.title ?? "?"))
                    .font(.system(size: 12, weight: .semibold)).lineLimit(2)
                if grant.options.count == 1, let details = first?.details, !details.isEmpty {
                    Text(details).font(.system(size: 10)).foregroundStyle(Theme.muted).lineLimit(2)
                }
            }
            Spacer(minLength: 0)
            if taken.contains(grant.grantId) {
                Text("✓ prise").font(.system(size: 10, weight: .bold)).foregroundStyle(Theme.accent)
            } else if grant.options.count > 1 {
                NavigationLink { RewardChoiceView(grant: grant) } label: {
                    Text("Choisir").font(.system(size: 11, weight: .bold)).foregroundStyle(Theme.ink)
                        .padding(.horizontal, 9).frame(height: 26).background(Theme.accent, in: Capsule())
                }
                .buttonStyle(.plain)
            } else if let first {
                Button {
                    taken.insert(grant.grantId)
                    client.send(["action": "reward_claim", "grantId": grant.grantId, "selections": [first.id]])
                } label: {
                    Text("Prendre").font(.system(size: 11, weight: .bold)).foregroundStyle(Theme.ink)
                        .padding(.horizontal, 9).frame(height: 26).background(Theme.accent, in: Capsule())
                }
                .buttonStyle(.plain)
                .disabled(client.busy)
            }
        }
        .padding(.horizontal, 9).frame(minHeight: 42)
        .background(Theme.card, in: RoundedRectangle(cornerRadius: 12))
    }
}

/// Reward with a choice: pick up to `max`, then confirm.
struct RewardChoiceView: View {
    @EnvironmentObject var client: RemoteClient
    @Environment(\.dismiss) private var dismiss
    let grant: RewardGrant
    @State private var picked: [String] = []

    private var limit: Int { max(1, grant.max ?? 1) }

    var body: some View {
        VStack(spacing: 6) {
            ScrollView {
                VStack(spacing: 5) {
                    ScreenHeader(title: "Choisis \(limit)")
                    ForEach(grant.options) { option in
                        let chosen = picked.contains(option.id)
                        Button {
                            if chosen {
                                picked.removeAll { $0 == option.id }
                            } else {
                                if picked.count >= limit { picked.removeFirst() }
                                picked.append(option.id)
                            }
                        } label: {
                            HStack(spacing: 8) {
                                VStack(alignment: .leading, spacing: 0) {
                                    Text(option.title).font(.system(size: 12, weight: .semibold)).lineLimit(2)
                                    if let details = option.details, !details.isEmpty {
                                        Text(details).font(.system(size: 10)).lineLimit(2)
                                            .foregroundStyle(chosen ? Theme.ink : Theme.muted)
                                    }
                                }
                                Spacer(minLength: 0)
                                Text(chosen ? "✓ choisie" : "toucher").font(.system(size: 10, weight: .bold))
                            }
                            .foregroundStyle(chosen ? Theme.ink : .white)
                            .padding(.horizontal, 9).frame(minHeight: 44)
                            .background(chosen ? Theme.accent : Theme.card, in: RoundedRectangle(cornerRadius: 12))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            Button {
                client.send(["action": "reward_claim", "grantId": grant.grantId, "selections": picked])
                dismiss()
            } label: {
                Text("Valider ce choix")
            }
            .buttonStyle(PrimaryButtonStyle(height: 40))
            .disabled(picked.isEmpty || client.busy)
            .opacity(picked.isEmpty ? 0.5 : 1)
        }
    }
}
