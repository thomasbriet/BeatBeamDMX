import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UiCleanupNavigationV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        cls.live = (ROOT / "native" / "LiveShowUX.swift").read_text(encoding="utf-8")

    def test_primary_navigation_contains_exactly_the_four_product_surfaces(self):
        workspace = self.native[
            self.native.index("private enum WorkspaceMode"):
            self.native.index("private enum UtilityPanel")
        ]
        self.assertEqual(
            [
                'case live = "Live Show"',
                'case preview = "Stage Map"',
                'case manual = "Manual"',
                'case advanced = "Advanced"',
            ],
            [line.strip() for line in workspace.splitlines() if line.strip().startswith("case ")],
        )

    def test_advanced_preserves_moved_surfaces_without_a_duplicate_map(self):
        advanced = self.live[
            self.live.index("struct AdvancedOperationsWorkspaceView"):
            self.live.index("// MARK: - Small presentation building blocks")
        ]
        for value in ('case showConfiguration = "Show Configuration"', 'case simulator = "Simulator"',
                      'case fixtureDiagnostics = "Fixture Diagnostics"', 'case developer = "Developer"',
                      'AutoShowWorkspaceView()', 'SimulatorWorkspaceView()',
                      'PreviewPulseTestPanel()', 'MovementLabPanel()', 'DebugInspectorView()'):
            self.assertIn(value, advanced)
        self.assertNotIn('case map = "Map"', advanced)
        self.assertNotIn('MapWorkspaceView()', advanced)

    def test_stage_map_remains_the_only_map_and_keeps_physical_setup(self):
        map_workspace = self.native[
            self.native.index("struct MapWorkspaceView"):
            self.native.index("private struct StageMapResizableSplitView")
        ]
        for value in ('VenueManagementPanel()', 'VenueGeometryPanel()',
                      'FixtureVenueCalibrationPanel()', 'VenueTargetTestPanel()',
                      'Button("Open Preview")'):
            self.assertIn(value, map_workspace)
        self.assertNotIn('MovementLabPanel()', map_workspace)

    def test_preview_pulse_test_is_developer_only_and_keeps_existing_action(self):
        auto_show = self.native[
            self.native.index("struct AutoShowControlView"):
            self.native.index("struct PreviewPulseTestPanel")
        ]
        self.assertNotIn('Pulse Test (Preview only)', auto_show)
        pulse_panel = self.native[
            self.native.index("struct PreviewPulseTestPanel"):
            self.native.index("struct LiveOverrideColorButton")
        ]
        self.assertIn('Picker("Pulse Test (Preview only)"', pulse_panel)
        self.assertIn('model.setPreviewPulseTestMode($0)', pulse_panel)


if __name__ == "__main__":
    unittest.main()
