import copy
import math
import unittest
from unittest.mock import MagicMock

import beatbeam_app as beatbeam


GEOMETRY = beatbeam.VenueGeometry(10.0, 12.0, 3.0, 1.2)
CENTERED = (-1.0, -1.0 / 3.0, 1.0 / 3.0, 1.0)


def participant_context(index):
    return {
        "role": "moving",
        "role_index": index,
        "role_count": 4,
        "member_index": index,
        "member_count": 4,
        "member_centered": CENTERED[index],
        "member_alternate": -1.0 if index % 2 == 0 else 1.0,
        "artistic_participant_index": index,
        "artistic_participant_count": 4,
        "artistic_participant_centered": CENTERED[index],
        "artistic_closed_phase_offset": index / 4.0,
    }


def intents(effect, beat=6.0, progress=None):
    return [
        beatbeam.venue_native_effect_intent(effect, beat, GEOMETRY, participant_context(index), progress=progress)
        for index in range(4)
    ]


class ProductionMovementSpatialSemanticsV1Tests(unittest.TestCase):
    def test_global_participant_order_uses_venue_x_then_y(self):
        controller = beatbeam.DmxController(MagicMock())
        config = controller.default_config()
        base = config["slots"]["head"]
        config["slots"] = {}
        config["slot_order"] = []
        for slot_id, x, y, group in (
            ("right", 2.0, 1.0, "b"),
            ("left", -2.0, 1.0, "a"),
            ("inner_right", 0.5, 0.0, "b"),
            ("inner_left", -0.5, 0.0, "a"),
        ):
            slot = copy.deepcopy(base)
            slot.update({"address": 1 + len(config["slot_order"]) * 20, "label": slot_id, "group": group})
            slot["venue_calibration"] = {"position_m": {"x": x, "y": y, "z": 2.8}}
            config["slots"][slot_id] = slot
            config["slot_order"].append(slot_id)
        indices = {
            slot_id: controller._slot_context(config, slot_id, slot)["artistic_participant_index"]
            for slot_id, slot in config["slots"].items()
        }
        self.assertEqual({"left": 0, "inner_left": 1, "inner_right": 2, "right": 3}, indices)

    def test_intentional_convergence_remains_shared(self):
        for effect in ("center", "drop_full_audience_hit", "fan_close", "snap_position_hits"):
            targets = [intent["world_target_xyz_m"] for intent in intents(effect)]
            self.assertEqual(1, len({tuple(sorted(target.items())) for target in targets}), effect)

    def test_fans_emit_four_distinct_world_directions(self):
        for effect in ("wide_fan_white", "drop_snap_fan", "fan_open", "build_narrow_to_wide_fan", "snap_fan"):
            result = intents(effect)
            self.assertTrue(all(item["kind"] == "WORLD_DIRECTION" for item in result), effect)
            directions = [tuple(sorted(item["world_direction"].items())) for item in result]
            self.assertEqual(4, len(set(directions)), effect)

    def test_closed_paths_have_four_distinct_continuous_samples(self):
        for effect in (
            "fast_audience_circle", "slow_audience_oval", "pulse_circle", "fast_audience_figure_8",
        ):
            first = [item["world_target_xyz_m"] for item in intents(effect, beat=6.0)]
            later = [item["world_target_xyz_m"] for item in intents(effect, beat=6.01)]
            self.assertEqual(4, len({tuple(sorted(point.items())) for point in first}), effect)
            for before, after in zip(first, later):
                distance = math.sqrt(sum((before[axis] - after[axis]) ** 2 for axis in "xyz"))
                self.assertGreater(distance, 0.0, effect)
                self.assertLess(distance, 0.1, effect)

    def test_open_paths_riser_and_wave_use_four_artistic_lanes(self):
        for effect, kwargs in (
            ("fast_audience_sweep", {}),
            ("build_rising_sweep", {}),
            ("fan_wave", {}),
            ("build_audience_wave", {}),
            ("up_down_sweep", {}),
            ("audience_riser", {"progress": 0.5}),
        ):
            result = intents(effect, **kwargs)
            targets = [tuple(sorted(item["world_target_xyz_m"].items())) for item in result]
            self.assertEqual(4, len(set(targets)), effect)

    def test_searchlights_are_deterministic_four_lane_paths(self):
        first = intents("slow_random_searchlight", beat=6.0)
        again = intents("slow_random_searchlight", beat=6.0)
        self.assertEqual(first, again)
        samples = [tuple(sorted(item["world_target_xyz_m"].items())) for item in first]
        self.assertEqual(4, len(set(samples)))
        points = [item["world_target_xyz_m"] for item in first]
        for left, right in zip(points, points[1:]):
            self.assertGreater(math.hypot(left["x"] - right["x"], left["y"] - right["y"]), 0.25)

    def test_mirror_bounce_preserves_world_x_symmetry_and_center_crossing(self):
        profile = beatbeam.auto_show_motion_profile("mirror_bounce")
        symmetry = intents("mirror_bounce", beat=5.0)
        xs = [item["world_target_xyz_m"]["x"] for item in symmetry]
        self.assertAlmostEqual(xs[0], -xs[3])
        self.assertAlmostEqual(xs[1], -xs[2])
        center_beat = 4.0 / float(profile["phase_scale"])
        crossing = intents("mirror_bounce", beat=center_beat)
        self.assertTrue(all(abs(item["world_target_xyz_m"]["x"]) < 1e-8 for item in crossing))


if __name__ == "__main__":
    unittest.main()
