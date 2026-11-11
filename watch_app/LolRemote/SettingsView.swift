// Réglages : amis suivis et bouton Jouer (gardés sur le Pi : Social.swift), puis
// retours de kill (vibrations, son), gardés sur la montre (@AppStorage).
import SwiftUI
import WatchKit

/// Clés et valeurs par défaut, partagées avec KillFeedback.
enum KillSettings {
    static let hapticKey = "killHaptic"        // force des kills simples → triples
    static let repeatKey = "killRepeat"        // chaque vibration jouée N fois
    static let soundKey = "killSound"
    static let volumeKey = "killVolume"

    /// Force (du plus doux au plus fort) : libellé écrit + vibration watchOS.
    static let strengths: [(id: String, label: String, haptic: WKHapticType)] = [
        ("douce", "Douce", .click),
        ("moyenne", "Moyenne", .directionUp),
        ("forte", "Forte", .retry),
    ]

    static var haptic: WKHapticType {
        let id = UserDefaults.standard.string(forKey: hapticKey) ?? "forte"
        return strengths.first { $0.id == id }?.haptic ?? .retry
    }
    static var repeats: Int { max(1, UserDefaults.standard.object(forKey: repeatKey) as? Int ?? 2) }
    static var soundOn: Bool { UserDefaults.standard.object(forKey: soundKey) as? Bool ?? true }
    static var volume: Float { Float(UserDefaults.standard.object(forKey: volumeKey) as? Double ?? 1.0) }
}

struct SettingsView: View {
    @AppStorage(KillSettings.hapticKey) private var haptic = "forte"
    @AppStorage(KillSettings.repeatKey) private var repeats = 2
    @AppStorage(KillSettings.soundKey) private var soundOn = true
    @AppStorage(KillSettings.volumeKey) private var volume = 1.0

    @EnvironmentObject var client: RemoteClient

    /// "ARAM Chaos + Friend": the current value, written under the setting.
    private var playSummary: String {
        let settings = client.state?.settings
        let queue = settings?.queues?.first { $0.id == settings?.queueId }?.name ?? ""
        let names = (settings?.invites ?? []).map { $0.components(separatedBy: "#").first ?? $0 }
        return ([queue] + names).filter { !$0.isEmpty }.joined(separator: " + ")
    }

    // Ouvert depuis le menu de l'accueil, déjà dans une NavigationStack.
    var body: some View {
        List {
            Section {
                NavigationLink { FollowsView() } label: {
                    VStack(alignment: .leading, spacing: 0) {
                        Text("Amis suivis")
                        Text("\((client.state?.settings?.follows ?? []).count) ami(s)")
                            .font(.system(size: 11)).foregroundStyle(Theme.muted)
                    }
                }
                NavigationLink { PlayConfigView() } label: {
                    VStack(alignment: .leading, spacing: 0) {
                        Text("Bouton Jouer")
                        Text(playSummary).font(.system(size: 11)).foregroundStyle(Theme.muted).lineLimit(2)
                    }
                }
            } header: {
                Text("League")
            } footer: {
                Text(client.connected ? "Gardés sur le Pi." : "Pi injoignable : réglages indisponibles.")
            }
            .disabled(!client.connected)
            Section {
                Picker("Force", selection: $haptic) {
                    ForEach(KillSettings.strengths, id: \.id) { Text($0.label).tag($0.id) }
                }
                Picker("Répéter", selection: $repeats) {
                    ForEach(1...3, id: \.self) { Text("×\($0)").tag($0) }
                }
            } header: {
                Text("Vibrations")
            } footer: {
                Text("Kill → triple. Quadra et penta : toujours au plus fort.")
            }
            Section {
                Toggle("Son", isOn: $soundOn)
                if soundOn {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Volume \(Int(volume * 100)) %").font(.system(size: 13))
                        Slider(value: $volume, in: 0.2...1.0, step: 0.1)
                    }
                }
            } header: {
                Text("Son")
            } footer: {
                Text("Au maximum, le son suit le volume de la montre (Réglages › Sons et vibrations).")
            }
            Section("Tester") {
                ForEach(1...5, id: \.self) { level in
                    Button(["Kill", "Double kill", "Triple kill", "Quadrakill", "Pentakill"][level - 1]) {
                        KillFeedback.preview(level)
                    }
                }
            }
        }
        .navigationTitle("Réglages")
    }
}
