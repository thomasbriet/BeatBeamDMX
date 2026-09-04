import math
import unittest
from unittest.mock import MagicMock

import beatbeam_app as beatbeam


GEOMETRY = beatbeam.VenueGeometry(10.0, 12.0, 3.0, 1.2)
FULL_SPHERE_EFFECTS = (
    "full_sphere_explode", "floor_hit", "floor_hold_explode",
    "full_sphere_cannon", "floor_forward_cannon", "dome_sweep_3d",
    "floor_forward_sweep", "forward_rear_arc", "cross_3d",
    "volumetric_orbit", "volumetric_figure_8", "energy_scatter", "fan_3d", "rear_hold_split",
)


def context(index=0, count=4, **extra):
    payload = {
        "role": "moving", "role_count": count,
        "artistic_participant_count": count,
        "artistic_participant_index": index,
        "artistic_participant_centered": -1.0 + 2.0 * index / max(1, count - 1),
        "section": "drop", "phrase": "drop", "event_type": "DROP",
        "section_progress": .5,
        "motion_parameters": {"range_scale": 1.0, "speed_scale": 1.0},
    }
    payload.update(extra)
    return payload


def intents(effect, beat, **extra):
    return [beatbeam.venue_native_effect_intent(effect, beat, GEOMETRY, context(index, **extra)) for index in range(4)]


class FullSphereEnergyChoreographyV1Tests(unittest.TestCase):
    def test_every_recipe_is_production_v3_world_direction_without_raw_motors(self):
        for effect in FULL_SPHERE_EFFECTS:
            with self.subTest(effect=effect):
                result = intents(effect, 4.0)
                self.assertTrue(all(item and item["kind"] == "WORLD_DIRECTION" for item in result))
                self.assertTrue(all(item["path_metadata"]["route"] == "V3_RECIPE" for item in result))
                self.assertTrue(all("pan" not in item and "tilt" not in item for item in result))
                self.assertTrue(all(set(item["world_direction"]) == {"x", "y", "z"} for item in result))

    def test_floor_direction_is_negative_z_for_all_pair_and_single_participants(self):
        all_roles = intents("floor_hit", 2.0)
        pair = [beatbeam.venue_native_effect_intent("floor_hit", 2.0, GEOMETRY, context(index, count=2)) for index in range(2)]
        single = beatbeam.venue_native_effect_intent("floor_hit", 2.0, GEOMETRY, context(0, count=1))
        for result in all_roles + pair + [single]:
            self.assertLessEqual(result["world_direction"]["z"], -.90)
            self.assertTrue(result["path_metadata"]["floor_facing"])

    def test_explode_has_broad_xyz_and_floor_rear_side_participation(self):
        result = intents("full_sphere_explode", 4.0)
        metric = beatbeam.full_sphere_directional_diversity(result)
        self.assertGreater(metric["x_range"], 1.5)
        self.assertGreater(metric["y_range"], 1.2)
        self.assertGreater(metric["z_range"], 1.2)
        self.assertEqual(1, metric["floor_facing_count"])
        self.assertGreaterEqual(metric["rear_or_side_count"], 2)
        self.assertGreater(metric["min_pairwise_separation"], 1.0)
        self.assertEqual(1, sum(beatbeam.full_sphere_clear_rear(item["world_direction"]) for item in result))

    def test_floor_hold_then_explode_is_phrase_wide_and_directionally_separated(self):
        held = intents("floor_hold_explode", 1.0)
        released = intents("floor_hold_explode", 4.0)
        self.assertTrue(all(item["path_metadata"]["floor_facing"] for item in held))
        metric = beatbeam.full_sphere_directional_diversity(released)
        self.assertIn("FLOOR_DOWN", metric["regions"])
        self.assertGreaterEqual(metric["rear_or_side_count"], 2)
        self.assertGreater(metric["min_pairwise_separation"], 1.0)
        self.assertEqual(1, sum(beatbeam.full_sphere_clear_rear(item["world_direction"]) for item in released))

    def test_rear_hold_split_has_one_stable_clear_rear_role_and_nonconverged_contrast(self):
        first = intents("rear_hold_split", 2.0, variation_seed="rear-a")
        later = intents("rear_hold_split", 6.0, variation_seed="rear-a")
        again = intents("rear_hold_split", 2.0, variation_seed="rear-a")
        self.assertEqual(first, again)
        self.assertEqual(1, sum(beatbeam.full_sphere_clear_rear(item["world_direction"]) for item in first))
        self.assertEqual(1, sum(beatbeam.full_sphere_clear_rear(item["world_direction"]) for item in later))
        self.assertTrue(any(item["path_metadata"]["floor_facing"] for item in first))
        directions = [tuple(item["world_direction"][axis] for axis in "xyz") for item in first]
        self.assertEqual(4, len(set(directions)))
        self.assertGreater(beatbeam.full_sphere_directional_diversity(first)["min_pairwise_separation"], 1.0)

    def test_cannons_and_3d_fan_assign_each_role_a_distinct_direction(self):
        for effect in ("full_sphere_cannon", "floor_forward_cannon", "fan_3d"):
            with self.subTest(effect=effect):
                result = intents(effect, 3.0)
                directions = [tuple(item["world_direction"][axis] for axis in "xyz") for item in result]
                self.assertEqual(4, len(set(directions)))
        floor_forward = beatbeam.full_sphere_directional_diversity(intents("floor_forward_cannon", 3.0))
        self.assertGreaterEqual(floor_forward["floor_facing_count"], 1)
        self.assertIn("FORWARD_RIGHT", floor_forward["regions"])

    def test_sweeps_cross_forward_rear_floor_and_full_3d_ranges_over_time(self):
        samples = []
        for effect in ("dome_sweep_3d", "floor_forward_sweep", "forward_rear_arc"):
            samples.extend(item for beat in range(0, 13) for item in intents(effect, float(beat)))
        metric = beatbeam.full_sphere_directional_diversity(samples)
        self.assertGreater(metric["x_range"], 1.8)
        self.assertGreater(metric["y_range"], 1.7)
        self.assertGreater(metric["z_range"], 1.5)
        self.assertIn("FLOOR_DOWN", metric["regions"])
        self.assertTrue(any(region.startswith("REAR") for region in metric["regions"]))

    def test_cross_orbits_figure_eight_and_scatter_are_volumetric(self):
        for effect in ("cross_3d", "volumetric_orbit", "volumetric_figure_8", "energy_scatter"):
            with self.subTest(effect=effect):
                samples = [item for beat in range(0, 13) for item in intents(effect, float(beat))]
                metric = beatbeam.full_sphere_directional_diversity(samples)
                self.assertGreater(metric["x_range"], 1.3)
                self.assertGreater(metric["y_range"], 1.2)
                self.assertGreater(metric["z_range"], 1.2)

    def test_build_sweep_grows_from_floor_to_wider_forward_diversity(self):
        closed = intents("floor_forward_sweep", 3.0, section="build", event_type="BUILD", section_progress=0.0)
        open_ = intents("floor_forward_sweep", 3.0, section="build", event_type="BUILD", section_progress=1.0)
        closed_metric = beatbeam.full_sphere_directional_diversity(closed)
        open_metric = beatbeam.full_sphere_directional_diversity(open_)
        self.assertGreater(open_metric["x_range"], closed_metric["x_range"] * 2.5)
        self.assertGreater(open_metric["z_range"], .8)

    def test_break_remains_forward_target_character_while_drop_is_full_sphere(self):
        break_intents = intents("break_slow_pulse_circle", 4.0, section="break", event_type="BREAK")
        drop_metric = beatbeam.full_sphere_directional_diversity(intents("floor_hold_explode", 4.0))
        self.assertTrue(all(item["kind"] == "WORLD_TARGET_XYZ_M" for item in break_intents))
        self.assertGreater(drop_metric["z_range"], 1.5)
        self.assertGreaterEqual(drop_metric["rear_or_side_count"], 2)

    def test_calling_acceptance_effects_have_a_clear_rear_role_without_bar_logic(self):
        # These are deterministic acceptance samples only. Production selects
        # by musical event type, never by Calling bar number.
        for bar, effect in ((81, "full_sphere_explode"), (113, "floor_hold_explode"), (145, "full_sphere_explode")):
            with self.subTest(bar=bar, effect=effect):
                result = intents(effect, float(bar * 4))
                self.assertEqual(1, sum(beatbeam.full_sphere_clear_rear(item["world_direction"]) for item in result))
                self.assertTrue(any(item["path_metadata"]["floor_facing"] for item in result))

    def test_full_sphere_world_intent_resolves_via_existing_bounded_calibrated_route(self):
        controller = beatbeam.DmxController(MagicMock())
        slot_id = controller.config["slot_order"][0]
        controller.config = controller._merge_payload({"venue_geometry": GEOMETRY.as_dict()})
        controller.config = controller._merge_payload({"slot_id": slot_id, "slot": {"venue_calibration": {
            "position_m": {"x": -1.0, "y": 0.0, "z": 2.8},
            "physical_forward": {"x": 0, "y": 1, "z": 0},
            "physical_up": {"x": 0, "y": 0, "z": 1},
        }}})
        intent = intents("full_sphere_explode", 4.0)[0]
        resolved = beatbeam.resolve_spatial_movement_intent(slot_id, controller.config["slots"][slot_id], GEOMETRY, intent)
        self.assertEqual("RESOLVED", resolved["status"])
        self.assertEqual("WORLD_DIRECTION", resolved["spatial_intent"]["kind"])
        self.assertTrue(all(math.isfinite(float(value)) for value in resolved["predicted_output"].values() if value is not None))
        self.assertTrue(all(0 <= int(value) <= 255 for value in resolved["predicted_output"].values() if value is not None))


if __name__ == "__main__":
    unittest.main()
