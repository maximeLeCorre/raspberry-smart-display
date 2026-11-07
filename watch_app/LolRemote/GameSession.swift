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

/// Retour d'un kill : vibrations DOUCES jusqu'au triple (une de plus par kill de la
/// série), FORTES au quadra et au penta ; + le son `killN` s'il est sur la montre.
/// Seul le kill LE PLUS RÉCENT compte, sans jamais couper un son : un kill arrivé
/// dans les 0,35 s remplace le précédent (double juste après le simple → seulement
/// le double) ; pendant un son, les kills suivants attendent sa fin et seul le
/// dernier est joué (1 → 3 pendant le son du 1 : le 2 est sauté).
@MainActor
final class KillFeedback: NSObject, AVAudioPlayerDelegate {
    static let shared = KillFeedback()
    private var player: AVAudioPlayer?
    private var pending: Int?                  // dernier kill en attente de la fin du son
    private var generation = 0                 // regroupe les kills très rapprochés
    private let gather: TimeInterval = 0.35

    static func play(streak: Int) { shared.queue(max(1, min(streak, 5))) }

    private func queue(_ level: Int) {
        generation += 1
        let mine = generation
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(gather * 1_000_000_000))
            guard mine == generation else { return }     // un kill plus récent est arrivé
            if player?.isPlaying == true {
                pending = level                          // joué à la fin du son en cours
            } else {
                perform(level)
            }
        }
    }

    private func perform(_ level: Int) {
        playSound(level)
        let strong = level >= 4
        let pulses = strong ? level - 2 : level           // 1, 2, 3 douces ; 2 / 3 fortes
        Task { @MainActor in
            for i in 0..<pulses {
                if i > 0 { try? await Task.sleep(nanoseconds: strong ? 450_000_000 : 300_000_000) }
                WKInterfaceDevice.current().play(strong ? .notification : .click)
            }
        }
    }

    private func playSound(_ level: Int) {
        guard let url = SoundStore.shared.url(level: level) else { return }
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .default)
        try? AVAudioSession.sharedInstance().setActive(true)
        player = try? AVAudioPlayer(contentsOf: url)
        player?.delegate = self
        player?.play()
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            guard let level = self.pending else { return }
            self.pending = nil
            self.perform(level)
        }
    }
}
