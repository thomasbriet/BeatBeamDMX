import unittest

import beatbeam_app as beatbeam
from enttec_open_dmx import find_fixture, find_mode, load_fixture_profiles


PALETTE = [
    beatbeam.MANUAL_COLOR_PRESETS["blue"],
    beatbeam.MANUAL_COLOR_PRESETS["orange"],
    beatbeam.MANUAL_COLOR_PRESETS["cyan"],
]


def trace(name, beat, *, fixture_index=0, fixture_count=2, progress=.5, count=8):
    return beatbeam.wall_wash_v2_zone_rgb(
        name, count, beat, PALETTE, fixture_index, fixture_count, progress
    )


def peak_index(values):
    return max(range(len(values)), key=lambda index: sum(values[index]))


def active(values):
    return {index for index, value in enumerate(values) if sum(value) > 80}


class WallWashEffectsV2Tests(unittest.TestCase):
    def test_configured_uking_p001_profile_exposes_eight_profile_declared_rgb_zones(self):
        fixture = find_fixture(load_fixture_profiles(), "uking_zq06016")
        mode = find_mode(fixture, "P001")
        self.assertEqual("uking_zq06016", fixture["id"])
        self.assertEqual("P001", mode["name"])
        self.assertEqual(24, mode["footprint"])
        self.assertEqual(8, beatbeam.wall_wash_zone_count(mode))

    def test_recipe_model_is_generic_over_zone_count(self):
        for count in (1, 3, 5, 9):
            with self.subTest(count=count):
                values = trace("wash_center_out", .0, count=count)
                self.assertEqual(count, len(values))
                self.assertTrue(all(len(value) == 4 and all(0 <= channel <= 255 for channel in value) for value in values))

    def test_composer_wash_identity_routes_to_profile_declared_zone_intent(self):
        controller = object.__new__(beatbeam.DmxController)
        config = {"fixture": "uking_zq06016", "mode": "P001"}
        auto_show = {
            "dynamic_composition_applied": True,
            "selected_primitives": {
                "wash": {
                    "wash_cue": "wash_mirror_chase",
                    "palette": "amber_teal",
                    "wash_parameters": {"phase_offset": 0},
                }
            },
            "dynamic_composer": {"continuous_musical_state": {"section_progress": .5}},
        }
        zones = controller._wall_wash_zone_rgb_for_slot(
            {"wash_coordination_index": 1, "wash_coordination_count": 2},
            auto_show, {"beat_value": 1.0}, config,
        )
        self.assertEqual(8, len(zones))
        self.assertEqual(6, peak_index(zones))

    def test_forward_reverse_and_bounce_have_distinct_ordered_motion(self):
        self.assertEqual([0, 1, 2], [peak_index(trace("wash_chase_forward", beat)) for beat in (0, .5, 1)])
        self.assertEqual([0, 7, 6], [peak_index(trace("wash_chase_reverse", beat)) for beat in (0, .5, 1)])
        bounce = [peak_index(trace("wash_bounce", beat)) for beat in (4, 14 / 3, 16 / 3, 6)]
        self.assertEqual([6, 7, 6, 5], bounce)

    def test_center_out_and_outside_in_start_at_opposite_logical_regions(self):
        center = active(trace("wash_center_out", 0))
        outside = active(trace("wash_outside_in", 0))
        self.assertEqual({3, 4}, center)
        self.assertEqual({0, 7}, outside)

    def test_halves_alternate_wave_is_multizone_and_wipe_progresses_color(self):
        self.assertNotEqual(trace("wash_alternating_halves", 0), trace("wash_alternating_halves", 1))
        wave = trace("wash_wave_forward", .4)
        self.assertGreater(len({sum(value) for value in wave}), 3)
        self.assertNotEqual(trace("wash_wave_forward", .4), trace("wash_chase_forward", .4))
        self.assertNotEqual(trace("wash_color_wipe", 0), trace("wash_color_wipe", 2))

    def test_build_and_drop_are_bounded_and_materially_develop(self):
        early = active(trace("wash_build_fill", 1, progress=.0))
        late = active(trace("wash_build_fill", 1, progress=1.0))
        self.assertGreater(len(late), len(early))
        impact = trace("wash_drop_explosion", .0)
        follow = trace("wash_drop_explosion", .4)
        settle = trace("wash_drop_explosion", 1.2)
        self.assertNotEqual(impact, follow)
        self.assertLess(sum(map(sum, settle)), sum(map(sum, impact)))

    def test_cross_wash_recipes_are_coordinated_not_identical(self):
        mirror_a = trace("wash_mirror_chase", 1, fixture_index=0)
        mirror_b = trace("wash_mirror_chase", 1, fixture_index=1)
        self.assertEqual(2, peak_index(mirror_a))
        self.assertEqual(6, peak_index(mirror_b))
        self.assertNotEqual(trace("wash_opposing_wave", .45, fixture_index=0), trace("wash_opposing_wave", .45, fixture_index=1))
        self.assertNotEqual(trace("wash_cannon", 1, fixture_index=0), trace("wash_cannon", 1, fixture_index=1))
        self.assertNotEqual(trace("wash_call_response", 0, fixture_index=0), trace("wash_call_response", 0, fixture_index=1))
        self.assertNotEqual(trace("wash_cross_ripple", 2, fixture_index=0), trace("wash_cross_ripple", 2, fixture_index=1))

    def test_named_effects_are_deterministic_and_materially_diverse(self):
        names = ("wash_chase_forward", "wash_wave_forward", "wash_bounce", "wash_color_wipe", "wash_build_fill", "wash_zone_hits")
        states = [tuple(trace(name, 1.25, progress=.6)) for name in names]
        self.assertEqual(len(states), len(set(states)))
        self.assertEqual(trace("wash_zone_hits", 1.25), trace("wash_zone_hits", 1.25))


if __name__ == "__main__":
    unittest.main()
