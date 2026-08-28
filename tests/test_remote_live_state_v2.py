import tempfile
import threading
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

    def test_numeric_energy_trajectory_is_normalized_to_the_swift_string_contract(self):
        state = fixture_state()
        state["dmx"]["preview_auto_show"]["continuous_musical_state"]["energy_trajectory"] = -0.41
        self.assertEqual("falling", self.project(state)["musical_state"]["energy_trajectory"])

    def test_unknown_energy_trajectory_has_a_bounded_contract_value(self):
        state = fixture_state()
        state["dmx"]["preview_auto_show"]["continuous_musical_state"]["energy_trajectory"] = "sideways"
        self.assertEqual("unknown", self.project(state)["musical_state"]["energy_trajectory"])


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

    def test_pairing_qr_prefers_reachable_lan_before_optional_tailscale(self):
        with patch("beatbeam_app.SERVER_HOST", "0.0.0.0"), \
             patch("beatbeam_app._interface_ipv4_candidates", return_value=[
                 {"name": "en0", "label": "Wi-Fi", "kind": "wifi", "ip": "192.0.2.20"},
             ]), \
             patch("beatbeam_app.tailscale_ipv4", return_value="100.64.0.20"):
            state = beatbeam_app.remote_access_state()
        self.assertTrue(state["preferred_url"].startswith("http://192.0.2.20:"))


class RemoteLiveControlTests(unittest.TestCase):
    def setUp(self):
        self.config = beatbeam_app.REMOTE_ACCESS_CONFIG
        self.dmx = beatbeam_app.DMX
        self.leases = dict(beatbeam_app.REMOTE_MOMENTARY_LEASES)
        self.results = dict(beatbeam_app.REMOTE_CONTROL_RESULTS)
        beatbeam_app.REMOTE_ACCESS_CONFIG = {"remote_credentials": {
            "control-token": {"scope": "REMOTE_READ", "scopes": ["REMOTE_READ", "LIVE_CONTROL"], "client_id": "ipad-a"},
            "read-token": {"scope": "REMOTE_READ", "scopes": ["REMOTE_READ"], "client_id": "ipad-b"},
        }}
        class FakeDmx:
            def __init__(self):
                self.lock = threading.RLock(); self.config = {"auto_show": {}}; self.calls = []
            def update_config(self, payload): self.calls.append(("update", payload)); self.config.update(payload); return {}
            def blackout(self): self.calls.append(("blackout",))
            def trigger_one_shot_cue(self, cue): self.calls.append(("cue", cue))
            def set_production_show_mode(self, mode): self.calls.append(("mode", mode))
        beatbeam_app.DMX = FakeDmx()
        beatbeam_app.REMOTE_MOMENTARY_LEASES.clear(); beatbeam_app.REMOTE_CONTROL_RESULTS.clear()
        self.state = {"state_revision": 7, "event_sequence": 7, "overrides": {}}
        self.patcher = patch("beatbeam_app.remote_live_state_v2", return_value=self.state)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop(); beatbeam_app.REMOTE_ACCESS_CONFIG = self.config; beatbeam_app.DMX = self.dmx
        beatbeam_app.REMOTE_MOMENTARY_LEASES.clear(); beatbeam_app.REMOTE_MOMENTARY_LEASES.update(self.leases)
        beatbeam_app.REMOTE_CONTROL_RESULTS.clear(); beatbeam_app.REMOTE_CONTROL_RESULTS.update(self.results)

    def command(self, action, value=None, command_id="command-1", **extra):
        return beatbeam_app.remote_live_control_command("control-token", {"command_id": command_id, "action": action, "value": value, **extra})

    def test_live_control_allowlist_ack_and_idempotent_manual_color(self):
        first = self.command("set_color", "red")
        duplicate = self.command("set_color", "red")
        self.assertTrue(first["accepted"]); self.assertEqual(first, duplicate)
        self.assertEqual(1, len(beatbeam_app.DMX.calls))
        self.assertEqual("red", beatbeam_app.DMX.calls[0][1]["auto_show"]["override_color"])
        denied = self.command("developer_force_reanalyze", command_id="nope")
        self.assertFalse(denied["accepted"]); self.assertIn("allowlisted", denied["error"])

    def test_phrase_energy_cue_release_all_blackout_and_modes_are_bounded(self):
        self.assertTrue(self.command("set_phrase", "chorus", command_id="phrase")["accepted"])
        self.assertTrue(self.command("set_energy", "high", command_id="energy")["accepted"])
        self.assertTrue(self.command("trigger_cue", "white_hit", command_id="cue")["accepted"])
        self.assertTrue(self.command("blackout_on", command_id="blackout")["accepted"])
        self.assertTrue(self.command("blackout_off", command_id="unblackout")["accepted"])
        self.assertTrue(self.command("revert_baseline", command_id="baseline")["accepted"])
        self.assertTrue(self.command("enable_dynamic_composer", command_id="dynamic")["accepted"])
        self.assertTrue(self.command("release_all", command_id="release")["accepted"])
        self.assertIn(("cue", "white_hit"), beatbeam_app.DMX.calls)
        self.assertIn(("blackout",), beatbeam_app.DMX.calls)

    def test_momentary_lease_is_client_owned_and_expiry_releases(self):
        self.assertTrue(self.command("momentary_press", "par_chase", command_id="press")["accepted"])
        self.assertIn("par_chase", beatbeam_app.REMOTE_MOMENTARY_LEASES)
        before = len(beatbeam_app.DMX.calls)
        self.assertTrue(self.command("momentary_renew", "par_chase", command_id="renew")["accepted"])
        self.assertGreater(len(beatbeam_app.DMX.calls), before)
        beatbeam_app._reap_remote_momentary_leases(now=beatbeam_app.REMOTE_MOMENTARY_LEASES["par_chase"]["expires_at"] + 1)
        self.assertNotIn("par_chase", beatbeam_app.REMOTE_MOMENTARY_LEASES)
        self.assertFalse(beatbeam_app.DMX.calls[-1][1]["auto_show"]["override_par_chase"])

    def test_read_scope_cannot_control_and_stale_revision_rejects(self):
        self.assertFalse(beatbeam_app.remote_live_control_token_is_valid("read-token"))
        stale = self.command("set_color", "blue", command_id="stale", expected_state_revision=6)
        self.assertFalse(stale["accepted"]); self.assertEqual("stale_state_revision", stale["error"])


if __name__ == "__main__":
    unittest.main()
