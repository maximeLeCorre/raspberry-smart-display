// Réglages des retours de kill (vibrations, son), gardés sur la montre (@AppStorage).
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

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Picker("Force", selection: $haptic) {
                        ForEach(KillSettings.strengths, id: \.id) { Text($0.label).tag($0.id) }
                    }
                    Stepper("Répéter ×\(repeats)", value: $repeats, in: 1...3)
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
}
