import Foundation

struct ContractAppInfo: Decodable {
    let name: String
    let apiSchemaVersion: Int
}

struct ContractSourceState: Decodable {
    let mode: String
    let resolvedMode: String?
    let app: String
    let port: Int?
    let expectedDestination: String
    let lastSource: String?
}

struct ContractTransportState: Decodable {
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

struct ContractState: Decodable {
    let app: ContractAppInfo
    let source: ContractSourceState
    let transport: ContractTransportState
}

func decode(_ json: String) throws -> ContractState {
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    return try decoder.decode(ContractState.self, from: Data(json.utf8))
}

func require(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else {
        fputs("FAIL: \(message)\n", stderr)
        exit(1)
    }
}

do {
    let virtualDj = try decode("""
    {
      "app": { "name": "BeatBeam DMX Beta", "api_schema_version": 4 },
      "source": {
        "mode": "auto",
        "resolved_mode": "virtualdj",
        "active_playback_source": "virtualdj",
        "app": "VirtualDJ",
        "port": null,
        "expected_destination": "MusicAnalyzer playback snapshot",
        "last_source": null,
        "available": true,
        "deck_number": 2,
        "track_path": "/Music/Test.flac"
      },
      "transport": {
        "mode": "auto",
        "resolved_mode": "virtualdj",
        "manual_bpm": 120.0,
        "effective_bpm": 125.0,
        "manual_phrase": "verse",
        "manual_phrase_label": "Verse",
        "idle_animation_enabled": true,
        "tap_count": 0,
        "tap_locked": false,
        "external_available": false,
        "last_tap_at": null,
        "active_playback_source": "virtualdj",
        "virtualdj_deck_number": 2,
        "virtualdj_track_path": "/Music/Test.flac",
        "virtualdj_bar_number": 4,
        "virtualdj_beat_number": 3
      },
      "developer_playback": { "source": "virtualdj" },
      "dmx": { "playback": { "source": "virtualdj" } }
    }
    """)
    require(virtualDj.app.apiSchemaVersion == 4, "VirtualDJ schema version")
    require(virtualDj.source.port == nil, "VirtualDJ accepts a null source port")
    require(virtualDj.transport.resolvedMode == "virtualdj", "VirtualDJ transport mode")
    require(virtualDj.transport.effectiveBpm == 125.0, "VirtualDJ effective BPM")

    let legacy = try decode("""
    {
      "app": { "name": "BeatBeam DMX", "api_schema_version": 4 },
      "source": {
        "mode": "external_osc",
        "resolved_mode": "external_osc",
        "app": "External OSC / Rekordbox",
        "port": 4461,
        "expected_destination": "127.0.0.1:4461",
        "last_source": "127.0.0.1:51000"
      },
      "transport": {
        "mode": "auto",
        "resolved_mode": "external_osc",
        "manual_bpm": 120.0,
        "effective_bpm": 128.0,
        "manual_phrase": "verse",
        "manual_phrase_label": "Verse",
        "idle_animation_enabled": true,
        "tap_count": 0,
        "tap_locked": false,
        "external_available": true,
        "last_tap_at": null
      }
    }
    """)
    require(legacy.source.port == 4461, "Legacy source port remains available")
    require(legacy.transport.resolvedMode == "external_osc", "Legacy transport remains decodeable")

    print("PASS: native backend state contract")
} catch {
    fputs("FAIL: \(error)\n", stderr)
    exit(1)
}
