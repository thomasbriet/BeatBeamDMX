import Foundation
import Security
import SwiftUI
import UIKit

private enum RemoteKeychain {
    static let service = "nl.beatbeam.remote"

    private static func simulatorDefaultsKey(account: String) -> String {
        "\(service).SimulatorCredential.\(account)"
    }

    static func save(_ value: String, account: String) throws {
#if targetEnvironment(simulator)
        // Simulator binaries do not receive the physical provisioning profile's
        // application-identifier entitlement. Keep acceptance pairing local to
        // this simulated device; production/device builds remain Keychain-only.
        UserDefaults.standard.set(value, forKey: simulatorDefaultsKey(account: account))
#else
        let data = Data(value.utf8)
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                    kSecAttrAccount as String: account]
        SecItemDelete(query as CFDictionary)
        var item = query
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(item as CFDictionary, nil)
        guard status == errSecSuccess else { throw NSError(domain: "BeatBeamRemote.Keychain", code: Int(status)) }
#endif
    }

    static func load(account: String) -> String? {
#if targetEnvironment(simulator)
        return UserDefaults.standard.string(forKey: simulatorDefaultsKey(account: account))
#else
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                    kSecAttrAccount as String: account, kSecReturnData as String: true,
                                    kSecMatchLimit as String: kSecMatchLimitOne]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
#endif
    }

    static func delete(account: String) {
#if targetEnvironment(simulator)
        UserDefaults.standard.removeObject(forKey: simulatorDefaultsKey(account: account))
#else
        SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                       kSecAttrAccount as String: account] as CFDictionary)
#endif
    }
}

@MainActor
final class RemoteStore: ObservableObject {
    /// Command routing is explicit. The HTTP/SSE implementation below remains
    /// the LAN transport; the USB listener supplies the same typed snapshots
    /// and acknowledgements without gaining independent UI authority.
    enum ActiveTransport: String, Equatable {
        case lan = "LAN"
        case usb = "USB"
    }
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
    @Published private(set) var activeTransport: ActiveTransport?
    @Published var configurationURLText = ""
    @Published var pairingCodeText = ""
    @Published var showConfiguration = false
    @Published var showScanner = false
    @Published var transientMessage: String?
    @Published private(set) var pendingActions: Set<String> = []
    @Published private(set) var locallyPressedMomentaryEffects: Set<String> = []
    @Published private(set) var locallyPressedSmoke = false

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
    private var newestUSBSequence = -1
    // Every LAN restart gets a fresh generation. This prevents an old SSE or
    // poll completion from changing transport/UI after USB supersedes it.
    private var networkGenerationGate = RemoteTransportGenerationGate()
    private weak var usbTransport: USBTransportPOCListener?
    // A gesture can emit several changed callbacks before its first network
    // acknowledgement.  Keep one state record per effect from touch-down,
    // rather than using the renewal task itself as the only active marker.
    private var momentaryStarts: Set<String> = []
    private var momentaryRenewals: [String: Task<Void, Never>] = [:]
    private var momentaryLeaseIDs: [String: String] = [:]
    private var momentaryReleasePending: Set<String> = []
    private var smokeStartPending = false
    private var smokeReleasePending = false
    private var smokeLeaseID: String?
    private var smokeRenewal: Task<Void, Never>?
    private var masterDimmerCoalescingTask: Task<Void, Never>?
    private var pendingMasterDimmer: Double?
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
    // The event stream stays open for the life of a connected remote.  HOLD
    // controls use a separate responsive session so touch-down never queues
    // behind polling/SSE transport work.
    private lazy var controlSession: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.waitsForConnectivity = false
        configuration.timeoutIntervalForRequest = 3
        configuration.timeoutIntervalForResource = 3
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.httpMaximumConnectionsPerHost = 2
        configuration.allowsConstrainedNetworkAccess = true
        configuration.allowsExpensiveNetworkAccess = true
        return URLSession(configuration: configuration)
    }()

    var isConnected: Bool { connectionState == .connected }
    var connectionLabel: String {
        guard connectionState == .connected, let activeTransport else { return connectionState.label }
        return "\(connectionState.label) · \(activeTransport.rawValue)"
    }
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

    func attachUSBTransport(_ transport: USBTransportPOCListener) {
        usbTransport = transport
        transport.onConnected = { [weak self] in
            Task { @MainActor in self?.usbConnected() }
        }
        transport.onDisconnected = { [weak self] in
            Task { @MainActor in self?.usbDisconnected() }
        }
        transport.onState = { [weak self] data, sequence in
            Task { @MainActor in self?.receiveUSBState(data, sequence: sequence) }
        }
    }

    func resumePolling() {
        guard credential != nil, host != nil else { return }
        guard activeTransport != .usb else { return }
        restartNetworkTransport()
    }

    func pausePolling() {
        releaseActiveMomentaries(reason: "connection paused")
        networkGenerationGate.invalidateLAN()
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
        activeTransport = nil; connectionState = .notPaired
        showConfiguration = true
    }

    func perform(_ action: String, value: String? = nil) {
        Task { _ = await sendControl(action, value: value) }
    }

    func queueMasterDimmer(_ value: Double) {
        pendingMasterDimmer = min(1, max(0, value))
        masterDimmerCoalescingTask?.cancel()
        masterDimmerCoalescingTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 70_000_000)
            guard !Task.isCancelled, let self else { return }
            await self.flushMasterDimmer()
        }
    }

    func commitMasterDimmer(_ value: Double) {
        pendingMasterDimmer = min(1, max(0, value))
        masterDimmerCoalescingTask?.cancel()
        masterDimmerCoalescingTask = nil
        Task { [weak self] in await self?.flushMasterDimmer() }
    }

    private func flushMasterDimmer() async {
        guard let value = pendingMasterDimmer else { return }
        pendingMasterDimmer = nil
        masterDimmerCoalescingTask = nil
        let wireValue = String(format: "%.4f", locale: Locale(identifier: "en_US_POSIX"), value)
        _ = await sendControl("set_master_dimmer", value: wireValue)
    }

    func beginMomentary(_ effect: String) {
        // Insert before awaiting so repeated onChanged callbacks cannot create
        // overlapping press/renewal lifecycles for the same HOLD pad.
        guard momentaryStarts.insert(effect).inserted else { return }
        locallyPressedMomentaryEffects.insert(effect)
        Task { [weak self] in
            guard let self else { return }
            let outcome = await self.sendControl("momentary_press", value: effect)
            self.completeMomentaryStart(effect, outcome: outcome)
        }
    }

    func endMomentary(_ effect: String) {
        locallyPressedMomentaryEffects.remove(effect)
        momentaryRenewals.removeValue(forKey: effect)?.cancel()
        if let leaseID = momentaryLeaseIDs.removeValue(forKey: effect) {
            momentaryStarts.remove(effect)
            releaseMomentary(effect, leaseID: leaseID)
        } else if momentaryStarts.contains(effect) {
            // Touch-up raced the press response.  The start completion will
            // immediately release the exact lease it receives.
            momentaryReleasePending.insert(effect)
        }
    }

    func releaseActiveMomentaries(reason: String = "") {
        let effects = Set(momentaryStarts).union(momentaryRenewals.keys).union(momentaryLeaseIDs.keys)
        for effect in effects { endMomentary(effect) }
        endSmokeHold()
    }

    func isMomentaryEngaged(_ effect: String) -> Bool {
        locallyPressedMomentaryEffects.contains(effect)
    }

    func beginSmokeHold() {
        guard !smokeStartPending, smokeLeaseID == nil else { return }
        smokeStartPending = true; locallyPressedSmoke = true
        Task { [weak self] in
            guard let self else { return }
            let outcome = await self.sendControl("smoke_hold_start")
            self.completeSmokeStart(outcome)
        }
    }

    func endSmokeHold() {
        locallyPressedSmoke = false
        smokeRenewal?.cancel(); smokeRenewal = nil
        if let leaseID = smokeLeaseID {
            smokeLeaseID = nil; smokeStartPending = false
            releaseSmoke(leaseID: leaseID)
        } else if smokeStartPending {
            smokeReleasePending = true
        }
    }

    private func completeSmokeStart(_ outcome: ControlOutcome) {
        guard smokeStartPending else { return }
        guard outcome.accepted, let lease = outcome.momentaryLease, lease.active, let leaseID = lease.leaseId else {
            smokeStartPending = false; smokeReleasePending = false; locallyPressedSmoke = false; return
        }
        smokeLeaseID = leaseID; smokeStartPending = false
        if smokeReleasePending { smokeReleasePending = false; smokeLeaseID = nil; releaseSmoke(leaseID: leaseID); return }
        smokeRenewal = Task { [weak self] in
            while let self, !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 900_000_000)
                guard !Task.isCancelled else { break }
                guard await self.renewSmoke() else { break }
            }
        }
    }

    private func renewSmoke() async -> Bool {
        guard let leaseID = smokeLeaseID else { return false }
        let outcome = await sendControl("smoke_hold_renew", leaseID: leaseID, suppressBenignMomentaryError: true)
        guard outcome.accepted, outcome.momentaryLease?.active == true else {
            smokeRenewal?.cancel(); smokeRenewal = nil; smokeLeaseID = nil; locallyPressedSmoke = false
            return false
        }
        return true
    }

    private func releaseSmoke(leaseID: String) {
        Task { [weak self] in
            guard let self else { return }
            _ = await self.sendControl("smoke_hold_end", leaseID: leaseID, suppressBenignMomentaryError: true)
        }
    }

    private struct ControlOutcome {
        let accepted: Bool
        let momentaryLease: RemoteMomentaryLease?
    }

    private func completeMomentaryStart(_ effect: String, outcome: ControlOutcome) {
        guard momentaryStarts.contains(effect) else { return }
        guard outcome.accepted, let lease = outcome.momentaryLease, lease.active, let leaseID = lease.leaseId else {
            momentaryStarts.remove(effect)
            momentaryReleasePending.remove(effect)
            locallyPressedMomentaryEffects.remove(effect)
            return
        }
        momentaryLeaseIDs[effect] = leaseID
        momentaryStarts.remove(effect)
        if momentaryReleasePending.remove(effect) != nil {
            momentaryLeaseIDs.removeValue(forKey: effect)
            releaseMomentary(effect, leaseID: leaseID)
            return
        }
        momentaryRenewals[effect]?.cancel()
        momentaryRenewals[effect] = Task { [weak self] in
            while let self, !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 900_000_000)
                guard !Task.isCancelled else { break }
                guard await self.renewMomentary(effect) else { break }
            }
        }
    }

    private func renewMomentary(_ effect: String) async -> Bool {
        guard let leaseID = momentaryLeaseIDs[effect] else { return false }
        let outcome = await sendControl("momentary_renew", value: effect, leaseID: leaseID, suppressBenignMomentaryError: true)
        guard outcome.accepted, outcome.momentaryLease?.active == true else {
            momentaryRenewals.removeValue(forKey: effect)?.cancel()
            momentaryLeaseIDs.removeValue(forKey: effect)
            locallyPressedMomentaryEffects.remove(effect)
            return false
        }
        return true
    }

    private func releaseMomentary(_ effect: String, leaseID: String) {
        Task { [weak self] in
            guard let self else { return }
            _ = await self.sendControl("momentary_release", value: effect, leaseID: leaseID, suppressBenignMomentaryError: true)
        }
    }

    private func sendControl(_ action: String, value: String? = nil, leaseID: String? = nil, suppressBenignMomentaryError: Bool = false) async -> ControlOutcome {
        if activeTransport == .usb, let usbTransport {
            return await sendUSBControl(usbTransport, action: action, value: value, leaseID: leaseID, suppressBenignMomentaryError: suppressBenignMomentaryError)
        }
        guard credential != nil, host != nil else { showConfiguration = true; return ControlOutcome(accepted: false, momentaryLease: nil) }
        let pending = "\(action):\(value ?? "")"
        pendingActions.insert(pending)
        defer { pendingActions.remove(pending) }
        do {
            var request = try authenticatedRequest(path: "/api/remote-v2/control", method: "POST")
            request.networkServiceType = .responsiveData
            var body: [String: Any] = [
                "command_id": UUID().uuidString, "action": action, "value": value ?? NSNull(),
            ]
            if let leaseID { body["lease_id"] = leaseID }
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            let (data, response) = try await controlSession.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
            if (200..<300).contains(http.statusCode) {
                let acknowledgement = try decoder().decode(RemoteControlAcknowledgement.self, from: data)
                apply(acknowledgement.effectiveState)
                guard acknowledgement.accepted else {
                    if !shouldSuppressMomentaryLifecycleError(action: action, error: acknowledgement.error, enabled: suppressBenignMomentaryError) { transientMessage = acknowledgement.error ?? "Opdracht geweigerd door BeatBeam." }
                    return ControlOutcome(accepted: false, momentaryLease: acknowledgement.momentaryLease)
                }
                return ControlOutcome(accepted: true, momentaryLease: acknowledgement.momentaryLease)
            }
            if http.statusCode == 409 {
                // A conflict is a typed command rejection, never a success ack.
                let rejection = try decoder().decode(RemoteControlRejection.self, from: data)
                apply(rejection.effectiveState)
                if !shouldSuppressMomentaryLifecycleError(action: action, error: rejection.error, enabled: suppressBenignMomentaryError) { transientMessage = rejection.error ?? "Opdracht geweigerd door BeatBeam." }
                return ControlOutcome(accepted: false, momentaryLease: rejection.momentaryLease)
            }
            try validateHTTP(http, data: data)
            return ControlOutcome(accepted: false, momentaryLease: nil)
        } catch {
            applyConnectionError(error)
            return ControlOutcome(accepted: false, momentaryLease: nil)
        }
    }

    private func sendUSBControl(_ transport: USBTransportPOCListener, action: String, value: String?, leaseID: String?, suppressBenignMomentaryError: Bool) async -> ControlOutcome {
        guard let data = await transport.sendCommand(action: action, value: value, leaseID: leaseID) else {
            // Never retry this command over LAN: its completion is unknown.
            usbDisconnected()
            transientMessage = "USB-opdracht niet bevestigd. Niet opnieuw verzonden."
            return ControlOutcome(accepted: false, momentaryLease: nil)
        }
        do {
            let acknowledgement = try decoder().decode(RemoteControlAcknowledgement.self, from: data)
            apply(acknowledgement.effectiveState, from: .usb)
            guard acknowledgement.accepted else {
                if !shouldSuppressMomentaryLifecycleError(action: action, error: acknowledgement.error, enabled: suppressBenignMomentaryError) { transientMessage = acknowledgement.error ?? "Opdracht geweigerd door BeatBeam." }
                return ControlOutcome(accepted: false, momentaryLease: acknowledgement.momentaryLease)
            }
            return ControlOutcome(accepted: true, momentaryLease: acknowledgement.momentaryLease)
        } catch {
            transientMessage = "USB-antwoord is niet compatibel."
            usbDisconnected()
            return ControlOutcome(accepted: false, momentaryLease: nil)
        }
    }

    private func shouldSuppressMomentaryLifecycleError(action: String, error: String?, enabled: Bool) -> Bool {
        enabled && ["momentary_release", "momentary_renew", "smoke_hold_end", "smoke_hold_renew"].contains(action) && (error == "momentary effect has no active lease" || error == "smoke hold has no active lease")
    }

    private func applyPairingInput(_ raw: String) {
        configurationURLText = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if let parsed = try? Self.parsePairingURL(configurationURLText), let code = parsed.pairingCode {
            pairingCodeText = code
        }
    }

    private func connectStoredCredential() {
        if activeTransport != .usb { connectionState = .connecting }
        Task {
            do {
                try await refreshState()
                if self.activeTransport != .usb { connectionState = .connected; self.activeTransport = .lan }
                failedRefreshes = 0
                restartNetworkTransport()
            } catch { applyConnectionError(error) }
        }
    }

    private func pair(using rawURL: String, code: String) async {
        if activeTransport != .usb { connectionState = .connecting }
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
            if activeTransport != .usb { connectionState = .connected; activeTransport = .lan }; failedRefreshes = 0
            restartNetworkTransport()
        } catch { applyConnectionError(error) }
    }

    /// Rebuild the LAN lifecycle without touching stored pairing material. It
    /// is used for foreground recovery and, critically, USB → LAN failover.
    private func restartNetworkTransport() {
        guard credential != nil, host != nil else {
            activeTransport = nil; connectionState = .offline; return
        }
        let generation = networkGenerationGate.restartLAN()
        pollingTask?.cancel(); eventStreamTask?.cancel()
        pollingTask = nil; eventStreamTask = nil
        if activeTransport != .usb { connectionState = .reconnecting }
        startEventStream(generation: generation)
        pollingTask = Task { [weak self] in
            while let self, !Task.isCancelled {
                guard self.isCurrentNetworkGeneration(generation) else { break }
                do {
                    try await self.refreshState(generation: generation)
                    guard self.isCurrentNetworkGeneration(generation) else { break }
                    self.failedRefreshes = 0
                    if self.activeTransport != .usb {
                        if self.connectionState != .connected { self.connectionState = .connected }
                        self.activeTransport = .lan
                    }
                } catch {
                    guard self.isCurrentNetworkGeneration(generation) else { break }
                    self.failedRefreshes += 1
                    if self.activeTransport != .usb && self.connectionState != .authFailed && self.connectionState != .serverIncompatible {
                        self.connectionState = self.failedRefreshes >= 3 ? .offline : .reconnecting
                    }
                }
                try? await Task.sleep(nanoseconds: self.fallbackPollIntervalNanoseconds)
            }
        }
    }

    private func startEventStream(generation: Int) {
        eventStreamTask = Task { [weak self] in
            while let self, !Task.isCancelled {
                guard self.isCurrentNetworkGeneration(generation) else { break }
                do { try await self.runEventStream(generation: generation) }
                catch is CancellationError { break }
                catch {
                    if Task.isCancelled || !self.isCurrentNetworkGeneration(generation) { break }
                    if self.activeTransport != .usb && self.connectionState != .authFailed && self.connectionState != .serverIncompatible { self.connectionState = .reconnecting }
                }
                try? await Task.sleep(nanoseconds: self.streamRetryDelayNanoseconds)
            }
        }
    }

    private func isCurrentNetworkGeneration(_ generation: Int) -> Bool {
        networkGenerationGate.acceptsLAN(generation, usbIsActive: activeTransport == .usb)
    }

    private func refreshState(generation: Int? = nil) async throws {
        let state: RemoteLiveStateV2 = try await get("/api/remote-v2/state")
        try validate(state)
        if let generation, !isCurrentNetworkGeneration(generation) { return }
        apply(state, from: .lan, networkGeneration: generation)
    }

    private func runEventStream(generation: Int) async throws {
        var streamRequest = try authenticatedRequest(path: "/api/remote-v2/events", method: "GET", timeout: 3600)
        streamRequest.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        streamRequest.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        let (bytes, response) = try await session.bytes(for: streamRequest)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        try validateHTTP(http, data: nil)
        for try await line in bytes.lines {
            if Task.isCancelled || !isCurrentNetworkGeneration(generation) { break }
            guard line.hasPrefix("data:") else { continue }
            let json = String(line.dropFirst(5)).trimmingCharacters(in: CharacterSet.whitespacesAndNewlines)
            guard !json.isEmpty else { continue }
            do {
                let state = try decoder().decode(RemoteLiveStateV2.self, from: Data(json.utf8))
                try validate(state)
                guard isCurrentNetworkGeneration(generation) else { break }
                apply(state, from: .lan, networkGeneration: generation); failedRefreshes = 0
                if activeTransport != .usb, connectionState != .connected { connectionState = .connected; activeTransport = .lan }
            } catch { throw error }
        }
    }

    private func apply(_ state: RemoteLiveStateV2, from transport: ActiveTransport = .lan, networkGeneration stateGeneration: Int? = nil) {
        if let stateGeneration, !networkGenerationGate.acceptsLAN(stateGeneration, usbIsActive: activeTransport == .usb) { return }
        guard activeTransport == nil || activeTransport == transport else { return }
        guard state.stateRevision > newestRevision || (state.stateRevision == newestRevision && state.eventSequence > newestSequence) else { return }
        newestRevision = state.stateRevision; newestSequence = state.eventSequence; liveState = state
    }

    private func usbConnected() {
        // USB becomes authoritative at a clear boundary; old LAN callbacks
        // cannot later retake the UI or command route.
        networkGenerationGate.invalidateLAN()
        pollingTask?.cancel(); pollingTask = nil
        eventStreamTask?.cancel(); eventStreamTask = nil
        newestUSBSequence = -1
        activeTransport = .usb
        connectionState = .connected
        showConfiguration = false
        transientMessage = nil
    }

    private func receiveUSBState(_ data: Data, sequence: Int) {
        guard activeTransport == .usb, sequence > newestUSBSequence else { return }
        do {
            let state = try decoder().decode(RemoteLiveStateV2.self, from: data)
            try validate(state)
            newestUSBSequence = sequence
            apply(state, from: .usb)
            connectionState = .connected
        } catch {
            transientMessage = "USB-status is niet compatibel."
        }
    }

    private func usbDisconnected() {
        guard activeTransport == .usb else { return }
        // The bridge releases USB-owned leases centrally on session loss. The
        // local flags must also clear without attempting a second transport.
        locallyPressedMomentaryEffects.removeAll(); locallyPressedSmoke = false
        momentaryRenewals.values.forEach { $0.cancel() }; momentaryRenewals.removeAll(); momentaryLeaseIDs.removeAll(); momentaryStarts.removeAll(); momentaryReleasePending.removeAll()
        smokeRenewal?.cancel(); smokeRenewal = nil; smokeLeaseID = nil; smokeStartPending = false; smokeReleasePending = false
        activeTransport = nil
        connectionState = credential != nil && host != nil ? .reconnecting : .offline
        // Merely selecting LAN was the failure: start a new HTTP/SSE/poll
        // lifecycle immediately, reusing the saved host and Keychain token.
        restartNetworkTransport()
    }

    private func validate(_ state: RemoteLiveStateV2) throws {
        guard state.schemaVersion == 2, state.connection.protocolVersion == 2, state.connection.compatible else {
            throw RemoteConnectionError.incompatibleServer
        }
    }

    private func applyConnectionError(_ error: Error) {
        if activeTransport == .usb { return }
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
