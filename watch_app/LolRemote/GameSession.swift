// Pendant la partie : l'app reste en vie poignet baissé (session longue watchOS,
// type « rééducation » : en arrière-plan, sans capteurs, 1 h max) pour vibrer à
// chacun de nos kills. ⚠️ Démarrable SEULEMENT app active (règle Apple) : elle
// démarre dès que l'app est ouverte en sélection ou en partie, et s'arrête à la fin.
import AVFoundation
import WatchKit

@MainActor
final class GameSession: NSObject, WKExtendedRuntimeSessionDelegate {
    private var session: WKExtendedRuntimeSession?

    /// À appeler à chaque changement d'écran et au retour au premier plan.
    func update(screen: String?) {
        if screen == "champselect" || screen == "lol" {
            startIfPossible()
        } else if screen == "default" || screen == "postgame" {
            stop()
        }
    }

    private func startIfPossible() {
        guard session == nil, WKApplication.shared().applicationState == .active else { return }
        let new = WKExtendedRuntimeSession()
        new.delegate = self
        new.start()
        session = new
    }

    func stop() {
        session?.invalidate()
        session = nil
    }

    nonisolated func extendedRuntimeSessionDidStart(_ extendedRuntimeSession: WKExtendedRuntimeSession) {}

    nonisolated func extendedRuntimeSessionWillExpire(_ extendedRuntimeSession: WKExtendedRuntimeSession) {}

    nonisolated func extendedRuntimeSession(_ extendedRuntimeSession: WKExtendedRuntimeSession,
                                            didInvalidateWith reason: WKExtendedRuntimeSessionInvalidationReason,
                                            error: Error?) {
        Task { @MainActor in
            if self.session === extendedRuntimeSession { self.session = nil }   // redémarrable
        }
    }
}

/// Sons des kills : servis par le Pi (`pi_display/sounds/`, hors dépôt public) et
/// gardés dans le stockage PERMANENT de la montre. `sync()` (lancement, début de
/// sélection) ne retélécharge qu'un son dont l'empreinte a changé : en partie, ils
/// se jouent sans réseau.
@MainActor
final class SoundStore {
    static let shared = SoundStore()
    private struct Info: Codable { let ext: String; let hash: String }
    private let session = wifiSession(.ephemeral, timeout: 10)
    private let dir: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("Sounds", isDirectory: true)
    }()
    private var known: [String: Info] {
        get {
            UserDefaults.standard.data(forKey: "sounds")
                .flatMap { try? JSONDecoder().decode([String: Info].self, from: $0) } ?? [:]
        }
        set { UserDefaults.standard.set(try? JSONEncoder().encode(newValue), forKey: "sounds") }
    }
    private var syncing = false

    func sync() {
        guard !syncing else { return }
        syncing = true
        Task {
            defer { syncing = false }
            guard let list = try? await session.data(for: apiRequest("/asset/league/sounds")),
                  let remote = try? JSONDecoder().decode([String: Info].self, from: list.0) else { return }
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            var stored = known
            for (name, info) in remote where stored[name]?.hash != info.hash {
                let req = apiRequest("/asset/league/sound/\(name)")
                guard let result = try? await session.data(for: req),
                      (result.1 as? HTTPURLResponse)?.statusCode == 200 else { continue }
                let bytes = result.0
                if let old = stored[name] { try? FileManager.default.removeItem(at: file(name, old.ext)) }
                try? bytes.write(to: file(name, info.ext), options: .atomic)
                stored[name] = info
            }
            known = stored
        }
    }

    func url(level: Int) -> URL? {
        guard let info = known["kill\(level)"] else { return nil }
        let url = file("kill\(level)", info.ext)
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }

    private func file(_ name: String, _ ext: String) -> URL {
        dir.appendingPathComponent("\(name).\(ext)")
    }
}

/// Retour d'un kill (réglages : SettingsView) : vibrations de la force choisie,
/// une de plus par kill de la série jusqu'au triple, au plus fort au quadra et au
/// penta ; + le son `killN` s'il est sur la montre. Joué AUSSITÔT ; pendant un son,
/// les kills suivants attendent sa fin (jamais coupé) et seul le dernier est joué
/// (1 → 3 pendant le son du 1 : le 2 est sauté).
/// ⚠️ Tout l'audio vit sur `audioQueue`, JAMAIS sur le fil principal : l'activation
/// de la session audio peut bloquer longtemps (surtout en arrière-plan) et figeait
/// l'app entière (plus aucun appui pris en compte). Activation asynchrone, une seule
/// fois, abandonnée au bout de 2 s : les vibrations, elles, partent toujours.
@MainActor
final class KillFeedback: NSObject, AVAudioPlayerDelegate {
    static let shared = KillFeedback()
    private var soundPlaying = false           // un son est en cours (fil principal)
    private var pending: Int?                  // dernier kill en attente de la fin du son

    private let audioQueue = DispatchQueue(label: "lolremote.killsound")
    // Accédés UNIQUEMENT sur `audioQueue`.
    nonisolated(unsafe) private var player: AVAudioPlayer?
    nonisolated(unsafe) private var audioReady = false

    static func play(streak: Int) {
        let level = max(1, min(streak, 5))
        if shared.soundPlaying {
            shared.pending = level                       // joué à la fin du son en cours
        } else {
            shared.perform(level)
        }
    }

    /// Bouton « Tester » des réglages : coupe un éventuel test en cours.
    static func preview(_ level: Int) {
        shared.pending = nil
        shared.soundPlaying = false
        shared.audioQueue.async { shared.player?.stop() }
        shared.perform(level)
    }

    private func perform(_ level: Int) {
        if KillSettings.soundOn, let url = SoundStore.shared.url(level: level) {
            soundPlaying = true
            let volume = KillSettings.volume
            audioQueue.async { self.startSound(url, volume: volume) }
        }
        let strong = level >= 4
        let haptic: WKHapticType = strong ? .notification : KillSettings.haptic
        let pulses = (strong ? level - 2 : level) * KillSettings.repeats   // 1, 2, 3 ; 2 / 3 fortes
        Task { @MainActor in
            for i in 0..<pulses {
                if i > 0 { try? await Task.sleep(nanoseconds: strong ? 400_000_000 : 250_000_000) }
                WKInterfaceDevice.current().play(haptic)
            }
        }
    }

    /// Sur `audioQueue`.
    nonisolated private func startSound(_ url: URL, volume: Float) {
        if !audioReady {
            let session = AVAudioSession.sharedInstance()
            try? session.setCategory(.playback, mode: .default)
            let done = DispatchSemaphore(value: 0)
            var ok = false
            session.activate(options: []) { success, _ in
                ok = success
                done.signal()
            }
            guard done.wait(timeout: .now() + 2) == .success, ok else { return soundEnded() }
            audioReady = true
        }
        player = try? AVAudioPlayer(contentsOf: url)
        player?.volume = volume
        player?.delegate = self
        if player?.play() != true { soundEnded() }
    }

    nonisolated private func soundEnded() {
        Task { @MainActor in
            self.soundPlaying = false
            guard let level = self.pending else { return }
            self.pending = nil
            self.perform(level)
        }
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        soundEnded()
    }
}
