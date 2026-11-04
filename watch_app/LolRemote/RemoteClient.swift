// Client de l'API télécommande du Pi (pi_display/remote_api.py).
// GET /state en long polling (le Pi répond au 1er changement) + POST /action.
import Foundation
import WatchKit

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

    private func request(_ path: String) -> URLRequest {
        var req = URLRequest(url: URL(string: Secrets.baseURL + path)!)
        req.setValue("Bearer \(Secrets.token)", forHTTPHeaderField: "Authorization")
        return req
    }

    private func loop() async {
        var version: Int?
        while !Task.isCancelled {
            let path = "/state?wait=25" + (version.map { "&v=\($0)" } ?? "")
            do {
                let (data, response) = try await session.data(for: request(path))
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

    func send(_ body: [String: Any]) {
        Task {
            busy = true
            defer { busy = false }
            var req = request("/action")
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
            do {
                let (data, response) = try await session.data(for: req)
                let code = (response as? HTTPURLResponse)?.statusCode ?? 0
                if code == 200 {
                    message = nil
                    WKInterfaceDevice.current().play(.success)
                } else {
                    let result = try? JSONDecoder().decode(ActionResult.self, from: data)
                    message = result?.error ?? "Erreur \(code)"
                    WKInterfaceDevice.current().play(.failure)
                }
            } catch {
                message = "Pi injoignable"
                WKInterfaceDevice.current().play(.failure)
            }
        }
    }
}
