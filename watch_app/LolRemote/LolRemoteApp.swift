import SwiftUI

@main
struct LolRemoteApp: App {
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
                client.restart()
            } else if phase == .background {
                client.stop()
            }
        }
    }
}
