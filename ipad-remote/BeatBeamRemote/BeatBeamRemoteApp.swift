import SwiftUI
import UIKit

@main
struct BeatBeamRemoteApp: App {
    @StateObject private var store = RemoteStore()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(store)
                .preferredColorScheme(.dark)
                .task {
                    store.bootstrap()
                }
        }
        .onChange(of: scenePhase) { _, newPhase in
            UIApplication.shared.isIdleTimerDisabled = (newPhase == .active)
            if newPhase == .active {
                store.resumePolling()
            } else {
                store.pausePolling()
            }
        }
    }
}
