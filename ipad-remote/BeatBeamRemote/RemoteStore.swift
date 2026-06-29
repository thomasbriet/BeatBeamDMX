import Foundation
import SwiftUI
import UIKit

@MainActor
final class RemoteStore: ObservableObject {
    struct StyleOption: Identifiable {
        let value: String
        let title: String
        var id: String { value }
    }

    struct ColorOption: Identifiable {
        let value: String
        let title: String
        let color: Color
        let secondary: Color?
        var id: String { value }
    }

    struct EffectOption: Identifiable {
        let key: String
        let title: String
        let symbol: String
        var id: String { key }
    }

    struct EnergyOption: Identifiable {
        let value: String
        let title: String
        var id: String { value }
    }

    struct PhraseOption: Identifiable {
        let value: String
        let title: String
        var id: String { value }
    }

    enum ConnectionState: Equatable {
        case idle
        case connecting
        case connected
        case offline
        case error(String)

        var label: String {
            switch self {
            case .idle: return "Niet verbonden"
            case .connecting: return "Verbinden…"
            case .connected: return "Verbonden"
            case .offline: return "Offline"
            case .error(let text): return text
            }
        }
    }

    @Published var appState: BeatBeamState?
    @Published var connectionState: ConnectionState = .idle
    @Published var configurationURLText = ""
    @Published var showConfiguration = false
    @Published var showScanner = false
    @Published var transientMessage: String?

    private let defaults = UserDefaults.standard
    private let storedURLKey = "BeatBeamRemote.StoredURL"
    private var parsedConnection: ParsedRemoteConnection?
    private var pollingTask: Task<Void, Never>?
    private var eventStreamTask: Task<Void, Never>?
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

    let styles: [StyleOption] = [
        .init(value: "adaptive", title: "Adaptive"),
        .init(value: "club", title: "Club"),
        .init(value: "cinematic", title: "Cinematic"),
        .init(value: "warm", title: "Warm"),
        .init(value: "festival", title: "Festival"),
        .init(value: "minimal", title: "Minimal"),
    ]

    let energyOptions: [EnergyOption] = [
        .init(value: "none", title: "Auto"),
        .init(value: "low", title: "Low"),
        .init(value: "mid", title: "Mid"),
        .init(value: "high", title: "High"),
    ]

    let phraseOptions: [PhraseOption] = [
        .init(value: "none", title: "Auto"),
        .init(value: "intro", title: "Intro"),
        .init(value: "verse", title: "Verse"),
        .init(value: "build", title: "Build"),
        .init(value: "chorus", title: "Chorus"),
        .init(value: "drop", title: "Drop"),
        .init(value: "down", title: "Down"),
        .init(value: "break", title: "Break"),
        .init(value: "outro", title: "Outro"),
    ]

    let colors: [ColorOption] = [
        .init(value: "none", title: "Auto", color: Color(.secondarySystemFill), secondary: nil),
        .init(value: "red", title: "Red", color: .red, secondary: nil),
        .init(value: "yellow", title: "Yellow", color: .yellow, secondary: nil),
        .init(value: "green", title: "Green", color: .green, secondary: nil),
        .init(value: "lime", title: "Lime", color: Color(red: 0.55, green: 1.00, blue: 0.12), secondary: nil),
        .init(value: "purple", title: "Purple", color: .purple, secondary: nil),
        .init(value: "pink", title: "Pink", color: Color(red: 1.00, green: 0.12, blue: 0.62), secondary: nil),
        .init(value: "cyan", title: "Cyan", color: .cyan, secondary: nil),
        .init(value: "orange", title: "Orange", color: .orange, secondary: nil),
        .init(value: "blue", title: "Blue", color: .blue, secondary: nil),
        .init(value: "white", title: "White", color: .white, secondary: nil),
        .init(value: "rainbow", title: "Rainbow", color: .red, secondary: .blue),
    ]

    let effects: [EffectOption] = [
        .init(key: "override_manual_strobe", title: "Strobe", symbol: "bolt.fill"),
        .init(key: "override_audience_sweep", title: "Audience", symbol: "arrow.left.and.right.circle.fill"),
        .init(key: "override_all_on", title: "All On", symbol: "light.max"),
        .init(key: "override_par_chase", title: "PAR Chase", symbol: "arrow.left.and.right"),
        .init(key: "override_par_snake", title: "PAR Snake", symbol: "waveform.path"),
    ]

    func bootstrap() {
        guard parsedConnection == nil else { return }
        if let stored = defaults.string(forKey: storedURLKey), !stored.isEmpty {
            configurationURLText = stored
            Task { await connect(using: stored) }
        } else {
            showConfiguration = true
        }
    }

    func resumePolling() {
        guard parsedConnection != nil else { return }
        startPolling()
    }

    func pausePolling() {
        pollingTask?.cancel()
        pollingTask = nil
        eventStreamTask?.cancel()
        eventStreamTask = nil
    }

    func pasteFromClipboard() {
        if let text = UIPasteboard.general.string?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty {
            configurationURLText = text
        }
    }

    func handleScannedURL(_ value: String) {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        configurationURLText = trimmed
        showScanner = false
        Task { await connect(using: trimmed) }
    }

    func saveConfiguration() {
        Task { await connect(using: configurationURLText) }
    }

    func reconnect() {
        guard !configurationURLText.isEmpty else {
            showConfiguration = true
            return
        }
        Task { await connect(using: configurationURLText) }
    }

    func connect(using rawURL: String) async {
        connectionState = .connecting
        do {
            let parsed = try Self.parseRemoteURL(rawURL)
            parsedConnection = parsed
            configurationURLText = parsed.sourceURL
            defaults.set(parsed.sourceURL, forKey: storedURLKey)
            showConfiguration = false
            try await refreshState()
            connectionState = .connected
            startPolling()
        } catch {
            connectionState = .error(error.localizedDescription)
            transientMessage = error.localizedDescription
        }
    }

    func disconnect() {
        pausePolling()
        appState = nil
        parsedConnection = nil
        connectionState = .idle
    }

    func setAutoShowEnabled(_ enabled: Bool) async {
        applyOptimisticAutoShowPatch(["enabled": enabled])
        await sendAutoShowPatch(["enabled": enabled])
    }

    func setStyle(_ style: String) async {
        applyOptimisticAutoShowPatch(["style": style])
        await sendAutoShowPatch(["style": style])
    }

    func setColor(_ value: String) async {
        applyOptimisticAutoShowPatch(["override_color": value])
        await sendAutoShowPatch(["override_color": value])
    }

    func setEnergyOverride(_ value: String) async {
        applyOptimisticAutoShowPatch(["override_energy": value])
        await sendAutoShowPatch(["override_energy": value])
    }

    func setPhraseOverride(_ value: String) async {
        applyOptimisticAutoShowPatch(["override_phrase": value])
        await sendAutoShowPatch(["override_phrase": value])
    }

    func toggleEffect(_ key: String) async {
        guard let autoShow = appState?.dmx.autoShow else { return }
        let current = valueForEffectKey(key, in: autoShow)
        await sendAutoShowPatch([key: !current])
    }

    func setEffect(_ key: String, enabled: Bool) async {
        applyOptimisticAutoShowPatch([key: enabled])
        await sendAutoShowPatch([key: enabled])
    }

    func clearOverrides() async {
        applyOptimisticAutoShowPatch([
            "override_phrase": "none",
            "override_color": "none",
            "override_energy": "none",
            "override_manual_strobe": false,
            "override_audience_sweep": false,
            "override_all_on": false,
            "override_par_chase": false,
            "override_par_snake": false,
        ])
        await sendAutoShowPatch([
            "override_phrase": "none",
            "override_color": "none",
            "override_energy": "none",
            "override_manual_strobe": false,
            "override_audience_sweep": false,
            "override_all_on": false,
            "override_par_chase": false,
            "override_par_snake": false,
        ])
    }

    func triggerBlackout() async {
        applyOptimisticBlackout(true)
        do {
            let state: BeatBeamState = try await post("/api/dmx/blackout", body: [:])
            appState = state
        } catch {
            handleError(error)
        }
    }

    func releaseBlackout() async {
        let slot = appState?.dmx.activeSlot ?? "head"
        applyOptimisticBlackout(false)
        do {
            let state: BeatBeamState = try await post("/api/dmx/update", body: [
                "active_slot": slot,
                "blackout_active": false,
            ])
            appState = state
        } catch {
            handleError(error)
        }
    }

    func setBlackoutEnabled(_ enabled: Bool) async {
        if enabled {
            await triggerBlackout()
        } else {
            await releaseBlackout()
        }
    }

    func isEffectEnabled(_ key: String) -> Bool {
        guard let autoShow = appState?.dmx.autoShow else { return false }
        return valueForEffectKey(key, in: autoShow)
    }

    var isConnected: Bool {
        if case .connected = connectionState { return true }
        return false
    }

    var currentCue: String {
        appState?.dmx.autoShow.cueLabel ?? "Geen cue"
    }

    var trackTitle: String {
        appState?.osc.trackTitle ?? "(geen track)"
    }

    var trackArtist: String {
        appState?.osc.trackArtist ?? "onbekend"
    }

    var remoteHostLabel: String {
        parsedConnection?.displayHost ?? "Niet ingesteld"
    }

    private func startPolling() {
        pollingTask?.cancel()
        eventStreamTask?.cancel()
        startEventStream()
        pollingTask = Task { [weak self] in
            while let self, !Task.isCancelled {
                do {
                    try await self.refreshState()
                    if self.connectionState != .connected {
                        self.connectionState = .connected
                    }
                } catch {
                    if self.connectionState != .connecting {
                        self.connectionState = .offline
                    }
                }
                try? await Task.sleep(nanoseconds: self.fallbackPollIntervalNanoseconds)
            }
        }
    }

    private func refreshState() async throws {
        let state: BeatBeamState = try await get("/api/remote-state")
        appState = state
    }

    private func startEventStream() {
        eventStreamTask?.cancel()
        eventStreamTask = Task { [weak self] in
            while let self, !Task.isCancelled {
                do {
                    try await self.runEventStream()
                } catch is CancellationError {
                    break
                } catch {
                    if Task.isCancelled { break }
                    if self.connectionState != .connecting {
                        self.connectionState = .offline
                    }
                }
                try? await Task.sleep(nanoseconds: self.streamRetryDelayNanoseconds)
            }
        }
    }

    private func runEventStream() async throws {
        let request = try eventStreamRequest("/api/remote-events")
        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        guard (200..<300).contains(http.statusCode) else {
            throw NSError(domain: "BeatBeamRemote", code: http.statusCode, userInfo: [
                NSLocalizedDescriptionKey: HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
            ])
        }
        for try await line in bytes.lines {
            if Task.isCancelled { break }
            guard line.hasPrefix("data:") else { continue }
            let payload = line.dropFirst(5).trimmingCharacters(in: .whitespacesAndNewlines)
            guard !payload.isEmpty else { continue }
            let data = Data(payload.utf8)
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            let state = try decoder.decode(BeatBeamState.self, from: data)
            appState = state
            if connectionState != .connected {
                connectionState = .connected
            }
        }
    }

    private func sendAutoShowPatch(_ patch: [String: Any]) async {
        let slot = appState?.dmx.activeSlot ?? "head"
        do {
            let state: BeatBeamState = try await post("/api/dmx/update", body: [
                "active_slot": slot,
                "auto_show": patch,
            ])
            appState = state
        } catch {
            handleError(error)
        }
    }

    private func applyOptimisticBlackout(_ enabled: Bool) {
        guard var state = appState else { return }
        state.dmx.blackoutActive = enabled
        appState = state
    }

    private func applyOptimisticAutoShowPatch(_ patch: [String: Any]) {
        guard var state = appState else { return }
        if let enabled = patch["enabled"] as? Bool {
            state.dmx.autoShow.enabled = enabled
        }
        if let style = patch["style"] as? String {
            state.dmx.autoShow.style = style
            state.dmx.autoShow.styleLabel = styleLabel(for: style)
            state.dmx.autoShow.cueLabel = "\(state.dmx.autoShow.styleLabel) • updating"
        }
        if let overridePhrase = patch["override_phrase"] as? String {
            state.dmx.autoShow.overridePhrase = overridePhrase
            state.dmx.autoShow.overridePhraseLabel = phraseLabel(for: overridePhrase)
        }
        if let overrideColor = patch["override_color"] as? String {
            state.dmx.autoShow.overrideColor = overrideColor
            state.dmx.autoShow.overrideColorLabel = colorLabel(for: overrideColor)
        }
        if let overrideEnergy = patch["override_energy"] as? String {
            state.dmx.autoShow.overrideEnergy = overrideEnergy
            state.dmx.autoShow.overrideEnergyLabel = energyLabel(for: overrideEnergy)
        }
        for key in [
            "override_manual_strobe",
            "override_audience_sweep",
            "override_all_on",
            "override_par_chase",
            "override_par_snake",
        ] {
            guard let value = patch[key] as? Bool else { continue }
            switch key {
            case "override_manual_strobe":
                state.dmx.autoShow.overrideManualStrobe = value
            case "override_audience_sweep":
                state.dmx.autoShow.overrideAudienceSweep = value
            case "override_all_on":
                state.dmx.autoShow.overrideAllOn = value
            case "override_par_chase":
                state.dmx.autoShow.overrideParChase = value
                if value { state.dmx.autoShow.overrideParSnake = false }
            case "override_par_snake":
                state.dmx.autoShow.overrideParSnake = value
                if value { state.dmx.autoShow.overrideParChase = false }
            default:
                break
            }
        }
        appState = state
    }

    private func valueForEffectKey(_ key: String, in autoShow: RemoteAutoShowState) -> Bool {
        switch key {
        case "override_manual_strobe": return autoShow.overrideManualStrobe
        case "override_audience_sweep": return autoShow.overrideAudienceSweep
        case "override_all_on": return autoShow.overrideAllOn
        case "override_par_chase": return autoShow.overrideParChase
        case "override_par_snake": return autoShow.overrideParSnake
        default: return false
        }
    }

    private func handleError(_ error: Error) {
        transientMessage = error.localizedDescription
        connectionState = .error(error.localizedDescription)
    }

    private func styleLabel(for value: String) -> String {
        switch value {
        case "club": return "Club"
        case "cinematic": return "Cinematic"
        case "warm": return "Warm"
        case "festival": return "Festival"
        case "minimal": return "Minimal"
        default: return "Adaptive"
        }
    }

    private func colorLabel(for value: String) -> String {
        switch value {
        case "red": return "Red"
        case "yellow": return "Yellow"
        case "green": return "Green"
        case "lime": return "Lime"
        case "purple": return "Purple"
        case "pink": return "Pink"
        case "cyan": return "Cyan"
        case "orange": return "Orange"
        case "blue": return "Blue"
        case "white": return "White"
        case "rainbow": return "Rainbow"
        default: return "Auto"
        }
    }

    private func energyLabel(for value: String) -> String {
        switch value {
        case "low": return "Low"
        case "mid": return "Mid"
        case "high": return "High"
        default: return "Auto"
        }
    }

    private func phraseLabel(for value: String) -> String {
        switch value {
        case "intro": return "Intro"
        case "verse": return "Verse"
        case "build": return "Build"
        case "chorus": return "Chorus"
        case "drop": return "Drop"
        case "down": return "Down"
        case "break": return "Break"
        case "outro": return "Outro"
        default: return "Auto"
        }
    }

    private func buildURL(path: String) throws -> URL {
        guard let parsedConnection else { throw RemoteConnectionError.invalidURL }
        return parsedConnection.origin.appending(path: path)
    }

    private func request(_ path: String, method: String, body: [String: Any]? = nil) async throws -> Data {
        var request = try buildRequest(path: path, method: method, timeoutInterval: 6)
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body, options: [])
        }

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        guard (200..<300).contains(http.statusCode) else {
            let message = (try? JSONDecoder().decode(APIErrorResponse.self, from: data).error) ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
            throw NSError(domain: "BeatBeamRemote", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: message])
        }
        return data
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        let data = try await request(path, method: "GET")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(T.self, from: data)
    }

    private func buildRequest(path: String, method: String, timeoutInterval: TimeInterval) throws -> URLRequest {
        let url = try buildURL(path: path)
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        if let token = parsedConnection?.token, !token.isEmpty {
            var items = components?.queryItems ?? []
            items.removeAll(where: { $0.name == "token" })
            items.append(URLQueryItem(name: "token", value: token))
            components?.queryItems = items
        }
        guard let finalURL = components?.url else { throw RemoteConnectionError.invalidURL }
        var request = URLRequest(url: finalURL, timeoutInterval: timeoutInterval)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token = parsedConnection?.token, !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private func eventStreamRequest(_ path: String) throws -> URLRequest {
        var request = try buildRequest(path: path, method: "GET", timeoutInterval: 3600)
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        return request
    }

    private func post<T: Decodable>(_ path: String, body: [String: Any]) async throws -> T {
        let data = try await request(path, method: "POST", body: body)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(T.self, from: data)
    }

    static func parseRemoteURL(_ raw: String) throws -> ParsedRemoteConnection {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw RemoteConnectionError.emptyURL }
        guard let url = URL(string: trimmed), let scheme = url.scheme, let host = url.host() else {
            throw RemoteConnectionError.invalidURL
        }
        var origin = URLComponents()
        origin.scheme = scheme
        origin.host = host
        origin.port = url.port
        guard let originURL = origin.url else {
            throw RemoteConnectionError.missingHost
        }
        let token = URLComponents(url: url, resolvingAgainstBaseURL: false)?
            .queryItems?
            .first(where: { $0.name == "token" })?
            .value
        return ParsedRemoteConnection(origin: originURL, token: token, sourceURL: trimmed)
    }
}

private struct APIErrorResponse: Decodable {
    let error: String
}
