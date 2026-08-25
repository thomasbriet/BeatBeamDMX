import copy
import unittest

from rich_musical_events import (
    BEATBEAM_RICH_EVENT_MODE,
    RichMusicalEventHandoff,
    observe_rich_musical_events,
    parse_rich_musical_event_handoff,
)


def event(event_type="BUILD", temporal_kind="INTERVAL", start=0, end=8, start_bar=1, end_bar=4):
    value = {
        "type": event_type,
        "temporal_kind": temporal_kind,
        "start_seconds": start,
        "start_bar": start_bar,
        "origin_observation_id": "origin",
        "destination_observation_id": "destination",
        "structural_context": {"family_id": "opaque-family", "has_earlier_family_occurrence": True},
        "character_context": {"origin_relative_energy": .2, "destination_relative_energy": .8,
                              "energy_trajectory": .4, "energy_direction": .8,
                              "onset_direction": .5, "silence_direction": -.7,
                              "entry_contrast": .7, "boundary_novelty": .6},
        "provenance": {
            "source_category": "software_independent_structure_character",
            "derivation": "derived",
            "reasons": ["PositiveExitEnergyDirection", "PositivePreparationTrajectory"],
            "required_inputs": ["preparation_bundle", "section_timing"],
        },
    }
    if end is not None:
        value["end_seconds"] = end
    if end_bar is not None:
        value["end_bar"] = end_bar
    return value


def payload(events=None):
    return {
        "schema_version": 1,
        "contract": "rich-musical-events",
        "mode": "shadow_only",
        "track_key": "opaque-track",
        "availability": "available",
        "events": events if events is not None else [event()],
    }


class RichMusicalEventsTests(unittest.TestCase):
    def test_geldig_contract_wordt_immutable_en_shadow_only_geparseerd(self):
        parsed = parse_rich_musical_event_handoff(payload())

        self.assertIsInstance(parsed, RichMusicalEventHandoff)
        self.assertEqual("opaque-track", parsed.track_key)
        self.assertEqual("BUILD", parsed.events[0].event_type)
        self.assertEqual(("PositiveExitEnergyDirection", "PositivePreparationTrajectory"),
                         parsed.events[0].provenance.reasons)
        self.assertEqual("SHADOW_ONLY", BEATBEAM_RICH_EVENT_MODE)

    def test_point_en_boundary_semantiek_weigeren_intervaleinde(self):
        for temporal_kind in ("POINT", "BOUNDARY_TRANSITION"):
            with self.subTest(temporal_kind=temporal_kind):
                value = event("ARRIVAL", temporal_kind, 8, 16, 5, 8)
                with self.assertRaises(ValueError):
                    parse_rich_musical_event_handoff(payload([value]))

    def test_malformed_schema_type_timing_en_provenance_falen_gesloten(self):
        mutations = []
        wrong_schema = payload(); wrong_schema["schema_version"] = 2; mutations.append(wrong_schema)
        unknown_type = payload(); unknown_type["events"][0]["type"] = "CHORUS"; mutations.append(unknown_type)
        invalid_time = payload(); invalid_time["events"][0]["end_seconds"] = 0; mutations.append(invalid_time)
        boolean_time = payload(); boolean_time["events"][0]["start_seconds"] = True; mutations.append(boolean_time)
        wrong_source = payload(); wrong_source["events"][0]["provenance"]["source_category"] = "legacy"; mutations.append(wrong_source)
        missing_reason = payload(); missing_reason["events"][0]["provenance"]["reasons"] = []; mutations.append(missing_reason)
        for malformed in mutations:
            with self.subTest(malformed=malformed):
                with self.assertRaises(ValueError):
                    parse_rich_musical_event_handoff(malformed)

    def test_unsorted_en_duplicate_events_worden_geweigerd(self):
        later = event("BUILD", "INTERVAL", 8, 16, 5, 8)
        earlier = event("BUILD", "INTERVAL", 0, 8, 1, 4)
        with self.assertRaises(ValueError):
            parse_rich_musical_event_handoff(payload([later, earlier]))
        with self.assertRaises(ValueError):
            parse_rich_musical_event_handoff(payload([earlier, copy.deepcopy(earlier)]))

    def test_missingness_is_explicit_available_of_unavailable(self):
        unavailable = payload([])
        unavailable["availability"] = "unavailable"
        self.assertEqual((), parse_rich_musical_event_handoff(unavailable).events)
        with self.assertRaises(ValueError):
            parse_rich_musical_event_handoff(payload([]))
        unavailable["events"] = [event()]
        with self.assertRaises(ValueError):
            parse_rich_musical_event_handoff(unavailable)

    def test_observer_is_read_only_en_geeft_active_en_next_diagnostics(self):
        point = event("RELEASE", "BOUNDARY_TRANSITION", 8, None, 5, None)
        value = payload([event(), point])
        original = copy.deepcopy(value)
        handoff = parse_rich_musical_event_handoff(value)

        during = observe_rich_musical_events(handoff, 4)
        boundary = observe_rich_musical_events(handoff, 8)

        self.assertEqual(("BUILD",), during["active_interval_events"])
        self.assertEqual("RELEASE", during["next_event"]["type"])
        self.assertEqual(("RELEASE",), boundary["boundary_events"])
        self.assertEqual("SHADOW_ONLY", during["mode"])
        self.assertEqual(original, value)

    def test_consumer_heeft_geen_live_show_of_dmx_input(self):
        import inspect
        import rich_musical_events

        source = inspect.getsource(rich_musical_events)
        self.assertNotIn("beatbeam_app", source)
        self.assertNotIn("DmxController", source)
        self.assertNotIn("ShowIntent", source)
        self.assertEqual(["handoff", "position_seconds"],
                         list(inspect.signature(observe_rich_musical_events).parameters))


if __name__ == "__main__":
    unittest.main()
