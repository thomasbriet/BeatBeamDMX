import threading
import unittest

from beatbeam_app import DmxController
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


if __name__ == "__main__":
    unittest.main()
