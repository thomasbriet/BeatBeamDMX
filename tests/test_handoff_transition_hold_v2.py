import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from beatbeam_app import DmxController
from dynamic_composer import compose_dynamic_preview, project_continuous_musical_state
from production_show_selector import select_production_show_source
from rme_preview import apply_dynamic_composer_preview, preview_rme_context


TRACK_A = "/Music/Transition/A.flac"
TRACK_B = "/Music/Transition/B.flac"
TRACK_C = "/Music/Transition/C.flac"


def playback(path, generation):
    return {
        "_active_playback_source": "virtualdj",
        "_playback_generation": generation,
        "track_path": path,
        "time_seconds": 12.0,
        "beat_value": 24.0,
        "stale": False,
        "playing": True,
        "transport": {"virtualdj_deck_number": 2},
        "playback_state": {"availability": "available", "transport_state": "advancing"},
    }


def projection(path, generation, status="ready"):
    if status != "ready":
        return {
            "track_match": "active_not_ready",
            "availability": status,
            "projection_status": "unknown",
            "canonical_track_path": path,
            "active_track": {
                "canonical_path": path,
                "deck": 2,
                "status": status,
                "generation": generation,
            },
        }
    return {
        "track_match": "exact",
        "availability": "available_current",
        "projection_status": "in_segment",
        "canonical_track_path": path,
        "active_track": {
            "canonical_path": path,
            "deck": 2,
            "status": "ready",
            "generation": generation,
        },
        "composer_readiness": {
            "status": "ready",
            "version": "dynamic-composer-backbone-v1",
            "reason": "ready",
            "missing_fields": [],
        },
        "shadow_analysis": {
            "model": "SectionCharacterProfileShadow",
            "section_characters": [{
                "observation_id": f"section-{generation}",
                "start_seconds": 0.0,
                "end_seconds": 30.0,
                "start_bar": 1,
                "end_bar": 16,
                "bar_count": 16,
                "relative_energy": .62,
                "energy_rise": .2,
                "recurrence_strength": .4,
                "family_salience": .7,
            }],
        },
        "rich_musical_events": {"mode": "SHADOW_ONLY", "availability": "available", "events": []},
    }


def baseline():
    return {
        "enabled": True,
        "available": True,
        "energy": .5,
        "movement": .4,
        "motion_name": "center",
        "override_active": False,
        "override_phrase": "none",
        "override_color": "none",
        "override_energy": "none",
        "one_shot_active": False,
    }


def candidate(source, transport):
    state, reason = project_continuous_musical_state(source, transport["time_seconds"])
    context = preview_rme_context(source, transport["time_seconds"], "DYNAMIC_COMPOSER")
    context = {**context, "continuous_state_reason": reason}
    composition = compose_dynamic_preview(baseline(), state, context)
    return apply_dynamic_composer_preview(baseline(), context, composition)


class HandoffTransitionHoldV3RegressionTests(unittest.TestCase):
    def setUp(self):
        self.config_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.config_directory.cleanup)
        self.controller = DmxController(
            MagicMock(), MagicMock(),
            config_path=Path(self.config_directory.name) / "beatbeam_config.json",
        )
        self.controller.config = self.controller._clean_full_config(self.controller.default_config())
        self.controller.config["production_show_mode"] = "DYNAMIC_COMPOSER_ENABLED"
        self.controller.config["auto_show"].update({
            "enabled": True,
            "preview_rme_mode": "DYNAMIC_COMPOSER",
        })
        self.controller.render_active = True

    def select(self, transport, source, dynamic, now, base=None):
        self.controller._preview_auto_show_evaluation = MagicMock(return_value=(dynamic, source))
        with patch("beatbeam_app.time.monotonic", return_value=now):
            return self.controller._select_production_auto_show(
                self.controller.config, transport, base or baseline()
            )

    def prime_a(self, now=100.0, playback_generation=1, handoff_generation=10, dynamic=None):
        transport = playback(TRACK_A, playback_generation)
        source = projection(TRACK_A, handoff_generation)
        selected, _, decision = self.select(
            transport, source, dynamic or candidate(source, transport), now
        )
        self.assertEqual("dynamic_composer", decision["production_show_source"])
        return selected, decision

    def test_raw_pending_tick_reproduces_the_previous_baseline_selection(self):
        base = baseline()
        a_playback = playback(TRACK_A, 1)
        b_pending = projection(TRACK_B, 11, "pending")

        selected, decision = select_production_show_source(
            "DYNAMIC_COMPOSER_ENABLED", base, baseline(), b_pending, a_playback, 1
        )

        self.assertIs(base, selected)
        self.assertEqual("handoff_not_current", decision["fallback_reason"])
        self.assertEqual("existing_autoshow", decision["production_show_source"])
        self.assertEqual(TRACK_A, a_playback["track_path"])
        self.assertEqual(TRACK_B, decision["handoff_track_path"])

    def test_prewarm_only_keeps_normal_a_without_starting_or_aging_a_hold(self):
        selected_a, first = self.prime_a()
        a_playback = playback(TRACK_A, 1)

        b_pending = projection(TRACK_B, 11, "pending")
        selected_during, _, during = self.select(a_playback, b_pending, baseline(), 500.0)

        self.assertEqual("dynamic_composer", first["production_show_source"])
        self.assertEqual("dynamic_composer", during["production_show_source"])
        self.assertEqual(selected_a, selected_during)
        self.assertFalse(during["handoff_effect_hold"])
        self.assertIsNone(during["handoff_effect_hold_age_seconds"])
        self.assertIsNone(during["handoff_effect_hold_deadline_monotonic"])
        self.assertIsNone(during["handoff_effect_hold_from_track_path"])
        self.assertIsNone(self.controller._dynamic_composer_handoff_hold)

    def test_actual_playback_switch_starts_bounded_hold_at_real_transition_boundary(self):
        self.prime_a()
        pending = projection(TRACK_B, 11, "pending")
        _, _, before_switch = self.select(playback(TRACK_A, 1), pending, baseline(), 100.1)
        _, _, after_switch = self.select(playback(TRACK_B, 2), pending, baseline(), 500.0)

        self.assertFalse(before_switch["handoff_effect_hold"])
        self.assertTrue(after_switch["handoff_effect_hold"])
        self.assertEqual(0.0, after_switch["handoff_effect_hold_age_seconds"])
        self.assertEqual(502.0, after_switch["handoff_effect_hold_deadline_monotonic"])
        self.assertEqual(2.0, after_switch["handoff_effect_hold_remaining_seconds"])

    def test_a_ready_b_pending_b_ready_has_zero_baseline_sources(self):
        sources = []
        _, first = self.prime_a()
        sources.append(first["production_show_source"])
        b_pending = projection(TRACK_B, 11, "pending")
        for now, state in ((100.1, playback(TRACK_A, 1)), (100.2, playback(TRACK_B, 2))):
            _, _, decision = self.select(state, b_pending, baseline(), now)
            sources.append(decision["production_show_source"])
        b_playback = playback(TRACK_B, 2)
        b_ready = projection(TRACK_B, 11)
        _, _, ready = self.select(b_playback, b_ready, candidate(b_ready, b_playback), 100.3)
        sources.append(ready["production_show_source"])

        self.assertEqual(0, sources.count("existing_autoshow"))
        self.assertEqual("composer_ready", ready["handoff_effect_hold_exit_reason"])
        self.assertEqual(TRACK_B, self.controller._last_dynamic_composer_handoff_effect["track_path"])

    def test_track_change_discontinuity_holds_a_until_b_is_ready_without_baseline(self):
        sources = []
        selected_a, first = self.prime_a()
        sources.append(first["production_show_source"])
        b_pending = projection(TRACK_B, 11, "pending")
        boundary = playback(TRACK_B, 2)
        boundary["playing"] = False
        boundary["playback_state"].update({
            "transport_state": "unknown",
            "last_discontinuity": "track_changed",
        })

        held_a, _, held = self.select(boundary, b_pending, baseline(), 100.1)
        sources.append(held["production_show_source"])
        b_playback = playback(TRACK_B, 2)
        b_ready = projection(TRACK_B, 11)
        selected_b, _, ready = self.select(
            b_playback, b_ready, candidate(b_ready, b_playback), 100.2
        )
        sources.append(ready["production_show_source"])

        self.assertEqual(0, sources.count("existing_autoshow"))
        self.assertEqual(selected_a["composition_signature"], held_a["composition_signature"])
        self.assertTrue(held["handoff_effect_hold"])
        self.assertEqual("handoff_effect_hold", held["fallback_reason"])
        self.assertEqual(candidate(b_ready, b_playback), selected_b)
        self.assertEqual("composer_ready", ready["handoff_effect_hold_exit_reason"])

    def test_b_ready_almost_immediately_switches_directly_without_baseline(self):
        sources = []
        _, first = self.prime_a()
        sources.append(first["production_show_source"])
        b_playback = playback(TRACK_B, 2)
        b_ready = projection(TRACK_B, 11)
        selected_b, _, ready = self.select(
            b_playback, b_ready, candidate(b_ready, b_playback), 100.01
        )
        sources.append(ready["production_show_source"])

        self.assertEqual(["dynamic_composer", "dynamic_composer"], sources)
        self.assertFalse(ready["handoff_effect_hold"])
        self.assertEqual(TRACK_B, self.controller._last_dynamic_composer_handoff_effect["track_path"])
        self.assertEqual(candidate(b_ready, b_playback), selected_b)

    def test_b_ready_after_one_second_keeps_a_for_the_full_preparation_interval(self):
        selected_a, first = self.prime_a()
        pending = projection(TRACK_B, 11, "pending")
        held_a, _, held = self.select(playback(TRACK_B, 2), pending, baseline(), 100.1)
        b_playback = playback(TRACK_B, 2)
        b_ready = projection(TRACK_B, 11)
        selected_b, _, ready = self.select(
            b_playback, b_ready, candidate(b_ready, b_playback), 101.1
        )

        self.assertEqual("dynamic_composer", first["production_show_source"])
        self.assertEqual("dynamic_composer", held["production_show_source"])
        self.assertEqual(TRACK_A, held["handoff_effect_hold_from_track_path"])
        self.assertEqual(selected_a["composition_signature"], held_a["composition_signature"])
        self.assertEqual("dynamic_composer", ready["production_show_source"])
        self.assertEqual(candidate(b_ready, b_playback), selected_b)

    def test_hold_expires_to_explicit_baseline(self):
        self.prime_a()
        pending = projection(TRACK_B, 11, "pending")
        self.select(playback(TRACK_B, 2), pending, baseline(), 100.1)
        _, _, expired = self.select(playback(TRACK_B, 2), pending, baseline(), 102.11)

        self.assertEqual("existing_autoshow", expired["production_show_source"])
        self.assertEqual("hold_expired", expired["handoff_effect_hold_exit_reason"])
        self.assertIsNone(self.controller._last_dynamic_composer_handoff_effect)

    def test_unavailable_ends_hold_and_does_not_leave_hidden_a_authority(self):
        self.prime_a()
        self.select(playback(TRACK_B, 2), projection(TRACK_B, 11, "pending"), baseline(), 100.1)
        _, _, unavailable = self.select(
            playback(TRACK_B, 2), projection(TRACK_B, 11, "unavailable"), baseline(), 100.2
        )

        self.assertEqual("existing_autoshow", unavailable["production_show_source"])
        self.assertEqual("handoff_unavailable", unavailable["handoff_effect_hold_exit_reason"])
        self.assertIsNone(self.controller._last_dynamic_composer_handoff_effect)

    def test_invalid_composer_readiness_ends_hold_fail_closed(self):
        self.prime_a()
        self.select(playback(TRACK_B, 2), projection(TRACK_B, 11, "pending"), baseline(), 100.1)
        invalid = projection(TRACK_B, 11)
        invalid["composer_readiness"] = {
            "status": "invalid",
            "version": "dynamic-composer-backbone-v1",
            "reason": "backbone_invalid",
            "missing_fields": ["section_characters"],
        }
        b_playback = playback(TRACK_B, 2)
        _, _, decision = self.select(b_playback, invalid, candidate(invalid, b_playback), 100.2)

        self.assertEqual("existing_autoshow", decision["production_show_source"])
        self.assertEqual("composer_readiness_invalid", decision["fallback_reason"])
        self.assertEqual("fallback_not_transition_pending", decision["handoff_effect_hold_exit_reason"])

    def test_transport_loss_ends_hold_fail_closed(self):
        self.prime_a()
        pending = projection(TRACK_B, 11, "pending")
        self.select(playback(TRACK_B, 2), pending, baseline(), 100.1)
        lost = playback(TRACK_B, 2)
        lost["playing"] = False
        lost["playback_state"]["transport_state"] = "stationary"
        _, _, decision = self.select(lost, pending, baseline(), 100.2)

        self.assertEqual("existing_autoshow", decision["production_show_source"])
        self.assertEqual("transport_not_advancing", decision["handoff_effect_hold_exit_reason"])
        self.assertIsNone(self.controller._last_dynamic_composer_handoff_effect)

    def test_rapid_a_b_c_never_resurrects_b_and_c_becomes_authoritative(self):
        self.prime_a()
        _, _, b_hold = self.select(
            playback(TRACK_B, 2), projection(TRACK_B, 11, "pending"), baseline(), 100.1
        )
        _, _, c_hold = self.select(
            playback(TRACK_C, 3), projection(TRACK_C, 12, "pending"), baseline(), 100.2
        )
        stale_b = projection(TRACK_B, 11)
        _, _, stale = self.select(playback(TRACK_C, 3), stale_b, candidate(stale_b, playback(TRACK_B, 2)), 100.25)
        c_playback = playback(TRACK_C, 3)
        c_ready = projection(TRACK_C, 12)
        _, _, final = self.select(c_playback, c_ready, candidate(c_ready, c_playback), 100.3)

        self.assertEqual(TRACK_A, b_hold["handoff_effect_hold_from_track_path"])
        self.assertEqual(TRACK_A, c_hold["handoff_effect_hold_from_track_path"])
        self.assertEqual("dynamic_composer", stale["production_show_source"])
        self.assertTrue(stale["handoff_effect_hold"])
        self.assertEqual("dynamic_composer", final["production_show_source"])
        self.assertEqual(TRACK_C, self.controller._last_dynamic_composer_handoff_effect["track_path"])

    def test_a_b_a_reactivation_keeps_generation_and_visual_continuity(self):
        self.prime_a()
        self.select(playback(TRACK_B, 2), projection(TRACK_B, 11, "pending"), baseline(), 100.1)
        _, _, a2_hold = self.select(
            playback(TRACK_A, 3), projection(TRACK_A, 12, "pending"), baseline(), 100.2
        )
        a2_playback = playback(TRACK_A, 3)
        a2_ready = projection(TRACK_A, 12)
        _, _, final = self.select(a2_playback, a2_ready, candidate(a2_ready, a2_playback), 100.3)

        self.assertTrue(a2_hold["handoff_effect_hold"])
        self.assertEqual(3, final["playback_generation"])
        self.assertEqual(12, final["handoff_generation"])

    def test_same_track_reload_uses_new_generation_without_baseline(self):
        self.prime_a()
        _, _, prewarm = self.select(
            playback(TRACK_A, 1), projection(TRACK_A, 11, "pending"), baseline(), 100.05
        )
        _, _, pending = self.select(
            playback(TRACK_A, 2), projection(TRACK_A, 11, "pending"), baseline(), 100.1
        )
        a2_playback = playback(TRACK_A, 2)
        a2_ready = projection(TRACK_A, 11)
        _, _, ready = self.select(a2_playback, a2_ready, candidate(a2_ready, a2_playback), 100.2)

        self.assertEqual("dynamic_composer", prewarm["production_show_source"])
        self.assertFalse(prewarm["handoff_effect_hold"])
        self.assertEqual("dynamic_composer", pending["production_show_source"])
        self.assertTrue(pending["handoff_effect_hold"])
        self.assertEqual("dynamic_composer", ready["production_show_source"])

    def test_pending_without_previous_composer_remains_on_baseline(self):
        _, _, decision = self.select(
            playback(TRACK_B, 1), projection(TRACK_B, 10, "pending"), baseline(), 100.0
        )

        self.assertEqual("existing_autoshow", decision["production_show_source"])
        self.assertEqual("no_previous_composer", decision["handoff_effect_hold_exit_reason"])

    def test_manual_override_wins_immediately(self):
        self.prime_a()
        manual = baseline()
        manual["override_color"] = "red"
        _, _, decision = self.select(
            playback(TRACK_B, 2), projection(TRACK_B, 11, "pending"), baseline(), 100.1,
            base=manual,
        )

        self.assertEqual("existing_autoshow", decision["production_show_source"])
        self.assertEqual("manual_override", decision["handoff_effect_hold_exit_reason"])
        self.assertIsNone(self.controller._last_dynamic_composer_handoff_effect)

    def test_blackout_wins_immediately(self):
        self.prime_a()
        self.controller.config["blackout_active"] = True
        _, _, decision = self.select(
            playback(TRACK_B, 2), projection(TRACK_B, 11, "pending"), baseline(), 100.1
        )

        self.assertEqual("existing_autoshow", decision["production_show_source"])
        self.assertEqual("blackout_active", decision["handoff_effect_hold_exit_reason"])
        self.assertIsNone(self.controller._last_dynamic_composer_handoff_effect)

    def test_renderer_failure_wins_immediately(self):
        self.prime_a()
        self.controller.renderer_error = "synthetic"
        _, _, decision = self.select(
            playback(TRACK_B, 2), projection(TRACK_B, 11, "pending"), baseline(), 100.1
        )

        self.assertEqual("existing_autoshow", decision["production_show_source"])
        self.assertEqual("renderer_unhealthy", decision["handoff_effect_hold_exit_reason"])
        self.assertIsNone(self.controller._last_dynamic_composer_handoff_effect)

    def test_held_visual_neutralizes_stale_transient_triggers(self):
        a_playback = playback(TRACK_A, 1)
        a_ready = projection(TRACK_A, 10)
        dynamic = candidate(a_ready, a_playback)
        dynamic.update({
            "beat_pulse": True,
            "dynamic_level": True,
            "external_strobe": True,
            "strobe_window": True,
            "one_shot_active": False,
        })
        self.prime_a(dynamic=dynamic)
        captured = self.controller._last_dynamic_composer_handoff_effect["auto_show"]
        for primitive in captured["selected_primitives"].values():
            primitive["pulse"] = "hit"
            primitive["dimmer_motif"] = "burst_all"

        held, _, decision = self.select(
            playback(TRACK_B, 2), projection(TRACK_B, 11, "pending"), baseline(), 100.1
        )

        self.assertTrue(decision["handoff_effect_hold"])
        self.assertFalse(held["beat_pulse"])
        self.assertFalse(held["dynamic_level"])
        self.assertFalse(held["external_strobe"])
        self.assertFalse(held["strobe_window"])
        self.assertFalse(held["one_shot_active"])
        self.assertTrue(all(item["pulse"] == "none" for item in held["selected_primitives"].values()))
        self.assertTrue(all(item["dimmer_motif"] is None for item in held["selected_primitives"].values()))


if __name__ == "__main__":
    unittest.main()
