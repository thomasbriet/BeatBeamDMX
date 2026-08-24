import dataclasses
import math
import unittest
from pathlib import Path

from show_interpreter_input import ShowInterpreterInput


class ShowInterpreterInputTests(unittest.TestCase):
    def test_geldig_model_behoudt_bucket_en_modifier(self):
        value = ShowInterpreterInput("build", 0.04)

        self.assertEqual("build", value.section_bucket)
        self.assertEqual(0.04, value.energy_modifier)

    def test_model_is_immutable(self):
        value = ShowInterpreterInput("chorus", 0.0)

        with self.assertRaises(dataclasses.FrozenInstanceError):
            value.section_bucket = "break"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            value.energy_modifier = 0.08

    def test_iedere_geldige_bucket_blijft_exact_behouden(self):
        for bucket in ("intro", "verse", "build", "chorus", "drop", "down", "break", "outro", "unknown"):
            with self.subTest(bucket=bucket):
                self.assertEqual(bucket, ShowInterpreterInput(bucket, 0.0).section_bucket)

    def test_ongeldige_bucket_valt_fail_closed_terug_op_unknown(self):
        for value in ("onbekend", None, 7, object()):
            with self.subTest(value=value):
                self.assertEqual("unknown", ShowInterpreterInput(value, 0.0).section_bucket)

    def test_modifier_binnen_bestaande_grenzen_blijft_behouden(self):
        self.assertEqual(-0.08, ShowInterpreterInput("intro", -0.08).energy_modifier)
        self.assertEqual(0.08, ShowInterpreterInput("outro", 0.08).energy_modifier)
        self.assertEqual(0.0, ShowInterpreterInput("unknown", 0.0).energy_modifier)

    def test_modifier_buiten_bestaande_grenzen_wordt_geclamped(self):
        self.assertEqual(-0.08, ShowInterpreterInput("build", -1.0).energy_modifier)
        self.assertEqual(0.08, ShowInterpreterInput("build", 1.0).energy_modifier)

    def test_ongeldige_modifier_valt_veilig_terug_op_neutraal(self):
        for value in (float("nan"), float("inf"), float("-inf"), True, None, "0.04", object()):
            with self.subTest(value=value):
                self.assertEqual(0.0, ShowInterpreterInput("verse", value).energy_modifier)

    def test_meerdere_synthetische_inputs_zijn_zelfstandig_en_staatloos(self):
        values = [
            ShowInterpreterInput("intro", -0.04),
            ShowInterpreterInput("build", 0.04),
            ShowInterpreterInput("invalid", 9.0),
        ]

        self.assertEqual(
            [("intro", -0.04), ("build", 0.04), ("unknown", 0.08)],
            [(value.section_bucket, value.energy_modifier) for value in values],
        )

    def test_module_blijft_puur_en_zonder_candidate_of_runtimeafhankelijkheid(self):
        source = (Path(__file__).parents[1] / "show_interpreter_input.py").read_text(encoding="utf-8").lower()
        forbidden = (
            "import beatbeam_app", "songanalyzer", "virtualdj", "osc", "dmx", "fixture",
            "native", "current_event", "next_event", "upward", "transport", "playback",
            "resolve_show_intent", "candidate", "track", "continuity",
        )
        self.assertTrue(all(token not in source for token in forbidden))
        self.assertNotIn("class showinterpreter:", source)
        self.assertFalse(math.isnan(ShowInterpreterInput("unknown", 0.0).energy_modifier))


if __name__ == "__main__":
    unittest.main()
