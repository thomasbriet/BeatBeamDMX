import copy
import json
import tempfile
import unittest
from pathlib import Path

from beatbeam_app import SongAnalyzerStructureHandoff


TRACK = "/Music/M23A Runtime.flac"
ANALYSIS_HASH = "a" * 64


def playback(position=4):
    return {"_active_playback_source": "virtualdj", "track_path": TRACK, "time_seconds": position}


def rich_event_payload():
    return {
        "schema_version": 1,
        "contract": "rich-musical-events",
        "mode": "shadow_only",
        "track_key": ANALYSIS_HASH,
        "availability": "available",
        "events": [{
            "type": "SECTION_START",
            "temporal_kind": "POINT",
            "start_seconds": 0,
            "start_bar": 1,
            "origin_observation_id": "raw-section-0000-0004",
            "structural_context": {},
            "character_context": {},
            "provenance": {
                "source_category": "software_independent_structure_character",
                "derivation": "direct",
                "reasons": ["RawSectionStart"],
                "required_inputs": ["bar_grid", "section_timing"],
            },
        }],
    }


def structure_payload(include_rich_events=False):
    track = {
        "canonical_path": TRACK,
        "content_sha256": "b" * 64,
        "analysis_hash": ANALYSIS_HASH,
        "analysis_version": "m14-v5",
        "phrase_analysis_version": "phrase-analysis-v17",
        "availability": "current",
        "structure": {"model": "PhraseAnalysisResult", "segments": [{
            "index": 0, "start_seconds": 0, "end_seconds": 8,
            "label": "Intro 1", "confidence": 90, "start_bar": 1, "end_bar": 5,
        }]},
    }
    if include_rich_events:
        track["rich_musical_events"] = rich_event_payload()
    return {"schema_version": 2, "generated_at_unix_milliseconds": 0, "tracks": [track]}


class RichMusicalEventsRuntimeHandoffTests(unittest.TestCase):
    def project(self, payload, include_rich_events):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project(
                playback(), include_rich_events=include_rich_events)

    def test_compact_events_are_parsed_and_observed_only_in_shadow_projection(self):
        production = self.project(structure_payload(include_rich_events=True), include_rich_events=False)
        debug = self.project(structure_payload(include_rich_events=True), include_rich_events=True)

        self.assertIsNone(production["rich_musical_events"])
        self.assertEqual("SHADOW_ONLY", debug["rich_musical_events"]["mode"])
        self.assertEqual(1, debug["rich_musical_events"]["event_count"])
        self.assertEqual(("SECTION_START",), tuple(debug["rich_musical_events"]["event_types"]))
        self.assertEqual("SHADOW_ONLY", debug["rich_musical_events"]["observation"]["mode"])

    def test_rich_event_presence_cannot_change_production_projection(self):
        baseline = self.project(structure_payload(include_rich_events=False), include_rich_events=False)
        enriched = self.project(structure_payload(include_rich_events=True), include_rich_events=False)

        baseline.pop("contract_path")
        enriched.pop("contract_path")
        self.assertEqual(baseline, enriched)

    def test_malformed_or_identity_mismatched_events_fail_closed(self):
        malformed = structure_payload(include_rich_events=True)
        malformed["tracks"][0]["rich_musical_events"]["mode"] = "production"
        self.assertEqual("invalid", self.project(malformed, include_rich_events=True)["load_status"])

        mismatched = structure_payload(include_rich_events=True)
        mismatched["tracks"][0]["rich_musical_events"]["track_key"] = "c" * 64
        self.assertEqual("invalid", self.project(mismatched, include_rich_events=True)["load_status"])

    def test_missing_events_remain_valid_and_explicitly_absent(self):
        state = self.project(copy.deepcopy(structure_payload()), include_rich_events=True)
        self.assertEqual("ready", state["load_status"])
        self.assertIsNone(state["rich_musical_events"])


if __name__ == "__main__":
    unittest.main()
