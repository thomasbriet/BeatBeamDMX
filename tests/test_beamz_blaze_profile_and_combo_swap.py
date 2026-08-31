import unittest

from enttec_open_dmx import find_fixture, find_mode, load_fixture_profiles, values_for_fixture
from beatbeam_app import DmxController, MANUAL_COLOR_COMBOS, MANUAL_COLOR_PRESETS, mode_capabilities


class BeamzBlazeProfileTests(unittest.TestCase):
    def setUp(self):
        self.fixture = find_fixture(load_fixture_profiles(), "beamz_blaze_series_rgba_fogger")
        self.mode = find_mode(self.fixture, "8ch")

    def test_exact_documented_eight_channel_profile(self):
        self.assertEqual(["160.538", "160.540", "160.542"], self.fixture["model_variants"])
        self.assertEqual(
            [("Fog", "custom", 255), ("Master Dimmer", "intensity", 255),
             ("Red", "color", 100), ("Green", "color", 100),
             ("Blue", "color", 100), ("Amber", "color", 100),
             ("Strobe Mode", "strobe", 100), ("Macro Mode", "custom", 100)],
            [(channel["name"], channel["type"], channel.get("native_max", 255)) for channel in self.mode["channels"]],
        )
        self.assertNotIn("white", {channel.get("component") for channel in self.mode["channels"]})
        self.assertEqual(
            {"dimmer": True, "strobe": True, "fog": True, "macro": True, "amber": True, "white": False},
            {key: mode_capabilities(self.mode)[key] for key in ("dimmer", "strobe", "fog", "macro", "amber", "white")},
        )

    def test_manual_rgb_and_white_use_documented_native_range_with_safe_fog_macro(self):
        values = values_for_fixture(self.mode, 1, MANUAL_COLOR_PRESETS["white"], 255, 0, 0, strobe=255)
        self.assertEqual({1: 0, 2: 255, 3: 100, 4: 100, 5: 100, 6: 0, 7: 100, 8: 0}, values)


class ManualComboBeatSwapTests(unittest.TestCase):
    def setUp(self):
        self.controller = object.__new__(DmxController)
        self.controller.manual_combo_last_valid_beat_parity = 0
        self.context_a = {"color_capable": True, "color_index": 0}
        self.context_b = {"color_capable": True, "color_index": 1}

    def rgbw(self, combo, context, beat, stale=False):
        return self.controller._live_override_combo_rgbw_for_slot(combo, context, {"beat_value": beat, "stale": stale})

    def test_stable_partitions_swap_only_on_authoritative_beat_parity(self):
        self.assertEqual(MANUAL_COLOR_PRESETS["red"], self.rgbw("red_lime", self.context_a, 100))
        self.assertEqual(MANUAL_COLOR_PRESETS["lime"], self.rgbw("red_lime", self.context_b, 100))
        self.assertEqual(MANUAL_COLOR_PRESETS["lime"], self.rgbw("red_lime", self.context_a, 101))
        self.assertEqual(MANUAL_COLOR_PRESETS["red"], self.rgbw("red_lime", self.context_b, 101))
        self.assertEqual(MANUAL_COLOR_PRESETS["red"], self.rgbw("red_lime", self.context_a, 102))

    def test_expanded_combo_vocabulary_uses_only_approved_exact_manual_presets(self):
        self.assertEqual(
            {
                "blue_orange": ("blue", "orange"), "purple_yellow": ("purple", "yellow"),
                "pink_cyan": ("pink", "cyan"), "orange_cyan": ("orange", "cyan"),
                "pink_blue": ("pink", "blue"), "red_lime": ("red", "lime"),
                "cyan_white": ("cyan", "white"), "orange_white": ("orange", "white"),
                "red_blue": ("red", "blue"), "red_yellow": ("red", "yellow"),
                "red_white": ("red", "white"), "green_blue": ("green", "blue"),
                "green_purple": ("green", "purple"), "green_white": ("green", "white"),
                "blue_yellow": ("blue", "yellow"), "purple_white": ("purple", "white"),
            },
            MANUAL_COLOR_COMBOS,
        )

    def test_every_combo_remains_exact_and_stale_transport_freezes_last_phase(self):
        for combo, colors in MANUAL_COLOR_COMBOS.items():
            with self.subTest(combo=combo):
                self.controller.manual_combo_last_valid_beat_parity = 0
                first = self.rgbw(combo, self.context_a, 40)
                same_beat = self.rgbw(combo, self.context_a, 40.9)
                swapped = self.rgbw(combo, self.context_a, 41)
                frozen = self.rgbw(combo, self.context_a, 99, stale=True)
                self.assertEqual(first, same_beat)
                self.assertNotEqual(first, swapped)
                self.assertEqual(swapped, frozen)
                self.assertIn(first, [MANUAL_COLOR_PRESETS[color] for color in colors])
                self.assertIn(swapped, [MANUAL_COLOR_PRESETS[color] for color in colors])
