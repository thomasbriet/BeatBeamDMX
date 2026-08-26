import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BetaBackendPackagingTests(unittest.TestCase):
    def test_buildscript_bundelt_de_pure_show_intent_modules_explicit(self):
        script = (ROOT / "build_native_app.sh").read_text(encoding="utf-8")

        self.assertIn("BACKEND_PYTHON_SOURCES=(", script)
        self.assertIn('for backend_source in "${BACKEND_PYTHON_SOURCES[@]}"; do', script)
        self.assertIn('cp "${backend_source}" "${BACKEND_RESOURCES}/"', script)
        for filename in (
            "show_intent.py",
            "show_interpreter_input.py",
            "show_intent_candidate_mapper.py",
            "show_interpreter_input_adapter.py",
            "rich_musical_events.py",
            "rme_preview.py",
            "dynamic_composer.py",
            "musical_event_envelope.py",
        ):
            with self.subTest(filename=filename):
                self.assertIn(filename, script)


if __name__ == "__main__":
    unittest.main()
