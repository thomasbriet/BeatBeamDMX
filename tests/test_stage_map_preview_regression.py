import copy
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import beatbeam_app as beatbeam


ROOT = Path(__file__).resolve().parents[1]


class StageMapPreviewRegressionTests(unittest.TestCase):
    @staticmethod
    def ready_controller():
        osc = MagicMock()
        osc.snapshot_for_render.return_value = {
            "phrase_current": "verse", "stale": False, "beat_value": 0.0,
        }
        controller = beatbeam.DmxController(osc)
        controller._schedule_save_locked = lambda: None
        controller.config = controller.default_config()
        controller.config = controller._merge_payload({"venue_geometry": {
            "venue_width_m": 6.0,
            "venue_forward_depth_m": 8.0,
            "venue_rear_depth_m": 0.5,
            "audience_target_height_m": 1.0,
            "ceiling_height_m": 3.0,
        }})
        first = controller.config["slot_order"][0]
        second = "preview_head_2"
        controller.config["slots"][second] = copy.deepcopy(controller.config["slots"][first])
        controller.config["slots"][second]["address"] = 60
        controller.config["slots"][second]["label"] = "Preview Head 2"
        controller.config["slot_order"].append(second)
        for slot_id, x in ((first, -2.0), (second, 2.0)):
            controller.config["slots"][slot_id]["venue_calibration"] = {
                "version": 4,
                "position_m": {"x": x, "y": 0.0, "z": 2.8},
                "position": {"x": x / 5.0, "y": 0.0},
                "mounting_height_m": 2.8,
                "physical_forward": {"x": 0, "y": 1, "z": 0},
                "physical_up": {"x": 0, "y": 0, "z": 1},
            }
        controller.render_active = True
        controller.renderer_error = None
        controller.connected = False
        controller.dmx = None
        return controller, first, second

    def test_test_all_preview_is_backend_authoritative_without_dmx(self):
        controller, first, second = self.ready_controller()

        response = controller.activate_venue_target_preview_test({"target": "AUDIENCE_MID_CENTER"})

        self.assertTrue(response["accepted"])
        authority = response["authority"]
        self.assertTrue(authority["active"])
        self.assertEqual("VENUE_TARGET_PREVIEW", authority["mode"])
        self.assertEqual({first, second}, set(authority["participating_fixture_ids"]))
        participants = controller.venue_target_test_authority["participants"]
        self.assertEqual(
            participants[first]["target_xyz_m"], participants[second]["target_xyz_m"],
        )
        self.assertEqual({"x": 0.0, "y": 4.4, "z": 1.0}, participants[first]["target_xyz_m"])
        self.assertNotEqual(
            (participants[first]["predicted_output"]["pan"], participants[first]["predicted_output"].get("pan_fine")),
            (participants[second]["predicted_output"]["pan"], participants[second]["predicted_output"].get("pan_fine")),
        )

        rendered = controller._render_values(time.time())
        controller.current_final_values = rendered
        state = controller.state()
        self.assertTrue(state["venue_target_test"]["active"])
        self.assertEqual("VENUE_TARGET_PREVIEW", state["venue_target_test"]["mode"])
        self.assertIn(first, state["rendered_motion"])
        self.assertIn(second, state["rendered_motion"])
        self.assertTrue(controller.renew_venue_target_test({})["accepted"])
        self.assertTrue(controller.release_venue_target_test()["accepted"])
        self.assertFalse(controller.state()["venue_target_test"]["active"])

    def test_vertical_layers_share_preview_authority_and_preserve_lease_selection(self):
        expected = {"FLOOR": 0.0, "NORMAL": 1.0, "CEILING": 3.0}
        for layer, z in expected.items():
            controller, first, second = self.ready_controller()
            response = controller.activate_venue_target_preview_test({
                "target": "AUDIENCE_MID_CENTER", "vertical_layer": layer,
            })
            self.assertTrue(response["accepted"])
            authority = response["authority"]
            self.assertEqual(layer, authority["vertical_layer"])
            self.assertEqual(layer, authority["result_set"]["vertical_layer"])
            participants = controller.venue_target_test_authority["participants"]
            self.assertEqual({"x": 0.0, "y": 4.4, "z": z}, participants[first]["target_xyz_m"])
            self.assertEqual(participants[first]["target_xyz_m"], participants[second]["target_xyz_m"])
            controller.current_final_values = controller._render_values(time.time())
            refreshed = controller.state()["venue_target_test"]
            self.assertEqual(layer, refreshed["vertical_layer"])
            self.assertIn(first, controller.state()["rendered_motion"])
            self.assertTrue(controller.release_venue_target_test()["accepted"])

    def test_ceiling_preview_is_rejected_when_height_is_unset(self):
        controller, _, _ = self.ready_controller()
        controller.config["venue_geometry"].pop("ceiling_height_m")
        response = controller.activate_venue_target_preview_test({
            "target": "AUDIENCE_MID_CENTER", "vertical_layer": "CEILING",
        })
        self.assertFalse(response["accepted"])
        self.assertEqual("CEILING_UNAVAILABLE", response["status"])

    def test_each_target_depth_uses_the_backend_preview_authority_without_dmx(self):
        expected_y = {
            "AUDIENCE_NEAR_CENTER": 1.6,
            "AUDIENCE_MID_CENTER": 4.4,
            "AUDIENCE_FAR_CENTER": 7.2,
            "REAR_CENTER": -0.5,
        }
        for target_id, y in expected_y.items():
            controller, first, second = self.ready_controller()
            response = controller.activate_venue_target_preview_test({"target": target_id})
            self.assertTrue(response["accepted"])
            participants = controller.venue_target_test_authority["participants"]
            self.assertEqual({"x": 0.0, "y": y, "z": 1.0}, participants[first]["target_xyz_m"])
            self.assertEqual(participants[first]["target_xyz_m"], participants[second]["target_xyz_m"])
            rendered = controller._render_values(time.time())
            controller.current_final_values = rendered
            state = controller.state()
            self.assertEqual("VENUE_TARGET_PREVIEW", state["venue_target_test"]["mode"])
            self.assertIn(first, state["rendered_motion"])
            self.assertIn(second, state["rendered_motion"])

    def test_open_preview_reconnects_existing_3d_deck_controls(self):
        source = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        window = source.split("struct MapPreviewWindowView", 1)[1].split("struct StageFixtureBeam", 1)[0]
        self.assertIn("StageProjectionDeckView(", window)
        self.assertIn("showControls: true", window)
        deck = source.split("struct StageProjectionDeckView", 1)[1].split("struct StageFixtureBeam", 1)[0]
        self.assertIn('Text("3D")', deck)
        self.assertIn("Stage3DPreviewView()", deck)

    def test_native_test_all_dispatches_the_backend_preview_authority(self):
        source = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        action = source.split("func testAllMovingHeadsInPreview()", 1)[1].split("func testAudienceCenterForSelectedFixture", 1)[0]
        self.assertIn('"/api/dmx/venue-target-preview"', action)
        self.assertIn("startVenueTargetLeaseHeartbeat()", action)
        self.assertNotIn('"/api/dmx/venue-target-test"', action)

    def test_native_vertical_layer_controls_share_the_backend_contract(self):
        source = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn('let ceilingHeightM: Double?', source)
        self.assertIn('geometryField("CEILING HEIGHT", unit: "m", text: $model.ceilingHeightMetersText)', source)
        self.assertIn('ForEach(["FLOOR", "NORMAL", "CEILING"] as [String]', source)
        self.assertIn('verticalLayer: selectedVenueTargetVerticalLayer', source)
        self.assertIn('CEILING UNAVAILABLE', source)

    def test_native_physical_tilt_limits_stay_in_fixture_calibration_only(self):
        source = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        fixture_panel = source.split("struct FixtureVenueCalibrationPanel", 1)[1].split("struct VenueGeometryPanel", 1)[0]
        self.assertIn('Text("PHYSICAL MOVEMENT LIMITS")', fixture_panel)
        self.assertIn('physicalTiltField("TILT MIN"', fixture_panel)
        self.assertIn('physicalTiltField("TILT CENTER"', fixture_panel)
        self.assertIn('physicalTiltField("TILT MAX"', fixture_panel)
        self.assertIn('savePhysicalTiltLimits(', fixture_panel)
        self.assertIn('physicalTiltLimits: PhysicalTiltLimitsPayload', source)


if __name__ == "__main__":
    unittest.main()
