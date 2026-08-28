import copy
import unittest

from dynamic_composer import compose_dynamic_preview, project_continuous_musical_state
from production_show_selector import (
    BASELINE_ONLY, DYNAMIC_COMPOSER_ENABLED, DYNAMIC_COMPOSER_SHADOW,
    normalize_production_show_mode, select_production_show_source,
    validate_dynamic_composer_candidate,
)
from rme_preview import apply_dynamic_composer_preview, preview_rme_context


PATH = "/Music/current.flac"


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


if __name__ == "__main__":
    unittest.main()
