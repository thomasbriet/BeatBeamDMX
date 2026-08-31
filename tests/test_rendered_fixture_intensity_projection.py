import threading
import unittest

from beatbeam_app import DmxController, _remote_live_output_preview


class _Transport:
    def __init__(self):
        self.lock = threading.Lock()

    def snapshot_for_render(self):
        return {
            "_active_playback_source": "virtualdj",
            "_playback_generation": 1,
            "_playback_event": "virtualdj_active",
            "track_path": "/Music/Projection/Track.flac",
            "time_seconds": 12.0,
            "bpm": 126.0,
            "beat_value": 24.0,
            "phrase_current": "verse",
            "stale": False,
        }

    def developer_playback_state(self):
        return {}

    def structure_behavior_source(self):
        return "song_analyzer"


class _Bridge:
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


class RenderedFixtureIntensityProjectionTests(unittest.TestCase):
    def make_controller(self):
        controller = DmxController(_Transport(), _Bridge())
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"]["enabled"] = True
        controller.render_active = True
        return controller

    def render(self, controller, master, color):
        controller.config["master_dimmer"] = master
        controller.config["auto_show"]["override_color"] = color
        self.assertFalse(controller._render_tick())
        state = controller.state()
        remote = {
            fixture["id"]: fixture
            for fixture in _remote_live_output_preview(state)["fixtures"]
        }
        return state["slot_previews"], remote

    def test_master_scales_shared_intensity_without_dimming_resolved_color_identity(self):
        controller = self.make_controller()
        full, remote_full = self.render(controller, 1.0, "red")
        half, remote_half = self.render(controller, 0.5, "red")
        dark, remote_dark = self.render(controller, 0.0, "red")

        for slot_id in ("head", "par"):
            with self.subTest(slot=slot_id):
                self.assertAlmostEqual(
                    full[slot_id]["effective_intensity"] * 0.5,
                    half[slot_id]["effective_intensity"],
                    places=6,
                )
                self.assertEqual(0.0, dark[slot_id]["effective_intensity"])
                self.assertEqual(
                    half[slot_id]["effective_intensity"],
                    remote_half[slot_id]["effective_intensity"],
                )
                self.assertEqual(0.0, remote_dark[slot_id]["effective_intensity"])

        blue, _ = self.render(controller, 0.5, "blue")
        self.assertEqual(
            half["par"]["effective_intensity"], blue["par"]["effective_intensity"]
        )
        self.assertEqual(255, remote_full["par"]["resolved_red"])
