import Foundation

/// Small, deterministic ownership gate shared by LAN task creation and USB
/// takeover. It intentionally contains no networking or UI policy.
struct RemoteTransportGenerationGate {
    private(set) var lanGeneration = 0

    mutating func restartLAN() -> Int {
        lanGeneration &+= 1
        return lanGeneration
    }

    mutating func invalidateLAN() { lanGeneration &+= 1 }

    func acceptsLAN(_ generation: Int, usbIsActive: Bool) -> Bool {
        generation == lanGeneration && !usbIsActive
    }
}

struct RemoteLiveStateV2: Decodable, Equatable {
    let schemaVersion: Int
    let schema: String
    let stateRevision: Int
    let eventSequence: Int
    let serverTimestamp: Int
    let connection: RemoteConnectionMetadata
    let show: RemoteShowState
    let track: RemoteTrackState
    let decks: [RemoteDeckState]
    let musicalState: RemoteMusicalState
    let dmx: RemoteDmxHealth
    let fixtures: [RemoteFixtureGroup]
    let output: RemoteOutputPreview?
    let overrides: RemoteOverrideState
    let smoke: RemoteSmokeState?
    let warnings: [RemoteWarning]
    let control: RemoteControlCapabilities
}

struct RemoteConnectionMetadata: Decodable, Equatable { let protocolVersion: Int; let compatible: Bool; let server: String? }
struct RemoteShowState: Decodable, Equatable {
    let configuredProductionMode: String; let physicalFrameSource: String; let previewSource: String?
    let fallbackActive: Bool; let fallbackReason: String?; let dynamicComposerEligible: Bool
    let dynamicComposerActive: Bool; let baselineFallbackAvailable: Bool
}
struct RemoteTrackState: Decodable, Equatable {
    let title: String?; let artist: String?; let activeDeck: Int?; let playing: Bool
    let positionMilliseconds: Int?; let durationMilliseconds: Int?; let bpm: Double?; let beat: Int?; let bar: Int?
    let transportFresh: Bool; let readiness: String?
}
struct RemoteDeckState: Decodable, Equatable, Identifiable {
    let number: Int?; let loaded: Bool; let title: String?; let artist: String?; let playing: Bool
    let master: Bool; let active: Bool; let analysisReadiness: String?; let prewarmReadiness: String?
    var id: Int { number ?? -1 }
}
struct RemoteMusicalState: Decodable, Equatable {
    let section: String?; let sectionProgress: Double?; let relativeEnergy: Double?; let energyTrajectory: String?
    let recurrence: Double?; let materialContext: String?; let currentRme: RemoteRme?; let eventEnvelope: RemoteEventEnvelope
    let effectiveIntensity: Double?; let analyzedIntensity: Double?; let liveIntensityValid: Bool?
}
struct RemoteRme: Decodable, Equatable { let type: String?; let temporalKind: String? }
struct RemoteEventEnvelope: Decodable, Equatable { let active: Bool; let phase: String?; let progress: Double?; let eventType: String? }
struct RemoteDmxHealth: Decodable, Equatable {
    let connected: Bool; let deviceName: String?; let rendererHealthy: Bool; let rendererActive: Bool
    let frameSequence: Int?; let lastError: String?; let dispatchFailures: Int?; let renderedOutputAvailable: Bool?; let physicalOutputAvailable: Bool
}
struct RemoteOutputPreview: Decodable, Equatable {
    let renderedAvailable: Bool; let physicalOutputAvailable: Bool; let blackout: Bool
    let frameSequence: Int?; let fixtures: [RemoteOutputFixture]
}
struct RemoteOutputFixture: Decodable, Equatable, Identifiable {
    let id: String; let label: String; let role: String; let active: Bool
    let dimmer: Int; let red: Int; let green: Int; let blue: Int; let white: Int; let strobe: Int
    let effectiveIntensity: Double?; let resolvedRed: Int?; let resolvedGreen: Int?; let resolvedBlue: Int?; let resolvedWhite: Int?
    let pan: Int?; let tilt: Int?
}
struct RemoteFixtureGroup: Decodable, Equatable, Identifiable {
    let id: String; let label: String; let role: String; let active: Bool; let enabledSlots: Int
    let intensity: Double?; let colorPreset: String?; let movementActive: Bool; let overrideActive: Bool; let available: Bool
}
struct RemoteOverrideState: Decodable, Equatable {
    let anyActive: Bool; let phrase: String?; let energy: String?; let color: String?; let colorCombo: String?
    let momentaryEffects: [String]; let oneShot: RemoteOneShotState?; let fxSpeed: RemoteFxSpeedState?
    let masterDimmer: Double?; let blackout: Bool; let automatic: Bool
}
struct RemoteSmokeState: Decodable, Equatable {
    let supported: Bool; let reasonIfUnavailable: String?; let active: Bool
    let outputPercent: Int; let resolvedDmxValue: Int; let fixtureSlotIds: [String]
}
struct RemoteOneShotState: Decodable, Equatable {
    let id: String; let label: String; let durationBeats: Double; let progress: Double; let remainingBeats: Double
    let fxSpeed: String?
}
struct RemoteFxSpeedState: Decodable, Equatable { let mode: String; let resolved: String }
struct RemoteWarning: Decodable, Equatable, Identifiable {
    let code: String; let severity: String; let message: String
    var id: String { code }
}
struct RemotePairingResponse: Decodable {
    let schemaVersion: Int; let protocolVersion: Int; let scope: String; let credential: String
    let scopes: [String]?; let clientId: String?; let statePath: String; let eventsPath: String; let controlPath: String?
}
struct RemoteControlOption: Decodable, Equatable, Identifiable { let id: String; let label: String }
struct RemoteColorComboCapability: Decodable, Equatable, Identifiable {
    let id: String; let label: String; let colors: [String]; let available: Bool; let reasonIfUnavailable: String?
}
struct RemoteEffectCapability: Decodable, Equatable, Identifiable {
    let id: String; let label: String; let kind: String?; let available: Bool?
    let reasonIfUnavailable: String?; let temporarilyUnavailable: Bool?; let targetGroup: String?
    var isAvailable: Bool { available ?? true }
    var isTemporarilyUnavailable: Bool { temporarilyUnavailable ?? false }
}
struct RemoteControlCapabilities: Decodable, Equatable {
    let scope: String; let colors: [RemoteControlOption]; let phrases: [RemoteControlOption]
    let colorCombinations: [RemoteColorComboCapability]?
    let energies: [RemoteControlOption]; let fxSpeeds: [RemoteControlOption]?
    let momentaryEffects: [RemoteEffectCapability]
    let cueShots: [RemoteEffectCapability]; let momentaryLeaseSeconds: Double
}
struct RemoteControlAcknowledgement: Decodable {
    let accepted: Bool; let commandId: String?; let newStateRevision: Int; let effectiveState: RemoteLiveStateV2; let error: String?; let momentaryLease: RemoteMomentaryLease?
}
struct RemoteControlRejection: Decodable {
    let accepted: Bool; let commandId: String?; let newStateRevision: Int; let effectiveState: RemoteLiveStateV2; let error: String?; let momentaryLease: RemoteMomentaryLease?
}
struct RemoteMomentaryLease: Decodable, Equatable {
    let effect: String; let leaseId: String?; let active: Bool; let status: String
}
struct RemoteConnectionHost: Codable, Equatable {
    let origin: URL
    var displayHost: String {
        guard let host = origin.host() else { return origin.absoluteString }
        return origin.port.map { "\(host):\($0)" } ?? host
    }
}
struct ParsedRemotePairing: Equatable { let host: RemoteConnectionHost; let pairingCode: String?; let wasLegacyTokenURL: Bool }

enum RemoteConnectionError: LocalizedError, Equatable {
    case emptyURL, invalidURL, missingHost, pairingCodeRequired, legacyLinkRequiresPairing, authenticationFailed, incompatibleServer
    var errorDescription: String? {
        switch self {
        case .emptyURL: return "Voer een BeatBeam-pairingadres in."
        case .invalidURL: return "Het BeatBeam-adres is ongeldig."
        case .missingHost: return "Het BeatBeam-adres mist een host of poort."
        case .pairingCodeRequired: return "Voer de zes-cijferige pairingcode van BeatBeam in."
        case .legacyLinkRequiresPairing: return "Deze oude tokenlink is niet meer geschikt. Scan de nieuwe pairing-QR of voer het adres en de pairingcode in."
        case .authenticationFailed: return "De read-only verbinding is niet meer geautoriseerd. Pair opnieuw met BeatBeam."
        case .incompatibleServer: return "Deze BeatBeam-server ondersteunt Remote Live State V2 niet."
        }
    }
}
