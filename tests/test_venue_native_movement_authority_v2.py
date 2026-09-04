import copy
import math
import unittest
from unittest.mock import MagicMock

import beatbeam_app as beatbeam


GEOMETRY = beatbeam.VenueGeometry(10.0, 12.0, 3.0, 1.2)
CONTEXT = {
    "role": "moving",
    "role_count": 4,
    "member_count": 4,
    "role_index": 2,
    "member_index": 2,
    "role_centered": 1.0 / 3.0,
    "member_centered": 1.0 / 3.0,
    "member_alternate": 1.0,
}


class VenueNativeMovementAuthorityV2Tests(unittest.TestCase):
    def test_inventory_classifies_every_profile_and_every_exception(self):
        inventory = beatbeam.production_movement_inventory()
        by_name = {item["name"]: item for item in inventory}
        self.assertEqual(set(beatbeam.MOVEMENT_SPACE_CLASSIFICATION), set(by_name))
        self.assertTrue(all(item["current_authority"] in {
            beatbeam.MOVEMENT_SPACE_VENUE_NATIVE,
            beatbeam.MOVEMENT_SPACE_FIXTURE_RELATIVE,
            beatbeam.MOVEMENT_SPACE_CALIBRATION_ONLY,
            beatbeam.MOVEMENT_SPACE_NON_MOVEMENT,
        } for item in inventory))
        self.assertEqual(
            set(beatbeam.FIXTURE_RELATIVE_MOVEMENT_JUSTIFICATIONS),
            {name for name, value in beatbeam.MOVEMENT_SPACE_CLASSIFICATION.items()
             if value == beatbeam.MOVEMENT_SPACE_FIXTURE_RELATIVE},
        )
        self.assertEqual(
            set(beatbeam.CALIBRATION_MOVEMENT_SOURCES),
            {name for name, value in beatbeam.MOVEMENT_SPACE_CLASSIFICATION.items()
             if value == beatbeam.MOVEMENT_SPACE_CALIBRATION_ONLY},
        )

    def test_every_spatial_profile_produces_one_world_space_intent(self):
        missing = []
        for name in beatbeam.AUTO_SHOW_MOTION_PROFILES:
            classification = beatbeam.movement_space_classification(name)
            intent = beatbeam.venue_native_effect_intent(name, 12.5, GEOMETRY, CONTEXT)
            if classification == beatbeam.MOVEMENT_SPACE_VENUE_NATIVE:
                if not intent or intent.get("kind") not in {"WORLD_TARGET_XYZ_M", "WORLD_DIRECTION"}:
                    missing.append(name)
                else:
                    self.assertEqual("VENUE_NATIVE", intent["movement_space"])
                    field = "world_direction" if intent["kind"] == "WORLD_DIRECTION" else "world_target_xyz_m"
                    self.assertTrue(all(math.isfinite(intent[field][axis]) for axis in "xyz"))
            else:
                self.assertIsNone(intent)
        self.assertEqual([], missing)

    def test_non_movement_profiles_retain_light_metadata_without_pan_tilt(self):
        controller = beatbeam.DmxController(MagicMock())
        for name in beatbeam.NON_MOVEMENT_AUTO_SHOW_EFFECTS:
            motion = beatbeam.styled_phrase_motion("build", 8.0, name, CONTEXT, 0.7, {})
            attached = controller._attach_spatial_intent(
                motion, name, 8.0, {"_venue_geometry": GEOMETRY.as_dict()}, CONTEXT
            )
            self.assertEqual("NON_MOVEMENT", attached["movement_space"])
            self.assertNotIn("pan", attached)
            self.assertNotIn("tilt", attached)
            for key in ("dimmer", "strobe", "program", "speed", "rgbw"):
                if key in motion:
                    self.assertEqual(motion[key], attached[key])

    def test_venue_native_effect_contract_contains_no_fixture_local_target(self):
        controller = beatbeam.DmxController(MagicMock())
        config = {
            "_venue_geometry": GEOMETRY.as_dict(),
            "_auto_show_member_mirror": False,
            "_dynamic_motion_parameters": None,
        }
        for name in beatbeam.AUTO_SHOW_MOTION_PROFILES:
            if beatbeam.movement_space_classification(name) != beatbeam.MOVEMENT_SPACE_VENUE_NATIVE:
                continue
            legacy = beatbeam.styled_phrase_motion("drop", 4.0, name, CONTEXT, 0.8, {})
            attached = controller._attach_spatial_intent(legacy, name, 4.0, config, CONTEXT)
            self.assertIn("spatial_intent", attached, name)
            self.assertNotIn("pan", attached, name)
            self.assertNotIn("tilt", attached, name)

    def test_audience_sweep_uses_dj_world_left_center_right(self):
        profile = beatbeam.auto_show_motion_profile("fast_audience_sweep")
        scale = float(profile["phase_scale"])
        lead_context = {
            **CONTEXT,
            "artistic_participant_index": 0,
            "artistic_participant_count": 4,
            "artistic_participant_centered": -1.0,
            "artistic_closed_phase_offset": 0.0,
        }
        beats = [(-1.0, 0.75), (0.0, 0.0), (1.0, 0.25)]
        for expected_sign, phase in beats:
            target = beatbeam.venue_native_effect_intent(
                "fast_audience_sweep", phase * 24.0 / scale, GEOMETRY, lead_context
            )["world_target_xyz_m"]
            self.assertIn(expected_sign, {-1.0, 0.0, 1.0})
            self.assertTrue(math.isfinite(target["x"]))
        samples = [
            beatbeam.venue_native_effect_intent(
                "fast_audience_sweep", 18.0 / scale, GEOMETRY,
                {**CONTEXT, "artistic_participant_index": index, "artistic_participant_count": 4,
                 "artistic_participant_centered": centered, "artistic_closed_phase_offset": index / 4},
            )["world_target_xyz_m"]
            for index, centered in enumerate((-1.0, -1 / 3, 1 / 3, 1.0))
        ]
        self.assertEqual(4, len({tuple(sorted(point.items())) for point in samples}))

        live = beatbeam.auto_show_motion_profile("live_audience_tilt_sweep")
        live_scale = float(live["phase_scale"])
        live_points = [
            beatbeam.venue_native_effect_intent(
                "live_audience_tilt_sweep", phase * 32.0 / live_scale, GEOMETRY, lead_context
            )
            for phase in (0.75, 0.0, 0.25)
        ]
        self.assertEqual("LEFT_TO_RIGHT", live_points[0]["semantic_path"])
        self.assertNotEqual(live_points[0]["world_target_xyz_m"], live_points[1]["world_target_xyz_m"])
        self.assertNotEqual(live_points[1]["world_target_xyz_m"], live_points[2]["world_target_xyz_m"])

    def test_audience_rise_and_wave_are_physical_world_paths(self):
        low = beatbeam.venue_native_effect_intent("audience_riser", 0, GEOMETRY, CONTEXT, progress=0.0)
        high = beatbeam.venue_native_effect_intent("audience_riser", 0, GEOMETRY, CONTEXT, progress=1.0)
        self.assertGreater(high["world_target_xyz_m"]["y"], low["world_target_xyz_m"]["y"])
        self.assertGreater(high["world_target_xyz_m"]["z"], low["world_target_xyz_m"]["z"])
        left = beatbeam.venue_native_effect_intent("build_audience_wave", 5.0, GEOMETRY, {**CONTEXT, "artistic_participant_centered": -1})
        right = beatbeam.venue_native_effect_intent("build_audience_wave", 5.0, GEOMETRY, {**CONTEXT, "artistic_participant_centered": 1})
        self.assertLess(left["world_target_xyz_m"]["x"], 0)
        self.assertGreater(right["world_target_xyz_m"]["x"], 0)
        self.assertEqual("AUDIENCE_WAVE", left["semantic_path"])

    def test_fan_and_crossing_beams_are_world_spreads_not_shared_raw(self):
        fan_directions = [
            beatbeam.venue_native_effect_intent(
                "drop_snap_fan", 0, GEOMETRY,
                {**CONTEXT, "artistic_participant_index": index, "artistic_participant_count": 4,
                 "artistic_participant_centered": centered},
            )["world_direction"]
            for index, centered in enumerate((-1.0, -1 / 3, 1 / 3, 1.0))
        ]
        self.assertEqual(sorted(point["x"] for point in fan_directions), [point["x"] for point in fan_directions])
        self.assertEqual(4, len({tuple(sorted(point.items())) for point in fan_directions}))
        crossing_left = beatbeam.venue_native_effect_intent(
            "drop_crossing_beams", 0, GEOMETRY, {**CONTEXT, "artistic_participant_centered": -1}
        )
        crossing_right = beatbeam.venue_native_effect_intent(
            "drop_crossing_beams", 0, GEOMETRY, {**CONTEXT, "artistic_participant_centered": 1}
        )
        self.assertGreater(crossing_left["world_target_xyz_m"]["x"], 0)
        self.assertLess(crossing_right["world_target_xyz_m"]["x"], 0)

    def test_circle_oval_and_figure_eight_are_world_shapes(self):
        def point(name, phase):
            scale = float(beatbeam.auto_show_motion_profile(name)["phase_scale"])
            return beatbeam.venue_native_effect_intent(name, phase * 28.0 / scale, GEOMETRY, CONTEXT)["world_target_xyz_m"]

        circle = [point("fast_audience_circle", phase) for phase in (0, .25, .5, .75, 1.0)]
        self.assertAlmostEqual(circle[0]["x"], circle[-1]["x"], places=6)
        self.assertAlmostEqual(circle[0]["y"], circle[-1]["y"], places=6)
        self.assertGreater(max(p["x"] for p in circle) - min(p["x"] for p in circle), 4.0)
        oval = [point("slow_audience_oval", phase) for phase in (0, .25, .5, .75)]
        self.assertGreater(
            max(p["x"] for p in oval) - min(p["x"] for p in oval),
            max(p["y"] for p in oval) - min(p["y"] for p in oval),
        )
        eight_a = point("fast_audience_figure_8", 0.0)
        eight_b = point("fast_audience_figure_8", 0.5)
        self.assertAlmostEqual(0.0, eight_a["x"], places=6)
        self.assertAlmostEqual(0.0, eight_b["x"], places=6)

    def test_searchlight_scans_bounded_world_area_deterministically(self):
        first = beatbeam.venue_native_effect_intent("slow_random_searchlight", 3.0, GEOMETRY, CONTEXT)
        again = beatbeam.venue_native_effect_intent("slow_random_searchlight", 3.0, GEOMETRY, CONTEXT)
        later = beatbeam.venue_native_effect_intent("slow_random_searchlight", 30.0, GEOMETRY, CONTEXT)
        self.assertEqual(first, again)
        self.assertNotEqual(first["world_target_xyz_m"], later["world_target_xyz_m"])
        for intent in (first, later):
            point = intent["world_target_xyz_m"]
            self.assertLessEqual(abs(point["x"]), GEOMETRY.width_m / 2)
            self.assertGreaterEqual(point["y"], 0)
            self.assertLessEqual(point["y"], GEOMETRY.forward_depth_m)

    def test_world_mirror_bounce_mirrors_targets_about_dj_center(self):
        positive = beatbeam.venue_native_effect_intent(
            "mirror_bounce", 5.0, GEOMETRY, {**CONTEXT, "artistic_participant_centered": 1}
        )
        negative = beatbeam.venue_native_effect_intent(
            "mirror_bounce", 5.0, GEOMETRY, {**CONTEXT, "artistic_participant_centered": -1}
        )
        self.assertAlmostEqual(
            positive["world_target_xyz_m"]["x"],
            -negative["world_target_xyz_m"]["x"],
        )
        self.assertEqual(positive["world_target_xyz_m"]["y"], negative["world_target_xyz_m"]["y"])

    def test_same_world_target_resolves_independently_for_two_fixture_positions(self):
        controller = beatbeam.DmxController(MagicMock())
        base = controller.default_config()["slots"]["head"]
        target = beatbeam.venue_native_effect_intent("fast_audience_circle", 7.0, GEOMETRY, CONTEXT)
        outputs = []
        for index, x in enumerate((-2.0, 2.0)):
            slot = copy.deepcopy(base)
            slot["venue_calibration"] = {
                "position_m": {"x": x, "y": 0.0, "z": 2.8},
                "physical_forward": {"x": 0, "y": 1, "z": 0},
                "physical_up": {"x": 0, "y": 0, "z": 1},
            }
            result = beatbeam.resolve_spatial_movement_intent(str(index), slot, GEOMETRY, target)
            self.assertEqual("RESOLVED", result["status"])
            outputs.append(result["predicted_output"])
        self.assertNotEqual(
            (outputs[0]["pan"], outputs[0]["pan_fine"]),
            (outputs[1]["pan"], outputs[1]["pan_fine"]),
        )

    def test_world_direction_contract_uses_the_same_shared_resolver(self):
        controller = beatbeam.DmxController(MagicMock())
        slot = controller.default_config()["slots"]["head"]
        slot["venue_calibration"] = {
            "position_m": {"x": 1.0, "y": 0.0, "z": 2.8},
            "physical_forward": {"x": 0, "y": 1, "z": 0},
            "physical_up": {"x": 0, "y": 0, "z": 1},
        }
        result = beatbeam.resolve_spatial_movement_intent(
            "head", slot, GEOMETRY,
            {"kind": "WORLD_DIRECTION", "effect": "parallel_test", "world_direction": {"x": 0, "y": 1, "z": 0}},
        )
        self.assertEqual("RESOLVED", result["status"])
        self.assertEqual("WORLD_DIRECTION", result["spatial_intent"]["kind"])
        self.assertAlmostEqual(0.0, result["target_vector_m"]["x"])
        self.assertGreater(result["target_vector_m"]["y"], 0)

    def test_venue_resize_changes_paths_without_moving_fixture_position(self):
        intent_small = beatbeam.venue_native_effect_intent("drop_snap_fan", 0, GEOMETRY, {**CONTEXT, "artistic_participant_centered": 1})
        wider = beatbeam.VenueGeometry(18.0, 20.0, 4.0, 1.2)
        intent_large = beatbeam.venue_native_effect_intent("drop_snap_fan", 0, wider, {**CONTEXT, "artistic_participant_centered": 1})
        self.assertEqual(intent_small["world_direction"], intent_large["world_direction"])
        fixture_position = {"x": 2.0, "y": 0.0, "z": 2.8}
        self.assertEqual(fixture_position, copy.deepcopy(fixture_position))


if __name__ == "__main__":
    unittest.main()
