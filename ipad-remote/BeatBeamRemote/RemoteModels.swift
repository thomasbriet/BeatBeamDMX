import Foundation

struct BeatBeamState: Decodable {
    var dmx: RemoteDMXState
    var osc: RemoteOSCState
}

struct RemoteDMXState: Decodable {
    var connected: Bool
    var blackoutActive: Bool
    var activeSlot: String
    var autoShow: RemoteAutoShowState
}

struct RemoteAutoShowState: Decodable {
    var enabled: Bool
    var style: String
    var styleLabel: String
    var phraseBucket: String?
    var behaviorBucket: String?
    var cueLabel: String?
    var themeLabel: String?
    var themeName: String?
    var motionName: String?
    var overridePhrase: String?
    var overridePhraseLabel: String?
    var dimmerFxName: String?
    var dimmerFxLabel: String?
    var overrideColor: String?
    var overrideColorLabel: String?
    var overrideEnergy: String?
    var overrideEnergyLabel: String?
    var overrideManualStrobe: Bool
    var overrideAudienceSweep: Bool
    var overrideAllOn: Bool
    var overrideParChase: Bool
    var overrideParSnake: Bool
}

struct RemoteOSCState: Decodable {
    let bpm: Double?
    let beatDisplay: Double?
    let phraseCurrent: String?
    let phraseNext: String?
    let trackTitle: String?
    let trackArtist: String?
    let stale: Bool
}

struct ParsedRemoteConnection: Equatable {
    let origin: URL
    let token: String?
    let sourceURL: String

    var displayHost: String {
        if let host = origin.host() {
            if let port = origin.port {
                return "\(host):\(port)"
            }
            return host
        }
        return origin.absoluteString
    }
}

enum RemoteConnectionError: LocalizedError {
    case emptyURL
    case invalidURL
    case missingHost

    var errorDescription: String? {
        switch self {
        case .emptyURL:
            return "Voer een remote URL in."
        case .invalidURL:
            return "De remote URL is ongeldig."
        case .missingHost:
            return "De remote URL mist een host of poort."
        }
    }
}
