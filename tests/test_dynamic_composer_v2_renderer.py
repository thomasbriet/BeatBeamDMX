import threading
import unittest

from beatbeam_app import (
    AUTO_SHOW_MANUAL_PRESET_PALETTES,
    DmxController,
    MANUAL_COLOR_PRESETS,
)
from dynamic_composer import DIMMER_ANIMATION_MOTIFS


class NullOsc:
    def __init__(self):
        self.lock = threading.Lock()
        self.decks = {}

    def snapshot_for_render(self):
        return {}

    def developer_playback_state(self):
        return {}

    def structure_behavior_source(self):
        return "legacy"


class DynamicComposerV2RendererTests(unittest.TestCase):
    def setUp(self):
        self.controller = DmxController(NullOsc(), None)
        self.context = {
            "member_count": 4, "member_index": 1, "member_normalized": 1 / 3,
            "member_centered": -1 / 3, "group_count": 4, "group_index": 1,
        }

    def _brightness(self, motif, beat_value=8.125, context=None):
        config = {
            "_dynamic_dimmer_motif": motif,
            "_slot_context": context or self.context,
        }
        return self.controller._dynamic_dimmer_brightness(
            config, {"beat_value": beat_value}, 220, 1.0,
        )

    def test_every_dimmer_motif_is_deterministic_and_bounded(self):
        for descriptor in DIMMER_ANIMATION_MOTIFS:
            first = self._brightness(descriptor.name)
            second = self._brightness(descriptor.name)
            self.assertEqual(first, second, descriptor.name)
            self.assertGreaterEqual(first, 0, descriptor.name)
            self.assertLessEqual(first, 255, descriptor.name)

    def test_topology_required_motifs_fall_back_safely_for_single_member(self):
        singleton = {"member_count": 1, "member_index": 0, "member_normalized": .5,
                     "member_centered": 0.0, "group_count": 1, "group_index": 0}
        for descriptor in DIMMER_ANIMATION_MOTIFS:
            if descriptor.topology_required:
                value = self._brightness(descriptor.name, context=singleton)
                self.assertGreaterEqual(value, round(220 * .38), descriptor.name)
                self.assertLessEqual(value, 220, descriptor.name)

    def test_bar_quantized_motifs_only_change_on_their_declared_boundary(self):
        self.assertEqual(self._brightness("bar_gate", 8.10), self._brightness("bar_gate", 8.90))
        self.assertEqual(self._brightness("half_bar_gate", 8.10), self._brightness("half_bar_gate", 9.90))
        self.assertNotEqual(self._brightness("half_bar_gate", 8.10), self._brightness("half_bar_gate", 10.10))

    def _dynamic_par_color(self, animation, beat_value, context=None):
        auto_show = {
            "dynamic_composition_applied": True,
            "beat_value": beat_value,
            "selected_primitives": {
                "par": {
                    "palette": "amber_teal",
                    "palette_parameters": {
                        "relationship": "complementary",
                        "balance": .5,
                        "phase_offset": 0,
                    },
                    "color_animation": animation,
                    "fixture_partition": "call_response",
                },
            },
            "fixture_group_intents": {"par": {"color_change_rate": 1.0}},
        }
        return self.controller._dynamic_preview_palette_rgbw(
            {"role": "par", **(context or self.context)}, auto_show
        )

    def test_par_color_animations_have_deterministic_distinct_renderer_output(self):
        other = {**self.context, "member_index": 2, "group_index": 0}
        chase_other = {**self.context, "member_index": 0, "group_index": 1}
        all_same = {
            self._dynamic_par_color("all_same", beat, context)
            for beat in (8.0, 9.0) for context in (self.context, other)
        }
        group_split = {
            self._dynamic_par_color("group_split", 8.0, context)
            for context in (self.context, other)
        }
        alternate = [self._dynamic_par_color("alternate", beat) for beat in (8.0, 9.0)]
        chase = [self._dynamic_par_color("chase_color", 8.0, context) for context in (self.context, chase_other)]

        self.assertEqual(1, len(all_same))
        self.assertGreater(len(group_split), 1)
        self.assertNotEqual(*alternate)
        self.assertNotEqual(*chase)
        # call_response is a bounded group-participation primitive. Its color
        # remains the selected PAR palette; the dimmer envelope stays separate.
        self.assertIsNotNone(self._dynamic_par_color("group_split", 8.0))
        self.assertNotEqual(
            self._brightness("static_full", 8.0),
            self._brightness("chase_forward", 8.0),
        )
        approved = set(MANUAL_COLOR_PRESETS.values())
        for animation in ("all_same", "group_split", "alternate", "chase_color",
                          "swap_on_bar", "swap_on_2_bars", "event_accent",
                          "return_palette_recall"):
            for beat in (8.0, 9.0, 12.0, 16.0):
                self.assertIn(self._dynamic_par_color(animation, beat), approved, animation)

    def test_auto_show_color_output_is_always_an_exact_manual_preset(self):
        approved = set(MANUAL_COLOR_PRESETS.values())
        for palette_name in (*AUTO_SHOW_MANUAL_PRESET_PALETTES, "unsupported"):
            for beat in (1.0, 2.0, 3.0, 4.0):
                color = self.controller._auto_show_rgbw_for_slot(
                    (17, 34, 51, 0), {"role": "par", **self.context},
                    {"color_profile_name": palette_name, "beat_value": beat},
                )
                self.assertIn(color, approved, palette_name)


if __name__ == "__main__":
    unittest.main()
