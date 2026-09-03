import UIKit

@main
@MainActor
final class BeatBeamRemoteApp: UIResponder, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        configurationForConnecting connectingSceneSession: UISceneSession,
        options: UIScene.ConnectionOptions
    ) -> UISceneConfiguration {
        let configuration = UISceneConfiguration(name: "BeatBeam Remote", sessionRole: connectingSceneSession.role)
        configuration.delegateClass = BeatBeamSceneDelegate.self
        return configuration
    }
}

@MainActor
final class BeatBeamSceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?
    private let store = RemoteStore()
    private let usbTransportPOCListener = USBTransportPOCListener()

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }
        let window = UIWindow(windowScene: windowScene)
        window.rootViewController = BBRemoteApplicationViewController(store: store)
        window.overrideUserInterfaceStyle = .dark
        self.window = window
        window.makeKeyAndVisible()
        store.attachUSBTransport(usbTransportPOCListener)
        store.bootstrap()
    }

    func sceneDidBecomeActive(_ scene: UIScene) {
        UIApplication.shared.isIdleTimerDisabled = true
        store.resumePolling()
        usbTransportPOCListener.start()
    }

    func sceneWillResignActive(_ scene: UIScene) {
        UIApplication.shared.isIdleTimerDisabled = false
        store.releaseActiveMomentaries(reason: "app backgrounded")
        store.pausePolling()
        usbTransportPOCListener.stop()
    }

    func sceneDidDisconnect(_ scene: UIScene) {
        UIApplication.shared.isIdleTimerDisabled = false
        store.pausePolling()
        usbTransportPOCListener.stop()
    }
}
