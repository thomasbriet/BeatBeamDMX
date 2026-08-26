import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LiveShowUxTests(unittest.TestCase):
    def setUp(self):
        self.native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.live = (ROOT / "native" / "LiveShowUX.swift").read_text(encoding="utf-8")
        self.backend = (ROOT / "beatbeam_app.py").read_text(encoding="utf-8")

    def test_live_show_has_operational_hierarchy_and_keeps_raw_diagnostics_advanced(self):
        for text in (
            'PanelSurface(title: "Live Show"',
            '"NOW PLAYING / MASTER"',
            'PanelSurface(title: "Decks"',
            'PanelSurface(title: "Musical State"',
            'PanelSurface(title: "Current Event"',
            'PanelSurface(title: "Dynamic Composer"',
            'PanelSurface(title: "Fixture Groups"',
            'PanelSurface(title: "Manual / Safety"',
        ):
            self.assertIn(text, self.live)
        self.assertIn('case advanced = "Advanced"', self.native)
        self.assertIn('DebugInspectorView()', self.live)

    def test_live_show_deck_cards_use_existing_typed_authority_and_readiness_fields(self):
        for text in (
            'let isMaster: Bool?',
            'let isActive: Bool?',
            'let prewarmStatus: String?',
            'let analysisStatus: String?',
            'let isPlaying: Bool?',
            'liveAnalysisState(deck)',
        ):
            self.assertIn(text, self.native + self.live)
        self.assertIn('"is_playing": bool(raw.get("is_playing"))', self.backend)

    def test_normal_baseline_and_no_rme_are_not_presented_as_errors(self):
        self.assertIn('value == "existing_autoshow" ? "BASELINE"', self.live)
        self.assertIn('"No current musical event. Continuous state remains active."', self.live)
        self.assertNotIn('fallback_reason', self.live)

    def test_preview_remains_explicit_and_non_authoritative(self):
        self.assertIn('"Preview controls and the fixture map are non-authoritative.', self.live)
        self.assertIn('AutoShowControlView()', self.live)
        live_show_section = self.live[self.live.index('struct LiveShowWorkspaceView'):self.live.index('// MARK: - Preview and advanced workspaces')]
        self.assertNotIn('Pulse Test (Preview only)', live_show_section)
        self.assertIn('"auto_show -> current_values"', self.native)

    def test_manual_and_physical_state_remain_visible_without_new_control_engine(self):
        self.assertIn('model.blackout()', self.live)
        self.assertIn('"MANUAL OVERRIDE ACTIVE"', self.live)
        self.assertIn('"PHYSICAL DISCONNECTED"', self.live)
        self.assertIn('Preview remains usable', self.live)

    def test_live_presentation_does_not_introduce_a_second_backend_or_production_selector(self):
        self.assertNotIn('URLSession', self.live)
        self.assertNotIn('select_production_show_source', self.live)
        self.assertNotIn('DYNAMIC_COMPOSER_ENABLED', self.live)


if __name__ == "__main__":
    unittest.main()
