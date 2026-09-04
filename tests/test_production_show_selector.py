import copy
import unittest

from dynamic_composer import compose_dynamic_preview, project_continuous_musical_state
from musical_event_envelope import project_musical_event_envelope
from production_show_selector import (
    BASELINE_ONLY, DYNAMIC_COMPOSER_ENABLED, DYNAMIC_COMPOSER_SHADOW,
    FULL_SPHERE_V3_PRODUCTION_MOTIONS, KNOWN_MOTIONS,
    normalize_production_show_mode, select_production_show_source,
    validate_dynamic_composer_candidate,
)
from rme_preview import apply_dynamic_composer_preview, preview_rme_context


PATH = "/Music/current.flac"
CALLING_PATH = "/Users/thomasbriet/Music/Music/Test/Sebastian Ingrosso, Alesso, Ryan Tedder Calling (Lose My Mind) - Extended Club Mix.flac"
FULL_SPHERE_V3_IDENTITIES = frozenset({
    "full_sphere_explode", "floor_hold_explode", "rear_hold_split",
    "full_sphere_cannon", "floor_forward_cannon", "dome_sweep_3d",
    "floor_forward_sweep", "forward_rear_arc", "cross_3d",
    "volumetric_orbit", "volumetric_figure_8", "energy_scatter", "fan_3d",
})


def baseline():
    return {
        "energy": .5, "movement": .4, "motion_name": "center", "override_active": False,
        "override_phrase": "none", "override_color": "none", "override_energy": "none",
        "one_shot_active": False,
    }


def projection():
    return {
        "track_match": "exact", "availability": "available_current", "projection_status": "in_segment",
        "canonical_track_path": PATH,
        "active_track": {"canonical_path": PATH, "status": "ready", "generation": 7},
        "shadow_analysis": {"model": "SectionCharacterProfileShadow", "section_characters": [{
            "observation_id": "section-7", "start_seconds": 0.0, "end_seconds": 30.0,
            "relative_energy": .62, "energy_rise": .4, "recurrence_strength": .4,
            "family_salience": .7,
        }]},
        "rich_musical_events": {"mode": "SHADOW_ONLY", "availability": "available", "events": []},
    }


def playback():
    return {"_active_playback_source": "virtualdj", "_playback_generation": 7,
            "track_path": PATH, "time_seconds": 15.0}


def candidate():
    source = projection()
    state, _ = project_continuous_musical_state(source, 15.0)
    context = preview_rme_context(source, 15.0, "DYNAMIC_COMPOSER")
    composition = compose_dynamic_preview(baseline(), state, context)
    return apply_dynamic_composer_preview(baseline(), context, composition)


def calling_projection(bar, event_type, start_seconds, origin, destination, contrast):
    """Exact production Calling evidence, kept out of selector implementation."""
    return {
        "track_match": "exact", "availability": "available_current", "projection_status": "in_segment",
        "canonical_track_path": CALLING_PATH,
        "active_track": {"canonical_path": CALLING_PATH, "status": "ready", "generation": 7},
        "shadow_analysis": {"model": "SectionCharacterProfileShadow", "section_characters": [{
            "observation_id": f"calling-bar-{bar}", "start_seconds": 0.0, "end_seconds": 400.0,
            "relative_energy": destination, "energy_rise": destination - origin,
            "recurrence_strength": .4, "family_salience": .7,
        }]},
        "rich_musical_events": {"mode": "SHADOW_ONLY", "availability": "available", "events": [{
            "type": event_type, "temporal_kind": "BOUNDARY_TRANSITION",
            "start_seconds": start_seconds, "start_bar": bar,
            "character_context": {
                "origin_relative_energy": origin,
                "destination_relative_energy": destination,
                "entry_contrast": contrast,
            },
        }]},
    }


def calling_playback(bar, position_seconds):
    return {
        "_active_playback_source": "virtualdj", "_playback_generation": 7,
        "track_path": CALLING_PATH, "time_seconds": position_seconds,
        "beat_value": float((bar - 1) * 4),
        "transport": {"virtualdj_bar_number": bar, "virtualdj_beat_number": 1},
    }


def calling_candidate(bar, event_type, start_seconds, origin, destination, contrast):
    source = calling_projection(bar, event_type, start_seconds, origin, destination, contrast)
    transport = calling_playback(bar, start_seconds)
    state, state_reason = project_continuous_musical_state(source, start_seconds)
    envelope, envelope_reason = project_musical_event_envelope(source, transport)
    assert state_reason == "current"
    assert envelope_reason == "active"
    context = preview_rme_context(source, start_seconds, "DYNAMIC_COMPOSER")
    composition = compose_dynamic_preview(baseline(), state, context, envelope)
    return apply_dynamic_composer_preview(baseline(), context, composition), source, transport


class ProductionShowSelectorTests(unittest.TestCase):
    def select(self, mode=DYNAMIC_COMPOSER_ENABLED, base=None, dynamic=None, source=None,
               transport=None, composer_generation=7, renderer_healthy=True):
        return select_production_show_source(
            mode, base or baseline(), dynamic or candidate(), source or projection(),
            transport or playback(), composer_generation, renderer_healthy=renderer_healthy,
        )

    def test_unknown_and_missing_modes_normalize_to_hard_baseline(self):
        self.assertEqual(BASELINE_ONLY, normalize_production_show_mode(None))
        self.assertEqual(BASELINE_ONLY, normalize_production_show_mode("future"))
        base = baseline()
        selected, decision = self.select("future", base=base)
        self.assertIs(selected, base)
        self.assertEqual("mode_baseline", decision["fallback_reason"])

    def test_shadow_computes_eligibility_but_never_selects_candidate(self):
        base, dynamic = baseline(), candidate()
        selected, decision = self.select(DYNAMIC_COMPOSER_SHADOW, base=base, dynamic=dynamic)
        self.assertIs(selected, base)
        self.assertTrue(decision["dynamic_composer_eligible"])
        self.assertFalse(decision["dynamic_composer_active"])
        self.assertEqual("mode_shadow", decision["fallback_reason"])

    def test_enabled_selects_valid_candidate_with_matching_transport_generation_and_track(self):
        dynamic = candidate()
        selected, decision = self.select(dynamic=dynamic)
        self.assertIs(selected, dynamic)
        self.assertTrue(decision["dynamic_composer_active"])
        self.assertEqual("dynamic_composer", decision["production_show_source"])

    def test_manual_overrides_all_fail_back_same_frame(self):
        fields = {
            "override_phrase": "chorus", "override_color": "red", "override_energy": "high",
            "override_manual_strobe": True, "override_audience_sweep": True,
            "override_all_on": True, "override_par_chase": True, "override_par_snake": True,
            "one_shot_active": True,
        }
        for field, value in fields.items():
            with self.subTest(field=field):
                base = baseline()
                base[field] = value
                selected, decision = self.select(base=base)
                self.assertIs(selected, base)
                self.assertEqual("manual_override", decision["fallback_reason"])

    def test_track_handoff_and_renderer_gates_are_fail_closed(self):
        cases = []
        wrong_track = projection(); wrong_track["canonical_track_path"] = "/Music/other.flac"
        cases.append(("track_mismatch", {"source": wrong_track}))
        stale = projection(); stale["availability"] = "available_stale"
        cases.append(("handoff_not_current", {"source": stale}))
        missing_handoff_generation = projection(); missing_handoff_generation["active_track"]["generation"] = None
        cases.append(("generation_mismatch", {"source": missing_handoff_generation}))
        cases.append(("generation_mismatch", {"composer_generation": 8}))
        cases.append(("renderer_unhealthy", {"renderer_healthy": False}))
        paused = playback(); paused["playback_state"] = {
            "availability": "available", "transport_state": "stationary"
        }
        cases.append(("transport_not_advancing", {"transport": paused}))
        for reason, kwargs in cases:
            with self.subTest(reason=reason, kwargs=kwargs):
                base = baseline()
                selected, decision = self.select(base=base, **kwargs)
                self.assertIs(selected, base)
                self.assertEqual(reason, decision["fallback_reason"])

    def test_handoff_and_playback_generations_are_independent_authority_witnesses(self):
        source = projection()
        source["active_track"]["generation"] = 22
        dynamic = candidate()
        selected, decision = self.select(source=source, dynamic=dynamic, composer_generation=7)
        self.assertIs(selected, dynamic)
        self.assertTrue(decision["dynamic_composer_active"])
        self.assertEqual(7, decision["playback_generation"])
        self.assertEqual(22, decision["handoff_generation"])

    def test_invalid_or_nonfinite_candidate_fails_back_without_partial_selection(self):
        for mutation in (
            "missing_state", "nan_group", "inf_group", "unknown_primitive",
            "missing_signature", "partial_signature",
        ):
            with self.subTest(mutation=mutation):
                dynamic = copy.deepcopy(candidate())
                if mutation == "missing_state":
                    dynamic["continuous_musical_state"] = {}
                elif mutation == "nan_group":
                    dynamic["fixture_group_intents"]["moving"]["intensity"] = float("nan")
                elif mutation == "inf_group":
                    dynamic["fixture_group_intents"]["moving"]["intensity"] = float("inf")
                elif mutation == "unknown_primitive":
                    dynamic["selected_primitives"]["moving"]["movement_pattern"] = "unknown"
                elif mutation == "missing_signature":
                    dynamic.pop("composition_signature")
                else:
                    dynamic["composition_signature"].pop("fixture_roles")
                base = baseline()
                selected, decision = self.select(base=base, dynamic=dynamic)
                self.assertIs(selected, base)
                self.assertIn(decision["fallback_reason"], {"continuous_state_missing", "composition_invalid"})

    def test_validator_accepts_current_composer_contract_without_dmx_fields(self):
        dynamic = candidate()
        self.assertTrue(validate_dynamic_composer_candidate(dynamic))
        self.assertNotIn("dmx", repr(dynamic).lower())

    def test_full_sphere_v3_identities_are_admitted_by_the_real_selector(self):
        self.assertEqual(FULL_SPHERE_V3_IDENTITIES, FULL_SPHERE_V3_PRODUCTION_MOTIONS)
        self.assertTrue(FULL_SPHERE_V3_IDENTITIES.issubset(KNOWN_MOTIONS))
        for motion in sorted(FULL_SPHERE_V3_IDENTITIES):
            with self.subTest(motion=motion):
                dynamic = copy.deepcopy(candidate())
                dynamic["selected_primitives"]["moving"]["movement_pattern"] = motion
                dynamic["composition_signature"]["motion_family"] = motion
                selected, decision = self.select(dynamic=dynamic)
                self.assertIs(selected, dynamic)
                self.assertTrue(decision["dynamic_composer_eligible"])
                self.assertEqual("dynamic_composer", decision["production_show_source"])

    def test_unknown_motion_identity_remains_fail_closed(self):
        dynamic = copy.deepcopy(candidate())
        dynamic["selected_primitives"]["moving"]["movement_pattern"] = "unregistered_motion"
        dynamic["composition_signature"]["motion_family"] = "unregistered_motion"
        base = baseline()
        selected, decision = self.select(base=base, dynamic=dynamic)
        self.assertIs(selected, base)
        self.assertEqual("composition_invalid", decision["fallback_reason"])

    def test_calling_production_route_admits_the_actual_arrival_and_drop_evidence(self):
        # Values mirror the current Calling handoff.  Selection remains driven
        # only by event evidence, never by bar number in production code.
        cases = (
            (81, "ARRIVAL", 155.878911, .34719055509724234, .9636501155803732,
             .3085890356766859, "STRONG_ARRIVAL", "full_sphere_explode"),
            (113, "DROP", 216.075237, .40, .93, .30, "DROP", "floor_hold_explode"),
            (145, "ARRIVAL", 276.271563, .39793455873094025, .8984358314613035,
             .3263587486506337, "STRONG_ARRIVAL", "full_sphere_explode"),
        )
        for bar, event_type, start, origin, destination, contrast, expected_event, expected_motion in cases:
            with self.subTest(bar=bar):
                dynamic, source, transport = calling_candidate(
                    bar, event_type, start, origin, destination, contrast,
                )
                self.assertEqual(expected_event, dynamic["dynamic_composer"]["event_type"])
                self.assertEqual(expected_motion, dynamic["selected_primitives"]["moving"]["movement_pattern"])
                selected, decision = self.select(
                    dynamic=dynamic, source=source, transport=transport,
                )
                self.assertIs(selected, dynamic)
                self.assertTrue(decision["dynamic_composer_eligible"])
                self.assertTrue(decision["dynamic_composer_active"])
                self.assertEqual("dynamic_composer", decision["production_show_source"])


if __name__ == "__main__":
    unittest.main()
