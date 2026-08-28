import copy
import json
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from beatbeam_app import DmxController, MANUAL_COLOR_PRESETS
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


class RmeHandoff:
    def project(self, state, include_shadow=False, include_rich_events=False):
        if not include_rich_events and not include_shadow:
            return {}
        projection = {
            "track_match": "exact",
            "availability": "available_current",
            "projection_status": "in_segment",
            "rich_musical_events": {
                "mode": "SHADOW_ONLY", "availability": "available", "events": [{
                    "type": "BUILD", "temporal_kind": "INTERVAL",
                    "start_seconds": 10.0, "end_seconds": 20.0,
                    "origin_observation_id": "build-1",
                }],
            },
        }
        if include_shadow:
            projection["shadow_analysis"] = {
                "model": "SectionCharacterProfileShadow",
                "section_characters": [{
                    "observation_id": "section-1", "start_seconds": 0.0,
                    "end_seconds": 30.0, "relative_energy": .62,
                    "energy_rise": .4, "recurrence_strength": .84,
                    "family_salience": .75,
                }],
            }
        return projection


class RmePreviewBridge(PreviewBridge):
    def __init__(self):
        self.handoff = RmeHandoff()


class ProductionAuthorityHandoff(RmeHandoff):
    def project(self, state, include_shadow=False, include_rich_events=False):
        result = super().project(state, include_shadow, include_rich_events)
        if result:
            result["canonical_track_path"] = "/Music/Preview/Track.flac"
            result["active_track"] = {
                "canonical_path": "/Music/Preview/Track.flac",
                "status": "ready",
                "generation": 1,
            }
        return result


class ProductionAuthorityBridge(PreviewBridge):
    def __init__(self):
        self.handoff = ProductionAuthorityHandoff()


class CrossDomainProductionAuthorityHandoff(ProductionAuthorityHandoff):
    def project(self, state, include_shadow=False, include_rich_events=False):
        result = super().project(state, include_shadow, include_rich_events)
        if result:
            result["active_track"]["generation"] = 22
        return result


class CrossDomainProductionAuthorityBridge(PreviewBridge):
    def __init__(self):
        self.handoff = CrossDomainProductionAuthorityHandoff()


class ArrivalEnvelopeHandoff(RmeHandoff):
    def project(self, state, include_shadow=False, include_rich_events=False):
        result = super().project(state, include_shadow, include_rich_events)
        if result:
            result["rich_musical_events"]["events"] = [{
                "type": "ARRIVAL", "temporal_kind": "POINT", "start_seconds": 10.0,
                "start_bar": 5, "origin_observation_id": "arrival-1",
            }]
        return result


class ArrivalEnvelopeBridge(PreviewBridge):
    def __init__(self):
        self.handoff = ArrivalEnvelopeHandoff()


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

    def test_production_selector_runtime_default_is_baseline_and_physically_identical(self):
        transport = PreviewTransport()
        controller = DmxController(transport, ProductionAuthorityBridge())
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"].update({"enabled": True, "preview_rme_mode": "DYNAMIC_COMPOSER"})
        controller.render_active = True
        with patch("beatbeam_app.time.time", return_value=300.0):
            baseline = controller._auto_show_state(transport.snapshot_for_render(), controller.config["auto_show"])
            expected = controller._render_values(
                300.0, config=controller.config, osc=transport.snapshot_for_render(), auto_show=baseline
            )
            self.tick(controller)

        decision = controller.state()["production_show_selector"]
        self.assertEqual("BASELINE_ONLY", decision["production_show_mode"])
        self.assertEqual("existing_autoshow", decision["production_show_source"])
        self.assertEqual("mode_baseline", decision["fallback_reason"])
        self.assertEqual(expected, controller.current_values)

    def test_dynamic_par_trace_has_eight_beat_congruent_final_dmx_frames(self):
        transport = PreviewTransport()
        transport.state["_playback_generation"] = 10
        controller = DmxController(transport, CrossDomainProductionAuthorityBridge())
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"].update({"enabled": True, "preview_rme_mode": "DYNAMIC_COMPOSER"})
        controller.config["production_show_mode"] = "DYNAMIC_COMPOSER_ENABLED"
        controller.render_active = controller.connected = controller.running = True
        dmx = FakeDmx()
        controller.dmx = dmx
        original_evaluation = controller._preview_auto_show_evaluation

        def alternating_par_candidate(*args, **kwargs):
            candidate, projection = original_evaluation(*args, **kwargs)
            candidate = copy.deepcopy(candidate)
            candidate["selected_primitives"]["par"]["color_animation"] = "alternate"
            candidate["composition_signature"]["color_animation"] = "alternate"
            return candidate, projection

        controller._preview_auto_show_evaluation = alternating_par_candidate
        previews = []
        for offset, beat in enumerate(range(24, 32)):
            transport.state["beat_value"] = float(beat)
            transport.state["time_seconds"] = 12.0 + offset * .48
            with patch("beatbeam_app.time.time", return_value=300.0 + offset):
                self.tick(controller)
            previews.append(controller.state()["slot_previews"]["par"])

        state = controller.state()
        trace = state["physical_dmx_trace"]
        self.assertEqual("dynamic_composer", state["production_show_selector"]["production_show_source"])
        self.assertEqual(8, len(trace))
        self.assertEqual(8, len(dmx.sent))
        self.assertGreater(len({(item["red"], item["green"], item["blue"]) for item in previews}), 1)
        self.assertGreater(len({tuple(item["par_fixtures"][0]["composer_desired_rgbw"][:3]) for item in trace}), 1)
        for frame, sent in zip(trace, dmx.sent):
            self.assertEqual("dmx_dispatch", frame["output_state"])
            self.assertEqual("alternate", frame["par_color_animation"])
            channels = frame["par_fixtures"][0]["channels"]
            desired = tuple(frame["par_fixtures"][0]["composer_desired_rgbw"])
            self.assertIn(desired, MANUAL_COLOR_PRESETS.values())
            for component in ("red", "green", "blue"):
                channel = channels[component]["channel"]
                self.assertEqual(channels[component]["current_value"], channels[component]["final_dmx_value"])
                self.assertEqual(channels[component]["final_dmx_value"], sent[channel])
                self.assertEqual(channels[component]["final_dmx_value"], desired[("red", "green", "blue").index(component)])
            self.assertEqual(channels["dimmer"]["current_value"], channels["dimmer"]["final_dmx_value"])

    def test_new_controller_restart_defaults_to_persisted_baseline_mode(self):
        first, _ = self.controller()
        second, _ = self.controller()
        self.tick(first)
        self.tick(second)

        self.assertEqual("BASELINE_ONLY", first.default_config()["production_show_mode"])
        self.assertEqual("BASELINE_ONLY", first.state()["production_show_selector"]["production_mode"])
        self.assertEqual("BASELINE_ONLY", second.state()["production_show_selector"]["production_mode"])

    def test_operator_mode_is_explicit_persistent_and_invalid_settings_fail_to_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "beatbeam_config.json"
            with patch("beatbeam_app.CONFIG_PATH", config_path):
                controller, _ = self.controller()
                self.assertEqual("BASELINE_ONLY", controller.config["production_show_mode"])
                self.assertEqual(
                    "BASELINE_ONLY",
                    controller._clean_full_config({"production_show_mode": "broken"})["production_show_mode"],
                )
                controller.set_production_show_mode("DYNAMIC_COMPOSER_ENABLED")
                controller.flush_config()
                restarted = DmxController(PreviewTransport(), PreviewBridge())
                self.assertEqual("DYNAMIC_COMPOSER_ENABLED", restarted.config["production_show_mode"])

                config_path.write_text("{ invalid", encoding="utf-8")
                corrupt_restart = DmxController(PreviewTransport(), PreviewBridge())
                self.assertEqual("BASELINE_ONLY", corrupt_restart.config["production_show_mode"])

    def test_runtime_revert_is_immediate_and_never_auto_reenables(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "beatbeam_config.json"
            with patch("beatbeam_app.CONFIG_PATH", config_path):
                transport = PreviewTransport()
                controller = DmxController(transport, ProductionAuthorityBridge())
                controller.config = controller._clean_full_config(controller.default_config())
                controller.config["auto_show"].update({"enabled": True, "preview_rme_mode": "DYNAMIC_COMPOSER"})
                controller.config["production_show_mode"] = "DYNAMIC_COMPOSER_ENABLED"
                controller.render_active = True
                with patch("beatbeam_app.time.time", return_value=300.0):
                    self.tick(controller)
                    self.assertEqual("dynamic_composer", controller.state()["production_show_selector"]["production_show_source"])
                    controller.set_production_show_mode("BASELINE_ONLY")
                    self.tick(controller)

                decision = controller.state()["production_show_selector"]
                self.assertEqual("BASELINE_ONLY", controller.config["production_show_mode"])
                self.assertEqual("existing_autoshow", decision["production_show_source"])
                self.assertEqual("mode_baseline", decision["fallback_reason"])
                self.tick(controller)
                self.assertEqual(
                    "existing_autoshow",
                    controller.state()["production_show_selector"]["production_show_source"],
                )
                controller.set_production_show_mode("DYNAMIC_COMPOSER_ENABLED")
                self.tick(controller)
                self.assertEqual(
                    "dynamic_composer",
                    controller.state()["production_show_selector"]["production_show_source"],
                )
                controller.flush_config()

    def test_renderer_exception_after_candidate_selection_retries_same_frame_with_baseline(self):
        transport = PreviewTransport()
        controller = DmxController(transport, ProductionAuthorityBridge())
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"].update({"enabled": True, "preview_rme_mode": "DYNAMIC_COMPOSER"})
        controller.config["production_show_mode"] = "DYNAMIC_COMPOSER_ENABLED"
        controller.render_active = True
        original_render = controller._render_values

        def render_or_fault(now, *, config, osc, auto_show):
            if auto_show.get("dynamic_composer_active"):
                raise RuntimeError("candidate renderer fault")
            return original_render(now, config=config, osc=osc, auto_show=auto_show)

        with patch.object(controller, "_render_values", side_effect=render_or_fault), \
                patch("beatbeam_app.time.time", return_value=300.0):
            self.tick(controller)

        decision = controller.state()["production_show_selector"]
        self.assertEqual("existing_autoshow", decision["production_show_source"])
        self.assertEqual("renderer_exception", decision["fallback_reason"])
        self.assertTrue(controller.current_values)
        observation = controller.state()["production_show_observation"]
        self.assertEqual(0, observation["dynamic_frames"])
        self.assertEqual(1, observation["baseline_fallback_frames"])
        self.assertEqual(1, observation["candidate_faults"])

    def test_shadow_mode_cannot_be_selected_through_operator_settings(self):
        transport = PreviewTransport()
        controller = DmxController(transport, ProductionAuthorityBridge())
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"].update({"enabled": True, "preview_rme_mode": "DYNAMIC_COMPOSER"})
        controller.render_active = True
        controller.config["production_show_mode"] = "DYNAMIC_COMPOSER_SHADOW"
        with patch("beatbeam_app.time.time", return_value=300.0):
            baseline = controller._auto_show_state(transport.snapshot_for_render(), controller.config["auto_show"])
            expected = controller._render_values(
                300.0, config=controller.config, osc=transport.snapshot_for_render(), auto_show=baseline
            )
            self.tick(controller)

        decision = controller.state()["production_show_selector"]
        self.assertEqual("BASELINE_ONLY", decision["production_show_mode"])
        self.assertFalse(decision["dynamic_composer_active"])
        self.assertEqual("mode_baseline", decision["fallback_reason"])
        self.assertEqual(expected, controller.current_values)

    def test_composer_exception_is_observed_and_fails_back_to_same_frame_baseline(self):
        transport = PreviewTransport()
        controller = DmxController(transport, ProductionAuthorityBridge())
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"].update({"enabled": True, "preview_rme_mode": "DYNAMIC_COMPOSER"})
        controller.render_active = True
        controller.config["production_show_mode"] = "DYNAMIC_COMPOSER_ENABLED"
        with patch("beatbeam_app.compose_dynamic_preview", side_effect=RuntimeError("synthetic")):
            self.tick(controller)

        decision = controller.state()["production_show_selector"]
        self.assertEqual("composer_exception", decision["fallback_reason"])
        self.assertEqual("existing_autoshow", decision["production_source"])

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

    def test_preview_projection_does_not_mutate_physical_rhythm_state(self):
        controller, transport = self.controller()
        controller.slot_rhythm_states = {"head": {"mode": "soft_pulse", "lock_until_beat": 30.0}}
        controller.last_slot_rhythm_signatures = {"head": ("soft_pulse", "soft_pulse", False, "build")}
        before_states = dict(controller.slot_rhythm_states)
        before_signatures = dict(controller.last_slot_rhythm_signatures)
        with patch("beatbeam_app.time.time", return_value=300.0):
            auto_show = controller._auto_show_state(
                transport.snapshot_for_render(), controller.config["auto_show"]
            )
            controller._build_slot_previews(
                controller.config, transport.snapshot_for_render(), 300.0, auto_show=auto_show
            )

        self.assertEqual(before_states, controller.slot_rhythm_states)
        self.assertEqual(before_signatures, controller.last_slot_rhythm_signatures)

    def test_rme_enhanced_changes_only_preview_and_keeps_physical_frame_identical(self):
        transport = PreviewTransport()
        controller = DmxController(transport, RmePreviewBridge())
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"].update({"enabled": True, "preview_rme_mode": "RME_ENHANCED"})
        controller.render_active = True
        dmx = FakeDmx()
        controller.dmx = dmx
        controller.connected = True
        controller.running = True

        with patch("beatbeam_app.time.time", return_value=300.0):
            baseline, _ = controller._auto_show_evaluation(
                transport.snapshot_for_render(), controller.config["auto_show"]
            )
            baseline_previews = controller._build_slot_previews(
                controller.config,
                transport.snapshot_for_render(),
                300.0,
                auto_show=baseline,
            )
            expected_values = controller._render_values(
                300.0, config=controller.config, osc=transport.snapshot_for_render(), auto_show=baseline
            )
            self.tick(controller)

        state = controller.state()
        differential = state["rme_preview_differential"]
        self.assertEqual(expected_values, controller.current_values)
        self.assertEqual(expected_values, dmx.sent[0])
        self.assertEqual(expected_values, state["values"])
        self.assertEqual("RME_ENHANCED", state["auto_show"]["preview_rme_mode"])
        self.assertEqual("BUILD", state["preview_auto_show"]["rme_preview"]["current_rme"]["type"])
        self.assertGreater(state["preview_auto_show"]["energy"], state["auto_show"]["energy"])
        self.assertNotEqual(baseline_previews, state["slot_previews"])
        self.assertTrue(differential["show_state_changed"])
        self.assertTrue(differential["fixture_values_changed"])
        self.assertEqual("preview_auto_show -> slot_previews", differential["selected_preview_source"])

    def test_dynamic_composer_replaces_scene_primitives_only_in_preview(self):
        transport = PreviewTransport()
        controller = DmxController(transport, RmePreviewBridge())
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"].update({"enabled": True, "preview_rme_mode": "DYNAMIC_COMPOSER"})
        controller.config["slots"]["wall_wash"] = controller._clean_slot_config(
            "wall_wash",
            controller.default_slot_config("wall_wash", fixture_id="uking_zq06016", address=50),
        )
        controller.config["slot_order"].append("wall_wash")
        controller.render_active = True
        dmx = FakeDmx()
        controller.dmx = dmx
        controller.connected = True
        controller.running = True

        with patch("beatbeam_app.time.time", return_value=300.0):
            baseline, _ = controller._auto_show_evaluation(
                transport.snapshot_for_render(), controller.config["auto_show"]
            )
            baseline_previews = controller._build_slot_previews(
                controller.config, transport.snapshot_for_render(), 300.0, auto_show=baseline
            )
            expected_values = controller._render_values(
                300.0, config=controller.config, osc=transport.snapshot_for_render(), auto_show=baseline
            )
            self.tick(controller)

        state = controller.state()
        differential = state["rme_preview_differential"]
        self.assertEqual(expected_values, controller.current_values)
        self.assertEqual(expected_values, dmx.sent[0])
        self.assertEqual("DYNAMIC_COMPOSER", differential["mode"])
        self.assertEqual("build", differential["interpretation"])
        self.assertEqual("dynamic_composer", differential["preview_source"])
        self.assertTrue(differential["dynamic_composer_active"])
        self.assertFalse(differential["fallback_to_baseline"])
        self.assertTrue(differential["dynamic_composition_applied"])
        self.assertFalse(differential["baseline_scene_reused"])
        self.assertIn("movement", differential["changed_dimensions"])
        self.assertIn("intensity", differential["changed_dimensions"])
        self.assertEqual("build_fastening_circle", differential["selected_primitives"]["moving"]["movement_pattern"])
        self.assertEqual("amber_teal", differential["selected_primitives"]["par"]["palette"])
        self.assertEqual("center_out_build", differential["selected_primitives"]["wash"]["wash_cue"])
        self.assertIn("Dynamic Composer • RME Build", differential["preview_cue"])
        self.assertNotEqual(baseline_previews["head"]["target_pan"], state["slot_previews"]["head"]["target_pan"])
        self.assertNotEqual(
            tuple(baseline_previews["par"][channel] for channel in ("red", "green", "blue")),
            tuple(state["slot_previews"]["par"][channel] for channel in ("red", "green", "blue")),
        )
        self.assertNotEqual(
            tuple(baseline_previews["wall_wash"][channel] for channel in ("red", "green", "blue")),
            tuple(state["slot_previews"]["wall_wash"][channel] for channel in ("red", "green", "blue")),
        )
        self.assertEqual(
            state["slot_previews"]["head"]["target_pan"],
            differential["rendered_preview_slots"]["head"]["target_pan"],
        )
        self.assertTrue(differential["fixture_values_changed"])

    def test_dynamic_composer_without_current_rme_remains_preview_only_and_active(self):
        transport = PreviewTransport()
        handoff = RmeHandoff()
        original_project = handoff.project

        def without_event(state, include_shadow=False, include_rich_events=False):
            result = original_project(state, include_shadow, include_rich_events)
            if result:
                result["rich_musical_events"]["events"] = []
            return result

        handoff.project = without_event
        bridge = PreviewBridge()
        bridge.handoff = handoff
        controller = DmxController(transport, bridge)
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"].update({"enabled": True, "preview_rme_mode": "DYNAMIC_COMPOSER"})
        controller.render_active = True
        dmx = FakeDmx()
        controller.dmx = dmx
        controller.connected = True
        controller.running = True

        with patch("beatbeam_app.time.time", return_value=300.0):
            baseline, _ = controller._auto_show_evaluation(
                transport.snapshot_for_render(), controller.config["auto_show"]
            )
            expected_values = controller._render_values(
                300.0, config=controller.config, osc=transport.snapshot_for_render(), auto_show=baseline
            )
            self.tick(controller)

        differential = controller.state()["rme_preview_differential"]
        self.assertEqual(expected_values, controller.current_values)
        self.assertEqual(expected_values, dmx.sent[0])
        self.assertIsNone(differential["event"])
        self.assertEqual("none", differential["interpretation"])
        self.assertTrue(differential["dynamic_composer_active"])
        self.assertFalse(differential["fallback_to_baseline"])
        self.assertFalse(differential["baseline_scene_reused"])
        self.assertIn("relative_energy", differential["continuous_musical_state"])
        self.assertIn("motion_parameters", differential["composition_signature"])
        self.assertIn("selection", differential["variation"])
        self.assertTrue(differential["fixture_values_changed"])

    def test_arrival_envelope_outlives_point_context_and_keeps_physical_frame_identical(self):
        transport = PreviewTransport()
        controller = DmxController(transport, ArrivalEnvelopeBridge())
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"].update({"enabled": True, "preview_rme_mode": "DYNAMIC_COMPOSER"})
        controller.render_active = True
        dmx = FakeDmx()
        controller.dmx = dmx
        controller.connected = True
        controller.running = True

        with patch("beatbeam_app.time.time", return_value=300.0):
            baseline, _ = controller._auto_show_evaluation(
                transport.snapshot_for_render(), controller.config["auto_show"]
            )
            expected_values = controller._render_values(
                300.0, config=controller.config, osc=transport.snapshot_for_render(), auto_show=baseline
            )
            self.tick(controller)

        differential = controller.state()["rme_preview_differential"]
        self.assertEqual(expected_values, controller.current_values)
        self.assertEqual(expected_values, dmx.sent[0])
        self.assertEqual("ARRIVAL", differential["event"]["type"])
        self.assertIsNone(differential["source_event"])
        self.assertTrue(differential["event_envelope"]["active"])
        self.assertEqual("SETTLE", differential["event_envelope"]["phase"])
        self.assertEqual("bpm", differential["event_envelope"]["timing_source"])
        self.assertTrue(differential["dynamic_composer_active"])
        self.assertFalse(differential["fallback_to_baseline"])
        self.assertTrue(differential["fixture_values_changed"])


if __name__ == "__main__":
    unittest.main()
