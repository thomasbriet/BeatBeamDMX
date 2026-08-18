import json
import tempfile
import unittest
from pathlib import Path

from beatbeam_app import SongAnalyzerStructureHandoff


FIXTURE = Path(__file__).parent / "fixtures" / "beatbeam-structure-handoff-v1.json"


def playback(path, seconds, source="virtualdj"):
    return {
        "_active_playback_source": source,
        "track_path": path,
        "time_seconds": seconds,
    }


class SongAnalyzerStructureHandoffTests(unittest.TestCase):
    def write_fixture(self, destination):
        destination.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    def test_golden_contract_projects_exact_path_unicode_apostrophe_and_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            self.write_fixture(path)
            handoff = SongAnalyzerStructureHandoff(path, check_interval_seconds=0)

            at_boundary = handoff.project(playback("/Music/Example/O'Brien Café.flac", 16.0))

            self.assertEqual("exact", at_boundary["track_match"])
            self.assertEqual("available_current", at_boundary["availability"])
            self.assertEqual("in_segment", at_boundary["projection_status"])
            self.assertEqual("Up 1", at_boundary["current"]["label"])
            self.assertEqual(1, at_boundary["current"]["index"])
            self.assertEqual("Intro 1", at_boundary["previous"]["label"])

    def test_before_after_seek_and_hot_cue_are_direct_safe_projections(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            self.write_fixture(path)
            handoff = SongAnalyzerStructureHandoff(path, check_interval_seconds=0)
            track = "/Music/Example/O'Brien Café.flac"

            self.assertEqual("before_structure", handoff.project(playback(track, -0.1))["projection_status"])
            early = handoff.project(playback(track, 2.0))
            self.assertEqual(14.0, early["next"]["starts_in_seconds"])
            self.assertEqual("Up 1", handoff.project(playback(track, 24.0))["current"]["label"])
            self.assertEqual("Intro 1", early["current"]["label"])
            final = handoff.project(playback(track, 32.0))
            self.assertEqual("in_final_segment", final["projection_status"])
            self.assertEqual("Up 1", final["current"]["label"])
            self.assertEqual("after_structure", handoff.project(playback(track, 32.01))["projection_status"])

    def test_known_unknown_known_and_deck_switches_cannot_leak_previous_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            second = dict(payload["tracks"][0])
            second["canonical_path"] = "/Music/Second.flac"
            second["structure"] = dict(second["structure"])
            second["structure"]["segments"] = [
                {"index": 0, "start_seconds": 0, "end_seconds": 10, "label": "Chorus 1"}
            ]
            payload["tracks"].append(second)
            path.write_text(json.dumps(payload), encoding="utf-8")
            handoff = SongAnalyzerStructureHandoff(path, check_interval_seconds=0)

            self.assertEqual("Intro 1", handoff.project(playback("/Music/Example/O'Brien Café.flac", 2))["current"]["label"])
            unknown = handoff.project(playback("/Music/Unknown.flac", 2))
            self.assertEqual("none", unknown["track_match"])
            self.assertIsNone(unknown["current"])
            self.assertEqual("Chorus 1", handoff.project(playback("/Music/Second.flac", 2))["current"]["label"])
            self.assertEqual("Intro 1", handoff.project(playback("/Music/Example/O'Brien Café.flac", 2))["current"]["label"])

    def test_stale_malformed_and_unsupported_contracts_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            payload["tracks"][0]["availability"] = "stale"
            path.write_text(json.dumps(payload), encoding="utf-8")
            handoff = SongAnalyzerStructureHandoff(path, check_interval_seconds=0)
            track = "/Music/Example/O'Brien Café.flac"
            self.assertEqual("available_stale", handoff.project(playback(track, 2))["availability"])

            path.write_text("{not-json", encoding="utf-8")
            invalid = handoff.project(playback(track, 2))
            self.assertEqual("invalid", invalid["load_status"])
            self.assertIsNone(invalid["current"])

            path.write_text(json.dumps({"schema_version": 999, "tracks": []}), encoding="utf-8")
            unsupported = handoff.project(playback(track, 2))
            self.assertEqual("unsupported_schema", unsupported["load_status"])
            self.assertEqual("none", unsupported["track_match"])

    def test_inactive_source_never_claims_song_analyzer_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            self.write_fixture(path)
            state = SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project(
                playback("/Music/Example/O'Brien Café.flac", 2, source="legacy")
            )
            self.assertEqual("inactive", state["availability"])
            self.assertIsNone(state["current"])

    def test_missing_structure_never_projects_an_old_segment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            payload["tracks"][0]["availability"] = "missing"
            path.write_text(json.dumps(payload), encoding="utf-8")
            state = SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project(
                playback("/Music/Example/O'Brien Café.flac", 2)
            )
            self.assertEqual("exact", state["track_match"])
            self.assertEqual("unavailable", state["availability"])
            self.assertIsNone(state["current"])


if __name__ == "__main__":
    unittest.main()
