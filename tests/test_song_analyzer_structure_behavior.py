import json
import tempfile
import threading
import unittest
from pathlib import Path

from beatbeam_app import (
    DmxController,
    SongAnalyzerStructureHandoff,
    StructureBehaviorBridge,
    song_analyzer_behavior_bucket,
)


FIXTURE = Path(__file__).parent / "fixtures" / "beatbeam-structure-handoff-v1.json"
TRACK = "/Music/Example/O'Brien Café.flac"


def playback(seconds=18.0, phrase="verse", source="virtualdj", track=TRACK):
    return {
        "_active_playback_source": source,
        "track_path": track,
        "time_seconds": seconds,
        "bpm": 126.0,
        "beat_value": 12.0,
        "phrase_current": phrase,
        "stale": False,
    }


class StructureBehaviorTransport:
    def __init__(self, selected_source):
        self.selected_source = selected_source
        self.lock = threading.RLock()
        self.decks = {}

    def structure_behavior_source(self):
        return self.selected_source


class SongAnalyzerStructureBehaviorTests(unittest.TestCase):
    def bridge_with_fixture(self, payload=None):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "handoff.json"
        path.write_text(
            json.dumps(payload) if payload is not None else FIXTURE.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self.addCleanup(directory.cleanup)
        return StructureBehaviorBridge(SongAnalyzerStructureHandoff(path, check_interval_seconds=0))

    def test_full_exported_native_label_vocabulary_maps_only_to_existing_buckets(self):
        expected = {
            "Intro 1": "intro", "Intro 2": "intro", "Intro": "intro",
            "Up 1": "build", "Up 2": "build", "Up 3": "build", "Build": "build", "Down": "down",
            "Chorus 1": "chorus", "Chorus 2": "chorus", "Chorus": "chorus",
            "Outro 1": "outro", "Outro 2": "outro", "Outro": "outro",
            "Verse 1": "verse", "Verse 2": "verse", "Verse 3": "verse",
            "Verse 4": "verse", "Verse 5": "verse", "Verse 6": "verse", "Verse": "verse",
            "Bridge": "down", "Drop": "drop", "Break": "break",
        }
        self.assertEqual(expected, {label: song_analyzer_behavior_bucket(label) for label in expected})
        self.assertEqual("build", song_analyzer_behavior_bucket(" Up 1 "))
        self.assertIsNone(song_analyzer_behavior_bucket("up 1"))
        self.assertIsNone(song_analyzer_behavior_bucket("Other"))
        self.assertIsNone(song_analyzer_behavior_bucket("Up 4"))
        self.assertIsNone(song_analyzer_behavior_bucket("Unknown future label"))

    def test_current_exact_known_segment_replaces_the_legacy_behavior_input(self):
        bridge = self.bridge_with_fixture()
        resolved = bridge.resolve("song_analyzer", playback())

        self.assertTrue(resolved["eligible"])
        self.assertEqual("song_analyzer", resolved["effective_source"])
        self.assertEqual("Up 1", resolved["song_analyzer_label"])
        self.assertEqual("build", resolved["mapped_behavior_bucket"])
        self.assertEqual("verse", resolved["legacy_phrase"])

    def test_legacy_selection_does_not_read_or_replace_the_legacy_behavior_input(self):
        bridge = self.bridge_with_fixture()
        resolved = bridge.resolve("legacy", playback())

        self.assertFalse(resolved["eligible"])
        self.assertEqual("legacy", resolved["effective_source"])
        self.assertEqual("legacy_selected", resolved["fallback_reason"])
        self.assertEqual("verse", resolved["legacy_phrase"])
        self.assertIsNone(resolved["projection"])

    def test_legacy_shadow_diagnostics_keep_legacy_control_but_report_the_mapped_label(self):
        bridge = self.bridge_with_fixture()
        resolved = bridge.resolve("legacy", playback(), include_shadow=True)

        self.assertTrue(resolved["eligible"])
        self.assertEqual("legacy", resolved["effective_source"])
        self.assertEqual("legacy_selected", resolved["fallback_reason"])
        self.assertEqual("Up 1", resolved["song_analyzer_label"])
        self.assertEqual("build", resolved["mapped_behavior_bucket"])

    def test_stale_missing_unknown_and_inactive_paths_fail_closed(self):
        stale = json.loads(FIXTURE.read_text(encoding="utf-8"))
        stale["tracks"][0]["availability"] = "stale"
        self.assertEqual(
            "structure_not_current",
            self.bridge_with_fixture(stale).resolve("song_analyzer", playback())["fallback_reason"],
        )

        unknown_label = json.loads(FIXTURE.read_text(encoding="utf-8"))
        unknown_label["tracks"][0]["structure"]["segments"][1]["label"] = "Other"
        self.assertEqual(
            "unknown_song_analyzer_label",
            self.bridge_with_fixture(unknown_label).resolve("song_analyzer", playback())["fallback_reason"],
        )

        self.assertEqual(
            "track_not_exact",
            self.bridge_with_fixture().resolve("song_analyzer", playback(track="/Music/Other.flac"))["fallback_reason"],
        )
        self.assertEqual(
            "virtualdj_inactive",
            self.bridge_with_fixture().resolve("song_analyzer", playback(source="legacy"))["fallback_reason"],
        )

    def test_new_track_handoff_holds_only_the_last_effect_bucket_briefly(self):
        bridge = self.bridge_with_fixture()
        previous = bridge.resolve("song_analyzer", playback(), now=100.0)
        held = bridge.resolve(
            "song_analyzer", playback(track="/Music/Prepared But Not Visible.flac"), now=100.25,
        )
        expired = bridge.resolve(
            "song_analyzer", playback(track="/Music/Prepared But Not Visible.flac"), now=102.01,
        )

        self.assertEqual("song_analyzer", previous["effective_source"])
        self.assertTrue(held["handoff_effect_hold"])
        self.assertEqual("handoff_effect_hold", held["fallback_reason"])
        self.assertEqual("song_analyzer", held["effective_source"])
        self.assertEqual(previous["mapped_behavior_bucket"], held["mapped_behavior_bucket"])
        self.assertEqual(previous["song_analyzer_label"], held["song_analyzer_label"])
        self.assertEqual("/Music/Prepared But Not Visible.flac", held["projection"]["canonical_track_path"])
        self.assertEqual("none", held["projection"]["track_match"])
        self.assertFalse(expired["handoff_effect_hold"])
        self.assertEqual("legacy", expired["effective_source"])
        self.assertEqual("track_not_exact", expired["fallback_reason"])

    def test_same_track_invalid_structure_never_uses_the_handoff_effect_hold(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        bridge = self.bridge_with_fixture(payload)
        bridge.resolve("song_analyzer", playback(), now=100.0)
        payload["tracks"][0]["availability"] = "stale"
        bridge.handoff.path.write_text(json.dumps(payload), encoding="utf-8")

        fallback = bridge.resolve("song_analyzer", playback(), now=100.2)

        self.assertFalse(fallback["handoff_effect_hold"])
        self.assertEqual("legacy", fallback["effective_source"])
        self.assertEqual("structure_not_current", fallback["fallback_reason"])

    def test_unsupported_schema_and_missing_current_segment_fail_closed(self):
        unsupported = json.loads(FIXTURE.read_text(encoding="utf-8"))
        unsupported["schema_version"] = 99
        self.assertEqual(
            "unsupported_schema",
            self.bridge_with_fixture(unsupported).resolve("song_analyzer", playback())["fallback_reason"],
        )
        self.assertEqual(
            "no_current_segment",
            self.bridge_with_fixture().resolve("song_analyzer", playback(seconds=-0.1))["fallback_reason"],
        )

    def test_natural_boundary_and_seek_choose_only_the_projected_current_segment(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["tracks"][0]["structure"]["segments"] = [
            {"index": 0, "start_seconds": 0, "end_seconds": 16, "label": "Intro 1"},
            {"index": 1, "start_seconds": 16, "end_seconds": 32, "label": "Up 1"},
            {"index": 2, "start_seconds": 32, "end_seconds": 48, "label": "Chorus 1"},
        ]
        bridge = self.bridge_with_fixture(payload)

        trace = [
            bridge.resolve("song_analyzer", playback(seconds=31.9))["mapped_behavior_bucket"],
            bridge.resolve("song_analyzer", playback(seconds=32.0))["mapped_behavior_bucket"],
            bridge.resolve("song_analyzer", playback(seconds=32.1))["mapped_behavior_bucket"],
        ]
        self.assertEqual(["build", "chorus", "chorus"], trace)
        self.assertEqual(1, sum(left != right for left, right in zip(trace, trace[1:])))

        seek_trace = [
            bridge.resolve("song_analyzer", playback(seconds=18))["mapped_behavior_bucket"],
            bridge.resolve("song_analyzer", playback(seconds=34))["mapped_behavior_bucket"],
            bridge.resolve("song_analyzer", playback(seconds=2))["mapped_behavior_bucket"],
        ]
        self.assertEqual(["build", "chorus", "intro"], seek_trace)

    def test_controller_uses_structure_bucket_and_bypasses_legacy_track_plan(self):
        bridge = self.bridge_with_fixture()
        controller = DmxController(StructureBehaviorTransport("song_analyzer"), bridge)
        config = controller._clean_full_config(controller.default_config())
        config["auto_show"]["enabled"] = True
        controller._planned_scene_variants = lambda *unused: {"section": "drop"}

        auto_show = controller._auto_show_state(playback(), config["auto_show"])
        behavior_osc = controller._behavior_osc(playback(), auto_show)

        self.assertEqual("song_analyzer", auto_show["structure_behavior"]["effective_source"])
        self.assertEqual("build", auto_show["phrase_bucket"])
        self.assertEqual("build", auto_show["behavior_bucket"])
        self.assertFalse(auto_show["track_plan_active"])
        self.assertEqual("build", behavior_osc["phrase_current"])

    def test_controller_keeps_legacy_path_unchanged_when_song_analyzer_is_ineligible(self):
        bridge = self.bridge_with_fixture()
        controller = DmxController(StructureBehaviorTransport("song_analyzer"), bridge)
        config = controller._clean_full_config(controller.default_config())
        config["auto_show"]["enabled"] = True

        auto_show = controller._auto_show_state(
            playback(track="/Music/Other.flac", phrase="chorus"), config["auto_show"]
        )

        self.assertEqual("legacy", auto_show["structure_behavior"]["effective_source"])
        self.assertEqual("track_not_exact", auto_show["structure_behavior"]["fallback_reason"])
        self.assertEqual("chorus", auto_show["phrase_bucket"])

    def test_ineligible_song_analyzer_control_preserves_legacy_behavior_decisions(self):
        bridge = self.bridge_with_fixture()
        config = DmxController.default_config()
        config["auto_show"]["enabled"] = True
        legacy_controller = DmxController(StructureBehaviorTransport("legacy"), bridge)
        fallback_controller = DmxController(StructureBehaviorTransport("song_analyzer"), bridge)
        state = playback(track="/Music/Unknown.flac", phrase="chorus")

        legacy = legacy_controller._auto_show_state(state, config["auto_show"])
        fallback = fallback_controller._auto_show_state(state, config["auto_show"])

        for key in ("phrase_bucket", "behavior_bucket", "rhythm_mode", "motion_name", "pulse_name", "energy"):
            self.assertEqual(legacy[key], fallback[key], key)

    def test_rich_energy_is_a_deterministic_bounded_auto_show_modifier(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["schema_version"] = 2
        payload["active_track"] = {"canonical_path": TRACK, "deck": 1, "status": "ready", "generation": 4}
        payload["tracks"][0]["rich_analysis"] = {
            "model": "SongAnalyzerRichAnalysis",
            "energy_scale": "segment-normalized-rms-z-score",
            "segments": [
                {"index": 0, "start_seconds": 0, "end_seconds": 16, "label": "Intro 1", "level": "phrase", "energy": 0.0},
                {"index": 1, "start_seconds": 16, "end_seconds": 32, "label": "Up 1", "level": "phrase", "energy": 10.0},
            ],
        }
        bridge = self.bridge_with_fixture(payload)
        controller = DmxController(StructureBehaviorTransport("song_analyzer"), bridge)
        config = controller._clean_full_config(controller.default_config())
        config["auto_show"]["enabled"] = True
        low = controller._auto_show_state(playback(seconds=2), config["auto_show"])
        high = controller._auto_show_state(playback(seconds=18), config["auto_show"])

        self.assertEqual(0.0, low["song_analyzer_energy_modifier"])
        self.assertEqual(0.08, high["song_analyzer_energy_modifier"])
        self.assertLessEqual(high["energy"], 1.0)
        self.assertGreaterEqual(high["energy"], 0.0)


if __name__ == "__main__":
    unittest.main()
