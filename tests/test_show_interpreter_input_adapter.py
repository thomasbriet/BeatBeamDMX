import dataclasses
import unittest
from pathlib import Path

from show_intent import ShowIntent, resolve_show_intent
from show_intent_candidate_mapper import map_show_intent_candidate
from show_interpreter_input import ShowInterpreterInput
from show_interpreter_input_adapter import (
    ShowInterpreterEffectiveContext,
    project_show_interpreter_input,
)


class ShowInterpreterInputAdapterTests(unittest.TestCase):
    def test_context_is_immutable_and_has_exact_contract_fields(self):
        context = ShowInterpreterEffectiveContext(True, "build", 0.04)

        self.assertEqual(
            ("source_is_valid", "section_bucket", "energy_modifier"),
            tuple(field.name for field in dataclasses.fields(context)),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            context.section_bucket = "drop"

    def test_absent_or_not_exactly_true_source_fails_closed(self):
        self.assertIsNone(project_show_interpreter_input(None))
        for validity in (False, None, 0, 1, "true"):
            with self.subTest(validity=validity):
                context = ShowInterpreterEffectiveContext(validity, "build", 0.04)
                self.assertIsNone(project_show_interpreter_input(context))

    def test_valid_source_projects_existing_input_values(self):
        projected = project_show_interpreter_input(
            ShowInterpreterEffectiveContext(True, "build", 0.04)
        )

        self.assertIsInstance(projected, ShowInterpreterInput)
        self.assertEqual(("build", 0.04), (projected.section_bucket, projected.energy_modifier))

    def test_every_canonical_bucket_and_modifier_bounds_pass_through(self):
        for bucket in ("intro", "verse", "build", "chorus", "drop", "down", "break", "outro", "unknown"):
            with self.subTest(bucket=bucket):
                projected = project_show_interpreter_input(
                    ShowInterpreterEffectiveContext(True, bucket, 0.0)
                )
                self.assertEqual(bucket, projected.section_bucket)
        self.assertEqual(-0.08, project_show_interpreter_input(
            ShowInterpreterEffectiveContext(True, "intro", -0.08)
        ).energy_modifier)
        self.assertEqual(0.08, project_show_interpreter_input(
            ShowInterpreterEffectiveContext(True, "outro", 0.08)
        ).energy_modifier)

    def test_valid_unknown_and_zero_are_inputs_not_absence(self):
        projected = project_show_interpreter_input(
            ShowInterpreterEffectiveContext(True, "unknown", 0.0)
        )

        self.assertIsInstance(projected, ShowInterpreterInput)
        self.assertEqual(("unknown", 0.0), (projected.section_bucket, projected.energy_modifier))

    def test_existing_input_normalization_remains_the_single_normalization_owner(self):
        projected = project_show_interpreter_input(
            ShowInterpreterEffectiveContext(True, "not-a-bucket", 9.0)
        )

        self.assertEqual(("unknown", 0.08), (projected.section_bucket, projected.energy_modifier))

    def test_adapter_mapper_and_resolver_keep_separate_responsibilities(self):
        contexts = (
            ShowInterpreterEffectiveContext(True, "build", 0.04),
            None,
            ShowInterpreterEffectiveContext(False, "drop", 0.08),
            ShowInterpreterEffectiveContext(True, "break", -0.04),
        )
        inputs = [project_show_interpreter_input(context) for context in contexts]
        candidates = [map_show_intent_candidate(value) for value in inputs]

        state = None
        resolved = []
        for candidate in candidates:
            state = resolve_show_intent(state, candidate)
            resolved.append(state)

        self.assertEqual([ShowIntent("build", 0.04), None, None, ShowIntent("break", -0.04)], candidates)
        self.assertEqual([
            ShowIntent("build", 0.04), ShowIntent("build", 0.04),
            ShowIntent("build", 0.04), ShowIntent("break", -0.04),
        ], resolved)

    def test_module_is_pure_stateless_and_has_no_runtime_or_duplicate_logic(self):
        source = (Path(__file__).parents[1] / "show_interpreter_input_adapter.py").read_text(encoding="utf-8").lower()
        forbidden = (
            "import beatbeam_app", "songanalyzer", "virtualdj", "osc", "dmx", "fixture",
            "native", "current_event", "next_event", "legacy phrase", "manual override",
            "upward", "previous", "resolve_show_intent", "map_show_intent_candidate",
            "transport", "track", "reset", "* 0.04", "clamp(", "normalize_section_bucket",
            "normalize_energy_modifier",
        )
        self.assertTrue(all(token not in source for token in forbidden))
        self.assertIn("source.source_is_valid is not true", source)


if __name__ == "__main__":
    unittest.main()
