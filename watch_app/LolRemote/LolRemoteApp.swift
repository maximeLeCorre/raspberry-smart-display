import SwiftUI
import WatchKit

@main
struct LolRemoteApp: App {
    @WKApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate   // notifications push
    @StateObject private var client = RemoteClient()
    @StateObject private var icons = IconStore()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView().environmentObject(client).environmentObject(icons)
        }
        .onChange(of: scenePhase) { _, phase in
            // Poignet relevé : état frais tout de suite ; app en fond : on coupe.
            if phase == .active {
                client.resume()
                WKApplication.shared().registerForRemoteNotifications()   // jeton renvoyé au Pi
            } else if phase == .background {
                client.stop()
            }
        }
    }
}
