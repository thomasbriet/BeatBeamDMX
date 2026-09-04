import unittest
import math
from unittest.mock import MagicMock

import beatbeam_app as beatbeam


GEOMETRY = beatbeam.VenueGeometry(10.0, 12.0, 3.0, 1.2)


def context(index=0, count=4, **extra):
    payload = {
        "role": "moving",
        "role_count": count,
        "artistic_participant_count": count,
        "artistic_participant_index": index,
        "artistic_participant_centered": -1.0 + 2.0 * index / max(1, count - 1),
        "section": "chorus",
        "phrase": "chorus",
        "event_type": "CHORUS",
        "section_progress": .5,
        "motion_parameters": {"range_scale": 1.0, "speed_scale": 1.0},
    }
    payload.update(extra)
    return payload


class MovementEngineV3Tests(unittest.TestCase):
    FULL_SPHERE_LAB_EFFECTS = (
        "full_sphere_explode", "floor_hold_explode", "rear_hold_split",
        "full_sphere_cannon", "floor_forward_cannon", "dome_sweep_3d",
        "floor_forward_sweep", "forward_rear_arc", "cross_3d",
        "volumetric_orbit", "volumetric_figure_8", "energy_scatter", "fan_3d",
    )

    def test_explicit_recipe_route_and_unmigrated_world_fallback(self):
        routed = beatbeam.venue_native_effect_intent("fast_audience_circle", 8, GEOMETRY, context())
        fallback = beatbeam.venue_native_effect_intent("baseline_phrase_motion", 8, GEOMETRY, context())
        self.assertEqual("V3_RECIPE", routed["path_metadata"]["route"])
        self.assertEqual("V3", routed["path_metadata"]["engine"])
        self.assertEqual("V2_WORLD_NATIVE_FALLBACK", fallback["path_metadata"]["route"])
        self.assertNotIn("pan", routed)
        self.assertNotIn("tilt", routed)

    def test_v3_recipe_is_immutable_world_only_data(self):
        recipe = beatbeam.movement_engine_v3_recipe("fast_audience_circle")
        self.assertIsNotNone(recipe)
        self.assertFalse(hasattr(recipe, "pan"))
        self.assertFalse(hasattr(recipe, "tilt"))
        with self.assertRaises(TypeError):
            beatbeam.V3_EFFECT_RECIPES["new"] = recipe

    def test_fast_circle_advances_more_than_slow_circle_and_has_separate_vertical_phase(self):
        slow_a = beatbeam.venue_native_effect_intent("slow_audience_circle", 4, GEOMETRY, context())
        slow_b = beatbeam.venue_native_effect_intent("slow_audience_circle", 12, GEOMETRY, context())
        fast_a = beatbeam.venue_native_effect_intent("fast_audience_circle", 4, GEOMETRY, context())
        fast_b = beatbeam.venue_native_effect_intent("fast_audience_circle", 12, GEOMETRY, context())
        slow_distance = abs(slow_b["world_target_xyz_m"]["x"] - slow_a["world_target_xyz_m"]["x"])
        fast_distance = abs(fast_b["world_target_xyz_m"]["x"] - fast_a["world_target_xyz_m"]["x"])
        self.assertGreater(fast_distance, slow_distance)
        trace = slow_a["path_metadata"]
        self.assertNotEqual(trace["horizontal_phase"], trace["vertical_phase"])

    def test_high_value_shapes_have_v3_recipes_and_global_nonregular_roles(self):
        effects = (
            "slow_audience_oval", "fast_audience_figure_8", "fast_audience_sweep",
            "fast_diagonal_sweep", "build_narrow_to_wide_fan", "drop_crossing_beams",
            "mirror_bounce_show", "build_rising_sweep", "slow_random_searchlight",
        )
        for effect in effects:
            with self.subTest(effect=effect):
                intents = [beatbeam.venue_native_effect_intent(effect, 7, GEOMETRY, context(index)) for index in range(4)]
                self.assertTrue(all(item["path_metadata"]["route"] == "V3_RECIPE" for item in intents))
                phases = [item["path_metadata"]["horizontal_phase"] for item in intents]
                self.assertNotEqual(phases, [0, .25, .5, .75])

    def test_rising_recipe_with_absent_optional_progress_uses_finite_v2_fallback(self):
        no_event = context(event_type=None, section_progress=None)
        self.assertIsNone(beatbeam.movement_engine_v3_effect_intent(
            "build_rising_sweep", 16, GEOMETRY, no_event,
        ))
        fallback = beatbeam.venue_native_effect_intent(
            "build_rising_sweep", 16, GEOMETRY, no_event,
        )
        self.assertEqual("V2_WORLD_NATIVE_FALLBACK", fallback["path_metadata"]["route"])
        self.assertTrue(all(
            math.isfinite(float(value))
            for value in fallback["world_target_xyz_m"].values()
        ))

    def test_searchlight_window_is_deterministic_and_changes_by_window(self):
        first = beatbeam.venue_native_effect_intent("slow_random_searchlight", 3, GEOMETRY, context(1, variation_seed="a"))
        again = beatbeam.venue_native_effect_intent("slow_random_searchlight", 3, GEOMETRY, context(1, variation_seed="a"))
        later = beatbeam.venue_native_effect_intent("slow_random_searchlight", 27, GEOMETRY, context(1, variation_seed="a"))
        self.assertEqual(first, again)
        self.assertNotEqual(first["world_target_xyz_m"], later["world_target_xyz_m"])

    def test_movement_lab_is_ephemeral_and_uses_production_v3_route_without_dmx(self):
        controller = beatbeam.DmxController(MagicMock())
        started = controller.start_movement_lab({"effect_id": "fast_audience_circle", "section": "drop", "variation": 2})
        self.assertTrue(started["accepted"])
        self.assertFalse(started["movement_lab"]["dmx_connected"])
        self.assertEqual("V3_RECIPE", started["movement_lab"]["route"])
        self.assertTrue(controller._movement_lab_state_locked()["active"])
        stopped = controller.stop_movement_lab()
        self.assertTrue(stopped["accepted"])
        self.assertFalse(stopped["movement_lab"]["active"])

    def test_movement_lab_can_display_v2_world_native_fallback(self):
        controller = beatbeam.DmxController(MagicMock())
        response = controller.start_movement_lab({"effect_id": "baseline_phrase_motion", "section": "verse"})
        self.assertTrue(response["accepted"])
        self.assertEqual("V2_WORLD_NATIVE_FALLBACK", response["movement_lab"]["route"])

    def test_full_sphere_lab_effects_are_real_v3_recipes_and_use_the_production_route(self):
        controller = beatbeam.DmxController(MagicMock())
        for effect in self.FULL_SPHERE_LAB_EFFECTS:
            with self.subTest(effect=effect):
                recipe = beatbeam.movement_engine_v3_recipe(effect)
                self.assertIs(recipe, beatbeam.V3_EFFECT_RECIPES[effect])
                started = controller.start_movement_lab({
                    "effect_id": effect, "section": "drop", "variation": 3,
                })
                self.assertTrue(started["accepted"])
                self.assertEqual(effect, started["movement_lab"]["effect_id"])
                self.assertEqual("V3_RECIPE", started["movement_lab"]["route"])
                intents = [
                    beatbeam.venue_native_effect_intent(effect, 4.0, GEOMETRY, context(index))
                    for index in range(4)
                ]
                self.assertTrue(all(intent["path_metadata"]["route"] == "V3_RECIPE" for intent in intents))
                for intent in intents:
                    coordinates = intent.get("world_direction") or intent.get("world_target_xyz_m") or {}
                    self.assertTrue(all(math.isfinite(float(value)) for value in coordinates.values()))
                stopped = controller.stop_movement_lab()
                self.assertTrue(stopped["accepted"])
                self.assertFalse(stopped["movement_lab"]["active"])


if __name__ == "__main__":
    unittest.main()
