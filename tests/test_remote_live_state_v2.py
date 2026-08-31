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
            # This is the authoritative post-authority frame.  It exists even
            # when the Enttec sink is deliberately disconnected.
            "rendered_final_values": {
                1: 66, 3: 77, 6: 180, 7: 12, 10: 201, 11: 20, 12: 10, 13: 0,
                16: 80, 18: 90, 21: 160, 25: 30, 26: 190, 27: 40, 28: 0,
                31: 210, 32: 111, 33: 22, 34: 33, 35: 0, 36: 9,
                39: 200, 40: 44, 41: 55, 42: 66, 43: 0, 44: 8,
                47: 70, 48: 80, 49: 90,
            },
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
                "override_phrase": "none", "override_energy": "none", "override_color": "none", "override_color_combo": "none",
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
            "slot_order": ["moving", "moving_2", "par", "par_2", "wash"],
            "slots": {
                "moving": {"enabled": True, "group": "movers_a", "fixture": "shehds_led_wash_7x12w_rgbw_moving_head", "mode": "15ch", "label": "Moving", "address": 1},
                "moving_2": {"enabled": True, "group": "movers_a", "fixture": "shehds_led_wash_7x12w_rgbw_moving_head", "mode": "15ch", "label": "Moving 2", "address": 16},
                "par": {"enabled": True, "group": "pars", "fixture": "shehds_flat_par_12x3w_rgbw", "mode": "8ch", "label": "PAR", "address": 31},
                "par_2": {"enabled": True, "group": "pars", "fixture": "shehds_flat_par_12x3w_rgbw", "mode": "8ch", "label": "PAR 2", "address": 39},
                "wash": {"enabled": True, "group": "washes", "fixture": "uking_zq06016", "mode": "P001", "label": "Wash", "address": 47},
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
        self.assertIn({"id": "rainbow", "label": "Rainbow"}, payload["control"]["colors"])
        self.assertEqual(16, len(payload["control"]["color_combinations"]))
        self.assertTrue(all(combo["available"] for combo in payload["control"]["color_combinations"]))
        self.assertEqual(
            {"red_blue", "red_yellow", "red_white", "green_blue", "green_purple", "green_white", "blue_yellow", "purple_white"},
            {combo["id"] for combo in payload["control"]["color_combinations"][-8:]},
        )

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

    def test_active_color_combo_is_projected_authoritatively_and_clears_single_color(self):
        state = fixture_state(override=True)
        state["dmx"]["auto_show"].update({"override_color": "none", "override_color_combo": "blue_orange"})
        payload = self.project(state)
        self.assertIsNone(payload["overrides"]["color"])
        self.assertEqual("blue_orange", payload["overrides"]["color_combo"])
        self.assertTrue(payload["overrides"]["any_active"])

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

    def test_effect_capabilities_follow_fixture_modes_not_physical_dispatch(self):
        state = fixture_state()["dmx"]
        effects = {effect["id"]: effect for effect in beatbeam_app._remote_live_effect_capabilities(state)}
        self.assertTrue(all(effect["available"] for effect in effects.values()))
        self.assertEqual("moving fixtures", effects["audience_sweep"]["target_group"])
        self.assertEqual("one_shot", effects["mirror_bounce"]["kind"])

        without_pars = fixture_state()["dmx"]
        without_pars["slots"] = {key: value for key, value in without_pars["slots"].items() if not key.startswith("par")}
        unavailable = {effect["id"]: effect for effect in beatbeam_app._remote_live_effect_capabilities(without_pars)}
        self.assertFalse(unavailable["par_chase"]["available"])
        self.assertFalse(unavailable["par_chase"]["temporarily_unavailable"])

        disconnected = fixture_state(connected=False)["dmx"]
        offline = {effect["id"]: effect for effect in beatbeam_app._remote_live_effect_capabilities(disconnected)}
        self.assertTrue(offline["white_hit"]["available"])
        self.assertFalse(offline["white_hit"]["temporarily_unavailable"])
        self.assertIsNone(offline["white_hit"]["reason_if_unavailable"])

        renderer_down = fixture_state(renderer_healthy=False)["dmx"]
        temporary = {effect["id"]: effect for effect in beatbeam_app._remote_live_effect_capabilities(renderer_down)}
        self.assertFalse(temporary["white_hit"]["available"])
        self.assertTrue(temporary["white_hit"]["temporarily_unavailable"])
        self.assertIn("Renderer", temporary["white_hit"]["reason_if_unavailable"])

    def test_color_combo_capability_is_structural_and_not_gated_by_dmx_connection(self):
        online = beatbeam_app._remote_manual_color_combo_capability(fixture_state()["dmx"])
        offline = beatbeam_app._remote_manual_color_combo_capability(fixture_state(connected=False)["dmx"])
        self.assertTrue(online["available"])
        self.assertEqual(online["color_slot_ids"], offline["color_slot_ids"])

        one_target = fixture_state()["dmx"]
        first_slot_id = next(iter(one_target["slots"]))
        one_target["slots"] = {first_slot_id: one_target["slots"][first_slot_id]}
        one_target["slot_order"] = [first_slot_id]
        unavailable = beatbeam_app._remote_manual_color_combo_capability(one_target)
        self.assertFalse(unavailable["available"])
        self.assertIn("2+", unavailable["reason_if_unavailable"])

    def test_output_preview_projects_post_authority_frame_while_dmx_is_disconnected(self):
        payload = self.project(fixture_state(connected=False))
        self.assertFalse(payload["dmx"]["physical_output_available"])
        self.assertTrue(payload["dmx"]["rendered_output_available"])
        self.assertTrue(payload["output"]["rendered_available"])
        self.assertFalse(payload["output"]["physical_output_available"])
        self.assertEqual(42, payload["output"]["frame_sequence"])
        fixtures = {fixture["id"]: fixture for fixture in payload["output"]["fixtures"]}
        self.assertEqual((201, 20, 10, 180, 12), tuple(fixtures["moving"][key] for key in ("red", "green", "blue", "dimmer", "strobe")))
        self.assertEqual((111, 22, 33, 210), tuple(fixtures["par"][key] for key in ("red", "green", "blue", "dimmer")))

        blackout = self.project(fixture_state(connected=False, blackout=True))["output"]
        self.assertTrue(blackout["blackout"])
        self.assertTrue(all(not fixture["active"] and fixture["dimmer"] == 0
                            and fixture["red"] == 0 and fixture["green"] == 0 and fixture["blue"] == 0
                            for fixture in blackout["fixtures"]))

    def test_blackout_remains_authoritative_while_remote_state_exposes_it_separately(self):
        state = fixture_state(blackout=True)
        payload = self.project(state)
        self.assertTrue(payload["overrides"]["blackout"])
        self.assertEqual("dynamic_composer", payload["show"]["preview_source"])


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
                self.lock = threading.RLock(); self.config = beatbeam_app.DmxController.default_config(); self.calls = []
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

    def command_as(self, token, action, value=None, command_id="command-1", **extra):
        return beatbeam_app.remote_live_control_command(token, {"command_id": command_id, "action": action, "value": value, **extra})

    def test_live_control_allowlist_ack_and_idempotent_manual_color(self):
        first = self.command("set_color", "red")
        duplicate = self.command("set_color", "red")
        self.assertTrue(first["accepted"]); self.assertEqual(first, duplicate)
        self.assertEqual(1, len(beatbeam_app.DMX.calls))
        self.assertEqual("red", beatbeam_app.DMX.calls[0][1]["auto_show"]["override_color"])
        self.assertEqual("none", beatbeam_app.DMX.calls[0][1]["auto_show"]["override_color_combo"])
        denied = self.command("developer_force_reanalyze", command_id="nope")
        self.assertFalse(denied["accepted"]); self.assertIn("allowlisted", denied["error"])

    def test_color_combo_is_live_control_scoped_and_mutually_exclusive_with_single_color(self):
        combo = self.command("set_color_combo", "blue_orange", command_id="combo")
        self.assertTrue(combo["accepted"])
        auto_show = beatbeam_app.DMX.calls[-1][1]["auto_show"]
        self.assertEqual("blue_orange", auto_show["override_color_combo"])
        self.assertEqual("none", auto_show["override_color"])
        single = self.command("set_color", "white", command_id="single")
        self.assertTrue(single["accepted"])
        auto_show = beatbeam_app.DMX.calls[-1][1]["auto_show"]
        self.assertEqual("white", auto_show["override_color"])
        self.assertEqual("none", auto_show["override_color_combo"])
        release = self.command("release_all", command_id="release")
        self.assertTrue(release["accepted"])
        self.assertEqual("none", beatbeam_app.DMX.calls[-1][1]["auto_show"]["override_color_combo"])
        self.assertFalse(self.command_as("read-token", "set_color_combo", "blue_orange", command_id="read")["accepted"])

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
        press = self.command("momentary_press", "par_chase", command_id="press")
        self.assertTrue(press["accepted"])
        self.assertTrue(press["momentary_lease"]["active"])
        self.assertEqual("par_chase", press["momentary_lease"]["effect"])
        self.assertTrue(press["momentary_lease"]["lease_id"])
        self.assertIn("par_chase", beatbeam_app.REMOTE_MOMENTARY_LEASES)
        before = len(beatbeam_app.DMX.calls)
        self.assertTrue(self.command("momentary_renew", "par_chase", command_id="renew", lease_id=press["momentary_lease"]["lease_id"])["accepted"])
        self.assertGreater(len(beatbeam_app.DMX.calls), before)
        beatbeam_app._reap_remote_momentary_leases(now=beatbeam_app.REMOTE_MOMENTARY_LEASES["par_chase"]["expires_at"] + 1)
        self.assertNotIn("par_chase", beatbeam_app.REMOTE_MOMENTARY_LEASES)
        self.assertFalse(beatbeam_app.DMX.calls[-1][1]["auto_show"]["override_par_chase"])

    def test_all_hold_effects_share_the_same_press_hold_release_lease_lifecycle(self):
        for index, effect in enumerate(beatbeam_app.REMOTE_MOMENTARY_EFFECT_KEYS):
            with self.subTest(effect=effect):
                press = self.command("momentary_press", effect, command_id=f"{effect}-press")
                self.assertTrue(press["accepted"])
                lease = press["momentary_lease"]
                self.assertEqual("active", lease["status"])
                self.assertEqual(effect, lease["effect"])
                self.assertTrue(lease["lease_id"])
                self.assertIn(effect, beatbeam_app.REMOTE_MOMENTARY_LEASES)
                self.assertTrue(self.command("momentary_renew", effect, command_id=f"{effect}-renew", lease_id=lease["lease_id"])["accepted"])
                release = self.command("momentary_release", effect, command_id=f"{effect}-release", lease_id=lease["lease_id"])
                self.assertTrue(release["accepted"])
                self.assertEqual("released", release["momentary_lease"]["status"])
                self.assertFalse(release["momentary_lease"]["active"])
                self.assertNotIn(effect, beatbeam_app.REMOTE_MOMENTARY_LEASES)
                self.assertFalse(beatbeam_app.DMX.config["auto_show"][beatbeam_app.REMOTE_MOMENTARY_EFFECT_KEYS[effect]])

    def test_momentary_release_is_idempotent_for_touch_cancel_fast_tap_and_expiry_cleanup(self):
        press = self.command("momentary_press", "manual_strobe", command_id="fast-press")
        lease_id = press["momentary_lease"]["lease_id"]
        # The release is the same bounded operation used for touch-up and touch-cancel.
        release = self.command("momentary_release", "manual_strobe", command_id="touch-cancel", lease_id=lease_id)
        self.assertTrue(release["accepted"]); self.assertEqual("released", release["momentary_lease"]["status"])
        duplicate = self.command("momentary_release", "manual_strobe", command_id="late-touch-up", lease_id=lease_id)
        self.assertTrue(duplicate["accepted"]); self.assertEqual("already_released", duplicate["momentary_lease"]["status"])

        press = self.command("momentary_press", "manual_strobe", command_id="network-loss-press")
        expires_at = beatbeam_app.REMOTE_MOMENTARY_LEASES["manual_strobe"]["expires_at"]
        beatbeam_app._reap_remote_momentary_leases(now=expires_at + 1)
        expired = self.command("momentary_release", "manual_strobe", command_id="expired-release", lease_id=press["momentary_lease"]["lease_id"])
        self.assertTrue(expired["accepted"]); self.assertEqual("already_released", expired["momentary_lease"]["status"])

    def test_momentary_renew_after_expiry_is_benign_and_never_reactivates_the_effect(self):
        press = self.command("momentary_press", "all_on", command_id="press")
        lease_id = press["momentary_lease"]["lease_id"]
        beatbeam_app._reap_remote_momentary_leases(now=beatbeam_app.REMOTE_MOMENTARY_LEASES["all_on"]["expires_at"] + 1)
        renew = self.command("momentary_renew", "all_on", command_id="late-renew", lease_id=lease_id)
        self.assertTrue(renew["accepted"])
        self.assertEqual("expired", renew["momentary_lease"]["status"])
        self.assertFalse(renew["momentary_lease"]["active"])
        self.assertNotIn("all_on", beatbeam_app.REMOTE_MOMENTARY_LEASES)

    def test_momentary_lease_rejects_wrong_client_and_wrong_lease_identity(self):
        beatbeam_app.REMOTE_ACCESS_CONFIG["remote_credentials"]["other-control-token"] = {
            "scope": "REMOTE_READ", "scopes": ["REMOTE_READ", "LIVE_CONTROL"], "client_id": "ipad-b"
        }
        press = self.command("momentary_press", "audience_sweep", command_id="press")
        lease_id = press["momentary_lease"]["lease_id"]
        wrong_client = self.command_as("other-control-token", "momentary_release", "audience_sweep", command_id="wrong-client", lease_id=lease_id)
        self.assertFalse(wrong_client["accepted"]); self.assertIn("another client", wrong_client["error"])
        wrong_lease = self.command("momentary_release", "audience_sweep", command_id="wrong-lease", lease_id="not-the-lease")
        self.assertFalse(wrong_lease["accepted"]); self.assertIn("does not match", wrong_lease["error"])
        self.assertIn("audience_sweep", beatbeam_app.REMOTE_MOMENTARY_LEASES)

    def test_momentary_controls_do_not_require_physical_dmx_connection(self):
        # The fake renderer intentionally has no physical connection property;
        # the LIVE_CONTROL lease path must still update authoritative intent.
        press = self.command("momentary_press", "par_snake", command_id="offline-press")
        self.assertTrue(press["accepted"])
        self.assertTrue(beatbeam_app.DMX.config["auto_show"]["override_par_snake"])
        release = self.command("momentary_release", "par_snake", command_id="offline-release", lease_id=press["momentary_lease"]["lease_id"])
        self.assertTrue(release["accepted"])
        self.assertFalse(beatbeam_app.DMX.config["auto_show"]["override_par_snake"])

    def test_read_scope_cannot_control_and_stale_revision_rejects(self):
        self.assertFalse(beatbeam_app.remote_live_control_token_is_valid("read-token"))
        stale = self.command("set_color", "blue", command_id="stale", expected_state_revision=6)
        self.assertFalse(stale["accepted"]); self.assertEqual("stale_state_revision", stale["error"])


if __name__ == "__main__":
    unittest.main()
