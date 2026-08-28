import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import beatbeam_app


def fixture_state(*, mode="DYNAMIC_COMPOSER_ENABLED", source="dynamic_composer",
                  fallback=None, renderer_healthy=True, connected=True,
                  readiness="READY", blackout=False, override=False,
                  current_rme=None):
    return {
        "live_ui": {
            "availability": "available", "transport_state": "advancing",
            "track_title": "Current Track", "track_artist": "Artist",
            "active_deck_number": 1, "position_milliseconds": 12_000,
            "bpm": 128.0, "beat_number": 2, "bar_number": 9, "phrase": "chorus",
            "decks": [{"deck_number": 1, "is_loaded": True, "is_active": True,
                       "is_playing": True, "is_master": True, "track_title": "Current Track",
                       "track_artist": "Artist", "analysis_status": readiness,
                       "prewarm_status": readiness}],
        },
        "dmx": {
            "connected": connected, "port": "/dev/cu.usbserial-test", "error": None,
            "production_show_mode": mode, "blackout_active": blackout,
            "renderer_health": {"active": True, "healthy": renderer_healthy,
                                "error": None if renderer_healthy else "renderer fault",
                                "render_frame_sequence": 42},
            "playback": {"dmx_dispatch_failures": 0},
            "production_show_selector": {
                "production_show_mode": mode, "production_show_source": source,
                "fallback_active": fallback is not None, "fallback_reason": fallback,
                "dynamic_composer_eligible": True, "dynamic_composer_active": source == "dynamic_composer",
                "effective_intensity": .78, "analyzed_intensity": .72,
                "live_intensity_valid": True, "current_rme": current_rme,
                "event_envelope": {"active": False},
            },
            "auto_show": {
                "energy": .72, "movement": .45, "override_active": override,
                "override_phrase": "none", "override_energy": "none", "override_color": "none",
                "override_manual_strobe": False, "override_audience_sweep": False,
                "override_all_on": False, "override_par_chase": False, "override_par_snake": False,
                "fixture_group_intents": {"moving": {"intensity": .8, "movement_amount": .5},
                                          "par": {"intensity": .7}, "wash": {"intensity": .6}},
                "selected_primitives": {"moving": {"palette": "amber_teal"},
                                        "par": {"palette": "amber_teal"}, "wash": {"palette": "amber_teal"}},
            },
            "preview_auto_show": {
                "preview_source": "dynamic_composer",
                "continuous_musical_state": {"section_label": "chorus", "section_progress": .4,
                                             "relative_energy": .72, "energy_trajectory": "rising",
                                             "recurrence_strength": .3},
                "rme_preview": {"current_rme": current_rme},
                "event_envelope": {"active": False},
            },
            "slot_order": ["moving", "par", "wash"],
            "slots": {
                "moving": {"enabled": True, "group": "movers_a", "fixture": "moving_head", "label": "Moving"},
                "par": {"enabled": True, "group": "pars", "fixture": "flat_par", "label": "PAR"},
                "wash": {"enabled": True, "group": "washes", "fixture": "wall_wash", "label": "Wash"},
            },
        },
    }


class RemoteLiveStateV2Tests(unittest.TestCase):
    def setUp(self):
        self.original_version = dict(beatbeam_app.REMOTE_LIVE_STATE_VERSION)
        beatbeam_app.REMOTE_LIVE_STATE_VERSION.update(signature=None, state_revision=0, event_sequence=0)

    def tearDown(self):
        beatbeam_app.REMOTE_LIVE_STATE_VERSION.update(self.original_version)

    def project(self, state):
        with patch("beatbeam_app.full_state", return_value=state):
            return beatbeam_app.remote_live_state_v2()

    def test_dynamic_frame_projection_is_typed_and_uses_authoritative_groups(self):
        payload = self.project(fixture_state())
        self.assertEqual(2, payload["schema_version"])
        self.assertEqual("DYNAMIC_COMPOSER_ENABLED", payload["show"]["configured_production_mode"])
        self.assertEqual("dynamic_composer", payload["show"]["physical_frame_source"])
        self.assertEqual("READY", payload["track"]["readiness"])
        self.assertEqual({"movers_a", "pars", "washes"}, {group["id"] for group in payload["fixtures"]})
        self.assertTrue(payload["dmx"]["physical_output_available"])

    def test_fallback_renderer_transport_and_readiness_are_visible_without_recalculation(self):
        state = fixture_state(source="existing_autoshow", fallback="transport_stale", renderer_healthy=False,
                              connected=False, readiness="FAILED")
        state["live_ui"]["availability"] = "unavailable"
        state["live_ui"]["transport_state"] = "stale"
        payload = self.project(state)
        self.assertTrue(payload["show"]["fallback_active"])
        self.assertEqual("transport_stale", payload["show"]["fallback_reason"])
        codes = {warning["code"] for warning in payload["warnings"]}
        self.assertTrue({"RENDERER_UNHEALTHY", "DMX_DISCONNECTED", "TRANSPORT_STALE", "SONGANALYZER_FAILED"} <= codes)

    def test_baseline_blackout_override_and_no_rme_are_explicit(self):
        state = fixture_state(mode="BASELINE_ONLY", source="existing_autoshow", blackout=True, override=True)
        payload = self.project(state)
        self.assertEqual("BASELINE_ONLY", payload["show"]["configured_production_mode"])
        self.assertIsNone(payload["musical_state"]["current_rme"])
        self.assertTrue(payload["overrides"]["blackout"])
        self.assertTrue(payload["overrides"]["any_active"])
        self.assertIn("BLACKOUT_ACTIVE", {warning["code"] for warning in payload["warnings"]})

    def test_revision_changes_only_when_authoritative_projection_changes(self):
        state = fixture_state()
        first = self.project(state)
        second = self.project(state)
        changed = fixture_state(source="existing_autoshow", fallback="transport_stale")
        third = self.project(changed)
        self.assertEqual(first["state_revision"], second["state_revision"])
        self.assertEqual(first["event_sequence"], second["event_sequence"])
        self.assertGreater(third["state_revision"], second["state_revision"])
        self.assertGreater(third["event_sequence"], second["event_sequence"])


class RemoteReadScopeTests(unittest.TestCase):
    def setUp(self):
        self.config = beatbeam_app.REMOTE_ACCESS_CONFIG
        self.config_path = beatbeam_app.REMOTE_ACCESS_PATH
        self.temp = tempfile.TemporaryDirectory()
        beatbeam_app.REMOTE_ACCESS_PATH = Path(self.temp.name) / "remote.json"
        beatbeam_app.REMOTE_ACCESS_CONFIG = {
            "require_token": True, "token": "legacy-broad-token", "pairing_code": "123456",
            "remote_credentials": {},
        }

    def tearDown(self):
        beatbeam_app.REMOTE_ACCESS_CONFIG = self.config
        beatbeam_app.REMOTE_ACCESS_PATH = self.config_path
        self.temp.cleanup()

    def test_pairing_issues_read_scope_and_rejects_legacy_broad_token_for_v2(self):
        self.assertIsNone(beatbeam_app.issue_remote_read_credential("bad"))
        issued = beatbeam_app.issue_remote_read_credential("123456", "iPad Test")
        self.assertEqual(beatbeam_app.REMOTE_READ_SCOPE, issued["scope"])
        self.assertTrue(beatbeam_app.remote_read_token_is_valid(issued["token"]))
        self.assertFalse(beatbeam_app.remote_read_token_is_valid("legacy-broad-token"))
        self.assertNotEqual("123456", beatbeam_app.remote_access_pairing_code())

    def test_remote_read_handler_auth_does_not_accept_a_legacy_token(self):
        issued = beatbeam_app.issue_remote_read_credential("123456")
        handler = object.__new__(beatbeam_app.AppHandler)
        handler.client_address = ("192.0.2.44", 1234)
        handler.headers = {"Authorization": "Bearer legacy-broad-token"}
        self.assertFalse(handler.is_authorized_remote_v2_read_request())
        handler.headers = {"Authorization": f"Bearer {issued['token']}"}
        self.assertTrue(handler.is_authorized_remote_v2_read_request())


if __name__ == "__main__":
    unittest.main()
