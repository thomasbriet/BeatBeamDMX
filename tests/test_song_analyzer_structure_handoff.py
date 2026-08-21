import json
import tempfile
import unittest
from pathlib import Path

from beatbeam_app import SongAnalyzerStructureHandoff


FIXTURE = Path(__file__).parent / "fixtures" / "beatbeam-structure-handoff-v1.json"
TRACK = "/Music/Example/O'Brien Café.flac"


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

    def test_v2_rich_segment_and_ready_active_track_project_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            payload["schema_version"] = 2
            payload["active_track"] = {
                "canonical_path": TRACK, "deck": 1, "status": "ready", "generation": 9,
            }
            payload["tracks"][0]["rich_analysis"] = {
                "model": "SongAnalyzerRichAnalysis",
                "energy_scale": "segment-normalized-rms-z-score",
                "segments": [
                    {"index": 0, "start_seconds": 0, "end_seconds": 16, "label": "Intro 1", "level": "phrase", "energy": -1.0},
                    {"index": 1, "start_seconds": 16, "end_seconds": 32, "label": "Up 1", "level": "phrase", "energy": 2.0},
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            state = SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project(playback(TRACK, 18))

            self.assertEqual(2, state["schema_version"])
            self.assertEqual(9, state["active_track"]["generation"])
            self.assertEqual(2.0, state["rich_current"]["energy"])

    def test_v2_events_project_current_next_and_safe_empty_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            payload["schema_version"] = 2
            payload["tracks"][0]["rich_analysis"] = {
                "model": "SongAnalyzerRichAnalysis",
                "energy_scale": "segment-normalized-rms-z-score",
                "segments": [
                    {"index": 0, "start_seconds": 0, "end_seconds": 16, "label": "Build", "level": "phrase", "energy": 0.2, "start_bar": 1, "end_bar": 5},
                    {"index": 1, "start_seconds": 16, "end_seconds": 32, "label": "Drop", "level": "phrase", "energy": 1.1, "start_bar": 5, "end_bar": 9},
                ],
                "events": [
                    {"type": "BUILD", "start_seconds": 0, "target_seconds": 16, "end_seconds": 16,
                     "start_bar": 1, "target_bar": 5, "confidence": 88},
                    {"type": "DROP", "start_seconds": 16, "start_bar": 5, "confidence": 91},
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            handoff = SongAnalyzerStructureHandoff(path, check_interval_seconds=0)
            before = handoff.project(playback(TRACK, 8))
            self.assertEqual("BUILD", before["current_event"]["type"])
            self.assertEqual("DROP", before["next_event"]["type"])
            self.assertEqual(2, before["next_event"]["bars_to_next"])
            self.assertEqual("DROP", handoff.project(playback(TRACK, 16))["current_event"]["type"])
            self.assertEqual(2, before["rich_analysis"]["segment_count"])
            self.assertEqual(2, len(before["rich_analysis"]["segments"]))
            self.assertEqual("BUILD", before["rich_analysis"]["events"][0]["type"])
            self.assertEqual("DROP", before["rich_analysis"]["events"][1]["type"])

    def test_ready_active_track_is_used_when_virtualdj_live_state_has_no_track_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            payload["schema_version"] = 2
            payload["active_track"] = {
                "canonical_path": TRACK, "deck": 1, "status": "ready", "generation": 11,
            }
            path.write_text(json.dumps(payload), encoding="utf-8")

            state = SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project({
                "_active_playback_source": "virtualdj",
                "time_seconds": 2,
            })

            self.assertEqual(TRACK, state["canonical_track_path"])
            self.assertEqual("exact", state["track_match"])
            self.assertEqual("available_current", state["availability"])
            self.assertEqual(11, state["active_track"]["generation"])
            self.assertEqual("Intro 1", state["current"]["label"])

    def test_pending_or_other_active_track_cannot_project_previous_track_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            payload["schema_version"] = 2
            payload["active_track"] = {
                "canonical_path": TRACK, "deck": 1, "status": "pending", "generation": 10,
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            handoff = SongAnalyzerStructureHandoff(path, check_interval_seconds=0)
            pending = handoff.project(playback(TRACK, 2))
            self.assertEqual("active_not_ready", pending["track_match"])
            self.assertIsNone(pending["current"])

            payload["active_track"]["canonical_path"] = "/Music/Other.flac"
            payload["active_track"]["status"] = "ready"
            path.write_text(json.dumps(payload), encoding="utf-8")
            other = handoff.project(playback(TRACK, 2))
            self.assertEqual("not_active", other["track_match"])
            self.assertIsNone(other["current"])


if __name__ == "__main__":
    unittest.main()
