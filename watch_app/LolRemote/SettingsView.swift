// Réglages : retours de kill (vibrations, son, gardés sur la montre) et domicile
// du trajet retour (adresse → coordonnées, enregistrées sur le Pi : la
// complication les y reprend).
import CoreLocation
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
    @AppStorage("homeLabel") private var homeLabel = ""
    @State private var address = ""
    @State private var homeStatus: String?
    @State private var location = LocationOnce()

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
                Section {
                    Text(homeLabel.isEmpty ? "Non défini" : homeLabel)
                        .font(.system(size: 13)).foregroundStyle(homeLabel.isEmpty ? Theme.muted : .white)
                    TextField("Saisir l'adresse", text: $address)
                        .onSubmit { Task { await saveAddress() } }
                    Button { Task { await saveHere() } } label: {
                        Label("Ma position actuelle", systemImage: "location.fill")
                    }
                    if let homeStatus {
                        Text(homeStatus).font(.system(size: 12)).foregroundStyle(Theme.muted)
                    }
                } header: {
                    Text("Domicile")
                } footer: {
                    Text("Pour le trajet retour. À enregistrer depuis chez toi (Wi-Fi du Pi).")
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

    private func saveAddress() async {
        let query = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return }
        homeStatus = "Recherche…"
        guard let place = try? await CLGeocoder().geocodeAddressString(query).first,
              let found = place.location else {
            homeStatus = "Adresse introuvable"
            return
        }
        await save(found, label: describe(place) ?? query)
    }

    private func saveHere() async {
        location.requestPermission()
        homeStatus = "Localisation…"
        guard let here = await location.current(maxAge: 60) else {
            homeStatus = location.authorized ? "Position introuvable" : "Autorise la localisation"
            return
        }
        let place = try? await CLGeocoder().reverseGeocodeLocation(here).first
        await save(here, label: place.flatMap(describe) ?? "Ma position")
    }

    /// Enregistré sur le Pi (pour la complication) ET sur la montre (pour l'app).
    private func save(_ place: CLLocation, label: String) async {
        let lat = place.coordinate.latitude, lon = place.coordinate.longitude
        let code = await postToPi("/settings/transit/home", ["lat": lat, "lon": lon, "label": label])
        guard code == 200 else {
            homeStatus = code == 0 ? "Pi injoignable : enregistre depuis chez toi" : "Refusé par le Pi (\(code))"
            WKInterfaceDevice.current().play(.failure)
            return
        }
        HomePlace.setHome(lat: lat, lon: lon, label: label)
        homeLabel = label
        address = ""
        homeStatus = "Enregistré"
        WKInterfaceDevice.current().play(.success)
        await HomePlace.sync()              // clé IDFM, si pas encore reçue
    }

    /// « 12 rue X, Ville ».
    private func describe(_ place: CLPlacemark) -> String? {
        let text = [place.name, place.locality].compactMap { $0 }.joined(separator: ", ")
        return text.isEmpty ? nil : text
    }
}
