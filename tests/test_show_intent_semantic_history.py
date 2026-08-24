import json
import threading
import unittest
import urllib.request
from unittest.mock import patch

import beatbeam_app
from beatbeam_app import DmxController, SHOW_INTENT_SEMANTIC_HISTORY_MAX_FRAMES
from show_interpreter_input_adapter import ShowInterpreterEffectiveContext


VALID_BUILD = ShowInterpreterEffectiveContext(True, "build", 0.04)
VALID_UNKNOWN = ShowInterpreterEffectiveContext(True, "unknown", 0.0)


class Clock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value


def playback(path="/Music/Semantic/A.flac", generation=1,
             event="virtualdj_active", source="virtualdj"):
    return {
        "_active_playback_source": source,
        "_playback_generation": generation,
        "_playback_event": event,
        "track_path": path,
        "time_seconds": 18.0,
        "bpm": 126.0,
        "beat_value": 12.0,
        "phrase_current": "verse",
        "stale": False,
    }


class SemanticTransport:
    def __init__(self):
        self._state = playback()
        self.lock = threading.Lock()
        self.decks = {}

    def snapshot_for_render(self):
        return dict(self._state)

    def developer_playback_state(self):
        return {}

    def structure_behavior_source(self):
        return "song_analyzer"


class SemanticBridge:
    def resolve(self, selected_source, transport_state):
        return {
            "selected_source": "song_analyzer",
            "effective_source": "song_analyzer",
            "eligible": True,
            "fallback_reason": None,
            "legacy_phrase": "verse",
            "mapped_behavior_bucket": "build",
            "song_analyzer_label": "Up 1",
            "projection": {"rich_current": {"energy": 1.0}},
        }


class ShowIntentSemanticHistoryTests(unittest.TestCase):
    def controller(self, capacity=SHOW_INTENT_SEMANTIC_HISTORY_MAX_FRAMES):
        transport = SemanticTransport()
        controller = DmxController(
            transport,
            SemanticBridge(),
            show_intent_semantic_history_capacity=capacity,
        )
        config = controller._clean_full_config(controller.default_config())
        config["auto_show"]["enabled"] = True
        return controller, transport, config

    def observe(self, controller, context, **values):
        osc = playback(**values)
        previous = controller._show_intent_shadow_last_track_identity
        controller._update_show_intent_shadow(context, osc)
        controller._observe_show_intent_shadow_frame(osc, previous)
        return controller.show_intent_observation_history()

    def test_default_history_is_empty_with_the_production_capacity(self):
        controller, _, _ = self.controller()
        state = controller.state()["show_intent_observation"]
        history = controller.show_intent_observation_history()

        self.assertEqual(0, state["semantic_history_count"])
        self.assertEqual(SHOW_INTENT_SEMANTIC_HISTORY_MAX_FRAMES, state["semantic_history_capacity"])
        self.assertEqual(0, state["semantic_history_dropped_frame_count"])
        self.assertFalse(state["semantic_history_truncated"])
        self.assertEqual([], history["semantic_history"])

    def test_one_record_is_added_per_observed_authoritative_frame(self):
        controller, _, _ = self.controller()
        controller.start_show_intent_observation()
        for _ in range(3):
            self.observe(controller, VALID_BUILD)
        history = controller.show_intent_observation_history()

        self.assertEqual(3, history["semantic_history_count"])
        self.assertEqual([1, 2, 3], [row["frame_sequence"] for row in history["semantic_history"]])
        self.assertEqual(3, controller.state()["show_intent_observation"]["authoritative_frame_count"])

    def test_record_schema_and_known_semantics_are_exact(self):
        clock = Clock()
        controller, _, _ = self.controller()
        expected_fields = {
            "frame_sequence", "session_seconds", "source_valid", "candidate_present",
            "input_section_bucket", "input_energy_modifier", "resolved_section_bucket",
            "resolved_energy_modifier", "retained_previous", "stale_warning",
            "lifecycle_reset", "lifecycle_reason", "track_key",
        }
        with patch("beatbeam_app.time.monotonic", clock):
            controller.start_show_intent_observation()
            clock.value = 2.0
            row = self.observe(controller, VALID_BUILD)["semantic_history"][0]

        self.assertEqual(expected_fields, set(row))
        self.assertEqual({
            "frame_sequence": 1, "session_seconds": 2.0, "source_valid": True,
            "candidate_present": True, "input_section_bucket": "build",
            "input_energy_modifier": 0.04, "resolved_section_bucket": "build",
            "resolved_energy_modifier": 0.04, "retained_previous": False,
            "stale_warning": False, "lifecycle_reset": False,
            "lifecycle_reason": None, "track_key": "track-0001",
        }, row)

    def test_candidate_absence_preserves_resolved_previous_with_null_input(self):
        controller, _, _ = self.controller()
        controller.start_show_intent_observation()
        self.observe(controller, VALID_BUILD)
        row = self.observe(controller, None)["semantic_history"][-1]

        self.assertEqual((None, None, "build", True, True), (
            row["input_section_bucket"], row["input_energy_modifier"],
            row["resolved_section_bucket"], row["retained_previous"], row["stale_warning"],
        ))

    def test_valid_canonical_unknown_is_retained_as_an_input_and_resolution(self):
        controller, _, _ = self.controller()
        controller.start_show_intent_observation()
        row = self.observe(controller, VALID_UNKNOWN)["semantic_history"][0]

        self.assertEqual((True, True, "unknown", "unknown"), (
            row["source_valid"], row["candidate_present"],
            row["input_section_bucket"], row["resolved_section_bucket"],
        ))

    def test_stale_then_candidate_return_history_reproduces_the_chronology(self):
        controller, _, _ = self.controller()
        controller.start_show_intent_observation()
        self.observe(controller, VALID_BUILD)
        self.observe(controller, None)
        self.observe(controller, None)
        history = self.observe(controller, VALID_UNKNOWN)["semantic_history"]

        self.assertEqual([
            ("build", False, False), ("build", True, True),
            ("build", True, True), ("unknown", False, False),
        ], [
            (row["resolved_section_bucket"], row["retained_previous"], row["stale_warning"])
            for row in history
        ])

    def test_lifecycle_record_has_opaque_current_track_key_without_a_path(self):
        controller, _, _ = self.controller()
        controller.start_show_intent_observation()
        self.observe(controller, VALID_BUILD, path="/Music/Semantic/A.flac")
        row = self.observe(
            controller, VALID_BUILD, path="/Music/Semantic/B.flac",
            generation=2, event="track_changed",
        )["semantic_history"][-1]
        serialized = json.dumps(controller.show_intent_observation_history())

        self.assertEqual((True, "track_changed", "track-0002"), (
            row["lifecycle_reset"], row["lifecycle_reason"], row["track_key"],
        ))
        self.assertNotIn("/Music/Semantic", serialized)
        self.assertNotIn("A.flac", serialized)
        self.assertNotIn("B.flac", serialized)

    def test_history_capacity_discards_only_oldest_records_with_an_explicit_count(self):
        controller, _, _ = self.controller(capacity=3)
        controller.start_show_intent_observation()
        for _ in range(5):
            self.observe(controller, VALID_BUILD)
        state = controller.state()["show_intent_observation"]
        history = controller.show_intent_observation_history()

        self.assertEqual((3, 3, 2, True), (
            state["semantic_history_count"], state["semantic_history_capacity"],
            state["semantic_history_dropped_frame_count"], state["semantic_history_truncated"],
        ))
        self.assertEqual([3, 4, 5], [row["frame_sequence"] for row in history["semantic_history"]])

    def test_state_has_summary_but_never_the_full_history(self):
        controller, _, _ = self.controller()
        controller.start_show_intent_observation()
        self.observe(controller, VALID_BUILD)
        state = controller.state()

        self.assertNotIn("semantic_history", state["dmx"] if "dmx" in state else state)
        self.assertNotIn("semantic_history", state["show_intent_observation"])
        self.assertEqual(1, state["show_intent_observation"]["semantic_history_count"])

    def test_history_reads_and_http_endpoint_are_passive(self):
        controller, _, _ = self.controller()
        controller.start_show_intent_observation()
        self.observe(controller, VALID_BUILD)
        before = controller.state()["show_intent_observation"]
        server = beatbeam_app.ThreadingHTTPServer(("127.0.0.1", 0), beatbeam_app.AppHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(beatbeam_app, "DMX", controller):
                url = f"http://127.0.0.1:{server.server_port}/api/show-intent-observation/history"
                first = json.load(urllib.request.urlopen(url))
                second = json.load(urllib.request.urlopen(url))
            self.assertEqual(first, second)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1.0)
        self.assertEqual(before, controller.state()["show_intent_observation"])

    def test_stop_and_double_start_stop_freeze_history(self):
        controller, _, _ = self.controller()
        controller.start_show_intent_observation()
        self.observe(controller, VALID_BUILD)
        controller.start_show_intent_observation()
        active = controller.show_intent_observation_history()
        self.assertEqual(1, active["semantic_history_count"])
        controller.stop_show_intent_observation()
        frozen = controller.show_intent_observation_history()
        controller.stop_show_intent_observation()

        self.assertFalse(frozen["session_active"])
        self.assertEqual(frozen, controller.show_intent_observation_history())

    def test_preview_only_render_ticks_produce_history_without_physical_dmx(self):
        controller, _, _ = self.controller()
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"]["enabled"] = True
        controller.render_active = True
        controller.start_show_intent_observation()
        for _ in range(3):
            self.assertFalse(controller._render_tick())
        state = controller.state()

        self.assertFalse(state["connected"])
        self.assertIsNone(state["last_sent"])
        self.assertEqual(3, state["show_intent_observation"]["semantic_history_count"])

    def test_history_observability_does_not_change_auto_show_render_or_resolved_intent(self):
        controller, transport, config = self.controller()
        auto_show = controller._auto_show_state(transport.snapshot_for_render(), config["auto_show"])
        baseline = controller._render_values(
            1.0, advance_motion=False, config=config,
            osc=transport.snapshot_for_render(), auto_show=auto_show,
        )
        controller.start_show_intent_observation()
        self.observe(controller, VALID_BUILD)
        controller.show_intent_observation_history()
        current_auto_show = controller._auto_show_state(
            transport.snapshot_for_render(), config["auto_show"]
        )
        current = controller._render_values(
            1.0, advance_motion=False, config=config,
            osc=transport.snapshot_for_render(), auto_show=current_auto_show,
        )

        self.assertEqual(baseline, current)
        self.assertEqual("build", controller._show_intent_shadow_resolved.section_bucket)


if __name__ == "__main__":
    unittest.main()
