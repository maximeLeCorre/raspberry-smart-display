// Client de l'API télécommande du Pi (pi_display/remote_api.py).
// GET /state en long polling (le Pi répond au 1er changement) + POST /action ;
// icônes de champions : GET /asset/league/icon/<id> (IconStore).
import Foundation
import UIKit
import WatchKit

/// Erreur réseau en clair, avec son code (diagnostic quand la montre ne joint pas le Pi).
func describe(_ error: Error) -> String {
    guard let error = error as? URLError else { return "Pi injoignable" }
    let reason: String
    switch error.code {
    case .timedOut: reason = "délai dépassé"
    case .notConnectedToInternet: reason = "pas de réseau"
    case .cannotConnectToHost: reason = "connexion refusée"
    case .cannotFindHost: reason = "adresse introuvable"
    case .networkConnectionLost: reason = "connexion perdue"
    case .dataNotAllowed: reason = "réseau non autorisé"
    case .appTransportSecurityRequiresSecureConnection: reason = "HTTP bloqué (ATS)"
    default: reason = "Pi injoignable"
    }
    return "\(reason) (\(error.code.rawValue))"
}

/// Requête vers le Pi, avec le jeton.
func apiRequest(_ path: String) -> URLRequest {
    var req = URLRequest(url: URL(string: Secrets.baseURL + path)!)
    req.setValue("Bearer \(Secrets.token)", forHTTPHeaderField: "Authorization")
    return req
}

struct QueueInfo: Codable {
    let state: String?          // "readycheck" | "searching"
    let remaining: Int?         // ready-check : secondes restantes
    let response: String?       // "None" | "Accepted" | "Declined"
    let timeInQueue: Int?
    let estimated: Int?
}

struct Champ: Codable, Identifiable, Hashable {
    let championId: Int
    let championName: String
    var id: Int { championId }
    var label: String { championName.isEmpty ? "#\(championId)" : championName }
}

struct SelectTimer: Codable {
    let phase: String?
    let left: Int?
}

struct ChampSelect: Codable {
    let me: Champ?
    let bench: [Champ]?
    let choices: [Champ]?       // choix de départ (ARAM Chaos : 2-3 champions, ~15 s)
    let rerolls: Int?
    let timer: SelectTimer?
}

struct LobbyMember: Codable, Hashable {
    let name: String
    let isLeader: Bool?
    let isSelf: Bool?
}

struct LobbyInvite: Codable, Hashable {
    let name: String
    let state: String?
}

/// Ami invitable (en ligne sur PC, pas déjà dans le lobby) ; `isDefault` = `[lol] lobby_invite`.
struct Friend: Codable, Hashable, Identifiable {
    let name: String
    let summonerId: Int
    let status: String?         // « en ligne », « absent », « occupé », « en partie »
    let isDefault: Bool?
    var id: Int { summonerId }
}

struct Lobby: Codable {
    let queueName: String?
    let members: [LobbyMember]?
    let invites: [LobbyInvite]?
    let isLeader: Bool?
    let canStart: Bool?
    let friends: [Friend]?
}

struct Invitation: Codable {
    let id: String
    let from: String?
    let queueName: String?
}

/// Accueil : bouton « Jouer » (étapes `playStatus`), lobby en cours, invitation reçue.
struct Home: Codable {
    let lobby: Lobby?
    let invitation: Invitation?
    let playStatus: String?
    let playBusy: Bool?
    let playInvite: String?     // ami invité par le bouton Jouer (`[lol] lobby_invite`)
}

struct RemoteState: Codable {
    let v: Int
    let t: Double?              // horodatage Pi de la version (mesure de latence)
    let agent: Bool?
    let screen: String?
    let queue: QueueInfo?
    let champselect: ChampSelect?
    let home: Home?
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
    /// Écran « Connexion au Pi… » : depuis quand, et la dernière erreur (diagnostic).
    @Published var connectingSince = Date()
    @Published var lastError: String?

    private var task: Task<Void, Never>?
    private var lastResponse = Date.distantPast
    private static let cacheKey = "lastHomeState"

    /// Dernier accueil connu affiché dès le lancement (le temps que le Pi réponde) ;
    /// jamais un ready-check ou une sélection, périmés en quelques secondes.
    init() {
        if let data = UserDefaults.standard.data(forKey: Self.cacheKey),
           let cached = try? JSONDecoder().decode(RemoteState.self, from: data) {
            state = cached
        }
    }
    private let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 28    // > attente du long polling (20 s)
        return URLSession(configuration: config)
    }()
    /// Actions sur des connexions NEUVES (session éphémère à part) : une connexion
    /// gardée ouverte peut être morte (Pi redémarré, relais iPhone coupé) sans le savoir.
    private let actionSession: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 6
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

    /// Retour au premier plan : relance seulement si la boucle est arrêtée ou muette
    /// depuis plus longtemps qu'un long polling (requête morte pendant la pause). Au
    /// lancement, `.task` vient de démarrer : la couper rallongerait la connexion.
    func resume() {
        if task == nil {
            start()
        } else if Date().timeIntervalSince(lastResponse) > 30 {
            stop()
            start()
        }
    }

    private func loop() async {
        var version: Int?
        var failures = 0
        connectingSince = Date()
        while !Task.isCancelled {
            let path = "/state?wait=20" + (version.map { "&v=\($0)" } ?? "")
            var req = apiRequest(path)
            // 1re requête (sans version) = réponse immédiate attendue : délai court, pour
            // ne pas rester 40 s sur une connexion morte (réveil, relais iPhone coupé).
            req.timeoutInterval = version == nil ? 4 : 28
            do {
                let (data, response) = try await session.data(for: req)
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
                failures = 0
                lastError = nil
                lastResponse = Date()
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
                    if new.screen == "default", let data = try? JSONEncoder().encode(new) {
                        UserDefaults.standard.set(data, forKey: Self.cacheKey)
                    }
                }
            } catch {
                if Task.isCancelled { break }
                if connected { connectingSince = Date() }
                connected = false
                version = nil
                lastError = describe(error)
                // Nouvel essai vite d'abord (réseau qui se réveille), puis toutes les 2 s.
                failures += 1
                let delay = [0.25, 0.5, 1.0][min(failures - 1, 2)] * (failures > 3 ? 2 : 1)
                try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            }
        }
    }

    /// Vibrations : partie trouvée (forte), entrée en sélection (légère).
    private func notify(old: RemoteState?, new: RemoteState) {
        if new.queue?.state == "readycheck" && old?.queue?.state != "readycheck" {
            WKInterfaceDevice.current().play(.notification)
        } else if !(new.champselect?.choices ?? []).isEmpty && (old?.champselect?.choices ?? []).isEmpty {
            WKInterfaceDevice.current().play(.notification)   // à toi de choisir
        } else if new.screen == "champselect" && old?.screen != "champselect" {
            WKInterfaceDevice.current().play(.click)
        }
    }

    func accept(_ yes: Bool) {
        pendingResponse = yes ? "Accepted" : "Declined"
        send(["action": yes ? "accept" : "decline"])
    }

    func pick(_ champ: Champ) {
        pendingChamp = champ
        send(["action": "pick", "championId": champ.championId])
        expirePending(champ)
    }

    func swap(_ champ: Champ) {
        pendingChamp = champ
        send(["action": "swap", "championId": champ.championId])
        expirePending(champ)
    }

    /// L'affichage optimiste n'est qu'une promesse : si le client League n'a pas
    /// réellement changé notre champion après quelques secondes (l'agent réessaie
    /// ~4 s), on revient à l'état réel et on le dit, au lieu d'afficher « bon ».
    private func expirePending(_ champ: Champ) {
        Task {
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            guard pendingChamp?.championId == champ.championId,
                  state?.champselect?.me?.championId != champ.championId else { return }
            pendingChamp = nil
            message = "\(champ.label) non pris : réessaie"
            WKInterfaceDevice.current().play(.failure)
        }
    }

    /// Un 2e essai (connexion neuve) si le 1er échoue au niveau réseau.
    private func postWithRetry(_ req: URLRequest) async throws -> (Data, URLResponse) {
        do {
            return try await actionSession.data(for: req)
        } catch {
            try? await Task.sleep(nanoseconds: 300_000_000)
            return try await actionSession.data(for: req)
        }
    }

    func send(_ body: [String: Any]) {
        WKInterfaceDevice.current().play(.click)   // retour immédiat au doigt
        Task {
            busy = true
            defer { busy = false }
            let sentAt = Date()
            var req = apiRequest("/action")
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
            do {
                let (data, response) = try await postWithRetry(req)
                let code = (response as? HTTPURLResponse)?.statusCode ?? 0
                actionMs = Int(Date().timeIntervalSince(sentAt) * 1000)
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
                message = describe(error)
                WKInterfaceDevice.current().play(.failure)
                if connected {        // le long polling tient sans doute une connexion morte
                    connected = false
                    stop()
                    start()
                }
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
