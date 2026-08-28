import Foundation
import Security
import SwiftUI
import UIKit

private enum RemoteKeychain {
    static let service = "nl.beatbeam.remote"

    static func save(_ value: String, account: String) throws {
        let data = Data(value.utf8)
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                    kSecAttrAccount as String: account]
        SecItemDelete(query as CFDictionary)
        var item = query
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(item as CFDictionary, nil)
        guard status == errSecSuccess else { throw NSError(domain: "BeatBeamRemote.Keychain", code: Int(status)) }
    }

    static func load(account: String) -> String? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                    kSecAttrAccount as String: account, kSecReturnData as String: true,
                                    kSecMatchLimit as String: kSecMatchLimitOne]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func delete(account: String) {
        SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                       kSecAttrAccount as String: account] as CFDictionary)
    }
}

@MainActor
final class RemoteStore: ObservableObject {
    enum ConnectionState: Equatable {
        case notPaired, connecting, connected, reconnecting, offline, authFailed, serverIncompatible

        var label: String {
            switch self {
            case .notPaired: return "Niet gepaird"
            case .connecting: return "Verbinden…"
            case .connected: return "Verbonden"
            case .reconnecting: return "Herverbinden…"
            case .offline: return "Offline"
            case .authFailed: return "Pair opnieuw"
            case .serverIncompatible: return "Server niet compatibel"
            }
        }
    }

    @Published private(set) var liveState: RemoteLiveStateV2?
    @Published private(set) var connectionState: ConnectionState = .notPaired
    @Published var configurationURLText = ""
    @Published var pairingCodeText = ""
    @Published var showConfiguration = false
    @Published var showScanner = false
    @Published var transientMessage: String?
    @Published private(set) var pendingActions: Set<String> = []

    private let defaults = UserDefaults.standard
    private let storedHostKey = "BeatBeamRemote.V2Host"
    private let oldStoredURLKey = "BeatBeamRemote.StoredURL"
    private var host: RemoteConnectionHost?
    private var credential: String?
    private var pollingTask: Task<Void, Never>?
    private var eventStreamTask: Task<Void, Never>?
    private var failedRefreshes = 0
    private var newestRevision = -1
    private var newestSequence = -1
    private var momentaryRenewals: [String: Task<Void, Never>] = [:]
    private let fallbackPollIntervalNanoseconds: UInt64 = 2_500_000_000
    private let streamRetryDelayNanoseconds: UInt64 = 900_000_000
    private lazy var session: URLSession = {
        let configuration = URLSessionConfiguration.default
        configuration.waitsForConnectivity = true
        configuration.timeoutIntervalForRequest = 12
        configuration.timeoutIntervalForResource = 3600
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.allowsConstrainedNetworkAccess = true
        configuration.allowsExpensiveNetworkAccess = true
        return URLSession(configuration: configuration)
    }()

    var isConnected: Bool { connectionState == .connected }
    var remoteHostLabel: String { host?.displayHost ?? "Niet ingesteld" }
    var trackTitle: String { liveState?.track.title ?? "(geen track)" }
    var trackArtist: String { liveState?.track.artist ?? "Onbekend" }

    func bootstrap() {
        guard host == nil else { return }
        if let data = defaults.data(forKey: storedHostKey), let stored = try? JSONDecoder().decode(RemoteConnectionHost.self, from: data) {
            host = stored
            configurationURLText = stored.origin.absoluteString
            credential = RemoteKeychain.load(account: stored.origin.absoluteString)
            if credential != nil { connectStoredCredential() } else { showConfiguration = true }
            return
        }
        // A legacy URL intentionally is not imported as an authority. Keep the
        // address only long enough to guide the operator to a fresh pairing.
        if let legacy = defaults.string(forKey: oldStoredURLKey), !legacy.isEmpty {
            configurationURLText = legacy
            defaults.removeObject(forKey: oldStoredURLKey)
            transientMessage = RemoteConnectionError.legacyLinkRequiresPairing.errorDescription
        }
        showConfiguration = true
    }

    func resumePolling() {
        guard credential != nil, host != nil else { return }
        startConnections()
    }

    func pausePolling() {
        releaseActiveMomentaries(reason: "connection paused")
        pollingTask?.cancel(); pollingTask = nil
        eventStreamTask?.cancel(); eventStreamTask = nil
    }

    func pasteFromClipboard() {
        guard let text = UIPasteboard.general.string?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty else { return }
        applyPairingInput(text)
    }

    func handleScannedURL(_ value: String) {
        applyPairingInput(value)
        showScanner = false
        // A pairing QR is a complete, one-use pairing offer. Scanning it must
        // perform the exchange rather than merely populate a form behind the
        // scanner, where it looks as if nothing happened.
        Task { await pair(using: configurationURLText, code: pairingCodeText) }
    }

    func saveConfiguration() {
        Task { await pair(using: configurationURLText, code: pairingCodeText) }
    }

    func reconnect() {
        guard credential != nil, host != nil else { showConfiguration = true; return }
        connectStoredCredential()
    }

    func forgetConnection() {
        pausePolling()
        if let host { RemoteKeychain.delete(account: host.origin.absoluteString) }
        defaults.removeObject(forKey: storedHostKey)
        host = nil; credential = nil; liveState = nil; newestRevision = -1; newestSequence = -1
        connectionState = .notPaired
        showConfiguration = true
    }

    func perform(_ action: String, value: String? = nil) {
        Task { await sendControl(action, value: value) }
    }

    func beginMomentary(_ effect: String) {
        guard momentaryRenewals[effect] == nil else { return }
        Task {
            let accepted = await sendControl("momentary_press", value: effect)
            guard accepted else { return }
            momentaryRenewals[effect] = Task { [weak self] in
                while let self, !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: 900_000_000)
                    guard !Task.isCancelled else { break }
                    guard await self.sendControl("momentary_renew", value: effect) else { break }
                }
            }
        }
    }

    func endMomentary(_ effect: String) {
        momentaryRenewals.removeValue(forKey: effect)?.cancel()
        perform("momentary_release", value: effect)
    }

    func releaseActiveMomentaries(reason: String = "") {
        let effects = Array(momentaryRenewals.keys)
        momentaryRenewals.values.forEach { $0.cancel() }
        momentaryRenewals.removeAll()
        for effect in effects { perform("momentary_release", value: effect) }
    }

    private func sendControl(_ action: String, value: String? = nil) async -> Bool {
        guard credential != nil, host != nil else { showConfiguration = true; return false }
        let pending = "\(action):\(value ?? "")"
        pendingActions.insert(pending)
        defer { pendingActions.remove(pending) }
        do {
            var request = try authenticatedRequest(path: "/api/remote-v2/control", method: "POST")
            let body: [String: Any] = [
                "command_id": UUID().uuidString, "action": action, "value": value ?? NSNull(),
            ]
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
            if (200..<300).contains(http.statusCode) {
                let acknowledgement = try decoder().decode(RemoteControlAcknowledgement.self, from: data)
                apply(acknowledgement.effectiveState)
                guard acknowledgement.accepted else { transientMessage = acknowledgement.error ?? "Opdracht geweigerd door BeatBeam."; return false }
                return true
            }
            if http.statusCode == 409 {
                // A conflict is a typed command rejection, never a success ack.
                let rejection = try decoder().decode(RemoteControlRejection.self, from: data)
                apply(rejection.effectiveState)
                transientMessage = rejection.error ?? "Opdracht geweigerd door BeatBeam."
                return false
            }
            try validateHTTP(http, data: data)
            return false
        } catch {
            applyConnectionError(error)
            return false
        }
    }

    private func applyPairingInput(_ raw: String) {
        configurationURLText = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if let parsed = try? Self.parsePairingURL(configurationURLText), let code = parsed.pairingCode {
            pairingCodeText = code
        }
    }

    private func connectStoredCredential() {
        connectionState = .connecting
        Task {
            do {
                try await refreshState()
                connectionState = .connected
                failedRefreshes = 0
                startConnections()
            } catch { applyConnectionError(error) }
        }
    }

    private func pair(using rawURL: String, code: String) async {
        connectionState = .connecting
        do {
            let parsed = try Self.parsePairingURL(rawURL)
            if parsed.wasLegacyTokenURL { throw RemoteConnectionError.legacyLinkRequiresPairing }
            let pairingCode = (code.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? parsed.pairingCode : code.trimmingCharacters(in: .whitespacesAndNewlines)) ?? ""
            guard pairingCode.count == 6, pairingCode.allSatisfy(\.isNumber) else { throw RemoteConnectionError.pairingCodeRequired }
            let response: RemotePairingResponse = try await unauthenticatedPost(host: parsed.host, path: "/api/remote-v2/pair", body: [
                "pairing_code": pairingCode, "client_name": UIDevice.current.name,
            ])
            guard response.schemaVersion == 2, response.protocolVersion == 2,
                  (response.scopes ?? [response.scope]).contains("REMOTE_READ"),
                  (response.scopes ?? []).contains("LIVE_CONTROL") else {
                throw RemoteConnectionError.incompatibleServer
            }
            try RemoteKeychain.save(response.credential, account: parsed.host.origin.absoluteString)
            host = parsed.host; credential = response.credential; configurationURLText = parsed.host.origin.absoluteString; pairingCodeText = ""
            defaults.set(try JSONEncoder().encode(parsed.host), forKey: storedHostKey)
            showConfiguration = false; newestRevision = -1; newestSequence = -1
            try await refreshState()
            connectionState = .connected; failedRefreshes = 0
            startConnections()
        } catch { applyConnectionError(error) }
    }

    private func startConnections() {
        pollingTask?.cancel(); eventStreamTask?.cancel()
        startEventStream()
        pollingTask = Task { [weak self] in
            while let self, !Task.isCancelled {
                do {
                    try await self.refreshState()
                    self.failedRefreshes = 0
                    if self.connectionState != .connected { self.connectionState = .connected }
                } catch {
                    self.failedRefreshes += 1
                    if self.connectionState != .authFailed && self.connectionState != .serverIncompatible {
                        self.connectionState = self.failedRefreshes >= 3 ? .offline : .reconnecting
                    }
                }
                try? await Task.sleep(nanoseconds: self.fallbackPollIntervalNanoseconds)
            }
        }
    }

    private func startEventStream() {
        eventStreamTask = Task { [weak self] in
            while let self, !Task.isCancelled {
                do { try await self.runEventStream() }
                catch is CancellationError { break }
                catch {
                    if Task.isCancelled { break }
                    if self.connectionState != .authFailed && self.connectionState != .serverIncompatible { self.connectionState = .reconnecting }
                }
                try? await Task.sleep(nanoseconds: self.streamRetryDelayNanoseconds)
            }
        }
    }

    private func refreshState() async throws {
        let state: RemoteLiveStateV2 = try await get("/api/remote-v2/state")
        try validate(state)
        apply(state)
    }

    private func runEventStream() async throws {
        var streamRequest = try authenticatedRequest(path: "/api/remote-v2/events", method: "GET", timeout: 3600)
        streamRequest.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        streamRequest.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        let (bytes, response) = try await session.bytes(for: streamRequest)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        try validateHTTP(http, data: nil)
        for try await line in bytes.lines {
            if Task.isCancelled { break }
            guard line.hasPrefix("data:") else { continue }
            let json = String(line.dropFirst(5)).trimmingCharacters(in: CharacterSet.whitespacesAndNewlines)
            guard !json.isEmpty else { continue }
            do {
                let state = try decoder().decode(RemoteLiveStateV2.self, from: Data(json.utf8))
                try validate(state); apply(state); failedRefreshes = 0
                if connectionState != .connected { connectionState = .connected }
            } catch { throw error }
        }
    }

    private func apply(_ state: RemoteLiveStateV2) {
        guard state.stateRevision > newestRevision || (state.stateRevision == newestRevision && state.eventSequence > newestSequence) else { return }
        newestRevision = state.stateRevision; newestSequence = state.eventSequence; liveState = state
    }

    private func validate(_ state: RemoteLiveStateV2) throws {
        guard state.schemaVersion == 2, state.connection.protocolVersion == 2, state.connection.compatible else {
            throw RemoteConnectionError.incompatibleServer
        }
    }

    private func applyConnectionError(_ error: Error) {
        if let decoding = error as? DecodingError {
            let diagnostic = Self.decodingDiagnostic(decoding)
            print("BeatBeam Remote decoding failure: \(diagnostic)")
            connectionState = .serverIncompatible
            transientMessage = "Serverdata is niet compatibel: \(diagnostic)"
            return
        }
        if let remote = error as? RemoteConnectionError {
            connectionState = remote == .authenticationFailed ? .authFailed : .serverIncompatible
            transientMessage = remote.errorDescription
            return
        }
        if let http = error as? RemoteHTTPError, http.statusCode == 401 || http.statusCode == 403 {
            connectionState = .authFailed
            transientMessage = RemoteConnectionError.authenticationFailed.errorDescription
            return
        }
        if let http = error as? RemoteHTTPError, http.statusCode == 404 || http.statusCode == 426 {
            connectionState = .serverIncompatible
            transientMessage = RemoteConnectionError.incompatibleServer.errorDescription
            return
        }
        connectionState = .offline; transientMessage = error.localizedDescription
    }

    private static func decodingDiagnostic(_ error: DecodingError) -> String {
        func path(_ context: DecodingError.Context) -> String { context.codingPath.map(\.stringValue).joined(separator: ".") }
        switch error {
        case let .typeMismatch(type, context): return "typeMismatch \(type) at \(path(context)): \(context.debugDescription)"
        case let .valueNotFound(type, context): return "valueNotFound \(type) at \(path(context)): \(context.debugDescription)"
        case let .keyNotFound(key, context): return "keyNotFound \(key.stringValue) at \(path(context)): \(context.debugDescription)"
        case let .dataCorrupted(context): return "dataCorrupted at \(path(context)): \(context.debugDescription)"
        @unknown default: return "unknown DecodingError"
        }
    }

    private func request(host: RemoteConnectionHost, path: String, method: String, timeout: TimeInterval, token: String?) throws -> URLRequest {
        let url = host.origin.appending(path: path)
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token, !token.isEmpty { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        return request
    }

    private func authenticatedRequest(path: String, method: String, timeout: TimeInterval = 12) throws -> URLRequest {
        guard let host, let credential else { throw RemoteConnectionError.authenticationFailed }
        return try request(host: host, path: path, method: method, timeout: timeout, token: credential)
    }

    private func unauthenticatedPost<T: Decodable>(host: RemoteConnectionHost, path: String, body: [String: Any]) async throws -> T {
        var request = try request(host: host, path: path, method: "POST", timeout: 12, token: nil)
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        try validateHTTP(http, data: data)
        return try decoder().decode(T.self, from: data)
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        let request = try authenticatedRequest(path: path, method: "GET")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        try validateHTTP(http, data: data)
        return try decoder().decode(T.self, from: data)
    }

    private func validateHTTP(_ response: HTTPURLResponse, data: Data?) throws {
        guard (200..<300).contains(response.statusCode) else { throw RemoteHTTPError(statusCode: response.statusCode) }
    }

    private func decoder() -> JSONDecoder { let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase; return decoder }

    static func parsePairingURL(_ raw: String) throws -> ParsedRemotePairing {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { throw RemoteConnectionError.emptyURL }
        guard let url = URL(string: text), let scheme = url.scheme, let host = url.host() else { throw RemoteConnectionError.invalidURL }
        var components = URLComponents(); components.scheme = scheme; components.host = host; components.port = url.port
        guard let origin = components.url else { throw RemoteConnectionError.missingHost }
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        return ParsedRemotePairing(host: RemoteConnectionHost(origin: origin), pairingCode: items.first(where: { $0.name == "pairing" })?.value,
                                   wasLegacyTokenURL: items.contains(where: { $0.name == "token" }))
    }
}

private struct RemoteHTTPError: LocalizedError {
    let statusCode: Int
    var errorDescription: String? { HTTPURLResponse.localizedString(forStatusCode: statusCode) }
}
