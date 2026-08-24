import dataclasses
import unittest
from pathlib import Path

from show_intent import ShowIntent, resolve_show_intent
from show_intent_candidate_mapper import map_show_intent_candidate
from show_interpreter_input import ShowInterpreterInput


class ShowIntentCandidateMapperTests(unittest.TestCase):
    def test_none_levert_geen_candidate(self):
        self.assertIsNone(map_show_intent_candidate(None))

    def test_canonical_input_levert_overeenkomstige_show_intent(self):
        source = ShowInterpreterInput("build", 0.04)

        candidate = map_show_intent_candidate(source)

        self.assertIsInstance(candidate, ShowIntent)
        self.assertEqual("build", candidate.section_bucket)
        self.assertEqual(0.04, candidate.energy_modifier)

    def test_iedere_canonical_bucket_wordt_exact_doorgelaten(self):
        for bucket in ("intro", "verse", "build", "chorus", "drop", "down", "break", "outro", "unknown"):
            with self.subTest(bucket=bucket):
                candidate = map_show_intent_candidate(ShowInterpreterInput(bucket, 0.0))
                self.assertEqual(bucket, candidate.section_bucket)

    def test_unknown_en_neutrale_waarden_worden_niet_onderdrukt(self):
        candidate = map_show_intent_candidate(ShowInterpreterInput("unknown", 0.0))

        self.assertIsInstance(candidate, ShowIntent)
        self.assertEqual(("unknown", 0.0), (candidate.section_bucket, candidate.energy_modifier))

    def test_grenswaarden_van_modifier_worden_exact_doorgelaten(self):
        self.assertEqual(-0.08, map_show_intent_candidate(ShowInterpreterInput("intro", -0.08)).energy_modifier)
        self.assertEqual(0.08, map_show_intent_candidate(ShowInterpreterInput("drop", 0.08)).energy_modifier)

    def test_output_is_immutable(self):
        candidate = map_show_intent_candidate(ShowInterpreterInput("chorus", 0.0))

        with self.assertRaises(dataclasses.FrozenInstanceError):
            candidate.section_bucket = "break"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            candidate.energy_modifier = 0.08

    def test_mapper_is_staatloos_bij_herhaalde_en_verschillende_calls(self):
        first = map_show_intent_candidate(ShowInterpreterInput("build", 0.04))
        repeated = map_show_intent_candidate(ShowInterpreterInput("build", 0.04))
        other = map_show_intent_candidate(ShowInterpreterInput("break", -0.04))

        self.assertEqual(first, repeated)
        self.assertIsNot(first, repeated)
        self.assertEqual(("build", 0.04), (first.section_bucket, first.energy_modifier))
        self.assertEqual(("break", -0.04), (other.section_bucket, other.energy_modifier))

    def test_mapper_en_continuity_resolver_hebben_gescheiden_verantwoordelijkheid(self):
        source_a = ShowInterpreterInput("build", 0.04)
        source_b = ShowInterpreterInput("break", -0.04)
        mapped = [map_show_intent_candidate(source) for source in (source_a, None, None, source_b, None)]

        state = None
        resolved = []
        for candidate in mapped:
            state = resolve_show_intent(state, candidate)
            resolved.append(state)

        self.assertEqual([
            ShowIntent("build", 0.04), ShowIntent("build", 0.04), ShowIntent("build", 0.04),
            ShowIntent("break", -0.04), ShowIntent("break", -0.04),
        ], resolved)
        self.assertIsNone(mapped[1])
        self.assertIsNone(mapped[2])
        self.assertIsNone(mapped[4])

    def test_module_blijft_puur_zonder_runtime_of_contentgating(self):
        source = (Path(__file__).parents[1] / "show_intent_candidate_mapper.py").read_text(encoding="utf-8").lower()
        forbidden = (
            "import beatbeam_app", "songanalyzer", "virtualdj", "osc", "dmx", "fixture",
            "native", "current_event", "next_event", "upward", "transport", "track",
            "previous", "resolve_show_intent", "== \"unknown\"", "== 0.0",
        )
        self.assertTrue(all(token not in source for token in forbidden))
        self.assertNotIn("class showinterpreter", source)


if __name__ == "__main__":
    unittest.main()
