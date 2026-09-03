import Foundation
import Network

/// Version-one USB transport. The physical direction remains the proven one:
/// the Mac bridge connects through iproxy to this iPad listener.
enum USBRemoteProtocol {
    static let name = "beatbeam-usb-remote-v1"
    static let maximumFrameBytes = 64 * 1024
}

enum USBTransportPOCLineParser {
    enum Result { case lines([Data]), overflow }

    static func consume(_ input: Data, buffered: inout Data) -> Result {
        guard buffered.count + input.count <= USBRemoteProtocol.maximumFrameBytes else {
            buffered.removeAll(keepingCapacity: false); return .overflow
        }
        buffered.append(input)
        var lines: [Data] = []
        while let newline = buffered.firstIndex(of: 0x0A) {
            let line = Data(buffered.prefix(upTo: newline))
            buffered.removeSubrange(...newline)
            guard line.count <= USBRemoteProtocol.maximumFrameBytes else {
                buffered.removeAll(keepingCapacity: false); return .overflow
            }
            if !line.isEmpty { lines.append(line) }
        }
        return .lines(lines)
    }
}

/// Name retained from the physical PoC so the public NWListener route remains
/// clear. It is transport-only; RemoteStore owns state and command semantics.
final class USBTransportPOCListener {
    private static let port = NWEndpoint.Port(rawValue: 8790)!
    private let queue = DispatchQueue(label: "nl.beatbeam.remote.usb-transport-v1")
    private var listener: NWListener?
    private var connection: NWConnection?
    private var buffer = Data()
    private var handshaken = false
    private var pendingAcks: [String: CheckedContinuation<Data?, Never>] = [:]

    var onState: ((Data, Int) -> Void)?
    var onConnected: (() -> Void)?
    var onDisconnected: (() -> Void)?

    var isHealthy: Bool { queue.sync { connection != nil && handshaken } }

    func start() { queue.async { [weak self] in self?.startOnQueue() } }
    func stop() { queue.async { [weak self] in self?.stopOnQueue(notify: true) } }

    func sendCommand(action: String, value: String?, leaseID: String?) async -> Data? {
        let id = UUID().uuidString
        return await withCheckedContinuation { continuation in
            queue.async { [weak self] in
                guard let self, self.handshaken, self.connection != nil else {
                    continuation.resume(returning: nil); return
                }
                self.pendingAcks[id] = continuation
                var payload: [String: Any] = [:]
                if let value { payload["value"] = value }
                if let leaseID { payload["lease_id"] = leaseID }
                self.send(["protocol": USBRemoteProtocol.name, "type": "command", "id": id,
                           "command": action, "payload": payload])
                self.queue.asyncAfter(deadline: .now() + 4) { [weak self] in
                    guard let self, let pending = self.pendingAcks.removeValue(forKey: id) else { return }
                    pending.resume(returning: nil)
                }
            }
        }
    }

    private func startOnQueue() {
        guard listener == nil else { return }
        do {
            let listener = try NWListener(using: .tcp, on: Self.port)
            listener.stateUpdateHandler = { [weak self] state in
                if case .failed = state { self?.queue.async { self?.stopOnQueue(notify: true) } }
            }
            listener.newConnectionHandler = { [weak self] in self?.accept($0) }
            self.listener = listener
            listener.start(queue: queue)
        } catch { print("[USB Remote] listener unavailable: \(error)") }
    }

    private func stopOnQueue(notify: Bool) {
        let hadConnection = connection != nil || handshaken
        listener?.cancel(); listener = nil
        closeConnection(notify: notify && hadConnection)
    }

    private func accept(_ newConnection: NWConnection) {
        // Exactly one command-active USB session. A new bridge session replaces
        // the old one at a clear connection boundary.
        closeConnection(notify: handshaken)
        connection = newConnection; buffer.removeAll(keepingCapacity: false); handshaken = false
        newConnection.stateUpdateHandler = { [weak self, weak newConnection] state in
            guard let self, let newConnection else { return }
            switch state {
            case .ready: self.receive(on: newConnection)
            case .failed, .cancelled:
                self.queue.async { if self.connection === newConnection { self.closeConnection(notify: true) } }
            default: break
            }
        }
        newConnection.start(queue: queue)
    }

    private func receive(on source: NWConnection) {
        source.receive(minimumIncompleteLength: 1, maximumLength: 4096) { [weak self, weak source] data, _, complete, error in
            guard let self, let source else { return }
            self.queue.async {
                guard self.connection === source else { return }
                if error != nil || complete { self.closeConnection(notify: true); return }
                if let data, !data.isEmpty { self.process(data, from: source) }
                if self.connection === source { self.receive(on: source) }
            }
        }
    }

    private func process(_ data: Data, from source: NWConnection) {
        switch USBTransportPOCLineParser.consume(data, buffered: &buffer) {
        case .overflow: closeConnection(notify: true)
        case .lines(let lines): for line in lines { processFrame(line, from: source) }
        }
    }

    private func processFrame(_ data: Data, from source: NWConnection) {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              object["protocol"] as? String == USBRemoteProtocol.name,
              let type = object["type"] as? String else {
            send(["protocol": USBRemoteProtocol.name, "type": "error", "error": "malformed_frame"]); closeConnection(notify: true); return
        }
        switch type {
        case "hello":
            guard !handshaken else { closeConnection(notify: true); return }
            handshaken = true
            send(["protocol": USBRemoteProtocol.name, "type": "hello_ack", "payload": ["role": "remote"]])
            DispatchQueue.main.async { [weak self] in self?.onConnected?() }
        case "state":
            guard handshaken, let sequence = object["sequence"] as? Int,
                  let payload = object["payload"], JSONSerialization.isValidJSONObject(payload),
                  let state = try? JSONSerialization.data(withJSONObject: payload) else { closeConnection(notify: true); return }
            DispatchQueue.main.async { [weak self] in self?.onState?(state, sequence) }
        case "ack":
            guard handshaken, let id = object["id"] as? String,
                  let payload = object["payload"], JSONSerialization.isValidJSONObject(payload),
                  let result = try? JSONSerialization.data(withJSONObject: payload) else { closeConnection(notify: true); return }
            pendingAcks.removeValue(forKey: id)?.resume(returning: result)
        case "ping": send(["protocol": USBRemoteProtocol.name, "type": "pong"])
        case "pong": break
        default:
            send(["protocol": USBRemoteProtocol.name, "type": "error", "error": "unknown_type"]); closeConnection(notify: true)
        }
    }

    private func send(_ object: [String: Any]) {
        guard let connection, let data = try? JSONSerialization.data(withJSONObject: object),
              data.count <= USBRemoteProtocol.maximumFrameBytes else { return }
        var framed = data; framed.append(0x0A)
        connection.send(content: framed, completion: .contentProcessed { [weak self] error in
            if error != nil { self?.queue.async { self?.closeConnection(notify: true) } }
        })
    }

    private func closeConnection(notify: Bool) {
        let active = connection; connection = nil; buffer.removeAll(keepingCapacity: false)
        let wasHandshaken = handshaken; handshaken = false
        active?.cancel()
        let pending = pendingAcks; pendingAcks.removeAll()
        pending.values.forEach { $0.resume(returning: nil) }
        if notify && wasHandshaken { DispatchQueue.main.async { [weak self] in self?.onDisconnected?() } }
    }
}
