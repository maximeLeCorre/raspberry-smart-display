// Client de l'API télécommande du Pi (pi_display/remote_api.py).
// GET /state en long polling (le Pi répond au 1er changement) + POST /action ;
// icônes de champions : GET /asset/league/icon/<id> (IconStore).
import Foundation
import UIKit
import WatchKit

/// Requête vers le Pi, avec le jeton.
func apiRequest(_ path: String) -> URLRequest {
    var req = URLRequest(url: URL(string: Secrets.baseURL + path)!)
    req.setValue("Bearer \(Secrets.token)", forHTTPHeaderField: "Authorization")
    return req
}

struct QueueInfo: Decodable {
    let state: String?          // "readycheck" | "searching"
    let remaining: Int?         // ready-check : secondes restantes
    let response: String?       // "None" | "Accepted" | "Declined"
    let timeInQueue: Int?
    let estimated: Int?
}

struct Champ: Decodable, Identifiable, Hashable {
    let championId: Int
    let championName: String
    var id: Int { championId }
    var label: String { championName.isEmpty ? "#\(championId)" : championName }
}

struct SelectTimer: Decodable {
    let phase: String?
    let left: Int?
}

struct ChampSelect: Decodable {
    let me: Champ?
    let bench: [Champ]?
    let rerolls: Int?
    let timer: SelectTimer?
}

struct RemoteState: Decodable {
    let v: Int
    let t: Double?              // horodatage Pi de la version (mesure de latence)
    let agent: Bool?
    let screen: String?
    let queue: QueueInfo?
    let champselect: ChampSelect?
}

private struct ActionResult: Decodable {
    let ok: Bool
    let error: String?
}

@MainActor
final class RemoteClient: ObservableObject {
    @Published var state: RemoteState?
    @Published var connected = false
    @Published var message: String?     // erreur ou refus d'action, affiché en bas
    @Published var busy = false         // action en cours d'envoi
    /// Affichage optimiste : l'appui se voit tout de suite, sans attendre l'aller-retour
    /// (annulé si le Pi refuse ; remplacé par l'état réel dès qu'il arrive).
    @Published var pendingResponse: String?   // "Accepted" | "Declined"
    @Published var pendingChamp: Champ?       // champion demandé au banc
    /// Mesures affichées sur l'écran d'accueil (ms) : Pi → montre, et action → réponse.
    @Published var latencyMs: Int?
    @Published var actionMs: Int?

    private var task: Task<Void, Never>?
    private let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 40    // > attente du long polling (25 s)
        return URLSession(configuration: config)
    }()

    func start() {
        guard task == nil else { return }
        task = Task { await loop() }
    }

    func stop() {
        task?.cancel()
        task = nil
    }

    /// Au retour au premier plan : nouvelle requête tout de suite (l'ancienne a pu mourir en pause).
    func restart() {
        stop()
        start()
    }

    private func loop() async {
        var version: Int?
        while !Task.isCancelled {
            let path = "/state?wait=25" + (version.map { "&v=\($0)" } ?? "")
            do {
                let (data, response) = try await session.data(for: apiRequest(path))
                let code = (response as? HTTPURLResponse)?.statusCode ?? 0
                guard code == 200 else {
                    connected = false
                    message = code == 401 ? "Jeton refusé par le Pi" : "Erreur du Pi (\(code))"
                    try? await Task.sleep(nanoseconds: 3_000_000_000)
                    continue
                }
                let new = try JSONDecoder().decode(RemoteState.self, from: data)
                if !connected { message = nil }
                connected = true
                if new.v != version {
                    if version != nil, let t = new.t {   // réveil du long polling = vrai changement
                        latencyMs = max(0, Int((Date().timeIntervalSince1970 - t) * 1000))
                    }
                    if new.queue?.response != state?.queue?.response || new.screen != "queue" {
                        pendingResponse = nil
                    }
                    if new.champselect?.me?.championId != state?.champselect?.me?.championId
                        || new.screen != "champselect" {
                        pendingChamp = nil
                    }
                    notify(old: state, new: new)
                    state = new
                    version = new.v
                }
            } catch {
                if Task.isCancelled { break }
                connected = false
                version = nil
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
        }
    }

    /// Vibrations : partie trouvée (forte), entrée en sélection (légère).
    private func notify(old: RemoteState?, new: RemoteState) {
        if new.queue?.state == "readycheck" && old?.queue?.state != "readycheck" {
            WKInterfaceDevice.current().play(.notification)
        } else if new.screen == "champselect" && old?.screen != "champselect" {
            WKInterfaceDevice.current().play(.click)
        }
    }

    func accept(_ yes: Bool) {
        pendingResponse = yes ? "Accepted" : "Declined"
        send(["action": yes ? "accept" : "decline"])
    }

    func swap(_ champ: Champ) {
        pendingChamp = champ
        send(["action": "swap", "championId": champ.championId])
    }

    func send(_ body: [String: Any]) {
        WKInterfaceDevice.current().play(.click)   // retour immédiat au doigt
        Task {
            busy = true
            defer { busy = false }
            let start = Date()
            var req = apiRequest("/action")
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
            do {
                let (data, response) = try await session.data(for: req)
                let code = (response as? HTTPURLResponse)?.statusCode ?? 0
                actionMs = Int(Date().timeIntervalSince(start) * 1000)
                if code == 200 {
                    message = nil
                    WKInterfaceDevice.current().play(.success)
                } else {
                    let result = try? JSONDecoder().decode(ActionResult.self, from: data)
                    message = result?.error ?? "Erreur \(code)"
                    pendingResponse = nil
                    pendingChamp = nil
                    WKInterfaceDevice.current().play(.failure)
                }
            } catch {
                pendingResponse = nil
                pendingChamp = nil
                message = "Pi injoignable"
                WKInterfaceDevice.current().play(.failure)
            }
        }
    }
}

/// Icônes de champions, téléchargées une fois chacune. Le Pi envoie
/// `Cache-Control: max-age` : le cache disque d'URLSession les garde entre
/// deux lancements (pas de nouveau téléchargement au champ select suivant).
@MainActor
final class IconStore: ObservableObject {
    @Published private(set) var images: [Int: UIImage] = [:]
    private var pending = Set<Int>()
    private let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 10
        config.urlCache = URLCache(memoryCapacity: 4 << 20, diskCapacity: 32 << 20)
        return URLSession(configuration: config)
    }()

    func load(_ championId: Int) {
        guard championId > 0, images[championId] == nil, !pending.contains(championId) else { return }
        pending.insert(championId)
        Task {
            defer { pending.remove(championId) }
            let req = apiRequest("/asset/league/icon/\(championId)")
            guard let result = try? await session.data(for: req),
                  (result.1 as? HTTPURLResponse)?.statusCode == 200,
                  let image = UIImage(data: result.0) else { return }
            images[championId] = image
        }
    }
}
