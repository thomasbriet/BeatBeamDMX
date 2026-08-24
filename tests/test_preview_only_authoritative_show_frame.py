import json
import threading
import unittest
from unittest.mock import Mock, patch

from beatbeam_app import DmxController
from show_interpreter_input_adapter import ShowInterpreterEffectiveContext


class PreviewTransport:
    def __init__(self):
        self.state = {
            "_active_playback_source": "virtualdj",
            "_playback_generation": 1,
            "_playback_event": "virtualdj_active",
            "track_path": "/Music/Preview/Track.flac",
            "time_seconds": 12.0,
            "bpm": 126.0,
            "beat_value": 24.0,
            "phrase_current": "verse",
            "stale": False,
        }
        self.lock = threading.Lock()
        self.decks = {}

    def snapshot_for_render(self):
        return dict(self.state)

    def developer_playback_state(self):
        return {}

    def structure_behavior_source(self):
        return "song_analyzer"


class PreviewBridge:
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


class FakeDmx:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, values):
        self.sent.append(dict(values))

    def close(self):
        self.closed = True


class PreviewOnlyAuthoritativeShowFrameTests(unittest.TestCase):
    def controller(self):
        transport = PreviewTransport()
        controller = DmxController(transport, PreviewBridge())
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"]["enabled"] = True
        controller.render_active = True
        return controller, transport

    def tick(self, controller):
        self.assertFalse(controller._render_tick())

    def test_disconnected_engine_tick_updates_render_diagnostics_without_last_sent(self):
        controller, _ = self.controller()
        self.tick(controller)
        first = controller.state()
        self.tick(controller)
        second = controller.state()

        self.assertFalse(first["connected"])
        self.assertTrue(first["render_active"])
        self.assertEqual(1, first["render_frame_sequence"])
        self.assertIsNotNone(first["last_rendered"])
        self.assertEqual(2, second["render_frame_sequence"])
        self.assertGreaterEqual(second["last_rendered"], first["last_rendered"])
        self.assertIsNone(second["last_sent"])

    def test_disconnected_tick_runs_each_authoritative_stage_once_without_send(self):
        controller, _ = self.controller()
        controller._auto_show_evaluation = Mock(wraps=controller._auto_show_evaluation)
        controller._update_show_intent_shadow = Mock(wraps=controller._update_show_intent_shadow)
        controller._observe_show_intent_shadow_frame = Mock(
            wraps=controller._observe_show_intent_shadow_frame
        )
        controller._render_values = Mock(wraps=controller._render_values)
        controller._send_dmx_frame = Mock(wraps=controller._send_dmx_frame)

        self.tick(controller)

        self.assertEqual(1, controller._auto_show_evaluation.call_count)
        self.assertEqual(1, controller._update_show_intent_shadow.call_count)
        self.assertEqual(1, controller._observe_show_intent_shadow_frame.call_count)
        self.assertEqual(1, controller._render_values.call_count)
        controller._send_dmx_frame.assert_not_called()

    def test_observation_accumulates_authoritative_frames_without_dmx(self):
        controller, _ = self.controller()
        controller.start_show_intent_observation()
        for _ in range(3):
            self.tick(controller)
        observation = controller.state()["show_intent_observation"]

        self.assertTrue(observation["session_active"])
        self.assertEqual(3, observation["frame_sequence"])
        self.assertEqual(3, observation["authoritative_frame_count"])
        self.assertIsNone(controller.state()["last_sent"])

    def test_state_reads_are_passive(self):
        controller, _ = self.controller()
        controller.start_show_intent_observation()
        self.tick(controller)
        before = controller.state()
        resolved = controller._show_intent_shadow_resolved
        for _ in range(5):
            self.assertEqual(before, controller.state())

        after = controller.state()
        self.assertEqual(before["render_frame_sequence"], after["render_frame_sequence"])
        self.assertEqual(
            before["show_intent_observation"]["authoritative_frame_count"],
            after["show_intent_observation"]["authoritative_frame_count"],
        )
        self.assertIs(resolved, controller._show_intent_shadow_resolved)

    def test_last_sent_remains_physical_only_while_last_rendered_advances(self):
        controller, _ = self.controller()
        self.tick(controller)
        first = controller.state()
        self.tick(controller)
        second = controller.state()

        self.assertIsNone(first["last_sent"])
        self.assertIsNone(second["last_sent"])
        self.assertIsNotNone(first["last_rendered"])
        self.assertGreaterEqual(second["last_rendered"], first["last_rendered"])

    def test_connected_tick_renders_once_and_sends_that_authoritative_frame_once(self):
        controller, _ = self.controller()
        dmx = FakeDmx()
        controller.dmx = dmx
        controller.connected = True
        controller.running = True
        controller._render_values = Mock(wraps=controller._render_values)

        self.tick(controller)

        self.assertEqual(1, controller._render_values.call_count)
        self.assertEqual(1, len(dmx.sent))
        self.assertEqual(controller.current_values, dmx.sent[0])
        self.assertIsNotNone(controller.last_sent)

    def test_connect_disconnect_and_reconnect_do_not_duplicate_the_existing_engine(self):
        controller, _ = self.controller()
        entered = threading.Event()
        release = threading.Event()

        def blocked_loop():
            entered.set()
            release.wait(1.0)

        controller._render_loop = blocked_loop
        self.assertTrue(controller.start_show_engine())
        self.assertTrue(entered.wait(1.0))
        engine = controller.render_thread
        first, second = FakeDmx(), FakeDmx()
        with patch("beatbeam_app.EnttecOpenDmx", side_effect=(first, second)):
            controller.connect("fake-a")
            self.assertIs(engine, controller.render_thread)
            controller.disconnect()
            self.assertTrue(controller.render_active)
            self.assertIs(engine, controller.render_thread)
            controller.connect("fake-b")
            self.assertIs(engine, controller.render_thread)
            controller.disconnect()
        release.set()
        controller.stop_show_engine()

    def test_shutdown_stops_the_engine_and_prevents_new_ticks(self):
        controller, _ = self.controller()
        self.tick(controller)
        sequence = controller.render_frame_sequence
        with patch.object(controller, "disconnect") as disconnect:
            controller.shutdown()
        self.assertFalse(controller.render_active)
        self.assertFalse(controller._render_tick())
        self.assertEqual(sequence, controller.render_frame_sequence)
        disconnect.assert_called_once()

    def test_connected_render_values_match_existing_auto_show_rendering(self):
        controller, transport = self.controller()
        expected = DmxController(PreviewTransport(), PreviewBridge())
        expected.config = expected._clean_full_config(expected.default_config())
        expected.config["auto_show"]["enabled"] = True
        with patch("beatbeam_app.time.time", return_value=300.0):
            auto_show = expected._auto_show_state(
                transport.snapshot_for_render(), expected.config["auto_show"]
            )
            expected_values = expected._render_values(
                300.0,
                config=expected.config,
                osc=transport.snapshot_for_render(),
                auto_show=auto_show,
            )
            self.tick(controller)

        self.assertEqual(expected_values, controller.current_values)

    def test_preview_state_is_json_safe_without_dmx(self):
        controller, _ = self.controller()
        self.tick(controller)
        state = controller.state()

        self.assertFalse(state["connected"])
        self.assertTrue(state["slot_previews"])
        self.assertTrue(state["values"])
        self.assertTrue(state["render_active"])
        self.assertEqual(1, state["render_frame_sequence"])
        json.dumps(state)


if __name__ == "__main__":
    unittest.main()
