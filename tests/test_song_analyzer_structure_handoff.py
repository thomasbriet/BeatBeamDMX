import json
import tempfile
import unittest
from pathlib import Path

from beatbeam_app import SongAnalyzerStructureHandoff, shadow_section_character_at


FIXTURE = Path(__file__).parent / "fixtures" / "beatbeam-structure-handoff-v1.json"
TRACK = "/Music/Example/O'Brien Café.flac"


def playback(path, seconds, source="virtualdj"):
    return {
        "_active_playback_source": source,
        "track_path": path,
        "time_seconds": seconds,
    }


class SongAnalyzerStructureHandoffTests(unittest.TestCase):
    def test_default_refresh_interval_bounds_live_handoff_reloads(self):
        handoff = SongAnalyzerStructureHandoff(FIXTURE)

        self.assertEqual(5.0, handoff.check_interval_seconds)

    def test_transient_unavailable_snapshot_does_not_invalidate_stable_track_cache(self):
        handoff = SongAnalyzerStructureHandoff(FIXTURE, check_interval_seconds=60)

        stable = handoff.project(playback(TRACK, 2))
        unavailable = handoff.project({
            "_active_playback_source": "virtualdj",
            "track_path": None,
            "time_seconds": None,
            "playback_state": {
                "availability": "unavailable",
                "transport_state": "unknown",
                "last_discontinuity": "source_unavailable",
            },
        })
        recovered = handoff.project(playback(TRACK, 2))

        self.assertEqual(1, stable["metrics"]["structure_loads"])
        self.assertEqual(1, stable["metrics"]["track_switches"])
        self.assertIsNone(unavailable["canonical_track_path"])
        self.assertEqual(1, unavailable["metrics"]["structure_loads"])
        self.assertEqual(1, unavailable["metrics"]["track_switches"])
        self.assertEqual(1, recovered["metrics"]["structure_loads"])
        self.assertEqual(1, recovered["metrics"]["track_switches"])

    def test_same_track_transport_noise_respects_refresh_interval(self):
        handoff = SongAnalyzerStructureHandoff(FIXTURE, check_interval_seconds=60)

        initial = handoff.project(playback(TRACK, 2))
        changed_transport = handoff.project({
            "_active_playback_source": "virtualdj",
            "track_path": TRACK,
            "time_seconds": 3,
            "playback_state": {
                "availability": "available",
                "transport_state": "advancing",
                "last_discontinuity": "position_jump_forward",
            },
        })

        self.assertEqual(1, initial["metrics"]["structure_loads"])
        self.assertEqual(1, changed_transport["metrics"]["structure_loads"])
        self.assertEqual(1, changed_transport["metrics"]["track_switches"])

    def test_genuine_track_path_change_reloads_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            alternate = json.loads(json.dumps(payload["tracks"][0]))
            alternate["canonical_path"] = "/Music/Example/Second Track.flac"
            payload["tracks"].append(alternate)
            path.write_text(json.dumps(payload), encoding="utf-8")
            handoff = SongAnalyzerStructureHandoff(path, check_interval_seconds=60)

            first = handoff.project(playback(TRACK, 2))
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            switched = handoff.project(playback(alternate["canonical_path"], 2))
            repeated = handoff.project(playback(alternate["canonical_path"], 3))

        self.assertEqual(1, first["metrics"]["structure_loads"])
        self.assertEqual(2, switched["metrics"]["structure_loads"])
        self.assertEqual(2, switched["metrics"]["track_switches"])
        self.assertEqual(2, repeated["metrics"]["structure_loads"])
        self.assertEqual(2, repeated["metrics"]["track_switches"])

    def test_preloaded_exact_inactive_deck_track_swaps_without_waiting_for_active_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            prepared = json.loads(json.dumps(payload["tracks"][0]))
            prepared["canonical_path"] = "/Music/Prepared Next.flac"
            payload["tracks"].append(prepared)
            payload["active_track"] = {
                "canonical_path": TRACK, "deck": 1, "status": "ready", "generation": 10,
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            handoff = SongAnalyzerStructureHandoff(path, check_interval_seconds=60)

            current = handoff.project(playback(TRACK, 2))
            switched = handoff.project(playback(prepared["canonical_path"], 2))

        self.assertEqual(TRACK, current["canonical_track_path"])
        self.assertEqual("exact", current["track_match"])
        self.assertEqual("exact", switched["track_match"])
        self.assertEqual("available_current", switched["availability"])
        self.assertEqual("Intro 1", switched["current"]["label"])
        self.assertEqual(1, switched["metrics"]["structure_loads"])

    def test_preloader_installs_next_track_before_authority_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            prepared = json.loads(json.dumps(payload["tracks"][0]))
            prepared["canonical_path"] = "/Music/Prepared Next.flac"
            payload["tracks"].append(prepared)
            payload["active_track"] = {
                "canonical_path": TRACK, "deck": 1, "status": "ready", "generation": 10,
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            handoff = SongAnalyzerStructureHandoff(path, check_interval_seconds=60)
            self.assertTrue(handoff._preload_once())
            current = handoff.project(playback(TRACK, 2))
            payload["active_track"] = {
                "canonical_path": prepared["canonical_path"], "deck": 2, "status": "ready", "generation": 11,
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            handoff._background_preloader_started = True
            switched = handoff.project(playback(prepared["canonical_path"], 2))

        self.assertEqual(TRACK, current["canonical_track_path"])
        self.assertEqual("exact", current["track_match"])
        self.assertEqual("exact", switched["track_match"])
        self.assertEqual(1, switched["metrics"]["structure_loads"])

    def test_active_sidecar_updates_without_reparsing_prepared_track_index(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            active_path = Path(directory) / "beatbeam-active-track.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            prepared = json.loads(json.dumps(payload["tracks"][0]))
            prepared["canonical_path"] = "/Music/Prepared Next.flac"
            payload["tracks"].append(prepared)
            payload["active_track"] = {
                "canonical_path": TRACK, "deck": 1, "status": "ready", "generation": 10,
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            handoff = SongAnalyzerStructureHandoff(path, check_interval_seconds=60, active_track_path=active_path)
            self.assertTrue(handoff._preload_once())
            active_path.write_text(json.dumps({
                "schema_version": 1,
                "active_track": {
                    "canonical_path": prepared["canonical_path"], "deck": 2,
                    "status": "ready", "generation": 11,
                },
            }), encoding="utf-8")
            handoff._refresh_active_track(force=True)
            before_switch = handoff.project(playback(TRACK, 2))
            switched = handoff.project(playback(prepared["canonical_path"], 2))

        self.assertEqual("sidecar", before_switch["active_track_source"])
        self.assertEqual(TRACK, before_switch["canonical_track_path"])
        self.assertEqual("exact", before_switch["track_match"])
        self.assertEqual("exact", switched["track_match"])
        self.assertEqual(1, switched["metrics"]["structure_loads"])

    def test_pending_active_sidecar_fails_closed_without_using_prepared_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            active_path = Path(directory) / "beatbeam-active-track.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            path.write_text(json.dumps(payload), encoding="utf-8")
            active_path.write_text(json.dumps({
                "schema_version": 1,
                "active_track": {
                    "canonical_path": TRACK, "deck": 1,
                    "status": "pending", "generation": 11,
                },
            }), encoding="utf-8")
            handoff = SongAnalyzerStructureHandoff(path, check_interval_seconds=60, active_track_path=active_path)
            result = handoff.project(playback(TRACK, 2))

        self.assertEqual("sidecar", result["active_track_source"])
        self.assertEqual("pending", result["availability"])
        self.assertEqual("active_not_ready", result["track_match"])

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

    def test_optional_shadow_section_characters_are_parsed_and_are_debug_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            payload["tracks"][0]["shadow_analysis"] = shadow_analysis()
            path.write_text(json.dumps(payload), encoding="utf-8")
            handoff = SongAnalyzerStructureHandoff(path, check_interval_seconds=0)

            production = handoff.project(playback(TRACK, 8))
            debug = handoff.project(playback(TRACK, 8), include_shadow=True)

            self.assertNotIn("shadow_analysis", production)
            self.assertEqual("Intro 1", production["current"]["label"])
            character = debug["shadow_analysis"]["section_characters"][0]
            self.assertEqual("raw-section-0000-0004", character["observation_id"])
            self.assertEqual(.91, character["recurrence_strength"])
            self.assertEqual(.72, character["relative_energy"])
            self.assertEqual(.31, character["energy_rise"])
            self.assertIsNone(character["build_momentum"])
            self.assertEqual(.61, character["boundary_novelty"])
            self.assertEqual(4, character["bar_count"])
            self.assertEqual(.91, character["entry_boundary"]["membership_exit_strength"])
            self.assertEqual(.46, character["entry_boundary"]["energy_change"])
            self.assertEqual(.62, character["entry_boundary"]["energy_delta"])
            self.assertEqual(-.40, character["entry_boundary"]["onset_delta"])
            self.assertEqual(.31, character["preparation_profile"]["energy_trajectory"])
            self.assertEqual(.62, character["arrival_profile"]["energy_direction"])
            self.assertIsNone(character["arrival_profile"]["origin_relative_energy"])
            self.assertEqual(.72, character["arrival_profile"]["destination_relative_energy"])
            self.assertEqual("family-exit", character["entry_structural_departure"]["structural_route"])

    def test_shadow_range_lookup_respects_boundaries_and_unknown_values(self):
        sections = shadow_analysis()["section_characters"]

        self.assertEqual("raw-section-0000-0004", shadow_section_character_at({"section_characters": sections}, 0)["observation_id"])
        self.assertEqual("raw-section-0000-0004", shadow_section_character_at({"section_characters": sections}, 7.99)["observation_id"])
        self.assertEqual("raw-section-0004-0008", shadow_section_character_at({"section_characters": sections}, 8)["observation_id"])
        self.assertIsNone(shadow_section_character_at({"section_characters": sections}, -0.01))
        self.assertIsNone(shadow_section_character_at({"section_characters": sections}, 16.01))

    def test_optional_shadow_event_evidence_is_debug_only_and_maps_to_the_destination_context(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            shadow = shadow_analysis()
            shadow["event_evidence"] = [{
                "origin_observation_id": "raw-section-0000-0004",
                "destination_observation_id": "raw-section-0004-0008",
                "boundary_seconds": 8, "boundary_bar": 5,
                "preparation_aspect": shadow["section_characters"][0]["preparation_profile"],
                "arrival_aspect": shadow["section_characters"][1].get("arrival_profile"),
                "structural_departure_aspect": {"origin_exit": None, "destination_entry": None},
                "arrangement_identity_aspect": {"recurrence_strength": None, "family_salience": None,
                                                "family_id": None, "has_earlier_family_occurrence": None},
                "destination_is_terminal": True,
                "temporal_context": {"pre_boundary_normalized_rms": -.42, "post_boundary_normalized_rms": 1.17,
                                     "late_origin_relative_energy": .31, "early_destination_relative_energy": .86,
                                     "window": {"bars": [
                                         {"relative_bar_offset": -2, "normalized_rms": -.8, "relative_energy": .2},
                                         {"relative_bar_offset": -1, "normalized_rms": -.42, "relative_energy": .31},
                                         {"relative_bar_offset": 1, "normalized_rms": 1.17, "relative_energy": .86},
                                         {"relative_bar_offset": 2, "normalized_rms": 1.4, "relative_energy": .9},
                                     ]}},
            }]
            payload["tracks"][0]["shadow_analysis"] = shadow
            path.write_text(json.dumps(payload), encoding="utf-8")
            handoff = SongAnalyzerStructureHandoff(path, check_interval_seconds=0)

            production = handoff.project(playback(TRACK, 10))
            debug = handoff.project(playback(TRACK, 10), include_shadow=True)

            self.assertNotIn("shadow_analysis", production)
            evidence = debug["shadow_analysis"]["event_evidence"]
            self.assertEqual(1, len(evidence))
            self.assertEqual("raw-section-0000-0004", evidence[0]["origin_observation_id"])
            self.assertEqual("raw-section-0004-0008", evidence[0]["destination_observation_id"])
            self.assertTrue(evidence[0]["destination_is_terminal"])
            self.assertEqual(-.42, evidence[0]["temporal_context"]["pre_boundary_normalized_rms"])
            self.assertEqual(1.17, evidence[0]["temporal_context"]["post_boundary_normalized_rms"])
            self.assertEqual(.31, evidence[0]["temporal_context"]["late_origin_relative_energy"])
            self.assertEqual(.86, evidence[0]["temporal_context"]["early_destination_relative_energy"])
            self.assertEqual([-2, -1, 1, 2], [bar["relative_bar_offset"]
                             for bar in evidence[0]["temporal_context"]["window"]["bars"]])
            self.assertNotIn("upward", json.dumps(evidence[0]).lower())

    def test_temporal_window_missing_partial_and_malformed_are_debug_fail_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            shadow = shadow_analysis()
            event = {"origin_observation_id": "raw-section-0000-0004", "destination_observation_id": "raw-section-0004-0008",
                     "boundary_seconds": 8, "boundary_bar": 5, "structural_departure_aspect": {"origin_exit": None, "destination_entry": None},
                     "arrangement_identity_aspect": {"family_id": None, "has_earlier_family_occurrence": None},
                     "temporal_context": {"pre_boundary_normalized_rms": -.42, "post_boundary_normalized_rms": 1.17,
                                          "late_origin_relative_energy": .31, "early_destination_relative_energy": .86}}
            shadow["event_evidence"] = [event]
            payload["tracks"][0]["shadow_analysis"] = shadow
            path.write_text(json.dumps(payload), encoding="utf-8")

            context = SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project(
                playback(TRACK, 10), include_shadow=True)["shadow_analysis"]["event_evidence"][0]["temporal_context"]
            self.assertIsNone(context["window"])

            event["temporal_context"]["window"] = {"bars": [
                {"relative_bar_offset": -1, "normalized_rms": -.42, "relative_energy": .31},
                {"relative_bar_offset": 1, "normalized_rms": 1.17, "relative_energy": .86},
            ]}
            path.write_text(json.dumps(payload), encoding="utf-8")
            context = SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project(
                playback(TRACK, 10), include_shadow=True)["shadow_analysis"]["event_evidence"][0]["temporal_context"]
            self.assertEqual([-1, 1], [bar["relative_bar_offset"] for bar in context["window"]["bars"]])

            event["temporal_context"]["window"] = {"bars": [{"relative_bar_offset": 0, "normalized_rms": 0, "relative_energy": .5}]}
            path.write_text(json.dumps(payload), encoding="utf-8")
            state = SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project(playback(TRACK, 10), include_shadow=True)
            self.assertNotEqual("invalid", state["load_status"])
            self.assertIsNone(state["shadow_analysis"]["event_evidence"][0]["temporal_context"]["window"])
            self.assertNotIn("shadow_analysis", SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project(playback(TRACK, 10)))

    def test_temporal_context_nulls_remain_null_and_partial_context_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            shadow = shadow_analysis()
            event = {
                "origin_observation_id": "raw-section-0000-0004", "destination_observation_id": "raw-section-0004-0008",
                "boundary_seconds": 8, "boundary_bar": 5,
                "structural_departure_aspect": {"origin_exit": None, "destination_entry": None},
                "arrangement_identity_aspect": {"family_id": None, "has_earlier_family_occurrence": None},
                "temporal_context": {"pre_boundary_normalized_rms": None, "post_boundary_normalized_rms": None,
                                     "late_origin_relative_energy": None, "early_destination_relative_energy": None},
            }
            shadow["event_evidence"] = [event]
            payload["tracks"][0]["shadow_analysis"] = shadow
            path.write_text(json.dumps(payload), encoding="utf-8")

            debug = SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project(playback(TRACK, 10), include_shadow=True)
            self.assertEqual({**event["temporal_context"], "window": None},
                             debug["shadow_analysis"]["event_evidence"][0]["temporal_context"])
            self.assertNotIn("shadow_analysis", SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project(playback(TRACK, 10)))

            event["temporal_context"] = {"pre_boundary_normalized_rms": -.42}
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual("invalid", SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project(playback(TRACK, 10))["load_status"])

    def test_missing_shadow_event_terminality_remains_backward_compatible_without_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            shadow = shadow_analysis()
            shadow["event_evidence"] = [{
                "origin_observation_id": "raw-section-0000-0004",
                "destination_observation_id": "raw-section-0004-0008",
                "boundary_seconds": 8, "boundary_bar": 5,
                "structural_departure_aspect": {"origin_exit": None, "destination_entry": None},
                "arrangement_identity_aspect": {"family_id": None, "has_earlier_family_occurrence": None},
            }]
            payload["tracks"][0]["shadow_analysis"] = shadow
            path.write_text(json.dumps(payload), encoding="utf-8")

            evidence = SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project(
                playback(TRACK, 10), include_shadow=True)["shadow_analysis"]["event_evidence"]

            self.assertIsNone(evidence[0]["destination_is_terminal"])

    def test_non_contiguous_shadow_event_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            shadow = shadow_analysis()
            shadow["event_evidence"] = [{
                "origin_observation_id": "raw-section-0000-0004",
                "destination_observation_id": "raw-section-0004-0008",
                "boundary_seconds": 9,
                "structural_departure_aspect": {"origin_exit": None, "destination_entry": None},
                "arrangement_identity_aspect": {"family_id": None, "has_earlier_family_occurrence": None},
            }]
            payload["tracks"][0]["shadow_analysis"] = shadow
            path.write_text(json.dumps(payload), encoding="utf-8")

            state = SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project(playback(TRACK, 10), include_shadow=True)

            self.assertEqual("invalid", state["load_status"])

    def test_legacy_structural_novelty_remains_readable_but_is_republished_as_boundary_novelty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            legacy = shadow_analysis()
            first = legacy["section_characters"][0]
            first["structural_novelty"] = first.pop("boundary_novelty")
            first.pop("bar_count")
            payload["tracks"][0]["shadow_analysis"] = legacy
            path.write_text(json.dumps(payload), encoding="utf-8")

            shadow = SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project(playback(TRACK, 2), include_shadow=True)["shadow_analysis"]

            character = shadow["section_characters"][0]
            self.assertEqual(.61, character["boundary_novelty"])
            self.assertNotIn("structural_novelty", character)
            self.assertIsNone(character["bar_count"])

    def test_invalid_shadow_value_fails_closed_without_affecting_legacy_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            payload["tracks"][0]["shadow_analysis"] = shadow_analysis()
            payload["tracks"][0]["shadow_analysis"]["section_characters"][0]["recurrence_strength"] = 1.1
            path.write_text(json.dumps(payload), encoding="utf-8")

            invalid = SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project(playback(TRACK, 2), include_shadow=True)

            self.assertEqual("invalid", invalid["load_status"])
            self.assertIsNone(invalid["current"])

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

    def test_v2_semantic_sections_are_projected_and_legacy_remains_available(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            payload["schema_version"] = 2
            payload["tracks"][0]["rich_analysis"] = {
                "model": "SongAnalyzerRichAnalysis", "energy_scale": "segment-normalized-rms-z-score",
                "segments": [{"index": 0, "start_seconds": 0, "end_seconds": 32, "label": "Phrase", "level": "phrase", "energy": 0.2}],
                "sections": [{"index": 0, "start_seconds": 0, "end_seconds": 32, "role": "PreChorus", "occurrence": 1, "family_id": "family-001", "confidence": 86, "start_bar": 1, "end_bar": 17, "source_phrase_count": 2}],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            state = SongAnalyzerStructureHandoff(path, check_interval_seconds=0).project(playback(TRACK, 12))
            self.assertEqual("PreChorus", state["semantic_section"]["role"])
            self.assertEqual("family-001", state["semantic_section"]["family_id"])
            self.assertEqual(1, len(state["rich_analysis"]["sections"]))
            self.assertEqual("Phrase", state["rich_current"]["label"])

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

    def test_pending_or_other_active_track_never_projects_previous_track_data(self):
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
            payload["tracks"][0]["availability"] = "missing"
            path.write_text(json.dumps(payload), encoding="utf-8")
            other = handoff.project(playback(TRACK, 2))
            self.assertEqual("not_active", other["track_match"])
            self.assertIsNone(other["current"])

def shadow_analysis():
    return {
        "model": "SectionCharacterProfileShadow",
        "section_characters": [
            {"observation_id": "raw-section-0000-0004", "start_seconds": 0, "end_seconds": 8,
             "start_bar": 1, "end_bar": 4, "bar_count": 4, "recurrence_strength": .91, "family_salience": .65,
             "relative_energy": .72, "energy_rise": .31, "entry_contrast": .74, "exit_contrast": None, "build_momentum": None, "boundary_novelty": .61,
             "preparation_profile": {"energy_trajectory": .31, "exit_energy_direction": .62,
                                     "exit_onset_direction": -.40, "exit_silence_direction": -1.2,
                                     "exit_structural_context": .3},
             "arrival_profile": {"entry_contrast": .74, "boundary_novelty": .61, "energy_direction": .62,
                                 "onset_direction": -.40, "silence_direction": -1.2,
                                 "origin_relative_energy": None, "destination_relative_energy": .72},
             "entry_structural_departure": {"structural_context_change": .3, "membership_exit_strength": .91,
                                              "repeated_section_end": .8, "recurrence_change": .2, "structural_route": "family-exit",
                                              "structural_evidence": .55, "structural_target_bar": 13},
             "entry_boundary": {"recurrence_change": .2, "structural_context_change": .3,
                                "membership_exit_strength": .91, "repeated_section_end": .8,
                                "structural_route": "family-exit", "structural_evidence": .55,
                                "structural_target_bar": 13, "energy_change": .46, "onset_change": .28,
                                "silence_change": .14, "energy_delta": .62, "onset_delta": -.40,
                                "silence_delta": .18}},
            {"observation_id": "raw-section-0004-0008", "start_seconds": 8, "end_seconds": 16,
             "start_bar": 5, "end_bar": 8, "bar_count": 4, "recurrence_strength": None, "family_salience": None,
             "entry_contrast": None, "exit_contrast": None, "build_momentum": None, "boundary_novelty": None},
        ],
    }


if __name__ == "__main__":
    unittest.main()
