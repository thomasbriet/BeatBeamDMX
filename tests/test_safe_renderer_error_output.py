import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from beatbeam_app import DmxController
from enttec_open_dmx import find_fixture, find_mode, load_fixture_profiles


FIXTURES = load_fixture_profiles()


class RenderTransport:
    def __init__(self):
        self.lock = threading.Lock()
        self.decks = {}

    def snapshot_for_render(self):
        return {
            "stale": True,
            "beat_value": 12.25,
            "bpm": 124.0,
            "phrase_current": "verse",
            "strobe_active": False,
        }

    def developer_playback_state(self):
        return {"source": "none"}


class RecordingDmx:
    def __init__(self, fail=False):
        self.frames = []
        self.fail = fail

    def send(self, values):
        self.frames.append(dict(values))
        if self.fail:
            raise RuntimeError("synthetic dmx dispatch failure")


class SafeRendererErrorOutputTests(unittest.TestCase):
    def setUp(self):
        self.config_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.config_directory.cleanup)
        self.controller = DmxController(
            RenderTransport(),
            config_path=Path(self.config_directory.name) / "beatbeam_config.json",
        )
        slots = {
            "mover_8": self._slot(
                "mover_8", "shehds_led_wash_7x12w_rgbw_moving_head", "10ch", 1,
                pan=61, tilt=173, pan_tilt_speed=37,
            ),
            "mover_16": self._slot(
                "mover_16", "shehds_led_wash_7x12w_rgbw_moving_head", "15ch", 20,
                pan=203, tilt=77, pan_tilt_speed=49,
            ),
            "par": self._slot("par", "shehds_flat_par_12x3w_rgbw", "8ch", 40),
            "blaze": self._slot("blaze", "beamz_blaze_series_rgba_fogger", "8ch", 60),
            "bee": self._slot(
                "bee", "generic_smart_bee_eye_pattern_moving_head", "15ch", 80,
                pan=39, tilt=211, pan_tilt_speed=29,
            ),
            "rgb_only": self._slot("rgb_only", "uking_zq06016", "C001", 110),
        }
        slots["bee"]["extra_values"] = {
            "spot_dimmer": 210,
            "spot_strobe": 230,
            "pattern_plate": 35,
            "z_rotation": 180,
            "macro_function": 255,
        }
        self.controller.config = self.controller._clean_full_config({
            **self.controller.default_config(),
            "active_slot": "mover_8",
            "slot_order": list(slots),
            "slots": slots,
        })
        self.controller.last_valid_render_config = self.controller.config
        self.output = RecordingDmx()
        self.controller.dmx = self.output
        self.controller.render_active = True
        self.controller.connected = True
        self.controller.running = True

    def _slot(self, slot_id, fixture_id, mode, address, **updates):
        slot = self.controller.default_slot_config(
            slot_id, fixture_id=fixture_id, mode=mode, address=address
        )
        slot.update({
            "sync_enabled": True,
            "dimmer": 224,
            "strobe": 0,
            "program": 0,
            "speed": 0,
            **updates,
        })
        return slot

    def _channel(self, slot_id, *, channel_type=None, control=None):
        slot = self.controller.config["slots"][slot_id]
        fixture = find_fixture(FIXTURES, slot["fixture"])
        mode = find_mode(fixture, slot["mode"])
        definition = next(
            channel for channel in mode["channels"]
            if (channel_type is None or channel.get("type") == channel_type)
            and (control is None or channel.get("control") == control)
        )
        return int(slot["address"]) + int(definition["offset"]) - 1

    def _fail_next_render(self, message="synthetic renderer failure"):
        return patch.object(
            self.controller,
            "_auto_show_evaluation",
            side_effect=RuntimeError(message),
        )

    def test_failure_before_normal_frame_dispatches_profile_aware_safe_bytes(self):
        with self._fail_next_render("early renderer failure"):
            self.assertFalse(self.controller._render_tick())

        self.assertEqual(1, len(self.output.frames))
        safe = self.output.frames[-1]
        state = self.controller.state()
        health = state["renderer_health"]
        self.assertEqual("early renderer failure", health["error"])
        self.assertEqual("SAFE_RENDERER_FAILURE", health["output_state"])
        self.assertEqual("CONFIGURED_POSITION_FALLBACK", health["safe_output"]["movement_policy"])
        self.assertEqual(safe, state["rendered_final_values"])
        self.assertEqual({}, state["slot_previews"])

        self.assertEqual(61, safe[self._channel("mover_8", channel_type="pan")])
        self.assertEqual(173, safe[self._channel("mover_8", channel_type="tilt")])
        self.assertEqual(203, safe[self._channel("mover_16", channel_type="pan")])
        self.assertEqual(0, safe[self._channel("mover_16", channel_type="pan_fine")])
        self.assertEqual(77, safe[self._channel("mover_16", channel_type="tilt")])
        self.assertEqual(0, safe[self._channel("mover_16", channel_type="tilt_fine")])

        for slot_id in ("mover_8", "mover_16", "par", "blaze", "bee"):
            fixture = find_fixture(FIXTURES, self.controller.config["slots"][slot_id]["fixture"])
            mode = find_mode(fixture, self.controller.config["slots"][slot_id]["mode"])
            address = int(self.controller.config["slots"][slot_id]["address"])
            for channel in mode["channels"]:
                if channel.get("type") in {"pan", "pan_fine", "tilt", "tilt_fine", "pan_tilt_speed"}:
                    continue
                absolute = address + int(channel["offset"]) - 1
                self.assertEqual(0, safe[absolute], (slot_id, channel))
        self.assertEqual(
            [0, 0, 0],
            [safe[channel] for channel in range(110, 113)],
        )

    def test_failure_after_valid_frame_holds_motors_and_releases_optical_effects(self):
        self.controller.config["auto_show"]["enabled"] = True
        self.controller.config["auto_show"]["override_manual_strobe"] = True
        self.controller.config["auto_show"]["override_all_on"] = True
        self.controller.start_manual_smoke_hold()
        self.assertFalse(self.controller._render_tick())
        bright = self.output.frames[-1]
        self.assertGreater(bright[self._channel("blaze", control="fog")], 0)
        self.assertGreater(bright[self._channel("par", channel_type="intensity")], 0)
        self.assertGreater(bright[self._channel("par", channel_type="strobe")], 0)

        self.controller.active_one_shot_cue = {"id": "white_hit"}
        with self._fail_next_render():
            self.assertFalse(self.controller._render_tick())
        safe = self.output.frames[-1]

        for slot_id in ("mover_8", "mover_16", "bee"):
            fixture = find_fixture(FIXTURES, self.controller.config["slots"][slot_id]["fixture"])
            mode = find_mode(fixture, self.controller.config["slots"][slot_id]["mode"])
            address = int(self.controller.config["slots"][slot_id]["address"])
            for channel in mode["channels"]:
                if channel.get("type") not in {"pan", "pan_fine", "tilt", "tilt_fine", "pan_tilt_speed"}:
                    continue
                absolute = address + int(channel["offset"]) - 1
                self.assertEqual(bright[absolute], safe[absolute], (slot_id, channel))

        self.assertEqual(0, safe[self._channel("blaze", control="fog")])
        self.assertEqual(0, safe[self._channel("blaze", channel_type="intensity")])
        self.assertEqual(0, safe[self._channel("blaze", channel_type="strobe")])
        self.assertEqual(0, safe[self._channel("blaze", control="macro")])
        self.assertEqual(0, safe[self._channel("par", channel_type="intensity")])
        self.assertEqual(0, safe[self._channel("par", channel_type="strobe")])
        self.assertEqual(0, safe[self._channel("bee", control="spot_dimmer")])
        self.assertEqual(0, safe[self._channel("bee", control="spot_strobe")])
        self.assertEqual(0, safe[self._channel("bee", control="macro_function")])
        self.assertNotEqual(bright, safe)
        self.assertFalse(self.controller.manual_smoke_active)
        self.assertFalse(self.controller.config["auto_show"]["override_manual_strobe"])
        self.assertIsNone(self.controller.active_one_shot_cue)
        self.assertEqual(
            "HOLD_LAST_VALID_FINAL_BYTES",
            self.controller.state()["renderer_health"]["safe_output"]["movement_policy"],
        )

    def test_repeated_failures_are_stable_and_recovery_uses_only_new_valid_output(self):
        self.controller.config["auto_show"]["enabled"] = True
        self.controller.config["auto_show"]["override_manual_strobe"] = True
        self.controller.start_manual_smoke_hold()
        self.controller.active_one_shot_cue = {"id": "white_hit"}
        with self._fail_next_render("repeated renderer failure"):
            for _ in range(3):
                self.assertFalse(self.controller._render_tick())

        self.assertEqual(self.output.frames[-1], self.output.frames[-2])
        self.assertEqual(self.output.frames[-2], self.output.frames[-3])
        health = self.controller.state()["renderer_health"]
        self.assertEqual(3, health["consecutive_failures"])
        self.assertEqual(1, health["failure_events"])
        self.assertEqual(3, health["safe_frame_sequence"])
        self.assertEqual("repeated renderer failure", health["error"])

        self.assertFalse(self.controller._render_tick())
        recovered = self.output.frames[-1]
        recovered_state = self.controller.state()
        self.assertEqual("NORMAL", recovered_state["renderer_health"]["output_state"])
        self.assertIsNone(recovered_state["renderer_health"]["error"])
        self.assertEqual(0, recovered_state["renderer_health"]["consecutive_failures"])
        self.assertFalse(recovered_state["renderer_health"]["safe_output"]["active"])
        self.assertEqual(0, recovered[self._channel("blaze", control="fog")])
        self.assertEqual(0, recovered[self._channel("par", channel_type="strobe")])
        self.assertIsNone(self.controller.active_one_shot_cue)
        self.assertTrue(recovered_state["rendered_motion"])

    def test_safe_renderer_frame_dispatch_failure_remains_a_separate_fault(self):
        self.output = RecordingDmx(fail=True)
        self.controller.dmx = self.output
        with self._fail_next_render("renderer computation failed"):
            self.assertTrue(self.controller._render_tick())

        state = self.controller.state()
        self.assertEqual("renderer computation failed", state["renderer_health"]["error"])
        self.assertEqual("SAFE_RENDERER_FAILURE", state["renderer_health"]["output_state"])
        self.assertEqual(1, state["playback"]["dmx_dispatch_failures"])
        self.assertIn("synthetic dmx dispatch failure", state["error"])
        self.assertEqual(state["rendered_final_values"], self.output.frames[-1])


if __name__ == "__main__":
    unittest.main()
