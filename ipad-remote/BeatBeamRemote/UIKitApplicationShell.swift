import Combine
import SwiftUI
import UIKit

@MainActor
final class BBRemoteApplicationViewController: UIViewController {
    private let store: RemoteStore
    private var cancellables: Set<AnyCancellable> = []
    private var contentController: UIViewController?
    private var consoleController: BBRemoteRootViewController?
    private var unpairedController: BBUnpairedViewController?
    private weak var pairingController: BBPairingNavigationController?
    private weak var scannerController: BBScannerNavigationController?
    private weak var messageController: UIAlertController?

    init(store: RemoteStore) {
        self.store = store
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = BBUIKitTokens.background
        bindStore()

        if BBRemotePresentationMode.current == .legacySwiftUI {
            let legacy = UIHostingController(rootView: ContentView().environmentObject(store))
            installContent(legacy)
        } else {
            updateContent(liveState: store.liveState)
        }
    }

    override func viewDidDisappear(_ animated: Bool) {
        super.viewDidDisappear(animated)
        store.releaseActiveMomentaries(reason: "UIKit application root disappeared")
    }

    private func bindStore() {
        store.$liveState
            .receive(on: RunLoop.main)
            .sink { [weak self] in self?.updateContent(liveState: $0) }
            .store(in: &cancellables)

        store.$connectionState
            .receive(on: RunLoop.main)
            .sink { [weak self] state in
                guard let self else { return }
                self.unpairedController?.render(connection: state, host: self.store.remoteHostLabel)
                if let consoleController, let liveState = self.store.liveState { consoleController.render(state: liveState) }
            }
            .store(in: &cancellables)

        store.$activeTransport
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                guard let self, let consoleController, let liveState = self.store.liveState else { return }
                consoleController.render(state: liveState)
            }
            .store(in: &cancellables)

        store.$showConfiguration
            .removeDuplicates()
            .receive(on: RunLoop.main)
            .sink { [weak self] in self?.syncPairing(isPresented: $0) }
            .store(in: &cancellables)

        store.$showScanner
            .removeDuplicates()
            .receive(on: RunLoop.main)
            .sink { [weak self] in self?.syncScanner(isPresented: $0) }
            .store(in: &cancellables)

        store.$transientMessage
            .removeDuplicates()
            .receive(on: RunLoop.main)
            .sink { [weak self] message in self?.syncMessage(message) }
            .store(in: &cancellables)
    }

    private func updateContent(liveState: RemoteLiveStateV2?) {
        guard BBRemotePresentationMode.current == .uiKitV1 else { return }
        if let liveState {
            if let consoleController {
                consoleController.render(state: liveState)
            } else {
                let controller = BBRemoteRootViewController(actions: BBRemoteActionBridge(store: store), initialState: liveState)
                consoleController = controller
                unpairedController = nil
                installContent(controller)
            }
        } else if unpairedController == nil {
            consoleController?.releaseMomentariesForDismissal()
            consoleController = nil
            let controller = BBUnpairedViewController(store: store)
            unpairedController = controller
            installContent(controller)
            controller.render(connection: store.connectionState, host: store.remoteHostLabel)
        }
    }

    private func installContent(_ controller: UIViewController) {
        guard contentController !== controller else { return }
        if let old = contentController {
            old.willMove(toParent: nil)
            old.view.removeFromSuperview()
            old.removeFromParent()
        }
        addChild(controller)
        view.addSubview(controller.view)
        controller.view.bbPinEdges(to: view)
        controller.didMove(toParent: self)
        contentController = controller
    }

    private func syncPairing(isPresented: Bool) {
        if isPresented {
            guard pairingController == nil else { return }
            let pairing = BBPairingViewController(store: store)
            pairing.navigationItem.rightBarButtonItem = UIBarButtonItem(title: "Sluit", style: .done, target: pairing, action: #selector(BBPairingViewController.closePairing))
            let navigation = BBPairingNavigationController(rootViewController: pairing)
            navigation.modalPresentationStyle = .formSheet
            navigation.isModalInPresentation = true
            navigation.preferredContentSize = CGSize(width: 820, height: 610)
            pairingController = navigation
            present(navigation, animated: true)
        } else if let pairingController {
            pairingController.dismiss(animated: true)
        }
    }

    private func syncScanner(isPresented: Bool) {
        if isPresented {
            guard scannerController == nil else { return }
            let scanner = QRScannerViewController()
            scanner.onCode = { [weak self] value in self?.store.handleScannedURL(value) }
            scanner.navigationItem.rightBarButtonItem = UIBarButtonItem(title: "Sluit", style: .done, target: self, action: #selector(closeScanner))
            let navigation = BBScannerNavigationController(rootViewController: scanner)
            navigation.modalPresentationStyle = .fullScreen
            navigation.isModalInPresentation = true
            scannerController = navigation
            topPresenter().present(navigation, animated: true)
        } else if let scannerController {
            scannerController.dismiss(animated: true)
        }
    }

    private func syncMessage(_ message: String?) {
        guard let message, messageController == nil else { return }
        let alert = UIAlertController(title: "BeatBeam Remote", message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "OK", style: .cancel) { [weak self] _ in
            self?.store.transientMessage = nil
        })
        messageController = alert
        topPresenter().present(alert, animated: true)
    }

    private func topPresenter() -> UIViewController {
        var current: UIViewController = self
        while let presented = current.presentedViewController { current = presented }
        return current
    }

    @objc private func closeScanner() { store.showScanner = false }
}

final class BBPairingNavigationController: UINavigationController {}
final class BBScannerNavigationController: UINavigationController {}

@MainActor
private final class BBUnpairedViewController: UIViewController {
    private let store: RemoteStore
    private let status = BBStatusIndicator(title: "CONNECTION")
    private let host = BBStatusIndicator(title: "TARGET")

    init(store: RemoteStore) {
        self.store = store
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = BBUIKitTokens.background

        let brand = UILabel()
        brand.text = "BEATBEAM REMOTE"
        brand.font = .systemFont(ofSize: 25, weight: .bold)
        brand.textColor = .white
        brand.textAlignment = .center

        let subtitle = UILabel()
        subtitle.text = "Pair deze vaste landscape control-surface met BeatBeam."
        subtitle.font = .systemFont(ofSize: 14, weight: .medium)
        subtitle.textColor = BBUIKitTokens.secondary
        subtitle.textAlignment = .center

        let scan = BBHardwareButton(symbol: "qrcode.viewfinder", accessibilityLabel: "Scan pairing QR")
        let configure = BBHardwareButton(symbol: "link.badge.plus", accessibilityLabel: "Open pairing")
        let reconnect = BBHardwareButton(symbol: "arrow.clockwise", accessibilityLabel: "Reconnect")
        scan.addAction(UIAction { [weak self] _ in self?.store.showScanner = true }, for: .touchUpInside)
        configure.addAction(UIAction { [weak self] _ in self?.store.showConfiguration = true }, for: .touchUpInside)
        reconnect.addAction(UIAction { [weak self] _ in self?.store.reconnect() }, for: .touchUpInside)
        let actions = UIStackView(arrangedSubviews: [
            BBLabeledControl(label: "SCAN QR", control: scan),
            BBLabeledControl(label: "PAIR", control: configure),
            BBLabeledControl(label: "RECONNECT", control: reconnect),
        ])
        actions.axis = .horizontal
        actions.spacing = 12
        actions.distribution = .fillEqually
        actions.heightAnchor.constraint(equalToConstant: 76).isActive = true

        let panel = BBPanelView(title: "REMOTE CONNECTION")
        let content = UIStackView(arrangedSubviews: [brand, subtitle, status, host, actions])
        content.axis = .vertical
        content.spacing = 16
        panel.contentView.addSubview(content)
        content.bbPinEdges(to: panel.contentView)
        view.addSubview(panel)
        panel.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            panel.centerXAnchor.constraint(equalTo: view.safeAreaLayoutGuide.centerXAnchor),
            panel.centerYAnchor.constraint(equalTo: view.safeAreaLayoutGuide.centerYAnchor),
            panel.widthAnchor.constraint(equalToConstant: 720),
            panel.heightAnchor.constraint(equalToConstant: 390),
        ])
    }

    func render(connection: RemoteStore.ConnectionState, host: String) {
        let connected = connection == .connected
        status.set(value: connection.label, healthy: connected, warning: !connected)
        self.host.set(value: host, healthy: connected, warning: !connected)
    }
}

@MainActor
final class BBPairingViewController: UIViewController, UITextFieldDelegate {
    private let store: RemoteStore
    private let addressField = UITextField()
    private let codeField = UITextField()
    private let status = BBStatusIndicator(title: "PAIRING STATE")
    private var cancellables: Set<AnyCancellable> = []

    init(store: RemoteStore) {
        self.store = store
        super.init(nibName: nil, bundle: nil)
        title = "BeatBeam Pairing"
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = BBUIKitTokens.background

        let explanation = UILabel()
        explanation.text = "Scan de QR-code uit BeatBeam, of voer het serveradres en de zescijferige pairingcode in. Credentials blijven scoped tot REMOTE_READ en LIVE_CONTROL."
        explanation.font = .systemFont(ofSize: 13, weight: .medium)
        explanation.textColor = BBUIKitTokens.secondary
        explanation.numberOfLines = 3

        configureField(addressField, placeholder: "http://beatbeam-host:8781", keyboard: .URL)
        configureField(codeField, placeholder: "000000", keyboard: .numberPad)
        addressField.addTarget(self, action: #selector(fieldsChanged), for: .editingChanged)
        codeField.addTarget(self, action: #selector(fieldsChanged), for: .editingChanged)

        let address = labeledField("BEATBEAM ADDRESS", field: addressField)
        let code = labeledField("PAIRING CODE", field: codeField)
        status.heightAnchor.constraint(equalToConstant: 64).isActive = true

        let scan = BBHardwareButton(symbol: "qrcode.viewfinder", accessibilityLabel: "Scan pairing QR")
        let paste = BBHardwareButton(symbol: "doc.on.clipboard", accessibilityLabel: "Paste pairing address")
        let pair = BBHardwareButton(symbol: "link.badge.plus", accessibilityLabel: "Pair this iPad")
        scan.addAction(UIAction { [weak self] _ in self?.store.showScanner = true }, for: .touchUpInside)
        paste.addAction(UIAction { [weak self] _ in self?.store.pasteFromClipboard(); self?.renderFields() }, for: .touchUpInside)
        pair.addAction(UIAction { [weak self] _ in self?.fieldsChanged(); self?.store.saveConfiguration() }, for: .touchUpInside)
        pair.activeColor = BBUIKitTokens.accent

        let actions = UIStackView(arrangedSubviews: [
            BBLabeledControl(label: "SCAN QR", control: scan),
            BBLabeledControl(label: "PASTE", control: paste),
            BBLabeledControl(label: "PAIR", control: pair),
        ])
        actions.axis = .horizontal
        actions.spacing = 10
        actions.distribution = .fillEqually
        actions.heightAnchor.constraint(equalToConstant: 82).isActive = true

        let forget = BBHardwareButton(symbol: "trash", accessibilityLabel: "Forget this pairing")
        forget.activeColor = BBUIKitTokens.danger
        forget.normalFaceColor = BBUIKitTokens.danger.withAlphaComponent(0.18)
        forget.addAction(UIAction { [weak self] _ in self?.confirmForget() }, for: .touchUpInside)
        let forgetControl = BBLabeledControl(label: "FORGET PAIRING", control: forget)
        forgetControl.heightAnchor.constraint(equalToConstant: 72).isActive = true

        let panel = BBPanelView(title: "SECURE REMOTE PAIRING")
        let stack = UIStackView(arrangedSubviews: [explanation, address, code, status, actions, forgetControl])
        stack.axis = .vertical
        stack.spacing = 12
        panel.contentView.addSubview(stack)
        stack.bbPinEdges(to: panel.contentView)
        view.addSubview(panel)
        panel.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            panel.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 24),
            panel.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -24),
            panel.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 18),
            panel.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -18),
        ])

        store.$connectionState
            .receive(on: RunLoop.main)
            .sink { [weak self] state in self?.render(connection: state) }
            .store(in: &cancellables)
        renderFields()
    }

    @objc func closePairing() { store.showConfiguration = false }

    @objc private func fieldsChanged() {
        store.configurationURLText = addressField.text ?? ""
        store.pairingCodeText = codeField.text ?? ""
    }

    private func renderFields() {
        addressField.text = store.configurationURLText
        codeField.text = store.pairingCodeText
    }

    private func render(connection: RemoteStore.ConnectionState) {
        let connected = connection == .connected
        status.set(value: connection.label, healthy: connected, warning: !connected)
    }

    private func configureField(_ field: UITextField, placeholder: String, keyboard: UIKeyboardType) {
        field.placeholder = placeholder
        field.keyboardType = keyboard
        field.autocapitalizationType = .none
        field.autocorrectionType = .no
        field.textColor = .white
        field.tintColor = BBUIKitTokens.accent
        field.backgroundColor = BBUIKitTokens.recessed
        field.layer.cornerRadius = BBUIKitTokens.cornerRadius
        field.layer.borderWidth = 1
        field.layer.borderColor = BBUIKitTokens.border.cgColor
        field.font = BBUIKitTokens.labelFont(12)
        field.leftView = UIView(frame: CGRect(x: 0, y: 0, width: 12, height: 1))
        field.leftViewMode = .always
        field.heightAnchor.constraint(equalToConstant: 48).isActive = true
    }

    private func labeledField(_ title: String, field: UITextField) -> UIView {
        let label = UILabel()
        label.text = title
        label.font = BBUIKitTokens.labelFont(10)
        label.textColor = BBUIKitTokens.secondary
        let stack = UIStackView(arrangedSubviews: [label, field])
        stack.axis = .vertical
        stack.spacing = 4
        return stack
    }

    private func confirmForget() {
        let alert = UIAlertController(title: "Forget pairing?", message: "This removes the local BeatBeam credential from this iPad.", preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
        alert.addAction(UIAlertAction(title: "Forget", style: .destructive) { [weak self] _ in self?.store.forgetConnection() })
        present(alert, animated: true)
    }
}
