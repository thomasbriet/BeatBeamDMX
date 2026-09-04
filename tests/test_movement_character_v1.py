import math
import unittest

import beatbeam_app as beatbeam


GEOMETRY = beatbeam.VenueGeometry(10.0, 12.0, 3.0, 1.2)
CENTERED = (-1.0, -1.0 / 3.0, 1.0 / 3.0, 1.0)


def context(index=0, *, motif=None, section="chorus", event_type=None, parameters=None, progress=.5):
    payload = {
        "role": "moving",
        "phrase": section,
        "section": section,
        "event_type": event_type,
        "energy": .76,
        "section_progress": progress,
        "variation_seed": "movement-character-v1-test",
        "artistic_participant_index": index,
        "artistic_participant_count": 4,
        "artistic_participant_centered": CENTERED[index],
        "artistic_closed_phase_offset": index / 4.0,
        "motion_parameters": parameters or {"range_scale": 1.0, "speed_scale": 1.0},
    }
    if motif:
        payload["movement_character_motif"] = motif
    return payload


def intents(effect, *, beat=8.0, motif=None, section="chorus", event_type=None, parameters=None, progress=.5):
    return [
        beatbeam.venue_native_effect_intent(
            effect, beat, GEOMETRY,
            context(index, motif=motif, section=section, event_type=event_type,
                    parameters=parameters, progress=progress),
            progress=progress,
        )
        for index in range(4)
    ]


class MovementCharacterV1Tests(unittest.TestCase):
    def test_character_is_deterministic_and_contains_only_world_character_terms(self):
        first = beatbeam.movement_character_for_context(
            "fast_audience_circle", 8.0, context(1), progress=.5
        )
        again = beatbeam.movement_character_for_context(
            "fast_audience_circle", 8.0, context(1), progress=.5
        )
        self.assertEqual(first, again)
        self.assertIn(first.motif, beatbeam.MOVEMENT_CHARACTER_MOTIFS)
        self.assertFalse(hasattr(first, "pan"))
        self.assertFalse(hasattr(first, "tilt"))

    def test_circle_motifs_change_pre_physical_relationships_without_shared_targets(self):
        shapes = {}
        for motif in ("CHASE", "PAIR", "MIRROR", "BLOOM", "RIPPLE"):
            result = intents("fast_audience_circle", motif=motif)
            self.assertTrue(all(item["kind"] == "WORLD_TARGET_XYZ_M" for item in result))
            points = [tuple(sorted(item["world_target_xyz_m"].items())) for item in result]
            self.assertEqual(4, len(set(points)), motif)
            shapes[motif] = tuple(points)
            metadata = result[0]["path_metadata"]
            self.assertEqual(motif, metadata["movement_character"]["motif"])
            self.assertIn("effective_phase", metadata)
            self.assertIn("range_envelope", metadata)
        self.assertEqual(5, len(set(shapes.values())))

    def test_circle_chase_pair_mirror_and_bloom_have_evidence_backed_structure(self):
        chase = intents("fast_audience_circle", motif="CHASE")
        chase_offsets = [item["path_metadata"]["movement_character"]["effective_phase_offset"] for item in chase]
        self.assertEqual([0.0, .17, .43, .71], chase_offsets)
        self.assertNotEqual(chase_offsets, [0.0, .25, .5, .75])

        pair = intents("fast_audience_circle", motif="PAIR")
        pair_offsets = [item["path_metadata"]["movement_character"]["effective_phase_offset"] for item in pair]
        self.assertLess(pair_offsets[1] - pair_offsets[0], .08)
        self.assertLess(pair_offsets[3] - pair_offsets[2], .08)
        self.assertGreater(pair_offsets[2] - pair_offsets[0], .4)

        mirror = intents("fast_audience_circle", motif="MIRROR", beat=7.0)
        for left, right in ((0, 3), (1, 2)):
            a, b = mirror[left]["world_target_xyz_m"], mirror[right]["world_target_xyz_m"]
            self.assertAlmostEqual(a["x"], -b["x"], places=6)
            self.assertAlmostEqual(a["y"], b["y"], places=6)

        early = intents("fast_audience_circle", motif="BLOOM", beat=1.0)
        later = intents("fast_audience_circle", motif="BLOOM", beat=13.0)
        self.assertNotEqual(
            early[0]["path_metadata"]["range_envelope"],
            later[0]["path_metadata"]["range_envelope"],
        )

    def test_speed_and_range_scale_affect_world_intent_not_venue_geometry(self):
        slow = intents("fast_audience_circle", parameters={"range_scale": 1.0, "speed_scale": .82})
        fast = intents("fast_audience_circle", parameters={"range_scale": 1.0, "speed_scale": 1.16})
        self.assertNotEqual(slow[0]["world_target_xyz_m"], fast[0]["world_target_xyz_m"])
        self.assertLess(
            slow[0]["path_metadata"]["movement_character"]["speed_factor"],
            fast[0]["path_metadata"]["movement_character"]["speed_factor"],
        )
        narrow = intents("fast_audience_circle", parameters={"range_scale": .72, "speed_scale": 1.0})
        wide = intents("fast_audience_circle", parameters={"range_scale": 1.0, "speed_scale": 1.0})
        self.assertLess(
            narrow[0]["path_metadata"]["range_envelope"],
            wide[0]["path_metadata"]["range_envelope"],
        )
        self.assertEqual(10.0, GEOMETRY.width_m)
        self.assertEqual(12.0, GEOMETRY.forward_depth_m)

    def test_hold_release_keeps_sweep_stationary_then_releases(self):
        held_a = beatbeam.venue_native_effect_intent(
            "fast_audience_sweep", 1.0, GEOMETRY, context(0, motif="HOLD_RELEASE", section="verse")
        )
        held_b = beatbeam.venue_native_effect_intent(
            "fast_audience_sweep", 2.0, GEOMETRY, context(0, motif="HOLD_RELEASE", section="verse")
        )
        moving = beatbeam.venue_native_effect_intent(
            "fast_audience_sweep", 9.0, GEOMETRY, context(0, motif="HOLD_RELEASE", section="verse")
        )
        self.assertTrue(held_a["path_metadata"]["hold_state"])
        self.assertEqual(held_a["world_target_xyz_m"], held_b["world_target_xyz_m"])
        self.assertNotEqual(held_b["world_target_xyz_m"], moving["world_target_xyz_m"])

    def test_cannon_sweep_and_crossing_accent_are_deterministic(self):
        cannon = intents("fast_audience_sweep", motif="CANNON", beat=8.0)
        offsets = [item["path_metadata"]["movement_character"]["effective_phase_offset"] for item in cannon]
        self.assertEqual([0.0, .10, .31, .58], offsets)
        self.assertEqual(4, len({tuple(sorted(item["world_target_xyz_m"].items())) for item in cannon}))
        crossing_a = intents("drop_crossing_beams", motif="HOLD_RELEASE", beat=.5, section="drop", event_type="DROP")
        crossing_b = intents("drop_crossing_beams", motif="HOLD_RELEASE", beat=.5, section="drop", event_type="DROP")
        self.assertEqual(crossing_a, crossing_b)
        self.assertTrue(crossing_a[0]["path_metadata"]["hold_state"])

    def test_fans_remain_directional_with_inner_outer_and_converge_explode(self):
        inner_outer = intents("drop_snap_fan", motif="INNER_OUTER", beat=8.0)
        self.assertTrue(all(item["kind"] == "WORLD_DIRECTION" for item in inner_outer))
        spreads = [abs(item["world_direction"]["x"]) for item in inner_outer]
        self.assertGreater(spreads[0], spreads[1])
        self.assertGreater(spreads[3], spreads[2])

        narrow = intents("build_narrow_to_wide_fan", motif="CONVERGE_EXPLODE", beat=1.0, section="drop", event_type="DROP")
        wide = intents("build_narrow_to_wide_fan", motif="CONVERGE_EXPLODE", beat=24.0, section="drop", event_type="DROP")
        self.assertTrue(all(item["kind"] == "WORLD_DIRECTION" for item in narrow + wide))
        self.assertTrue(narrow[0]["path_metadata"]["movement_character"]["snap"])
        self.assertLess(abs(narrow[0]["world_direction"]["x"]), abs(wide[0]["world_direction"]["x"]))

        widened_a = intents("build_narrow_to_wide_fan", motif="WIDEN", beat=1.0)
        widened_b = intents("build_narrow_to_wide_fan", motif="WIDEN", beat=24.0)
        pulse_a = intents("build_narrow_to_wide_fan", motif="PULSE", beat=1.0)
        pulse_b = intents("build_narrow_to_wide_fan", motif="PULSE", beat=24.0)
        self.assertNotEqual(widened_a[0]["world_direction"], widened_b[0]["world_direction"])
        self.assertNotEqual(pulse_a[0]["world_direction"], pulse_b[0]["world_direction"])

    def test_build_growth_drop_accent_and_prephysical_metadata(self):
        start = beatbeam.movement_character_for_context(
            "build_fastening_circle", 6.0, context(0, section="build", event_type="BUILD", progress=0.0), progress=0.0
        )
        end = beatbeam.movement_character_for_context(
            "build_fastening_circle", 6.0, context(0, section="build", event_type="BUILD", progress=1.0), progress=1.0
        )
        self.assertGreaterEqual(end.range_factor, start.range_factor)
        self.assertGreaterEqual(end.speed_factor, start.speed_factor)
        drop = beatbeam.movement_character_for_context(
            "drop_fast_circle_white", 6.0, context(0, section="drop", event_type="DROP"), progress=.5
        )
        self.assertIn(drop.motif, {"BLOOM", "CHASE"})
        intent = intents("drop_fast_circle_white", motif="BLOOM", section="drop", event_type="DROP")[0]
        self.assertNotIn("pan", intent)
        self.assertNotIn("tilt", intent)
        self.assertIn("movement_character", intent["path_metadata"])


if __name__ == "__main__":
    unittest.main()
