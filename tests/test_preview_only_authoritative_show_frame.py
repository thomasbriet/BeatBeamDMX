import copy
import json
import math
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import beatbeam_app
from beatbeam_app import (
    COLOR_BURST_PRESET_SEQUENCE,
    COLOR_BURST_STEPS_PER_BEAT,
    COLOR_BURST_SUBDIVISIONS_PER_BEAT,
    EFFECT_COLOR_OWNERSHIP,
    DmxController,
    MANUAL_COLOR_COMBOS,
    MANUAL_COLOR_PRESETS,
    ONE_SHOT_FX_SPEED_POLICY,
    _remote_live_output_preview,
)
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


class FailOnceDmx(FakeDmx):
    def __init__(self):
        super().__init__()
        self.fail_next = True

    def send(self, values):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("synthetic dmx dispatch failure")
        super().send(values)


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

    @staticmethod
    def composer_color(auto_show, palette_name):
        result = copy.deepcopy(auto_show)
        result.update({
            "override_color": "none",
            "override_color_combo": "none",
            "dynamic_composition_applied": True,
            "dynamic_composer_active": True,
            "fixture_group_intents": {
                role: {"color_change_rate": 0.0}
                for role in ("moving", "par", "wash", "static")
            },
            "selected_primitives": {
                role: {"palette": palette_name, "color_animation": "all_same"}
                for role in ("moving", "par", "wash", "static")
            },
        })
        return result

    def test_auto_color_is_transparent_and_presentation_uses_selected_production_source(self):
        controller, transport = self.controller()
        osc = transport.snapshot_for_render()
        baseline = controller._auto_show_state(osc, controller.config["auto_show"])
        selected_red = self.composer_color(baseline, "ruby_lime")
        unselected_blue_candidate = self.composer_color(baseline, "cobalt_amber")

        effective = controller._effective_slot_config(
            "head", controller.config["slots"]["head"], osc, selected_red,
            full_config=controller.config,
        )
        self.assertEqual(MANUAL_COLOR_PRESETS["red"], effective["_auto_show_rgbw"])
        self.assertNotIn("_manual_color_override", effective)

        _, previews, differential = controller._preview_auto_show_frame(
            controller.config,
            osc,
            100.0,
            baseline,
            preview_auto_show=unselected_blue_candidate,
            production_decision={"production_show_source": "existing_autoshow"},
            presentation_auto_show=selected_red,
        )
        self.assertEqual(255, previews["head"]["resolved_red"])
        self.assertEqual(0, previews["head"]["resolved_blue"])
        self.assertEqual(
            "preview_auto_show motion + selected_production_auto_show color -> slot_previews",
            differential["selected_preview_source"],
        )

    def test_auto_color_matrix_tracks_current_show_across_intensity_and_temporary_owners(self):
        controller, transport = self.controller()
        osc = transport.snapshot_for_render()
        baseline = controller._auto_show_state(osc, controller.config["auto_show"])
        red = self.composer_color(baseline, "ruby_lime")
        blue = self.composer_color(baseline, "cobalt_amber")

        def resolved(auto_show, **updates):
            frame = {**copy.deepcopy(auto_show), **updates}
            return controller._effective_slot_config(
                "head", controller.config["slots"]["head"], osc, frame,
                full_config=controller.config,
            )["_auto_show_rgbw"]

        self.assertEqual(MANUAL_COLOR_PRESETS["red"], resolved(red))
        self.assertEqual(MANUAL_COLOR_PRESETS["blue"], resolved(blue))

        controller.config["master_dimmer"] = .5
        preview = controller._preview_for_slot(
            "head", controller.config["slots"]["head"], osc, 100.0,
            full_config=controller.config, auto_show=blue,
        )
        self.assertEqual(MANUAL_COLOR_PRESETS["blue"][:3], (
            preview["resolved_red"], preview["resolved_green"], preview["resolved_blue"],
        ))
        self.assertEqual(MANUAL_COLOR_PRESETS["blue"], resolved(
            blue, rhythm_mode="chase", beat_pulse=True,
        ))

        white_hit = resolved(
            red,
            one_shot_active=True,
            one_shot_cue="white_hit",
            one_shot_progress=.5,
            one_shot_elapsed_beats=2.0,
        )
        self.assertEqual(MANUAL_COLOR_PRESETS["white"], white_hit)
        self.assertEqual(MANUAL_COLOR_PRESETS["blue"], resolved(blue))

        burst = resolved(
            red,
            one_shot_active=True,
            one_shot_cue="color_burst",
            one_shot_progress=.5,
            one_shot_elapsed_beats=.5,
            one_shot_color_steps_per_beat=4,
        )
        self.assertIn(burst, set(MANUAL_COLOR_PRESETS.values()))
        self.assertEqual(MANUAL_COLOR_PRESETS["blue"], resolved(blue))

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
        self.assertEqual(first["values"], first["rendered_final_values"])
        self.assertEqual(2, second["render_frame_sequence"])
        self.assertGreaterEqual(second["last_rendered"], first["last_rendered"])
        self.assertIsNone(second["last_sent"])
        self.assertTrue(second["rendered_final_values"])

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

    def test_every_remote_effect_reaches_its_existing_renderer_route_without_physical_dmx(self):
        controller, transport = self.controller()
        controller.config["slots"]["par_2"] = copy.deepcopy(controller.config["slots"]["par"])
        controller.config["slots"]["par_2"]["address"] = 17
        controller.config["slot_order"].append("par_2")
        osc = transport.snapshot_for_render()
        baseline = controller._auto_show_state(osc, controller.config["auto_show"])

        momentaries = {
            "manual_strobe": ("head", "override_manual_strobe", lambda value: value["strobe"] >= 220),
            "audience_sweep": ("head", "override_audience_sweep", lambda value: value["_live_override_audience_sweep"]),
            "all_on": ("head", "override_all_on", lambda value: value["dimmer"] == 255),
            "par_chase": ("par", "override_par_chase", lambda value: value["_auto_show_rhythm_mode"] == "pair_swap"),
            "par_snake": ("par", "override_par_snake", lambda value: value["_auto_show_rhythm_mode"] == "par_snake"),
        }
        for effect_id, (slot_id, field, assertion) in momentaries.items():
            with self.subTest(effect=effect_id):
                auto_show = dict(baseline); auto_show[field] = True
                rendered = controller._effective_slot_config(
                    slot_id, controller.config["slots"][slot_id], osc, auto_show, full_config=controller.config
                )
                self.assertTrue(assertion(rendered))

        for cue_id in ("audience_riser", "white_hit", "color_burst", "snap_fan", "mirror_bounce", "par_chase_burst"):
            with self.subTest(cue=cue_id):
                auto_show = dict(baseline)
                auto_show.update({"one_shot_active": True, "one_shot_cue": cue_id, "one_shot_progress": .5})
                slot_id = "par" if cue_id == "par_chase_burst" else "head"
                rendered = controller._effective_slot_config(
                    slot_id, controller.config["slots"][slot_id], osc, auto_show, full_config=controller.config
                )
                self.assertEqual(cue_id, rendered["_one_shot_cue_id"])

    def test_effect_color_ownership_matrix_preserves_underlying_manual_color(self):
        controller, transport = self.controller()
        osc = transport.snapshot_for_render()
        baseline = controller._auto_show_state(osc, controller.config["auto_show"])
        expected = MANUAL_COLOR_PRESETS["red"]

        hold_fields = {
            "manual_strobe": "override_manual_strobe",
            "audience_sweep": "override_audience_sweep",
            "all_on": "override_all_on",
            "par_chase": "override_par_chase",
            "par_snake": "override_par_snake",
        }
        for effect_id, field in hold_fields.items():
            with self.subTest(effect=effect_id):
                auto_show = dict(baseline)
                auto_show.update({"override_color": "red", field: True})
                rendered = controller._effective_slot_config(
                    "head", controller.config["slots"]["head"], osc, auto_show, full_config=controller.config
                )
                self.assertFalse(EFFECT_COLOR_OWNERSHIP[effect_id])
                self.assertEqual(expected, rendered["_auto_show_rgbw"])

        for effect_id in ("audience_riser", "snap_fan", "mirror_bounce", "par_chase_burst"):
            with self.subTest(effect=effect_id):
                auto_show = dict(baseline)
                auto_show.update({
                    "override_color": "red", "one_shot_active": True,
                    "one_shot_cue": effect_id, "one_shot_progress": .5,
                    "one_shot_elapsed_beats": 2.0,
                })
                rendered = controller._effective_slot_config(
                    "head", controller.config["slots"]["head"], osc, auto_show, full_config=controller.config
                )
                self.assertFalse(EFFECT_COLOR_OWNERSHIP[effect_id])
                self.assertEqual(expected, rendered["_auto_show_rgbw"])

    def test_strobe_preserves_combo_partitions_and_current_beat_parity(self):
        controller, transport = self.controller()
        controller.config["slots"]["par_2"] = copy.deepcopy(controller.config["slots"]["par"])
        controller.config["slots"]["par_2"]["address"] = 17
        controller.config["slot_order"].append("par_2")
        expected = {MANUAL_COLOR_PRESETS["purple"], MANUAL_COLOR_PRESETS["white"]}
        observed = []
        for beat in (24.0, 25.0):
            transport.state["beat_value"] = beat
            osc = transport.snapshot_for_render()
            auto_show = controller._auto_show_state(osc, controller.config["auto_show"])
            auto_show.update({"override_color": "none", "override_color_combo": "purple_white", "override_manual_strobe": True})
            frame = tuple(
                controller._effective_slot_config(slot_id, controller.config["slots"][slot_id], osc, auto_show, full_config=controller.config)["_auto_show_rgbw"]
                for slot_id in ("par", "par_2")
            )
            self.assertEqual(expected, set(frame))
            observed.append(frame)
        self.assertEqual(observed[0], tuple(reversed(observed[1])))

    def test_white_hit_and_color_burst_own_only_their_explicit_manual_presets(self):
        controller, transport = self.controller()
        osc = transport.snapshot_for_render()
        baseline = controller._auto_show_state(osc, controller.config["auto_show"])
        white_hit = dict(baseline)
        white_hit.update({"override_color": "red", "one_shot_active": True, "one_shot_cue": "white_hit", "one_shot_progress": .5, "one_shot_elapsed_beats": 2.0})
        white = controller._effective_slot_config("head", controller.config["slots"]["head"], osc, white_hit, full_config=controller.config)
        self.assertTrue(EFFECT_COLOR_OWNERSHIP["white_hit"])
        self.assertEqual(MANUAL_COLOR_PRESETS["white"], white["_auto_show_rgbw"])

        observed = []
        for step in range(len(COLOR_BURST_PRESET_SEQUENCE) * 2):
            auto_show = dict(baseline)
            auto_show.update({
                "override_color": "red", "one_shot_active": True, "one_shot_cue": "color_burst",
                "one_shot_progress": .5, "one_shot_elapsed_beats": step / COLOR_BURST_SUBDIVISIONS_PER_BEAT,
                "one_shot_color_steps_per_beat": COLOR_BURST_SUBDIVISIONS_PER_BEAT,
            })
            rendered = controller._effective_slot_config(
                "head", controller.config["slots"]["head"], osc, auto_show, full_config=controller.config
            )
            observed.append(rendered["_auto_show_rgbw"])
        self.assertTrue(EFFECT_COLOR_OWNERSHIP["color_burst"])
        self.assertTrue(set(observed).issubset(set(MANUAL_COLOR_PRESETS.values())))
        self.assertGreater(len(set(observed)), 6)
        self.assertTrue(all(left != right for left, right in zip(observed, observed[1:])))

        restored = controller._effective_slot_config(
            "head", controller.config["slots"]["head"], osc,
            {**baseline, "override_color": "red"}, full_config=controller.config,
        )
        self.assertEqual(MANUAL_COLOR_PRESETS["red"], restored["_auto_show_rgbw"])

    def test_fx_speed_auto_uses_effective_energy_with_hysteresis_and_manual_wins(self):
        controller, _ = self.controller()
        self.assertEqual("slow", controller._resolved_fx_speed("auto", .30))
        self.assertEqual("slow", controller._resolved_fx_speed("auto", .47))
        self.assertEqual("mid", controller._resolved_fx_speed("auto", .52))
        self.assertEqual("mid", controller._resolved_fx_speed("auto", .73))
        self.assertEqual("fast", controller._resolved_fx_speed("auto", .80))
        self.assertEqual("slow", controller._resolved_fx_speed("slow", .95))

    def test_one_shot_fx_speed_is_captured_at_activation_and_progress_uses_stored_duration(self):
        controller, transport = self.controller()
        for speed in ("slow", "mid", "fast"):
            with self.subTest(speed=speed):
                controller.config["auto_show"]["override_fx_speed"] = speed
                controller.trigger_one_shot_cue("audience_riser")
                self.assertEqual(speed, controller.active_one_shot_cue["fx_speed"])
                self.assertEqual(
                    ONE_SHOT_FX_SPEED_POLICY["audience_riser"][speed],
                    controller.active_one_shot_cue["duration_beats"],
                )

        controller.config["auto_show"]["override_fx_speed"] = "slow"
        transport.state["beat_value"] = 100.0
        controller.trigger_one_shot_cue("snap_fan")
        controller.config["auto_show"]["override_fx_speed"] = "fast"
        transport.state["beat_value"] = 102.0
        state = controller._resolved_one_shot_cue_state(transport.snapshot_for_render())
        self.assertEqual(8.0, state["duration_beats"])
        self.assertAlmostEqual(.25, state["progress"])

        transport.state["beat_value"] = None
        frozen = controller._resolved_one_shot_cue_state(
            transport.snapshot_for_render(), now=controller.active_one_shot_cue["started_at"] + 120
        )
        self.assertAlmostEqual(state["progress"], frozen["progress"])

    def test_white_hit_duration_is_fixed_and_color_burst_rate_is_beat_based(self):
        controller, transport = self.controller()
        for speed in ("slow", "mid", "fast"):
            controller.config["auto_show"]["override_fx_speed"] = speed
            controller.trigger_one_shot_cue("white_hit")
            self.assertEqual(4.0, controller.active_one_shot_cue["duration_beats"])

        for bpm in (100.0, 128.0, 160.0):
            transport.state["bpm"] = bpm
            for speed, subdivisions in COLOR_BURST_STEPS_PER_BEAT.items():
                auto_show = {
                    "one_shot_elapsed_beats": .5,
                    "one_shot_color_steps_per_beat": subdivisions,
                }
                expected = COLOR_BURST_PRESET_SEQUENCE[int(.5 * subdivisions)]
                self.assertEqual(expected, controller._color_burst_preset_name(auto_show))

    def test_master_dimmer_scales_only_profile_declared_luminous_channels(self):
        controller, _ = self.controller()

        native = controller.config["slots"]["par"]
        native_values = {native["address"] + offset: 200 for offset in range(8)}
        native_dimmed = controller._apply_master_dimmer_to_slot_values(native, native_values, .5)
        self.assertEqual(100, native_dimmed[native["address"]])
        self.assertEqual(200, native_dimmed[native["address"] + 1])  # exact red
        self.assertEqual(200, native_dimmed[native["address"] + 5])  # strobe rate

        rgb = controller.default_slot_config("rgb", fixture_id="uking_zq06016", mode="C001", address=100)
        rgb_values = {100: 200, 101: 100, 102: 50}
        self.assertEqual(
            {100: 50, 101: 25, 102: 12},
            controller._apply_master_dimmer_to_slot_values(rgb, rgb_values, .25),
        )

        blaze = controller.default_slot_config(
            "blaze", fixture_id="beamz_blaze_series_rgba_fogger", mode="8ch", address=200
        )
        blaze_values = {channel: 80 for channel in range(200, 208)}
        blaze_dimmed = controller._apply_master_dimmer_to_slot_values(blaze, blaze_values, .5)
        self.assertEqual(80, blaze_dimmed[200])  # fog excluded
        self.assertEqual(40, blaze_dimmed[201])  # native master intensity
        self.assertEqual(80, blaze_dimmed[202])  # color identity stays exact
        self.assertEqual(80, blaze_dimmed[206])  # strobe rate excluded
        self.assertEqual(80, blaze_dimmed[207])  # macro excluded

    def test_master_dimmer_updates_authoritative_output_offline_and_blackout_retains_it(self):
        controller, _ = self.controller()
        controller.update_config({"master_dimmer": 1.0})
        full = dict(controller.current_values)
        controller.update_config({"master_dimmer": .35})
        dimmed = dict(controller.current_values)
        self.assertFalse(controller.connected)
        self.assertEqual(.35, controller.state()["master_dimmer"])
        self.assertNotEqual(full, dimmed)
        controller.blackout()
        self.assertEqual({}, controller.current_values)
        controller.update_config({"blackout_active": False})
        self.assertEqual(.35, controller.state()["master_dimmer"])
        self.assertTrue(controller.current_values)

    def test_remote_master_dimmer_command_scales_the_live_final_frame_at_every_quarter(self):
        """Exercise the real Remote V2 command route, not only the helper."""
        controller, _ = self.controller()
        previous_dmx = beatbeam_app.DMX
        previous_access = beatbeam_app.REMOTE_ACCESS_CONFIG
        previous_results = dict(beatbeam_app.REMOTE_CONTROL_RESULTS)
        try:
            beatbeam_app.DMX = controller
            beatbeam_app.REMOTE_ACCESS_CONFIG = {"remote_credentials": {
                "live-control": {"scope": "REMOTE_READ", "scopes": ["REMOTE_READ", "LIVE_CONTROL"], "client_id": "test-ipad"},
            }}
            beatbeam_app.REMOTE_CONTROL_RESULTS.clear()
            with patch("beatbeam_app.remote_live_state_v2", return_value={"state_revision": 9, "event_sequence": 9}):
                controller.update_config({"master_dimmer": 1.0})
                self.tick(controller)
                dimmer_channel = controller.config["slots"]["par"]["address"]
                full_dimmer = controller.current_final_values[dimmer_channel]
                for index, factor in enumerate((1.0, .75, .50, .25, 0.0)):
                    result = beatbeam_app.remote_live_control_command(
                        "live-control",
                        {"command_id": f"master-quarter-{index}", "action": "set_master_dimmer", "value": f"{factor:.2f}"},
                    )
                    self.assertTrue(result["accepted"])
                    self.tick(controller)
                    self.assertEqual(factor, controller.state()["master_dimmer"])
                    self.assertEqual(round(full_dimmer * factor), controller.current_final_values[dimmer_channel])
                    output = _remote_live_output_preview(controller.state())
                    par = next(fixture for fixture in output["fixtures"] if fixture["id"] == "par")
                    self.assertEqual(round(full_dimmer * factor), par["dimmer"])
                    self.assertFalse(output["blackout"])
        finally:
            beatbeam_app.DMX = previous_dmx
            beatbeam_app.REMOTE_ACCESS_CONFIG = previous_access
            beatbeam_app.REMOTE_CONTROL_RESULTS.clear()
            beatbeam_app.REMOTE_CONTROL_RESULTS.update(previous_results)

    def test_rendered_fixture_intensity_projection_tracks_master_without_rgb_luminance(self):
        controller, transport = self.controller()
        controller.config["slots"]["wall_wash"] = controller._clean_slot_config(
            "wall_wash",
            controller.default_slot_config("wall_wash", fixture_id="uking_zq06016", address=50),
        )
        controller.config["slot_order"].append("wall_wash")
        controller.config["auto_show"]["override_color"] = "red"

        def render(master, color):
            controller.config["master_dimmer"] = master
            controller.config["auto_show"]["override_color"] = color
            with patch("beatbeam_app.time.time", return_value=300.0):
                self.tick(controller)
            state = controller.state()
            previews = state["slot_previews"]
            output = _remote_live_output_preview(state)
            remote = {fixture["id"]: fixture for fixture in output["fixtures"]}
            return previews, remote

        full, remote_full = render(1.0, "red")
        half, remote_half = render(.5, "red")
        quarter, remote_quarter = render(.25, "red")
        dark, remote_dark = render(0.0, "red")
        for slot_id in ("par", "head", "wall_wash"):
            with self.subTest(slot=slot_id):
                self.assertAlmostEqual(full[slot_id]["effective_intensity"] * .5, half[slot_id]["effective_intensity"], places=6)
                self.assertAlmostEqual(full[slot_id]["effective_intensity"] * .25, quarter[slot_id]["effective_intensity"], places=6)
                self.assertEqual(0.0, dark[slot_id]["effective_intensity"])
                self.assertEqual(half[slot_id]["effective_intensity"], remote_half[slot_id]["effective_intensity"])
                self.assertEqual(0.0, remote_dark[slot_id]["effective_intensity"])

        red, _ = render(.5, "red")
        blue, _ = render(.5, "blue")
        white, _ = render(.5, "white")
        for slot_id in ("par", "head", "wall_wash"):
            with self.subTest(color_independent_slot=slot_id):
                self.assertEqual(red[slot_id]["effective_intensity"], blue[slot_id]["effective_intensity"])
                self.assertEqual(red[slot_id]["effective_intensity"], white[slot_id]["effective_intensity"])
        self.assertEqual(255, remote_full["par"]["resolved_red"])

    def test_manual_zone_color_preserves_brightness_without_a_native_dimmer(self):
        controller, transport = self.controller()
        slot = controller.default_slot_config(
            "wash", fixture_id="uking_zq06016", mode="P001", address=100
        )
        effective = {
            **slot,
            "_auto_show_zone_rgb": [MANUAL_COLOR_PRESETS["red"]] * 8,
            "_auto_show_rgbw": MANUAL_COLOR_PRESETS["red"],
            "_manual_color_override": True,
            "_force_rgbw_override": True,
            "_slot_context": {"role": "wash", "member_count": 1, "member_index": 0},
        }
        osc = transport.snapshot_for_render()
        with patch.object(controller, "_effective_brightness_with_motion", side_effect=(64, 192)):
            low = controller._render_slot_values("wash", effective, osc, 1.0, advance_motion=False)
            high = controller._render_slot_values("wash", effective, osc, 1.0, advance_motion=False)
        self.assertLess(low[100], high[100])
        self.assertEqual(0, low[101])
        self.assertEqual(0, high[101])

    def test_manual_single_and_combo_preserve_par_chase_dimmer_and_participation(self):
        controller, transport = self.controller()
        for index in range(2, 5):
            slot_id = f"par_{index}"
            controller.config["slots"][slot_id] = copy.deepcopy(controller.config["slots"]["par"])
            controller.config["slots"][slot_id]["address"] = 20 + index * 10
            controller.config["slot_order"].append(slot_id)
        slots = ("par", "par_2", "par_3", "par_4")

        for color, combo in (("red", "none"), ("cyan", "none"), ("none", "purple_white"), ("none", "blue_orange")):
            with self.subTest(color=color, combo=combo):
                frames = []
                for beat in (24.0, 25.0):
                    transport.state["beat_value"] = beat
                    osc = transport.snapshot_for_render()
                    osc["beat_phase_age_seconds"] = .1
                    auto_show = controller._auto_show_state(osc, controller.config["auto_show"])
                    auto_show.update({
                        "override_color": color,
                        "override_color_combo": combo,
                        "override_par_chase": True,
                    })
                    brightness = []
                    for slot_id in slots:
                        effective = controller._effective_slot_config(
                            slot_id, controller.config["slots"][slot_id], osc, auto_show,
                            full_config=controller.config,
                        )
                        brightness.append(controller._brightness_for_config(effective, osc, 300.0))
                    frames.append(brightness)
                self.assertEqual(2, sum(value > 0 for value in frames[0]))
                self.assertEqual(2, sum(value > 0 for value in frames[1]))
                self.assertEqual([value == 0 for value in frames[0]], [value > 0 for value in frames[1]])

    def test_manual_color_changes_only_rgbw_while_existing_movement_continues(self):
        controller, transport = self.controller()
        osc = transport.snapshot_for_render()
        baseline = controller._auto_show_state(osc, controller.config["auto_show"])
        base_config = controller._effective_slot_config(
            "head", controller.config["slots"]["head"], osc, baseline,
            full_config=controller.config,
        )
        base_motion = controller._motion_for_config("head", base_config, osc)
        self.assertIsNotNone(base_motion)
        for color, combo in (("cyan", "none"), ("none", "purple_white")):
            manual = dict(baseline)
            manual.update({"override_color": color, "override_color_combo": combo})
            effective = controller._effective_slot_config(
                "head", controller.config["slots"]["head"], osc, manual,
                full_config=controller.config,
            )
            self.assertEqual(base_motion, controller._motion_for_config("head", effective, osc))

    def test_manual_colors_render_authoritative_offline_output_without_dmx(self):
        controller, _ = self.controller()
        rendered = {}
        with patch("beatbeam_app.time.time", return_value=300.0):
            for color in ("red", "blue", "yellow", "cyan", "none"):
                auto_show = dict(controller.config["auto_show"])
                auto_show["override_color"] = color
                controller.update_config({"auto_show": auto_show})
                state = controller.state()
                self.assertFalse(state["connected"])
                self.assertIsNone(state["last_sent"])
                self.assertTrue(state["rendered_final_values"])
                rendered[color] = dict(state["rendered_final_values"])
        self.assertNotEqual(rendered["red"], rendered["blue"])
        self.assertNotEqual(rendered["yellow"], rendered["cyan"])
        self.assertNotEqual(rendered["cyan"], rendered["none"])

    def test_manual_color_combos_render_only_the_two_exact_presets_offline(self):
        controller, _ = self.controller()
        with patch("beatbeam_app.time.time", return_value=300.0):
            for combo_id, colors in MANUAL_COLOR_COMBOS.items():
                with self.subTest(combo=combo_id):
                    auto_show = dict(controller.config["auto_show"])
                    auto_show.update({"override_color": "none", "override_color_combo": combo_id})
                    controller.update_config({"auto_show": auto_show})
                    preview = _remote_live_output_preview(controller.state())
                    self.assertFalse(preview["physical_output_available"])
                    rendered = [
                        (fixture["red"], fixture["green"], fixture["blue"], fixture["white"])
                        for fixture in preview["fixtures"]
                        if any(fixture[channel] for channel in ("red", "green", "blue", "white"))
                    ]
                    expected = [MANUAL_COLOR_PRESETS[color] for color in colors]
                    # RGB-only fixtures are the established capability projection
                    # of Manual WHITE: its RGB stays exact while W is absent/0.
                    # No channel may become a blend or brightness-scaled colour.
                    self.assertTrue(all(any(
                        value[:3] == preset[:3] and value[3] in {0, preset[3]}
                        for preset in expected
                    ) for value in rendered))
                    self.assertEqual({value[:3] for value in rendered}, {preset[:3] for preset in expected})

            controller.blackout()
            self.assertTrue(_remote_live_output_preview(controller.state())["blackout"])
            controller.update_config({"blackout_active": False})
            restored = _remote_live_output_preview(controller.state())
            self.assertEqual(
                {preset[:3] for preset in (MANUAL_COLOR_PRESETS[color] for color in MANUAL_COLOR_COMBOS[combo_id])},
                {(fixture["red"], fixture["green"], fixture["blue"]) for fixture in restored["fixtures"]},
            )

    def test_hold_effects_and_cue_shots_render_and_release_without_dmx(self):
        controller, _ = self.controller()
        with patch("beatbeam_app.time.time", return_value=300.0):
            baseline_auto_show = dict(controller.config["auto_show"])
            controller.update_config({"auto_show": baseline_auto_show})
            baseline = dict(controller.current_final_values)
            for field in (
                "override_manual_strobe", "override_audience_sweep", "override_all_on",
                "override_par_chase", "override_par_snake",
            ):
                with self.subTest(hold=field):
                    pressed = dict(baseline_auto_show); pressed[field] = True
                    controller.update_config({"auto_show": pressed})
                    self.assertNotEqual(baseline, controller.current_final_values)
                    pressed_frame = dict(controller.current_final_values)
                    released = dict(baseline_auto_show); released[field] = False
                    controller.update_config({"auto_show": released})
                    self.assertFalse(controller.current_auto_show[field])
                    self.assertNotEqual(pressed_frame, controller.current_final_values)
                    self.assertIsNone(controller.state()["last_sent"])
            for cue in ("audience_riser", "white_hit", "color_burst", "snap_fan", "mirror_bounce", "par_chase_burst"):
                with self.subTest(cue=cue):
                    controller.trigger_one_shot_cue(cue)
                    self.assertEqual(cue, controller.active_one_shot_cue["id"])
                    self.assertTrue(controller.current_final_values)
                    self.assertIsNone(controller.state()["last_sent"])

    def test_offline_blackout_zeros_final_output_then_rendering_resumes(self):
        controller, _ = self.controller()
        with patch("beatbeam_app.time.time", return_value=300.0):
            controller.update_config({"auto_show": dict(controller.config["auto_show"])})
            self.assertTrue(controller.current_final_values)
            controller.blackout()
            state = controller.state()
            self.assertEqual({}, state["rendered_final_values"])
            self.assertIsNone(state["last_sent"])
            controller.update_config({"blackout_active": False})
            self.assertTrue(controller.state()["rendered_final_values"])

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

    def test_new_track_handoff_keeps_the_previous_dynamic_composer_effect_for_two_seconds(self):
        transport = PreviewTransport()
        controller = DmxController(transport, ProductionAuthorityBridge())
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"].update({"enabled": True, "preview_rme_mode": "DYNAMIC_COMPOSER"})
        controller.config["production_show_mode"] = "DYNAMIC_COMPOSER_ENABLED"
        controller.render_active = True

        with patch("beatbeam_app.time.monotonic", return_value=100.0):
            self.tick(controller)
        before = controller.state()["production_show_selector"]
        transport.state["track_path"] = "/Music/Preview/Next Track.flac"
        transport.state["_playback_generation"] = 2
        with patch("beatbeam_app.time.monotonic", return_value=100.2):
            self.tick(controller)
        held = controller.state()["production_show_selector"]
        with patch("beatbeam_app.time.monotonic", return_value=102.01):
            self.tick(controller)
        expired = controller.state()["production_show_selector"]

        self.assertEqual("dynamic_composer", before["production_show_source"])
        self.assertEqual("dynamic_composer", held["production_show_source"])
        self.assertTrue(held["handoff_effect_hold"])
        self.assertEqual("handoff_effect_hold", held["fallback_reason"])
        self.assertEqual("/Music/Preview/Track.flac", held["handoff_effect_hold_from_track_path"])
        self.assertEqual("existing_autoshow", expired["production_show_source"])
        self.assertFalse(expired["handoff_effect_hold"])
        self.assertEqual("track_mismatch", expired["fallback_reason"])

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

    def test_dmx_dispatch_error_does_not_make_healthy_dynamic_renderer_ineligible(self):
        transport = PreviewTransport()
        controller = DmxController(transport, ProductionAuthorityBridge())
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"].update({"enabled": True, "preview_rme_mode": "DYNAMIC_COMPOSER"})
        controller.config["production_show_mode"] = "DYNAMIC_COMPOSER_ENABLED"
        controller.render_active = controller.connected = controller.running = True
        controller.dmx = FailOnceDmx()

        self.assertTrue(controller._render_tick())
        first = controller.state()
        self.assertEqual("dynamic_composer", first["production_show_selector"]["production_show_source"])
        self.assertTrue(first["production_show_selector"]["renderer_healthy"])
        self.assertTrue(first["renderer_health"]["healthy"])
        self.assertIn("dmx dispatch failure", first["error"])

        self.assertFalse(controller._render_tick())
        second = controller.state()
        self.assertEqual("dynamic_composer", second["production_show_selector"]["production_show_source"])
        self.assertIsNone(second["production_show_selector"]["fallback_reason"])
        self.assertTrue(second["renderer_health"]["healthy"])
        self.assertEqual(1, second["playback"]["dmx_dispatch_failures"])

    def test_renderer_health_failure_falls_back_then_recovers_without_restart(self):
        transport = PreviewTransport()
        controller = DmxController(transport, ProductionAuthorityBridge())
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"].update({"enabled": True, "preview_rme_mode": "DYNAMIC_COMPOSER"})
        controller.config["production_show_mode"] = "DYNAMIC_COMPOSER_ENABLED"
        controller.render_active = True
        controller.renderer_error = "synthetic renderer fault"

        self.tick(controller)
        fallback = controller.state()
        self.assertEqual("existing_autoshow", fallback["production_show_selector"]["production_show_source"])
        self.assertEqual("renderer_unhealthy", fallback["production_show_selector"]["fallback_reason"])
        self.assertFalse(fallback["production_show_selector"]["renderer_healthy"])
        self.assertTrue(fallback["renderer_health"]["healthy"])

        self.tick(controller)
        recovered = controller.state()
        self.assertEqual("dynamic_composer", recovered["production_show_selector"]["production_show_source"])
        self.assertIsNone(recovered["production_show_selector"]["fallback_reason"])
        self.assertTrue(recovered["production_show_selector"]["renderer_healthy"])

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
        self.assertEqual(
            "preview_auto_show motion + selected_production_auto_show color -> slot_previews",
            differential["selected_preview_source"],
        )

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
        self.assertEqual("build_rising_sweep", differential["selected_primitives"]["moving"]["movement_pattern"])
        self.assertEqual("amber_teal", differential["selected_primitives"]["par"]["palette"])
        self.assertEqual("center_out_build", differential["selected_primitives"]["wash"]["wash_cue"])
        self.assertIn("Dynamic Composer • RME Build", differential["preview_cue"])
        self.assertNotEqual(baseline_previews["head"]["target_pan"], state["slot_previews"]["head"]["target_pan"])
        self.assertEqual(
            tuple(baseline_previews["par"][channel] for channel in ("red", "green", "blue")),
            tuple(state["slot_previews"]["par"][channel] for channel in ("red", "green", "blue")),
        )
        self.assertEqual(
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

    def test_production_composer_without_current_rme_keeps_active_finite_output(self):
        transport = PreviewTransport()
        bridge = ProductionAuthorityBridge()
        original_project = bridge.handoff.project

        def without_event(state, include_shadow=False, include_rich_events=False):
            result = original_project(state, include_shadow, include_rich_events)
            if result:
                result["rich_musical_events"]["events"] = []
            return result

        bridge.handoff.project = without_event
        controller = DmxController(transport, bridge)
        controller.config = controller._clean_full_config(controller.default_config())
        controller.config["auto_show"].update({"enabled": True, "preview_rme_mode": "DYNAMIC_COMPOSER"})
        controller.config["production_show_mode"] = "DYNAMIC_COMPOSER_ENABLED"
        controller.render_active = True

        with patch("beatbeam_app.time.time", return_value=300.0):
            self.tick(controller)

        state = controller.state()
        self.assertEqual("dynamic_composer", state["production_show_selector"]["production_show_source"])
        self.assertIsNone(state["rme_preview_differential"]["event"])
        self.assertTrue(state["rme_preview_differential"]["dynamic_composer_active"])
        self.assertIsNone(state["renderer_health"]["error"])
        self.assertTrue(controller.current_values)
        self.assertTrue(all(
            math.isfinite(float(value))
            for value in controller.current_values.values()
        ))

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
