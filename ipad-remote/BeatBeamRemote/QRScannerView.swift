import AVFoundation
import SwiftUI

struct QRScannerView: UIViewControllerRepresentable {
    let onCode: (String) -> Void

    func makeUIViewController(context: Context) -> QRScannerViewController {
        let controller = QRScannerViewController()
        controller.onCode = onCode
        return controller
    }

    func updateUIViewController(_ uiViewController: QRScannerViewController, context: Context) {}
}

final class QRScannerViewController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    var onCode: ((String) -> Void)?

    private let session = AVCaptureSession()
    private var previewLayer: AVCaptureVideoPreviewLayer?
    private var didEmitCode = false
    private var isSessionConfigured = false
    private let overlayLabel = UILabel()
    private let actionButton = UIButton(type: .system)

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        buildOverlay()
        prepareCameraAccess()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        previewLayer?.frame = view.bounds
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        didEmitCode = false
        startSessionIfPossible()
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        if session.isRunning {
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                self?.session.stopRunning()
            }
        }
    }

    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput metadataObjects: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard !didEmitCode else { return }
        guard
            let object = metadataObjects.first as? AVMetadataMachineReadableCodeObject,
            object.type == .qr,
            let value = object.stringValue
        else { return }

        didEmitCode = true
        onCode?(value)
    }

    private func buildOverlay() {
        overlayLabel.translatesAutoresizingMaskIntoConstraints = false
        overlayLabel.text = "Scan de BeatBeam QR-code"
        overlayLabel.font = .preferredFont(forTextStyle: .headline)
        overlayLabel.textColor = .white
        overlayLabel.textAlignment = .center
        overlayLabel.backgroundColor = UIColor.black.withAlphaComponent(0.45)
        overlayLabel.layer.cornerRadius = 12
        overlayLabel.layer.masksToBounds = true
        overlayLabel.numberOfLines = 3
        view.addSubview(overlayLabel)

        actionButton.translatesAutoresizingMaskIntoConstraints = false
        actionButton.configuration = .filled()
        actionButton.configuration?.baseBackgroundColor = .systemOrange
        actionButton.configuration?.baseForegroundColor = .white
        actionButton.isHidden = true
        view.addSubview(actionButton)

        NSLayoutConstraint.activate([
            overlayLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
            overlayLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24),
            overlayLabel.bottomAnchor.constraint(equalTo: actionButton.topAnchor, constant: -16),
            overlayLabel.heightAnchor.constraint(greaterThanOrEqualToConstant: 56),

            actionButton.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            actionButton.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -24),
            actionButton.heightAnchor.constraint(greaterThanOrEqualToConstant: 44),
        ])
    }

    private func prepareCameraAccess() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            configureSessionIfNeeded()
        case .notDetermined:
            overlayLabel.text = "Camera-toegang nodig om de BeatBeam QR-code te scannen."
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                DispatchQueue.main.async {
                    guard let self else { return }
                    if granted {
                        self.configureSessionIfNeeded()
                        self.startSessionIfPossible()
                    } else {
                        self.showPermissionDenied()
                    }
                }
            }
        case .denied, .restricted:
            showPermissionDenied()
        @unknown default:
            showPermissionDenied()
        }
    }

    private func configureSessionIfNeeded() {
        guard !isSessionConfigured else { return }
        guard
            let device = AVCaptureDevice.default(for: .video),
            let input = try? AVCaptureDeviceInput(device: device),
            session.canAddInput(input)
        else {
            overlayLabel.text = "Geen bruikbare camera gevonden op dit apparaat."
            return
        }

        session.beginConfiguration()
        session.addInput(input)

        let output = AVCaptureMetadataOutput()
        guard session.canAddOutput(output) else {
            session.commitConfiguration()
            overlayLabel.text = "QR-scanner kon niet worden gestart."
            return
        }

        session.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr]
        session.commitConfiguration()

        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        previewLayer = layer
        view.layer.insertSublayer(layer, at: 0)
        isSessionConfigured = true
        overlayLabel.text = "Scan de BeatBeam QR-code"
        actionButton.isHidden = true
    }

    private func startSessionIfPossible() {
        guard isSessionConfigured, !session.isRunning else { return }
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            self?.session.startRunning()
        }
    }

    private func showPermissionDenied() {
        overlayLabel.text = "Camera-toegang staat uit. Geef BeatBeam Remote toegang tot de camera in Instellingen."
        actionButton.setTitle("Open Instellingen", for: .normal)
        actionButton.isHidden = false
        actionButton.removeTarget(nil, action: nil, for: .allEvents)
        actionButton.addTarget(self, action: #selector(openSettings), for: .touchUpInside)
    }

    @objc
    private func openSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }
}
