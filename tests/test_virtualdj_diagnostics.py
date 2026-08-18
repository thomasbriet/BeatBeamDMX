import importlib.util
import io
import json
import unittest
from pathlib import Path


TOOL_PATH = Path(__file__).parents[1] / "tools" / "beatbeam_virtualdj_diagnostics.py"
SPEC = importlib.util.spec_from_file_location("beatbeam_virtualdj_diagnostics", TOOL_PATH)
DIAGNOSTICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAGNOSTICS)


def response(payload):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *unused):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    return Response()


def opener_for(playbacks, structures, behaviors=None):
    calls = {"count": 0}
    behaviors = behaviors or [behavior()]

    def opener(url, timeout):
        index = calls["count"] // 3
        calls["count"] += 1
        if url.endswith("playback"):
            return response(playbacks[min(index, len(playbacks) - 1)])
        if url.endswith("structure-behavior"):
            return response(behaviors[min(index, len(behaviors) - 1)])
        return response(structures[min(index, len(structures) - 1)])

    return opener


def structure(label="Build", availability="current", index=3, previous=True, following=True):
    return {
        "track_match": "exact",
        "availability": availability,
        "schema_version": 1,
        "analysis_version": "m14-v5",
        "phrase_analysis_version": "phrase-analysis-v6",
        "segment_count": 3,
        "canonical_track_path": "/Music/Calling.flac",
        "current": {"index": index, "label": label, "start_seconds": 62.4, "end_seconds": 91.2, "progress": 0.73, "remaining_seconds": 7.8},
        "previous": {"index": 2, "label": "Build", "start_seconds": 45.12, "end_seconds": 62.4} if previous else None,
        "next": {"index": 4, "label": "Break", "start_seconds": 91.2, "end_seconds": 120.0, "starts_in_seconds": 7.8} if following else None,
        "metrics": {"structure_loads": 1, "cache_hits": 4, "parse_failures": 0, "schema_failures": 0},
    }


def playback(position=83400, discontinuity=None):
    return {
        "availability": "available",
        "virtualdj": {"track_path": "/Music/Calling.flac", "deck_number": 2},
        "beatbeam": {"track_path": "/Music/Calling.flac", "deck_number": 2, "estimated_position_milliseconds": position, "bpm": 125.0, "beat_number": 3, "bar_number": 44},
        "last_discontinuity": discontinuity,
    }


def behavior(selected="song_analyzer", effective="song_analyzer", eligible=True, fallback=None):
    return {
        "selected_source": selected,
        "effective_source": effective,
        "eligible": eligible,
        "fallback_reason": fallback,
        "legacy_phrase": "verse",
        "song_analyzer_label": "Up 3" if eligible else None,
        "mapped_behavior_bucket": "build" if eligible else None,
    }


class VirtualDjDiagnosticsTests(unittest.TestCase):
    def test_known_track_renders_current_previous_and_next(self):
        text = DIAGNOSTICS.render_dashboard(playback(), structure(), behavior())
        self.assertIn("Match: EXACT | Status: CURRENT | Schema: 1", text)
        self.assertIn(">>> CURRENT: BUILD <<<", text)
        self.assertIn("#2 Build", text)
        self.assertIn("#4 Break", text)
        self.assertIn("Selected: SONG_ANALYZER | Effective: SONG_ANALYZER | Eligible: YES", text)
        self.assertIn("Mapped behavior: build", text)

    def test_unknown_and_stale_structure_are_explicit(self):
        unknown = structure(availability="unavailable", previous=False, following=False)
        unknown["track_match"] = "none"
        unknown["current"] = None
        fallback = behavior(effective="legacy", eligible=False, fallback="structure_not_current")
        self.assertIn("Match: NONE | Status: UNAVAILABLE", DIAGNOSTICS.render_dashboard(playback(), unknown, fallback))
        stale_text = DIAGNOSTICS.render_dashboard(playback(), structure(availability="stale"), fallback)
        self.assertIn("Status: STALE", stale_text)
        self.assertIn("Fallback: structure_not_current", stale_text)

    def test_unavailable_playback_snapshot_keeps_diagnostics_available(self):
        unavailable_playback = {
            "availability": "available",
            "virtualdj": None,
            "beatbeam": None,
            "last_discontinuity": "source_unavailable",
        }
        fallback = behavior(effective="legacy", eligible=False, fallback="track_unavailable")
        text = DIAGNOSTICS.render_dashboard(unavailable_playback, structure(availability="unavailable"), fallback, DIAGNOSTICS.TransitionObserver())
        self.assertIn("Fallback: track_unavailable", text)
        self.assertIn("Track: -", text)

    def test_natural_and_seek_transitions_are_distinguished(self):
        observer = DIAGNOSTICS.TransitionObserver()
        DIAGNOSTICS.render_dashboard(playback(60000), structure("Build", index=3), behavior(), observer)
        natural = DIAGNOSTICS.render_dashboard(playback(63000), structure("Drop", index=4), behavior(), observer)
        self.assertIn("Build -> Drop", natural)
        observer = DIAGNOSTICS.TransitionObserver()
        DIAGNOSTICS.render_dashboard(playback(60000), structure("Build", index=3), behavior(), observer)
        jumped = DIAGNOSTICS.render_dashboard(playback(30000, {"reason": "seek"}), structure("Chorus", index=5), behavior(), observer)
        self.assertIn("SEEK/JUMP -> Chorus", jumped)

    def test_once_and_no_clear_output_modes(self):
        stream = io.StringIO()
        DIAGNOSTICS.main(["--once"], stream, opener_for([playback()], [structure()]), is_tty=True)
        self.assertNotIn(DIAGNOSTICS.CLEAR_AND_HOME, stream.getvalue())
        self.assertEqual(1, stream.getvalue().count("BeatBeam M19F Structure Diagnostics"))

        stream = io.StringIO()
        DIAGNOSTICS.main(["--no-clear"], stream, opener_for([playback(), playback()], [structure(), structure()]), is_tty=True, sleep_fn=lambda unused: None, maximum_iterations=2)
        self.assertNotIn(DIAGNOSTICS.CLEAR_AND_HOME, stream.getvalue())
        self.assertEqual(2, stream.getvalue().count("BeatBeam M19F Structure Diagnostics"))

    def test_tty_uses_clear_sequence_but_non_tty_does_not(self):
        stream = io.StringIO()
        DIAGNOSTICS.main([], stream, opener_for([playback()], [structure()]), is_tty=True, sleep_fn=lambda unused: None, maximum_iterations=1)
        self.assertTrue(stream.getvalue().startswith(DIAGNOSTICS.CLEAR_AND_HOME))

        stream = io.StringIO()
        DIAGNOSTICS.main([], stream, opener_for([playback()], [structure()]), is_tty=False, sleep_fn=lambda unused: None, maximum_iterations=1)
        self.assertNotIn(DIAGNOSTICS.CLEAR_AND_HOME, stream.getvalue())


if __name__ == "__main__":
    unittest.main()
