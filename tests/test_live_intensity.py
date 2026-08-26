import unittest
from unittest.mock import patch

from beatbeam_app import TransportController, beat_pattern_classification
from live_intensity import LIVE_INTENSITY_MAX_MODIFIER, LiveIntensityFeedback


def source(value, lifecycle=("virtualdj", 1, "/Music/A.flac", 1)):
    return {"valid": True, "reason": "master_deck_energy_current", "value": value, "lifecycle": lifecycle}


class LiveIntensityTests(unittest.TestCase):
    def test_missing_stale_and_mismatched_deck_fail_closed(self):
        feedback = LiveIntensityFeedback()
        missing = feedback.observe(.42, None, 0.0)
        stale = feedback.observe(.42, {"valid": False, "reason": "master_deck_energy_stale"}, .1)
        self.assertFalse(missing["source_valid"])
        self.assertEqual(.42, missing["effective_intensity"])
        self.assertEqual(.42, stale["effective_intensity"])

        playback = {"beatbeam": {"deck_number": 2, "track_path": "/Music/B.flac"}}
        mismatch = TransportController._virtualdj_live_intensity_input(
            {"decks": {"1": {"waveform_energy": .8, "waveform_energy_age_seconds": .1}}}, playback)
        self.assertFalse(mismatch["valid"])
        self.assertEqual("master_deck_energy_missing", mismatch["reason"])

    def test_attack_release_normalization_and_lifecycle_reset_are_bounded(self):
        feedback = LiveIntensityFeedback()
        baseline = feedback.observe(.50, source(.20), 0.0)
        rise = feedback.observe(.50, source(.90), .20)
        fall = feedback.observe(.50, source(.20), 2.00)
        switched = feedback.observe(.50, source(.80, ("virtualdj", 2, "/Music/B.flac", 2)), 2.01)
        self.assertEqual(0.0, baseline["live_modifier"])
        self.assertGreater(rise["live_modifier"], 0.0)
        self.assertLess(fall["live_modifier"], rise["live_modifier"])
        self.assertEqual(0.0, switched["live_modifier"])
        for state in (baseline, rise, fall, switched):
            self.assertLessEqual(abs(state["live_modifier"]), LIVE_INTENSITY_MAX_MODIFIER)
            self.assertGreaterEqual(state["effective_intensity"], 0.0)
            self.assertLessEqual(state["effective_intensity"], 1.0)

    def test_single_transient_settles_while_sustained_change_remains_bounded(self):
        transient = LiveIntensityFeedback()
        transient.observe(.50, source(.25), 0.0)
        peak = transient.observe(.50, source(1.0), .20)
        settling = peak
        for now in (.40, .60, .80, 1.00, 1.20, 1.40, 1.60, 1.80, 2.00):
            settling = transient.observe(.50, source(.25), now)
        self.assertGreater(peak["live_modifier"], 0.0)
        self.assertLess(abs(settling["live_modifier"]), abs(peak["live_modifier"]))

        sustained = LiveIntensityFeedback()
        sustained.observe(.50, source(.25), 0.0)
        states = [sustained.observe(.50, source(.85), now)
                  for now in (.20, .40, .60, .80, 1.00)]
        self.assertTrue(all(state["live_modifier"] > 0.0 for state in states))
        self.assertLessEqual(max(state["live_modifier"] for state in states),
                             LIVE_INTENSITY_MAX_MODIFIER)

    def test_master_bound_input_requires_fresh_deck_specific_energy(self):
        playback = {"beatbeam": {"deck_number": 2, "track_path": "/Music/B.flac"}}
        current = TransportController._virtualdj_live_intensity_input(
            {"_playback_generation": 9, "decks": {"2": {"waveform_energy": .73, "waveform_energy_age_seconds": .2}}}, playback)
        stale = TransportController._virtualdj_live_intensity_input(
            {"decks": {"2": {"waveform_energy": .73, "waveform_energy_age_seconds": .76}}}, playback)
        self.assertTrue(current["valid"])
        self.assertEqual(("virtualdj", 2, "/Music/B.flac", 9), current["lifecycle"])
        self.assertFalse(stale["valid"])

    def test_bridge_level_requires_current_authoritative_identity_and_generation(self):
        observed = 1_700_000_000_000
        playback = {
            "availability": "available", "transport_state": "advancing",
            "beatbeam": {"deck_number": 2, "track_path": "/Music/B.flac"},
            "decks": [{"deck_number": 2, "track_path": "/Music/B.flac",
                       "captured_at_unix_milliseconds": observed, "signal_level": .73,
                       "active_generation": 12}],
        }
        with patch("beatbeam_app.time.time", return_value=observed / 1000.0 + .2):
            current = TransportController._virtualdj_live_intensity_input({}, playback)
        self.assertTrue(current["valid"])
        self.assertEqual("master_deck_pre_master_level_current", current["reason"])
        self.assertEqual(("virtualdj", 2, "/Music/B.flac", 12), current["lifecycle"])
        self.assertEqual(.73, current["value"])
        self.assertAlmostEqual(200.0, current["age_milliseconds"])
        self.assertEqual(2, current["deck_number"])
        self.assertEqual(12, current["generation"])
        self.assertEqual("virtualdj_get_level", current["source_kind"])

        state = LiveIntensityFeedback().observe(.5, current, 0.0)
        self.assertEqual(.73, state["raw_source_level"])
        self.assertAlmostEqual(200.0, state["source_age_milliseconds"])
        self.assertEqual(2, state["source_deck"])
        self.assertEqual(12, state["source_generation"])
        self.assertEqual("virtualdj_get_level", state["source_kind"])

        playback["decks"][0]["active_generation"] = None
        with patch("beatbeam_app.time.time", return_value=observed / 1000.0 + .2):
            unbound = TransportController._virtualdj_live_intensity_input({}, playback)
        self.assertFalse(unbound["valid"])
        self.assertEqual("master_deck_signal_unbound", unbound["reason"])

    def test_pattern_classes_separate_expected_sparse_and_every_beat_output(self):
        self.assertEqual("EVERY_BEAT", beat_pattern_classification("strong_pulse"))
        self.assertEqual("HALF_TIME", beat_pattern_classification("alternate_whole"))
        self.assertEqual("BAR_ACCENT", beat_pattern_classification("drop_blinder"))
        self.assertEqual("SUBDIVISION", beat_pattern_classification("double_hit"))
        self.assertEqual("INTENTIONALLY_SPARSE", beat_pattern_classification("hit"))
        self.assertEqual("UNKNOWN", beat_pattern_classification("future_mode"))
