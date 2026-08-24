import json
import threading
import unittest
import urllib.request
from unittest.mock import patch

import beatbeam_app
from beatbeam_app import DmxController
from show_interpreter_input_adapter import ShowInterpreterEffectiveContext


VALID_A = ShowInterpreterEffectiveContext(True, "build", 0.04)
VALID_B = ShowInterpreterEffectiveContext(True, "break", -0.04)
VALID_UNKNOWN = ShowInterpreterEffectiveContext(True, "unknown", 0.0)


class Clock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value


def playback(path="/Music/Observation/A.flac", generation=1,
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


class ObservationTransport:
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


class ObservationBridge:
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


class ShowIntentShadowObservationTests(unittest.TestCase):
    def controller(self):
        transport = ObservationTransport()
        controller = DmxController(transport, ObservationBridge())
        config = controller._clean_full_config(controller.default_config())
        config["auto_show"]["enabled"] = True
        return controller, transport, config

    def observation(self, controller):
        return controller.state()["show_intent_observation"]

    def observe(self, controller, context, **values):
        osc = playback(**values)
        previous_track_identity = controller._show_intent_shadow_last_track_identity
        controller._update_show_intent_shadow(context, osc)
        controller._observe_show_intent_shadow_frame(osc, previous_track_identity)
        return self.observation(controller)

    def test_default_is_inactive_and_start_stop_are_idempotent(self):
        clock = Clock()
        controller, _, _ = self.controller()
        with patch("beatbeam_app.time.monotonic", clock):
            initial = self.observation(controller)
            self.assertFalse(initial["session_active"])
            self.assertEqual(0, initial["authoritative_frame_count"])
            self.assertEqual([], initial["lifecycle_reset_records"])

            started = controller.start_show_intent_observation()
            self.assertTrue(started["session_active"])
            self.observe(controller, VALID_A)
            repeated_start = controller.start_show_intent_observation()
            self.assertEqual(1, repeated_start["authoritative_frame_count"])

            clock.value = 3.0
            stopped = controller.stop_show_intent_observation()
            self.assertFalse(stopped["session_active"])
            self.assertEqual(3.0, stopped["session_elapsed_seconds"])
            self.assertEqual(stopped, controller.stop_show_intent_observation())

    def test_only_authoritative_frame_observation_mutates_counters(self):
        clock = Clock()
        controller, transport, config = self.controller()
        with patch("beatbeam_app.time.monotonic", clock):
            controller.start_show_intent_observation()
            controller._update_show_intent_shadow(VALID_A, transport.snapshot_for_render())
            controller._auto_show_state(transport.snapshot_for_render(), config["auto_show"])
            before = self.observation(controller)
            self.assertEqual(0, before["authoritative_frame_count"])
            self.assertEqual(before, self.observation(controller))

            controller._auto_show_evaluation(transport.snapshot_for_render(), config["auto_show"])
            self.assertEqual(before, self.observation(controller))
            self.observe(controller, VALID_A)
            self.assertEqual(1, self.observation(controller)["authoritative_frame_count"])

    def test_send_loop_accumulates_once_after_the_authoritative_shadow_update(self):
        clock = Clock()
        controller, transport, config = self.controller()
        auto_show = controller._auto_show_state(transport.snapshot_for_render(), config["auto_show"])
        with patch("beatbeam_app.time.monotonic", clock):
            controller.start_show_intent_observation()
            controller._auto_show_evaluation = lambda *_: (auto_show, VALID_A)
            controller._render_values = lambda *args, **kwargs: setattr(controller, "running", False) or {}
            controller._build_slot_previews = lambda *args, **kwargs: {}
            controller._send_dmx_frame = lambda *args, **kwargs: None
            controller.running = True
            controller.dmx = object()
            controller._send_loop()
        observation = self.observation(controller)
        self.assertEqual((1, 1, 1, 1), (
            observation["frame_sequence"], observation["authoritative_frame_count"],
            observation["source_valid_frame_count"], observation["candidate_present_frame_count"],
        ))

    def test_frame_and_unknown_counters_are_exact_and_distinct(self):
        clock = Clock()
        controller, _, _ = self.controller()
        with patch("beatbeam_app.time.monotonic", clock):
            controller.start_show_intent_observation()
            self.observe(controller, VALID_UNKNOWN)
            clock.value = 1.0
            self.observe(controller, None, path="/Music/Observation/B.flac",
                         generation=2, event="track_changed")
        observation = self.observation(controller)
        self.assertEqual((2, 2, 1, 1, 0, 0), (
            observation["frame_sequence"], observation["authoritative_frame_count"],
            observation["source_valid_frame_count"], observation["candidate_present_frame_count"],
            observation["retained_previous_frame_count"], observation["stale_frame_count"],
        ))
        self.assertEqual(2, observation["resolved_unknown_frame_count"])
        self.assertEqual(1, observation["valid_canonical_unknown_frame_count"])

    def test_stale_episode_uses_monotonic_duration_not_fps(self):
        clock = Clock()
        controller, _, _ = self.controller()
        with patch("beatbeam_app.time.monotonic", clock):
            controller.start_show_intent_observation()
            clock.value = 1.0
            self.observe(controller, VALID_A)
            clock.value = 2.0
            self.observe(controller, None)
            clock.value = 5.0
            self.observe(controller, None)
            clock.value = 7.0
            self.observe(controller, VALID_B)
        observation = self.observation(controller)
        self.assertEqual((1, 2, 5.0, 5.0, 0.0), (
            observation["stale_episode_count"], observation["stale_frame_count"],
            observation["stale_total_seconds"], observation["stale_max_seconds"],
            observation["stale_current_seconds"],
        ))

    def test_open_and_multiple_stale_episodes_finalize_on_stop(self):
        clock = Clock()
        controller, _, _ = self.controller()
        with patch("beatbeam_app.time.monotonic", clock):
            controller.start_show_intent_observation()
            clock.value = 1.0
            self.observe(controller, VALID_A)
            clock.value = 2.0
            self.observe(controller, None)
            clock.value = 5.0
            self.observe(controller, VALID_B)
            clock.value = 7.0
            self.observe(controller, None)
            clock.value = 10.0
            stopped = controller.stop_show_intent_observation()
        self.assertEqual((2, 6.0, 3.0, 0.0), (
            stopped["stale_episode_count"], stopped["stale_total_seconds"],
            stopped["stale_max_seconds"], stopped["stale_current_seconds"],
        ))

    def test_lifecycle_records_use_opaque_session_scoped_track_keys(self):
        clock = Clock()
        controller, _, _ = self.controller()
        path_a, path_b = "/Music/Observation/A.flac", "/Music/Observation/B.flac"
        with patch("beatbeam_app.time.monotonic", clock):
            controller.start_show_intent_observation()
            self.observe(controller, VALID_A, path=path_a)
            clock.value = 2.0
            self.observe(controller, VALID_B, path=path_b, generation=2, event="track_changed")
            clock.value = 3.0
            self.observe(controller, VALID_A, path=path_a, generation=3, event="track_changed")
            observation = self.observation(controller)
            self.assertEqual(2, observation["lifecycle_reset_count"])
            self.assertEqual({"track_changed": 2}, observation["lifecycle_resets_by_reason"])
            first, second = observation["lifecycle_reset_records"]
            self.assertEqual((2, 2.0, "track_changed", "track-0001", "track-0002", 2, "track_changed"), (
                first["frame_sequence"], first["session_seconds"], first["reason"],
                first["previous_track_key"], first["current_track_key"],
                first["generation"], first["playback_event"],
            ))
            self.assertEqual(("track-0002", "track-0001"), (
                second["previous_track_key"], second["current_track_key"],
            ))
            serialized = json.dumps(observation)
            self.assertNotIn(path_a, serialized)
            self.assertNotIn(path_b, serialized)

            controller.stop_show_intent_observation()
            controller.start_show_intent_observation()
            self.assertEqual({}, controller._show_intent_observation_track_keys)

    def test_lifecycle_reasons_and_session_continue_across_tracks(self):
        clock = Clock()
        controller, _, _ = self.controller()
        with patch("beatbeam_app.time.monotonic", clock):
            controller.start_show_intent_observation()
            self.observe(controller, VALID_A)
            clock.value = 1.0
            self.observe(controller, VALID_B, path="/Music/Observation/B.flac",
                         generation=2, event="track_changed")
            clock.value = 2.0
            self.observe(controller, VALID_A, path="/Music/Observation/B.flac",
                         generation=3, event="position_jump_backward")
            clock.value = 3.0
            self.observe(controller, VALID_B, path="/Music/Observation/B.flac",
                         generation=4, event="deck_changed")
        observation = self.observation(controller)
        self.assertTrue(observation["session_active"])
        self.assertEqual(4, observation["authoritative_frame_count"])
        self.assertEqual(3, observation["lifecycle_reset_count"])
        self.assertEqual({
            "track_changed": 1,
            "position_jump_backward": 1,
            "deck_changed": 1,
        }, observation["lifecycle_resets_by_reason"])

    def test_passive_reads_and_observation_do_not_change_production(self):
        clock = Clock()
        controller, transport, config = self.controller()
        with patch("beatbeam_app.time.monotonic", clock):
            controller.start_show_intent_observation()
            self.observe(controller, VALID_A)
            frozen = self.observation(controller)
            self.assertEqual(frozen, self.observation(controller))
            controller.stop_show_intent_observation()
            stopped = self.observation(controller)
            self.assertEqual(stopped, self.observation(controller))
        plain, plain_transport, plain_config = self.controller()
        for _ in range(5):
            plain.state()
        plain_auto = plain._auto_show_state(
            plain_transport.snapshot_for_render(), plain_config["auto_show"]
        )
        observed_auto = controller._auto_show_state(
            transport.snapshot_for_render(), config["auto_show"]
        )
        self.assertEqual(plain_auto, observed_auto)
        self.assertEqual(
            plain._render_values(1.0, advance_motion=False, config=plain_config,
                                 osc=plain_transport.snapshot_for_render(), auto_show=plain_auto),
            controller._render_values(1.0, advance_motion=False, config=config,
                                      osc=transport.snapshot_for_render(), auto_show=observed_auto),
        )

    def test_api_start_and_stop_return_observation_state(self):
        controller, _, _ = self.controller()
        server = beatbeam_app.ThreadingHTTPServer(("127.0.0.1", 0), beatbeam_app.AppHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(beatbeam_app, "DMX", controller):
                base = f"http://127.0.0.1:{server.server_port}"
                for action, expected in (("start", True), ("stop", False)):
                    request = urllib.request.Request(
                        f"{base}/api/show-intent-observation/{action}",
                        data=b"{}", method="POST", headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(request) as response:
                        payload = json.loads(response.read())
                    self.assertEqual(expected, payload["dmx"]["show_intent_observation"]["session_active"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1.0)


if __name__ == "__main__":
    unittest.main()
