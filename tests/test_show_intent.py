import dataclasses
import math
import unittest
from pathlib import Path

from show_intent import (
    MAXIMUM_ENERGY_MODIFIER,
    MINIMUM_ENERGY_MODIFIER,
    NEUTRAL_ENERGY_MODIFIER,
    NEUTRAL_SECTION_BUCKET,
    ShowIntent,
    neutral_show_intent,
    resolve_show_intent,
)


class ShowIntentTests(unittest.TestCase):
    def test_neutral_initial_state_uses_existing_fail_closed_values(self):
        intent = neutral_show_intent()

        self.assertEqual(NEUTRAL_SECTION_BUCKET, intent.section_bucket)
        self.assertEqual("unknown", intent.section_bucket)
        self.assertEqual(NEUTRAL_ENERGY_MODIFIER, intent.energy_modifier)
        self.assertEqual(0.0, intent.energy_modifier)

    def test_model_is_immutable(self):
        intent = ShowIntent("build", 0.04)

        with self.assertRaises(dataclasses.FrozenInstanceError):
            intent.section_bucket = "drop"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            intent.energy_modifier = 0.0

    def test_existing_bucket_values_are_kept_and_invalid_values_fail_closed(self):
        self.assertEqual("build", ShowIntent("build", 0.0).section_bucket)
        self.assertEqual("chorus", ShowIntent(" CHORUS ", 0.0).section_bucket)
        self.assertEqual("unknown", ShowIntent("not-a-bucket", 0.0).section_bucket)
        self.assertEqual("unknown", ShowIntent(None, 0.0).section_bucket)

    def test_energy_modifier_preserves_bounds_and_fails_closed(self):
        self.assertEqual(0.04, ShowIntent("build", 0.04).energy_modifier)
        self.assertEqual(MINIMUM_ENERGY_MODIFIER, ShowIntent("build", -1.0).energy_modifier)
        self.assertEqual(MAXIMUM_ENERGY_MODIFIER, ShowIntent("build", 1.0).energy_modifier)
        for invalid in (float("nan"), float("inf"), float("-inf"), True, "0.04", None):
            with self.subTest(invalid=invalid):
                self.assertEqual(0.0, ShowIntent("build", invalid).energy_modifier)

    def test_none_without_previous_creates_neutral_state(self):
        self.assertEqual(neutral_show_intent(), resolve_show_intent(None, None))

    def test_none_candidate_preserves_the_exact_previous_instance(self):
        previous = ShowIntent("build", 0.04)

        self.assertIs(previous, resolve_show_intent(previous, None))

    def test_explicit_candidate_replaces_without_hidden_carry_over(self):
        previous = ShowIntent("build", 0.08)
        candidate = ShowIntent("break", -0.04)

        resolved = resolve_show_intent(previous, candidate)

        self.assertIs(candidate, resolved)
        self.assertEqual("break", resolved.section_bucket)
        self.assertEqual(-0.04, resolved.energy_modifier)
        self.assertNotEqual(previous, resolved)

    def test_continuity_sequence_holds_then_replaces(self):
        candidate_a = ShowIntent("build", 0.04)
        candidate_b = ShowIntent("break", -0.04)
        sequence = [None, candidate_a, None, None, candidate_b, None]
        state = None
        resolved = []

        for candidate in sequence:
            state = resolve_show_intent(state, candidate)
            resolved.append(state)

        self.assertEqual([
            ShowIntent("unknown", 0.0), candidate_a, candidate_a,
            candidate_a, candidate_b, candidate_b,
        ], resolved)
        self.assertIs(resolved[1], resolved[2])
        self.assertIs(resolved[2], resolved[3])
        self.assertIs(resolved[4], resolved[5])

    def test_multiple_explicit_candidates_replace_atomically(self):
        first = ShowIntent("intro", -0.08)
        second = ShowIntent("chorus", 0.08)
        third = ShowIntent("outro", 0.0)

        state = resolve_show_intent(None, first)
        state = resolve_show_intent(state, second)
        state = resolve_show_intent(state, third)

        self.assertIs(third, state)
        self.assertEqual(("outro", 0.0), (state.section_bucket, state.energy_modifier))

    def test_invalid_resolver_arguments_are_explicit(self):
        with self.assertRaises(TypeError):
            resolve_show_intent("not-an-intent", None)
        with self.assertRaises(TypeError):
            resolve_show_intent(None, "not-an-intent")

    def test_module_has_no_runtime_or_rendering_dependencies(self):
        source = (Path(__file__).parents[1] / "show_intent.py").read_text(encoding="utf-8").lower()
        forbidden = (
            "import beatbeam_app", "songanalyzer", "virtualdj", "osc",
            "dmx", "fixture", "upward_arrival", "current_event", "next_event",
        )
        self.assertTrue(all(token not in source for token in forbidden))
        self.assertNotIn("if section_bucket ==", source)
        self.assertNotIn("event_type", source)
        self.assertFalse(math.isnan(ShowIntent("unknown", 0.0).energy_modifier))


if __name__ == "__main__":
    unittest.main()
