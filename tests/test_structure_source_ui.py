import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StructureSourceUiTests(unittest.TestCase):
    def test_main_transport_panel_contains_structure_source_choices(self):
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn('Text("Structuurbron")', native)
        self.assertIn('Text("Legacy").tag("legacy")', native)
        self.assertIn('Text("SongAnalyzer").tag("song_analyzer")', native)
        self.assertIn('"/api/developer/structure-behavior"', native)

    def test_live_remote_no_longer_contains_structure_source_control(self):
        html = (ROOT / "static" / "remote.html").read_text(encoding="utf-8")
        javascript = (ROOT / "static" / "remote.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "remote.css").read_text(encoding="utf-8")
        self.assertNotIn("structureSource", html)
        self.assertNotIn("structureSource", javascript)
        self.assertNotIn("structure-source-control", css)

    def test_native_debug_entrypoint_has_one_central_feature_gate(self):
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn('BEATBEAM_DEBUG_UI', native)
        self.assertIn('if nativeDebugUIEnabled', native)
        self.assertIn('Label("Debug", systemImage: "ladybug")', native)
        self.assertIn('DebugInspectorView()', native)
        self.assertIn('Window("BeatBeam Debug", id: "debug")', native)
        self.assertIn('openWindow(id: "debug")', native)
        debug_window_start = native.index('Window("BeatBeam Debug", id: "debug")')
        self.assertNotIn('.sheet', native[debug_window_start:])

    def test_debug_state_is_bounded_and_reuses_existing_diagnostics(self):
        backend = (ROOT / "beatbeam_app.py").read_text(encoding="utf-8")
        self.assertIn('class SongAnalyzerBridgeDiagnostics', backend)
        self.assertIn('refresh_seconds = max(0.5', backend)
        self.assertIn('"type": "diagnostics"', backend)
        self.assertIn('"debug": beatbeam_debug_state(osc_state)', backend)
        self.assertNotIn('"beat_timestamps"', backend[backend.index('def beatbeam_debug_state'):backend.index('def song_analyzer_structure_state')])

    def test_debug_window_exposes_optional_native_plugin_telemetry(self):
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn("let nativePlugin: DebugNativePlugin?", native)
        self.assertIn('debugDisclosure("LEGACY / NATIVE DIAGNOSTICS"', native)
        self.assertIn('row("Plugin deck"', native)
        self.assertIn('row("Selection reason"', native)
        self.assertIn('row("Send result"', native)

    def test_debug_window_exposes_optional_bridge_control_telemetry(self):
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn("let control: DebugBridgeControl?", native)
        self.assertIn('debugDisclosure("LEGACY / BRIDGE CONTROL"', native)
        self.assertIn('row("Last received"', native)
        self.assertIn('row("Activate received"', native)
        self.assertIn('row("Mutation reason"', native)

    def test_debug_position_uses_readable_milliseconds_and_missing_placeholder(self):
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn("func formatDebugTrackPosition(_ milliseconds: Int?) -> String", native)
        self.assertIn('String(format: "%02d:%02d.%03d", totalSeconds / 60, seconds, millis)', native)
        self.assertIn('String(format: "%02d:%02d:%02d.%03d", hours, minutes, seconds, millis)', native)
        self.assertIn('return "—"', native)
        self.assertIn('row("Position", formatDebugTrackPosition(model.debugState?.virtualdj?.positionMilliseconds))', native)

    def test_debug_analysis_exposes_both_analysis_versions(self):
        backend = (ROOT / "beatbeam_app.py").read_text(encoding="utf-8")
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn('"analysis_version": projection.get("analysis_version")', backend)
        self.assertIn('"phrase_analysis_version": projection.get("phrase_analysis_version")', backend)
        self.assertIn("let analysisVersion: String?", native)
        self.assertIn("let phraseAnalysisVersion: String?", native)
        self.assertIn('row("Analysis version", model.debugState?.analysis?.analysisVersion)', native)
        self.assertIn('row("Phrase analysis", model.debugState?.analysis?.phraseAnalysisVersion)', native)

    def test_debug_queue_keeps_failure_reasons_and_library_status_separate(self):
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn("let failedRunner: Int?", native)
        self.assertIn("let uniqueFailedTracks: Int?", native)
        self.assertIn("let currentTrackCount: Int?", native)
        self.assertIn('row("Failed runner"', native)
        self.assertIn('row("Library current / stale"', native)

    def test_debug_contains_bounded_full_structure_with_current_highlights(self):
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn('DisclosureGroup("Volledige trackstructuur"', native)
        self.assertIn("let segments: [DebugTrackStructureSegment]?", native)
        self.assertIn("let events: [DebugTrackStructureEvent]?", native)
        self.assertIn("frame(maxHeight: 280)", native)
        self.assertIn("let isCurrent = segment.index == currentIndex", native)
        self.assertIn('Text("EVENT \\(event.type ?? "—")', native)

    def test_debug_exposes_shadow_section_character_without_a_confidence_rejection(self):
        backend = (ROOT / "beatbeam_app.py").read_text(encoding="utf-8")
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn("def shadow_section_character_at", backend)
        self.assertIn("project(state, include_shadow=True)", backend)
        self.assertIn('debugDisclosure("SHADOW ANALYSE · SECTION CHARACTER"', native)
        self.assertIn("let shadowSectionCharacter: DebugShadowSectionCharacter?", native)
        self.assertIn("struct DebugPreparationProfile: Decodable", native)
        self.assertIn("struct DebugArrivalProfile: Decodable", native)
        self.assertIn("struct DebugStructuralDepartureProfile: Decodable", native)
        self.assertIn('row("PREPARATION", preparationSummary(shadow?.preparationProfile))', native)
        self.assertIn('row("ARRIVAL", arrivalSummary(shadow?.arrivalProfile))', native)
        self.assertIn('row("Build momentum"', native)
        self.assertIn('row("Relative energy"', native)
        self.assertIn('row("Energy rise"', native)
        self.assertIn('shadowBoundaryTransition', native)
        self.assertIn('"nog niet gekalibreerd"', native)

    def test_debug_exposes_boundary_first_shadow_event_evidence_without_event_labels(self):
        backend = (ROOT / "beatbeam_app.py").read_text(encoding="utf-8")
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn("class SongAnalyzerShadowEventEvidence", backend)
        self.assertIn("def shadow_event_evidence_for_destination", backend)
        self.assertIn('"event_evidence"', backend)
        self.assertIn('debugDisclosure("SHADOW EVENT EVIDENCE"', native)
        self.assertIn("let shadowEventEvidence: DebugShadowEventEvidence?", native)
        self.assertIn("struct DebugShadowArrangementIdentityAspect: Decodable", native)
        self.assertIn("struct DebugShadowStructuralDepartureAspect: Decodable", native)
        self.assertIn("arrangementIdentitySummary", native)
        self.assertIn("destinationIsTerminal", native)
        self.assertIn('row("Destination terminal"', native)
        self.assertIn("struct DebugShadowEventHypothesis: Decodable", native)
        self.assertIn("shadowHypothesesSummary", native)
        self.assertIn("class SongAnalyzerBoundaryTemporalContext", backend)
        self.assertIn('"temporal_context"', backend)
        self.assertIn("struct DebugBoundaryTemporalContext: Decodable", native)
        self.assertIn("struct DebugBoundaryTemporalWindow: Decodable", native)
        self.assertIn('row("RMS pre → post"', native)
        self.assertIn('row("Relative energy late-origin → early-destination"', native)
        self.assertIn('row("Energy window"', native)
        self.assertIn("temporalRmsSummary", native)
        self.assertIn("temporalRelativeEnergySummary", native)
        self.assertIn("temporalWindowSummary", native)
        self.assertNotIn("DROP_CANDIDATE", backend)
        self.assertNotIn("BUILD_CANDIDATE", backend)

    def test_debug_uses_independent_persistent_disclosure_groups(self):
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        for title in ("LIVE / VIRTUALDJ", "CANONICAL ANALYSE", "RICH MUSICAL EVENTS",
                      "SHADOW ANALYSE · SECTION CHARACTER", "SHADOW EVENT EVIDENCE", "QUEUE / CACHE / PLAYLIST",
                      "FAILURES", "HANDOFF / BEATBEAM", "LEGACY / NATIVE DIAGNOSTICS"):
            self.assertIn(f'debugDisclosure("{title}"', native)
        self.assertIn('@AppStorage("beatbeam.debug.liveExpanded")', native)
        self.assertIn('@AppStorage("beatbeam.debug.shadowExpanded")', native)
        self.assertIn('@AppStorage("beatbeam.debug.shadowEventEvidenceExpanded")', native)
        self.assertIn('@AppStorage("beatbeam.debug.queueExpanded")', native)

    def test_debug_shadow_group_exposes_sorted_full_ephemeral_structure(self):
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn('Volledige shadowstructuur (\\(allShadow.count))', native)
        self.assertIn('sorted {', native)
        self.assertIn('shadowObservationRow', native)
        self.assertIn('shadowValue(observation.recurrenceStrength) ?? "—"', native)
        self.assertIn('Boundary novelty', native)
        self.assertIn('barCountText(observation)', native)
        self.assertIn('structuralDepartureSummary(observation.entryStructuralDeparture)', native)
        self.assertIn('preparationSummary(observation.preparationProfile)', native)
        self.assertIn('arrivalSummary(observation.arrivalProfile)', native)
        self.assertIn('signed(observation.energyRise)', native)
        self.assertNotIn('structuralNovelty', native)
        self.assertIn('· bars \\(barRange(observation)) · \\(barCountText(observation))', native)
        self.assertIn('"actueel"', native)
        self.assertIn('@AppStorage("beatbeam.debug.fullShadowExpanded")', native)

    def test_bundled_backend_disables_runtime_bytecode_writes(self):
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn('environment["PYTHONDONTWRITEBYTECODE"] = "1"', native)

    def test_native_auto_show_separates_production_and_preview_cues(self):
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn('MetricTile(title: "Cue", value: model.autoShowCueText)', native)
        self.assertIn('Text("PREVIEW CUE")', native)
        self.assertIn('"DYNAMIC COMPOSER"', native)
        self.assertIn('Text("MUSICAL STATE")', native)
        self.assertIn('Text("RME MODIFIER · \\(preview.event?.type ?? "None")")', native)
        self.assertIn('Text("EVENT ENVELOPE · \\(previewEventEnvelope(preview))")', native)
        self.assertIn('@Published var previewComposition: PreviewCompositionState?', native)
        self.assertIn('previewComposition = state.dmx.rmePreviewDifferential', native)
        self.assertIn('let previewSource: String?', native)
        self.assertIn('let dynamicCompositionApplied: Bool?', native)

    def test_native_preview_decoder_is_tolerant_of_nested_primitive_payloads(self):
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn("enum PreviewPrimitiveValue: Decodable", native)
        self.assertIn("case object([String: PreviewPrimitiveValue])", native)
        self.assertIn("case array([PreviewPrimitiveValue])", native)
        self.assertIn("[String: [String: PreviewPrimitiveValue]]", native)
        self.assertIn("parameters (\\(values.count))", native)

    def test_debug_force_reanalysis_is_explicit_and_not_an_auto_show_path(self):
        backend = (ROOT / "beatbeam_app.py").read_text(encoding="utf-8")
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn("def force_reanalyze_active_song_analyzer_track", backend)
        self.assertIn('"type": "forceReanalyze"', backend)
        self.assertIn('client.connect(str(DEFAULT_SONG_ANALYZER_BRIDGE_SOCKET_PATH))', backend)
        self.assertIn('"/api/developer/force-reanalyze-active-track"', backend)
        self.assertIn('Button("Actieve track heranalyseren")', native)
        self.assertIn("forceReanalysisInFlight", native)


if __name__ == "__main__":
    unittest.main()
