import Foundation

func require(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else {
        fputs("FAIL: \(message)\n", stderr)
        exit(1)
    }
}

func decode(_ json: String) throws -> RemoteLiveStateV2 {
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    return try decoder.decode(RemoteLiveStateV2.self, from: Data(json.utf8))
}

func decodeSSEData(_ wire: String) throws -> RemoteLiveStateV2 {
    let dataLines = wire.split(separator: "\n").compactMap { line -> String? in
        line.hasPrefix("data:") ? String(line.dropFirst(5)).trimmingCharacters(in: .whitespaces) : nil
    }
    return try decode(dataLines.joined(separator: "\n"))
}

func decoder() -> JSONDecoder {
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    return decoder
}

let healthy = """
{
  "schema_version": 2, "schema": "beatbeam.remote-live-state.v2", "state_revision": 10, "event_sequence": 10, "server_timestamp": 1,
  "connection": { "protocol_version": 2, "compatible": true, "server": "BeatBeam" },
  "show": { "configured_production_mode": "DYNAMIC_COMPOSER_ENABLED", "physical_frame_source": "dynamic_composer", "preview_source": "dynamic_composer", "fallback_active": false, "fallback_reason": null, "dynamic_composer_eligible": true, "dynamic_composer_active": true, "baseline_fallback_available": true },
  "track": { "title": "Track", "artist": "Artist", "active_deck": 1, "playing": true, "position_milliseconds": 1200, "duration_milliseconds": null, "bpm": 128, "beat": 2, "bar": 3, "transport_fresh": true, "readiness": "READY" },
  "decks": [{ "number": 1, "loaded": true, "title": "Track", "artist": "Artist", "playing": true, "master": true, "active": true, "analysis_readiness": "READY", "prewarm_readiness": "READY" }],
  "musical_state": { "section": "chorus", "section_progress": 0.5, "relative_energy": 0.8, "energy_trajectory": "rising", "recurrence": 0.2, "material_context": null, "current_rme": null, "event_envelope": { "active": false, "phase": null, "progress": null, "event_type": null }, "effective_intensity": 0.8, "analyzed_intensity": 0.7, "live_intensity_valid": true },
  "dmx": { "connected": true, "device_name": "DMX", "renderer_healthy": true, "renderer_active": true, "frame_sequence": 10, "last_error": null, "dispatch_failures": 0, "physical_output_available": true },
  "fixtures": [], "overrides": { "any_active": false, "phrase": null, "energy": null, "color": null, "momentary_effects": [], "blackout": false, "automatic": true }, "control": { "scope": "LIVE_CONTROL", "colors": [{"id":"red","label":"Red"}], "phrases": [], "energies": [], "momentary_effects": [], "cue_shots": [], "momentary_lease_seconds": 3 }, "warnings": [], "future_additive_field": "ignored"
}
"""

@main
struct RemoteLiveStateV2ContractTests {
    static func main() {
        do {
            let full = try decode(healthy)
            require(full.show.physicalFrameSource == "dynamic_composer", "healthy physical source")
            require(full.track.readiness == "READY", "healthy readiness")
            require(full.stateRevision == 10, "revision")

            let fallback = try decode(healthy.replacingOccurrences(of: "\"dynamic_composer\", \"preview_source\": \"dynamic_composer\", \"fallback_active\": false, \"fallback_reason\": null", with: "\"existing_autoshow\", \"preview_source\": \"baseline\", \"fallback_active\": true, \"fallback_reason\": \"transport_stale\""))
            require(fallback.show.fallbackActive, "fallback active")
            require(fallback.show.fallbackReason == "transport_stale", "fallback reason")

            let disconnectedFixture = healthy
                .replacingOccurrences(of: "\"connected\": true", with: "\"connected\": false")
                .replacingOccurrences(of: "\"physical_output_available\": true", with: "\"physical_output_available\": false")
            let disconnected = try decode(disconnectedFixture)
            require(!disconnected.dmx.connected && !disconnected.dmx.physicalOutputAvailable, "DMX disconnected")

            let blackout = try decode(healthy.replacingOccurrences(of: "\"blackout\": false, \"automatic\": true", with: "\"blackout\": true, \"automatic\": false"))
            require(blackout.overrides.blackout, "blackout")

            let manual = try decode(healthy.replacingOccurrences(of: "\"color\": null", with: "\"color\": \"red\""))
            require(manual.overrides.color == "red", "manual override")

            let unavailable = try decode(healthy.replacingOccurrences(of: "\"readiness\": \"READY\"", with: "\"readiness\": \"UNAVAILABLE\""))
            require(unavailable.track.readiness == "UNAVAILABLE", "SongAnalyzer unavailable")

            let nullable = try decode(healthy.replacingOccurrences(of: "\"artist\": \"Artist\"", with: "\"artist\": null"))
            require(nullable.track.artist == nil, "known nullable field")

            let unknownTrajectory = try decode(healthy.replacingOccurrences(of: "\"energy_trajectory\": \"rising\"", with: "\"energy_trajectory\": \"unknown\""))
            require(unknownTrajectory.musicalState.energyTrajectory == "unknown", "bounded unknown trajectory")

            let compactState = try JSONSerialization.data(withJSONObject: JSONSerialization.jsonObject(with: Data(healthy.utf8)))
            let compactJSON = String(decoding: compactState, as: UTF8.self)
            let sse = try decodeSSEData("event: state\nid: 10\ndata: \(compactJSON)\n\n")
            require(sse.stateRevision == full.stateRevision, "SSE and polling decode the same state DTO")

            let pairing = """
            {"schema_version":2,"protocol_version":2,"scope":"REMOTE_READ","credential":"redacted","scopes":["REMOTE_READ","LIVE_CONTROL"],"client_id":"ipad","state_path":"/api/remote-v2/state","events_path":"/api/remote-v2/events","control_path":"/api/remote-v2/control"}
            """
            let pairingResponse = try decoder().decode(RemotePairingResponse.self, from: Data(pairing.utf8))
            require(pairingResponse.scopes?.contains("LIVE_CONTROL") == true, "pairing capabilities")
            let pairingError = "{\"error\":\"invalid_pairing_code\"}"
            do {
                _ = try decoder().decode(RemotePairingResponse.self, from: Data(pairingError.utf8))
                require(false, "pairing error must not decode as pairing success")
            } catch { }

            let acknowledgement = "{\"accepted\":true,\"command_id\":\"red\",\"new_state_revision\":11,\"effective_state\":\(healthy),\"error\":null}"
            let accepted = try decoder().decode(RemoteControlAcknowledgement.self, from: Data(acknowledgement.utf8))
            require(accepted.accepted && accepted.newStateRevision == 11, "command acknowledgement")
            let rejection = "{\"accepted\":false,\"command_id\":\"bad\",\"new_state_revision\":10,\"effective_state\":\(healthy),\"error\":\"allowlisted\"}"
            let rejected = try decoder().decode(RemoteControlRejection.self, from: Data(rejection.utf8))
            require(!rejected.accepted && rejected.error == "allowlisted", "command rejection")
        } catch {
            fputs("FAIL: \(error)\n", stderr)
            exit(1)
        }
    }
}
