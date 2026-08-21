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
        self.assertIn('debugCard("Native VDJ Plugin")', native)
        self.assertIn('row("Plugin deck"', native)
        self.assertIn('row("Selection reason"', native)
        self.assertIn('row("Send result"', native)

    def test_debug_window_exposes_optional_bridge_control_telemetry(self):
        native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn("let control: DebugBridgeControl?", native)
        self.assertIn('debugCard("Bridge Control")', native)
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


if __name__ == "__main__":
    unittest.main()
