import copy
import unittest

from dynamic_composer import compose_dynamic_preview, project_continuous_musical_state
from musical_event_envelope import MusicalEventEnvelope, project_musical_event_envelope
from rme_preview import preview_rme_context


def projection(event_type="ARRIVAL", *, availability="available_current", status="in_segment"):
    events = [] if event_type is None else [{
        "type": event_type, "temporal_kind": "POINT", "start_seconds": 10.0,
        "start_bar": 5, "origin_observation_id": f"event-{event_type}",
    }]
    return {
        "track_match": "exact", "availability": availability, "projection_status": status,
        "shadow_analysis": {"model": "SectionCharacterProfileShadow", "section_characters": [{
            "observation_id": "section-envelope", "start_seconds": 0.0, "end_seconds": 30.0,
            "relative_energy": .62, "energy_rise": .4, "recurrence_strength": .84,
            "family_salience": .75,
        }]},
        "rich_musical_events": {"mode": "SHADOW_ONLY", "availability": "available", "events": events},
    }


def playback(position=10.0, bar=5, beat=1, phase=0.0):
    return {
        "time_seconds": position, "bpm": 120.0, "beat_value": 16.0 + phase,
        "transport": {"virtualdj_bar_number": bar, "virtualdj_beat_number": beat},
    }


def base_show():
    return {"energy": .5, "movement": .4, "override_active": False}


class MusicalEventEnvelopeTests(unittest.TestCase):
    def state(self):
        state, reason = project_continuous_musical_state(projection(), 10.0)
        self.assertEqual("current", reason)
        return state

    def context(self, source, position):
        return preview_rme_context(source, position, "DYNAMIC_COMPOSER")

    def test_envelope_is_immutable_and_bar_timing_has_priority(self):
        source = projection("ARRIVAL")
        envelope, reason = project_musical_event_envelope(source, playback(10.4, 5, 1))
        self.assertEqual("active", reason)
        self.assertEqual(("ARRIVAL", "ATTACK", 0.0, "bar"),
                         (envelope.event_type, envelope.phase, envelope.beats_since_event, envelope.timing_source))
        with self.assertRaises(Exception):
            envelope.progress = .5
        with self.assertRaises(ValueError):
            MusicalEventEnvelope("ARRIVAL", "SETTLE", 1.1, .2, 1, 8, "bar")

    def test_arrival_attack_settle_and_completion_return_exactly_to_backbone(self):
        source = projection("ARRIVAL")
        state = self.state()
        baseline = compose_dynamic_preview(base_show(), state, self.context(projection(None), 10.0))
        attack, _ = project_musical_event_envelope(source, playback(10.0, 5, 1))
        half_bar, _ = project_musical_event_envelope(source, playback(11.0, 5, 3))
        one_bar, _ = project_musical_event_envelope(source, playback(12.0, 6, 1))
        complete, complete_reason = project_musical_event_envelope(source, playback(14.0, 7, 1))
        attack_show = compose_dynamic_preview(base_show(), state, self.context(source, 10.0), attack)
        half_show = compose_dynamic_preview(base_show(), state, self.context(source, 11.0), half_bar)
        one_show = compose_dynamic_preview(base_show(), state, self.context(source, 12.0), one_bar)
        complete_show = compose_dynamic_preview(base_show(), state, self.context(source, 14.0), complete)

        self.assertEqual("ATTACK", attack.phase)
        self.assertEqual("SETTLE", half_bar.phase)
        self.assertEqual("SETTLE", one_bar.phase)
        self.assertGreater(half_bar.strength, one_bar.strength)
        self.assertEqual("ARRIVAL", attack_show["event_type"])
        self.assertEqual("release", attack_show["fixture_group_intents"]["moving"]["palette_role"])
        self.assertNotEqual("hit", attack_show["selected_primitives"]["moving"]["pulse"])
        self.assertNotEqual(baseline["fixture_group_intents"], attack_show["fixture_group_intents"])
        self.assertEqual("complete_or_no_point_event", complete_reason)
        self.assertIsNone(complete)
        self.assertEqual(baseline["fixture_group_intents"], complete_show["fixture_group_intents"])
        self.assertEqual(baseline["selected_primitives"], complete_show["selected_primitives"])

    def test_drop_and_release_are_bounded_modifiers_not_latches(self):
        state = self.state()
        baseline = compose_dynamic_preview(base_show(), state, self.context(projection(None), 10.0))
        drop_source, release_source = projection("DROP"), projection("RELEASE")
        drop, _ = project_musical_event_envelope(drop_source, playback())
        release, _ = project_musical_event_envelope(release_source, playback())
        dropped = compose_dynamic_preview(base_show(), state, self.context(drop_source, 10.0), drop)
        released = compose_dynamic_preview(base_show(), state, self.context(release_source, 10.0), release)
        drop_complete, _ = project_musical_event_envelope(drop_source, playback(13.0, 6, 3))
        release_complete, _ = project_musical_event_envelope(release_source, playback(14.0, 7, 1))

        self.assertGreater(dropped["fixture_group_intents"]["par"]["accent_strength"], baseline["fixture_group_intents"]["par"]["accent_strength"])
        self.assertEqual("impact", dropped["fixture_group_intents"]["moving"]["palette_role"])
        self.assertEqual("release", released["fixture_group_intents"]["moving"]["palette_role"])
        self.assertIsNone(drop_complete)
        self.assertIsNone(release_complete)

    def test_arrival_is_stronger_than_backbone_but_remains_below_drop(self):
        state = self.state()
        baseline = compose_dynamic_preview(base_show(), state, self.context(projection(None), 10.0))
        arrival_source, drop_source = projection("ARRIVAL"), projection("DROP")
        arrival, _ = project_musical_event_envelope(arrival_source, playback())
        drop, _ = project_musical_event_envelope(drop_source, playback())
        arrived = compose_dynamic_preview(base_show(), state, self.context(arrival_source, 10.0), arrival)
        dropped = compose_dynamic_preview(base_show(), state, self.context(drop_source, 10.0), drop)
        for field in ("intensity", "pulse_amount", "accent_strength"):
            self.assertGreater(arrived["fixture_group_intents"]["par"][field],
                               baseline["fixture_group_intents"]["par"][field])
            self.assertLess(arrived["fixture_group_intents"]["par"][field],
                            dropped["fixture_group_intents"]["par"][field])

    def test_calling_high_energy_arrivals_project_as_strong_release_without_bar_rule(self):
        for bar, origin, destination, contrast in ((81, .347, .964, .309), (145, .398, .898, .301)):
            source = projection("ARRIVAL")
            event = source["rich_musical_events"]["events"][0]
            event["start_bar"] = bar
            event["character_context"] = {
                "origin_relative_energy": origin,
                "destination_relative_energy": destination,
                "entry_contrast": contrast,
            }
            envelope, reason = project_musical_event_envelope(source, playback(10.0, bar, 1))
            self.assertEqual("active", reason)
            self.assertEqual("STRONG_ARRIVAL", envelope.event_type)
            composition = compose_dynamic_preview(base_show(), self.state(), self.context(source, 10.0), envelope)
            self.assertEqual("full_sphere_explode", composition["selected_primitives"]["moving"]["movement_pattern"])

    def test_ordinary_or_quiet_arrival_is_not_promoted_to_strong_release(self):
        source = projection("ARRIVAL")
        source["rich_musical_events"]["events"][0]["character_context"] = {
            "origin_relative_energy": .91,
            "destination_relative_energy": .22,
            "entry_contrast": .31,
        }
        envelope, reason = project_musical_event_envelope(source, playback())
        self.assertEqual("active", reason)
        self.assertEqual("ARRIVAL", envelope.event_type)

    def test_future_fill_is_bounded_accent_without_raw_strobe_or_fixture_output(self):
        source = projection("FILL")
        envelope, _ = project_musical_event_envelope(source, playback())
        composition = compose_dynamic_preview(base_show(), self.state(), self.context(source, 10.0), envelope)
        self.assertEqual("FILL", composition["event_type"])
        self.assertGreater(composition["fixture_group_intents"]["par"]["accent_strength"], 0)
        for forbidden in ("dmx", "channel", "pan", "tilt", "strobe"):
            self.assertNotIn(forbidden, repr(composition).lower())
        complete, _ = project_musical_event_envelope(source, playback(11.0, 5, 3))
        self.assertIsNone(complete)

    def test_bpm_fallback_is_deterministic_when_bar_context_is_missing(self):
        source = projection("ARRIVAL")
        fallback = playback(11.0, None, None)
        first, reason = project_musical_event_envelope(source, fallback)
        second, _ = project_musical_event_envelope(copy.deepcopy(source), copy.deepcopy(fallback))
        self.assertEqual("active", reason)
        self.assertEqual((2.0, "bpm"), (first.beats_since_event, first.timing_source))
        self.assertEqual(first, second)

    def test_same_boundary_uses_one_bounded_semantic_modifier_without_stacking(self):
        source = projection("ARRIVAL")
        source["rich_musical_events"]["events"].append({
            "type": "RELEASE", "temporal_kind": "POINT", "start_seconds": 10.0,
            "start_bar": 5,
        })
        source["rich_musical_events"]["events"].append({
            "type": "DROP", "temporal_kind": "POINT", "start_seconds": 10.0,
            "start_bar": 5,
        })
        envelope, reason = project_musical_event_envelope(source, playback())
        self.assertEqual("active", reason)
        self.assertEqual("DROP", envelope.event_type)
        completed, completed_reason = project_musical_event_envelope(
            source, playback(13.0, 6, 3)
        )
        self.assertIsNone(completed)
        self.assertEqual("complete_or_no_point_event", completed_reason)

    def test_seek_track_switch_stale_and_manual_fail_closed(self):
        source = projection("ARRIVAL")
        self.assertEqual((None, "complete_or_no_point_event"),
                         project_musical_event_envelope(source, playback(9.0, 4, 3)))
        self.assertEqual((None, "track_not_current"),
                         project_musical_event_envelope(projection(availability="available_stale"), playback()))
        switched = projection()
        switched["track_match"] = "not_active"
        self.assertEqual((None, "track_not_current"), project_musical_event_envelope(switched, playback()))
        envelope, _ = project_musical_event_envelope(source, playback())
        manual = dict(base_show(), override_active=True)
        self.assertIsNone(compose_dynamic_preview(manual, self.state(), self.context(source, 10.0), envelope))


if __name__ == "__main__":
    unittest.main()
