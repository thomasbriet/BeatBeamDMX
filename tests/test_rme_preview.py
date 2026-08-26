import copy
import unittest

from rme_preview import apply_rme_preview_modifier, preview_rme_context


def event(event_type, kind, start, end=None):
    value = {"type": event_type, "temporal_kind": kind, "start_seconds": start,
             "origin_observation_id": f"event-{event_type}"}
    if end is not None:
        value["end_seconds"] = end
    return value


def projection(events, **overrides):
    value = {
        "track_match": "exact", "availability": "available_current",
        "projection_status": "in_segment",
        "rich_musical_events": {"mode": "SHADOW_ONLY", "availability": "available", "events": events},
    }
    value.update(overrides)
    return value


class RmePreviewTests(unittest.TestCase):
    def test_baseline_and_missing_or_stale_rme_fail_closed(self):
        source = projection([event("BUILD", "INTERVAL", 10, 20)])
        self.assertEqual("mode_baseline", preview_rme_context(source, 12, "BASELINE")["reason"])
        self.assertEqual("track_not_current", preview_rme_context({}, 12, "RME_ENHANCED")["reason"])
        stale = projection([event("BUILD", "INTERVAL", 10, 20)], availability="available_stale")
        self.assertEqual("track_not_current", preview_rme_context(stale, 12, "RME_ENHANCED")["reason"])

    def test_build_progress_is_continuous(self):
        source = projection([event("BUILD", "INTERVAL", 10, 20)])
        self.assertEqual(0.0, preview_rme_context(source, 10, "RME_ENHANCED")["rme_progress"])
        self.assertEqual(0.5, preview_rme_context(source, 15, "RME_ENHANCED")["rme_progress"])
        self.assertIsNone(preview_rme_context(source, 20, "RME_ENHANCED")["rme_progress"])

    def test_break_drop_arrival_and_seek_select_current_context(self):
        source = projection([
            event("BUILD", "INTERVAL", 0, 10), event("BREAK", "INTERVAL", 10, 20),
            event("ARRIVAL", "POINT", 20), event("DROP", "POINT", 30),
        ])
        self.assertEqual("BREAK", preview_rme_context(source, 15, "RME_ENHANCED")["current_rme"]["type"])
        self.assertEqual("ARRIVAL", preview_rme_context(source, 20.2, "RME_ENHANCED")["current_rme"]["type"])
        self.assertEqual("DROP", preview_rme_context(source, 30.2, "RME_ENHANCED")["current_rme"]["type"])
        self.assertEqual("BUILD", preview_rme_context(source, 4, "RME_ENHANCED")["current_rme"]["type"])

    def test_arrival_is_not_a_drop_and_base_is_not_mutated(self):
        base = {"energy": 0.5, "movement": 0.5, "rhythm_mode": "medium", "beat_pulse": False, "strobe_window": False}
        arrival = preview_rme_context(projection([event("ARRIVAL", "POINT", 10)]), 10.2, "RME_ENHANCED")
        enhanced = apply_rme_preview_modifier(base, arrival)
        self.assertEqual("medium", enhanced["rhythm_mode"])
        self.assertFalse(enhanced["beat_pulse"])
        self.assertEqual(base, {"energy": 0.5, "movement": 0.5, "rhythm_mode": "medium", "beat_pulse": False, "strobe_window": False})

    def test_drop_is_bounded_and_deterministic(self):
        base = {"energy": 0.94, "movement": 0.95, "rhythm_mode": "medium", "beat_pulse": False, "strobe_window": False}
        context = preview_rme_context(projection([event("DROP", "POINT", 10)]), 10.2, "RME_ENHANCED")
        first = apply_rme_preview_modifier(base, context)
        self.assertEqual(first, apply_rme_preview_modifier(copy.deepcopy(base), copy.deepcopy(context)))
        self.assertEqual((1.0, 1.0, "strong_pulse", False), (first["energy"], first["movement"], first["rhythm_mode"], first["strobe_window"]))

    def test_manual_override_keeps_preview_on_the_existing_show_intent(self):
        base = {"energy": 0.5, "movement": 0.5, "override_active": True}
        context = preview_rme_context(
            projection([event("BUILD", "INTERVAL", 10, 20)]), 12, "RME_ENHANCED"
        )
        enhanced = apply_rme_preview_modifier(base, context)

        self.assertEqual(0.5, enhanced["energy"])
        self.assertEqual(0.5, enhanced["movement"])
        self.assertNotIn("preview_intensity_multiplier", enhanced)
        self.assertEqual("manual_override_baseline", enhanced["rme_preview"]["rme_modifier"])


if __name__ == "__main__":
    unittest.main()
