import copy
import unittest

from production_show_selector import (
    DYNAMIC_COMPOSER_ENABLED,
    select_production_show_source,
)
from tests.test_production_show_selector import baseline, candidate, playback, projection


class ProductionShowSelectorFaultMatrixTests(unittest.TestCase):
    def valid_context(self):
        base = baseline()
        dynamic = candidate()
        source = projection()
        source["active_track"].update({"deck": 1, "status": "ready"})
        transport = playback()
        transport.update({
            "playing": True,
            "transport": {"virtualdj_deck_number": 1},
            "playback_state": {"availability": "available", "transport_state": "advancing"},
        })
        return base, dynamic, source, transport

    def select(self, base, dynamic, source, transport, *, generation=7,
               renderer_healthy=True, blackout=False):
        return select_production_show_source(
            DYNAMIC_COMPOSER_ENABLED,
            base,
            dynamic,
            source,
            transport,
            generation,
            renderer_healthy=renderer_healthy,
            safety_context={"blackout_active": blackout},
        )

    def assert_fail_closed(self, expected_reason, mutate=None, **options):
        base, dynamic, source, transport = self.valid_context()
        if mutate is not None:
            dynamic, source, transport, base = mutate(dynamic, source, transport, base)
        selected, decision = self.select(base, dynamic, source, transport, **options)
        self.assertIs(selected, base)
        self.assertEqual("existing_autoshow", decision["production_source"])
        self.assertTrue(decision["fallback_active"])
        self.assertFalse(decision["composer_active"])
        self.assertEqual(expected_reason, decision["fallback_reason"])
        return decision

    def test_complete_fault_matrix_fails_closed_to_same_frame_baseline(self):
        def change(which, value=None):
            def mutate(dynamic, source, transport, base):
                target, key = which.split(".", 1)
                {"dynamic": dynamic, "source": source, "transport": transport,
                 "base": base}[target][key] = value
                return dynamic, source, transport, base
            return mutate

        def missing_handoff(dynamic, source, transport, base):
            return dynamic, {}, transport, base

        def wrong_deck(dynamic, source, transport, base):
            source["active_track"]["deck"] = 2
            return dynamic, source, transport, base

        def missing_handoff_generation(dynamic, source, transport, base):
            source["active_track"]["generation"] = None
            return dynamic, source, transport, base

        def state_mutation(field, value):
            def mutate(dynamic, source, transport, base):
                dynamic["continuous_musical_state"][field] = value
                return dynamic, source, transport, base
            return mutate

        def context_exception(dynamic, source, transport, base):
            dynamic["rme_preview"]["continuous_state_reason"] = "composer_exception"
            return dynamic, source, transport, base

        def no_candidate(dynamic, source, transport, base):
            return None, source, transport, base

        def missing_group(dynamic, source, transport, base):
            dynamic["fixture_group_intents"].pop("wash")
            return dynamic, source, transport, base

        def primitive(group, field, value):
            def mutate(dynamic, source, transport, base):
                dynamic["selected_primitives"][group][field] = value
                return dynamic, source, transport, base
            return mutate

        def group_value(value):
            def mutate(dynamic, source, transport, base):
                dynamic["fixture_group_intents"]["moving"]["intensity"] = value
                return dynamic, source, transport, base
            return mutate

        def motion_parameter(value):
            def mutate(dynamic, source, transport, base):
                dynamic["selected_primitives"]["moving"]["motion_parameters"]["range_scale"] = value
                return dynamic, source, transport, base
            return mutate

        def incomplete_signature(dynamic, source, transport, base):
            dynamic["composition_signature"].pop("fixture_roles")
            return dynamic, source, transport, base

        def override(field, value=True):
            def mutate(dynamic, source, transport, base):
                base[field] = value
                return dynamic, source, transport, base
            return mutate

        def active_pending(dynamic, source, transport, base):
            source["active_track"]["status"] = "pending"
            return dynamic, source, transport, base

        cases = [
            ("stale_handoff", "handoff_not_current", change("source.availability", "available_stale"), {}),
            ("missing_handoff", "handoff_not_current", missing_handoff, {}),
            ("wrong_track", "track_mismatch", change("source.canonical_track_path", "/Music/wrong.flac"), {}),
            ("wrong_deck", "deck_mismatch", wrong_deck, {}),
            ("generation_mismatch", "generation_mismatch", missing_handoff_generation, {}),
            ("playback_stopped", "transport_not_advancing", change("transport.playing", False), {}),
            ("transport_stale", "transport_stale", change("transport.stale", True), {}),
            ("state_missing", "continuous_state_missing", state_mutation("observation_id", ""), {}),
            ("state_malformed", "continuous_state_missing", state_mutation("section_progress", 2.0), {}),
            ("composer_exception", "composer_exception", context_exception, {}),
            ("candidate_none", "candidate_missing", no_candidate, {}),
            ("candidate_incomplete", "composition_invalid", missing_group, {}),
            ("unknown_motion", "composition_invalid", primitive("moving", "movement_pattern", "unknown"), {}),
            ("unknown_palette", "composition_invalid", primitive("par", "palette", "unknown"), {}),
            ("unknown_pulse", "composition_invalid", primitive("par", "pulse", "unknown"), {}),
            ("unknown_wash", "composition_invalid", primitive("wash", "wash_cue", "unknown"), {}),
            ("nan", "composition_invalid", group_value(float("nan")), {}),
            ("inf", "composition_invalid", motion_parameter(float("inf")), {}),
            ("negative", "composition_invalid", group_value(-.01), {}),
            ("above_range", "composition_invalid", motion_parameter(1.01), {}),
            ("incomplete_signature", "composition_invalid", incomplete_signature, {}),
            ("manual_phrase", "manual_override", override("override_phrase", "chorus"), {}),
            ("manual_color", "manual_override", override("override_color", "red"), {}),
            ("manual_energy", "manual_override", override("override_energy", "high"), {}),
            ("manual_strobe", "manual_override", override("override_manual_strobe"), {}),
            ("one_shot", "manual_override", override("one_shot_active"), {}),
            ("blackout", "blackout_active", None, {"blackout": True}),
            ("chase", "manual_override", override("override_par_chase"), {}),
            ("snake", "manual_override", override("override_par_snake"), {}),
            ("all_on", "manual_override", override("override_all_on"), {}),
            ("sweep", "manual_override", override("override_audience_sweep"), {}),
            ("track_switch_transient", "track_mismatch", change("transport.track_path", "/Music/new.flac"), {}),
            ("seek_transient", "generation_mismatch", None, {"generation": 8}),
            ("same_path_other_deck", "deck_mismatch", wrong_deck, {}),
            ("prewarm_stale_replacement", "handoff_not_current", active_pending, {}),
            ("renderer_failure", "renderer_unhealthy", None, {"renderer_healthy": False}),
        ]
        for name, reason, mutation, options in cases:
            with self.subTest(name=name):
                self.assert_fail_closed(reason, mutation, **options)

    def test_pause_resume_and_rapid_a_b_a_recover_only_current_candidate(self):
        base, dynamic, source, transport = self.valid_context()
        transport["playback_state"]["transport_state"] = "stationary"
        selected, decision = self.select(base, dynamic, source, transport)
        self.assertIs(selected, base)
        self.assertEqual("transport_not_advancing", decision["fallback_reason"])

        transport["playback_state"]["transport_state"] = "advancing"
        for deck, path, generation in (
            (1, "/Music/a.flac", 8), (2, "/Music/b.flac", 9), (1, "/Music/a.flac", 10)
        ):
            current_base = copy.deepcopy(base)
            current_dynamic = copy.deepcopy(dynamic)
            current_source = copy.deepcopy(source)
            current_transport = copy.deepcopy(transport)
            current_source.update({"canonical_track_path": path})
            current_source["active_track"].update({
                "canonical_path": path, "deck": deck, "generation": generation,
            })
            current_transport.update({"track_path": path, "_playback_generation": generation})
            current_transport["transport"]["virtualdj_deck_number"] = deck
            selected, decision = self.select(
                current_base, current_dynamic, current_source, current_transport,
                generation=generation,
            )
            self.assertIs(selected, current_dynamic)
            self.assertTrue(decision["composer_active"])

    def test_fault_after_valid_candidate_never_latches_or_partially_reuses_it(self):
        base, dynamic, source, transport = self.valid_context()
        selected, decision = self.select(base, dynamic, source, transport)
        self.assertIs(selected, dynamic)
        self.assertTrue(decision["composer_active"])

        next_base = copy.deepcopy(base)
        invalid = copy.deepcopy(dynamic)
        invalid["fixture_group_intents"]["wash"]["intensity"] = float("nan")
        selected, decision = self.select(next_base, invalid, source, transport)
        self.assertIs(selected, next_base)
        self.assertIsNot(selected, dynamic)
        self.assertEqual("composition_invalid", decision["fallback_reason"])


if __name__ == "__main__":
    unittest.main()
