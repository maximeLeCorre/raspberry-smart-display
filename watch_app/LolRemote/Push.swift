// Notifications push (envoyées par le Pi, pi_display/push_apns.py) : « Partie
// trouvée ! », invitation, arrivée dans notre lobby, message privé (réponse :
// Reply.swift), ami suivi connecté / sorti de partie (« Jouer ensemble ») ; avec boutons d'action, même app fermée. À chaque lancement, le jeton APNs de la
// montre est renvoyé au Pi (POST /push/register).
import Foundation
import UserNotifications
import WatchKit

/// Wi-Fi seul, comme le reste (le relais de l'iPhone ne joint pas le Pi).
private let pushSession = wifiSession(.ephemeral, timeout: 10)

/// POST JSON vers le Pi ; renvoie le statut HTTP (0 = injoignable).
@discardableResult
func postToPi(_ path: String, _ body: [String: Any]) async -> Int {
    var req = apiRequest(path)
    req.httpMethod = "POST"
    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
    req.httpBody = try? JSONSerialization.data(withJSONObject: body)
    req.timeoutInterval = 10
    guard let result = try? await pushSession.data(for: req) else { return 0 }
    return (result.1 as? HTTPURLResponse)?.statusCode ?? 0
}

final class AppDelegate: NSObject, WKApplicationDelegate, UNUserNotificationCenterDelegate {
    func applicationDidFinishLaunching() {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        // Boutons des notifications. Accepter (`.foreground`) ouvre l'app en plus
        // d'envoyer l'action : la suite (choix du champion, lobby) s'y affiche.
        let accept = UNNotificationAction(identifier: "ACCEPT", title: "Accepter", options: [.foreground])
        let decline = UNNotificationAction(identifier: "DECLINE", title: "Refuser", options: [.destructive])
        let join = UNNotificationAction(identifier: "INVITE_ACCEPT", title: "Accepter", options: [.foreground])
        let refuse = UNNotificationAction(identifier: "INVITE_DECLINE", title: "Refuser", options: [.destructive])
        let start = UNNotificationAction(identifier: "START_QUEUE", title: "Lancer la partie", options: [.foreground])
        // Ami suivi dispo (connecté, ou sort de partie) : lobby + invitation, en 1 geste.
        let playWith = UNNotificationAction(identifier: "PLAY_WITH", title: "Jouer ensemble", options: [.foreground])
        // Message : « Répondre… » en 1er (= double tap) ouvre l'écran de réponse ;
        // les réponses rapides partent sans ouvrir l'app.
        let reply = UNNotificationAction(identifier: "REPLY", title: "Répondre…", options: [.foreground])
        let quick = QuickReplies.all.prefix(QuickReplies.inNotification).enumerated().map { index, text in
            UNNotificationAction(identifier: "QUICK_\(index)", title: text, options: [])
        }
        center.setNotificationCategories([
            UNNotificationCategory(identifier: "READY_CHECK", actions: [accept, decline],
                                   intentIdentifiers: [], options: []),
            UNNotificationCategory(identifier: "LOBBY_INVITE", actions: [join, refuse],
                                   intentIdentifiers: [], options: []),
            // Quelqu'un rejoint notre lobby (simple appui = ouvrir l'app).
            UNNotificationCategory(identifier: "LOBBY_JOIN", actions: [start],
                                   intentIdentifiers: [], options: []),
            UNNotificationCategory(identifier: "CHAT_MESSAGE", actions: [reply] + quick,
                                   intentIdentifiers: [], options: []),
            UNNotificationCategory(identifier: "FRIEND_FREE", actions: [playWith],
                                   intentIdentifiers: [], options: []),
            UNNotificationCategory(identifier: "FRIEND_INFO", actions: [],
                                   intentIdentifiers: [], options: []),
        ])
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else { return }
            DispatchQueue.main.async { WKApplication.shared().registerForRemoteNotifications() }
        }
    }

    func didRegisterForRemoteNotifications(withDeviceToken deviceToken: Data) {
        let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
        Task { await postToPi("/push/register", ["token": hex]) }
    }

    func didFailToRegisterForRemoteNotificationsWithError(_ error: Error) {
        print("[push] enregistrement impossible : \(error)")
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                didReceive response: UNNotificationResponse) async {
        let info = response.notification.request.content.userInfo
        let invitationId = info["invitationId"] as? String ?? ""
        let conversationId = info["conversationId"] as? String ?? ""
        let from = info["from"] as? String ?? ""
        let riotId = info["riotId"] as? String ?? ""
        let action = response.actionIdentifier
        if action.hasPrefix("QUICK_"), let index = Int(action.dropFirst(6)),
           QuickReplies.all.indices.contains(index), !conversationId.isEmpty {
            if !(await sendReply(QuickReplies.all[index], to: conversationId)) { notifyReplyFailed(to: from) }
            return
        }
        switch action {
        case "REPLY" where !conversationId.isEmpty:
            await MainActor.run { ReplyCenter.shared.target = ReplyTarget(conversationId: conversationId, from: from) }
        case "ACCEPT": await postToPi("/action", ["action": "accept"])
        case "DECLINE": await postToPi("/action", ["action": "decline"])
        case "INVITE_ACCEPT": await postToPi("/action", ["action": "invite_accept", "invitationId": invitationId])
        case "INVITE_DECLINE": await postToPi("/action", ["action": "invite_decline", "invitationId": invitationId])
        case "START_QUEUE": await postToPi("/action", ["action": "start_queue"])
        case "PLAY_WITH" where !riotId.isEmpty: await postToPi("/action", ["action": "play", "invite": [riotId]])
        default: break      // simple appui : l'app s'ouvre sur le ready-check
        }
    }

    /// App déjà à l'écran : pas de bandeau pour ce qu'elle affiche déjà (ready-check,
    /// choix, invitation) ; bandeau pour un message ou une arrivée dans le lobby.
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        switch notification.request.content.categoryIdentifier {
        case "CHAT_MESSAGE", "LOBBY_JOIN", "FRIEND_FREE", "FRIEND_INFO": return [.banner, .sound]
        default: return []
        }
    }
}
