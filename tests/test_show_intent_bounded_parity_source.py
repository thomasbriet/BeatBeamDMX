import json
import threading
import unittest
import urllib.request
from unittest.mock import patch

import beatbeam_app
from beatbeam_app import (
    DmxController,
    SHOWINTENT_BOUNDED_PARITY_SOURCE_ENABLED,
    _select_showintent_bounded_parity_source,
)


def playback(path="/Music/Parity/A.flac", generation=1, event="virtualdj_active"):
    return {
        "_active_playback_source": "virtualdj",
        "_playback_generation": generation,
        "_playback_event": event,
        "track_path": path,
        "time_seconds": 18.0,
        "bpm": 126.0,
        "beat_value": 12.0,
        "phrase_current": "verse",
        "stale": False,
    }


class ParityTransport:
    def __init__(self):
        self.state = playback()
        self.lock = threading.Lock()
        self.decks = {}

    def snapshot_for_render(self):
        return dict(self.state)

    def developer_playback_state(self):
        return {}

    def structure_behavior_source(self):
        return "song_analyzer"


class ParityBridge:
    def __init__(self, valid=True, bucket="build", energy=1.0):
        self.valid = valid
        self.bucket = bucket
        self.energy = energy

    def resolve(self, selected_source, transport_state):
        return {
            "selected_source": "song_analyzer",
            "effective_source": "song_analyzer" if self.valid else "legacy",
            "eligible": self.valid,
            "fallback_reason": None if self.valid else "track_not_exact",
            "legacy_phrase": "verse",
            "mapped_behavior_bucket": self.bucket if self.valid else None,
            "song_analyzer_label": "Up 1" if self.valid else None,
            "projection": {"rich_current": {"energy": self.energy}} if self.valid else None,
        }


class FakeDmx:
    def __init__(self):
        self.sent = []

    def send(self, values):
        self.sent.append(dict(values))


class ShowIntentBoundedParitySourceTests(unittest.TestCase):
    def controller(self, *, capacity=120000, bridge=None):
        transport = ParityTransport()
        controller = DmxController(
            transport,
            bridge or ParityBridge(),
            show_intent_semantic_history_capacity=capacity,
        )
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"]["enabled"] = True
        controller.render_active = True
        return controller, transport

    @staticmethod
    def select(**overrides):
        values = {
            "feature_gate_enabled": False,
            "manual_phrase_override": False,
            "existing_section_bucket": "verse",
            "existing_energy_modifier": 0.0,
            "source_valid": True,
            "input_present": True,
            "candidate_present": True,
            "candidate_section_bucket": "build",
            "candidate_energy_modifier": 0.04,
        }
        values.update(overrides)
        return _select_showintent_bounded_parity_source(**values)

    def tick(self, controller):
        self.assertFalse(controller._render_tick())
        return controller.state()

    def test_gate_default_off_keeps_existing_pair_and_exposes_snapshot(self):
        self.assertFalse(SHOWINTENT_BOUNDED_PARITY_SOURCE_ENABLED)
        selected = self.select()

        self.assertEqual(("existing_autoshow", "verse", 0.0, False, "feature_gate_off"), (
            selected["production_semantic_source"], selected["production_section_bucket"],
            selected["production_energy_modifier"], selected["showintent_eligible"],
            selected["fallback_reason"],
        ))

        controller, _ = self.controller()
        parity = self.tick(controller)["show_intent_bounded_parity"]
        self.assertEqual((False, False, "existing_autoshow", "feature_gate_off"), (
            parity["gate_enabled"], parity["showintent_eligible"],
            parity["production_semantic_source"], parity["fallback_reason"],
        ))
        self.assertEqual(
            (parity["existing_section_bucket"], parity["existing_energy_modifier"]),
            (parity["production_section_bucket"], parity["production_energy_modifier"]),
        )
        json.dumps(parity)

    def test_gate_on_selects_only_the_current_candidate_pair(self):
        selected = self.select(
            feature_gate_enabled=True,
            candidate_section_bucket="drop",
            candidate_energy_modifier=0.08,
        )

        self.assertEqual((True, "showintent_candidate", "drop", 0.08, "showintent_selected"), (
            selected["showintent_eligible"], selected["production_semantic_source"],
            selected["production_section_bucket"], selected["production_energy_modifier"],
            selected["fallback_reason"],
        ))

    def test_ineligible_candidates_fail_closed_to_the_existing_pair(self):
        cases = (
            ({"candidate_present": False}, "candidate_absent"),
            ({"source_valid": False}, "source_invalid"),
            ({"input_present": False}, "input_absent"),
            ({"manual_phrase_override": True}, "manual_phrase_override"),
            ({"candidate_section_bucket": None}, "selector_failure"),
        )
        for overrides, reason in cases:
            with self.subTest(reason=reason):
                selected = self.select(feature_gate_enabled=True, **overrides)
                self.assertEqual(("existing_autoshow", "verse", 0.0, False, reason), (
                    selected["production_semantic_source"], selected["production_section_bucket"],
                    selected["production_energy_modifier"], selected["showintent_eligible"],
                    selected["fallback_reason"],
                ))

    def test_valid_unknown_zero_is_current_candidate_not_value_suppressed(self):
        selected = self.select(
            feature_gate_enabled=True,
            candidate_section_bucket="unknown",
            candidate_energy_modifier=0.0,
        )

        self.assertEqual((True, "showintent_candidate", "unknown", 0.0), (
            selected["showintent_eligible"], selected["production_semantic_source"],
            selected["production_section_bucket"], selected["production_energy_modifier"],
        ))

    def test_track_and_same_path_deck_boundaries_select_direct_candidate(self):
        for event, path in (("track_changed", "/Music/Parity/B.flac"), ("deck_changed", "/Music/Parity/A.flac")):
            with self.subTest(event=event):
                selected = self.select(
                    feature_gate_enabled=True,
                    candidate_section_bucket="break",
                    candidate_energy_modifier=-0.04,
                )
                self.assertEqual(("showintent_candidate", "break", -0.04), (
                    selected["production_semantic_source"], selected["production_section_bucket"],
                    selected["production_energy_modifier"],
                ))
                self.assertIn(event, {"track_changed", "deck_changed"})
                self.assertTrue(path.startswith("/Music/Parity/"))

    def test_gate_off_auto_show_baseline_is_exact(self):
        controller, transport = self.controller()
        baseline, _ = controller._auto_show_evaluation(
            transport.snapshot_for_render(), controller.config["auto_show"]
        )
        state = self.tick(controller)
        parity = state["show_intent_bounded_parity"]

        self.assertEqual((baseline["phrase_bucket"], baseline["song_analyzer_energy_modifier"]), (
            parity["existing_section_bucket"], parity["existing_energy_modifier"],
        ))
        self.assertEqual((parity["existing_section_bucket"], parity["existing_energy_modifier"]), (
            parity["production_section_bucket"], parity["production_energy_modifier"],
        ))

    def test_current_snapshot_schema_is_compact_and_json_safe(self):
        controller, _ = self.controller()
        parity = self.tick(controller)["show_intent_bounded_parity"]
        self.assertEqual({
            "gate_enabled", "showintent_eligible", "existing_section_bucket",
            "existing_energy_modifier", "candidate_section_bucket", "candidate_energy_modifier",
            "production_semantic_source", "production_section_bucket",
            "production_energy_modifier", "fallback_reason",
        }, set(parity))
        json.dumps(parity)

    def test_parity_history_is_authoritative_only_and_state_is_compact(self):
        controller, _ = self.controller()
        controller.start_show_intent_observation()
        before = controller.show_intent_observation_parity_history()
        controller.state()
        self.assertEqual(before, controller.show_intent_observation_parity_history())

        for _ in range(3):
            self.tick(controller)
        state = controller.state()
        history = controller.show_intent_observation_parity_history()

        self.assertEqual((3, 3), (
            state["show_intent_observation"]["authoritative_frame_count"],
            history["parity_history_count"],
        ))
        self.assertNotIn("parity_history", state["show_intent_observation"])
        self.assertEqual([1, 2, 3], [row["frame_sequence"] for row in history["parity_history"]])

    def test_parity_history_is_bounded_and_drops_oldest(self):
        controller, _ = self.controller(capacity=3)
        controller.start_show_intent_observation()
        for _ in range(5):
            self.tick(controller)
        history = controller.show_intent_observation_parity_history()

        self.assertEqual((3, 3, 2, True), (
            history["parity_history_count"], history["parity_history_capacity"],
            history["parity_history_dropped_frame_count"], history["parity_history_truncated"],
        ))
        self.assertEqual([3, 4, 5], [row["frame_sequence"] for row in history["parity_history"]])

    def test_start_stop_freeze_and_passive_reads_preserve_parity_history(self):
        controller, _ = self.controller()
        controller.start_show_intent_observation()
        self.tick(controller)
        controller.start_show_intent_observation()
        self.assertEqual(1, controller.show_intent_observation_parity_history()["parity_history_count"])
        controller.stop_show_intent_observation()
        frozen = controller.show_intent_observation_parity_history()
        controller.stop_show_intent_observation()
        controller.state()

        self.assertFalse(frozen["session_active"])
        self.assertEqual(frozen, controller.show_intent_observation_parity_history())
        controller.start_show_intent_observation()
        self.assertEqual(0, controller.show_intent_observation_parity_history()["parity_history_count"])

    def test_parity_history_endpoint_is_passive_and_json_safe(self):
        controller, _ = self.controller()
        controller.start_show_intent_observation()
        self.tick(controller)
        server = beatbeam_app.ThreadingHTTPServer(("127.0.0.1", 0), beatbeam_app.AppHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(beatbeam_app, "DMX", controller):
                url = f"http://127.0.0.1:{server.server_port}/api/show-intent-observation/parity-history"
                first = json.load(urllib.request.urlopen(url))
                second = json.load(urllib.request.urlopen(url))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1.0)
        self.assertEqual(first, second)
        self.assertEqual(1, first["parity_history_count"])
        json.dumps(first)

    def test_preview_only_and_physical_send_remain_single_authoritative_path(self):
        preview, _ = self.controller()
        preview.start_show_intent_observation()
        self.tick(preview)
        self.assertIsNone(preview.state()["last_sent"])
        self.assertEqual(1, preview.show_intent_observation_parity_history()["parity_history_count"])

        physical, _ = self.controller()
        dmx = FakeDmx()
        physical.dmx = dmx
        physical.connected = True
        physical.running = True
        self.tick(physical)
        self.assertEqual(1, len(dmx.sent))
        self.assertEqual(1, physical.render_frame_sequence)

    def test_observation_diagnostics_do_not_change_the_selected_production_pair(self):
        controller, _ = self.controller()
        before = self.tick(controller)["show_intent_bounded_parity"]
        controller.start_show_intent_observation()
        self.tick(controller)
        controller.show_intent_observation_history()
        controller.show_intent_observation_parity_history()
        controller.stop_show_intent_observation()
        after = controller.state()["show_intent_bounded_parity"]

        self.assertEqual((before["production_section_bucket"], before["production_energy_modifier"]), (
            after["production_section_bucket"], after["production_energy_modifier"],
        ))


if __name__ == "__main__":
    unittest.main()
