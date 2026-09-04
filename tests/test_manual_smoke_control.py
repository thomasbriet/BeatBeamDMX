import unittest

import beatbeam_app


class _Osc:
    def snapshot_for_render(self):
        return {"stale": True, "beat_value": 0, "bpm": 120}

    def developer_playback_state(self):
        return {"source": "none"}


class ManualSmokeControlTests(unittest.TestCase):
    def setUp(self):
        self.controller = beatbeam_app.DmxController(_Osc())
        blaze = self.controller.default_slot_config(
            "blaze", fixture_id="beamz_blaze_series_rgba_fogger", mode="8ch", address=200
        )
        self.controller.config = self.controller._clean_full_config({
            **self.controller.default_config(), "slot_order": ["blaze"], "slots": {"blaze": blaze},
        })

    def test_hold_owns_only_blaze_fog_and_defaults_to_fifty_percent(self):
        self.assertEqual(50, self.controller._manual_smoke_state_locked()["output_percent"])
        self.controller.start_manual_smoke_hold()
        output = self.controller._apply_manual_smoke_overlay_locked(
            {200: 12, 201: 90, 202: 20, 203: 21, 204: 22, 205: 23, 206: 24, 207: 25}, self.controller.config
        )
        self.assertEqual(128, output[200])
        self.assertEqual(90, output[201])
        self.assertEqual([20, 21, 22, 23, 24, 25], [output[channel] for channel in range(202, 208)])

    def test_release_blackout_disconnect_and_invalidated_profile_clear_smoke(self):
        self.controller.start_manual_smoke_hold()
        self.controller.release_manual_smoke("test")
        self.assertFalse(self.controller._manual_smoke_state_locked()["active"])
        self.controller.start_manual_smoke_hold()
        self.controller.blackout()
        self.assertFalse(self.controller._manual_smoke_state_locked()["active"])
        self.controller.config["blackout_active"] = False
        self.controller.start_manual_smoke_hold()
        self.controller.disconnect()
        self.assertFalse(self.controller._manual_smoke_state_locked()["active"])

    def test_master_dimmer_does_not_change_manual_fog(self):
        self.controller.config["smoke_output_percent"] = 75
        self.controller.start_manual_smoke_hold()
        output = self.controller._apply_manual_smoke_overlay_locked({200: 0, 201: 255}, self.controller.config)
        blaze = self.controller.config["slots"]["blaze"]
        dimmed = self.controller._apply_master_dimmer_to_slot_values(blaze, output, 0.25)
        self.assertEqual(191, dimmed[200])
        self.assertEqual(64, dimmed[201])
