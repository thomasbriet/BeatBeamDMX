import unittest

from show_simulator import ShowSimulationSession


class FakeHandoff:
    path = "/music/example.flac"

    def catalog(self):
        return [{"path": self.path, "title": "Example", "duration_seconds": 120.0,
                 "bpm": 120.0, "analysis_version": "current", "analysis_hash": "a" * 64}]

    def project(self, playback, include_shadow=False, include_rich_events=False):
        self.last_playback = dict(playback)
        return {
            "track_match": "exact", "availability": "available_current", "projection_status": "in_segment",
            "analysis_version": "current", "shadow_analysis": {"model": "SectionCharacterProfileShadow", "section_characters": [{
                "observation_id": "section-0", "start_seconds": 0.0, "end_seconds": 120.0,
                "relative_energy": 0.5, "energy_rise": 0.1, "recurrence_strength": 0.0, "family_salience": 0.2,
            }]},
            "rich_musical_events": {"mode": "SHADOW_ONLY", "availability": "available", "events": [{
                "type": "DROP", "start_seconds": 30.0, "start_bar": 16,
            }]},
            "rich_analysis": {"events": []},
        }


class ShowSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.handoff = FakeHandoff()
        self.session = ShowSimulationSession(self.handoff, smart_cues=lambda path: [{"role": "MAIN", "planned": True}])

    def test_selection_is_simulation_only_and_has_analyzed_only_intensity(self):
        state = self.session.select(self.handoff.path)
        self.assertEqual("SIMULATION", state["mode"])
        self.assertEqual("NONE", state["physical_output"])
        self.assertEqual("ANALYZED_ONLY", state["live_intensity"]["status"])
        self.assertEqual("simulator", self.handoff.last_playback["_active_playback_source"])
        self.assertEqual([{"role": "MAIN", "planned": True}], state["smart_cues"])

    def test_direct_seek_derives_active_envelope_and_is_deterministic(self):
        first = self.session.select(self.handoff.path)
        at_event = self.session.seek(30.2)
        repeated = self.session.seek(30.2)
        self.assertIsNotNone(first["composition"])
        self.assertEqual("IMPACT", at_event["event_envelope"]["phase"])
        self.assertEqual(at_event["composition"]["composition_signature"], repeated["composition"]["composition_signature"])
        self.assertEqual(at_event["composition"], repeated["composition"])

    def test_restart_and_bounds(self):
        self.session.select(self.handoff.path)
        self.session.seek(119.9)
        self.assertEqual(120000, self.session.seek(999.0)["transport"]["position_milliseconds"])
        self.assertEqual(0, self.session.restart()["transport"]["position_milliseconds"])
        self.assertFalse(self.session.state()["transport"]["playing"])
