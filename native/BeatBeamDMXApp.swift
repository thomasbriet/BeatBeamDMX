import AppKit
import AVFoundation
import CoreAudio
import CoreImage.CIFilterBuiltins
import Darwin
import Foundation
import MetalKit
import SceneKit
import SwiftUI

private let beamConeShaderModifiers: [SCNShaderModifierEntryPoint: String] = [
    .geometry: """
    #pragma varyings
    float3 beamLocalPos;

    #pragma body
    out.beamLocalPos = _geometry.position.xyz;
    """,
    .fragment: """
    #pragma arguments
    float beamFalloffExponent;
    float beamSourceLift;
    float beamViewExponent;
    float beamNoiseAmount;
    float beamNoiseScale;
    float beamMinimumAlpha;
    float beamGlowBoost;

    #pragma varyings
    float3 beamLocalPos;

    #pragma transparent

    #pragma declaration
    float beamNoiseHash(float3 p) {
        return fract(sin(dot(p, float3(12.9898, 78.233, 37.719))) * 43758.5453);
    }

    #pragma body
    float minY = scn_node.boundingBox[0].y;
    float maxY = scn_node.boundingBox[1].y;
    float lengthRange = max(0.0001, maxY - minY);
    float beamT = saturate((in.beamLocalPos.y - minY) / lengthRange);
    float sourceMask = pow(max(0.0, 1.0 - beamT), beamFalloffExponent);
    float sideView = pow(
        saturate(1.0 - abs(dot(normalize(_surface.view), normalize(_surface.geometryNormal)))),
        beamViewExponent
    );
    float breakup = mix(
        1.0 - beamNoiseAmount,
        1.0,
        beamNoiseHash(float3(
            in.beamLocalPos.x * beamNoiseScale,
            in.beamLocalPos.z * beamNoiseScale,
            beamT * 21.0 + scn_frame.time * 0.25
        ))
    );
    float beamMask = max(
        beamMinimumAlpha,
        (beamSourceLift + sourceMask * (1.0 - beamSourceLift)) *
        (0.24 + sideView * 0.76) *
        breakup
    );
    float glowMask = beamMask * (0.82 + sourceMask * beamGlowBoost);
    _output.color.rgb *= glowMask;
    _output.color.a *= beamMask;
    """
]

private func appInfoString(_ key: String, default defaultValue: String) -> String {
    guard let rawValue = Bundle.main.object(forInfoDictionaryKey: key) else {
        return defaultValue
    }
    if let value = rawValue as? String {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? defaultValue : trimmed
    }
    if let number = rawValue as? NSNumber {
        return number.stringValue
    }
    return defaultValue
}

private func appInfoInt(_ key: String, default defaultValue: Int) -> Int {
    guard let rawValue = Bundle.main.object(forInfoDictionaryKey: key) else {
        return defaultValue
    }
    if let number = rawValue as? NSNumber {
        return number.intValue
    }
    if let value = rawValue as? String,
       let parsed = Int(value.trimmingCharacters(in: .whitespacesAndNewlines)) {
        return parsed
    }
    return defaultValue
}

private let beatBeamAppDisplayName = appInfoString("CFBundleDisplayName", default: "BeatBeam DMX")
private let beatBeamAppVersion = appInfoString("CFBundleShortVersionString", default: "1.2.0-dev")
private let beatBeamAppBundleFileName = Bundle.main.bundleURL.lastPathComponent
private let beatBeamDefaultsPrefix = appInfoString("BeatBeamDefaultsPrefix", default: "BeatBeamDMX")
private let beatBeamBackendPort = appInfoInt("BeatBeamBackendPort", default: 8780)
private let beatBeamBackendOscPort = appInfoInt("BeatBeamBackendOscPort", default: 4461)
private let beatBeamSupportDirectoryName = appInfoString("BeatBeamSupportDirectoryName", default: "BeatBeamDMX Native")
private let beatBeamStableSupportDirectoryName = appInfoString("BeatBeamStableSupportDirectoryName", default: "BeatBeamDMX Native")
private let beatBeamTemporaryDirectoryName = appInfoString("BeatBeamTemporaryDirectoryName", default: "BeatBeamDMX")
private let beatBeamLogStem = appInfoString("BeatBeamLogStem", default: beatBeamDefaultsPrefix.lowercased())
private let beatBeamAppSlug = appInfoString("BeatBeamAppSlug", default: beatBeamDefaultsPrefix)
let nativeLogURL = FileManager.default.temporaryDirectory.appendingPathComponent("\(beatBeamLogStem)-native.log")
let backendLogURL = FileManager.default.temporaryDirectory.appendingPathComponent("\(beatBeamLogStem)-native-backend.log")
private let stageMapAspectRatio: CGFloat = 16.0 / 9.0
private let requiredBackendSchemaVersion = 4
private let defaultBackendOscPort = beatBeamBackendOscPort
private let stageMapInspectorWidthDefaultsKey = "BeatBeamDMX.stageMap.inspectorWidth"

private func defaultRekordboxBridgeScriptPath() -> String {
    let fallback = (URL(fileURLWithPath: NSHomeDirectory()) as URL)
        .appendingPathComponent("BPM Trigger/start_bridge.sh")
        .path
    let candidates: [String] = [
        fallback,
        URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
            .appendingPathComponent("../BPM Trigger/start_bridge.sh")
            .standardizedFileURL
            .path,
    ]
    for candidate in candidates where FileManager.default.fileExists(atPath: candidate) {
        return candidate
    }
    return fallback
}

private func runSystemProcess(_ executable: String, _ args: [String]) -> (ok: Bool, message: String) {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: executable)
    process.arguments = args

    let out = Pipe()
    let err = Pipe()
    process.standardOutput = out
    process.standardError = err

    do {
        try process.run()
        process.waitUntilExit()
        let outText = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        let errText = String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        let ok = process.terminationStatus == 0
        let msg = (outText + "\n" + errText).trimmingCharacters(in: .whitespacesAndNewlines)
        return (ok, msg)
    } catch {
        return (false, error.localizedDescription)
    }
}

private func launchSystemProcess(_ executable: String, _ args: [String], startupWaitMicros: useconds_t = 350_000) -> (ok: Bool, message: String) {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: executable)
    process.arguments = args

    let out = Pipe()
    let err = Pipe()
    process.standardOutput = out
    process.standardError = err

    do {
        try process.run()
        usleep(startupWaitMicros)
        if process.isRunning {
            return (true, "")
        }

        let outText = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        let errText = String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        let ok = process.terminationStatus == 0
        let msg = (outText + "\n" + errText).trimmingCharacters(in: .whitespacesAndNewlines)
        return (ok, msg)
    } catch {
        return (false, error.localizedDescription)
    }
}

private func shellSingleQuote(_ text: String) -> String {
    "'" + text.replacingOccurrences(of: "'", with: "'\"'\"'") + "'"
}

private func runAdministratorShell(_ command: String) -> (ok: Bool, message: String) {
    let escaped = command
        .replacingOccurrences(of: "\\", with: "\\\\")
        .replacingOccurrences(of: "\"", with: "\\\"")
    let script = "do shell script \"\(escaped)\" with administrator privileges"
    return runSystemProcess("/usr/bin/osascript", ["-e", script])
}

final class BeatBeamAppDelegate: NSObject, NSApplicationDelegate {
    var onTerminate: (() -> Void)?

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        onTerminate?()
    }
}

enum StageWorld {
    static let minX: Double = -700
    static let maxX: Double = 700
    static let minY: Double = -200
    static let maxY: Double = 900
    static let minZ: Double = 0
    static let maxZ: Double = 450
    /// Projection storage remains centimetres for backward-compatible local
    /// UserDefaults, but every authored/public coordinate is metres.
    static let majorGridStepCm: Double = 100
    static let minorGridStepCm: Double = 25
    static let dragSnapCm: Double = 25
    static let beamMaxDistanceCm: Double = 700
    static let movingHeadBeamDistanceCm: Double = 350
}

enum BeatBeamPalette {
    static let brandCyan = Color(red: 0.12, green: 0.88, blue: 0.96)
    static let brandMagenta = Color(red: 0.93, green: 0.17, blue: 0.70)
    static let brandAmber = Color(red: 1.00, green: 0.72, blue: 0.10)
    static let appBackground = Color(red: 0.04, green: 0.05, blue: 0.07)
    static let panelBackground = Color(red: 0.09, green: 0.10, blue: 0.14)
    static let raisedBackground = Color(red: 0.13, green: 0.15, blue: 0.20)
    static let mutedBackground = Color.white.opacity(0.06)
    static let border = Color.white.opacity(0.09)
    static let triggerActive = brandCyan
    static let triggerOutline = brandCyan.opacity(0.46)
    static let utilityActive = brandMagenta
    static let warningActive = brandAmber
    static let secondaryText = Color.white.opacity(0.72)

    static var appGradient: LinearGradient {
        LinearGradient(
            colors: [
                Color(red: 0.05, green: 0.07, blue: 0.11),
                Color(red: 0.04, green: 0.05, blue: 0.07),
                Color(red: 0.06, green: 0.05, blue: 0.09)
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    static var surfaceGradient: LinearGradient {
        LinearGradient(
            colors: [
                Color(red: 0.11, green: 0.13, blue: 0.18),
                Color(red: 0.08, green: 0.09, blue: 0.13)
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    static var raisedGradient: LinearGradient {
        LinearGradient(
            colors: [
                Color(red: 0.15, green: 0.17, blue: 0.23),
                Color(red: 0.11, green: 0.13, blue: 0.18)
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    static var activeGradient: LinearGradient {
        LinearGradient(
            colors: [brandCyan, Color(red: 0.05, green: 0.62, blue: 0.86)],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    static var utilityGradient: LinearGradient {
        LinearGradient(
            colors: [brandMagenta, Color(red: 0.48, green: 0.12, blue: 0.74)],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    static var warningGradient: LinearGradient {
        LinearGradient(
            colors: [brandAmber, Color(red: 0.95, green: 0.40, blue: 0.08)],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }
}

private func beatBeamBrandImage() -> NSImage? {
    guard let url = Bundle.main.url(forResource: "BrandMark", withExtension: "png") else { return nil }
    return NSImage(contentsOf: url)
}

struct BeatBeamBrandLockup: View {
    var compact: Bool = false

    var body: some View {
        HStack(spacing: compact ? 10 : 12) {
            Group {
                if let image = beatBeamBrandImage() {
                    Image(nsImage: image)
                        .resizable()
                        .interpolation(.high)
                        .scaledToFit()
                } else {
                    Image(systemName: "waveform.path.ecg.rectangle.fill")
                        .resizable()
                        .scaledToFit()
                        .foregroundStyle(BeatBeamPalette.brandCyan)
                        .padding(compact ? 8 : 10)
                }
            }
            .frame(width: compact ? 34 : 42, height: compact ? 34 : 42)
            .background(
                RoundedRectangle(cornerRadius: compact ? 11 : 14, style: .continuous)
                    .fill(BeatBeamPalette.raisedGradient)
            )
            .overlay(
                RoundedRectangle(cornerRadius: compact ? 11 : 14, style: .continuous)
                    .stroke(BeatBeamPalette.brandCyan.opacity(0.26), lineWidth: 1)
            )

            VStack(alignment: .leading, spacing: compact ? 1 : 2) {
                Text("BeatBeam")
                    .font(.system(size: compact ? 14 : 16, weight: .bold))
                    .foregroundStyle(Color.white)
                Text(compact ? "DMX" : "DMX Control")
                    .font(.system(size: compact ? 10 : 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(BeatBeamPalette.brandMagenta.opacity(0.88))
            }
        }
    }
}

func nativeLog(_ text: String) {
    let line = "[\(Date())] \(text)\n"
    let data = Data(line.utf8)
    if FileManager.default.fileExists(atPath: nativeLogURL.path) {
        if let handle = try? FileHandle(forWritingTo: nativeLogURL) {
            _ = try? handle.seekToEnd()
            try? handle.write(contentsOf: data)
            try? handle.close()
        }
    } else {
        try? data.write(to: nativeLogURL)
    }
}

func formatDebugTrackPosition(_ milliseconds: Int?) -> String {
    guard let milliseconds, milliseconds >= 0 else { return "—" }
    return "\(formatDebugClock(milliseconds)) · \(milliseconds) ms"
}

func formatDebugClock(_ milliseconds: Int?) -> String {
    guard let milliseconds, milliseconds >= 0 else { return "—" }
    let totalSeconds = milliseconds / 1000
    let hours = totalSeconds / 3600
    let minutes = (totalSeconds / 60) % 60
    let seconds = totalSeconds % 60
    let millis = milliseconds % 1000
    return hours > 0
        ? String(format: "%02d:%02d:%02d.%03d", hours, minutes, seconds, millis)
        : String(format: "%02d:%02d.%03d", totalSeconds / 60, seconds, millis)
}

func redactedRemoteURL(_ value: String?) -> String {
    guard let value, !value.isEmpty, var components = URLComponents(string: value) else {
        return value ?? "nil"
    }
    components.queryItems = components.queryItems?.map { item in
        ["token", "pairing"].contains { item.name.caseInsensitiveCompare($0) == .orderedSame }
            ? URLQueryItem(name: item.name, value: "<redacted>")
            : item
    }
    return components.string ?? value
}

private func clampDMX(_ value: Int) -> Int {
    min(255, max(0, value))
}

struct AppInfo: Decodable {
    let name: String
}

struct AppState: Decodable {
    let app: AppInfo
    let dmx: DmxState
    let osc: OscState
    let remote: RemoteAccessState?
    let source: SourceState
    let transport: TransportState
    let liveUi: LiveUiState?
    let developerStructureBehavior: DeveloperStructureBehaviorState?
    let debug: DebugState?
}

struct DebugState: Decodable {
    let virtualdj: DebugVirtualDjState?
    let activeTrack: DebugActiveTrack?
    let analysis: DebugAnalysisState?
    let handoff: DebugHandoffState?
    let bridgeDiagnostics: DebugBridgeDiagnostics?
}

struct DebugVirtualDjState: Decodable {
    let transportSource: String?; let activeDeck: Int?; let trackPath: String?; let bridgeStatus: String?
    let playing: Bool?; let positionMilliseconds: Int?; let positionAgeMilliseconds: Int?; let transportState: String?
}
struct DebugActiveTrack: Decodable {
    let canonicalPath: String
    let deck: Int
    let status: String
    let generation: Int
    let activatedAtUnixMilliseconds: Int?
    let lastFailure: DebugFailure?
    let forceStatus: String?

    private enum CodingKeys: String, CodingKey {
        case canonicalPath
        case filePath
        case deck
        case status
        case generation
        case activatedAtUnixMilliseconds
        case lastFailure
        case forceStatus
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        canonicalPath = try container.decodeIfPresent(String.self, forKey: .canonicalPath)
            ?? container.decode(String.self, forKey: .filePath)
        deck = try container.decode(Int.self, forKey: .deck)
        status = try container.decode(String.self, forKey: .status)
        generation = try container.decode(Int.self, forKey: .generation)
        activatedAtUnixMilliseconds = try container.decodeIfPresent(Int.self, forKey: .activatedAtUnixMilliseconds)
        lastFailure = try container.decodeIfPresent(DebugFailure.self, forKey: .lastFailure)
        forceStatus = try container.decodeIfPresent(String.self, forKey: .forceStatus)
    }
}
struct DebugFailure: Decodable {
    let filePath: String?; let timestampUtc: String?; let priority: String?; let phase: String?
    let message: String?; let exitCode: Int?; let timedOut: Bool?; let stderr: String?
    let category: String?; let jobId: String?
}
struct DebugAnalysisState: Decodable {
    let schemaVersion: Int?
    let analysisVersion: String?
    let phraseAnalysisVersion: String?
    let model: String?
    let segment: DebugSegment?
    let semanticSection: DebugSemanticSection?
    let richCurrent: DebugRichSegment?
    let currentEvent: DebugRichEvent?
    let nextEvent: DebugRichEvent?
    let energyModifier: Double?
    let shadowSectionCharacter: DebugShadowSectionCharacter?
    let shadowEventEvidence: DebugShadowEventEvidence?
}
struct DebugSegment: Decodable { let index: Int?; let label: String?; let startSeconds: Double?; let endSeconds: Double?; let confidence: Double? }
struct DebugRichSegment: Decodable { let index: Int?; let label: String?; let level: String?; let energy: Double?; let confidence: Double? }
struct DebugRichEvent: Decodable { let type: String?; let confidence: Double?; let startSeconds: Double?; let targetSeconds: Double?; let startBar: Int?; let targetBar: Int?; let barsToNext: Int? }
struct DebugShadowSectionCharacter: Decodable {
    let observationId: String?; let startSeconds: Double?; let endSeconds: Double?; let startBar: Int?; let endBar: Int?
    let barCount: Int?
    let relativeEnergy: Double?; let energyRise: Double?
    let recurrenceStrength: Double?; let familySalience: Double?; let entryContrast: Double?; let exitContrast: Double?
    let buildMomentum: Double?; let boundaryNovelty: Double?
    let entryBoundary: DebugShadowBoundaryEvidence?; let exitBoundary: DebugShadowBoundaryEvidence?
    let preparationProfile: DebugPreparationProfile?; let arrivalProfile: DebugArrivalProfile?
    let entryStructuralDeparture: DebugStructuralDepartureProfile?; let exitStructuralDeparture: DebugStructuralDepartureProfile?
}
struct DebugPreparationProfile: Decodable {
    let energyTrajectory: Double?; let exitEnergyDirection: Double?; let exitOnsetDirection: Double?
    let exitSilenceDirection: Double?; let exitStructuralContext: Double?
}
struct DebugArrivalProfile: Decodable {
    let entryContrast: Double?; let boundaryNovelty: Double?; let energyDirection: Double?
    let onsetDirection: Double?; let silenceDirection: Double?; let originRelativeEnergy: Double?
    let destinationRelativeEnergy: Double?
}
struct DebugStructuralDepartureProfile: Decodable {
    let structuralContextChange: Double?; let membershipExitStrength: Double?; let repeatedSectionEnd: Double?
    let recurrenceChange: Double?; let structuralRoute: String?; let structuralEvidence: Double?; let structuralTargetBar: Int?
}
struct DebugShadowStructuralDepartureAspect: Decodable {
    let originExit: DebugStructuralDepartureProfile?; let destinationEntry: DebugStructuralDepartureProfile?
}
struct DebugShadowArrangementIdentityAspect: Decodable {
    let recurrenceStrength: Double?; let familySalience: Double?; let familyId: String?; let hasEarlierFamilyOccurrence: Bool?
}
struct DebugBoundaryTemporalContext: Decodable {
    let preBoundaryNormalizedRms: Double?; let postBoundaryNormalizedRms: Double?
    let lateOriginRelativeEnergy: Double?; let earlyDestinationRelativeEnergy: Double?
    let window: DebugBoundaryTemporalWindow?
}
struct DebugBoundaryTemporalWindow: Decodable { let bars: [DebugBoundaryTemporalBar]? }
struct DebugBoundaryTemporalBar: Decodable { let relativeBarOffset: Int?; let normalizedRms: Double?; let relativeEnergy: Double? }
struct DebugShadowEventEvidence: Decodable {
    let originObservationId: String?; let destinationObservationId: String?
    let boundarySeconds: Double?; let boundaryBar: Int?
    let preparationAspect: DebugPreparationProfile?; let arrivalAspect: DebugArrivalProfile?
    let structuralDepartureAspect: DebugShadowStructuralDepartureAspect?
    let arrangementIdentityAspect: DebugShadowArrangementIdentityAspect?
    let destinationIsTerminal: Bool?
    let hypotheses: [DebugShadowEventHypothesis]?
    let temporalContext: DebugBoundaryTemporalContext?
}
struct DebugShadowEventHypothesis: Decodable {
    let kind: String?; let anchorKind: String?; let startSeconds: Double?; let targetSeconds: Double?; let endSeconds: Double?
    let supportingEvidence: [String]?; let conflictingEvidence: [String]?
}
struct DebugShadowBoundaryEvidence: Decodable {
    let recurrenceChange: Double?; let structuralContextChange: Double?; let membershipExitStrength: Double?
    let repeatedSectionEnd: Double?; let structuralRoute: String?; let structuralEvidence: Double?; let structuralTargetBar: Int?
    let energyChange: Double?; let onsetChange: Double?; let silenceChange: Double?
    let energyDelta: Double?; let onsetDelta: Double?; let silenceDelta: Double?
}
struct DebugHandoffState: Decodable { let trackMatch: String?; let availability: String?; let richAnalysis: DebugRichAnalysis?; let shadowAnalysis: DebugShadowAnalysis?; let fallbackReason: String?; let effectiveSource: String?; let selectedSource: String? }
struct DebugShadowAnalysis: Decodable { let model: String?; let sectionCharacters: [DebugShadowSectionCharacter]?; let eventEvidence: [DebugShadowEventEvidence]? }
struct DebugForceReanalysisResponse: Decodable { let status: String?; let jobId: String?; let filePath: String? }
struct DebugRichAnalysis: Decodable {
    let model: String?
    let energyScale: String?
    let segmentCount: Int?
    let eventCount: Int?
    let segments: [DebugTrackStructureSegment]?
    let sections: [DebugSemanticSection]?
    let events: [DebugTrackStructureEvent]?
}
struct DebugTrackStructureSegment: Decodable {
    let index: Int?; let startSeconds: Double?; let endSeconds: Double?; let label: String?
    let level: String?; let energy: Double?; let confidence: Double?; let startBar: Int?; let endBar: Int?
}
struct DebugSemanticSection: Decodable {
    let index: Int?; let startSeconds: Double?; let endSeconds: Double?; let role: String?
    let occurrence: Int?; let familyId: String?; let energy: Double?; let confidence: Double?
    let startBar: Int?; let endBar: Int?; let sourcePhraseCount: Int?
}
struct DebugTrackStructureEvent: Decodable {
    let type: String?; let startSeconds: Double?; let targetSeconds: Double?; let endSeconds: Double?
    let startBar: Int?; let targetBar: Int?; let confidence: Double?
}
struct DebugBridgeDiagnostics: Decodable { let status: String?; let error: String?; let diagnostics: DebugBridgeDetails? }
struct DebugBridgeDetails: Decodable { let playlistWatcher: DebugPlaylistWatcher?; let analysisQueue: DebugQueue?; let activeTrack: DebugActiveTrack?; let nativePlugin: DebugNativePlugin?; let control: DebugBridgeControl?; let runningJob: DebugRunningJob?; let recentFailures: [DebugFailure]?; let prewarmTracks: [DebugPrewarmTrack]?; let staleRecoveryCount: Int? }
struct DebugRunningJob: Decodable {
    let filePath: String?; let priority: String?; let enqueuedAtUtc: String?; let startedAtUtc: String?
    let elapsedMilliseconds: Int?; let analysisVersion: String?; let phraseAnalysisVersion: String?
    let source: String?; let generation: Int?; let jobId: String?; let state: String?; let workerPid: Int?
}
struct DebugPrewarmTrack: Decodable { let filePath: String?; let deck: Int?; let status: String?; let generation: Int?; let jobId: String?; let lastFailure: DebugFailure? }
struct DebugPlaylistWatcher: Decodable { let enabled: Bool?; let playlistDirectory: String?; let playlistCount: Int?; let discoveredTrackCount: Int?; let cacheHitsThisSession: Int?; let lastReconcileUtc: String?; let lastError: String?; let currentTrackCount: Int?; let staleTrackCount: Int?; let needsAnalysisTrackCount: Int?; let failedKnownTrackCount: Int? }
struct DebugQueue: Decodable { let capacity: Int?; let queuedNormal: Int?; let queuedHigh: Int?; let running: Int?; let analyzing: Int?; let completedThisSession: Int?; let failedThisSession: Int?; let oldestQueuedMilliseconds: Int?; let failedRunner: Int?; let failedInvalidResult: Int?; let evictedNormalForHigh: Int?; let otherFailed: Int?; let uniqueFailedTracks: Int?; let uniqueFailureTrackingSaturated: Bool?; let cancelledThisSession: Int?; let timedOutThisSession: Int?; let deduplicatedThisSession: Int?; let terminalHistoryCount: Int?; let workerAlive: Bool?; let workerHealthy: Bool?; let lastFailureCategory: String?; let analysisTimeoutSeconds: Int? }
struct DebugNativePlugin: Decodable {
    let poller: DebugNativePoller?
    let selectors: DebugNativeSelectors?
    let candidates: [DebugNativeCandidate]?
    let selection: DebugNativeSelection?
    let ipc: DebugNativeIpc?
    let response: DebugNativeResponse?
    let recovery: DebugNativeRecovery?
}
struct DebugNativePoller: Decodable { let alive: Bool?; let pollCounter: Int?; let lastPollUnixMilliseconds: Int? }
struct DebugNativeSelectors: Decodable {
    let masterDeckQuerySucceeded: Bool?; let masterDeckRaw: Double?; let masterDeck: Int?; let masterDeckObservedUnixMilliseconds: Int?
    let pluginDeckQuerySucceeded: Bool?; let pluginDeckRaw: Double?; let pluginDeck: Int?
    let leftDeckQuerySucceeded: Bool?; let leftDeckRaw: Double?; let leftDeck: Int?
    let rightDeckQuerySucceeded: Bool?; let rightDeckRaw: Double?; let rightDeck: Int?
}
struct DebugNativeCandidate: Decodable {
    let deck: Int?; let sources: [String]?; let playQuerySucceeded: Bool?; let playing: Bool?
    let filePathQuerySucceeded: Bool?; let filePath: String?; let filePathExists: Bool?; let relevant: Bool?
}
struct DebugNativeSelection: Decodable {
    let previousSelectedDeck: Int?; let selectedDeck: Int?; let selectedFilePath: String?; let reason: String?; let noSelectionReason: String?; let authoritativeSelectionUnixMilliseconds: Int?
}
struct DebugNativeIpc: Decodable {
    let lastAction: String?; let lastDeck: Int?; let lastFilePath: String?; let lastSendSucceeded: Bool?; let lastError: String?; let lastSentUnixMilliseconds: Int?; let activateEmittedUnixMilliseconds: Int?
}
struct DebugNativeResponse: Decodable { let received: Bool?; let valid: Bool?; let success: Bool?; let accepted: Bool?; let status: String?; let errorCode: String?; let errorMessage: String?; let jobId: String? }
struct DebugNativeRecovery: Decodable { let bridgeHealth: String?; let resyncPending: Bool? }
struct DebugBridgeControl: Decodable {
    let type: String?; let requestId: String?; let protocolVersion: Int?; let deck: Int?; let filePath: String?
    let valid: Bool?; let validationError: String?; let accepted: Bool?; let cacheState: String?
    let requestedGeneration: Int?; let resultStatus: String?; let resultGeneration: Int?; let resultFilePath: String?
    let processingError: String?; let lastMutation: DebugActiveTrackMutation?
    let activateReceived: Int?; let deactivateReceived: Int?; let activateSucceeded: Int?; let activateFailed: Int?
    let receivedUtc: String?
}
struct DebugActiveTrackMutation: Decodable {
    let type: String?; let oldPath: String?; let oldStatus: String?; let oldGeneration: Int?
    let newPath: String?; let newStatus: String?; let newGeneration: Int?; let reason: String?; let timestampUtc: String?
}

struct DeveloperStructureBehaviorState: Decodable {
    let selectedSource: String
}

struct LiveUiState: Decodable {
    let source: String?
    let availability: String?
    let transportState: String?
    let activeDeckNumber: Int?
    let trackPath: String?
    let trackTitle: String?
    let trackArtist: String?
    let bpm: Double?
    let beatNumber: Int?
    let barNumber: Int?
    let fractionalBeat: Double?
    let positionMilliseconds: Int?
    let phrase: String?
    let nextPhrase: String?
    let barsToNext: Int?
    let structureStatus: String?
    let structureReason: String?
    let decks: [LiveDeckState]?
}

struct LiveDeckState: Decodable {
    let deckNumber: Int?
    let isLoaded: Bool?
    let isActive: Bool?
    let trackPath: String?
    let trackTitle: String?
    let trackArtist: String?
    let bpm: Double?
    let positionMilliseconds: Int?
    let beatNumber: Int?
    let barNumber: Int?
    let phrase: String?
    let nextPhrase: String?
    let barsToNext: Int?
    let structureStatus: String?
    let structureReason: String?
    let analysisStatus: String?
    let prewarmStatus: String?
    let generation: Int?
    let isMaster: Bool?
    let isPlaying: Bool?
}

struct RemoteAccessState: Decodable {
    let enabled: Bool
    let bindHost: String
    let port: Int
    let path: String
    let localUrl: String?
    let lanUrl: String?
    let usbUrl: String?
    let tailscaleUrl: String?
    let preferredUrl: String?
    let authRequired: Bool
    let pairingCode: String?
    let remoteProtocolVersion: Int?
}

struct DmxState: Decodable {
    let connected: Bool
    let port: String?
    let fps: Double
    let error: String?
    let lastSent: Double?
    let activeSlot: String
    let blackoutActive: Bool
    let manualSmoke: ManualSmokeState?
    let autoShow: AutoShowState
    let slotOrder: [String]
    let slots: [String: SlotState]
    let slotRanges: [String: SlotRange]
    let slotCapabilities: [String: SlotCapabilities]
    let slotPreviews: [String: SlotPreview]
    let renderedMotion: [String: RenderedMotionState]
    let venueSpace: VenueSpaceState?
    let venueTargetTest: VenueTargetTestAuthorityState?
    let movementLab: MovementLabState?
    let conflicts: [ChannelConflict]
    let values: [String: Int]
    let developerVirtualdjBeatPulsePreview: VirtualDjBeatPulsePreviewState?
    let rmePreviewDifferential: PreviewCompositionState?
    let productionShowSelector: ProductionShowSelectorState?
    let productionShowObservation: ProductionShowObservationState?
    let previewPulseTest: PreviewPulseTestState?

    private enum CodingKeys: String, CodingKey {
        case connected
        case port
        case fps
        case error
        case lastSent
        case activeSlot
        case blackoutActive
        case manualSmoke
        case autoShow
        case slotOrder
        case slots
        case slotRanges
        case slotCapabilities
        case slotPreviews
        case renderedMotion
        case venueSpace
        case venueTargetTest
        case movementLab
        case conflicts
        case values
        case developerVirtualdjBeatPulsePreview
        case rmePreviewDifferential
        case productionShowSelector
        case productionShowObservation
        case previewPulseTest
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        connected = try container.decode(Bool.self, forKey: .connected)
        port = try container.decodeIfPresent(String.self, forKey: .port)
        fps = try container.decode(Double.self, forKey: .fps)
        error = try container.decodeIfPresent(String.self, forKey: .error)
        lastSent = try container.decodeIfPresent(Double.self, forKey: .lastSent)
        activeSlot = try container.decode(String.self, forKey: .activeSlot)
        blackoutActive = try container.decode(Bool.self, forKey: .blackoutActive)
        manualSmoke = try container.decodeIfPresent(ManualSmokeState.self, forKey: .manualSmoke)
        autoShow = try container.decodeIfPresent(AutoShowState.self, forKey: .autoShow) ?? .disabled
        slotOrder = try container.decode([String].self, forKey: .slotOrder)
        slots = try container.decode([String: SlotState].self, forKey: .slots)
        slotRanges = try container.decode([String: SlotRange].self, forKey: .slotRanges)
        slotCapabilities = try container.decode([String: SlotCapabilities].self, forKey: .slotCapabilities)
        slotPreviews = try container.decodeIfPresent([String: SlotPreview].self, forKey: .slotPreviews) ?? [:]
        renderedMotion = try container.decodeIfPresent([String: RenderedMotionState].self, forKey: .renderedMotion) ?? [:]
        venueSpace = try container.decodeIfPresent(VenueSpaceState.self, forKey: .venueSpace)
        venueTargetTest = try container.decodeIfPresent(VenueTargetTestAuthorityState.self, forKey: .venueTargetTest)
        movementLab = try container.decodeIfPresent(MovementLabState.self, forKey: .movementLab)
        conflicts = try container.decode([ChannelConflict].self, forKey: .conflicts)
        values = try container.decode([String: Int].self, forKey: .values)
        developerVirtualdjBeatPulsePreview = try container.decodeIfPresent(
            VirtualDjBeatPulsePreviewState.self,
            forKey: .developerVirtualdjBeatPulsePreview
        )
        rmePreviewDifferential = try container.decodeIfPresent(
            PreviewCompositionState.self,
            forKey: .rmePreviewDifferential
        )
        productionShowSelector = try container.decodeIfPresent(
            ProductionShowSelectorState.self,
            forKey: .productionShowSelector
        )
        productionShowObservation = try container.decodeIfPresent(
            ProductionShowObservationState.self,
            forKey: .productionShowObservation
        )
        previewPulseTest = try container.decodeIfPresent(PreviewPulseTestState.self, forKey: .previewPulseTest)
    }
}

struct ManualSmokeState: Decodable, Equatable {
    let supported: Bool
    let reasonIfUnavailable: String?
    let active: Bool
    let outputPercent: Int
    let resolvedDmxValue: Int
    let fixtureSlotIds: [String]
}

struct VenuePointState: Codable {
    let x: Double
    let y: Double
    let z: Double?

    init(x: Double, y: Double, z: Double? = nil) {
        self.x = x
        self.y = y
        self.z = z
    }
}

struct VenuePhysicalPointState: Codable {
    let x: Double
    let y: Double
    let z: Double
}

struct VenueVectorState: Codable {
    let x: Double
    let y: Double
    let z: Double
}

struct VenueTargetState: Decodable, Identifiable {
    let id: String
    let zone: String?
    let position: String?
    let point: VenuePointState
    let physicalPointM: VenuePhysicalPointState?
    let missingGeometry: [String]?
}

struct VenueGeometryState: Decodable {
    let venueWidthM: Double?
    let venueForwardDepthM: Double?
    let venueRearDepthM: Double?
    let audienceTargetHeightM: Double?
    let ceilingHeightM: Double?
    let status: String
    let missingGeometry: [String]
}

struct VenueTargetVerticalLayerState: Decodable, Identifiable {
    let id: String
    let available: Bool
    let reason: String?
}

struct VenueResolverState: Decodable {
    let status: String
    let missingCalibration: [String]
}

struct VenueFixtureCapabilitiesState: Decodable {
    let pan: Bool
    let panFine: Bool
    let tilt: Bool
    let tiltFine: Bool
    let panRangeDegrees: Double?
    let tiltRangeDegrees: Double?
    let physicalTiltMinDeg: Double?
    let physicalTiltCenterDeg: Double?
    let physicalTiltMaxDeg: Double?
    let physicalTiltLimitsSource: String?
    let panZeroReference: String
    let tiltZeroReference: String
}

struct VenuePredictedOutputState: Decodable {
    let pan: Int
    let tilt: Int
    let panFine: Int?
    let tiltFine: Int?
}

struct VenueTargetResolutionState: Decodable {
    let status: String
    let reason: String?
    let panDegrees: Double?
    let tiltDegrees: Double?
    let pan: Int?
    let tilt: Int?
    let fixtureXyzM: VenuePhysicalPointState?
    let targetXyzM: VenuePhysicalPointState?
    let targetVectorM: VenueVectorState?
    let horizontalDistanceM: Double?
    let verticalDeltaM: Double?
    let directDistanceM: Double?
    let predictedOutput: VenuePredictedOutputState?
    let mappingSource: String?
    let desiredWorldAzimuthDegrees: Double?
    let desiredWorldElevationDegrees: Double?
    let chosenPanRaw: Int?
    let chosenTiltRaw: Int?
    let predictedPhysicalAzimuthDegrees: Double?
    let predictedPhysicalElevationDegrees: Double?
}

struct VenueTargetFixtureResultState: Decodable, Identifiable {
    var id: String { slotID }
    let slotID: String
    let label: String
    let classification: String
    let resolverStatus: String
    let resolution: VenueTargetResolutionState

    private enum CodingKeys: String, CodingKey {
        case slotID = "slotId"
        case label
        case classification
        case resolverStatus
        case resolution
    }
}

struct VenueTargetResultSetState: Decodable {
    let target: String
    let verticalLayer: String?
    let targetPoint: VenuePointState
    let candidateCount: Int
    let targetedCount: Int
    let skippedCount: Int
    let rendererHealthy: Bool
    let dmxConnected: Bool
    let physicalReady: Bool
    let results: [VenueTargetFixtureResultState]
}

struct VenueTargetTestAuthorityState: Decodable {
    let status: String
    let active: Bool
    let scope: String
    let mode: String?
    let axis: String?
    let sampleIndex: Int?
    let sampleRaw: Int?
    let selectedFixtureID: String?
    let target: String?
    let verticalLayer: String?
    let leaseRemainingSeconds: Double?
    let participatingFixtureIDs: [String]?
    let resultSet: VenueTargetResultSetState?
    let renderedOutputs: [String: VenuePredictedOutputState]?
    let theoreticalOutput: VenuePredictedOutputState?
    let selectedResolution: VenueTargetResolutionState?

    private enum CodingKeys: String, CodingKey {
        case status
        case active
        case scope
        case mode
        case axis
        case sampleIndex
        case sampleRaw
        case selectedFixtureID = "selectedFixtureId"
        case target
        case verticalLayer
        case leaseRemainingSeconds
        case participatingFixtureIDs = "participatingFixtureIds"
        case resultSet
        case renderedOutputs
        case theoreticalOutput
        case selectedResolution
    }
}

struct MovementLabState: Decodable {
    let status: String
    let active: Bool
    let engine: String
    let effectID: String?
    let section: String?
    let variation: Int?
    let bpm: Double?
    let route: String?
    let dmxConnected: Bool?

    private enum CodingKeys: String, CodingKey {
        case status, active, engine, section, variation, bpm, route
        case effectID = "effectId"
        case dmxConnected
    }
}

struct KinematicAxisModelState: Decodable {
    let slopeRawPerDegree: Double
    let interceptRaw: Double
    let maximumAbsoluteResidualRaw: Double
    let rmsResidualRaw: Double
    let inputSpreadDegrees: Double
    let rawMax: Int?
    let branchReferenceRaw: Int?
}

struct KinematicModelState: Decodable {
    let status: String
    let reason: String?
    let model: String?
    let pan: KinematicAxisModelState?
    let tilt: KinematicAxisModelState?
}

struct KinematicAnchorState: Decodable {
    let target: String
    let desiredPanDegrees: Double
    let desiredTiltDegrees: Double
    let actualPanRaw: Int
    let actualTiltRaw: Int
    let actualOutput: VenuePredictedOutputState
}

struct KinematicValidationState: Decodable {
    let target: String
    let result: String?
}

struct KinematicCalibrationState: Decodable {
    let status: String
    let reason: String?
    let anchorCount: Int
    let requiredAnchorCount: Int
    let requiredAnchors: [String]?
    let missingAnchors: [String]?
    let anchors: [String: KinematicAnchorState]?
    let model: KinematicModelState?
    let validation: KinematicValidationState?
}

struct AxisMappingV2SampleState: Decodable {
    let index: Int
    let raw: Int
    let coarse: Int?
    let fine: Int?
    let normalizedFraction: Double?
    let measuredAzimuthDegrees: Double?
    let measuredElevationDegrees: Double?
    let measuredTiltPlaneDegrees: Double?
}

struct AxisMappingV2PointState: Decodable {
    let raw: Int
    let physicalDegrees: Double
    let index: Int
}

struct AxisMappingV2AxisModelState: Decodable {
    let status: String?
    let direction: String?
    let coverageDegrees: Double?
    let points: [AxisMappingV2PointState]?
}

struct AxisMappingV2ModelState: Decodable {
    let status: String
    let reason: String?
    let model: String?
    let pan: AxisMappingV2AxisModelState?
    let tilt: AxisMappingV2AxisModelState?
}

struct AxisMappingV2ValidationState: Decodable {
    let target: String
    let result: String
    let desiredWorldAzimuthDegrees: Double?
    let desiredWorldElevationDegrees: Double?
    let chosenPanRaw: Int?
    let chosenTiltRaw: Int?
}

struct AxisMappingV2State: Decodable {
    let status: String
    let active: Bool
    let movementMappingAuthority: String?
    let panSampleCount: Int
    let panRequiredCount: Int
    let tiltSampleCount: Int
    let tiltRequiredCount: Int
    let panSamplePositions: [Int]?
    let tiltSamplePositions: [Int]?
    let panSamples: [String: AxisMappingV2SampleState]?
    let tiltSamples: [String: AxisMappingV2SampleState]?
    let legacyTiltSamples: [String: AxisMappingV2SampleState]?
    let legacyTiltDirectionReviewRequired: Bool?
    let model: AxisMappingV2ModelState?
    let validations: [String: AxisMappingV2ValidationState]?
    let requiredValidationTargets: [String]?
    let validationStale: Bool?
    let legacyPhysicalAimStatus: String?
    let tiltSweepReferencePanRaw: Int?
    let panSweepReferenceTiltPlaneDegrees: Double?
    let legacyPanSweepReferenceElevationDegrees: Double?
    let panSweepReferenceTiltRaw: Int?
    let panSamplesReviewRequired: Bool?
    let workflowPhase: String?
    let workflowSampleIndex: Int?
    let workflowSavedCount: Int?
    let workflowMoveStatus: String?
    let workflowMoveError: String?
    let panStartAllowed: Bool?
    let tiltStartAllowed: Bool?
    let panSweepTiltPlaneOptions: [Double]?
    let defaultPanSweepTiltPlaneDegrees: Double?
}

struct VenueTargetTestActionResponse: Decodable {
    let accepted: Bool
    let status: String
    let reason: String?
    let authority: VenueTargetTestAuthorityState?
    let resultSet: VenueTargetResultSetState?
}

struct VenueFixtureCalibrationState: Decodable, Identifiable {
    var id: String { slotID }
    let slotID: String
    let label: String
    let status: String
    let missingCalibration: [String]
    let positionM: VenuePhysicalPointState?
    let positionSource: String?
    let position: VenuePointState?
    let mountingHeightM: Double?
    let physicalForward: VenueVectorState?
    let physicalUp: VenueVectorState?
    let derivedRight: VenueVectorState?
    let basisReason: String?
    let panCorrectionDegrees: Double
    let tiltCorrectionDegrees: Double
    let capabilities: VenueFixtureCapabilitiesState
    let audienceCenterTest: VenueTargetResolutionState
    let kinematicCalibration: KinematicCalibrationState?
    let axisMappingV2: AxisMappingV2State?

    private enum CodingKeys: String, CodingKey {
        case slotID = "slotId"
        case label
        case status
        case missingCalibration
        case positionM
        case positionSource
        case position
        case mountingHeightM
        case physicalForward
        case physicalUp
        case derivedRight
        case basisReason
        case panCorrectionDegrees
        case tiltCorrectionDegrees
        case capabilities
        case audienceCenterTest
        case kinematicCalibration
        case axisMappingV2
    }
}

struct VenueSpaceState: Decodable {
    let version: Int
    let viewpoint: String
    let origin: VenuePointState
    let venueGeometry: VenueGeometryState?
    let verticalLayers: [VenueTargetVerticalLayerState]?
    let defaultVerticalLayer: String?
    let targets: [VenueTargetState]
    let resolver: VenueResolverState
    let fixtures: [VenueFixtureCalibrationState]?
    let audienceEffectMigration: String
}

struct ProductionShowSelectorState: Decodable {
    let productionMode: String?
    let productionSource: String?
    let fallbackActive: Bool?
    let fallbackReason: String?
    let dynamicComposerEligible: Bool?
    let manualOverrideActive: Bool?
    let blackoutActive: Bool?
}

struct ProductionShowObservationState: Decodable {
    let dynamicFrames: Int?
    let baselineFallbackFrames: Int?
    let candidateFaults: Int?
    let sourceSwitches: Int?
}

struct PreviewPulseTestState: Decodable { let mode: String; let active: Bool; let pattern: String? }

struct PreviewCompositionEvent: Decodable {
    let type: String?
}

struct PreviewFixtureGroupIntent: Decodable {
    let activity: Double?
    let intensity: Double?
    let movementAmount: Double?
    let movementSpeed: Double?
    let colorChangeRate: Double?
    let paletteRole: String?
    let pulseAmount: Double?
    let accentStrength: Double?
}

struct PreviewContinuousMusicalState: Decodable {
    let sectionProgress: Double?
    let relativeEnergy: Double?
    let energyTrajectory: Double?
    let recurrenceStrength: Double?
    let familySalience: Double?
}

struct PreviewMusicalEventEnvelope: Decodable {
    let eventType: String?
    let phase: String?
    let progress: Double?
    let beatsSinceEvent: Double?
    let totalBeats: Double?
    let timingSource: String?
    let active: Bool?
}

/// Preview primitives deliberately evolve independently from the native UI.
/// An unknown nested debug value must never make the complete live state fail.
enum PreviewPrimitiveValue: Decodable {
    case string(String)
    case number(Double)
    case boolean(Bool)
    case object([String: PreviewPrimitiveValue])
    case array([PreviewPrimitiveValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode(Bool.self) { self = .boolean(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode([String: PreviewPrimitiveValue].self) { self = .object(value) }
        else if let value = try? container.decode([PreviewPrimitiveValue].self) { self = .array(value) }
        else { self = .null }
    }

    var displayText: String? {
        switch self {
        case .string(let value): return value
        case .number(let value): return String(format: "%.3g", value)
        case .boolean(let value): return value ? "true" : "false"
        case .object(let values): return "parameters (\(values.count))"
        case .array(let values): return "values (\(values.count))"
        case .null: return nil
        }
    }
}

struct PreviewCompositionState: Decodable {
    let mode: String?
    let productionSource: String?
    let previewSource: String?
    let dynamicComposerActive: Bool?
    let fallbackToBaseline: Bool?
    let dynamicCompositionApplied: Bool?
    let baselineSceneReused: Bool?
    let baselineSceneComponentsReused: [String]?
    let contextReason: String?
    let continuousStateReason: String?
    let continuousMusicalState: PreviewContinuousMusicalState?
    let eventEnvelopeReason: String?
    let eventEnvelope: PreviewMusicalEventEnvelope?
    let event: PreviewCompositionEvent?
    let interpretation: String?
    let progress: Double?
    let previewCue: String?
    let fixtureGroupIntents: [String: PreviewFixtureGroupIntent]?
    let selectedPrimitives: [String: [String: PreviewPrimitiveValue]]?
    let compositionSignature: [String: PreviewPrimitiveValue]?
    let variation: [String: PreviewPrimitiveValue]?
    let changedDimensions: [String]?
    let physicalOutputSource: String?
}

struct SimulatorTrack: Decodable, Identifiable {
    let path: String; let title: String; let durationSeconds: Double; let bpm: Double?; let analysisVersion: String?
    var id: String { path }
}
struct SimulatorTracksResponse: Decodable { let tracks: [SimulatorTrack] }
struct SimulatorTrackIdentity: Decodable { let path: String; let analysisIdentity: String?; let availability: String? }
struct SimulatorTransportState: Decodable { let playing: Bool; let positionMilliseconds: Int; let durationMilliseconds: Int; let bpm: Double?; let beat: Int?; let bar: Int?; let generation: Int }
struct SimulatorCue: Decodable, Identifiable { let role: String?; let positionMilliseconds: Int?; let planned: Bool?; var id: String { role ?? UUID().uuidString } }
struct SimulatorState: Decodable {
    let mode: String; let physicalOutput: String; let track: SimulatorTrackIdentity?; let transport: SimulatorTransportState
    let continuousMusicalState: PreviewContinuousMusicalState?; let rme: PreviewCompositionEvent?; let eventEnvelope: PreviewMusicalEventEnvelope?
    let composition: PreviewCompositionState?; let smartCues: [SimulatorCue]
    let timeline: SimulatorTimeline; let simulationSlotPreviews: [String: SlotPreview]
}
struct SimulatorTimeline: Decodable { let durationSeconds: Double; let playheadSeconds: Double; let sections: [SimulatorSection]; let events: [SimulatorEvent]; let smartCues: [SimulatorTimelineCue]; let envelope: PreviewMusicalEventEnvelope? }
struct SimulatorSection: Decodable, Identifiable { let id: String?; let startSeconds: Double; let endSeconds: Double; let relativeEnergy: Double?; let recurrenceStrength: Double?; let familySalience: Double?; var stableID: String { id ?? "\(startSeconds)-\(endSeconds)" } }
struct SimulatorEvent: Decodable, Identifiable { let type: String?; let startSeconds: Double; let endSeconds: Double?; let temporalKind: String?; var id: String { "\(type ?? "event")-\(startSeconds)" } }
struct SimulatorTimelineCue: Decodable, Identifiable { let role: String?; let startSeconds: Double; let planned: Bool; var id: String { "\(role ?? "cue")-\(startSeconds)" } }

struct VirtualDjBeatPulsePreviewState: Decodable {
    let enabled: Bool
    let pending: Bool
    let lastReason: String
    let mode: String
    let physicalDmxOutput: Bool
}

struct SlotState: Decodable {
    let enabled: Bool
    let color: SlotColor
    let dimmer: Int
    let strobe: Int
    let program: Int
    let speed: Int
    let extraValues: [String: Int]?
    let pan: Int
    let tilt: Int
    let panTiltSpeed: Int
    let syncEnabled: Bool
    let beatPulseEnabled: Bool
    let beatDepth: Int
    let beatDecayMs: Int
    let colorSource: String
    let oscStrobeEnabled: Bool
    let useFinePanTilt: Bool?
    let panInvert: Bool
    let tiltInvert: Bool
    let panOffsetDeg: Int
    let tiltOffsetDeg: Int
    let panSpanPercent: Int
    let tiltSpanPercent: Int
    let panLeftValue: Int?
    let panRightValue: Int?
    let tiltBackValue: Int?
    let tiltFrontValue: Int?
    let poseCenter: SlotPose?
    let poseAudienceLeft: SlotPose?
    let poseAudienceCenter: SlotPose?
    let poseAudienceRight: SlotPose?
    let poseCeilingCenter: SlotPose?
    let label: String
    let fixture: String
    let mode: String
    let address: Int
    let group: String
}

struct SlotColor: Decodable {
    let red: Int
    let green: Int
    let blue: Int
    let white: Int
}

struct SlotPose: Codable {
    let pan: Int
    let tilt: Int
}

struct SlotWorldPosition: Codable {
    var x: Double
    var y: Double
    var z: Double
    var yawDegrees: Double
    var pitchDegrees: Double
    var rollDegrees: Double
    var panFlip: Bool
    var tiltFlip: Bool

    init(
        x: Double,
        y: Double,
        z: Double,
        yawDegrees: Double = 0,
        pitchDegrees: Double = 0,
        rollDegrees: Double = 0,
        panFlip: Bool = false,
        tiltFlip: Bool = false
    ) {
        self.x = x
        self.y = y
        self.z = z
        self.yawDegrees = yawDegrees
        self.pitchDegrees = pitchDegrees
        self.rollDegrees = rollDegrees
        self.panFlip = panFlip
        self.tiltFlip = tiltFlip
    }

    private enum CodingKeys: String, CodingKey {
        case x
        case y
        case z
        case yawDegrees
        case pitchDegrees
        case rollDegrees
        case panFlip
        case tiltFlip
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        x = try container.decode(Double.self, forKey: .x)
        y = try container.decode(Double.self, forKey: .y)
        z = try container.decode(Double.self, forKey: .z)
        yawDegrees = try container.decodeIfPresent(Double.self, forKey: .yawDegrees) ?? 0
        pitchDegrees = try container.decodeIfPresent(Double.self, forKey: .pitchDegrees) ?? 0
        rollDegrees = try container.decodeIfPresent(Double.self, forKey: .rollDegrees) ?? 0
        panFlip = try container.decodeIfPresent(Bool.self, forKey: .panFlip) ?? false
        tiltFlip = try container.decodeIfPresent(Bool.self, forKey: .tiltFlip) ?? false
    }
}

struct SlotRange: Decodable {
    let slotId: String
    let label: String
    let enabled: Bool
    let fixtureLabel: String
    let mode: String
    let address: Int
    let lastChannel: Int
}

struct ChannelConflict: Decodable {
    let channel: Int
    let first: String
    let second: String
}

struct SlotPreview: Decodable {
    let enabled: Bool
    let fixtureKind: String?
    let red: Int
    let green: Int
    let blue: Int
    let white: Int
    let resolvedRed: Int?
    let resolvedGreen: Int?
    let resolvedBlue: Int?
    let resolvedWhite: Int?
    let effectiveIntensity: Double?
    let spotRed: Int?
    let spotGreen: Int?
    let spotBlue: Int?
    let spotWhite: Int?
    let spotBrightness: Int?
    let spotColorIndex: Int?
    let spotColorLabel: String?
    let spotColorToken: String?
    let spotColorCycle: Bool?
    let spotColorCycleRate: Double?
    let spotColorCount: Int?
    let spotPatternIndex: Int?
    let spotPatternLabel: String?
    let spotPatternId: String?
    let spotPatternOpen: Bool?
    let spotPatternCycle: Bool?
    let spotPatternCycleRate: Double?
    let spotPatternCount: Int?
    let spotPatternRotationDegrees: Double?
    let spotPatternSpinDps: Double?
    let beeEffectMode: String?
    let beeSpread: Double?
    let beeBackgroundLevel: Double?
    let beeSoftness: Double?
    let beeShapeTransition: Double?
    let brightness: Int
    let strobe: Int
    let strobeActive: Bool
    let strobeExternal: Bool
    let pan: Int
    let tilt: Int
    let panTiltSpeed: Int
    let targetPan: Int?
    let targetTilt: Int?
    let panRange: Double?
    let tiltRange: Double?
    let panDegrees: Double?
    let tiltDegrees: Double?
    let targetPanDegrees: Double?
    let targetTiltDegrees: Double?
    let logicalPanDegrees: Double?
    let logicalTiltDegrees: Double?
    let logicalTargetPanDegrees: Double?
    let logicalTargetTiltDegrees: Double?
    let panSpeedDps: Double?
    let tiltSpeedDps: Double?
    let motionActive: Bool
}

struct StageBeamPose {
    let panDegrees: Double
    let tiltDegrees: Double
}

private func defaultsKey(_ suffix: String) -> String {
    "\(beatBeamDefaultsPrefix).\(suffix)"
}

private let frontProjectionMirrorDefaultsKey = defaultsKey("frontProjectionMirrored")
private let topProjectionRotationDefaultsKey = defaultsKey("topProjectionRotationQuarterTurns")
private let mapProjectionShow3DDefaultsKey = defaultsKey("mapProjectionShow3D")
private let mapProjection2DZoomDefaultsKey = defaultsKey("mapProjection2DZoom")
private let mapProjectionTopCenterXDefaultsKey = defaultsKey("mapProjectionTopCenterX")
private let mapProjectionTopCenterYDefaultsKey = defaultsKey("mapProjectionTopCenterY")
private let mapProjectionFrontCenterXDefaultsKey = defaultsKey("mapProjectionFrontCenterX")
private let mapProjectionFrontCenterZDefaultsKey = defaultsKey("mapProjectionFrontCenterZ")
private let mapProjectionBackCenterXDefaultsKey = defaultsKey("mapProjectionBackCenterX")
private let mapProjectionBackCenterZDefaultsKey = defaultsKey("mapProjectionBackCenterZ")
private let mapProjectionSideCenterYDefaultsKey = defaultsKey("mapProjectionSideCenterY")
private let mapProjectionSideCenterZDefaultsKey = defaultsKey("mapProjectionSideCenterZ")
private let mapFixtureSnapEnabledDefaultsKey = defaultsKey("fixtureSnapEnabled")

private func normalizedQuarterTurns(_ value: Int) -> Int {
    ((value % 4) + 4) % 4
}

private func clampedProjection2DZoom(_ value: Double) -> Double {
    min(max(value, 0.75), 4.00)
}

/// Render identity for the metric 2D world. The revision is changed only by
/// view/camera mutations; it is deliberately independent from all venue,
/// fixture, calibration and DMX state.
struct MetricStageMapViewportRenderKey: Hashable {
    let zoom: Double
    let cameraRevision: Int
}

private func projection2DZoomValue() -> Double {
    let stored = UserDefaults.standard.double(forKey: mapProjection2DZoomDefaultsKey)
    if stored == 0 {
        return 1.0
    }
    return clampedProjection2DZoom(stored)
}

/// This is deliberately a view-only transform. Its multiplier is applied once,
/// after the unzoomed metric fit scale has been calculated, so it can never be
/// cancelled by a second fit-to-viewport pass.
private func projectionViewportTransform(_ point: CGPoint, zoom: Double = projection2DZoomValue()) -> CGPoint {
    let safeZoom = clampedProjection2DZoom(zoom)
    return CGPoint(
        x: 0.5 + (point.x - 0.5) * safeZoom,
        y: 0.5 + (point.y - 0.5) * safeZoom
    )
}

private func projectionViewportInverse(_ point: CGPoint, zoom: Double = projection2DZoomValue()) -> CGPoint {
    let safeZoom = max(0.0001, clampedProjection2DZoom(zoom))
    return CGPoint(
        x: 0.5 + (point.x - 0.5) / safeZoom,
        y: 0.5 + (point.y - 0.5) / safeZoom
    )
}

private func rotatedTopProjectionPoint(_ point: CGPoint, quarterTurns: Int) -> CGPoint {
    switch normalizedQuarterTurns(quarterTurns) {
    case 1:
        return CGPoint(x: 1.0 - point.y, y: point.x)
    case 2:
        return CGPoint(x: 1.0 - point.x, y: 1.0 - point.y)
    case 3:
        return CGPoint(x: point.y, y: 1.0 - point.x)
    default:
        return point
    }
}

private func unrotatedTopProjectionPoint(_ point: CGPoint, quarterTurns: Int) -> CGPoint {
    switch normalizedQuarterTurns(quarterTurns) {
    case 1:
        return CGPoint(x: point.y, y: 1.0 - point.x)
    case 2:
        return CGPoint(x: 1.0 - point.x, y: 1.0 - point.y)
    case 3:
        return CGPoint(x: 1.0 - point.y, y: point.x)
    default:
        return point
    }
}

/// Metric orthographic viewport. `screenHorizontal` and `screenDown` are in
/// centimetres solely for the legacy local cache; both axes share one physical
/// pixels-per-metre scale before zoom is applied.
private func metricProjectionPoint(
    screenHorizontal: Double,
    horizontalBounds: ClosedRange<Double>,
    screenDown: Double,
    verticalBounds: ClosedRange<Double>,
    cameraCenter: (horizontal: Double, down: Double)? = nil,
    zoom: Double = projection2DZoomValue()
) -> CGPoint {
    let aspect = Double(stageMapAspectRatio)
    let horizontalSpan = max(0.0001, horizontalBounds.upperBound - horizontalBounds.lowerBound)
    let verticalSpan = max(0.0001, verticalBounds.upperBound - verticalBounds.lowerBound)
    let unitsPerCanvasHeight = min(aspect / horizontalSpan, 1.0 / verticalSpan)
    // Base scale is derived solely from viewport aspect and the unzoomed world
    // bounds. `zoom` is applied only by projectionViewportTransform below.
    let horizontalCenter = cameraCenter?.horizontal ?? (horizontalBounds.lowerBound + horizontalBounds.upperBound) * 0.5
    let verticalCenter = cameraCenter?.down ?? (verticalBounds.lowerBound + verticalBounds.upperBound) * 0.5
    let raw = CGPoint(
        x: 0.5 + (screenHorizontal - horizontalCenter) * unitsPerCanvasHeight / aspect,
        y: 0.5 + (screenDown - verticalCenter) * unitsPerCanvasHeight
    )
    return projectionViewportTransform(raw, zoom: zoom)
}

private func metricProjectionCoordinates(
    _ point: CGPoint,
    horizontalBounds: ClosedRange<Double>,
    verticalBounds: ClosedRange<Double>,
    cameraCenter: (horizontal: Double, down: Double)? = nil,
    zoom: Double = projection2DZoomValue()
) -> (horizontal: Double, down: Double) {
    let raw = projectionViewportInverse(point, zoom: zoom)
    let aspect = Double(stageMapAspectRatio)
    let horizontalSpan = max(0.0001, horizontalBounds.upperBound - horizontalBounds.lowerBound)
    let verticalSpan = max(0.0001, verticalBounds.upperBound - verticalBounds.lowerBound)
    let unitsPerCanvasHeight = min(aspect / horizontalSpan, 1.0 / verticalSpan)
    let horizontalCenter = cameraCenter?.horizontal ?? (horizontalBounds.lowerBound + horizontalBounds.upperBound) * 0.5
    let verticalCenter = cameraCenter?.down ?? (verticalBounds.lowerBound + verticalBounds.upperBound) * 0.5
    return (
        horizontalCenter + (raw.x - 0.5) * aspect / unitsPerCanvasHeight,
        verticalCenter + (raw.y - 0.5) / unitsPerCanvasHeight
    )
}

private func metricWorldProjectedPoint(
    _ world: SlotWorldPosition,
    projection: StageProjection,
    frontMirrored: Bool,
    topQuarterTurns: Int,
    viewportCenter: SlotWorldPosition? = nil
) -> CGPoint {
    let center = projectionCameraScreenCenter(
        projection: projection,
        worldCenter: viewportCenter ?? projectionViewportCenter(for: projection),
        frontMirrored: frontMirrored,
        topQuarterTurns: topQuarterTurns
    )
    switch projection {
    case .top:
        switch normalizedQuarterTurns(topQuarterTurns) {
        case 1:
            return metricProjectionPoint(screenHorizontal: -world.y, horizontalBounds: -StageWorld.maxY ... -StageWorld.minY, screenDown: -world.x, verticalBounds: -StageWorld.maxX ... -StageWorld.minX, cameraCenter: center)
        case 2:
            return metricProjectionPoint(screenHorizontal: world.x, horizontalBounds: StageWorld.minX ... StageWorld.maxX, screenDown: -world.y, verticalBounds: -StageWorld.maxY ... -StageWorld.minY, cameraCenter: center)
        case 3:
            return metricProjectionPoint(screenHorizontal: world.y, horizontalBounds: StageWorld.minY ... StageWorld.maxY, screenDown: world.x, verticalBounds: StageWorld.minX ... StageWorld.maxX, cameraCenter: center)
        default:
            return metricProjectionPoint(screenHorizontal: -world.x, horizontalBounds: -StageWorld.maxX ... -StageWorld.minX, screenDown: world.y, verticalBounds: StageWorld.minY ... StageWorld.maxY, cameraCenter: center)
        }
    case .front:
        let horizontal = frontMirrored ? -world.x : world.x
        let bounds = frontMirrored ? -StageWorld.maxX ... -StageWorld.minX : StageWorld.minX ... StageWorld.maxX
        return metricProjectionPoint(screenHorizontal: horizontal, horizontalBounds: bounds, screenDown: -world.z, verticalBounds: -StageWorld.maxZ ... -StageWorld.minZ, cameraCenter: center)
    case .back:
        return metricProjectionPoint(screenHorizontal: -world.x, horizontalBounds: -StageWorld.maxX ... -StageWorld.minX, screenDown: -world.z, verticalBounds: -StageWorld.maxZ ... -StageWorld.minZ, cameraCenter: center)
    case .side:
        return metricProjectionPoint(screenHorizontal: world.y, horizontalBounds: StageWorld.minY ... StageWorld.maxY, screenDown: -world.z, verticalBounds: -StageWorld.maxZ ... -StageWorld.minZ, cameraCenter: center)
    }
}

enum StageProjection: String, CaseIterable, Identifiable {
    case top
    case front
    case back
    case side

    var id: String { rawValue }

    var title: String {
        switch self {
        case .top:
            return "Top View"
        case .front:
            return "Front View"
        case .back:
            return "Back View"
        case .side:
            return "Side View"
        }
    }

    var subtitle: String {
        switch self {
        case .top:
            return "Rig layout and horizontal spread"
        case .front:
            return "Tilt, height and throw"
        case .back:
            return "Rear view of tilt, height and throw"
        case .side:
            return "Depth and vertical throw"
        }
    }
}

/// Persistent camera centers are metres-in-cache (centimetres) and are strictly
/// view state. They never participate in venue/calibration payloads.
// The stage map can render many world-space elements for one pointer update.
// Keep its view-only camera in memory so those render paths never repeatedly
// query UserDefaults. Persistence is explicitly performed at the end of pan.
private var inMemoryProjectionViewportCenters: [StageProjection: SlotWorldPosition] = [:]

private func projectionViewportCenter(for projection: StageProjection) -> SlotWorldPosition {
    if let cached = inMemoryProjectionViewportCenters[projection] {
        return cached
    }
    let defaults = UserDefaults.standard
    func stored(_ key: String, fallback: Double) -> Double {
        (defaults.object(forKey: key) as? Double) ?? fallback
    }
    let center: SlotWorldPosition
    switch projection {
    case .top:
        center = SlotWorldPosition(
            x: stored(mapProjectionTopCenterXDefaultsKey, fallback: 0),
            y: stored(mapProjectionTopCenterYDefaultsKey, fallback: (StageWorld.minY + StageWorld.maxY) * 0.5),
            z: 0
        )
    case .front:
        center = SlotWorldPosition(
            x: stored(mapProjectionFrontCenterXDefaultsKey, fallback: 0),
            y: 0,
            z: stored(mapProjectionFrontCenterZDefaultsKey, fallback: (StageWorld.minZ + StageWorld.maxZ) * 0.5)
        )
    case .back:
        center = SlotWorldPosition(
            x: stored(mapProjectionBackCenterXDefaultsKey, fallback: 0),
            y: 0,
            z: stored(mapProjectionBackCenterZDefaultsKey, fallback: (StageWorld.minZ + StageWorld.maxZ) * 0.5)
        )
    case .side:
        center = SlotWorldPosition(
            x: 0,
            y: stored(mapProjectionSideCenterYDefaultsKey, fallback: (StageWorld.minY + StageWorld.maxY) * 0.5),
            z: stored(mapProjectionSideCenterZDefaultsKey, fallback: (StageWorld.minZ + StageWorld.maxZ) * 0.5)
        )
    }
    inMemoryProjectionViewportCenters[projection] = center
    return center
}

private func saveProjectionViewportCenter(_ center: SlotWorldPosition, for projection: StageProjection) {
    inMemoryProjectionViewportCenters[projection] = center
    let defaults = UserDefaults.standard
    switch projection {
    case .top:
        defaults.set(center.x, forKey: mapProjectionTopCenterXDefaultsKey)
        defaults.set(center.y, forKey: mapProjectionTopCenterYDefaultsKey)
    case .front:
        defaults.set(center.x, forKey: mapProjectionFrontCenterXDefaultsKey)
        defaults.set(center.z, forKey: mapProjectionFrontCenterZDefaultsKey)
    case .back:
        defaults.set(center.x, forKey: mapProjectionBackCenterXDefaultsKey)
        defaults.set(center.z, forKey: mapProjectionBackCenterZDefaultsKey)
    case .side:
        defaults.set(center.y, forKey: mapProjectionSideCenterYDefaultsKey)
        defaults.set(center.z, forKey: mapProjectionSideCenterZDefaultsKey)
    }
}

private func resetProjectionViewportCenters() {
    inMemoryProjectionViewportCenters.removeAll()
    for projection in StageProjection.allCases {
        let defaults = UserDefaults.standard
        switch projection {
        case .top:
            defaults.removeObject(forKey: mapProjectionTopCenterXDefaultsKey)
            defaults.removeObject(forKey: mapProjectionTopCenterYDefaultsKey)
        case .front:
            defaults.removeObject(forKey: mapProjectionFrontCenterXDefaultsKey)
            defaults.removeObject(forKey: mapProjectionFrontCenterZDefaultsKey)
        case .back:
            defaults.removeObject(forKey: mapProjectionBackCenterXDefaultsKey)
            defaults.removeObject(forKey: mapProjectionBackCenterZDefaultsKey)
        case .side:
            defaults.removeObject(forKey: mapProjectionSideCenterYDefaultsKey)
            defaults.removeObject(forKey: mapProjectionSideCenterZDefaultsKey)
        }
    }
}

private func projectionCameraScreenCenter(
    projection: StageProjection,
    worldCenter: SlotWorldPosition,
    frontMirrored: Bool,
    topQuarterTurns: Int
) -> (horizontal: Double, down: Double) {
    switch projection {
    case .top:
        switch normalizedQuarterTurns(topQuarterTurns) {
        case 1: return (-worldCenter.y, -worldCenter.x)
        case 2: return (worldCenter.x, -worldCenter.y)
        case 3: return (worldCenter.y, worldCenter.x)
        default: return (-worldCenter.x, worldCenter.y)
        }
    case .front:
        return (frontMirrored ? -worldCenter.x : worldCenter.x, -worldCenter.z)
    case .back:
        return (-worldCenter.x, -worldCenter.z)
    case .side:
        return (worldCenter.y, -worldCenter.z)
    }
}

private func metricWorldPosition(
    from projectedPoint: CGPoint,
    projection: StageProjection,
    frontMirrored: Bool,
    topQuarterTurns: Int,
    viewportCenter: SlotWorldPosition? = nil
) -> SlotWorldPosition {
    let center = viewportCenter ?? projectionViewportCenter(for: projection)
    let screenCenter = projectionCameraScreenCenter(
        projection: projection,
        worldCenter: center,
        frontMirrored: frontMirrored,
        topQuarterTurns: topQuarterTurns
    )
    switch projection {
    case .top:
        switch normalizedQuarterTurns(topQuarterTurns) {
        case 1:
            let value = metricProjectionCoordinates(projectedPoint, horizontalBounds: -StageWorld.maxY ... -StageWorld.minY, verticalBounds: -StageWorld.maxX ... -StageWorld.minX, cameraCenter: screenCenter)
            return SlotWorldPosition(x: -value.down, y: -value.horizontal, z: center.z)
        case 2:
            let value = metricProjectionCoordinates(projectedPoint, horizontalBounds: StageWorld.minX ... StageWorld.maxX, verticalBounds: -StageWorld.maxY ... -StageWorld.minY, cameraCenter: screenCenter)
            return SlotWorldPosition(x: value.horizontal, y: -value.down, z: center.z)
        case 3:
            let value = metricProjectionCoordinates(projectedPoint, horizontalBounds: StageWorld.minY ... StageWorld.maxY, verticalBounds: StageWorld.minX ... StageWorld.maxX, cameraCenter: screenCenter)
            return SlotWorldPosition(x: value.down, y: value.horizontal, z: center.z)
        default:
            let value = metricProjectionCoordinates(projectedPoint, horizontalBounds: -StageWorld.maxX ... -StageWorld.minX, verticalBounds: StageWorld.minY ... StageWorld.maxY, cameraCenter: screenCenter)
            return SlotWorldPosition(x: -value.horizontal, y: value.down, z: center.z)
        }
    case .front:
        let bounds = frontMirrored ? -StageWorld.maxX ... -StageWorld.minX : StageWorld.minX ... StageWorld.maxX
        let value = metricProjectionCoordinates(projectedPoint, horizontalBounds: bounds, verticalBounds: -StageWorld.maxZ ... -StageWorld.minZ, cameraCenter: screenCenter)
        return SlotWorldPosition(x: frontMirrored ? -value.horizontal : value.horizontal, y: center.y, z: -value.down)
    case .back:
        let value = metricProjectionCoordinates(projectedPoint, horizontalBounds: -StageWorld.maxX ... -StageWorld.minX, verticalBounds: -StageWorld.maxZ ... -StageWorld.minZ, cameraCenter: screenCenter)
        return SlotWorldPosition(x: -value.horizontal, y: center.y, z: -value.down)
    case .side:
        let value = metricProjectionCoordinates(projectedPoint, horizontalBounds: StageWorld.minY ... StageWorld.maxY, verticalBounds: -StageWorld.maxZ ... -StageWorld.minZ, cameraCenter: screenCenter)
        return SlotWorldPosition(x: center.x, y: value.horizontal, z: -value.down)
    }
}

struct LegacyProjectionPoint: Codable {
    let x: Double
    let y: Double
}

struct StageMotionState {
    let currentPanDegrees: Double
    let currentTiltDegrees: Double
    let targetPanDegrees: Double
    let targetTiltDegrees: Double
    let panRange: Double
    let tiltRange: Double
    let estimatedSpeedDegreesPerSecond: Double
    let trail: [StageBeamPose]
    let updatedAt: TimeInterval
    /// Non-nil only when the backend has decoded the post-merge renderer frame
    /// through the fixture calibration. Live Stage Map must display this vector
    /// directly and must not apply local panFlip/heading logic to it.
    let worldDirection: VenueVectorState?
}

struct RenderedMotionState: Decodable {
    let slotId: String
    let fixtureId: String
    let label: String
    let source: String
    let supported: Bool
    let available: Bool
    let status: String
    let pan: Int?
    let panFine: Int?
    let tilt: Int?
    let tiltFine: Int?
    let pan16bit: Int?
    let tilt16bit: Int?
    let physicalPanDegrees: Double?
    let physicalTiltDegrees: Double?
    let physicalTiltPlaneDegrees: Double?
    let commandedPanDegrees: Double?
    let commandedTiltDegrees: Double?
    let worldDirection: VenueVectorState?
    let fixturePositionM: VenuePhysicalPointState?
    let calibrationStatus: String?
}

/// A semantic venue-target preview uses the same canonical target point as the
/// resolver, rather than attempting to replay its fixture-local pan/tilt in
/// the generic stage-map orientation model.  This keeps the existing fixture
/// beam as the sole visual while ensuring its endpoint really is the selected
/// audience target in every projection.
struct VenueTargetPreviewVisual {
    let startEndpoint: SlotWorldPosition
    let endpoint: SlotWorldPosition
    let progress: Double

    var easedProgress: Double {
        progress * progress * (3.0 - 2.0 * progress)
    }
}

struct AutoShowState: Decodable {
    let enabled: Bool
    let available: Bool
    let style: String
    let styleLabel: String
    let previewRmeMode: String
    let audiencePanFocusEnabled: Bool
    let audiencePanMin: Int
    let audiencePanMax: Int
    let audienceTurnPanMin: Int
    let audienceTurnPanMax: Int
    let audienceTiltSplit: Int
    let cueLabel: String
    let phraseBucket: String
    let colorSource: String
    let energy: Double
    let liveIntensity: LiveIntensityState?
    let movement: Double
    let beatPulse: Bool
    let strobeWindow: Bool
    let rhythmMode: String?
    let waveformEnergy: Double?
    let waveformBands: WaveformBandsState?
    let waveformLookahead: [String: WaveformBandsState]?
    let waveformAnalysis: WaveformAnalysis?
    let drumSignals: DrumSignalsState?
    let anticipation: Double?
    let overrideActive: Bool
    let overrideColor: String
    let overrideColorLabel: String
    let overrideColorCombo: String
    let overrideManualStrobe: Bool
    let overrideAudienceSweep: Bool
    let overrideAllOn: Bool
    let overrideParChase: Bool
    let overrideParSnake: Bool
    let oneShotActive: Bool
    let oneShotCue: String
    let oneShotLabel: String
    let oneShotProgress: Double

    private enum CodingKeys: String, CodingKey {
        case enabled
        case available
        case style
        case styleLabel
        case previewRmeMode
        case audiencePanFocusEnabled
        case audiencePanMin
        case audiencePanMax
        case audienceTurnPanMin
        case audienceTurnPanMax
        case audienceTiltSplit
        case cueLabel
        case phraseBucket
        case colorSource
        case energy
        case liveIntensity
        case movement
        case beatPulse
        case strobeWindow
        case rhythmMode
        case waveformEnergy
        case waveformBands
        case waveformLookahead
        case waveformAnalysis
        case drumSignals
        case anticipation
        case overrideActive
        case overrideColor
        case overrideColorLabel
        case overrideColorCombo
        case overrideManualStrobe
        case overrideAudienceSweep
        case overrideAllOn
        case overrideParChase
        case overrideParSnake
        case oneShotActive
        case oneShotCue
        case oneShotLabel
        case oneShotProgress
    }

    static let disabled = AutoShowState(
        enabled: false,
        available: false,
        style: "adaptive",
        styleLabel: "Adaptive",
        previewRmeMode: "BASELINE",
        audiencePanFocusEnabled: true,
        audiencePanMin: 135,
        audiencePanMax: 205,
        audienceTurnPanMin: 50,
        audienceTurnPanMax: 120,
        audienceTiltSplit: 127,
        cueLabel: "Auto Show uit",
        phraseBucket: "unknown",
        colorSource: "manual",
        energy: 0,
        liveIntensity: nil,
        movement: 0,
        beatPulse: false,
        strobeWindow: false,
        rhythmMode: nil,
        waveformEnergy: nil,
        waveformBands: nil,
        waveformLookahead: nil,
        waveformAnalysis: nil,
        drumSignals: nil,
        anticipation: nil,
        overrideActive: false,
        overrideColor: "none",
        overrideColorLabel: "Auto",
        overrideColorCombo: "none",
        overrideManualStrobe: false,
        overrideAudienceSweep: false,
        overrideAllOn: false,
        overrideParChase: false,
        overrideParSnake: false,
        oneShotActive: false,
        oneShotCue: "none",
        oneShotLabel: "None",
        oneShotProgress: 0
    )

    init(
        enabled: Bool,
        available: Bool,
        style: String,
        styleLabel: String,
        previewRmeMode: String,
        audiencePanFocusEnabled: Bool,
        audiencePanMin: Int,
        audiencePanMax: Int,
        audienceTurnPanMin: Int,
        audienceTurnPanMax: Int,
        audienceTiltSplit: Int,
        cueLabel: String,
        phraseBucket: String,
        colorSource: String,
        energy: Double,
        liveIntensity: LiveIntensityState? = nil,
        movement: Double,
        beatPulse: Bool,
        strobeWindow: Bool,
        rhythmMode: String?,
        waveformEnergy: Double?,
        waveformBands: WaveformBandsState?,
        waveformLookahead: [String: WaveformBandsState]?,
        waveformAnalysis: WaveformAnalysis?,
        drumSignals: DrumSignalsState?,
        anticipation: Double?,
        overrideActive: Bool,
        overrideColor: String,
        overrideColorLabel: String,
        overrideColorCombo: String,
        overrideManualStrobe: Bool,
        overrideAudienceSweep: Bool,
        overrideAllOn: Bool,
        overrideParChase: Bool,
        overrideParSnake: Bool,
        oneShotActive: Bool,
        oneShotCue: String,
        oneShotLabel: String,
        oneShotProgress: Double
    ) {
        self.enabled = enabled
        self.available = available
        self.style = style
        self.styleLabel = styleLabel
        self.previewRmeMode = previewRmeMode
        self.audiencePanFocusEnabled = audiencePanFocusEnabled
        self.audiencePanMin = audiencePanMin
        self.audiencePanMax = audiencePanMax
        self.audienceTurnPanMin = audienceTurnPanMin
        self.audienceTurnPanMax = audienceTurnPanMax
        self.audienceTiltSplit = audienceTiltSplit
        self.cueLabel = cueLabel
        self.phraseBucket = phraseBucket
        self.colorSource = colorSource
        self.energy = energy
        self.liveIntensity = liveIntensity
        self.movement = movement
        self.beatPulse = beatPulse
        self.strobeWindow = strobeWindow
        self.rhythmMode = rhythmMode
        self.waveformEnergy = waveformEnergy
        self.waveformBands = waveformBands
        self.waveformLookahead = waveformLookahead
        self.waveformAnalysis = waveformAnalysis
        self.drumSignals = drumSignals
        self.anticipation = anticipation
        self.overrideActive = overrideActive
        self.overrideColor = overrideColor
        self.overrideColorLabel = overrideColorLabel
        self.overrideColorCombo = overrideColorCombo
        self.overrideManualStrobe = overrideManualStrobe
        self.overrideAudienceSweep = overrideAudienceSweep
        self.overrideAllOn = overrideAllOn
        self.overrideParChase = overrideParChase
        self.overrideParSnake = overrideParSnake
        self.oneShotActive = oneShotActive
        self.oneShotCue = oneShotCue
        self.oneShotLabel = oneShotLabel
        self.oneShotProgress = oneShotProgress
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let fallback = Self.disabled
        let audiencePanMin = try container.decodeIfPresent(Int.self, forKey: .audiencePanMin) ?? fallback.audiencePanMin
        let audiencePanMax = try container.decodeIfPresent(Int.self, forKey: .audiencePanMax) ?? fallback.audiencePanMax
        let defaultTurnMin = 50
        let defaultTurnMax = 120
        self.init(
            enabled: try container.decodeIfPresent(Bool.self, forKey: .enabled) ?? fallback.enabled,
            available: try container.decodeIfPresent(Bool.self, forKey: .available) ?? fallback.available,
            style: try container.decodeIfPresent(String.self, forKey: .style) ?? fallback.style,
            styleLabel: try container.decodeIfPresent(String.self, forKey: .styleLabel) ?? fallback.styleLabel,
            previewRmeMode: try container.decodeIfPresent(String.self, forKey: .previewRmeMode) ?? fallback.previewRmeMode,
            audiencePanFocusEnabled: try container.decodeIfPresent(Bool.self, forKey: .audiencePanFocusEnabled) ?? fallback.audiencePanFocusEnabled,
            audiencePanMin: audiencePanMin,
            audiencePanMax: audiencePanMax,
            audienceTurnPanMin: try container.decodeIfPresent(Int.self, forKey: .audienceTurnPanMin) ?? defaultTurnMin,
            audienceTurnPanMax: try container.decodeIfPresent(Int.self, forKey: .audienceTurnPanMax) ?? defaultTurnMax,
            audienceTiltSplit: try container.decodeIfPresent(Int.self, forKey: .audienceTiltSplit) ?? fallback.audienceTiltSplit,
            cueLabel: try container.decodeIfPresent(String.self, forKey: .cueLabel) ?? fallback.cueLabel,
            phraseBucket: try container.decodeIfPresent(String.self, forKey: .phraseBucket) ?? fallback.phraseBucket,
            colorSource: try container.decodeIfPresent(String.self, forKey: .colorSource) ?? fallback.colorSource,
            energy: try container.decodeIfPresent(Double.self, forKey: .energy) ?? fallback.energy,
            liveIntensity: try container.decodeIfPresent(LiveIntensityState.self, forKey: .liveIntensity),
            movement: try container.decodeIfPresent(Double.self, forKey: .movement) ?? fallback.movement,
            beatPulse: try container.decodeIfPresent(Bool.self, forKey: .beatPulse) ?? fallback.beatPulse,
            strobeWindow: try container.decodeIfPresent(Bool.self, forKey: .strobeWindow) ?? fallback.strobeWindow,
            rhythmMode: try container.decodeIfPresent(String.self, forKey: .rhythmMode),
            waveformEnergy: try container.decodeIfPresent(Double.self, forKey: .waveformEnergy),
            waveformBands: try container.decodeIfPresent(WaveformBandsState.self, forKey: .waveformBands),
            waveformLookahead: try container.decodeIfPresent([String: WaveformBandsState].self, forKey: .waveformLookahead),
            waveformAnalysis: try container.decodeIfPresent(WaveformAnalysis.self, forKey: .waveformAnalysis),
            drumSignals: try container.decodeIfPresent(DrumSignalsState.self, forKey: .drumSignals),
            anticipation: try container.decodeIfPresent(Double.self, forKey: .anticipation),
            overrideActive: try container.decodeIfPresent(Bool.self, forKey: .overrideActive) ?? fallback.overrideActive,
            overrideColor: try container.decodeIfPresent(String.self, forKey: .overrideColor) ?? fallback.overrideColor,
            overrideColorLabel: try container.decodeIfPresent(String.self, forKey: .overrideColorLabel) ?? fallback.overrideColorLabel,
            overrideColorCombo: try container.decodeIfPresent(String.self, forKey: .overrideColorCombo) ?? fallback.overrideColorCombo,
            overrideManualStrobe: try container.decodeIfPresent(Bool.self, forKey: .overrideManualStrobe) ?? fallback.overrideManualStrobe,
            overrideAudienceSweep: try container.decodeIfPresent(Bool.self, forKey: .overrideAudienceSweep) ?? fallback.overrideAudienceSweep,
            overrideAllOn: try container.decodeIfPresent(Bool.self, forKey: .overrideAllOn) ?? fallback.overrideAllOn,
            overrideParChase: try container.decodeIfPresent(Bool.self, forKey: .overrideParChase) ?? fallback.overrideParChase,
            overrideParSnake: try container.decodeIfPresent(Bool.self, forKey: .overrideParSnake) ?? fallback.overrideParSnake,
            oneShotActive: try container.decodeIfPresent(Bool.self, forKey: .oneShotActive) ?? fallback.oneShotActive,
            oneShotCue: try container.decodeIfPresent(String.self, forKey: .oneShotCue) ?? fallback.oneShotCue,
            oneShotLabel: try container.decodeIfPresent(String.self, forKey: .oneShotLabel) ?? fallback.oneShotLabel,
            oneShotProgress: try container.decodeIfPresent(Double.self, forKey: .oneShotProgress) ?? fallback.oneShotProgress
        )
    }
}

struct LiveIntensityState: Decodable {
    let analyzedIntensity: Double?
    let rawSourceLevel: Double?
    let liveIntensity: Double?
    let effectiveIntensity: Double?
    let liveModifier: Double?
    let sourceAgeMilliseconds: Double?
    let sourceDeck: Int?
    let sourceGeneration: Int?
    let sourceKind: String?
    let sourceValid: Bool?
    let fallbackReason: String?
}

struct WaveformBandsState: Decodable {
    let low: Double?
    let mid: Double?
    let high: Double?
}

struct DrumSignalsState: Decodable {
    let kick: Double?
    let snare: Double?
    let hihat: Double?
    let impact: Double?
    let sparkle: Double?
    let motion: Double?
    let lowOnset: Double?
    let midOnset: Double?
    let highOnset: Double?
}

struct WaveformAnalysis: Decodable {
    let instant: Double
    let shortAvg: Double
    let midAvg: Double
    let longAvg: Double
    let lift: Double
    let crest: Double
    let transient: Double
    let volatility: Double
    let sustainedHigh: Bool
    let attack: Bool
    let calm: Bool
    let breakdown: Bool
    let moodHint: Double?
    let state: String?

    private enum CodingKeys: String, CodingKey {
        case instant
        case shortAvg
        case midAvg
        case longAvg
        case lift
        case crest
        case transient
        case volatility
        case sustainedHigh
        case attack
        case calm
        case breakdown
        case moodHint
        case state
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        instant = try container.decodeIfPresent(Double.self, forKey: .instant) ?? 0
        shortAvg = try container.decodeIfPresent(Double.self, forKey: .shortAvg) ?? 0
        midAvg = try container.decodeIfPresent(Double.self, forKey: .midAvg) ?? 0
        longAvg = try container.decodeIfPresent(Double.self, forKey: .longAvg) ?? 0
        lift = try container.decodeIfPresent(Double.self, forKey: .lift) ?? 0
        crest = try container.decodeIfPresent(Double.self, forKey: .crest) ?? 0
        transient = try container.decodeIfPresent(Double.self, forKey: .transient) ?? 0
        volatility = try container.decodeIfPresent(Double.self, forKey: .volatility) ?? 0
        sustainedHigh = try container.decodeIfPresent(Bool.self, forKey: .sustainedHigh) ?? false
        attack = try container.decodeIfPresent(Bool.self, forKey: .attack) ?? false
        calm = try container.decodeIfPresent(Bool.self, forKey: .calm) ?? false
        breakdown = try container.decodeIfPresent(Bool.self, forKey: .breakdown) ?? false
        moodHint = try container.decodeIfPresent(Double.self, forKey: .moodHint)
        state = try container.decodeIfPresent(String.self, forKey: .state)
    }
}

struct OscState: Decodable {
    let port: Int
    let running: Bool
    let stale: Bool
    let error: String?
    let messageCount: Int
    let lastReceivedAt: Double?
    let lastMessage: OscMessage?
    let bpm: Double?
    let beat: Double?
    let beatDisplay: Double?
    let timeSeconds: Double?
    let timeDisplaySeconds: Double?
    let phraseCurrent: String?
    let phraseNext: String?
    let phraseCountIn: Int?
    let phraseCountdownBeats: Double?
    let phraseCountdownSeconds: Double?
    let mood: Double?
    let colorBank: Int?
    let waveformEnergy: Double?
    let audioBands: WaveformBandsState?
    let waveformBands: WaveformBandsState?
    let waveformLookahead: [String: WaveformBandsState]?
    let waveformAnalysis: WaveformAnalysis?
    let audioDrums: DrumSignalsState?
    let drumSignals: DrumSignalsState?
    let strobeActive: Bool
    let strobeCountIn: Int?
    let trackTitle: String?
    let trackArtist: String?
    let trackAlbum: String?
    let decks: OscDeckCollection?
    let lastBeatAt: Double?
}

struct OscDeckState: Decodable {
    let trackTitle: String?
    let trackArtist: String?
    let trackAlbum: String?
    let timeSeconds: Double?
    let timeDisplaySeconds: Double?
    let phraseCurrent: String?
    let phraseNext: String?
    let mood: Double?
    let colorBank: Int?
    let waveformEnergy: Double?
    let waveformBands: WaveformBandsState?
    let waveformLookahead: [String: WaveformBandsState]?
    let drumSignals: DrumSignalsState?
}

struct OscDeckOverviewState: Decodable {
    let deckNumber: Int
    let isLoaded: Bool
    let trackPath: String?
    let fileName: String?
    let artist: String?
    let title: String?
    let bpm: Double?
    let positionMilliseconds: Int?
    let beatPosition: Double?
    let beatNumber: Int?
    let barNumber: Int?
    let capturedAtUnixMilliseconds: Int
    let isPlaying: Bool?
}

struct OscDeckCollection: Decodable {
    let legacy: [String: OscDeckState]?
    let overview: [OscDeckOverviewState]?

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let legacy = try? container.decode([String: OscDeckState].self) {
            self.legacy = legacy
            self.overview = nil
            return
        }

        let overview = try container.decode([OscDeckOverviewState].self)
        var seen = Set<Int>()
        for deck in overview {
            guard deck.deckNumber > 0 else {
                throw DecodingError.dataCorruptedError(
                    in: container,
                    debugDescription: "osc.decks deck_number must be positive"
                )
            }
            guard seen.insert(deck.deckNumber).inserted else {
                throw DecodingError.dataCorruptedError(
                    in: container,
                    debugDescription: "osc.decks contains duplicate deck_number"
                )
            }
        }
        self.legacy = nil
        self.overview = overview
    }
}

struct OscMessage: Decodable {
    let address: String
    let numeric: Double?
    let text: String?
    let source: String
}

struct SourceState: Decodable {
    let mode: String
    let resolvedMode: String?
    let app: String
    // VirtualDJ is consumed through MusicAnalyzer's local snapshot, so it has
    // no backend listener port of its own.
    let port: Int?
    let expectedDestination: String
    let lastSource: String?
}

private struct BackendResponseDecodeFailure: LocalizedError {
    let requestPath: String
    let underlyingError: Error

    var errorDescription: String? {
        "Backendstatus kon niet worden gelezen."
    }
}

struct TransportState: Decodable {
    let mode: String
    let resolvedMode: String
    let manualBpm: Double
    let effectiveBpm: Double?
    let manualPhrase: String
    let manualPhraseLabel: String
    let idleAnimationEnabled: Bool
    let tapCount: Int
    let tapLocked: Bool
    let externalAvailable: Bool
    let lastTapAt: Double?
}

struct AudioInputDevice: Identifiable, Hashable {
    let id: AudioDeviceID
    let name: String
}

private func getAudioDeviceIDs() -> [AudioDeviceID] {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDevices,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )
    var dataSize: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &dataSize) == noErr else {
        return []
    }

    let count = Int(dataSize) / MemoryLayout<AudioDeviceID>.size
    var ids = Array(repeating: AudioDeviceID(0), count: count)
    guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &dataSize, &ids) == noErr else {
        return []
    }
    return ids
}

private func audioDeviceName(_ deviceID: AudioDeviceID) -> String {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioObjectPropertyName,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )
    var name: CFString = "" as CFString
    var dataSize = UInt32(MemoryLayout<CFString>.size)
    let status = AudioObjectGetPropertyData(deviceID, &address, 0, nil, &dataSize, &name)
    return status == noErr ? (name as String) : "Onbekend"
}

private func audioDeviceHasInput(_ deviceID: AudioDeviceID) -> Bool {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioDevicePropertyStreamConfiguration,
        mScope: kAudioDevicePropertyScopeInput,
        mElement: kAudioObjectPropertyElementMain
    )
    var dataSize: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(deviceID, &address, 0, nil, &dataSize) == noErr else {
        return false
    }

    let rawPointer = UnsafeMutableRawPointer.allocate(
        byteCount: Int(dataSize),
        alignment: MemoryLayout<AudioBufferList>.alignment
    )
    defer { rawPointer.deallocate() }

    let bufferListPointer = rawPointer.bindMemory(to: AudioBufferList.self, capacity: 1)
    guard AudioObjectGetPropertyData(deviceID, &address, 0, nil, &dataSize, bufferListPointer) == noErr else {
        return false
    }

    let buffers = UnsafeMutableAudioBufferListPointer(bufferListPointer)
    return buffers.contains { $0.mNumberChannels > 0 }
}

private func listAudioInputDevices() -> [AudioInputDevice] {
    getAudioDeviceIDs()
        .filter { audioDeviceHasInput($0) }
        .map { AudioInputDevice(id: $0, name: audioDeviceName($0)) }
        .sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
}

private func setEngineInputDevice(engine: AVAudioEngine, deviceID: AudioDeviceID) -> Bool {
    guard let audioUnit = engine.inputNode.audioUnit else { return false }
    var id = deviceID
    let status = AudioUnitSetProperty(
        audioUnit,
        kAudioOutputUnitProperty_CurrentDevice,
        kAudioUnitScope_Global,
        0,
        &id,
        UInt32(MemoryLayout<AudioDeviceID>.size)
    )
    return status == noErr
}

struct LiveAudioFeatureFrame {
    let rms: Double
    let low: Double
    let mid: Double
    let high: Double
    let kick: Double
    let snare: Double
    let hihat: Double
}

final class LiveAudioFeatureAnalyzer {
    private let sampleRate: Double
    private let lowCutoff: Double = 180.0
    private let midCutoff: Double = 2_000.0
    private var lowPassState: Double = 0.0
    private var midLowPassState: Double = 0.0
    private var midHighPassState: Double = 0.0
    private var highSplitLowPassState: Double = 0.0
    private var peakLow: Double = 0.01
    private var peakMid: Double = 0.01
    private var peakHigh: Double = 0.01
    private var fastLow: Double = 0.0
    private var fastMid: Double = 0.0
    private var fastHigh: Double = 0.0
    private var slowLow: Double = 0.0
    private var slowMid: Double = 0.0
    private var slowHigh: Double = 0.0
    private var kickHold: Double = 0.0
    private var snareHold: Double = 0.0
    private var hihatHold: Double = 0.0

    init(sampleRate: Double) {
        self.sampleRate = max(8_000.0, sampleRate)
    }

    func process(buffer: AVAudioPCMBuffer) -> LiveAudioFeatureFrame? {
        guard let channels = buffer.floatChannelData else { return nil }
        let frameCount = Int(buffer.frameLength)
        let channelCount = Int(buffer.format.channelCount)
        guard frameCount > 0, channelCount > 0 else { return nil }

        let lowAlpha = filterAlpha(cutoff: lowCutoff)
        let midAlpha = filterAlpha(cutoff: midCutoff)

        var fullSumSquares = 0.0
        var lowSumSquares = 0.0
        var midSumSquares = 0.0
        var highSumSquares = 0.0

        for frame in 0..<frameCount {
            var mono: Double = 0.0
            for channel in 0..<channelCount {
                mono += Double(channels[channel][frame])
            }
            mono /= Double(channelCount)

            lowPassState += lowAlpha * (mono - lowPassState)
            midLowPassState += midAlpha * (mono - midLowPassState)
            midHighPassState += lowAlpha * (mono - midHighPassState)
            highSplitLowPassState += midAlpha * (mono - highSplitLowPassState)

            let low = lowPassState
            let mid = midLowPassState - midHighPassState
            let high = mono - highSplitLowPassState

            fullSumSquares += mono * mono
            lowSumSquares += low * low
            midSumSquares += mid * mid
            highSumSquares += high * high
        }

        let scale = max(1.0, Double(frameCount))
        let rms = sqrt(fullSumSquares / scale + 1e-12)
        let lowNorm = normalizedBand(sqrt(lowSumSquares / scale + 1e-12), peak: &peakLow, response: 0.996)
        let midNorm = normalizedBand(sqrt(midSumSquares / scale + 1e-12), peak: &peakMid, response: 0.996)
        let highNorm = normalizedBand(sqrt(highSumSquares / scale + 1e-12), peak: &peakHigh, response: 0.996)

        let kick = updateOnset(
            current: lowNorm,
            fast: &fastLow,
            slow: &slowLow,
            hold: &kickHold,
            energyFloor: 0.08,
            liftFloor: 0.030,
            riseFloor: 0.012,
            dominance: clamp01(lowNorm - (midNorm * 0.55 + highNorm * 0.25))
        )
        let snare = updateOnset(
            current: midNorm,
            fast: &fastMid,
            slow: &slowMid,
            hold: &snareHold,
            energyFloor: 0.07,
            liftFloor: 0.022,
            riseFloor: 0.010,
            dominance: clamp01(midNorm - (lowNorm * 0.30 + highNorm * 0.30))
        )
        let hihat = updateOnset(
            current: highNorm,
            fast: &fastHigh,
            slow: &slowHigh,
            hold: &hihatHold,
            energyFloor: 0.05,
            liftFloor: 0.018,
            riseFloor: 0.008,
            dominance: clamp01(highNorm - (lowNorm * 0.18 + midNorm * 0.22))
        )

        return LiveAudioFeatureFrame(
            rms: clamp01(rms * 10.0),
            low: lowNorm,
            mid: midNorm,
            high: highNorm,
            kick: kick,
            snare: snare,
            hihat: hihat
        )
    }

    private func filterAlpha(cutoff: Double) -> Double {
        let normalized = (2.0 * Double.pi * cutoff) / sampleRate
        return clamp01(1.0 - exp(-normalized))
    }

    private func normalizedBand(_ value: Double, peak: inout Double, response: Double) -> Double {
        peak = max(value, peak * response)
        return clamp01(value / max(peak * 0.82, 1e-6))
    }

    private func updateOnset(
        current: Double,
        fast: inout Double,
        slow: inout Double,
        hold: inout Double,
        energyFloor: Double,
        liftFloor: Double,
        riseFloor: Double,
        dominance: Double
    ) -> Double {
        let previousFast = fast
        fast += 0.55 * (current - fast)
        slow += 0.10 * (current - slow)

        let lift = max(0.0, fast - slow)
        let rise = max(0.0, fast - previousFast)
        let transient = (current >= energyFloor && (lift >= liftFloor || rise >= riseFloor))
            ? clamp01(
                ((lift - liftFloor) / 0.16) * 0.52
                + ((rise - riseFloor) / 0.10) * 0.28
                + ((current - energyFloor) / 0.30) * 0.12
                + dominance * 0.08
            )
            : 0.0

        hold = max(transient, hold * 0.58)
        return hold
    }

    private func clamp01(_ value: Double) -> Double {
        min(1.0, max(0.0, value))
    }
}

final class OscFloatForwarder {
    private var socketFD: Int32 = -1
    private var remoteAddress = sockaddr_storage()
    private var remoteAddressLength: socklen_t = 0
    private let lock = NSLock()

    deinit {
        stop()
    }

    func start(host: String, port: Int) throws {
        stop()
        guard !host.isEmpty else {
            throw NSError(domain: "BeatBeamDMX", code: 5101, userInfo: [NSLocalizedDescriptionKey: "Lege OSC host."])
        }
        guard port > 0 && port <= 65535 else {
            throw NSError(domain: "BeatBeamDMX", code: 5102, userInfo: [NSLocalizedDescriptionKey: "Ongeldige OSC poort."])
        }

        var hints = addrinfo(
            ai_flags: AI_NUMERICSERV,
            ai_family: AF_UNSPEC,
            ai_socktype: SOCK_DGRAM,
            ai_protocol: IPPROTO_UDP,
            ai_addrlen: 0,
            ai_canonname: nil,
            ai_addr: nil,
            ai_next: nil
        )

        var result: UnsafeMutablePointer<addrinfo>?
        let service = String(port)
        let status = getaddrinfo(host, service, &hints, &result)
        guard status == 0, let resolved = result else {
            throw NSError(domain: "BeatBeamDMX", code: 5103, userInfo: [NSLocalizedDescriptionKey: "Kon OSC doel niet resolven."])
        }
        defer { freeaddrinfo(resolved) }

        let fd = socket(resolved.pointee.ai_family, resolved.pointee.ai_socktype, resolved.pointee.ai_protocol)
        guard fd >= 0 else {
            throw NSError(domain: "BeatBeamDMX", code: 5104, userInfo: [NSLocalizedDescriptionKey: "Kon OSC socket niet openen."])
        }

        var storage = sockaddr_storage()
        memcpy(&storage, resolved.pointee.ai_addr, Int(resolved.pointee.ai_addrlen))

        lock.lock()
        socketFD = fd
        remoteAddress = storage
        remoteAddressLength = resolved.pointee.ai_addrlen
        lock.unlock()
    }

    func stop() {
        lock.lock()
        let fd = socketFD
        socketFD = -1
        remoteAddressLength = 0
        lock.unlock()

        if fd >= 0 {
            Darwin.close(fd)
        }
    }

    func sendFloat(address: String, value: Double) {
        guard value.isFinite else { return }
        let payload = encode(address: address, value: value)
        guard !payload.isEmpty else { return }

        lock.lock()
        let fd = socketFD
        var addr = remoteAddress
        let addrLen = remoteAddressLength
        lock.unlock()

        guard fd >= 0, addrLen > 0 else { return }
        payload.withUnsafeBytes { raw in
            guard let base = raw.baseAddress else { return }
            withUnsafePointer(to: &addr) { ptr in
                ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockPtr in
                    _ = sendto(fd, base, payload.count, 0, sockPtr, addrLen)
                }
            }
        }
    }

    private func encode(address: String, value: Double) -> Data {
        var data = Data()
        data.append(paddedOscString(address))
        data.append(paddedOscString(",f"))
        var bits = Float32(value).bitPattern.bigEndian
        withUnsafeBytes(of: &bits) { data.append(contentsOf: $0) }
        return data
    }

    private func paddedOscString(_ value: String) -> Data {
        var bytes = Array(value.utf8)
        bytes.append(0)
        while (bytes.count % 4) != 0 {
            bytes.append(0)
        }
        return Data(bytes)
    }
}

final class BeatBeamLiveAudioBridge {
    private let queue = DispatchQueue(label: "beatbeam.liveaudio.bridge")
    private var audioEngine: AVAudioEngine?
    private var analyzer: LiveAudioFeatureAnalyzer?
    private var forwarder: OscFloatForwarder?
    private var lastEmitAt: CFAbsoluteTime = 0

    var onStatus: ((String) -> Void)?

    func start(inputDeviceID: AudioDeviceID?, oscPort: Int = defaultBackendOscPort) throws {
        stop()

        guard let inputDeviceID else {
            throw NSError(domain: "BeatBeamDMX", code: 5201, userInfo: [NSLocalizedDescriptionKey: "Geen live audio input geselecteerd."])
        }

        let forwarder = OscFloatForwarder()
        try forwarder.start(host: "127.0.0.1", port: oscPort)

        let engine = AVAudioEngine()
        if !setEngineInputDevice(engine: engine, deviceID: inputDeviceID) {
            onStatus?("Live audio gebruikt standaard input.")
        }

        let input = engine.inputNode
        let format = input.inputFormat(forBus: 0)
        let analyzer = LiveAudioFeatureAnalyzer(sampleRate: format.sampleRate)
        self.analyzer = analyzer
        self.forwarder = forwarder
        self.lastEmitAt = 0

        input.installTap(onBus: 0, bufferSize: 512, format: format) { [weak self] buffer, _ in
            guard let self, let analyzer = self.analyzer else { return }
            guard let frame = analyzer.process(buffer: buffer) else { return }
            self.emit(frame)
        }

        do {
            try engine.start()
            self.audioEngine = engine
            onStatus?("Live audio actief op \(audioDeviceName(inputDeviceID)).")
        } catch {
            input.removeTap(onBus: 0)
            self.audioEngine = nil
            self.analyzer = nil
            self.forwarder?.stop()
            self.forwarder = nil
            throw error
        }
    }

    func stop() {
        queue.sync {
            audioEngine?.inputNode.removeTap(onBus: 0)
            audioEngine?.stop()
            audioEngine = nil
            analyzer = nil
            forwarder?.stop()
            forwarder = nil
            lastEmitAt = 0
        }
    }

    private func emit(_ frame: LiveAudioFeatureFrame) {
        queue.async { [weak self] in
            guard let self, let forwarder = self.forwarder else { return }
            let now = CFAbsoluteTimeGetCurrent()
            if (now - self.lastEmitAt) < 0.04 {
                return
            }
            self.lastEmitAt = now

            forwarder.sendFloat(address: "/master/waveform/energy", value: frame.rms)
            forwarder.sendFloat(address: "/master/audio/low_energy", value: frame.low)
            forwarder.sendFloat(address: "/master/audio/mid_energy", value: frame.mid)
            forwarder.sendFloat(address: "/master/audio/high_energy", value: frame.high)
            forwarder.sendFloat(address: "/master/waveform/low_energy", value: frame.low)
            forwarder.sendFloat(address: "/master/waveform/mid_energy", value: frame.mid)
            forwarder.sendFloat(address: "/master/waveform/high_energy", value: frame.high)
            forwarder.sendFloat(address: "/master/audio/kick", value: frame.kick)
            forwarder.sendFloat(address: "/master/audio/snare", value: frame.snare)
            forwarder.sendFloat(address: "/master/audio/hihat", value: frame.hihat)
            forwarder.sendFloat(address: "/master/drums/kick", value: frame.kick)
            forwarder.sendFloat(address: "/master/drums/snare", value: frame.snare)
            forwarder.sendFloat(address: "/master/drums/hihat", value: frame.hihat)
        }
    }
}

struct PortsResponse: Decodable {
    let ports: [PortInfo]
}

struct FixturesResponse: Decodable {
    let fixtures: [FixtureProfile]
}

struct FixtureProfile: Decodable, Identifiable, Hashable {
    let id: String
    let manufacturer: String
    let model: String
    let modes: [FixtureMode]
    let panRange: Double?
    let tiltRange: Double?

    var displayName: String {
        "\(manufacturer) \(model)"
    }
}

struct FixtureMode: Decodable, Hashable {
    let name: String
    let footprint: Int
    let channels: [FixtureChannel]?

    var extraControls: [FixtureExtraControl] {
        (channels ?? []).compactMap { channel in
            guard channel.type == "custom" else { return nil }
            let rawID = channel.control ?? channel.id ?? channel.name ?? "custom_\(channel.offset)"
            let trimmedID = rawID.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmedID.isEmpty else { return nil }
            return FixtureExtraControl(
                id: trimmedID,
                title: channel.name ?? trimmedID,
                offset: channel.offset,
                defaultValue: max(0, min(255, channel.defaultValue ?? 0)),
                ranges: channel.ranges ?? []
            )
        }
    }
}

struct FixtureChannel: Decodable, Hashable {
    let offset: Int
    let name: String?
    let type: String
    let id: String?
    let control: String?
    let ranges: [FixtureChannelRange]?
    let defaultValue: Int?

    enum CodingKeys: String, CodingKey {
        case offset
        case name
        case type
        case id
        case control
        case ranges
        case defaultValue = "default"
    }
}

struct FixtureChannelRange: Decodable, Hashable {
    let from: Int
    let to: Int
    let name: String
}

struct FixtureExtraControl: Identifiable, Hashable {
    let id: String
    let title: String
    let offset: Int
    let defaultValue: Int
    let ranges: [FixtureChannelRange]
}

struct PortInfo: Decodable, Hashable {
    let device: String
    let label: String
    let manufacturer: String?
    let product: String?
    let serialNumber: String?
}

struct ConnectRequest: Encodable {
    let port: String
    let fps: Double
}

struct EmptyRequest: Encodable {}

struct VirtualDjBeatPulsePreviewRequest: Encodable {
    let slotID: String
    let durationMilliseconds: Int
}

struct AddSlotRequest: Encodable {
    let fixtureID: String
    let mode: String?
}

struct RemoveSlotRequest: Encodable {
    let slotID: String
}

struct SlotUpdateRequest: Encodable {
    let slotID: String
    let activeSlot: String
    let slot: SlotUpdateBody
}

struct VenueCalibrationUpdateRequest: Encodable {
    let slotID: String
    let activeSlot: String
    let slot: VenueCalibrationSlotUpdate
}

struct VenueCalibrationSlotUpdate: Encodable {
    let venueCalibration: VenueCalibrationPayload
}

struct PhysicalTiltLimitsPayload: Encodable {
    let minDeg: Double
    let centerDeg: Double
    let maxDeg: Double
}

struct VenueCalibrationPayload: Encodable {
    let version: Int
    let positionM: VenuePhysicalPointState
    let position: VenuePointState
    let mountingHeightM: Double
    let physicalForward: VenueVectorState
    let physicalUp: VenueVectorState
    let panCorrectionDegrees: Double
    let tiltCorrectionDegrees: Double
    let physicalTiltLimits: PhysicalTiltLimitsPayload?

    init(
        version: Int,
        positionM: VenuePhysicalPointState,
        position: VenuePointState,
        mountingHeightM: Double,
        physicalForward: VenueVectorState,
        physicalUp: VenueVectorState,
        panCorrectionDegrees: Double,
        tiltCorrectionDegrees: Double,
        physicalTiltLimits: PhysicalTiltLimitsPayload? = nil
    ) {
        self.version = version
        self.positionM = positionM
        self.position = position
        self.mountingHeightM = mountingHeightM
        self.physicalForward = physicalForward
        self.physicalUp = physicalUp
        self.panCorrectionDegrees = panCorrectionDegrees
        self.tiltCorrectionDegrees = tiltCorrectionDegrees
        self.physicalTiltLimits = physicalTiltLimits
    }
}

/// A Stage Map edit owns fixture position only.  It intentionally leaves the
/// separately calibrated Forward/Up basis and aim mappings intact.
struct FixturePositionUpdateRequest: Encodable {
    let activeSlot: String
    let slots: [String: FixturePositionSlotUpdate]
}

struct FixturePositionSlotUpdate: Encodable {
    let venueCalibration: FixturePositionOnlyPayload
}

struct FixturePositionOnlyPayload: Encodable {
    let positionM: VenuePhysicalPointState
}

struct VenueGeometryUpdateRequest: Encodable {
    let venueGeometry: VenueGeometryUpdatePayload
}

struct VenueGeometryUpdatePayload: Encodable {
    let venueWidthM: Double?
    let venueForwardDepthM: Double?
    let venueRearDepthM: Double?
    let audienceTargetHeightM: Double?
    let ceilingHeightM: Double?
}

struct VenueTargetTestRequest: Encodable {
    let slotID: String
    let venueCalibration: VenueCalibrationPayload
    let target: String?
    let verticalLayer: String?
}

struct VenueTargetGroupRequest: Encodable {
    let target: String
    let verticalLayer: String
}

struct AimCalibrationMoveRequest: Encodable {
    let slotID: String
    let target: String
}

struct AimCalibrationNudgeRequest: Encodable {
    let axis: String
    let direction: String
    let granularity: String
}

struct AimCalibrationValidationRequest: Encodable {
    let result: String
}

struct AimCalibrationResetRequest: Encodable {
    let slotID: String
    let confirm: Bool
}

struct AimCalibrationActionResponse: Decodable {
    let accepted: Bool
    let status: String
    let reason: String?
    let authority: VenueTargetTestAuthorityState?
    let aimCalibration: KinematicCalibrationState?
}

struct AxisMappingV2BeginRequest: Encodable { let slotID: String; let axis: String }
struct AxisMappingV2ReferencePoseNudgeRequest: Encodable { let slotID: String; let axis: String; let direction: String; let granularity: String }
struct AxisMappingV2LockTiltReferenceRequest: Encodable { }
struct AxisMappingV2PanReferenceRequest: Encodable { let slotID: String; let tiltPlaneDegrees: Double }
struct AxisMappingV2MoveSampleRequest: Encodable { let slotID: String; let axis: String; let index: Int }
struct AxisMappingV2SaveSampleRequest: Encodable { let axis: String; let measuredDegrees: Double }
struct AxisMappingV2ValidationMoveRequest: Encodable { let slotID: String; let target: String }
struct AxisMappingV2ValidationResultRequest: Encodable { let result: String }
struct AxisMappingV2ActivateRequest: Encodable { let slotID: String }
struct AxisMappingV2ResetRequest: Encodable { let slotID: String; let confirm: Bool }

struct AxisMappingV2ActionResponse: Decodable {
    let accepted: Bool
    let status: String
    let reason: String?
    let authority: VenueTargetTestAuthorityState?
    let axisMappingV2: AxisMappingV2State?
}

struct MovementLabRequest: Encodable {
    let effectID: String
    let section: String
    let variation: Int
    let bpm: Double
}

struct MovementLabResponse: Decodable {
    let accepted: Bool
    let reason: String?
    let movementLab: MovementLabState
}

struct VenueTargetGroupResponse: Decodable {
    let target: String
    let verticalLayer: String?
    let targetPoint: VenuePointState
    let candidateCount: Int
    let targetedCount: Int
    let skippedCount: Int
    let rendererHealthy: Bool
    let dmxConnected: Bool
    let physicalReady: Bool
    let results: [VenueTargetFixtureResultState]
    let physicalCommandSent: Bool

    var resultSet: VenueTargetResultSetState {
        VenueTargetResultSetState(
            target: target,
            verticalLayer: verticalLayer,
            targetPoint: targetPoint,
            candidateCount: candidateCount,
            targetedCount: targetedCount,
            skippedCount: skippedCount,
            rendererHealthy: rendererHealthy,
            dmxConnected: dmxConnected,
            physicalReady: physicalReady,
            results: results
        )
    }
}

struct VenueTargetTestResponse: Decodable {
    let slotID: String
    let target: String
    let result: VenueTargetResolutionState
    let physicalCommandSent: Bool

    private enum CodingKeys: String, CodingKey {
        case slotID = "slotId"
        case target
        case result
        case physicalCommandSent
    }
}

struct MultiSlotUpdateRequest: Encodable {
    let activeSlot: String
    let slots: [String: SlotUpdateBody]
    let autoShow: AutoShowUpdateBody?
}

struct AutoShowUpdateRequest: Encodable {
    let activeSlot: String
    let autoShow: AutoShowUpdateBody
}

struct ProductionShowModeRequest: Encodable {
    let productionShowMode: String
}

struct TriggerCueRequest: Encodable {
    let cueID: String
}

struct TransportUpdateRequest: Encodable {
    let mode: String
    let manualPhrase: String
    let idleAnimationEnabled: Bool
}

struct StructureBehaviorUpdateRequest: Encodable {
    let source: String
}

struct StructureBehaviorUpdateResponse: Decodable {
    let selectedSource: String
}

struct AutoShowUpdateBody: Encodable {
    let enabled: Bool
    let style: String
    let previewRmeMode: String
    let audiencePanFocusEnabled: Bool
    let audiencePanMin: Int
    let audiencePanMax: Int
    let audienceTurnPanMin: Int
    let audienceTurnPanMax: Int
    let audienceTiltSplit: Int
    let overrideColor: String
    let overrideColorCombo: String
    let overrideManualStrobe: Bool
    let overrideAudienceSweep: Bool
    let overrideAllOn: Bool
    let overrideParChase: Bool
    let overrideParSnake: Bool
}

struct SlotUpdateBody: Encodable {
    let enabled: Bool
    let fixture: String
    let mode: String
    let address: Int
    let group: String
    let syncEnabled: Bool
    let beatPulseEnabled: Bool
    let oscStrobeEnabled: Bool
    let useFinePanTilt: Bool
    let panInvert: Bool
    let tiltInvert: Bool
    let panOffsetDeg: Int
    let tiltOffsetDeg: Int
    let panSpanPercent: Int
    let tiltSpanPercent: Int
    let panLeftValue: Int?
    let panRightValue: Int?
    let tiltBackValue: Int?
    let tiltFrontValue: Int?
    let poseCenter: SlotPose?
    let poseAudienceLeft: SlotPose?
    let poseAudienceCenter: SlotPose?
    let poseAudienceRight: SlotPose?
    let poseCeilingCenter: SlotPose?
    let colorSource: String
    let dimmer: Int
    let strobe: Int
    let program: Int
    let speed: Int
    let extraValues: [String: Int]
    let pan: Int
    let tilt: Int
    let panTiltSpeed: Int
    let beatDepth: Int
    let beatDecayMs: Int
    let color: SlotColorPayload
}

struct SlotColorPayload: Encodable {
    let red: Int
    let green: Int
    let blue: Int
    let white: Int
}

struct SlotCapabilities: Decodable {
    let dimmer: Bool
    let strobe: Bool
    let program: Bool
    let speed: Bool
    let pan: Bool
    let panFine: Bool?
    let tilt: Bool
    let tiltFine: Bool?
    let panTiltSpeed: Bool
    let white: Bool
}

@MainActor
final class SlotEditor: ObservableObject, Identifiable {
    let id: String
    @Published var label: String
    @Published var fixtureID: String
    @Published var fixtureLabel: String
    @Published var modeOptions: [String]
    @Published var groupID = ""

    @Published var enabled = true
    @Published var mode: String
    @Published var address = 1
    @Published var syncEnabled = true
    @Published var beatPulseEnabled = true
    @Published var oscStrobeEnabled = true
    @Published var useFinePanTilt = true
    @Published var colorSource = "manual"
    @Published var panInvert = false
    @Published var tiltInvert = false
    @Published var panOffsetDeg = 0
    @Published var tiltOffsetDeg = 0
    @Published var panSpanPercent = 100
    @Published var tiltSpanPercent = 100
    @Published var panLeftValue = 0
    @Published var panRightValue = 255
    @Published var tiltBackValue = 0
    @Published var tiltFrontValue = 255
    @Published var poseCenter: SlotPose?
    @Published var poseAudienceLeft: SlotPose?
    @Published var poseAudienceCenter: SlotPose?
    @Published var poseAudienceRight: SlotPose?
    @Published var poseCeilingCenter: SlotPose?
    @Published var dimmer = 255
    @Published var strobe = 0
    @Published var program = 0
    @Published var speed = 0
    @Published var extraValues: [String: Int] = [:]
    @Published var extraControls: [FixtureExtraControl] = []
    @Published var pan = 127
    @Published var tilt = 127
    @Published var panTiltSpeed = 0
    @Published var beatDepth = 65
    @Published var beatDecayMs = 180
    @Published var red = 255
    @Published var green = 0
    @Published var blue = 0
    @Published var white = 0
    @Published var rangeText = ""
    @Published var supportsDimmer = true
    @Published var supportsStrobe = true
    @Published var supportsProgram = true
    @Published var supportsSpeed = true
    @Published var supportsPan = false
    @Published var supportsPanFine = false
    @Published var supportsTilt = false
    @Published var supportsTiltFine = false
    @Published var supportsPanTiltSpeed = false
    @Published var supportsWhite = true
    @Published var panRangeDegrees = 540.0
    @Published var tiltRangeDegrees = 180.0

    init(id: String, label: String, fixtureID: String, fixtureLabel: String, modeOptions: [String], mode: String) {
        self.id = id
        self.label = label
        self.fixtureID = fixtureID
        self.fixtureLabel = fixtureLabel
        self.modeOptions = modeOptions
        self.mode = mode
    }

    func syncMetadata(label: String, fixtureID: String, fixtureLabel: String, modeOptions: [String]) {
        self.label = label
        self.fixtureID = fixtureID
        self.fixtureLabel = fixtureLabel
        self.modeOptions = modeOptions
    }

    func apply(_ slot: SlotState, range: SlotRange?, capabilities: SlotCapabilities, fixture: FixtureProfile?) {
        enabled = slot.enabled
        mode = slot.mode
        address = slot.address
        syncEnabled = slot.syncEnabled
        beatPulseEnabled = slot.beatPulseEnabled
        oscStrobeEnabled = slot.oscStrobeEnabled
        useFinePanTilt = slot.useFinePanTilt ?? true
        colorSource = slot.colorSource
        panInvert = slot.panInvert
        tiltInvert = slot.tiltInvert
        panOffsetDeg = slot.panOffsetDeg
        tiltOffsetDeg = slot.tiltOffsetDeg
        panSpanPercent = slot.panSpanPercent
        tiltSpanPercent = slot.tiltSpanPercent
        let resolvedPanRange = max(180.0, fixture?.panRange ?? 540.0)
        let resolvedTiltRange = max(90.0, fixture?.tiltRange ?? 180.0)
        panRangeDegrees = resolvedPanRange
        tiltRangeDegrees = resolvedTiltRange
        let derivedPanRefs = Self.referenceValues(
            axisRange: resolvedPanRange,
            invert: slot.panInvert,
            offsetDeg: slot.panOffsetDeg,
            spanPercent: slot.panSpanPercent
        )
        let derivedTiltRefs = Self.referenceValues(
            axisRange: resolvedTiltRange,
            invert: slot.tiltInvert,
            offsetDeg: slot.tiltOffsetDeg,
            spanPercent: slot.tiltSpanPercent
        )
        panLeftValue = slot.panLeftValue ?? derivedPanRefs.low
        panRightValue = slot.panRightValue ?? derivedPanRefs.high
        tiltBackValue = slot.tiltBackValue ?? derivedTiltRefs.low
        tiltFrontValue = slot.tiltFrontValue ?? derivedTiltRefs.high
        poseCenter = slot.poseCenter
        poseAudienceLeft = slot.poseAudienceLeft
        poseAudienceCenter = slot.poseAudienceCenter
        poseAudienceRight = slot.poseAudienceRight
        poseCeilingCenter = slot.poseCeilingCenter
        groupID = slot.group
        dimmer = slot.dimmer
        strobe = slot.strobe
        program = slot.program
        speed = slot.speed
        let selectedMode = fixture?.modes.first(where: { $0.name.caseInsensitiveCompare(slot.mode) == .orderedSame })
        extraControls = selectedMode?.extraControls ?? []
        extraValues = Dictionary(
            uniqueKeysWithValues: extraControls.map { control in
                (
                    control.id,
                    max(0, min(255, slot.extraValues?[control.id] ?? control.defaultValue))
                )
            }
        )
        pan = slot.pan
        tilt = slot.tilt
        panTiltSpeed = slot.panTiltSpeed
        beatDepth = slot.beatDepth
        beatDecayMs = slot.beatDecayMs
        red = slot.color.red
        green = slot.color.green
        blue = slot.color.blue
        white = slot.color.white
        rangeText = range.map {
            "\($0.fixtureLabel) | DMX \($0.address)-\($0.lastChannel)"
        } ?? "\(fixtureLabel) | ongeldige mode"
        supportsDimmer = capabilities.dimmer
        supportsStrobe = capabilities.strobe
        supportsProgram = capabilities.program
        supportsSpeed = capabilities.speed
        supportsPan = capabilities.pan
        supportsPanFine = capabilities.panFine ?? false
        supportsTilt = capabilities.tilt
        supportsTiltFine = capabilities.tiltFine ?? false
        supportsPanTiltSpeed = capabilities.panTiltSpeed
        supportsWhite = capabilities.white
    }

    private static func referenceValues(axisRange: Double, invert: Bool, offsetDeg: Int, spanPercent: Int) -> (low: Int, high: Int) {
        let halfWidth = 127.5 * max(0.01, Double(spanPercent) / 100.0)
        let midpoint = ((((Double(offsetDeg) / max(axisRange, 1.0)) + 0.5) * 255.0))
        let first = Int((midpoint - halfWidth).rounded())
        let second = Int((midpoint + halfWidth).rounded())
        if invert {
            return (clampDMX(second), clampDMX(first))
        }
        return (clampDMX(first), clampDMX(second))
    }
}

enum LivePreset: String, CaseIterable, Identifiable {
    case warmWash
    case coolWash
    case magentaPop
    case iceWhite
    case phraseDrive
    case moodDrive
    case colorBankDrive
    case beatPush
    case strobeHit
    case focus
    case sweep
    case fanOut
    case blackout

    var id: String { rawValue }

    var title: String {
        switch self {
        case .warmWash: return "Warm Wash"
        case .coolWash: return "Cool Wash"
        case .magentaPop: return "Magenta Pop"
        case .iceWhite: return "Ice White"
        case .phraseDrive: return "Phrase Drive"
        case .moodDrive: return "Mood Drive"
        case .colorBankDrive: return "Color Bank"
        case .beatPush: return "Beat Push"
        case .strobeHit: return "Strobe Hit"
        case .focus: return "Focus"
        case .sweep: return "Sweep"
        case .fanOut: return "Fan Out"
        case .blackout: return "Blackout"
        }
    }

    var subtitle: String {
        switch self {
        case .warmWash: return "manual amber"
        case .coolWash: return "manual cyan"
        case .magentaPop: return "manual pink"
        case .iceWhite: return "clean white"
        case .phraseDrive: return "beat + phrase"
        case .moodDrive: return "mood color"
        case .colorBankDrive: return "bank follow"
        case .beatPush: return "beat accent"
        case .strobeHit: return "white hit"
        case .focus: return "center beam"
        case .sweep: return "wide move"
        case .fanOut: return "spread heads"
        case .blackout: return "lights out"
        }
    }

    var systemImage: String {
        switch self {
        case .warmWash: return "sun.max.fill"
        case .coolWash: return "snowflake"
        case .magentaPop: return "theatermasks.fill"
        case .iceWhite: return "light.beacon.max.fill"
        case .phraseDrive: return "music.note"
        case .moodDrive: return "sparkles"
        case .colorBankDrive: return "paintpalette.fill"
        case .beatPush: return "waveform.path.ecg"
        case .strobeHit: return "bolt.fill"
        case .focus: return "scope"
        case .sweep: return "arrow.left.and.right.righttriangle.left.righttriangle.right.fill"
        case .fanOut: return "point.3.filled.connected.trianglepath.dotted"
        case .blackout: return "moon.fill"
        }
    }
}

enum StageAnchor: String, CaseIterable, Identifiable {
    case p1, mh1, p2, p3, mh2, p4, b1, b2, mh3, mh4

    var id: String { rawValue }

    var title: String { rawValue.uppercased() }

    var defaultWorldPosition: SlotWorldPosition {
        switch self {
        case .p1: return SlotWorldPosition(x: -170, y: 0, z: 300, yawDegrees: defaultYawDegrees)
        case .mh1: return SlotWorldPosition(x: -90, y: 0, z: 300, yawDegrees: defaultYawDegrees)
        case .p2: return SlotWorldPosition(x: -10, y: 0, z: 300, yawDegrees: defaultYawDegrees)
        case .p3: return SlotWorldPosition(x: 110, y: 0, z: 300, yawDegrees: defaultYawDegrees)
        case .mh2: return SlotWorldPosition(x: 190, y: 0, z: 300, yawDegrees: defaultYawDegrees)
        case .p4: return SlotWorldPosition(x: 270, y: 0, z: 300, yawDegrees: defaultYawDegrees)
        case .b1: return SlotWorldPosition(x: -220, y: 180, z: 150, yawDegrees: defaultYawDegrees)
        case .b2: return SlotWorldPosition(x: 220, y: 180, z: 150, yawDegrees: defaultYawDegrees)
        case .mh3: return SlotWorldPosition(x: -380, y: 140, z: 200, yawDegrees: defaultYawDegrees)
        case .mh4: return SlotWorldPosition(x: 380, y: 140, z: 200, yawDegrees: defaultYawDegrees)
        }
    }

    var defaultYawDegrees: Double {
        switch self {
        case .mh3:
            return 55
        case .mh4:
            return -55
        default:
            return 0
        }
    }

    var placementGroup: String {
        switch self {
        case .p1, .p2, .p3, .p4:
            return "PAR / Wash"
        case .mh1, .mh2, .mh3, .mh4:
            return "Moving Head"
        case .b1, .b2:
            return "Bar"
        }
    }
}

@MainActor
final class AppModel: ObservableObject {
    @Published var ports: [PortInfo] = []
    @Published var availableFixtures: [FixtureProfile] = []
    @Published var slotEditors: [SlotEditor] = []
    @Published var slotPreviews: [String: SlotPreview] = [:]
    @Published var manualSmoke: ManualSmokeState?
    @Published private var manualSmokeReleasedAt: Date?
    @Published var venueSpace: VenueSpaceState?
    @Published var fixtureCalibrations: [String: VenueFixtureCalibrationState] = [:]
    @Published var venueWidthMetersText = ""
    @Published var venueForwardDepthMetersText = ""
    @Published var venueRearDepthMetersText = ""
    @Published var audienceTargetHeightMetersText = ""
    @Published var ceilingHeightMetersText = ""
    @Published var venueGeometrySaveInFlight = false
    @Published var calibrationTestSlotID: String?
    @Published var audienceCenterTestResults: [String: VenueTargetResolutionState] = [:]
    @Published var previewVenueTargetResolution: VenueTargetResolutionState?
    @Published var previewVenueTargetResultSet: VenueTargetResultSetState?
    @Published var previewVenueTargetResolutions: [String: VenueTargetResolutionState] = [:]
    @Published var previewVenueTargetSlotID: String?
    @Published var previewVenueTargetSlotIDs = Set<String>()
    @Published var previewVenueTargetStartedAt: Date?
    @Published var previewVenueTargetStartPanDegrees: Double?
    @Published var previewVenueTargetStartTiltDegrees: Double?
    @Published var previewVenueTargetStartEndpoint: SlotWorldPosition?
    @Published var previewVenueTargetStartEndpoints: [String: SlotWorldPosition] = [:]
    @Published var previewVenueTargetStartPanBySlot: [String: Double] = [:]
    @Published var previewVenueTargetStartTiltBySlot: [String: Double] = [:]
    @Published var calibrationTestInFlightSlotID: String?
    @Published var calibrationSaveInFlight = false
    @Published var projectionLayoutSaveInFlight = false
    @Published var selectedVenueTargetZone = "MID"
    @Published var selectedVenueTargetPosition = "CENTER"
    @Published var selectedVenueTarget = "AUDIENCE_MID_CENTER"
    @Published var selectedVenueTargetVerticalLayer = "NORMAL"
    @Published var venueTargetTestState: VenueTargetTestAuthorityState?
    @Published var movementLabState: MovementLabState?
    @Published var movementLabEffectID = "fast_audience_circle"
    @Published var movementLabSection = "chorus"
    @Published var movementLabVariation = 0
    @Published var movementLabInFlight = false
    @Published var venueTargetTestStatusText = "READY • Select a target, then move when every physical safety gate passes."
    @Published var venueTargetTestInFlight = false
    @Published var aimCalibrationGranularity = "FINE"
    @Published var aimCalibrationInFlight = false
    @Published var axisMappingV2InFlight = false
    private var venueTargetLeaseTask: Task<Void, Never>?
    @Published var stageMotionStates: [String: StageMotionState] = [:]
    private var venueGeometryFieldsInitialized = false
    @Published var dmxSlotOrder: [String] = []
    @Published var dmxSlotRanges: [String: SlotRange] = [:]
    @Published var dmxValues: [Int: Int] = [:]
    @Published var dmxConflicts: [ChannelConflict] = []
    @Published var mapAssignments: [String: String] = [:]
    @Published var projectionLayouts: [String: SlotWorldPosition] = [:]
    @Published var projectionLayoutDrafts: [String: SlotWorldPosition] = [:]
    /// Explicit SwiftUI render dependency for the persistent, view-only
    /// camera centers. A paused TimelineView does not observe UserDefaults by
    /// itself, so every camera mutation advances this token.
    @Published private(set) var metricStageMapViewportRevision = 0
    /// Global Stage Map editor preference. It is deliberately UI-only and is
    /// never included in venue geometry or fixture calibration payloads.
    @Published var fixtureSnapEnabled = true {
        didSet {
            UserDefaults.standard.set(fixtureSnapEnabled, forKey: mapFixtureSnapEnabledDefaultsKey)
        }
    }
    @Published var frontProjectionMirrored = false {
        didSet {
            saveFrontProjectionMirrored()
            invalidateMetricStageMapViewport()
        }
    }
    @Published var topProjectionRotationQuarterTurns = 0 {
        didSet {
            saveTopProjectionRotation()
            invalidateMetricStageMapViewport()
        }
    }
    @Published var isEditingProjectionLayout = false
    @Published var isFixtureCalibrationMode = false
    @Published var previewSelectedSlotIDs: Set<String> = []
    @Published var selectedSlotID = ""
    @Published var selectedPortLabel = "" {
        didSet { saveSelectedPortLabel() }
    }
    @Published var dmxStatus = "DMX niet verbonden"
    @Published var oscStatus = "OSC wacht op data"
    @Published var oscSourceStatus = "Transport wacht op OSC of interne clock"
    @Published var trackTitle = "(geen track)"
    @Published var trackMeta = "onbekend"
    @Published var deck1Title = "Deck 1"
    @Published var deck1Meta = "(geen track)"
    @Published var deck1Time = "-"
    @Published var deck1IsActive = false
    @Published var deck2Title = "Deck 2"
    @Published var deck2Meta = "(geen track)"
    @Published var deck2Time = "-"
    @Published var deck2IsActive = false
    @Published var bpmValue = "-"
    @Published var beatValue = "-"
    @Published var barValue = "-"
    @Published var timeValue = "-"
    @Published var moodValue = "-"
    @Published var transportMode = "auto"
    @Published var transportResolvedMode = "external_osc"
    @Published var transportManualBpm = 124.0
    @Published var transportEffectiveBpm: Double?
    @Published var transportManualPhrase = "verse"
    @Published var transportManualPhraseLabel = "Verse"
    @Published var transportIdleAnimationEnabled = true
    @Published var transportTapCount = 0
    @Published var transportTapLocked = false
    @Published var transportExternalAvailable = false
    @Published var transportStatusText = "External OSC actief"
    @Published var structureBehaviorSource = "legacy"
    @Published var liveAudioDevices: [AudioInputDevice] = []
    @Published var selectedLiveAudioDeviceID: UInt32 = 0 {
        didSet { saveSelectedLiveAudioDeviceID() }
    }
    @Published var liveAudioEnabled = false {
        didSet { saveLiveAudioEnabled() }
    }
    @Published var liveAudioStatusText = "Live audio uit"
    @Published var bridgeScriptPath = defaultRekordboxBridgeScriptPath() {
        didSet { saveBridgeScriptPath() }
    }
    @Published var bridgeRunning = false
    @Published var bridgePasswordlessEnabled = false
    @Published var bridgeStatusText = "Rekordbox bridge uit"
    @Published var waveformEnergyValue = "-"
    @Published var waveformStatusText = "Waveform wacht op data"
    @Published var waveformInfluenceText = "Nog geen waveform-feedback"
    @Published var waveformHistory: [Double] = []
    @Published var waveformBandLow: Double?
    @Published var waveformBandMid: Double?
    @Published var waveformBandHigh: Double?
    @Published var waveformLookahead2Low: Double?
    @Published var waveformLookahead2Mid: Double?
    @Published var waveformLookahead2High: Double?
    @Published var waveformLookahead4Low: Double?
    @Published var waveformLookahead4Mid: Double?
    @Published var waveformLookahead4High: Double?
    @Published var waveformAnticipation: Double?
    @Published var drumKick: Double?
    @Published var drumSnare: Double?
    @Published var drumHihat: Double?
    @Published var phraseCurrentValue = "-"
    @Published var phraseNextValue = "-"
    @Published var phraseCountValue = "-"
    @Published var phraseEtaValue = "-"
    @Published var playbackSummary = "BPM -   Beat -   Time -"
    @Published var phraseSummary = "Phrase - -> -   Count-in -   ETA -"
    @Published var universeSummary = "Geen actieve kanalen"
    @Published var conflictSummary = "Geen kanaalconflicten"
    @Published var rawValuesText = "Geen actieve DMX-waarden."
    @Published var renderedMotionSummary = "Geen final-motionprojectie beschikbaar."
    @Published var virtualDjBeatPulsePreviewEnabled = false
    @Published var virtualDjBeatPulsePreviewStatus = "Visuele VirtualDJ-test uit"
    @Published var activeLivePreset: LivePreset?
    @Published var autoShowEnabled = false
    @Published var autoShowAvailable = false
    @Published var autoShowStyle = "adaptive"
    @Published var autoShowStyleLabel = "Adaptive"
    @Published var previewRmeMode = "BASELINE"
    @Published var previewPulseTestMode = "OFF"
    @Published var previewComposition: PreviewCompositionState?
    @Published var simulatorTracks: [SimulatorTrack] = []
    @Published var simulatorState: SimulatorState?
    @Published var simulatorSlotPreviews: [String: SlotPreview] = [:]
    @Published var renderedMotion: [String: RenderedMotionState] = [:]

    /// The stage maps are read-only consumers.  When the simulator is active,
    /// they deliberately render its isolated preview frame instead of live DMX.
    var presentedSlotPreviews: [String: SlotPreview] {
        guard simulatorState?.mode == "SIMULATION", !simulatorSlotPreviews.isEmpty else {
            return slotPreviews
        }
        return simulatorSlotPreviews
    }

    func smokePreviewIntensity(at date: Date = Date()) -> Double {
        if let smoke = manualSmoke, smoke.active, smoke.resolvedDmxValue > 0 {
            return Double(smoke.resolvedDmxValue) / 255.0
        }
        guard let releasedAt = manualSmokeReleasedAt else { return 0 }
        return max(0, 1 - date.timeIntervalSince(releasedAt) / 0.55) * 0.72
    }

    private func reconcileManualSmoke(_ next: ManualSmokeState?) {
        let previousWasVisible = (manualSmoke?.resolvedDmxValue ?? 0) > 0 && manualSmoke?.active == true
        let nextIsVisible = (next?.resolvedDmxValue ?? 0) > 0 && next?.active == true
        if previousWasVisible && !nextIsVisible { manualSmokeReleasedAt = Date() }
        if nextIsVisible { manualSmokeReleasedAt = nil }
        manualSmoke = next
    }

    var presentedStageMotionStates: [String: StageMotionState] {
        var states = simulatorState?.mode == "SIMULATION" ? [:] : stageMotionStates
        if simulatorState?.mode != "SIMULATION" {
            for (slotID, motion) in renderedMotion where motion.supported && motion.available && motion.status == "AVAILABLE" {
                guard let direction = motion.worldDirection else { continue }
                let existing = states[slotID]
                let preview = slotPreviews[slotID]
                states[slotID] = StageMotionState(
                    currentPanDegrees: motion.physicalPanDegrees ?? existing?.currentPanDegrees ?? preview?.logicalPanDegrees ?? 0,
                    currentTiltDegrees: motion.physicalTiltDegrees ?? existing?.currentTiltDegrees ?? preview?.logicalTiltDegrees ?? 0,
                    targetPanDegrees: motion.physicalPanDegrees ?? existing?.targetPanDegrees ?? preview?.logicalTargetPanDegrees ?? 0,
                    targetTiltDegrees: motion.physicalTiltDegrees ?? existing?.targetTiltDegrees ?? preview?.logicalTargetTiltDegrees ?? 0,
                    panRange: existing?.panRange ?? preview?.panRange ?? 540,
                    tiltRange: existing?.tiltRange ?? preview?.tiltRange ?? 180,
                    estimatedSpeedDegreesPerSecond: existing?.estimatedSpeedDegreesPerSecond ?? 0,
                    trail: [],
                    updatedAt: Date().timeIntervalSinceReferenceDate,
                    worldDirection: direction
                )
            }
        }
        guard let startedAt = previewVenueTargetStartedAt else { return states }
        let progress = min(1.0, max(0.0, Date().timeIntervalSince(startedAt) / 0.65))
        let eased = progress * progress * (3.0 - 2.0 * progress)
        for (slotID, resolution) in previewVenueTargetResolutions {
            guard
                resolution.status == "RESOLVED",
                let targetPan = resolution.panDegrees,
                let targetTilt = resolution.tiltDegrees
            else { continue }
            let existing = states[slotID]
            let panRange = existing?.panRange ?? 540
            let tiltRange = existing?.tiltRange ?? 180
            let startPan = previewVenueTargetStartPanBySlot[slotID] ?? existing?.currentPanDegrees ?? 0
            let startTilt = previewVenueTargetStartTiltBySlot[slotID] ?? existing?.currentTiltDegrees ?? 0
            let currentPan = startPan + (targetPan - startPan) * eased
            let currentTilt = startTilt + (targetTilt - startTilt) * eased
            states[slotID] = StageMotionState(
                currentPanDegrees: currentPan,
                currentTiltDegrees: currentTilt,
                targetPanDegrees: targetPan,
                targetTiltDegrees: targetTilt,
                panRange: panRange,
                tiltRange: tiltRange,
                estimatedSpeedDegreesPerSecond: max(120, existing?.estimatedSpeedDegreesPerSecond ?? 240),
                trail: [
                    StageBeamPose(panDegrees: startPan, tiltDegrees: startTilt),
                    StageBeamPose(panDegrees: currentPan, tiltDegrees: currentTilt),
                ],
                updatedAt: Date().timeIntervalSinceReferenceDate,
                worldDirection: existing?.worldDirection
            )
        }
        return states
    }

    /// Returns a direct world-space endpoint for the active preview target.
    /// The resolver remains authoritative for physical pan/tilt; this is only
    /// the equivalent visual endpoint for the existing fixture beam.
    func venueTargetPreviewVisual(for slotID: String) -> VenueTargetPreviewVisual? {
        guard
            previewVenueTargetSlotIDs.contains(slotID),
            previewVenueTargetResolutions[slotID]?.status == "RESOLVED",
            let startedAt = previewVenueTargetStartedAt,
            let target = venueSpace?.targets.first(where: { $0.id == selectedVenueTarget }),
            let startEndpoint = previewVenueTargetStartEndpoints[slotID]
        else { return nil }

        guard let physicalTarget = target.physicalPointM else { return nil }

        let endpoint = SlotWorldPosition(
            x: physicalTarget.x * 100,
            y: physicalTarget.y * 100,
            z: physicalTarget.z * 100
        )
        let progress = min(1.0, max(0.0, Date().timeIntervalSince(startedAt) / 0.65))
        return VenueTargetPreviewVisual(
            startEndpoint: startEndpoint,
            endpoint: endpoint,
            progress: progress
        )
    }
    @Published var autoShowCueText = "Auto Show uit"
    @Published var autoShowDetailText = "Zet Auto Show aan om phrase- en beat-gestuurde output te laten spelen."
    @Published var autoShowAudiencePanFocusEnabled = true
    @Published var autoShowAudiencePanMin = 135
    @Published var autoShowAudiencePanMax = 205
    @Published var autoShowAudienceTurnPanMin = 50
    @Published var autoShowAudienceTurnPanMax = 120
    @Published var autoShowAudienceTiltSplit = 127
    @Published var liveOverrideColor = "none"
    @Published var liveOverrideColorLabel = "Auto"
    @Published var liveOverrideColorCombo = "none"
    @Published var liveOverrideManualStrobe = false
    @Published var liveOverrideAudienceSweep = false
    @Published var liveOverrideAllOn = false
    @Published var liveOverrideParChase = false
    @Published var liveOverrideParSnake = false
    @Published var liveOneShotCue = "none"
    @Published var liveOneShotCueLabel = "None"
    @Published var liveOneShotCueProgress = 0.0
    @Published var remoteURLText = "-"
    /// Optional overlay-network route. Keep this separate from the normal
    /// preferred LAN/USB route so either pairing workflow remains explicit.
    @Published var remoteTailscaleURLText = "-"
    @Published var remoteStatusText = "Remote niet beschikbaar"
    @Published var remotePairingCodeText = "-"
    @Published var errorText = ""
    @Published var debugState: DebugState?
    @Published private(set) var liveUiState: LiveUiState?
    @Published private(set) var liveIntensityState: LiveIntensityState?
    @Published private(set) var physicalDmxConnected = false
    @Published private(set) var physicalDmxError: String?
    @Published private(set) var blackoutActive = false
    @Published private(set) var physicalOutputSource = "auto_show -> current_values"
    @Published private(set) var productionShowSource = "existing_autoshow"
    @Published private(set) var productionShowMode = "BASELINE_ONLY"
    @Published private(set) var productionFallbackActive = false
    @Published private(set) var productionFallbackReason: String?

    private var baseURL: URL {
        URL(string: "http://127.0.0.1:\(beatBeamBackendPort)")!
    }
    private var backendProcess: Process?
    private var ownedBackendPID: Int?
    private var ownsBackend = false
    private var pollingTask: Task<Void, Never>?
    private var stageSimulationTimer: Timer?
    private var started = false
    private var editorsByID: [String: SlotEditor] = [:]
    private var livePresetRestoreSlots: [String: SlotUpdateBody]?
    private var livePresetRestoreAutoShow: AutoShowUpdateBody?
    private var ignorePolledStateUntil = Date.distantPast
    private var pendingAutoShowRequest: AutoShowUpdateBody?
    private var pendingAutoShowDeadline = Date.distantPast
    private var slotPushTasks: [String: Task<Void, Never>] = [:]
    private var slotPushTokens: [String: Int] = [:]
    private var nextSlotPushToken = 1
    private var previewClockAnchorDate = Date()
    private var previewClockSourceSeconds: TimeInterval?
    private var previewClockBeatValue: Double?
    private var previewClockBpm: Double?
    private let liveAudioBridge = BeatBeamLiveAudioBridge()
    private var bridgeStateTask: Task<Void, Never>?
    private var lastBridgeCheckAt = Date.distantPast
    private let mapAssignmentsDefaultsKey = defaultsKey("mapAssignments")
    private let projectionLayoutsDefaultsKey = defaultsKey("worldPositions")
    private let legacyProjectionLayoutsDefaultsKey = defaultsKey("projectionLayouts")
    private let selectedPortDefaultsKey = defaultsKey("selectedPortLabel")
    private let liveAudioDeviceDefaultsKey = defaultsKey("liveAudioDeviceID")
    private let liveAudioEnabledDefaultsKey = defaultsKey("liveAudioEnabled")
    private let bridgeScriptDefaultsKey = defaultsKey("bridgeScriptPath")

    init() {
        if let storedSnap = UserDefaults.standard.object(forKey: mapFixtureSnapEnabledDefaultsKey) as? Bool {
            fixtureSnapEnabled = storedSnap
        }
        loadMapAssignments()
        loadProjectionLayouts()
        loadFrontProjectionMirrored()
        loadTopProjectionRotation()
        loadSelectedPortLabel()
        loadSelectedLiveAudioDeviceID()
        loadLiveAudioEnabled()
        loadBridgeScriptPath()
        liveAudioBridge.onStatus = { [weak self] text in
            Task { @MainActor in
                self?.liveAudioStatusText = text
            }
        }
    }

    func start() {
        guard !started else { return }
        started = true
        Task {
            await bootstrap()
        }
    }

    func stop() {
        pollingTask?.cancel()
        pollingTask = nil
        stageSimulationTimer?.invalidate()
        stageSimulationTimer = nil
        cancelPendingSlotPushes()
        liveAudioBridge.stop()
        bridgeStateTask?.cancel()
        bridgeStateTask = nil
        _ = stopRekordboxBridgeSynchronouslyForShutdown()
        bridgeRunning = false
        bridgeStatusText = "Rekordbox bridge uit"
        terminateOwnedBackendIfNeeded()
        started = false
    }

    func openRemoteURL() {
        guard let url = URL(string: remoteURLText), url.scheme?.hasPrefix("http") == true else { return }
        NSWorkspace.shared.open(url)
    }

    func copyTailscaleRemoteURL() {
        guard remoteTailscaleURLText != "-" else { return }
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(remoteTailscaleURLText, forType: .string)
    }

    func refreshDebugState() {
        Task { try? await refreshState() }
    }

    func loadSimulator() {
        Task { do {
            let response: SimulatorTracksResponse = try await get("/api/simulator/tracks", as: SimulatorTracksResponse.self)
            simulatorTracks = response.tracks
            applySimulator(try await get("/api/simulator/state", as: SimulatorState.self))
        } catch { errorText = "Simulator kon analyses niet laden: \(error.localizedDescription)" } }
    }
    func simulatorSelect(_ path: String) { simulatorPost("/api/simulator/select", body: ["path": path]) }
    func simulatorPlay() { simulatorPost("/api/simulator/play", body: EmptyRequest()) }
    func simulatorPause() { simulatorPost("/api/simulator/pause", body: EmptyRequest()) }
    func simulatorRestart() { simulatorPost("/api/simulator/restart", body: EmptyRequest()) }
    func simulatorSeek(milliseconds: Int) { simulatorPost("/api/simulator/seek", body: ["seconds": Double(milliseconds) / 1000.0]) }
    func simulatorJumpCue(_ role: String) { simulatorPost("/api/simulator/jump-cue", body: ["role": role]) }
    func simulatorNavigate(_ path: String) { simulatorPost(path, body: EmptyRequest()) }
    private func simulatorPost<Body: Encodable>(_ path: String, body: Body) {
        Task { do { applySimulator(try await post(path, body: body, as: SimulatorState.self)) }
               catch { errorText = "Simulatoractie mislukt: \(error.localizedDescription)" } }
    }
    private func applySimulator(_ state: SimulatorState) { simulatorState = state; simulatorSlotPreviews = state.simulationSlotPreviews }

    func forceReanalyzeActiveTrack() async throws -> DebugForceReanalysisResponse {
        try await post("/api/developer/force-reanalyze-active-track", body: EmptyRequest(), as: DebugForceReanalysisResponse.self)
    }

    func copyRemoteURL() {
        guard remoteURLText != "-" else { return }
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(remoteURLText, forType: .string)
    }

    func refreshAudioInputs() {
        let devices = listAudioInputDevices()
        liveAudioDevices = devices
        if selectedLiveAudioDeviceID == 0 || !devices.contains(where: { $0.id == selectedLiveAudioDeviceID }) {
            if let blackHole = devices.first(where: { $0.name.localizedCaseInsensitiveContains("blackhole") }) {
                selectedLiveAudioDeviceID = blackHole.id
            } else {
                selectedLiveAudioDeviceID = devices.first?.id ?? 0
            }
        }
        if liveAudioEnabled {
            restartLiveAudioBridge()
        } else if let current = selectedLiveAudioDevice() {
            liveAudioStatusText = "Geselecteerd: \(audioDeviceName(current))"
        } else {
            liveAudioStatusText = "Geen live audio input"
        }
    }

    func setSelectedLiveAudioDevice(_ deviceID: UInt32) {
        if deviceID == selectedLiveAudioDeviceID { return }
        selectedLiveAudioDeviceID = deviceID
        if liveAudioEnabled {
            restartLiveAudioBridge()
        } else if let current = selectedLiveAudioDevice() {
            liveAudioStatusText = "Geselecteerd: \(audioDeviceName(current))"
        }
    }

    func setLiveAudioEnabled(_ enabled: Bool) {
        if enabled == liveAudioEnabled { return }
        liveAudioEnabled = enabled
        if enabled {
            restartLiveAudioBridge()
        } else {
            liveAudioBridge.stop()
            liveAudioStatusText = "Live audio uit"
        }
    }

    func startRekordboxBridge() {
        let scriptPath = bridgeScriptPath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !scriptPath.isEmpty else {
            bridgeStatusText = "Bridge script pad is leeg"
            return
        }
        guard FileManager.default.isExecutableFile(atPath: scriptPath) else {
            bridgeStatusText = "Bridge script niet uitvoerbaar"
            return
        }

        bridgeStatusText = "Rekordbox bridge start..."
        let oscDestination = "127.0.0.1:\(defaultBackendOscPort)"
        let passwordlessReady = bridgeCanUsePasswordlessSudo(scriptPath: scriptPath, oscDestination: oscDestination)
        bridgePasswordlessEnabled = passwordlessReady
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard self != nil else { return }
            let result: (ok: Bool, message: String)
            if passwordlessReady {
                result = launchSystemProcess("/usr/bin/sudo", ["-n", scriptPath, oscDestination])
            } else {
                let command = "\(shellSingleQuote(scriptPath)) \(oscDestination) >/tmp/rkbx_bridge_gui.log 2>&1 &"
                result = runAdministratorShell(command)
            }
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                if result.ok {
                    self.bridgeStatusText = "Rekordbox bridge actief"
                    self.refreshBridgeStatus(force: true)
                } else {
                    self.bridgeStatusText = "Bridge start mislukt"
                    if !result.message.isEmpty {
                        self.errorText = "Bridge start mislukt: \(result.message)"
                    }
                }
            }
        }
    }

    func stopRekordboxBridge() {
        bridgeStatusText = "Rekordbox bridge stopt..."
        let passwordlessReady = bridgeCanUsePasswordlessSudo(scriptPath: bridgeScriptPath.trimmingCharacters(in: .whitespacesAndNewlines), oscDestination: "127.0.0.1:\(defaultBackendOscPort)")
        bridgePasswordlessEnabled = passwordlessReady
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard self != nil else { return }
            let result: (ok: Bool, message: String)
            if passwordlessReady {
                result = Self.stopBridgeProcessesSynchronously(passwordlessReady: true)
            } else {
                result = runAdministratorShell("/usr/bin/pkill -f rkbx_link || true")
            }
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                if !result.ok, self.isBridgeProcessRunning(), !result.message.isEmpty {
                    self.errorText = "Bridge stop mislukt: \(result.message)"
                }
                self.refreshBridgeStatus(force: true)
            }
        }
    }

    private func stopRekordboxBridgeSynchronouslyForShutdown() -> (ok: Bool, message: String) {
        let scriptPath = bridgeScriptPath.trimmingCharacters(in: .whitespacesAndNewlines)
        let oscDestination = "127.0.0.1:\(defaultBackendOscPort)"
        let passwordlessReady = bridgeCanUsePasswordlessSudo(scriptPath: scriptPath, oscDestination: oscDestination)
        return Self.stopBridgeProcessesSynchronously(passwordlessReady: passwordlessReady)
    }

    nonisolated private static func stopBridgeProcessesSynchronously(passwordlessReady: Bool) -> (ok: Bool, message: String) {
        if passwordlessReady {
            return runSystemProcess("/usr/bin/sudo", ["-n", "/usr/bin/pkill", "-f", "rkbx_link"])
        }

        return runSystemProcess("/usr/bin/pkill", ["-f", "rkbx_link"])
    }

    func refreshBridgeStatus(force: Bool = false) {
        let now = Date()
        if !force, now.timeIntervalSince(lastBridgeCheckAt) < 2.0 {
            return
        }
        lastBridgeCheckAt = now
        bridgeStateTask?.cancel()
        let scriptPath = bridgeScriptPath.trimmingCharacters(in: .whitespacesAndNewlines)
        let oscDestination = "127.0.0.1:\(defaultBackendOscPort)"
        bridgeStateTask = Task {
            let running = await Task.detached(priority: .utility) {
                (
                    self.isBridgeProcessRunning(),
                    self.bridgeCanUsePasswordlessSudo(scriptPath: scriptPath, oscDestination: oscDestination)
                )
            }.value
            guard !Task.isCancelled else { return }
            bridgeRunning = running.0
            bridgePasswordlessEnabled = running.1
            if running.0 {
                bridgeStatusText = "Rekordbox bridge actief"
            } else if running.1 {
                bridgeStatusText = "Rekordbox bridge uit · zonder prompt klaar"
            } else {
                bridgeStatusText = "Rekordbox bridge uit · wachtwoordpad actief"
            }
        }
    }

    func connectDMX() {
        guard let device = selectedPortDevice() else {
            errorText = "Geen DMX-poort geselecteerd."
            return
        }
        Task {
            do {
                beginLocalMutationHold()
                let request = ConnectRequest(port: device, fps: 30)
                let state: AppState = try await post("/api/dmx/connect", body: request, as: AppState.self)
                apply(state, source: .action)
                errorText = ""
            } catch {
                errorText = "DMX connectie mislukt: \(error.localizedDescription)"
            }
        }
    }

    private func selectedLiveAudioDevice() -> AudioDeviceID? {
        let rawID = selectedLiveAudioDeviceID
        guard rawID != 0 else { return nil }
        return AudioDeviceID(rawID)
    }

    private func restartLiveAudioBridge() {
        guard liveAudioEnabled else { return }
        guard let inputDeviceID = selectedLiveAudioDevice() else {
            liveAudioStatusText = "Geen live audio input"
            return
        }
        do {
            try liveAudioBridge.start(inputDeviceID: inputDeviceID, oscPort: defaultBackendOscPort)
        } catch {
            liveAudioEnabled = false
            liveAudioStatusText = "Live audio fout: \(error.localizedDescription)"
        }
    }

    nonisolated private func isBridgeProcessRunning() -> Bool {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/pgrep")
        process.arguments = ["-f", "rkbx_link|start_bridge\\.sh"]
        do {
            try process.run()
            process.waitUntilExit()
            return process.terminationStatus == 0
        } catch {
            return false
        }
    }

    func disconnectDMX() {
        Task {
            do {
                beginLocalMutationHold()
                let state: AppState = try await post("/api/dmx/disconnect", body: EmptyRequest(), as: AppState.self)
                apply(state, source: .action)
                errorText = ""
            } catch {
                errorText = "DMX disconnectie mislukt: \(error.localizedDescription)"
            }
        }
    }

    func reconnectDMX() {
        guard let device = selectedPortDevice() else {
            errorText = "Geen DMX-poort geselecteerd."
            return
        }
        Task {
            do {
                beginLocalMutationHold()
                _ = try await post("/api/dmx/disconnect", body: EmptyRequest(), as: AppState.self)
                let state: AppState = try await post(
                    "/api/dmx/connect",
                    body: ConnectRequest(port: device, fps: 30),
                    as: AppState.self
                )
                apply(state, source: .action)
                errorText = ""
            } catch {
                errorText = "DMX opnieuw verbinden mislukt: \(error.localizedDescription)"
            }
        }
    }

    func blackout() {
        Task {
            do {
                beginLocalMutationHold()
                let state: AppState = try await post("/api/dmx/blackout", body: EmptyRequest(), as: AppState.self)
                apply(state, source: .action)
                activeLivePreset = nil
                clearLivePresetRestoreState()
                errorText = ""
            } catch {
                errorText = "Blackout mislukt: \(error.localizedDescription)"
            }
        }
    }

    func startVirtualDjBeatPulsePreview() {
        let slotID = selectedSlotID.isEmpty ? (slotEditors.first?.id ?? "") : selectedSlotID
        guard !slotID.isEmpty else {
            errorText = "Kies eerst een fixture voor de visuele VirtualDJ-test."
            return
        }
        Task {
            do {
                let request = VirtualDjBeatPulsePreviewRequest(
                    slotID: slotID,
                    durationMilliseconds: 100
                )
                let state: VirtualDjBeatPulsePreviewState = try await post(
                    "/api/developer/virtualdj-beat-pulse-preview/start",
                    body: request,
                    as: VirtualDjBeatPulsePreviewState.self
                )
                applyVirtualDjBeatPulsePreview(state)
                errorText = ""
            } catch {
                errorText = "Visuele VirtualDJ-test starten mislukt: (error.localizedDescription)"
            }
        }
    }

    func stopVirtualDjBeatPulsePreview() {
        Task {
            do {
                let state: VirtualDjBeatPulsePreviewState = try await post(
                    "/api/developer/virtualdj-beat-pulse-preview/stop",
                    body: EmptyRequest(),
                    as: VirtualDjBeatPulsePreviewState.self
                )
                applyVirtualDjBeatPulsePreview(state)
                errorText = ""
            } catch {
                errorText = "Visuele VirtualDJ-test stoppen mislukt: (error.localizedDescription)"
            }
        }
    }

    func refreshPorts() {
        Task {
            do {
                try await loadPorts()
                errorText = ""
            } catch {
                errorText = "Poorten laden mislukt: \(error.localizedDescription)"
            }
        }
    }

    func addSlot(fixtureID: String, mode: String? = nil) {
        Task {
            do {
                beginLocalMutationHold()
                let request = AddSlotRequest(fixtureID: fixtureID, mode: mode)
                let state: AppState = try await post("/api/dmx/add-slot", body: request, as: AppState.self)
                apply(state, forceSelectionToActiveSlot: true, source: .action)
                activeLivePreset = nil
                clearLivePresetRestoreState()
                errorText = ""
            } catch {
                errorText = "Fixture toevoegen mislukt: \(error.localizedDescription)"
            }
        }
    }

    func removeSlot(_ slotID: String) {
        guard !slotID.isEmpty else { return }
        guard slotEditors.count > 1 else {
            errorText = "De laatste fixture kan niet worden verwijderd."
            return
        }
        slotPushTasks[slotID]?.cancel()
        slotPushTasks.removeValue(forKey: slotID)
        slotPushTokens.removeValue(forKey: slotID)
        previewSelectedSlotIDs.remove(slotID)
        mapAssignments.removeValue(forKey: slotID)
        saveMapAssignments()
        activeLivePreset = nil
        clearLivePresetRestoreState()
        Task {
            do {
                beginLocalMutationHold()
                let request = RemoveSlotRequest(slotID: slotID)
                let state: AppState = try await post("/api/dmx/remove-slot", body: request, as: AppState.self)
                apply(state, source: .action)
                errorText = ""
            } catch {
                errorText = "Fixture verwijderen mislukt: \(error.localizedDescription)"
            }
        }
    }

    func selectSlot(_ slotID: String) {
        if venueTargetTestState?.active == true, selectedSlotID != slotID {
            releaseVenueTargetTest()
        }
        selectedSlotID = slotID
    }

    func togglePreviewSelection(_ slotID: String) {
        guard let editor = editorsByID[slotID], editor.supportsPan || editor.supportsTilt else { return }
        if previewSelectedSlotIDs.contains(slotID) {
            previewSelectedSlotIDs.remove(slotID)
        } else {
            previewSelectedSlotIDs.insert(slotID)
        }
    }

    func clearPreviewSelection() {
        previewSelectedSlotIDs.removeAll()
    }

    func previewSelectionContains(_ slotID: String) -> Bool {
        previewSelectedSlotIDs.contains(slotID)
    }

    var previewSelectedMovingHeadEditors: [SlotEditor] {
        slotEditors.filter { previewSelectedSlotIDs.contains($0.id) && ($0.supportsPan || $0.supportsTilt) }
    }

    func setAutoShowEnabled(_ enabled: Bool) {
        if enabled == autoShowEnabled { return }
        activeLivePreset = nil
        clearLivePresetRestoreState()
        beginLocalMutationHold(seconds: 1.2)
        autoShowEnabled = enabled
        autoShowCueText = enabled ? "\(autoShowStyleLabel) • starting" : "Auto Show uit"
        let request = currentAutoShowUpdateBody(enabled: enabled, style: autoShowStyle)
        setPendingAutoShowRequest(request)
        postAutoShow(request)
    }

    func setAutoShowStyle(_ style: String) {
        if style == autoShowStyle { return }
        beginLocalMutationHold(seconds: 1.2)
        autoShowStyle = style
        autoShowStyleLabel = label(forAutoShowStyle: style)
        if autoShowEnabled {
            autoShowCueText = "\(autoShowStyleLabel) • updating"
        } else {
            autoShowCueText = "\(autoShowStyleLabel) • ready"
        }
        let request = currentAutoShowUpdateBody(enabled: autoShowEnabled, style: style)
        setPendingAutoShowRequest(request)
        postAutoShow(request)
    }

    func enableDynamicComposerProduction() {
        setProductionShowMode("DYNAMIC_COMPOSER_ENABLED")
    }

    func revertProductionToBaseline() {
        setProductionShowMode("BASELINE_ONLY")
    }

    private func setProductionShowMode(_ mode: String) {
        let normalized = mode == "DYNAMIC_COMPOSER_ENABLED" ? mode : "BASELINE_ONLY"
        Task {
            do {
                let state: AppState = try await post(
                    "/api/dmx/production-mode",
                    body: ProductionShowModeRequest(productionShowMode: normalized),
                    as: AppState.self
                )
                apply(state, source: .action)
                errorText = ""
            } catch {
                errorText = "Production source wijzigen mislukt: \(error.localizedDescription)"
            }
        }
    }

    func setPreviewRmeMode(_ mode: String) {
        let normalized = ["RME_ENHANCED", "DYNAMIC_COMPOSER"].contains(mode) ? mode : "BASELINE"
        if normalized == previewRmeMode { return }
        beginLocalMutationHold(seconds: 1.2)
        previewRmeMode = normalized
        let request = currentAutoShowUpdateBody()
        setPendingAutoShowRequest(request)
        postAutoShow(request)
    }

    func setPreviewPulseTestMode(_ mode: String) {
        let normalized = ["EVERY_BEAT", "HALF_TIME", "BAR_ACCENT"].contains(mode) ? mode : "OFF"
        Task {
            do {
                let state: AppState = try await post("/api/developer/preview-pulse-test", body: ["mode": normalized], as: AppState.self)
                apply(state, source: .action)
            } catch { errorText = "Pulse Test wijzigen mislukt: \(error.localizedDescription)" }
        }
    }

    func setAutoShowAudiencePanFocusEnabled(_ enabled: Bool) {
        if enabled == autoShowAudiencePanFocusEnabled { return }
        beginLocalMutationHold(seconds: 1.2)
        autoShowAudiencePanFocusEnabled = enabled
        let request = currentAutoShowUpdateBody()
        setPendingAutoShowRequest(request)
        postAutoShow(request)
    }

    func setAutoShowAudiencePanMin(_ value: Int) {
        let clamped = min(max(value, 0), autoShowAudiencePanMax)
        if clamped == autoShowAudiencePanMin { return }
        beginLocalMutationHold(seconds: 1.2)
        autoShowAudiencePanMin = clamped
        let request = currentAutoShowUpdateBody()
        setPendingAutoShowRequest(request)
        postAutoShow(request)
    }

    func setAutoShowAudiencePanMax(_ value: Int) {
        let clamped = max(min(value, 255), autoShowAudiencePanMin)
        if clamped == autoShowAudiencePanMax { return }
        beginLocalMutationHold(seconds: 1.2)
        autoShowAudiencePanMax = clamped
        let request = currentAutoShowUpdateBody()
        setPendingAutoShowRequest(request)
        postAutoShow(request)
    }

    func setAutoShowAudienceTurnPanMin(_ value: Int) {
        let clamped = min(max(value, 0), autoShowAudienceTurnPanMax)
        if clamped == autoShowAudienceTurnPanMin { return }
        beginLocalMutationHold(seconds: 1.2)
        autoShowAudienceTurnPanMin = clamped
        let request = currentAutoShowUpdateBody()
        setPendingAutoShowRequest(request)
        postAutoShow(request)
    }

    func setAutoShowAudienceTurnPanMax(_ value: Int) {
        let clamped = max(min(value, 255), autoShowAudienceTurnPanMin)
        if clamped == autoShowAudienceTurnPanMax { return }
        beginLocalMutationHold(seconds: 1.2)
        autoShowAudienceTurnPanMax = clamped
        let request = currentAutoShowUpdateBody()
        setPendingAutoShowRequest(request)
        postAutoShow(request)
    }

    func setAutoShowAudienceTiltSplit(_ value: Int) {
        let clamped = min(max(value, 0), 255)
        if clamped == autoShowAudienceTiltSplit { return }
        beginLocalMutationHold(seconds: 1.2)
        autoShowAudienceTiltSplit = clamped
        let request = currentAutoShowUpdateBody()
        setPendingAutoShowRequest(request)
        postAutoShow(request)
    }

    func setLiveOverrideColor(_ color: String) {
        let normalized = color.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if normalized == liveOverrideColor && liveOverrideColorCombo == "none" { return }
        beginLocalMutationHold(seconds: 1.2)
        liveOverrideColor = normalized
        liveOverrideColorCombo = "none"
        let request = currentAutoShowUpdateBody()
        setPendingAutoShowRequest(request)
        postAutoShow(request)
    }

    func setLiveOverrideManualStrobe(_ enabled: Bool) {
        if enabled == liveOverrideManualStrobe { return }
        beginLocalMutationHold(seconds: 1.2)
        liveOverrideManualStrobe = enabled
        let request = currentAutoShowUpdateBody()
        setPendingAutoShowRequest(request)
        postAutoShow(request)
    }

    func setLiveOverrideAudienceSweep(_ enabled: Bool) {
        if enabled == liveOverrideAudienceSweep { return }
        beginLocalMutationHold(seconds: 1.2)
        liveOverrideAudienceSweep = enabled
        let request = currentAutoShowUpdateBody()
        setPendingAutoShowRequest(request)
        postAutoShow(request)
    }

    func setLiveOverrideAllOn(_ enabled: Bool) {
        if enabled == liveOverrideAllOn { return }
        beginLocalMutationHold(seconds: 1.2)
        liveOverrideAllOn = enabled
        let request = currentAutoShowUpdateBody()
        setPendingAutoShowRequest(request)
        postAutoShow(request)
    }

    func setLiveOverrideParChase(_ enabled: Bool) {
        if enabled == liveOverrideParChase { return }
        beginLocalMutationHold(seconds: 1.2)
        liveOverrideParChase = enabled
        if enabled {
            liveOverrideParSnake = false
        }
        let request = currentAutoShowUpdateBody()
        setPendingAutoShowRequest(request)
        postAutoShow(request)
    }

    func setLiveOverrideParSnake(_ enabled: Bool) {
        if enabled == liveOverrideParSnake { return }
        beginLocalMutationHold(seconds: 1.2)
        liveOverrideParSnake = enabled
        if enabled {
            liveOverrideParChase = false
        }
        let request = currentAutoShowUpdateBody()
        setPendingAutoShowRequest(request)
        postAutoShow(request)
    }

    func setTransportMode(_ mode: String) {
        let normalized = mode.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if normalized == transportMode { return }
        beginLocalMutationHold(seconds: 0.6)
        transportMode = normalized
        transportStatusText = "\(transportModeLabel(for: normalized)) wordt toegepast"
        postTransportUpdate()
    }

    func setTransportManualPhrase(_ phrase: String) {
        let normalized = phrase.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if normalized == transportManualPhrase { return }
        beginLocalMutationHold(seconds: 0.6)
        transportManualPhrase = normalized
        transportManualPhraseLabel = transportPhraseLabel(for: normalized)
        postTransportUpdate()
    }

    func setTransportIdleAnimationEnabled(_ enabled: Bool) {
        if enabled == transportIdleAnimationEnabled { return }
        beginLocalMutationHold(seconds: 0.6)
        transportIdleAnimationEnabled = enabled
        postTransportUpdate()
    }

    func tapTransportTempo() {
        Task {
            do {
                beginLocalMutationHold(seconds: 0.2)
                let state: AppState = try await post("/api/transport/tap", body: EmptyRequest(), as: AppState.self)
                apply(state, source: .action)
                errorText = ""
            } catch {
                errorText = "Tap tempo mislukt: \(error.localizedDescription)"
            }
        }
    }

    func resetTransportClock() {
        Task {
            do {
                beginLocalMutationHold(seconds: 0.2)
                let state: AppState = try await post("/api/transport/reset", body: EmptyRequest(), as: AppState.self)
                apply(state, source: .action)
                errorText = ""
            } catch {
                errorText = "Transport reset mislukt: \(error.localizedDescription)"
            }
        }
    }

    func previewAnimationTime(for date: Date) -> TimeInterval {
        let elapsed = max(0, date.timeIntervalSince(previewClockAnchorDate))
        if let sourceSeconds = previewClockSourceSeconds {
            return sourceSeconds + elapsed
        }
        if let beatValue = previewClockBeatValue, let bpm = previewClockBpm, bpm > 0 {
            let normalizedBeat = max(0, beatValue - 1.0)
            return (normalizedBeat * 60.0 / bpm) + elapsed
        }
        return date.timeIntervalSinceReferenceDate
    }

    func triggerOneShotCue(_ cueID: String) {
        let normalized = cueID.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !normalized.isEmpty else { return }
        Task {
            do {
                beginLocalMutationHold(seconds: 0.25)
                let state: AppState = try await post(
                    "/api/dmx/trigger-cue",
                    body: TriggerCueRequest(cueID: normalized),
                    as: AppState.self
                )
                apply(state, source: .action)
                errorText = ""
            } catch {
                errorText = "Cue trigger mislukt: \(error.localizedDescription)"
            }
        }
    }

    func clearLiveOverrides() {
        beginLocalMutationHold(seconds: 1.2)
        liveOverrideColor = "none"
        liveOverrideManualStrobe = false
        liveOverrideAudienceSweep = false
        liveOverrideAllOn = false
        liveOverrideParChase = false
        liveOverrideParSnake = false
        let request = currentAutoShowUpdateBody()
        setPendingAutoShowRequest(request)
        postAutoShow(request)
    }

    func applyLivePreset(_ preset: LivePreset) {
        guard !slotEditors.isEmpty else { return }
        if activeLivePreset == preset {
            restoreLivePresetState()
            return
        }
        captureLivePresetRestoreStateIfNeeded()
        let movingIDs = slotEditors.filter { $0.supportsPan || $0.supportsTilt }.map(\.id)
        let movingCount = movingIDs.count
        for editor in slotEditors {
            let movingIndex = movingIDs.firstIndex(of: editor.id)
            configure(editor, for: preset, movingIndex: movingIndex, movingCount: movingCount)
        }
        activeLivePreset = preset
        autoShowEnabled = false
        pushAll(
            activeSlotID: selectedSlotID.isEmpty ? slotEditors[0].id : selectedSlotID,
            autoShow: currentAutoShowUpdateBody(enabled: false, style: autoShowStyle)
        )
    }

    private func configure(_ editor: SlotEditor, for preset: LivePreset, movingIndex: Int?, movingCount: Int) {
        editor.enabled = true
        switch preset {
        case .warmWash:
            editor.syncEnabled = false
            editor.beatPulseEnabled = false
            editor.oscStrobeEnabled = false
            editor.colorSource = "manual"
            editor.red = 255
            editor.green = 120
            editor.blue = 24
            editor.white = 0
            if editor.supportsDimmer { editor.dimmer = 255 }
            if editor.supportsStrobe { editor.strobe = 0 }
            if editor.supportsPan { editor.pan = 127 }
            if editor.supportsTilt { editor.tilt = 148 }
        case .coolWash:
            editor.syncEnabled = false
            editor.beatPulseEnabled = false
            editor.oscStrobeEnabled = false
            editor.colorSource = "manual"
            editor.red = 20
            editor.green = 180
            editor.blue = 255
            editor.white = editor.supportsWhite ? 40 : 0
            if editor.supportsDimmer { editor.dimmer = 255 }
            if editor.supportsStrobe { editor.strobe = 0 }
            if editor.supportsPan { editor.pan = 127 }
            if editor.supportsTilt { editor.tilt = 136 }
        case .magentaPop:
            editor.syncEnabled = false
            editor.beatPulseEnabled = false
            editor.oscStrobeEnabled = false
            editor.colorSource = "manual"
            editor.red = 255
            editor.green = 30
            editor.blue = 150
            editor.white = 0
            if editor.supportsDimmer { editor.dimmer = 255 }
            if editor.supportsStrobe { editor.strobe = 0 }
            if editor.supportsPan { editor.pan = 127 }
            if editor.supportsTilt { editor.tilt = 132 }
        case .iceWhite:
            editor.syncEnabled = false
            editor.beatPulseEnabled = false
            editor.oscStrobeEnabled = false
            editor.colorSource = "manual"
            editor.red = 210
            editor.green = 230
            editor.blue = 255
            editor.white = editor.supportsWhite ? 210 : 0
            if editor.supportsDimmer { editor.dimmer = 255 }
            if editor.supportsStrobe { editor.strobe = 0 }
            if editor.supportsPan { editor.pan = 127 }
            if editor.supportsTilt { editor.tilt = 126 }
        case .phraseDrive:
            editor.syncEnabled = true
            editor.beatPulseEnabled = true
            editor.oscStrobeEnabled = false
            editor.colorSource = "phrase"
            if editor.supportsDimmer { editor.dimmer = 255 }
            if editor.supportsStrobe { editor.strobe = 0 }
            if editor.supportsPanTiltSpeed { editor.panTiltSpeed = 22 }
        case .moodDrive:
            editor.syncEnabled = true
            editor.beatPulseEnabled = false
            editor.oscStrobeEnabled = false
            editor.colorSource = "mood"
            if editor.supportsDimmer { editor.dimmer = 255 }
            if editor.supportsStrobe { editor.strobe = 0 }
            if editor.supportsPanTiltSpeed { editor.panTiltSpeed = 18 }
        case .colorBankDrive:
            editor.syncEnabled = true
            editor.beatPulseEnabled = true
            editor.oscStrobeEnabled = false
            editor.colorSource = "color_bank"
            if editor.supportsDimmer { editor.dimmer = 255 }
            if editor.supportsStrobe { editor.strobe = 0 }
            if editor.supportsPanTiltSpeed { editor.panTiltSpeed = 20 }
        case .beatPush:
            editor.syncEnabled = false
            editor.beatPulseEnabled = true
            editor.oscStrobeEnabled = false
            editor.colorSource = "manual"
            editor.red = 255
            editor.green = 255
            editor.blue = 255
            editor.white = editor.supportsWhite ? 160 : 0
            if editor.supportsDimmer { editor.dimmer = 235 }
            if editor.supportsStrobe { editor.strobe = 0 }
        case .strobeHit:
            editor.syncEnabled = false
            editor.beatPulseEnabled = false
            editor.oscStrobeEnabled = false
            editor.colorSource = "manual"
            editor.red = 255
            editor.green = 255
            editor.blue = 255
            editor.white = editor.supportsWhite ? 255 : 0
            if editor.supportsDimmer { editor.dimmer = 255 }
            if editor.supportsStrobe { editor.strobe = 220 }
        case .focus:
            editor.syncEnabled = false
            editor.beatPulseEnabled = false
            editor.oscStrobeEnabled = false
            editor.colorSource = "manual"
            editor.red = 255
            editor.green = 255
            editor.blue = 255
            editor.white = editor.supportsWhite ? 180 : 0
            if editor.supportsDimmer { editor.dimmer = 255 }
            if editor.supportsPan { editor.pan = 127 }
            if editor.supportsTilt { editor.tilt = 127 }
            if editor.supportsPanTiltSpeed { editor.panTiltSpeed = 0 }
            if editor.supportsStrobe { editor.strobe = 0 }
        case .sweep:
            editor.syncEnabled = true
            editor.beatPulseEnabled = true
            editor.oscStrobeEnabled = false
            editor.colorSource = "phrase"
            if editor.supportsDimmer { editor.dimmer = 255 }
            if editor.supportsPan { editor.pan = 127 }
            if editor.supportsTilt { editor.tilt = 144 }
            if editor.supportsPanTiltSpeed { editor.panTiltSpeed = 25 }
            if editor.supportsStrobe { editor.strobe = 0 }
        case .fanOut:
            editor.syncEnabled = false
            editor.beatPulseEnabled = false
            editor.oscStrobeEnabled = false
            editor.colorSource = "manual"
            editor.red = 160
            editor.green = 200
            editor.blue = 255
            editor.white = editor.supportsWhite ? 70 : 0
            if editor.supportsDimmer { editor.dimmer = 255 }
            if editor.supportsStrobe { editor.strobe = 0 }
            if let movingIndex, movingCount > 0 {
                let fraction = movingCount == 1 ? 0.5 : Double(movingIndex) / Double(max(1, movingCount - 1))
                if editor.supportsPan { editor.pan = Int((40.0 + (175.0 * fraction)).rounded()) }
                if editor.supportsTilt { editor.tilt = 132 }
                if editor.supportsPanTiltSpeed { editor.panTiltSpeed = 12 }
            }
        case .blackout:
            if editor.supportsDimmer {
                editor.enabled = true
                editor.dimmer = 0
            } else {
                editor.enabled = false
            }
            if editor.supportsStrobe { editor.strobe = 0 }
            editor.red = 0
            editor.green = 0
            editor.blue = 0
            editor.white = 0
        }
    }

    func anchorAssignment(for slotID: String) -> String {
        mapAssignments[slotID] ?? ""
    }

    func assignAnchor(_ rawValue: String, to slotID: String) {
        if rawValue.isEmpty {
            mapAssignments.removeValue(forKey: slotID)
        } else {
            mapAssignments[slotID] = rawValue
        }
        saveMapAssignments()
    }

    func startProjectionLayoutEditing() {
        projectionLayoutDrafts = projectionLayouts
        isFixtureCalibrationMode = false
        isEditingProjectionLayout = true
    }

    func startFixtureCalibration() {
        guard
            !selectedSlotID.isEmpty,
            let editor = editorsByID[selectedSlotID],
            editor.supportsPan && editor.supportsTilt
        else {
            errorText = "Selecteer eerst één moving head met Pan en Tilt."
            return
        }
        projectionLayoutDrafts = projectionLayouts
        isFixtureCalibrationMode = true
        calibrationTestSlotID = nil
        isEditingProjectionLayout = true
    }

    func cancelProjectionLayoutEditing() {
        projectionLayoutDrafts = projectionLayouts
        isFixtureCalibrationMode = false
        calibrationTestSlotID = nil
        isEditingProjectionLayout = false
    }

    func applyProjectionLayoutEditing() {
        if isFixtureCalibrationMode {
            saveSelectedFixtureCalibration()
            return
        }
        saveProjectionLayoutPositions()
    }

    private func saveProjectionLayoutPositions() {
        guard !projectionLayoutSaveInFlight else { return }
        let updates = Dictionary(uniqueKeysWithValues: projectionLayoutDrafts.map { slotID, world in
            (
                slotID,
                FixturePositionSlotUpdate(
                    venueCalibration: FixturePositionOnlyPayload(
                        positionM: VenuePhysicalPointState(
                            x: world.x / 100,
                            y: world.y / 100,
                            z: world.z / 100
                        )
                    )
                )
            )
        })
        guard !updates.isEmpty else {
            isEditingProjectionLayout = false
            return
        }
        let payload = FixturePositionUpdateRequest(
            activeSlot: selectedSlotID,
            slots: updates
        )
        projectionLayoutSaveInFlight = true
        Task {
            do {
                let state: AppState = try await post("/api/dmx/update", body: payload, as: AppState.self)
                projectionLayouts = projectionLayoutDrafts
                saveProjectionLayouts()
                isEditingProjectionLayout = false
                projectionLayoutSaveInFlight = false
                apply(state, source: .action)
                errorText = ""
            } catch {
                projectionLayoutSaveInFlight = false
                errorText = "Fixtureposities opslaan mislukt: \(error.localizedDescription)"
            }
        }
    }

    func savePhysicalTiltLimits(minimumText: String, centerText: String, maximumText: String) {
        guard
            let minimum = Double(minimumText.trimmingCharacters(in: .whitespacesAndNewlines)),
            let center = Double(centerText.trimmingCharacters(in: .whitespacesAndNewlines)),
            let maximum = Double(maximumText.trimmingCharacters(in: .whitespacesAndNewlines)),
            minimum.isFinite, center.isFinite, maximum.isFinite, minimum < center, center < maximum
        else {
            errorText = "Tilt limits require finite MIN < CENTER < MAX."
            return
        }
        saveSelectedFixtureCalibrationWithPhysicalTiltLimits(
            physicalTiltLimits: PhysicalTiltLimitsPayload(minDeg: minimum, centerDeg: center, maxDeg: maximum),
            preserveCalibrationMode: true
        )
    }

    private func saveSelectedFixtureCalibration() {
        saveSelectedFixtureCalibrationWithPhysicalTiltLimits()
    }

    private func saveSelectedFixtureCalibrationWithPhysicalTiltLimits(
        physicalTiltLimits: PhysicalTiltLimitsPayload? = nil,
        preserveCalibrationMode: Bool = false
    ) {
        guard
            !calibrationSaveInFlight,
            !selectedSlotID.isEmpty,
            let editor = editorsByID[selectedSlotID],
            editor.supportsPan && editor.supportsTilt,
            let world = projectionLayoutDrafts[selectedSlotID] ?? projectionLayouts[selectedSlotID]
        else { return }
        let basis = venueOrientationBasis(for: world)
        let position = VenuePointState(
            x: venueNormalizedCoordinate(world.x, negativeExtent: abs(StageWorld.minX), positiveExtent: StageWorld.maxX),
            y: venueNormalizedCoordinate(world.y, negativeExtent: abs(StageWorld.minY), positiveExtent: StageWorld.maxY)
        )
        let calibration = fixtureCalibrations[selectedSlotID]
        let payload = VenueCalibrationUpdateRequest(
            slotID: selectedSlotID,
            activeSlot: selectedSlotID,
            slot: VenueCalibrationSlotUpdate(
                venueCalibration: VenueCalibrationPayload(
                    version: 3,
                    positionM: VenuePhysicalPointState(
                        x: world.x / 100,
                        y: world.y / 100,
                        z: world.z / 100
                    ),
                    position: position,
                    mountingHeightM: world.z / 100,
                    physicalForward: basis.forward,
                    physicalUp: basis.up,
                    panCorrectionDegrees: calibration?.panCorrectionDegrees ?? 0,
                    tiltCorrectionDegrees: calibration?.tiltCorrectionDegrees ?? 0,
                    physicalTiltLimits: physicalTiltLimits
                )
            )
        )
        calibrationSaveInFlight = true
        Task {
            do {
                let state: AppState = try await post("/api/dmx/update", body: payload, as: AppState.self)
                projectionLayouts = projectionLayoutDrafts
                saveProjectionLayouts()
                if !preserveCalibrationMode {
                    isFixtureCalibrationMode = false
                    isEditingProjectionLayout = false
                }
                calibrationSaveInFlight = false
                apply(state, source: .action)
                errorText = ""
            } catch {
                calibrationSaveInFlight = false
                errorText = "Fixturecalibratie opslaan mislukt: \(error.localizedDescription)"
            }
        }
    }

    func testAllMovingHeadsInPreview() {
        guard calibrationTestInFlightSlotID == nil else { return }
        calibrationTestInFlightSlotID = "__venue_target_group__"
        Task {
            do {
                let response: VenueTargetTestActionResponse = try await post(
                    "/api/dmx/venue-target-preview",
                    body: VenueTargetGroupRequest(target: selectedVenueTarget, verticalLayer: selectedVenueTargetVerticalLayer),
                    as: VenueTargetTestActionResponse.self
                )
                venueTargetTestState = response.authority
                if response.accepted, let resultSet = response.authority?.resultSet {
                    clearVenueTargetPreview()
                    previewVenueTargetResultSet = resultSet
                    venueTargetTestStatusText = "\(resultSet.targetedCount)/\(resultSet.candidateCount) TARGETED • PREVIEW TEST ACTIVE"
                    startVenueTargetLeaseHeartbeat()
                } else {
                    venueTargetTestStatusText = response.reason ?? response.status
                }
                calibrationTestInFlightSlotID = nil
                errorText = response.accepted ? "" : (response.reason ?? "Venue target preview-test was rejected.")
            } catch {
                calibrationTestInFlightSlotID = nil
                errorText = "Venue target preview-test mislukt: \(error.localizedDescription)"
            }
        }
    }

    /// Kept for the calibration inspector: resolve and preview only the head
    /// currently being calibrated.
    func testAudienceCenterForSelectedFixture() {
        testAudienceTargetPreview()
    }

    /// The selected moving head supplies the normal resolver diagnostic.  The
    /// optional group then shares that canonical target visually, without any
    /// physical movement endpoint being called.
    private func testAudienceTargetPreview() {
        guard
            let editor = editorsByID[selectedSlotID],
            editor.supportsPan && editor.supportsTilt
        else {
            errorText = "Selecteer eerst één moving head."
            return
        }
        calibrationTestSlotID = selectedSlotID
        calibrationTestInFlightSlotID = selectedSlotID
        let world = projectionLayoutDrafts[selectedSlotID] ?? projectionLayouts[selectedSlotID] ?? effectiveWorldPosition(for: selectedSlotID)
        let basis = venueOrientationBasis(for: world)
        let position = VenuePointState(
            x: venueNormalizedCoordinate(world.x, negativeExtent: abs(StageWorld.minX), positiveExtent: StageWorld.maxX),
            y: venueNormalizedCoordinate(world.y, negativeExtent: abs(StageWorld.minY), positiveExtent: StageWorld.maxY)
        )
        let persisted = fixtureCalibrations[selectedSlotID]
        let request = VenueTargetTestRequest(
            slotID: selectedSlotID,
            venueCalibration: VenueCalibrationPayload(
                version: 3,
                positionM: VenuePhysicalPointState(
                    x: world.x / 100,
                    y: world.y / 100,
                    z: world.z / 100
                ),
                position: position,
                mountingHeightM: world.z / 100,
                physicalForward: basis.forward,
                physicalUp: basis.up,
                panCorrectionDegrees: persisted?.panCorrectionDegrees ?? 0,
                tiltCorrectionDegrees: persisted?.tiltCorrectionDegrees ?? 0
            ),
            target: selectedVenueTarget,
            verticalLayer: selectedVenueTargetVerticalLayer
        )
        Task {
            do {
                let response: VenueTargetTestResponse = try await post(
                    "/api/dmx/venue-target-test",
                    body: request,
                    as: VenueTargetTestResponse.self
                )
                audienceCenterTestResults[response.slotID] = response.result
                activateVenueTargetPreview(
                    response.result,
                    slotID: response.slotID
                )
                calibrationTestInFlightSlotID = nil
                errorText = ""
            } catch {
                calibrationTestInFlightSlotID = nil
                errorText = "Audience target preview-test mislukt: \(error.localizedDescription)"
            }
        }
    }

    func selectVenueTarget(_ target: String) {
        let parts = target.split(separator: "_").map(String.init)
        let zone: String
        let position: String
        if parts.count == 3, parts[0] == "AUDIENCE" {
            zone = parts[1]
            position = parts[2]
        } else if parts.count == 2, parts[0] == "REAR" {
            zone = "REAR"
            position = parts[1]
        } else {
            return
        }
        guard venueTargetTestState?.active != true else {
            errorText = "Release the active physical target test before changing target."
            return
        }
        selectedVenueTargetZone = zone
        selectedVenueTargetPosition = position
        selectedVenueTarget = target
        clearVenueTargetPreview()
        venueTargetTestStatusText = "READY • \(zone) / \(position) selected."
    }

    func selectVenueTargetZone(_ zone: String) {
        selectVenueTarget(zone == "REAR"
            ? "REAR_\(selectedVenueTargetPosition)"
            : "AUDIENCE_\(zone)_\(selectedVenueTargetPosition)")
    }

    func selectVenueTargetPosition(_ position: String) {
        selectVenueTarget(selectedVenueTargetZone == "REAR"
            ? "REAR_\(position)"
            : "AUDIENCE_\(selectedVenueTargetZone)_\(position)")
    }

    func selectVenueTargetVerticalLayer(_ layer: String) {
        guard venueTargetTestState?.active != true else {
            errorText = "Release the active target test before changing vertical layer."
            return
        }
        guard venueTargetVerticalLayerState(layer)?.available != false else {
            venueTargetTestStatusText = "CEILING UNAVAILABLE • \(venueTargetVerticalLayerState(layer)?.reason ?? "CEILING_HEIGHT_UNSET")"
            return
        }
        selectedVenueTargetVerticalLayer = layer
        clearVenueTargetPreview()
        venueTargetTestStatusText = "READY • \(selectedVenueTarget) / \(layer) selected."
    }

    func venueTargetVerticalLayerState(_ layer: String) -> VenueTargetVerticalLayerState? {
        venueSpace?.verticalLayers?.first(where: { $0.id == layer })
    }

    func moveAimCalibration(to target: String) {
        guard !selectedSlotID.isEmpty, venueTargetTestState?.active != true else {
            errorText = "Release the active movement lease before changing calibration target."
            return
        }
        aimCalibrationInFlight = true
        Task {
            do {
                let response: AimCalibrationActionResponse = try await post(
                    "/api/dmx/aim-calibration/move",
                    body: AimCalibrationMoveRequest(slotID: selectedSlotID, target: target),
                    as: AimCalibrationActionResponse.self
                )
                aimCalibrationInFlight = false
                venueTargetTestState = response.authority
                venueTargetTestStatusText = response.reason ?? response.status
                if response.accepted, response.authority?.active == true {
                    selectedVenueTarget = target
                    if let resultSet = response.authority?.resultSet { activateVenueTargetPreview(resultSet) }
                    startVenueTargetLeaseHeartbeat()
                    errorText = ""
                }
            } catch {
                aimCalibrationInFlight = false
                errorText = "Physical aim move failed: \(error.localizedDescription)"
            }
        }
    }

    func nudgeAimCalibration(axis: String, direction: String) {
        guard venueTargetTestState?.mode == "PHYSICAL_AIM_CALIBRATION" else { return }
        Task {
            do {
                let response: AimCalibrationActionResponse = try await post(
                    "/api/dmx/aim-calibration/nudge",
                    body: AimCalibrationNudgeRequest(axis: axis, direction: direction, granularity: aimCalibrationGranularity),
                    as: AimCalibrationActionResponse.self
                )
                venueTargetTestState = response.authority
                venueTargetTestStatusText = response.reason ?? response.status
                if !response.accepted { errorText = response.reason ?? "Aim adjustment was rejected." }
            } catch {
                errorText = "Aim adjustment failed: \(error.localizedDescription)"
            }
        }
    }

    func saveAimCalibrationAnchor() {
        aimCalibrationInFlight = true
        Task {
            do {
                let response: AimCalibrationActionResponse = try await post(
                    "/api/dmx/aim-calibration/save-anchor",
                    body: EmptyRequest(),
                    as: AimCalibrationActionResponse.self
                )
                aimCalibrationInFlight = false
                venueTargetTestState = response.authority
                stopVenueTargetLeaseHeartbeat()
                clearVenueTargetPreview()
                try await refreshState()
                errorText = response.accepted ? "" : (response.reason ?? "Anchor was not saved.")
            } catch {
                aimCalibrationInFlight = false
                errorText = "Save anchor failed: \(error.localizedDescription)"
            }
        }
    }

    func recordAimValidation(_ result: String) {
        aimCalibrationInFlight = true
        Task {
            do {
                let response: AimCalibrationActionResponse = try await post(
                    "/api/dmx/aim-calibration/validation",
                    body: AimCalibrationValidationRequest(result: result),
                    as: AimCalibrationActionResponse.self
                )
                aimCalibrationInFlight = false
                venueTargetTestState = response.authority
                stopVenueTargetLeaseHeartbeat()
                clearVenueTargetPreview()
                try await refreshState()
                errorText = response.accepted ? "" : (response.reason ?? "Validation was not recorded.")
            } catch {
                aimCalibrationInFlight = false
                errorText = "Validation save failed: \(error.localizedDescription)"
            }
        }
    }

    func resetAimCalibration() {
        guard !selectedSlotID.isEmpty else { return }
        aimCalibrationInFlight = true
        Task {
            do {
                let response: AimCalibrationActionResponse = try await post(
                    "/api/dmx/aim-calibration/reset",
                    body: AimCalibrationResetRequest(slotID: selectedSlotID, confirm: true),
                    as: AimCalibrationActionResponse.self
                )
                aimCalibrationInFlight = false
                venueTargetTestState = response.authority
                stopVenueTargetLeaseHeartbeat()
                clearVenueTargetPreview()
                try await refreshState()
                errorText = response.accepted ? "" : (response.reason ?? "Aim calibration reset failed.")
            } catch {
                aimCalibrationInFlight = false
                errorText = "Aim calibration reset failed: \(error.localizedDescription)"
            }
        }
    }

    func beginAxisMappingV2(axis: String) {
        guard !selectedSlotID.isEmpty else { return }
        axisMappingV2InFlight = true
        Task {
            do {
                let response: AxisMappingV2ActionResponse = try await post(
                    "/api/dmx/axis-mapping-v2/begin",
                    body: AxisMappingV2BeginRequest(slotID: selectedSlotID, axis: axis),
                    as: AxisMappingV2ActionResponse.self
                )
                axisMappingV2InFlight = false
                venueTargetTestState = response.authority
                try await refreshState()
                errorText = response.accepted ? "" : (response.reason ?? "Axis mapping could not start.")
            } catch {
                axisMappingV2InFlight = false
                errorText = "Axis mapping start failed: \(error.localizedDescription)"
            }
        }
    }

    func nudgeAxisMappingV2ReferencePose(axis: String, direction: String, granularity: String) {
        guard !selectedSlotID.isEmpty else { return }
        axisMappingV2InFlight = true
        Task { do {
            let response: AxisMappingV2ActionResponse = try await post("/api/dmx/axis-mapping-v2/tilt-reference/nudge", body: AxisMappingV2ReferencePoseNudgeRequest(slotID: selectedSlotID, axis: axis, direction: direction, granularity: granularity), as: AxisMappingV2ActionResponse.self)
            axisMappingV2InFlight = false; venueTargetTestState = response.authority
            if response.accepted { startVenueTargetLeaseHeartbeat(); errorText = "" } else { errorText = response.reason ?? "Reference-pose movement was rejected." }
        } catch { axisMappingV2InFlight = false; errorText = "Reference-pose movement failed: \(error.localizedDescription)" } }
    }

    func lockAxisMappingV2TiltReference() {
        axisMappingV2InFlight = true
        Task { do {
            let response: AxisMappingV2ActionResponse = try await post("/api/dmx/axis-mapping-v2/tilt-reference/lock", body: AxisMappingV2LockTiltReferenceRequest(), as: AxisMappingV2ActionResponse.self)
            axisMappingV2InFlight = false; venueTargetTestState = response.authority
            if response.authority?.active == true { startVenueTargetLeaseHeartbeat() } else { stopVenueTargetLeaseHeartbeat() }
            try await refreshState()
            errorText = response.accepted && response.status != "NEXT_MOVE_FAILED" ? "" : (response.reason ?? "Pan reference lock was rejected.")
        } catch { axisMappingV2InFlight = false; errorText = "Pan reference lock failed: \(error.localizedDescription)" } }
    }

    func setAxisMappingV2PanReference(tiltPlaneDegrees: Double) {
        guard !selectedSlotID.isEmpty else { return }
        axisMappingV2InFlight = true
        Task { do {
            let response: AxisMappingV2ActionResponse = try await post("/api/dmx/axis-mapping-v2/pan-reference", body: AxisMappingV2PanReferenceRequest(slotID: selectedSlotID, tiltPlaneDegrees: tiltPlaneDegrees), as: AxisMappingV2ActionResponse.self)
            axisMappingV2InFlight = false; venueTargetTestState = response.authority
            if response.authority?.active == true { startVenueTargetLeaseHeartbeat() } else { stopVenueTargetLeaseHeartbeat() }
            try await refreshState()
            errorText = response.accepted && response.status != "NEXT_MOVE_FAILED" ? "" : (response.reason ?? "Pan sweep reference was rejected.")
        } catch { axisMappingV2InFlight = false; errorText = "Pan sweep reference failed: \(error.localizedDescription)" } }
    }

    func moveAxisMappingV2Sample(axis: String, index: Int) {
        guard !selectedSlotID.isEmpty else { return }
        axisMappingV2InFlight = true
        Task {
            do {
                let response: AxisMappingV2ActionResponse = try await post(
                    "/api/dmx/axis-mapping-v2/move-sample",
                    body: AxisMappingV2MoveSampleRequest(slotID: selectedSlotID, axis: axis, index: index),
                    as: AxisMappingV2ActionResponse.self
                )
                axisMappingV2InFlight = false
                venueTargetTestState = response.authority
                venueTargetTestStatusText = response.reason ?? response.status
                if response.accepted { startVenueTargetLeaseHeartbeat(); errorText = "" }
                else { errorText = response.reason ?? "Motor position was rejected." }
            } catch {
                axisMappingV2InFlight = false
                errorText = "Motor position failed: \(error.localizedDescription)"
            }
        }
    }

    func saveAxisMappingV2Sample(axis: String, measuredDegrees: Double) {
        axisMappingV2InFlight = true
        Task {
            do {
                let response: AxisMappingV2ActionResponse = try await post(
                    "/api/dmx/axis-mapping-v2/save-sample",
                    body: AxisMappingV2SaveSampleRequest(axis: axis, measuredDegrees: measuredDegrees),
                    as: AxisMappingV2ActionResponse.self
                )
                axisMappingV2InFlight = false
                venueTargetTestState = response.authority
                if response.authority?.active == true { startVenueTargetLeaseHeartbeat() }
                else { stopVenueTargetLeaseHeartbeat() }
                try await refreshState()
                errorText = response.accepted && response.status != "NEXT_MOVE_FAILED" ? "" : (response.reason ?? "Measured direction was not saved.")
            } catch {
                axisMappingV2InFlight = false
                errorText = "Save measured direction failed: \(error.localizedDescription)"
            }
        }
    }

    func moveAxisMappingV2Validation(target: String) {
        guard !selectedSlotID.isEmpty, venueTargetTestState?.active != true else { return }
        axisMappingV2InFlight = true
        Task {
            do {
                let response: AxisMappingV2ActionResponse = try await post(
                    "/api/dmx/axis-mapping-v2/validation-move",
                    body: AxisMappingV2ValidationMoveRequest(slotID: selectedSlotID, target: target),
                    as: AxisMappingV2ActionResponse.self
                )
                axisMappingV2InFlight = false
                venueTargetTestState = response.authority
                if response.accepted {
                    if let resultSet = response.authority?.resultSet { activateVenueTargetPreview(resultSet) }
                    startVenueTargetLeaseHeartbeat()
                    errorText = ""
                } else { errorText = response.reason ?? "Validation move was rejected." }
            } catch {
                axisMappingV2InFlight = false
                errorText = "Validation move failed: \(error.localizedDescription)"
            }
        }
    }

    func recordAxisMappingV2Validation(_ result: String) {
        axisMappingV2InFlight = true
        Task {
            do {
                let response: AxisMappingV2ActionResponse = try await post(
                    "/api/dmx/axis-mapping-v2/validation-result",
                    body: AxisMappingV2ValidationResultRequest(result: result),
                    as: AxisMappingV2ActionResponse.self
                )
                axisMappingV2InFlight = false
                venueTargetTestState = response.authority
                stopVenueTargetLeaseHeartbeat()
                clearVenueTargetPreview()
                try await refreshState()
                errorText = response.accepted ? "" : (response.reason ?? "Validation was not recorded.")
            } catch {
                axisMappingV2InFlight = false
                errorText = "Validation result failed: \(error.localizedDescription)"
            }
        }
    }

    func activateAxisMappingV2() {
        guard !selectedSlotID.isEmpty else { return }
        axisMappingV2InFlight = true
        Task {
            do {
                let response: AxisMappingV2ActionResponse = try await post(
                    "/api/dmx/axis-mapping-v2/activate",
                    body: AxisMappingV2ActivateRequest(slotID: selectedSlotID),
                    as: AxisMappingV2ActionResponse.self
                )
                axisMappingV2InFlight = false
                try await refreshState()
                errorText = response.accepted ? "" : (response.reason ?? "V2 activation was rejected.")
            } catch {
                axisMappingV2InFlight = false
                errorText = "V2 activation failed: \(error.localizedDescription)"
            }
        }
    }

    func resetAxisMappingV2() {
        guard !selectedSlotID.isEmpty else { return }
        axisMappingV2InFlight = true
        Task {
            do {
                let response: AxisMappingV2ActionResponse = try await post(
                    "/api/dmx/axis-mapping-v2/reset",
                    body: AxisMappingV2ResetRequest(slotID: selectedSlotID, confirm: true),
                    as: AxisMappingV2ActionResponse.self
                )
                axisMappingV2InFlight = false
                venueTargetTestState = response.authority
                stopVenueTargetLeaseHeartbeat()
                clearVenueTargetPreview()
                try await refreshState()
                errorText = response.accepted ? "" : (response.reason ?? "V2 reset was rejected.")
            } catch {
                axisMappingV2InFlight = false
                errorText = "V2 reset failed: \(error.localizedDescription)"
            }
        }
    }

    func moveSelectedFixtureToVenueTarget() {
        guard (previewVenueTargetResultSet?.targetedCount ?? 0) > 0 else {
            errorText = "Run TEST ALL IN PREVIEW first; no targetable moving heads are available."
            return
        }
        guard venueTargetTestState?.active != true else {
            errorText = "Target test is already active; release it before selecting another target."
            return
        }
        venueTargetTestInFlight = true
        Task {
            do {
                let response: VenueTargetTestActionResponse = try await post(
                    "/api/dmx/venue-target-move",
                    body: VenueTargetGroupRequest(target: selectedVenueTarget, verticalLayer: selectedVenueTargetVerticalLayer),
                    as: VenueTargetTestActionResponse.self
                )
                venueTargetTestInFlight = false
                venueTargetTestState = response.authority
                venueTargetTestStatusText = response.reason ?? response.status
                if response.accepted, response.authority?.active == true {
                    if let resultSet = response.authority?.resultSet {
                        activateVenueTargetPreview(resultSet)
                        venueTargetTestStatusText = "\(resultSet.targetedCount)/\(resultSet.candidateCount) TARGETED • PHYSICAL TEST ACTIVE"
                    }
                    startVenueTargetLeaseHeartbeat()
                    errorText = ""
                } else {
                    stopVenueTargetLeaseHeartbeat()
                }
            } catch {
                venueTargetTestInFlight = false
                venueTargetTestStatusText = "ERROR"
                errorText = "Target movement failed: \(error.localizedDescription)"
            }
        }
    }

    func releaseVenueTargetTest() {
        stopVenueTargetLeaseHeartbeat()
        Task {
            do {
                let response: VenueTargetTestActionResponse = try await post(
                    "/api/dmx/venue-target-release",
                    body: EmptyRequest(),
                    as: VenueTargetTestActionResponse.self
                )
                venueTargetTestState = response.authority
                venueTargetTestStatusText = "READY • Pan/tilt test released."
                clearVenueTargetPreview()
                errorText = ""
            } catch {
                errorText = "Target test release failed: \(error.localizedDescription)"
            }
        }
    }

    func playMovementLab() {
        movementLabInFlight = true
        Task {
            do {
                let response: MovementLabResponse = try await post(
                    "/api/dmx/movement-lab/play",
                    body: MovementLabRequest(
                        effectID: movementLabEffectID,
                        section: movementLabSection,
                        variation: movementLabVariation,
                        bpm: 124
                    ),
                    as: MovementLabResponse.self
                )
                movementLabInFlight = false
                movementLabState = response.movementLab
                errorText = response.accepted ? "" : (response.reason ?? "Movement Lab was rejected.")
            } catch {
                movementLabInFlight = false
                errorText = "Movement Lab play failed: \(error.localizedDescription)"
            }
        }
    }

    func stopMovementLab() {
        movementLabInFlight = true
        Task {
            do {
                let response: MovementLabResponse = try await post(
                    "/api/dmx/movement-lab/stop",
                    body: EmptyRequest(),
                    as: MovementLabResponse.self
                )
                movementLabInFlight = false
                movementLabState = response.movementLab
                errorText = ""
            } catch {
                movementLabInFlight = false
                errorText = "Movement Lab stop failed: \(error.localizedDescription)"
            }
        }
    }

    private func startVenueTargetLeaseHeartbeat() {
        stopVenueTargetLeaseHeartbeat()
        venueTargetLeaseTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                guard !Task.isCancelled, let self else { return }
                do {
                    let response: VenueTargetTestActionResponse = try await self.post(
                        "/api/dmx/venue-target-renew",
                        body: EmptyRequest(),
                        as: VenueTargetTestActionResponse.self
                    )
                    self.venueTargetTestState = response.authority
                    self.venueTargetTestStatusText = response.reason ?? response.status
                    if !response.accepted || response.authority?.active != true {
                        self.stopVenueTargetLeaseHeartbeat()
                        return
                    }
                } catch {
                    self.venueTargetTestStatusText = "Lease heartbeat lost; backend will release safely."
                    self.stopVenueTargetLeaseHeartbeat()
                    return
                }
            }
        }
    }

    private func stopVenueTargetLeaseHeartbeat() {
        venueTargetLeaseTask?.cancel()
        venueTargetLeaseTask = nil
    }

    /// The backend owns both physical and renderer-only Venue Target Tests. A fresh State poll may
    /// arrive after navigation, redraw, or reconnect without the Swift process
    /// that originally pressed MOVE TO TARGET.  Reconstruct only its UI state;
    /// live beams themselves come from `rendered_motion`, never from this
    /// frontend-side target preview.
    private func reconcileVenueTargetPresentation(_ authority: VenueTargetTestAuthorityState?) {
        guard authority?.active == true else { return }
        if let target = authority?.target {
            let parts = target.split(separator: "_").map(String.init)
            if parts.count == 3, parts[0] == "AUDIENCE" {
                selectedVenueTargetZone = parts[1]
                selectedVenueTargetPosition = parts[2]
            } else if parts.count == 2, parts[0] == "REAR" {
                selectedVenueTargetZone = "REAR"
                selectedVenueTargetPosition = parts[1]
            }
            selectedVenueTarget = target
        }
        if let verticalLayer = authority?.verticalLayer {
            selectedVenueTargetVerticalLayer = verticalLayer
        }
        // A local preview might contain a stale, pre-authority start point.
        // Do not let it cover the backend's post-render direction after a poll.
        if !previewVenueTargetSlotIDs.isEmpty {
            clearVenueTargetPreview()
        }
        previewVenueTargetResultSet = authority?.resultSet
        if let resultSet = authority?.resultSet {
            let label = authority?.mode == "VENUE_TARGET_PREVIEW" ? "PREVIEW TEST ACTIVE" : "PHYSICAL TEST ACTIVE"
            venueTargetTestStatusText = "\(resultSet.targetedCount)/\(resultSet.candidateCount) TARGETED • \(label)"
        }
        if venueTargetLeaseTask == nil {
            startVenueTargetLeaseHeartbeat()
        }
    }

    private func activateVenueTargetPreview(
        _ resolution: VenueTargetResolutionState,
        slotID: String
    ) {
        previewVenueTargetResolution = resolution
        guard resolution.status == "RESOLVED" else {
            clearVenueTargetPreview()
            return
        }
        let state = stageMotionStates[slotID]
        previewVenueTargetStartPanDegrees = state?.currentPanDegrees
        previewVenueTargetStartTiltDegrees = state?.currentTiltDegrees
        let slotIDs: Set<String> = [slotID]
        previewVenueTargetStartEndpoints = Dictionary(
            uniqueKeysWithValues: slotIDs.map { candidateID in
                (candidateID, venueTargetPreviewStartEndpoint(for: candidateID))
            }
        )
        previewVenueTargetStartEndpoint = previewVenueTargetStartEndpoints[slotID]
        previewVenueTargetSlotIDs = slotIDs
        previewVenueTargetSlotID = slotID
        previewVenueTargetResolutions = [slotID: resolution]
        previewVenueTargetStartPanBySlot = [slotID: state?.currentPanDegrees ?? 0]
        previewVenueTargetStartTiltBySlot = [slotID: state?.currentTiltDegrees ?? 0]
        previewVenueTargetStartedAt = Date()
    }

    private func activateVenueTargetPreview(_ resultSet: VenueTargetResultSetState) {
        let targetable = resultSet.results.filter { $0.classification == "TARGETABLE" && $0.resolution.status == "RESOLVED" }
        previewVenueTargetResultSet = resultSet
        previewVenueTargetResolutions = Dictionary(uniqueKeysWithValues: targetable.map { ($0.slotID, $0.resolution) })
        previewVenueTargetSlotIDs = Set(targetable.map(\.slotID))
        previewVenueTargetStartEndpoints = Dictionary(
            uniqueKeysWithValues: previewVenueTargetSlotIDs.map { ($0, venueTargetPreviewStartEndpoint(for: $0)) }
        )
        previewVenueTargetStartPanBySlot = Dictionary(
            uniqueKeysWithValues: previewVenueTargetSlotIDs.map { ($0, stageMotionStates[$0]?.currentPanDegrees ?? 0) }
        )
        previewVenueTargetStartTiltBySlot = Dictionary(
            uniqueKeysWithValues: previewVenueTargetSlotIDs.map { ($0, stageMotionStates[$0]?.currentTiltDegrees ?? 0) }
        )
        previewVenueTargetSlotID = targetable.first?.slotID
        previewVenueTargetResolution = targetable.first?.resolution
        previewVenueTargetStartedAt = targetable.isEmpty ? nil : Date()
    }

    private func venueTargetPreviewStartEndpoint(for slotID: String) -> SlotWorldPosition {
        let world = worldPosition(for: slotID)
        let state = stageMotionStates[slotID]
        if let preview = presentedSlotPreviews[slotID] {
            let isMovingHead = slotEditors.first(where: { $0.id == slotID }).map { $0.supportsPan && $0.supportsTilt } ?? false
            let panRange = state?.panRange ?? (preview.panRange ?? (isMovingHead ? 540.0 : 180.0))
            let tiltRange = state?.tiltRange ?? (preview.tiltRange ?? (isMovingHead ? 180.0 : 90.0))
            let pose = StageBeamPose(
                panDegrees: state?.currentPanDegrees
                    ?? preview.logicalPanDegrees
                    ?? preview.panDegrees
                    ?? panDegrees(forDMX: preview.pan, range: panRange),
                tiltDegrees: state?.currentTiltDegrees
                    ?? preview.logicalTiltDegrees
                    ?? preview.tiltDegrees
                    ?? tiltDegrees(forDMX: preview.tilt, range: tiltRange)
            )
            return beamWorldEndpoint(
                worldOrigin: world,
                mountYawDegrees: world.yawDegrees,
                mountPitchDegrees: world.pitchDegrees,
                pose: pose,
                panRange: panRange,
                tiltRange: tiltRange,
                beamKind: isMovingHead ? .movingHead : .staticWash
            )
        }
        return worldOrientationEndpoint(world, distance: 260)
    }

    private func clearVenueTargetPreview() {
        previewVenueTargetResolution = nil
        previewVenueTargetResultSet = nil
        previewVenueTargetResolutions.removeAll()
        previewVenueTargetSlotID = nil
        previewVenueTargetSlotIDs.removeAll()
        previewVenueTargetStartedAt = nil
        previewVenueTargetStartPanDegrees = nil
        previewVenueTargetStartTiltDegrees = nil
        previewVenueTargetStartEndpoint = nil
        previewVenueTargetStartEndpoints.removeAll()
        previewVenueTargetStartPanBySlot.removeAll()
        previewVenueTargetStartTiltBySlot.removeAll()
    }

    func saveVenueGeometry() {
        guard !venueGeometrySaveInFlight else { return }
        let fields: [(String, String, Bool)] = [
            ("Venue width", venueWidthMetersText, false),
            ("Forward audience depth", venueForwardDepthMetersText, false),
            ("Rear depth", venueRearDepthMetersText, true),
            ("Audience target height", audienceTargetHeightMetersText, true),
            ("Ceiling height", ceilingHeightMetersText, false),
        ]
        for (label, text, allowsZero) in fields {
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard trimmed.isEmpty || (venueNumber(trimmed).map { allowsZero ? $0 >= 0 : $0 > 0 } ?? false) else {
                errorText = "\(label) must be a valid positive value, or left UNSET."
                return
            }
        }
        if let ceiling = venueNumber(ceilingHeightMetersText),
           let normal = venueNumber(audienceTargetHeightMetersText),
           ceiling <= normal {
            errorText = "Ceiling height must be above audience target height, or left UNSET."
            return
        }
        let request = VenueGeometryUpdateRequest(
            venueGeometry: VenueGeometryUpdatePayload(
                venueWidthM: venueNumber(venueWidthMetersText),
                venueForwardDepthM: venueNumber(venueForwardDepthMetersText),
                venueRearDepthM: venueNumber(venueRearDepthMetersText),
                audienceTargetHeightM: venueNumber(audienceTargetHeightMetersText),
                ceilingHeightM: venueNumber(ceilingHeightMetersText)
            )
        )
        venueGeometrySaveInFlight = true
        Task {
            do {
                beginLocalMutationHold()
                let state: AppState = try await post("/api/dmx/update", body: request, as: AppState.self)
                venueGeometrySaveInFlight = false
                apply(state, source: .action)
                errorText = ""
            } catch {
                venueGeometrySaveInFlight = false
                errorText = "Venue Geometry opslaan mislukt: \(error.localizedDescription)"
            }
        }
    }

    private func venueNumber(_ text: String) -> Double? {
        let normalized = text.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: ",", with: ".")
        guard !normalized.isEmpty, let value = Double(normalized), value.isFinite else { return nil }
        return value
    }

    func calibrationState(for slotID: String) -> VenueFixtureCalibrationState? {
        fixtureCalibrations[slotID]
    }

    func audienceCenterTestResult(for slotID: String) -> VenueTargetResolutionState? {
        audienceCenterTestResults[slotID]
    }

    func projectionPoint(for slotID: String, projection: StageProjection) -> CGPoint {
        let world = effectiveWorldPosition(for: slotID)
        return worldProjectedPoint(world, projection: projection)
    }

    func worldPosition(for slotID: String) -> SlotWorldPosition {
        effectiveWorldPosition(for: slotID)
    }

    func updateProjectionPoint(
        for slotID: String,
        projection: StageProjection,
        point: CGPoint,
        snapEnabled: Bool? = nil
    ) {
        guard isEditingProjectionLayout else { return }
        var world = effectiveWorldPosition(for: slotID)
        update(world: &world, from: point, projection: projection)
        if snapEnabled ?? fixtureSnapEnabled {
            switch projection {
            case .top:
                world.x = (world.x / StageWorld.dragSnapCm).rounded() * StageWorld.dragSnapCm
                world.y = (world.y / StageWorld.dragSnapCm).rounded() * StageWorld.dragSnapCm
            case .front, .back:
                world.x = (world.x / StageWorld.dragSnapCm).rounded() * StageWorld.dragSnapCm
                world.z = (world.z / StageWorld.dragSnapCm).rounded() * StageWorld.dragSnapCm
            case .side:
                world.y = (world.y / StageWorld.dragSnapCm).rounded() * StageWorld.dragSnapCm
                world.z = (world.z / StageWorld.dragSnapCm).rounded() * StageWorld.dragSnapCm
            }
        }
        projectionLayoutDrafts[slotID] = world
    }

    /// Commit a completed visual pan. Active pointer updates use only a local
    /// screen-space compositor offset; the canonical metric camera changes
    /// once here, at release, with the exact existing inverse transform.
    func commitProjectionViewportPan(
        projection: StageProjection,
        startCenter: SlotWorldPosition,
        translation: CGSize,
        canvasSize: CGSize
    ) {
        guard canvasSize.width > 0, canvasSize.height > 0 else { return }
        let projectedCenter = CGPoint(
            x: 0.5 - translation.width / canvasSize.width,
            y: 0.5 - translation.height / canvasSize.height
        )
        let next = metricWorldPosition(
            from: projectedCenter,
            projection: projection,
            frontMirrored: frontProjectionMirrored,
            topQuarterTurns: topProjectionRotationQuarterTurns,
            viewportCenter: startCenter
        )
        inMemoryProjectionViewportCenters[projection] = next
        saveProjectionViewportCenter(next, for: projection)
        // One authoritative world rebuild after the visual translation clears.
        invalidateMetricStageMapViewport()
    }

    func resetMetricStageMapView() {
        resetProjectionViewportCenters()
        topProjectionRotationQuarterTurns = 0
        frontProjectionMirrored = false
        UserDefaults.standard.set(1.0, forKey: mapProjection2DZoomDefaultsKey)
        invalidateMetricStageMapViewport()
    }

    private func invalidateMetricStageMapViewport() {
        metricStageMapViewportRevision &+= 1
    }

    func fixturePositionMeters(for slotID: String) -> VenuePhysicalPointState {
        let world = effectiveWorldPosition(for: slotID)
        return VenuePhysicalPointState(x: world.x / 100, y: world.y / 100, z: world.z / 100)
    }

    func setFixturePositionMeters(for slotID: String, axis: String, value: Double) {
        guard isEditingProjectionLayout, value.isFinite else { return }
        var world = effectiveWorldPosition(for: slotID)
        let centimeters = value * 100
        switch axis.lowercased() {
        case "x": world.x = min(max(centimeters, StageWorld.minX), StageWorld.maxX)
        case "y": world.y = min(max(centimeters, StageWorld.minY), StageWorld.maxY)
        case "z": world.z = min(max(centimeters, StageWorld.minZ), StageWorld.maxZ)
        default: return
        }
        // Numeric entry intentionally preserves 0.01 m precision and is not
        // quantized to the visual drag grid.
        projectionLayoutDrafts[slotID] = world
    }

    func rotateSelectedProjectionOrientation(by degrees: Double) {
        guard isEditingProjectionLayout, !selectedSlotID.isEmpty else { return }
        rotateProjectionOrientation(for: selectedSlotID, by: degrees)
    }

    func rotateSelectedProjectionMountPitch(by degrees: Double) {
        guard isEditingProjectionLayout, !selectedSlotID.isEmpty else { return }
        rotateProjectionMountPitch(for: selectedSlotID, by: degrees)
    }

    func rotateSelectedProjectionRoll(by degrees: Double) {
        guard isEditingProjectionLayout, !selectedSlotID.isEmpty else { return }
        rotateProjectionRoll(for: selectedSlotID, by: degrees)
    }

    func toggleSelectedProjectionPanFlip() {
        guard isEditingProjectionLayout, !selectedSlotID.isEmpty else { return }
        toggleProjectionPanFlip(for: selectedSlotID)
    }

    func toggleSelectedProjectionTiltFlip() {
        guard isEditingProjectionLayout, !selectedSlotID.isEmpty else { return }
        toggleProjectionTiltFlip(for: selectedSlotID)
    }

    func rotateProjectionOrientation(for slotID: String, by degrees: Double) {
        guard isEditingProjectionLayout else { return }
        var world = effectiveWorldPosition(for: slotID)
        world.yawDegrees = snappedYawDegrees(world.yawDegrees + degrees)
        projectionLayoutDrafts[slotID] = world
    }

    func rotateProjectionMountPitch(for slotID: String, by degrees: Double) {
        guard isEditingProjectionLayout else { return }
        var world = effectiveWorldPosition(for: slotID)
        world.pitchDegrees = snappedPitchDegrees(world.pitchDegrees + degrees)
        projectionLayoutDrafts[slotID] = world
    }

    func rotateProjectionRoll(for slotID: String, by degrees: Double) {
        guard isEditingProjectionLayout else { return }
        var world = effectiveWorldPosition(for: slotID)
        world.rollDegrees = snappedRollDegrees(world.rollDegrees + degrees)
        projectionLayoutDrafts[slotID] = world
    }

    func toggleProjectionPanFlip(for slotID: String) {
        guard isEditingProjectionLayout, let editor = editorsByID[slotID], editor.supportsPan else { return }
        var world = effectiveWorldPosition(for: slotID)
        world.panFlip.toggle()
        projectionLayoutDrafts[slotID] = world
    }

    func toggleProjectionTiltFlip(for slotID: String) {
        guard isEditingProjectionLayout, let editor = editorsByID[slotID], editor.supportsTilt else { return }
        var world = effectiveWorldPosition(for: slotID)
        world.tiltFlip.toggle()
        projectionLayoutDrafts[slotID] = world
    }

    func projectionYawDegrees(for slotID: String) -> Double {
        effectiveWorldPosition(for: slotID).yawDegrees
    }

    func projectionPitchDegrees(for slotID: String) -> Double {
        effectiveWorldPosition(for: slotID).pitchDegrees
    }

    func projectionRollDegrees(for slotID: String) -> Double {
        effectiveWorldPosition(for: slotID).rollDegrees
    }

    func projectionPanFlip(for slotID: String) -> Bool {
        effectiveWorldPosition(for: slotID).panFlip
    }

    func projectionTiltFlip(for slotID: String) -> Bool {
        effectiveWorldPosition(for: slotID).tiltFlip
    }

    func setPreviewFineTune(slotID: String, pan: Int? = nil, tilt: Int? = nil) {
        guard let editor = editorsByID[slotID], editor.supportsPan || editor.supportsTilt else { return }
        beginLocalMutationHold(seconds: 1.2)
        editor.syncEnabled = false
        if let pan, editor.supportsPan {
            editor.pan = clampDMX(pan)
        }
        if let tilt, editor.supportsTilt {
            editor.tilt = clampDMX(tilt)
        }
        push(editor)
    }

    func nudgePreviewSelection(panDelta: Int = 0, tiltDelta: Int = 0) {
        let editors = previewSelectedMovingHeadEditors
        guard !editors.isEmpty else { return }
        beginLocalMutationHold(seconds: 1.2)
        for editor in editors {
            editor.syncEnabled = false
            if editor.supportsPan, panDelta != 0 {
                editor.pan = clampDMX(editor.pan + panDelta)
            }
            if editor.supportsTilt, tiltDelta != 0 {
                editor.tilt = clampDMX(editor.tilt + tiltDelta)
            }
            push(editor)
        }
    }

    func moveFixtureHome(_ editor: SlotEditor) {
        guard editor.supportsPan || editor.supportsTilt || editor.supportsPanTiltSpeed else { return }
        beginLocalMutationHold(seconds: 1.2)
        editor.syncEnabled = false
        if editor.supportsPan {
            editor.pan = 127
        }
        if editor.supportsTilt {
            editor.tilt = 127
        }
        if editor.supportsPanTiltSpeed {
            editor.panTiltSpeed = 0
        }
        if editor.supportsStrobe {
            editor.strobe = 0
        }
        push(editor)
    }

    func push(_ editor: SlotEditor) {
        schedulePush(for: editor)
    }

    func captureCurrentPose(_ kind: String, for editor: SlotEditor) {
        let pose = SlotPose(pan: clampDMX(editor.pan), tilt: clampDMX(editor.tilt))
        switch kind {
        case "center":
            editor.poseCenter = pose
        case "audience_left":
            editor.poseAudienceLeft = pose
        case "audience_center":
            editor.poseAudienceCenter = pose
        case "audience_right":
            editor.poseAudienceRight = pose
        case "ceiling_center":
            editor.poseCeilingCenter = pose
        default:
            return
        }
        push(editor)
    }

    private func schedulePush(for editor: SlotEditor, debounceNanoseconds: UInt64 = 120_000_000) {
        activeLivePreset = nil
        clearLivePresetRestoreState()
        beginLocalMutationHold(seconds: 1.2)
        let slotID = editor.id
        slotPushTasks[slotID]?.cancel()
        let token = nextSlotPushToken
        nextSlotPushToken += 1
        slotPushTokens[slotID] = token
        slotPushTasks[slotID] = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                try await Task.sleep(nanoseconds: debounceNanoseconds)
            } catch {
                return
            }
            guard !Task.isCancelled else { return }
            await self.performSlotPush(slotID: slotID, token: token)
        }
    }

    private func performSlotPush(slotID: String, token: Int) async {
        guard slotPushTokens[slotID] == token else { return }
        guard let editor = editorsByID[slotID] else { return }
        do {
            beginLocalMutationHold(seconds: 1.2)
            let payload = SlotUpdateRequest(slotID: editor.id, activeSlot: editor.id, slot: updateBody(for: editor))
            let state: AppState = try await post("/api/dmx/update", body: payload, as: AppState.self)
            guard slotPushTokens[slotID] == token else { return }
            slotPushTasks[slotID] = nil
            apply(state, source: .action)
            errorText = ""
        } catch {
            guard slotPushTokens[slotID] == token else { return }
            slotPushTasks[slotID] = nil
            errorText = "Fixture update mislukt: \(error.localizedDescription)"
        }
    }

    private func cancelPendingSlotPushes() {
        for task in slotPushTasks.values {
            task.cancel()
        }
        slotPushTasks.removeAll()
        slotPushTokens.removeAll()
    }

    private func pushAll(activeSlotID: String, autoShow: AutoShowUpdateBody? = nil) {
        cancelPendingSlotPushes()
        Task {
            do {
                beginLocalMutationHold()
                let payload = MultiSlotUpdateRequest(
                    activeSlot: activeSlotID,
                    slots: Dictionary(uniqueKeysWithValues: slotEditors.map { ($0.id, updateBody(for: $0)) }),
                    autoShow: autoShow
                )
                let state: AppState = try await post("/api/dmx/update", body: payload, as: AppState.self)
                apply(state, source: .action)
                errorText = ""
            } catch {
                errorText = "Preset update mislukt: \(error.localizedDescription)"
            }
        }
    }

    private func updateBody(for editor: SlotEditor) -> SlotUpdateBody {
        SlotUpdateBody(
            enabled: editor.enabled,
            fixture: editor.fixtureID,
            mode: editor.mode,
            address: editor.address,
            group: editor.groupID,
            syncEnabled: editor.syncEnabled,
            beatPulseEnabled: editor.beatPulseEnabled,
            oscStrobeEnabled: editor.oscStrobeEnabled,
            useFinePanTilt: editor.useFinePanTilt,
            panInvert: editor.panInvert,
            tiltInvert: editor.tiltInvert,
            panOffsetDeg: editor.panOffsetDeg,
            tiltOffsetDeg: editor.tiltOffsetDeg,
            panSpanPercent: editor.panSpanPercent,
            tiltSpanPercent: editor.tiltSpanPercent,
            panLeftValue: editor.panLeftValue,
            panRightValue: editor.panRightValue,
            tiltBackValue: editor.tiltBackValue,
            tiltFrontValue: editor.tiltFrontValue,
            poseCenter: editor.poseCenter,
            poseAudienceLeft: editor.poseAudienceLeft,
            poseAudienceCenter: editor.poseAudienceCenter,
            poseAudienceRight: editor.poseAudienceRight,
            poseCeilingCenter: editor.poseCeilingCenter,
            colorSource: editor.colorSource,
            dimmer: editor.dimmer,
            strobe: editor.strobe,
            program: editor.program,
            speed: editor.speed,
            extraValues: editor.extraValues,
            pan: editor.pan,
            tilt: editor.tilt,
            panTiltSpeed: editor.panTiltSpeed,
            beatDepth: editor.beatDepth,
            beatDecayMs: editor.beatDecayMs,
            color: SlotColorPayload(
                red: editor.red,
                green: editor.green,
                blue: editor.blue,
                white: editor.white
            )
        )
    }

    private func captureLivePresetRestoreStateIfNeeded() {
        guard livePresetRestoreSlots == nil else { return }
        livePresetRestoreSlots = Dictionary(uniqueKeysWithValues: slotEditors.map { ($0.id, updateBody(for: $0)) })
        livePresetRestoreAutoShow = currentAutoShowUpdateBody(enabled: autoShowEnabled, style: autoShowStyle)
    }

    private func clearLivePresetRestoreState() {
        livePresetRestoreSlots = nil
        livePresetRestoreAutoShow = nil
    }

    private func restoreLivePresetState() {
        guard let restoreSlots = livePresetRestoreSlots else {
            activeLivePreset = nil
            return
        }
        cancelPendingSlotPushes()
        let restoreAutoShow = livePresetRestoreAutoShow ?? currentAutoShowUpdateBody(enabled: false, style: autoShowStyle)
        activeLivePreset = nil
        autoShowEnabled = restoreAutoShow.enabled
        autoShowStyle = restoreAutoShow.style
        clearLivePresetRestoreState()
        Task {
            do {
                beginLocalMutationHold()
                let activeSlot = selectedSlotID.isEmpty ? (slotEditors.first?.id ?? "head") : selectedSlotID
                let payload = MultiSlotUpdateRequest(
                    activeSlot: activeSlot,
                    slots: restoreSlots,
                    autoShow: restoreAutoShow
                )
                let state: AppState = try await post("/api/dmx/update", body: payload, as: AppState.self)
                apply(state, source: .action)
                errorText = ""
            } catch {
                errorText = "Preset restore mislukt: \(error.localizedDescription)"
            }
        }
    }

    private func label(forAutoShowStyle style: String) -> String {
        switch style {
        case "club": return "Club"
        case "cinematic": return "Cinematic"
        case "warm": return "Warm"
        case "festival": return "Festival"
        case "minimal": return "Minimal"
        default: return "Adaptive"
        }
    }

    private func beginLocalMutationHold(seconds: TimeInterval = 0.6) {
        ignorePolledStateUntil = Date().addingTimeInterval(seconds)
    }

    private func transportModeLabel(for value: String) -> String {
        switch value {
        case "manual_tap":
            return "Tap"
        case "external_osc":
            return "OSC"
        default:
            return "Auto"
        }
    }

    private func transportResolvedLabel(for value: String) -> String {
        switch value {
        case "manual_tap":
            return "Tap tempo actief"
        case "idle":
            return "Interne idle-clock actief"
        case "external_osc":
            return "Externe OSC actief"
        default:
            return "Clock actief"
        }
    }

    private func transportPhraseLabel(for value: String) -> String {
        switch value {
        case "intro": return "Intro"
        case "build": return "Build"
        case "chorus": return "Chorus"
        case "drop": return "Drop"
        case "down": return "Down"
        case "break": return "Break"
        case "outro": return "Outro"
        default: return "Verse"
        }
    }

    private func currentTransportUpdateBody() -> TransportUpdateRequest {
        TransportUpdateRequest(
            mode: transportMode,
            manualPhrase: transportManualPhrase,
            idleAnimationEnabled: transportIdleAnimationEnabled
        )
    }

    private func postTransportUpdate() {
        Task {
            do {
                let state: AppState = try await post("/api/transport/update", body: currentTransportUpdateBody(), as: AppState.self)
                apply(state, source: .action)
                errorText = ""
            } catch {
                errorText = "Transport update mislukt: \(error.localizedDescription)"
            }
        }
    }

    func setStructureBehaviorSource(_ source: String) {
        let normalized = source == "song_analyzer" ? "song_analyzer" : "legacy"
        structureBehaviorSource = normalized
        Task {
            do {
                let state: StructureBehaviorUpdateResponse = try await post(
                    "/api/developer/structure-behavior",
                    body: StructureBehaviorUpdateRequest(source: normalized),
                    as: StructureBehaviorUpdateResponse.self
                )
                structureBehaviorSource = state.selectedSource == "song_analyzer" ? "song_analyzer" : "legacy"
                errorText = ""
            } catch {
                structureBehaviorSource = "legacy"
                errorText = "Structuurbron wijzigen mislukt: \(error.localizedDescription)"
            }
        }
    }

    nonisolated private func bridgeCanUsePasswordlessSudo(scriptPath: String, oscDestination: String) -> Bool {
        guard !scriptPath.isEmpty else { return false }
        let canStart = runSystemProcess("/usr/bin/sudo", ["-n", "-l", scriptPath, oscDestination]).ok
        let canStop = runSystemProcess("/usr/bin/sudo", ["-n", "-l", "/usr/bin/pkill", "-f", "rkbx_link"]).ok
        return canStart && canStop
    }

    private func currentAutoShowUpdateBody(enabled: Bool? = nil, style: String? = nil) -> AutoShowUpdateBody {
        AutoShowUpdateBody(
            enabled: enabled ?? autoShowEnabled,
            style: style ?? autoShowStyle,
            previewRmeMode: previewRmeMode,
            audiencePanFocusEnabled: autoShowAudiencePanFocusEnabled,
            audiencePanMin: autoShowAudiencePanMin,
            audiencePanMax: autoShowAudiencePanMax,
            audienceTurnPanMin: autoShowAudienceTurnPanMin,
            audienceTurnPanMax: autoShowAudienceTurnPanMax,
            audienceTiltSplit: autoShowAudienceTiltSplit,
            overrideColor: liveOverrideColor,
            overrideColorCombo: liveOverrideColorCombo,
            overrideManualStrobe: liveOverrideManualStrobe,
            overrideAudienceSweep: liveOverrideAudienceSweep,
            overrideAllOn: liveOverrideAllOn,
            overrideParChase: liveOverrideParChase,
            overrideParSnake: liveOverrideParSnake
        )
    }

    private func setPendingAutoShowRequest(_ request: AutoShowUpdateBody) {
        pendingAutoShowRequest = request
        pendingAutoShowDeadline = Date().addingTimeInterval(1.2)
    }

    private func clearPendingAutoShowRequest() {
        pendingAutoShowRequest = nil
        pendingAutoShowDeadline = Date.distantPast
    }

    private func shouldKeepPendingAutoShow(against remote: AutoShowState, source: StateApplySource) -> Bool {
        guard let pending = pendingAutoShowRequest else { return false }
        let matches =
            remote.enabled == pending.enabled &&
            remote.style == pending.style &&
            remote.previewRmeMode == pending.previewRmeMode &&
            remote.audiencePanFocusEnabled == pending.audiencePanFocusEnabled &&
            remote.audiencePanMin == pending.audiencePanMin &&
            remote.audiencePanMax == pending.audiencePanMax &&
            remote.audienceTurnPanMin == pending.audienceTurnPanMin &&
            remote.audienceTurnPanMax == pending.audienceTurnPanMax &&
            remote.audienceTiltSplit == pending.audienceTiltSplit &&
            remote.overrideColor == pending.overrideColor &&
            remote.overrideColorCombo == pending.overrideColorCombo &&
            remote.overrideManualStrobe == pending.overrideManualStrobe &&
            remote.overrideAudienceSweep == pending.overrideAudienceSweep &&
            remote.overrideAllOn == pending.overrideAllOn &&
            remote.overrideParChase == pending.overrideParChase &&
            remote.overrideParSnake == pending.overrideParSnake
        if source == .action || matches || Date() >= pendingAutoShowDeadline {
            clearPendingAutoShowRequest()
            return false
        }
        return true
    }

    func boolBinding(for editor: SlotEditor, _ keyPath: ReferenceWritableKeyPath<SlotEditor, Bool>) -> Binding<Bool> {
        Binding(
            get: { editor[keyPath: keyPath] },
            set: { value in
                editor[keyPath: keyPath] = value
                self.push(editor)
            }
        )
    }

    func intBinding(for editor: SlotEditor, _ keyPath: ReferenceWritableKeyPath<SlotEditor, Int>, range: ClosedRange<Int>) -> Binding<Double> {
        Binding(
            get: { Double(editor[keyPath: keyPath]) },
            set: { value in
                let rounded = Int(value.rounded())
                editor[keyPath: keyPath] = min(range.upperBound, max(range.lowerBound, rounded))
                self.push(editor)
            }
        )
    }

    func extraIntBinding(for editor: SlotEditor, controlID: String, range: ClosedRange<Int> = 0...255) -> Binding<Double> {
        Binding(
            get: {
                let fallback = editor.extraControls.first(where: { $0.id == controlID })?.defaultValue ?? 0
                return Double(editor.extraValues[controlID] ?? fallback)
            },
            set: { value in
                let rounded = Int(value.rounded())
                editor.extraValues[controlID] = min(range.upperBound, max(range.lowerBound, rounded))
                self.push(editor)
            }
        )
    }

    func stepperBinding(for editor: SlotEditor, _ keyPath: ReferenceWritableKeyPath<SlotEditor, Int>, range: ClosedRange<Int>) -> Binding<Int> {
        Binding(
            get: { editor[keyPath: keyPath] },
            set: { value in
                editor[keyPath: keyPath] = min(range.upperBound, max(range.lowerBound, value))
                self.push(editor)
            }
        )
    }

    func stringBinding(for editor: SlotEditor, _ keyPath: ReferenceWritableKeyPath<SlotEditor, String>) -> Binding<String> {
        Binding(
            get: { editor[keyPath: keyPath] },
            set: { value in
                editor[keyPath: keyPath] = value
                self.push(editor)
            }
        )
    }

    private func postAutoShow(_ requestBody: AutoShowUpdateBody) {
        Task {
            do {
                beginLocalMutationHold()
                let activeSlot = selectedSlotID.isEmpty ? (slotEditors.first?.id ?? "head") : selectedSlotID
                let payload = AutoShowUpdateRequest(
                    activeSlot: activeSlot,
                    autoShow: requestBody
                )
                let state: AppState = try await post("/api/dmx/update", body: payload, as: AppState.self)
                apply(state, source: .action)
                errorText = ""
            } catch {
                clearPendingAutoShowRequest()
                errorText = "Auto Show update mislukt: \(error.localizedDescription)"
            }
        }
    }

    private func bootstrap() async {
        do {
            nativeLog("bootstrap start")
            let reachable = try await backendReachable()
            if reachable {
                let compatible = try await backendSchemaCompatible()
                if !compatible {
                    nativeLog("backend reachable but incompatible, restarting local backend")
                    try await terminateIncompatibleBackendIfNeeded()
                    try startBackend()
                    try await waitForBackend()
                } else {
                    try adoptReachableBackendIfNeeded()
                }
            } else {
                nativeLog("backend not reachable, starting local backend")
                try startBackend()
                try await waitForBackend()
            }
            nativeLog("backend reachable, loading state")
            try await loadPorts()
            try await loadFixtures()
            try await refreshState(forceSelectionToActiveSlot: true)
            refreshAudioInputs()
            refreshBridgeStatus(force: true)
            startStageSimulation()
            startPolling()
        } catch let error as BackendResponseDecodeFailure {
            nativeLog("bootstrap backend response decode failure for \(error.requestPath): \(describeDecodingError(error.underlyingError))")
            errorText = "Native app kon backendstatus niet lezen. Zie het lokale logbestand."
        } catch {
            nativeLog("bootstrap error: \(error.localizedDescription)")
            errorText = "Native app kon backend niet starten: \(error.localizedDescription)"
        }
    }

    private func startPolling() {
        pollingTask?.cancel()
        pollingTask = Task {
            while !Task.isCancelled {
                do {
                    try await refreshState()
                    clearRecoveredStatusPollError()
                    refreshBridgeStatus()
                } catch {
                    errorText = "Status ophalen mislukt: \(error.localizedDescription)"
                }
                try? await Task.sleep(nanoseconds: 33_000_000)
            }
        }
    }

    private func clearRecoveredStatusPollError() {
        guard errorText.hasPrefix("Status ophalen mislukt:") else { return }
        errorText = ""
    }

    private func loadPorts() async throws {
        let response: PortsResponse = try await get("/api/ports", as: PortsResponse.self)
        ports = response.ports
        if !response.ports.contains(where: { $0.label == selectedPortLabel }) {
            selectedPortLabel = response.ports.first(where: { $0.device.contains("usbserial") })?.label
                ?? response.ports.first?.label
                ?? ""
        }
    }

    private func loadFixtures() async throws {
        let response: FixturesResponse = try await get("/api/fixtures", as: FixturesResponse.self)
        availableFixtures = response.fixtures.sorted { $0.displayName.localizedStandardCompare($1.displayName) == .orderedAscending }
    }

    private func refreshState(forceSelectionToActiveSlot: Bool = false) async throws {
        let state: AppState = try await get("/api/state", as: AppState.self)
        apply(state, forceSelectionToActiveSlot: forceSelectionToActiveSlot, source: .poll)
    }

    private enum StateApplySource {
        case poll
        case action
    }

    private func apply(_ state: AppState, forceSelectionToActiveSlot: Bool = false, source: StateApplySource = .action) {
        if source == .poll, Date() < ignorePolledStateUntil {
            return
        }
        if let remote = state.remote {
            nativeLog("remote state decoded: preferred=\(redactedRemoteURL(remote.preferredUrl)) usb=\(redactedRemoteURL(remote.usbUrl)) tailscale=\(redactedRemoteURL(remote.tailscaleUrl)) lan=\(redactedRemoteURL(remote.lanUrl)) local=\(redactedRemoteURL(remote.localUrl))")
            remoteURLText = remote.preferredUrl ?? remote.usbUrl ?? remote.tailscaleUrl ?? remote.lanUrl ?? remote.localUrl ?? "-"
            remoteTailscaleURLText = remote.tailscaleUrl ?? "-"
            remotePairingCodeText = remote.pairingCode ?? "-"
            if let usbUrl = remote.usbUrl, !usbUrl.isEmpty, remoteURLText == usbUrl {
                remoteStatusText = "USB/Wired remote: \(usbUrl)"
            } else if let tailscaleUrl = remote.tailscaleUrl, !tailscaleUrl.isEmpty {
                remoteStatusText = "Tailscale remote: \(tailscaleUrl)"
            } else if let lanUrl = remote.lanUrl, !lanUrl.isEmpty {
                remoteStatusText = "LAN remote: \(lanUrl)"
            } else if let localUrl = remote.localUrl, !localUrl.isEmpty {
                remoteStatusText = "Alleen lokaal beschikbaar: \(localUrl)"
            } else {
                remoteStatusText = remote.enabled ? "Geen bruikbaar LAN-adres gevonden" : "Remote alleen lokaal bereikbaar"
            }
        } else {
            remoteURLText = "-"
            remoteTailscaleURLText = "-"
            remoteStatusText = "Remote info niet beschikbaar"
            remotePairingCodeText = "-"
        }
        transportMode = state.transport.mode
        transportResolvedMode = state.transport.resolvedMode
        transportManualBpm = state.transport.manualBpm
        transportEffectiveBpm = state.transport.effectiveBpm
        transportManualPhrase = state.transport.manualPhrase
        transportManualPhraseLabel = state.transport.manualPhraseLabel
        transportIdleAnimationEnabled = state.transport.idleAnimationEnabled
        transportTapCount = state.transport.tapCount
        transportTapLocked = state.transport.tapLocked
        transportExternalAvailable = state.transport.externalAvailable
        transportStatusText = transportResolvedLabel(for: state.transport.resolvedMode)
        debugState = state.debug
        liveUiState = state.liveUi
        liveIntensityState = state.dmx.autoShow.liveIntensity
        physicalDmxConnected = state.dmx.connected
        physicalDmxError = state.dmx.error
        blackoutActive = state.dmx.blackoutActive
        structureBehaviorSource = state.developerStructureBehavior?.selectedSource == "song_analyzer"
            ? "song_analyzer" : "legacy"
        slotPreviews = state.dmx.slotPreviews
        reconcileManualSmoke(state.dmx.manualSmoke)
        renderedMotion = state.dmx.renderedMotion
        venueSpace = state.dmx.venueSpace
        venueTargetTestState = state.dmx.venueTargetTest
        movementLabState = state.dmx.movementLab
        reconcileVenueTargetPresentation(state.dmx.venueTargetTest)
        if state.dmx.venueTargetTest?.active != true {
            stopVenueTargetLeaseHeartbeat()
        }
        fixtureCalibrations = Dictionary(uniqueKeysWithValues: (state.dmx.venueSpace?.fixtures ?? []).map { ($0.slotID, $0) })
        if !venueGeometryFieldsInitialized, let geometry = state.dmx.venueSpace?.venueGeometry {
            venueWidthMetersText = geometry.venueWidthM.map { String(format: "%.2f", $0) } ?? ""
            venueForwardDepthMetersText = geometry.venueForwardDepthM.map { String(format: "%.2f", $0) } ?? ""
            venueRearDepthMetersText = geometry.venueRearDepthM.map { String(format: "%.2f", $0) } ?? ""
            audienceTargetHeightMetersText = geometry.audienceTargetHeightM.map { String(format: "%.2f", $0) } ?? ""
            ceilingHeightMetersText = geometry.ceilingHeightM.map { String(format: "%.2f", $0) } ?? ""
            venueGeometryFieldsInitialized = true
        }
        previewComposition = state.dmx.rmePreviewDifferential
        physicalOutputSource = state.dmx.rmePreviewDifferential?.physicalOutputSource ?? "auto_show -> current_values"
        productionShowSource = state.dmx.rmePreviewDifferential?.productionSource ?? "existing_autoshow"
        productionShowMode = state.dmx.productionShowSelector?.productionMode ?? "BASELINE_ONLY"
        productionFallbackActive = state.dmx.productionShowSelector?.fallbackActive ?? false
        productionFallbackReason = state.dmx.productionShowSelector?.fallbackReason
        previewPulseTestMode = state.dmx.previewPulseTest?.mode ?? "OFF"
        dmxSlotOrder = state.dmx.slotOrder
        dmxSlotRanges = state.dmx.slotRanges
        dmxValues = Dictionary(uniqueKeysWithValues: state.dmx.values.compactMap { key, value in
            guard let channel = Int(key) else { return nil }
            return (channel, value)
        })
        dmxConflicts = state.dmx.conflicts
        if let previewState = state.dmx.developerVirtualdjBeatPulsePreview {
            applyVirtualDjBeatPulsePreview(previewState)
        }
        liveOneShotCue = state.dmx.autoShow.oneShotCue
        liveOneShotCueLabel = state.dmx.autoShow.oneShotLabel
        liveOneShotCueProgress = state.dmx.autoShow.oneShotProgress
        let pendingAutoShowMismatch = shouldKeepPendingAutoShow(against: state.dmx.autoShow, source: source)
        if !pendingAutoShowMismatch {
            autoShowEnabled = state.dmx.autoShow.enabled
            autoShowAvailable = state.dmx.autoShow.available
            autoShowStyle = state.dmx.autoShow.style
            autoShowStyleLabel = state.dmx.autoShow.styleLabel
            previewRmeMode = state.dmx.autoShow.previewRmeMode
            autoShowCueText = state.dmx.autoShow.cueLabel
            autoShowAudiencePanFocusEnabled = state.dmx.autoShow.audiencePanFocusEnabled
            autoShowAudiencePanMin = state.dmx.autoShow.audiencePanMin
            autoShowAudiencePanMax = state.dmx.autoShow.audiencePanMax
            autoShowAudienceTurnPanMin = state.dmx.autoShow.audienceTurnPanMin
            autoShowAudienceTurnPanMax = state.dmx.autoShow.audienceTurnPanMax
            autoShowAudienceTiltSplit = state.dmx.autoShow.audienceTiltSplit
            liveOverrideColor = state.dmx.autoShow.overrideColor
            liveOverrideColorLabel = state.dmx.autoShow.overrideColorLabel
            liveOverrideColorCombo = state.dmx.autoShow.overrideColorCombo
            liveOverrideManualStrobe = state.dmx.autoShow.overrideManualStrobe
            liveOverrideAudienceSweep = state.dmx.autoShow.overrideAudienceSweep
            liveOverrideAllOn = state.dmx.autoShow.overrideAllOn
            liveOverrideParChase = state.dmx.autoShow.overrideParChase
            liveOverrideParSnake = state.dmx.autoShow.overrideParSnake
            let overrideParts = [
                state.dmx.autoShow.overrideColor != "none" ? state.dmx.autoShow.overrideColorLabel : nil,
                state.dmx.autoShow.overrideManualStrobe ? "strobe" : nil,
                state.dmx.autoShow.overrideAudienceSweep ? "audience sweep" : nil,
                state.dmx.autoShow.overrideAllOn ? "all on" : nil,
                state.dmx.autoShow.overrideParChase ? "par chase" : nil,
                state.dmx.autoShow.overrideParSnake ? "par snake" : nil,
                state.dmx.autoShow.oneShotActive ? "cue \(state.dmx.autoShow.oneShotLabel)" : nil,
            ].compactMap { $0 }
            let overrideText = overrideParts.isEmpty ? "none" : overrideParts.joined(separator: ", ")
            let panFocusText = state.dmx.autoShow.audiencePanFocusEnabled
                ? "front \(state.dmx.autoShow.audiencePanMin)-\(state.dmx.autoShow.audiencePanMax) • turn \(state.dmx.autoShow.audienceTurnPanMin)-\(state.dmx.autoShow.audienceTurnPanMax) • split \(state.dmx.autoShow.audienceTiltSplit)"
                : "pan free"
            let intensity = state.dmx.autoShow.liveIntensity
            let analyzedPercent = Int(((intensity?.analyzedIntensity ?? state.dmx.autoShow.energy) * 100).rounded())
            let liveIntensityText: String
            if intensity?.sourceValid == true {
                let rawPercent = Int(((intensity?.rawSourceLevel ?? 0) * 100).rounded())
                let livePercent = Int(((intensity?.liveIntensity ?? 0) * 100).rounded())
                let effectivePercent = Int(((intensity?.effectiveIntensity ?? state.dmx.autoShow.energy) * 100).rounded())
                let modifierPercent = Int(((intensity?.liveModifier ?? 0) * 100).rounded())
                let modifier = String(format: "%+d%%", modifierPercent)
                let deck = intensity?.sourceDeck.map { "Deck \($0)" } ?? "Deck —"
                let age = intensity?.sourceAgeMilliseconds.map { "age \(Int($0.rounded())) ms" } ?? "age —"
                liveIntensityText = "Analyzed \(analyzedPercent)% • Raw \(rawPercent)% • Live \(livePercent)% • Modifier \(modifier) • Effective \(effectivePercent)% • \(deck) • \(age)"
            } else {
                let reason = intensity?.fallbackReason ?? "missing"
                let raw = intensity?.rawSourceLevel.map { "Raw \(Int(($0 * 100).rounded()))%" }
                let deck = intensity?.sourceDeck.map { "Deck \($0)" }
                let age = intensity?.sourceAgeMilliseconds.map { "age \(Int($0.rounded())) ms" }
                let source = [raw, deck, age].compactMap { $0 }.joined(separator: " • ")
                liveIntensityText = "Analyzed \(analyzedPercent)% • Live fallback (\(reason))" +
                    (source.isEmpty ? "" : " • \(source)")
            }
            autoShowDetailText = "Source \(state.dmx.autoShow.colorSource) • energy \(Int((state.dmx.autoShow.energy * 100).rounded()))% • \(liveIntensityText) • move \(Int((state.dmx.autoShow.movement * 100).rounded()))% • beat \(state.dmx.autoShow.beatPulse ? "on" : "off") • \(panFocusText) • override \(overrideText)"
        }
        if autoShowEnabled {
            activeLivePreset = nil
        }
        if state.dmx.connected, let port = state.dmx.port {
            dmxStatus = "DMX actief op \(port) @ \(Int(state.dmx.fps.rounded())) fps"
        } else {
            dmxStatus = "DMX niet verbonden"
        }
        if let error = state.dmx.error, !error.isEmpty {
            dmxStatus += " | fout: \(error)"
        }

        var oscParts = ["OSC UDP \(state.osc.port)"]
        if let bpm = state.osc.bpm {
            oscParts.append(String(format: "BPM %.2f", bpm))
        }
        if let beatDisplay = state.osc.beatDisplay {
            oscParts.append("Beat \(Int(beatDisplay.rounded(.down)))")
        } else if let beat = state.osc.beat {
            let beatNumber = Int(beat.rounded(.down)).quotientAndRemainder(dividingBy: 4).remainder + 1
            oscParts.append("Beat \(beatNumber) raw")
        }
        if let phrase = state.osc.phraseCurrent, !phrase.isEmpty {
            oscParts.append("Phrase \(phrase)")
        }
        if state.osc.stale {
            oscParts.append("geen recente data")
        }
        if let error = state.osc.error, !error.isEmpty {
            oscParts.append("fout: \(error)")
        }
        oscStatus = oscParts.joined(separator: " | ")
        let liveSource = state.source.lastSource ?? "geen bron"
        let sourceLabel = transportModeLabel(for: state.source.mode)
        let resolvedLabel = transportResolvedLabel(for: state.source.resolvedMode ?? state.transport.resolvedMode)
        oscSourceStatus = "\(sourceLabel) • \(resolvedLabel) • \(state.source.app) • \(state.source.expectedDestination) • bron \(liveSource)"

        let liveUi = state.liveUi?.source == "virtualdj" ? state.liveUi : nil

        let loadedTitle = normalizedDisplay(
            state.osc.trackTitle ?? deckTitleFallback(from: state),
            fallback: "(geen track)"
        )
        let loadedArtist = normalizedDisplay(
            state.osc.trackArtist ?? deckArtistFallback(from: state),
            fallback: "onbekend"
        )
        let loadedAlbum = normalizedDisplay(
            state.osc.trackAlbum ?? deckAlbumFallback(from: state),
            fallback: ""
        )
        trackTitle = loadedTitle
        trackMeta = loadedAlbum.isEmpty ? loadedArtist : "\(loadedArtist) • \(loadedAlbum)"

        let deck1 = deckState(state, logicalDeckNumber: 1)
        let deck2 = deckState(state, logicalDeckNumber: 2)
        deck1Title = "Deck 1"
        deck1Meta = [
            normalizedDisplay(deck1?.trackTitle, fallback: "(geen track)"),
            normalizedDisplay(deck1?.trackArtist, fallback: "onbekend")
        ].joined(separator: " • ")
        deck1Time = formatTime(deck1?.timeDisplaySeconds ?? deck1?.timeSeconds)
        deck2Title = "Deck 2"
        deck2Meta = [
            normalizedDisplay(deck2?.trackTitle, fallback: "(geen track)"),
            normalizedDisplay(deck2?.trackArtist, fallback: "onbekend")
        ].joined(separator: " • ")
        deck2Time = formatTime(deck2?.timeDisplaySeconds ?? deck2?.timeSeconds)

        if let liveUi {
            trackTitle = normalizedDisplay(liveUi.trackTitle, fallback: loadedTitle)
            trackMeta = normalizedDisplay(liveUi.trackArtist, fallback: loadedArtist)
            func liveDeckMeta(_ deck: LiveDeckState?) -> String {
                guard let deck, deck.isLoaded == true else { return "(geen track)" }
                let artist = normalizedDisplay(deck.trackArtist, fallback: "onbekend")
                let bpm = deck.bpm.map { formatNumber($0) + " BPM" } ?? "BPM -"
                let beat = deck.beatNumber.map(String.init) ?? "Beat -"
                let bar = deck.barNumber.map { "Bar \($0)" } ?? "Bar -"
                let phrase = normalizedDisplay(deck.phrase, fallback: "Phrase -")
                let status = normalizedDisplay(deck.prewarmStatus ?? deck.analysisStatus, fallback: "Loaded")
                return "\(artist) • \(bpm) · \(beat) · \(bar)\n\(phrase) · \(status)"
            }

            let liveDeck1 = liveUi.decks?.first { $0.deckNumber == 1 }
            let liveDeck2 = liveUi.decks?.first { $0.deckNumber == 2 }
            deck1Title = liveDeck1?.isLoaded == true
                ? normalizedDisplay(liveDeck1?.trackTitle, fallback: "Deck 1")
                : "Deck 1"
            deck1Meta = liveDeckMeta(liveDeck1)
            deck1Time = liveDeck1?.positionMilliseconds.map { formatTime(Double($0) / 1000.0) } ?? "-"
            deck1IsActive = liveDeck1?.isActive == true || liveUi.activeDeckNumber == 1
            deck2Title = liveDeck2?.isLoaded == true
                ? normalizedDisplay(liveDeck2?.trackTitle, fallback: "Deck 2")
                : "Deck 2"
            deck2Meta = liveDeckMeta(liveDeck2)
            deck2Time = liveDeck2?.positionMilliseconds.map { formatTime(Double($0) / 1000.0) } ?? "-"
            deck2IsActive = liveDeck2?.isActive == true || liveUi.activeDeckNumber == 2
        } else {
            deck1IsActive = false
            deck2IsActive = false
        }

        var bpmText = formatNumber(state.osc.bpm)
        var beatText: String
        if let beatDisplay = state.osc.beatDisplay {
            beatText = String(format: "%.2f", beatDisplay)
        } else if let beat = state.osc.beat {
            let beatNumber = Int(beat.rounded(.down)).quotientAndRemainder(dividingBy: 4).remainder + 1
            beatText = "\(beatNumber)"
        } else {
            beatText = "-"
        }
        if let liveUi {
            bpmText = formatNumber(liveUi.bpm)
            beatText = liveUi.beatNumber.map(String.init) ?? "-"
            barValue = liveUi.barNumber.map(String.init) ?? "-"
            timeValue = liveUi.positionMilliseconds.map { formatTime(Double($0) / 1000.0) } ?? "-"
        } else {
            barValue = "-"
        }
        bpmValue = bpmText
        beatValue = beatText
        if liveUi == nil {
            timeValue = formatTime(state.osc.timeDisplaySeconds ?? state.osc.timeSeconds)
        }
        moodValue = formatMood(state.osc.mood)
        previewClockAnchorDate = Date()
        previewClockSourceSeconds = state.osc.timeDisplaySeconds ?? state.osc.timeSeconds
        previewClockBeatValue = state.osc.beatDisplay ?? state.osc.beat
        previewClockBpm = state.osc.bpm
        let hasBandData: (WaveformBandsState?) -> Bool = { bands in
            bands?.low != nil || bands?.mid != nil || bands?.high != nil
        }
        let hasDrumData: (DrumSignalsState?) -> Bool = { drums in
            drums?.kick != nil
                || drums?.snare != nil
                || drums?.hihat != nil
                || drums?.lowOnset != nil
                || drums?.midOnset != nil
                || drums?.highOnset != nil
        }
        let waveformEnergy = state.osc.waveformEnergy ?? state.dmx.autoShow.waveformEnergy
        let waveformBands = hasBandData(state.osc.audioBands)
            ? state.osc.audioBands
            : (state.osc.waveformBands ?? state.dmx.autoShow.waveformBands)
        let waveformLookahead = state.osc.waveformLookahead ?? state.dmx.autoShow.waveformLookahead
        let waveformAnalysis = state.osc.waveformAnalysis ?? state.dmx.autoShow.waveformAnalysis
        let drumSignals = hasDrumData(state.osc.audioDrums)
            ? state.osc.audioDrums
            : (state.osc.drumSignals ?? state.dmx.autoShow.drumSignals)
        updateWaveformHistory(with: waveformEnergy, stale: state.osc.stale)
        waveformEnergyValue = formatPercent(waveformEnergy)
        waveformStatusText = waveformHeadline(from: waveformAnalysis, energy: waveformEnergy)
        waveformInfluenceText = waveformInfluenceSummary(
            analysis: waveformAnalysis,
            autoShow: state.dmx.autoShow
        )
        waveformBandLow = waveformBands?.low
        waveformBandMid = waveformBands?.mid
        waveformBandHigh = waveformBands?.high
        waveformLookahead2Low = waveformLookahead?["2"]?.low
        waveformLookahead2Mid = waveformLookahead?["2"]?.mid
        waveformLookahead2High = waveformLookahead?["2"]?.high
        waveformLookahead4Low = waveformLookahead?["4"]?.low
        waveformLookahead4Mid = waveformLookahead?["4"]?.mid
        waveformLookahead4High = waveformLookahead?["4"]?.high
        waveformAnticipation = state.dmx.autoShow.anticipation
        drumKick = drumSignals?.kick
        drumSnare = drumSignals?.snare
        drumHihat = drumSignals?.hihat
        playbackSummary = "BPM \(bpmText)   Beat \(beatText)   Time \(formatTime(state.osc.timeDisplaySeconds ?? state.osc.timeSeconds))"

        let phraseCurrent = normalizedDisplay(liveUi == nil ? state.osc.phraseCurrent : liveUi?.phrase, fallback: "-")
        let phraseNext = normalizedDisplay(liveUi == nil ? state.osc.phraseNext : liveUi?.nextPhrase, fallback: "-")
        let countIn = state.osc.phraseCountIn.map(String.init) ?? "-"
        let etaBeats = state.osc.phraseCountdownBeats.map { String(format: "%.2f beats", $0) } ?? "-"
        let etaSeconds = state.osc.phraseCountdownSeconds.map { formatTime($0) } ?? "-"
        phraseCurrentValue = phraseCurrent
        if let bars = liveUi?.barsToNext, phraseNext != "-" {
            phraseNextValue = "\(phraseNext) • \(bars) bars"
        } else {
            phraseNextValue = phraseNext
        }
        phraseCountValue = countIn
        phraseEtaValue = etaSeconds == "-" ? etaBeats : "\(etaBeats) / \(etaSeconds)"
        phraseSummary = "Phrase \(phraseCurrent) -> \(phraseNextValue)   Count-in \(countIn)   ETA \(etaBeats) / \(etaSeconds)"

        if state.dmx.connected, let device = state.dmx.port {
            if let port = ports.first(where: { $0.device == device }) {
                selectedPortLabel = port.label
            }
        }
        syncEditors(from: state, forceSelectionToActiveSlot: forceSelectionToActiveSlot)
        syncAuthoritativeVenueLayouts()

        let sortedChannels = state.dmx.values.keys.compactMap(Int.init).sorted()
        if let first = sortedChannels.first, let last = sortedChannels.last {
            universeSummary = "\(sortedChannels.count) actieve waarden in use, bereik \(first)-\(last)"
        } else {
            universeSummary = "Geen actieve kanalen"
        }

        if state.dmx.conflicts.isEmpty {
            conflictSummary = "Geen kanaalconflicten"
        } else {
            conflictSummary = state.dmx.conflicts
                .map { "ch \($0.channel) (\($0.first) vs \($0.second))" }
                .joined(separator: ", ")
        }

        if state.dmx.values.isEmpty {
            rawValuesText = "Geen actieve DMX-waarden."
        } else {
            rawValuesText = sortedChannels.map { channel in
                "\(channel): \(state.dmx.values[String(channel)] ?? 0)"
            }.joined(separator: "\n")
        }
        let motionLines = state.dmx.renderedMotion.values
            .filter { $0.supported }
            .sorted { $0.slotId < $1.slotId }
            .map { motion in
                let preview = state.dmx.slotPreviews[motion.slotId]
                let previewMotion = "intent p/t \(preview?.pan ?? -1)/\(preview?.tilt ?? -1)"
                let finalMotion = "final p/f/t/f \(motion.pan ?? -1)/\(motion.panFine ?? -1)/\(motion.tilt ?? -1)/\(motion.tiltFine ?? -1)"
                let direction = motion.worldDirection.map {
                    String(format: "dir %.3f, %.3f, %.3f", $0.x, $0.y, $0.z)
                } ?? "dir unavailable"
                return "\(motion.slotId) • \(motion.status) • \(previewMotion) • \(finalMotion) • \(direction)"
            }
        renderedMotionSummary = motionLines.isEmpty
            ? "Geen final-motionprojectie beschikbaar."
            : motionLines.joined(separator: "\n")
        advanceStageSimulation(forceSnapIfNeeded: false)
    }

    private func applyVirtualDjBeatPulsePreview(_ state: VirtualDjBeatPulsePreviewState) {
        virtualDjBeatPulsePreviewEnabled = state.enabled
        if state.enabled {
            virtualDjBeatPulsePreviewStatus = state.pending
                ? "Virtuele VirtualDJ-puls wacht op de volgende maat"
                : "Virtuele VirtualDJ-puls actief"
        } else {
            virtualDjBeatPulsePreviewStatus = "Visuele VirtualDJ-test uit"
        }
    }

    private func syncEditors(from state: AppState, forceSelectionToActiveSlot: Bool) {
        let orderedSlotIDs = state.dmx.slotOrder.filter { state.dmx.slots[$0] != nil }
        var nextEditors: [SlotEditor] = []
        var liveIDs = Set<String>()

        for slotID in orderedSlotIDs {
            guard let slot = state.dmx.slots[slotID] else { continue }
            let range = state.dmx.slotRanges[slotID]
            let capabilities = state.dmx.slotCapabilities[slotID] ?? SlotCapabilities(
                dimmer: true,
                strobe: true,
                program: true,
                speed: true,
                pan: false,
                panFine: false,
                tilt: false,
                tiltFine: false,
                panTiltSpeed: false,
                white: true
            )
            let fixture = availableFixtures.first(where: { $0.id == slot.fixture })
            let fixtureLabel = fixture?.displayName ?? range?.fixtureLabel ?? slot.fixture
            let modeOptions = uniqueModes(from: fixture, including: slot.mode)

            let editor: SlotEditor
            if let existing = editorsByID[slotID] {
                editor = existing
                editor.syncMetadata(
                    label: slot.label,
                    fixtureID: slot.fixture,
                    fixtureLabel: fixtureLabel,
                    modeOptions: modeOptions
                )
            } else {
                editor = SlotEditor(
                    id: slotID,
                    label: slot.label,
                    fixtureID: slot.fixture,
                    fixtureLabel: fixtureLabel,
                    modeOptions: modeOptions,
                    mode: slot.mode
                )
                editorsByID[slotID] = editor
            }

            editor.apply(slot, range: range, capabilities: capabilities, fixture: fixture)
            nextEditors.append(editor)
            liveIDs.insert(slotID)
        }

        editorsByID = Dictionary(uniqueKeysWithValues: editorsByID.filter { liveIDs.contains($0.key) })
        slotEditors = nextEditors
        reconcileMapAssignments(with: nextEditors)

        let validSelection = Set(orderedSlotIDs)
        if forceSelectionToActiveSlot || !validSelection.contains(selectedSlotID) {
            selectedSlotID = validSelection.contains(state.dmx.activeSlot)
                ? state.dmx.activeSlot
                : (orderedSlotIDs.first ?? "")
        }
        previewSelectedSlotIDs = previewSelectedSlotIDs.intersection(validSelection)
    }

    private func uniqueModes(from fixture: FixtureProfile?, including currentMode: String) -> [String] {
        var modes = fixture?.modes.map(\.name) ?? []
        if !modes.contains(currentMode) {
            modes.append(currentMode)
        }
        return modes
    }

    private func startStageSimulation() {
        stageSimulationTimer?.invalidate()
        let timer = Timer(timeInterval: 1.0 / 30.0, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.advanceStageSimulation(forceSnapIfNeeded: false)
            }
        }
        stageSimulationTimer = timer
        RunLoop.main.add(timer, forMode: .common)
        advanceStageSimulation(forceSnapIfNeeded: true)
    }

    private func advanceStageSimulation(forceSnapIfNeeded: Bool) {
        let now = Date().timeIntervalSinceReferenceDate
        var nextStates = stageMotionStates
        let liveIDs = Set(slotEditors.map(\.id))
        nextStates = nextStates.filter { liveIDs.contains($0.key) }

        for editor in slotEditors {
            guard editor.supportsPan || editor.supportsTilt else {
                nextStates.removeValue(forKey: editor.id)
                continue
            }
            guard let preview = slotPreviews[editor.id], preview.enabled else {
                nextStates.removeValue(forKey: editor.id)
                continue
            }

            let fixture = availableFixtures.first(where: { $0.id == editor.fixtureID })
            let panRange = max(180.0, preview.panRange ?? fixture?.panRange ?? 540.0)
            let tiltRange = max(90.0, preview.tiltRange ?? fixture?.tiltRange ?? 180.0)
            let targetPanDegrees = preview.logicalTargetPanDegrees
                ?? preview.targetPanDegrees
                ?? panDegrees(forDMX: preview.targetPan ?? preview.pan, range: panRange)
            let targetTiltDegrees = preview.logicalTargetTiltDegrees
                ?? preview.targetTiltDegrees
                ?? tiltDegrees(forDMX: preview.targetTilt ?? preview.tilt, range: tiltRange)
            let previous = nextStates[editor.id]
            let currentPanDegrees = preview.logicalPanDegrees
                ?? preview.panDegrees
                ?? panDegrees(forDMX: preview.pan, range: panRange)
            let currentTiltDegrees = preview.logicalTiltDegrees
                ?? preview.tiltDegrees
                ?? tiltDegrees(forDMX: preview.tilt, range: tiltRange)
            let previousPan = previous?.currentPanDegrees ?? currentPanDegrees
            let previousTilt = previous?.currentTiltDegrees ?? currentTiltDegrees
            let dt = max(1.0 / 60.0, min(0.20, now - (previous?.updatedAt ?? (now - 1.0 / 30.0))))
            let estimatedSpeed: Double
            if let panSpeed = preview.panSpeedDps, let tiltSpeed = preview.tiltSpeedDps {
                estimatedSpeed = min(900.0, sqrt(panSpeed * panSpeed + tiltSpeed * tiltSpeed))
            } else {
                let deltaPan = currentPanDegrees - previousPan
                let deltaTilt = currentTiltDegrees - previousTilt
                estimatedSpeed = min(
                    900.0,
                    sqrt(deltaPan * deltaPan + deltaTilt * deltaTilt) / max(dt, 1.0 / 120.0)
                )
            }

            var trail = previous?.trail ?? []
            let currentPose = StageBeamPose(
                panDegrees: currentPanDegrees,
                tiltDegrees: currentTiltDegrees
            )
            if forceSnapIfNeeded {
                trail = [currentPose]
            } else if trail.isEmpty || abs((trail.last?.panDegrees ?? 0) - currentPanDegrees) > 0.5 || abs((trail.last?.tiltDegrees ?? 0) - currentTiltDegrees) > 0.5 {
                trail.append(currentPose)
            } else {
                trail[trail.count - 1] = currentPose
            }
            if trail.count > 6 {
                trail.removeFirst(trail.count - 6)
            }
            if !preview.motionActive, abs(targetPanDegrees - currentPanDegrees) < 0.8, abs(targetTiltDegrees - currentTiltDegrees) < 0.8 {
                trail = [currentPose]
            }

            nextStates[editor.id] = StageMotionState(
                currentPanDegrees: currentPanDegrees,
                currentTiltDegrees: currentTiltDegrees,
                targetPanDegrees: targetPanDegrees,
                targetTiltDegrees: targetTiltDegrees,
                panRange: panRange,
                tiltRange: tiltRange,
                estimatedSpeedDegreesPerSecond: estimatedSpeed,
                trail: trail,
                updatedAt: now,
                worldDirection: nil
            )
        }

        stageMotionStates = nextStates
    }

    private func loadMapAssignments() {
        guard
            let data = UserDefaults.standard.data(forKey: mapAssignmentsDefaultsKey),
            let stored = try? JSONDecoder().decode([String: String].self, from: data)
        else {
            mapAssignments = [:]
            return
        }
        mapAssignments = stored
    }

    private func saveMapAssignments() {
        guard let data = try? JSONEncoder().encode(mapAssignments) else { return }
        UserDefaults.standard.set(data, forKey: mapAssignmentsDefaultsKey)
    }

    private func loadProjectionLayouts() {
        if
            let data = UserDefaults.standard.data(forKey: projectionLayoutsDefaultsKey),
            let stored = try? JSONDecoder().decode([String: SlotWorldPosition].self, from: data),
            !stored.isEmpty
        {
            projectionLayouts = stored
            projectionLayoutDrafts = stored
            return
        }

        if let migrated = loadLegacyProjectionLayouts(), !migrated.isEmpty {
            projectionLayouts = migrated
            projectionLayoutDrafts = migrated
            saveProjectionLayouts()
            return
        }

        projectionLayouts = [:]
        projectionLayoutDrafts = [:]
    }

    private func saveProjectionLayouts() {
        guard let data = try? JSONEncoder().encode(projectionLayouts) else { return }
        UserDefaults.standard.set(data, forKey: projectionLayoutsDefaultsKey)
    }

    private func loadFrontProjectionMirrored() {
        frontProjectionMirrored = UserDefaults.standard.bool(forKey: frontProjectionMirrorDefaultsKey)
    }

    private func saveFrontProjectionMirrored() {
        UserDefaults.standard.set(frontProjectionMirrored, forKey: frontProjectionMirrorDefaultsKey)
    }

    func toggleFrontProjectionMirrored() {
        frontProjectionMirrored.toggle()
    }

    private func loadTopProjectionRotation() {
        topProjectionRotationQuarterTurns = normalizedQuarterTurns(
            UserDefaults.standard.integer(forKey: topProjectionRotationDefaultsKey)
        )
    }

    private func saveTopProjectionRotation() {
        UserDefaults.standard.set(
            normalizedQuarterTurns(topProjectionRotationQuarterTurns),
            forKey: topProjectionRotationDefaultsKey
        )
    }

    func rotateTopProjection(by quarterTurns: Int) {
        topProjectionRotationQuarterTurns = normalizedQuarterTurns(
            topProjectionRotationQuarterTurns + quarterTurns
        )
    }

    var topProjectionRotationDegrees: Int {
        normalizedQuarterTurns(topProjectionRotationQuarterTurns) * 90
    }

    private func loadLegacyProjectionLayouts() -> [String: SlotWorldPosition]? {
        guard
            let data = UserDefaults.standard.data(forKey: legacyProjectionLayoutsDefaultsKey),
            let stored = try? JSONDecoder().decode([String: [String: LegacyProjectionPoint]].self, from: data)
        else {
            return nil
        }

        var migrated: [String: SlotWorldPosition] = [:]
        for (slotID, views) in stored {
            let base = fallbackWorldPosition(for: slotID)
            var world = base

            if let top = views[StageProjection.top.rawValue] {
                world.x = scalarDenormalized(top.x, lower: StageWorld.minX, upper: StageWorld.maxX)
                world.y = scalarDenormalized(top.y, lower: StageWorld.minY, upper: StageWorld.maxY)
            }
            if let front = views[StageProjection.front.rawValue] {
                world.x = scalarDenormalized(front.x, lower: StageWorld.minX, upper: StageWorld.maxX)
                world.z = scalarDenormalized(1.0 - front.y, lower: StageWorld.minZ, upper: StageWorld.maxZ)
            }
            if let side = views[StageProjection.side.rawValue] {
                world.y = scalarDenormalized(side.x, lower: StageWorld.minY, upper: StageWorld.maxY)
                world.z = scalarDenormalized(1.0 - side.y, lower: StageWorld.minZ, upper: StageWorld.maxZ)
            }

            migrated[slotID] = world
        }
        return migrated
    }

    private func loadSelectedPortLabel() {
        selectedPortLabel = UserDefaults.standard.string(forKey: selectedPortDefaultsKey) ?? ""
    }

    private func saveSelectedPortLabel() {
        UserDefaults.standard.set(selectedPortLabel, forKey: selectedPortDefaultsKey)
    }

    private func loadSelectedLiveAudioDeviceID() {
        let stored = UserDefaults.standard.integer(forKey: liveAudioDeviceDefaultsKey)
        selectedLiveAudioDeviceID = stored > 0 ? UInt32(stored) : 0
    }

    private func saveSelectedLiveAudioDeviceID() {
        UserDefaults.standard.set(Int(selectedLiveAudioDeviceID), forKey: liveAudioDeviceDefaultsKey)
    }

    private func loadLiveAudioEnabled() {
        liveAudioEnabled = UserDefaults.standard.bool(forKey: liveAudioEnabledDefaultsKey)
    }

    private func saveLiveAudioEnabled() {
        UserDefaults.standard.set(liveAudioEnabled, forKey: liveAudioEnabledDefaultsKey)
    }

    private func loadBridgeScriptPath() {
        let stored = UserDefaults.standard.string(forKey: bridgeScriptDefaultsKey)?.trimmingCharacters(in: .whitespacesAndNewlines)
        bridgeScriptPath = (stored?.isEmpty == false) ? stored! : defaultRekordboxBridgeScriptPath()
    }

    private func saveBridgeScriptPath() {
        UserDefaults.standard.set(bridgeScriptPath, forKey: bridgeScriptDefaultsKey)
    }

    private func reconcileMapAssignments(with editors: [SlotEditor]) {
        let liveIDs = Set(editors.map(\.id))
        mapAssignments = mapAssignments.filter { liveIDs.contains($0.key) }
        projectionLayouts = projectionLayouts.filter { liveIDs.contains($0.key) }
        projectionLayoutDrafts = projectionLayoutDrafts.filter { liveIDs.contains($0.key) }

        var usedAnchors = Set(mapAssignments.values)
        for editor in editors {
            if mapAssignments[editor.id] == nil, projectionLayouts[editor.id] == nil {
                let centered = defaultNewFixtureWorldPosition()
                projectionLayouts[editor.id] = centered
                projectionLayoutDrafts[editor.id] = centered
            }
        }
        for editor in editors where mapAssignments[editor.id] == nil {
            if let suggested = nextSuggestedAnchor(for: editor, excluding: usedAnchors) {
                mapAssignments[editor.id] = suggested.rawValue
                usedAnchors.insert(suggested.rawValue)
            }
        }
        saveMapAssignments()
        saveProjectionLayouts()
    }

    private func effectiveWorldPosition(for slotID: String) -> SlotWorldPosition {
        if isEditingProjectionLayout, let draft = projectionLayoutDrafts[slotID] {
            return draft
        }
        if let stored = projectionLayouts[slotID] {
            return stored
        }
        return fallbackWorldPosition(for: slotID)
    }

    private func syncAuthoritativeVenueLayouts() {
        guard !isEditingProjectionLayout else { return }
        var changed = false
        for (slotID, calibration) in fixtureCalibrations {
            guard calibration.positionM != nil || calibration.position != nil else { continue }
            var world = projectionLayouts[slotID] ?? fallbackWorldPosition(for: slotID)
            if let positionM = calibration.positionM {
                world.x = positionM.x * 100
                world.y = positionM.y * 100
                world.z = positionM.z * 100
            }
            if let forward = calibration.physicalForward, let up = calibration.physicalUp {
                let normalizedForward = venueVectorNormalized(venueVectorTuple(forward))
                world.yawDegrees = atan2(normalizedForward.x, normalizedForward.y) * 180.0 / .pi
                world.pitchDegrees = asin(min(1, max(-1, normalizedForward.z))) * 180.0 / .pi
                var zeroRollWorld = world
                zeroRollWorld.rollDegrees = 0
                let zeroRollUp = venueVectorTuple(venueOrientationBasis(for: zeroRollWorld).up)
                let normalizedUp = venueVectorNormalized(venueVectorTuple(up))
                let sine = venueVectorDot(
                    normalizedForward,
                    venueVectorCross(zeroRollUp, normalizedUp)
                )
                let cosine = min(1, max(-1, venueVectorDot(zeroRollUp, normalizedUp)))
                world.rollDegrees = atan2(sine, cosine) * 180.0 / .pi
            }
            projectionLayouts[slotID] = world
            projectionLayoutDrafts[slotID] = world
            changed = true
        }
        if changed {
            // Compatibility cache only. The decoded backend calibration above
            // remains authoritative and can reconstruct this local projection.
            saveProjectionLayouts()
        }
    }

    private func fallbackWorldPosition(for slotID: String) -> SlotWorldPosition {
        if
            let raw = mapAssignments[slotID],
            let anchor = StageAnchor(rawValue: raw)
        {
            return anchor.defaultWorldPosition
        }
        return SlotWorldPosition(x: 0, y: 150, z: 200)
    }

    private func defaultNewFixtureWorldPosition() -> SlotWorldPosition {
        SlotWorldPosition(
            x: (StageWorld.minX + StageWorld.maxX) * 0.5,
            y: (StageWorld.minY + StageWorld.maxY) * 0.5,
            z: (StageWorld.minZ + StageWorld.maxZ) * 0.5
        )
    }

    private func project(world: SlotWorldPosition, projection: StageProjection) -> CGPoint {
        metricWorldProjectedPoint(
            world,
            projection: projection,
            frontMirrored: frontProjectionMirrored,
            topQuarterTurns: topProjectionRotationQuarterTurns
        )
    }

    private func update(world: inout SlotWorldPosition, from point: CGPoint, projection: StageProjection) {
        let projected = metricWorldPosition(
            from: point,
            projection: projection,
            frontMirrored: frontProjectionMirrored,
            topQuarterTurns: topProjectionRotationQuarterTurns
        )
        switch projection {
        case .top:
            world.x = projected.x; world.y = projected.y
        case .front, .back:
            world.x = projected.x; world.z = projected.z
        case .side:
            world.y = projected.y; world.z = projected.z
        }
        world.x = min(max(world.x, StageWorld.minX), StageWorld.maxX)
        world.y = min(max(world.y, StageWorld.minY), StageWorld.maxY)
        world.z = min(max(world.z, StageWorld.minZ), StageWorld.maxZ)
    }

    private func scalarNormalized(_ value: Double, lower: Double, upper: Double) -> Double {
        guard upper > lower else { return 0.5 }
        return Swift.min(Swift.max((value - lower) / (upper - lower), 0.0), 1.0)
    }

    private func scalarDenormalized(_ value: Double, lower: Double, upper: Double) -> Double {
        lower + Swift.min(Swift.max(value, 0.0), 1.0) * (upper - lower)
    }

    private func snappedYawDegrees(_ value: Double) -> Double {
        let normalized = value.truncatingRemainder(dividingBy: 360)
        let wrapped = normalized < 0 ? normalized + 360 : normalized
        return (wrapped / 90.0).rounded() * 90.0
    }

    private func snappedPitchDegrees(_ value: Double) -> Double {
        let normalized = value.truncatingRemainder(dividingBy: 360)
        let wrapped = normalized < 0 ? normalized + 360 : normalized
        return (wrapped / 90.0).rounded() * 90.0
    }

    private func snappedRollDegrees(_ value: Double) -> Double {
        let normalized = value.truncatingRemainder(dividingBy: 360)
        let wrapped = normalized < 0 ? normalized + 360 : normalized
        return (wrapped / 90.0).rounded() * 90.0
    }

    private func nextSuggestedAnchor(for editor: SlotEditor, excluding usedAnchors: Set<String>) -> StageAnchor? {
        for anchor in candidateAnchors(for: editor) where !usedAnchors.contains(anchor.rawValue) {
            return anchor
        }
        return StageAnchor.allCases.first(where: { !usedAnchors.contains($0.rawValue) })
    }

    private func candidateAnchors(for editor: SlotEditor) -> [StageAnchor] {
        if editor.supportsPan || editor.supportsTilt {
            return [.mh1, .mh2, .mh3, .mh4]
        }
        let lower = "\(editor.label) \(editor.fixtureLabel)".lowercased()
        if lower.contains("bar") {
            return [.b1, .b2]
        }
        return [.p1, .p2, .p3, .p4, .b1, .b2]
    }

    private func selectedPortDevice() -> String? {
        ports.first(where: { $0.label == selectedPortLabel })?.device
    }

    private func backendReachable() async throws -> Bool {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/state"))
        request.timeoutInterval = 0.6
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                return false
            }
            return (200..<300).contains(http.statusCode)
        } catch {
            return false
        }
    }

    private func backendSchemaCompatible() async throws -> Bool {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/state"))
        request.timeoutInterval = 0.8
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            return false
        }
        guard
            let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
            let app = root["app"] as? [String: Any],
            let dmx = root["dmx"] as? [String: Any],
            let autoShow = dmx["auto_show"] as? [String: Any]
        else {
            return false
        }
        let schemaVersion = app["api_schema_version"] as? Int ?? 0
        return schemaVersion >= requiredBackendSchemaVersion
            && autoShow["audience_pan_focus_enabled"] != nil
            && autoShow["audience_pan_min"] != nil
            && autoShow["audience_pan_max"] != nil
            && !(autoShow["audience_turn_pan_min"] is NSNull)
            && autoShow["audience_turn_pan_min"] != nil
            && !(autoShow["audience_turn_pan_max"] is NSNull)
            && autoShow["audience_turn_pan_max"] != nil
            && !(autoShow["audience_tilt_split"] is NSNull)
            && autoShow["audience_tilt_split"] != nil
    }

    private func runTool(_ launchPath: String, arguments: [String]) throws -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: launchPath)
        process.arguments = arguments
        let output = Pipe()
        let errors = Pipe()
        process.standardOutput = output
        process.standardError = errors
        try process.run()
        process.waitUntilExit()
        let stdout = String(data: output.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        if process.terminationStatus == 0 {
            return stdout
        }
        let stderr = String(data: errors.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        throw NSError(
            domain: "BeatBeamDMX",
            code: Int(process.terminationStatus),
            userInfo: [NSLocalizedDescriptionKey: stderr.isEmpty ? stdout : stderr]
        )
    }

    private func listeningBackendPID(on port: Int) throws -> Int? {
        let output = try runTool("/usr/sbin/lsof", arguments: [
            "-nP",
            "-iTCP:\(port)",
            "-sTCP:LISTEN",
            "-t",
        ])
        let line = output
            .split(whereSeparator: \.isNewline)
            .map(String.init)
            .first(where: { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty })
        guard let line, let pid = Int(line.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            return nil
        }
        return pid
    }

    private func commandLine(for pid: Int) throws -> String {
        try runTool("/bin/ps", arguments: ["-p", String(pid), "-o", "command="])
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func isManagedBackendCommand(_ command: String) -> Bool {
        guard command.contains("beatbeam_app.py") else { return false }
        let root = backendRootURL().path
        return command.contains(root) || command.contains(beatBeamAppBundleFileName)
    }

    private func adoptReachableBackendIfNeeded() throws {
        guard let pid = try listeningBackendPID(on: beatBeamBackendPort) else {
            backendProcess = nil
            ownedBackendPID = nil
            ownsBackend = false
            return
        }
        let command = (try? commandLine(for: pid)) ?? ""
        guard isManagedBackendCommand(command) else {
            backendProcess = nil
            ownedBackendPID = nil
            ownsBackend = false
            nativeLog("reachable backend on \(beatBeamBackendPort) is not managed by this app: \(command)")
            return
        }
        backendProcess = nil
        ownedBackendPID = pid
        ownsBackend = true
        nativeLog("adopted reachable backend pid \(pid): \(command)")
    }

    private func processIsAlive(_ pid: Int) -> Bool {
        guard pid > 0 else { return false }
        return kill(pid_t(pid), 0) == 0 || errno == EPERM
    }

    private func terminateOwnedBackendIfNeeded() {
        guard ownsBackend else { return }

        let pid = ownedBackendPID ?? {
            let processID = backendProcess?.processIdentifier ?? 0
            return processID > 0 ? Int(processID) : nil
        }()

        if let process = backendProcess, process.isRunning {
            nativeLog("terminating owned backend process pid \(process.processIdentifier)")
            process.terminate()
            let deadline = Date().addingTimeInterval(1.0)
            while process.isRunning && Date() < deadline {
                Thread.sleep(forTimeInterval: 0.05)
            }
        }

        if let pid, processIsAlive(pid) {
            nativeLog("sending SIGTERM to owned backend pid \(pid)")
            _ = kill(pid_t(pid), SIGTERM)
            let deadline = Date().addingTimeInterval(1.2)
            while processIsAlive(pid) && Date() < deadline {
                Thread.sleep(forTimeInterval: 0.05)
            }
            if processIsAlive(pid) {
                nativeLog("owned backend pid \(pid) survived SIGTERM, sending SIGKILL")
                _ = kill(pid_t(pid), SIGKILL)
            }
        }

        backendProcess = nil
        ownedBackendPID = nil
        ownsBackend = false
    }

    private func terminateIncompatibleBackendIfNeeded() async throws {
        guard let pid = try listeningBackendPID(on: beatBeamBackendPort) else { return }
        let command = (try? commandLine(for: pid)) ?? ""
        guard command.contains("beatbeam_app.py") else {
            throw NSError(domain: "BeatBeamDMX", code: 4, userInfo: [
                NSLocalizedDescriptionKey: "Poort \(beatBeamBackendPort) wordt gebruikt door een ander proces: \(command.isEmpty ? "onbekend" : command)"
            ])
        }
        nativeLog("terminating incompatible backend pid \(pid): \(command)")
        _ = kill(pid_t(pid), SIGTERM)
        for _ in 0..<20 {
            if try await !backendReachable() {
                return
            }
            try await Task.sleep(nanoseconds: 150_000_000)
        }
        nativeLog("backend pid \(pid) did not stop after SIGTERM, sending SIGKILL")
        _ = kill(pid_t(pid), SIGKILL)
        for _ in 0..<10 {
            if try await !backendReachable() {
                return
            }
            try await Task.sleep(nanoseconds: 100_000_000)
        }
        throw NSError(domain: "BeatBeamDMX", code: 5, userInfo: [
            NSLocalizedDescriptionKey: "Oude backend op poort \(beatBeamBackendPort) kon niet worden gestopt"
        ])
    }

    private func startBackend() throws {
        let root = backendRootURL()
        let bundledPythonRuntimeURL = root.appendingPathComponent("python-runtime", isDirectory: true)
        let bundledPythonURL = bundledPythonRuntimeURL.appendingPathComponent("bin/python3")
        let legacyPythonURL = root.appendingPathComponent(".venv/bin/python")
        let pythonURL: URL
        let bundledRuntimeAvailable = FileManager.default.isExecutableFile(atPath: bundledPythonURL.path)
        if bundledRuntimeAvailable {
            pythonURL = bundledPythonURL
        } else {
            pythonURL = legacyPythonURL
        }
        let scriptURL = root.appendingPathComponent("beatbeam_app.py")
        let appSupportURL = backendSupportDirectoryURL()
        let configURL = appSupportURL.appendingPathComponent("beatbeam_config.json")
        let transportConfigURL = appSupportURL.appendingPathComponent("beatbeam_transport.json")
        let remoteAccessURL = appSupportURL.appendingPathComponent("beatbeam_remote.json")
        let triggerLogURL = appSupportURL.appendingPathComponent("beatbeam-trigger.log")
        let previewCacheURL = appSupportURL.appendingPathComponent("track_preview_cache", isDirectory: true)
        try FileManager.default.createDirectory(at: appSupportURL, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: previewCacheURL, withIntermediateDirectories: true)
        try seedBackendConfigIfNeeded(backendRoot: root, supportDirectory: appSupportURL)
        nativeLog("backend root: \(root.path)")
        nativeLog("python path: \(pythonURL.path)")
        nativeLog("script path: \(scriptURL.path)")
        guard FileManager.default.isExecutableFile(atPath: pythonURL.path) else {
            throw NSError(domain: "BeatBeamDMX", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "Geen bruikbare Python runtime gevonden op \(pythonURL.path)"
            ])
        }
        guard FileManager.default.fileExists(atPath: scriptURL.path) else {
            throw NSError(domain: "BeatBeamDMX", code: 2, userInfo: [
                NSLocalizedDescriptionKey: "Backend script ontbreekt op \(scriptURL.path)"
            ])
        }

        let process = Process()
        process.executableURL = pythonURL
        process.arguments = [
            scriptURL.path,
            "--host", "0.0.0.0",
            "--port", String(beatBeamBackendPort),
            "--osc-port", String(defaultBackendOscPort),
        ]
        process.currentDirectoryURL = root
        var environment = ProcessInfo.processInfo.environment
        environment["BEATBEAM_APP_NAME"] = beatBeamAppDisplayName
        environment["BEATBEAM_APP_SLUG"] = beatBeamAppSlug
        environment["BEATBEAM_SERVER_VERSION"] = "\(beatBeamAppSlug)/\(beatBeamAppVersion)"
        environment["BEATBEAM_CONFIG_PATH"] = configURL.path
        environment["BEATBEAM_TRANSPORT_CONFIG_PATH"] = transportConfigURL.path
        environment["BEATBEAM_REMOTE_ACCESS_PATH"] = remoteAccessURL.path
        environment["BEATBEAM_TRIGGER_LOG_PATH"] = triggerLogURL.path
        environment["BEATBEAM_TRACK_PREVIEW_CACHE_DIR"] = previewCacheURL.path
        // The signed app bundle is read-only runtime input; bytecode belongs
        // nowhere in it and would invalidate its signature after launch.
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        if bundledRuntimeAvailable {
            environment["PYTHONHOME"] = bundledPythonRuntimeURL.path
            if let bundledSitePackages = bundledPythonSitePackagesURL(runtimeRoot: bundledPythonRuntimeURL) {
                environment["PYTHONPATH"] = bundledSitePackages.path
            }
            environment["PYTHONNOUSERSITE"] = "1"
        }
        process.environment = environment
        FileManager.default.createFile(atPath: backendLogURL.path, contents: nil)
        let handle = try FileHandle(forWritingTo: backendLogURL)
        process.standardOutput = handle
        process.standardError = handle
        try process.run()
        nativeLog("backend process started with pid \(process.processIdentifier)")
        backendProcess = process
        ownedBackendPID = Int(process.processIdentifier)
        ownsBackend = true
    }

    private func waitForBackend() async throws {
        for _ in 0..<20 {
            if try await backendReachable() {
                return
            }
            try await Task.sleep(nanoseconds: 250_000_000)
        }
        throw NSError(domain: "BeatBeamDMX", code: 3, userInfo: [
            NSLocalizedDescriptionKey: "Backend startte niet binnen de timeout"
        ])
    }

    private func bundledPythonSitePackagesURL(runtimeRoot: URL) -> URL? {
        let libURL = runtimeRoot.appendingPathComponent("lib", isDirectory: true)
        guard let versionDirectories = try? FileManager.default.contentsOfDirectory(
            at: libURL,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        ) else {
            return nil
        }

        let versionDirectory = versionDirectories.first {
            $0.lastPathComponent.hasPrefix("python3.")
        }
        return versionDirectory?.appendingPathComponent("site-packages", isDirectory: true)
    }

    private func backendRootURL() -> URL {
        if let resourceURL = Bundle.main.resourceURL {
            let bundledRoot = resourceURL.appendingPathComponent("backend", isDirectory: true)
            if FileManager.default.fileExists(atPath: bundledRoot.path) {
                nativeLog("backend root derived from bundle resources: \(bundledRoot.path)")
                return bundledRoot
            }
        }
        let root = repoRootURL()
        nativeLog("backend root derived from repo root fallback: \(root.path)")
        return root
    }

    private func backendSupportDirectoryURL() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support", isDirectory: true)
        let candidates = [
            base.appendingPathComponent(beatBeamSupportDirectoryName, isDirectory: true),
            URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent(".\(beatBeamDefaultsPrefix.lowercased())", isDirectory: true),
            FileManager.default.temporaryDirectory.appendingPathComponent(beatBeamTemporaryDirectoryName, isDirectory: true),
        ]
        for candidate in candidates {
            do {
                try FileManager.default.createDirectory(at: candidate, withIntermediateDirectories: true)
                let probe = candidate.appendingPathComponent(".write_probe")
                try Data("ok".utf8).write(to: probe, options: .atomic)
                try? FileManager.default.removeItem(at: probe)
                return candidate
            } catch {
                nativeLog("backend support dir rejected: \(candidate.path) (\(error.localizedDescription))")
            }
        }
        return candidates[0]
    }

    private func seedBackendConfigIfNeeded(backendRoot: URL, supportDirectory: URL) throws {
        let fileManager = FileManager.default
        let supportConfigURL = supportDirectory.appendingPathComponent("beatbeam_config.json")
        let candidateURLs = legacyConfigCandidateURLs(backendRoot: backendRoot)

        let supportSlotCount = slotCount(at: supportConfigURL)
        let bestLegacy = candidateURLs
            .map { ($0, slotCount(at: $0)) }
            .filter { $0.1 > 0 }
            .max { lhs, rhs in lhs.1 < rhs.1 }

        let shouldMigrate: Bool
        if !fileManager.fileExists(atPath: supportConfigURL.path) {
            shouldMigrate = true
        } else if let bestLegacy, supportSlotCount <= 2, bestLegacy.1 > supportSlotCount {
            shouldMigrate = true
        } else {
            shouldMigrate = false
        }

        guard shouldMigrate, let sourceURL = bestLegacy?.0 else { return }
        let backupURL = supportDirectory.appendingPathComponent("beatbeam_config.backup.json")
        if fileManager.fileExists(atPath: supportConfigURL.path) {
            withExtendedLifetime(backupURL) {
                try? fileManager.removeItem(at: backupURL)
                try? fileManager.copyItem(at: supportConfigURL, to: backupURL)
            }
        }
        try? fileManager.removeItem(at: supportConfigURL)
        try fileManager.copyItem(at: sourceURL, to: supportConfigURL)
        nativeLog("migrated config from \(sourceURL.path) to \(supportConfigURL.path)")
    }

    private func legacyConfigCandidateURLs(backendRoot: URL) -> [URL] {
        var candidates: [URL] = []
        let repoConfigURL = repoRootURL().appendingPathComponent("beatbeam_config.json")
        let applicationSupportBaseURL = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support", isDirectory: true)
        let stableSupportConfigURL = applicationSupportBaseURL
            .appendingPathComponent(beatBeamStableSupportDirectoryName, isDirectory: true)
            .appendingPathComponent("beatbeam_config.json")
        let oldSupportConfigURL = (
            applicationSupportBaseURL
        ).appendingPathComponent("BeatBeamDMX/beatbeam_config.json")
        let bundledConfigURL = backendRoot.appendingPathComponent("beatbeam_config.json")

        for url in [repoConfigURL, stableSupportConfigURL, oldSupportConfigURL, bundledConfigURL] {
            if !candidates.contains(url) {
                candidates.append(url)
            }
        }
        return candidates
    }

    private func slotCount(at url: URL) -> Int {
        guard let data = try? Data(contentsOf: url),
              let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let slots = payload["slots"] as? [String: Any] else {
            return 0
        }
        return slots.count
    }

    private func repoRootURL() -> URL {
        guard let executable = Bundle.main.executableURL else {
            return URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        }
        return executable
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }

    private func get<Response: Decodable>(_ path: String, as type: Response.Type) async throws -> Response {
        var request = URLRequest(url: baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))))
        request.httpMethod = "GET"
        request.timeoutInterval = 5.0
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        return try decodeBackendResponse(Response.self, from: data, requestPath: path)
    }

    private func post<Body: Encodable, Response: Decodable>(_ path: String, body: Body, as type: Response.Type) async throws -> Response {
        var request = URLRequest(url: baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))))
        request.httpMethod = "POST"
        request.timeoutInterval = 30.0
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try encoder().encode(body)
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        return try decodeBackendResponse(Response.self, from: data, requestPath: path)
    }

    private func decodeBackendResponse<Response: Decodable>(
        _ type: Response.Type,
        from data: Data,
        requestPath: String
    ) throws -> Response {
        do {
            return try decoder().decode(Response.self, from: data)
        } catch {
            nativeLog("backend response decode failure path=\(requestPath) \(describeDecodingError(error))")
            throw BackendResponseDecodeFailure(requestPath: requestPath, underlyingError: error)
        }
    }

    private func describeDecodingError(_ error: Error) -> String {
        switch error {
        case let DecodingError.keyNotFound(key, context):
            return "keyNotFound key=\(key.stringValue) codingPath=\(codingPathDescription(context.codingPath)) detail=\(context.debugDescription)"
        case let DecodingError.valueNotFound(type, context):
            return "valueNotFound type=\(type) codingPath=\(codingPathDescription(context.codingPath)) detail=\(context.debugDescription)"
        case let DecodingError.typeMismatch(type, context):
            return "typeMismatch type=\(type) codingPath=\(codingPathDescription(context.codingPath)) detail=\(context.debugDescription)"
        case let DecodingError.dataCorrupted(context):
            return "dataCorrupted codingPath=\(codingPathDescription(context.codingPath)) detail=\(context.debugDescription)"
        default:
            return "error=\(error.localizedDescription)"
        }
    }

    private func codingPathDescription(_ codingPath: [CodingKey]) -> String {
        let path = codingPath.map(\.stringValue).joined(separator: " -> ")
        return path.isEmpty ? "<root>" : path
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw NSError(domain: "BeatBeamDMX", code: 10, userInfo: [
                NSLocalizedDescriptionKey: "Ongeldige backend response"
            ])
        }
        guard (200..<300).contains(http.statusCode) else {
            let text = String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)"
            throw NSError(domain: "BeatBeamDMX", code: http.statusCode, userInfo: [
                NSLocalizedDescriptionKey: text
            ])
        }
    }

    private func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    private func encoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }

    private func normalizedDisplay(_ value: String?, fallback: String) -> String {
        guard let value else { return fallback }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? fallback : trimmed
    }

    private func deckState(_ state: AppState, logicalDeckNumber: Int) -> OscDeckState? {
        guard let decks = state.osc.decks?.legacy else { return nil }
        let zeroBased = decks.keys.contains("0")
        let key = zeroBased ? String(max(0, logicalDeckNumber - 1)) : String(logicalDeckNumber)
        return decks[key]
    }

    private func deckTitleFallback(from state: AppState) -> String? {
        [1, 2].compactMap { deckState(state, logicalDeckNumber: $0)?.trackTitle }.first(where: {
            !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        })
    }

    private func deckArtistFallback(from state: AppState) -> String? {
        [1, 2].compactMap { deckState(state, logicalDeckNumber: $0)?.trackArtist }.first(where: {
            !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        })
    }

    private func deckAlbumFallback(from state: AppState) -> String? {
        [1, 2].compactMap { deckState(state, logicalDeckNumber: $0)?.trackAlbum }.first(where: {
            !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        })
    }

    private func updateWaveformHistory(with energy: Double?, stale: Bool) {
        guard !stale else {
            if !waveformHistory.isEmpty {
                waveformHistory.removeAll(keepingCapacity: true)
            }
            return
        }
        guard let energy, energy.isFinite else { return }
        let clamped = min(1.0, max(0.0, energy))
        waveformHistory.append(clamped)
        if waveformHistory.count > 120 {
            waveformHistory.removeFirst(waveformHistory.count - 120)
        }
    }

    private func formatPercent(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "-" }
        return "\(Int((min(1.0, max(0.0, value)) * 100.0).rounded()))%"
    }

    private func waveformHeadline(from analysis: WaveformAnalysis?, energy: Double?) -> String {
        let level = formatPercent(energy)
        guard let analysis else {
            return "Wave \(level)"
        }
        let state: String
        if analysis.attack {
            state = "Attack"
        } else if analysis.sustainedHigh {
            state = "Sustain"
        } else if analysis.breakdown {
            state = "Breakdown"
        } else if analysis.calm {
            state = "Calm"
        } else {
            state = "Neutral"
        }
        return "\(state) • \(level)"
    }

    private func waveformInfluenceSummary(analysis: WaveformAnalysis?, autoShow: AutoShowState) -> String {
        guard let analysis else {
            return autoShow.available ? "Auto Show live, wacht op waveform-trend." : "Geen live waveform-input."
        }

        let hint: String
        switch Int((analysis.moodHint ?? 0).rounded()) {
        case 1: hint = "hint High"
        case 2: hint = "hint Mid"
        case 3: hint = "hint Low"
        default: hint = "hint hold"
        }

        let rhythm = titleizeMetric(autoShow.rhythmMode ?? (autoShow.beatPulse ? "pulse" : "none"))
        let beat = autoShow.beatPulse ? "beat on" : "beat off"
        let energy = "energy \(Int((autoShow.energy * 100).rounded()))%"
        return "\(hint) • \(rhythm) • \(beat) • \(energy)"
    }

    private func titleizeMetric(_ raw: String) -> String {
        raw
            .replacingOccurrences(of: "_", with: " ")
            .split(separator: " ")
            .map { $0.prefix(1).uppercased() + $0.dropFirst().lowercased() }
            .joined(separator: " ")
    }

    private func formatMood(_ value: Double?) -> String {
        guard let value else { return "-" }
        let rounded = Int(round(value))
        let label: String
        switch rounded {
        case ...1:
            label = "High"
        case 2:
            label = "Mid"
        default:
            label = "Low"
        }
        return "\(rounded) • \(label)"
    }

    private func formatNumber(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "-" }
        return String(format: "%.2f", value)
    }

    private func formatTime(_ seconds: Double?) -> String {
        guard let seconds, seconds.isFinite, seconds >= 0 else { return "-" }
        let total = Int(seconds)
        let mins = total / 60
        let secs = total % 60
        let hundredths = Int((seconds - floor(seconds)) * 100.0)
        return String(format: "%d:%02d.%02d", mins, secs, max(0, min(99, hundredths)))
    }
}

struct ContentView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.openWindow) private var openWindow
    @State private var workspaceMode: WorkspaceMode = .live
    @State private var utilityPanel: UtilityPanel? = nil

    private enum WorkspaceMode: String, CaseIterable, Identifiable {
        case live = "Live Show"
        case preview = "Stage Map"
        case autoShow = "Auto Show"
        case simulator = "Simulator"
        case manual = "Manual"
        case advanced = "Advanced"

        var id: String { rawValue }
    }

    private enum UtilityPanel: String, CaseIterable, Identifiable {
        case transport = "Transport"
        case remote = "Remote"
        case universe = "Universe"

        var id: String { rawValue }

        var title: String {
            switch self {
            case .transport: return "Transport"
            case .remote: return "iPad Remote"
            case .universe: return "Universe"
            }
        }

        var icon: String {
            switch self {
            case .transport: return "waveform.path.ecg"
            case .remote: return "ipad.and.iphone"
            case .universe: return "dial.high"
            }
        }

        var width: CGFloat {
            switch self {
            case .transport: return 420
            case .remote: return 360
            case .universe: return 340
            }
        }
    }

    var body: some View {
        GeometryReader { proxy in
            ZStack {
                BeatBeamPalette.appGradient
                    .ignoresSafeArea()

                VStack(alignment: .leading, spacing: 14) {
                    workspaceModeBar
                    if !model.errorText.isEmpty {
                        Text(model.errorText)
                            .foregroundStyle(.red)
                            .padding(.horizontal, 4)
                    }
                    HStack(alignment: .top, spacing: 16) {
                        fixtureWorkspace
                        if let utilityPanel {
                            utilityPanelView(utilityPanel)
                                .frame(width: utilityPanel.width)
                                .frame(maxHeight: .infinity, alignment: .top)
                                .transition(.move(edge: .trailing).combined(with: .opacity))
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                }
                .padding(18)
                .frame(width: proxy.size.width, height: proxy.size.height, alignment: .topLeading)
            }
        }
        .onAppear {
            model.start()
        }
        .animation(.easeInOut(duration: 0.18), value: utilityPanel)
    }

    private var selectedEditor: SlotEditor? {
        model.slotEditors.first(where: { $0.id == model.selectedSlotID }) ?? model.slotEditors.first
    }

    private var monitorFixtures: [UniverseFixtureGroup] {
        model.dmxSlotOrder.compactMap { slotID in
            guard let range = model.dmxSlotRanges[slotID] else { return nil }
            let channels = (range.address...range.lastChannel).map { channel in
                UniverseChannelValue(channel: channel, value: model.dmxValues[channel] ?? 0)
            }
            return UniverseFixtureGroup(
                slotID: slotID,
                range: range,
                preview: model.slotPreviews[slotID],
                channels: channels
            )
        }
    }

    private var workspaceModeBar: some View {
        HStack(spacing: 8) {
            BeatBeamBrandLockup(compact: true)
                .padding(.trailing, 8)

            ForEach(WorkspaceMode.allCases) { mode in
                Button {
                    workspaceMode = mode
                } label: {
                    Text(mode.rawValue)
                        .font(.system(size: 14, weight: .semibold))
                        .padding(.horizontal, 16)
                        .padding(.vertical, 9)
                        .background(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(workspaceMode == mode ? AnyShapeStyle(BeatBeamPalette.activeGradient) : AnyShapeStyle(BeatBeamPalette.raisedGradient))
                        )
                        .foregroundStyle(workspaceMode == mode ? Color.black : Color.white.opacity(0.92))
                        .overlay(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .stroke(workspaceMode == mode ? BeatBeamPalette.brandCyan.opacity(0.72) : BeatBeamPalette.border, lineWidth: 1)
                        )
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                }
                .buttonStyle(.plain)
            }

            Button {
                openWindow(id: "map-preview")
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "rectangle.on.rectangle")
                        .font(.system(size: 12, weight: .semibold))
                    Text("Open Preview")
                        .font(.system(size: 14, weight: .semibold))
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 9)
                .background(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(BeatBeamPalette.raisedGradient)
                )
                .foregroundStyle(Color.white.opacity(0.92))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(BeatBeamPalette.brandMagenta.opacity(0.34), lineWidth: 1)
                )
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .buttonStyle(.plain)

            Spacer(minLength: 12)

            if workspaceMode == .advanced {
                Button {
                    model.refreshDebugState()
                    workspaceMode = .advanced
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                        .font(.system(size: 14, weight: .semibold))
                        .padding(.horizontal, 14)
                        .padding(.vertical, 9)
                }
                .buttonStyle(.plain)
            }

            if workspaceMode == .advanced {
                ForEach(UtilityPanel.allCases) { panel in
                    Button {
                        utilityPanel = utilityPanel == panel ? nil : panel
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: panel.icon)
                                .font(.system(size: 12, weight: .semibold))
                            Text(panel.title)
                                .font(.system(size: 14, weight: .semibold))
                        }
                        .padding(.horizontal, 14)
                        .padding(.vertical, 9)
                        .background(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(utilityPanel == panel ? AnyShapeStyle(BeatBeamPalette.utilityGradient) : AnyShapeStyle(BeatBeamPalette.raisedGradient))
                        )
                        .foregroundStyle(utilityPanel == panel ? Color.white : Color.white.opacity(0.92))
                        .overlay(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .stroke(utilityPanel == panel ? BeatBeamPalette.brandMagenta.opacity(0.72) : BeatBeamPalette.border, lineWidth: 1)
                        )
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private var statusDeck: some View {
        HStack(alignment: .top, spacing: 16) {
            outputDeck
                .frame(width: 380)
            playbackSummaryDeck
        }
    }

    private var fixtureWorkspace: some View {
        Group {
            if workspaceMode == .live {
                ScrollView {
                    LiveShowWorkspaceView()
                        .padding(.trailing, 4)
                        .padding(.bottom, 32)
                }
            } else if workspaceMode == .preview {
                PreviewComposerWorkspaceView()
                    .padding(.trailing, 4)
                    .frame(maxHeight: .infinity, alignment: .topLeading)
            } else if workspaceMode == .autoShow {
                ScrollView {
                    AutoShowWorkspaceView()
                        .padding(.trailing, 4)
                        .padding(.bottom, 32)
                }
            } else if workspaceMode == .simulator {
                ScrollView {
                    SimulatorWorkspaceView()
                        .padding(.trailing, 4)
                        .padding(.bottom, 32)
                }
            } else if workspaceMode == .manual {
                ScrollView {
                    LivePresetWorkspaceView()
                        .padding(.trailing, 4)
                        .padding(.bottom, 32)
                }
            } else {
                AdvancedOperationsWorkspaceView(
                    fixtureBank: AnyView(fixtureBankPanel),
                    selectedEditor: selectedEditor
                )
                .padding(.trailing, 4)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var fixtureBankPanel: some View {
        PanelSurface(title: "Fixture Bank", compact: true) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(model.slotEditors) { editor in
                        Button {
                            model.selectSlot(editor.id)
                        } label: {
                            HStack(spacing: 8) {
                                Image(systemName: model.selectedSlotID == editor.id ? "smallcircle.filled.circle" : "circle")
                                    .font(.caption)
                                Text(editor.label)
                                    .lineLimit(1)
                            }
                            .padding(.horizontal, 14)
                            .padding(.vertical, 8)
                            .background(model.selectedSlotID == editor.id ? BeatBeamPalette.triggerActive : BeatBeamPalette.mutedBackground)
                            .foregroundStyle(model.selectedSlotID == editor.id ? Color.white : Color.primary)
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                        }
                        .buttonStyle(.plain)
                    }

                    Menu {
                        ForEach(model.availableFixtures) { fixture in
                            Button(fixture.displayName) {
                                model.addSlot(fixtureID: fixture.id)
                            }
                        }
                    } label: {
                        Image(systemName: "plus")
                            .frame(width: 30, height: 30)
                            .background(BeatBeamPalette.mutedBackground)
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    }
                    .menuStyle(.borderlessButton)
                    .disabled(model.availableFixtures.isEmpty)
                }

            }
        }
    }

    private var outputDeck: some View {
        PanelSurface(title: "DMX / OSC") {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Picker("Serial port", selection: $model.selectedPortLabel) {
                        ForEach(model.ports, id: \.self) { port in
                            Text(port.label).tag(port.label)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .pickerStyle(.menu)

                    Button("Refresh") {
                        model.refreshPorts()
                    }
                }

                HStack(spacing: 10) {
                    Button("Connect") { model.connectDMX() }
                        .buttonStyle(.borderedProminent)
                    Button("Disconnect") { model.disconnectDMX() }
                        .buttonStyle(.bordered)
                    Button("Blackout") { model.blackout() }
                        .buttonStyle(.borderedProminent)
                        .tint(.red)
                }

                Divider()

                LabeledStatusRow(title: "DMX", text: model.dmxStatus)
                LabeledStatusRow(title: "OSC", text: model.oscStatus)

                Divider()

                HStack(spacing: 8) {
                    Button {
                        if model.virtualDjBeatPulsePreviewEnabled {
                            model.stopVirtualDjBeatPulsePreview()
                        } else {
                            model.startVirtualDjBeatPulsePreview()
                        }
                    } label: {
                        Label(
                            model.virtualDjBeatPulsePreviewEnabled
                                ? "Stop VirtualDJ-preview"
                                : "Test VirtualDJ-preview",
                            systemImage: model.virtualDjBeatPulsePreviewEnabled
                                ? "stop.fill"
                                : "sparkles"
                        )
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(model.virtualDjBeatPulsePreviewEnabled ? .red : BeatBeamPalette.brandCyan)

                    Text(model.virtualDjBeatPulsePreviewStatus)
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .foregroundStyle(BeatBeamPalette.secondaryText)
                        .lineLimit(2)
                }

                Text("Alleen in de app-preview; er wordt geen DMX-signaal verstuurd.")
                    .font(.system(size: 10))
                    .foregroundStyle(BeatBeamPalette.secondaryText)
            }
        }
    }

    private var playbackSummaryDeck: some View {
        PanelSurface(title: "Now", compact: true) {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    DeckTransportTile(title: model.deck1Title, meta: model.deck1Meta, time: model.deck1Time, isActive: model.deck1IsActive)
                    DeckTransportTile(title: model.deck2Title, meta: model.deck2Meta, time: model.deck2Time, isActive: model.deck2IsActive)
                }

                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(model.trackTitle)
                            .font(.system(size: 15, weight: .semibold))
                            .lineLimit(1)
                        Text(model.autoShowCueText)
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }

                    Spacer(minLength: 0)

                    Text(model.autoShowStyleLabel)
                        .font(.system(size: 11, weight: .bold, design: .monospaced))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(BeatBeamPalette.mutedBackground)
                        .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                }

                LazyVGrid(
                    columns: [
                        GridItem(.flexible(minimum: 72), spacing: 8),
                        GridItem(.flexible(minimum: 72), spacing: 8),
                        GridItem(.flexible(minimum: 72), spacing: 8),
                        GridItem(.flexible(minimum: 72), spacing: 8),
                        GridItem(.flexible(minimum: 72), spacing: 8),
                    ],
                    spacing: 8
                ) {
                    CompactMetricTile(title: "BPM", value: model.bpmValue)
                    CompactMetricTile(title: "Beat", value: model.beatValue)
                    CompactMetricTile(title: "Bar", value: model.barValue)
                    CompactMetricTile(title: "Phrase", value: model.phraseCurrentValue)
                    CompactMetricTile(title: "Next", value: model.phraseNextValue)
                }

                TransportMiniStrip()
            }
        }
    }

    private var transportDetailPanel: some View {
        PanelSurface(title: "Transport", compact: true) {
            VStack(alignment: .leading, spacing: 8) {
                TransportControlPanel()

                HStack(spacing: 8) {
                    DeckTransportTile(title: model.deck1Title, meta: model.deck1Meta, time: model.deck1Time, isActive: model.deck1IsActive)
                    DeckTransportTile(title: model.deck2Title, meta: model.deck2Meta, time: model.deck2Time, isActive: model.deck2IsActive)
                }

                VStack(alignment: .leading, spacing: 2) {
                    Text("MASTER")
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .foregroundStyle(.secondary)
                    Text(model.trackTitle)
                        .font(.system(size: 15, weight: .semibold))
                        .lineLimit(1)
                    Text(model.trackMeta)
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }

                LazyVGrid(
                    columns: [
                        GridItem(.flexible(minimum: 88), spacing: 8),
                        GridItem(.flexible(minimum: 88), spacing: 8),
                        GridItem(.flexible(minimum: 88), spacing: 8),
                        GridItem(.flexible(minimum: 88), spacing: 8),
                    ],
                    spacing: 8
                ) {
                    CompactMetricTile(title: "BPM", value: model.bpmValue)
                    CompactMetricTile(title: "Beat", value: model.beatValue)
                    CompactMetricTile(title: "Time", value: model.timeValue)
                    CompactMetricTile(title: "Mood", value: model.moodValue)
                    CompactMetricTile(title: "Phrase", value: model.phraseCurrentValue)
                    CompactMetricTile(title: "Next", value: model.phraseNextValue)
                    CompactMetricTile(title: "Count / ETA", value: "\(model.phraseCountValue) • \(model.phraseEtaValue)")
                }

                WaveformTransportTile(
                    history: model.waveformHistory,
                    energyValue: model.waveformEnergyValue,
                    status: model.waveformStatusText,
                    influence: model.waveformInfluenceText,
                    anticipation: model.waveformAnticipation,
                    bandValues: [
                        SignalMeterValue(label: "Low", value: model.waveformBandLow, accent: Color.orange),
                        SignalMeterValue(label: "Mid", value: model.waveformBandMid, accent: Color.cyan),
                        SignalMeterValue(label: "High", value: model.waveformBandHigh, accent: Color.purple)
                    ],
                    lookahead2Values: [
                        SignalMeterValue(label: "Low", value: model.waveformLookahead2Low, accent: Color.orange),
                        SignalMeterValue(label: "Mid", value: model.waveformLookahead2Mid, accent: Color.cyan),
                        SignalMeterValue(label: "High", value: model.waveformLookahead2High, accent: Color.purple)
                    ],
                    lookahead4Values: [
                        SignalMeterValue(label: "Low", value: model.waveformLookahead4Low, accent: Color.orange),
                        SignalMeterValue(label: "Mid", value: model.waveformLookahead4Mid, accent: Color.cyan),
                        SignalMeterValue(label: "High", value: model.waveformLookahead4High, accent: Color.purple)
                    ],
                    drumValues: [
                        SignalMeterValue(label: "Kick", value: model.drumKick, accent: Color.red),
                        SignalMeterValue(label: "Snare", value: model.drumSnare, accent: Color.blue),
                        SignalMeterValue(label: "Hat", value: model.drumHihat, accent: Color.green)
                    ]
                )

                Text(model.phraseSummary)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(.secondary)

                Text(model.oscSourceStatus)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder
    private func utilityPanelView(_ panel: UtilityPanel) -> some View {
        switch panel {
        case .transport:
            transportDetailPanel
        case .remote:
            RemoteAccessPanel(embedded: false)
        case .universe:
            monitorPanel
        }
    }

    private var monitorPanel: some View {
        PanelSurface(title: "Universe Monitor") {
            VStack(alignment: .leading, spacing: 10) {
                Text(model.universeSummary)
                    .font(.headline)
                Text(model.conflictSummary)
                    .foregroundStyle(.secondary)

                DisclosureGroup("Final Motion Projection") {
                    Text(model.renderedMotionSummary)
                        .font(.system(.caption2, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.top, 4)
                }
                .font(.system(.caption, design: .monospaced))

                Group {
                    if monitorFixtures.isEmpty {
                        Text("Geen actieve fixtures of ranges beschikbaar.")
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    } else {
                        ScrollView {
                            VStack(alignment: .leading, spacing: 8) {
                                ForEach(Array(monitorFixtures.enumerated()), id: \.element.id) { index, group in
                                    UniverseFixtureListBlock(
                                        group: group,
                                        isStriped: index.isMultiple(of: 2)
                                    )
                                }
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }
}

struct SlotPanelView: View {
    @EnvironmentObject private var model: AppModel
    @ObservedObject var editor: SlotEditor

    private var canRemoveFixture: Bool {
        model.slotEditors.count > 1
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            PanelSurface(title: editor.label, compact: true) {
                VStack(alignment: .leading, spacing: 12) {
                    HStack(alignment: .center, spacing: 12) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(editor.fixtureLabel)
                                .font(.headline)
                            Text(editor.rangeText.isEmpty ? "\(editor.fixtureLabel) | ongeldige mode" : editor.rangeText)
                                .foregroundStyle(.secondary)
                        }

                        Spacer(minLength: 12)
                        Button {
                            model.removeSlot(editor.id)
                        } label: {
                            HStack(spacing: 6) {
                                Image(systemName: "trash")
                                    .font(.system(size: 12, weight: .semibold))
                                Text("Verwijder")
                                    .font(.system(size: 12, weight: .semibold))
                            }
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                            .background(canRemoveFixture ? BeatBeamPalette.warningActive : BeatBeamPalette.mutedBackground)
                            .foregroundStyle(canRemoveFixture ? Color.black : Color.white.opacity(0.55))
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                        }
                        .buttonStyle(.plain)
                        .disabled(!canRemoveFixture)

                        ColorPreviewSwatch(editor: editor)
                    }

                    HStack(alignment: .top, spacing: 12) {
                        PanelSurface(title: "Patch", compact: true) {
                            VStack(alignment: .leading, spacing: 10) {
                                Picker("Mode", selection: model.stringBinding(for: editor, \.mode)) {
                                    ForEach(editor.modeOptions, id: \.self) { mode in
                                        Text(mode).tag(mode)
                                    }
                                }
                                .pickerStyle(.menu)

                                Stepper(value: model.stepperBinding(for: editor, \.address, range: 1...512), in: 1...512) {
                                    Text("Address \(editor.address)")
                                        .font(.system(.body, design: .monospaced))
                                }

                                VStack(alignment: .leading, spacing: 6) {
                                    Text("Group")
                                        .font(.system(.caption, design: .monospaced))
                                        .foregroundStyle(.secondary)
                                    TextField("movers_a / movers_b / pars", text: model.stringBinding(for: editor, \.groupID))
                                        .textFieldStyle(.roundedBorder)
                                    Text("Fixtures in dezelfde group bewegen en kleuren als team.")
                                        .font(.system(.caption2, design: .monospaced))
                                        .foregroundStyle(.secondary)
                                }

                                if editor.supportsPan || editor.supportsTilt {
                                    Divider()

                                    Text("Calibration")
                                        .font(.system(.caption, design: .monospaced))
                                        .foregroundStyle(.secondary)

                                    if let anchor = StageAnchor(rawValue: model.anchorAssignment(for: editor.id)) {
                                        Text("Map position \(anchor.title)")
                                            .font(.system(.caption2, design: .monospaced))
                                            .foregroundStyle(.secondary)
                                    }

                                    Text("Gebruik Map > Edit voor richting en mount. Hieronder alleen de directe correcties en pose-targets die autoshow nog gebruikt.")
                                        .font(.system(.caption2, design: .monospaced))
                                        .foregroundStyle(.secondary)

                                    LazyVGrid(
                                        columns: [
                                            GridItem(.flexible(minimum: 120), spacing: 10),
                                            GridItem(.flexible(minimum: 120), spacing: 10),
                                        ],
                                        spacing: 10
                                    ) {
                                        if editor.supportsPanFine || editor.supportsTiltFine {
                                            Toggle("Use fine pan/tilt", isOn: model.boolBinding(for: editor, \.useFinePanTilt))
                                            Text(
                                                editor.useFinePanTilt
                                                    ? "DMX fine kanalen actief voor extra precisie."
                                                    : "Fine kanalen worden op 0 geforceerd."
                                            )
                                            .font(.system(.caption2, design: .monospaced))
                                            .foregroundStyle(.secondary)
                                        }

                                        if editor.supportsPan {
                                            Toggle("Pan invert", isOn: model.boolBinding(for: editor, \.panInvert))
                                            Stepper(value: model.stepperBinding(for: editor, \.panOffsetDeg, range: -180...180), in: -180...180) {
                                                Text("Pan offset \(editor.panOffsetDeg)°")
                                                    .font(.system(.body, design: .monospaced))
                                            }
                                            Stepper(value: model.stepperBinding(for: editor, \.panSpanPercent, range: 5...160), in: 5...160) {
                                                Text("Pan span \(editor.panSpanPercent)%")
                                                    .font(.system(.body, design: .monospaced))
                                            }
                                        }

                                        if editor.supportsTilt {
                                            Toggle("Tilt invert", isOn: model.boolBinding(for: editor, \.tiltInvert))
                                            Stepper(value: model.stepperBinding(for: editor, \.tiltOffsetDeg, range: -90...90), in: -90...90) {
                                                Text("Tilt offset \(editor.tiltOffsetDeg)°")
                                                    .font(.system(.body, design: .monospaced))
                                            }
                                            Stepper(value: model.stepperBinding(for: editor, \.tiltSpanPercent, range: 5...160), in: 5...160) {
                                                Text("Tilt span \(editor.tiltSpanPercent)%")
                                                    .font(.system(.body, design: .monospaced))
                                            }
                                        }
                                    }

                                    DisclosureGroup {
                                        LazyVGrid(
                                            columns: [
                                                GridItem(.flexible(minimum: 120), spacing: 10),
                                                GridItem(.flexible(minimum: 120), spacing: 10),
                                            ],
                                            spacing: 10
                                        ) {
                                            Button("Save Center") {
                                                model.captureCurrentPose("center", for: editor)
                                            }
                                            .buttonStyle(.bordered)
                                            .controlSize(.small)

                                            Text(editor.poseCenter.map { "P\($0.pan) T\($0.tilt)" } ?? "niet gezet")
                                                .font(.system(.caption2, design: .monospaced))
                                                .foregroundStyle(.secondary)

                                            Button("Save Audience L") {
                                                model.captureCurrentPose("audience_left", for: editor)
                                            }
                                            .buttonStyle(.bordered)
                                            .controlSize(.small)

                                            Text(editor.poseAudienceLeft.map { "P\($0.pan) T\($0.tilt)" } ?? "niet gezet")
                                                .font(.system(.caption2, design: .monospaced))
                                                .foregroundStyle(.secondary)

                                            Button("Save Audience C") {
                                                model.captureCurrentPose("audience_center", for: editor)
                                            }
                                            .buttonStyle(.bordered)
                                            .controlSize(.small)

                                            Text(editor.poseAudienceCenter.map { "P\($0.pan) T\($0.tilt)" } ?? "niet gezet")
                                                .font(.system(.caption2, design: .monospaced))
                                                .foregroundStyle(.secondary)

                                            Button("Save Audience R") {
                                                model.captureCurrentPose("audience_right", for: editor)
                                            }
                                            .buttonStyle(.bordered)
                                            .controlSize(.small)

                                            Text(editor.poseAudienceRight.map { "P\($0.pan) T\($0.tilt)" } ?? "niet gezet")
                                                .font(.system(.caption2, design: .monospaced))
                                                .foregroundStyle(.secondary)

                                            Button("Save Ceiling C") {
                                                model.captureCurrentPose("ceiling_center", for: editor)
                                            }
                                            .buttonStyle(.bordered)
                                            .controlSize(.small)

                                            Text(editor.poseCeilingCenter.map { "P\($0.pan) T\($0.tilt)" } ?? "niet gezet")
                                                .font(.system(.caption2, design: .monospaced))
                                                .foregroundStyle(.secondary)
                                        }
                                        .padding(.top, 8)
                                    } label: {
                                        Text("Pose Targets")
                                            .font(.system(.caption, design: .monospaced))
                                            .foregroundStyle(.secondary)
                                    }
                                }
                            }
                        }
                        .frame(maxWidth: 360)

                        PanelSurface(title: "Settings", compact: true) {
                            VStack(alignment: .leading, spacing: 10) {
                                Text("Behavior")
                                    .font(.system(.caption, design: .monospaced))
                                    .foregroundStyle(.secondary)

                                LazyVGrid(
                                    columns: [
                                        GridItem(.flexible(minimum: 120), spacing: 10),
                                        GridItem(.flexible(minimum: 120), spacing: 10),
                                    ],
                                    spacing: 10
                                ) {
                                    Toggle("Enabled", isOn: model.boolBinding(for: editor, \.enabled))
                                    Toggle("Sync", isOn: model.boolBinding(for: editor, \.syncEnabled))
                                    Toggle("Beat pulse", isOn: model.boolBinding(for: editor, \.beatPulseEnabled))
                                    Toggle("OSC strobe", isOn: model.boolBinding(for: editor, \.oscStrobeEnabled))
                                }

                                Divider()

                                Text("Color Source")
                                    .font(.system(.caption, design: .monospaced))
                                    .foregroundStyle(.secondary)

                                Picker("Color source", selection: model.stringBinding(for: editor, \.colorSource)) {
                                    Text("Manual").tag("manual")
                                    Text("Phrase").tag("phrase")
                                    Text("Mood").tag("mood")
                                    Text("Bank").tag("color_bank")
                                }
                                .pickerStyle(.segmented)
                            }
                        }
                    }

                    HStack(alignment: .top, spacing: 12) {
                        FaderBankSection(
                            title: "Beam",
                            faders: [
                                FaderSpec(title: "Dimmer", value: model.intBinding(for: editor, \.dimmer, range: 0...255), display: "\(editor.dimmer)", enabled: editor.supportsDimmer),
                                FaderSpec(title: "Strobe", value: model.intBinding(for: editor, \.strobe, range: 0...255), display: "\(editor.strobe)", enabled: editor.supportsStrobe),
                                FaderSpec(title: "Program", value: model.intBinding(for: editor, \.program, range: 0...255), display: "\(editor.program)", enabled: editor.supportsProgram),
                                FaderSpec(title: "Speed", value: model.intBinding(for: editor, \.speed, range: 0...255), display: "\(editor.speed)", enabled: editor.supportsSpeed),
                            ]
                        )

                        FaderBankSection(
                            title: "Position",
                            faders: [
                                FaderSpec(title: "Pan", value: model.intBinding(for: editor, \.pan, range: 0...255), display: "\(editor.pan)", enabled: editor.supportsPan),
                                FaderSpec(title: "Tilt", value: model.intBinding(for: editor, \.tilt, range: 0...255), display: "\(editor.tilt)", enabled: editor.supportsTilt),
                                FaderSpec(title: "Move", value: model.intBinding(for: editor, \.panTiltSpeed, range: 0...255), display: "\(editor.panTiltSpeed)", enabled: editor.supportsPanTiltSpeed),
                            ]
                        )

                        FaderBankSection(
                            title: "Rhythm",
                            faders: [
                                FaderSpec(title: "Depth", value: model.intBinding(for: editor, \.beatDepth, range: 0...255), display: "\(editor.beatDepth)", enabled: true),
                                FaderSpec(title: "Decay", value: model.intBinding(for: editor, \.beatDecayMs, range: 30...1500), display: "\(editor.beatDecayMs)", upperBound: 1500, enabled: true),
                            ]
                        )

                        FaderBankSection(
                            title: "Color Mix",
                            faders: [
                                FaderSpec(title: "Red", value: model.intBinding(for: editor, \.red, range: 0...255), display: "\(editor.red)", enabled: true, tint: .red),
                                FaderSpec(title: "Green", value: model.intBinding(for: editor, \.green, range: 0...255), display: "\(editor.green)", enabled: true, tint: .green),
                                FaderSpec(title: "Blue", value: model.intBinding(for: editor, \.blue, range: 0...255), display: "\(editor.blue)", enabled: true, tint: .blue),
                                FaderSpec(title: "White", value: model.intBinding(for: editor, \.white, range: 0...255), display: "\(editor.white)", enabled: editor.supportsWhite, tint: .white),
                            ]
                        )
                    }

                    if !editor.extraControls.isEmpty {
                        FaderBankSection(
                            title: "Fixture FX",
                            faders: editor.extraControls.map { control in
                                let currentValue = editor.extraValues[control.id] ?? control.defaultValue
                                return FaderSpec(
                                    title: control.title,
                                    value: model.extraIntBinding(for: editor, controlID: control.id, range: 0...255),
                                    display: "\(currentValue)"
                                )
                            }
                        )
                    }

                    if editor.supportsPan || editor.supportsTilt || editor.supportsPanTiltSpeed {
                        HStack(alignment: .center, spacing: 10) {
                            Button("Home") {
                                model.moveFixtureHome(editor)
                            }
                            .buttonStyle(.borderedProminent)
                            .controlSize(.small)

                            Text("Neutrale handmatige home-stand voor kalibratie.")
                                .font(.system(.caption2, design: .monospaced))
                                .foregroundStyle(.secondary)

                            Spacer(minLength: 0)
                        }
                    }
                }
            }
        }
    }
}

struct LivePresetWorkspaceView: View {
    @EnvironmentObject private var model: AppModel

    private let colorOptions: [(value: String, title: String, swatch: Color, secondary: Color?)] = [
        ("none", "Auto", .clear, nil),
        ("red", "Red", Color(red: 1.00, green: 0.22, blue: 0.18), nil),
        ("yellow", "Yellow", Color(red: 1.00, green: 0.85, blue: 0.12), nil),
        ("green", "Green", Color(red: 0.18, green: 0.92, blue: 0.38), nil),
        ("lime", "Lime", Color(red: 0.55, green: 1.00, blue: 0.12), nil),
        ("purple", "Purple", Color(red: 0.72, green: 0.24, blue: 1.00), nil),
        ("pink", "Pink", Color(red: 1.00, green: 0.12, blue: 0.62), nil),
        ("cyan", "Cyan", Color(red: 0.10, green: 0.92, blue: 0.92), nil),
        ("orange", "Orange", Color(red: 1.00, green: 0.52, blue: 0.12), nil),
        ("blue", "Blue", Color(red: 0.18, green: 0.44, blue: 1.00), nil),
        ("white", "White", Color.white, nil),
        ("rainbow", "Rainbow", Color(red: 1.00, green: 0.20, blue: 0.18), Color(red: 0.18, green: 0.44, blue: 1.00)),
    ]

    private let cueOptions: [(value: String, title: String, icon: String)] = [
        ("audience_riser", "Audience Rise", "arrow.up.forward.circle.fill"),
        ("white_hit", "White Hit", "sun.max.fill"),
        ("color_burst", "Color Burst", "sparkles"),
        ("snap_fan", "Snap Fan", "line.3.horizontal.decrease.circle.fill"),
        ("mirror_bounce", "Mirror Bounce", "arrow.left.arrow.right.circle.fill"),
        ("par_chase_burst", "PAR Chase", "square.3.layers.3d.down.right"),
    ]

    private var colorBinding: Binding<String> {
        Binding(
            get: { model.liveOverrideColor },
            set: { model.setLiveOverrideColor($0) }
        )
    }

    private var manualStrobeBinding: Binding<Bool> {
        Binding(
            get: { model.liveOverrideManualStrobe },
            set: { model.setLiveOverrideManualStrobe($0) }
        )
    }

    private var audienceSweepBinding: Binding<Bool> {
        Binding(
            get: { model.liveOverrideAudienceSweep },
            set: { model.setLiveOverrideAudienceSweep($0) }
        )
    }

    private var allOnBinding: Binding<Bool> {
        Binding(
            get: { model.liveOverrideAllOn },
            set: { model.setLiveOverrideAllOn($0) }
        )
    }

    private var parChaseBinding: Binding<Bool> {
        Binding(
            get: { model.liveOverrideParChase },
            set: { model.setLiveOverrideParChase($0) }
        )
    }

    private var parSnakeBinding: Binding<Bool> {
        Binding(
            get: { model.liveOverrideParSnake },
            set: { model.setLiveOverrideParSnake($0) }
        )
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            PanelSurface(title: "Live Overrides", compact: true) {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Global override-laag bovenop Auto Show. Actieve overrides zijn ook altijd zichtbaar in Live Show.")
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(.secondary)

                    PanelSurface(title: "Color", compact: true) {
                        VStack(alignment: .leading, spacing: 10) {
                            LazyVGrid(
                                columns: [GridItem(.adaptive(minimum: 88, maximum: 116), spacing: 10)],
                                spacing: 10
                            ) {
                                ForEach(colorOptions, id: \.value) { option in
                                    LiveOverrideColorButton(
                                        title: option.title,
                                        value: option.value,
                                        selection: colorBinding,
                                        swatch: option.swatch,
                                        secondary: option.secondary
                                    )
                                }
                            }

                            HStack(spacing: 10) {
                                MetricTile(title: "Color", value: model.liveOverrideColorLabel)
                                MetricTile(title: "Strobe", value: model.liveOverrideManualStrobe ? "On" : "Off")
                                MetricTile(title: "Sweep", value: model.liveOverrideAudienceSweep ? "On" : "Off")
                                MetricTile(title: "All On", value: model.liveOverrideAllOn ? "On" : "Off")
                                MetricTile(title: "PAR Chase", value: model.liveOverrideParChase ? "On" : "Off")
                                MetricTile(title: "PAR Snake", value: model.liveOverrideParSnake ? "On" : "Off")
                            }
                        }
                    }

                    PanelSurface(title: "Effects", compact: true) {
                        VStack(alignment: .leading, spacing: 10) {
                            LazyVGrid(
                                columns: [
                                    GridItem(.flexible(minimum: 120), spacing: 10),
                                    GridItem(.flexible(minimum: 120), spacing: 10),
                                    GridItem(.flexible(minimum: 120), spacing: 10),
                                    GridItem(.flexible(minimum: 120), spacing: 10),
                                ],
                                spacing: 10
                            ) {
                                TouchPadToggleButton(title: "Manual Strobe", systemImage: "bolt.fill", isOn: manualStrobeBinding)
                                TouchPadToggleButton(title: "Audience Sweep", systemImage: "arrow.up.and.down.and.arrow.left.and.right", isOn: audienceSweepBinding)
                                TouchPadToggleButton(title: "All On", systemImage: "light.max", isOn: allOnBinding)
                                TouchPadToggleButton(title: "PAR Chase", systemImage: "arrow.left.and.right", isOn: parChaseBinding)
                                TouchPadToggleButton(title: "PAR Snake", systemImage: "waveform.path", isOn: parSnakeBinding)
                            }

                            HStack {
                                Spacer()
                                Button("Clear Overrides") {
                                    model.clearLiveOverrides()
                                }
                                .buttonStyle(.bordered)
                            }
                        }
                    }

                    PanelSurface(title: "Cue Shots", compact: true) {
                        VStack(alignment: .leading, spacing: 10) {
                            LazyVGrid(
                                columns: [
                                    GridItem(.flexible(minimum: 120), spacing: 10),
                                    GridItem(.flexible(minimum: 120), spacing: 10),
                                    GridItem(.flexible(minimum: 120), spacing: 10),
                                ],
                                spacing: 10
                            ) {
                                ForEach(cueOptions, id: \.value) { cue in
                                    TouchPadTriggerButton(
                                        title: cue.title,
                                        systemImage: cue.icon,
                                        isActive: model.liveOneShotCue == cue.value,
                                        progress: model.liveOneShotCue == cue.value ? model.liveOneShotCueProgress : 0,
                                        action: { model.triggerOneShotCue(cue.value) }
                                    )
                                }
                            }

                            HStack(spacing: 10) {
                                MetricTile(title: "Cue", value: model.liveOneShotCue == "none" ? "-" : model.liveOneShotCueLabel)
                                MetricTile(title: "State", value: model.liveOneShotCue == "none" ? "Ready" : "\(Int((model.liveOneShotCueProgress * 100).rounded()))%")
                            }
                        }
                    }
                }
            }
        }
    }
}

struct RemoteAccessPanel: View {
    @EnvironmentObject private var model: AppModel
    var embedded: Bool = false

    var body: some View {
        Group {
            if embedded {
                embeddedBody
            } else {
                PanelSurface(title: "iPad Remote", compact: true) {
                    fullBody
                }
            }
        }
    }

    private var embeddedBody: some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(alignment: .leading, spacing: 8) {
                Text("iPad Remote")
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)

                Text(model.remoteStatusText)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)

                Text(model.remoteURLText)
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .lineLimit(2)
                    .truncationMode(.middle)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 7)
                    .background(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(BeatBeamPalette.raisedBackground)
                    )

                Text("Pairing code: \(model.remotePairingCodeText)")
                    .font(.system(size: 14, weight: .bold, design: .monospaced))
                    .foregroundStyle(BeatBeamPalette.brandCyan)

                HStack(spacing: 8) {
                    Button("Copy") {
                        model.copyRemoteURL()
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .disabled(model.remoteURLText == "-")

                    Button("Open") {
                        model.openRemoteURL()
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .disabled(model.remoteURLText == "-")
                }
            }

            if model.remoteURLText != "-" {
                QRCodeCard(text: model.remoteURLText, size: 92, label: nil)
                    .frame(width: 108)
            }
        }
    }

    private var fullBody: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(model.remoteStatusText)
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary)
                .textSelection(.enabled)

            VStack(alignment: .leading, spacing: 8) {
                Text("Remote URL")
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)

                Text(model.remoteURLText)
                    .font(.system(size: 12, weight: .medium, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                    .background(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(BeatBeamPalette.raisedBackground)
                    )
            }

            HStack {
                Text("Pairing code")
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
                Spacer()
                Text(model.remotePairingCodeText)
                    .font(.system(size: 18, weight: .bold, design: .monospaced))
                    .foregroundStyle(BeatBeamPalette.brandCyan)
                    .textSelection(.enabled)
            }

            HStack(spacing: 8) {
                Button("Copy URL") {
                    model.copyRemoteURL()
                }
                .buttonStyle(.bordered)
                .disabled(model.remoteURLText == "-")

                Button("Open in Browser") {
                    model.openRemoteURL()
                }
                .buttonStyle(.bordered)
                .disabled(model.remoteURLText == "-")
            }

            if model.remoteTailscaleURLText != "-" {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Tailscale URL")
                        .font(.system(size: 11, weight: .medium, design: .monospaced))
                        .foregroundStyle(BeatBeamPalette.brandCyan)
                    Text(model.remoteTailscaleURLText)
                        .font(.system(size: 12, weight: .medium, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(10)
                        .background(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(BeatBeamPalette.raisedBackground)
                        )
                    HStack {
                        Button("Copy Tailscale URL") {
                            model.copyTailscaleRemoteURL()
                        }
                        .buttonStyle(.bordered)
                        Spacer()
                    }
                    HStack {
                        Spacer(minLength: 0)
                        QRCodeCard(text: model.remoteTailscaleURLText, size: 132, label: "Scan with iPad via Tailscale")
                        Spacer(minLength: 0)
                    }
                }
            }

            if model.remoteURLText != "-" {
                HStack {
                    Spacer(minLength: 0)
                    QRCodeCard(text: model.remoteURLText, size: 132, label: "Scan with iPad")
                    Spacer(minLength: 0)
                }
            }
        }
    }
}

struct QRCodeCard: View {
    let text: String
    var size: CGFloat = 132
    var label: String? = "Scan with iPad"

    private let context = CIContext()
    private let filter = CIFilter.qrCodeGenerator()

    private var image: NSImage? {
        filter.message = Data(text.utf8)
        filter.correctionLevel = "M"
        guard let outputImage = filter.outputImage else { return nil }
        let scaled = outputImage.transformed(by: CGAffineTransform(scaleX: 10, y: 10))
        guard let cgImage = context.createCGImage(scaled, from: scaled.extent) else { return nil }
        let size = NSSize(width: cgImage.width, height: cgImage.height)
        return NSImage(cgImage: cgImage, size: size)
    }

    var body: some View {
        VStack(alignment: .center, spacing: 8) {
            if let image {
                Image(nsImage: image)
                    .interpolation(.none)
                    .resizable()
                    .aspectRatio(1, contentMode: .fit)
                    .frame(width: size, height: size)
                    .padding(8)
                    .background(Color.white)
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            }

            if let label {
                Text(label)
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
        }
    }
}

struct TransportMiniStrip: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        HStack(spacing: 8) {
            HStack(spacing: 6) {
                TransportModePill(title: "Auto", value: "auto", compact: true)
                TransportModePill(title: "OSC", value: "external_osc", compact: true)
                TransportModePill(title: "Tap", value: "manual_tap", compact: true)
            }

            Text(model.transportResolvedMode == "idle" ? "Idle" : model.transportStatusText)
                .font(.system(size: 11, weight: .medium, design: .monospaced))
                .foregroundStyle(BeatBeamPalette.secondaryText)
                .lineLimit(1)

            Spacer(minLength: 0)

            Text("\(Int((model.transportEffectiveBpm ?? model.transportManualBpm).rounded())) BPM")
                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                .padding(.horizontal, 10)
                .padding(.vertical, 7)
                .background(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(BeatBeamPalette.mutedBackground)
                )

            Button {
                model.tapTransportTempo()
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "hand.tap.fill")
                    Text("Tap")
                }
                .font(.system(size: 12, weight: .bold))
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(BeatBeamPalette.utilityGradient)
                )
                .foregroundStyle(.white)
            }
            .buttonStyle(.plain)

            Button {
                model.startRekordboxBridge()
            } label: {
                Image(systemName: "play.fill")
                    .font(.system(size: 12, weight: .bold))
                    .frame(width: 34, height: 34)
                    .background(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(model.bridgeRunning ? BeatBeamPalette.mutedBackground : Color.green.opacity(0.85))
                    )
                    .foregroundStyle(.white)
            }
            .buttonStyle(.plain)
            .disabled(model.bridgeRunning)
            .opacity(model.bridgeRunning ? 0.5 : 1.0)
            .help("Start BPM Trigger / Rekordbox bridge")

            Button {
                model.stopRekordboxBridge()
            } label: {
                Image(systemName: "stop.fill")
                    .font(.system(size: 12, weight: .bold))
                    .frame(width: 34, height: 34)
                    .background(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(model.bridgeRunning ? Color.red.opacity(0.85) : BeatBeamPalette.mutedBackground)
                    )
                    .foregroundStyle(.white)
            }
            .buttonStyle(.plain)
            .disabled(!model.bridgeRunning)
            .opacity(model.bridgeRunning ? 1.0 : 0.5)
            .help("Stop BPM Trigger / Rekordbox bridge")
        }
    }
}

struct TransportControlPanel: View {
    @EnvironmentObject private var model: AppModel

    private let phraseOptions: [(value: String, label: String)] = [
        ("intro", "Intro"),
        ("verse", "Verse"),
        ("build", "Build"),
        ("chorus", "Chorus"),
        ("drop", "Drop"),
        ("down", "Down"),
        ("break", "Break"),
        ("outro", "Outro"),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                TransportModePill(title: "Auto", value: "auto")
                TransportModePill(title: "OSC", value: "external_osc")
                TransportModePill(title: "Tap", value: "manual_tap")

                Spacer(minLength: 0)

                Button {
                    model.tapTransportTempo()
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "hand.tap.fill")
                        Text("Tap Tempo")
                    }
                    .font(.system(size: 12, weight: .bold))
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(BeatBeamPalette.utilityGradient)
                    )
                    .foregroundStyle(.white)
                }
                .buttonStyle(.plain)

                Button {
                    model.resetTransportClock()
                } label: {
                    Image(systemName: "arrow.counterclockwise")
                        .font(.system(size: 13, weight: .bold))
                        .frame(width: 34, height: 34)
                        .background(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(BeatBeamPalette.mutedBackground)
                        )
                        .foregroundStyle(.white)
                }
                .buttonStyle(.plain)
            }

            HStack(spacing: 10) {
                Text("Structuurbron")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(BeatBeamPalette.secondaryText)
                Picker("Structuurbron", selection: Binding(
                    get: { model.structureBehaviorSource },
                    set: { model.setStructureBehaviorSource($0) }
                )) {
                    Text("Legacy").tag("legacy")
                    Text("SongAnalyzer").tag("song_analyzer")
                }
                .pickerStyle(.segmented)
                .labelsHidden()
            }

            HStack(spacing: 10) {
                Menu {
                    ForEach(phraseOptions, id: \.value) { option in
                        Button(option.label) {
                            model.setTransportManualPhrase(option.value)
                        }
                    }
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "waveform")
                        Text(model.transportManualPhraseLabel)
                            .font(.system(size: 12, weight: .semibold))
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(BeatBeamPalette.mutedBackground)
                    )
                    .foregroundStyle(.white)
                }
                .menuStyle(.borderlessButton)

                Button {
                    model.setTransportIdleAnimationEnabled(!model.transportIdleAnimationEnabled)
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: model.transportIdleAnimationEnabled ? "figure.wave.circle.fill" : "figure.wave.circle")
                        Text("Idle")
                            .font(.system(size: 12, weight: .semibold))
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(model.transportIdleAnimationEnabled ? AnyShapeStyle(BeatBeamPalette.activeGradient) : AnyShapeStyle(BeatBeamPalette.mutedBackground))
                    )
                    .foregroundStyle(model.transportIdleAnimationEnabled ? Color.black : Color.white)
                }
                .buttonStyle(.plain)

                Spacer(minLength: 0)
            }

            LazyVGrid(
                columns: [
                    GridItem(.flexible(minimum: 90), spacing: 8),
                    GridItem(.flexible(minimum: 90), spacing: 8),
                    GridItem(.flexible(minimum: 90), spacing: 8),
                    GridItem(.flexible(minimum: 90), spacing: 8),
                ],
                spacing: 8
            ) {
                CompactMetricTile(
                    title: "Mode",
                    value: model.transportResolvedMode == "manual_tap"
                        ? "Tap"
                        : (model.transportResolvedMode == "idle" ? "Idle" : "OSC")
                )
                CompactMetricTile(title: "Manual", value: "\(Int(model.transportManualBpm.rounded()))")
                CompactMetricTile(title: "Live", value: model.transportEffectiveBpm.map { "\(Int($0.rounded()))" } ?? "-")
                CompactMetricTile(title: "Taps", value: "\(model.transportTapCount)/4")
            }

            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    Menu {
                        ForEach(model.liveAudioDevices) { device in
                            Button(device.name) {
                                model.setSelectedLiveAudioDevice(device.id)
                            }
                        }
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: "mic.fill")
                            Text(
                                model.liveAudioDevices.first(where: { $0.id == model.selectedLiveAudioDeviceID })?.name
                                ?? "Geen input"
                            )
                            .font(.system(size: 12, weight: .semibold))
                            .lineLimit(1)
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(BeatBeamPalette.mutedBackground)
                        )
                        .foregroundStyle(.white)
                    }
                    .menuStyle(.borderlessButton)
                    .disabled(model.liveAudioDevices.isEmpty)

                    Button {
                        model.refreshAudioInputs()
                    } label: {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 13, weight: .bold))
                            .frame(width: 34, height: 34)
                            .background(
                                RoundedRectangle(cornerRadius: 8, style: .continuous)
                                    .fill(BeatBeamPalette.mutedBackground)
                            )
                            .foregroundStyle(.white)
                    }
                    .buttonStyle(.plain)

                    Spacer(minLength: 0)

                    Button {
                        model.setLiveAudioEnabled(!model.liveAudioEnabled)
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: model.liveAudioEnabled ? "waveform.circle.fill" : "waveform.circle")
                            Text(model.liveAudioEnabled ? "Audio On" : "Audio Off")
                                .font(.system(size: 12, weight: .bold))
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(model.liveAudioEnabled ? AnyShapeStyle(BeatBeamPalette.utilityGradient) : AnyShapeStyle(BeatBeamPalette.mutedBackground))
                        )
                        .foregroundStyle(.white)
                    }
                    .buttonStyle(.plain)
                    .disabled(model.liveAudioDevices.isEmpty)
                }

                Text(model.liveAudioStatusText)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(BeatBeamPalette.secondaryText)
                    .lineLimit(2)
            }

            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    Button {
                        model.startRekordboxBridge()
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: "play.fill")
                            Text("Bridge Start")
                                .font(.system(size: 12, weight: .bold))
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(BeatBeamPalette.activeGradient)
                        )
                        .foregroundStyle(Color.black)
                    }
                    .buttonStyle(.plain)

                    Button {
                        model.stopRekordboxBridge()
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: "stop.fill")
                            Text("Bridge Stop")
                                .font(.system(size: 12, weight: .bold))
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(BeatBeamPalette.mutedBackground)
                        )
                        .foregroundStyle(.white)
                    }
                    .buttonStyle(.plain)

                    Button {
                        model.refreshBridgeStatus(force: true)
                    } label: {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 13, weight: .bold))
                            .frame(width: 34, height: 34)
                            .background(
                                RoundedRectangle(cornerRadius: 8, style: .continuous)
                                    .fill(BeatBeamPalette.mutedBackground)
                            )
                            .foregroundStyle(.white)
                    }
                    .buttonStyle(.plain)

                    Spacer(minLength: 0)

                    CompactMetricTile(title: "Bridge", value: model.bridgeRunning ? "On" : "Off")
                        .frame(maxWidth: 92)
                }

                Text(model.bridgeStatusText)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(BeatBeamPalette.secondaryText)
                    .lineLimit(2)
            }
        }
    }
}

struct TransportModePill: View {
    @EnvironmentObject private var model: AppModel
    let title: String
    let value: String
    var compact: Bool = false

    private var isActive: Bool {
        model.transportMode == value
    }

    var body: some View {
        Button {
            model.setTransportMode(value)
        } label: {
            Text(title)
                .font(.system(size: compact ? 11 : 12, weight: .bold))
                .padding(.horizontal, compact ? 10 : 12)
                .padding(.vertical, compact ? 7 : 8)
                .background(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(isActive ? AnyShapeStyle(BeatBeamPalette.activeGradient) : AnyShapeStyle(BeatBeamPalette.mutedBackground))
                )
                .foregroundStyle(isActive ? Color.black : Color.white)
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(isActive ? BeatBeamPalette.brandCyan.opacity(0.7) : BeatBeamPalette.border, lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
    }
}

struct DebugInspectorView: View {
    @EnvironmentObject private var model: AppModel
    @AppStorage("beatbeam.debug.liveExpanded") private var liveExpanded = true
    @AppStorage("beatbeam.debug.canonicalExpanded") private var canonicalExpanded = true
    @AppStorage("beatbeam.debug.richEventsExpanded") private var richEventsExpanded = false
    @AppStorage("beatbeam.debug.shadowExpanded") private var shadowExpanded = true
    @AppStorage("beatbeam.debug.fullShadowExpanded") private var fullShadowExpanded = false
    @AppStorage("beatbeam.debug.shadowEventEvidenceExpanded") private var shadowEventEvidenceExpanded = true
    @AppStorage("beatbeam.debug.queueExpanded") private var queueExpanded = false
    @AppStorage("beatbeam.debug.failuresExpanded") private var failuresExpanded = false
    @AppStorage("beatbeam.debug.handoffExpanded") private var handoffExpanded = false
    @AppStorage("beatbeam.debug.legacyExpanded") private var legacyExpanded = false
    @AppStorage("beatbeam.debug.bridgeControlExpanded") private var bridgeControlExpanded = false
    @State private var showFullStructure = false
    @State private var forceReanalysisInFlight = false
    @State private var forceReanalysisStatus: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Debug")
                    .font(.title2.bold())
                Spacer()
                Button("Actieve track heranalyseren") {
                    forceReanalysisInFlight = true
                    forceReanalysisStatus = "aangevraagd"
                    Task {
                        do {
                            let response = try await model.forceReanalyzeActiveTrack()
                            forceReanalysisStatus = response.jobId == nil ? "queued" : "queued · \(response.jobId!)"
                            for _ in 0..<30 {
                                model.refreshDebugState()
                                try? await Task.sleep(for: .seconds(1))
                                if let status = model.debugState?.bridgeDiagnostics?.diagnostics?.activeTrack?.forceStatus,
                                   status != "queued" { break }
                            }
                        } catch {
                            forceReanalysisStatus = "fout: \(error.localizedDescription)"
                        }
                        forceReanalysisInFlight = false
                    }
                }
                .disabled(forceReanalysisInFlight || model.debugState?.activeTrack?.status != "ready")
                Button("Vernieuwen") { model.refreshDebugState() }
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    debugDisclosure("LIVE / VIRTUALDJ", isExpanded: $liveExpanded) {
                        row("Transport", model.debugState?.virtualdj?.transportSource)
                        row("Bridge", model.debugState?.virtualdj?.bridgeStatus)
                        row("Deck", model.debugState?.virtualdj?.activeDeck.map(String.init))
                        row("Track", model.debugState?.activeTrack?.canonicalPath ?? model.debugState?.virtualdj?.trackPath)
                        row("Playing", model.debugState?.virtualdj?.playing.map { $0 ? "Ja" : "Nee" })
                        row("Position", formatDebugTrackPosition(model.debugState?.virtualdj?.positionMilliseconds))
                        row("Position age", model.debugState?.virtualdj?.positionAgeMilliseconds.map { "\($0) ms" })
                        row("Live state", model.debugState?.virtualdj?.transportState)
                        row("Status", model.debugState?.activeTrack?.status)
                        row("Generation", model.debugState?.activeTrack.map { String($0.generation) })
                        row("Activated", model.debugState?.activeTrack?.activatedAtUnixMilliseconds.map { "\($0) ms" })
                        row("Force heranalyse", model.debugState?.bridgeDiagnostics?.diagnostics?.activeTrack?.forceStatus ?? forceReanalysisStatus)
                    }
                    debugDisclosure("CANONICAL ANALYSE", isExpanded: $canonicalExpanded) {
                        row("Schema", model.debugState?.analysis?.schemaVersion.map { "v\($0)" })
                        row("Analysis version", model.debugState?.analysis?.analysisVersion)
                        row("Phrase analysis", model.debugState?.analysis?.phraseAnalysisVersion)
                        row("Model", model.debugState?.analysis?.model)
                        row("Semantic section", model.debugState?.analysis?.semanticSection.map { "\($0.role ?? "—") \($0.occurrence.map(String.init) ?? "—")" })
                        row("Energy z-score", signed(model.debugState?.analysis?.richCurrent?.energy))
                        row("Auto Show modifier", signed(model.debugState?.analysis?.energyModifier))
                        row("Confidence", model.debugState?.analysis?.richCurrent?.confidence.map { String(format: "%.0f", $0) })
                        DisclosureGroup("Volledige trackstructuur", isExpanded: $showFullStructure) {
                            fullTrackStructure
                        }
                        .font(.system(size: 12, weight: .semibold))
                    }
                    debugDisclosure("SHADOW ANALYSE · SECTION CHARACTER", isExpanded: $shadowExpanded) {
                        let shadow = model.debugState?.analysis?.shadowSectionCharacter
                        row("Observation", shadow?.observationId)
                        row("Range", shadowRange(shadow))
                        row("Relative energy", shadowValue(shadow?.relativeEnergy))
                        row("Energy rise", signed(shadow?.energyRise))
                        row("Recurrence", shadowValue(shadow?.recurrenceStrength))
                        row("Family salience", shadowValue(shadow?.familySalience))
                        row("Entry contrast", shadowValue(shadow?.entryContrast))
                        row("Exit contrast", shadowValue(shadow?.exitContrast))
                        row("Build momentum", shadowValue(shadow?.buildMomentum))
                        row("Boundary novelty", shadowValue(shadow?.boundaryNovelty))
                        row("PREPARATION", preparationSummary(shadow?.preparationProfile))
                        row("ARRIVAL", arrivalSummary(shadow?.arrivalProfile))
                        row("ENTRY STRUCTURAL DEPARTURE", structuralDepartureSummary(shadow?.entryStructuralDeparture))
                        row("EXIT STRUCTURAL DEPARTURE", structuralDepartureSummary(shadow?.exitStructuralDeparture))
                        row("Entry raw transition", shadowBoundaryTransition(shadow?.entryBoundary))
                        row("Exit raw transition", shadowBoundaryTransition(shadow?.exitBoundary))
                        row("Confidence", shadow == nil ? nil : "nog niet gekalibreerd")
                        let allShadow = (model.debugState?.handoff?.shadowAnalysis?.sectionCharacters ?? [])
                            .sorted {
                                let start = ($0.startSeconds ?? .greatestFiniteMagnitude, $0.endSeconds ?? .greatestFiniteMagnitude, $0.observationId ?? "")
                                let next = ($1.startSeconds ?? .greatestFiniteMagnitude, $1.endSeconds ?? .greatestFiniteMagnitude, $1.observationId ?? "")
                                return start < next
                            }
                        DisclosureGroup("Volledige shadowstructuur (\(allShadow.count))", isExpanded: $fullShadowExpanded) {
                            if allShadow.isEmpty {
                                Text("Geen shadow observations beschikbaar").foregroundStyle(.secondary)
                            } else {
                                VStack(alignment: .leading, spacing: 7) {
                                    ForEach(Array(allShadow.enumerated()), id: \.offset) { index, observation in
                                        shadowObservationRow(observation, index: index, isLast: index == allShadow.count - 1, currentPositionMilliseconds: model.debugState?.virtualdj?.positionMilliseconds)
                                    }
                                }
                                .padding(.top, 4)
                            }
                        }
                        .font(.system(size: 12, weight: .semibold))
                    }
                    debugDisclosure("SHADOW EVENT EVIDENCE", isExpanded: $shadowEventEvidenceExpanded) {
                        let currentEvidence = model.debugState?.analysis?.shadowEventEvidence
                        row("Boundary", shadowEventBoundary(currentEvidence))
                        row("Origin → destination", shadowEventRoute(currentEvidence))
                        row("PREPARATION", preparationSummary(currentEvidence?.preparationAspect))
                        row("ARRIVAL", arrivalSummary(currentEvidence?.arrivalAspect))
                        row("RMS pre → post", temporalRmsSummary(currentEvidence?.temporalContext))
                        row("Relative energy late-origin → early-destination", temporalRelativeEnergySummary(currentEvidence?.temporalContext))
                        row("Energy window", temporalWindowSummary(currentEvidence?.temporalContext?.window))
                        row("ORIGIN EXIT STRUCTURAL", structuralDepartureSummary(currentEvidence?.structuralDepartureAspect?.originExit))
                        row("DESTINATION ENTRY STRUCTURAL", structuralDepartureSummary(currentEvidence?.structuralDepartureAspect?.destinationEntry))
                        row("Identity", arrangementIdentitySummary(currentEvidence?.arrangementIdentityAspect))
                        row("Destination terminal", currentEvidence?.destinationIsTerminal.map(bool))
                        row("Hypotheses", shadowHypothesesSummary(currentEvidence?.hypotheses))
                        let allEvidence = model.debugState?.handoff?.shadowAnalysis?.eventEvidence ?? []
                        DisclosureGroup("Volledige boundary-evidence (\(allEvidence.count))") {
                            if allEvidence.isEmpty {
                                Text("Geen shadow boundary-evidence beschikbaar").foregroundStyle(.secondary)
                            } else {
                                VStack(alignment: .leading, spacing: 7) {
                                    ForEach(Array(allEvidence.enumerated()), id: \.offset) { index, evidence in
                                        shadowEventEvidenceRow(evidence, index: index, current: evidence.destinationObservationId == currentEvidence?.destinationObservationId)
                                    }
                                }
                                .padding(.top, 4)
                            }
                        }
                        .font(.system(size: 12, weight: .semibold))
                    }
                    debugDisclosure("QUEUE / CACHE / PLAYLIST", isExpanded: $queueExpanded) {
                        let diag = model.debugState?.bridgeDiagnostics?.diagnostics
                        row("Queue", diag?.analysisQueue?.capacity.map { "\(diag?.analysisQueue?.queuedNormal ?? 0) NORMAL · \(diag?.analysisQueue?.queuedHigh ?? 0) HIGH / \($0)" })
                        row("Running", diag?.analysisQueue?.running.map(String.init))
                        row("Completed / failed", diag.map { "\($0.analysisQueue?.completedThisSession ?? 0) / \($0.analysisQueue?.failedThisSession ?? 0)" })
                        row("Cancelled / timed out", diag.map { "\($0.analysisQueue?.cancelledThisSession ?? 0) / \($0.analysisQueue?.timedOutThisSession ?? 0)" })
                        row("Deduplicated / history", diag.map { "\($0.analysisQueue?.deduplicatedThisSession ?? 0) / \($0.analysisQueue?.terminalHistoryCount ?? 0)" })
                        row("Worker", diag?.analysisQueue?.workerHealthy.map { "\($0 ? "healthy" : "unhealthy") · \(diag?.analysisQueue?.workerAlive == true ? "alive" : "idle")" })
                        row("Worker PID", diag?.runningJob?.workerPid.map(String.init))
                        row("Worker timeout", diag?.analysisQueue?.analysisTimeoutSeconds.map { "\($0) s" })
                        row("Last failure category", diag?.analysisQueue?.lastFailureCategory)
                        row("Failed runner", diag?.analysisQueue?.failedRunner.map(String.init))
                        row("Invalid / evicted", diag.map { "\($0.analysisQueue?.failedInvalidResult ?? 0) / \($0.analysisQueue?.evictedNormalForHigh ?? 0)" })
                        row("Other / unique", diag.map { "\($0.analysisQueue?.otherFailed ?? 0) / \($0.analysisQueue?.uniqueFailedTracks ?? 0)" })
                        row("Oldest queued", diag?.analysisQueue?.oldestQueuedMilliseconds.map { "\($0) ms" })
                        row("Running job", diag?.runningJob?.filePath.map { URL(fileURLWithPath: $0).lastPathComponent })
                        row("Priority", diag?.runningJob?.priority)
                        row("Running for", diag?.runningJob?.elapsedMilliseconds.map { "\($0) ms" })
                        row("Cache hits", diag?.playlistWatcher?.cacheHitsThisSession.map(String.init))
                        row("Playlist", diag?.playlistWatcher?.playlistCount.map { "\($0) playlists · \(diag?.playlistWatcher?.discoveredTrackCount ?? 0) tracks" })
                        row("Library current / stale", diag.map { "\($0.playlistWatcher?.currentTrackCount ?? 0) / \($0.playlistWatcher?.staleTrackCount ?? 0)" })
                        row("Needs / failed-known", diag.map { "\($0.playlistWatcher?.needsAnalysisTrackCount ?? 0) / \($0.playlistWatcher?.failedKnownTrackCount ?? 0)" })
                        row("Stale recovery", diag?.staleRecoveryCount.map(String.init))
                    }
                    debugDisclosure("RICH MUSICAL EVENTS", isExpanded: $richEventsExpanded) {
                        row("Current event", model.debugState?.analysis?.currentEvent?.type)
                        row("Event confidence", model.debugState?.analysis?.currentEvent?.confidence.map { String(format: "%.0f", $0) })
                        row("Next event", model.debugState?.analysis?.nextEvent?.type)
                        row("Bars to next", model.debugState?.analysis?.nextEvent?.barsToNext.map(String.init))
                    }
                    debugDisclosure("FAILURES", isExpanded: $failuresExpanded) {
                        let diag = model.debugState?.bridgeDiagnostics?.diagnostics
                        if let failure = diag?.activeTrack?.lastFailure {
                            row("Last failure", [failure.category, failure.phase, failure.message].compactMap { $0 }.joined(separator: " · "))
                        }
                        if let failures = diag?.recentFailures, !failures.isEmpty {
                            ForEach(Array(failures.enumerated()), id: \.offset) { _, failure in
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(failure.filePath.map { URL(fileURLWithPath: $0).lastPathComponent } ?? "—")
                                    Text([failure.category, failure.phase, failure.message].compactMap { $0 }.joined(separator: " · "))
                                        .foregroundStyle(.secondary)
                                }
                            }
                        } else {
                            Text("Geen recente analysefouten").foregroundStyle(.secondary)
                        }
                    }
                    debugDisclosure("HANDOFF / BEATBEAM", isExpanded: $handoffExpanded) {
                        row("Track match", model.debugState?.handoff?.trackMatch)
                        row("Availability", model.debugState?.handoff?.availability)
                        row("Rich analysis", model.debugState?.handoff?.richAnalysis == nil ? "Nee" : "Ja")
                        row("Rich current", model.debugState?.analysis?.richCurrent == nil ? "Nee" : "Ja")
                        row("Shadow diagnostics", model.debugState?.handoff?.shadowAnalysis == nil ? "Nee" : "Ja")
                        row("Source", model.debugState?.handoff?.selectedSource)
                        row("Fallback", model.debugState?.handoff?.fallbackReason)
                    }
                    debugDisclosure("LEGACY / NATIVE DIAGNOSTICS", isExpanded: $legacyExpanded) {
                        row("Native segment", model.debugState?.analysis?.segment?.label)
                        let native = model.debugState?.bridgeDiagnostics?.diagnostics?.nativePlugin
                        row("Poller", native?.poller?.alive.map { $0 ? "alive" : "stopped" })
                        row("Poll count", native?.poller?.pollCounter.map(String.init))
                        row("Last poll", native?.poller?.lastPollUnixMilliseconds.map { "\($0) ms" })
                        row("Master deck", selector(native?.selectors?.masterDeck, native?.selectors?.masterDeckRaw, native?.selectors?.masterDeckQuerySucceeded))
                        row("T0 master observed", native?.selectors?.masterDeckObservedUnixMilliseconds.map { "\($0) ms" })
                        row("Plugin deck", selector(native?.selectors?.pluginDeck, native?.selectors?.pluginDeckRaw, native?.selectors?.pluginDeckQuerySucceeded))
                        row("Left deck", selector(native?.selectors?.leftDeck, native?.selectors?.leftDeckRaw, native?.selectors?.leftDeckQuerySucceeded))
                        row("Right deck", selector(native?.selectors?.rightDeck, native?.selectors?.rightDeckRaw, native?.selectors?.rightDeckQuerySucceeded))
                        if let candidates = native?.candidates, !candidates.isEmpty {
                            ForEach(Array(candidates.enumerated()), id: \.offset) { _, candidate in
                                row("Deck \(candidate.deck.map(String.init) ?? "—")", "\(candidate.sources?.joined(separator: " / ") ?? "unknown") · play \(bool(candidate.playing)) · path \(candidate.filePath ?? "empty") · relevant \(bool(candidate.relevant))")
                            }
                        } else {
                            row("Candidates", native == nil ? nil : "none")
                        }
                        row("Selected", native?.selection?.selectedDeck.map { "deck \($0) · \(native?.selection?.selectedFilePath ?? "")" })
                        row("Selection reason", native?.selection?.reason)
                        row("T1 selection", native?.selection?.authoritativeSelectionUnixMilliseconds.map { "\($0) ms" })
                        row("No-selection reason", native?.selection?.noSelectionReason)
                        row("Last action", native?.ipc?.lastAction)
                        row("T2 activate emitted", native?.ipc?.activateEmittedUnixMilliseconds.map { "\($0) ms" })
                        row("Send result", native?.ipc?.lastSendSucceeded.map(bool))
                        row("Last error", native?.ipc?.lastError)
                        row("Response", native?.response?.status.map { "\($0) / \(bool(native?.response?.success))" })
                        row("Response error", native?.response?.errorMessage ?? native?.response?.errorCode)
                        row("Bridge / resync", native?.recovery.map { "\($0.bridgeHealth ?? "—") / \(bool($0.resyncPending))" })
                    }
                    debugDisclosure("LEGACY / BRIDGE CONTROL", isExpanded: $bridgeControlExpanded) {
                        let control = model.debugState?.bridgeDiagnostics?.diagnostics?.control
                        row("Last received", control?.type)
                        row("Request ID", control?.requestId)
                        row("Deck", control?.deck.map(String.init))
                        row("Track", control?.filePath)
                        row("Valid", control?.valid.map(bool))
                        row("Validation error", control?.validationError)
                        row("Accepted", control?.accepted.map(bool))
                        row("Cache", control?.cacheState)
                        row("Requested generation", control?.requestedGeneration.map(String.init))
                        row("Result", control?.resultStatus.map { "\($0) / \(control?.resultGeneration.map(String.init) ?? "—")" })
                        row("Activate received", control?.activateReceived.map(String.init))
                        row("Activate success / failed", control.map { "\($0.activateSucceeded ?? 0) / \($0.activateFailed ?? 0)" })
                        row("Deactivate received", control?.deactivateReceived.map(String.init))
                        row("Last mutation", control?.lastMutation?.type)
                        row("Mutation reason", control?.lastMutation?.reason)
                        row("Mutation timestamp", control?.lastMutation?.timestampUtc)
                        row("Processing error", control?.processingError)
                    }
                }
            }
        }
        .padding(20)
        .onAppear { model.refreshDebugState() }
    }

    private func selector(_ deck: Int?, _ raw: Double?, _ succeeded: Bool?) -> String? {
        guard let succeeded else { return nil }
        return "\(deck.map(String.init) ?? "—") (raw \(raw.map { String(format: "%.0f", $0) } ?? "—"), \(succeeded ? "ok" : "failed"))"
    }

    @ViewBuilder
    private var fullTrackStructure: some View {
        let rich = model.debugState?.handoff?.richAnalysis
        if let sections = rich?.sections, !sections.isEmpty {
            ScrollView {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(sections.enumerated()), id: \.offset) { offset, section in
                        structureSemanticSectionRow(section, fallbackIndex: offset, nativeSegments: rich?.segments ?? [])
                    }
                    structureEvents(rich?.events)
                }.padding(.vertical, 5)
            }.frame(maxHeight: 280)
        } else if let segments = rich?.segments, !segments.isEmpty {
            ScrollView {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(segments.enumerated()), id: \.offset) { offset, segment in
                        structureSegmentRow(segment, fallbackIndex: offset)
                    }
                    if let events = rich?.events, !events.isEmpty {
                        Divider().padding(.vertical, 3)
                        Text("Rich Musical Events")
                            .font(.system(size: 11, weight: .bold, design: .monospaced))
                            .foregroundStyle(BeatBeamPalette.secondaryText)
                        ForEach(Array(events.enumerated()), id: \.offset) { offset, event in
                            structureEventRow(event, fallbackIndex: offset)
                        }
                    }
                }
                .padding(.vertical, 5)
            }
            .frame(maxHeight: 280)
        } else {
            Text("Geen volledige structuur beschikbaar")
                .font(.system(size: 12, design: .monospaced))
                .foregroundStyle(BeatBeamPalette.secondaryText)
                .padding(.vertical, 5)
        }
    }

    @ViewBuilder
    private func structureEvents(_ events: [DebugTrackStructureEvent]?) -> some View {
        if let events, !events.isEmpty {
            Divider().padding(.vertical, 3)
            Text("Rich Musical Events").font(.system(size: 11, weight: .bold, design: .monospaced)).foregroundStyle(BeatBeamPalette.secondaryText)
            ForEach(Array(events.enumerated()), id: \.offset) { offset, event in
                structureEventRow(event, fallbackIndex: offset)
            }
        }
    }

    private func structureSemanticSectionRow(_ section: DebugSemanticSection, fallbackIndex: Int, nativeSegments: [DebugTrackStructureSegment]) -> some View {
        let currentIndex = model.debugState?.analysis?.semanticSection?.index
        let isCurrent = section.index == currentIndex || (section.index == nil && fallbackIndex == currentIndex)
        let native = nativeSegments.first { ($0.startSeconds ?? .infinity) < (section.endSeconds ?? -.infinity) && ($0.endSeconds ?? -.infinity) > (section.startSeconds ?? .infinity) }
        let bars = "Bar \(section.startBar.map(String.init) ?? "—")–\(section.endBar.map(String.init) ?? "—")"
        let times = "\(formatDebugClock(milliseconds(section.startSeconds)))–\(formatDebugClock(milliseconds(section.endSeconds)))"
        let family = section.familyId.map { " · \($0)" } ?? ""
        return VStack(alignment: .leading, spacing: 2) {
            Text("\(bars)   \(times)")
            Text("\(section.role ?? "—") \(section.occurrence.map(String.init) ?? "—") · Conf \(section.confidence.map { String(format: "%.0f", $0) } ?? "—")\(family)")
            if let native { Text("Native: \(native.label ?? "—") · Conf \(native.confidence.map { String(format: "%.0f", $0) } ?? "—")") }
        }
        .font(.system(size: 11, design: .monospaced)).foregroundStyle(isCurrent ? Color.black : Color.white)
        .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 8).padding(.vertical, 5)
        .background(isCurrent ? BeatBeamPalette.brandCyan : BeatBeamPalette.mutedBackground).clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
    }

    private func structureSegmentRow(_ segment: DebugTrackStructureSegment, fallbackIndex: Int) -> some View {
        let currentIndex = model.debugState?.analysis?.richCurrent?.index
        let isCurrent = segment.index == currentIndex || (segment.index == nil && fallbackIndex == currentIndex)
        let bars = "Bar \(segment.startBar.map(String.init) ?? "—")–\(segment.endBar.map(String.init) ?? "—")"
        let times = "\(formatDebugClock(milliseconds(segment.startSeconds)))–\(formatDebugClock(milliseconds(segment.endSeconds)))"
        return VStack(alignment: .leading, spacing: 2) {
            Text("\(bars)   \(times)")
            Text("\(segment.label ?? "—") · Conf \(segment.confidence.map { String(format: "%.0f", $0) } ?? "—") · E \(signed(segment.energy) ?? "—")")
        }
        .font(.system(size: 11, design: .monospaced))
        .foregroundStyle(isCurrent ? Color.black : Color.white)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 8)
        .padding(.vertical, 5)
        .background(isCurrent ? BeatBeamPalette.brandCyan : BeatBeamPalette.mutedBackground)
        .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
    }

    private func structureEventRow(_ event: DebugTrackStructureEvent, fallbackIndex: Int) -> some View {
        let current = model.debugState?.analysis?.currentEvent
        let isCurrent = event.type == current?.type && event.startSeconds == current?.startSeconds
        let start = "Bar \(event.startBar.map(String.init) ?? "—") · \(formatDebugClock(milliseconds(event.startSeconds)))"
        let end = event.targetSeconds ?? event.endSeconds
        let interval = end.map { " → Bar \(event.targetBar.map(String.init) ?? "—") · \(formatDebugClock(milliseconds($0)))" } ?? ""
        return Text("EVENT \(event.type ?? "—")  \(start)\(interval) · Conf \(event.confidence.map { String(format: "%.0f", $0) } ?? "—")")
            .font(.system(size: 11, design: .monospaced))
            .foregroundStyle(isCurrent ? BeatBeamPalette.brandCyan : BeatBeamPalette.secondaryText)
            .padding(.leading, 12)
    }

    private func milliseconds(_ seconds: Double?) -> Int? {
        guard let seconds, seconds.isFinite, seconds >= 0 else { return nil }
        return Int((seconds * 1000).rounded())
    }

    private func bool(_ value: Bool?) -> String { value == true ? "yes" : value == false ? "no" : "—" }

    private func debugCard<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title).font(.headline)
            content()
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(BeatBeamPalette.raisedGradient)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    private func debugDisclosure<Content: View>(_ title: String, isExpanded: Binding<Bool>, @ViewBuilder content: @escaping () -> Content) -> some View {
        DisclosureGroup(isExpanded: isExpanded) {
            VStack(alignment: .leading, spacing: 7) { content() }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(BeatBeamPalette.raisedGradient)
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        } label: {
            Text(title).font(.headline)
        }
    }

    private func row(_ label: String, _ value: String?) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label).foregroundStyle(.secondary).frame(width: 150, alignment: .leading)
            Text(value?.isEmpty == false ? value! : "—").textSelection(.enabled)
            Spacer(minLength: 0)
        }
        .font(.system(size: 12, design: .monospaced))
    }

    private func signed(_ value: Double?) -> String? {
        guard let value, value.isFinite else { return nil }
        return String(format: "%+.2f", value)
    }

    private func shadowValue(_ value: Double?) -> String? {
        guard let value, value.isFinite else { return nil }
        return String(format: "%.2f", value)
    }

    private func shadowRange(_ shadow: DebugShadowSectionCharacter?) -> String? {
        guard let shadow, let start = shadow.startSeconds, let end = shadow.endSeconds else { return nil }
        return String(format: "%.3f–%.3f s", start, end)
    }

    private func shadowObservationRow(_ observation: DebugShadowSectionCharacter, index: Int, isLast: Bool, currentPositionMilliseconds: Int?) -> some View {
        let current = isCurrentShadowObservation(observation, isLast: isLast, positionMilliseconds: currentPositionMilliseconds)
        return VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text("#\(index + 1)  \(shadowRange(observation) ?? "—") · bars \(barRange(observation)) · \(barCountText(observation))")
                Spacer(minLength: 4)
                if current { Text("actueel").foregroundStyle(BeatBeamPalette.brandCyan) }
            }
            Text("Rec \(shadowValue(observation.recurrenceStrength) ?? "—") · Sal \(shadowValue(observation.familySalience) ?? "—") · Entry \(shadowValue(observation.entryContrast) ?? "—") · Exit \(shadowValue(observation.exitContrast) ?? "—")")
            Text("Energy \(shadowValue(observation.relativeEnergy) ?? "—") · Rise \(signed(observation.energyRise) ?? "—") · Boundary novelty \(shadowValue(observation.boundaryNovelty) ?? "—")")
            if let preparation = preparationSummary(observation.preparationProfile) { Text("Prep \(preparation)") }
            if let arrival = arrivalSummary(observation.arrivalProfile) { Text("Arrival \(arrival)") }
            if let entry = structuralDepartureSummary(observation.entryStructuralDeparture) { Text("Entry structural \(entry)") }
            if let exit = structuralDepartureSummary(observation.exitStructuralDeparture) { Text("Exit structural \(exit)") }
        }
        .font(.system(size: 11, design: .monospaced))
        .foregroundStyle(current ? Color.black : Color.white)
        .padding(7)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(current ? BeatBeamPalette.brandCyan : BeatBeamPalette.mutedBackground)
        .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
    }

    private func barRange(_ observation: DebugShadowSectionCharacter) -> String {
        [observation.startBar, observation.endBar].compactMap { $0.map(String.init) }.joined(separator: "–").isEmpty
            ? "—" : [observation.startBar, observation.endBar].compactMap { $0.map(String.init) }.joined(separator: "–")
    }

    private func barCountText(_ observation: DebugShadowSectionCharacter) -> String {
        observation.barCount.map { "\($0) bars" } ?? "— bars"
    }

    private func shadowBoundarySummary(_ boundary: DebugShadowBoundaryEvidence?) -> String? {
        guard let boundary else { return nil }
        var fields: [String] = []
        if let value = shadowValue(boundary.structuralContextChange) { fields.append("Context \(value)") }
        if let value = shadowValue(boundary.membershipExitStrength) { fields.append("Membership exit \(value)") }
        if let value = shadowValue(boundary.repeatedSectionEnd) { fields.append("Repeat end \(value)") }
        if let value = shadowValue(boundary.recurrenceChange) { fields.append("Recurrence change \(value)") }
        if let route = boundary.structuralRoute { fields.append("Route \(route)") }
        if let value = shadowValue(boundary.structuralEvidence) { fields.append("Evidence \(value)") }
        if let target = boundary.structuralTargetBar { fields.append("Target bar \(target)") }
        return fields.isEmpty ? nil : fields.joined(separator: " · ")
    }

    private func shadowBoundaryTransition(_ boundary: DebugShadowBoundaryEvidence?) -> String? {
        guard let boundary else { return nil }
        var fields: [String] = []
        if let value = shadowValue(boundary.energyChange) { fields.append("E \(value)") }
        if let value = signed(boundary.energyDelta) { fields.append("ΔE \(value)") }
        if let value = shadowValue(boundary.onsetChange) { fields.append("Onset \(value)") }
        if let value = signed(boundary.onsetDelta) { fields.append("ΔOnset \(value)") }
        if let value = shadowValue(boundary.silenceChange) { fields.append("Silence \(value)") }
        if let value = signed(boundary.silenceDelta) { fields.append("ΔSilence \(value)") }
        return fields.isEmpty ? nil : fields.joined(separator: " · ")
    }

    private func preparationSummary(_ profile: DebugPreparationProfile?) -> String? {
        guard let profile else { return nil }
        let fields = [signed(profile.energyTrajectory).map { "Rise \($0)" },
                      signed(profile.exitEnergyDirection).map { "Exit ΔE \($0)" },
                      signed(profile.exitOnsetDirection).map { "ΔO \($0)" },
                      signed(profile.exitSilenceDirection).map { "ΔS \($0)" },
                      shadowValue(profile.exitStructuralContext).map { "Context \($0)" }].compactMap { $0 }
        return fields.isEmpty ? nil : fields.joined(separator: " · ")
    }

    private func arrivalSummary(_ profile: DebugArrivalProfile?) -> String? {
        guard let profile else { return nil }
        let state: String? = {
            guard let origin = shadowValue(profile.originRelativeEnergy), let destination = shadowValue(profile.destinationRelativeEnergy) else { return nil }
            return "E \(origin)→\(destination)"
        }()
        let fields = [state, signed(profile.energyDirection).map { "ΔE \($0)" },
                      signed(profile.onsetDirection).map { "ΔO \($0)" },
                      signed(profile.silenceDirection).map { "ΔS \($0)" },
                      shadowValue(profile.entryContrast).map { "Entry \($0)" },
                      shadowValue(profile.boundaryNovelty).map { "Novelty \($0)" }].compactMap { $0 }
        return fields.isEmpty ? nil : fields.joined(separator: " · ")
    }

    private func structuralDepartureSummary(_ profile: DebugStructuralDepartureProfile?) -> String? {
        guard let profile else { return nil }
        let fields = [shadowValue(profile.structuralContextChange).map { "Context \($0)" },
                      shadowValue(profile.membershipExitStrength).map { "Membership exit \($0)" },
                      shadowValue(profile.repeatedSectionEnd).map { "Repeat end \($0)" },
                      shadowValue(profile.recurrenceChange).map { "Recurrence change \($0)" },
                      profile.structuralRoute.map { "Route \($0)" },
                      shadowValue(profile.structuralEvidence).map { "Evidence \($0)" },
                      profile.structuralTargetBar.map { "Target bar \($0)" }].compactMap { $0 }
        return fields.isEmpty ? nil : fields.joined(separator: " · ")
    }

    private func shadowEventBoundary(_ evidence: DebugShadowEventEvidence?) -> String? {
        guard let evidence else { return nil }
        let time = evidence.boundarySeconds.map { String(format: "%.3f s", $0) }
        let bar = evidence.boundaryBar.map { "bar \($0)" }
        return [time, bar].compactMap { $0 }.joined(separator: " · ")
    }

    private func shadowEventRoute(_ evidence: DebugShadowEventEvidence?) -> String? {
        guard let evidence else { return nil }
        return [evidence.originObservationId, evidence.destinationObservationId].compactMap { $0 }.joined(separator: " → ")
    }

    private func arrangementIdentitySummary(_ aspect: DebugShadowArrangementIdentityAspect?) -> String? {
        guard let aspect else { return nil }
        let fields: [String] = [shadowValue(aspect.recurrenceStrength).map { "Rec \($0)" },
                                shadowValue(aspect.familySalience).map { "Sal \($0)" },
                                aspect.familyId.map { "Family \($0)" },
                                aspect.hasEarlierFamilyOccurrence.map { "Earlier \(bool($0))" }].compactMap { $0 }
        return fields.isEmpty ? nil : fields.joined(separator: " · ")
    }

    private func temporalRmsSummary(_ context: DebugBoundaryTemporalContext?) -> String? {
        guard let context else { return nil }
        return "\(signed(context.preBoundaryNormalizedRms) ?? "—") → \(signed(context.postBoundaryNormalizedRms) ?? "—")"
    }

    private func temporalRelativeEnergySummary(_ context: DebugBoundaryTemporalContext?) -> String? {
        guard let context else { return nil }
        return "\(shadowValue(context.lateOriginRelativeEnergy) ?? "—") → \(shadowValue(context.earlyDestinationRelativeEnergy) ?? "—")"
    }

    private func temporalWindowSummary(_ window: DebugBoundaryTemporalWindow?) -> String? {
        guard let bars = window?.bars, !bars.isEmpty else { return nil }
        return bars.compactMap { bar in
            guard let offset = bar.relativeBarOffset else { return nil }
            return String(format: "%+d E %@ | RMS %@", offset, shadowValue(bar.relativeEnergy) ?? "—", signed(bar.normalizedRms) ?? "—")
        }.joined(separator: " · ")
    }

    private func shadowEventEvidenceRow(_ evidence: DebugShadowEventEvidence, index: Int, current: Bool) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("#\(index + 1)  \(shadowEventRoute(evidence) ?? "—") · \(shadowEventBoundary(evidence) ?? "—")")
            if let preparation = preparationSummary(evidence.preparationAspect) { Text("Prep \(preparation)") }
            if let arrival = arrivalSummary(evidence.arrivalAspect) { Text("Arrival \(arrival)") }
            Text("RMS \(temporalRmsSummary(evidence.temporalContext) ?? "—")")
            Text("Relative energy \(temporalRelativeEnergySummary(evidence.temporalContext) ?? "—")")
            Text("Energy window \(temporalWindowSummary(evidence.temporalContext?.window) ?? "—")")
            if let structural = structuralDepartureSummary(evidence.structuralDepartureAspect?.originExit) { Text("Origin structural \(structural)") }
            if let structural = structuralDepartureSummary(evidence.structuralDepartureAspect?.destinationEntry) { Text("Destination structural \(structural)") }
            if let identity = arrangementIdentitySummary(evidence.arrangementIdentityAspect) { Text("Identity \(identity)") }
            if let terminal = evidence.destinationIsTerminal { Text("Destination terminal \(bool(terminal))") }
            if let hypotheses = shadowHypothesesSummary(evidence.hypotheses) { Text("Hypotheses \(hypotheses)") }
        }
        .font(.system(size: 11, design: .monospaced))
        .foregroundStyle(current ? Color.black : Color.white)
        .padding(7)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(current ? BeatBeamPalette.brandCyan : BeatBeamPalette.mutedBackground)
        .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
    }

    private func shadowHypothesesSummary(_ hypotheses: [DebugShadowEventHypothesis]?) -> String? {
        guard let hypotheses else { return nil }
        guard !hypotheses.isEmpty else { return "—" }
        return hypotheses.compactMap { hypothesis in
            let support = hypothesis.supportingEvidence?.joined(separator: ", ")
            return [hypothesis.kind, hypothesis.anchorKind.map { "anchor \($0)" },
                    hypothesis.startSeconds.map { String(format: "%.3f s", $0) }, support].compactMap { $0 }.joined(separator: " · ")
        }.joined(separator: " | ")
    }

    private func isCurrentShadowObservation(_ observation: DebugShadowSectionCharacter, isLast: Bool, positionMilliseconds: Int?) -> Bool {
        guard let positionMilliseconds, let start = observation.startSeconds, let end = observation.endSeconds else { return false }
        let position = Double(positionMilliseconds) / 1000
        return position >= start && (position < end || (isLast && position == end))
    }
}

struct AutoShowControlView: View {
    @EnvironmentObject private var model: AppModel

    private let styles: [(value: String, title: String, icon: String)] = [
        ("adaptive", "Adaptive", "sparkles"),
        ("club", "Club", "music.note.list"),
        ("cinematic", "Cinematic", "film.stack"),
        ("warm", "Warm", "sun.max.fill"),
        ("festival", "Festival", "bolt.fill"),
        ("minimal", "Minimal", "moon.fill"),
    ]

    private var autoShowBinding: Binding<Bool> {
        Binding(
            get: { model.autoShowEnabled },
            set: { model.setAutoShowEnabled($0) }
        )
    }

    private var styleBinding: Binding<String> {
        Binding(
            get: { model.autoShowStyle },
            set: { model.setAutoShowStyle($0) }
        )
    }

    private var previewRmeBinding: Binding<String> {
        Binding(
            get: { model.previewRmeMode },
            set: { model.setPreviewRmeMode($0) }
        )
    }

    private var previewPulseTestBinding: Binding<String> {
        Binding(get: { model.previewPulseTestMode }, set: { model.setPreviewPulseTestMode($0) })
    }

    private var audiencePanFocusBinding: Binding<Bool> {
        Binding(
            get: { model.autoShowAudiencePanFocusEnabled },
            set: { model.setAutoShowAudiencePanFocusEnabled($0) }
        )
    }

    private var audiencePanMinBinding: Binding<Int> {
        Binding(
            get: { model.autoShowAudiencePanMin },
            set: { model.setAutoShowAudiencePanMin($0) }
        )
    }

    private var audiencePanMaxBinding: Binding<Int> {
        Binding(
            get: { model.autoShowAudiencePanMax },
            set: { model.setAutoShowAudiencePanMax($0) }
        )
    }

    private var audienceTurnPanMinBinding: Binding<Int> {
        Binding(
            get: { model.autoShowAudienceTurnPanMin },
            set: { model.setAutoShowAudienceTurnPanMin($0) }
        )
    }

    private var audienceTurnPanMaxBinding: Binding<Int> {
        Binding(
            get: { model.autoShowAudienceTurnPanMax },
            set: { model.setAutoShowAudienceTurnPanMax($0) }
        )
    }

    private var audienceTiltSplitBinding: Binding<Int> {
        Binding(
            get: { model.autoShowAudienceTiltSplit },
            set: { model.setAutoShowAudienceTiltSplit($0) }
        )
    }

    private var statusValue: String {
        if model.liveOverrideColor != "none" || model.liveOverrideManualStrobe || model.liveOverrideAudienceSweep || model.liveOverrideAllOn {
            return "Override"
        }
        return model.autoShowAvailable ? "Live OSC" : "Waiting"
    }

    @ViewBuilder
    private var previewCompositionCard: some View {
        if let preview = model.previewComposition {
            let isDynamicComposer = preview.mode == "DYNAMIC_COMPOSER"
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(isDynamicComposer ? "DYNAMIC COMPOSER" : "PREVIEW CUE")
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                        .foregroundStyle(BeatBeamPalette.brandCyan)
                    Spacer()
                    Text(isDynamicComposer ? (preview.dynamicComposerActive == true ? "ACTIVE" : "FALLBACK") : (preview.previewSource ?? "baseline"))
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                        .foregroundStyle(preview.dynamicComposerActive == true ? BeatBeamPalette.brandCyan : Color.secondary)
                }
                if isDynamicComposer {
                    Text("MUSICAL STATE")
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                        .foregroundStyle(.secondary)
                    Text(previewMusicalState(preview))
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .foregroundStyle(.secondary)
                    Text("RME MODIFIER · \(preview.event?.type ?? "None")")
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                        .foregroundStyle(.secondary)
                    Text("EVENT ENVELOPE · \(previewEventEnvelope(preview))")
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                        .foregroundStyle(.secondary)
                    Text("PREVIEW CUE")
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                        .foregroundStyle(BeatBeamPalette.brandCyan)
                }
                Text(preview.previewCue ?? previewFallbackCue(preview))
                    .font(.system(size: 11, weight: .semibold))
                    .lineLimit(2)
                if preview.dynamicCompositionApplied == true {
                    previewGroupRow("Moving", group: preview.fixtureGroupIntents?["moving"], primitives: preview.selectedPrimitives?["moving"])
                    previewGroupRow("PAR", group: preview.fixtureGroupIntents?["par"], primitives: preview.selectedPrimitives?["par"])
                    previewGroupRow("Wash", group: preview.fixtureGroupIntents?["wash"], primitives: preview.selectedPrimitives?["wash"])
                    if let dimensions = preview.changedDimensions, !dimensions.isEmpty {
                        Text("Changed: \(dimensions.joined(separator: ", "))")
                            .font(.system(size: 10, weight: .medium, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                } else if isDynamicComposer {
                    Text("Preview valt terug op baseline · \(preview.continuousStateReason ?? preview.contextReason ?? "ongeldige musical state")")
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
            }
            .padding(9)
            .background(BeatBeamPalette.raisedBackground)
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
    }

    private func previewMusicalState(_ preview: PreviewCompositionState) -> String {
        guard let state = preview.continuousMusicalState else {
            return "Unavailable"
        }
        let energy = state.relativeEnergy.map { String(format: "energy %.2f", $0) } ?? "energy —"
        let progress = state.sectionProgress.map { String(format: "progress %.0f%%", $0 * 100) } ?? "progress —"
        let recurrence = state.recurrenceStrength.map { String(format: "recurrence %.2f", $0) } ?? "recurrence —"
        return "\(energy) · \(progress) · \(recurrence)"
    }

    private func previewEventEnvelope(_ preview: PreviewCompositionState) -> String {
        guard let envelope = preview.eventEnvelope, envelope.active == true else {
            return "None"
        }
        let phase = envelope.phase?.capitalized ?? "Active"
        let progress = envelope.progress.map { String(format: "%.0f%%", $0 * 100) } ?? "—"
        if let beats = envelope.beatsSinceEvent, let total = envelope.totalBeats {
            return "\(phase) \(progress) · \(String(format: "%.2g", beats / 4))/\(String(format: "%.2g", total / 4)) bars"
        }
        return "\(phase) \(progress)"
    }

    @ViewBuilder
    private func previewGroupRow(_ title: String, group: PreviewFixtureGroupIntent?, primitives: [String: PreviewPrimitiveValue]?) -> some View {
        let primitiveText = (primitives ?? [:]).keys.sorted().map { key in
            "\(key) \(primitives?[key]?.displayText ?? "—")"
        }.joined(separator: " · ")
        let intensity = group?.intensity.map { String(format: "%.0f%%", $0 * 100) } ?? "—"
        let movement = group?.movementAmount.map { String(format: "%.0f%%", $0 * 100) } ?? "—"
        Text("\(title): \(primitiveText.isEmpty ? "neutral" : primitiveText) · intensity \(intensity) · movement \(movement)")
            .font(.system(size: 10, weight: .medium, design: .monospaced))
            .foregroundStyle(.secondary)
            .lineLimit(2)
    }

    private func previewFallbackCue(_ preview: PreviewCompositionState) -> String {
        let event = preview.event?.type ?? "geen actuele RME"
        let progress = preview.progress.map { String(format: "%.0f%%", $0 * 100) } ?? ""
        return "\(preview.mode ?? "BASELINE") • \(event) \(progress)"
    }

    var body: some View {
        PanelSurface(title: "Auto Show", compact: true) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .top, spacing: 12) {
                    TouchPadToggleButton(title: "Auto Show", systemImage: "wand.and.stars.inverse", isOn: autoShowBinding)
                        .frame(width: 130)

                    LazyVGrid(
                        columns: [
                            GridItem(.flexible(minimum: 96), spacing: 8),
                            GridItem(.flexible(minimum: 96), spacing: 8),
                            GridItem(.flexible(minimum: 96), spacing: 8),
                        ],
                        spacing: 8
                    ) {
                        ForEach(styles, id: \.value) { style in
                            AutoShowStyleButton(
                                title: style.title,
                                systemImage: style.icon,
                                value: style.value,
                                selection: styleBinding,
                                autoShowEnabled: model.autoShowEnabled
                            )
                        }
                    }
                }

                HStack(spacing: 10) {
                    MetricTile(title: "Mode", value: model.autoShowStyleLabel)
                    MetricTile(title: "Cue", value: model.autoShowCueText)
                    MetricTile(title: "Status", value: statusValue)
                }

                Picker("Preview Map", selection: previewRmeBinding) {
                    Text("Baseline").tag("BASELINE")
                    Text("RME enhanced").tag("RME_ENHANCED")
                    Text("Dynamic composer").tag("DYNAMIC_COMPOSER")
                }
                .pickerStyle(.segmented)
                Text("Alleen Preview Map · fysieke DMX blijft baseline")
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)

                Picker("Pulse Test (Preview only)", selection: previewPulseTestBinding) {
                    Text("Off").tag("OFF")
                    Text("Every Beat").tag("EVERY_BEAT")
                    Text("Half Time").tag("HALF_TIME")
                    Text("Bar Accent").tag("BAR_ACCENT")
                }
                .pickerStyle(.segmented)

                previewCompositionCard

                HStack(alignment: .center, spacing: 12) {
                    Button {
                        audiencePanFocusBinding.wrappedValue.toggle()
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: audiencePanFocusBinding.wrappedValue ? "scope" : "scope")
                                .font(.system(size: 14, weight: .semibold))
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Audience PAN")
                                    .font(.system(size: 11, weight: .semibold))
                                Text(audiencePanFocusBinding.wrappedValue ? "Focus on" : "Free")
                                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                                    .foregroundStyle(.secondary)
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 10)
                        .background(
                            audiencePanFocusBinding.wrappedValue
                                ? BeatBeamPalette.triggerActive
                                : BeatBeamPalette.raisedBackground
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .stroke(
                                    audiencePanFocusBinding.wrappedValue
                                        ? BeatBeamPalette.triggerOutline
                                        : BeatBeamPalette.border,
                                    lineWidth: 1
                                )
                        )
                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    .frame(width: 170)

                    Stepper(value: audiencePanMinBinding, in: 0...model.autoShowAudiencePanMax) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Min")
                                .font(.system(size: 11, weight: .semibold))
                            Text("\(model.autoShowAudiencePanMin)")
                                .font(.system(size: 13, weight: .bold, design: .monospaced))
                                .foregroundStyle(.primary)
                        }
                    }
                    .disabled(!audiencePanFocusBinding.wrappedValue)
                    .frame(maxWidth: .infinity)

                    Stepper(value: audiencePanMaxBinding, in: model.autoShowAudiencePanMin...255) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Max")
                                .font(.system(size: 11, weight: .semibold))
                            Text("\(model.autoShowAudiencePanMax)")
                                .font(.system(size: 13, weight: .bold, design: .monospaced))
                                .foregroundStyle(.primary)
                        }
                    }
                    .disabled(!audiencePanFocusBinding.wrappedValue)
                    .frame(maxWidth: .infinity)
                }

                HStack(spacing: 12) {
                    Stepper(value: audienceTurnPanMinBinding, in: 0...model.autoShowAudienceTurnPanMax) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Turn min")
                                .font(.system(size: 11, weight: .semibold))
                            Text("\(model.autoShowAudienceTurnPanMin)")
                                .font(.system(size: 13, weight: .bold, design: .monospaced))
                                .foregroundStyle(.primary)
                        }
                    }
                    .disabled(!audiencePanFocusBinding.wrappedValue)
                    .frame(maxWidth: .infinity)

                    Stepper(value: audienceTurnPanMaxBinding, in: model.autoShowAudienceTurnPanMin...255) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Turn max")
                                .font(.system(size: 11, weight: .semibold))
                            Text("\(model.autoShowAudienceTurnPanMax)")
                                .font(.system(size: 13, weight: .bold, design: .monospaced))
                                .foregroundStyle(.primary)
                        }
                    }
                    .disabled(!audiencePanFocusBinding.wrappedValue)
                    .frame(maxWidth: .infinity)

                    Stepper(value: audienceTiltSplitBinding, in: 0...255) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Tilt split")
                                .font(.system(size: 11, weight: .semibold))
                            Text("\(model.autoShowAudienceTiltSplit)")
                                .font(.system(size: 13, weight: .bold, design: .monospaced))
                                .foregroundStyle(.primary)
                        }
                    }
                    .disabled(!audiencePanFocusBinding.wrappedValue)
                    .frame(maxWidth: .infinity)
                }

                Text(model.autoShowDetailText)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
        }
    }
}

struct LiveOverrideColorButton: View {
    let title: String
    let value: String
    let selection: Binding<String>
    let swatch: Color
    let secondary: Color?

    private var isSelected: Bool {
        selection.wrappedValue == value
    }

    var body: some View {
        Button {
            selection.wrappedValue = value
        } label: {
            VStack(spacing: 8) {
                Group {
                    if value == "none" {
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(BeatBeamPalette.mutedBackground)
                            .overlay(
                                Text("AUTO")
                                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                                    .foregroundStyle(.secondary)
                            )
                    } else if let secondary {
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(
                                LinearGradient(
                                    colors: [swatch, secondary, Color(red: 0.18, green: 0.92, blue: 0.38)],
                                    startPoint: .leading,
                                    endPoint: .trailing
                                )
                            )
                    } else {
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(swatch)
                    }
                }
                .frame(height: 28)
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(Color.white.opacity(value == "white" ? 0.18 : 0.08), lineWidth: 1)
                )

                Text(title)
                    .font(.system(size: 11, weight: .semibold))
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, minHeight: 58)
            .padding(.horizontal, 6)
            .background(isSelected ? BeatBeamPalette.triggerActive : BeatBeamPalette.raisedBackground)
            .foregroundStyle(isSelected ? Color.white : Color.primary)
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(isSelected ? BeatBeamPalette.triggerOutline : BeatBeamPalette.border, lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}

struct MapWorkspaceView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.openWindow) private var openWindow

    private let workspaceMinimumHeight: CGFloat = 660
    @State private var inspectorWidth: CGFloat

    init() {
        let storedWidth = UserDefaults.standard.object(forKey: stageMapInspectorWidthDefaultsKey) as? Double
        _inspectorWidth = State(initialValue: CGFloat(storedWidth ?? 340))
    }

    var body: some View {
        PanelSurface(title: "Stage Map", compact: true) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Place fixtures and calibrate one moving head at a time.")
                            .font(.system(size: 12, weight: .semibold))
                        Text("Map editing is preview-only. Only explicit Physical Aim or Move actions lease bounded Pan/Tilt; all other show dimensions remain untouched.")
                            .font(.system(size: 10, weight: .medium, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Open Preview") {
                        openWindow(id: "map-preview")
                    }
                    .buttonStyle(.borderedProminent)
                }

                StageMapResizableSplitView(
                    inspectorWidth: $inspectorWidth,
                    left: stageMapWorkSurface,
                    right: stageMapSidebar
                )
                .frame(minHeight: workspaceMinimumHeight, alignment: .top)
                .onChange(of: inspectorWidth) { _, width in
                    UserDefaults.standard.set(Double(width), forKey: stageMapInspectorWidthDefaultsKey)
                }
            }
        }
    }

    private var stageMapWorkSurface: some View {
        StageProjectionDeckView(
            showControls: true,
            topInteractive: true,
            showSelection: true,
            showAnchorLabels: true,
            selectionMode: .editor,
            singlePrimaryView: true
        )
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(BeatBeamPalette.mutedBackground.opacity(0.18))
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    private var stageMapSidebar: some View {
        ScrollViewReader { proxy in
            ScrollView(.vertical) {
                Color.clear
                    .frame(height: 1)
                    .id("stage-map-sidebar-top")
                LazyVStack(spacing: 10) {
                    VenueGeometryPanel()
                    FixtureVenueCalibrationPanel()
                    VenueTargetTestPanel()
                    MovementLabPanel()
                }
                .frame(maxWidth: .infinity, alignment: .topLeading)
                .padding(.trailing, 2)
            }
            .scrollIndicators(.visible)
            .onAppear {
                proxy.scrollTo("stage-map-sidebar-top", anchor: .top)
            }
        }
        .padding(1)
        .background(BeatBeamPalette.mutedBackground.opacity(0.22))
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

private struct StageMapResizableSplitView<Left: View, Right: View>: NSViewRepresentable {
    @EnvironmentObject private var model: AppModel
    @Binding var inspectorWidth: CGFloat
    let left: Left
    let right: Right

    private let mapMinimumWidth: CGFloat = 620
    private let inspectorMinimumWidth: CGFloat = 290
    private let inspectorMaximumWidth: CGFloat = 520

    func makeCoordinator() -> Coordinator {
        Coordinator(
            inspectorWidth: $inspectorWidth,
            mapMinimumWidth: mapMinimumWidth,
            inspectorMinimumWidth: inspectorMinimumWidth,
            inspectorMaximumWidth: inspectorMaximumWidth
        )
    }

    func makeNSView(context: Context) -> NSSplitView {
        let splitView = NSSplitView()
        splitView.isVertical = true
        splitView.dividerStyle = .thin
        splitView.delegate = context.coordinator

        let mapHost = NSHostingView(rootView: AnyView(left.environmentObject(model)))
        let inspectorHost = NSHostingView(rootView: AnyView(right.environmentObject(model)))
        mapHost.translatesAutoresizingMaskIntoConstraints = true
        inspectorHost.translatesAutoresizingMaskIntoConstraints = true
        splitView.addArrangedSubview(mapHost)
        splitView.addArrangedSubview(inspectorHost)
        context.coordinator.applyInitialInspectorWidth(inspectorWidth, to: splitView)
        return splitView
    }

    func updateNSView(_ splitView: NSSplitView, context: Context) {
        guard splitView.subviews.count == 2,
              let mapHost = splitView.subviews[0] as? NSHostingView<AnyView>,
              let inspectorHost = splitView.subviews[1] as? NSHostingView<AnyView> else { return }
        mapHost.rootView = AnyView(left.environmentObject(model))
        inspectorHost.rootView = AnyView(right.environmentObject(model))
    }

    final class Coordinator: NSObject, NSSplitViewDelegate {
        private var inspectorWidth: Binding<CGFloat>
        private let mapMinimumWidth: CGFloat
        private let inspectorMinimumWidth: CGFloat
        private let inspectorMaximumWidth: CGFloat
        private var appliedInitialWidth = false

        init(
            inspectorWidth: Binding<CGFloat>,
            mapMinimumWidth: CGFloat,
            inspectorMinimumWidth: CGFloat,
            inspectorMaximumWidth: CGFloat
        ) {
            self.inspectorWidth = inspectorWidth
            self.mapMinimumWidth = mapMinimumWidth
            self.inspectorMinimumWidth = inspectorMinimumWidth
            self.inspectorMaximumWidth = inspectorMaximumWidth
        }

        func applyInitialInspectorWidth(_ requestedWidth: CGFloat, to splitView: NSSplitView) {
            guard !appliedInitialWidth else { return }
            appliedInitialWidth = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self, weak splitView] in
                guard let self, let splitView else { return }
                self.applyInspectorWidth(requestedWidth, to: splitView)
            }
        }

        private func applyInspectorWidth(_ requestedWidth: CGFloat, to splitView: NSSplitView) {
            let dividerWidth = splitView.dividerThickness
            let availableWidth = max(0, splitView.bounds.width - dividerWidth)
            guard availableWidth > 0 else { return }
            let maximumInspectorWidth = min(
                inspectorMaximumWidth,
                max(inspectorMinimumWidth, availableWidth - mapMinimumWidth)
            )
            let resolvedInspectorWidth = min(max(requestedWidth, inspectorMinimumWidth), maximumInspectorWidth)
            splitView.setPosition(max(0, availableWidth - resolvedInspectorWidth), ofDividerAt: 0)
        }

        func splitViewDidResizeSubviews(_ notification: Notification) {
            guard let splitView = notification.object as? NSSplitView,
                  splitView.subviews.count == 2 else { return }
            let width = splitView.subviews[1].frame.width
            guard width > 0 else { return }
            DispatchQueue.main.async { [inspectorWidth] in
                inspectorWidth.wrappedValue = width
            }
        }

        func splitView(_ splitView: NSSplitView, constrainMinCoordinate proposedMinimumPosition: CGFloat, ofSubviewAt dividerIndex: Int) -> CGFloat {
            let availableWidth = max(0, splitView.bounds.width - splitView.dividerThickness)
            let maximumInspectorWidth = min(
                inspectorMaximumWidth,
                max(inspectorMinimumWidth, availableWidth - mapMinimumWidth)
            )
            return max(mapMinimumWidth, availableWidth - maximumInspectorWidth)
        }

        func splitView(_ splitView: NSSplitView, constrainMaxCoordinate proposedMaximumPosition: CGFloat, ofSubviewAt dividerIndex: Int) -> CGFloat {
            let availableWidth = max(0, splitView.bounds.width - splitView.dividerThickness)
            let minimumMapWidth = min(mapMinimumWidth, max(0, availableWidth - inspectorMinimumWidth))
            return max(minimumMapWidth, availableWidth - inspectorMinimumWidth)
        }
    }
}

struct VenueTargetTestPanel: View {
    @EnvironmentObject private var model: AppModel
    private let zones = ["NEAR", "MID", "FAR", "REAR"]
    private let positions = ["LEFT", "CENTER", "RIGHT"]

    var body: some View {
        PanelSurface(title: "Target Test", compact: true) {
            VStack(alignment: .leading, spacing: 10) {
                Text("Physical PAN / TILT only. Colour, dimmer, effects, fog and master stay under the normal renderer.")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                selectorRow(title: "ZONE", values: zones, selected: model.selectedVenueTargetZone) {
                    model.selectVenueTargetZone($0)
                }
                selectorRow(title: "POSITION", values: positions, selected: model.selectedVenueTargetPosition) {
                    model.selectVenueTargetPosition($0)
                }
                verticalLayerRow
                if let ceiling = model.venueTargetVerticalLayerState("CEILING"), !ceiling.available {
                    Text("CEILING UNAVAILABLE • \(ceiling.reason ?? "CEILING_HEIGHT_UNSET")")
                        .font(.system(size: 8, weight: .bold, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
                HStack(spacing: 8) {
                    Button(model.calibrationTestInFlightSlotID == model.selectedSlotID ? "TESTING…" : "TEST ALL IN PREVIEW") {
                        model.testAllMovingHeadsInPreview()
                    }
                    .buttonStyle(.bordered)
                    .disabled(model.calibrationTestInFlightSlotID != nil)
                    if model.venueTargetTestState?.active == true {
                        Button("RELEASE TEST") { model.releaseVenueTargetTest() }
                            .buttonStyle(.bordered)
                    } else {
                        Button(model.venueTargetTestInFlight ? "MOVING…" : "MOVE TO TARGET") {
                            model.moveSelectedFixtureToVenueTarget()
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.venueTargetTestInFlight || model.previewVenueTargetResultSet?.physicalReady != true)
                    }
                    Spacer()
                    Text(model.venueTargetTestState?.active == true ? "ACTIVE" : "READY")
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                        .foregroundStyle(model.venueTargetTestState?.active == true ? BeatBeamPalette.brandCyan : .secondary)
                }
                Text(model.venueTargetTestStatusText)
                    .font(.system(size: 9, weight: .semibold, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let resultSet = displayedResultSet {
                    Text("\(resultSet.targetedCount)/\(resultSet.candidateCount) TARGETED • \(resultSet.skippedCount) SKIPPED")
                        .font(.system(size: 9, weight: .medium, design: .monospaced))
                        .foregroundStyle(resultSet.targetedCount > 0 ? BeatBeamPalette.brandCyan : BeatBeamPalette.brandAmber)
                        .fixedSize(horizontal: false, vertical: true)
                    DisclosureGroup("FIXTURE DETAILS") {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(resultSet.results) { item in
                                HStack(spacing: 6) {
                                    Circle()
                                        .fill(item.classification == "TARGETABLE" ? BeatBeamPalette.brandCyan : BeatBeamPalette.brandAmber)
                                        .frame(width: 6, height: 6)
                                    Text(item.label)
                                        .lineLimit(1)
                                    Spacer()
                                    Text(item.classification.replacingOccurrences(of: "SKIPPED_", with: "SKIP "))
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                        .font(.system(size: 8, weight: .semibold, design: .monospaced))
                        .padding(.top, 4)
                    }
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                }
            }
        }
    }

    private var displayedResultSet: VenueTargetResultSetState? {
        model.venueTargetTestState?.resultSet ?? model.previewVenueTargetResultSet
    }

    private var verticalLayerRow: some View {
        HStack(spacing: 6) {
            Text("HEIGHT")
                .font(.system(size: 8, weight: .bold, design: .monospaced))
                .foregroundStyle(.secondary)
                .frame(width: 48, alignment: .leading)
            ForEach(["FLOOR", "NORMAL", "CEILING"] as [String], id: \.self) { layer in
                let available = model.venueTargetVerticalLayerState(layer)?.available ?? (layer != "CEILING")
                let selected = model.selectedVenueTargetVerticalLayer == layer
                Button(layer) { model.selectVenueTargetVerticalLayer(layer) }
                    .buttonStyle(.bordered)
                    .tint(selected ? BeatBeamPalette.brandCyan : nil)
                    .disabled((model.venueTargetTestState?.active == true && !selected) || !available)
                    .frame(maxWidth: .infinity)
            }
        }
    }

    @ViewBuilder
    private func selectorRow(
        title: String,
        values: [String],
        selected: String,
        action: @escaping (String) -> Void
    ) -> some View {
        HStack(spacing: 6) {
            Text(title)
                .font(.system(size: 8, weight: .bold, design: .monospaced))
                .foregroundStyle(.secondary)
                .frame(width: 48, alignment: .leading)
            ForEach(values, id: \.self) { value in
                selectorButton(value, selected: selected, action: action)
            }
        }
    }

    @ViewBuilder
    private func selectorButton(_ value: String, selected: String, action: @escaping (String) -> Void) -> some View {
        let disabled = model.venueTargetTestState?.active == true && value != selected
        if value == selected {
            Button(value) { action(value) }
                .buttonStyle(.borderedProminent)
                .disabled(disabled)
                .frame(maxWidth: .infinity)
        } else {
            Button(value) { action(value) }
                .buttonStyle(.bordered)
                .disabled(disabled)
                .frame(maxWidth: .infinity)
        }
    }
}

struct MovementLabPanel: View {
    @EnvironmentObject private var model: AppModel
    private let effects = [
        "slow_audience_circle", "fast_audience_circle", "slow_audience_oval",
        "fast_audience_figure_8", "fast_audience_sweep", "build_rising_sweep",
        "build_narrow_to_wide_fan", "drop_crossing_beams", "slow_random_searchlight",
        // Existing production V3 identities. Keep this picker as an explicit
        // audition inventory: its values travel unchanged to the production
        // Movement Lab API and V3 recipe catalog.
        "full_sphere_explode", "floor_hold_explode", "rear_hold_split",
        "full_sphere_cannon", "floor_forward_cannon", "dome_sweep_3d",
        "floor_forward_sweep", "forward_rear_arc", "cross_3d",
        "volumetric_orbit", "volumetric_figure_8", "energy_scatter", "fan_3d",
        "baseline_phrase_motion"
    ]
    private let sections = ["break", "verse", "build", "chorus", "drop"]

    var body: some View {
        PanelSurface(title: "Movement Lab", compact: true) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Production audition • world-space V3 recipes; unmigrated effects show the V2 world-native fallback.")
                    .font(.system(size: 9, weight: .medium))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Picker("EFFECT", selection: $model.movementLabEffectID) {
                    ForEach(effects, id: \.self) { effect in Text(effect.replacingOccurrences(of: "_", with: " ")).tag(effect) }
                }
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                HStack(spacing: 5) {
                    ForEach(["slow_audience_circle", "fast_audience_sweep", "build_narrow_to_wide_fan", "drop_crossing_beams"], id: \.self) { effect in
                        Button(effect == "slow_audience_circle" ? "SLOW" : effect == "fast_audience_sweep" ? "FAST" : effect == "build_narrow_to_wide_fan" ? "FAN" : "DROP") { model.movementLabEffectID = effect }
                            .buttonStyle(.bordered)
                            .tint(model.movementLabEffectID == effect ? BeatBeamPalette.brandCyan : nil)
                            .frame(maxWidth: .infinity)
                    }
                }
                HStack(spacing: 5) {
                    Text("CONTEXT").font(.system(size: 8, weight: .bold, design: .monospaced)).foregroundStyle(.secondary)
                    ForEach(sections, id: \.self) { section in
                        Button(section.uppercased()) { model.movementLabSection = section }
                            .buttonStyle(.bordered)
                            .tint(model.movementLabSection == section ? BeatBeamPalette.brandCyan : nil)
                            .font(.system(size: 8, weight: .bold, design: .monospaced))
                    }
                }
                HStack(spacing: 8) {
                    Button("‹ VAR") { model.movementLabVariation = max(0, model.movementLabVariation - 1) }
                        .buttonStyle(.bordered)
                    Text("V\(model.movementLabVariation)").font(.system(size: 9, weight: .bold, design: .monospaced))
                    Button("VAR ›") { model.movementLabVariation = min(31, model.movementLabVariation + 1) }
                        .buttonStyle(.bordered)
                    Spacer()
                    Button(model.movementLabState?.active == true ? "STOP" : "PLAY") {
                        if model.movementLabState?.active == true { model.stopMovementLab() } else { model.playMovementLab() }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.movementLabInFlight)
                }
                HStack(spacing: 5) {
                    Text(model.movementLabState?.active == true ? "ACTIVE" : "READY")
                        .font(.system(size: 9, weight: .bold, design: .monospaced))
                        .foregroundStyle(model.movementLabState?.active == true ? BeatBeamPalette.brandCyan : .secondary)
                    Text("• \(model.movementLabState?.engine ?? "V3")")
                    Text("• \(model.movementLabState?.route ?? "PRODUCTION READY")")
                }
                .font(.system(size: 9, weight: .semibold, design: .monospaced))
                .foregroundStyle(.secondary)
            }
        }
    }
}

struct VenueGeometryPanel: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        PanelSurface(title: "Venue Geometry", compact: true) {
            VStack(alignment: .leading, spacing: 9) {
                Text("Enter measured physical dimensions. Empty fields remain UNSET; BeatBeam never guesses scale.")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 10) {
                    geometryField("WIDTH", unit: "m", text: $model.venueWidthMetersText)
                    geometryField("AUDIENCE DEPTH", unit: "m", text: $model.venueForwardDepthMetersText)
                }
                HStack(spacing: 10) {
                    geometryField("REAR DEPTH", unit: "m", text: $model.venueRearDepthMetersText)
                    geometryField("AUDIENCE HEIGHT", unit: "m", text: $model.audienceTargetHeightMetersText)
                }
                HStack(spacing: 10) {
                    geometryField("CEILING HEIGHT", unit: "m", text: $model.ceilingHeightMetersText)
                    Text("UNSET keeps CEILING targeting unavailable.")
                        .font(.system(size: 9, weight: .medium))
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                HStack(spacing: 8) {
                    Text(model.venueSpace?.venueGeometry?.status ?? "MISSING_VENUE_SCALE")
                        .font(.system(size: 9, weight: .bold, design: .monospaced))
                        .foregroundStyle(geometryReady ? BeatBeamPalette.brandCyan : BeatBeamPalette.brandAmber)
                    Spacer()
                    Button(model.venueGeometrySaveInFlight ? "SAVING…" : "SAVE GEOMETRY") {
                        model.saveVenueGeometry()
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.venueGeometrySaveInFlight)
                }
            }
        }
    }

    private var geometryReady: Bool {
        model.venueSpace?.venueGeometry?.status == "READY"
    }

    private func geometryField(_ label: String, unit: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.system(size: 9, weight: .bold, design: .monospaced))
                .foregroundStyle(.secondary)
            HStack(spacing: 5) {
                TextField("UNSET", text: text)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                Text(unit)
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity)
    }
}

struct FixtureMapAssignmentPanel: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        PanelSurface(title: "Assignments", compact: true) {
            VStack(alignment: .leading, spacing: 10) {
                Text("Assign each fixture to a stage position.")
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(.secondary)

                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(model.slotEditors) { editor in
                            VStack(alignment: .leading, spacing: 6) {
                                HStack(spacing: 8) {
                                    Circle()
                                        .fill(previewColor(for: editor.id))
                                        .frame(width: 10, height: 10)
                                    Text(editor.label)
                                        .font(.system(size: 13, weight: .semibold))
                                    Spacer()
                                    Text(editor.rangeText)
                                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                }

                                Picker("Position", selection: Binding(
                                    get: { model.anchorAssignment(for: editor.id) },
                                    set: { model.assignAnchor($0, to: editor.id) }
                                )) {
                                    Text("Unassigned").tag("")
                                    ForEach(StageAnchor.allCases) { anchor in
                                        Text("\(anchor.title) • \(anchor.placementGroup)").tag(anchor.rawValue)
                                    }
                                }
                                .pickerStyle(.menu)

                                if editor.supportsPan && editor.supportsTilt {
                                    HStack(spacing: 8) {
                                        Button("Select") {
                                            model.selectSlot(editor.id)
                                        }
                                        .buttonStyle(.bordered)
                                        Spacer()
                                        Text(model.calibrationState(for: editor.id)?.status ?? "UNCALIBRATED")
                                            .font(.system(size: 9, weight: .bold, design: .monospaced))
                                            .foregroundStyle(
                                                model.calibrationState(for: editor.id)?.status == "VALID"
                                                    ? BeatBeamPalette.brandCyan
                                                    : BeatBeamPalette.brandAmber
                                            )
                                    }
                                }
                            }
                            .padding(10)
                            .background(BeatBeamPalette.raisedBackground)
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                        }
                    }
                }
            }
        }
        .frame(maxHeight: .infinity, alignment: .top)
    }

    private func previewColor(for slotID: String) -> Color {
        guard let preview = model.presentedSlotPreviews[slotID], preview.enabled else {
            return Color.white.opacity(0.12)
        }
        return slotPreviewColor(preview)
    }
}

struct FixtureVenueCalibrationPanel: View {
    @EnvironmentObject private var model: AppModel
    @State private var showAimResetConfirmation = false
    @State private var showAxisV2ResetConfirmation = false
    @State private var axisV2SelectedAxis = "TILT"
    @State private var axisV2PanSampleIndex = 0
    @State private var axisV2TiltSampleIndex = 0
    @State private var axisV2MeasuredPan = 0.0
    @State private var axisV2MeasuredTilt = 0.0
    @State private var showLegacyAim = false
    @State private var showAxisV2Details = false
    @State private var physicalTiltMinimumText = ""
    @State private var physicalTiltCenterText = ""
    @State private var physicalTiltMaximumText = ""

    var body: some View {
        PanelSurface(title: "Selected Fixture", compact: true) {
            if let editor = selectedMovingFixture {
                let world = model.worldPosition(for: editor.id)
                let basis = venueOrientationBasis(for: world)
                let state = model.calibrationState(for: editor.id)
                VStack(alignment: .leading, spacing: 9) {
                    HStack {
                        Text(editor.label)
                            .font(.system(size: 12, weight: .semibold))
                        Spacer()
                        Text(state?.status ?? "UNCALIBRATED")
                            .font(.system(size: 10, weight: .bold, design: .monospaced))
                            .foregroundStyle(state?.status == "VALID" ? BeatBeamPalette.brandCyan : BeatBeamPalette.brandAmber)
                    }
                    HStack(spacing: 7) {
                        positionField("X", axis: "x", slotID: editor.id)
                        positionField("Y", axis: "y", slotID: editor.id)
                        positionField("Z", axis: "z", slotID: editor.id)
                    }
                    Text("X − LEFT / + RIGHT  •  Y + AUDIENCE / − REAR  •  exact to 0.01 m")
                        .font(.system(size: 8, weight: .semibold, design: .monospaced))
                        .foregroundStyle(.secondary)
                    calibrationLine("POSITION SOURCE", state?.positionSource ?? "LOCAL DRAFT")
                    calibrationLine("FORWARD", vectorText(basis.forward))
                    calibrationLine("UP", vectorText(basis.up))
                    calibrationLine("RIGHT (derived)", vectorText(basis.right))
                    if let capabilities = state?.capabilities {
                        calibrationLine(
                            "PAN / TILT",
                            "\(Int((capabilities.panRangeDegrees ?? 0).rounded()))° / \(Int((capabilities.tiltRangeDegrees ?? 0).rounded()))°"
                        )
                    }
                    physicalMovementLimits(state: state)
                    if model.isFixtureCalibrationMode {
                        calibrationGuide
                    }
                    HStack {
                        if model.isFixtureCalibrationMode {
                            Label("CALIBRATION ACTIVE", systemImage: "checkmark.circle.fill")
                                .font(.system(size: 10, weight: .bold, design: .monospaced))
                                .foregroundStyle(BeatBeamPalette.brandCyan)
                                .padding(.horizontal, 9)
                                .padding(.vertical, 7)
                                .background(BeatBeamPalette.brandCyan.opacity(0.12))
                                .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
                        } else {
                            Button("CALIBRATE SELECTED") {
                                model.startFixtureCalibration()
                            }
                            .buttonStyle(.borderedProminent)
                        }
                        Button {
                            model.testAudienceCenterForSelectedFixture()
                        } label: {
                            if model.calibrationTestInFlightSlotID == editor.id {
                                Label("TESTING…", systemImage: "clock.arrow.circlepath")
                            } else {
                                Label("TEST AUDIENCE CENTER", systemImage: "scope")
                            }
                        }
                        .buttonStyle(.bordered)
                        .disabled(model.calibrationTestInFlightSlotID != nil)
                    }
                    .disabled(model.calibrationSaveInFlight)
                    if model.calibrationTestSlotID == editor.id {
                        let result = model.audienceCenterTestResult(for: editor.id)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(
                                model.calibrationTestInFlightSlotID == editor.id
                                    ? "Resolving current draft…"
                                    : audienceTestText(result)
                            )
                            .font(.system(size: 10, weight: .semibold, design: .monospaced))
                            .foregroundStyle(result?.status == "RESOLVED" ? BeatBeamPalette.brandCyan : BeatBeamPalette.brandAmber)
                            Text("DRAFT DIAGNOSTIC • no config save • no DMX movement")
                                .font(.system(size: 9, weight: .medium, design: .monospaced))
                                .foregroundStyle(.secondary)
                            if let result {
                                if let fixture = result.fixtureXyzM, let target = result.targetXyzM {
                                    Text("FIXTURE \(physicalPointText(fixture))  TARGET \(physicalPointText(target))")
                                        .font(.system(size: 9, weight: .medium, design: .monospaced))
                                        .foregroundStyle(.secondary)
                                }
                                if let horizontal = result.horizontalDistanceM,
                                   let vertical = result.verticalDeltaM,
                                   let direct = result.directDistanceM {
                                    Text(String(format: "H %.2f m  ΔZ %.2f m  DIRECT %.2f m", horizontal, vertical, direct))
                                        .font(.system(size: 9, weight: .medium, design: .monospaced))
                                        .foregroundStyle(.secondary)
                                }
                                if let output = result.predictedOutput {
                                    Text(
                                        "PREDICTED DMX • PAN \(output.pan)"
                                            + (output.panFine.map { "/\($0)" } ?? "")
                                            + " • TILT \(output.tilt)"
                                            + (output.tiltFine.map { "/\($0)" } ?? "")
                                    )
                                    .font(.system(size: 9, weight: .medium, design: .monospaced))
                                    .foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    Divider()
                    physicalAxisMappingV2(editor: editor, state: state)
                    DisclosureGroup("LEGACY / EXPERIMENTAL PHYSICAL AIM", isExpanded: $showLegacyAim) {
                        physicalAimCalibration(editor: editor, state: state)
                            .padding(.top, 6)
                    }
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                }
                .onAppear { seedPhysicalTiltLimits(from: state) }
                .onChange(of: editor.id) { seedPhysicalTiltLimits(from: state) }
                .onChange(of: state?.capabilities.physicalTiltLimitsSource) { seedPhysicalTiltLimits(from: state) }
            } else {
                Text("Select one moving head to calibrate Position, Forward and Up.")
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
        }
        .alert("Reset physical aim calibration?", isPresented: $showAimResetConfirmation) {
            Button("Cancel", role: .cancel) {}
            Button("Reset Aim Calibration", role: .destructive) { model.resetAimCalibration() }
        } message: {
            Text("This removes only the selected fixture's physical aim anchors and model. Venue Position, Forward and Up remain unchanged.")
        }
        .alert("Fixture remounted / reset Axis Mapping V2?", isPresented: $showAxisV2ResetConfirmation) {
            Button("Cancel", role: .cancel) {}
            Button("Reset Axis Mapping V2", role: .destructive) { model.resetAxisMappingV2() }
        } message: {
            Text("This removes only this fixture's measured V2 motor-axis samples and activation. Venue calibration and legacy Physical Aim evidence remain intact.")
        }
    }

    @ViewBuilder
    private func physicalMovementLimits(state: VenueFixtureCalibrationState?) -> some View {
        let capabilities = state?.capabilities
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("PHYSICAL MOVEMENT LIMITS")
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(BeatBeamPalette.brandCyan)
                Spacer()
                Text(capabilities?.physicalTiltLimitsSource == "FIXTURE_OVERRIDE" ? "FIXTURE OVERRIDE" : "PROFILE DEFAULT")
                    .font(.system(size: 8, weight: .bold, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
            Text("Local mechanical Tilt travel. Axis Mapping V2 separately determines the installed world direction.")
                .font(.system(size: 9, weight: .medium))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 7) {
                physicalTiltField("TILT MIN", text: $physicalTiltMinimumText)
                physicalTiltField("TILT CENTER", text: $physicalTiltCenterText)
                physicalTiltField("TILT MAX", text: $physicalTiltMaximumText)
            }
            HStack {
                Text("At least 1° precision • MIN < CENTER < MAX")
                    .font(.system(size: 8, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
                Spacer()
                Button(model.calibrationSaveInFlight ? "SAVING…" : "SAVE LIMITS") {
                    model.savePhysicalTiltLimits(
                        minimumText: physicalTiltMinimumText,
                        centerText: physicalTiltCenterText,
                        maximumText: physicalTiltMaximumText
                    )
                }
                .buttonStyle(.bordered)
                .disabled(model.calibrationSaveInFlight)
            }
        }
        .padding(8)
        .background(BeatBeamPalette.mutedBackground.opacity(0.62))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private func physicalTiltField(_ label: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label).font(.system(size: 8, weight: .bold, design: .monospaced)).foregroundStyle(.secondary)
            HStack(spacing: 3) {
                TextField("—", text: text)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                Text("°").font(.system(size: 10, weight: .bold, design: .monospaced)).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func seedPhysicalTiltLimits(from state: VenueFixtureCalibrationState?) {
        guard let capabilities = state?.capabilities,
              let minimum = capabilities.physicalTiltMinDeg,
              let center = capabilities.physicalTiltCenterDeg,
              let maximum = capabilities.physicalTiltMaxDeg
        else { return }
        physicalTiltMinimumText = String(format: "%.1f", minimum)
        physicalTiltCenterText = String(format: "%.1f", center)
        physicalTiltMaximumText = String(format: "%.1f", maximum)
    }

    @ViewBuilder
    private func physicalAxisMappingV2(editor: SlotEditor, state: VenueFixtureCalibrationState?) -> some View {
        let mapping = state?.axisMappingV2
        let active = model.venueTargetTestState?.selectedFixtureID == editor.id
            && ["PHYSICAL_AXIS_MAPPING_V2", "AXIS_MAPPING_V2_VALIDATION"].contains(model.venueTargetTestState?.mode ?? "")
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("PHYSICAL AXIS MAPPING")
                        .font(.system(size: 11, weight: .bold, design: .monospaced))
                        .foregroundStyle(BeatBeamPalette.brandCyan)
                    Text("Known raw motor position → measured real beam direction")
                        .font(.system(size: 9, weight: .medium))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Text(mapping?.status ?? "UNCALIBRATED")
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                    .foregroundStyle(mapping?.status == "ACTIVE" ? BeatBeamPalette.brandCyan : BeatBeamPalette.brandAmber)
            }
            HStack(spacing: 8) {
                calibrationLine("PAN", "\(mapping?.panSampleCount ?? 0)/\(mapping?.panRequiredCount ?? 7)")
                Divider().frame(height: 18)
                calibrationLine("TILT", "\(mapping?.tiltSampleCount ?? 0)/\(mapping?.tiltRequiredCount ?? 5)")
                Divider().frame(height: 18)
                calibrationLine("MAPPING", mapping?.movementMappingAuthority ?? "LEGACY / UNCALIBRATED")
            }

            axisV2TiltFirstFlow(mapping: mapping, active: active)

            if mapping?.workflowPhase == "PAN" {
                axisV2PanWizard(editor: editor, mapping: mapping, active: active)
            } else if mapping?.workflowPhase == "TILT" {
                axisV2TiltWizard(editor: editor, mapping: mapping, active: active)
            }

            DisclosureGroup("RECOVERY / MANUAL SAMPLE") {
                VStack(alignment: .leading, spacing: 7) {
                    Picker("Axis", selection: $axisV2SelectedAxis) {
                        Text("TILT").tag("TILT")
                        Text("PAN").tag("PAN")
                    }
                    .pickerStyle(.segmented)
                    if axisV2SelectedAxis == "PAN" {
                        Picker("Sample", selection: $axisV2PanSampleIndex) {
                            ForEach(0..<7, id: \.self) { Text("\($0 + 1)").tag($0) }
                        }
                        Button("MOVE SELECTED EXACT PAN RAW") {
                            model.moveAxisMappingV2Sample(axis: "PAN", index: axisV2PanSampleIndex)
                        }
                        .disabled(model.axisMappingV2InFlight || mapping?.panStartAllowed != true)
                    } else {
                        Picker("Sample", selection: $axisV2TiltSampleIndex) {
                            ForEach(0..<5, id: \.self) { Text("\($0 + 1)").tag($0) }
                        }
                        Button("MOVE SELECTED EXACT TILT RAW") {
                            model.moveAxisMappingV2Sample(axis: "TILT", index: axisV2TiltSampleIndex)
                        }
                        .disabled(model.axisMappingV2InFlight || mapping?.tiltStartAllowed != true)
                    }
                }
                .buttonStyle(.bordered)
                .padding(.top, 5)
            }
            .font(.system(size: 9, weight: .bold, design: .monospaced))

            if let modelState = mapping?.model, modelState.status == "CALIBRATED_CANDIDATE" || ["CALIBRATED_CANDIDATE", "VALIDATED", "VALIDATION_FAILED", "ACTIVE"].contains(mapping?.status ?? "") {
                Divider()
                Text("OUT-OF-SAMPLE VENUE VALIDATION • DO NOT ADJUST")
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                    .foregroundStyle(.secondary)
                ForEach([("NEAR CENTER", "AUDIENCE_NEAR_CENTER"), ("MID LEFT", "AUDIENCE_MID_LEFT"), ("FAR RIGHT", "AUDIENCE_FAR_RIGHT")], id: \.1) { label, target in
                    HStack {
                        Image(systemName: mapping?.validations?[target]?.result == "PASS" ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(mapping?.validations?[target]?.result == "PASS" ? BeatBeamPalette.brandCyan : .secondary)
                        Text(label).font(.system(size: 10, weight: .semibold, design: .monospaced))
                        Spacer()
                        Button("MOVE") { model.moveAxisMappingV2Validation(target: target) }
                            .buttonStyle(.borderedProminent)
                            .disabled(active || model.axisMappingV2InFlight)
                    }
                }
                if model.venueTargetTestState?.mode == "AXIS_MAPPING_V2_VALIDATION" {
                    HStack {
                        Button("RELEASE") { model.releaseVenueTargetTest() }.buttonStyle(.bordered)
                        Spacer()
                        Button("FAIL") { model.recordAxisMappingV2Validation("FAIL") }.buttonStyle(.bordered)
                        Button("PASS") { model.recordAxisMappingV2Validation("PASS") }.buttonStyle(.borderedProminent)
                    }
                }
            }

            if mapping?.status == "VALIDATED" {
                Button("ACTIVATE AXIS MAPPING V2") { model.activateAxisMappingV2() }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .frame(maxWidth: .infinity)
            }
            if mapping?.status == "ACTIVE" {
                Label("Movement Mapping: AXIS MAPPING V2 — ACTIVE", systemImage: "checkmark.seal.fill")
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(BeatBeamPalette.brandCyan)
            }
            if let pan = mapping?.model?.pan, let tilt = mapping?.model?.tilt {
                DisclosureGroup("DETAILS", isExpanded: $showAxisV2Details) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(String(format: "PAN • %@ • %.1f° physical coverage • %d points", pan.direction ?? "—", pan.coverageDegrees ?? 0, pan.points?.count ?? 0))
                        Text(String(format: "TILT • %@ • %.1f° physical coverage • %d points", tilt.direction ?? "—", tilt.coverageDegrees ?? 0, tilt.points?.count ?? 0))
                        Text("Final trace is exposed through desired world direction, chosen raw Pan/Tilt, final rendered bytes and rendered_motion mapping authority.")
                    }
                    .font(.system(size: 9, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .padding(.top, 4)
                }
                .font(.system(size: 9, weight: .bold, design: .monospaced))
            }
            HStack {
                Text("Legacy Aim: \(mapping?.legacyPhysicalAimStatus ?? "LEGACY_AVAILABLE")")
                    .font(.system(size: 9, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
                Spacer()
                Button("FIXTURE REMOUNTED / RESET…", role: .destructive) { showAxisV2ResetConfirmation = true }
                    .buttonStyle(.bordered)
                    .disabled(active || ((mapping?.panSampleCount ?? 0) + (mapping?.tiltSampleCount ?? 0) == 0))
            }
        }
        .padding(10)
        .background(BeatBeamPalette.mutedBackground.opacity(0.72))
        .overlay(RoundedRectangle(cornerRadius: 9).stroke(BeatBeamPalette.brandCyan.opacity(0.22)))
        .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
        .onDisappear {
            if ["PHYSICAL_AXIS_MAPPING_V2", "AXIS_MAPPING_V2_VALIDATION"].contains(model.venueTargetTestState?.mode ?? "") {
                model.releaseVenueTargetTest()
            }
        }
    }

    @ViewBuilder
    private func axisV2TiltFirstFlow(mapping: AxisMappingV2State?, active: Bool) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            if mapping?.tiltSweepReferencePanRaw == nil {
                Text("STEP 1  SET TILT CALIBRATION VIEWING POSE")
                    .font(.system(size: 10, weight: .bold, design: .monospaced)).foregroundStyle(BeatBeamPalette.brandAmber)
                Text("POSITION THE REAL FIXTURE  •  Pan and Tilt physically move only the selected fixture. Position it where vertical beam motion is easy to see.")
                    .font(.system(size: 9, weight: .medium)).foregroundStyle(.secondary)
                Grid(horizontalSpacing: 6, verticalSpacing: 5) {
                    GridRow {
                        Text("PAN").font(.system(size: 9, weight: .bold, design: .monospaced)).foregroundStyle(BeatBeamPalette.brandCyan)
                        Button("LEFT · COARSE") { model.nudgeAxisMappingV2ReferencePose(axis: "PAN", direction: "LEFT", granularity: "COARSE") }
                        Button("LEFT · FINE") { model.nudgeAxisMappingV2ReferencePose(axis: "PAN", direction: "LEFT", granularity: "FINE") }
                        Button("RIGHT · FINE") { model.nudgeAxisMappingV2ReferencePose(axis: "PAN", direction: "RIGHT", granularity: "FINE") }
                        Button("RIGHT · COARSE") { model.nudgeAxisMappingV2ReferencePose(axis: "PAN", direction: "RIGHT", granularity: "COARSE") }
                    }
                    GridRow {
                        Text("TILT").font(.system(size: 9, weight: .bold, design: .monospaced)).foregroundStyle(BeatBeamPalette.brandCyan)
                        Button("UP · COARSE") { model.nudgeAxisMappingV2ReferencePose(axis: "TILT", direction: "UP", granularity: "COARSE") }
                        Button("UP · FINE") { model.nudgeAxisMappingV2ReferencePose(axis: "TILT", direction: "UP", granularity: "FINE") }
                        Button("DOWN · FINE") { model.nudgeAxisMappingV2ReferencePose(axis: "TILT", direction: "DOWN", granularity: "FINE") }
                        Button("DOWN · COARSE") { model.nudgeAxisMappingV2ReferencePose(axis: "TILT", direction: "DOWN", granularity: "COARSE") }
                    }
                }
                .buttonStyle(.bordered)
                .disabled(active || model.axisMappingV2InFlight)
                HStack { Button("RELEASE") { model.releaseVenueTargetTest() }.buttonStyle(.bordered); Spacer(); Button("LOCK PAN FOR TILT SWEEP") { model.lockAxisMappingV2TiltReference() }.buttonStyle(.borderedProminent).disabled(model.venueTargetTestState?.mode != "PHYSICAL_AXIS_MAPPING_V2_REFERENCE") }
            } else if (mapping?.tiltSampleCount ?? 0) < (mapping?.tiltRequiredCount ?? 5) {
                Text("STEP 2  RECORD ALL FIVE DIRECTED TILT SAMPLES")
                    .font(.system(size: 10, weight: .bold, design: .monospaced)).foregroundStyle(BeatBeamPalette.brandAmber)
                Text("TILT SWEEP Pan reference: LOCKED · raw \(mapping?.tiltSweepReferencePanRaw ?? 0)  •  \(mapping?.tiltSampleCount ?? 0)/\(mapping?.tiltRequiredCount ?? 5) directed samples")
                    .font(.system(size: 9, weight: .medium, design: .monospaced)).foregroundStyle(.secondary)
            } else if mapping?.panSweepReferenceTiltRaw == nil {
                Text("AUTO FRONT REFERENCE FAILED")
                    .font(.system(size: 10, weight: .bold, design: .monospaced)).foregroundStyle(BeatBeamPalette.brandAmber)
                Text("TILT SWEEP Pan reference: LOCKED · raw \(mapping?.tiltSweepReferencePanRaw ?? 0)")
                    .font(.system(size: 9, weight: .medium, design: .monospaced)).foregroundStyle(.secondary)
                Text(mapping?.workflowMoveError ?? "HORIZON FRONT 0° is not reachable in the measured Tilt map.")
                    .font(.system(size: 9, weight: .semibold, design: .monospaced)).foregroundStyle(BeatBeamPalette.brandAmber)
                Button("RETRY MEASURED HORIZON FRONT") { model.setAxisMappingV2PanReference(tiltPlaneDegrees: 0) }
                    .buttonStyle(.bordered).disabled(model.axisMappingV2InFlight)
            } else {
                Text(String(format: "PAN SWEEP  Directed Tilt plane: %.1f° FRONT-side  •  Tilt reference: LOCKED · raw %d", mapping?.panSweepReferenceTiltPlaneDegrees ?? 0, mapping?.panSweepReferenceTiltRaw ?? 0))
                    .font(.system(size: 9, weight: .bold, design: .monospaced)).foregroundStyle(BeatBeamPalette.brandCyan)
            }
            if mapping?.legacyTiltDirectionReviewRequired == true { Text("LEGACY TILT DIRECTION REVIEW REQUIRED: old elevation-only samples remain stored but cannot distinguish HORIZON FRONT from HORIZON BACK. Remeasure all five Tilt samples.").font(.system(size: 9, weight: .bold, design: .monospaced)).foregroundStyle(BeatBeamPalette.brandAmber) }
            if mapping?.panSamplesReviewRequired == true { Text("LEGACY ORDER / REVIEW REQUIRED: existing PAN samples stay stored but cannot be used until remeasured at this Tilt reference.").font(.system(size: 9, weight: .bold, design: .monospaced)).foregroundStyle(BeatBeamPalette.brandAmber) }
        }
        .padding(8).background(BeatBeamPalette.panelBackground.opacity(0.55)).clipShape(RoundedRectangle(cornerRadius: 7))
    }

    @ViewBuilder
    private func axisV2PanWizard(editor: SlotEditor, mapping: AxisMappingV2State?, active: Bool) -> some View {
        let positions = mapping?.panSamplePositions ?? []
        let sampleIndex = mapping?.workflowPhase == "PAN" ? (mapping?.workflowSampleIndex ?? 0) : axisV2PanSampleIndex
        let raw: Int? = positions.indices.contains(sampleIndex) ? positions[sampleIndex] : nil
        let sampleActive = model.venueTargetTestState?.mode == "PHYSICAL_AXIS_MAPPING_V2"
            && model.venueTargetTestState?.axis == "PAN"
            && model.venueTargetTestState?.sampleIndex == sampleIndex
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Sample \(sampleIndex + 1) / 7 • raw \(raw.map(String.init) ?? "—") • \(mapping?.panSampleCount ?? 0) saved")
                    .font(.system(size: 9, weight: .semibold, design: .monospaced))
            }
            Button(sampleActive ? "AT EXACT PAN SAMPLE POSITION" : "START / RETRY CURRENT PAN SAMPLE") { model.moveAxisMappingV2Sample(axis: "PAN", index: sampleIndex) }
                .buttonStyle(.borderedProminent).controlSize(.large).frame(maxWidth: .infinity)
                .disabled(sampleActive || model.axisMappingV2InFlight || mapping?.panStartAllowed != true)
            Text("WHERE DOES THE REAL BEAM POINT? • Audience = 0°, Right = 90°, Rear = 180°, Left = 270°")
                .font(.system(size: 9, weight: .bold, design: .monospaced)).foregroundStyle(.secondary)
            AxisMeasuredDirectionEditor(axis: .pan, degrees: $axisV2MeasuredPan)
                .frame(height: 172)
            LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 2), spacing: 6) {
                ForEach([("AUDIENCE", 0.0), ("FRONT-RIGHT", 45.0), ("RIGHT", 90.0), ("REAR-RIGHT", 135.0), ("REAR", 180.0), ("REAR-LEFT", 225.0), ("LEFT", 270.0), ("FRONT-LEFT", 315.0)], id: \.0) { label, value in
                    Button(label) { axisV2MeasuredPan = value }
                        .buttonStyle(.bordered).tint(abs(axisV2MeasuredPan - value) < 0.1 ? BeatBeamPalette.brandCyan : nil)
                }
            }
            HStack {
                Button("−5°") { axisV2MeasuredPan = (axisV2MeasuredPan - 5).truncatingRemainder(dividingBy: 360) }
                Button("−1°") { axisV2MeasuredPan = (axisV2MeasuredPan - 1).truncatingRemainder(dividingBy: 360) }
                Spacer(); Text(String(format: "%.1f°", normalizedCompass(axisV2MeasuredPan))).font(.system(.body, design: .monospaced))
                Spacer(); Button("+1°") { axisV2MeasuredPan = (axisV2MeasuredPan + 1).truncatingRemainder(dividingBy: 360) }
                Button("+5°") { axisV2MeasuredPan = (axisV2MeasuredPan + 5).truncatingRemainder(dividingBy: 360) }
            }.buttonStyle(.bordered)
            HStack {
                Button("RELEASE") { model.releaseVenueTargetTest() }.buttonStyle(.bordered)
                Spacer()
                Button("SAVE SAMPLE") { model.saveAxisMappingV2Sample(axis: "PAN", measuredDegrees: normalizedCompass(axisV2MeasuredPan)) }
                    .buttonStyle(.borderedProminent).controlSize(.large)
                    .disabled(model.venueTargetTestState?.mode != "PHYSICAL_AXIS_MAPPING_V2" || model.venueTargetTestState?.axis != "PAN")
            }
        }
    }

    @ViewBuilder
    private func axisV2TiltWizard(editor: SlotEditor, mapping: AxisMappingV2State?, active: Bool) -> some View {
        let positions = mapping?.tiltSamplePositions ?? []
        let sampleIndex = mapping?.workflowPhase == "TILT" ? (mapping?.workflowSampleIndex ?? 0) : axisV2TiltSampleIndex
        let raw: Int? = positions.indices.contains(sampleIndex) ? positions[sampleIndex] : nil
        let sampleActive = model.venueTargetTestState?.mode == "PHYSICAL_AXIS_MAPPING_V2"
            && model.venueTargetTestState?.axis == "TILT"
            && model.venueTargetTestState?.sampleIndex == sampleIndex
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Sample \(sampleIndex + 1) / 5 • raw \(raw.map(String.init) ?? "—") • \(mapping?.tiltSampleCount ?? 0) saved")
                    .font(.system(size: 9, weight: .semibold, design: .monospaced))
            }
            Button(sampleActive ? "AT EXACT TILT SAMPLE POSITION" : "START / RETRY CURRENT TILT SAMPLE") { model.moveAxisMappingV2Sample(axis: "TILT", index: sampleIndex) }
                .buttonStyle(.borderedProminent).controlSize(.large).frame(maxWidth: .infinity)
                .disabled(sampleActive || model.axisMappingV2InFlight || mapping?.tiltStartAllowed != true)
            Text("OBSERVED BEAM DIRECTION  •  Tell BeatBeam where the real beam is pointing in the Tilt plane. These controls do not move the fixture.")
                .font(.system(size: 9, weight: .bold, design: .monospaced)).foregroundStyle(.secondary)
            Text("FRONT / BACK are relative to the locked Pan reference — not automatically Audience / Rear.")
                .font(.system(size: 9, weight: .semibold, design: .monospaced)).foregroundStyle(BeatBeamPalette.brandAmber)
            AxisMeasuredDirectionEditor(axis: .tilt, degrees: $axisV2MeasuredTilt)
                .frame(height: 172)
            LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 4), spacing: 6) {
                ForEach([("HORIZON FRONT", 0.0), ("UP", 90.0), ("HORIZON BACK", 180.0), ("DOWN", -90.0)], id: \.0) { label, value in
                    Button(label) { axisV2MeasuredTilt = value }
                        .buttonStyle(.bordered).tint(abs(normalizedDirectedTiltPlane(axisV2MeasuredTilt - value)) < 0.1 ? BeatBeamPalette.brandCyan : nil)
                }
            }
            HStack {
                Button("−5°") { axisV2MeasuredTilt = normalizedDirectedTiltPlane(axisV2MeasuredTilt - 5) }
                Button("−1°") { axisV2MeasuredTilt = normalizedDirectedTiltPlane(axisV2MeasuredTilt - 1) }
                Spacer(); Text(String(format: "%.1f°", axisV2MeasuredTilt)).font(.system(.body, design: .monospaced))
                Spacer(); Button("+1°") { axisV2MeasuredTilt = normalizedDirectedTiltPlane(axisV2MeasuredTilt + 1) }
                Button("+5°") { axisV2MeasuredTilt = normalizedDirectedTiltPlane(axisV2MeasuredTilt + 5) }
            }.buttonStyle(.bordered)
            HStack {
                Button("RELEASE") { model.releaseVenueTargetTest() }.buttonStyle(.bordered)
                Spacer()
                Button("SAVE SAMPLE") { model.saveAxisMappingV2Sample(axis: "TILT", measuredDegrees: axisV2MeasuredTilt) }
                    .buttonStyle(.borderedProminent).controlSize(.large)
                    .disabled(model.venueTargetTestState?.mode != "PHYSICAL_AXIS_MAPPING_V2" || model.venueTargetTestState?.axis != "TILT")
            }
        }
    }

    private func normalizedCompass(_ value: Double) -> Double {
        let result = value.truncatingRemainder(dividingBy: 360)
        return result < 0 ? result + 360 : result
    }

    private func normalizedDirectedTiltPlane(_ value: Double) -> Double {
        var result = value.truncatingRemainder(dividingBy: 360)
        if result > 180 { result -= 360 }
        if result <= -180 { result += 360 }
        return result
    }

    @ViewBuilder
    private func physicalAimCalibration(editor: SlotEditor, state: VenueFixtureCalibrationState?) -> some View {
        let aim = state?.kinematicCalibration
        let active = model.venueTargetTestState?.mode == "PHYSICAL_AIM_CALIBRATION"
            && model.venueTargetTestState?.selectedFixtureID == editor.id
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("PHYSICAL AIM CALIBRATION")
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(BeatBeamPalette.brandCyan)
                Spacer()
                Text("Venue: \(state?.status ?? "UNCALIBRATED") • Aim: \(aimStatus(aim))")
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                    .foregroundStyle(aim?.status == "CALIBRATED" ? BeatBeamPalette.brandCyan : BeatBeamPalette.brandAmber)
            }
            Text("One selected fixture only. Pan/Tilt are leased; colour, dimmer, Master and effects remain under the live renderer.")
                .font(.system(size: 9, weight: .medium))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            ForEach(Array([
                ("1", "MID CENTER", "AUDIENCE_MID_CENTER"),
                ("2", "FAR LEFT", "AUDIENCE_FAR_LEFT"),
                ("3", "NEAR CENTER", "AUDIENCE_NEAR_CENTER"),
            ].enumerated()), id: \.offset) { _, step in
                HStack(spacing: 7) {
                    Image(systemName: aim?.anchors?[step.2] == nil ? "circle" : "checkmark.circle.fill")
                        .foregroundStyle(aim?.anchors?[step.2] == nil ? .secondary : BeatBeamPalette.brandCyan)
                    Text("\(step.0)  \(step.1)")
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    Spacer()
                    Button("MOVE") { model.moveAimCalibration(to: step.2) }
                        .buttonStyle(.bordered)
                        .disabled(active || state?.status != "VALID" || model.aimCalibrationInFlight)
                }
            }

            if active {
                Picker("Adjustment", selection: $model.aimCalibrationGranularity) {
                    Text("FINE").tag("FINE")
                    Text("COARSE").tag("COARSE")
                }
                .pickerStyle(.segmented)
                HStack(spacing: 8) {
                    Spacer()
                    Button { model.nudgeAimCalibration(axis: "tilt", direction: "positive") } label: {
                        Label("TILT UP", systemImage: "arrow.up")
                    }
                    .buttonStyle(.borderedProminent)
                    Spacer()
                }
                HStack(spacing: 8) {
                    Button { model.nudgeAimCalibration(axis: "pan", direction: "negative") } label: {
                        Label("PAN LEFT", systemImage: "arrow.left")
                    }
                    .buttonStyle(.borderedProminent)
                    Spacer()
                    Button { model.nudgeAimCalibration(axis: "pan", direction: "positive") } label: {
                        Label("PAN RIGHT", systemImage: "arrow.right")
                    }
                    .buttonStyle(.borderedProminent)
                }
                HStack(spacing: 8) {
                    Spacer()
                    Button { model.nudgeAimCalibration(axis: "tilt", direction: "negative") } label: {
                        Label("TILT DOWN", systemImage: "arrow.down")
                    }
                    .buttonStyle(.borderedProminent)
                    Spacer()
                }
                if let target = model.venueTargetTestState?.target,
                   let output = model.venueTargetTestState?.renderedOutputs?[editor.id] {
                    if let resolution = model.venueTargetTestState?.selectedResolution {
                        Text(String(format: "DESIRED • pan %.2f° • tilt %.2f°", resolution.panDegrees ?? 0, resolution.tiltDegrees ?? 0))
                            .font(.system(size: 9, weight: .semibold, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                    Text("\(target.replacingOccurrences(of: "AUDIENCE_", with: "")) • FINAL PAN \(output.pan)\(output.panFine.map { "/\($0)" } ?? "") • TILT \(output.tilt)\(output.tiltFine.map { "/\($0)" } ?? "")")
                        .font(.system(size: 9, weight: .semibold, design: .monospaced))
                        .foregroundStyle(.secondary)
                    if let theoretical = model.venueTargetTestState?.theoreticalOutput {
                        Text("Δ THEORETICAL • pan \(rawAxis(output.pan, output.panFine) - rawAxis(theoretical.pan, theoretical.panFine)) • tilt \(rawAxis(output.tilt, output.tiltFine) - rawAxis(theoretical.tilt, theoretical.tiltFine)) raw")
                            .font(.system(size: 9, weight: .medium, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                }
                HStack {
                    Button("RELEASE") { model.releaseVenueTargetTest() }
                        .buttonStyle(.bordered)
                    Spacer()
                    if model.venueTargetTestState?.target == "AUDIENCE_FAR_RIGHT" {
                        Button("ADJUSTMENT REQUIRED") { model.recordAimValidation("ADJUSTMENT_REQUIRED") }
                            .buttonStyle(.bordered)
                        Button("PASS") { model.recordAimValidation("PASS") }
                            .buttonStyle(.borderedProminent)
                    } else {
                        Button("SAVE ANCHOR") { model.saveAimCalibrationAnchor() }
                            .buttonStyle(.borderedProminent)
                    }
                }
            }

            if aim?.status == "CALIBRATED", !active {
                HStack {
                    Text("OUT-OF-SAMPLE")
                        .font(.system(size: 9, weight: .bold, design: .monospaced))
                        .foregroundStyle(.secondary)
                    Spacer()
                    Button("MOVE FAR RIGHT • DO NOT ADJUST") {
                        model.moveAimCalibration(to: "AUDIENCE_FAR_RIGHT")
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
            if let pan = aim?.model?.pan, let tilt = aim?.model?.tilt {
                Text(String(format: "MODEL residual • pan %.0f raw • tilt %.0f raw • spread %.1f° / %.1f°", pan.maximumAbsoluteResidualRaw, tilt.maximumAbsoluteResidualRaw, pan.inputSpreadDegrees, tilt.inputSpreadDegrees))
                    .font(.system(size: 9, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
            HStack {
                if let validation = aim?.validation?.result {
                    Text("FAR RIGHT: \(validation)")
                        .font(.system(size: 9, weight: .bold, design: .monospaced))
                        .foregroundStyle(validation == "PASS" ? BeatBeamPalette.brandCyan : BeatBeamPalette.brandAmber)
                }
                Spacer()
                Button("RESET AIM…", role: .destructive) { showAimResetConfirmation = true }
                    .buttonStyle(.bordered)
                    .disabled(active || (aim?.anchorCount ?? 0) == 0)
            }
        }
        .padding(8)
        .background(BeatBeamPalette.mutedBackground.opacity(0.62))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private func aimStatus(_ aim: KinematicCalibrationState?) -> String {
        guard let aim else { return "0/3 anchors" }
        if aim.status == "CALIBRATED" { return "CALIBRATED" }
        if aim.status == "STALE" { return "STALE" }
        if aim.status == "KINEMATIC_MODEL_MISMATCH" { return "MODEL MISMATCH" }
        if aim.status == "INSUFFICIENT_ANCHOR_SPREAD" { return "INSUFFICIENT SPREAD" }
        return "\(aim.anchorCount)/\(aim.requiredAnchorCount) anchors"
    }

    private func rawAxis(_ coarse: Int, _ fine: Int?) -> Int {
        fine.map { (coarse << 8) | $0 } ?? coarse
    }

    private var selectedMovingFixture: SlotEditor? {
        guard let editor = model.slotEditors.first(where: { $0.id == model.selectedSlotID }) else { return nil }
        return editor.supportsPan && editor.supportsTilt ? editor : nil
    }

    private func venuePosition(_ world: SlotWorldPosition) -> VenuePointState {
        VenuePointState(
            x: venueNormalizedCoordinate(world.x, negativeExtent: abs(StageWorld.minX), positiveExtent: StageWorld.maxX),
            y: venueNormalizedCoordinate(world.y, negativeExtent: abs(StageWorld.minY), positiveExtent: StageWorld.maxY)
        )
    }

    private func physicalPointText(_ point: VenuePhysicalPointState) -> String {
        String(format: "(%.2f, %.2f, %.2f)m", point.x, point.y, point.z)
    }

    private func vectorText(_ vector: VenueVectorState) -> String {
        String(format: "%.2f  %.2f  %.2f", vector.x, vector.y, vector.z)
    }

    private func calibrationLine(_ name: String, _ value: String) -> some View {
        HStack {
            Text(name)
                .font(.system(size: 9, weight: .bold, design: .monospaced))
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
        }
    }

    private func positionField(_ label: String, axis: String, slotID: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("\(label) · m")
                .font(.system(size: 8, weight: .bold, design: .monospaced))
                .foregroundStyle(.secondary)
            TextField(
                label,
                value: Binding(
                    get: {
                        let point = model.fixturePositionMeters(for: slotID)
                        if axis == "x" { return point.x }
                        if axis == "y" { return point.y }
                        return point.z
                    },
                    set: { model.setFixturePositionMeters(for: slotID, axis: axis, value: $0) }
                ),
                format: .number.precision(.fractionLength(2))
            )
            .textFieldStyle(.roundedBorder)
            .font(.system(size: 10, weight: .semibold, design: .monospaced))
            .disabled(!model.isEditingProjectionLayout)
        }
    }

    private var calibrationGuide: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("CALIBRATION LEGEND")
                .font(.system(size: 9, weight: .bold, design: .monospaced))
                .foregroundStyle(.secondary)
            calibrationLegendRow(
                BeatBeamPalette.brandAmber,
                "AMBER F",
                "Forward: physical lens/nose direction"
            )
            calibrationLegendRow(
                BeatBeamPalette.brandCyan,
                "BLUE / CYAN",
                "Right: derived from Forward × Up; do not set separately"
            )
            calibrationLegendRow(
                BeatBeamPalette.brandMagenta,
                "RED / MAGENTA",
                "Up: physical top/mount direction"
            )
            calibrationLegendRow(
                BeatBeamPalette.brandCyan.opacity(0.78),
                "DOTTED LINE",
                "Fixture → Audience Center diagnostic only; no movement"
            )
            Text("1 Drag Position  2 Set Forward  3 Set Up  4 Apply  5 Test Audience Center")
                .font(.system(size: 9, weight: .semibold, design: .monospaced))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Text("Red fixture glow is live preview/selection feedback, not a calibration vector.")
                .font(.system(size: 9, weight: .medium))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(8)
        .background(BeatBeamPalette.mutedBackground.opacity(0.62))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private func calibrationLegendRow(_ color: Color, _ title: String, _ detail: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Circle()
                .fill(color)
                .frame(width: 7, height: 7)
            Text(title)
                .font(.system(size: 9, weight: .bold, design: .monospaced))
                .foregroundStyle(color)
                .frame(width: 98, alignment: .leading)
            Text(detail)
                .font(.system(size: 9, weight: .medium))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func audienceTestText(_ result: VenueTargetResolutionState?) -> String {
        guard let result else { return "TEST DID NOT RETURN A RESULT" }
        let pan = result.panDegrees.map { String(format: "pan %.1f°", $0) } ?? "pan HOLD"
        let tilt = result.tiltDegrees.map { String(format: "tilt %.1f°", $0) } ?? "tilt HOLD"
        return "\(result.status) • \(pan) • \(tilt) • \(result.reason ?? "diagnostic only")"
    }
}

private enum AxisMeasuredDirectionKind { case pan, tilt }

private struct AxisMeasuredDirectionEditor: View {
    let axis: AxisMeasuredDirectionKind
    @Binding var degrees: Double

    var body: some View {
        GeometryReader { proxy in
            let size = min(proxy.size.width, proxy.size.height)
            let center = CGPoint(x: proxy.size.width / 2, y: proxy.size.height / 2)
            let radius = max(38, size / 2 - 17)
            ZStack {
                Circle()
                    .fill(BeatBeamPalette.raisedBackground)
                    .overlay(Circle().stroke(BeatBeamPalette.border, lineWidth: 1))
                    .frame(width: radius * 2, height: radius * 2)
                    .position(center)
                Path { path in
                    path.move(to: CGPoint(x: center.x - radius, y: center.y))
                    path.addLine(to: CGPoint(x: center.x + radius, y: center.y))
                    path.move(to: CGPoint(x: center.x, y: center.y - radius))
                    path.addLine(to: CGPoint(x: center.x, y: center.y + radius))
                }
                .stroke(BeatBeamPalette.border.opacity(0.72), style: StrokeStyle(lineWidth: 1, dash: [4, 4]))
                Path { path in
                    path.move(to: center)
                    let endpoint = rayEndpoint(center: center, radius: radius * 0.82)
                    path.addLine(to: endpoint)
                }
                .stroke(BeatBeamPalette.brandCyan, style: StrokeStyle(lineWidth: 5, lineCap: .round))
                Circle().fill(BeatBeamPalette.brandCyan).frame(width: 18, height: 18).position(rayEndpoint(center: center, radius: radius * 0.82))
                Text(axis == .pan ? "AUDIENCE" : "UP")
                    .font(.system(size: 8, weight: .bold, design: .monospaced))
                    .position(x: center.x, y: center.y - radius - 8)
                Text(axis == .pan ? "REAR" : "DOWN")
                    .font(.system(size: 8, weight: .bold, design: .monospaced))
                    .position(x: center.x, y: center.y + radius + 8)
                Text(axis == .pan ? "LEFT" : "HORIZON BACK")
                    .font(.system(size: 8, weight: .bold, design: .monospaced))
                    .position(x: center.x - radius - (axis == .pan ? 16 : 38), y: center.y)
                Text(axis == .pan ? "RIGHT" : "HORIZON FRONT")
                    .font(.system(size: 8, weight: .bold, design: .monospaced))
                    .position(x: center.x + radius + (axis == .pan ? 18 : 42), y: center.y)
            }
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0).onChanged { value in
                    let dx = value.location.x - center.x
                    let dy = value.location.y - center.y
                    if axis == .pan {
                        var angle = atan2(dx, -dy) * 180 / .pi
                        if angle < 0 { angle += 360 }
                        degrees = angle
                    } else {
                        var angle = atan2(-dy, dx) * 180 / .pi
                        if angle <= -180 { angle += 360 }
                        degrees = angle
                    }
                }
            )
        }
    }

    private func rayEndpoint(center: CGPoint, radius: CGFloat) -> CGPoint {
        let radians: Double
        if axis == .pan {
            radians = degrees * .pi / 180
            return CGPoint(x: center.x + sin(radians) * radius, y: center.y - cos(radians) * radius)
        }
        radians = degrees * .pi / 180
        return CGPoint(x: center.x + cos(radians) * radius, y: center.y - sin(radians) * radius)
    }
}

struct StageProjectionDeckView: View {
    @EnvironmentObject private var model: AppModel
    @AppStorage("mapProjectionShowTop") private var showTop = true
    @AppStorage("mapProjectionShowFront") private var showFront = true
    @AppStorage("mapProjectionShowBack") private var showBack = false
    @AppStorage("mapProjectionShowSide") private var showSide = true
    @AppStorage(mapProjectionShow3DDefaultsKey) private var show3D = true
    @AppStorage(mapProjection2DZoomDefaultsKey) private var projection2DZoom = 1.0
    @State private var primaryProjection: StageProjection = .top
    @State private var primaryShows3D = false

    let showControls: Bool
    let topInteractive: Bool
    let showSelection: Bool
    let showAnchorLabels: Bool
    var selectionMode: ProjectionSelectionMode = .none
    var singlePrimaryView = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if showControls {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 8) {
                    ForEach(StageProjection.allCases) { projection in
                        Button(action: { toggle(projection) }) {
                            HStack(spacing: 6) {
                                Image(systemName: iconName(for: projection))
                                    .font(.system(size: 11, weight: .semibold))
                                Text(projection.title.replacingOccurrences(of: " View", with: ""))
                                    .font(.system(size: 12, weight: .semibold, design: .monospaced))
                            }
                            .padding(.horizontal, 10)
                            .padding(.vertical, 7)
                            .background(isActive(projection) ? BeatBeamPalette.triggerActive.opacity(0.22) : BeatBeamPalette.raisedBackground)
                            .overlay(
                                RoundedRectangle(cornerRadius: 8, style: .continuous)
                                    .stroke(isActive(projection) ? BeatBeamPalette.triggerActive.opacity(0.78) : BeatBeamPalette.border, lineWidth: 1)
                            )
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                        }
                        .buttonStyle(.plain)
                    }

                    Button(action: { toggle3DVisibility() }) {
                        HStack(spacing: 6) {
                            Image(systemName: "cube.transparent")
                                .font(.system(size: 11, weight: .semibold))
                            Text("3D")
                                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                        }
                        .padding(.horizontal, 10)
                        .padding(.vertical, 7)
                        .background((singlePrimaryView ? primaryShows3D : show3D) ? BeatBeamPalette.triggerActive.opacity(0.22) : BeatBeamPalette.raisedBackground)
                        .overlay(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .stroke((singlePrimaryView ? primaryShows3D : show3D) ? BeatBeamPalette.triggerActive.opacity(0.78) : BeatBeamPalette.border, lineWidth: 1)
                        )
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    }

                    HStack(spacing: 8) {

                    if showTop {
                        Text("Top \(model.topProjectionRotationDegrees)°")
                            .font(.system(size: 11, weight: .semibold, design: .monospaced))
                            .foregroundStyle(.secondary)

                        Button {
                            model.rotateTopProjection(by: -1)
                        } label: {
                            Label("-90°", systemImage: "rotate.left")
                        }
                        .buttonStyle(.bordered)

                        Button {
                            model.rotateTopProjection(by: 1)
                        } label: {
                            Label("+90°", systemImage: "rotate.right")
                        }
                        .buttonStyle(.bordered)
                    }
                    if showFront {
                        Group {
                            if model.frontProjectionMirrored {
                                Button {
                                    model.toggleFrontProjectionMirrored()
                                } label: {
                                    Label("Flip Front", systemImage: "arrow.left.and.right")
                                }
                                .buttonStyle(.borderedProminent)
                            } else {
                                Button {
                                    model.toggleFrontProjectionMirrored()
                                } label: {
                                    Label("Flip Front", systemImage: "arrow.left.and.right")
                                }
                                .buttonStyle(.bordered)
                            }
                        }
                    }
                    HStack(spacing: 6) {
                        Image(systemName: "magnifyingglass")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(.secondary)

                        Button {
                            projection2DZoom = clampedProjection2DZoom(projection2DZoom - 0.25)
                        } label: {
                            Image(systemName: "minus")
                        }
                        .buttonStyle(.bordered)

                        Text("2D \(Int((clampedProjection2DZoom(projection2DZoom) * 100).rounded()))%")
                            .font(.system(size: 11, weight: .semibold, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .frame(minWidth: 66)

                        Button {
                            model.resetMetricStageMapView()
                            projection2DZoom = 1.0
                        } label: {
                            Text("Reset View")
                        }
                        .buttonStyle(.bordered)

                        Button {
                            projection2DZoom = clampedProjection2DZoom(projection2DZoom + 0.25)
                        } label: {
                            Image(systemName: "plus")
                        }
                        .buttonStyle(.bordered)

                        Menu("Zoom") {
                            ForEach([0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0], id: \.self) { zoom in
                                Button("\(Int(zoom * 100))%") {
                                    projection2DZoom = zoom
                                }
                            }
                        }
                        .menuStyle(.borderlessButton)
                    }

                    Button {
                        model.fixtureSnapEnabled.toggle()
                    } label: {
                        Label(
                            model.fixtureSnapEnabled ? "SNAP ON" : "SNAP OFF",
                            systemImage: model.fixtureSnapEnabled ? "square.grid.4x3.fill" : "circle.dashed"
                        )
                        .font(.system(size: 11, weight: .bold, design: .monospaced))
                        .padding(.horizontal, 9)
                        .padding(.vertical, 7)
                        .background(model.fixtureSnapEnabled ? BeatBeamPalette.triggerActive.opacity(0.28) : BeatBeamPalette.raisedBackground)
                        .overlay(
                            RoundedRectangle(cornerRadius: 7, style: .continuous)
                                .stroke(model.fixtureSnapEnabled ? BeatBeamPalette.triggerActive.opacity(0.88) : BeatBeamPalette.border, lineWidth: 1)
                        )
                        .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Fixture drag snap")
                    .help("Fixture position drag snap: \(model.fixtureSnapEnabled ? "0.25 m" : "off")")

                    }

                    HStack(spacing: 8) {
                    Spacer(minLength: 0)
                        if model.isEditingProjectionLayout {
                            if let selectedEditor = model.slotEditors.first(where: { $0.id == model.selectedSlotID }) {
                                let yaw = Int(model.projectionYawDegrees(for: selectedEditor.id).rounded())
                                let pitch = Int(model.projectionPitchDegrees(for: selectedEditor.id).rounded())
                                let roll = Int(model.projectionRollDegrees(for: selectedEditor.id).rounded())
                                let lower = "\(selectedEditor.label) \(selectedEditor.fixtureLabel)".lowercased()
                                let isWallWashEditor = !(selectedEditor.supportsPan || selectedEditor.supportsTilt) && (lower.contains("wall wash") || lower.contains("light bar") || lower.contains("wallwash") || lower.contains("bar"))
                                HStack(spacing: 8) {
                                Text(
                                    isWallWashEditor
                                        ? "\(selectedEditor.label) • yaw \(yaw)° • roll \(roll)°"
                                        : "\(selectedEditor.label) • yaw \(yaw)° • pitch \(pitch)°"
                                )
                                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                                    .foregroundStyle(.secondary)
                                Button {
                                    model.rotateSelectedProjectionOrientation(by: -90)
                                } label: {
                                    Label("-90°", systemImage: "rotate.left")
                                }
                                .buttonStyle(.bordered)

                                Button {
                                    model.rotateSelectedProjectionOrientation(by: 90)
                                } label: {
                                    Label("+90°", systemImage: "rotate.right")
                                }
                                .buttonStyle(.bordered)

                                if selectedEditor.supportsPan || selectedEditor.supportsTilt {
                                    Button {
                                        model.rotateSelectedProjectionMountPitch(by: -90)
                                    } label: {
                                        Label("Pitch -90°", systemImage: "arrow.down")
                                    }
                                    .buttonStyle(.bordered)

                                    Button {
                                        model.rotateSelectedProjectionMountPitch(by: 90)
                                    } label: {
                                        Label("Pitch +90°", systemImage: "arrow.up")
                                    }
                                    .buttonStyle(.bordered)

                                    if model.isFixtureCalibrationMode {
                                        Button {
                                            model.rotateSelectedProjectionRoll(by: -90)
                                        } label: {
                                            Label("Up -90°", systemImage: "arrow.clockwise")
                                        }
                                        .buttonStyle(.bordered)

                                        Button {
                                            model.rotateSelectedProjectionRoll(by: 90)
                                        } label: {
                                            Label("Up +90°", systemImage: "arrow.counterclockwise")
                                        }
                                        .buttonStyle(.bordered)
                                    }
                                } else if isWallWashEditor {
                                    Button {
                                        model.rotateSelectedProjectionRoll(by: -90)
                                    } label: {
                                        Label("Roll -90°", systemImage: "arrow.clockwise")
                                    }
                                    .buttonStyle(.bordered)

                                    Button {
                                        model.rotateSelectedProjectionRoll(by: 90)
                                    } label: {
                                        Label("Roll +90°", systemImage: "arrow.counterclockwise")
                                    }
                                    .buttonStyle(.bordered)
                                }

                                if selectedEditor.supportsPan {
                                    Group {
                                        if model.projectionPanFlip(for: selectedEditor.id) {
                                            Button {
                                                model.toggleSelectedProjectionPanFlip()
                                            } label: {
                                                Label("Flip Pan", systemImage: "arrow.left.and.right")
                                            }
                                            .buttonStyle(.borderedProminent)
                                        } else {
                                            Button {
                                                model.toggleSelectedProjectionPanFlip()
                                            } label: {
                                                Label("Flip Pan", systemImage: "arrow.left.and.right")
                                            }
                                            .buttonStyle(.bordered)
                                        }
                                    }
                                }

                                if selectedEditor.supportsTilt {
                                    Group {
                                        if model.projectionTiltFlip(for: selectedEditor.id) {
                                            Button {
                                                model.toggleSelectedProjectionTiltFlip()
                                            } label: {
                                                Label("Flip Tilt", systemImage: "arrow.up.and.down")
                                            }
                                            .buttonStyle(.borderedProminent)
                                        } else {
                                            Button {
                                                model.toggleSelectedProjectionTiltFlip()
                                            } label: {
                                                Label("Flip Tilt", systemImage: "arrow.up.and.down")
                                            }
                                            .buttonStyle(.bordered)
                                        }
                                    }
                                }
                            }
                        }

                        Button("Cancel") {
                            model.cancelProjectionLayoutEditing()
                        }
                        .buttonStyle(.bordered)

                        Button("Apply") {
                            model.applyProjectionLayoutEditing()
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.calibrationSaveInFlight)
                    } else {
                        Button("Calibrate Fixture") {
                            model.startFixtureCalibration()
                        }
                        .buttonStyle(.borderedProminent)
                        Button("Edit") {
                            model.startProjectionLayoutEditing()
                        }
                        .buttonStyle(.bordered)
                    }
                    }
                    .padding(.horizontal, 1)
                    .padding(.vertical, 2)
                }
            }

            if model.isFixtureCalibrationMode {
                calibrationProjectionGuide
            }

            let projections = activeProjections
            if visiblePanelCount == 1 {
                singleVisiblePanel(for: projections)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            } else {
                LazyVGrid(
                    columns: [GridItem(.flexible(minimum: 320), spacing: 12), GridItem(.flexible(minimum: 320), spacing: 12)],
                    alignment: .leading,
                    spacing: 12
                ) {
                    ForEach(projections) { projection in
                        projectionPanel(for: projection)
                    }

                    if show3D {
                        threeDPreviewPanel
                    }
                }
            }
        }
    }

    /// Keep the viewport scale as an explicit input to every 2D canvas. The
    /// metric projection helpers read the same persisted value, but passing it
    /// through the view tree invalidates an already-visible canvas as soon as
    /// a zoom control changes.
    private var viewportZoom: Double {
        clampedProjection2DZoom(projection2DZoom)
    }

    private var viewportRenderKey: MetricStageMapViewportRenderKey {
        MetricStageMapViewportRenderKey(
            zoom: viewportZoom,
            cameraRevision: model.metricStageMapViewportRevision
        )
    }

    private var calibrationProjectionGuide: some View {
        HStack(spacing: 10) {
            calibrationProjectionGuideItem(
                color: BeatBeamPalette.brandAmber,
                title: "TOP VIEW",
                detail: "Forward → Back"
            )
            calibrationProjectionGuideItem(
                color: BeatBeamPalette.brandMagenta,
                title: "FRONT / BACK / SIDE",
                detail: "Up → Down"
            )
            Text("One axis per view")
                .font(.system(size: 9, weight: .semibold, design: .monospaced))
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(BeatBeamPalette.mutedBackground.opacity(0.72))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private func calibrationProjectionGuideItem(color: Color, title: String, detail: String) -> some View {
        HStack(spacing: 5) {
            Circle()
                .fill(color)
                .frame(width: 7, height: 7)
            Text(title)
                .font(.system(size: 9, weight: .bold, design: .monospaced))
                .foregroundStyle(color)
            Text(detail)
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(.secondary)
        }
    }

    private var activeProjections: [StageProjection] {
        if singlePrimaryView {
            return primaryShows3D ? [] : [primaryProjection]
        }
        let selected = StageProjection.allCases.filter(isActive)
        if selected.isEmpty {
            return show3D ? [] : [.top]
        }
        return selected
    }

    private var visiblePanelCount: Int {
        activeProjections.count + ((singlePrimaryView ? primaryShows3D : show3D) ? 1 : 0)
    }

    private func isActive(_ projection: StageProjection) -> Bool {
        if singlePrimaryView {
            return !primaryShows3D && primaryProjection == projection
        }
        switch projection {
        case .top:
            return showTop
        case .front:
            return showFront
        case .back:
            return showBack
        case .side:
            return showSide
        }
    }

    private func setActive(_ projection: StageProjection, _ value: Bool) {
        if singlePrimaryView {
            if value {
                primaryProjection = projection
                primaryShows3D = false
            }
            return
        }
        switch projection {
        case .top:
            showTop = value
        case .front:
            showFront = value
        case .back:
            showBack = value
        case .side:
            showSide = value
        }
    }

    private func toggle(_ projection: StageProjection) {
        if singlePrimaryView {
            primaryProjection = projection
            primaryShows3D = false
            return
        }
        if isActive(projection) && activeProjections.count == 1 && !show3D {
            return
        }
        setActive(projection, !isActive(projection))
    }

    private func toggle3DVisibility() {
        if singlePrimaryView {
            primaryShows3D.toggle()
            return
        }
        if show3D && activeProjections.isEmpty {
            showTop = true
            show3D = false
            return
        }
        show3D.toggle()
        if !show3D && activeProjections.isEmpty {
            showTop = true
        }
    }

    private func iconName(for projection: StageProjection) -> String {
        switch projection {
        case .top:
            return "square.split.2x1"
        case .front:
            return "rectangle.lefthalf.inset.filled"
        case .back:
            return "rectangle.center.inset.filled"
        case .side:
            return "rectangle.righthalf.inset.filled"
        }
    }

    @ViewBuilder
    private func singleVisiblePanel(for projections: [StageProjection]) -> some View {
        if let projection = projections.first {
            projectionPanel(for: projection)
        } else if primaryShows3D || show3D {
            threeDPreviewPanel
        }
    }

    private var threeDPreviewPanel: some View {
        StageThreeDPreviewPanel(
            title: "3D View",
            subtitle: "Orbit, pan and zoom the rig in space"
        ) {
            Stage3DPreviewView()
                .aspectRatio(stageMapAspectRatio, contentMode: .fit)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    @ViewBuilder
    private func projectionPanel(for projection: StageProjection) -> some View {
        StagePreviewPanel(
            title: projection.title,
            subtitle: projection.subtitle,
            projection: projection,
            viewportRenderKey: viewportRenderKey,
            showsWorldBackdrop: projection != .top
        ) {
            switch projection {
            case .top:
                StageMapCanvas(
                    showAnchorLabels: showAnchorLabels,
                    showBackdrop: false,
                    interactive: topInteractive && !model.isEditingProjectionLayout,
                    showSelection: showSelection,
                    showDiagnostics: false,
                    projection: .top,
                    editMode: model.isEditingProjectionLayout,
                    selectionMode: selectionMode,
                    viewportRenderKey: viewportRenderKey
                )
                .aspectRatio(stageMapAspectRatio, contentMode: .fit)
            case .front:
                StageFrontCanvas(
                    showDiagnostics: false,
                    projection: .front,
                    editMode: model.isEditingProjectionLayout,
                    selectionMode: selectionMode,
                    viewportRenderKey: viewportRenderKey
                )
                    .aspectRatio(stageMapAspectRatio, contentMode: .fit)
            case .back:
                StageFrontCanvas(
                    showDiagnostics: false,
                    projection: .back,
                    editMode: model.isEditingProjectionLayout,
                    selectionMode: selectionMode,
                    viewportRenderKey: viewportRenderKey
                )
                    .aspectRatio(stageMapAspectRatio, contentMode: .fit)
            case .side:
                StageSideCanvas(
                    showDiagnostics: false,
                    editMode: model.isEditingProjectionLayout,
                    selectionMode: selectionMode,
                    viewportRenderKey: viewportRenderKey
                )
                    .aspectRatio(stageMapAspectRatio, contentMode: .fit)
            }
        }
    }
}

enum ProjectionSelectionMode {
    case none
    case editor
    case preview
}

/// Narrow interaction-only state. `StageMapCanvas` deliberately does not
/// observe its published translation, so a pointer update invalidates only the
/// lightweight transform wrapper—not the TimelineView/world construction.
private final class StageMapPanInteractionState: ObservableObject {
    @Published var translationPx: CGSize = .zero
}

private struct StageMapPanTranslationLayer<Content: View>: View {
    @ObservedObject var interaction: StageMapPanInteractionState
    let content: Content

    init(interaction: StageMapPanInteractionState, @ViewBuilder content: () -> Content) {
        self.interaction = interaction
        self.content = content()
    }

    var body: some View {
        content
            // A single outer transform keeps active panning in screen space.
            // Do not force an offscreen group: Metal/beam content can flicker
            // when repeatedly rasterized into a transient layer while dragging.
            .transformEffect(
                CGAffineTransform(
                    translationX: interaction.translationPx.width,
                    y: interaction.translationPx.height
                )
            )
            .transaction { transaction in
                transaction.animation = nil
            }
    }
}

struct StageMapCanvas: View {
    @EnvironmentObject private var model: AppModel
    var showAnchorLabels: Bool = true
    var showBackdrop: Bool = true
    var interactive: Bool = true
    var showSelection: Bool = true
    var showDiagnostics: Bool = false
    var projection: StageProjection = .top
    var editMode: Bool = false
    var selectionMode: ProjectionSelectionMode = .none
    let viewportRenderKey: MetricStageMapViewportRenderKey
    @State private var backgroundPanStart: SlotWorldPosition?
    // Keep the reference in State rather than StateObject: this canvas must
    // not subscribe to `translationPx`; only StageMapPanTranslationLayer does.
    @State private var panInteraction = StageMapPanInteractionState()

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: !(hasAnimatedStrobe || hasActiveVenuePreviewTest || model.previewPulseTestMode != "OFF" || model.smokePreviewIntensity() > 0))) { timeline in
            GeometryReader { geometry in
                ZStack {
                    StageMapPanTranslationLayer(interaction: panInteraction) {
                        // The grid and all projected world content are one
                        // composited layer during active panning.
                        ProjectionPanelBackdrop(projection: projection, viewportRenderKey: viewportRenderKey)

                        if showBackdrop {
                            StageMapBackdrop()
                        }

                        if interactive || editMode {
                            Color.clear
                                .contentShape(Rectangle())
                                .gesture(backgroundPanGesture(canvasSize: geometry.size))
                        }

                    if projection == .top, let venueSpace = model.venueSpace {
                        VenueSpaceOverlay(space: venueSpace, size: geometry.size)
                            .allowsHitTesting(false)
                    }

                    ForEach(model.slotEditors) { editor in
                        let worldOrigin = model.worldPosition(for: editor.id)
                        let normalizedOrigin = model.projectionPoint(for: editor.id, projection: projection)
                        let origin = absolutePoint(normalizedOrigin, in: geometry.size)
                        let preview = model.presentedSlotPreviews[editor.id]
                        let stageMotion = model.presentedStageMotionStates[editor.id]
                        let beamKind = beamKind(for: editor)
                        let previewTime = model.previewAnimationTime(for: timeline.date)

                        if let preview, preview.enabled {
                            StageFixtureBeam(
                                origin: origin,
                                worldOrigin: worldOrigin,
                                mountYawDegrees: worldOrigin.yawDegrees,
                                mountPitchDegrees: worldOrigin.pitchDegrees,
                                preview: preview,
                                stageMotion: stageMotion,
                                venueTargetPreview: model.venueTargetPreviewVisual(for: editor.id),
                                beamKind: beamKind,
                                wallWashEmitters: beamKind == .wallWash
                                    ? wallWashEmitterPreviews(editor: editor, model: model, preview: preview, animationTime: previewTime)
                                    : [],
                                color: slotPreviewBeamColor(preview),
                                projection: projection,
                                size: geometry.size,
                                animationTime: previewTime
                            )
                        }

                        ProjectionFixtureNode(
                            editor: editor,
                            preview: preview,
                            stageMotion: stageMotion,
                            isSelected: isSelected(editor.id),
                            showDiagnostics: showDiagnostics,
                            animationTime: previewTime,
                            projection: projection,
                            editMode: editMode,
                            interactive: interactive,
                            selectionMode: selectionMode,
                            normalizedOrigin: normalizedOrigin,
                            absoluteOrigin: origin,
                            canvasSize: geometry.size
                        )
                    }

                    ManualSmokePlumeOverlay(projection: projection, size: geometry.size, time: timeline.date)

                    if editMode {
                        EditModeBanner()
                            .padding(12)
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    }
                    }
                }
            }
        }
        // Rebuild only for an authoritative zoom/camera change, never for an
        // active pointer sample. The latter is the outer compositor offset.
        .id(viewportRenderKey)
    }

    private func beamKind(for editor: SlotEditor) -> StageFixtureBeam.BeamKind {
        if editor.supportsPan || editor.supportsTilt {
            return .movingHead
        }
        let lower = "\(editor.label) \(editor.fixtureLabel)".lowercased()
        if lower.contains("wall wash") || lower.contains("light bar") || lower.contains("wallwash") {
            return .wallWash
        }
        return .staticWash
    }

    private var hasAnimatedStrobe: Bool {
        model.presentedSlotPreviews.values.contains { $0.enabled && $0.strobeActive && $0.strobe > 0 }
    }

    private var hasActiveVenuePreviewTest: Bool {
        !model.previewVenueTargetSlotIDs.isEmpty
    }

    private func absolutePoint(_ normalized: CGPoint, in size: CGSize) -> CGPoint {
        CGPoint(x: size.width * normalized.x, y: size.height * normalized.y)
    }

    private func backgroundPanGesture(canvasSize: CGSize) -> some Gesture {
        DragGesture(minimumDistance: 4)
            .onChanged { value in
                if backgroundPanStart == nil {
                    backgroundPanStart = projectionViewportCenter(for: projection)
                }
                guard backgroundPanStart != nil else { return }
                panInteraction.translationPx = value.translation
            }
            .onEnded { value in
                guard let start = backgroundPanStart else { return }
                // Commit and clear in the same non-animated transaction, so
                // the canonical reprojection occupies the exact translated
                // screen position without a release jump.
                withTransaction(Transaction(animation: nil)) {
                    model.commitProjectionViewportPan(
                        projection: projection,
                        startCenter: start,
                        translation: value.translation,
                        canvasSize: canvasSize
                    )
                    panInteraction.translationPx = .zero
                    backgroundPanStart = nil
                }
            }
    }

    private func isSelected(_ slotID: String) -> Bool {
        guard showSelection else { return false }
        switch selectionMode {
        case .none:
            return false
        case .editor:
            return model.selectedSlotID == slotID
        case .preview:
            return model.previewSelectionContains(slotID)
        }
    }
}

struct VenueSpaceOverlay: View {
    @EnvironmentObject private var model: AppModel
    let space: VenueSpaceState
    let size: CGSize

    var body: some View {
        ZStack {
            Path { path in
                path.move(to: absoluteWorld(x: StageWorld.minX, y: 0))
                path.addLine(to: absoluteWorld(x: StageWorld.maxX, y: 0))
                path.move(to: absoluteWorld(x: 0, y: StageWorld.minY))
                path.addLine(to: absoluteWorld(x: 0, y: StageWorld.maxY))
            }
            .stroke(BeatBeamPalette.brandAmber.opacity(0.16), style: StrokeStyle(lineWidth: 1, dash: [4, 5]))

            venueLabel("LEFT", position: absoluteWorld(x: StageWorld.minX + 70, y: 0))
            venueLabel("RIGHT", position: absoluteWorld(x: StageWorld.maxX - 70, y: 0))
            venueLabel("AUDIENCE", position: absoluteWorld(x: 0, y: StageWorld.maxY - 60))
            venueLabel("DJ / REAR", position: absoluteWorld(x: 0, y: StageWorld.minY + 45))

            VStack(spacing: 2) {
                Circle()
                    .fill(BeatBeamPalette.brandAmber.opacity(0.85))
                    .frame(width: 6, height: 6)
                Text("DJ")
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                    .foregroundStyle(BeatBeamPalette.brandAmber.opacity(0.82))
            }
            .position(absoluteWorld(x: 0, y: 0))

            ForEach(space.targets) { target in
                if let physical = target.physicalPointM {
                    VenueTargetMarker(
                        label: targetLabel(target.id),
                        isSelected: target.id == model.selectedVenueTarget
                    )
                    .position(absolute(physical))
                }
            }

            if !previewTargetActive,
               let fixturePoint = selectedFixtureWorldPoint,
               let target = space.targets.first(where: { $0.id == model.selectedVenueTarget })?.physicalPointM {
                Path { path in
                    path.move(to: fixturePoint)
                    path.addLine(to: absolute(target))
                }
                .stroke(
                    BeatBeamPalette.brandCyan.opacity(0.88),
                    style: StrokeStyle(lineWidth: 2, dash: [7, 4])
                )
                ZStack {
                    Circle()
                        .fill(Color.black.opacity(0.76))
                        .frame(width: 24, height: 24)
                    Circle()
                        .stroke(BeatBeamPalette.brandAmber, lineWidth: 2)
                        .frame(width: 20, height: 20)
                    Text("F")
                        .font(.system(size: 9, weight: .bold, design: .monospaced))
                        .foregroundStyle(BeatBeamPalette.brandAmber)
                }
                .position(fixturePoint)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("DJ-centric venue axes and audience targets")
    }

    private func absolute(_ point: VenuePhysicalPointState) -> CGPoint {
        let world = SlotWorldPosition(
            x: point.x * 100,
            y: point.y * 100,
            z: point.z * 100
        )
        let normalized = worldProjectedPoint(world, projection: .top)
        return CGPoint(x: size.width * normalized.x, y: size.height * normalized.y)
    }

    private func absoluteWorld(x: Double, y: Double) -> CGPoint {
        let normalized = worldProjectedPoint(SlotWorldPosition(x: x, y: y, z: 0), projection: .top)
        return CGPoint(x: size.width * normalized.x, y: size.height * normalized.y)
    }

    private func targetLabel(_ id: String) -> String {
        let parts = id.replacingOccurrences(of: "AUDIENCE_", with: "").split(separator: "_")
        guard parts.count == 2 else { return id }
        return String(parts[0].prefix(1)) + String(parts[1].prefix(1))
    }

    private var selectedFixtureWorldPoint: CGPoint? {
        guard !model.selectedSlotID.isEmpty else { return nil }
        let world = model.worldPosition(for: model.selectedSlotID)
        return worldProjectedAbsolutePoint(world, projection: .top, size: size)
    }

    private var previewTargetActive: Bool {
        !model.previewVenueTargetSlotIDs.isEmpty
    }

    private func venueLabel(_ text: String, position: CGPoint) -> some View {
        Text(text)
            .font(.system(size: 9, weight: .bold, design: .monospaced))
            .foregroundStyle(BeatBeamPalette.brandAmber.opacity(0.74))
            .padding(.horizontal, 5)
            .padding(.vertical, 3)
            .background(Color.black.opacity(0.32))
            .clipShape(RoundedRectangle(cornerRadius: 5, style: .continuous))
            .position(position)
    }
}

struct VenueTargetMarker: View {
    let label: String
    var isSelected = false

    var body: some View {
        VStack(spacing: 2) {
            ZStack {
                Circle()
                    .stroke(isSelected ? BeatBeamPalette.brandAmber : BeatBeamPalette.brandCyan.opacity(0.62), lineWidth: isSelected ? 2 : 1)
                    .frame(width: isSelected ? 22 : 16, height: isSelected ? 22 : 16)
                Circle()
                    .fill((isSelected ? BeatBeamPalette.brandAmber : BeatBeamPalette.brandCyan).opacity(0.82))
                    .frame(width: 4, height: 4)
                Rectangle()
                    .fill(BeatBeamPalette.brandCyan.opacity(0.48))
                    .frame(width: 22, height: 1)
                Rectangle()
                    .fill(BeatBeamPalette.brandCyan.opacity(0.48))
                    .frame(width: 1, height: 22)
            }
            Text(label)
                .font(.system(size: 8, weight: .semibold, design: .monospaced))
                .foregroundStyle((isSelected ? BeatBeamPalette.brandAmber : BeatBeamPalette.brandCyan).opacity(0.82))
        }
    }
}

/// A preview-only plume. Its anchor and intensity come from the final backend
/// smoke authority; the short local decay is presentation only and never DMX.
struct ManualSmokePlumeOverlay: View {
    @EnvironmentObject private var model: AppModel
    let projection: StageProjection
    let size: CGSize
    let time: Date

    var body: some View {
        let intensity = model.smokePreviewIntensity(at: time)
        if intensity > 0.001, let smoke = model.manualSmoke {
            ForEach(smoke.fixtureSlotIds, id: \.self) { slotID in
                let origin = worldProjectedAbsolutePoint(model.worldPosition(for: slotID), projection: projection, size: size)
                SmokePlume(intensity: intensity, projection: projection)
                    .position(origin)
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
            }
        }
    }
}

private struct SmokePlume: View {
    let intensity: Double
    let projection: StageProjection

    private var rise: CGFloat {
        projection == .top ? 0 : -34
    }

    var body: some View {
        ZStack {
            Circle().fill(Color.white.opacity(0.12 + intensity * 0.16)).frame(width: 32 + 45 * intensity, height: 32 + 45 * intensity).offset(x: -10, y: rise - 11)
            Circle().fill(BeatBeamPalette.brandCyan.opacity(0.12 + intensity * 0.14)).frame(width: 25 + 34 * intensity, height: 25 + 34 * intensity).offset(x: 13, y: rise - 24)
            Circle().fill(Color.white.opacity(0.10 + intensity * 0.12)).frame(width: 18 + 26 * intensity, height: 18 + 26 * intensity).offset(x: 1, y: rise - 43)
        }
        .blur(radius: 4 + 7 * intensity)
        .opacity(0.35 + intensity * 0.65)
    }
}

struct StageFrontCanvas: View {
    @EnvironmentObject private var model: AppModel
    var showDiagnostics: Bool = false
    var projection: StageProjection = .front
    var editMode: Bool = false
    var selectionMode: ProjectionSelectionMode = .none
    let viewportRenderKey: MetricStageMapViewportRenderKey

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: !(hasAnimatedStrobe || hasActiveVenuePreviewTest || model.previewPulseTestMode != "OFF" || model.smokePreviewIntensity() > 0))) { timeline in
            GeometryReader { geometry in
                ZStack {
                    ForEach(model.slotEditors) { editor in
                        let worldOrigin = model.worldPosition(for: editor.id)
                        let normalizedOrigin = model.projectionPoint(for: editor.id, projection: projection)
                        let origin = absolutePoint(normalizedOrigin, in: geometry.size)
                        let preview = model.presentedSlotPreviews[editor.id]
                        let stageMotion = model.presentedStageMotionStates[editor.id]
                        let beamKind = beamKind(for: editor)
                        let previewTime = model.previewAnimationTime(for: timeline.date)

                        if let preview, preview.enabled {
                            StageFixtureBeam(
                                origin: origin,
                                worldOrigin: worldOrigin,
                                mountYawDegrees: worldOrigin.yawDegrees,
                                mountPitchDegrees: worldOrigin.pitchDegrees,
                                preview: preview,
                                stageMotion: stageMotion,
                                venueTargetPreview: model.venueTargetPreviewVisual(for: editor.id),
                                beamKind: beamKind,
                                wallWashEmitters: beamKind == .wallWash
                                    ? wallWashEmitterPreviews(editor: editor, model: model, preview: preview, animationTime: previewTime)
                                    : [],
                                color: slotPreviewBeamColor(preview),
                                projection: projection,
                                size: geometry.size,
                                animationTime: previewTime
                            )
                        }

                        ProjectionFixtureNode(
                            editor: editor,
                            preview: preview,
                            stageMotion: stageMotion,
                            isSelected: isSelected(editor.id),
                            showDiagnostics: showDiagnostics,
                            animationTime: previewTime,
                            projection: projection,
                            editMode: editMode,
                            interactive: false,
                            selectionMode: selectionMode,
                            normalizedOrigin: normalizedOrigin,
                            absoluteOrigin: origin,
                            canvasSize: geometry.size
                        )
                    }

                    ManualSmokePlumeOverlay(projection: projection, size: geometry.size, time: timeline.date)

                    if editMode {
                        EditModeBanner()
                            .padding(12)
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    }
                }
            }
        }
        .id(viewportRenderKey)
    }

    private func beamKind(for editor: SlotEditor) -> StageFixtureBeam.BeamKind {
        if editor.supportsPan || editor.supportsTilt {
            return .movingHead
        }
        let lower = "\(editor.label) \(editor.fixtureLabel)".lowercased()
        if lower.contains("wall wash") || lower.contains("light bar") || lower.contains("wallwash") {
            return .wallWash
        }
        return .staticWash
    }

    private var hasAnimatedStrobe: Bool {
        model.presentedSlotPreviews.values.contains { $0.enabled && $0.strobeActive && $0.strobe > 0 }
    }

    private var hasActiveVenuePreviewTest: Bool {
        model.previewVenueTargetSlotID != nil
            && model.previewVenueTargetResolution?.status == "RESOLVED"
    }

    private func absolutePoint(_ normalized: CGPoint, in size: CGSize) -> CGPoint {
        CGPoint(x: size.width * normalized.x, y: size.height * normalized.y)
    }

    private func isSelected(_ slotID: String) -> Bool {
        switch selectionMode {
        case .none:
            return false
        case .editor:
            return model.selectedSlotID == slotID
        case .preview:
            return model.previewSelectionContains(slotID)
        }
    }
}

struct StageSideCanvas: View {
    @EnvironmentObject private var model: AppModel
    var showDiagnostics: Bool = false
    var editMode: Bool = false
    var selectionMode: ProjectionSelectionMode = .none
    let viewportRenderKey: MetricStageMapViewportRenderKey

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: !(hasAnimatedStrobe || hasActiveVenuePreviewTest || model.previewPulseTestMode != "OFF" || model.smokePreviewIntensity() > 0))) { timeline in
            GeometryReader { geometry in
                ZStack {
                    ForEach(model.slotEditors) { editor in
                        let worldOrigin = model.worldPosition(for: editor.id)
                        let normalizedOrigin = model.projectionPoint(for: editor.id, projection: .side)
                        let origin = absolutePoint(normalizedOrigin, in: geometry.size)
                        let preview = model.presentedSlotPreviews[editor.id]
                        let stageMotion = model.presentedStageMotionStates[editor.id]
                        let beamKind = beamKind(for: editor)
                        let previewTime = model.previewAnimationTime(for: timeline.date)

                        if let preview, preview.enabled {
                            StageFixtureBeam(
                                origin: origin,
                                worldOrigin: worldOrigin,
                                mountYawDegrees: worldOrigin.yawDegrees,
                                mountPitchDegrees: worldOrigin.pitchDegrees,
                                preview: preview,
                                stageMotion: stageMotion,
                                venueTargetPreview: model.venueTargetPreviewVisual(for: editor.id),
                                beamKind: beamKind,
                                wallWashEmitters: beamKind == .wallWash
                                    ? wallWashEmitterPreviews(editor: editor, model: model, preview: preview, animationTime: previewTime)
                                    : [],
                                color: slotPreviewBeamColor(preview),
                                projection: .side,
                                size: geometry.size,
                                animationTime: previewTime
                            )
                        }

                        ProjectionFixtureNode(
                            editor: editor,
                            preview: preview,
                            stageMotion: stageMotion,
                            isSelected: isSelected(editor.id),
                            showDiagnostics: showDiagnostics,
                            animationTime: previewTime,
                            projection: .side,
                            editMode: editMode,
                            interactive: false,
                            selectionMode: selectionMode,
                            normalizedOrigin: normalizedOrigin,
                            absoluteOrigin: origin,
                            canvasSize: geometry.size
                        )
                    }

                    ManualSmokePlumeOverlay(projection: .side, size: geometry.size, time: timeline.date)

                    if editMode {
                        EditModeBanner()
                            .padding(12)
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    }
                }
            }
        }
        .id(viewportRenderKey)
    }

    private func beamKind(for editor: SlotEditor) -> StageFixtureBeam.BeamKind {
        if editor.supportsPan || editor.supportsTilt {
            return .movingHead
        }
        let lower = "\(editor.label) \(editor.fixtureLabel)".lowercased()
        if lower.contains("wall wash") || lower.contains("light bar") || lower.contains("wallwash") {
            return .wallWash
        }
        return .staticWash
    }

    private var hasAnimatedStrobe: Bool {
        model.presentedSlotPreviews.values.contains { $0.enabled && $0.strobeActive && $0.strobe > 0 }
    }

    private var hasActiveVenuePreviewTest: Bool {
        model.previewVenueTargetSlotID != nil
            && model.previewVenueTargetResolution?.status == "RESOLVED"
    }

    private func absolutePoint(_ normalized: CGPoint, in size: CGSize) -> CGPoint {
        CGPoint(x: size.width * normalized.x, y: size.height * normalized.y)
    }

    private func isSelected(_ slotID: String) -> Bool {
        switch selectionMode {
        case .none:
            return false
        case .editor:
            return model.selectedSlotID == slotID
        case .preview:
            return model.previewSelectionContains(slotID)
        }
    }
}

struct StageMapBackdrop: View {
    var body: some View {
        GeometryReader { geometry in
            let width = geometry.size.width
            let height = geometry.size.height
            let trussY = height * 0.12
            let leftTruss = width * 0.24
            let rightTruss = width * 0.76
            let sideStandLeft = width * 0.08
            let sideStandRight = width * 0.92

            ZStack {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [
                                Color(red: 0.14, green: 0.17, blue: 0.21),
                                Color(red: 0.11, green: 0.13, blue: 0.17)
                            ],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )

                Path { path in
                    path.move(to: CGPoint(x: leftTruss, y: trussY))
                    path.addLine(to: CGPoint(x: rightTruss, y: trussY))
                }
                .stroke(Color.white.opacity(0.18), lineWidth: 8)

                TrussSegmentLine()
                    .stroke(Color.white.opacity(0.12), lineWidth: 2)
                    .frame(width: rightTruss - leftTruss, height: 34)
                    .position(x: (leftTruss + rightTruss) / 2, y: trussY + 20)

                ForEach([leftTruss, rightTruss], id: \.self) { x in
                    Rectangle()
                        .fill(Color.white.opacity(0.10))
                        .frame(width: 6, height: height * 0.72)
                        .position(x: x, y: height * 0.46)
                }

                ForEach([sideStandLeft, sideStandRight], id: \.self) { x in
                    StageStandShape()
                        .stroke(Color.white.opacity(0.14), lineWidth: 7)
                        .frame(width: 130, height: 190)
                        .position(x: x, y: height * 0.68)
                }

                RoundedRectangle(cornerRadius: 2, style: .continuous)
                    .fill(Color.black.opacity(0.42))
                    .frame(width: width * 0.27, height: height * 0.34)
                    .position(x: width * 0.50, y: height * 0.72)

                Image(systemName: "music.mic")
                    .font(.system(size: 72, weight: .thin))
                    .foregroundStyle(Color.white.opacity(0.08))
                    .position(x: width * 0.50, y: height * 0.52)

                ForEach([leftTruss, rightTruss], id: \.self) { x in
                    RoundedRectangle(cornerRadius: 6, style: .continuous)
                        .fill(Color.white.opacity(0.08))
                        .overlay(
                            RoundedRectangle(cornerRadius: 6, style: .continuous)
                                .stroke(Color.white.opacity(0.10), lineWidth: 1)
                        )
                        .frame(width: 16, height: 160)
                        .position(x: x, y: height * 0.49)
                }
            }
        }
    }
}

struct StageFrontBackdrop: View {
    var body: some View {
        GeometryReader { geometry in
            let width = geometry.size.width
            let height = geometry.size.height
            let trussY = height * 0.15
            let floorY = height * 0.87
            let leftTruss = width * 0.24
            let rightTruss = width * 0.76
            let sideStandLeft = width * 0.08
            let sideStandRight = width * 0.92

            ZStack {
                Path { path in
                    path.move(to: CGPoint(x: leftTruss, y: trussY))
                    path.addLine(to: CGPoint(x: rightTruss, y: trussY))
                }
                .stroke(Color.white.opacity(0.16), lineWidth: 6)

                ForEach([leftTruss, rightTruss], id: \.self) { x in
                    Path { path in
                        path.move(to: CGPoint(x: x, y: trussY))
                        path.addLine(to: CGPoint(x: x, y: floorY))
                    }
                    .stroke(Color.white.opacity(0.08), lineWidth: 4)
                }

                ForEach([sideStandLeft, sideStandRight], id: \.self) { x in
                    StageStandFrontShape()
                        .stroke(Color.white.opacity(0.12), lineWidth: 4)
                        .frame(width: 100, height: 190)
                        .position(x: x, y: height * 0.66)
                }

                RoundedRectangle(cornerRadius: 3, style: .continuous)
                    .fill(Color.white.opacity(0.06))
                    .frame(width: width * 0.26, height: height * 0.22)
                    .position(x: width * 0.50, y: height * 0.74)

                Path { path in
                    path.move(to: CGPoint(x: 0, y: floorY))
                    path.addLine(to: CGPoint(x: width, y: floorY))
                }
                .stroke(Color.white.opacity(0.12), style: StrokeStyle(lineWidth: 1.5, dash: [7, 5]))
            }
        }
    }
}

struct StageSideBackdrop: View {
    var body: some View {
        GeometryReader { geometry in
            let width = geometry.size.width
            let height = geometry.size.height
            let floorY = height * 0.87
            let trussX = width * 0.28
            let standX = width * 0.74

            ZStack {
                Path { path in
                    path.move(to: CGPoint(x: 0, y: floorY))
                    path.addLine(to: CGPoint(x: width, y: floorY))
                }
                .stroke(Color.white.opacity(0.12), style: StrokeStyle(lineWidth: 1.5, dash: [7, 5]))

                Path { path in
                    path.move(to: CGPoint(x: trussX, y: height * 0.14))
                    path.addLine(to: CGPoint(x: trussX, y: floorY))
                }
                .stroke(Color.white.opacity(0.08), lineWidth: 4)

                Path { path in
                    path.move(to: CGPoint(x: trussX - 48, y: height * 0.14))
                    path.addLine(to: CGPoint(x: trussX + 48, y: height * 0.14))
                }
                .stroke(Color.white.opacity(0.16), lineWidth: 6)

                StageStandFrontShape()
                    .stroke(Color.white.opacity(0.12), lineWidth: 4)
                    .frame(width: 100, height: 190)
                    .position(x: standX, y: height * 0.66)

                RoundedRectangle(cornerRadius: 3, style: .continuous)
                    .fill(Color.white.opacity(0.06))
                    .frame(width: width * 0.18, height: height * 0.22)
                    .position(x: width * 0.52, y: height * 0.74)
            }
        }
    }
}

struct StageFixtureNode: View {
    @EnvironmentObject private var model: AppModel
    let editor: SlotEditor
    let anchor: StageAnchor?
    let worldOrigin: SlotWorldPosition
    let preview: SlotPreview?
    let stageMotion: StageMotionState?
    let isSelected: Bool
    let showDiagnostics: Bool
    let animationTime: TimeInterval
    let projection: StageProjection
    let canvasSize: CGSize
    let action: (() -> Void)?

    var body: some View {
        Group {
            if let action {
                Button(action: action) {
                    nodeBody
                }
                .buttonStyle(.plain)
            } else {
                nodeBody
            }
        }
    }

    private var nodeBody: some View {
        let strobeFactor = slotPreviewStrobeFactor(preview, at: animationTime)
        let brightness = effectivePreviewBrightness(preview, at: animationTime)
        let strobeHighlighted = (preview?.strobeActive ?? false) && strobeFactor > 0.65
        let wallMetrics = wallWashMetrics
        return ZStack {
            if isWallWash {
                wallWashBody(brightness: brightness, strobeHighlighted: strobeHighlighted)
            } else if isBeeEyeFixture {
                beeEyeBody(brightness: brightness)
            } else {
                genericMovingHeadBody(brightness: brightness)
            }

            if let preview, preview.strobeActive {
                Group {
                    if isWallWash {
                        RoundedRectangle(cornerRadius: 9, style: .continuous)
                            .stroke(
                                BeatBeamPalette.triggerActive.opacity(strobeHighlighted ? 0.95 : 0.36),
                                style: StrokeStyle(lineWidth: strobeHighlighted ? 3.2 : 1.8, dash: [4, 4])
                            )
                            .frame(width: wallMetrics.envelope, height: wallMetrics.envelope)
                    } else {
                        Circle()
                            .stroke(
                                BeatBeamPalette.triggerActive.opacity(strobeHighlighted ? 0.95 : 0.36),
                                style: StrokeStyle(lineWidth: strobeHighlighted ? 3.2 : 1.8, dash: [4, 4])
                            )
                            .frame(width: fixtureSize + 18, height: fixtureSize + 18)
                    }
                }

                Image(systemName: preview.strobeExternal ? "bolt.fill" : "sparkle")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundStyle(
                        preview.strobeExternal
                            ? BeatBeamPalette.triggerActive.opacity(strobeHighlighted ? 1.0 : 0.72)
                            : Color.white.opacity(strobeHighlighted ? 0.98 : 0.62)
                    )
                    .padding(5)
                    .background(
                        Circle()
                            .fill(Color.black.opacity(strobeHighlighted ? 0.82 : 0.58))
                    )
                    .overlay(
                        Circle()
                            .stroke(BeatBeamPalette.triggerActive.opacity(strobeHighlighted ? 0.88 : 0.26), lineWidth: 1)
                    )
                    .offset(
                        x: isWallWash ? -wallMetrics.size.width * 0.30 : -fixtureSize * 0.32,
                        y: isWallWash ? -wallMetrics.size.height * 0.95 : -fixtureSize * 0.34
                    )
            }

            if let preview, preview.motionActive, editor.supportsPan || editor.supportsTilt {
                Image(systemName: "arrow.trianglehead.2.clockwise.rotate.90")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(displayColor.opacity(0.95))
                    .offset(x: fixtureSize * 0.30, y: -fixtureSize * 0.30)
            }

            if showDiagnostics, let stageMotion, editor.supportsPan || editor.supportsTilt {
                VStack(spacing: 2) {
                    Text("P \(Int(stageMotion.currentPanDegrees.rounded()))°  T \(Int(stageMotion.currentTiltDegrees.rounded()))°")
                        .font(.system(size: 9, weight: .semibold, design: .monospaced))
                    Text("\(Int(stageMotion.estimatedSpeedDegreesPerSecond.rounded()))°/s")
                        .font(.system(size: 8, weight: .medium, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 6)
                .padding(.vertical, 4)
                .background(Color.black.opacity(0.62))
                .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 6, style: .continuous)
                        .stroke(Color.white.opacity(0.08), lineWidth: 1)
                )
                .offset(y: fixtureSize * 0.92)
            }

            fixtureMapLabel
        }
    }

    @ViewBuilder
    private var fixtureMapLabel: some View {
        Text(isSelected ? editor.label : compactFixtureMapLabel)
            .font(.system(
                size: isSelected ? 11 : 8.5,
                weight: isSelected ? .bold : .semibold,
                design: .monospaced
            ))
            .lineLimit(1)
            .fixedSize(horizontal: true, vertical: false)
            .foregroundStyle(isSelected ? Color.white : Color.white.opacity(0.56))
            .padding(.horizontal, isSelected ? 6 : 0)
            .padding(.vertical, isSelected ? 3 : 0)
            .background {
                if isSelected {
                    Color.black.opacity(0.58)
                        .clipShape(RoundedRectangle(cornerRadius: 5, style: .continuous))
                }
            }
            // This is a screen-space label attached to the live fixture node,
            // never a hit target. The node keeps priority for edit dragging.
            .allowsHitTesting(false)
            .offset(y: fixtureLabelOffset)
    }

    private var compactFixtureMapLabel: String {
        let label = editor.label.trimmingCharacters(in: .whitespacesAndNewlines)
        let lower = label.lowercased()
        let trailingNumber = label.split(separator: " ").last.flatMap { token in
            Int(token).map(String.init)
        } ?? ""
        if lower.contains("moving head") { return "MH\(trailingNumber)" }
        if lower.contains("bee") { return "BEE\(trailingNumber)" }
        if lower.contains("wall wash") || lower.contains("wallwash") { return "WASH\(trailingNumber)" }
        if lower.contains("par") { return "PAR\(trailingNumber)" }
        return label.count > 10 ? String(label.prefix(10)) + "…" : label
    }

    private var fixtureLabelOffset: CGFloat {
        isWallWash ? wallWashMetrics.envelope * 0.56 + 8 : fixtureSize * 0.78 + 8
    }

    private var isWallWash: Bool {
        let lower = "\(editor.label) \(editor.fixtureLabel)".lowercased()
        return !(editor.supportsPan || editor.supportsTilt) && (lower.contains("wall wash") || lower.contains("light bar") || lower.contains("wallwash"))
    }

    private var isBeeEyeFixture: Bool {
        slotPreviewIsBeeEye(preview) || editor.fixtureID == "generic_smart_bee_eye_pattern_moving_head"
    }

    private var fixtureSize: CGFloat {
        (editor.supportsPan || editor.supportsTilt) ? 42 : 28
    }

    private var wallWashMetrics: WallWashNodeMetrics {
        let endpoints = wallWashBarWorldEndpoints(worldOrigin, halfLength: 45.0)
        let start = endpoints.start
        let end = endpoints.end
        let startPoint = worldProjectedAbsolutePoint(start, projection: projection, size: canvasSize)
        let endPoint = worldProjectedAbsolutePoint(end, projection: projection, size: canvasSize)
        let rawLength = hypot(endPoint.x - startPoint.x, endPoint.y - startPoint.y)
        let thickness: CGFloat
        switch projection {
        case .top:
            thickness = 18
        case .front, .back:
            thickness = 22
        case .side:
            thickness = 20
        }
        // The bar's position and orientation are world-projected, while its
        // visible body stays a usable screen-space marker. Otherwise a 400%
        // camera zoom would create a four-times larger hit target.
        let length = boundedScreenSpaceFixtureMarkerExtent(
            rawLength,
            minimum: max(34, thickness * 1.45),
            maximum: 96
        )
        let angle = atan2(endPoint.y - startPoint.y, endPoint.x - startPoint.x)
        let envelope = hypot(length, thickness) + 22
        let ledDiameter = min(thickness * 0.56, max(4.2, length / 18.0))
        return WallWashNodeMetrics(
            size: CGSize(width: length, height: thickness),
            angleRadians: angle,
            envelope: envelope,
            ledDiameter: ledDiameter
        )
    }

    @ViewBuilder
    private func genericMovingHeadBody(brightness: CGFloat) -> some View {
        Circle()
            .fill(displayColor.opacity(0.24 + brightness * 0.30))
            .frame(width: fixtureSize + 12 + brightness * 22, height: fixtureSize + 12 + brightness * 22)
            .blur(radius: 6 + brightness * 7)

        Circle()
            .fill(Color.black.opacity(0.74))
            .overlay(
                Circle()
                    .stroke(isSelected ? Color.white : Color.white.opacity(0.82), lineWidth: isSelected ? 3 : 2)
            )
            .frame(width: fixtureSize, height: fixtureSize)

        Circle()
            .stroke(displayColor.opacity(0.85), lineWidth: 2)
            .frame(width: fixtureSize - 10, height: fixtureSize - 10)

        if spotBrightness > 0.06 {
            Circle()
                .fill(spotDisplayColor.opacity(max(0.22, spotBrightness * 0.88)))
                .frame(
                    width: fixtureSize * 0.34 + spotBrightness * 8,
                    height: fixtureSize * 0.34 + spotBrightness * 8
                )
                .blur(radius: 1.2 + spotBrightness * 1.8)

            Circle()
                .stroke(spotDisplayColor.opacity(0.92), lineWidth: 1.6)
                .frame(
                    width: fixtureSize * 0.24 + spotBrightness * 5,
                    height: fixtureSize * 0.24 + spotBrightness * 5
                )
        }

        Circle()
            .trim(from: 0, to: brightness)
            .stroke(
                displayColor.opacity(0.95),
                style: StrokeStyle(lineWidth: 3, lineCap: .round)
            )
            .rotationEffect(.degrees(-90))
            .frame(width: fixtureSize + 10, height: fixtureSize + 10)

        RoundedRectangle(cornerRadius: 3, style: .continuous)
            .fill(Color.white.opacity(0.10))
            .frame(width: fixtureSize - 12, height: 5)
            .overlay(alignment: .leading) {
                RoundedRectangle(cornerRadius: 3, style: .continuous)
                    .fill(displayColor.opacity(0.96))
                    .frame(width: max(4, (fixtureSize - 12) * brightness), height: 5)
            }
            .offset(y: fixtureSize * 0.36)
    }

    @ViewBuilder
    private func beeEyeBody(brightness: CGFloat) -> some View {
        Circle()
            .fill(displayColor.opacity(0.18 + brightness * 0.22))
            .frame(width: fixtureSize + 18 + brightness * 24, height: fixtureSize + 18 + brightness * 24)
            .blur(radius: 7 + brightness * 8)

        Circle()
            .fill(Color.black.opacity(0.82))
            .overlay(
                Circle()
                    .stroke(isSelected ? Color.white : Color.white.opacity(0.84), lineWidth: isSelected ? 3 : 2)
            )
            .frame(width: fixtureSize + 6, height: fixtureSize + 6)

        Circle()
            .stroke(displayColor.opacity(0.84), lineWidth: 2)
            .frame(width: fixtureSize - 2, height: fixtureSize - 2)

        ForEach(0..<6, id: \.self) { index in
            let angle = Angle.degrees(Double(index) * 60.0 - 90.0)
            Circle()
                .fill(displayColor.opacity(0.30 + brightness * 0.58))
                .frame(width: fixtureSize * 0.22, height: fixtureSize * 0.22)
                .overlay(
                    Circle()
                        .stroke(Color.white.opacity(0.16), lineWidth: 0.8)
                )
                .offset(
                    x: cos(angle.radians) * fixtureSize * 0.26,
                    y: sin(angle.radians) * fixtureSize * 0.26
                )
                .blur(radius: brightness > 0.5 ? 0.3 : 0)
        }

        if spotBrightness > 0.05 {
            Circle()
                .fill(spotDisplayColor.opacity(max(0.24, spotBrightness * 0.92)))
                .frame(
                    width: fixtureSize * 0.40 + spotBrightness * 8,
                    height: fixtureSize * 0.40 + spotBrightness * 8
                )
                .blur(radius: 1.4 + spotBrightness * 2.1)
        }

        Circle()
            .fill(Color.black.opacity(0.50))
            .overlay(
                Circle()
                    .stroke(spotDisplayColor.opacity(0.94), lineWidth: 1.8)
            )
            .frame(width: fixtureSize * 0.36, height: fixtureSize * 0.36)

        if let preview, spotBrightness > 0.05 {
            let patternID = slotPreviewResolvedPatternID(preview, at: animationTime)
            if patternID != "open" && !(preview.spotPatternOpen ?? false) {
                BeeEyePatternGlyph(
                    patternID: patternID,
                    color: Color.white,
                    rotationDegrees: slotPreviewResolvedPatternRotation(preview, at: animationTime),
                    opacity: max(0.64, Double(spotBrightness))
                )
                .frame(width: fixtureSize * 0.28, height: fixtureSize * 0.28)
                .blendMode(.screen)
            }
        }

        Circle()
            .trim(from: 0, to: brightness)
            .stroke(
                displayColor.opacity(0.95),
                style: StrokeStyle(lineWidth: 3, lineCap: .round)
            )
            .rotationEffect(.degrees(-90))
            .frame(width: fixtureSize + 12, height: fixtureSize + 12)

    }

    private var displayColor: Color {
        guard let preview, preview.enabled else { return Color.white.opacity(0.18) }
        let brightness = effectivePreviewBrightness(preview, at: animationTime)
        let base = slotPreviewBaseColor(preview)
        if preview.strobeActive {
            let highlight = slotPreviewStrobeFactor(preview, at: animationTime)
            return base.opacity(min(1.0, brightness + CGFloat(highlight) * 0.22))
        }
        return base.opacity(brightness)
    }

    private var spotDisplayColor: Color {
        guard let preview, preview.enabled else { return Color.white.opacity(0.18) }
        return slotPreviewResolvedSpotColor(preview, at: animationTime)
    }

    private var spotBrightness: CGFloat {
        guard let preview, preview.enabled else { return 0 }
        let base = effectiveSpotPreviewBrightness(preview, at: animationTime)
        if preview.strobeActive {
            return base * CGFloat(slotPreviewStrobeFactor(preview, at: animationTime))
        }
        return base
    }

    @ViewBuilder
    private func wallWashBody(brightness: CGFloat, strobeHighlighted: Bool) -> some View {
        let metrics = wallWashMetrics
        let size = metrics.size
        let emitters = wallWashEmitters
        ZStack {
            ZStack {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(Color.black.opacity(0.18 + brightness * 0.06))
                    .frame(width: size.width + 16, height: size.height + 18)
                    .blur(radius: 3 + brightness * 2)

                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .fill(Color.black.opacity(0.94))
                    .overlay(
                        RoundedRectangle(cornerRadius: 7, style: .continuous)
                            .stroke(isSelected ? Color.white : Color.white.opacity(0.42), lineWidth: isSelected ? 2.2 : 1.0)
                    )
                    .frame(width: size.width, height: size.height)

                ZStack {
                    ForEach(Array(emitters.enumerated()), id: \.offset) { index, emitter in
                        let t = emitters.count <= 1 ? 0.5 : CGFloat(index) / CGFloat(emitters.count - 1)
                        ZStack {
                            Capsule(style: .continuous)
                                .fill(emitter.color.opacity(emitter.intensity * (0.34 + emitter.intensity * 0.66)))
                                .frame(width: metrics.ledDiameter * 0.76, height: metrics.ledDiameter * 1.62)
                                .blur(radius: 1.1)

                            Capsule(style: .continuous)
                                .fill(emitter.color.opacity(emitter.intensity * (0.42 + emitter.intensity * 0.48)))
                                .frame(width: metrics.ledDiameter * 0.44, height: metrics.ledDiameter * 1.02)
                                .blur(radius: 0.45)

                            Capsule(style: .continuous)
                                .fill(Color.white.opacity(emitter.intensity * (0.08 + emitter.intensity * 0.16)))
                                .frame(width: metrics.ledDiameter * 0.18, height: metrics.ledDiameter * 0.48)
                                .blur(radius: 0.18)
                        }
                        .overlay(
                            Capsule(style: .continuous)
                                .stroke(Color.white.opacity(emitter.intensity * (0.08 + emitter.intensity * 0.10)), lineWidth: 0.4)
                                .frame(width: metrics.ledDiameter * 0.76, height: metrics.ledDiameter * 1.62)
                        )
                        .shadow(color: emitter.color.opacity(emitter.intensity * (0.36 + emitter.intensity * 0.42)), radius: 4.6, x: 0, y: 0)
                            .position(
                                x: 6 + t * max(1, size.width - 12),
                                y: size.height * 0.5
                            )
                    }
                }
                .frame(width: size.width, height: size.height)

                if strobeHighlighted {
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(BeatBeamPalette.triggerActive.opacity(0.82), lineWidth: 1.5)
                        .frame(width: size.width + 8, height: size.height + 8)
                }
            }
            .rotationEffect(.radians(metrics.angleRadians))
            .frame(width: metrics.envelope, height: metrics.envelope)
        }
    }

    private var wallWashEmitters: [WallWashEmitterPreview] {
        wallWashEmitterPreviews(
            editor: editor,
            model: model,
            preview: preview,
            animationTime: animationTime
        )
    }

    private struct WallWashNodeMetrics {
        let size: CGSize
        let angleRadians: CGFloat
        let envelope: CGFloat
        let ledDiameter: CGFloat
    }
}

private func boundedScreenSpaceFixtureMarkerExtent(
    _ proposed: CGFloat,
    minimum: CGFloat,
    maximum: CGFloat
) -> CGFloat {
    min(maximum, max(minimum, proposed))
}

private let beePatternAssetBaseNames: [String: String] = [
    "open": "bee__Open",
    "spoke_star": "bee__Spoke-star",
    "flower": "bee__Flower",
    "swirl": "bee__Swirl",
    "dot_star": "bee__Dot-star",
    "dot_cluster": "bee__Hearts",
    "triskelion": "bee__trisklion",
    "pinwheel_flower": "bee__ice",
]

private final class BeePatternAssetStore {
    static let shared = BeePatternAssetStore()

    private var baseCache: [String: NSImage] = [:]
    private var templateCache: [String: NSImage] = [:]
    private let lock = NSLock()

    func baseImage(patternID: String) -> NSImage? {
        lock.lock()
        if let cached = baseCache[patternID] {
            lock.unlock()
            return cached
        }
        lock.unlock()

        guard
            let url = beePatternAssetURL(patternID: patternID),
            let image = NSImage(contentsOf: url)
        else {
            return nil
        }

        lock.lock()
        baseCache[patternID] = image
        lock.unlock()
        return image
    }

    func templateImage(patternID: String) -> NSImage? {
        lock.lock()
        if let cached = templateCache[patternID] {
            let copy = cached.copy() as? NSImage
            lock.unlock()
            return copy ?? cached
        }
        lock.unlock()

        guard
            let base = baseImage(patternID: patternID),
            let template = base.copy() as? NSImage
        else {
            return nil
        }

        template.isTemplate = true
        lock.lock()
        templateCache[patternID] = template
        let copy = template.copy() as? NSImage
        lock.unlock()
        return copy ?? template
    }
}

private func beatBeamResourceSearchRoots() -> [URL] {
    var roots: [URL] = []

    if let resourceURL = Bundle.main.resourceURL {
        roots.append(resourceURL)
    }

    roots.append(URL(fileURLWithPath: FileManager.default.currentDirectoryPath))

    if let executable = Bundle.main.executableURL {
        roots.append(
            executable
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .deletingLastPathComponent()
        )
    }

    var uniqueRoots: [URL] = []
    for root in roots {
        let normalized = root.standardizedFileURL
        if !uniqueRoots.contains(normalized) {
            uniqueRoots.append(normalized)
        }
    }
    return uniqueRoots
}

private func beePatternAssetURL(patternID: String) -> URL? {
    guard let baseName = beePatternAssetBaseNames[patternID] else { return nil }
    for root in beatBeamResourceSearchRoots() {
        let candidate = root.appendingPathComponent("assets/\(baseName).png")
        if FileManager.default.fileExists(atPath: candidate.path) {
            return candidate
        }
    }
    return nil
}

private func beePatternBaseImage(patternID: String) -> NSImage? {
    BeePatternAssetStore.shared.baseImage(patternID: patternID)
}

private func beePatternTemplateImage(patternID: String) -> NSImage? {
    BeePatternAssetStore.shared.templateImage(patternID: patternID)
}

private func aspectFitRect(for imageSize: CGSize, inside bounds: CGRect) -> CGRect {
    guard imageSize.width > 0, imageSize.height > 0, bounds.width > 0, bounds.height > 0 else {
        return bounds
    }

    let scale = min(bounds.width / imageSize.width, bounds.height / imageSize.height)
    let fittedSize = CGSize(width: imageSize.width * scale, height: imageSize.height * scale)
    return CGRect(
        x: bounds.midX - fittedSize.width * 0.5,
        y: bounds.midY - fittedSize.height * 0.5,
        width: fittedSize.width,
        height: fittedSize.height
    )
}

@MainActor
private func beePatternTintedRasterImage(patternID: String, color: NSColor, size: Int) -> NSImage? {
    let safeSize = max(64, size)
    let canvasSize = NSSize(width: safeSize, height: safeSize)

    if let baseImage = beePatternBaseImage(patternID: patternID) {
        let canvas = NSImage(size: canvasSize)
        canvas.lockFocus()
        defer { canvas.unlockFocus() }

        NSGraphicsContext.current?.imageInterpolation = .high
        let bounds = CGRect(origin: .zero, size: canvasSize)
        let drawRect = aspectFitRect(for: baseImage.size, inside: bounds)
        baseImage.draw(in: drawRect, from: .zero, operation: .sourceOver, fraction: 1.0)
        (color.usingColorSpace(.deviceRGB) ?? color).setFill()
        drawRect.fill(using: .sourceIn)
        return canvas
    }

    let renderer = ImageRenderer(
        content: BeeEyeProceduralPatternGlyph(
            patternID: patternID,
            color: Color(nsColor: color),
            rotationDegrees: 0,
            opacity: 1.0
        )
        .frame(width: CGFloat(safeSize), height: CGFloat(safeSize))
        .background(Color.clear)
    )
    renderer.scale = 2.0
    renderer.isOpaque = false
    return renderer.nsImage
}

@MainActor
private func beePatternMaskRasterImage(patternID: String, size: Int) -> NSImage? {
    let safeSize = max(64, size)
    let canvasSize = NSSize(width: safeSize, height: safeSize)

    if let baseImage = beePatternBaseImage(patternID: patternID) {
        let canvas = NSImage(size: canvasSize)
        canvas.lockFocus()
        defer { canvas.unlockFocus() }

        NSGraphicsContext.current?.imageInterpolation = .high
        let bounds = CGRect(origin: .zero, size: canvasSize)
        let drawRect = aspectFitRect(for: baseImage.size, inside: bounds)
        baseImage.draw(in: drawRect, from: .zero, operation: .copy, fraction: 1.0)
        return canvas
    }

    let renderer = ImageRenderer(
        content: BeeEyeProceduralPatternGlyph(
            patternID: patternID,
            color: .white,
            rotationDegrees: 0,
            opacity: 1.0
        )
        .frame(width: CGFloat(safeSize), height: CGFloat(safeSize))
        .background(Color.clear)
    )
    renderer.scale = 2.0
    renderer.isOpaque = false
    return renderer.nsImage
}

struct BeeEyePatternGlyph: View {
    let patternID: String
    let color: Color
    let rotationDegrees: Double
    let opacity: Double

    var body: some View {
        if let assetImage = beePatternTemplateImage(patternID: patternID) {
            Image(nsImage: assetImage)
                .renderingMode(.template)
                .resizable()
                .scaledToFit()
                .foregroundStyle(color.opacity(opacity))
                .rotationEffect(Angle.degrees(rotationDegrees))
        } else {
            BeeEyeProceduralPatternGlyph(
                patternID: patternID,
                color: color,
                rotationDegrees: rotationDegrees,
                opacity: opacity
            )
        }
    }
}

private struct BeeEyeProceduralPatternGlyph: View {
    let patternID: String
    let color: Color
    let rotationDegrees: Double
    let opacity: Double

    var body: some View {
        GeometryReader { geometry in
            let size = min(geometry.size.width, geometry.size.height)
            let center = CGPoint(x: geometry.size.width / 2, y: geometry.size.height / 2)
            let fill = color.opacity(opacity)

            ZStack {
                switch patternID {
                case "spoke_star":
                    ForEach(0..<5, id: \.self) { index in
                        let armRotation = Double(index) * 72.0 + 18.0
                        ZStack {
                            Capsule(style: .continuous)
                                .fill(fill)
                                .frame(width: size * 0.08, height: size * 0.48)
                                .offset(x: -size * 0.05, y: -size * 0.11)
                            Capsule(style: .continuous)
                                .fill(fill)
                                .frame(width: size * 0.08, height: size * 0.48)
                                .offset(x: size * 0.05, y: -size * 0.11)
                        }
                        .rotationEffect(.degrees(armRotation))
                    }
                case "flower":
                    ForEach(0..<5, id: \.self) { index in
                        BeePetalShape()
                            .fill(fill)
                            .frame(width: size * 0.27, height: size * 0.38)
                            .offset(y: -size * 0.21)
                            .rotationEffect(.degrees(Double(index) * 72.0))
                    }
                    Circle()
                        .fill(Color.black.opacity(0.55))
                        .frame(width: size * 0.15, height: size * 0.15)
                case "swirl":
                    ForEach(0..<5, id: \.self) { index in
                        BeePetalShape()
                            .fill(fill)
                            .frame(width: size * 0.24, height: size * 0.40)
                            .offset(x: size * 0.12, y: -size * 0.11)
                            .rotationEffect(.degrees(Double(index) * 72.0 + 24.0))
                    }
                case "dot_star":
                    ForEach(dotStarPoints(size: size).indices, id: \.self) { index in
                        let point = dotStarPoints(size: size)[index]
                        Circle()
                            .fill(fill)
                            .frame(width: point.size, height: point.size)
                            .position(x: center.x + point.x, y: center.y + point.y)
                    }
                case "dot_cluster":
                    ForEach(clusterOffsets(size: size).indices, id: \.self) { index in
                        let point = clusterOffsets(size: size)[index]
                        BeePetalShape()
                            .fill(fill)
                            .frame(width: point.size * 0.92, height: point.size * 1.18)
                            .rotationEffect(.degrees(point.rotation))
                            .position(x: center.x + point.x, y: center.y + point.y)
                    }
                case "triskelion":
                    ForEach(0..<3, id: \.self) { index in
                        Circle()
                            .trim(from: 0.10, to: 0.72)
                            .stroke(fill, style: StrokeStyle(lineWidth: size * 0.10, lineCap: .round))
                            .frame(width: size * 0.44, height: size * 0.44)
                            .offset(x: size * 0.14, y: -size * 0.08)
                            .rotationEffect(.degrees(Double(index) * 120.0 + 14.0))
                    }
                    Circle()
                        .fill(Color.black.opacity(0.70))
                        .frame(width: size * 0.14, height: size * 0.14)
                case "pinwheel_flower":
                    ForEach(0..<5, id: \.self) { index in
                        BeePetalShape()
                            .fill(fill)
                            .frame(width: size * 0.25, height: size * 0.40)
                            .offset(x: size * 0.10, y: -size * 0.13)
                            .rotationEffect(.degrees(Double(index) * 72.0 + 34.0))
                        Ellipse()
                            .fill(Color.black.opacity(0.62))
                            .frame(width: size * 0.07, height: size * 0.15)
                            .offset(x: size * 0.03, y: -size * 0.07)
                            .rotationEffect(.degrees(Double(index) * 72.0 + 34.0))
                    }
                default:
                    EmptyView()
                }
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
            .rotationEffect(.degrees(rotationDegrees))
        }
    }

    private func dotStarPoints(size: CGFloat) -> [(x: CGFloat, y: CGFloat, size: CGFloat)] {
        let armCount = 8
        let radii: [CGFloat] = [0.14, 0.28, 0.42, 0.56]
        let sizes: [CGFloat] = [0.07, 0.08, 0.09, 0.10]
        var points: [(x: CGFloat, y: CGFloat, size: CGFloat)] = []
        for arm in 0..<armCount {
            let angle = CGFloat(arm) * (.pi / 4.0)
            for (index, radius) in radii.enumerated() {
                points.append((
                    x: cos(angle) * size * radius,
                    y: sin(angle) * size * radius,
                    size: size * sizes[index]
                ))
            }
        }
        return points
    }

    private func clusterOffsets(size: CGFloat) -> [(x: CGFloat, y: CGFloat, size: CGFloat, rotation: Double)] {
        [
            (-size * 0.22, -size * 0.20, size * 0.12, -30),
            (-size * 0.08, -size * 0.24, size * 0.11, -22),
            (size * 0.07, -size * 0.23, size * 0.11, -12),
            (size * 0.20, -size * 0.18, size * 0.10, -6),
            (-size * 0.25, -size * 0.04, size * 0.10, -34),
            (-size * 0.11, -size * 0.06, size * 0.11, -24),
            (size * 0.03, -size * 0.05, size * 0.11, -16),
            (size * 0.16, -size * 0.02, size * 0.10, -8),
            (size * 0.28, 0, size * 0.09, 0),
            (-size * 0.19, size * 0.12, size * 0.10, -28),
            (-size * 0.05, size * 0.11, size * 0.11, -18),
            (size * 0.09, size * 0.12, size * 0.10, -8),
            (size * 0.22, size * 0.14, size * 0.09, 0),
            (-size * 0.09, size * 0.24, size * 0.10, -18),
            (size * 0.06, size * 0.24, size * 0.09, -10),
            (size * 0.20, size * 0.22, size * 0.08, -2),
        ]
    }
}

private struct BeePetalShape: Shape {
    func path(in rect: CGRect) -> Path {
        let top = CGPoint(x: rect.midX, y: rect.minY)
        let left = CGPoint(x: rect.minX + rect.width * 0.16, y: rect.midY)
        let right = CGPoint(x: rect.maxX - rect.width * 0.16, y: rect.midY)
        let bottom = CGPoint(x: rect.midX, y: rect.maxY)

        var path = Path()
        path.move(to: top)
        path.addCurve(
            to: left,
            control1: CGPoint(x: rect.minX + rect.width * 0.40, y: rect.minY + rect.height * 0.06),
            control2: CGPoint(x: rect.minX + rect.width * 0.02, y: rect.minY + rect.height * 0.34)
        )
        path.addQuadCurve(
            to: bottom,
            control: CGPoint(x: rect.minX + rect.width * 0.26, y: rect.maxY - rect.height * 0.02)
        )
        path.addQuadCurve(
            to: right,
            control: CGPoint(x: rect.maxX - rect.width * 0.26, y: rect.maxY - rect.height * 0.02)
        )
        path.addCurve(
            to: top,
            control1: CGPoint(x: rect.maxX - rect.width * 0.02, y: rect.minY + rect.height * 0.34),
            control2: CGPoint(x: rect.maxX - rect.width * 0.40, y: rect.minY + rect.height * 0.06)
        )
        path.closeSubpath()
        return path
    }
}

@MainActor
private func renderBeePatternTextureImage(patternID: String, size: Int) -> NSImage? {
    beePatternTintedRasterImage(patternID: patternID, color: .white, size: size)
}

struct ProjectionFixtureNode: View {
    @EnvironmentObject private var model: AppModel
    let editor: SlotEditor
    let preview: SlotPreview?
    let stageMotion: StageMotionState?
    let isSelected: Bool
    let showDiagnostics: Bool
    let animationTime: TimeInterval
    let projection: StageProjection
    let editMode: Bool
    let interactive: Bool
    let selectionMode: ProjectionSelectionMode
    let normalizedOrigin: CGPoint
    let absoluteOrigin: CGPoint
    let canvasSize: CGSize

    @State private var dragStartNormalized: CGPoint?
    @State private var dragSnapEnabled: Bool?

    var body: some View {
        let worldOrigin = model.worldPosition(for: editor.id)
        let node = StageFixtureNode(
            editor: editor,
            anchor: currentAnchor,
            worldOrigin: worldOrigin,
            preview: preview,
            stageMotion: stageMotion,
            isSelected: isSelected,
            showDiagnostics: showDiagnostics,
            animationTime: animationTime,
            projection: projection,
            canvasSize: canvasSize,
            action: editMode ? nil : tapAction
        )
        .position(absoluteOrigin)

        ZStack {
            if calibrationHighlighted {
                calibrationAxisArrow(for: worldOrigin)
            } else if projection == .top {
                ProjectionOrientationArrow(
                    start: absoluteOrigin,
                    end: orientationArrowTarget(for: worldOrigin),
                    color: orientationArrowColor,
                    highlighted: isSelected || editMode
                )
            }

            if editMode {
                node.highPriorityGesture(dragGesture)
            } else {
                node
            }
        }
    }

    private var dragGesture: some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                let base = dragStartNormalized ?? normalizedOrigin
                if dragStartNormalized == nil {
                    dragStartNormalized = normalizedOrigin
                    // Capture once so changing SNAP cannot make an active drag
                    // jump between quantized and continuous coordinates.
                    dragSnapEnabled = model.fixtureSnapEnabled
                    model.selectSlot(editor.id)
                }
                let next = CGPoint(
                    x: base.x + (value.translation.width / max(1, canvasSize.width)),
                    y: base.y + (value.translation.height / max(1, canvasSize.height))
                )
                model.updateProjectionPoint(
                    for: editor.id,
                    projection: projection,
                    point: next,
                    snapEnabled: dragSnapEnabled
                )
            }
            .onEnded { _ in
                dragStartNormalized = nil
                dragSnapEnabled = nil
            }
    }

    private var tapAction: (() -> Void)? {
        switch selectionMode {
        case .none:
            return nil
        case .editor:
            return interactive ? { model.selectSlot(editor.id) } : nil
        case .preview:
            guard editor.supportsPan || editor.supportsTilt else { return nil }
            return { model.togglePreviewSelection(editor.id) }
        }
    }

    private var currentAnchor: StageAnchor? {
        StageAnchor(rawValue: model.anchorAssignment(for: editor.id))
    }

    private func orientationArrowTarget(for worldOrigin: SlotWorldPosition) -> CGPoint {
        if calibrationHighlighted {
            return calibrationAxisTarget(venueOrientationBasis(for: worldOrigin).forward, worldOrigin: worldOrigin)
        }
        let endpoint = worldOrientationEndpoint(worldOrigin, distance: 45)
        return worldProjectedAbsoluteBeamPoint(endpoint, projection: projection, size: canvasSize)
    }

    private var calibrationHighlighted: Bool {
        model.isFixtureCalibrationMode && model.selectedSlotID == editor.id && (editor.supportsPan || editor.supportsTilt)
    }

    @ViewBuilder
    private func calibrationAxisArrow(for worldOrigin: SlotWorldPosition) -> some View {
        switch projection {
        case .top:
            ProjectionOrientationArrow(
                start: absoluteOrigin,
                end: calibrationAxisTarget(venueOrientationBasis(for: worldOrigin).forward, worldOrigin: worldOrigin),
                color: BeatBeamPalette.brandAmber,
                highlighted: true,
                label: "FORWARD"
            )
        case .front, .back, .side:
            ProjectionOrientationArrow(
                start: absoluteOrigin,
                end: calibrationAxisTarget(venueOrientationBasis(for: worldOrigin).up, worldOrigin: worldOrigin),
                color: BeatBeamPalette.brandMagenta,
                highlighted: true,
                label: "UP"
            )
        }
    }

    private func calibrationAxisTarget(_ vector: VenueVectorState, worldOrigin: SlotWorldPosition) -> CGPoint {
        let distance = 70.0
        let endpoint = SlotWorldPosition(
            x: worldOrigin.x + vector.x * distance,
            y: worldOrigin.y + vector.y * distance,
            z: worldOrigin.z + vector.z * distance,
            yawDegrees: worldOrigin.yawDegrees,
            pitchDegrees: worldOrigin.pitchDegrees,
            rollDegrees: worldOrigin.rollDegrees
        )
        return worldProjectedAbsoluteBeamPoint(endpoint, projection: projection, size: canvasSize)
    }

    private var orientationArrowColor: Color {
        if let preview, preview.enabled {
            return slotPreviewBaseColor(preview)
        }
        return Color.white.opacity(0.72)
    }
}

struct ProjectionOrientationArrow: View {
    let start: CGPoint
    let end: CGPoint
    let color: Color
    let highlighted: Bool
    var label: String? = nil

    var body: some View {
        let dx = end.x - start.x
        let dy = end.y - start.y
        let length = hypot(dx, dy)
        let angle = atan2(dy, dx)
        let displayLength = highlighted ? max(32, min(62, length)) : max(14, min(34, length))
        let opacity = highlighted ? 0.92 : 0.42
        let tip = endPoint(from: start, angle: angle, length: displayLength)

        ZStack {
            Path { path in
                path.move(to: start)
                path.addLine(to: tip)
            }
            .stroke(color.opacity(opacity), style: StrokeStyle(lineWidth: highlighted ? 2.2 : 1.4, lineCap: .round))

            Path { path in
                path.move(to: tip)
                path.addLine(to: endPoint(from: tip, angle: angle + .pi * 0.78, length: 6))
                path.move(to: tip)
                path.addLine(to: endPoint(from: tip, angle: angle - .pi * 0.78, length: 6))
            }
            .stroke(color.opacity(opacity), style: StrokeStyle(lineWidth: highlighted ? 2.1 : 1.2, lineCap: .round))

            if let label {
                Text(label)
                    .font(.system(size: 8, weight: .bold, design: .monospaced))
                    .foregroundStyle(color)
                    .padding(.horizontal, 5)
                    .padding(.vertical, 3)
                    .background(Color.black.opacity(0.78))
                    .overlay(Capsule().stroke(color.opacity(0.92), lineWidth: 1))
                    .clipShape(Capsule())
                    .position(labelPosition(from: start, to: tip))
            }
        }
        .blendMode(.screen)
    }

    private func endPoint(from origin: CGPoint, angle: CGFloat, length: CGFloat) -> CGPoint {
        CGPoint(
            x: origin.x + cos(angle) * length,
            y: origin.y + sin(angle) * length
        )
    }

    private func labelPosition(from start: CGPoint, to tip: CGPoint) -> CGPoint {
        CGPoint(
            x: start.x + (tip.x - start.x) * 0.66,
            y: start.y + (tip.y - start.y) * 0.66 - 13
        )
    }
}

struct EditModeBanner: View {
    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "cursorarrow.motionlines")
                .font(.system(size: 11, weight: .bold))
            Text("EDIT MODE")
                .font(.system(size: 11, weight: .bold, design: .monospaced))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(Color.black.opacity(0.58))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(BeatBeamPalette.triggerActive.opacity(0.48), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

struct PreviewFineTuneSheet: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if selection.count == 1, let editor = selection.first {
                        SingleMovingHeadFineTuneSection(editor: editor)
                    } else {
                        MultiMovingHeadFineTuneSection(editors: selection)
                    }
                }
                .padding(20)
            }
            .navigationTitle("Fine Tune")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") {
                        dismiss()
                    }
                }
            }
        }
        .frame(minWidth: 520, minHeight: 380)
    }

    private var selection: [SlotEditor] {
        model.previewSelectedMovingHeadEditors
    }
}

struct SingleMovingHeadFineTuneSection: View {
    @EnvironmentObject private var model: AppModel
    @ObservedObject var editor: SlotEditor

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 6) {
                Text(editor.label)
                    .font(.system(size: 18, weight: .semibold))
                Text("Pan/Tilt preview test. Bij de eerste wijziging gaat sync voor deze head uit.")
                    .font(.system(size: 12, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
            }

            FineTuneSliderRow(
                title: "Pan",
                value: Binding(
                    get: { Double(editor.pan) },
                    set: { model.setPreviewFineTune(slotID: editor.id, pan: Int($0.rounded())) }
                ),
                displayValue: editor.pan
            )

            FineTuneSliderRow(
                title: "Tilt",
                value: Binding(
                    get: { Double(editor.tilt) },
                    set: { model.setPreviewFineTune(slotID: editor.id, tilt: Int($0.rounded())) }
                ),
                displayValue: editor.tilt
            )

            FineTuneNudgeGrid(singleEditorID: editor.id)
        }
    }
}

struct MultiMovingHeadFineTuneSection: View {
    let editors: [SlotEditor]

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 6) {
                Text("\(editors.count) moving heads")
                    .font(.system(size: 18, weight: .semibold))
                Text("Pan/Tilt nudge wordt als relatieve correctie op alle geselecteerde heads toegepast.")
                    .font(.system(size: 12, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 4) {
                ForEach(editors) { editor in
                    Text(editor.label)
                        .font(.system(size: 12, weight: .medium, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
            }

            FineTuneNudgeGrid(singleEditorID: nil)
        }
    }
}

struct FineTuneSliderRow: View {
    let title: String
    let value: Binding<Double>
    let displayValue: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(title)
                    .font(.system(size: 13, weight: .semibold))
                Spacer()
                Text("\(displayValue)")
                    .font(.system(size: 12, weight: .semibold, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
            Slider(value: value, in: 0...255, step: 1)
        }
    }
}

struct FineTuneNudgeGrid: View {
    @EnvironmentObject private var model: AppModel
    let singleEditorID: String?

    private let steps = [-20, -5, -1, 1, 5, 20]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            fineTuneRow(title: "Pan", isPan: true)
            fineTuneRow(title: "Tilt", isPan: false)
        }
    }

    @ViewBuilder
    private func fineTuneRow(title: String, isPan: Bool) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 13, weight: .semibold))
            HStack(spacing: 8) {
                ForEach(steps, id: \.self) { step in
                    Button(step > 0 ? "+\(step)" : "\(step)") {
                        if let singleEditorID {
                            model.setPreviewFineTune(
                                slotID: singleEditorID,
                                pan: isPan ? currentValue(for: singleEditorID, isPan: true) + step : nil,
                                tilt: isPan ? nil : currentValue(for: singleEditorID, isPan: false) + step
                            )
                        } else {
                            model.nudgePreviewSelection(
                                panDelta: isPan ? step : 0,
                                tiltDelta: isPan ? 0 : step
                            )
                        }
                    }
                    .buttonStyle(.bordered)
                }
            }
        }
    }

    private func currentValue(for slotID: String, isPan: Bool) -> Int {
        guard let editor = model.previewSelectedMovingHeadEditors.first(where: { $0.id == slotID }) else { return 127 }
        return isPan ? editor.pan : editor.tilt
    }
}

struct MapPreviewWindowView: View {
    @EnvironmentObject private var model: AppModel
    @State private var showFineTune = false

    var body: some View {
        ZStack {
            BeatBeamPalette.appBackground
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 14) {
                if !model.previewSelectedMovingHeadEditors.isEmpty {
                    HStack(spacing: 10) {
                        Text(selectionLabel)
                            .font(.system(size: 12, weight: .semibold, design: .monospaced))
                            .foregroundStyle(.secondary)
                        Spacer()
                        Button("Clear") {
                            model.clearPreviewSelection()
                        }
                        .buttonStyle(.bordered)

                        Button("Fine Tune") {
                            showFineTune = true
                        }
                        .buttonStyle(.borderedProminent)
                    }
                }

                StageProjectionDeckView(
                    showControls: true,
                    topInteractive: false,
                    showSelection: true,
                    showAnchorLabels: false,
                    selectionMode: .preview
                )
            }
            .padding(24)
        }
        .frame(minWidth: 1460, minHeight: 780)
        .sheet(isPresented: $showFineTune) {
            PreviewFineTuneSheet()
                .environmentObject(model)
        }
        .onChange(of: model.previewSelectedMovingHeadEditors.count) {
            if model.previewSelectedMovingHeadEditors.isEmpty {
                showFineTune = false
            }
        }
    }

    private var selectionLabel: String {
        let count = model.previewSelectedMovingHeadEditors.count
        return count == 1 ? "1 moving head selected" : "\(count) moving heads selected"
    }
}

struct StageFixtureBeam: View {
    enum BeamKind {
        case movingHead
        case wallWash
        case staticWash
    }

    let origin: CGPoint
    let worldOrigin: SlotWorldPosition
    let mountYawDegrees: Double
    let mountPitchDegrees: Double
    let preview: SlotPreview
    let stageMotion: StageMotionState?
    let venueTargetPreview: VenueTargetPreviewVisual?
    let beamKind: BeamKind
    let wallWashEmitters: [WallWashEmitterPreview]
    let color: Color
    let projection: StageProjection
    let size: CGSize
    let animationTime: TimeInterval

    var body: some View {
        let state = stageMotion
        let strobeFactor = slotPreviewStrobeFactor(preview, at: animationTime)
        let isMovingHead = beamKind == .movingHead
        let isWallWash = beamKind == .wallWash
        let isBeeEye = isMovingHead && slotPreviewIsBeeEye(preview)
        let washColor = slotPreviewBaseColor(preview)
        let spotColor = slotPreviewResolvedSpotColor(preview, at: animationTime)
        let washBrightness = effectivePreviewBrightness(preview, at: animationTime)
        let spotBrightness = effectiveSpotPreviewBrightness(preview, at: animationTime)
        let brightness = (
            isBeeEye
                ? max(washBrightness, spotBrightness)
                : (beamKind == .movingHead && (preview.spotBrightness ?? 0) > 10 ? spotBrightness : washBrightness)
        )
        let pulseBoost = preview.strobeActive ? CGFloat(strobeFactor) : 0
        let activeColor = isBeeEye ? spotColor : color
        let wideBeam: CGFloat = isMovingHead ? 34.0 : isWallWash ? 20.0 : 11.0
        let coreBeam: CGFloat = isMovingHead ? 8.0 : isWallWash ? 6.0 : 3.8
        let spotSize: CGFloat = isMovingHead ? 34.0 : isWallWash ? 24.0 : 14.0
        let currentTarget = currentBeamTarget(from: state)
        let targetPoint = targetBeamTarget(from: state)
        let trailTargets = trailBeamTargets(from: state)
        let lagDistance = hypot(currentTarget.x - targetPoint.x, currentTarget.y - targetPoint.y)

        return ZStack {
            ForEach(Array(trailTargets.enumerated()), id: \.offset) { index, target in
                let trailFactor = Double(index + 1) / Double(max(trailTargets.count, 1))
                let ghostOpacity = 0.05 + 0.14 * trailFactor
                Path { path in
                    path.move(to: origin)
                    path.addLine(to: target)
                }
                .stroke(activeColor.opacity((isMovingHead ? 0.10 : isWallWash ? 0.06 : 0.04 + brightness * 0.06) * ghostOpacity), style: StrokeStyle(lineWidth: wideBeam * CGFloat(ghostOpacity), lineCap: .round))
                .blur(radius: isMovingHead ? 8 : isWallWash ? 5 : 2.5)
                .blendMode(.screen)

                Circle()
                    .fill(activeColor.opacity((isMovingHead ? 0.16 : isWallWash ? 0.12 : 0.08 + brightness * 0.10) * ghostOpacity))
                    .frame(width: spotSize * CGFloat(0.24 + trailFactor * (isMovingHead ? 0.34 : isWallWash ? 0.26 : 0.18)), height: spotSize * CGFloat(0.24 + trailFactor * (isMovingHead ? 0.34 : isWallWash ? 0.26 : 0.18)))
                    .position(target)
                    .blur(radius: isMovingHead ? 3.2 : isWallWash ? 2.4 : 1.4)
                    .blendMode(.screen)
            }

            if venueTargetPreview == nil, lagDistance > 10 {
                Circle()
                    .stroke(activeColor.opacity(0.55), style: StrokeStyle(lineWidth: 2, dash: [4, 4]))
                    .frame(width: 18, height: 18)
                    .position(targetPoint)

                Path { path in
                    path.move(to: currentTarget)
                    path.addLine(to: targetPoint)
                }
                .stroke(activeColor.opacity(0.18), style: StrokeStyle(lineWidth: 1.6, lineCap: .round, dash: [5, 4]))
            }

            if isBeeEye {
                movingHeadConeLayer(
                    target: currentTarget,
                    brightness: washBrightness,
                    pulseBoost: pulseBoost * 0.45,
                    outer: true,
                    beamColor: washColor,
                    widthScale: 1.45
                )

                movingHeadConeLayer(
                    target: currentTarget,
                    brightness: washBrightness * 0.86,
                    pulseBoost: pulseBoost * 0.35,
                    outer: false,
                    beamColor: washColor,
                    widthScale: 1.12
                )

                movingHeadConeLayer(
                    target: currentTarget,
                    brightness: spotBrightness,
                    pulseBoost: pulseBoost,
                    outer: true,
                    beamColor: spotColor,
                    widthScale: 0.62
                )

                movingHeadConeLayer(
                    target: currentTarget,
                    brightness: spotBrightness,
                    pulseBoost: pulseBoost,
                    outer: false,
                    beamColor: spotColor,
                    widthScale: 0.42
                )
            } else if isMovingHead {
                movingHeadConeLayer(
                    target: currentTarget,
                    brightness: brightness,
                    pulseBoost: pulseBoost,
                    outer: true
                )

                movingHeadConeLayer(
                    target: currentTarget,
                    brightness: brightness,
                    pulseBoost: pulseBoost,
                    outer: false
                )
            } else if !isWallWash {
                Path { path in
                    path.move(to: origin)
                    path.addLine(to: currentTarget)
                }
                .stroke(
                    activeColor.opacity((isMovingHead ? 0.12 : isWallWash ? 0.10 : 0.04) + brightness * (isMovingHead ? 0.24 : isWallWash ? 0.16 : 0.08) + pulseBoost * (isMovingHead ? 0.18 : isWallWash ? 0.10 : 0.05)),
                    style: StrokeStyle(lineWidth: wideBeam, lineCap: .round)
                )
                .blur(radius: isMovingHead ? 10 : isWallWash ? 6 : 3)
                .blendMode(.screen)
            }

            if !isWallWash {
                Path { path in
                    path.move(to: origin)
                    path.addLine(to: currentTarget)
                }
                .stroke(
                    activeColor.opacity(
                        isMovingHead
                            ? (0.08 + brightness * 0.10 + pulseBoost * 0.05)
                            : 0.20 + brightness * 0.14 + pulseBoost * 0.05
                    ),
                    style: StrokeStyle(
                        lineWidth: isMovingHead
                            ? 1.6
                            : coreBeam,
                        lineCap: .round
                    )
                )
                .blendMode(.plusLighter)
            }

            if isBeeEye {
                beeEyeBeamHit(
                    target: currentTarget,
                    washColor: washColor,
                    spotColor: spotColor,
                    washBrightness: washBrightness,
                    spotBrightness: spotBrightness,
                    pulseBoost: pulseBoost,
                    spotSize: spotSize
                )
            } else {
                Circle()
                    .fill(activeColor.opacity((isMovingHead ? 0.28 : isWallWash ? 0.18 : 0.12) + brightness * (isMovingHead ? 0.54 : isWallWash ? 0.24 : 0.18) + pulseBoost * (isMovingHead ? 0.16 : isWallWash ? 0.08 : 0.05)))
                    .frame(width: spotSize, height: spotSize)
                    .position(currentTarget)
                    .blur(radius: isMovingHead ? 4 : isWallWash ? 2.6 : 1.4)
                    .blendMode(.screen)
            }

            if preview.strobeActive && pulseBoost > 0.5 {
                Circle()
                    .fill(Color.white.opacity(0.18 + pulseBoost * 0.22))
                    .frame(width: spotSize * 1.45, height: spotSize * 1.45)
                    .position(currentTarget)
                    .blur(radius: 5.5)
                    .blendMode(.plusLighter)
            }
        }
        .drawingGroup(opaque: false, colorMode: .linear)
    }

    @ViewBuilder
    private func beeEyeBeamHit(target: CGPoint, washColor: Color, spotColor: Color, washBrightness: CGFloat, spotBrightness: CGFloat, pulseBoost: CGFloat, spotSize: CGFloat) -> some View {
        if projection == .top {
            let patternID = slotPreviewResolvedPatternID(preview, at: animationTime)
            let patternRotation = slotPreviewResolvedPatternRotation(preview, at: animationTime)
            let isOpenPattern = patternID == "open" || (preview.spotPatternOpen ?? false)
            let beeMode = slotPreviewResolvedBeeEffectMode(preview)
            let spread = slotPreviewBeeSpread(preview)
            let backgroundLevel = slotPreviewBeeBackgroundLevel(preview)
            let softness = slotPreviewBeeSoftness(preview)
            let shapeTransition = slotPreviewBeeShapeTransition(preview)
            let clusterSpacing = spotSize * 1.72 * spread
            let cellSize = spotSize * (isOpenPattern ? 1.52 : 1.84) * (0.94 + softness * 0.16 + (beeMode == .wash ? 0.06 : 0.0))
            ZStack {
                Circle()
                    .fill(washColor.opacity((0.04 + washBrightness * 0.10) * (0.44 + backgroundLevel * 0.72)))
                    .frame(
                        width: spotSize * (1.90 + backgroundLevel * 0.62 + softness * 0.18),
                        height: spotSize * (1.90 + backgroundLevel * 0.62 + softness * 0.18)
                    )
                    .blur(radius: 4.0 + softness * 3.4)

                ZStack {
                    ForEach(0..<3, id: \.self) { index in
                        let offset = beeEyeTripletOffset(index, spacing: clusterSpacing)
                        let washGhostOpacityRaw: CGFloat = (0.06 + spotBrightness * 0.12) * (0.20 + shapeTransition * 0.60)
                        let washGhostOpacity = Double(washGhostOpacityRaw)
                        let washGhostSize: CGFloat = cellSize * (1.26 + shapeTransition * 0.16)
                        let spotOuterSize: CGFloat = cellSize * (1.08 + shapeTransition * 0.10)
                        let spotOuterBlur: CGFloat = 1.2 + softness * 1.8 + shapeTransition * 1.2
                        let patternContainerBlur: CGFloat = 0.08 + softness * 0.18
                        let washPatternOpacityRaw: CGFloat = (0.06 + washBrightness * 0.10) * (0.18 + backgroundLevel * 0.42)
                        let washPatternOpacity = Double(washPatternOpacityRaw)
                        let washPatternSize: CGFloat = cellSize * (1.24 + backgroundLevel * 0.10)
                        let washPatternBlur: CGFloat = 2.2 + softness * 2.0
                        Circle()
                            .fill(washColor.opacity((0.08 + washBrightness * 0.18) * (0.34 + backgroundLevel * 0.84)))
                            .frame(width: cellSize * (1.00 + backgroundLevel * 0.18), height: cellSize * (1.00 + backgroundLevel * 0.18))
                            .offset(x: offset.width, y: offset.height)
                            .blur(radius: 2.2 + softness * 2.6)

                        if isOpenPattern {
                            Circle()
                                .fill(spotColor.opacity(0.22 + spotBrightness * 0.72 + pulseBoost * 0.12))
                                .frame(width: cellSize * (beeMode == .beam ? 0.92 : 1.0), height: cellSize * (beeMode == .beam ? 0.92 : 1.0))
                                .offset(x: offset.width, y: offset.height)
                                .blur(radius: 1.2 + softness * 1.2)
                        } else {
                            ZStack {
                                BeeEyePatternGlyph(
                                    patternID: patternID,
                                    color: washColor,
                                    rotationDegrees: 0,
                                    opacity: washGhostOpacity
                                )
                                .frame(width: washGhostSize, height: washGhostSize)
                                .blur(radius: 3.0 + shapeTransition * 2.8)

                                BeeEyePatternGlyph(
                                    patternID: patternID,
                                    color: spotColor,
                                    rotationDegrees: 0,
                                    opacity: Double(0.34 + spotBrightness * 0.40 + pulseBoost * 0.08)
                                )
                                .frame(width: spotOuterSize, height: spotOuterSize)
                                .blur(radius: spotOuterBlur)

                                BeeEyePatternGlyph(
                                    patternID: patternID,
                                    color: spotColor,
                                    rotationDegrees: 0,
                                    opacity: Double(0.22 + spotBrightness * 0.24)
                                )
                                .frame(width: cellSize * 1.02, height: cellSize * 1.02)

                                BeeEyePatternGlyph(
                                    patternID: patternID,
                                    color: Color.white,
                                    rotationDegrees: 0,
                                    opacity: max(0.52, Double(spotBrightness))
                                )
                                .frame(width: cellSize * 0.96, height: cellSize * 0.96)
                            }
                            .frame(width: cellSize * 1.16, height: cellSize * 1.16)
                            .offset(x: offset.width, y: offset.height)
                            .blur(radius: patternContainerBlur)
                            .blendMode(.screen)

                            BeeEyePatternGlyph(
                                patternID: patternID,
                                color: washColor,
                                rotationDegrees: 0,
                                opacity: washPatternOpacity
                            )
                            .frame(width: washPatternSize, height: washPatternSize)
                            .offset(x: offset.width, y: offset.height)
                            .blur(radius: washPatternBlur)
                            .blendMode(.screen)
                        }
                    }
                }
                .rotationEffect(.degrees(patternRotation))
            }
            .position(target)
            .blendMode(.screen)
        } else {
            Circle()
                .fill(washColor.opacity(0.10 + washBrightness * 0.26))
                .frame(width: spotSize * 1.55, height: spotSize * 1.55)
                .position(target)
                .blur(radius: 4)
                .blendMode(.screen)

            Circle()
                .fill(spotColor.opacity(0.20 + spotBrightness * 0.68 + pulseBoost * 0.12))
                .frame(width: spotSize * 0.78, height: spotSize * 0.78)
                .position(target)
                .blur(radius: 2.4)
                .blendMode(.screen)
        }
    }

    private func beeEyeTripletOffset(_ index: Int, spacing: CGFloat, rotationDegrees: Double = 0) -> CGSize {
        let baseOffset: CGSize
        switch index {
        case 0:
            baseOffset = CGSize(width: 0, height: -spacing * 0.70)
        case 1:
            baseOffset = CGSize(width: -spacing * 0.68, height: spacing * 0.42)
        default:
            baseOffset = CGSize(width: spacing * 0.68, height: spacing * 0.42)
        }

        guard abs(rotationDegrees) > 0.0001 else { return baseOffset }
        let radians = CGFloat(rotationDegrees * .pi / 180.0)
        let cosine = cos(radians)
        let sine = sin(radians)
        return CGSize(
            width: baseOffset.width * cosine - baseOffset.height * sine,
            height: baseOffset.width * sine + baseOffset.height * cosine
        )
    }

    @ViewBuilder
    private func beeEyePatternHit(color: Color, brightness: CGFloat, size: CGFloat, target: CGPoint? = nil) -> some View {
        let patternID = slotPreviewResolvedPatternID(preview, at: animationTime)
        if patternID != "open" && !(preview.spotPatternOpen ?? false) && brightness > 0.04 {
            let glyph = BeeEyePatternGlyph(
                patternID: patternID,
                color: Color.white,
                rotationDegrees: slotPreviewResolvedPatternRotation(preview, at: animationTime),
                opacity: max(0.52, Double(brightness))
            )
            .frame(width: size, height: size)
            .background(
                Circle()
                    .fill(color.opacity(0.08 + brightness * 0.14))
            )
            .blur(radius: 0.2 + brightness * 0.5)
            .blendMode(.screen)

            if let target {
                glyph.position(target)
            } else {
                glyph
            }
        }
    }

    @ViewBuilder
    private func movingHeadConeLayer(target: CGPoint, brightness: CGFloat, pulseBoost: CGFloat, outer: Bool, beamColor: Color? = nil, widthScale: CGFloat = 1.0) -> some View {
        let activeBeamColor = beamColor ?? color
        conePath(to: target, outer: outer, brightness: brightness, pulseBoost: pulseBoost, widthScale: widthScale)
            .fill(
                activeBeamColor.opacity(
                    outer
                        ? (0.14 + brightness * 0.12 + pulseBoost * 0.05)
                        : (0.22 + brightness * 0.18 + pulseBoost * 0.08)
                )
            )
            .blur(radius: outer ? 12 : 6)
            .blendMode(.screen)
    }

    private func conePath(to target: CGPoint, outer: Bool, brightness: CGFloat, pulseBoost: CGFloat, widthScale: CGFloat = 1.0) -> Path {
        let dx = target.x - origin.x
        let dy = target.y - origin.y
        let length = max(1, hypot(dx, dy))
        let nx = dx / length
        let ny = dy / length
        let px = -ny
        let py = nx

        let nearWidth: CGFloat = (outer ? 2.4 : 1.1) * widthScale
        let farWidth: CGFloat = outer
            ? 40 * widthScale
            : 22 * widthScale

        let nearLeft = CGPoint(x: origin.x + px * nearWidth, y: origin.y + py * nearWidth)
        let nearRight = CGPoint(x: origin.x - px * nearWidth, y: origin.y - py * nearWidth)
        let farLeft = CGPoint(x: target.x + px * farWidth, y: target.y + py * farWidth)
        let farRight = CGPoint(x: target.x - px * farWidth, y: target.y - py * farWidth)

        var path = Path()
        path.move(to: nearLeft)
        path.addLine(to: farLeft)
        path.addLine(to: farRight)
        path.addLine(to: nearRight)
        path.closeSubpath()
        return path
    }

    private func wallWashProjectionPixels(targetCenter: CGPoint) -> [WallWashProjectionPixel] {
        let endpoints = wallWashBarWorldEndpoints(worldOrigin, halfLength: 45.0)
        let start = worldProjectedAbsolutePoint(endpoints.start, projection: projection, size: size)
        let end = worldProjectedAbsolutePoint(endpoints.end, projection: projection, size: size)
        let dx = end.x - start.x
        let dy = end.y - start.y
        let length = max(1, hypot(dx, dy))
        let axisX = dx / length
        let axisY = dy / length
        let spreadLength = min(max(28.0, length * 0.74), 100.0)
        return wallWashProjectionPoints(from: wallWashEmitters, count: 8).map { sample in
            let lateral = (sample.t - 0.5) * spreadLength
            return WallWashProjectionPixel(
                target: CGPoint(
                    x: targetCenter.x + axisX * lateral,
                    y: targetCenter.y + axisY * lateral
                ),
                color: sample.payload.color,
                intensity: sample.payload.intensity
            )
        }
    }

    @ViewBuilder
    private func wallWashPixelLayer(pixels: [WallWashProjectionPixel], brightness: CGFloat, pulseBoost: CGFloat) -> some View {
        ForEach(Array(pixels.enumerated()), id: \.offset) { _, pixel in
            Circle()
                .fill(pixel.color.opacity(0.16 + pixel.intensity * 0.30 + pulseBoost * 0.07))
                .frame(width: 38 + pixel.intensity * 18, height: 38 + pixel.intensity * 18)
                .position(pixel.target)
                .blur(radius: 10.0)
                .blendMode(.screen)

            Circle()
                .fill(pixel.color.opacity(0.28 + pixel.intensity * 0.34 + brightness * 0.10 + pulseBoost * 0.08))
                .frame(width: 16 + pixel.intensity * 8, height: 16 + pixel.intensity * 8)
                .position(pixel.target)
                .blur(radius: 3.2)
                .blendMode(.plusLighter)
        }
    }

    private struct WallWashProjectionPixel {
        let target: CGPoint
        let color: Color
        let intensity: CGFloat
    }

    private func currentBeamTarget(from state: StageMotionState?) -> CGPoint {
        let normalTarget: CGPoint
        if let direction = state?.worldDirection {
            // `rendered_motion.world_direction` has already passed through
            // final-frame decoding, profile inversion and fixture Forward/Up
            // calibration in the backend.  Do not reapply yaw or panFlip.
            let distance = StageWorld.movingHeadBeamDistanceCm
            let endpoint = SlotWorldPosition(
                x: worldOrigin.x + direction.x * distance,
                y: worldOrigin.y + direction.y * distance,
                z: worldOrigin.z + direction.z * distance,
                yawDegrees: worldOrigin.yawDegrees,
                pitchDegrees: worldOrigin.pitchDegrees,
                rollDegrees: worldOrigin.rollDegrees,
                panFlip: worldOrigin.panFlip,
                tiltFlip: worldOrigin.tiltFlip
            )
            normalTarget = worldProjectedAbsoluteBeamPoint(endpoint, projection: projection, size: size)
        } else if let state {
            normalTarget = projectedBeamTarget(
                origin: origin,
                worldOrigin: worldOrigin,
                mountYawDegrees: mountYawDegrees,
                mountPitchDegrees: mountPitchDegrees,
                pose: StageBeamPose(
                    panDegrees: state.currentPanDegrees,
                    tiltDegrees: state.currentTiltDegrees
                ),
                panRange: state.panRange,
                tiltRange: state.tiltRange,
                beamKind: beamKind,
                size: size,
                projection: projection
            )
        } else {
            normalTarget = projectedBeamTarget(
                origin: origin,
                worldOrigin: worldOrigin,
                mountYawDegrees: mountYawDegrees,
                mountPitchDegrees: mountPitchDegrees,
                preview: preview,
                beamKind: beamKind,
                size: size,
                projection: projection
            )
        }
        // Final rendered physical projection outranks composer/target intent.
        guard state?.worldDirection == nil, let venueTargetPreview else { return normalTarget }
        let target = worldProjectedAbsoluteBeamPoint(
            venueTargetPreview.endpoint,
            projection: projection,
            size: size
        )
        let start = worldProjectedAbsoluteBeamPoint(
            venueTargetPreview.startEndpoint,
            projection: projection,
            size: size
        )
        let progress = CGFloat(venueTargetPreview.easedProgress)
        return CGPoint(
            x: start.x + (target.x - start.x) * progress,
            y: start.y + (target.y - start.y) * progress
        )
    }

    private func targetBeamTarget(from state: StageMotionState?) -> CGPoint {
        if state?.worldDirection != nil {
            return currentBeamTarget(from: state)
        }
        if let venueTargetPreview {
            return worldProjectedAbsoluteBeamPoint(
                venueTargetPreview.endpoint,
                projection: projection,
                size: size
            )
        }
        guard let state else {
            return currentBeamTarget(from: nil)
        }
        return projectedBeamTarget(
            origin: origin,
            worldOrigin: worldOrigin,
            mountYawDegrees: mountYawDegrees,
            mountPitchDegrees: mountPitchDegrees,
            pose: StageBeamPose(
                panDegrees: state.targetPanDegrees,
                tiltDegrees: state.targetTiltDegrees
            ),
            panRange: state.panRange,
            tiltRange: state.tiltRange,
            beamKind: beamKind,
            size: size,
            projection: projection
        )
    }

    private func trailBeamTargets(from state: StageMotionState?) -> [CGPoint] {
        if venueTargetPreview != nil { return [] }
        guard let state, preview.motionActive, beamKind == .movingHead else { return [] }
        let history = state.trail.dropLast().suffix(3)
        return history.map { pose in
            projectedBeamTarget(
                origin: origin,
                worldOrigin: worldOrigin,
                mountYawDegrees: mountYawDegrees,
                mountPitchDegrees: mountPitchDegrees,
                pose: pose,
                panRange: state.panRange,
                tiltRange: state.tiltRange,
                beamKind: beamKind,
                size: size,
                projection: projection
            )
        }
    }
}

struct TrussSegmentLine: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.addRect(rect)
        let segments = 8
        let width = rect.width / CGFloat(segments)
        for index in 0..<segments {
            let startX = CGFloat(index) * width
            path.move(to: CGPoint(x: startX, y: rect.maxY))
            path.addLine(to: CGPoint(x: startX + width / 2, y: rect.minY))
            path.addLine(to: CGPoint(x: startX + width, y: rect.maxY))
        }
        return path
    }
}

struct StageStandShape: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        let centerX = rect.midX
        let topY = rect.minY + rect.height * 0.08
        let midY = rect.midY

        path.move(to: CGPoint(x: centerX, y: topY))
        path.addLine(to: CGPoint(x: centerX, y: rect.maxY))

        path.move(to: CGPoint(x: centerX, y: midY))
        path.addLine(to: CGPoint(x: rect.minX + rect.width * 0.10, y: rect.maxY))

        path.move(to: CGPoint(x: centerX, y: midY))
        path.addLine(to: CGPoint(x: rect.maxX - rect.width * 0.10, y: rect.maxY))

        return path
    }
}

struct StageStandFrontShape: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        let centerX = rect.midX
        let topY = rect.minY + rect.height * 0.08
        let floorY = rect.maxY

        path.move(to: CGPoint(x: centerX, y: topY))
        path.addLine(to: CGPoint(x: centerX, y: floorY))

        path.move(to: CGPoint(x: centerX, y: floorY - rect.height * 0.24))
        path.addLine(to: CGPoint(x: rect.minX + rect.width * 0.16, y: floorY))

        path.move(to: CGPoint(x: centerX, y: floorY - rect.height * 0.24))
        path.addLine(to: CGPoint(x: rect.maxX - rect.width * 0.16, y: floorY))

        return path
    }
}

@MainActor
private func stageBeamKindFor3D(_ editor: SlotEditor) -> StageFixtureBeam.BeamKind {
    if editor.supportsPan || editor.supportsTilt {
        return .movingHead
    }
    let lower = "\(editor.label) \(editor.fixtureLabel)".lowercased()
    if lower.contains("wall wash") || lower.contains("light bar") || lower.contains("wallwash") || lower.contains("bar") {
        return .wallWash
    }
    return .staticWash
}

struct StageThreeDPreviewPanel<Content: View>: View {
    let title: String
    let subtitle: String
    let content: Content

    init(title: String, subtitle: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.subtitle = subtitle
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 14, weight: .semibold))
                Text(subtitle)
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
            }

            ZStack {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [
                                Color(red: 0.06, green: 0.07, blue: 0.10),
                                Color(red: 0.04, green: 0.05, blue: 0.08)
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                content
                    .padding(12)
            }
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(Color.white.opacity(0.08), lineWidth: 1)
            )
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

enum Stage3DCameraPreset: String, CaseIterable, Identifiable {
    case audience
    case front
    case dj
    case top

    var id: String { rawValue }

    var title: String {
        switch self {
        case .audience:
            return "Audience"
        case .front:
            return "Front"
        case .dj:
            return "DJ"
        case .top:
            return "Top"
        }
    }

    var iconName: String {
        switch self {
        case .audience:
            return "person.3.sequence.fill"
        case .front:
            return "rectangle.center.inset.filled"
        case .dj:
            return "music.mic"
        case .top:
            return "square.split.2x1"
        }
    }

    var cameraPosition: SCNVector3 {
        switch self {
        case .audience:
            return SCNVector3(0.0, 2.4, -10.0)
        case .front:
            return SCNVector3(0.0, 1.9, -7.4)
        case .dj:
            return SCNVector3(0.0, 2.2, 3.0)
        case .top:
            return SCNVector3(0.0, 11.5, -2.5)
        }
    }

    var targetPosition: SCNVector3 {
        switch self {
        case .audience:
            return SCNVector3(0.0, 1.8, -1.2)
        case .front:
            return SCNVector3(0.0, 1.7, -2.0)
        case .dj:
            return SCNVector3(0.0, 1.6, -4.6)
        case .top:
            return SCNVector3(0.0, 1.4, -2.5)
        }
    }
}

private struct Stage3DBeamRenderState {
    let beamKind: StageFixtureBeam.BeamKind
    let end: SCNVector3
    let direction: SCNVector3
    let wallWashSpreadAxis: SCNVector3?
    let wallWashProjectionPixels: [WallWash3DProjectionPixel]
    let washColor: NSColor
    let spotColor: NSColor
    let brightness: CGFloat
    let washBrightness: CGFloat
    let spotBrightness: CGFloat
    let isBeeEye: Bool
    let strobeActive: Bool
    let beeEffectMode: BeeEffectMode
    let beeSpread: CGFloat
    let beeBackgroundLevel: CGFloat
    let beeSoftness: CGFloat
    let beeShapeTransition: CGFloat
    let spotPatternID: String?
    let spotPatternRotationDegrees: Double
    let spotPatternOpen: Bool
}

private struct WallWash3DProjectionPixel {
    let end: SCNVector3
    let color: NSColor
    let intensity: CGFloat
    let up: SCNVector3
}

@MainActor
final class Stage3DSceneController: ObservableObject {
    let scene = SCNScene()
    let cameraNode = SCNNode()

    private let cameraTargetNode = SCNNode()
    private let fixtureRootNode = SCNNode()
    private var beePatternTextureCache: [String: NSImage] = [:]
    private var beamSpriteTextureCache: [String: NSImage] = [:]
    private var didConfigure = false

    init() {
        configureSceneIfNeeded()
    }

    func applyCameraPreset(_ preset: Stage3DCameraPreset) {
        configureSceneIfNeeded()
        cameraNode.position = preset.cameraPosition
        cameraTargetNode.position = preset.targetPosition
    }

    func sync(from model: AppModel, animationTime: TimeInterval) {
        configureSceneIfNeeded()
        fixtureRootNode.childNodes.forEach { $0.removeFromParentNode() }

        for editor in model.slotEditors.sorted(by: { $0.id < $1.id }) {
            let world = model.worldPosition(for: editor.id)
            let preview = model.presentedSlotPreviews[editor.id]
            let stageMotion = model.presentedStageMotionStates[editor.id]
            let venueTargetPreview = model.venueTargetPreviewVisual(for: editor.id)
            let wallWashEmitters = stageBeamKindFor3D(editor) == .wallWash
                ? wallWashEmitterPreviews(editor: editor, model: model, preview: preview, animationTime: animationTime)
                : []
            let isPrimarySelected = model.selectedSlotID == editor.id
            let isPreviewSelected = model.previewSelectionContains(editor.id)
            let node = makeFixtureNode(
                editor: editor,
                world: world,
                preview: preview,
                stageMotion: stageMotion,
                venueTargetPreview: venueTargetPreview,
                wallWashEmitters: wallWashEmitters,
                animationTime: animationTime,
                isPrimarySelected: isPrimarySelected,
                isPreviewSelected: isPreviewSelected
            )
            fixtureRootNode.addChildNode(node)
        }
    }

    private func configureSceneIfNeeded() {
        guard !didConfigure else { return }
        didConfigure = true

        scene.background.contents = NSColor(calibratedRed: 0.03, green: 0.04, blue: 0.06, alpha: 1.0)
        scene.rootNode.addChildNode(fixtureRootNode)
        scene.rootNode.addChildNode(cameraTargetNode)
        scene.rootNode.addChildNode(cameraNode)

        let camera = SCNCamera()
        camera.fieldOfView = 48
        camera.zNear = 0.02
        camera.zFar = 60
        camera.wantsHDR = true
        camera.wantsExposureAdaptation = true
        camera.bloomIntensity = 1.25
        camera.bloomThreshold = 0.18
        camera.bloomBlurRadius = 24
        camera.saturation = 1.06
        camera.contrast = 1.08
        cameraNode.camera = camera

        let lookAt = SCNLookAtConstraint(target: cameraTargetNode)
        lookAt.isGimbalLockEnabled = true
        cameraNode.constraints = [lookAt]

        let ambient = SCNNode()
        ambient.light = SCNLight()
        ambient.light?.type = .ambient
        ambient.light?.color = NSColor(calibratedWhite: 0.65, alpha: 1.0)
        ambient.light?.intensity = 280
        scene.rootNode.addChildNode(ambient)

        let key = SCNNode()
        key.light = SCNLight()
        key.light?.type = .omni
        key.light?.color = NSColor(calibratedWhite: 0.92, alpha: 1.0)
        key.light?.intensity = 820
        key.position = SCNVector3(0.0, 6.5, -8.0)
        scene.rootNode.addChildNode(key)

        let fill = SCNNode()
        fill.light = SCNLight()
        fill.light?.type = .omni
        fill.light?.color = NSColor(calibratedRed: 0.40, green: 0.55, blue: 0.80, alpha: 1.0)
        fill.light?.intensity = 340
        fill.position = SCNVector3(-5.5, 3.0, 2.0)
        scene.rootNode.addChildNode(fill)

        buildStageEnvironment()
        applyCameraPreset(.audience)
    }

    private func buildStageEnvironment() {
        let stageWidth = CGFloat((StageWorld.maxX - StageWorld.minX) / 100.0)
        let stageDepth = CGFloat((StageWorld.maxY - StageWorld.minY) / 100.0)
        let stageCenterZ = CGFloat(-(StageWorld.minY + StageWorld.maxY) / 200.0)

        let floor = SCNPlane(width: stageWidth, height: stageDepth)
        let floorMaterial = SCNMaterial()
        floorMaterial.diffuse.contents = NSColor(calibratedRed: 0.11, green: 0.12, blue: 0.15, alpha: 1.0)
        floorMaterial.emission.contents = NSColor(calibratedRed: 0.02, green: 0.03, blue: 0.05, alpha: 1.0)
        floorMaterial.roughness.contents = 0.95
        floorMaterial.metalness.contents = 0.04
        floorMaterial.isDoubleSided = true
        floor.materials = [floorMaterial]

        let floorNode = SCNNode(geometry: floor)
        floorNode.eulerAngles.x = -.pi / 2
        floorNode.position = SCNVector3(0.0, 0.0, stageCenterZ)
        scene.rootNode.addChildNode(floorNode)

        let rearTruss = makeSceneSegmentNode(
            from: SCNVector3(CGFloat(StageWorld.minX / 100.0), CGFloat(StageWorld.maxZ / 100.0 - 0.45), 0.0),
            to: SCNVector3(CGFloat(StageWorld.maxX / 100.0), CGFloat(StageWorld.maxZ / 100.0 - 0.45), 0.0),
            radius: 0.028,
            color: NSColor(calibratedWhite: 0.46, alpha: 1.0),
            opacity: 0.95
        )
        scene.rootNode.addChildNode(rearTruss)

        let stageFront = makeSceneSegmentNode(
            from: SCNVector3(CGFloat(StageWorld.minX / 100.0), 0.01, CGFloat(-StageWorld.maxY / 100.0)),
            to: SCNVector3(CGFloat(StageWorld.maxX / 100.0), 0.01, CGFloat(-StageWorld.maxY / 100.0)),
            radius: 0.02,
            color: NSColor(calibratedRed: 0.10, green: 0.76, blue: 0.90, alpha: 1.0),
            opacity: 0.55
        )
        scene.rootNode.addChildNode(stageFront)

        let centerLine = makeSceneSegmentNode(
            from: SCNVector3(0.0, 0.012, 0.0),
            to: SCNVector3(0.0, 0.012, CGFloat(-StageWorld.maxY / 100.0)),
            radius: 0.008,
            color: NSColor(calibratedWhite: 0.72, alpha: 1.0),
            opacity: 0.28
        )
        scene.rootNode.addChildNode(centerLine)

        for value in stride(from: StageWorld.minX, through: StageWorld.maxX, by: StageWorld.minorGridStepCm) {
            let x = CGFloat(value / 100.0)
            let isMajor = abs(value.remainder(dividingBy: StageWorld.majorGridStepCm)) < 0.001
            let line = makeSceneSegmentNode(
                from: SCNVector3(x, 0.002, 0.0),
                to: SCNVector3(x, 0.002, CGFloat(-StageWorld.maxY / 100.0)),
                radius: 0.004,
                color: NSColor(calibratedWhite: 0.34, alpha: 1.0),
                opacity: value == 0 ? 0.26 : isMajor ? 0.16 : 0.07
            )
            scene.rootNode.addChildNode(line)
        }

        for value in stride(from: StageWorld.minY, through: StageWorld.maxY, by: StageWorld.minorGridStepCm) {
            let z = CGFloat(-value / 100.0)
            let isMajor = abs(value.remainder(dividingBy: StageWorld.majorGridStepCm)) < 0.001
            let line = makeSceneSegmentNode(
                from: SCNVector3(CGFloat(StageWorld.minX / 100.0), 0.002, z),
                to: SCNVector3(CGFloat(StageWorld.maxX / 100.0), 0.002, z),
                radius: 0.004,
                color: NSColor(calibratedWhite: 0.34, alpha: 1.0),
                opacity: value == 0 ? 0.20 : isMajor ? 0.16 : 0.07
            )
            scene.rootNode.addChildNode(line)
        }
    }

    private func makeFixtureNode(
        editor: SlotEditor,
        world: SlotWorldPosition,
        preview: SlotPreview?,
        stageMotion: StageMotionState?,
        venueTargetPreview: VenueTargetPreviewVisual?,
        wallWashEmitters: [WallWashEmitterPreview],
        animationTime: TimeInterval,
        isPrimarySelected: Bool,
        isPreviewSelected: Bool
    ) -> SCNNode {
        let root = SCNNode()
        let beamKind = stageBeamKindFor3D(editor)
        let isBeeEye = slotPreviewIsBeeEye(preview) || editor.fixtureID == "generic_smart_bee_eye_pattern_moving_head"
        let baseColor = fixtureSceneColor(preview)
        let spotColor = fixtureSceneSpotColor(preview)
        let isEnabled = preview?.enabled == true
        let bodyOpacity: CGFloat = isEnabled ? 1.0 : 0.42
        let selectionStrength: CGFloat = isPrimarySelected ? 1.0 : isPreviewSelected ? 0.78 : 0.0
        let selectionColor = isPrimarySelected
            ? NSColor(calibratedRed: 0.20, green: 0.92, blue: 1.00, alpha: 1.0)
            : NSColor(calibratedRed: 1.00, green: 0.48, blue: 0.18, alpha: 1.0)

        root.name = editor.id
        root.position = stageSceneVector(for: world)

        if world.z > 110 {
            let hangEnd = SCNVector3(0.0, CGFloat(StageWorld.maxZ / 100.0 - world.z / 100.0), 0.0)
            let hangLine = makeSceneSegmentNode(
                from: SCNVector3(0.0, 0.0, 0.0),
                to: hangEnd,
                radius: 0.007,
                color: NSColor(calibratedWhite: 0.56, alpha: 1.0),
                opacity: 0.42
            )
            root.addChildNode(hangLine)
        }

        let beamState: Stage3DBeamRenderState?
        if let preview, preview.enabled {
            beamState = makeBeamRenderState(
                editor: editor,
                world: world,
                preview: preview,
                stageMotion: stageMotion,
                venueTargetPreview: venueTargetPreview,
                wallWashEmitters: wallWashEmitters,
                beamKind: beamKind,
                animationTime: animationTime,
                isBeeEye: isBeeEye
            )
        } else {
            beamState = nil
        }

        let bodyNode: SCNNode
        if isBeeEye {
            bodyNode = makeBeeEyeBodyNode(
                baseColor: baseColor,
                spotColor: spotColor,
                opacity: bodyOpacity,
                selectionStrength: selectionStrength,
                aimEndpoint: beamState?.end
            )
        } else {
            switch beamKind {
            case .movingHead:
                bodyNode = makeMovingHeadBodyNode(
                    baseColor: baseColor,
                    spotColor: spotColor,
                    opacity: bodyOpacity,
                    selectionStrength: selectionStrength,
                    aimEndpoint: beamState?.end
                )
            case .wallWash:
                bodyNode = makeWallWashBodyNode(
                    color: baseColor,
                    emitters: wallWashEmitters,
                    opacity: bodyOpacity,
                    selectionStrength: selectionStrength,
                    yawDegrees: world.yawDegrees,
                    pitchDegrees: world.pitchDegrees,
                    rollDegrees: world.rollDegrees
                )
            case .staticWash:
                bodyNode = makeParBodyNode(
                    color: baseColor,
                    opacity: bodyOpacity,
                    selectionStrength: selectionStrength
                )
            }
        }
        root.addChildNode(bodyNode)

        if selectionStrength > 0.01 {
            root.addChildNode(
                makeSelectionIndicatorNode(
                    beamKind: beamKind,
                    color: selectionColor,
                    intensity: selectionStrength
                )
            )
        }

        if let beamState {
            root.addChildNode(makeBeamVolumeNode(state: beamState))
        }

        return root
    }

    private func makeBeamRenderState(
        editor: SlotEditor,
        world: SlotWorldPosition,
        preview: SlotPreview,
        stageMotion: StageMotionState?,
        venueTargetPreview: VenueTargetPreviewVisual?,
        wallWashEmitters: [WallWashEmitterPreview],
        beamKind: StageFixtureBeam.BeamKind,
        animationTime: TimeInterval,
        isBeeEye: Bool
    ) -> Stage3DBeamRenderState {
        let isMovingHead = beamKind == .movingHead
        let panRange = stageMotion?.panRange ?? (preview.panRange ?? (isMovingHead ? 540.0 : 180.0))
        let tiltRange = stageMotion?.tiltRange ?? (preview.tiltRange ?? (isMovingHead ? 180.0 : 90.0))

        let pose: StageBeamPose
        if let stageMotion, isMovingHead {
            pose = StageBeamPose(
                panDegrees: stageMotion.currentPanDegrees,
                tiltDegrees: stageMotion.currentTiltDegrees
            )
        } else {
            pose = StageBeamPose(
                panDegrees: preview.logicalPanDegrees
                    ?? preview.panDegrees
                    ?? panDegrees(forDMX: preview.pan, range: panRange),
                tiltDegrees: preview.logicalTiltDegrees
                    ?? preview.tiltDegrees
                    ?? tiltDegrees(forDMX: preview.tilt, range: tiltRange)
            )
        }

        let normalEndpoint = stageMotion?.worldDirection.map {
            worldEndpoint(from: world, direction: $0, distance: StageWorld.movingHeadBeamDistanceCm)
        } ?? beamWorldEndpoint(
            worldOrigin: world,
            mountYawDegrees: world.yawDegrees,
            mountPitchDegrees: world.pitchDegrees,
            pose: pose,
            panRange: panRange,
            tiltRange: tiltRange,
            beamKind: beamKind
        )
        let endpoint = interpolatedVenueTargetEndpoint(
            normalEndpoint,
            preview: stageMotion?.worldDirection == nil ? venueTargetPreview : nil
        )

        // Keep fixture geometry visible through its body node, but never add a
        // minimum emitted beam: authoritative zero intensity means no light.
        let washBrightness = effectivePreviewBrightness(preview, at: animationTime)
        let spotBrightness = effectiveSpotPreviewBrightness(preview, at: animationTime)
        let beeEffectMode = slotPreviewResolvedBeeEffectMode(preview)
        let beeSpread = slotPreviewBeeSpread(preview)
        let beeBackgroundLevel = slotPreviewBeeBackgroundLevel(preview)
        let beeSoftness = slotPreviewBeeSoftness(preview)
        let beeShapeTransition = slotPreviewBeeShapeTransition(preview)
        let brightness = isBeeEye
            ? max(washBrightness * 0.78, spotBrightness)
            : (beamKind == .movingHead && (preview.spotBrightness ?? 0) > 10 ? spotBrightness : washBrightness)
        let wallWashSpreadAxis: SCNVector3? = beamKind == .wallWash
            ? sceneWallWashSpreadAxis(world)
            : nil
        let wallWashProjectionPixels: [WallWash3DProjectionPixel] = []

        return Stage3DBeamRenderState(
            beamKind: beamKind,
            end: sceneVectorSubtract(stageSceneVector(for: endpoint), stageSceneVector(for: world)),
            direction: sceneVectorNormalize(sceneVectorSubtract(stageSceneVector(for: endpoint), stageSceneVector(for: world))),
            wallWashSpreadAxis: wallWashSpreadAxis,
            wallWashProjectionPixels: wallWashProjectionPixels,
            washColor: fixtureSceneColor(preview),
            spotColor: fixtureSceneSpotColor(preview),
            brightness: brightness,
            washBrightness: washBrightness,
            spotBrightness: spotBrightness,
            isBeeEye: isBeeEye,
            strobeActive: preview.strobeActive,
            beeEffectMode: beeEffectMode,
            beeSpread: beeSpread,
            beeBackgroundLevel: beeBackgroundLevel,
            beeSoftness: beeSoftness,
            beeShapeTransition: beeShapeTransition,
            spotPatternID: isBeeEye ? slotPreviewResolvedPatternID(preview, at: animationTime) : nil,
            spotPatternRotationDegrees: isBeeEye ? slotPreviewResolvedPatternRotation(preview, at: animationTime) : 0,
            spotPatternOpen: isBeeEye ? ((slotPreviewResolvedPatternID(preview, at: animationTime) == "open") || (preview.spotPatternOpen ?? false)) : true
        )
    }

    private func makeMovingHeadBodyNode(
        baseColor: NSColor,
        spotColor: NSColor,
        opacity: CGFloat,
        selectionStrength: CGFloat,
        aimEndpoint: SCNVector3?
    ) -> SCNNode {
        let root = SCNNode()
        let armColor = NSColor(calibratedWhite: 0.12, alpha: 1.0)
        let base = makeRoundedBoxNode(
            width: 0.26,
            height: 0.08,
            length: 0.18,
            chamfer: 0.02,
            color: armColor,
            emission: baseColor,
            emissionStrength: 0.10 + selectionStrength * 0.24,
            opacity: opacity
        )
        base.position = SCNVector3(0.0, -0.02, 0.0)
        root.addChildNode(base)

        for x in [-0.10, 0.10] {
            let arm = makeRoundedBoxNode(
                width: 0.04,
                height: 0.17,
                length: 0.05,
                chamfer: 0.012,
                color: armColor,
                emission: baseColor,
                emissionStrength: 0.05 + selectionStrength * 0.16,
                opacity: opacity
            )
            arm.position = SCNVector3(CGFloat(x), 0.06, 0.0)
            root.addChildNode(arm)
        }

        let headGroup = SCNNode()
        headGroup.position = SCNVector3(0.0, 0.11, 0.0)
        if let aimEndpoint {
            headGroup.look(at: aimEndpoint, up: SCNVector3(0, 1, 0), localFront: SCNVector3(0, 0, -1))
        }
        root.addChildNode(headGroup)

        let head = makeRoundedBoxNode(
            width: 0.19,
            height: 0.11,
            length: 0.17,
            chamfer: 0.026,
            color: armColor,
            emission: baseColor,
            emissionStrength: 0.16 + selectionStrength * 0.20,
            opacity: opacity
        )
        headGroup.addChildNode(head)

        let bezel = SCNTorus(ringRadius: 0.042, pipeRadius: 0.009)
        let bezelMaterial = makeEmissiveMaterial(
            color: baseColor,
            emission: baseColor,
            emissionStrength: 0.18 + selectionStrength * 0.26,
            opacity: opacity
        )
        bezel.materials = [bezelMaterial]
        let bezelNode = SCNNode(geometry: bezel)
        bezelNode.eulerAngles.x = .pi / 2
        bezelNode.position = SCNVector3(0.0, 0.0, -0.088)
        headGroup.addChildNode(bezelNode)

        let lens = SCNSphere(radius: 0.034)
        lens.materials = [makeEmissiveMaterial(
            color: NSColor.white,
            emission: spotColor,
            emissionStrength: 0.92 + selectionStrength * 0.22,
            opacity: opacity
        )]
        let lensNode = SCNNode(geometry: lens)
        lensNode.position = SCNVector3(0.0, 0.0, -0.092)
        headGroup.addChildNode(lensNode)

        return root
    }

    private func makeBeeEyeBodyNode(
        baseColor: NSColor,
        spotColor: NSColor,
        opacity: CGFloat,
        selectionStrength: CGFloat,
        aimEndpoint: SCNVector3?
    ) -> SCNNode {
        let root = SCNNode()
        let armColor = NSColor(calibratedWhite: 0.10, alpha: 1.0)
        let base = makeRoundedBoxNode(
            width: 0.28,
            height: 0.08,
            length: 0.20,
            chamfer: 0.022,
            color: armColor,
            emission: baseColor,
            emissionStrength: 0.12 + selectionStrength * 0.22,
            opacity: opacity
        )
        base.position = SCNVector3(0.0, -0.02, 0.0)
        root.addChildNode(base)

        for x in [-0.10, 0.10] {
            let arm = makeRoundedBoxNode(
                width: 0.04,
                height: 0.16,
                length: 0.05,
                chamfer: 0.012,
                color: armColor,
                emission: baseColor,
                emissionStrength: 0.06 + selectionStrength * 0.14,
                opacity: opacity
            )
            arm.position = SCNVector3(CGFloat(x), 0.05, 0.0)
            root.addChildNode(arm)
        }

        let headGroup = SCNNode()
        headGroup.position = SCNVector3(0.0, 0.11, 0.0)
        if let aimEndpoint {
            headGroup.look(at: aimEndpoint, up: SCNVector3(0, 1, 0), localFront: SCNVector3(0, 0, -1))
        }
        root.addChildNode(headGroup)

        let head = makeRoundedBoxNode(
            width: 0.22,
            height: 0.12,
            length: 0.18,
            chamfer: 0.028,
            color: armColor,
            emission: baseColor,
            emissionStrength: 0.16 + selectionStrength * 0.18,
            opacity: opacity
        )
        headGroup.addChildNode(head)

        let frontPlate = SCNCylinder(radius: 0.082, height: 0.020)
        frontPlate.materials = [makeEmissiveMaterial(
            color: NSColor(calibratedWhite: 0.08, alpha: 1.0),
            emission: baseColor,
            emissionStrength: 0.08 + selectionStrength * 0.12,
            opacity: opacity
        )]
        let frontPlateNode = SCNNode(geometry: frontPlate)
        frontPlateNode.eulerAngles.x = .pi / 2
        frontPlateNode.position = SCNVector3(0.0, 0.0, -0.092)
        headGroup.addChildNode(frontPlateNode)

        let lensOffsets: [(CGFloat, CGFloat)] = [
            (0.0, 0.0),
            (0.0, -0.040),
            (0.034, -0.020),
            (0.034, 0.020),
            (0.0, 0.040),
            (-0.034, 0.020),
            (-0.034, -0.020),
        ]
        for (index, offset) in lensOffsets.enumerated() {
            let radius: CGFloat = index == 0 ? 0.019 : 0.015
            let lens = SCNSphere(radius: radius)
            let lensColor = index == 0 ? spotColor : baseColor
            lens.materials = [makeEmissiveMaterial(
                color: NSColor.white,
                emission: lensColor,
                emissionStrength: index == 0 ? 1.08 + selectionStrength * 0.18 : 0.62 + selectionStrength * 0.12,
                opacity: opacity
            )]
            let lensNode = SCNNode(geometry: lens)
            lensNode.position = SCNVector3(offset.0, offset.1, -0.102)
            headGroup.addChildNode(lensNode)
        }

        return root
    }

    private func makeWallWashBodyNode(color: NSColor, emitters: [WallWashEmitterPreview], opacity: CGFloat, selectionStrength: CGFloat, yawDegrees: Double, pitchDegrees: Double, rollDegrees: Double) -> SCNNode {
        let root = SCNNode()
        root.eulerAngles = SCNVector3(
            CGFloat(pitchDegrees * .pi / 180.0),
            CGFloat(-yawDegrees * .pi / 180.0),
            CGFloat(rollDegrees * .pi / 180.0)
        )
        let body = makeRoundedBoxNode(
            width: 0.90,
            height: 0.06,
            length: 0.10,
            chamfer: 0.016,
            color: NSColor(calibratedWhite: 0.05, alpha: 1.0),
            emission: NSColor(calibratedWhite: 0.02, alpha: 1.0),
            emissionStrength: 0.02 + selectionStrength * 0.06,
            opacity: opacity
        )
        root.addChildNode(body)

        for index in 0..<24 {
            let t = CGFloat(index) / 23.0
            let x = -0.41 + t * 0.82
            let emitter = emitters.indices.contains(index)
                ? emitters[index]
                : WallWashEmitterPreview(red: 255, green: 255, blue: 255, white: 0, intensity: 0.12)
            let lens = SCNCapsule(capRadius: 0.010, height: 0.028)
            lens.materials = [makeEmissiveMaterial(
                color: NSColor.white,
                emission: emitter.nsColor,
                emissionStrength: 0.48 + emitter.intensity * 1.64 + selectionStrength * 0.20,
                opacity: opacity
            )]
            let lensNode = SCNNode(geometry: lens)
            lensNode.eulerAngles.x = .pi / 2
            lensNode.position = SCNVector3(x, 0.0, -0.056)
            root.addChildNode(lensNode)

            let glow = SCNPlane(width: 0.018, height: 0.030)
            let glowMaterial = makeEmissiveMaterial(
                color: NSColor.white,
                emission: emitter.nsColor,
                emissionStrength: 0.56 + emitter.intensity * 1.92 + selectionStrength * 0.24,
                opacity: opacity * (0.28 + emitter.intensity * 0.62)
            )
            glowMaterial.lightingModel = .constant
            glowMaterial.blendMode = .add
            glowMaterial.isDoubleSided = true
            glowMaterial.readsFromDepthBuffer = false
            glowMaterial.writesToDepthBuffer = false
            glow.materials = [glowMaterial]
            let glowNode = SCNNode(geometry: glow)
            glowNode.position = SCNVector3(x, 0.0, -0.062)
            root.addChildNode(glowNode)
        }

        for x in [-0.46, 0.46] {
            let bracket = makeRoundedBoxNode(
                width: 0.03,
                height: 0.12,
                length: 0.03,
                chamfer: 0.008,
                color: NSColor(calibratedWhite: 0.18, alpha: 1.0),
                emission: NSColor(calibratedWhite: 0.03, alpha: 1.0),
                emissionStrength: 0.01,
                opacity: opacity
            )
            bracket.position = SCNVector3(CGFloat(x), -0.03, 0.0)
            root.addChildNode(bracket)
        }

        return root
    }

    private func makeParBodyNode(color: NSColor, opacity: CGFloat, selectionStrength: CGFloat) -> SCNNode {
        let root = SCNNode()

        let can = SCNCylinder(radius: 0.092, height: 0.09)
        can.materials = [makeEmissiveMaterial(
            color: NSColor(calibratedWhite: 0.10, alpha: 1.0),
            emission: color,
            emissionStrength: 0.15 + selectionStrength * 0.18,
            opacity: opacity
        )]
        let canNode = SCNNode(geometry: can)
        canNode.eulerAngles.x = .pi / 2
        root.addChildNode(canNode)

        let lens = SCNSphere(radius: 0.05)
        lens.materials = [makeEmissiveMaterial(
            color: NSColor.white,
            emission: color,
            emissionStrength: 0.82 + selectionStrength * 0.16,
            opacity: opacity
        )]
        let lensNode = SCNNode(geometry: lens)
        lensNode.position = SCNVector3(0.0, 0.0, -0.048)
        root.addChildNode(lensNode)

        for x in [-0.095, 0.095] {
            let arm = makeRoundedBoxNode(
                width: 0.02,
                height: 0.12,
                length: 0.02,
                chamfer: 0.006,
                color: NSColor(calibratedWhite: 0.16, alpha: 1.0),
                emission: color,
                emissionStrength: 0.04,
                opacity: opacity
            )
            arm.position = SCNVector3(CGFloat(x), 0.0, 0.0)
            root.addChildNode(arm)
        }

        return root
    }

    private func makeSelectionIndicatorNode(beamKind: StageFixtureBeam.BeamKind, color: NSColor, intensity: CGFloat) -> SCNNode {
        let root = SCNNode()

        if beamKind == .wallWash {
            let plate = SCNPlane(width: 0.86, height: 0.15)
            let material = makeEmissiveMaterial(
                color: color,
                emission: color,
                emissionStrength: 0.26 + intensity * 0.30,
                opacity: 0.08 + intensity * 0.14
            )
            material.isDoubleSided = true
            plate.materials = [material]
            let plateNode = SCNNode(geometry: plate)
            plateNode.eulerAngles.x = -.pi / 2
            plateNode.position = SCNVector3(0.0, -0.05, 0.0)
            root.addChildNode(plateNode)
        } else {
            let ring = SCNTorus(ringRadius: beamKind == .movingHead ? 0.18 : 0.15, pipeRadius: 0.010)
            ring.materials = [makeEmissiveMaterial(
                color: color,
                emission: color,
                emissionStrength: 0.44 + intensity * 0.24,
                opacity: 0.42 + intensity * 0.26
            )]
            let ringNode = SCNNode(geometry: ring)
            ringNode.eulerAngles.x = .pi / 2
            ringNode.position = SCNVector3(0.0, -0.05, 0.0)
            root.addChildNode(ringNode)
        }

        let aura = SCNSphere(radius: beamKind == .movingHead ? 0.19 : 0.13)
        aura.materials = [makeEmissiveMaterial(
            color: color,
            emission: color,
            emissionStrength: 0.14 + intensity * 0.20,
            opacity: 0.04 + intensity * 0.08
        )]
        let auraNode = SCNNode(geometry: aura)
        auraNode.scale = SCNVector3(1.0, beamKind == .wallWash ? 0.35 : 0.7, 1.0)
        auraNode.position = SCNVector3(0.0, 0.02, 0.0)
        root.addChildNode(auraNode)

        return root
    }

    private func makeBeamVolumeNode(state: Stage3DBeamRenderState) -> SCNNode {
        let root = SCNNode()
        let direction = state.direction
        guard sceneVectorLength(direction) > 0.0001 else { return root }
        let basis = beamBasis(for: direction)

        switch state.beamKind {
        case .movingHead:
            if state.isBeeEye {
                let washWidth = 0.28 + state.beeBackgroundLevel * 0.18 + state.beeSoftness * 0.06
                let washOuterWidth = 0.18 + state.beeBackgroundLevel * 0.10 + state.beeSoftness * 0.04
                let washFarRadius = 0.14 + state.beeBackgroundLevel * 0.07 + state.beeSoftness * 0.03
                let washInnerFarRadius = 0.09 + state.beeBackgroundLevel * 0.05
                let spotFarRadius = 0.055 + state.beeSpread * 0.020 + state.beeSoftness * 0.012
                let spotOuterRadius = 0.072 + state.beeSpread * 0.024 + state.beeShapeTransition * 0.010
                root.addChildNode(makeBeamFogNode(
                    from: SCNVector3(0, 0, 0),
                    to: state.end,
                    width: washWidth,
                    color: state.washColor,
                    opacity: (0.06 + state.washBrightness * 0.10) * (0.38 + state.beeBackgroundLevel * 0.74),
                    planeCount: 4,
                    taper: 0.28 + state.beeSoftness * 0.10
                ))
                root.addChildNode(makeBeamFogNode(
                    from: SCNVector3(0, 0, 0),
                    to: state.end,
                    width: washOuterWidth,
                    color: state.spotColor,
                    opacity: 0.08 + state.spotBrightness * 0.12,
                    planeCount: 3,
                    taper: 0.18 + state.beeSoftness * 0.08
                ))
                root.addChildNode(makeBeamConeNode(
                    from: SCNVector3(0, 0, 0),
                    to: state.end,
                    nearRadius: 0.024,
                    farRadius: washFarRadius,
                    color: state.washColor,
                    opacity: (0.04 + state.washBrightness * 0.12) * (0.34 + state.beeBackgroundLevel * 0.76),
                    emissionStrength: 0.42
                ))
                root.addChildNode(makeBeamConeNode(
                    from: SCNVector3(0, 0, 0),
                    to: state.end,
                    nearRadius: 0.018,
                    farRadius: washInnerFarRadius,
                    color: state.washColor,
                    opacity: (0.08 + state.washBrightness * 0.14) * (0.40 + state.beeBackgroundLevel * 0.58),
                    emissionStrength: 0.54
                ))
                root.addChildNode(makeBeamConeNode(
                    from: SCNVector3(0, 0, 0),
                    to: state.end,
                    nearRadius: 0.012,
                    farRadius: spotFarRadius,
                    color: state.spotColor,
                    opacity: 0.12 + state.spotBrightness * 0.20,
                    emissionStrength: 0.72
                ))

                for offset in beeEyeTripletOffsets3D(
                    side: basis.side,
                    up: basis.up,
                    spread: state.beeSpread,
                    rotationDegrees: state.spotPatternRotationDegrees
                ) {
                    let startOffset = offset * 0.46
                    let end = state.end + offset * (1.56 + state.beeSpread * 0.62)
                    let throwDistance = Float(sceneVectorLength(sceneVectorSubtract(end, startOffset)))
                    root.addChildNode(makeBeamFogNode(
                        from: startOffset,
                        to: end,
                        width: 0.09 + state.beeSpread * 0.03 + state.beeSoftness * 0.02,
                        color: state.spotColor,
                        opacity: 0.06 + state.spotBrightness * 0.08 + state.beeShapeTransition * 0.06,
                        planeCount: 2,
                        taper: 0.16 + state.beeSoftness * 0.08
                    ))
                    root.addChildNode(makeBeamConeNode(
                        from: startOffset,
                        to: end,
                        nearRadius: 0.014,
                        farRadius: spotOuterRadius,
                        color: state.spotColor,
                        opacity: 0.08 + state.spotBrightness * 0.16,
                        emissionStrength: 0.64
                    ))
                    root.addChildNode(makeBeamConeNode(
                        from: startOffset,
                        to: end,
                        nearRadius: 0.010,
                        farRadius: spotFarRadius,
                        color: state.spotColor,
                        opacity: 0.14 + state.spotBrightness * 0.18,
                        emissionStrength: 0.96
                    ))
                    root.addChildNode(
                        makeEndpointGlowNode(
                            at: end + offset * 0.02,
                            color: state.spotColor,
                            radius: 0.034 + state.spotBrightness * 0.028 + state.beeSpread * 0.012,
                            opacity: 0.12 + state.spotBrightness * 0.22
                        )
                    )
                    if let patternID = state.spotPatternID, !state.spotPatternOpen {
                        root.addChildNode(
                            makeBeeEyePatternHitNode(
                                at: end + offset * 0.04,
                                direction: direction,
                                up: basis.up,
                                patternID: patternID,
                                rotationDegrees: state.spotPatternRotationDegrees,
                                color: state.spotColor,
                                size: CGFloat(beePatternProjectedSize(distance: throwDistance)) * (0.92 + state.beeSpread * 0.20),
                                opacity: 0.18 + state.spotBrightness * (0.26 + state.beeShapeTransition * 0.16)
                            )
                        )
                    } else {
                        root.addChildNode(
                            makeProjectedHitNode(
                                at: end + offset * 0.04,
                                direction: direction,
                                up: basis.up,
                                color: state.spotColor,
                                size: CGSize(
                                    width: 0.14 + state.spotBrightness * 0.05 + state.beeSpread * 0.03,
                                    height: 0.14 + state.spotBrightness * 0.05 + state.beeSpread * 0.03
                                ),
                                opacity: 0.14 + state.spotBrightness * 0.20
                            )
                        )
                    }
                }
            } else {
                root.addChildNode(makeBeamFogNode(
                    from: SCNVector3(0, 0, 0),
                    to: state.end,
                    width: 0.34,
                    color: state.washColor,
                    opacity: 0.08 + state.brightness * 0.12,
                    planeCount: 4,
                    taper: 0.26
                ))
                root.addChildNode(makeBeamConeNode(
                    from: SCNVector3(0, 0, 0),
                    to: state.end,
                    nearRadius: 0.020,
                    farRadius: 0.16,
                    color: state.washColor,
                    opacity: 0.05 + state.brightness * 0.14,
                    emissionStrength: 0.44
                ))
                root.addChildNode(makeBeamConeNode(
                    from: SCNVector3(0, 0, 0),
                    to: state.end,
                    nearRadius: 0.015,
                    farRadius: 0.11,
                    color: state.washColor,
                    opacity: 0.10 + state.brightness * 0.14,
                    emissionStrength: 0.62
                ))
                root.addChildNode(makeBeamConeNode(
                    from: SCNVector3(0, 0, 0),
                    to: state.end,
                    nearRadius: 0.010,
                    farRadius: 0.072,
                    color: state.washColor,
                    opacity: 0.16 + state.brightness * 0.24,
                    emissionStrength: 0.98
                ))
                root.addChildNode(
                    makeEndpointGlowNode(
                        at: state.end,
                        color: state.washColor,
                        radius: 0.060 + state.brightness * 0.04,
                        opacity: 0.12 + state.brightness * 0.20
                    )
                )
                root.addChildNode(
                    makeProjectedHitNode(
                        at: state.end + direction * 0.02,
                        direction: direction,
                        up: basis.up,
                        color: state.washColor,
                        size: CGSize(width: 0.18 + state.brightness * 0.05, height: 0.18 + state.brightness * 0.05),
                        opacity: 0.18 + state.brightness * 0.22
                    )
                )
            }
        case .wallWash:
            break
        case .staticWash:
            root.addChildNode(makeBeamFogNode(
                from: SCNVector3(0, 0, 0),
                to: state.end,
                width: 0.42,
                color: state.washColor,
                opacity: 0.08 + state.brightness * 0.12,
                planeCount: 4,
                taper: 0.28
            ))
            root.addChildNode(makeBeamConeNode(
                from: SCNVector3(0, 0, 0),
                to: state.end,
                nearRadius: 0.026,
                farRadius: 0.19,
                color: state.washColor,
                opacity: 0.06 + state.brightness * 0.14,
                emissionStrength: 0.48
            ))
            root.addChildNode(makeBeamConeNode(
                from: SCNVector3(0, 0, 0),
                to: state.end,
                nearRadius: 0.014,
                farRadius: 0.095,
                color: state.washColor,
                opacity: 0.16 + state.brightness * 0.20,
                emissionStrength: 0.92
            ))
            root.addChildNode(
                makeEndpointGlowNode(
                    at: state.end,
                    color: state.washColor,
                    radius: 0.056 + state.brightness * 0.04,
                    opacity: 0.12 + state.brightness * 0.18
                )
            )
            root.addChildNode(
                makeProjectedHitNode(
                    at: state.end + direction * 0.02,
                    direction: direction,
                    up: basis.up,
                    color: state.washColor,
                    size: CGSize(width: 0.22 + state.brightness * 0.05, height: 0.22 + state.brightness * 0.05),
                    opacity: 0.12 + state.brightness * 0.18
                )
            )
        }

        if state.strobeActive {
            root.addChildNode(makeBeamConeNode(
                from: SCNVector3(0, 0, 0),
                to: state.end,
                nearRadius: 0.012,
                farRadius: 0.05,
                color: NSColor.white,
                opacity: 0.06 + state.brightness * 0.12,
                emissionStrength: 1.05
            ))
            root.addChildNode(
                makeProjectedHitNode(
                    at: state.end + direction * 0.03,
                    direction: direction,
                    up: basis.up,
                    color: NSColor.white,
                    size: CGSize(width: 0.18 + state.brightness * 0.04, height: 0.18 + state.brightness * 0.04),
                    opacity: 0.10 + state.brightness * 0.16
                )
            )
        }

        return root
    }

    private func makeBeamFogNode(
        from start: SCNVector3,
        to end: SCNVector3,
        width: CGFloat,
        color: NSColor,
        opacity: CGFloat,
        planeCount: Int,
        taper: CGFloat
    ) -> SCNNode {
        let direction = sceneVectorSubtract(end, start)
        let length = sceneVectorLength(direction)
        guard length > 0.0001 else { return SCNNode() }

        let root = SCNNode()
        root.position = sceneVectorMidpoint(start, end)
        root.look(at: end, up: SCNVector3(0, 1, 0), localFront: SCNVector3(0, 1, 0))
        root.addParticleSystem(
            makeBeamParticleSystem(
                length: length,
                width: width,
                color: color,
                opacity: opacity,
                density: planeCount,
                taper: taper,
                outer: false
            )
        )
        root.addParticleSystem(
            makeBeamParticleSystem(
                length: length,
                width: width * 1.35,
                color: color,
                opacity: opacity * 0.82,
                density: max(planeCount + 1, 3),
                taper: taper * 1.15,
                outer: true
            )
        )

        return root
    }

    private func makeBeamParticleSystem(
        length: CGFloat,
        width: CGFloat,
        color: NSColor,
        opacity: CGFloat,
        density: Int,
        taper: CGFloat,
        outer: Bool
    ) -> SCNParticleSystem {
        let system = SCNParticleSystem()
        let radiusScale = outer ? 0.16 : 0.09
        let velocityScale = outer ? 0.022 : 0.014
        let imageSize = outer ? 256 : 160

        system.loops = true
        system.warmupDuration = outer ? 1.6 : 1.2
        system.birthRate = CGFloat(max(140, density * (outer ? 180 : 130)))
        system.particleLifeSpan = outer ? 2.2 : 1.6
        system.particleLifeSpanVariation = outer ? 0.55 : 0.35
        system.emitterShape = SCNCylinder(
            radius: max(0.02, width * max(radiusScale, taper * 0.24)),
            height: length
        )
        system.birthLocation = .volume
        system.birthDirection = .constant
        system.emittingDirection = SCNVector3(0, 1, 0)
        system.spreadingAngle = outer ? 14 : 8
        system.particleVelocity = max(0.04, length * velocityScale)
        system.particleVelocityVariation = max(0.02, length * velocityScale * 0.75)
        system.acceleration = SCNVector3(0, length * (outer ? 0.020 : 0.012), 0)
        system.particleSize = max(0.045, width * (outer ? 0.30 : 0.18))
        system.particleSizeVariation = system.particleSize * (outer ? 0.60 : 0.46)
        system.stretchFactor = outer ? 2.2 : 1.55
        system.blendMode = .additive
        system.isLightingEnabled = false
        system.isLocal = true
        system.particleColor = color.withAlphaComponent(opacity * (outer ? 0.32 : 0.44))
        system.particleColorVariation = SCNVector4(0.04, 0.04, 0.04, outer ? 0.14 : 0.10)
        system.particleImage = beamSpriteTexture(size: imageSize)
        return system
    }

    private func makeBeamScatterNode(
        length: CGFloat,
        width: CGFloat,
        color: NSColor,
        opacity: CGFloat,
        density: Int
    ) -> SCNNode {
        let root = SCNNode()
        guard let texture = beamSpriteTexture(size: 192) else { return root }

        let spriteCount = max(4, density * 3)
        for index in 0..<spriteCount {
            let progress = CGFloat(index + 1) / CGFloat(spriteCount + 1)
            let spriteWidth = max(0.08, width * (0.22 + progress * 0.34))
            let spriteHeight = spriteWidth * (1.15 + progress * 0.65)
            let plane = SCNPlane(width: spriteWidth, height: spriteHeight)
            let material = makeEmissiveMaterial(
                color: color,
                emission: color,
                emissionStrength: 1.0,
                opacity: opacity * (0.24 + progress * 0.34)
            )
            material.lightingModel = .constant
            material.diffuse.contents = color
            material.emission.contents = color
            material.transparent.contents = texture
            material.blendMode = .add
            material.isDoubleSided = true
            material.readsFromDepthBuffer = false
            material.writesToDepthBuffer = false
            plane.materials = [material]

            let node = SCNNode(geometry: plane)
            let spiral = progress * .pi * 4.0
            let offsetRadius = width * (0.03 + progress * 0.14)
            node.position = SCNVector3(
                cos(spiral) * offsetRadius,
                (-length * 0.5) + progress * length,
                sin(spiral * 1.35) * offsetRadius * 0.72
            )
            let billboard = SCNBillboardConstraint()
            billboard.freeAxes = []
            node.constraints = [billboard]
            root.addChildNode(node)
        }

        return root
    }

    private func makeBeamConeNode(
        from start: SCNVector3,
        to end: SCNVector3,
        nearRadius: CGFloat,
        farRadius: CGFloat,
        color: NSColor,
        opacity: CGFloat,
        emissionStrength: CGFloat
    ) -> SCNNode {
        let direction = sceneVectorSubtract(end, start)
        let length = sceneVectorLength(direction)
        guard length > 0.0001 else { return SCNNode() }

        let geometry = SCNCone(topRadius: farRadius, bottomRadius: nearRadius, height: length)
        let material = makeEmissiveMaterial(
            color: color,
            emission: color,
            emissionStrength: emissionStrength * 1.10,
            opacity: opacity * 0.62
        )
        material.lightingModel = .constant
        material.isDoubleSided = true
        material.blendMode = .add
        material.readsFromDepthBuffer = false
        material.writesToDepthBuffer = false
        material.transparent.contents = beamFogTexture(
            width: 320,
            height: 960,
            taper: max(0.12, min(0.36, (nearRadius / max(farRadius, 0.0001)) * 0.70 + 0.12))
        )
        material.shaderModifiers = beamConeShaderModifiers
        let radiusRatio = max(1.0, farRadius / max(nearRadius, 0.0001))
        let falloffExponent = min(3.6, max(1.2, 1.55 + farRadius * 2.2))
        let sourceLift = min(0.78, max(0.18, 0.22 + opacity * 0.42))
        let viewExponent = min(2.2, max(0.8, 1.65 - farRadius * 1.1))
        let noiseAmount = min(0.22, max(0.04, 0.05 + farRadius * 0.22))
        let noiseScale = min(16.0, max(5.5, 8.0 + radiusRatio * 0.6))
        let minimumAlpha = min(0.42, max(0.06, opacity * 0.18))
        let glowBoost = min(0.9, max(0.28, 0.34 + emissionStrength * 0.28))
        material.setValue(NSNumber(value: Double(falloffExponent)), forKey: "beamFalloffExponent")
        material.setValue(NSNumber(value: Double(sourceLift)), forKey: "beamSourceLift")
        material.setValue(NSNumber(value: Double(viewExponent)), forKey: "beamViewExponent")
        material.setValue(NSNumber(value: Double(noiseAmount)), forKey: "beamNoiseAmount")
        material.setValue(NSNumber(value: Double(noiseScale)), forKey: "beamNoiseScale")
        material.setValue(NSNumber(value: Double(minimumAlpha)), forKey: "beamMinimumAlpha")
        material.setValue(NSNumber(value: Double(glowBoost)), forKey: "beamGlowBoost")
        geometry.radialSegmentCount = 28
        geometry.materials = [material]

        let node = SCNNode(geometry: geometry)
        node.position = sceneVectorMidpoint(start, end)
        node.look(at: end, up: SCNVector3(0, 1, 0), localFront: SCNVector3(0, 1, 0))
        return node
    }

    private func makeEndpointGlowNode(
        at position: SCNVector3,
        color: NSColor,
        radius: CGFloat,
        opacity: CGFloat,
        scale: SCNVector3 = SCNVector3(1.0, 0.75, 1.0)
    ) -> SCNNode {
        let sphere = SCNSphere(radius: radius)
        let material = makeEmissiveMaterial(
            color: NSColor.white,
            emission: color,
            emissionStrength: 1.02,
            opacity: opacity
        )
        material.lightingModel = .constant
        material.blendMode = .add
        material.readsFromDepthBuffer = false
        material.writesToDepthBuffer = false
        sphere.materials = [material]
        let node = SCNNode(geometry: sphere)
        node.position = position
        node.scale = scale
        return node
    }

    private func makeProjectedHitNode(
        at position: SCNVector3,
        direction: SCNVector3,
        up: SCNVector3,
        color: NSColor,
        size: CGSize,
        opacity: CGFloat
    ) -> SCNNode {
        let plane = SCNPlane(width: size.width, height: size.height)
        let material = makeEmissiveMaterial(
            color: NSColor.white,
            emission: color,
            emissionStrength: 0.98,
            opacity: opacity
        )
        material.lightingModel = .constant
        material.blendMode = .add
        material.isDoubleSided = true
        material.diffuse.contents = color
        material.emission.contents = color
        material.transparent.contents = projectedHitTexture(size: 256)
        material.readsFromDepthBuffer = false
        material.writesToDepthBuffer = false
        plane.materials = [material]

        let node = SCNNode(geometry: plane)
        node.position = position
        node.look(at: position + direction, up: up, localFront: SCNVector3(0, 0, 1))
        return node
    }

    private func makeBeeEyePatternHitNode(
        at position: SCNVector3,
        direction: SCNVector3,
        up: SCNVector3,
        patternID: String,
        rotationDegrees: Double,
        color: NSColor,
        size: CGFloat,
        opacity: CGFloat
    ) -> SCNNode {
        let root = SCNNode()
        root.position = position
        root.look(at: position + direction, up: up, localFront: SCNVector3(0, 0, 1))
        root.eulerAngles.z += CGFloat(rotationDegrees * .pi / 180.0)

        root.addChildNode(
            makeProjectedHitNode(
                at: SCNVector3(0, 0, 0),
                direction: SCNVector3(0, 0, 1),
                up: SCNVector3(0, 1, 0),
                color: color,
                size: CGSize(width: size * 1.02, height: size * 1.02),
                opacity: opacity * 0.44
            )
        )

        if let maskImage = beePatternMaskRasterImage(patternID: patternID, size: max(96, Int((size * 520).rounded()))) {
            let plane = SCNPlane(width: size, height: size)
            let material = makeEmissiveMaterial(
                color: color,
                emission: color,
                emissionStrength: 1.0,
                opacity: opacity
            )
            material.lightingModel = .constant
            material.diffuse.contents = color
            material.emission.contents = color
            material.blendMode = .add
            material.isDoubleSided = true
            material.transparent.contents = maskImage
            material.readsFromDepthBuffer = false
            material.writesToDepthBuffer = false
            plane.materials = [material]
            let planeNode = SCNNode(geometry: plane)
            root.addChildNode(planeNode)
        }

        return root
    }

    private func makeRoundedBoxNode(
        width: CGFloat,
        height: CGFloat,
        length: CGFloat,
        chamfer: CGFloat,
        color: NSColor,
        emission: NSColor,
        emissionStrength: CGFloat,
        opacity: CGFloat
    ) -> SCNNode {
        let geometry = SCNBox(width: width, height: height, length: length, chamferRadius: chamfer)
        geometry.materials = [makeEmissiveMaterial(
            color: color,
            emission: emission,
            emissionStrength: emissionStrength,
            opacity: opacity
        )]
        return SCNNode(geometry: geometry)
    }

    private func makeEmissiveMaterial(
        color: NSColor,
        emission: NSColor,
        emissionStrength: CGFloat,
        opacity: CGFloat
    ) -> SCNMaterial {
        let material = SCNMaterial()
        material.diffuse.contents = color
        material.emission.contents = emission
        material.emission.intensity = emissionStrength
        material.roughness.contents = 0.42
        material.metalness.contents = 0.08
        material.transparency = opacity
        return material
    }

    private func beamFogTexture(width: Int, height: Int, taper: CGFloat) -> NSImage? {
        let key = "\(width)x\(height)-\(Int((taper * 1000).rounded()))"
        if let cached = beamSpriteTextureCache[key] {
            return cached
        }

        let image = NSImage(size: NSSize(width: width, height: height))
        image.lockFocus()
        defer { image.unlockFocus() }
        guard let context = NSGraphicsContext.current?.cgContext else { return nil }

        context.clear(CGRect(x: 0, y: 0, width: width, height: height))
        context.setAllowsAntialiasing(true)
        context.setShouldAntialias(true)

        let colorSpace = CGColorSpaceCreateDeviceRGB()
        let rect = CGRect(x: 0, y: 0, width: width, height: height)
        let beamPath = CGMutablePath()
        beamPath.addRect(rect)

        context.saveGState()
        context.addPath(beamPath)
        context.clip()

        let w = CGFloat(width)
        let h = CGFloat(height)
        let centerX = w * 0.5
        let startRadius = w * max(0.03, min(0.10, taper * 0.30))
        let endRadius = w * max(0.30, min(0.58, 0.22 + taper * 1.18))
        let coreGradient = CGGradient(
            colorsSpace: colorSpace,
            colors: [
                NSColor.clear.cgColor,
                NSColor.white.withAlphaComponent(0.18).cgColor,
                NSColor.white.withAlphaComponent(0.86).cgColor,
                NSColor.white.withAlphaComponent(0.18).cgColor,
                NSColor.clear.cgColor,
            ] as CFArray,
            locations: [0.0, 0.16, 0.50, 0.84, 1.0]
        )
        let hazeGradient = CGGradient(
            colorsSpace: colorSpace,
            colors: [
                NSColor.clear.cgColor,
                NSColor.white.withAlphaComponent(0.08).cgColor,
                NSColor.white.withAlphaComponent(0.34).cgColor,
                NSColor.white.withAlphaComponent(0.08).cgColor,
                NSColor.clear.cgColor,
            ] as CFArray,
            locations: [0.0, 0.22, 0.50, 0.78, 1.0]
        )

        if let hazeGradient {
            context.saveGState()
            context.scaleBy(x: 1.18, y: 1.0)
            context.drawRadialGradient(
                hazeGradient,
                startCenter: CGPoint(x: centerX / 1.18, y: h * 0.08),
                startRadius: startRadius * 1.4,
                endCenter: CGPoint(x: centerX / 1.18, y: h * 0.68),
                endRadius: endRadius * 1.22,
                options: [.drawsAfterEndLocation]
            )
            context.restoreGState()
        }
        if let coreGradient {
            context.drawRadialGradient(
                coreGradient,
                startCenter: CGPoint(x: centerX, y: h * 0.05),
                startRadius: startRadius,
                endCenter: CGPoint(x: centerX, y: h * 0.74),
                endRadius: endRadius,
                options: [.drawsAfterEndLocation]
            )
        }
        context.restoreGState()

        beamSpriteTextureCache[key] = image
        return image
    }

    private func beamSpriteTexture(size: Int) -> NSImage? {
        let key = "sprite-\(size)"
        if let cached = beamSpriteTextureCache[key] {
            return cached
        }

        let image = NSImage(size: NSSize(width: size, height: size))
        image.lockFocus()
        defer { image.unlockFocus() }
        guard let context = NSGraphicsContext.current?.cgContext else { return nil }

        context.clear(CGRect(x: 0, y: 0, width: size, height: size))
        context.setAllowsAntialiasing(true)
        context.setShouldAntialias(true)

        let colorSpace = CGColorSpaceCreateDeviceRGB()
        let gradient = CGGradient(
            colorsSpace: colorSpace,
            colors: [
                NSColor.clear.cgColor,
                NSColor.white.withAlphaComponent(0.10).cgColor,
                NSColor.white.withAlphaComponent(0.74).cgColor,
                NSColor.white.withAlphaComponent(0.18).cgColor,
                NSColor.clear.cgColor,
            ] as CFArray,
            locations: [0.0, 0.22, 0.46, 0.72, 1.0]
        )

        context.saveGState()
        context.translateBy(x: CGFloat(size) * 0.5, y: CGFloat(size) * 0.5)
        context.scaleBy(x: 1.24, y: 0.88)
        if let gradient {
            context.drawRadialGradient(
                gradient,
                startCenter: .zero,
                startRadius: 0,
                endCenter: .zero,
                endRadius: CGFloat(size) * 0.42,
                options: [.drawsAfterEndLocation]
            )
        }
        context.restoreGState()

        beamSpriteTextureCache[key] = image
        return image
    }

    private func projectedHitTexture(size: Int) -> NSImage? {
        let key = "hit-\(size)"
        if let cached = beamSpriteTextureCache[key] {
            return cached
        }

        let image = NSImage(size: NSSize(width: size, height: size))
        image.lockFocus()
        defer { image.unlockFocus() }
        guard let context = NSGraphicsContext.current?.cgContext else { return nil }

        context.clear(CGRect(x: 0, y: 0, width: size, height: size))
        context.setAllowsAntialiasing(true)
        context.setShouldAntialias(true)

        let colorSpace = CGColorSpaceCreateDeviceRGB()
        let gradient = CGGradient(
            colorsSpace: colorSpace,
            colors: [
                NSColor.clear.cgColor,
                NSColor.white.withAlphaComponent(0.28).cgColor,
                NSColor.white.withAlphaComponent(0.92).cgColor,
                NSColor.white.withAlphaComponent(0.26).cgColor,
                NSColor.clear.cgColor,
            ] as CFArray,
            locations: [0.0, 0.18, 0.46, 0.72, 1.0]
        )

        context.saveGState()
        context.translateBy(x: CGFloat(size) * 0.5, y: CGFloat(size) * 0.5)
        context.scaleBy(x: 1.10, y: 0.86)
        if let gradient {
            context.drawRadialGradient(
                gradient,
                startCenter: .zero,
                startRadius: 0,
                endCenter: .zero,
                endRadius: CGFloat(size) * 0.44,
                options: [.drawsAfterEndLocation]
            )
        }
        context.restoreGState()

        beamSpriteTextureCache[key] = image
        return image
    }

    private func beePatternTexture(patternID: String, color: NSColor, size: Int) -> NSImage? {
        let deviceColor = color.usingColorSpace(.deviceRGB) ?? color
        let red = Int((deviceColor.redComponent * 255.0).rounded())
        let green = Int((deviceColor.greenComponent * 255.0).rounded())
        let blue = Int((deviceColor.blueComponent * 255.0).rounded())
        let key = "\(patternID)-\(red)-\(green)-\(blue)-\(size)"
        if let cached = beePatternTextureCache[key] {
            return cached
        }

        guard let image = beePatternTintedRasterImage(patternID: patternID, color: color, size: size) else {
            return nil
        }
        beePatternTextureCache[key] = image
        return image
    }
}

private let stageMetalShaderSource = """
#include <metal_stdlib>
using namespace metal;

struct MetalUniforms {
    float4x4 viewProjection;
};

struct ColorVertex {
    float3 position;
    float4 color;
};

struct BeamVertex {
    float3 position;
    float4 color;
    float axial;
    float lateral;
    float mode;
};

struct SpriteVertex {
    float3 position;
    float2 uv;
    float4 color;
    float patternKind;
    float textureBlend;
};

struct ColorOut {
    float4 position [[position]];
    float4 color;
};

struct BeamOut {
    float4 position [[position]];
    float4 color;
    float axial;
    float lateral;
    float mode;
};

struct SpriteOut {
    float4 position [[position]];
    float2 uv;
    float4 color;
    float patternKind;
    float textureBlend;
};

vertex ColorOut stageColorVertex(
    uint vertexID [[vertex_id]],
    constant ColorVertex *vertices [[buffer(0)]],
    constant MetalUniforms &uniforms [[buffer(1)]]
) {
    ColorOut out;
    float4 world = float4(vertices[vertexID].position, 1.0);
    out.position = uniforms.viewProjection * world;
    out.color = vertices[vertexID].color;
    return out;
}

fragment half4 stageColorFragment(ColorOut in [[stage_in]]) {
    return half4(half3(in.color.rgb), half(in.color.a));
}

vertex BeamOut stageBeamVertex(
    uint vertexID [[vertex_id]],
    constant BeamVertex *vertices [[buffer(0)]],
    constant MetalUniforms &uniforms [[buffer(1)]]
) {
    BeamOut out;
    float4 world = float4(vertices[vertexID].position, 1.0);
    out.position = uniforms.viewProjection * world;
    out.color = vertices[vertexID].color;
    out.axial = vertices[vertexID].axial;
    out.lateral = vertices[vertexID].lateral;
    out.mode = vertices[vertexID].mode;
    return out;
}

fragment half4 stageBeamFragment(BeamOut in [[stage_in]]) {
    if (in.mode > 0.85) {
        float x = in.lateral;
        float y = in.axial;
        float r2 = x * x + y * y;
        float core = exp(-r2 * 6.2);
        float haze = exp(-r2 * 1.55);
        float edgeFade = 1.0 - smoothstep(0.82, 1.12, sqrt(r2));
        float alpha = in.color.a * (core * 0.52 + haze * 0.78) * edgeFade;
        float3 rgb = in.color.rgb * alpha * (1.02 + core * 0.38);
        return half4(half3(rgb), half(alpha));
    }
    float t = saturate(in.axial);
    float side = abs(in.lateral);
    float sideSquared = side * side;
    float d = mix(0.22, 1.0, t);
    float inverseSquare = (0.22 * 0.22) / (d * d);
    float softenedDistance = mix(inverseSquare, 1.0 / (1.0 + 0.85 * t + 1.85 * t * t), 0.68);
    float sourceHot = 0.82 + 0.18 * pow(max(0.0, 1.0 - t), 0.9);
    float breakup = 0.97 + 0.03 * sin(t * 9.0 + side * 2.8);
    float alpha;
    float3 rgb;

    if (in.mode < 0.15) {
        float beamCore = exp(-0.693147 * sideSquared); // 50% at beam-angle edge
        float beamFill = exp(-1.55 * sideSquared) * 0.22;
        float tailFade = 1.0 - smoothstep(0.90, 1.0, t) * 0.18;
        alpha = in.color.a * (beamCore + beamFill) * softenedDistance * sourceHot * tailFade * breakup;
        rgb = in.color.rgb * alpha * (1.02 + beamCore * 0.34);
    } else if (in.mode < 0.4) {
        float fieldShell = exp(-2.302585 * sideSquared); // 10% at field-angle edge
        float hazeShell = exp(-0.92 * sideSquared) * 0.30;
        float tailFade = 1.0 - smoothstep(0.94, 1.0, t) * 0.22;
        alpha = in.color.a * (fieldShell + hazeShell) * softenedDistance * tailFade * breakup;
        rgb = in.color.rgb * alpha * (0.94 + hazeShell * 0.18);
    } else {
        float structure = exp(-1.35 * sideSquared);
        float tailFade = 1.0 - smoothstep(0.86, 1.0, t) * 0.28;
        alpha = in.color.a * structure * softenedDistance * tailFade * 0.72;
        rgb = in.color.rgb * alpha * 0.92;
    }
    return half4(half3(rgb), half(alpha));
}

vertex SpriteOut stageSpriteVertex(
    uint vertexID [[vertex_id]],
    constant SpriteVertex *vertices [[buffer(0)]],
    constant MetalUniforms &uniforms [[buffer(1)]]
) {
    SpriteOut out;
    float4 world = float4(vertices[vertexID].position, 1.0);
    out.position = uniforms.viewProjection * world;
    out.uv = vertices[vertexID].uv;
    out.color = vertices[vertexID].color;
    out.patternKind = vertices[vertexID].patternKind;
    out.textureBlend = vertices[vertexID].textureBlend;
    return out;
}

float softCircle(float2 p, float radius, float blur) {
    return 1.0 - smoothstep(radius, radius + blur, length(p));
}

float softEllipse(float2 p, float2 radii, float blur) {
    float2 normalized = p / max(radii, float2(0.0001));
    return 1.0 - smoothstep(1.0, 1.0 + blur, length(normalized));
}

float softCapsule(float2 p, float2 a, float2 b, float radius, float blur) {
    float2 pa = p - a;
    float2 ba = b - a;
    float h = clamp(dot(pa, ba) / max(dot(ba, ba), 0.0001), 0.0, 1.0);
    return 1.0 - smoothstep(radius, radius + blur, length(pa - ba * h));
}

float softArc(float2 p, float radius, float thickness, float angleCenter, float angleSpan, float blur) {
    float angle = atan2(p.y, p.x);
    float delta = atan2(sin(angle - angleCenter), cos(angle - angleCenter));
    float radial = 1.0 - smoothstep(thickness, thickness + blur, abs(length(p) - radius));
    float angular = 1.0 - smoothstep(angleSpan * 0.5, angleSpan * 0.5 + blur * 2.4, abs(delta));
    return radial * angular;
}

float rotatedPetal(float2 p, float angle, float distance, float width, float height, float blur) {
    float c = cos(angle);
    float s = sin(angle);
    float2 rp = float2(
        c * p.x - s * p.y,
        s * p.x + c * p.y
    );
    rp.y += distance;
    return softEllipse(rp, float2(width, height), blur);
}

float beePatternMask(float2 uv, float patternKind) {
    float2 p = uv * 2.0 - 1.0;
    p.y *= -1.0;
    const float blur = 0.08;
    float mask = 0.0;

    if (patternKind < 0.5) {
        mask = softCircle(p, 0.78, blur);
    } else if (patternKind < 1.5) {
        for (int i = 0; i < 5; ++i) {
            float angle = float(i) * 1.25663706144 + 0.31415926535;
            float2 dir = float2(cos(angle), sin(angle));
            float2 normal = float2(-dir.y, dir.x) * 0.06;
            mask = max(mask, softCapsule(p, dir * 0.10 + normal, dir * 0.62 + normal, 0.055, blur));
            mask = max(mask, softCapsule(p, dir * 0.10 - normal, dir * 0.62 - normal, 0.055, blur));
        }
    } else if (patternKind < 2.5) {
        for (int i = 0; i < 5; ++i) {
            float angle = float(i) * 1.25663706144;
            mask = max(mask, rotatedPetal(p, angle, 0.36, 0.18, 0.34, blur));
        }
        mask *= (1.0 - softCircle(p, 0.18, blur));
    } else if (patternKind < 3.5) {
        for (int i = 0; i < 5; ++i) {
            float angle = float(i) * 1.25663706144 + 0.42;
            mask = max(mask, rotatedPetal(p, angle, 0.26, 0.15, 0.34, blur));
        }
    } else if (patternKind < 4.5) {
        for (int i = 0; i < 8; ++i) {
            float angle = float(i) * 0.78539816339;
            float2 dir = float2(cos(angle), sin(angle));
            mask = max(mask, softCircle(p - dir * 0.14, 0.055, blur));
            mask = max(mask, softCircle(p - dir * 0.28, 0.065, blur));
            mask = max(mask, softCircle(p - dir * 0.42, 0.075, blur));
            mask = max(mask, softCircle(p - dir * 0.56, 0.085, blur));
        }
    } else if (patternKind < 5.5) {
        const int count = 16;
        const float2 offsets[count] = {
            float2(-0.44, -0.40),
            float2(-0.16, -0.48),
            float2(0.14, -0.46),
            float2(0.42, -0.36),
            float2(-0.50, -0.08),
            float2(-0.24, -0.12),
            float2(0.02, -0.10),
            float2(0.28, -0.06),
            float2(0.52, 0.00),
            float2(-0.36, 0.18),
            float2(-0.10, 0.16),
            float2(0.16, 0.18),
            float2(0.42, 0.22),
            float2(-0.18, 0.46),
            float2(0.10, 0.46),
            float2(0.38, 0.42)
        };
        for (int i = 0; i < count; ++i) {
            float angle = -0.30 + float(i % 4) * 0.10;
            mask = max(mask, rotatedPetal(p - offsets[i], angle, 0.02, 0.07, 0.11, blur));
        }
    } else if (patternKind < 6.5) {
        for (int i = 0; i < 3; ++i) {
            float angle = float(i) * 2.09439510239 + 0.22;
            mask = max(mask, softArc(p - float2(cos(angle), sin(angle)) * 0.06, 0.34, 0.09, angle + 1.10, 2.10, blur));
        }
        mask *= (1.0 - softCircle(p, 0.16, blur));
    } else {
        float notchMask = 0.0;
        for (int i = 0; i < 5; ++i) {
            float angle = float(i) * 1.25663706144 + 0.60;
            mask = max(mask, rotatedPetal(p, angle, 0.28, 0.16, 0.34, blur));
            float c = cos(angle);
            float s = sin(angle);
            float2 rp = float2(
                c * p.x - s * p.y,
                s * p.x + c * p.y
            );
            notchMask = max(notchMask, softEllipse(rp + float2(0.02, 0.08), float2(0.05, 0.10), blur));
        }
        mask *= (1.0 - notchMask);
        mask *= (1.0 - softCircle(p, 0.14, blur));
    }

    return saturate(mask);
}

fragment half4 stageSpriteFragment(
    SpriteOut in [[stage_in]],
    texture2d<half> patternTexture [[texture(0)]]
) {
    float2 p = in.uv * 2.0 - 1.0;
    float pattern = 0.0;
    if (in.textureBlend > 0.5) {
        constexpr sampler textureSampler(coord::normalized, address::clamp_to_zero, filter::linear);
        half4 textureSample = patternTexture.sample(textureSampler, in.uv);
        pattern = max(textureSample.a, max(textureSample.r, max(textureSample.g, textureSample.b)));
    } else {
        pattern = beePatternMask(in.uv, in.patternKind);
    }
    float halo = softCircle(p, 0.96, 0.32) * 0.24;
    float alpha = saturate(pattern + halo) * in.color.a;
    float core = 0.42 + pattern * 0.92;
    float3 rgb = in.color.rgb * alpha * core;
    return half4(half3(rgb), half(alpha));
}
"""

private struct StageMetalColorVertex {
    var position: SIMD3<Float>
    var color: SIMD4<Float>
}

private struct StageMetalBeamVertex {
    var position: SIMD3<Float>
    var color: SIMD4<Float>
    var axial: Float
    var lateral: Float
    var mode: Float
}

private struct StageMetalSpriteVertex {
    var position: SIMD3<Float>
    var uv: SIMD2<Float>
    var color: SIMD4<Float>
    var patternKind: Float
    var textureBlend: Float
}

private struct StageMetalUniforms {
    var viewProjection: simd_float4x4
}

private struct StageMetalFixtureSnapshot {
    var position: SIMD3<Float>
    var beamKind: StageFixtureBeam.BeamKind
    var isBeeEye: Bool
    var yawDegrees: Float
    var pitchDegrees: Float
    var rollDegrees: Float
    var color: SIMD4<Float>
    var wallWashEmitterColors: [SIMD4<Float>]
    var selected: Bool
}

private struct StageMetalPatternSpriteSnapshot {
    var center: SIMD3<Float>
    var sideAxis: SIMD3<Float>
    var upAxis: SIMD3<Float>
    var size: SIMD2<Float>
    var color: SIMD4<Float>
    var patternID: String
    var patternKind: Float
    var rotationDegrees: Float
    var cameraFacing: Bool
}

private enum StageMetalBeamProfile {
    case round
    case oval
    case fan
}

private struct StageMetalBeamSnapshot {
    var start: SIMD3<Float>
    var end: SIMD3<Float>
    var color: SIMD4<Float>
    var nearSideRadius: Float
    var farSideRadius: Float
    var nearUpRadius: Float
    var farUpRadius: Float
    var expansionExponent: Float
    var ribbonCount: Int
    var segmentCount: Int
    var profile: StageMetalBeamProfile
    var allowFloorProjection: Bool
}

private struct StageMetalPreviewSnapshot {
    var fixtures: [StageMetalFixtureSnapshot]
    var beams: [StageMetalBeamSnapshot]
    var patternSprites: [StageMetalPatternSpriteSnapshot]
}

private struct StageMetalResolvedCamera {
    var position: SIMD3<Float>
    var target: SIMD3<Float>
    var up: SIMD3<Float>
}

private struct StageMetalCameraState {
    var preset: Stage3DCameraPreset = .audience
    var orbitYaw: Float = 0
    var orbitPitch: Float = 0
    var zoomScale: Float = 1
    var panOffset = SIMD3<Float>(repeating: 0)

    mutating func applyPreset(_ preset: Stage3DCameraPreset) {
        guard self.preset != preset else { return }
        self.preset = preset
        orbitYaw = 0
        orbitPitch = 0
        zoomScale = 1
        panOffset = SIMD3<Float>(repeating: 0)
    }

    func resolved() -> StageMetalResolvedCamera {
        let baseTarget = preset.metalTargetPosition
        var offset = preset.metalCameraPosition - baseTarget
        offset = simdRotate(offset, axis: SIMD3<Float>(0, 1, 0), radians: orbitYaw)
        let right = simd_normalize(simd_cross(offset, SIMD3<Float>(0, 1, 0)))
        let pitchAxis = simd_length_squared(right) > 0.0001 ? right : SIMD3<Float>(1, 0, 0)
        offset = simdRotate(offset, axis: pitchAxis, radians: orbitPitch)
        let target = baseTarget + panOffset
        let position = target + offset * zoomScale
        return StageMetalResolvedCamera(position: position, target: target, up: SIMD3<Float>(0, 1, 0))
    }
}

private final class StageMetalPreviewMTKView: MTKView {
    weak var interactionRenderer: StageMetalPreviewRenderer?
    private var dragMode: DragMode?
    private var lastPoint = NSPoint.zero

    private enum DragMode {
        case orbit
        case pan
    }

    override var acceptsFirstResponder: Bool { true }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool {
        true
    }

    override func mouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self)
        dragMode = event.modifierFlags.contains(.option) ? .pan : .orbit
        lastPoint = convert(event.locationInWindow, from: nil)
    }

    override func mouseDragged(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        let deltaX = Float(point.x - lastPoint.x)
        let deltaY = Float(point.y - lastPoint.y)
        switch dragMode {
        case .pan:
            interactionRenderer?.pan(deltaX: deltaX, deltaY: deltaY)
        default:
            interactionRenderer?.orbit(deltaX: deltaX, deltaY: deltaY)
        }
        lastPoint = point
    }

    override func mouseUp(with event: NSEvent) {
        dragMode = nil
    }

    override func rightMouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self)
        dragMode = .pan
        lastPoint = convert(event.locationInWindow, from: nil)
    }

    override func rightMouseDragged(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        interactionRenderer?.pan(
            deltaX: Float(point.x - lastPoint.x),
            deltaY: Float(point.y - lastPoint.y)
        )
        lastPoint = point
    }

    override func rightMouseUp(with event: NSEvent) {
        dragMode = nil
    }

    override func scrollWheel(with event: NSEvent) {
        interactionRenderer?.zoom(delta: Float(event.scrollingDeltaY))
    }

    override func magnify(with event: NSEvent) {
        interactionRenderer?.zoom(delta: Float(-event.magnification * 140))
    }
}

private final class StageMetalPreviewRenderer: NSObject, MTKViewDelegate {
    private weak var model: AppModel?
    private var metalDevice: MTLDevice?
    private var commandQueue: MTLCommandQueue?
    private var colorPipeline: MTLRenderPipelineState?
    private var beamPipeline: MTLRenderPipelineState?
    private var spritePipeline: MTLRenderPipelineState?
    private var solidDepthState: MTLDepthStencilState?
    private var beamDepthState: MTLDepthStencilState?
    private var beePatternMetalTextureCache: [String: MTLTexture] = [:]
    private var cameraState = StageMetalCameraState()

    func attach(model: AppModel, preset: Stage3DCameraPreset) {
        self.model = model
        cameraState.applyPreset(preset)
    }

    func setCameraPreset(_ preset: Stage3DCameraPreset) {
        cameraState.applyPreset(preset)
    }

    func orbit(deltaX: Float, deltaY: Float) {
        cameraState.orbitYaw += deltaX * 0.008
        cameraState.orbitPitch = max(-1.2, min(1.2, cameraState.orbitPitch + deltaY * 0.008))
    }

    func pan(deltaX: Float, deltaY: Float) {
        let resolved = cameraState.resolved()
        let forward = simd_normalize(resolved.target - resolved.position)
        let right = simd_normalize(simd_cross(forward, resolved.up))
        let up = simd_normalize(simd_cross(right, forward))
        let distance = max(0.8, simd_length(resolved.position - resolved.target))
        let scale = distance * 0.0018
        cameraState.panOffset += (-deltaX * scale) * right
        cameraState.panOffset += (deltaY * scale) * up
    }

    func zoom(delta: Float) {
        let factor = 1 + delta * 0.008
        cameraState.zoomScale = min(2.8, max(0.30, cameraState.zoomScale * max(0.85, factor)))
    }

    func mtkView(_ view: MTKView, drawableSizeWillChange size: CGSize) {}

    func draw(in view: MTKView) {
        configureIfNeeded(for: view)
        guard
            let descriptor = view.currentRenderPassDescriptor,
            let drawable = view.currentDrawable,
            let commandQueue,
            let colorPipeline,
            let beamPipeline,
            let spritePipeline,
            let solidDepthState,
            let beamDepthState
        else { return }

        let snapshot = currentSnapshot()
        let camera = cameraState.resolved()
        let uniforms = StageMetalUniforms(
            viewProjection: simdPerspectiveMatrix(
                fovYRadians: 48 * .pi / 180,
                aspect: max(0.1, Float(view.drawableSize.width / max(view.drawableSize.height, 1))),
                near: 0.02,
                far: 60
            ) * simdLookAtMatrix(eye: camera.position, target: camera.target, up: camera.up)
        )

        var lineVertices: [StageMetalColorVertex] = []
        var solidVertices: [StageMetalColorVertex] = []
        var solidIndices: [UInt32] = []
        var beamVertices: [StageMetalBeamVertex] = []
        var beamIndices: [UInt32] = []

        appendStageEnvironment(to: &lineVertices)
        appendFixtures(snapshot.fixtures, to: &solidVertices, indices: &solidIndices)
        appendBeams(
            snapshot.beams,
            cameraPosition: camera.position,
            to: &beamVertices,
            indices: &beamIndices
        )

        let commandBuffer = commandQueue.makeCommandBuffer()
        let encoder = commandBuffer?.makeRenderCommandEncoder(descriptor: descriptor)

        descriptor.colorAttachments[0].clearColor = MTLClearColor(red: 0.025, green: 0.035, blue: 0.055, alpha: 1.0)
        descriptor.depthAttachment.clearDepth = 1.0

        if let encoder {
            if !lineVertices.isEmpty {
                let vertexBuffer = metalDevice?.makeBuffer(
                    bytes: lineVertices,
                    length: MemoryLayout<StageMetalColorVertex>.stride * lineVertices.count
                )
                var uniformsCopy = uniforms
                let uniformBuffer = metalDevice?.makeBuffer(
                    bytes: &uniformsCopy,
                    length: MemoryLayout<StageMetalUniforms>.stride
                )
                encoder.setRenderPipelineState(colorPipeline)
                encoder.setDepthStencilState(solidDepthState)
                encoder.setVertexBuffer(vertexBuffer, offset: 0, index: 0)
                encoder.setVertexBuffer(uniformBuffer, offset: 0, index: 1)
                encoder.drawPrimitives(type: .line, vertexStart: 0, vertexCount: lineVertices.count)
            }

            if !solidVertices.isEmpty, !solidIndices.isEmpty {
                let vertexBuffer = metalDevice?.makeBuffer(
                    bytes: solidVertices,
                    length: MemoryLayout<StageMetalColorVertex>.stride * solidVertices.count
                )
                let indexBuffer = metalDevice?.makeBuffer(
                    bytes: solidIndices,
                    length: MemoryLayout<UInt32>.stride * solidIndices.count
                )
                var uniformsCopy = uniforms
                let uniformBuffer = metalDevice?.makeBuffer(
                    bytes: &uniformsCopy,
                    length: MemoryLayout<StageMetalUniforms>.stride
                )
                encoder.setRenderPipelineState(colorPipeline)
                encoder.setDepthStencilState(solidDepthState)
                encoder.setVertexBuffer(vertexBuffer, offset: 0, index: 0)
                encoder.setVertexBuffer(uniformBuffer, offset: 0, index: 1)
                encoder.drawIndexedPrimitives(
                    type: .triangle,
                    indexCount: solidIndices.count,
                    indexType: .uint32,
                    indexBuffer: indexBuffer!,
                    indexBufferOffset: 0
                )
            }

            if !beamVertices.isEmpty, !beamIndices.isEmpty {
                let vertexBuffer = metalDevice?.makeBuffer(
                    bytes: beamVertices,
                    length: MemoryLayout<StageMetalBeamVertex>.stride * beamVertices.count
                )
                let indexBuffer = metalDevice?.makeBuffer(
                    bytes: beamIndices,
                    length: MemoryLayout<UInt32>.stride * beamIndices.count
                )
                var uniformsCopy = uniforms
                let uniformBuffer = metalDevice?.makeBuffer(
                    bytes: &uniformsCopy,
                    length: MemoryLayout<StageMetalUniforms>.stride
                )
                encoder.setRenderPipelineState(beamPipeline)
                encoder.setDepthStencilState(beamDepthState)
                encoder.setVertexBuffer(vertexBuffer, offset: 0, index: 0)
                encoder.setVertexBuffer(uniformBuffer, offset: 0, index: 1)
                encoder.drawIndexedPrimitives(
                    type: .triangle,
                    indexCount: beamIndices.count,
                    indexType: .uint32,
                    indexBuffer: indexBuffer!,
                    indexBufferOffset: 0
                )
            }

            if !snapshot.patternSprites.isEmpty {
                var uniformsCopy = uniforms
                let uniformBuffer = metalDevice?.makeBuffer(
                    bytes: &uniformsCopy,
                    length: MemoryLayout<StageMetalUniforms>.stride
                )
                encoder.setRenderPipelineState(spritePipeline)
                encoder.setDepthStencilState(beamDepthState)
                encoder.setVertexBuffer(uniformBuffer, offset: 0, index: 1)

                for sprite in snapshot.patternSprites {
                    let patternTexture = metalDevice.flatMap { metalBeePatternTexture(patternID: sprite.patternID, device: $0) }
                    let spriteVertices = makePatternSpriteVertices(
                        for: sprite,
                        cameraPosition: camera.position,
                        textureBlend: patternTexture == nil ? 0.0 : 1.0
                    )
                    guard
                        let vertexBuffer = metalDevice?.makeBuffer(
                            bytes: spriteVertices,
                            length: MemoryLayout<StageMetalSpriteVertex>.stride * spriteVertices.count
                        )
                    else { continue }

                    let indices: [UInt16] = [0, 1, 2, 0, 2, 3]
                    guard let indexBuffer = metalDevice?.makeBuffer(
                        bytes: indices,
                        length: MemoryLayout<UInt16>.stride * indices.count
                    ) else { continue }

                    encoder.setVertexBuffer(vertexBuffer, offset: 0, index: 0)
                    encoder.setFragmentTexture(patternTexture, index: 0)
                    encoder.drawIndexedPrimitives(
                        type: .triangle,
                        indexCount: indices.count,
                        indexType: .uint16,
                        indexBuffer: indexBuffer,
                        indexBufferOffset: 0
                    )
                }
            }

            encoder.endEncoding()
        }

        commandBuffer?.present(drawable)
        commandBuffer?.commit()
    }

    private func configureIfNeeded(for view: MTKView) {
        guard colorPipeline == nil || beamPipeline == nil || spritePipeline == nil else { return }
        guard let device = view.device ?? MTLCreateSystemDefaultDevice() else { return }

        if metalDevice !== device {
            beePatternMetalTextureCache.removeAll()
        }
        metalDevice = device
        view.device = device
        view.colorPixelFormat = .bgra8Unorm
        view.depthStencilPixelFormat = .depth32Float
        view.sampleCount = 1
        view.clearColor = MTLClearColor(red: 0.025, green: 0.035, blue: 0.055, alpha: 1.0)
        view.preferredFramesPerSecond = 60
        view.isPaused = false
        view.enableSetNeedsDisplay = false

        commandQueue = device.makeCommandQueue()

        let library: MTLLibrary
        do {
            library = try device.makeLibrary(source: stageMetalShaderSource, options: nil)
        } catch {
            print("Metal shader compile error:", error)
            return
        }

        let colorDescriptor = MTLRenderPipelineDescriptor()
        colorDescriptor.label = "BeatBeamColorPipeline"
        colorDescriptor.vertexFunction = library.makeFunction(name: "stageColorVertex")
        colorDescriptor.fragmentFunction = library.makeFunction(name: "stageColorFragment")
        colorDescriptor.colorAttachments[0].pixelFormat = view.colorPixelFormat
        colorDescriptor.depthAttachmentPixelFormat = view.depthStencilPixelFormat
        colorDescriptor.vertexDescriptor = nil
        colorDescriptor.colorAttachments[0].isBlendingEnabled = true
        colorDescriptor.colorAttachments[0].rgbBlendOperation = .add
        colorDescriptor.colorAttachments[0].alphaBlendOperation = .add
        colorDescriptor.colorAttachments[0].sourceRGBBlendFactor = .sourceAlpha
        colorDescriptor.colorAttachments[0].destinationRGBBlendFactor = .oneMinusSourceAlpha
        colorDescriptor.colorAttachments[0].sourceAlphaBlendFactor = .sourceAlpha
        colorDescriptor.colorAttachments[0].destinationAlphaBlendFactor = .oneMinusSourceAlpha

        let beamDescriptor = MTLRenderPipelineDescriptor()
        beamDescriptor.label = "BeatBeamBeamPipeline"
        beamDescriptor.vertexFunction = library.makeFunction(name: "stageBeamVertex")
        beamDescriptor.fragmentFunction = library.makeFunction(name: "stageBeamFragment")
        beamDescriptor.colorAttachments[0].pixelFormat = view.colorPixelFormat
        beamDescriptor.depthAttachmentPixelFormat = view.depthStencilPixelFormat
        beamDescriptor.vertexDescriptor = nil
        beamDescriptor.colorAttachments[0].isBlendingEnabled = true
        beamDescriptor.colorAttachments[0].rgbBlendOperation = .add
        beamDescriptor.colorAttachments[0].alphaBlendOperation = .add
        beamDescriptor.colorAttachments[0].sourceRGBBlendFactor = .sourceAlpha
        beamDescriptor.colorAttachments[0].destinationRGBBlendFactor = .one
        beamDescriptor.colorAttachments[0].sourceAlphaBlendFactor = .one
        beamDescriptor.colorAttachments[0].destinationAlphaBlendFactor = .oneMinusSourceAlpha

        let spriteDescriptor = MTLRenderPipelineDescriptor()
        spriteDescriptor.label = "BeatBeamSpritePipeline"
        spriteDescriptor.vertexFunction = library.makeFunction(name: "stageSpriteVertex")
        spriteDescriptor.fragmentFunction = library.makeFunction(name: "stageSpriteFragment")
        spriteDescriptor.colorAttachments[0].pixelFormat = view.colorPixelFormat
        spriteDescriptor.depthAttachmentPixelFormat = view.depthStencilPixelFormat
        spriteDescriptor.vertexDescriptor = nil
        spriteDescriptor.colorAttachments[0].isBlendingEnabled = true
        spriteDescriptor.colorAttachments[0].rgbBlendOperation = .add
        spriteDescriptor.colorAttachments[0].alphaBlendOperation = .add
        spriteDescriptor.colorAttachments[0].sourceRGBBlendFactor = .one
        spriteDescriptor.colorAttachments[0].destinationRGBBlendFactor = .one
        spriteDescriptor.colorAttachments[0].sourceAlphaBlendFactor = .one
        spriteDescriptor.colorAttachments[0].destinationAlphaBlendFactor = .oneMinusSourceAlpha

        do {
            colorPipeline = try device.makeRenderPipelineState(descriptor: colorDescriptor)
            beamPipeline = try device.makeRenderPipelineState(descriptor: beamDescriptor)
            spritePipeline = try device.makeRenderPipelineState(descriptor: spriteDescriptor)
        } catch {
            print("Metal pipeline error:", error)
            return
        }

        let solidDepth = MTLDepthStencilDescriptor()
        solidDepth.depthCompareFunction = .lessEqual
        solidDepth.isDepthWriteEnabled = true
        solidDepthState = device.makeDepthStencilState(descriptor: solidDepth)

        let beamDepth = MTLDepthStencilDescriptor()
        beamDepth.depthCompareFunction = .lessEqual
        beamDepth.isDepthWriteEnabled = false
        beamDepthState = device.makeDepthStencilState(descriptor: beamDepth)
    }

    private func metalBeePatternTexture(patternID: String, device: MTLDevice) -> MTLTexture? {
        if let cached = beePatternMetalTextureCache[patternID] {
            return cached
        }

        let image: NSImage? = if Thread.isMainThread {
            MainActor.assumeIsolated {
                beePatternMaskRasterImage(patternID: patternID, size: 512)
            }
        } else {
            DispatchQueue.main.sync {
                MainActor.assumeIsolated {
                    beePatternMaskRasterImage(patternID: patternID, size: 512)
                }
            }
        }

        guard
            let image,
            let tiffData = image.tiffRepresentation,
            let bitmap = NSBitmapImageRep(data: tiffData),
            let cgImage = bitmap.cgImage
        else {
            return nil
        }

        do {
            let loader = MTKTextureLoader(device: device)
            let texture = try loader.newTexture(cgImage: cgImage, options: [
                MTKTextureLoader.Option.SRGB: false
            ])
            beePatternMetalTextureCache[patternID] = texture
            return texture
        } catch {
            nativeLog("kon Bee pattern texture niet laden voor \(patternID): \(error.localizedDescription)")
            return nil
        }
    }

    private func currentSnapshot() -> StageMetalPreviewSnapshot {
        if Thread.isMainThread {
            return MainActor.assumeIsolated { buildSnapshotOnMainActor() }
        }
        return DispatchQueue.main.sync {
            MainActor.assumeIsolated { buildSnapshotOnMainActor() }
        }
    }

    @MainActor
    private func buildSnapshotOnMainActor() -> StageMetalPreviewSnapshot {
        guard let model = model else {
            return StageMetalPreviewSnapshot(fixtures: [], beams: [], patternSprites: [])
        }

        let time = model.previewAnimationTime(for: Date())
        var fixtures: [StageMetalFixtureSnapshot] = []
        var beams: [StageMetalBeamSnapshot] = []
        var patternSprites: [StageMetalPatternSpriteSnapshot] = []

        for editor in model.slotEditors.sorted(by: { $0.id < $1.id }) {
            let world = model.worldPosition(for: editor.id)
            let preview = model.presentedSlotPreviews[editor.id]
            let stageMotion = model.presentedStageMotionStates[editor.id]
            let venueTargetPreview = model.venueTargetPreviewVisual(for: editor.id)
            let beamKind = stageBeamKindFor3D(editor)
            let wallWashEmitters = beamKind == .wallWash
                ? wallWashEmitterPreviews(editor: editor, model: model, preview: preview, animationTime: time)
                : []
            let isBeeEye = slotPreviewIsBeeEye(preview) || editor.fixtureID == "generic_smart_bee_eye_pattern_moving_head"
            let baseColor = fixtureSceneColor(preview)
            let spotColor = fixtureSceneSpotColor(preview)
            let fixturePosition = simdStageVector(for: world)

            fixtures.append(
                StageMetalFixtureSnapshot(
                    position: fixturePosition,
                    beamKind: beamKind,
                    isBeeEye: isBeeEye,
                    yawDegrees: Float(world.yawDegrees),
                    pitchDegrees: Float(world.pitchDegrees),
                    rollDegrees: Float(world.rollDegrees),
                    color: simdColor(baseColor, alpha: preview?.enabled == true ? 0.96 : 0.42),
                    wallWashEmitterColors: wallWashEmitters.map { $0.metalColor(alphaScale: 0.48 + Float($0.intensity) * 1.24) },
                    selected: model.selectedSlotID == editor.id || model.previewSelectionContains(editor.id)
                )
            )

            guard let preview, preview.enabled else { continue }

            let isMovingHead = beamKind == .movingHead
            let panRange = stageMotion?.panRange ?? (preview.panRange ?? (isMovingHead ? 540.0 : 180.0))
            let tiltRange = stageMotion?.tiltRange ?? (preview.tiltRange ?? (isMovingHead ? 180.0 : 90.0))

            let pose: StageBeamPose
            if let stageMotion, isMovingHead {
                pose = StageBeamPose(
                    panDegrees: stageMotion.currentPanDegrees,
                    tiltDegrees: stageMotion.currentTiltDegrees
                )
            } else {
                pose = StageBeamPose(
                    panDegrees: preview.logicalPanDegrees
                        ?? preview.panDegrees
                        ?? panDegrees(forDMX: preview.pan, range: panRange),
                    tiltDegrees: preview.logicalTiltDegrees
                        ?? preview.tiltDegrees
                        ?? tiltDegrees(forDMX: preview.tilt, range: tiltRange)
                )
            }

            let normalEndpoint = stageMotion?.worldDirection.map {
                worldEndpoint(from: world, direction: $0, distance: StageWorld.movingHeadBeamDistanceCm)
            } ?? beamWorldEndpoint(
                worldOrigin: world,
                mountYawDegrees: world.yawDegrees,
                mountPitchDegrees: world.pitchDegrees,
                pose: pose,
                panRange: panRange,
                tiltRange: tiltRange,
                beamKind: beamKind
            )
            let endpoint = interpolatedVenueTargetEndpoint(
                normalEndpoint,
                preview: stageMotion?.worldDirection == nil ? venueTargetPreview : nil
            )

            let start = simdStageVector(for: world)
            let end = simdStageVector(for: endpoint)
            let direction = simd_normalize(end - start)
            let basis = simdBeamBasis(for: direction)
            let beamLength = simd_length(end - start)
            let movingHeadFarRadius = coneFarRadius(length: beamLength, fullAngleDegrees: 40)
            let movingHeadNearRadius = max(0.012, movingHeadFarRadius * 0.06)
            let staticWashFarRadius = coneFarRadius(length: beamLength, fullAngleDegrees: 40)
            let staticWashNearRadius = max(0.016, staticWashFarRadius * 0.08)
            let washBrightness = Float(max(0.0, effectivePreviewBrightness(preview, at: time)))
            let spotBrightness = Float(max(0.0, effectiveSpotPreviewBrightness(preview, at: time)))
            let beeSpread = Float(slotPreviewBeeSpread(preview))
            let beeBackgroundLevel = Float(slotPreviewBeeBackgroundLevel(preview))
            let beeSoftness = Float(slotPreviewBeeSoftness(preview))
            let beeShapeTransition = Float(slotPreviewBeeShapeTransition(preview))
            let strobeBoost: Float = preview.strobeActive ? 0.12 : 0.0
            let patternID = slotPreviewResolvedPatternID(preview, at: time)
            let patternOpen = patternID == "open" || (preview.spotPatternOpen ?? false)
            let patternRotation = Float(slotPreviewResolvedPatternRotation(preview, at: time))

            switch beamKind {
            case .movingHead:
                if isBeeEye {
                    if washBrightness > 0.01 {
                        let washOuterAlpha = min(0.78, (0.10 + washBrightness * 0.28 + strobeBoost) * (0.38 + beeBackgroundLevel * 0.66))
                        let washInnerAlpha = min(0.68, (0.08 + washBrightness * 0.24) * (0.34 + beeBackgroundLevel * 0.54))
                        beams.append(
                            StageMetalBeamSnapshot(
                                start: start,
                                end: end,
                                color: simdColor(baseColor, alpha: washOuterAlpha),
                                nearSideRadius: movingHeadNearRadius * 1.18,
                                farSideRadius: movingHeadFarRadius * (0.96 + beeBackgroundLevel * 0.48 + beeSoftness * 0.12),
                                nearUpRadius: movingHeadNearRadius,
                                farUpRadius: movingHeadFarRadius * (0.82 + beeBackgroundLevel * 0.30),
                                expansionExponent: 1.0,
                                ribbonCount: 7,
                                segmentCount: 28,
                                profile: .oval,
                                allowFloorProjection: true
                            )
                        )
                        beams.append(
                            StageMetalBeamSnapshot(
                                start: start,
                                end: end,
                                color: simdColor(baseColor, alpha: washInnerAlpha),
                                nearSideRadius: movingHeadNearRadius * 0.92,
                                farSideRadius: movingHeadFarRadius * (0.72 + beeBackgroundLevel * 0.26),
                                nearUpRadius: movingHeadNearRadius * 0.82,
                                farUpRadius: movingHeadFarRadius * (0.62 + beeBackgroundLevel * 0.20),
                                expansionExponent: 1.0,
                                ribbonCount: 6,
                                segmentCount: 24,
                                profile: .round,
                                allowFloorProjection: true
                            )
                        )
                    }
                    if spotBrightness > 0.01 {
                        for offset in simdBeeEyeTripletOffsets(
                            side: basis.side,
                            up: basis.up,
                            spread: beeSpread,
                            rotationDegrees: patternRotation
                        ) {
                            let beeStart = start + offset * 0.46
                            let nominalBeeEnd = end + offset * (1.56 + beeSpread * 0.62)
                            let beeEnd = simdExtendedBeeSpotEnd(start: beeStart, end: nominalBeeEnd)
                            beams.append(
                                StageMetalBeamSnapshot(
                                    start: beeStart,
                                    end: beeEnd,
                                    color: simdColor(spotColor, alpha: min(0.92, 0.16 + spotBrightness * 0.52 + strobeBoost + beeShapeTransition * 0.10)),
                                    nearSideRadius: movingHeadNearRadius * 0.78,
                                    farSideRadius: movingHeadFarRadius * (0.72 + beeSpread * 0.18 + beeSoftness * 0.08),
                                    nearUpRadius: movingHeadNearRadius * 0.78,
                                    farUpRadius: movingHeadFarRadius * (0.68 + beeSpread * 0.14),
                                    expansionExponent: 1.0,
                                    ribbonCount: 6,
                                    segmentCount: 24,
                                    profile: .round,
                                    allowFloorProjection: patternOpen
                                )
                            )
                        }
                        if !patternOpen {
                            patternSprites.append(contentsOf: makeBeePatternGroupSpriteSnapshots(
                                start: start,
                                end: end,
                                color: simdColor(spotColor, alpha: min(1.0, 0.50 + spotBrightness * 0.28 + strobeBoost * 0.4 + beeShapeTransition * 0.18)),
                                patternID: patternID,
                                patternKind: beePatternShaderKind(for: patternID),
                                rotationDegrees: patternRotation,
                                sizeScale: 0.92 + beeSpread * 0.20,
                                spread: beeSpread
                            ))
                        }
                    }
                } else {
                    let brightness = max(washBrightness, spotBrightness)
                    if brightness > 0.01 {
                        let liveColor = spotBrightness > washBrightness * 1.05 ? spotColor : baseColor
                        beams.append(
                            StageMetalBeamSnapshot(
                                start: start,
                                end: end,
                                color: simdColor(liveColor, alpha: min(0.88, 0.18 + brightness * 0.58 + strobeBoost)),
                                nearSideRadius: movingHeadNearRadius,
                                farSideRadius: movingHeadFarRadius,
                                nearUpRadius: movingHeadNearRadius,
                                farUpRadius: movingHeadFarRadius,
                                expansionExponent: 1.0,
                                ribbonCount: 7,
                                segmentCount: 26,
                                profile: .round,
                                allowFloorProjection: true
                            )
                        )
                    }
                }
            case .wallWash:
                guard washBrightness > 0.01 else { continue }
                continue
            case .staticWash:
                guard washBrightness > 0.01 else { continue }
                beams.append(
                    StageMetalBeamSnapshot(
                        start: start,
                        end: end,
                        color: simdColor(baseColor, alpha: min(0.84, 0.20 + washBrightness * 0.54 + strobeBoost)),
                        nearSideRadius: staticWashNearRadius * 1.12,
                        farSideRadius: staticWashFarRadius * 1.18,
                        nearUpRadius: staticWashNearRadius,
                        farUpRadius: staticWashFarRadius,
                        expansionExponent: 1.0,
                        ribbonCount: 8,
                        segmentCount: 26,
                        profile: .oval,
                        allowFloorProjection: true
                    )
                )
            }
        }

        return StageMetalPreviewSnapshot(fixtures: fixtures, beams: beams, patternSprites: patternSprites)
    }

    private func appendStageEnvironment(to vertices: inout [StageMetalColorVertex]) {
        let rearHeight = Float(StageWorld.maxZ / 100.0 - 0.45)
        let stageFrontZ = Float(-StageWorld.maxY / 100.0)
        let minX = Float(StageWorld.minX / 100.0)
        let maxX = Float(StageWorld.maxX / 100.0)
        let minZ = Float(-StageWorld.maxY / 100.0)
        let maxZ = Float(0.0)

        appendLine(
            from: SIMD3<Float>(minX, rearHeight, 0.0),
            to: SIMD3<Float>(maxX, rearHeight, 0.0),
            color: SIMD4<Float>(0.72, 0.74, 0.78, 0.90),
            to: &vertices
        )
        appendLine(
            from: SIMD3<Float>(minX, 0.01, stageFrontZ),
            to: SIMD3<Float>(maxX, 0.01, stageFrontZ),
            color: SIMD4<Float>(0.10, 0.76, 0.90, 0.60),
            to: &vertices
        )
        appendLine(
            from: SIMD3<Float>(0.0, 0.01, 0.0),
            to: SIMD3<Float>(0.0, 0.01, stageFrontZ),
            color: SIMD4<Float>(0.82, 0.84, 0.88, 0.22),
            to: &vertices
        )

        for value in stride(from: StageWorld.minX, through: StageWorld.maxX, by: StageWorld.minorGridStepCm) {
            let x = Float(value / 100.0)
            let isMajor = abs(value.remainder(dividingBy: StageWorld.majorGridStepCm)) < 0.001
            appendLine(
                from: SIMD3<Float>(x, 0.002, maxZ),
                to: SIMD3<Float>(x, 0.002, minZ),
                color: SIMD4<Float>(0.42, 0.46, 0.54, value == 0 ? 0.28 : isMajor ? 0.17 : 0.07),
                to: &vertices
            )
        }

        for value in stride(from: StageWorld.minY, through: StageWorld.maxY, by: StageWorld.minorGridStepCm) {
            let z = Float(-value / 100.0)
            let isMajor = abs(value.remainder(dividingBy: StageWorld.majorGridStepCm)) < 0.001
            appendLine(
                from: SIMD3<Float>(minX, 0.002, z),
                to: SIMD3<Float>(maxX, 0.002, z),
                color: SIMD4<Float>(0.42, 0.46, 0.54, value == 0 ? 0.24 : isMajor ? 0.17 : 0.07),
                to: &vertices
            )
        }
    }

    private func appendFixtures(
        _ fixtures: [StageMetalFixtureSnapshot],
        to vertices: inout [StageMetalColorVertex],
        indices: inout [UInt32]
    ) {
        for fixture in fixtures {
            switch fixture.beamKind {
            case .movingHead:
                appendBox(
                    center: fixture.position + SIMD3<Float>(0, -0.02, 0),
                    size: SIMD3<Float>(0.26, 0.08, 0.18),
                    color: simdScaledColor(fixture.color, scale: 0.42),
                    to: &vertices,
                    indices: &indices
                )
                appendBox(
                    center: fixture.position + SIMD3<Float>(0, 0.11, 0),
                    size: fixture.isBeeEye ? SIMD3<Float>(0.22, 0.12, 0.18) : SIMD3<Float>(0.19, 0.11, 0.17),
                    color: simdScaledColor(fixture.color, scale: 0.52),
                    to: &vertices,
                    indices: &indices
                )
            case .wallWash:
                appendOrientedBox(
                    center: fixture.position,
                    size: SIMD3<Float>(0.90, 0.10, 0.11),
                    yawDegrees: fixture.yawDegrees,
                    pitchDegrees: fixture.pitchDegrees,
                    rollDegrees: fixture.rollDegrees,
                    color: SIMD4<Float>(0.05, 0.05, 0.06, 0.92),
                    to: &vertices,
                    indices: &indices
                )
                appendWallWashEmitters(
                    center: fixture.position,
                    yawDegrees: fixture.yawDegrees,
                    pitchDegrees: fixture.pitchDegrees,
                    rollDegrees: fixture.rollDegrees,
                    emitterColors: fixture.wallWashEmitterColors,
                    fallbackColor: simdScaledColor(fixture.color, scale: 0.92),
                    to: &vertices,
                    indices: &indices
                )
            case .staticWash:
                appendBox(
                    center: fixture.position,
                    size: SIMD3<Float>(0.20, 0.16, 0.20),
                    color: simdScaledColor(fixture.color, scale: 0.48),
                    to: &vertices,
                    indices: &indices
                )
            }

            if fixture.selected {
                if fixture.beamKind == .wallWash {
                    appendOrientedBox(
                        center: fixture.position + SIMD3<Float>(0, 0.02, 0),
                        size: SIMD3<Float>(1.02, 0.16, 0.20),
                        yawDegrees: fixture.yawDegrees,
                        pitchDegrees: fixture.pitchDegrees,
                        rollDegrees: fixture.rollDegrees,
                        color: SIMD4<Float>(0.18, 0.88, 1.0, 0.18),
                        to: &vertices,
                        indices: &indices
                    )
                } else {
                    appendBox(
                        center: fixture.position + SIMD3<Float>(0, 0.02, 0),
                        size: SIMD3<Float>(0.34, 0.24, 0.28),
                        color: SIMD4<Float>(0.18, 0.88, 1.0, 0.18),
                        to: &vertices,
                        indices: &indices
                    )
                }
            }
        }
    }

    private func appendBeams(
        _ beams: [StageMetalBeamSnapshot],
        cameraPosition: SIMD3<Float>,
        to vertices: inout [StageMetalBeamVertex],
        indices: inout [UInt32]
    ) {
        for beam in beams {
            let direction = simd_normalize(beam.end - beam.start)
            let basis = simdBeamBasis(for: direction)
            let diagonalAxis = simd_normalize(basis.side + basis.up * 0.72)
            switch beam.profile {
            case .round, .oval:
                appendBeamBillboard(
                    start: beam.start,
                    end: beam.end,
                    nearSideRadius: beam.nearSideRadius,
                    farSideRadius: beam.farSideRadius,
                    nearUpRadius: beam.nearUpRadius,
                    farUpRadius: beam.farUpRadius,
                    expansionExponent: beam.expansionExponent,
                    color: beam.color,
                    segmentCount: beam.segmentCount,
                    widthScale: 1.0,
                    mode: 0.0,
                    cameraPosition: cameraPosition,
                    to: &vertices,
                    indices: &indices
                )
                appendBeamSheet(
                    start: beam.start,
                    end: beam.end,
                    nearSideRadius: beam.nearSideRadius * 1.16,
                    farSideRadius: beam.farSideRadius * 1.48,
                    nearUpRadius: beam.nearUpRadius * 1.14,
                    farUpRadius: beam.farUpRadius * 1.42,
                    expansionExponent: beam.expansionExponent * 1.04,
                    color: SIMD4<Float>(beam.color.x, beam.color.y, beam.color.z, beam.color.w * 0.40),
                    segmentCount: max(16, beam.segmentCount - 2),
                    widthScale: 1.0,
                    mode: 0.25,
                    axis: basis.side,
                    to: &vertices,
                    indices: &indices
                )
                appendBeamSheet(
                    start: beam.start,
                    end: beam.end,
                    nearSideRadius: beam.nearSideRadius * 1.08,
                    farSideRadius: beam.farSideRadius * 1.24,
                    nearUpRadius: beam.nearUpRadius * 1.08,
                    farUpRadius: beam.farUpRadius * 1.22,
                    expansionExponent: beam.expansionExponent,
                    color: SIMD4<Float>(beam.color.x, beam.color.y, beam.color.z, beam.color.w * 0.28),
                    segmentCount: max(16, beam.segmentCount - 4),
                    widthScale: 1.0,
                    mode: 0.25,
                    axis: diagonalAxis,
                    to: &vertices,
                    indices: &indices
                )
                appendBeamRibbonSet(
                    start: beam.start,
                    end: beam.end,
                    nearSideRadius: beam.nearSideRadius * 0.84,
                    farSideRadius: beam.farSideRadius * 0.88,
                    nearUpRadius: beam.nearUpRadius * 0.84,
                    farUpRadius: beam.farUpRadius * 0.88,
                    expansionExponent: beam.expansionExponent,
                    color: SIMD4<Float>(beam.color.x, beam.color.y, beam.color.z, beam.color.w * 0.08),
                    ribbonCount: max(3, beam.ribbonCount / 2),
                    segmentCount: max(12, beam.segmentCount - 6),
                    widthScale: 0.72,
                    mode: 0.5,
                    profile: beam.profile,
                    to: &vertices,
                    indices: &indices
                )
            case .fan:
                appendBeamBillboard(
                    start: beam.start,
                    end: beam.end,
                    nearSideRadius: beam.nearSideRadius,
                    farSideRadius: beam.farSideRadius,
                    nearUpRadius: beam.nearUpRadius,
                    farUpRadius: beam.farUpRadius,
                    expansionExponent: beam.expansionExponent,
                    color: SIMD4<Float>(beam.color.x, beam.color.y, beam.color.z, beam.color.w * 0.74),
                    segmentCount: beam.segmentCount,
                    widthScale: 1.0,
                    mode: 0.0,
                    cameraPosition: cameraPosition,
                    to: &vertices,
                    indices: &indices
                )
                appendBeamSheet(
                    start: beam.start,
                    end: beam.end,
                    nearSideRadius: beam.nearSideRadius * 1.12,
                    farSideRadius: beam.farSideRadius * 1.36,
                    nearUpRadius: beam.nearUpRadius * 1.04,
                    farUpRadius: beam.farUpRadius * 1.18,
                    expansionExponent: beam.expansionExponent,
                    color: SIMD4<Float>(beam.color.x, beam.color.y, beam.color.z, beam.color.w * 0.34),
                    segmentCount: max(14, beam.segmentCount - 2),
                    widthScale: 1.0,
                    mode: 0.25,
                    axis: basis.side,
                    to: &vertices,
                    indices: &indices
                )
                appendBeamRibbonSet(
                    start: beam.start,
                    end: beam.end,
                    nearSideRadius: beam.nearSideRadius,
                    farSideRadius: beam.farSideRadius,
                    nearUpRadius: beam.nearUpRadius,
                    farUpRadius: beam.farUpRadius,
                    expansionExponent: beam.expansionExponent,
                    color: beam.color,
                    ribbonCount: beam.ribbonCount,
                    segmentCount: beam.segmentCount,
                    widthScale: 0.84,
                    mode: 0.5,
                    profile: beam.profile,
                    to: &vertices,
                    indices: &indices
                )
                appendBeamRibbonSet(
                    start: beam.start,
                    end: beam.end,
                    nearSideRadius: beam.nearSideRadius * 1.34,
                    farSideRadius: beam.farSideRadius * 1.42,
                    nearUpRadius: beam.nearUpRadius * 1.16,
                    farUpRadius: beam.farUpRadius * 1.22,
                    expansionExponent: beam.expansionExponent * 1.04,
                    color: SIMD4<Float>(beam.color.x, beam.color.y, beam.color.z, beam.color.w * 0.10),
                    ribbonCount: max(3, beam.ribbonCount - 1),
                    segmentCount: max(14, beam.segmentCount - 2),
                    widthScale: 0.96,
                    mode: 0.5,
                    profile: beam.profile,
                    to: &vertices,
                    indices: &indices
                )
            }

            if beam.allowFloorProjection {
                appendBeamFloorProjection(
                    beam,
                    to: &vertices,
                    indices: &indices
                )
            }
        }
    }

    private func makeBeePatternSpriteSnapshot(
        start: SIMD3<Float>,
        end: SIMD3<Float>,
        color: SIMD4<Float>,
        patternID: String,
        patternKind: Float,
        rotationDegrees: Float,
        sizeScale: Float = 1.0
    ) -> StageMetalPatternSpriteSnapshot? {
        let direction = simd_normalize(end - start)
        guard simd_length_squared(direction) > 0.0001 else { return nil }
        let basis = simdBeamBasis(for: direction)
        let beamLength = simd_length(end - start)
        let maxDistance = Float(StageWorld.beamMaxDistanceCm / 100.0)

        if direction.y < -0.02 {
            let distanceToFloor = start.y / max(0.0001, -direction.y)
            if distanceToFloor > 0, distanceToFloor <= min(maxDistance, beamLength + 0.6) {
                let hit = start + direction * distanceToFloor
                let minX = Float(StageWorld.minX / 100.0)
                let maxX = Float(StageWorld.maxX / 100.0)
                let minZ = Float(-StageWorld.maxY / 100.0)
                let maxZ = Float(-StageWorld.minY / 100.0)
                if hit.x >= minX - 0.4, hit.x <= maxX + 0.4, hit.z >= minZ - 0.4, hit.z <= maxZ + 0.4 {
                    var sideAxis = SIMD3<Float>(direction.z, 0, -direction.x)
                    if simd_length_squared(sideAxis) < 0.0001 {
                        sideAxis = basis.side
                    } else {
                        sideAxis = simd_normalize(sideAxis)
                    }
                    var forwardAxis = SIMD3<Float>(direction.x, 0, direction.z)
                    if simd_length_squared(forwardAxis) < 0.0001 {
                        forwardAxis = SIMD3<Float>(0, 0, -1)
                    } else {
                        forwardAxis = simd_normalize(forwardAxis)
                    }
                    return StageMetalPatternSpriteSnapshot(
                        center: SIMD3<Float>(hit.x, 0.014, hit.z) + forwardAxis * 0.03,
                        sideAxis: sideAxis,
                        upAxis: forwardAxis,
                        size: SIMD2<Float>(repeating: beePatternProjectedSize(distance: distanceToFloor) * max(0.72, sizeScale)),
                        color: color,
                        patternID: patternID,
                        patternKind: patternKind,
                        rotationDegrees: rotationDegrees
                        ,
                        cameraFacing: false
                    )
                }
            }
        }

        return nil
    }

    private func makeBeePatternGroupSpriteSnapshots(
        start: SIMD3<Float>,
        end: SIMD3<Float>,
        color: SIMD4<Float>,
        patternID: String,
        patternKind: Float,
        rotationDegrees: Float,
        sizeScale: Float = 1.0,
        spread: Float = 1.0
    ) -> [StageMetalPatternSpriteSnapshot] {
        let direction = simd_normalize(end - start)
        guard simd_length_squared(direction) > 0.0001 else { return [] }
        let basis = simdBeamBasis(for: direction)
        let beamLength = simd_length(end - start)
        let maxDistance = Float(StageWorld.beamMaxDistanceCm / 100.0)
        guard direction.y < -0.02 else { return [] }

        let distanceToFloor = start.y / max(0.0001, -direction.y)
        guard distanceToFloor > 0, distanceToFloor <= min(maxDistance, beamLength + 0.6) else { return [] }

        let hit = start + direction * distanceToFloor
        let minX = Float(StageWorld.minX / 100.0)
        let maxX = Float(StageWorld.maxX / 100.0)
        let minZ = Float(-StageWorld.maxY / 100.0)
        let maxZ = Float(-StageWorld.minY / 100.0)
        guard hit.x >= minX - 0.4, hit.x <= maxX + 0.4, hit.z >= minZ - 0.4, hit.z <= maxZ + 0.4 else { return [] }

        var sideAxis = SIMD3<Float>(direction.z, 0, -direction.x)
        if simd_length_squared(sideAxis) < 0.0001 {
            sideAxis = basis.side
        } else {
            sideAxis = simd_normalize(sideAxis)
        }

        var forwardAxis = SIMD3<Float>(direction.x, 0, direction.z)
        if simd_length_squared(forwardAxis) < 0.0001 {
            forwardAxis = SIMD3<Float>(0, 0, -1)
        } else {
            forwardAxis = simd_normalize(forwardAxis)
        }

        let groupCenter = SIMD3<Float>(hit.x, 0.014, hit.z) + forwardAxis * 0.03
        let glyphSize = beePatternProjectedSize(distance: distanceToFloor) * max(0.72, sizeScale)
        let spacingScale = glyphSize * 0.82 * max(0.78, min(1.40, spread))
        let radians = Float(Double(rotationDegrees) * .pi / 180.0)
        let cosine = Float(cos(Double(radians)))
        let sine = Float(sin(Double(radians)))
        let localOffsets: [SIMD2<Float>] = [
            SIMD2<Float>(0.0, -spacingScale * 0.70),
            SIMD2<Float>(-spacingScale * 0.68, spacingScale * 0.42),
            SIMD2<Float>(spacingScale * 0.68, spacingScale * 0.42),
        ]

        return localOffsets.map { offset in
            let rotated = SIMD2<Float>(
                offset.x * cosine - offset.y * sine,
                offset.x * sine + offset.y * cosine
            )
            return StageMetalPatternSpriteSnapshot(
                center: groupCenter + sideAxis * rotated.x + forwardAxis * rotated.y,
                sideAxis: sideAxis,
                upAxis: forwardAxis,
                size: SIMD2<Float>(repeating: glyphSize),
                color: color,
                patternID: patternID,
                patternKind: patternKind,
                rotationDegrees: rotationDegrees,
                cameraFacing: false
            )
        }
    }

    private func makePatternSpriteVertices(
        for sprite: StageMetalPatternSpriteSnapshot,
        cameraPosition: SIMD3<Float>,
        textureBlend: Float
    ) -> [StageMetalSpriteVertex] {
        let sideAxis: SIMD3<Float>
        let upAxis: SIMD3<Float>
        let normal: SIMD3<Float>

        if sprite.cameraFacing {
            let forward = simd_normalize(cameraPosition - sprite.center)
            let fallbackUp = abs(forward.y) > 0.92 ? SIMD3<Float>(1, 0, 0) : SIMD3<Float>(0, 1, 0)
            var side = simd_cross(fallbackUp, forward)
            if simd_length_squared(side) < 0.0001 {
                side = sprite.sideAxis
            }
            sideAxis = simd_normalize(side)
            upAxis = simd_normalize(simd_cross(forward, sideAxis))
            normal = forward
        } else {
            sideAxis = simd_normalize(sprite.sideAxis)
            upAxis = simd_normalize(sprite.upAxis)
            normal = simd_normalize(simd_cross(sideAxis, upAxis))
        }

        let rotationRadians = sprite.rotationDegrees * .pi / 180.0
        let rotatedSide = simdRotate(sideAxis, axis: normal, radians: rotationRadians)
        let rotatedUp = simdRotate(upAxis, axis: normal, radians: rotationRadians)
        let halfSide = simd_normalize(rotatedSide) * (sprite.size.x * 0.5)
        let halfUp = simd_normalize(rotatedUp) * (sprite.size.y * 0.5)

        let bottomLeft = sprite.center - halfSide - halfUp
        let bottomRight = sprite.center + halfSide - halfUp
        let topRight = sprite.center + halfSide + halfUp
        let topLeft = sprite.center - halfSide + halfUp

        return [
            StageMetalSpriteVertex(position: bottomLeft, uv: SIMD2<Float>(0, 1), color: sprite.color, patternKind: sprite.patternKind, textureBlend: textureBlend),
            StageMetalSpriteVertex(position: bottomRight, uv: SIMD2<Float>(1, 1), color: sprite.color, patternKind: sprite.patternKind, textureBlend: textureBlend),
            StageMetalSpriteVertex(position: topRight, uv: SIMD2<Float>(1, 0), color: sprite.color, patternKind: sprite.patternKind, textureBlend: textureBlend),
            StageMetalSpriteVertex(position: topLeft, uv: SIMD2<Float>(0, 0), color: sprite.color, patternKind: sprite.patternKind, textureBlend: textureBlend),
        ]
    }

    private func appendBeamBillboard(
        start: SIMD3<Float>,
        end: SIMD3<Float>,
        nearSideRadius: Float,
        farSideRadius: Float,
        nearUpRadius: Float,
        farUpRadius: Float,
        expansionExponent: Float,
        color: SIMD4<Float>,
        segmentCount: Int,
        widthScale: Float,
        mode: Float,
        cameraPosition: SIMD3<Float>,
        to vertices: inout [StageMetalBeamVertex],
        indices: inout [UInt32]
    ) {
        let direction = simd_normalize(end - start)
        guard simd_length_squared(direction) > 0.0001 else { return }
        let basis = simdBeamBasis(for: direction)
        let center = simd_mix(start, end, SIMD3<Float>(repeating: 0.5))
        let toCamera = simd_normalize(cameraPosition - center)
        var billboardAxis = simd_cross(direction, toCamera)
        if simd_length_squared(billboardAxis) < 0.0001 {
            billboardAxis = basis.side
        } else {
            billboardAxis = simd_normalize(billboardAxis)
        }
        appendBeamSheet(
            start: start,
            end: end,
            nearSideRadius: nearSideRadius,
            farSideRadius: farSideRadius,
            nearUpRadius: nearUpRadius,
            farUpRadius: farUpRadius,
            expansionExponent: expansionExponent,
            color: color,
            segmentCount: segmentCount,
            widthScale: widthScale,
            mode: mode,
            axis: billboardAxis,
            to: &vertices,
            indices: &indices
        )
    }

    private func appendBeamSheet(
        start: SIMD3<Float>,
        end: SIMD3<Float>,
        nearSideRadius: Float,
        farSideRadius: Float,
        nearUpRadius: Float,
        farUpRadius: Float,
        expansionExponent: Float,
        color: SIMD4<Float>,
        segmentCount: Int,
        widthScale: Float,
        mode: Float,
        axis: SIMD3<Float>,
        to vertices: inout [StageMetalBeamVertex],
        indices: inout [UInt32]
    ) {
        let direction = simd_normalize(end - start)
        guard simd_length_squared(direction) > 0.0001 else { return }
        let basis = simdBeamBasis(for: direction)
        let baseIndex = UInt32(vertices.count)
        let normalizedAxis = simd_length_squared(axis) > 0.0001 ? simd_normalize(axis) : basis.side

        for step in 0...segmentCount {
            let t = Float(step) / Float(segmentCount)
            let shapedT = pow(t, expansionExponent)
            let center = simd_mix(start, end, SIMD3<Float>(repeating: t))
            let radius = ellipseRadius(
                along: normalizedAxis,
                sideAxis: basis.side,
                upAxis: basis.up,
                sideRadius: nearSideRadius + (farSideRadius - nearSideRadius) * shapedT,
                upRadius: nearUpRadius + (farUpRadius - nearUpRadius) * shapedT
            ) * widthScale
            let offsetVector = normalizedAxis * radius

            vertices.append(
                StageMetalBeamVertex(
                    position: center - offsetVector,
                    color: color,
                    axial: t,
                    lateral: -1,
                    mode: mode
                )
            )
            vertices.append(
                StageMetalBeamVertex(
                    position: center + offsetVector,
                    color: color,
                    axial: t,
                    lateral: 1,
                    mode: mode
                )
            )
        }

        for step in 0..<segmentCount {
            let offset = UInt32(step * 2)
            indices.append(baseIndex + offset)
            indices.append(baseIndex + offset + 1)
            indices.append(baseIndex + offset + 2)
            indices.append(baseIndex + offset + 1)
            indices.append(baseIndex + offset + 3)
            indices.append(baseIndex + offset + 2)
        }
    }

    private func appendBeamFloorProjection(
        _ beam: StageMetalBeamSnapshot,
        to vertices: inout [StageMetalBeamVertex],
        indices: inout [UInt32]
    ) {
        let direction = simd_normalize(beam.end - beam.start)
        guard simd_length_squared(direction) > 0.0001 else { return }
        guard direction.y < -0.02 else { return }

        let distanceToFloor = beam.start.y / max(0.0001, -direction.y)
        let maxDistance = Float(StageWorld.beamMaxDistanceCm / 100.0)
        guard distanceToFloor > 0, distanceToFloor <= maxDistance else { return }

        let hit = beam.start + direction * distanceToFloor
        let minX = Float(StageWorld.minX / 100.0)
        let maxX = Float(StageWorld.maxX / 100.0)
        let minZ = Float(-StageWorld.maxY / 100.0)
        let maxZ = Float(-StageWorld.minY / 100.0)
        guard hit.x >= minX - 0.4, hit.x <= maxX + 0.4, hit.z >= minZ - 0.4, hit.z <= maxZ + 0.4 else { return }

        let beamLength = simd_length(beam.end - beam.start)
        let travelT = beamLength > 0.0001 ? (distanceToFloor / beamLength) : 1.0
        let shapedT = pow(max(0, travelT), beam.expansionExponent)
        let sideRadius = beam.nearSideRadius + (beam.farSideRadius - beam.nearSideRadius) * shapedT
        let upRadius = beam.nearUpRadius + (beam.farUpRadius - beam.nearUpRadius) * shapedT

        var sideAxis = SIMD3<Float>(direction.z, 0, -direction.x)
        if simd_length_squared(sideAxis) < 0.0001 {
            sideAxis = SIMD3<Float>(1, 0, 0)
        } else {
            sideAxis = simd_normalize(sideAxis)
        }

        var forwardAxis = SIMD3<Float>(direction.x, 0, direction.z)
        if simd_length_squared(forwardAxis) < 0.0001 {
            forwardAxis = SIMD3<Float>(0, 0, -1)
        } else {
            forwardAxis = simd_normalize(forwardAxis)
        }

        let forwardStretch = 1.0 / max(0.18, abs(direction.y))
        let footprintSideRadius = sideRadius * (beam.profile == .fan ? 1.22 : 1.08)
        let footprintForwardRadius = max(sideRadius, upRadius * forwardStretch) * (beam.profile == .fan ? 1.08 : 1.0)
        let center = SIMD3<Float>(hit.x, 0.008, hit.z)
        let footprintColor = SIMD4<Float>(beam.color.x, beam.color.y, beam.color.z, beam.color.w * 0.52)
        let baseIndex = UInt32(vertices.count)

        let corners: [(Float, Float)] = [
            (-1, -1),
            (1, -1),
            (1, 1),
            (-1, 1),
        ]

        for (lateral, axial) in corners {
            let position =
                center
                + sideAxis * (lateral * footprintSideRadius)
                + forwardAxis * (axial * footprintForwardRadius)
            vertices.append(
                StageMetalBeamVertex(
                    position: position,
                    color: footprintColor,
                    axial: axial,
                    lateral: lateral,
                    mode: 1
                )
            )
        }

        indices.append(contentsOf: [
            baseIndex + 0, baseIndex + 1, baseIndex + 2,
            baseIndex + 0, baseIndex + 2, baseIndex + 3,
        ])
    }

    private func appendBeamRibbonSet(
        start: SIMD3<Float>,
        end: SIMD3<Float>,
        nearSideRadius: Float,
        farSideRadius: Float,
        nearUpRadius: Float,
        farUpRadius: Float,
        expansionExponent: Float,
        color: SIMD4<Float>,
        ribbonCount: Int,
        segmentCount: Int,
        widthScale: Float,
        mode: Float,
        profile: StageMetalBeamProfile,
        to vertices: inout [StageMetalBeamVertex],
        indices: inout [UInt32]
    ) {
        let direction = simd_normalize(end - start)
        guard simd_length_squared(direction) > 0.0001 else { return }
        let basis = simdBeamBasis(for: direction)
        let planes = max(profile == .fan ? 3 : 4, ribbonCount)
        let fanArc: Float = profile == .fan ? (.pi * 0.72) : .pi

        for ribbon in 0..<planes {
            let normalizedRibbon = planes == 1 ? 0.5 : Float(ribbon) / Float(planes - 1)
            let angle = profile == .fan
                ? (normalizedRibbon - 0.5) * fanArc
                : Float(ribbon) * (fanArc / Float(planes))
            let baseIndex = UInt32(vertices.count)

            for step in 0...segmentCount {
                let t = Float(step) / Float(segmentCount)
                let center = simd_mix(start, end, SIMD3<Float>(repeating: t))
                let shapedT = pow(t, expansionExponent)
                let sideRadius = nearSideRadius + (farSideRadius - nearSideRadius) * shapedT
                let upRadius = nearUpRadius + (farUpRadius - nearUpRadius) * shapedT
                let offsetVector = (
                    basis.side * cos(angle) * sideRadius +
                    basis.up * sin(angle) * upRadius
                ) * widthScale
                vertices.append(
                    StageMetalBeamVertex(
                        position: center - offsetVector,
                        color: color,
                        axial: t,
                        lateral: -1,
                        mode: mode
                    )
                )
                vertices.append(
                    StageMetalBeamVertex(
                        position: center + offsetVector,
                        color: color,
                        axial: t,
                        lateral: 1,
                        mode: mode
                    )
                )
            }

            for step in 0..<segmentCount {
                let offset = UInt32(step * 2)
                indices.append(baseIndex + offset)
                indices.append(baseIndex + offset + 1)
                indices.append(baseIndex + offset + 2)
                indices.append(baseIndex + offset + 1)
                indices.append(baseIndex + offset + 3)
                indices.append(baseIndex + offset + 2)
            }
        }
    }

    private func appendLine(
        from start: SIMD3<Float>,
        to end: SIMD3<Float>,
        color: SIMD4<Float>,
        to vertices: inout [StageMetalColorVertex]
    ) {
        vertices.append(StageMetalColorVertex(position: start, color: color))
        vertices.append(StageMetalColorVertex(position: end, color: color))
    }

    private func appendOrientedBox(
        center: SIMD3<Float>,
        size: SIMD3<Float>,
        yawDegrees: Float,
        pitchDegrees: Float,
        rollDegrees: Float,
        color: SIMD4<Float>,
        to vertices: inout [StageMetalColorVertex],
        indices: inout [UInt32]
    ) {
        let half = size * 0.5
        let localPoints: [SIMD3<Float>] = [
            SIMD3<Float>(-half.x, -half.y, -half.z),
            SIMD3<Float>(half.x, -half.y, -half.z),
            SIMD3<Float>(half.x, half.y, -half.z),
            SIMD3<Float>(-half.x, half.y, -half.z),
            SIMD3<Float>(-half.x, -half.y, half.z),
            SIMD3<Float>(half.x, -half.y, half.z),
            SIMD3<Float>(half.x, half.y, half.z),
            SIMD3<Float>(-half.x, half.y, half.z),
        ]
        let rotatedPoints = localPoints.map {
            center + simdFixtureOrientedOffset(
                $0,
                yawDegrees: yawDegrees,
                pitchDegrees: pitchDegrees,
                rollDegrees: rollDegrees
            )
        }
        appendBoxVertices(rotatedPoints, color: color, to: &vertices, indices: &indices)
    }

    private func appendWallWashEmitters(
        center: SIMD3<Float>,
        yawDegrees: Float,
        pitchDegrees: Float,
        rollDegrees: Float,
        emitterColors: [SIMD4<Float>],
        fallbackColor: SIMD4<Float>,
        to vertices: inout [StageMetalColorVertex],
        indices: inout [UInt32]
    ) {
        for index in 0..<24 {
            let t = Float(index) / 23.0
            let localCenter = SIMD3<Float>(
                -0.41 + t * 0.82,
                0.0,
                -0.060
            )
            let rotatedCenter = center + simdFixtureOrientedOffset(
                localCenter,
                yawDegrees: yawDegrees,
                pitchDegrees: pitchDegrees,
                rollDegrees: rollDegrees
            )
            let emitterColor = emitterColors.indices.contains(index) ? emitterColors[index] : fallbackColor
            appendOrientedBox(
                center: rotatedCenter,
                size: SIMD3<Float>(0.022, 0.032, 0.012),
                yawDegrees: yawDegrees,
                pitchDegrees: pitchDegrees,
                rollDegrees: rollDegrees,
                color: emitterColor,
                to: &vertices,
                indices: &indices
            )
        }
    }

    private func appendBox(
        center: SIMD3<Float>,
        size: SIMD3<Float>,
        color: SIMD4<Float>,
        to vertices: inout [StageMetalColorVertex],
        indices: inout [UInt32]
    ) {
        let hx = size.x * 0.5
        let hy = size.y * 0.5
        let hz = size.z * 0.5
        let points: [SIMD3<Float>] = [
            center + SIMD3<Float>(-hx, -hy, -hz),
            center + SIMD3<Float>(hx, -hy, -hz),
            center + SIMD3<Float>(hx, hy, -hz),
            center + SIMD3<Float>(-hx, hy, -hz),
            center + SIMD3<Float>(-hx, -hy, hz),
            center + SIMD3<Float>(hx, -hy, hz),
            center + SIMD3<Float>(hx, hy, hz),
            center + SIMD3<Float>(-hx, hy, hz),
        ]
        appendBoxVertices(points, color: color, to: &vertices, indices: &indices)
    }

    private func appendBoxVertices(
        _ points: [SIMD3<Float>],
        color: SIMD4<Float>,
        to vertices: inout [StageMetalColorVertex],
        indices: inout [UInt32]
    ) {
        let baseIndex = UInt32(vertices.count)
        for point in points {
            vertices.append(StageMetalColorVertex(position: point, color: color))
        }
        indices.append(contentsOf: [
            baseIndex + 0, baseIndex + 1, baseIndex + 2, baseIndex + 0, baseIndex + 2, baseIndex + 3,
            baseIndex + 4, baseIndex + 6, baseIndex + 5, baseIndex + 4, baseIndex + 7, baseIndex + 6,
            baseIndex + 0, baseIndex + 4, baseIndex + 5, baseIndex + 0, baseIndex + 5, baseIndex + 1,
            baseIndex + 1, baseIndex + 5, baseIndex + 6, baseIndex + 1, baseIndex + 6, baseIndex + 2,
            baseIndex + 2, baseIndex + 6, baseIndex + 7, baseIndex + 2, baseIndex + 7, baseIndex + 3,
            baseIndex + 3, baseIndex + 7, baseIndex + 4, baseIndex + 3, baseIndex + 4, baseIndex + 0,
        ])
    }
}

private struct StageMetalPreviewRepresentable: NSViewRepresentable {
    @ObservedObject var model: AppModel
    let cameraPreset: Stage3DCameraPreset

    final class Coordinator {
        let renderer = StageMetalPreviewRenderer()
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeNSView(context: Context) -> StageMetalPreviewMTKView {
        let view = StageMetalPreviewMTKView(frame: .zero, device: MTLCreateSystemDefaultDevice())
        view.interactionRenderer = context.coordinator.renderer
        view.delegate = context.coordinator.renderer
        context.coordinator.renderer.attach(model: model, preset: cameraPreset)
        return view
    }

    func updateNSView(_ nsView: StageMetalPreviewMTKView, context: Context) {
        nsView.interactionRenderer = context.coordinator.renderer
        context.coordinator.renderer.attach(model: model, preset: cameraPreset)
        context.coordinator.renderer.setCameraPreset(cameraPreset)
    }
}

struct Stage3DPreviewView: View {
    @EnvironmentObject private var model: AppModel
    @State private var cameraPreset: Stage3DCameraPreset = .audience

    var body: some View {
        ZStack(alignment: .topLeading) {
            StageMetalPreviewRepresentable(
                model: model,
                cameraPreset: cameraPreset
            )

            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    ForEach(Stage3DCameraPreset.allCases) { preset in
                        Button {
                            cameraPreset = preset
                        } label: {
                            HStack(spacing: 6) {
                                Image(systemName: preset.iconName)
                                    .font(.system(size: 11, weight: .semibold))
                                Text(preset.title)
                                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                            }
                            .padding(.horizontal, 10)
                            .padding(.vertical, 7)
                            .background(cameraPreset == preset ? BeatBeamPalette.triggerActive.opacity(0.24) : Color.black.opacity(0.28))
                            .overlay(
                                RoundedRectangle(cornerRadius: 8, style: .continuous)
                                    .stroke(cameraPreset == preset ? BeatBeamPalette.triggerActive.opacity(0.80) : Color.white.opacity(0.10), lineWidth: 1)
                            )
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                        }
                        .buttonStyle(.plain)
                    }
                }

                Text("Drag = orbit  •  scroll/pinch = zoom  •  right-drag = pan")
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(Color.white.opacity(0.72))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                    .background(Color.black.opacity(0.26))
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .padding(10)
        }
    }
}

private extension Stage3DCameraPreset {
    var metalCameraPosition: SIMD3<Float> {
        SIMD3<Float>(Float(cameraPosition.x), Float(cameraPosition.y), Float(cameraPosition.z))
    }

    var metalTargetPosition: SIMD3<Float> {
        SIMD3<Float>(Float(targetPosition.x), Float(targetPosition.y), Float(targetPosition.z))
    }
}

private struct SimdBeamBasis {
    let side: SIMD3<Float>
    let up: SIMD3<Float>
}

private func simdStageVector(for world: SlotWorldPosition) -> SIMD3<Float> {
    SIMD3<Float>(
        Float(world.x / 100.0),
        Float(world.z / 100.0),
        Float(-world.y / 100.0)
    )
}

private func simdColor(_ color: NSColor, alpha: Float = 1.0) -> SIMD4<Float> {
    let resolved = color.usingColorSpace(.deviceRGB) ?? color
    return SIMD4<Float>(
        Float(resolved.redComponent),
        Float(resolved.greenComponent),
        Float(resolved.blueComponent),
        alpha
    )
}

private func simdScaledColor(_ color: SIMD4<Float>, scale: Float) -> SIMD4<Float> {
    SIMD4<Float>(color.x * scale, color.y * scale, color.z * scale, color.w)
}

private func coneFarRadius(length: Float, fullAngleDegrees: Float) -> Float {
    let halfAngleRadians = (fullAngleDegrees * .pi / 180) * 0.5
    return max(0.02, tan(halfAngleRadians) * max(0, length))
}

private func beePatternProjectedSize(distance: Float) -> Float {
    let projectedDiameter = coneFarRadius(length: distance, fullAngleDegrees: 40) * 2.0
    return min(1.75, max(0.22, projectedDiameter * 0.30))
}

private func simdRotate(_ vector: SIMD3<Float>, axis: SIMD3<Float>, radians: Float) -> SIMD3<Float> {
    let normalizedAxis = simd_normalize(axis)
    let cosine = cos(radians)
    let sine = sin(radians)
    return vector * cosine
        + simd_cross(normalizedAxis, vector) * sine
        + normalizedAxis * simd_dot(normalizedAxis, vector) * (1 - cosine)
}

private func simdFixtureOrientedOffset(
    _ vector: SIMD3<Float>,
    yawDegrees: Float,
    pitchDegrees: Float,
    rollDegrees: Float
) -> SIMD3<Float> {
    let yawRadians = -yawDegrees * .pi / 180.0
    let pitchRadians = pitchDegrees * .pi / 180.0
    let rollRadians = rollDegrees * .pi / 180.0
    var rotated = vector
    rotated = simdRotate(rotated, axis: SIMD3<Float>(0, 0, 1), radians: rollRadians)
    rotated = simdRotate(rotated, axis: SIMD3<Float>(1, 0, 0), radians: pitchRadians)
    rotated = simdRotate(rotated, axis: SIMD3<Float>(0, 1, 0), radians: yawRadians)
    return rotated
}

private func simdBeamBasis(for direction: SIMD3<Float>) -> SimdBeamBasis {
    let fallbackUp = abs(direction.y) > 0.92 ? SIMD3<Float>(1, 0, 0) : SIMD3<Float>(0, 1, 0)
    let side = simd_normalize(simd_cross(direction, fallbackUp))
    let up = simd_normalize(simd_cross(side, direction))
    return SimdBeamBasis(side: side, up: up)
}

private func ellipseRadius(
    along axis: SIMD3<Float>,
    sideAxis: SIMD3<Float>,
    upAxis: SIMD3<Float>,
    sideRadius: Float,
    upRadius: Float
) -> Float {
    let sideComponent = simd_dot(axis, sideAxis)
    let upComponent = simd_dot(axis, upAxis)
    let a = max(0.0001, sideRadius)
    let b = max(0.0001, upRadius)
    let denominator = (sideComponent * sideComponent) / (a * a) + (upComponent * upComponent) / (b * b)
    return denominator > 0.0001 ? 1.0 / sqrt(denominator) : max(a, b)
}

private func simdBeeEyeTripletOffsets(side: SIMD3<Float>, up: SIMD3<Float>, spread: Float = 1.0, rotationDegrees: Float = 0.0) -> [SIMD3<Float>] {
    let scaledSpread = max(0.78, min(1.40, spread))
    let radians = Float(Double(rotationDegrees) * .pi / 180.0)
    let cosine = Float(cos(Double(radians)))
    let sine = Float(sin(Double(radians)))
    let localOffsets: [SIMD2<Float>] = [
        SIMD2<Float>(0.0, 0.225 * scaledSpread),
        SIMD2<Float>(-0.225 * scaledSpread, -0.150 * scaledSpread),
        SIMD2<Float>(0.225 * scaledSpread, -0.150 * scaledSpread),
    ]

    return localOffsets.map { offset in
        let rotated = SIMD2<Float>(
            offset.x * cosine - offset.y * sine,
            offset.x * sine + offset.y * cosine
        )
        return side * rotated.x + up * rotated.y
    }
}

private func simdExtendedBeeSpotEnd(start: SIMD3<Float>, end: SIMD3<Float>) -> SIMD3<Float> {
    let direction = simd_normalize(end - start)
    guard simd_length_squared(direction) > 0.0001 else { return end }

    let maxDistance = Float(StageWorld.beamMaxDistanceCm / 100.0)
    let currentLength = simd_length(end - start)
    let preferredDistance = min(maxDistance, max(currentLength * 1.6, currentLength + 1.8))
    let extendedEnd = start + direction * preferredDistance

    if direction.y < -0.02 {
        let distanceToFloor = start.y / max(0.0001, -direction.y)
        if distanceToFloor > 0, distanceToFloor <= maxDistance {
            let hit = start + direction * distanceToFloor
            let minX = Float(StageWorld.minX / 100.0)
            let maxX = Float(StageWorld.maxX / 100.0)
            let minZ = Float(-StageWorld.maxY / 100.0)
            let maxZ = Float(-StageWorld.minY / 100.0)
            if hit.x >= minX - 0.4, hit.x <= maxX + 0.4, hit.z >= minZ - 0.4, hit.z <= maxZ + 0.4 {
                return hit
            }
        }
    }

    return extendedEnd
}

private func simdLookAtMatrix(eye: SIMD3<Float>, target: SIMD3<Float>, up: SIMD3<Float>) -> simd_float4x4 {
    let forward = simd_normalize(target - eye)
    let right = simd_normalize(simd_cross(forward, up))
    let upVector = simd_cross(right, forward)

    return simd_float4x4(
        SIMD4<Float>(right.x, upVector.x, -forward.x, 0),
        SIMD4<Float>(right.y, upVector.y, -forward.y, 0),
        SIMD4<Float>(right.z, upVector.z, -forward.z, 0),
        SIMD4<Float>(
            -simd_dot(right, eye),
            -simd_dot(upVector, eye),
            simd_dot(forward, eye),
            1
        )
    )
}

private func simdPerspectiveMatrix(fovYRadians: Float, aspect: Float, near: Float, far: Float) -> simd_float4x4 {
    let yScale = 1 / tan(fovYRadians * 0.5)
    let xScale = yScale / max(0.0001, aspect)
    let zRange = far - near
    let zScale = -(far + near) / zRange
    let wzScale = -(2 * far * near) / zRange

    return simd_float4x4(
        SIMD4<Float>(xScale, 0, 0, 0),
        SIMD4<Float>(0, yScale, 0, 0),
        SIMD4<Float>(0, 0, zScale, -1),
        SIMD4<Float>(0, 0, wzScale, 0)
    )
}

private func stageSceneVector(for world: SlotWorldPosition) -> SCNVector3 {
    SCNVector3(
        CGFloat(world.x / 100.0),
        CGFloat(world.z / 100.0),
        CGFloat(-world.y / 100.0)
    )
}

private func sceneVectorAdd(_ lhs: SCNVector3, _ rhs: SCNVector3) -> SCNVector3 {
    SCNVector3(lhs.x + rhs.x, lhs.y + rhs.y, lhs.z + rhs.z)
}

private func sceneVectorSubtract(_ lhs: SCNVector3, _ rhs: SCNVector3) -> SCNVector3 {
    SCNVector3(lhs.x - rhs.x, lhs.y - rhs.y, lhs.z - rhs.z)
}

private func sceneVectorScale(_ value: SCNVector3, _ factor: CGFloat) -> SCNVector3 {
    SCNVector3(value.x * factor, value.y * factor, value.z * factor)
}

private func sceneVectorLength(_ value: SCNVector3) -> CGFloat {
    sqrt(value.x * value.x + value.y * value.y + value.z * value.z)
}

private func sceneVectorNormalize(_ value: SCNVector3) -> SCNVector3 {
    let length = sceneVectorLength(value)
    guard length > 0.0001 else { return SCNVector3(0, 0, 0) }
    return sceneVectorScale(value, 1.0 / length)
}

private func sceneVectorCross(_ lhs: SCNVector3, _ rhs: SCNVector3) -> SCNVector3 {
    SCNVector3(
        lhs.y * rhs.z - lhs.z * rhs.y,
        lhs.z * rhs.x - lhs.x * rhs.z,
        lhs.x * rhs.y - lhs.y * rhs.x
    )
}

private func sceneVectorMidpoint(_ lhs: SCNVector3, _ rhs: SCNVector3) -> SCNVector3 {
    SCNVector3((lhs.x + rhs.x) * 0.5, (lhs.y + rhs.y) * 0.5, (lhs.z + rhs.z) * 0.5)
}

private func + (lhs: SCNVector3, rhs: SCNVector3) -> SCNVector3 {
    sceneVectorAdd(lhs, rhs)
}

private func * (lhs: SCNVector3, rhs: CGFloat) -> SCNVector3 {
    sceneVectorScale(lhs, rhs)
}

private func * (lhs: CGFloat, rhs: SCNVector3) -> SCNVector3 {
    sceneVectorScale(rhs, lhs)
}

private struct SceneBeamBasis {
    let side: SCNVector3
    let up: SCNVector3
}

private func beamBasis(for direction: SCNVector3) -> SceneBeamBasis {
    let fallbackUp = abs(direction.y) > 0.92 ? SCNVector3(1, 0, 0) : SCNVector3(0, 1, 0)
    let side = sceneVectorNormalize(sceneVectorCross(direction, fallbackUp))
    let up = sceneVectorNormalize(sceneVectorCross(side, direction))
    return SceneBeamBasis(side: side, up: up)
}

private func beeEyeTripletOffsets3D(side: SCNVector3, up: SCNVector3, spread: CGFloat = 1.0, rotationDegrees: Double = 0.0) -> [SCNVector3] {
    let scaledSpread = max(0.78, min(1.40, spread))
    let radians = CGFloat(rotationDegrees * .pi / 180.0)
    let cosine = cos(radians)
    let sine = sin(radians)
    let localOffsets: [CGPoint] = [
        CGPoint(x: 0.0, y: 0.225 * scaledSpread),
        CGPoint(x: -0.225 * scaledSpread, y: -0.150 * scaledSpread),
        CGPoint(x: 0.225 * scaledSpread, y: -0.150 * scaledSpread),
    ]

    return localOffsets.map { offset in
        let rotatedX = offset.x * cosine - offset.y * sine
        let rotatedY = offset.x * sine + offset.y * cosine
        return sceneVectorAdd(sceneVectorScale(side, rotatedX), sceneVectorScale(up, rotatedY))
    }
}

private func fixtureSceneColor(_ preview: SlotPreview?) -> NSColor {
    guard let preview, preview.enabled else {
        return NSColor(calibratedWhite: 0.58, alpha: 1.0)
    }
    let whiteBoost = Double(preview.white) / 255.0
    let scaledRed = min(1.0, Double(preview.red) / 255.0 + whiteBoost * 0.14)
    let scaledGreen = min(1.0, Double(preview.green) / 255.0 + whiteBoost * 0.14)
    let scaledBlue = min(1.0, Double(preview.blue) / 255.0 + whiteBoost * 0.14)
    let maxComponent = max(scaledRed, scaledGreen, scaledBlue, 0.001)
    let normalizedRed = min(1.0, scaledRed / maxComponent)
    let normalizedGreen = min(1.0, scaledGreen / maxComponent)
    let normalizedBlue = min(1.0, scaledBlue / maxComponent)
    return NSColor(
        calibratedRed: CGFloat(normalizedRed),
        green: CGFloat(normalizedGreen),
        blue: CGFloat(normalizedBlue),
        alpha: 1.0
    )
}

private func fixtureSceneSpotColor(_ preview: SlotPreview?) -> NSColor {
    guard
        let preview,
        preview.enabled,
        preview.spotRed != nil || preview.spotGreen != nil || preview.spotBlue != nil || preview.spotWhite != nil
    else {
        return fixtureSceneColor(preview)
    }
    let whiteBoost = Double(preview.spotWhite ?? 0) / 255.0
    let scaledRed = min(1.0, Double(preview.spotRed ?? 0) / 255.0 + whiteBoost * 0.14)
    let scaledGreen = min(1.0, Double(preview.spotGreen ?? 0) / 255.0 + whiteBoost * 0.14)
    let scaledBlue = min(1.0, Double(preview.spotBlue ?? 0) / 255.0 + whiteBoost * 0.14)
    let maxComponent = max(scaledRed, scaledGreen, scaledBlue, 0.001)
    return NSColor(
        calibratedRed: CGFloat(min(1.0, scaledRed / maxComponent)),
        green: CGFloat(min(1.0, scaledGreen / maxComponent)),
        blue: CGFloat(min(1.0, scaledBlue / maxComponent)),
        alpha: 1.0
    )
}

private func makeSceneSegmentNode(from start: SCNVector3, to end: SCNVector3, radius: CGFloat, color: NSColor, opacity: CGFloat) -> SCNNode {
    let dx = end.x - start.x
    let dy = end.y - start.y
    let dz = end.z - start.z
    let length = CGFloat(sqrt(dx * dx + dy * dy + dz * dz))
    guard length > 0.0001 else { return SCNNode() }

    let geometry = SCNCylinder(radius: radius, height: length)
    let material = SCNMaterial()
    material.diffuse.contents = color
    material.emission.contents = color
    material.emission.intensity = 0.48
    material.roughness.contents = 0.28
    material.metalness.contents = 0.02
    material.transparency = opacity
    geometry.radialSegmentCount = 10
    geometry.materials = [material]

    let node = SCNNode(geometry: geometry)
    node.position = SCNVector3(
        (start.x + end.x) * 0.5,
        (start.y + end.y) * 0.5,
        (start.z + end.z) * 0.5
    )
    node.look(at: end, up: SCNVector3(0, 1, 0), localFront: SCNVector3(0, 1, 0))
    return node
}

struct StagePreviewPanel<Content: View>: View {
    let title: String
    let subtitle: String
    let projection: StageProjection
    let viewportRenderKey: MetricStageMapViewportRenderKey
    var showsWorldBackdrop = true
    let content: Content

    init(title: String, subtitle: String, projection: StageProjection, viewportRenderKey: MetricStageMapViewportRenderKey, showsWorldBackdrop: Bool = true, @ViewBuilder content: () -> Content) {
        self.title = title
        self.subtitle = subtitle
        self.projection = projection
        self.viewportRenderKey = viewportRenderKey
        self.showsWorldBackdrop = showsWorldBackdrop
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 14, weight: .semibold))
                Text(subtitle)
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
            }

            content
                // The grid and every world-space projection now share this exact
                // padded canvas. Keeping the backdrop outside this frame was a
                // subtle second fit rectangle that made visual zoom ambiguous.
                .padding(16)
                .background {
                    if showsWorldBackdrop {
                        ProjectionPanelBackdrop(projection: projection, viewportRenderKey: viewportRenderKey)
                    }
                }
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(Color.white.opacity(0.08), lineWidth: 1)
            )
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

struct ProjectionPanelBackdrop: View {
    let projection: StageProjection
    let viewportRenderKey: MetricStageMapViewportRenderKey

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [
                                Color.white.opacity(0.05),
                                Color.white.opacity(0.025)
                            ],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )

                ProjectionWorldGrid(projection: projection)
                ProjectionReferenceLines(projection: projection)
                ProjectionAxisOverlay(projection: projection)
            }
        }
        .id(viewportRenderKey)
    }
}

struct ProjectionWorldGrid: View {
    let projection: StageProjection

    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .bottomTrailing) {
                gridPath(step: StageWorld.minorGridStepCm, size: geometry.size)
                    .stroke(Color.white.opacity(0.035), lineWidth: 0.7)
                gridPath(step: StageWorld.majorGridStepCm, size: geometry.size)
                    .stroke(Color.white.opacity(0.12), lineWidth: 1.1)
                Text("1 m grid · 0.25 m minor")
                    .font(.system(size: 8, weight: .semibold, design: .monospaced))
                    .foregroundStyle(Color.white.opacity(0.42))
                    .padding(7)
            }
        }
    }

    private func gridPath(step: Double, size: CGSize) -> Path {
        var path = Path()
        func add(_ start: SlotWorldPosition, _ end: SlotWorldPosition) {
            let a = worldProjectedAbsolutePoint(start, projection: projection, size: size)
            let b = worldProjectedAbsolutePoint(end, projection: projection, size: size)
            path.move(to: a)
            path.addLine(to: b)
        }
        switch projection {
        case .top:
            for x in stride(from: StageWorld.minX, through: StageWorld.maxX, by: step) {
                add(SlotWorldPosition(x: x, y: StageWorld.minY, z: 0), SlotWorldPosition(x: x, y: StageWorld.maxY, z: 0))
            }
            for y in stride(from: StageWorld.minY, through: StageWorld.maxY, by: step) {
                add(SlotWorldPosition(x: StageWorld.minX, y: y, z: 0), SlotWorldPosition(x: StageWorld.maxX, y: y, z: 0))
            }
        case .front, .back:
            for x in stride(from: StageWorld.minX, through: StageWorld.maxX, by: step) {
                add(SlotWorldPosition(x: x, y: 0, z: StageWorld.minZ), SlotWorldPosition(x: x, y: 0, z: StageWorld.maxZ))
            }
            for z in stride(from: StageWorld.minZ, through: StageWorld.maxZ, by: step) {
                add(SlotWorldPosition(x: StageWorld.minX, y: 0, z: z), SlotWorldPosition(x: StageWorld.maxX, y: 0, z: z))
            }
        case .side:
            for y in stride(from: StageWorld.minY, through: StageWorld.maxY, by: step) {
                add(SlotWorldPosition(x: 0, y: y, z: StageWorld.minZ), SlotWorldPosition(x: 0, y: y, z: StageWorld.maxZ))
            }
            for z in stride(from: StageWorld.minZ, through: StageWorld.maxZ, by: step) {
                add(SlotWorldPosition(x: 0, y: StageWorld.minY, z: z), SlotWorldPosition(x: 0, y: StageWorld.maxY, z: z))
            }
        }
        return path
    }
}

struct ProjectionAxisOverlay: View {
    @AppStorage(frontProjectionMirrorDefaultsKey) private var frontProjectionMirrored = false
    @AppStorage(topProjectionRotationDefaultsKey) private var topProjectionRotationQuarterTurns = 0
    let projection: StageProjection

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                axisLine(
                    from: CGPoint(x: 18, y: geometry.size.height - 18),
                    to: CGPoint(x: geometry.size.width - 18, y: geometry.size.height - 18)
                )

                axisLine(
                    from: CGPoint(x: 18, y: geometry.size.height - 18),
                    to: CGPoint(x: 18, y: 18)
                )

                HStack {
                    axisTag(horizontalAxisLeading)
                    Spacer()
                    axisTag(horizontalAxisTrailing)
                }
                .padding(.horizontal, 10)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
                .padding(.bottom, 4)

                VStack {
                    axisTag(verticalAxisTop)
                    Spacer()
                    axisTag(verticalAxisBottom)
                }
                .padding(.vertical, 10)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                .padding(.leading, 4)
            }
        }
    }

    private var horizontalAxisLeading: String {
        switch projection {
        case .top:
            switch normalizedQuarterTurns(topProjectionRotationQuarterTurns) {
            case 1:
                return "Front"
            case 2:
                return "X-"
            case 3:
                return "Back"
            default:
                return "X+"
            }
        case .front:
            return frontProjectionMirrored ? "X+" : "X-"
        case .back:
            return "X+"
        case .side:
            return "Y-"
        }
    }

    private var horizontalAxisTrailing: String {
        switch projection {
        case .top:
            switch normalizedQuarterTurns(topProjectionRotationQuarterTurns) {
            case 1:
                return "Back"
            case 2:
                return "X+"
            case 3:
                return "Front"
            default:
                return "X-"
            }
        case .front:
            return frontProjectionMirrored ? "X-" : "X+"
        case .back:
            return "X-"
        case .side:
            return "Y+"
        }
    }

    private var verticalAxisTop: String {
        switch projection {
        case .top:
            switch normalizedQuarterTurns(topProjectionRotationQuarterTurns) {
            case 1:
                return "X+"
            case 2:
                return "Front"
            case 3:
                return "X-"
            default:
                return "Back"
            }
        case .front, .back, .side:
            return "Z+"
        }
    }

    private var verticalAxisBottom: String {
        switch projection {
        case .top:
            switch normalizedQuarterTurns(topProjectionRotationQuarterTurns) {
            case 1:
                return "X-"
            case 2:
                return "Back"
            case 3:
                return "X+"
            default:
                return "Front"
            }
        case .front, .back, .side:
            return "Z0"
        }
    }

    private func axisTag(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 10, weight: .bold, design: .monospaced))
            .foregroundStyle(Color.white.opacity(0.72))
            .padding(.horizontal, 6)
            .padding(.vertical, 4)
            .background(Color.black.opacity(0.22))
            .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
    }

    private func axisLine(from: CGPoint, to: CGPoint) -> some View {
        Path { path in
            path.move(to: from)
            path.addLine(to: to)
        }
        .stroke(Color.white.opacity(0.12), lineWidth: 1.2)
    }
}

private func dmxPreviewColor(red: Int, green: Int, blue: Int, white: Int = 0) -> Color {
    let whiteBoost = Double(white) / 255.0
    let scaledRed = min(1.0, Double(red) / 255.0 + whiteBoost * 0.14)
    let scaledGreen = min(1.0, Double(green) / 255.0 + whiteBoost * 0.14)
    let scaledBlue = min(1.0, Double(blue) / 255.0 + whiteBoost * 0.14)
    let maxComponent = max(scaledRed, scaledGreen, scaledBlue, 0.001)
    let normalizedRed = min(1.0, scaledRed / maxComponent)
    let normalizedGreen = min(1.0, scaledGreen / maxComponent)
    let normalizedBlue = min(1.0, scaledBlue / maxComponent)
    return Color(red: normalizedRed, green: normalizedGreen, blue: normalizedBlue)
}

private func dmxPreviewNSColor(red: Int, green: Int, blue: Int, white: Int = 0) -> NSColor {
    let whiteBoost = CGFloat(white) / 255.0
    let scaledRed = min(1.0, CGFloat(red) / 255.0 + whiteBoost * 0.14)
    let scaledGreen = min(1.0, CGFloat(green) / 255.0 + whiteBoost * 0.14)
    let scaledBlue = min(1.0, CGFloat(blue) / 255.0 + whiteBoost * 0.14)
    let maxComponent = max(scaledRed, scaledGreen, scaledBlue, 0.001)
    let normalizedRed = min(1.0, scaledRed / maxComponent)
    let normalizedGreen = min(1.0, scaledGreen / maxComponent)
    let normalizedBlue = min(1.0, scaledBlue / maxComponent)
    return NSColor(
        calibratedRed: normalizedRed,
        green: normalizedGreen,
        blue: normalizedBlue,
        alpha: 1.0
    )
}

struct WallWashEmitterPreview {
    let red: Int
    let green: Int
    let blue: Int
    let white: Int
    let intensity: CGFloat

    var color: Color {
        dmxPreviewColor(red: red, green: green, blue: blue, white: white)
    }

    var nsColor: NSColor {
        dmxPreviewNSColor(red: red, green: green, blue: blue, white: white)
    }

    func metalColor(alphaScale: Float = 1.0) -> SIMD4<Float> {
        simdColor(nsColor, alpha: min(1.0, Float(intensity) * alphaScale))
    }
}

struct WallWashProjectionPoint<T> {
    let t: CGFloat
    let payload: T
}

private func wallWashFlashScale(preview: SlotPreview?, animationTime: TimeInterval) -> CGFloat {
    guard let preview, preview.strobeActive else { return 1.0 }
    return 0.08 + CGFloat(slotPreviewStrobeFactor(preview, at: animationTime)) * 0.92
}

@MainActor
private func wallWashEmitterPreviews(
    editor: SlotEditor,
    model: AppModel,
    preview: SlotPreview?,
    animationTime: TimeInterval
) -> [WallWashEmitterPreview] {
    guard let preview, preview.enabled else {
        return Array(
            repeating: WallWashEmitterPreview(red: 255, green: 255, blue: 255, white: 0, intensity: 0),
            count: 24
        )
    }

    let flashScale = wallWashFlashScale(preview: preview, animationTime: animationTime)
    let intensity = effectivePreviewBrightness(preview, at: animationTime)
    let fallback = Array(
        repeating: makeWallWashEmitterPreview(
            red: preview.resolvedRed ?? preview.red,
            green: preview.resolvedGreen ?? preview.green,
            blue: preview.resolvedBlue ?? preview.blue,
            white: preview.resolvedWhite ?? preview.white,
            intensity: intensity,
            flashScale: flashScale
        ),
        count: 24
    )

    guard let range = model.dmxSlotRanges[editor.id] else {
        return fallback
    }

    let channelValues = (range.address...range.lastChannel).map { model.dmxValues[$0] ?? 0 }
    let mode = editor.mode.lowercased()

    switch mode {
    case "p001":
        return wallWashZoneEmitterPreviews(channelValues: channelValues, zoneCount: 8, totalEmitters: 24, intensity: intensity, flashScale: flashScale)
    case "l001":
        return wallWashZoneEmitterPreviews(channelValues: channelValues, zoneCount: 4, totalEmitters: 24, intensity: intensity, flashScale: flashScale)
    case "e001":
        return wallWashZoneEmitterPreviews(channelValues: channelValues, zoneCount: 2, totalEmitters: 24, intensity: intensity, flashScale: flashScale)
    case "c001":
        guard channelValues.count >= 3 else { return fallback }
        return Array(
            repeating: makeWallWashEmitterPreview(
                red: channelValues[0],
                green: channelValues[1],
                blue: channelValues[2],
                intensity: intensity,
                flashScale: flashScale
            ),
            count: 24
        )
    case "d001", "h001":
        guard channelValues.count >= 4 else { return fallback }
        return Array(
            repeating: makeWallWashEmitterPreview(
                red: channelValues[1],
                green: channelValues[2],
                blue: channelValues[3],
                intensity: intensity,
                flashScale: flashScale
            ),
            count: 24
        )
    default:
        return fallback
    }
}

private func wallWashZoneEmitterPreviews(
    channelValues: [Int],
    zoneCount: Int,
    totalEmitters: Int,
    intensity: CGFloat,
    flashScale: CGFloat
) -> [WallWashEmitterPreview] {
    guard zoneCount > 0, totalEmitters > 0 else { return [] }
    let emittersPerZone = max(1, totalEmitters / zoneCount)
    var emitters: [WallWashEmitterPreview] = []
    emitters.reserveCapacity(totalEmitters)

    for zoneIndex in 0..<zoneCount {
        let offset = zoneIndex * 3
        guard channelValues.count >= offset + 3 else { break }
        let emitter = makeWallWashEmitterPreview(
            red: channelValues[offset],
            green: channelValues[offset + 1],
            blue: channelValues[offset + 2],
            intensity: intensity,
            flashScale: flashScale
        )
        for _ in 0..<emittersPerZone {
            emitters.append(emitter)
        }
    }

    while emitters.count < totalEmitters {
        emitters.append(emitters.last ?? WallWashEmitterPreview(red: 255, green: 255, blue: 255, white: 0, intensity: 0))
    }
    if emitters.count > totalEmitters {
        emitters.removeLast(emitters.count - totalEmitters)
    }
    return emitters
}

private func makeWallWashEmitterPreview(red: Int, green: Int, blue: Int, white: Int = 0, intensity: CGFloat, flashScale: CGFloat) -> WallWashEmitterPreview {
    return WallWashEmitterPreview(
        red: red,
        green: green,
        blue: blue,
        white: white,
        intensity: max(0, min(1, intensity * flashScale))
    )
}

private func wallWashProjectionPoints(
    from emitters: [WallWashEmitterPreview],
    count: Int
) -> [WallWashProjectionPoint<WallWashEmitterPreview>] {
    guard !emitters.isEmpty, count > 0 else { return [] }
    let groupCount = min(count, emitters.count)
    return (0..<groupCount).map { index in
        let start = (index * emitters.count) / groupCount
        let end = max(start + 1, ((index + 1) * emitters.count) / groupCount)
        let bucket = Array(emitters[start..<min(end, emitters.count)])
        let weightedIntensity = max(0.001, bucket.reduce(CGFloat.zero) { $0 + $1.intensity })
        let averaged = WallWashEmitterPreview(
            red: Int((bucket.reduce(CGFloat.zero) { $0 + CGFloat($1.red) * $1.intensity } / weightedIntensity).rounded()),
            green: Int((bucket.reduce(CGFloat.zero) { $0 + CGFloat($1.green) * $1.intensity } / weightedIntensity).rounded()),
            blue: Int((bucket.reduce(CGFloat.zero) { $0 + CGFloat($1.blue) * $1.intensity } / weightedIntensity).rounded()),
            white: Int((bucket.reduce(CGFloat.zero) { $0 + CGFloat($1.white) * $1.intensity } / weightedIntensity).rounded()),
            intensity: bucket.map(\.intensity).max() ?? 0
        )
        return WallWashProjectionPoint(
            t: groupCount == 1 ? 0.5 : CGFloat(index) / CGFloat(groupCount - 1),
            payload: averaged
        )
    }
}

private let beeEyeIndexedSpotColors: [Color] = [
    dmxPreviewColor(red: 255, green: 255, blue: 255, white: 255),
    dmxPreviewColor(red: 255, green: 0, blue: 0, white: 0),
    dmxPreviewColor(red: 0, green: 255, blue: 0, white: 0),
    dmxPreviewColor(red: 0, green: 0, blue: 255, white: 0),
    dmxPreviewColor(red: 255, green: 255, blue: 0, white: 0),
    dmxPreviewColor(red: 0, green: 255, blue: 255, white: 0),
    dmxPreviewColor(red: 255, green: 128, blue: 0, white: 0),
    dmxPreviewColor(red: 180, green: 0, blue: 255, white: 0),
]

private let beeEyePatternOrder = [
    "open",
    "spoke_star",
    "flower",
    "swirl",
    "dot_star",
    "dot_cluster",
    "triskelion",
    "pinwheel_flower",
]

private func steppedWheelIndex(base: Int, count: Int, rate: Double, time: TimeInterval) -> Int {
    guard count > 0 else { return 0 }
    guard rate > 0 else { return ((base % count) + count) % count }
    let advanced = base + Int(floor(time * rate))
    return ((advanced % count) + count) % count
}

private func beeEyeSpotColor(for index: Int) -> Color {
    guard !beeEyeIndexedSpotColors.isEmpty else { return Color.white }
    let safeIndex = ((index % beeEyeIndexedSpotColors.count) + beeEyeIndexedSpotColors.count) % beeEyeIndexedSpotColors.count
    return beeEyeIndexedSpotColors[safeIndex]
}

private func beeEyePatternID(for index: Int) -> String {
    guard !beeEyePatternOrder.isEmpty else { return "open" }
    let safeIndex = ((index % beeEyePatternOrder.count) + beeEyePatternOrder.count) % beeEyePatternOrder.count
    return beeEyePatternOrder[safeIndex]
}

private func beePatternShaderKind(for patternID: String) -> Float {
    switch patternID {
    case "spoke_star":
        return 1
    case "flower":
        return 2
    case "swirl":
        return 3
    case "dot_star":
        return 4
    case "dot_cluster":
        return 5
    case "triskelion":
        return 6
    case "pinwheel_flower":
        return 7
    default:
        return 0
    }
}

private enum BeeEffectMode: String {
    case wash
    case beam
    case fx
}

private func slotPreviewResolvedBeeEffectMode(_ preview: SlotPreview?) -> BeeEffectMode {
    if let raw = preview?.beeEffectMode?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(),
       let mode = BeeEffectMode(rawValue: raw) {
        return mode
    }

    let washBrightness = slotBrightnessFraction(preview)
    let spotBrightness = slotPreviewSpotBrightnessFraction(preview)
    let patternOpen = preview?.spotPatternOpen ?? true

    if !patternOpen {
        return .fx
    }
    if spotBrightness > washBrightness * 1.12 {
        return .beam
    }
    return .wash
}

private func slotPreviewBeeSpread(_ preview: SlotPreview?) -> CGFloat {
    if let explicit = preview?.beeSpread {
        return min(max(CGFloat(explicit), 0.82), 1.40)
    }
    switch slotPreviewResolvedBeeEffectMode(preview) {
    case .wash:
        return 0.92
    case .beam:
        return 1.00
    case .fx:
        return 1.18
    }
}

private func slotPreviewBeeBackgroundLevel(_ preview: SlotPreview?) -> CGFloat {
    if let explicit = preview?.beeBackgroundLevel {
        return min(max(CGFloat(explicit), 0.0), 1.0)
    }
    switch slotPreviewResolvedBeeEffectMode(preview) {
    case .wash:
        return 0.86
    case .beam:
        return 0.40
    case .fx:
        return 0.62
    }
}

private func slotPreviewBeeSoftness(_ preview: SlotPreview?) -> CGFloat {
    if let explicit = preview?.beeSoftness {
        return min(max(CGFloat(explicit), 0.0), 1.0)
    }
    switch slotPreviewResolvedBeeEffectMode(preview) {
    case .wash:
        return 0.76
    case .beam:
        return 0.28
    case .fx:
        return 0.54
    }
}

private func slotPreviewBeeShapeTransition(_ preview: SlotPreview?) -> CGFloat {
    if let explicit = preview?.beeShapeTransition {
        return min(max(CGFloat(explicit), 0.0), 1.0)
    }
    switch slotPreviewResolvedBeeEffectMode(preview) {
    case .wash:
        return 0.22
    case .beam:
        return 0.16
    case .fx:
        return 0.44
    }
}

private func slotPreviewIsBeeEye(_ preview: SlotPreview?) -> Bool {
    preview?.fixtureKind == "bee_eye_pattern"
}

private func slotPreviewResolvedSpotColor(_ preview: SlotPreview, at time: TimeInterval) -> Color {
    if slotPreviewIsBeeEye(preview), preview.spotColorCycle == true {
        let count = max(beeEyeIndexedSpotColors.count, preview.spotColorCount ?? 0)
        let index = steppedWheelIndex(
            base: preview.spotColorIndex ?? 0,
            count: count,
            rate: preview.spotColorCycleRate ?? 0,
            time: time
        )
        return beeEyeSpotColor(for: index)
    }
    return slotPreviewSpotBaseColor(preview)
}

private func slotPreviewResolvedPatternID(_ preview: SlotPreview, at time: TimeInterval) -> String {
    if slotPreviewIsBeeEye(preview), preview.spotPatternCycle == true {
        let count = max(beeEyePatternOrder.count, preview.spotPatternCount ?? 0)
        let index = steppedWheelIndex(
            base: preview.spotPatternIndex ?? 0,
            count: count,
            rate: preview.spotPatternCycleRate ?? 0,
            time: time
        )
        return beeEyePatternID(for: index)
    }
    let raw = (preview.spotPatternId ?? "open").trimmingCharacters(in: .whitespacesAndNewlines)
    return raw.isEmpty ? "open" : raw
}

private func slotPreviewResolvedPatternRotation(_ preview: SlotPreview, at time: TimeInterval) -> Double {
    (preview.spotPatternRotationDegrees ?? 0) + (preview.spotPatternSpinDps ?? 0) * time
}

private func slotPreviewBaseColor(_ preview: SlotPreview) -> Color {
    dmxPreviewColor(
        red: preview.resolvedRed ?? preview.red,
        green: preview.resolvedGreen ?? preview.green,
        blue: preview.resolvedBlue ?? preview.blue,
        white: preview.resolvedWhite ?? preview.white
    )
}

private func slotPreviewSpotBaseColor(_ preview: SlotPreview) -> Color {
    dmxPreviewColor(
        red: preview.spotRed ?? preview.red,
        green: preview.spotGreen ?? preview.green,
        blue: preview.spotBlue ?? preview.blue,
        white: preview.spotWhite ?? preview.white
    )
}

private func slotPreviewSpotBrightnessFraction(_ preview: SlotPreview?) -> CGFloat {
    guard let preview else { return 0 }
    return max(0, min(1, CGFloat(preview.spotBrightness ?? 0) / 255.0))
}

private func slotPreviewBeamColor(_ preview: SlotPreview) -> Color {
    if (preview.spotBrightness ?? 0) > 10 {
        return slotPreviewResolvedSpotColor(preview, at: 0)
    }
    return slotPreviewBaseColor(preview)
}

private func slotPreviewColor(_ preview: SlotPreview) -> Color {
    slotPreviewBaseColor(preview).opacity(slotBrightnessFraction(preview))
}

private func slotBrightnessFraction(_ preview: SlotPreview?) -> CGFloat {
    guard let preview else { return 0 }
    if let effective = preview.effectiveIntensity {
        return max(0, min(1, CGFloat(effective)))
    }
    return max(0, min(1, CGFloat(preview.brightness) / 255.0))
}

private func slotPreviewStrobeRate(_ preview: SlotPreview?) -> Double {
    guard let preview, preview.enabled, preview.strobeActive, preview.strobe > 0 else { return 0 }
    let normalized = min(1.0, max(0.0, Double(preview.strobe) / 255.0))
    return 2.0 + normalized * 10.0
}

private func slotPreviewStrobeFactor(_ preview: SlotPreview?, at time: TimeInterval) -> Double {
    guard let preview, preview.enabled, preview.strobeActive, preview.strobe > 0 else { return 0 }
    if preview.strobeExternal {
        return 1.0
    }
    let rate = slotPreviewStrobeRate(preview)
    guard rate > 0 else { return 0 }
    let normalized = min(1.0, max(0.0, Double(preview.strobe) / 255.0))
    let dutyCycle = max(0.10, 0.34 - normalized * 0.14)
    let phase = (time * rate).truncatingRemainder(dividingBy: 1.0)
    return phase < dutyCycle ? 1.0 : 0.0
}

private func effectivePreviewBrightness(_ preview: SlotPreview?, at time: TimeInterval) -> CGFloat {
    let base = slotBrightnessFraction(preview)
    guard let preview, preview.enabled, preview.strobeActive, preview.strobe > 0 else {
        return base
    }
    if preview.strobeExternal {
        return base
    }
    let gated = CGFloat(slotPreviewStrobeFactor(preview, at: time))
    return base * gated
}

private func effectiveSpotPreviewBrightness(_ preview: SlotPreview?, at time: TimeInterval) -> CGFloat {
    let base = slotBrightnessFraction(preview)
    guard let preview, preview.enabled, preview.strobeActive, preview.strobe > 0 else {
        return base
    }
    if preview.strobeExternal {
        return base
    }
    let gated = CGFloat(slotPreviewStrobeFactor(preview, at: time))
    return base * gated
}

struct UniverseChannelValue: Identifiable {
    let channel: Int
    let value: Int

    var id: Int { channel }
}

struct UniverseFixtureGroup: Identifiable {
    let slotID: String
    let range: SlotRange
    let preview: SlotPreview?
    let channels: [UniverseChannelValue]

    var id: String { slotID }
    var footprint: Int { max(1, range.lastChannel - range.address + 1) }
    var headerText: String { "\(range.label) • \(range.fixtureLabel)" }
    var rangeText: String { "DMX \(range.address)-\(range.lastChannel) • \(range.mode)" }
}

private func monitorGroupColor(_ group: UniverseFixtureGroup) -> Color {
    guard let preview = group.preview, preview.enabled else {
        return BeatBeamPalette.triggerActive.opacity(0.78)
    }
    return slotPreviewBaseColor(preview)
}

private func scalarNormalized(_ value: Double, lower: Double, upper: Double) -> CGFloat {
    guard upper > lower else { return 0.5 }
    return CGFloat(Swift.min(Swift.max((value - lower) / (upper - lower), 0.0), 1.0))
}

private func scalarProjected(_ value: Double, lower: Double, upper: Double) -> CGFloat {
    guard upper > lower else { return 0.5 }
    return CGFloat((value - lower) / (upper - lower))
}

struct ProjectionReferenceLines: View {
    let projection: StageProjection

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                switch projection {
                case .top:
                    worldLine(SlotWorldPosition(x: 0, y: StageWorld.minY, z: 0), SlotWorldPosition(x: 0, y: StageWorld.maxY, z: 0), size: geometry.size)
                    worldLine(SlotWorldPosition(x: StageWorld.minX, y: 0, z: 0), SlotWorldPosition(x: StageWorld.maxX, y: 0, z: 0), size: geometry.size)
                case .front, .back:
                    worldLine(SlotWorldPosition(x: 0, y: 0, z: StageWorld.minZ), SlotWorldPosition(x: 0, y: 0, z: StageWorld.maxZ), size: geometry.size)
                    worldLine(SlotWorldPosition(x: StageWorld.minX, y: 0, z: 0), SlotWorldPosition(x: StageWorld.maxX, y: 0, z: 0), size: geometry.size)
                case .side:
                    worldLine(SlotWorldPosition(x: 0, y: StageWorld.minY, z: 0), SlotWorldPosition(x: 0, y: StageWorld.maxY, z: 0), size: geometry.size)
                    worldLine(SlotWorldPosition(x: 0, y: 0, z: StageWorld.minZ), SlotWorldPosition(x: 0, y: 0, z: StageWorld.maxZ), size: geometry.size)
                }
            }
        }
    }

    private func worldLine(_ start: SlotWorldPosition, _ end: SlotWorldPosition, size: CGSize) -> some View {
        referenceLine(
            from: worldProjectedAbsolutePoint(start, projection: projection, size: size),
            to: worldProjectedAbsolutePoint(end, projection: projection, size: size)
        )
    }

    private func referenceLine(from: CGPoint, to: CGPoint) -> some View {
        Path { path in
            path.move(to: from)
            path.addLine(to: to)
        }
        .stroke(
            Color.white.opacity(0.20),
            style: StrokeStyle(lineWidth: 1.5, dash: [6, 4])
        )
    }
}

private func worldProjectedPoint(_ world: SlotWorldPosition, projection: StageProjection) -> CGPoint {
    let frontMirrored = UserDefaults.standard.bool(forKey: frontProjectionMirrorDefaultsKey)
    let topRotation = UserDefaults.standard.integer(forKey: topProjectionRotationDefaultsKey)
    return metricWorldProjectedPoint(world, projection: projection, frontMirrored: frontMirrored, topQuarterTurns: topRotation)
}

private func worldProjectedBeamPoint(_ world: SlotWorldPosition, projection: StageProjection) -> CGPoint {
    worldProjectedPoint(world, projection: projection)
}

private func worldProjectedAbsolutePoint(_ world: SlotWorldPosition, projection: StageProjection, size: CGSize) -> CGPoint {
    let normalized = worldProjectedPoint(world, projection: projection)
    return CGPoint(x: size.width * normalized.x, y: size.height * normalized.y)
}

private func worldProjectedAbsoluteBeamPoint(_ world: SlotWorldPosition, projection: StageProjection, size: CGSize) -> CGPoint {
    let normalized = worldProjectedBeamPoint(world, projection: projection)
    return CGPoint(x: size.width * normalized.x, y: size.height * normalized.y)
}

private func worldOrientationEndpoint(_ worldOrigin: SlotWorldPosition, distance: Double) -> SlotWorldPosition {
    let yawRadians = worldOrigin.yawDegrees * .pi / 180.0
    return SlotWorldPosition(
        x: worldOrigin.x + sin(yawRadians) * distance,
        y: worldOrigin.y + cos(yawRadians) * distance,
        z: worldOrigin.z,
        yawDegrees: worldOrigin.yawDegrees,
        pitchDegrees: worldOrigin.pitchDegrees,
        rollDegrees: worldOrigin.rollDegrees
    )
}

private struct FixtureVenueBasis {
    let forward: VenueVectorState
    let up: VenueVectorState
    let right: VenueVectorState
}

private func venueVectorTuple(_ vector: VenueVectorState) -> (x: Double, y: Double, z: Double) {
    (vector.x, vector.y, vector.z)
}

private func venueVectorLength(_ vector: (x: Double, y: Double, z: Double)) -> Double {
    sqrt(vector.x * vector.x + vector.y * vector.y + vector.z * vector.z)
}

private func venueVectorNormalized(_ vector: (x: Double, y: Double, z: Double)) -> (x: Double, y: Double, z: Double) {
    let length = max(0.0000001, venueVectorLength(vector))
    return (vector.x / length, vector.y / length, vector.z / length)
}

private func venueVectorDot(
    _ left: (x: Double, y: Double, z: Double),
    _ right: (x: Double, y: Double, z: Double)
) -> Double {
    left.x * right.x + left.y * right.y + left.z * right.z
}

private func venueVectorCross(
    _ left: (x: Double, y: Double, z: Double),
    _ right: (x: Double, y: Double, z: Double)
) -> (x: Double, y: Double, z: Double) {
    (
        left.y * right.z - left.z * right.y,
        left.z * right.x - left.x * right.z,
        left.x * right.y - left.y * right.x
    )
}

private func venueVectorRotated(
    _ vector: (x: Double, y: Double, z: Double),
    around rawAxis: (x: Double, y: Double, z: Double),
    radians: Double
) -> (x: Double, y: Double, z: Double) {
    let axis = venueVectorNormalized(rawAxis)
    let cosine = cos(radians)
    let sine = sin(radians)
    let cross = venueVectorCross(axis, vector)
    let dot = venueVectorDot(axis, vector)
    return (
        vector.x * cosine + cross.x * sine + axis.x * dot * (1 - cosine),
        vector.y * cosine + cross.y * sine + axis.y * dot * (1 - cosine),
        vector.z * cosine + cross.z * sine + axis.z * dot * (1 - cosine)
    )
}

/// Build the same right-handed fixture frame sent to the backend.  Local
/// Forward starts toward Audience (+Y), local Up at physical +Z and Right is
/// always derived as Forward × Up.
private func venueOrientationBasis(for world: SlotWorldPosition) -> FixtureVenueBasis {
    var forward = (x: 0.0, y: 1.0, z: 0.0)
    var up = (x: 0.0, y: 0.0, z: 1.0)
    up = venueVectorRotated(up, around: forward, radians: world.rollDegrees * .pi / 180.0)
    var right = venueVectorNormalized(venueVectorCross(forward, up))
    let pitch = world.pitchDegrees * .pi / 180.0
    forward = venueVectorRotated(forward, around: right, radians: pitch)
    up = venueVectorRotated(up, around: right, radians: pitch)
    let yaw = -world.yawDegrees * .pi / 180.0
    let globalUp = (x: 0.0, y: 0.0, z: 1.0)
    forward = venueVectorNormalized(venueVectorRotated(forward, around: globalUp, radians: yaw))
    up = venueVectorNormalized(venueVectorRotated(up, around: globalUp, radians: yaw))
    right = venueVectorNormalized(venueVectorCross(forward, up))
    up = venueVectorNormalized(venueVectorCross(right, forward))
    return FixtureVenueBasis(
        forward: VenueVectorState(x: forward.x, y: forward.y, z: forward.z),
        up: VenueVectorState(x: up.x, y: up.y, z: up.z),
        right: VenueVectorState(x: right.x, y: right.y, z: right.z)
    )
}

private func venueNormalizedCoordinate(_ value: Double, negativeExtent: Double, positiveExtent: Double) -> Double {
    let extent = value < 0 ? max(1, negativeExtent) : max(1, positiveExtent)
    return min(1, max(-1, value / extent))
}

private func venueWorldCoordinate(_ value: Double, negativeExtent: Double, positiveExtent: Double) -> Double {
    value * (value < 0 ? max(1, negativeExtent) : max(1, positiveExtent))
}

private func wallWashBarWorldEndpoints(_ worldOrigin: SlotWorldPosition, halfLength: Double) -> (start: SlotWorldPosition, end: SlotWorldPosition) {
    let axis = wallWashBarAxisVector(worldOrigin, halfLength: halfLength)
    let start = SlotWorldPosition(
        x: worldOrigin.x - axis.x,
        y: worldOrigin.y - axis.y,
        z: worldOrigin.z - axis.z,
        yawDegrees: worldOrigin.yawDegrees,
        pitchDegrees: worldOrigin.pitchDegrees,
        rollDegrees: worldOrigin.rollDegrees,
        panFlip: worldOrigin.panFlip,
        tiltFlip: worldOrigin.tiltFlip
    )
    let end = SlotWorldPosition(
        x: worldOrigin.x + axis.x,
        y: worldOrigin.y + axis.y,
        z: worldOrigin.z + axis.z,
        yawDegrees: worldOrigin.yawDegrees,
        pitchDegrees: worldOrigin.pitchDegrees,
        rollDegrees: worldOrigin.rollDegrees,
        panFlip: worldOrigin.panFlip,
        tiltFlip: worldOrigin.tiltFlip
    )
    return (start, end)
}

private func wallWashBarAxisVector(_ worldOrigin: SlotWorldPosition, halfLength: Double) -> (x: Double, y: Double, z: Double) {
    let rollRadians = worldOrigin.rollDegrees * .pi / 180.0
    let pitchRadians = worldOrigin.pitchDegrees * .pi / 180.0
    let yawRadians = worldOrigin.yawDegrees * .pi / 180.0

    var axis = (x: halfLength, y: 0.0, z: 0.0)
    axis = rotateAroundY(axis, radians: rollRadians)
    axis = rotateAroundX(axis, radians: pitchRadians)
    axis = rotateAroundZ(axis, radians: -yawRadians)
    return axis
}

private func sceneWallWashSpreadAxis(_ worldOrigin: SlotWorldPosition) -> SCNVector3 {
    let axis = wallWashBarAxisVector(worldOrigin, halfLength: 45.0)
    return sceneVectorNormalize(SCNVector3(CGFloat(axis.x / 100.0), CGFloat(axis.z / 100.0), CGFloat(-axis.y / 100.0)))
}

private func simdWallWashSpreadAxis(_ worldOrigin: SlotWorldPosition) -> SIMD3<Float> {
    let axis = wallWashBarAxisVector(worldOrigin, halfLength: 45.0)
    let vector = SIMD3<Float>(Float(axis.x / 100.0), Float(axis.z / 100.0), Float(-axis.y / 100.0))
    let length = simd_length(vector)
    guard length > 0.0001 else { return SIMD3<Float>(1, 0, 0) }
    return vector / length
}

private func projectedBeamTarget(origin: CGPoint, worldOrigin: SlotWorldPosition, mountYawDegrees: Double, mountPitchDegrees: Double, preview: SlotPreview, beamKind: StageFixtureBeam.BeamKind, size: CGSize, projection: StageProjection) -> CGPoint {
    let isMovingHead = beamKind == .movingHead
    let panRange = isMovingHead ? 540.0 : 180.0
    let tiltRange = isMovingHead ? 180.0 : 90.0
    return projectedBeamTarget(
        origin: origin,
        worldOrigin: worldOrigin,
        mountYawDegrees: mountYawDegrees,
        mountPitchDegrees: mountPitchDegrees,
        pose: StageBeamPose(
            panDegrees: preview.logicalPanDegrees
                ?? preview.panDegrees
                ?? panDegrees(forDMX: preview.pan, range: panRange),
            tiltDegrees: preview.logicalTiltDegrees
                ?? preview.tiltDegrees
                ?? tiltDegrees(forDMX: preview.tilt, range: tiltRange)
        ),
        panRange: panRange,
        tiltRange: tiltRange,
        beamKind: beamKind,
        size: size,
        projection: projection
    )
}

private func interpolatedVenueTargetEndpoint(
    _ normalEndpoint: SlotWorldPosition,
    preview: VenueTargetPreviewVisual?
) -> SlotWorldPosition {
    guard let preview else { return normalEndpoint }
    let progress = preview.easedProgress
    return SlotWorldPosition(
        x: preview.startEndpoint.x + (preview.endpoint.x - preview.startEndpoint.x) * progress,
        y: preview.startEndpoint.y + (preview.endpoint.y - preview.startEndpoint.y) * progress,
        z: preview.startEndpoint.z + (preview.endpoint.z - preview.startEndpoint.z) * progress,
        yawDegrees: normalEndpoint.yawDegrees,
        pitchDegrees: normalEndpoint.pitchDegrees,
        rollDegrees: normalEndpoint.rollDegrees,
        panFlip: normalEndpoint.panFlip,
        tiltFlip: normalEndpoint.tiltFlip
    )
}

private func projectedBeamTarget(origin: CGPoint, worldOrigin: SlotWorldPosition, mountYawDegrees: Double, mountPitchDegrees: Double, pose: StageBeamPose, panRange: Double, tiltRange: Double, beamKind: StageFixtureBeam.BeamKind, size: CGSize, projection: StageProjection) -> CGPoint {
    let endpoint = beamWorldEndpoint(
        worldOrigin: worldOrigin,
        mountYawDegrees: mountYawDegrees,
        mountPitchDegrees: mountPitchDegrees,
        pose: pose,
        panRange: panRange,
        tiltRange: tiltRange,
        beamKind: beamKind
    )
    return worldProjectedAbsoluteBeamPoint(endpoint, projection: projection, size: size)
}

private func worldEndpoint(from origin: SlotWorldPosition, direction: VenueVectorState, distance: Double) -> SlotWorldPosition {
    SlotWorldPosition(
        x: origin.x + direction.x * distance,
        y: origin.y + direction.y * distance,
        z: origin.z + direction.z * distance,
        yawDegrees: origin.yawDegrees,
        pitchDegrees: origin.pitchDegrees,
        rollDegrees: origin.rollDegrees,
        panFlip: origin.panFlip,
        tiltFlip: origin.tiltFlip
    )
}

private func beamWorldEndpoint(worldOrigin: SlotWorldPosition, mountYawDegrees: Double, mountPitchDegrees: Double, pose: StageBeamPose, panRange: Double, tiltRange: Double, beamKind: StageFixtureBeam.BeamKind) -> SlotWorldPosition {
    if beamKind != .movingHead {
        let distance = beamKind == .wallWash ? 260.0 : 180.0
        let staticYaw = mountYawDegrees * .pi / 180.0
        let directionX = sin(staticYaw)
        var directionY = cos(staticYaw)
        var directionZ = beamKind == .wallWash ? -0.38 : -0.55
        let pitchRadians = mountPitchDegrees * .pi / 180.0
        let rotatedY = directionY * cos(pitchRadians) - directionZ * sin(pitchRadians)
        let rotatedZ = directionY * sin(pitchRadians) + directionZ * cos(pitchRadians)
        directionY = rotatedY
        directionZ = rotatedZ
        return SlotWorldPosition(
            x: worldOrigin.x + directionX * distance,
            y: worldOrigin.y + directionY * distance,
            z: worldOrigin.z + directionZ * distance,
            yawDegrees: worldOrigin.yawDegrees,
            pitchDegrees: worldOrigin.pitchDegrees
        )
    }

    let previewPanDegrees = worldOrigin.panFlip ? -pose.panDegrees : pose.panDegrees
    let previewTiltDegrees = worldOrigin.tiltFlip ? -pose.tiltDegrees : pose.tiltDegrees
    let tiltPhysicalRadians = movingHeadTiltRadians(from: previewTiltDegrees, range: tiltRange)
    let horizontal = -cos(tiltPhysicalRadians)
    let vertical = -sin(tiltPhysicalRadians)
    let panRadians = previewPanDegrees * .pi / 180.0
    let pitchRadians = mountPitchDegrees * .pi / 180.0
    let mountYawRadians = mountYawDegrees * .pi / 180.0
    var direction = rotateAroundZ(
        (x: 0.0, y: horizontal, z: vertical),
        radians: -panRadians
    )
    direction = rotateAroundX(direction, radians: pitchRadians)
    direction = rotateAroundZ(direction, radians: -mountYawRadians)
    let beamDistance = StageWorld.movingHeadBeamDistanceCm

    return SlotWorldPosition(
        x: worldOrigin.x + direction.x * beamDistance,
        y: worldOrigin.y + direction.y * beamDistance,
        z: worldOrigin.z + direction.z * beamDistance,
        yawDegrees: worldOrigin.yawDegrees,
        pitchDegrees: worldOrigin.pitchDegrees
    )
}

private func rotateAroundX(_ vector: (x: Double, y: Double, z: Double), radians: Double) -> (x: Double, y: Double, z: Double) {
    (
        x: vector.x,
        y: vector.y * cos(radians) - vector.z * sin(radians),
        z: vector.y * sin(radians) + vector.z * cos(radians)
    )
}

private func rotateAroundY(_ vector: (x: Double, y: Double, z: Double), radians: Double) -> (x: Double, y: Double, z: Double) {
    (
        x: vector.x * cos(radians) + vector.z * sin(radians),
        y: vector.y,
        z: -vector.x * sin(radians) + vector.z * cos(radians)
    )
}

private func rotateAroundZ(_ vector: (x: Double, y: Double, z: Double), radians: Double) -> (x: Double, y: Double, z: Double) {
    (
        x: vector.x * cos(radians) - vector.y * sin(radians),
        y: vector.x * sin(radians) + vector.y * cos(radians),
        z: vector.z
    )
}

private func movingHeadTiltRadians(from tiltDegrees: Double, range: Double) -> Double {
    let physicalDegrees = min(max(tiltDegrees + range / 2.0, 0.0), range)
    return physicalDegrees * .pi / 180.0
}

private func panDegrees(forDMX value: Int, range: Double) -> Double {
    ((Double(value) / 255.0) - 0.5) * range
}

private func tiltDegrees(forDMX value: Int, range: Double) -> Double {
    ((Double(value) / 255.0) - 0.5) * range
}

private func stepToward(_ current: Double, _ target: Double, maxDelta: Double) -> Double {
    let delta = target - current
    guard abs(delta) > 0.0001 else { return target }
    let limited = min(abs(delta), max(0.0, maxDelta))
    return current + limited * (delta >= 0 ? 1.0 : -1.0)
}

private func clamp(_ value: CGFloat, lower: CGFloat, upper: CGFloat) -> CGFloat {
    min(max(value, lower), upper)
}

struct FaderSpec {
    let title: String
    let value: Binding<Double>
    let display: String
    var upperBound: Double = 255
    var enabled: Bool = true
    var tint: Color = .accentColor
}

struct UniverseFixtureStrip: View {
    let groups: [UniverseFixtureGroup]

    private var minChannel: Int {
        groups.map { $0.range.address }.min() ?? 1
    }

    private var totalSpan: CGFloat {
        CGFloat(max(1, (groups.map { $0.range.lastChannel }.max() ?? minChannel) - minChannel + 1))
    }

    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(BeatBeamPalette.raisedBackground)

                ForEach(Array(groups.enumerated()), id: \.element.id) { index, group in
                    let startOffset = CGFloat(group.range.address - minChannel) / totalSpan
                    let widthRatio = CGFloat(group.footprint) / totalSpan
                    let blockWidth = max(52, geometry.size.width * widthRatio)
                    let x = geometry.size.width * startOffset
                    UniverseFixtureStripBlock(group: group, isStriped: index.isMultiple(of: 2))
                        .frame(width: min(blockWidth, geometry.size.width - x), height: geometry.size.height - 8)
                        .offset(x: x, y: 4)
                }
            }
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(BeatBeamPalette.border, lineWidth: 1)
            )
        }
    }
}

struct UniverseFixtureStripBlock: View {
    let group: UniverseFixtureGroup
    let isStriped: Bool

    var body: some View {
        let accent = monitorGroupColor(group)
        let baseBackground = isStriped ? BeatBeamPalette.mutedBackground : Color.white.opacity(0.04)
        VStack(alignment: .leading, spacing: 4) {
            Text(group.range.label)
                .font(.system(size: 11, weight: .bold))
                .lineLimit(1)
            Text("\(group.range.address)-\(group.range.lastChannel)")
                .font(.system(size: 10, weight: .medium, design: .monospaced))
                .foregroundStyle(.secondary)
                .lineLimit(1)
            Spacer(minLength: 0)
        }
        .padding(8)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(baseBackground)
        .overlay(alignment: .leading) {
            Rectangle()
                .fill(accent)
                .frame(width: 4)
        }
        .overlay(
            RoundedRectangle(cornerRadius: 7, style: .continuous)
                .stroke(accent.opacity(0.40), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
    }
}

struct UniverseFixtureCard: View {
    let group: UniverseFixtureGroup
    let isStriped: Bool

    private let columns = [
        GridItem(.adaptive(minimum: 52, maximum: 64), spacing: 6)
    ]

    var body: some View {
        let accent = monitorGroupColor(group)
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 10) {
                RoundedRectangle(cornerRadius: 3, style: .continuous)
                    .fill(accent)
                    .frame(width: 8, height: 34)

                VStack(alignment: .leading, spacing: 4) {
                    Text(group.range.label)
                        .font(.system(size: 13, weight: .semibold))
                        .lineLimit(1)
                    Text(group.rangeText)
                        .font(.system(size: 11, weight: .medium, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    Text(group.range.fixtureLabel)
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }

                Spacer(minLength: 8)

                Text("\(group.footprint) ch")
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .background(accent.opacity(0.16))
                    .clipShape(Capsule())
            }

            LazyVGrid(columns: columns, spacing: 6) {
                ForEach(group.channels) { item in
                    UniverseChannelCell(channel: item.channel, value: item.value, accent: accent)
                }
            }
        }
        .padding(10)
        .background(isStriped ? BeatBeamPalette.raisedBackground : BeatBeamPalette.mutedBackground)
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(accent.opacity(0.22), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

struct UniverseChannelCell: View {
    let channel: Int
    let value: Int
    let accent: Color

    var body: some View {
        VStack(spacing: 3) {
            Text("\(channel)")
                .font(.system(size: 10, weight: .bold, design: .monospaced))
                .foregroundStyle(.secondary)
            Text("\(value)")
                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                .foregroundStyle(value > 0 ? Color.white : .secondary)
        }
        .frame(maxWidth: .infinity, minHeight: 42)
        .background(value > 0 ? accent.opacity(0.22) : Color.black.opacity(0.14))
        .overlay(
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .stroke(value > 0 ? accent.opacity(0.35) : BeatBeamPalette.border, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
    }
}

struct UniverseFixtureListBlock: View {
    let group: UniverseFixtureGroup
    let isStriped: Bool

    private var accent: Color {
        monitorGroupColor(group)
    }

    private var formattedChannels: String {
        let pairs = group.channels.map { item in
            String(format: "%3d:%3d", item.channel, item.value)
        }
        let chunkSize = 6
        return stride(from: 0, to: pairs.count, by: chunkSize).map { start in
            let end = min(start + chunkSize, pairs.count)
            return pairs[start..<end].joined(separator: "   ")
        }.joined(separator: "\n")
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(accent)
                .frame(width: 6)

            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(group.range.label)
                        .font(.system(size: 12, weight: .semibold))
                    Text(group.rangeText)
                        .font(.system(size: 11, weight: .medium, design: .monospaced))
                        .foregroundStyle(.secondary)
                    Spacer(minLength: 8)
                }

                Text(formattedChannels)
                    .font(.system(size: 12, weight: .medium, design: .monospaced))
                    .foregroundStyle(.primary)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 9)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(isStriped ? BeatBeamPalette.raisedBackground : BeatBeamPalette.mutedBackground)
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(accent.opacity(0.18), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

struct PanelSurface<Content: View>: View {
    let title: String
    var compact: Bool = false
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: compact ? 10 : 12) {
            Text(title)
                .font(.headline)
                .foregroundStyle(Color.white)
            content
        }
        .padding(compact ? 12 : 14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(BeatBeamPalette.surfaceGradient)
                .overlay(
                    LinearGradient(
                        colors: [BeatBeamPalette.brandCyan.opacity(0.10), BeatBeamPalette.brandMagenta.opacity(0.06), Color.clear],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(BeatBeamPalette.border, lineWidth: 1)
        )
    }
}

struct LabeledStatusRow: View {
    let title: String
    let text: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(title)
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(BeatBeamPalette.secondaryText)
                .frame(width: 42, alignment: .leading)
            Text(text)
                .foregroundStyle(BeatBeamPalette.secondaryText)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct MetricTile: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title.uppercased())
                .font(.system(size: 11, weight: .medium, design: .monospaced))
                .foregroundStyle(BeatBeamPalette.secondaryText)
            Text(value)
                .font(.system(.body, design: .monospaced))
                .foregroundStyle(Color.white)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(10)
        .frame(maxWidth: .infinity, minHeight: 64, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(BeatBeamPalette.raisedGradient)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(BeatBeamPalette.border, lineWidth: 1)
        )
    }
}

struct CompactMetricTile: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title.uppercased())
                .font(.system(size: 10, weight: .medium, design: .monospaced))
                .foregroundStyle(BeatBeamPalette.secondaryText)
            Text(value)
                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                .foregroundStyle(Color.white)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 7)
        .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(BeatBeamPalette.raisedGradient)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(BeatBeamPalette.border, lineWidth: 1)
        )
    }
}

struct SignalMeterValue: Identifiable {
    let label: String
    let value: Double?
    let accent: Color

    var id: String { label }
}

struct WaveformTransportTile: View {
    let history: [Double]
    let energyValue: String
    let status: String
    let influence: String
    let anticipation: Double?
    let bandValues: [SignalMeterValue]
    let lookahead2Values: [SignalMeterValue]
    let lookahead4Values: [SignalMeterValue]
    let drumValues: [SignalMeterValue]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("WAVEFORM")
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
                Spacer(minLength: 8)
                Text(energyValue)
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(.secondary)
            }

            WaveformSparkline(values: history)
                .frame(height: 34)

            Text(status)
                .font(.system(size: 12, weight: .semibold))
                .lineLimit(1)

            Text(influence)
                .font(.system(size: 11, weight: .medium, design: .monospaced))
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)

            SignalMeterRow(title: "Bands", values: bandValues)
            SignalMeterRow(
                title: anticipationText,
                values: lookahead2Values
            )
            SignalMeterRow(title: "Ahead +4", values: lookahead4Values)
            SignalMeterRow(title: "Drums", values: drumValues)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 7)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(BeatBeamPalette.raisedBackground)
        )
    }

    private var anticipationText: String {
        guard let anticipation else { return "Ahead +2" }
        return "Ahead +2  \(Int((min(1.0, max(0.0, anticipation)) * 100).rounded()))%"
    }
}

struct SignalMeterRow: View {
    let title: String
    let values: [SignalMeterValue]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title.uppercased())
                .font(.system(size: 9, weight: .medium, design: .monospaced))
                .foregroundStyle(.secondary)
            HStack(spacing: 6) {
                ForEach(values) { item in
                    SignalMeterTile(item: item)
                }
            }
        }
    }
}

struct SignalMeterTile: View {
    let item: SignalMeterValue

    var body: some View {
        let value = min(1.0, max(0.0, item.value ?? 0.0))
        let displayValue = pow(value, 0.58)

        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 4) {
                Text(item.label)
                    .font(.system(size: 9, weight: .semibold, design: .monospaced))
                    .foregroundStyle(.secondary)
                Spacer(minLength: 4)
                Text(item.value == nil ? "-" : "\(Int((value * 100).rounded()))")
                    .font(.system(size: 9, weight: .semibold, design: .monospaced))
                    .foregroundStyle(.secondary)
            }

            GeometryReader { geometry in
                let width = geometry.size.width
                ZStack(alignment: .leading) {
                    Capsule(style: .continuous)
                        .fill(Color.black.opacity(0.18))
                    Capsule(style: .continuous)
                        .fill(item.accent.opacity(item.value == nil ? 0.12 : 0.85))
                        .frame(width: max(4, width * displayValue))
                }
                .overlay(
                    Capsule(style: .continuous)
                        .stroke(Color.white.opacity(0.08), lineWidth: 1)
                )
            }
            .frame(height: 6)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct WaveformSparkline: View {
    let values: [Double]

    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            let normalized = values.map { min(1.0, max(0.0, $0)) }

            ZStack {
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .fill(Color.black.opacity(0.16))
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .stroke(BeatBeamPalette.border, lineWidth: 1)

                Path { path in
                    let y = size.height - 1
                    path.move(to: CGPoint(x: 0, y: y))
                    path.addLine(to: CGPoint(x: size.width, y: y))
                }
                .stroke(Color.white.opacity(0.08), style: StrokeStyle(lineWidth: 1, dash: [3, 3]))

                if normalized.count > 1 {
                    let points = sparklinePoints(values: normalized, size: size)

                    Path { path in
                        guard let first = points.first else { return }
                        path.move(to: CGPoint(x: first.x, y: size.height))
                        path.addLine(to: first)
                        for point in points.dropFirst() {
                            path.addLine(to: point)
                        }
                        if let last = points.last {
                            path.addLine(to: CGPoint(x: last.x, y: size.height))
                        }
                        path.closeSubpath()
                    }
                    .fill(
                        LinearGradient(
                            colors: [
                                BeatBeamPalette.triggerActive.opacity(0.28),
                                BeatBeamPalette.triggerActive.opacity(0.04)
                            ],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )

                    Path { path in
                        guard let first = points.first else { return }
                        path.move(to: first)
                        for point in points.dropFirst() {
                            path.addLine(to: point)
                        }
                    }
                    .stroke(BeatBeamPalette.triggerActive, lineWidth: 2)

                    if let last = points.last {
                        Circle()
                            .fill(Color.white)
                            .frame(width: 5, height: 5)
                            .position(last)
                    }
                } else {
                    Image(systemName: "waveform.path.ecg")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private func sparklinePoints(values: [Double], size: CGSize) -> [CGPoint] {
        guard !values.isEmpty else { return [] }
        if values.count == 1 {
            let y = size.height - CGFloat(values[0]) * (size.height - 4) - 2
            return [CGPoint(x: size.width, y: y)]
        }

        let step = size.width / CGFloat(max(values.count - 1, 1))
        return values.enumerated().map { index, value in
            CGPoint(
                x: CGFloat(index) * step,
                y: size.height - CGFloat(value) * (size.height - 4) - 2
            )
        }
    }
}

struct DeckTransportTile: View {
    let title: String
    let meta: String
    let time: String
    let isActive: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(title.uppercased())
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                    .foregroundStyle(isActive ? BeatBeamPalette.brandCyan : BeatBeamPalette.secondaryText)
                if isActive {
                    Text("ACTIVE")
                        .font(.system(size: 8, weight: .bold, design: .monospaced))
                        .foregroundStyle(BeatBeamPalette.brandCyan)
                }
                Spacer(minLength: 8)
                Text(time)
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(BeatBeamPalette.brandCyan)
            }
            Text(meta)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Color.white)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 7)
        .frame(maxWidth: .infinity, minHeight: 56, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(BeatBeamPalette.raisedGradient)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(BeatBeamPalette.border, lineWidth: 1)
        )
    }
}

struct ColorPreviewSwatch: View {
    @ObservedObject var editor: SlotEditor

    private var previewColor: Color {
        Color(
            red: Double(editor.red) / 255.0,
            green: Double(editor.green) / 255.0,
            blue: Double(editor.blue) / 255.0
        )
    }

    var body: some View {
        VStack(alignment: .trailing, spacing: 6) {
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(previewColor)
                .overlay(
                    RoundedRectangle(cornerRadius: 6, style: .continuous)
                        .stroke(Color.white.opacity(0.12), lineWidth: 1)
                )
                .frame(width: 78, height: 42)
            Text("RGBW \(editor.red)/\(editor.green)/\(editor.blue)/\(editor.white)")
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary)
        }
    }
}

struct TouchPadToggleButton: View {
    let title: String
    let systemImage: String
    let isOn: Binding<Bool>

    var body: some View {
        Button {
            isOn.wrappedValue.toggle()
        } label: {
            VStack(spacing: 8) {
                Image(systemName: systemImage)
                    .font(.system(size: 16, weight: .semibold))
                Text(title)
                    .font(.system(size: 11, weight: .semibold))
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
            }
            .frame(maxWidth: .infinity, minHeight: 52)
            .padding(.horizontal, 6)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(isOn.wrappedValue ? AnyShapeStyle(BeatBeamPalette.activeGradient) : AnyShapeStyle(BeatBeamPalette.raisedGradient))
            )
            .foregroundStyle(isOn.wrappedValue ? Color.black : Color.white.opacity(0.92))
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(isOn.wrappedValue ? BeatBeamPalette.triggerOutline : BeatBeamPalette.border, lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}

struct TouchPadTriggerButton: View {
    let title: String
    let systemImage: String
    let isActive: Bool
    let progress: Double
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 8) {
                Image(systemName: systemImage)
                    .font(.system(size: 17, weight: .semibold))
                Text(title)
                    .font(.system(size: 11, weight: .semibold))
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
            }
            .frame(maxWidth: .infinity, minHeight: 52)
            .padding(.horizontal, 6)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(isActive ? AnyShapeStyle(BeatBeamPalette.utilityGradient) : AnyShapeStyle(BeatBeamPalette.raisedGradient))
            )
            .foregroundStyle(isActive ? Color.white : Color.white.opacity(0.92))
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(isActive ? BeatBeamPalette.triggerOutline : BeatBeamPalette.border, lineWidth: isActive ? 2 : 1)
            )
            .overlay(alignment: .bottomLeading) {
                if isActive {
                    RoundedRectangle(cornerRadius: 3, style: .continuous)
                        .fill(Color.white.opacity(0.92))
                        .frame(width: max(8, min(1.0, max(0.0, progress)) * 84), height: 4)
                        .padding(.horizontal, 8)
                        .padding(.bottom, 8)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}

struct TouchPadSelectButton: View {
    let title: String
    let systemImage: String
    let value: String
    let selection: Binding<String>

    private var isSelected: Bool {
        selection.wrappedValue == value
    }

    var body: some View {
        Button {
            selection.wrappedValue = value
        } label: {
            VStack(spacing: 8) {
                Image(systemName: systemImage)
                    .font(.system(size: 16, weight: .semibold))
                Text(title)
                    .font(.system(size: 11, weight: .semibold))
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
            }
            .frame(maxWidth: .infinity, minHeight: 52)
            .padding(.horizontal, 6)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(isSelected ? AnyShapeStyle(BeatBeamPalette.activeGradient) : AnyShapeStyle(BeatBeamPalette.raisedGradient))
            )
            .foregroundStyle(isSelected ? Color.black : Color.white.opacity(0.92))
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(isSelected ? BeatBeamPalette.triggerOutline : BeatBeamPalette.border, lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}

struct AutoShowStyleButton: View {
    let title: String
    let systemImage: String
    let value: String
    let selection: Binding<String>
    let autoShowEnabled: Bool

    private var isSelected: Bool {
        selection.wrappedValue == value
    }

    var body: some View {
        Button {
            selection.wrappedValue = value
        } label: {
            VStack(spacing: 8) {
                Image(systemName: systemImage)
                    .font(.system(size: 16, weight: .semibold))
                Text(title)
                    .font(.system(size: 11, weight: .semibold))
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
            }
            .frame(maxWidth: .infinity, minHeight: 52)
            .padding(.horizontal, 6)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(
                        isSelected
                            ? (autoShowEnabled ? AnyShapeStyle(BeatBeamPalette.utilityGradient) : AnyShapeStyle(Color.white.opacity(0.08)))
                            : AnyShapeStyle(BeatBeamPalette.raisedGradient)
                    )
            )
            .foregroundStyle(foregroundColor)
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(borderColor, lineWidth: isSelected ? 2 : 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
        .buttonStyle(.plain)
    }

    private var backgroundColor: Color {
        guard isSelected else { return Color.clear }
        return autoShowEnabled ? BeatBeamPalette.utilityActive : BeatBeamPalette.mutedBackground
    }

    private var foregroundColor: Color {
        if isSelected && autoShowEnabled {
            return .white
        }
        return .white.opacity(0.92)
    }

    private var borderColor: Color {
        guard isSelected else { return BeatBeamPalette.border }
        return BeatBeamPalette.triggerOutline
    }
}

struct LivePresetButton: View {
    let preset: LivePreset
    let isActive: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .top, spacing: 6) {
                    Image(systemName: preset.systemImage)
                        .font(.system(size: 14, weight: .semibold))
                    Spacer(minLength: 0)
                    if isActive {
                        Text("LIVE")
                            .font(.system(size: 8, weight: .bold, design: .monospaced))
                            .padding(.horizontal, 5)
                            .padding(.vertical, 3)
                            .background(Color.white.opacity(0.18))
                            .clipShape(Capsule())
                    }
                }
                Spacer(minLength: 2)
                Text(preset.title)
                    .font(.system(size: 11, weight: .semibold))
                    .lineLimit(2)
                Text(preset.subtitle)
                    .font(.system(size: 9, weight: .medium, design: .monospaced))
                    .foregroundStyle(isActive ? Color.white.opacity(0.78) : .secondary)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
            .padding(8)
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(isActive ? AnyShapeStyle(BeatBeamPalette.utilityGradient) : AnyShapeStyle(BeatBeamPalette.raisedGradient))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(isActive ? BeatBeamPalette.triggerOutline : BeatBeamPalette.border, lineWidth: isActive ? 2 : 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .foregroundStyle(isActive ? Color.white : Color.white.opacity(0.92))
        }
        .buttonStyle(.plain)
    }
}

struct FaderBankSection: View {
    let title: String
    let faders: [FaderSpec]

    var body: some View {
        PanelSurface(title: title, compact: true) {
            HStack(alignment: .top, spacing: 10) {
                ForEach(Array(faders.enumerated()), id: \.offset) { _, fader in
                    VerticalFader(spec: fader)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct VerticalFader: View {
    let spec: FaderSpec

    var body: some View {
        VStack(spacing: 8) {
            Text(spec.title)
                .font(.system(size: 11, weight: .medium))
                .lineLimit(1)
                .frame(width: 58)

            ZStack {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(Color.black.opacity(0.18))
                    .frame(width: 58, height: 188)

                Slider(value: spec.value, in: 0...spec.upperBound, step: 1)
                    .rotationEffect(.degrees(-90))
                    .frame(width: 164)
                    .frame(height: 40)
                    .tint(spec.tint)
            }
            .opacity(spec.enabled ? 1 : 0.28)
            .allowsHitTesting(spec.enabled)

            Text(spec.display)
                .font(.system(.caption, design: .monospaced))
                .frame(width: 58)
        }
        .frame(width: 64)
    }
}

@main
struct BeatBeamDMXNativeApp: App {
    @StateObject private var model = AppModel()
    @NSApplicationDelegateAdaptor(BeatBeamAppDelegate.self) private var appDelegate

    init() {
        NSApplication.shared.appearance = NSAppearance(named: .darkAqua)
    }

    var body: some Scene {
        WindowGroup(beatBeamAppDisplayName) {
            ContentView()
                .environmentObject(model)
                .preferredColorScheme(.dark)
                .onAppear {
                    appDelegate.onTerminate = { [weak model] in
                        model?.stop()
                    }
                }
        }

        WindowGroup("\(beatBeamAppDisplayName) Map Preview", id: "map-preview") {
            MapPreviewWindowView()
                .environmentObject(model)
                .preferredColorScheme(.dark)
        }
        .defaultSize(width: 1280, height: 800)

    }
}
