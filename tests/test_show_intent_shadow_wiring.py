import json
from pathlib import Path
import threading
import unittest

from beatbeam_app import DmxController
from show_interpreter_input_adapter import ShowInterpreterEffectiveContext


def playback(phrase="verse"):
    return {
        "_active_playback_source": "virtualdj",
        "track_path": "/Music/Example/Shadow.flac",
        "time_seconds": 18.0,
        "bpm": 126.0,
        "beat_value": 12.0,
        "phrase_current": phrase,
        "stale": False,
    }


def behavior(bucket="build", energy=1.0, valid=True):
    return {
        "selected_source": "song_analyzer",
        "effective_source": "song_analyzer" if valid else "legacy",
        "eligible": valid,
        "fallback_reason": None if valid else "track_not_exact",
        "legacy_phrase": "verse",
        "mapped_behavior_bucket": bucket if valid else None,
        "song_analyzer_label": "Up 1" if valid else None,
        "projection": {"rich_current": {"energy": energy}} if valid else None,
    }


class ShadowTransport:
    def __init__(self, state, selected_source="song_analyzer"):
        self._state = dict(state)
        self._selected_source = selected_source
        self.lock = threading.Lock()
        self.decks = {}

    def snapshot_for_render(self):
        return dict(self._state)

    def developer_playback_state(self):
        return {}

    def structure_behavior_source(self):
        return self._selected_source


class ShadowBridge:
    def __init__(self, resolved):
        self.resolved = resolved

    def resolve(self, selected_source, transport_state):
        return dict(self.resolved)


class ShowIntentShadowWiringTests(unittest.TestCase):
    def controller(self, resolved=None, phrase="verse"):
        transport = ShadowTransport(playback(phrase))
        controller = DmxController(transport, ShadowBridge(resolved or behavior()))
        config = controller._clean_full_config(controller.default_config())
        config["auto_show"]["enabled"] = True
        return controller, transport, config

    def test_valid_canonical_snapshot_reuses_existing_modifier_and_resolves_intent(self):
        controller, transport, config = self.controller(behavior("build", 1.0))

        auto_show, context = controller._auto_show_evaluation(
            transport.snapshot_for_render(), config["auto_show"]
        )
        controller._update_show_intent_shadow(context)

        shadow = controller._show_intent_shadow_diagnostics
        self.assertEqual("build", auto_show["phrase_bucket"])
        self.assertEqual((True, "build", 0.04), (
            context.source_is_valid, context.section_bucket, context.energy_modifier,
        ))
        self.assertEqual("build", shadow["input_section_bucket"])
        self.assertEqual(0.04, shadow["input_energy_modifier"])
        self.assertEqual(("build", 0.04), (
            shadow["resolved_section_bucket"], shadow["resolved_energy_modifier"],
        ))
        self.assertTrue(shadow["input_present"])
        self.assertTrue(shadow["candidate_present"])

    def test_legacy_and_manual_override_never_become_shadow_input(self):
        legacy, legacy_transport, legacy_config = self.controller(behavior(valid=False), phrase="chorus")
        legacy_auto_show, legacy_context = legacy._auto_show_evaluation(
            legacy_transport.snapshot_for_render(), legacy_config["auto_show"]
        )
        legacy._update_show_intent_shadow(legacy_context)

        self.assertEqual("chorus", legacy_auto_show["phrase_bucket"])
        self.assertIsNone(legacy_context)
        self.assertFalse(legacy._show_intent_shadow_diagnostics["input_present"])
        self.assertEqual("unknown", legacy._show_intent_shadow_diagnostics["resolved_section_bucket"])

        override, override_transport, override_config = self.controller(behavior("build", 1.0))
        override_config["auto_show"]["override_phrase"] = "chorus"
        override_auto_show, override_context = override._auto_show_evaluation(
            override_transport.snapshot_for_render(), override_config["auto_show"]
        )
        override._update_show_intent_shadow(override_context)

        self.assertEqual("chorus", override_auto_show["phrase_bucket"])
        self.assertEqual("build", override_context.section_bucket)
        self.assertEqual("build", override._show_intent_shadow_diagnostics["resolved_section_bucket"])

    def test_auto_show_state_and_state_reads_do_not_mutate_shadow_continuity(self):
        controller, transport, config = self.controller(behavior("drop", 2.0))
        _, context = controller._auto_show_evaluation(transport.snapshot_for_render(), config["auto_show"])
        controller._update_show_intent_shadow(context)
        resolved = controller._show_intent_shadow_resolved
        diagnostics = dict(controller._show_intent_shadow_diagnostics)

        controller._auto_show_state(transport.snapshot_for_render(), config["auto_show"])
        state = controller.state()

        self.assertIs(resolved, controller._show_intent_shadow_resolved)
        self.assertEqual(diagnostics, controller._show_intent_shadow_diagnostics)
        self.assertEqual(diagnostics, state["show_intent_shadow"])

    def test_continuity_and_stale_warning_follow_only_candidate_presence(self):
        controller, _, _ = self.controller()
        valid_a = ShowInterpreterEffectiveContext(True, "build", 0.04)
        valid_b = ShowInterpreterEffectiveContext(True, "break", -0.04)

        observed = []
        for context in (valid_a, None, None, valid_b):
            controller._update_show_intent_shadow(context)
            shadow = controller._show_intent_shadow_diagnostics
            observed.append((
                shadow["resolved_section_bucket"], shadow["resolved_energy_modifier"],
                shadow["retained_previous"], shadow["stale_warning"],
            ))

        self.assertEqual([
            ("build", 0.04, False, False),
            ("build", 0.04, True, True),
            ("build", 0.04, True, True),
            ("break", -0.04, False, False),
        ], observed)

    def test_initial_none_and_valid_unknown_zero_have_distinct_contracts(self):
        controller, _, _ = self.controller()
        controller._update_show_intent_shadow(None)

        initial = dict(controller._show_intent_shadow_diagnostics)
        self.assertEqual((False, False, "unknown", 0.0, False, False), (
            initial["input_present"], initial["candidate_present"],
            initial["resolved_section_bucket"], initial["resolved_energy_modifier"],
            initial["retained_previous"], initial["stale_warning"],
        ))

        controller = self.controller()[0]
        controller._update_show_intent_shadow(
            ShowInterpreterEffectiveContext(True, "unknown", 0.0)
        )
        unknown = controller._show_intent_shadow_diagnostics
        self.assertEqual((True, True, "unknown", 0.0, False), (
            unknown["input_present"], unknown["candidate_present"],
            unknown["resolved_section_bucket"], unknown["resolved_energy_modifier"],
            unknown["stale_warning"],
        ))

    def test_send_loop_processes_exactly_one_shadow_update_per_frame(self):
        controller, transport, config = self.controller()
        auto_show = controller._auto_show_state(transport.snapshot_for_render(), config["auto_show"])
        context = ShowInterpreterEffectiveContext(True, "build", 0.04)
        updates = []
        original_update = controller._update_show_intent_shadow

        controller._auto_show_evaluation = lambda *_: (auto_show, context)
        controller._update_show_intent_shadow = lambda value, osc: (
            updates.append((value, osc)), original_update(value, osc)
        )[1]
        controller._render_values = lambda *args, **kwargs: setattr(controller, "running", False) or {}
        controller._build_slot_previews = lambda *args, **kwargs: {}
        controller.running = True
        controller.dmx = object()

        controller._send_loop()

        self.assertEqual([(context, transport.snapshot_for_render())], updates)
        self.assertEqual("build", controller._show_intent_shadow_diagnostics["resolved_section_bucket"])

    def test_shadow_processing_does_not_change_production_auto_show_or_render_values(self):
        plain, plain_transport, config = self.controller(behavior("build", 1.0))
        shadow, shadow_transport, _ = self.controller(behavior("build", 1.0))

        plain_auto_show = plain._auto_show_state(plain_transport.snapshot_for_render(), config["auto_show"])
        shadow_auto_show, context = shadow._auto_show_evaluation(
            shadow_transport.snapshot_for_render(), config["auto_show"]
        )
        shadow._update_show_intent_shadow(context)

        self.assertEqual(plain_auto_show, shadow_auto_show)
        self.assertEqual(
            plain._render_values(1.0, advance_motion=False, config=config, osc=plain_transport.snapshot_for_render(), auto_show=plain_auto_show),
            shadow._render_values(1.0, advance_motion=False, config=config, osc=shadow_transport.snapshot_for_render(), auto_show=shadow_auto_show),
        )

    def test_backend_shadow_payload_is_json_safe_and_has_no_event_or_reset_contract(self):
        controller, transport, config = self.controller()
        _, context = controller._auto_show_evaluation(transport.snapshot_for_render(), config["auto_show"])
        controller._update_show_intent_shadow(context)
        payload = controller.state()["show_intent_shadow"]

        self.assertEqual({
            "source_valid", "input_present", "candidate_present", "input_section_bucket",
            "input_energy_modifier", "resolved_section_bucket", "resolved_energy_modifier",
            "retained_previous", "stale_warning", "lifecycle_reset", "lifecycle_reason",
        }, set(payload))
        json.dumps(payload)
        source = (Path(__file__).parents[1] / "beatbeam_app.py").read_text(encoding="utf-8")
        update_source = source[source.index("def _update_show_intent_shadow"):source.index("def _resolved_behavior_section")]
        self.assertNotIn("current_event", update_source)
        self.assertNotIn("next_event", update_source)
        self.assertNotIn("_playback_generation", update_source)


if __name__ == "__main__":
    unittest.main()
