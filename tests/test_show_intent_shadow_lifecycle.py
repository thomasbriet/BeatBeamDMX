import json
import threading
import unittest
from unittest.mock import patch

import beatbeam_app
from beatbeam_app import DmxController
from show_interpreter_input_adapter import ShowInterpreterEffectiveContext


VALID_A = ShowInterpreterEffectiveContext(True, "build", 0.04)
VALID_B = ShowInterpreterEffectiveContext(True, "break", -0.04)


def playback(path="/Music/Example/A.flac", generation=1, event="virtualdj_active",
             source="virtualdj"):
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


class LifecycleTransport:
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


class LifecycleBridge:
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


class ShowIntentShadowLifecycleTests(unittest.TestCase):
    def controller(self):
        transport = LifecycleTransport()
        controller = DmxController(transport, LifecycleBridge())
        config = controller._clean_full_config(controller.default_config())
        config["auto_show"]["enabled"] = True
        return controller, transport, config

    def update(self, controller, context, **values):
        controller._update_show_intent_shadow(context, playback(**values))
        return dict(controller._show_intent_shadow_diagnostics)

    def assert_neutral_reset(self, shadow, reason):
        self.assertEqual((True, reason, "unknown", 0.0, False, False), (
            shadow["lifecycle_reset"], shadow["lifecycle_reason"],
            shadow["resolved_section_bucket"], shadow["resolved_energy_modifier"],
            shadow["retained_previous"], shadow["stale_warning"],
        ))

    def test_first_frame_and_same_track_gaps_preserve_continuity(self):
        controller, _, _ = self.controller()
        first = self.update(controller, None)
        self.assertEqual((False, None, "unknown", 0.0, False, False), (
            first["lifecycle_reset"], first["lifecycle_reason"],
            first["resolved_section_bucket"], first["resolved_energy_modifier"],
            first["retained_previous"], first["stale_warning"],
        ))

        self.update(controller, VALID_A, generation=2)
        gap_one = self.update(controller, None, path=None, generation=2)
        gap_two = self.update(controller, None, path=None, generation=2)
        for shadow in (gap_one, gap_two):
            self.assertEqual((False, None, "build", 0.04, True, True), (
                shadow["lifecycle_reset"], shadow["lifecycle_reason"],
                shadow["resolved_section_bucket"], shadow["resolved_energy_modifier"],
                shadow["retained_previous"], shadow["stale_warning"],
            ))

    def test_track_change_replaces_directly_or_resets_to_neutral(self):
        controller, _, _ = self.controller()
        self.update(controller, VALID_A)
        changed = self.update(controller, VALID_B, path="/Music/Example/B.flac",
                              generation=2, event="track_changed")
        self.assertEqual((True, "track_changed", "break", -0.04, False, False), (
            changed["lifecycle_reset"], changed["lifecycle_reason"],
            changed["resolved_section_bucket"], changed["resolved_energy_modifier"],
            changed["retained_previous"], changed["stale_warning"],
        ))

        controller, _, _ = self.controller()
        self.update(controller, VALID_A)
        self.assert_neutral_reset(self.update(controller, None, path="/Music/Example/B.flac",
                                              generation=2, event="track_changed"), "track_changed")

    def test_hard_seeks_reset_with_and_without_candidate(self):
        for event in ("position_jump_backward", "position_jump_forward"):
            with self.subTest(event=event, candidate=True):
                controller, _, _ = self.controller()
                self.update(controller, VALID_A)
                shadow = self.update(controller, VALID_B, generation=2, event=event)
                self.assertEqual((True, event, "break", -0.04), (
                    shadow["lifecycle_reset"], shadow["lifecycle_reason"],
                    shadow["resolved_section_bucket"], shadow["resolved_energy_modifier"],
                ))
            with self.subTest(event=event, candidate=False):
                controller, _, _ = self.controller()
                self.update(controller, VALID_A)
                self.assert_neutral_reset(self.update(controller, None, generation=2, event=event), event)

    def test_deck_change_resets_even_when_path_is_equal(self):
        controller, _, _ = self.controller()
        self.update(controller, VALID_A)
        shadow = self.update(controller, VALID_B, generation=2, event="deck_changed")
        self.assertEqual((True, "deck_changed", "break", -0.04), (
            shadow["lifecycle_reset"], shadow["lifecycle_reason"],
            shadow["resolved_section_bucket"], shadow["resolved_energy_modifier"],
        ))

    def test_source_unavailable_and_generation_only_do_not_reset(self):
        controller, _, _ = self.controller()
        self.update(controller, VALID_A)
        unavailable = self.update(controller, None, path=None, generation=2,
                                  event="source_unavailable", source=None)
        self.assertEqual((False, None, "build", 0.04, True, True), (
            unavailable["lifecycle_reset"], unavailable["lifecycle_reason"],
            unavailable["resolved_section_bucket"], unavailable["resolved_energy_modifier"],
            unavailable["retained_previous"], unavailable["stale_warning"],
        ))

        controller, _, _ = self.controller()
        self.update(controller, VALID_A)
        generation_only = self.update(controller, None, generation=2)
        self.assertEqual((False, None, "build", 0.04, True, True), (
            generation_only["lifecycle_reset"], generation_only["lifecycle_reason"],
            generation_only["resolved_section_bucket"], generation_only["resolved_energy_modifier"],
            generation_only["retained_previous"], generation_only["stale_warning"],
        ))

    def test_pause_and_explicit_generation_boundary_have_separate_semantics(self):
        controller, _, _ = self.controller()
        self.update(controller, VALID_A)
        paused = self.update(controller, None, event="paused")
        self.assertEqual((False, None, "build", 0.04, True, True), (
            paused["lifecycle_reset"], paused["lifecycle_reason"],
            paused["resolved_section_bucket"], paused["resolved_energy_modifier"],
            paused["retained_previous"], paused["stale_warning"],
        ))

        controller, _, _ = self.controller()
        self.update(controller, VALID_A)
        self.assert_neutral_reset(self.update(controller, None, generation=2,
                                              event="position_jump_backward"), "position_jump_backward")

    def test_state_debug_is_json_safe_and_passive(self):
        controller, _, _ = self.controller()
        self.update(controller, VALID_A)
        before = (
            controller._show_intent_shadow_resolved,
            controller._show_intent_shadow_lifecycle_seen,
            controller._show_intent_shadow_last_track_identity,
            controller._show_intent_shadow_last_playback_generation,
            controller._show_intent_shadow_last_playback_event,
            dict(controller._show_intent_shadow_diagnostics),
        )
        first, second = controller.state()["show_intent_shadow"], controller.state()["show_intent_shadow"]
        self.assertEqual(before[-1], first)
        self.assertEqual(first, second)
        self.assertIn("lifecycle_reset", first)
        self.assertIn("lifecycle_reason", first)
        json.dumps(first)
        self.assertEqual(before, (
            controller._show_intent_shadow_resolved,
            controller._show_intent_shadow_lifecycle_seen,
            controller._show_intent_shadow_last_track_identity,
            controller._show_intent_shadow_last_playback_generation,
            controller._show_intent_shadow_last_playback_event,
            dict(controller._show_intent_shadow_diagnostics),
        ))

    def test_send_loop_resolves_once_and_lifecycle_stays_shadow_only(self):
        controller, transport, config = self.controller()
        auto_show = controller._auto_show_state(transport.snapshot_for_render(), config["auto_show"])
        controller._auto_show_evaluation = lambda *_: (auto_show, VALID_A)
        controller._render_values = lambda *args, **kwargs: setattr(controller, "running", False) or {}
        controller._build_slot_previews = lambda *args, **kwargs: {}
        controller._send_dmx_frame = lambda *args, **kwargs: None
        controller.running = True
        controller.dmx = object()
        with patch("beatbeam_app.resolve_show_intent", wraps=beatbeam_app.resolve_show_intent) as resolver:
            controller._send_loop()
        self.assertEqual(1, resolver.call_count)

        plain, plain_transport, config = self.controller()
        shadow, shadow_transport, _ = self.controller()
        plain_auto_show = plain._auto_show_state(plain_transport.snapshot_for_render(), config["auto_show"])
        shadow_auto_show, context = shadow._auto_show_evaluation(
            shadow_transport.snapshot_for_render(), config["auto_show"]
        )
        shadow._update_show_intent_shadow(context, shadow_transport.snapshot_for_render())
        self.assertEqual(plain_auto_show, shadow_auto_show)
        self.assertEqual(
            plain._render_values(1.0, advance_motion=False, config=config,
                                 osc=plain_transport.snapshot_for_render(), auto_show=plain_auto_show),
            shadow._render_values(1.0, advance_motion=False, config=config,
                                  osc=shadow_transport.snapshot_for_render(), auto_show=shadow_auto_show),
        )


if __name__ == "__main__":
    unittest.main()
