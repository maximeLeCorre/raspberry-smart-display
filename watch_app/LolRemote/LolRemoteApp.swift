import SwiftUI
import WatchKit
import WidgetKit

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
                WidgetCenter.shared.reloadAllTimelines()   // complication train : relevé frais
            } else if phase == .background {
                client.stop()
            }
        }
    }
}
