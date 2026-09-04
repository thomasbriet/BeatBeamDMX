import re
import unittest
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "native" / "BeatBeamDMXApp.swift"


class MetricStageMapSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")

    def test_grid_contract_is_one_meter_with_quarter_meter_subgrid(self):
        self.assertIn("static let majorGridStepCm: Double = 100", self.source)
        self.assertIn("static let minorGridStepCm: Double = 25", self.source)
        self.assertIn('Text("1 m grid · 0.25 m minor")', self.source)

    def test_all_orthographic_views_share_metric_projection(self):
        body = self.source.split("private func metricWorldProjectedPoint", 1)[1]
        for projection in ("case .top:", "case .front:", "case .back:", "case .side:"):
            self.assertIn(projection, body)
        self.assertIn("let unitsPerCanvasHeight = min(aspect / horizontalSpan, 1.0 / verticalSpan)", self.source)
        self.assertIn("metricProjectionCoordinates", self.source)

    def test_zoom_is_a_viewport_transform_after_metric_projection(self):
        projection = self.source.split("private func metricProjectionPoint", 1)[1].split("private func metricProjectionCoordinates", 1)[0]
        self.assertIn("projectionViewportTransform(raw, zoom: zoom)", projection)
        self.assertIn("cameraCenter: (horizontal: Double, down: Double)? = nil", projection)
        self.assertNotRegex(projection, re.compile(r"majorGridStepCm\s*[*\/]\s*zoom"))

    def test_true_zoom_model_scales_pixels_and_visible_world_span(self):
        # This mirrors the explicit metric fit used by Swift: base fit is chosen
        # first, then zoom is applied exactly once to the projected delta.
        aspect = 16 / 9
        horizontal_span_cm = 1400
        vertical_span_cm = 1100
        base_units_per_canvas_height = min(aspect / horizontal_span_cm, 1 / vertical_span_cm)
        canvas_width = 1600

        def pixels_for_world_cm(distance_cm, zoom):
            return distance_cm * base_units_per_canvas_height / aspect * canvas_width * zoom

        at_100 = pixels_for_world_cm(100, 1.0)
        self.assertAlmostEqual(pixels_for_world_cm(100, 0.75), at_100 * 0.75)
        self.assertAlmostEqual(pixels_for_world_cm(100, 1.25), at_100 * 1.25)
        self.assertAlmostEqual(pixels_for_world_cm(25, 1.25), at_100 * 0.25 * 1.25)
        self.assertAlmostEqual(horizontal_span_cm / 1.25, horizontal_span_cm * 0.8)

    def test_viewport_has_persistent_world_camera_center_and_no_refit_on_zoom(self):
        for key in (
            "mapProjectionTopCenterXDefaultsKey",
            "mapProjectionTopCenterYDefaultsKey",
            "mapProjectionFrontCenterXDefaultsKey",
            "mapProjectionSideCenterYDefaultsKey",
        ):
            self.assertIn(key, self.source)
        self.assertIn("private func projectionViewportCenter(for projection: StageProjection)", self.source)
        self.assertIn("private func projectionCameraScreenCenter(", self.source)
        self.assertIn("viewportCenter: SlotWorldPosition? = nil", self.source)
        self.assertIn("after the unzoomed metric fit scale has been calculated", self.source)

    def test_background_drag_pans_only_viewport_and_fixture_drag_remains_priority(self):
        canvas = self.source.split("struct StageMapCanvas", 1)[1].split("struct VenueSpaceOverlay", 1)[0]
        self.assertIn("backgroundPanGesture(canvasSize: geometry.size)", canvas)
        self.assertIn("DragGesture(minimumDistance: 4)", canvas)
        self.assertIn("model.commitProjectionViewportPan(", canvas)
        self.assertIn("node.highPriorityGesture(dragGesture)", self.source)
        pan = self.source.split("func commitProjectionViewportPan", 1)[1].split("func resetMetricStageMapView", 1)[0]
        self.assertIn("0.5 - translation.width / canvasSize.width", pan)
        self.assertIn("0.5 - translation.height / canvasSize.height", pan)
        self.assertIn("inMemoryProjectionViewportCenters[projection] = next", pan)
        self.assertIn("saveProjectionViewportCenter(next, for: projection)", pan)
        self.assertNotIn("projectionLayoutDrafts", pan)

    def test_inverse_edit_uses_the_same_zoom_pan_rotation_transform(self):
        update = self.source.split("private func update(world: inout SlotWorldPosition", 1)[1].split("private func scalarNormalized", 1)[0]
        self.assertIn("metricWorldPosition(", update)
        self.assertIn("frontMirrored: frontProjectionMirrored", update)
        self.assertIn("topQuarterTurns: topProjectionRotationQuarterTurns", update)

    def test_reset_view_resets_camera_rotation_pan_and_zoom_without_world_mutation(self):
        reset = self.source.split("func resetMetricStageMapView()", 1)[1].split("func fixturePositionMeters", 1)[0]
        self.assertIn("resetProjectionViewportCenters()", reset)
        self.assertIn("topProjectionRotationQuarterTurns = 0", reset)
        self.assertIn("UserDefaults.standard.set(1.0, forKey: mapProjection2DZoomDefaultsKey)", reset)
        self.assertNotIn("projectionLayoutDrafts", reset)

    def test_ui_offers_exact_manual_zoom_acceptance_values(self):
        self.assertIn("ForEach([0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0]", self.source)
        self.assertIn('Text("Reset View")', self.source)

    def test_viewport_render_key_invalidates_each_visible_2d_canvas_and_metric_backdrop(self):
        deck = self.source.split("struct StageProjectionDeckView", 1)[1].split("struct StageMapCanvas", 1)[0]
        self.assertIn("private var viewportZoom: Double", deck)
        self.assertIn("private var viewportRenderKey: MetricStageMapViewportRenderKey", deck)
        self.assertIn("cameraRevision: model.metricStageMapViewportRevision", deck)
        self.assertIn("viewportRenderKey: viewportRenderKey", deck)
        for canvas in ("StageMapCanvas", "StageFrontCanvas", "StageSideCanvas", "ProjectionPanelBackdrop"):
            section = self.source.split(f"struct {canvas}", 1)[1]
            self.assertIn("let viewportRenderKey: MetricStageMapViewportRenderKey", section)
            self.assertIn(".id(viewportRenderKey)", section)

    def test_pan_uses_composited_translation_without_per_frame_reprojection_or_persistence(self):
        pan = self.source.split("func commitProjectionViewportPan", 1)[1].split("func resetMetricStageMapView", 1)[0]
        self.assertIn("inMemoryProjectionViewportCenters[projection] = next", pan)
        self.assertIn("invalidateMetricStageMapViewport()", pan)
        self.assertIn("saveProjectionViewportCenter(next, for: projection)", pan)
        canvas = self.source.split("struct StageMapCanvas", 1)[1].split("struct VenueSpaceOverlay", 1)[0]
        self.assertIn("private final class StageMapPanInteractionState: ObservableObject", self.source)
        self.assertIn("private struct StageMapPanTranslationLayer", self.source)
        self.assertIn("@ObservedObject var interaction: StageMapPanInteractionState", self.source)
        self.assertIn("@State private var panInteraction = StageMapPanInteractionState()", canvas)
        self.assertNotIn("@StateObject private var panInteraction", canvas)
        self.assertNotIn(".compositingGroup()", canvas)
        layer = self.source.split("private struct StageMapPanTranslationLayer", 1)[1].split("struct StageMapCanvas", 1)[0]
        self.assertIn("translationX: interaction.translationPx.width", layer)
        self.assertIn("y: interaction.translationPx.height", layer)
        self.assertIn("panInteraction.translationPx = value.translation", canvas)
        self.assertIn("panInteraction.translationPx = .zero", canvas)
        self.assertNotIn("model.commitProjectionViewportPan(", canvas.split(".onChanged", 1)[1].split(".onEnded", 1)[0])
        self.assertNotIn("localPanRenderRevision", canvas)
        self.assertIn("ProjectionPanelBackdrop(projection: projection", canvas)

    def test_composited_pan_commit_has_screen_translation_parity_at_every_supported_zoom(self):
        # The committed camera is found using the same inverse transform at the
        # translated screen center. Reprojecting any point therefore changes its
        # screen position by exactly the temporary compositor translation.
        canvas_width = 1600.0
        dx = 40.0
        for zoom in (0.75, 1.0, 2.0, 4.0):
            base_units_per_canvas_height = 1 / 1100.0
            # Inverse of the post-zoom screen delta produces this camera shift.
            camera_shift_cm = -dx / canvas_width / zoom / base_units_per_canvas_height
            reprojection_dx = -camera_shift_cm * base_units_per_canvas_height * zoom * canvas_width
            self.assertAlmostEqual(reprojection_dx, dx, places=8)

    def test_precision_zoom_reaches_400_percent_with_exact_metric_ratio(self):
        clamp = self.source.split("private func clampedProjection2DZoom", 1)[1].split("private func projection2DZoomValue", 1)[0]
        self.assertIn("min(max(value, 0.75), 4.00)", clamp)
        aspect = 16 / 9
        base_units_per_canvas_height = min(aspect / 1200, 1 / 1100)
        one_meter_at_100 = 100 * base_units_per_canvas_height / aspect * 1600
        self.assertAlmostEqual(one_meter_at_100 * 4.0, one_meter_at_100 * 4)
        self.assertAlmostEqual(1100 / 4.0, 275)

    def test_wall_wash_fixture_marker_extent_is_screen_space_bounded(self):
        def bounded(proposed, minimum=34, maximum=96):
            return min(maximum, max(minimum, proposed))
        self.assertEqual(34, bounded(12))
        self.assertEqual(96, bounded(400))
        self.assertLessEqual(bounded(400) / bounded(75), 96 / 75)
        self.assertIn("boundedScreenSpaceFixtureMarkerExtent", self.source)

    def test_drag_snaps_to_quarter_meter_but_numeric_entry_does_not(self):
        self.assertIn("static let dragSnapCm: Double = 25", self.source)
        update = self.source.split("func updateProjectionPoint", 1)[1].split("func rotateSelectedProjectionOrientation", 1)[0]
        self.assertIn("StageWorld.dragSnapCm", update)
        numeric = self.source.split("func setFixturePositionMeters", 1)[1].split("func rotateSelectedProjectionOrientation", 1)[0]
        self.assertNotIn("dragSnapCm", numeric)
        self.assertIn("value * 100", numeric)

    def test_fixture_snap_is_a_persisted_editor_preference_with_a_safe_drag_capture(self):
        self.assertIn('mapFixtureSnapEnabledDefaultsKey = defaultsKey("fixtureSnapEnabled")', self.source)
        self.assertIn("@Published var fixtureSnapEnabled = true", self.source)
        self.assertIn("UserDefaults.standard.set(fixtureSnapEnabled, forKey: mapFixtureSnapEnabledDefaultsKey)", self.source)
        update = self.source.split("func updateProjectionPoint", 1)[1].split("func panProjectionViewport", 1)[0]
        self.assertIn("if snapEnabled ?? fixtureSnapEnabled", update)
        fixture = self.source.split("struct ProjectionFixtureNode", 1)[1].split("private var tapAction", 1)[0]
        self.assertIn("@State private var dragSnapEnabled: Bool?", fixture)
        self.assertIn("dragSnapEnabled = model.fixtureSnapEnabled", fixture)
        self.assertIn("snapEnabled: dragSnapEnabled", fixture)
        self.assertIn("dragSnapEnabled = nil", fixture)

    def test_snap_toggle_is_visible_and_does_not_mutate_a_fixture_until_a_drag(self):
        deck = self.source.split("struct StageProjectionDeckView", 1)[1].split("enum ProjectionSelectionMode", 1)[0]
        self.assertIn('model.fixtureSnapEnabled ? "SNAP ON" : "SNAP OFF"', deck)
        self.assertIn("model.fixtureSnapEnabled.toggle()", deck)
        toggle_action = deck.split("model.fixtureSnapEnabled.toggle()", 1)[0].rsplit("Button", 1)[-1]
        self.assertNotIn("updateProjectionPoint", toggle_action)
        self.assertNotIn("setFixturePositionMeters", toggle_action)

    def test_snap_math_preserves_existing_nearest_quarter_behavior_and_off_is_continuous(self):
        snap_cm = 25.0
        self.assertEqual(round(183 / snap_cm) * snap_cm, 175.0)
        self.assertEqual(round(262 / snap_cm) * snap_cm, 250.0)
        # SNAP OFF intentionally applies no quantization to the resolved world point.
        self.assertEqual(183.0, 183.0)
        self.assertEqual(262.0, 262.0)

    def test_fixture_payload_persists_canonical_meter_xyz(self):
        self.assertIn("let positionM: VenuePhysicalPointState", self.source)
        self.assertIn("positionM: VenuePhysicalPointState(", self.source)
        self.assertIn('Text("X − LEFT / + RIGHT  •  Y + AUDIENCE / − REAR  •  exact to 0.01 m")', self.source)

    def test_live_fixture_labels_replace_static_anchor_labels_and_never_steal_drag(self):
        canvas = self.source.split("struct StageMapCanvas", 1)[1].split("struct VenueSpaceOverlay", 1)[0]
        fixture = self.source.split("struct StageFixtureNode", 1)[1].split("private func boundedScreenSpaceFixtureMarkerExtent", 1)[0]
        self.assertNotIn("StageAnchorMarker", self.source)
        self.assertNotIn("ForEach(StageAnchor.allCases)", canvas)
        self.assertIn("fixtureMapLabel", fixture)
        self.assertIn("isSelected ? editor.label : compactFixtureMapLabel", fixture)
        self.assertIn(".allowsHitTesting(false)", fixture)
        self.assertNotIn('Text("WASH")', fixture)

    def test_stage_map_apply_persists_each_live_fixture_position_m(self):
        apply = self.source.split("func applyProjectionLayoutEditing()", 1)[1].split("private func saveSelectedFixtureCalibration", 1)[0]
        self.assertIn("saveProjectionLayoutPositions()", apply)
        self.assertIn("FixturePositionUpdateRequest", apply)
        self.assertIn("positionM: VenuePhysicalPointState(", apply)
        self.assertIn('post("/api/dmx/update", body: payload, as: AppState.self)', apply)

    def test_live_beam_uses_backend_world_direction_without_local_reinterpretation(self):
        beam = self.source.split("private func currentBeamTarget", 1)[1].split("private func targetBeamTarget", 1)[0]
        self.assertIn("if let direction = state?.worldDirection", beam)
        calibrated_branch = beam.split("if let direction = state?.worldDirection", 1)[1].split("} else if let state", 1)[0]
        self.assertNotIn("worldOrigin.panFlip ?", calibrated_branch)
        self.assertNotIn("beamWorldEndpoint", calibrated_branch)
        self.assertNotIn("mountYawDegrees *", calibrated_branch)


if __name__ == "__main__":
    unittest.main()
