// Notifications push (envoyées par le Pi, pi_display/push_apns.py) : « Partie
// trouvée ! » avec Accepter/Refuser, même app fermée. À chaque lancement, le
// jeton APNs de la montre est renvoyé au Pi (POST /push/register).
import Foundation
import UserNotifications
import WatchKit

/// POST JSON vers le Pi ; renvoie le statut HTTP (0 = injoignable).
@discardableResult
func postToPi(_ path: String, _ body: [String: Any]) async -> Int {
    var req = apiRequest(path)
    req.httpMethod = "POST"
    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
    req.httpBody = try? JSONSerialization.data(withJSONObject: body)
    req.timeoutInterval = 10
    guard let result = try? await URLSession.shared.data(for: req) else { return 0 }
    return (result.1 as? HTTPURLResponse)?.statusCode ?? 0
}

final class AppDelegate: NSObject, WKApplicationDelegate, UNUserNotificationCenterDelegate {
    func applicationDidFinishLaunching() {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        // Boutons de la notification ; sans `.foreground` : l'action part sans ouvrir l'app.
        let accept = UNNotificationAction(identifier: "ACCEPT", title: "Accepter", options: [])
        let decline = UNNotificationAction(identifier: "DECLINE", title: "Refuser", options: [.destructive])
        center.setNotificationCategories([
            UNNotificationCategory(identifier: "READY_CHECK", actions: [accept, decline],
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
        switch response.actionIdentifier {
        case "ACCEPT": await postToPi("/action", ["action": "accept"])
        case "DECLINE": await postToPi("/action", ["action": "decline"])
        default: break      // simple appui : l'app s'ouvre sur le ready-check
        }
    }

    /// App déjà à l'écran : pas de bandeau, la vue du ready-check (et sa vibration) suffit.
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        []
    }
}
