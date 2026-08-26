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

struct ContractLiveDeck: Decodable {
    let deckNumber: Int?
    let isLoaded: Bool?
    let isActive: Bool?
    let trackTitle: String?
    let beatNumber: Int?
    let barNumber: Int?
    let phrase: String?
    let isPlaying: Bool?
}

struct ContractLiveUi: Decodable {
    let source: String?
    let activeDeckNumber: Int?
    let bpm: Double?
    let beatNumber: Int?
    let barNumber: Int?
    let phrase: String?
    let nextPhrase: String?
    let barsToNext: Int?
    let decks: [ContractLiveDeck]?
}

struct ContractState: Decodable {
    let app: ContractAppInfo
    let source: ContractSourceState
    let transport: ContractTransportState
    let liveUi: ContractLiveUi?
}

struct ContractOscLegacyDeck: Decodable {
    let trackTitle: String?
}

struct ContractOscDeckOverview: Decodable {
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

struct ContractOscDecks: Decodable {
    let legacy: [String: ContractOscLegacyDeck]?
    let overview: [ContractOscDeckOverview]?

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let legacy = try? container.decode([String: ContractOscLegacyDeck].self) {
            self.legacy = legacy
            self.overview = nil
            return
        }
        let overview = try container.decode([ContractOscDeckOverview].self)
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

struct ContractOscState: Decodable {
    let decks: ContractOscDecks?
}

func decodeOsc(_ json: String) throws -> ContractOscState {
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    return try decoder.decode(ContractOscState.self, from: Data(json.utf8))
}

func decodeLiveUi(_ json: String) throws -> ContractLiveUi {
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    return try decoder.decode(ContractLiveUi.self, from: Data(json.utf8))
}

func redactRemoteURL(_ value: String?) -> String {
    guard let value, !value.isEmpty, var components = URLComponents(string: value) else {
        return value ?? "nil"
    }
    components.queryItems = components.queryItems?.map { item in
        item.name.caseInsensitiveCompare("token") == .orderedSame
            ? URLQueryItem(name: item.name, value: "<redacted>")
            : item
    }
    return components.string ?? value
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
    let nullableUi = try decodeLiveUi("""
    { "phrase": null, "next_phrase": null, "bars_to_next": null }
    """)
    require(nullableUi.phrase == nil, "nullable live UI phrase")
    require(nullableUi.nextPhrase == nil, "nullable live UI next phrase")
    require(nullableUi.barsToNext == nil, "nullable live UI countdown")

    let oscDecks = try decodeOsc("""
    {
      "decks": [
        {
          "deck_number": 1,
          "is_loaded": true,
          "track_path": "/Music/Deck-1.flac",
          "file_name": "Deck-1.flac",
          "artist": "Artist One",
          "title": "Deck One",
          "bpm": 126.0,
          "position_milliseconds": 12000,
          "beat_position": 2.5,
          "beat_number": 3,
          "bar_number": 4,
          "captured_at_unix_milliseconds": 100,
          "is_playing": true
        },
        {
          "deck_number": 2,
          "is_loaded": false,
          "track_path": null,
          "file_name": null,
          "artist": null,
          "title": null,
          "bpm": null,
          "position_milliseconds": null,
          "beat_position": null,
          "beat_number": null,
          "bar_number": null,
          "captured_at_unix_milliseconds": 101,
          "is_playing": false
        }
      ]
    }
    """)
    require(oscDecks.decks?.overview?.count == 2, "osc.decks array count")
    require(oscDecks.decks?.overview?.first?.deckNumber == 1, "osc.decks first deck number")
    require(oscDecks.decks?.overview?.first?.bpm == 126.0, "osc.decks BPM")
    require(oscDecks.decks?.overview?.first?.beatNumber == 3, "osc.decks beat")
    require(oscDecks.decks?.overview?.first?.barNumber == 4, "osc.decks bar")
    require(oscDecks.decks?.overview?.last?.isLoaded == false, "osc.decks empty deck")
    require(oscDecks.decks?.overview?.last?.bpm == nil, "osc.decks empty deck has no stale BPM")

    let legacyDecks = try decodeOsc("""
    { "decks": { "1": { "track_title": "Legacy" } } }
    """)
    require(legacyDecks.decks?.legacy?["1"]?.trackTitle == "Legacy", "legacy osc.decks dictionary")

    do {
        _ = try decodeOsc("""
        { "decks": [{ "deck_number": 0, "is_loaded": false, "captured_at_unix_milliseconds": 1 }] }
        """)
        require(false, "invalid osc.decks shape must fail")
    } catch {
        // Expected: malformed deck identities must fail clearly.
    }

    let redacted = redactRemoteURL("http://127.0.0.1:8781/remote?token=fake-token&view=1")
    require(!redacted.contains("fake-token"), "remote token is redacted")
    require(redacted.contains("view=1"), "non-secret remote query remains visible")

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
      "live_ui": {
        "source": "virtualdj",
        "availability": "available",
        "active_deck_number": 2,
        "bpm": 125.0,
        "beat_number": 3,
        "bar_number": 4,
        "phrase": "Chorus 1",
        "next_phrase": "Outro 1",
        "bars_to_next": 8,
        "decks": [
          { "deck_number": 1, "is_loaded": false, "is_active": false, "track_title": null, "beat_number": null, "bar_number": null, "phrase": null },
          { "deck_number": 2, "is_loaded": true, "is_active": true, "track_title": "Test", "beat_number": 3, "bar_number": 4, "phrase": "Chorus 1", "is_playing": true }
        ]
      },
      "dmx": { "playback": { "source": "virtualdj" } }
    }
    """)
    require(virtualDj.app.apiSchemaVersion == 4, "VirtualDJ schema version")
    require(virtualDj.source.port == nil, "VirtualDJ accepts a null source port")
    require(virtualDj.transport.resolvedMode == "virtualdj", "VirtualDJ transport mode")
    require(virtualDj.transport.effectiveBpm == 125.0, "VirtualDJ effective BPM")
    require(virtualDj.liveUi?.source == "virtualdj", "VirtualDJ live UI source")
    require(virtualDj.liveUi?.activeDeckNumber == 2, "VirtualDJ live UI active deck")
    require(virtualDj.liveUi?.beatNumber == 3, "VirtualDJ live UI integer beat")
    require(virtualDj.liveUi?.barNumber == 4, "VirtualDJ live UI bar")
    require(virtualDj.liveUi?.phrase == "Chorus 1", "VirtualDJ live UI phrase")
    require(virtualDj.liveUi?.barsToNext == 8, "VirtualDJ live UI countdown")
    require(virtualDj.liveUi?.decks?.first?.isLoaded == false, "VirtualDJ live UI empty deck")
    require(virtualDj.liveUi?.decks?.last?.isActive == true, "VirtualDJ live UI active deck card")
    require(virtualDj.liveUi?.decks?.last?.isPlaying == true, "VirtualDJ live UI playing deck card")

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
