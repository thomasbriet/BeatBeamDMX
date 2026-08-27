import copy
import unittest

from dynamic_composer import (
    CompositionHistory,
    ContinuousMusicalState,
    DIMMER_ANIMATION_MOTIFS,
    DYNAMIC_COMPOSER_MODE,
    FixtureGroupIntent,
    compose_dynamic_preview,
    project_continuous_musical_state,
)
from musical_event_envelope import project_musical_event_envelope
from rme_preview import apply_dynamic_composer_preview, preview_rme_context


def projection(event_type=None, start=10.0, end=20.0, *, availability="available_current", status="in_segment"):
    events = []
    if event_type:
        event = {"type": event_type, "temporal_kind": "INTERVAL" if end else "POINT", "start_seconds": start}
        if end:
            event["end_seconds"] = end
        events.append(event)
    return {
        "track_match": "exact", "availability": availability, "projection_status": status,
        "canonical_track_path": "/Music/current.flac",
        "shadow_analysis": {
            "model": "SectionCharacterProfileShadow",
            "section_characters": [{
                "observation_id": "section-7", "start_seconds": 0.0,
                "end_seconds": 30.0, "relative_energy": .62,
                "energy_rise": .4, "recurrence_strength": .84,
                "family_salience": .75,
            }],
        },
        "rich_musical_events": {"mode": "SHADOW_ONLY", "availability": "available", "events": events},
    }


def base_show():
    return {"energy": .50, "movement": .40, "override_active": False, "motion_name": "center"}


class DynamicComposerTests(unittest.TestCase):
    def state(self, position=15.0, source=None):
        state, reason = project_continuous_musical_state(source or projection(), position)
        self.assertEqual("current", reason)
        self.assertIsNotNone(state)
        return state

    def context(self, position=15.0, event_type=None, end=20.0, source=None):
        source = source or projection(event_type, end=end)
        return preview_rme_context(source, position, DYNAMIC_COMPOSER_MODE)

    def test_continuous_state_and_group_intent_are_immutable_and_strictly_bounded(self):
        state = self.state()
        with self.assertRaises(Exception):
            state.relative_energy = .5
        with self.assertRaises(ValueError):
            ContinuousMusicalState("x", 0, 10, .5, 1.1)
        intent = FixtureGroupIntent(2, -1, float("nan"), .5, .4, "INVALID", .3, .2)
        self.assertEqual((1.0, 0.0, 0.0, "base"),
                         (intent.activity, intent.intensity, intent.movement_amount, intent.palette_role))

    def test_valid_continuous_state_without_rme_stays_active_and_chooses_multiple_dimensions(self):
        context = self.context(event_type=None)
        composition = compose_dynamic_preview(base_show(), self.state(), context)
        rendered = apply_dynamic_composer_preview(base_show(), context, composition)

        self.assertIsNone(composition["event_type"])
        self.assertEqual("none", composition["rme_modifier"])
        self.assertTrue(rendered["dynamic_composer_active"])
        self.assertFalse(rendered["fallback_to_baseline"])
        self.assertFalse(rendered["baseline_scene_reused"])
        self.assertIn("movement", composition["changed_dimensions"])
        self.assertIn("palette", composition["changed_dimensions"])
        self.assertIn("RME None", rendered["preview_cue"])

    def test_live_intensity_is_bounded_preview_modulation_without_semantic_change(self):
        context = self.context(event_type=None)
        base = compose_dynamic_preview(base_show(), self.state(), context)
        boosted = compose_dynamic_preview(
            base_show(), self.state(), context,
            live_intensity={"source_valid": True, "live_modifier": .06, "effective_intensity": .56},
        )
        fallback = compose_dynamic_preview(
            base_show(), self.state(), context,
            live_intensity={"source_valid": False, "live_modifier": .06, "fallback_reason": "stale"},
        )
        self.assertIsNone(boosted["event_type"])
        self.assertGreater(boosted["fixture_group_intents"]["moving"]["intensity"], base["fixture_group_intents"]["moving"]["intensity"])
        self.assertEqual(base["fixture_group_intents"], fallback["fixture_group_intents"])

    def test_invalid_continuous_state_fails_closed_to_baseline(self):
        invalid = projection()
        invalid["shadow_analysis"]["section_characters"][0]["relative_energy"] = None
        state, reason = project_continuous_musical_state(invalid, 15.0)
        composition = compose_dynamic_preview(base_show(), state, self.context())
        rendered = apply_dynamic_composer_preview(base_show(), {"reason": reason}, composition)
        self.assertIsNone(state)
        self.assertEqual("continuous_state_essential_missing", reason)
        self.assertFalse(rendered["dynamic_composer_active"])
        self.assertTrue(rendered["fallback_to_baseline"])
        self.assertTrue(rendered["baseline_scene_reused"])

    def test_build_modulates_the_same_backbone_monotonically(self):
        state = self.state()
        backbone = compose_dynamic_preview(base_show(), state, self.context(event_type=None))
        start = compose_dynamic_preview(base_show(), state, self.context(10.0, "BUILD"))
        middle = compose_dynamic_preview(base_show(), state, self.context(15.0, "BUILD"))
        end = compose_dynamic_preview(base_show(), state, self.context(19.9, "BUILD"))
        for group in ("moving", "par", "wash"):
            self.assertGreater(start["fixture_group_intents"][group]["intensity"],
                               backbone["fixture_group_intents"][group]["intensity"])
            self.assertLess(start["fixture_group_intents"][group]["intensity"], middle["fixture_group_intents"][group]["intensity"])
            self.assertLess(middle["fixture_group_intents"][group]["intensity"], end["fixture_group_intents"][group]["intensity"])
        self.assertEqual("build_fastening_circle", end["selected_primitives"]["moving"]["movement_pattern"])

    def test_break_reduces_backbone_and_drop_is_bounded_accent(self):
        state = self.state()
        backbone = compose_dynamic_preview(base_show(), state, self.context(event_type=None))
        broken = compose_dynamic_preview(base_show(), state, self.context(15.0, "BREAK"))
        drop_source = projection("DROP", end=None)
        envelope, _ = project_musical_event_envelope(
            drop_source, {"time_seconds": 10.2, "bpm": 120.0}
        )
        dropped = compose_dynamic_preview(base_show(), state, self.context(10.2, "DROP", end=None), envelope)
        self.assertLess(broken["fixture_group_intents"]["moving"]["intensity"],
                        backbone["fixture_group_intents"]["moving"]["intensity"])
        self.assertLess(broken["fixture_group_intents"]["moving"]["movement_amount"],
                        backbone["fixture_group_intents"]["moving"]["movement_amount"])
        self.assertGreater(dropped["fixture_group_intents"]["par"]["accent_strength"],
                           backbone["fixture_group_intents"]["par"]["accent_strength"])
        self.assertLessEqual(dropped["fixture_group_intents"]["par"]["accent_strength"], 1.0)

    def test_event_exit_returns_to_the_continuous_composition_not_baseline(self):
        state = self.state()
        no_event = compose_dynamic_preview(base_show(), state, self.context(event_type=None))
        drop_source = projection("DROP", end=None)
        during_envelope, _ = project_musical_event_envelope(
            drop_source, {"time_seconds": 10.2, "bpm": 120.0}
        )
        after_envelope, _ = project_musical_event_envelope(
            drop_source, {"time_seconds": 13.0, "bpm": 120.0}
        )
        during = compose_dynamic_preview(base_show(), state, self.context(10.2, "DROP", end=None), during_envelope)
        after = compose_dynamic_preview(base_show(), state, self.context(13.0, "DROP", end=None), after_envelope)
        self.assertEqual("DROP", during["event_type"])
        self.assertIsNone(after["event_type"])
        self.assertEqual(no_event["fixture_group_intents"], after["fixture_group_intents"])
        self.assertEqual(no_event["selected_primitives"], after["selected_primitives"])
        self.assertIsNotNone(after)

    def test_same_structure_context_is_deterministic_without_pattern_churn(self):
        state, context = self.state(), self.context(event_type=None)
        first = compose_dynamic_preview(base_show(), state, context)
        second = compose_dynamic_preview(copy.deepcopy(base_show()), state, copy.deepcopy(context))
        self.assertEqual(first, second)
        self.assertIn(first["selected_primitives"]["moving"]["movement_pattern"],
                      {"sweep_narrow", "sweep_mid", "sweep_arc"})

    def test_track_local_history_avoids_exact_recent_signature_and_retains_replay(self):
        history = CompositionHistory(capacity=4)
        states = [ContinuousMusicalState(
            f"similar-{index}", 0, 30, .50, .62, .4, .20, .75,
        ) for index in range(4)]
        compositions = [compose_dynamic_preview(
            base_show(), state, self.context(), composition_history=history,
            lifecycle_context=("virtualdj", "/Music/current.flac", 9),
        ) for state in states]
        signatures = [tuple(sorted(item["composition_signature"].items())) for item in compositions]
        self.assertEqual(4, len(set(signatures)))
        self.assertEqual("new", compositions[0]["variation"]["selection"])
        self.assertTrue(all(item["variation"]["selection"] == "anti_repeat_alternative"
                            for item in compositions[1:]))

        replay = compose_dynamic_preview(
            base_show(), states[-1], self.context(), composition_history=history,
            lifecycle_context=("virtualdj", "/Music/current.flac", 9),
        )
        self.assertEqual(compositions[-1]["selected_primitives"], replay["selected_primitives"])
        self.assertEqual("retained", replay["variation"]["selection"])

    def test_recurrence_can_reuse_identity_and_lifecycle_resets_history(self):
        history = CompositionHistory()
        first = ContinuousMusicalState("verse-a", 0, 30, .40, .62, .2, .10, .5)
        recurring = ContinuousMusicalState("verse-b", 30, 60, .40, .62, .2, .90, .5)
        recurring_again = ContinuousMusicalState("verse-c", 60, 90, .40, .62, .2, .90, .5)
        initial = compose_dynamic_preview(base_show(), first, self.context(), composition_history=history,
                                          lifecycle_context=("virtualdj", "track-a", 1))
        alternative = compose_dynamic_preview(base_show(), recurring, self.context(), composition_history=history,
                                              lifecycle_context=("virtualdj", "track-a", 1))
        reused = compose_dynamic_preview(base_show(), recurring_again, self.context(), composition_history=history,
                                         lifecycle_context=("virtualdj", "track-a", 1))
        reset = compose_dynamic_preview(base_show(), recurring, self.context(), composition_history=history,
                                        lifecycle_context=("virtualdj", "track-b", 2))
        self.assertNotEqual(initial["selected_primitives"], alternative["selected_primitives"])
        self.assertEqual("anti_repeat_alternative", alternative["variation"]["selection"])
        self.assertEqual(initial["selected_primitives"], reused["selected_primitives"])
        self.assertEqual("recurrence_reuse", reused["variation"]["selection"])
        self.assertEqual("new", reset["variation"]["selection"])
        self.assertEqual(1, reset["variation"]["history_size"])

    def test_v2_component_history_avoids_immediate_perceptual_repeats(self):
        history = CompositionHistory(capacity=6)
        compositions = []
        for index in range(6):
            state = ContinuousMusicalState(
                f"v2-{index}", index * 30, (index + 1) * 30, .50, .62, .35, .20, .75,
            )
            compositions.append(compose_dynamic_preview(
                base_show(), state, self.context(), composition_history=history,
                lifecycle_context=("simulation", "track-v2", 1),
            ))
        for previous, current in zip(compositions, compositions[1:]):
            left, right = previous["composition_signature"], current["composition_signature"]
            self.assertNotEqual(
                (left["dimmer_motif"], left["palette_family"], left["fixture_partition"]),
                (right["dimmer_motif"], right["palette_family"], right["fixture_partition"]),
            )
            self.assertIn(current["variation"]["repeat_classification"], {
                "NEW_MATERIAL", "COMPONENT_VARIATION", "NEAR_REPEAT", "CAPABILITY_LIMITED",
            })

    def test_track_identity_changes_opening_material_but_replay_is_stable(self):
        state = ContinuousMusicalState("same-section", 0, 30, .5, .72, .35, .2, .7)
        first = compose_dynamic_preview(base_show(), state, self.context(), lifecycle_context=("simulation", "track-a", 1))
        second = compose_dynamic_preview(base_show(), state, self.context(), lifecycle_context=("simulation", "track-b", 1))
        replay = compose_dynamic_preview(base_show(), state, self.context(), lifecycle_context=("simulation", "track-a", 2))
        self.assertNotEqual(first["selected_primitives"], second["selected_primitives"])
        self.assertEqual(first["selected_primitives"], replay["selected_primitives"])

    def test_parameters_are_bounded_and_fixture_independent(self):
        composition = compose_dynamic_preview(base_show(), self.state(), self.context())
        primitive = composition["selected_primitives"]["moving"]
        params = primitive["motion_parameters"]
        self.assertTrue(.72 <= params["range_scale"] <= 1.0)
        self.assertTrue(.82 <= params["speed_scale"] <= 1.16)
        self.assertTrue(-.34 <= params["phase_offset"] <= .34)
        self.assertTrue(.12 <= params["phase_spread"] <= .54)
        self.assertTrue(-12 <= params["horizontal_center_offset"] <= 12)
        self.assertTrue(-9 <= params["vertical_center_offset"] <= 9)
        self.assertIn(primitive["palette_parameters"]["relationship"],
                      {"mono", "adjacent_hue", "two_color_split", "complementary_bright",
                       "triad_bright", "warm_pair", "cool_pair", "warm_cool_contrast"})
        self.assertIn(primitive["dimmer_motif"], {motif.name for motif in DIMMER_ANIMATION_MOTIFS})
        self.assertIn(primitive["color_animation"], {
            "all_same", "group_split", "alternate", "chase_color", "swap_on_bar",
            "swap_on_2_bars", "event_accent", "return_palette_recall",
        })
        self.assertIn("motion_parameters", composition["composition_signature"])

    def test_track_switch_seek_and_stale_projection_fail_closed_or_reproject(self):
        stale = projection(availability="available_stale")
        self.assertEqual((None, "track_not_current"), project_continuous_musical_state(stale, 15.0))
        switched = projection()
        switched["track_match"] = "not_active"
        self.assertEqual((None, "track_not_current"), project_continuous_musical_state(switched, 15.0))
        self.assertEqual((None, "continuous_section_not_current"),
                         project_continuous_musical_state(projection(), 45.0))
        before, _ = project_continuous_musical_state(projection(), 5.0)
        after, _ = project_continuous_musical_state(projection(), 25.0)
        self.assertLess(before.section_progress, after.section_progress)

    def test_manual_override_fails_closed_and_output_has_no_physical_terms(self):
        manual = base_show()
        manual["override_active"] = True
        self.assertIsNone(compose_dynamic_preview(manual, self.state(), self.context()))
        composition = compose_dynamic_preview(base_show(), self.state(), self.context(15.0, "BUILD"))
        serialized = repr(composition).lower()
        for forbidden in ("dmx", "channel", "pan", "tilt", "strobe"):
            self.assertNotIn(forbidden, serialized)
        rendered = apply_dynamic_composer_preview(base_show(), self.context(15.0, "BUILD"), composition)
        self.assertEqual("build", rendered["rme_preview"]["rme_modifier"])
        self.assertTrue(rendered["dynamic_composition_applied"])
        self.assertIn("PAR amber_teal /", rendered["preview_cue"])


if __name__ == "__main__":
    unittest.main()
