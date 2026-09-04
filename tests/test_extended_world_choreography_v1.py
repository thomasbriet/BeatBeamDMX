import math
import unittest
from unittest.mock import MagicMock

import beatbeam_app as beatbeam


GEOMETRY = beatbeam.VenueGeometry(10.0, 12.0, 3.0, 1.2)


def context(index=0, count=4, **extra):
    result = {
        "role": "moving",
        "role_count": count,
        "artistic_participant_count": count,
        "artistic_participant_index": index,
        "artistic_participant_centered": -1.0 + 2.0 * index / max(1, count - 1),
        "section": "build",
        "phrase": "build",
        "event_type": "BUILD",
        "section_progress": .5,
        "motion_parameters": {"range_scale": 1.0, "speed_scale": 1.0},
    }
    result.update(extra)
    return result


class ExtendedWorldChoreographyV1Tests(unittest.TestCase):
    def samples(self, effect, beats, *, index=0, **extra):
        return [beatbeam.venue_native_effect_intent(effect, beat, GEOMETRY, context(index, **extra)) for beat in beats]

    def test_full_sweep_crosses_a_broad_field_beyond_venue_without_changing_geometry(self):
        intents = self.samples("fast_audience_sweep", range(0, 9))
        x_values = [item["world_target_xyz_m"]["x"] for item in intents]
        self.assertLess(min(x_values), -GEOMETRY.width_m / 2.0)
        self.assertGreater(max(x_values), GEOMETRY.width_m / 2.0)
        trace = intents[0]["path_metadata"]
        self.assertEqual("EXTENDED_BEYOND_VENUE_ALLOWED", trace["artistic_world"])
        self.assertGreater(trace["artistic_span_m"]["x"], GEOMETRY.width_m)
        self.assertEqual(10.0, GEOMETRY.width_m)

    def test_fast_and_slow_sweeps_have_explicitly_different_broad_timing(self):
        fast = beatbeam.movement_engine_v3_recipe("fast_audience_sweep")
        slow = beatbeam.movement_engine_v3_recipe("slow_audience_sweep_white")
        self.assertLess(fast.horizontal_beats, slow.horizontal_beats)
        self.assertGreater(fast.horizontal_range, 1.0)
        self.assertGreater(slow.horizontal_range, 1.0)

    def test_extended_target_resolves_through_existing_bounded_physical_route(self):
        controller = beatbeam.DmxController(MagicMock())
        slot_id = controller.config["slot_order"][0]
        controller.config = controller._merge_payload({"venue_geometry": GEOMETRY.as_dict()})
        controller.config = controller._merge_payload({"slot_id": slot_id, "slot": {"venue_calibration": {
            "position_m": {"x": -1.0, "y": 0.0, "z": 2.8},
            "physical_forward": {"x": 0, "y": 1, "z": 0},
            "physical_up": {"x": 0, "y": 0, "z": 1},
        }}})
        intent = beatbeam.venue_native_effect_intent("fast_audience_sweep", 3.0, GEOMETRY, context())
        self.assertGreater(abs(intent["world_target_xyz_m"]["x"]), GEOMETRY.width_m / 2.0)
        resolved = beatbeam.resolve_spatial_movement_intent(slot_id, controller.config["slots"][slot_id], GEOMETRY, intent)
        self.assertEqual("RESOLVED", resolved["status"])
        self.assertTrue(all(math.isfinite(float(value)) for value in resolved["predicted_output"].values() if value is not None))
        self.assertTrue(all(0 <= int(value) <= 255 for value in resolved["predicted_output"].values() if value is not None))

    def test_four_fixture_fan_has_four_distinct_open_directions_and_narrow_is_smaller(self):
        open_fan = [beatbeam.venue_native_effect_intent("fan_open", 4.0, GEOMETRY, context(index)) for index in range(4)]
        narrow_fan = [beatbeam.venue_native_effect_intent("narrow_fan_white", 4.0, GEOMETRY, context(index)) for index in range(4)]
        open_x = [item["world_direction"]["x"] for item in open_fan]
        narrow_x = [item["world_direction"]["x"] for item in narrow_fan]
        self.assertEqual(4, len(set(open_x)))
        self.assertGreater(max(open_x) - min(open_x), 2.5)
        self.assertGreater(max(open_x) - min(open_x), max(narrow_x) - min(narrow_x))
        self.assertEqual("DIRECTIONAL_EFFECT", open_fan[0]["path_metadata"]["spatial_type"])

    def test_build_fan_grows_spatially_with_real_progress(self):
        closed = [beatbeam.venue_native_effect_intent("build_narrow_to_wide_fan", 3.0, GEOMETRY, context(index), progress=.0) for index in range(4)]
        open_ = [beatbeam.venue_native_effect_intent("build_narrow_to_wide_fan", 3.0, GEOMETRY, context(index), progress=1.0) for index in range(4)]
        closed_span = max(item["world_direction"]["x"] for item in closed) - min(item["world_direction"]["x"] for item in closed)
        open_span = max(item["world_direction"]["x"] for item in open_) - min(item["world_direction"]["x"] for item in open_)
        self.assertGreater(open_span, closed_span * 3.0)

    def test_large_paths_have_role_lanes_and_uneven_timing(self):
        circle = [beatbeam.venue_native_effect_intent("fast_audience_circle", 2.0, GEOMETRY, context(index)) for index in range(4)]
        figure = [beatbeam.venue_native_effect_intent("fast_audience_figure_8", 2.0, GEOMETRY, context(index)) for index in range(4)]
        self.assertGreater(circle[0]["path_metadata"]["artistic_span_m"]["x"], GEOMETRY.width_m)
        self.assertEqual(4, len({item["world_target_xyz_m"]["x"] for item in circle}))
        self.assertEqual(4, len({item["world_target_xyz_m"]["x"] for item in figure}))
        self.assertNotEqual(circle[0]["path_metadata"]["horizontal_phase"], circle[0]["path_metadata"]["vertical_phase"])

    def test_cross_and_mirror_keep_wide_world_x_relationships(self):
        cross = [beatbeam.venue_native_effect_intent("drop_crossing_beams", 0.0, GEOMETRY, context(index)) for index in range(4)]
        mirror_left = beatbeam.venue_native_effect_intent("mirror_bounce_show", 4.0, GEOMETRY, context(0))
        mirror_right = beatbeam.venue_native_effect_intent("mirror_bounce_show", 4.0, GEOMETRY, context(3))
        cross_x = [item["world_target_xyz_m"]["x"] for item in cross]
        self.assertGreater(max(cross_x) - min(cross_x), GEOMETRY.width_m)
        self.assertAlmostEqual(mirror_left["world_target_xyz_m"]["x"], -mirror_right["world_target_xyz_m"]["x"], places=7)

    def test_rising_build_grows_width_and_height_and_rejects_invalid_progress(self):
        low = beatbeam.venue_native_effect_intent("build_rising_sweep", 3.0, GEOMETRY, context(), progress=.0)
        high = beatbeam.venue_native_effect_intent("build_rising_sweep", 3.0, GEOMETRY, context(), progress=1.0)
        self.assertGreater(high["world_target_xyz_m"]["z"], low["world_target_xyz_m"]["z"])
        self.assertGreater(abs(high["world_target_xyz_m"]["x"]), abs(low["world_target_xyz_m"]["x"]))
        for invalid in (None, float("nan"), float("inf"), True):
            with self.subTest(invalid=invalid):
                self.assertIsNone(beatbeam.movement_engine_v3_effect_intent("build_rising_sweep", 3.0, GEOMETRY, context(section_progress=invalid), progress=invalid))

    def test_v3_intents_never_reintroduce_raw_motor_authority(self):
        for effect in ("fast_audience_sweep", "fan_open", "fast_audience_circle", "drop_crossing_beams", "build_rising_sweep"):
            intent = beatbeam.venue_native_effect_intent(effect, 3.0, GEOMETRY, context(), progress=.5)
            with self.subTest(effect=effect):
                self.assertEqual("V3_RECIPE", intent["path_metadata"]["route"])
                self.assertNotIn("pan", intent)
                self.assertNotIn("tilt", intent)


if __name__ == "__main__":
    unittest.main()
