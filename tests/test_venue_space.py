import copy
import json
import math
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from beatbeam_app import (
    DmxController,
    VENUE_TARGETS,
    canonical_venue_target_id,
    VenueTargetVerticalLayer,
    VenueFixtureCalibration,
    VenueGeometry,
    VenuePhysicalPoint,
    VenuePoint,
    VenueVector3,
    fixture_calibration_state,
    fixture_physical_tilt_limits,
    _venue_calibration_for_slot,
    fit_kinematic_calibration,
    fixture_orientation_basis,
    find_fixture,
    find_mode,
    resolve_venue_target,
    resolve_venue_target_point,
    resolve_venue_target_z,
    resolve_spatial_movement_intent,
    rendered_motion_projection,
    kinematic_calibration_state,
    axis_mapping_v2_forward,
    axis_mapping_v2_inverse_pan,
    axis_mapping_v2_inverse_tilt,
    axis_mapping_v2_state,
    fit_axis_mapping_v2,
    venue_meters_to_normalized,
    venue_native_effect_intent,
    venue_normalized_to_meters,
    venue_space_state,
)


TEST_GEOMETRY = VenueGeometry(10.0, 12.0, 3.0, 1.2)


def calibrated_fixture(forward=(0, 1, 0), up=(0, 0, 1), position=(0, 0), **overrides):
    values = dict(
        supports_pan_tilt=True,
        position=VenuePoint(*position),
        mounting_height_m=2.5,
        physical_forward=VenueVector3(*forward),
        physical_up=VenueVector3(*up),
        pan_min_degrees=-270,
        pan_max_degrees=270,
        tilt_min_degrees=-90,
        tilt_max_degrees=90,
        use_fine_pan_tilt=True,
        supports_pan_fine=True,
        supports_tilt_fine=True,
    )
    values.update(overrides)
    return VenueFixtureCalibration(**values)


def geometry_dict(**overrides):
    value = TEST_GEOMETRY.as_dict()
    value.update(overrides)
    return value


class VenueGeometryV1Tests(unittest.TestCase):
    def test_dj_centric_axes_targets_and_unset_defaults_remain_stable(self):
        state = venue_space_state()
        self.assertEqual(4, state["version"])
        self.assertEqual("DJ", state["viewpoint"])
        self.assertEqual({"x": 0.0, "y": 0.0}, state["origin"])
        self.assertEqual("DJ_LEFT", state["axes"]["x_negative"])
        self.assertEqual("DJ_RIGHT", state["axes"]["x_positive"])
        self.assertEqual("AUDIENCE", state["axes"]["y_positive"])
        self.assertEqual("REAR", state["axes"]["y_negative"])
        self.assertEqual("MISSING_VENUE_SCALE", state["venue_geometry"]["status"])
        self.assertIsNone(state["venue_geometry"]["venue_width_m"])
        self.assertEqual(
            [
                "AUDIENCE_NEAR_LEFT", "AUDIENCE_NEAR_CENTER", "AUDIENCE_NEAR_RIGHT",
                "AUDIENCE_MID_LEFT", "AUDIENCE_MID_CENTER", "AUDIENCE_MID_RIGHT",
                "AUDIENCE_FAR_LEFT", "AUDIENCE_FAR_CENTER", "AUDIENCE_FAR_RIGHT",
                "REAR_LEFT", "REAR_CENTER", "REAR_RIGHT",
            ],
            [target["id"] for target in state["targets"]],
        )
        self.assertTrue(all(target["physical_point_m"] is None for target in state["targets"]))

    def test_normalized_and_physical_transforms_are_inverse_at_edges_and_rear(self):
        cases = (VenuePoint(-1, 1), VenuePoint(1, 0), VenuePoint(-0.35, -1), VenuePoint(0.42, 0.67))
        for normalized in cases:
            physical = venue_normalized_to_meters(normalized, TEST_GEOMETRY, height_m=2.25)
            round_trip = venue_meters_to_normalized(physical, TEST_GEOMETRY)
            self.assertAlmostEqual(normalized.x, round_trip.x)
            self.assertAlmostEqual(normalized.y, round_trip.y)
            self.assertEqual(2.25, physical.z)
        self.assertEqual(-5.0, venue_normalized_to_meters(VenuePoint(-1, 0), TEST_GEOMETRY, height_m=0).x)
        self.assertEqual(12.0, venue_normalized_to_meters(VenuePoint(0, 1), TEST_GEOMETRY, height_m=0).y)
        self.assertEqual(-3.0, venue_normalized_to_meters(VenuePoint(0, -1), TEST_GEOMETRY, height_m=0).y)

    def test_invalid_dimensions_are_unset_and_valid_target_xyz_are_published(self):
        controller = DmxController(MagicMock())
        cleaned = controller._merge_payload({"venue_geometry": {
            "venue_width_m": 0,
            "venue_forward_depth_m": -2,
            "venue_rear_depth_m": "not-a-number",
            "audience_target_height_m": -1,
        }})
        self.assertTrue(all(value is None for value in cleaned["venue_geometry"].values()))
        state = venue_space_state({"venue_geometry": geometry_dict(), "slots": {}, "slot_order": []})
        self.assertEqual("READY", state["venue_geometry"]["status"])
        physical = {target["id"]: target["physical_point_m"] for target in state["targets"]}
        self.assertLess(physical["AUDIENCE_MID_LEFT"]["x"], 0)
        self.assertEqual(0, physical["AUDIENCE_MID_CENTER"]["x"])
        self.assertGreater(physical["AUDIENCE_MID_RIGHT"]["x"], 0)
        self.assertTrue(all(point["z"] == 1.2 for point in physical.values()))

    def test_target_grid_depth_order_aliases_and_shared_height_are_canonical(self):
        self.assertEqual(12, len(VENUE_TARGETS))
        self.assertEqual("AUDIENCE_MID_LEFT", canonical_venue_target_id("AUDIENCE_LEFT"))
        self.assertEqual("AUDIENCE_MID_CENTER", canonical_venue_target_id("audience_center"))
        expected_y = {"NEAR": 0.20, "MID": 0.55, "FAR": 0.90}
        for position in ("LEFT", "CENTER", "RIGHT"):
            near = VENUE_TARGETS[f"AUDIENCE_NEAR_{position}"]
            mid = VENUE_TARGETS[f"AUDIENCE_MID_{position}"]
            far = VENUE_TARGETS[f"AUDIENCE_FAR_{position}"]
            self.assertEqual(near.x, mid.x)
            self.assertEqual(mid.x, far.x)
            self.assertEqual(expected_y["NEAR"], near.y)
            self.assertEqual(expected_y["MID"], mid.y)
            self.assertEqual(expected_y["FAR"], far.y)
            self.assertLess(near.y, mid.y)
            self.assertLess(mid.y, far.y)
            self.assertEqual(-1.00, VENUE_TARGETS[f"REAR_{position}"].y)
        self.assertEqual(VenuePoint(-0.65, 0.55), VENUE_TARGETS["AUDIENCE_MID_LEFT"])
        self.assertEqual(VenuePoint(0.0, 0.55), VENUE_TARGETS["AUDIENCE_MID_CENTER"])
        self.assertEqual(VenuePoint(0.65, 0.55), VENUE_TARGETS["AUDIENCE_MID_RIGHT"])

    def test_target_grid_uses_exact_relative_depth_contract(self):
        geometry = VenueGeometry(6.0, 8.0, 0.5, 1.0)
        state = venue_space_state({"venue_geometry": geometry.as_dict(), "slots": {}, "slot_order": []})
        physical = {target["id"]: target["physical_point_m"] for target in state["targets"]}
        self.assertEqual({"x": 0.0, "y": 1.6, "z": 1.0}, physical["AUDIENCE_NEAR_CENTER"])
        self.assertEqual({"x": 0.0, "y": 4.4, "z": 1.0}, physical["AUDIENCE_MID_CENTER"])
        self.assertEqual({"x": 0.0, "y": 7.2, "z": 1.0}, physical["AUDIENCE_FAR_CENTER"])
        self.assertEqual({"x": 0.0, "y": -0.5, "z": 1.0}, physical["REAR_CENTER"])
        for target_id, expected in {
            "AUDIENCE_NEAR_LEFT": (-1.95, 1.6),
            "AUDIENCE_MID_RIGHT": (1.95, 4.4),
            "AUDIENCE_FAR_LEFT": (-1.95, 7.2),
            "REAR_RIGHT": (1.95, -0.5),
        }.items():
            self.assertAlmostEqual(expected[0], physical[target_id]["x"])
            self.assertAlmostEqual(expected[1], physical[target_id]["y"])
            self.assertEqual(1.0, physical[target_id]["z"])
        self.assertAlmostEqual(2.8, physical["AUDIENCE_MID_CENTER"]["y"] - physical["AUDIENCE_NEAR_CENTER"]["y"])
        self.assertAlmostEqual(2.8, physical["AUDIENCE_FAR_CENTER"]["y"] - physical["AUDIENCE_MID_CENTER"]["y"])

        scaled = VenueGeometry(6.0, 10.0, 2.0, 1.0)
        self.assertEqual(2.0, venue_normalized_to_meters(VENUE_TARGETS["AUDIENCE_NEAR_CENTER"], scaled, height_m=1.0).y)
        self.assertEqual(5.5, venue_normalized_to_meters(VENUE_TARGETS["AUDIENCE_MID_CENTER"], scaled, height_m=1.0).y)
        self.assertEqual(9.0, venue_normalized_to_meters(VENUE_TARGETS["AUDIENCE_FAR_CENTER"], scaled, height_m=1.0).y)
        self.assertEqual(-2.0, venue_normalized_to_meters(VENUE_TARGETS["REAR_CENTER"], scaled, height_m=1.0).y)

    def test_vertical_layers_resolve_all_12_without_creating_new_target_ids(self):
        geometry = VenueGeometry(6.0, 8.0, 0.5, 1.0, 3.0)
        self.assertEqual(12, len(VENUE_TARGETS))
        resolved = []
        for target_id in VENUE_TARGETS:
            normal = resolve_venue_target_point(target_id, geometry, VenueTargetVerticalLayer.NORMAL)
            for layer, z in (("FLOOR", 0.0), ("NORMAL", 1.0), ("CEILING", 3.0)):
                result = resolve_venue_target_point(target_id, geometry, layer)
                self.assertEqual("RESOLVED", result["status"])
                self.assertEqual(layer, result["vertical_layer"])
                self.assertEqual(normal["physical_point_m"].x, result["physical_point_m"].x)
                self.assertEqual(normal["physical_point_m"].y, result["physical_point_m"].y)
                self.assertEqual(z, result["physical_point_m"].z)
                resolved.append((target_id, layer))
        self.assertEqual(36, len(resolved))
        self.assertEqual(
            {"x": 0.0, "y": 4.4, "z": 0.0},
            resolve_venue_target_point("AUDIENCE_MID_CENTER", geometry, "FLOOR")["physical_point_m"].as_dict(),
        )

    def test_vertical_layer_normal_parity_and_ceiling_fail_closed(self):
        normal_geometry = VenueGeometry(6.0, 8.0, 0.5, 1.0)
        ceiling_geometry = VenueGeometry(6.0, 8.0, 0.5, 1.0, 3.0)
        fixture = calibrated_fixture(position=(0, 0))
        for target_id, target in VENUE_TARGETS.items():
            legacy = resolve_venue_target(fixture, target, normal_geometry)
            layered = resolve_venue_target(fixture, target, normal_geometry, vertical_layer="NORMAL")
            self.assertEqual(legacy["target_xyz_m"], layered["target_xyz_m"])
            ceiling = resolve_venue_target(fixture, target, ceiling_geometry, vertical_layer="CEILING")
            self.assertEqual(3.0, ceiling["target_xyz_m"]["z"])
        self.assertEqual((0.0, "FLOOR", None), resolve_venue_target_z(normal_geometry, "FLOOR"))
        self.assertEqual("CEILING_HEIGHT_UNSET", resolve_venue_target_z(normal_geometry, "CEILING")[2])
        self.assertEqual("CEILING_HEIGHT_INVALID", resolve_venue_target_z(VenueGeometry(6, 8, .5, 1, 1), "CEILING")[2])
        self.assertEqual("CEILING_HEIGHT_INVALID", resolve_venue_target_z(VenueGeometry(6, 8, .5, 1, .5), "CEILING")[2])

    def test_ceiling_geometry_is_optional_persistent_and_does_not_rewrite_fixture_position(self):
        with tempfile.TemporaryDirectory() as directory, patch("beatbeam_app.CONFIG_PATH", Path(directory) / "config.json"):
            controller = DmxController(MagicMock())
            slot_id = controller.config["slot_order"][0]
            controller.config = controller._merge_payload({"venue_geometry": geometry_dict(ceiling_height_m=3.27)})
            fixture_position = {"x": -1.75, "y": 2.5, "z": 2.8}
            controller.config["slots"][slot_id]["venue_calibration"] = {
                "version": 4, "position_m": fixture_position, "position": {"x": -0.35, "y": 0.2},
                "mounting_height_m": 2.8, "physical_forward": {"x": 0, "y": 1, "z": 0}, "physical_up": {"x": 0, "y": 0, "z": 1},
            }
            controller.flush_config()
            restarted = DmxController(MagicMock())
            self.assertEqual(3.27, restarted.config["venue_geometry"]["ceiling_height_m"])
            self.assertEqual(fixture_position, restarted.config["slots"][slot_id]["venue_calibration"]["position_m"])

    def test_ceiling_height_does_not_stale_normal_calibration_signatures(self):
        controller = DmxController(MagicMock())
        slot_id = controller.config["slot_order"][0]
        slot = controller.config["slots"][slot_id]
        before_kinematic = __import__("beatbeam_app").kinematic_calibration_signature(slot, geometry_dict())
        before_axis = __import__("beatbeam_app").axis_mapping_v2_validation_signature(slot, geometry_dict())
        with_ceiling = geometry_dict(ceiling_height_m=3.0)
        self.assertEqual(before_kinematic, __import__("beatbeam_app").kinematic_calibration_signature(slot, with_ceiling))
        self.assertEqual(before_axis, __import__("beatbeam_app").axis_mapping_v2_validation_signature(slot, with_ceiling))

    def test_forward_up_derive_right_handed_orthonormal_basis(self):
        basis = fixture_orientation_basis(VenueVector3(0, 4, 0), VenueVector3(0.03, 0, 2))
        self.assertEqual("VALID", basis["status"])
        forward = tuple(basis["forward"].as_dict().values())
        right = tuple(basis["right"].as_dict().values())
        up = tuple(basis["up"].as_dict().values())
        for vector in (forward, right, up):
            self.assertAlmostEqual(1.0, math.sqrt(sum(component * component for component in vector)), places=7)
        for left, other in ((forward, right), (forward, up), (right, up)):
            self.assertAlmostEqual(0.0, sum(a * b for a, b in zip(left, other)), places=7)
        self.assertGreater(right[0], 0)

    def test_zero_and_parallel_orientation_are_invalid_without_nan(self):
        cases = (
            (VenueVector3(0, 0, 0), VenueVector3(0, 0, 1), "forward_zero"),
            (VenueVector3(0, 1, 0), VenueVector3(0, 0, 0), "up_zero"),
            (VenueVector3(0, 1, 0), VenueVector3(0, 2, 0.000000001), "forward_up_parallel"),
        )
        for forward, up, reason in cases:
            result = fixture_orientation_basis(forward, up)
            self.assertEqual("INVALID", result["status"])
            self.assertEqual(reason, result["reason"])
            self.assertNotIn("nan", repr(result).lower())

    def test_heading_rotations_resolve_same_physical_target_deterministically(self):
        target = VenuePoint(0, 0.82)
        fixtures = {
            0: calibrated_fixture(forward=(0, 1, 0), up=(0, 0, 1)),
            90: calibrated_fixture(forward=(1, 0, 0), up=(0, 0, 1)),
            180: calibrated_fixture(forward=(0, -1, 0), up=(0, 0, 1)),
            270: calibrated_fixture(forward=(-1, 0, 0), up=(0, 0, 1)),
        }
        angles = {
            heading: resolve_venue_target(fixture, target, TEST_GEOMETRY)["pan_degrees"]
            for heading, fixture in fixtures.items()
        }
        self.assertAlmostEqual(0, angles[0], places=6)
        self.assertAlmostEqual(-90, angles[90], places=6)
        self.assertAlmostEqual(180, abs(angles[180]), places=6)
        self.assertAlmostEqual(90, angles[270], places=6)
        self.assertEqual(
            resolve_venue_target(fixtures[90], target, TEST_GEOMETRY),
            resolve_venue_target(fixtures[90], target, TEST_GEOMETRY),
        )

    def test_mirrored_and_upside_down_frames_keep_global_semantics(self):
        normal = calibrated_fixture(forward=(0, 1, 0), up=(0, 0, 1))
        upside_down = calibrated_fixture(forward=(0, 1, 0), up=(0, 0, -1))
        target = VenuePoint(0.4, 0.8)
        normal_result = resolve_venue_target(normal, target, TEST_GEOMETRY, target_height_m=3.0)
        inverted_result = resolve_venue_target(upside_down, target, TEST_GEOMETRY, target_height_m=3.0)
        self.assertEqual("RESOLVED", normal_result["status"])
        self.assertEqual("RESOLVED", inverted_result["status"])
        self.assertAlmostEqual(-normal_result["pan_degrees"], inverted_result["pan_degrees"], places=6)
        self.assertAlmostEqual(-normal_result["tilt_degrees"], inverted_result["tilt_degrees"], places=6)

    def test_fixture_position_scale_and_height_change_physical_solution(self):
        target = VenuePoint(0, 0.82)
        left = resolve_venue_target(calibrated_fixture(position=(-0.5, 0)), target, TEST_GEOMETRY)
        center = resolve_venue_target(calibrated_fixture(position=(0, 0)), target, TEST_GEOMETRY)
        right = resolve_venue_target(calibrated_fixture(position=(0.5, 0)), target, TEST_GEOMETRY)
        self.assertGreater(left["pan_degrees"], center["pan_degrees"])
        self.assertGreater(center["pan_degrees"], right["pan_degrees"])
        low = resolve_venue_target(calibrated_fixture(mounting_height_m=1.2), target, TEST_GEOMETRY)
        high = resolve_venue_target(calibrated_fixture(mounting_height_m=4.0), target, TEST_GEOMETRY)
        self.assertGreater(low["tilt_degrees"], high["tilt_degrees"])
        wide = resolve_venue_target(calibrated_fixture(), VenuePoint(0.65, 0.78), VenueGeometry(20, 12, 3, 1.2))
        narrow = resolve_venue_target(calibrated_fixture(), VenuePoint(0.65, 0.78), VenueGeometry(5, 12, 3, 1.2))
        self.assertGreater(abs(wide["pan_degrees"]), abs(narrow["pan_degrees"]))

    def test_left_center_right_fixtures_converge_on_one_finite_world_xyz_target(self):
        target = VENUE_TARGETS["AUDIENCE_MID_CENTER"]
        results = [
            resolve_venue_target(
                calibrated_fixture(position=(x, y), mounting_height_m=height),
                target,
                TEST_GEOMETRY,
            )
            for x, y, height in ((-0.55, -0.15, 3.4), (0.0, 0.05, 2.7), (0.55, 0.2, 1.9))
        ]
        expected_target = venue_normalized_to_meters(target, TEST_GEOMETRY, height_m=TEST_GEOMETRY.audience_target_height_m)
        for result in results:
            self.assertEqual("RESOLVED", result["status"])
            self.assertEqual(expected_target.as_dict(), result["target_xyz_m"])
            fixture = result["fixture_xyz_m"]
            vector = result["target_vector_m"]
            self.assertAlmostEqual(expected_target.x, fixture["x"] + vector["x"])
            self.assertAlmostEqual(expected_target.y, fixture["y"] + vector["y"])
            self.assertAlmostEqual(expected_target.z, fixture["z"] + vector["z"])
        self.assertEqual(3, len({
            (round(item["pan_degrees"], 5), round(item["tilt_degrees"], 5))
            for item in results
        }))

    def test_near_mid_far_rear_and_height_targets_produce_distinct_world_vectors(self):
        fixture = calibrated_fixture(position=(0.18, -0.12), mounting_height_m=3.1)
        target_ids = ("AUDIENCE_NEAR_CENTER", "AUDIENCE_MID_CENTER", "AUDIENCE_FAR_CENTER", "REAR_CENTER")
        results = {
            target_id: resolve_venue_target(fixture, VENUE_TARGETS[target_id], TEST_GEOMETRY)
            for target_id in target_ids
        }
        self.assertTrue(all(item["status"] == "RESOLVED" for item in results.values()))
        self.assertEqual(4, len({
            tuple(round(item["target_vector_m"][axis], 5) for axis in ("x", "y", "z"))
            for item in results.values()
        }))
        self.assertLess(results["REAR_CENTER"]["target_xyz_m"]["y"], 0)
        higher = resolve_venue_target(
            fixture,
            VENUE_TARGETS["AUDIENCE_MID_CENTER"],
            VenueGeometry(10, 12, 3, 2.4),
        )
        self.assertNotEqual(results["AUDIENCE_MID_CENTER"]["target_vector_m"]["z"], higher["target_vector_m"]["z"])

    def test_resolved_diagnostics_use_only_metres_and_include_fine_output(self):
        result = resolve_venue_target(calibrated_fixture(position=(-0.2, 0.1)), VenuePoint(0.3, 0.8), TEST_GEOMETRY)
        self.assertEqual("RESOLVED", result["status"])
        self.assertAlmostEqual(-1.0, result["fixture_xyz_m"]["x"])
        self.assertAlmostEqual(1.2, result["fixture_xyz_m"]["y"])
        self.assertAlmostEqual(2.5, result["fixture_xyz_m"]["z"])
        self.assertAlmostEqual(1.5, result["target_xyz_m"]["x"])
        self.assertAlmostEqual(9.6, result["target_xyz_m"]["y"])
        self.assertAlmostEqual(1.2, result["target_xyz_m"]["z"])
        self.assertAlmostEqual(math.hypot(2.5, 8.4), result["horizontal_distance_m"])
        self.assertAlmostEqual(-1.3, result["vertical_delta_m"])
        self.assertAlmostEqual(math.sqrt(2.5**2 + 8.4**2 + 1.3**2), result["direct_distance_m"])
        self.assertIsInstance(result["predicted_output"]["pan"], int)
        self.assertIsInstance(result["predicted_output"]["pan_fine"], int)
        self.assertEqual(result["predicted_output"]["pan"], result["pan"])

    def test_corrections_are_applied_after_geometry(self):
        base = resolve_venue_target(calibrated_fixture(), VenuePoint(0.2, 0.82), TEST_GEOMETRY)
        corrected = resolve_venue_target(
            calibrated_fixture(pan_correction_degrees=5, tilt_correction_degrees=-3),
            VenuePoint(0.2, 0.82), TEST_GEOMETRY,
        )
        self.assertAlmostEqual(base["pan_degrees"] + 5, corrected["pan_degrees"])
        self.assertAlmostEqual(base["tilt_degrees"] - 3, corrected["tilt_degrees"])

    def test_every_missing_or_invalid_input_has_an_explicit_fail_closed_state(self):
        self.assertEqual("MISSING_FIXTURE_CALIBRATION", resolve_venue_target(
            VenueFixtureCalibration(supports_pan_tilt=True), VenuePoint(0, 0.8), TEST_GEOMETRY
        )["status"])
        self.assertEqual("MISSING_VENUE_SCALE", resolve_venue_target(
            calibrated_fixture(), VenuePoint(0, 0.8), VenueGeometry()
        )["status"])
        self.assertEqual("MISSING_FIXTURE_HEIGHT", resolve_venue_target(
            calibrated_fixture(mounting_height_m=None), VenuePoint(0, 0.8), TEST_GEOMETRY
        )["status"])
        self.assertEqual("MISSING_TARGET_HEIGHT", resolve_venue_target(
            calibrated_fixture(), VenuePoint(0, 0.8), VenueGeometry(10, 12, 3, None)
        )["status"])
        self.assertEqual("INVALID_CALIBRATION", resolve_venue_target(
            calibrated_fixture(up=(0, 2, 0.000000001)), VenuePoint(0, 0.8), TEST_GEOMETRY
        )["status"])
        unreachable = resolve_venue_target(
            calibrated_fixture(forward=(0, -1, 0), pan_min_degrees=-30, pan_max_degrees=30),
            VenuePoint(0, 0.82), TEST_GEOMETRY,
        )
        self.assertEqual("UNREACHABLE", unreachable["status"])
        self.assertIsNone(unreachable["pan"])
        self.assertIsNone(unreachable["predicted_output"])

    def test_rear_scale_is_required_only_for_points_behind_dj(self):
        no_rear = VenueGeometry(10, 12, None, 1.2)
        self.assertEqual("RESOLVED", resolve_venue_target(calibrated_fixture(), VenuePoint(0, 0.8), no_rear)["status"])
        self.assertEqual("MISSING_VENUE_SCALE", resolve_venue_target(
            calibrated_fixture(position=(0, -0.2)), VenuePoint(0, 0.8), no_rear
        )["status"])

    def test_calibration_state_audits_profile_and_separates_height_from_xy(self):
        slot = DmxController.default_slot_config("head")
        slot["venue_calibration"] = {
            "position": {"x": -0.25, "y": 0.1, "z": 0.75},
            "mounting_height_m": 3.2,
            "physical_forward": {"x": 0, "y": 1, "z": 0},
            "physical_up": {"x": 0, "y": 0, "z": 1},
        }
        state = fixture_calibration_state("head", slot, TEST_GEOMETRY)
        self.assertEqual("VALID", state["status"])
        self.assertEqual({"x": -0.25, "y": 0.1}, state["position"])
        self.assertEqual(3.2, state["mounting_height_m"])
        self.assertEqual(540, state["capabilities"]["pan_range_degrees"])
        self.assertEqual(180, state["capabilities"]["tilt_range_degrees"])
        self.assertEqual("RESOLVED", state["audience_center_test"]["status"])

    def test_geometry_and_fixture_height_persist_while_legacy_remains_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory, patch("beatbeam_app.CONFIG_PATH", Path(directory) / "config.json"):
            controller = DmxController(MagicMock())
            slot_id = controller.config["slot_order"][0]
            controller.config = controller._merge_payload({"venue_geometry": geometry_dict()})
            controller.config = controller._merge_payload({"slot_id": slot_id, "slot": {"venue_calibration": {
                "version": 2,
                "position": {"x": -0.3, "y": 0.2},
                "mounting_height_m": 3.4,
                "physical_forward": {"x": 0, "y": 1, "z": 0},
                "physical_up": {"x": 0, "y": 0, "z": 1},
                "pan_correction_degrees": 2.5,
                "tilt_correction_degrees": -1.5,
            }}})
            controller.flush_config()
            restarted = DmxController(MagicMock())
            self.assertEqual(geometry_dict(), restarted.config["venue_geometry"])
            self.assertEqual(3.4, restarted.config["slots"][slot_id]["venue_calibration"]["mounting_height_m"])
            self.assertNotIn("z", restarted.config["slots"][slot_id]["venue_calibration"]["position"])
            payload = json.loads(Path(directory, "config.json").read_text(encoding="utf-8"))
            payload.pop("venue_geometry")
            payload["slots"][slot_id]["venue_calibration"].pop("mounting_height_m")
            Path(directory, "config.json").write_text(json.dumps(payload), encoding="utf-8")
            legacy = DmxController(MagicMock())
            legacy_state = venue_space_state(legacy.config)
            self.assertEqual("MISSING_VENUE_SCALE", legacy_state["venue_geometry"]["status"])
            self.assertIsNone(legacy.config["slots"][slot_id]["venue_calibration"]["mounting_height_m"])

    def test_audience_draft_test_is_authoritative_and_never_mutates_or_sends_dmx(self):
        controller = DmxController(MagicMock())
        controller.config["venue_geometry"] = geometry_dict()
        slot_id = controller.config["slot_order"][0]
        before = json.dumps(controller.config, sort_keys=True)
        result = controller.venue_target_test({"slot_id": slot_id, "venue_calibration": {
            "version": 2,
            "position": {"x": 0, "y": 0},
            "mounting_height_m": 2.8,
            "physical_forward": {"x": 0, "y": 1, "z": 0},
            "physical_up": {"x": 0, "y": 0, "z": 1},
            "pan_correction_degrees": 0,
            "tilt_correction_degrees": 0,
        }})
        self.assertEqual(slot_id, result["slot_id"])
        self.assertEqual("AUDIENCE_MID_CENTER", result["target"])
        self.assertFalse(result["physical_command_sent"])
        self.assertEqual("RESOLVED", result["result"]["status"])
        self.assertEqual(before, json.dumps(controller.config, sort_keys=True))

    def test_preview_target_diagnostic_reuses_resolver_without_dmx_or_connection(self):
        controller = DmxController(MagicMock())
        controller.config = controller.default_config()
        controller.config["venue_geometry"] = geometry_dict()
        slot_id = controller.config["slot_order"][0]
        result = controller.venue_target_test({"slot_id": slot_id, "target": "AUDIENCE_LEFT", "venue_calibration": {
            "version": 2,
            "position": {"x": 0, "y": 0},
            "mounting_height_m": 2.8,
            "physical_forward": {"x": 0, "y": 1, "z": 0},
            "physical_up": {"x": 0, "y": 0, "z": 1},
        }})
        self.assertEqual("AUDIENCE_MID_LEFT", result["target"])
        self.assertEqual("RESOLVED", result["result"]["status"])
        self.assertFalse(result["physical_command_sent"])


class VenueTargetPhysicalTestV1Tests(unittest.TestCase):
    @staticmethod
    def calibrate_slot(controller, slot_id, *, x=0.0, y=0.0):
        controller.config = controller._merge_payload({"slot_id": slot_id, "slot": {"venue_calibration": {
            "version": 4,
            "position_m": {"x": x * 5.0, "y": y * 12.0, "z": 2.8},
            "position": {"x": x, "y": y},
            "mounting_height_m": 2.8,
            "physical_forward": {"x": 0, "y": 1, "z": 0},
            "physical_up": {"x": 0, "y": 0, "z": 1},
        }}})

    def make_ready_controller(self):
        osc = MagicMock()
        osc.snapshot_for_render.return_value = {
            "phrase_current": "verse", "stale": False, "beat_value": 0.0,
        }
        controller = DmxController(osc)
        controller.config = controller.default_config()
        controller.config = controller._merge_payload({"venue_geometry": geometry_dict()})
        slot_id = controller.config["slot_order"][0]
        self.calibrate_slot(controller, slot_id)
        controller.render_active = True
        controller.connected = True
        controller.dmx = MagicMock()
        return controller, slot_id

    def test_hard_gates_never_activate_or_send_a_physical_target(self):
        controller = DmxController(MagicMock())
        controller.config = controller.default_config()
        slot_id = controller.config["slot_order"][0]
        result = controller.activate_venue_target_test({"slot_id": slot_id, "target": "AUDIENCE_CENTER"})
        self.assertFalse(result["accepted"])
        self.assertEqual("CALIBRATION_INCOMPLETE", result["status"])
        self.assertIsNone(controller.venue_target_test_authority)

    def test_physical_move_uses_the_same_selected_vertical_layer_as_preview(self):
        controller, slot_id = self.make_ready_controller()
        controller.config = controller._merge_payload({"venue_geometry": geometry_dict(ceiling_height_m=3.0)})
        result = controller.activate_venue_target_test({
            "target": "AUDIENCE_MID_CENTER", "vertical_layer": "CEILING",
        })
        self.assertTrue(result["accepted"])
        authority = result["authority"]
        self.assertEqual("CEILING", authority["vertical_layer"])
        resolution = next(item["resolution"] for item in authority["result_set"]["results"] if item["slot_id"] == slot_id)
        self.assertEqual(3.0, resolution["target_xyz_m"]["z"])
        self.assertTrue(controller.release_venue_target_test()["accepted"])

        controller, slot_id = self.make_ready_controller()
        controller.connected = False
        controller.dmx = None
        result = controller.activate_venue_target_test({"slot_id": slot_id, "target": "AUDIENCE_CENTER"})
        self.assertFalse(result["accepted"])
        self.assertEqual("DMX_DISCONNECTED", result["status"])
        self.assertIsNone(controller.venue_target_test_authority)

    def test_active_target_overrides_only_final_pan_tilt_and_preserves_fine_bytes(self):
        controller, slot_id = self.make_ready_controller()
        baseline = controller._render_values(time.time())
        result = controller.activate_venue_target_test({"slot_id": slot_id, "target": "AUDIENCE_CENTER"})
        self.assertTrue(result["accepted"])
        active = controller._render_values(time.time())
        authority = controller.venue_target_test_authority
        predicted = authority["participants"][slot_id]["predicted_output"]
        fixture = controller.config["slots"][slot_id]
        mode = find_mode(find_fixture(__import__("beatbeam_app").FIXTURE_LIBRARY, fixture["fixture"]), fixture["mode"])
        movement_channels = {}
        for channel in mode["channels"]:
            absolute = fixture["address"] + channel["offset"] - 1
            if channel["type"] in {"pan", "pan_fine", "tilt", "tilt_fine"}:
                movement_channels[channel["type"]] = absolute
                self.assertEqual(predicted[channel["type"]], active[absolute])
            else:
                self.assertEqual(baseline.get(absolute), active.get(absolute))
        self.assertIn("pan_fine", movement_channels)
        self.assertIn("tilt_fine", movement_channels)
        self.assertEqual("PAN_TILT_ONLY", controller.state()["venue_target_test"]["scope"])

    def test_group_preview_and_physical_activation_share_exact_partial_result_set(self):
        controller, first_slot = self.make_ready_controller()
        second_slot = "head_2"
        controller.config["slots"][second_slot] = json.loads(json.dumps(controller.config["slots"][first_slot]))
        controller.config["slots"][second_slot]["label"] = "Moving Head 2"
        controller.config["slots"][second_slot]["address"] = 60
        controller.config["slot_order"].append(second_slot)
        self.calibrate_slot(controller, second_slot, x=0.35)
        moving_slots = [
            slot_id for slot_id in controller.config["slot_order"]
            if fixture_calibration_state(slot_id, controller.config["slots"][slot_id], TEST_GEOMETRY)["status"] != "UNSUPPORTED"
        ]

        preview = controller.venue_target_test({"target": "AUDIENCE_FAR_RIGHT"})
        self.assertFalse(preview["physical_command_sent"])
        self.assertEqual(len(moving_slots), preview["candidate_count"])
        self.assertEqual(2, preview["targeted_count"])
        classifications = {item["slot_id"]: item["classification"] for item in preview["results"]}
        self.assertEqual("TARGETABLE", classifications[first_slot])
        self.assertEqual("TARGETABLE", classifications[second_slot])
        self.assertTrue(all(slot_id in moving_slots for slot_id in classifications))

        activated = controller.activate_venue_target_test({"target": "AUDIENCE_FAR_RIGHT"})
        self.assertTrue(activated["accepted"])
        self.assertEqual(preview["target"], activated["authority"]["result_set"]["target"])
        self.assertEqual(preview["results"], activated["authority"]["result_set"]["results"])
        self.assertEqual({first_slot, second_slot}, set(activated["authority"]["participating_fixture_ids"]))
        first_output = controller.venue_target_test_authority["participants"][first_slot]["predicted_output"]
        second_output = controller.venue_target_test_authority["participants"][second_slot]["predicted_output"]
        self.assertNotEqual((first_output["pan"], first_output["pan_fine"]), (second_output["pan"], second_output["pan_fine"]))

        active_values = controller._render_values(time.time())
        for slot_id in (first_slot, second_slot):
            slot = controller.config["slots"][slot_id]
            mode = find_mode(find_fixture(__import__("beatbeam_app").FIXTURE_LIBRARY, slot["fixture"]), slot["mode"])
            predicted = controller.venue_target_test_authority["participants"][slot_id]["predicted_output"]
            for channel in mode["channels"]:
                if channel["type"] in {"pan", "pan_fine", "tilt", "tilt_fine"} and predicted[channel["type"]] is not None:
                    absolute = slot["address"] + channel["offset"] - 1
                    self.assertEqual(predicted[channel["type"]], active_values[absolute])

    def test_rear_target_fails_closed_per_fixture_without_rear_depth(self):
        controller, slot_id = self.make_ready_controller()
        controller.config["venue_geometry"]["venue_rear_depth_m"] = None
        preview = controller.venue_target_test({"target": "REAR_CENTER"})
        item = next(item for item in preview["results"] if item["slot_id"] == slot_id)
        self.assertEqual("SKIPPED_MISSING_GEOMETRY", item["classification"])
        self.assertEqual("MISSING_VENUE_SCALE", item["resolver_status"])
        activated = controller.activate_venue_target_test({"target": "REAR_CENTER"})
        self.assertFalse(activated["accepted"])
        self.assertEqual("GEOMETRY_INCOMPLETE", activated["status"])
        self.assertIsNone(controller.venue_target_test_authority)

    def test_partial_result_classifies_invalid_unreachable_and_uncalibrated_independently(self):
        controller, valid_slot = self.make_ready_controller()
        template = controller.config["slots"][valid_slot]
        for index, slot_id in enumerate(("invalid_head", "unreachable_head", "uncalibrated_head"), start=1):
            controller.config["slots"][slot_id] = json.loads(json.dumps(template))
            controller.config["slots"][slot_id]["label"] = slot_id
            controller.config["slots"][slot_id]["address"] = 60 + index * 20
            controller.config["slot_order"].append(slot_id)
        self.calibrate_slot(controller, "invalid_head", x=-0.3)
        controller.config["slots"]["invalid_head"]["venue_calibration"]["physical_up"] = {"x": 0, "y": 2, "z": 0}
        self.calibrate_slot(controller, "unreachable_head", x=0.0, y=0.55)
        controller.config["slots"]["unreachable_head"]["venue_calibration"]["mounting_height_m"] = 0
        controller.config["slots"]["unreachable_head"]["venue_calibration"]["position_m"]["z"] = 0
        controller.config["slots"]["unreachable_head"]["venue_calibration"]["tilt_correction_degrees"] = 15
        controller.config["slots"]["uncalibrated_head"]["venue_calibration"] = None

        result = controller.venue_target_test({"target": "AUDIENCE_MID_CENTER"})
        classifications = {item["slot_id"]: item["classification"] for item in result["results"]}
        self.assertEqual("TARGETABLE", classifications[valid_slot])
        self.assertEqual("SKIPPED_INVALID", classifications["invalid_head"])
        self.assertEqual("SKIPPED_UNREACHABLE", classifications["unreachable_head"])
        self.assertEqual("SKIPPED_UNCALIBRATED", classifications["uncalibrated_head"])
        self.assertEqual(1, result["targeted_count"])
        self.assertEqual(4, result["candidate_count"])
        self.assertNotIn("par", classifications)

        activated = controller.activate_venue_target_test({"target": "AUDIENCE_MID_CENTER"})
        self.assertTrue(activated["accepted"])
        self.assertEqual([valid_slot], activated["authority"]["participating_fixture_ids"])

    def test_release_expiry_and_mutations_clear_authority_without_stale_restore(self):
        controller, slot_id = self.make_ready_controller()
        before = json.dumps(controller.config, sort_keys=True)
        self.assertTrue(controller.activate_venue_target_test({"slot_id": slot_id, "target": "AUDIENCE_LEFT"})["accepted"])
        self.assertTrue(controller.release_venue_target_test()["accepted"])
        self.assertIsNone(controller.venue_target_test_authority)
        self.assertEqual(before, json.dumps(controller.config, sort_keys=True))

        self.assertTrue(controller.activate_venue_target_test({"slot_id": slot_id, "target": "AUDIENCE_LEFT"})["accepted"])
        controller.venue_target_test_authority["expires_at"] = 0
        self.assertEqual("READY", controller.state()["venue_target_test"]["status"])
        self.assertIsNone(controller.venue_target_test_authority)

        self.assertTrue(controller.activate_venue_target_test({"slot_id": slot_id, "target": "AUDIENCE_RIGHT"})["accepted"])
        controller.update_config({"venue_geometry": geometry_dict(venue_width_m=11)})
        self.assertIsNone(controller.venue_target_test_authority)

    def test_active_target_requires_release_before_target_change_and_disconnect_clears(self):
        controller, slot_id = self.make_ready_controller()
        self.assertTrue(controller.activate_venue_target_test({"slot_id": slot_id, "target": "AUDIENCE_CENTER"})["accepted"])
        changed = controller.activate_venue_target_test({"slot_id": slot_id, "target": "AUDIENCE_RIGHT"})
        self.assertFalse(changed["accepted"])
        self.assertEqual("ACTIVE", changed["status"])
        controller.disconnect()
        self.assertIsNone(controller.venue_target_test_authority)


class PhysicalAimKinematicCalibrationV1Tests(unittest.TestCase):
    @staticmethod
    def synthetic_anchors(pan_slope=190.0, pan_offset=31200.0, tilt_slope=-220.0, tilt_offset=28000.0):
        angles = {
            "AUDIENCE_MID_CENTER": (0.0, -12.0),
            "AUDIENCE_FAR_LEFT": (-34.0, -8.0),
            "AUDIENCE_NEAR_CENTER": (1.0, -38.0),
        }
        return {
            target: {
                "desired_pan_degrees": pan,
                "desired_tilt_degrees": tilt,
                "actual_pan_raw": round(pan_slope * pan + pan_offset),
                "actual_tilt_raw": round(tilt_slope * tilt + tilt_offset),
            }
            for target, (pan, tilt) in angles.items()
        }

    def test_known_offset_sign_scale_and_540_branch_are_recovered(self):
        model = fit_kinematic_calibration(
            self.synthetic_anchors(), pan_supports_fine=True, tilt_supports_fine=True
        )
        self.assertEqual("CALIBRATED", model["status"])
        self.assertAlmostEqual(190.0, model["pan"]["slope_raw_per_degree"])
        self.assertAlmostEqual(31200.0, model["pan"]["intercept_raw"])
        self.assertAlmostEqual(-220.0, model["tilt"]["slope_raw_per_degree"])
        self.assertAlmostEqual(28000.0, model["tilt"]["intercept_raw"])
        self.assertEqual("DETERMINISTIC_UNWRAPPED_RAW_DMX", model["pan"]["branch_model"])
        left = model["pan"]["slope_raw_per_degree"] * -40 + model["pan"]["intercept_raw"]
        center = model["pan"]["intercept_raw"]
        right = model["pan"]["slope_raw_per_degree"] * 40 + model["pan"]["intercept_raw"]
        self.assertLess(left, center)
        self.assertLess(center, right)

    def test_inverted_pan_and_tilt_sign_are_evidence_not_profile_assumptions(self):
        model = fit_kinematic_calibration(
            self.synthetic_anchors(pan_slope=-175, tilt_slope=205),
            pan_supports_fine=True,
            tilt_supports_fine=True,
        )
        self.assertEqual("CALIBRATED", model["status"])
        self.assertLess(model["pan"]["slope_raw_per_degree"], 0)
        self.assertGreater(model["tilt"]["slope_raw_per_degree"], 0)

    def test_pan_angles_crossing_minus_plus_180_use_one_unwrapped_branch(self):
        anchors = self.synthetic_anchors()
        desired = {
            "AUDIENCE_MID_CENTER": 178.0,
            "AUDIENCE_FAR_LEFT": -171.0,
            "AUDIENCE_NEAR_CENTER": 176.0,
        }
        for target, angle in desired.items():
            unwrapped = angle + (360.0 if angle < 0 else 0.0)
            anchors[target]["desired_pan_degrees"] = angle
            anchors[target]["actual_pan_raw"] = round(120.0 * unwrapped + 5000.0)
        model = fit_kinematic_calibration(anchors, pan_supports_fine=True, tilt_supports_fine=True)
        self.assertEqual("CALIBRATED", model["status"])
        self.assertAlmostEqual(120.0, model["pan"]["slope_raw_per_degree"], places=4)
        self.assertLess(model["pan"]["input_spread_degrees"], 20.0)

    def test_missing_and_bad_spread_never_claim_calibrated(self):
        anchors = self.synthetic_anchors()
        self.assertEqual("PARTIAL", fit_kinematic_calibration(
            {"AUDIENCE_MID_CENTER": anchors["AUDIENCE_MID_CENTER"]},
            pan_supports_fine=True,
            tilt_supports_fine=True,
        )["status"])
        flat = json.loads(json.dumps(anchors))
        for item in flat.values():
            item["desired_pan_degrees"] = 1.0
        self.assertEqual("INSUFFICIENT_ANCHOR_SPREAD", fit_kinematic_calibration(
            flat, pan_supports_fine=True, tilt_supports_fine=True
        )["status"])

    def test_nonlinear_anchor_residual_fails_affine_v1(self):
        anchors = self.synthetic_anchors()
        anchors["AUDIENCE_NEAR_CENTER"]["actual_tilt_raw"] += 30000
        self.assertEqual("KINEMATIC_MODEL_MISMATCH", fit_kinematic_calibration(
            anchors, pan_supports_fine=True, tilt_supports_fine=True
        )["status"])

    def _save_synthetic_anchor(self, controller, slot_id, target_id, pan_slope=190, pan_offset=31200, tilt_slope=-220, tilt_offset=28000):
        response = controller.activate_aim_calibration({"slot_id": slot_id, "target": target_id})
        self.assertTrue(response["accepted"], response)
        resolution = controller.venue_target_test_authority["participants"][slot_id]
        pan_raw = round(pan_slope * resolution["pan_degrees"] + pan_offset)
        tilt_raw = round(tilt_slope * resolution["tilt_degrees"] + tilt_offset)
        output = resolution["predicted_output"]
        output.update({
            "pan": (pan_raw >> 8) & 0xFF,
            "pan_fine": pan_raw & 0xFF,
            "tilt": (tilt_raw >> 8) & 0xFF,
            "tilt_fine": tilt_raw & 0xFF,
        })
        return controller.save_aim_calibration_anchor()

    def test_selected_fixture_workflow_persists_model_and_does_not_restore_lease(self):
        with tempfile.TemporaryDirectory() as directory, patch("beatbeam_app.CONFIG_PATH", Path(directory) / "config.json"):
            controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
            for target_id in ("AUDIENCE_MID_CENTER", "AUDIENCE_FAR_LEFT", "AUDIENCE_NEAR_CENTER"):
                saved = self._save_synthetic_anchor(controller, slot_id, target_id)
            self.assertEqual("CALIBRATED", saved["status"])
            self.assertIsNone(controller.venue_target_test_authority)
            controller.flush_config()
            restarted = DmxController(MagicMock())
            aim = kinematic_calibration_state(
                slot_id,
                restarted.config["slots"][slot_id],
                restarted.config["venue_geometry"],
            )
            self.assertEqual("CALIBRATED", aim["status"])
            self.assertIsNone(restarted.venue_target_test_authority)

    def test_calibrated_target_renderer_projection_share_inverse_model(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        for target_id in ("AUDIENCE_MID_CENTER", "AUDIENCE_FAR_LEFT", "AUDIENCE_NEAR_CENTER"):
            self._save_synthetic_anchor(controller, slot_id, target_id)
        result = controller.venue_target_test({"target": "AUDIENCE_FAR_RIGHT"})
        resolution = next(item for item in result["results"] if item["slot_id"] == slot_id)["resolution"]
        self.assertEqual("KINEMATIC_CALIBRATION_V1", resolution["mapping_source"])
        self.assertTrue(controller.activate_venue_target_test({"target": "AUDIENCE_FAR_RIGHT"})["accepted"])
        final_values = controller._render_values(time.time())
        projection = rendered_motion_projection(controller.config, final_values)[slot_id]
        self.assertEqual("KINEMATIC_CALIBRATION_V1", projection["mapping_source"])
        self.assertAlmostEqual(resolution["pan_degrees"], projection["physical_pan_degrees"], places=2)
        self.assertAlmostEqual(resolution["tilt_degrees"], projection["physical_tilt_degrees"], places=2)

    def test_geometry_change_marks_anchors_stale_and_releases_movement(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        for target_id in ("AUDIENCE_MID_CENTER", "AUDIENCE_FAR_LEFT", "AUDIENCE_NEAR_CENTER"):
            self._save_synthetic_anchor(controller, slot_id, target_id)
        self.assertTrue(controller.activate_aim_calibration({"slot_id": slot_id, "target": "AUDIENCE_FAR_RIGHT"})["accepted"])
        controller.update_config({"venue_geometry": geometry_dict(venue_width_m=11.0)})
        self.assertIsNone(controller.venue_target_test_authority)
        aim = kinematic_calibration_state(slot_id, controller.config["slots"][slot_id], controller.config["venue_geometry"])
        self.assertEqual("STALE", aim["status"])

    def test_calibration_authority_changes_only_selected_pan_tilt(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        second = "head_2"
        controller.config["slots"][second] = json.loads(json.dumps(controller.config["slots"][slot_id]))
        controller.config["slots"][second]["address"] = 60
        controller.config["slots"][second]["label"] = "Head 2"
        controller.config["slot_order"].append(second)
        baseline = controller._render_values(time.time())
        self.assertTrue(controller.activate_aim_calibration({"slot_id": slot_id, "target": "AUDIENCE_MID_CENTER"})["accepted"])
        self.assertEqual([slot_id], controller.state()["venue_target_test"]["participating_fixture_ids"])
        controller.nudge_aim_calibration({"axis": "pan", "direction": "positive", "granularity": "COARSE"})
        active = controller._render_values(time.time())
        for current_slot in (slot_id, second):
            slot = controller.config["slots"][current_slot]
            mode = find_mode(find_fixture(__import__("beatbeam_app").FIXTURE_LIBRARY, slot["fixture"]), slot["mode"])
            for channel in mode["channels"]:
                absolute = slot["address"] + channel["offset"] - 1
                if current_slot == slot_id and channel["type"] in {"pan", "pan_fine", "tilt", "tilt_fine"}:
                    continue
                self.assertEqual(baseline.get(absolute), active.get(absolute))


class RenderedMotionProjectionV1Tests(unittest.TestCase):
    @staticmethod
    def _movement_channels(controller, slot_id):
        slot = controller.config["slots"][slot_id]
        mode = find_mode(find_fixture(__import__("beatbeam_app").FIXTURE_LIBRARY, slot["fixture"]), slot["mode"])
        return {
            channel["type"]: slot["address"] + channel["offset"] - 1
            for channel in mode["channels"]
            if channel["type"] in {"pan", "pan_fine", "tilt", "tilt_fine"}
        }

    @staticmethod
    def _normalized(vector):
        length = math.sqrt(sum(value * value for value in vector))
        return tuple(value / length for value in vector)

    def _four_head_controller(self):
        controller, first = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        template = controller.config["slots"][first]
        controller.config["slots"] = {}
        controller.config["slot_order"] = []
        configurations = {
            "head": {"x": -0.36, "forward": (0, -1, 0), "up": (0, 0, -1), "pan_invert": True},
            "moving_head": {"x": -0.12, "forward": (0, 1, 0), "up": (0, 0, -1), "pan_invert": False},
            "bee_eye_head": {"x": 0.12, "forward": (0, 1, 0), "up": (0, 0, -1), "pan_invert": False},
            "bee_eye_head_2": {"x": 0.36, "forward": (0, 1, 0), "up": (0, 0, -1), "pan_invert": False},
        }
        for index, (slot_id, calibration) in enumerate(configurations.items()):
            slot = json.loads(json.dumps(template))
            slot["label"] = slot_id
            slot["address"] = 1 + index * 20
            slot["pan_invert"] = calibration["pan_invert"]
            slot["tilt_invert"] = False
            slot["venue_calibration"] = {
                "version": 2,
                "position": {"x": calibration["x"], "y": 0.0},
                "mounting_height_m": 2.8,
                "physical_forward": dict(zip(("x", "y", "z"), calibration["forward"])),
                "physical_up": dict(zip(("x", "y", "z"), calibration["up"])),
            }
            controller.config["slots"][slot_id] = slot
            controller.config["slot_order"].append(slot_id)
        return controller

    def test_final_projection_uses_post_authority_frame_not_stale_slot_preview(self):
        controller = self._four_head_controller()
        controller.current_slot_previews = {
            slot_id: {"pan": 0, "tilt": 0, "logical_pan_degrees": -270, "logical_tilt_degrees": -90}
            for slot_id in controller.config["slot_order"]
        }
        self.assertTrue(controller.activate_venue_target_test({"target": "AUDIENCE_FAR_RIGHT"})["accepted"])
        controller.current_final_values = controller._render_values(time.time())
        state = controller.state()
        projection = state["rendered_motion"]
        self.assertEqual(0, state["slot_previews"]["head"]["pan"])
        self.assertEqual("AVAILABLE", projection["head"]["status"])
        self.assertEqual(
            controller.venue_target_test_authority["participants"]["head"]["predicted_output"]["pan"],
            projection["head"]["pan"],
        )
        self.assertNotEqual(projection["head"]["pan"], state["slot_previews"]["head"]["pan"])

    def test_mixed_forward_orientations_resolve_same_global_left_and_right_direction(self):
        for target_id in ("AUDIENCE_FAR_LEFT", "AUDIENCE_FAR_RIGHT"):
            controller = self._four_head_controller()
            self.assertTrue(controller.activate_venue_target_test({"target": target_id})["accepted"])
            final_values = controller._render_values(time.time())
            projection = rendered_motion_projection(controller.config, final_values)
            target = VENUE_TARGETS[target_id]
            for slot_id in ("head", "moving_head", "bee_eye_head", "bee_eye_head_2"):
                item = projection[slot_id]
                self.assertEqual("AVAILABLE", item["status"])
                position = item["fixture_position_m"]
                target_m = venue_normalized_to_meters(target, TEST_GEOMETRY, height_m=TEST_GEOMETRY.audience_target_height_m)
                expected = self._normalized((
                    target_m.x - position["x"], target_m.y - position["y"], target_m.z - position["z"],
                ))
                actual = item["world_direction"]
                self.assertGreater(sum(expected[index] * actual[axis] for index, axis in enumerate(("x", "y", "z"))), 0.9999)
            self.assertNotEqual(projection["head"]["pan"], projection["moving_head"]["pan"])

    def test_fine_channel_changes_authoritative_angle_and_direction(self):
        controller = self._four_head_controller()
        slot_id = "head"
        channels = self._movement_channels(controller, slot_id)
        first = {channels["pan"]: 128, channels["pan_fine"]: 0, channels["tilt"]: 128, channels["tilt_fine"]: 0}
        second = {**first, channels["pan_fine"]: 255, channels["tilt_fine"]: 255}
        first_projection = rendered_motion_projection(controller.config, first)[slot_id]
        second_projection = rendered_motion_projection(controller.config, second)[slot_id]
        self.assertEqual(128, first_projection["pan"])
        self.assertEqual(0, first_projection["pan_fine"])
        self.assertEqual(255, second_projection["pan_fine"])
        self.assertNotEqual(first_projection["physical_pan_degrees"], second_projection["physical_pan_degrees"])
        self.assertNotEqual(first_projection["world_direction"], second_projection["world_direction"])

    def test_release_uses_then_current_final_frame_without_stale_target_projection(self):
        controller = self._four_head_controller()
        self.assertTrue(controller.activate_venue_target_test({"target": "AUDIENCE_FAR_LEFT"})["accepted"])
        target_frame = controller._render_values(time.time())
        target_projection = rendered_motion_projection(controller.config, target_frame)["head"]
        controller.release_venue_target_test()
        channels = self._movement_channels(controller, "head")
        underlying_frame = {**target_frame, channels["pan"]: 210, channels["pan_fine"]: 19, channels["tilt"]: 70, channels["tilt_fine"]: 4}
        released_projection = rendered_motion_projection(controller.config, underlying_frame)["head"]
        self.assertNotEqual(target_projection["world_direction"], released_projection["world_direction"])
        self.assertEqual(210, released_projection["pan"])
        self.assertEqual(19, released_projection["pan_fine"])

    def test_final_motion_remains_observable_without_dmx_connection(self):
        controller = self._four_head_controller()
        controller.connected = False
        controller.dmx = None
        channels = self._movement_channels(controller, "moving_head")
        controller.current_final_values = {channels["pan"]: 120, channels["pan_fine"]: 1, channels["tilt"]: 130, channels["tilt_fine"]: 2}
        motion = controller.state()["rendered_motion"]["moving_head"]
        self.assertTrue(motion["available"])
        self.assertEqual("AVAILABLE", motion["status"])
        self.assertIsNotNone(motion["world_direction"])


class PhysicalAxisMappingV2Tests(unittest.TestCase):
    @staticmethod
    def samples(pan_values=None, tilt_values=None, maximum=65535):
        pan_values = pan_values or (270, 0, 90, 180, 270, 0, 90)
        tilt_values = tilt_values or (0, 45, 90, 135, 180)
        pan_raw = [round(maximum * index / 6) for index in range(7)]
        tilt_raw = [round(maximum * index / 4) for index in range(5)]
        pan = {
            str(index): {"index": index, "raw": raw, "measured_azimuth_degrees": value}
            for index, (raw, value) in enumerate(zip(pan_raw, pan_values))
        }
        tilt = {
            str(index): {"index": index, "raw": raw, "measured_tilt_plane_degrees": value}
            for index, (raw, value) in enumerate(zip(tilt_raw, tilt_values))
        }
        return pan, tilt

    def test_normal_pan_forward_inverse_and_540_unwrap(self):
        pan, tilt = self.samples()
        model = fit_axis_mapping_v2(pan, tilt)
        self.assertEqual("CALIBRATED_CANDIDATE", model["status"])
        self.assertEqual("INCREASING", model["pan"]["direction"])
        self.assertAlmostEqual(540.0, model["pan"]["coverage_degrees"])
        self.assertAlmostEqual(630.0, axis_mapping_v2_forward(round(65535 * 4 / 6), model["pan"]), places=1)
        solution = axis_mapping_v2_inverse_pan(270.0, model["pan"], current_raw=60000)
        self.assertEqual(2, len(solution["candidates"]))
        self.assertGreater(solution["chosen_raw"], 40000)

    def test_reversed_pan_and_tilt_are_learned_without_invert_flags(self):
        pan, tilt = self.samples(
            pan_values=(90, 0, 270, 180, 90, 0, 270),
            tilt_values=(0, -45, -90, -135, 180),
        )
        model = fit_axis_mapping_v2(pan, tilt)
        self.assertEqual("CALIBRATED_CANDIDATE", model["status"])
        self.assertEqual("DECREASING", model["pan"]["direction"])
        self.assertEqual("DECREASING", model["tilt"]["direction"])
        self.assertAlmostEqual(0.0, axis_mapping_v2_forward(round(65535 / 6), model["pan"]), places=1)
        self.assertAlmostEqual(round(65535 * 0.75), axis_mapping_v2_inverse_tilt(-135, model["tilt"]), delta=1)

    def test_offset_and_mild_nonlinearity_remain_piecewise_evidence(self):
        pan, tilt = self.samples(
            pan_values=(15, 83, 176, 281, 369, 458, 550),
            tilt_values=(4, 51, 87, 132, 176),
        )
        model = fit_axis_mapping_v2(pan, tilt)
        self.assertEqual("PIECEWISE_LINEAR_PAN_DIRECTED_TILT_PLANE_V2", model["model"])
        raw = round(65535 * 2.5 / 6)
        self.assertAlmostEqual((176 + 281) / 2, axis_mapping_v2_forward(raw, model["pan"]), delta=.05)

    def test_bad_or_incomplete_sequences_fail_closed(self):
        pan, tilt = self.samples()
        self.assertEqual("TILT_MAPPING_VALID", fit_axis_mapping_v2(dict(list(pan.items())[:6]), tilt)["status"])
        self.assertEqual("TILT_PARTIAL", fit_axis_mapping_v2(pan, dict(list(tilt.items())[:4]))["status"])
        bad_pan, _ = self.samples(pan_values=(270, 0, 90, 20, 270, 0, 90))
        self.assertEqual("INVALID_SAMPLE_SEQUENCE", fit_axis_mapping_v2(bad_pan, tilt)["status"])
        _, bad_tilt = self.samples(tilt_values=(0, 45, 20, 135, 180))
        self.assertEqual("INVALID_TILT_SAMPLE_SEQUENCE", fit_axis_mapping_v2(pan, bad_tilt)["status"])

    def test_directed_tilt_cardinals_and_two_horizons_remain_distinct(self):
        world_direction = __import__("beatbeam_app").axis_mapping_v2_world_direction
        front = world_direction(0, 0)
        up = world_direction(0, 90)
        back = world_direction(0, 180)
        down = world_direction(0, -90)
        self.assertAlmostEqual(1.0, front.y, places=6)
        self.assertAlmostEqual(1.0, up.z, places=6)
        self.assertAlmostEqual(-1.0, back.y, places=6)
        self.assertAlmostEqual(-1.0, down.z, places=6)
        self.assertAlmostEqual(0.0, front.z, places=6)
        self.assertAlmostEqual(0.0, back.z, places=6)
        self.assertAlmostEqual(-1.0, front.x * back.x + front.y * back.y + front.z * back.z, places=6)

    def test_directed_tilt_forward_and_inverse_preserve_front_up_back(self):
        _, tilt = self.samples()
        model = fit_axis_mapping_v2({}, tilt)["tilt"]
        self.assertAlmostEqual(0.0, axis_mapping_v2_forward(0, model), places=6)
        self.assertAlmostEqual(90.0, axis_mapping_v2_forward(round(65535 / 2), model), delta=.01)
        self.assertAlmostEqual(180.0, axis_mapping_v2_forward(65535, model), places=6)
        front_raw = axis_mapping_v2_inverse_tilt(0, model)
        back_raw = axis_mapping_v2_inverse_tilt(180, model)
        self.assertAlmostEqual(0.0, front_raw, places=6)
        self.assertAlmostEqual(65535.0, back_raw, places=6)
        self.assertNotEqual(front_raw, back_raw)

    def test_reversed_tilt_path_unwraps_front_down_back(self):
        _, tilt = self.samples(tilt_values=(0, -45, -90, -135, 180))
        model = fit_axis_mapping_v2({}, tilt)
        self.assertEqual("TILT_MAPPING_VALID", model["status"])
        self.assertEqual("DECREASING", model["tilt"]["direction"])
        self.assertEqual([0, -45, -90, -135, -180], [point["physical_degrees"] for point in model["tilt"]["points"]])
        self.assertAlmostEqual(65535, axis_mapping_v2_inverse_tilt(180, model["tilt"]), delta=1)

    def test_rotated_pan_makes_tilt_front_right_and_back_left(self):
        world_direction = __import__("beatbeam_app").axis_mapping_v2_world_direction
        front = world_direction(90, 0)
        back = world_direction(90, 180)
        self.assertGreater(front.x, .999)
        self.assertLess(back.x, -.999)

    def test_venue_target_inverse_can_choose_front_or_equivalent_back_solution(self):
        pan, tilt = self.samples(tilt_values=(0, -45, -90, -135, 180))
        model = fit_axis_mapping_v2(pan, tilt)
        front_calibration = calibrated_fixture(
            axis_mapping_v2=model,
            current_pan_raw=round(65535 / 6),
            current_tilt_raw=0,
        )
        back_calibration = calibrated_fixture(
            axis_mapping_v2=model,
            current_pan_raw=round(65535 / 2),
            current_tilt_raw=65535,
        )
        target = VenuePoint(0, .8)
        front = resolve_venue_target(front_calibration, target, TEST_GEOMETRY)
        back = resolve_venue_target(back_calibration, target, TEST_GEOMETRY)
        self.assertEqual("RESOLVED", front["status"])
        self.assertEqual("RESOLVED", back["status"])
        self.assertEqual("FRONT_SIDE", front["chosen_mechanical_branch"])
        self.assertEqual("BACK_SIDE", back["chosen_mechanical_branch"])
        self.assertNotEqual(front["chosen_tilt_raw"], back["chosen_tilt_raw"])

    def test_legacy_elevation_only_tilt_samples_require_review_and_are_preserved(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        slot = controller.config["slots"][slot_id]
        _, directed = self.samples()
        legacy = {}
        for index, (key, sample) in enumerate(directed.items()):
            legacy[key] = {
                field: value for field, value in sample.items()
                if field != "measured_tilt_plane_degrees"
            }
            legacy[key]["measured_elevation_degrees"] = -90 + index * 45
        signature = __import__("beatbeam_app").axis_mapping_v2_signature(slot)
        for sample in legacy.values():
            sample["profile_signature"] = signature
        slot["axis_mapping_v2"] = {
            "version": 2,
            "profile_signature": signature,
            "session_revision": 1,
            "pan_samples": {},
            "tilt_samples": legacy,
        }
        controller.config = controller._clean_full_config(controller.config)
        state = axis_mapping_v2_state(slot_id, controller.config["slots"][slot_id], controller.config["venue_geometry"])
        self.assertEqual("LEGACY_TILT_DIRECTION_REVIEW_REQUIRED", state["status"])
        self.assertEqual(0, state["tilt_sample_count"])
        self.assertEqual(5, len(state["legacy_tilt_samples"]))
        self.assertTrue(state["legacy_tilt_direction_review_required"])

    @staticmethod
    def persisted_mapping(controller, slot_id, *, active=False, validations=True):
        slot = controller.config["slots"][slot_id]
        fixture = find_fixture(__import__("beatbeam_app").FIXTURE_LIBRARY, slot["fixture"])
        mode = find_mode(fixture, slot["mode"])
        capabilities = __import__("beatbeam_app").mode_capabilities(mode)
        pan_fine = bool(capabilities.get("pan_fine") and slot.get("use_fine_pan_tilt", True))
        tilt_fine = bool(capabilities.get("tilt_fine") and slot.get("use_fine_pan_tilt", True))
        pan, tilt = PhysicalAxisMappingV2Tests.samples(
            tilt_values=(0, -45, -90, -135, 180),
            maximum=65535 if pan_fine else 255,
        )
        if not tilt_fine:
            tilt_raw = [round(255 * index / 4) for index in range(5)]
            for index, raw in enumerate(tilt_raw):
                tilt[str(index)]["raw"] = raw
        signature = __import__("beatbeam_app").axis_mapping_v2_signature(slot)
        for sample in (*pan.values(), *tilt.values()):
            sample["profile_signature"] = signature
            sample["session_revision"] = 1
        tilt_reference_pan = round((65535 if pan_fine else 255) / 2)
        pan_reference_tilt = round((65535 if tilt_fine else 255) / 2)
        for sample in pan.values():
            sample["reference_raw"] = pan_reference_tilt
        for sample in tilt.values():
            sample["reference_raw"] = tilt_reference_pan
        model = fit_axis_mapping_v2(pan, tilt)
        evidence = {}
        if validations:
            geometry_signature = __import__("beatbeam_app").axis_mapping_v2_validation_signature(slot, controller.config["venue_geometry"])
            evidence = {
                target: {"target": target, "result": "PASS", "venue_geometry_signature": geometry_signature}
                for target in __import__("beatbeam_app").AXIS_MAPPING_V2_VALIDATION_TARGETS
            }
        slot["axis_mapping_v2"] = {
            "version": 2, "profile_signature": signature, "session_revision": 1,
            "pan_samples": pan, "tilt_samples": tilt, "model": model,
            "tilt_sweep_reference_pan_raw": tilt_reference_pan,
            "pan_sweep_reference_tilt_plane_degrees": 0.0,
            "pan_sweep_reference_tilt_raw": pan_reference_tilt,
            "pan_samples_review_required": False,
            "validations": evidence, "active": active,
        }
        controller.config = controller._clean_full_config(controller.config)

    def test_candidate_is_not_normal_authority_activation_disables_legacy_aim(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        self.persisted_mapping(controller, slot_id, active=False, validations=False)
        candidate = axis_mapping_v2_state(slot_id, controller.config["slots"][slot_id], controller.config["venue_geometry"])
        self.assertEqual("CALIBRATED_CANDIDATE", candidate["status"])
        normal = controller._venue_target_result_set_locked("AUDIENCE_NEAR_CENTER")["results"][0]["resolution"]
        self.assertNotEqual("AXIS_MAPPING_V2", normal["mapping_source"])
        self.persisted_mapping(controller, slot_id, active=False, validations=True)
        self.assertEqual("VALIDATED", axis_mapping_v2_state(slot_id, controller.config["slots"][slot_id], controller.config["venue_geometry"])["status"])
        self.assertTrue(controller.activate_axis_mapping_v2({"slot_id": slot_id})["accepted"])
        active = axis_mapping_v2_state(slot_id, controller.config["slots"][slot_id], controller.config["venue_geometry"])
        self.assertEqual("ACTIVE", active["status"])
        self.assertEqual("LEGACY_INACTIVE", active["legacy_physical_aim_status"])
        normal = controller._venue_target_result_set_locked("AUDIENCE_NEAR_CENTER")["results"][0]["resolution"]
        self.assertEqual("AXIS_MAPPING_V2", normal["mapping_source"])

    def test_v2_rendered_motion_uses_final_raw_without_forward_or_invert_double_transform(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        self.persisted_mapping(controller, slot_id, active=True, validations=True)
        slot = controller.config["slots"][slot_id]
        slot["pan_invert"] = True
        slot["tilt_invert"] = True
        slot["venue_calibration"]["physical_forward"] = {"x": -1, "y": 0, "z": 0}
        # Refresh the explicit remount signature while keeping measured evidence.
        mapping = slot["axis_mapping_v2"]
        signature = __import__("beatbeam_app").axis_mapping_v2_signature(slot)
        mapping["profile_signature"] = signature
        for sample in (*mapping["pan_samples"].values(), *mapping["tilt_samples"].values()):
            sample["profile_signature"] = signature
        controller.config = controller._clean_full_config(controller.config)
        mode = find_mode(find_fixture(__import__("beatbeam_app").FIXTURE_LIBRARY, slot["fixture"]), slot["mode"])
        channels = {channel["type"]: slot["address"] + channel["offset"] - 1 for channel in mode["channels"]}
        pan_raw, tilt_raw = round(65535 * 2 / 6), round(65535 * .75)
        frame = {
            channels["pan"]: pan_raw >> 8, channels["pan_fine"]: pan_raw & 255,
            channels["tilt"]: tilt_raw >> 8, channels["tilt_fine"]: tilt_raw & 255,
        }
        projection = rendered_motion_projection(controller.config, frame)[slot_id]
        self.assertEqual("AXIS_MAPPING_V2", projection["mapping_source"])
        self.assertAlmostEqual(450.0, projection["physical_pan_degrees"], places=1)
        self.assertAlmostEqual(-135.0, projection["physical_tilt_degrees"], places=1)
        self.assertLess(projection["world_direction"]["x"], -.7)

    def test_geometry_change_preserves_axis_samples_but_stales_validation(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        self.persisted_mapping(controller, slot_id, active=True, validations=True)
        controller.config["venue_geometry"]["venue_width_m"] += 1
        state = axis_mapping_v2_state(slot_id, controller.config["slots"][slot_id], controller.config["venue_geometry"])
        self.assertEqual("CALIBRATED_CANDIDATE", state["status"])
        self.assertTrue(state["validation_stale"])
        self.assertEqual(7, state["pan_sample_count"])
        self.assertEqual(5, state["tilt_sample_count"])

    def test_sample_lease_changes_only_selected_fixture_pan_tilt(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        self.persisted_mapping(controller, slot_id, validations=False)
        baseline = controller._render_values(time.time())
        moved = controller.move_axis_mapping_v2_sample({"slot_id": slot_id, "axis": "PAN", "index": 0})
        self.assertTrue(moved["accepted"], moved)
        active = controller._render_values(time.time())
        slot = controller.config["slots"][slot_id]
        mode = find_mode(find_fixture(__import__("beatbeam_app").FIXTURE_LIBRARY, slot["fixture"]), slot["mode"])
        movement = {"pan", "pan_fine", "tilt", "tilt_fine"}
        for channel in mode["channels"]:
            absolute = slot["address"] + channel["offset"] - 1
            if channel["type"] not in movement:
                self.assertEqual(baseline.get(absolute), active.get(absolute))

    def test_branch_selection_is_stable_near_current_authoritative_raw(self):
        pan, tilt = self.samples()
        model = fit_axis_mapping_v2(pan, tilt)
        first = axis_mapping_v2_inverse_pan(359.0, model["pan"], current_raw=55000)
        second = axis_mapping_v2_inverse_pan(1.0, model["pan"], current_raw=first["chosen_raw"])
        self.assertLess(abs(second["chosen_raw"] - first["chosen_raw"]), 1000)
        self.assertGreater(second["chosen_raw"], 40000)

    def test_eight_bit_axis_uses_exact_coarse_samples(self):
        pan, tilt = self.samples(maximum=255)
        model = fit_axis_mapping_v2(pan, tilt)
        self.assertEqual("CALIBRATED_CANDIDATE", model["status"])
        self.assertEqual([0, 42, 85, 128, 170, 212, 255], [point["raw"] for point in model["pan"]["points"]])
        self.assertAlmostEqual(0, axis_mapping_v2_inverse_tilt(0, model["tilt"]), delta=1)

    def test_guided_sample_api_persists_complete_candidate_and_restart_has_no_lease(self):
        with tempfile.TemporaryDirectory() as directory, patch("beatbeam_app.CONFIG_PATH", Path(directory) / "config.json"):
            controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
            blocked = controller.begin_axis_mapping_v2({"slot_id": slot_id, "axis": "PAN"})
            self.assertFalse(blocked["accepted"])
            self.assertIn("CALIBRATE TILT FIRST", blocked["reason"])
            moved_reference = controller.nudge_axis_mapping_v2_tilt_reference({"slot_id": slot_id, "direction": "RIGHT", "granularity": "FINE"})
            self.assertTrue(moved_reference["accepted"], moved_reference)
            self.assertTrue(controller.lock_axis_mapping_v2_tilt_reference({})["accepted"])
            tilt_values = (0, 45, 90, 135, 180)
            for index, measured in enumerate(tilt_values):
                response = controller.move_axis_mapping_v2_sample({"slot_id": slot_id, "axis": "TILT", "index": index})
                self.assertTrue(response["accepted"], response)
                saved = controller.save_axis_mapping_v2_sample({"axis": "TILT", "measured_degrees": measured})
                self.assertTrue(saved["accepted"], saved)
            selected_reference = controller.set_axis_mapping_v2_pan_reference({"slot_id": slot_id, "tilt_plane_degrees": 0})
            self.assertTrue(selected_reference["accepted"], selected_reference)
            pan_values = (270, 0, 90, 180, 270, 0, 90)
            for index, measured in enumerate(pan_values):
                response = controller.move_axis_mapping_v2_sample({"slot_id": slot_id, "axis": "PAN", "index": index})
                self.assertTrue(response["accepted"], response)
                saved = controller.save_axis_mapping_v2_sample({"axis": "PAN", "measured_degrees": measured})
                self.assertTrue(saved["accepted"], saved)
                if index < 6:
                    self.assertEqual(index + 1, controller.venue_target_test_authority["sample_index"])
                    self.assertEqual("PAN", controller.venue_target_test_authority["axis"])
                else:
                    self.assertIsNone(controller.venue_target_test_authority)
            self.assertEqual("CALIBRATED_CANDIDATE", saved["status"])
            controller.flush_config()
            restarted = DmxController(MagicMock())
            self.assertEqual("CALIBRATED_CANDIDATE", axis_mapping_v2_state(slot_id, restarted.config["slots"][slot_id], restarted.config["venue_geometry"])["status"])
            self.assertIsNone(restarted.venue_target_test_authority)

    def test_progressive_wizard_auto_advances_tilt_front_reference_pan_and_validation(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        self.assertTrue(controller.nudge_axis_mapping_v2_tilt_reference({
            "slot_id": slot_id, "axis": "PAN", "direction": "RIGHT", "granularity": "FINE",
        })["accepted"])
        locked = controller.lock_axis_mapping_v2_tilt_reference({})
        self.assertTrue(locked["accepted"], locked)
        self.assertEqual(("TILT", 0), (
            controller.venue_target_test_authority["axis"],
            controller.venue_target_test_authority["sample_index"],
        ))

        for index, measured in enumerate((0, 45, 90, 135, 180)):
            saved = controller.save_axis_mapping_v2_sample({"axis": "TILT", "measured_degrees": measured})
            self.assertTrue(saved["accepted"], saved)
            if index < 4:
                self.assertEqual(("TILT", index + 1), (
                    controller.venue_target_test_authority["axis"],
                    controller.venue_target_test_authority["sample_index"],
                ))
            else:
                self.assertEqual(("PAN", 0), (
                    controller.venue_target_test_authority["axis"],
                    controller.venue_target_test_authority["sample_index"],
                ))
                state = saved["axis_mapping_v2"]
                self.assertEqual("PAN", state["workflow_phase"])
                self.assertEqual(0, state["workflow_sample_index"])
                self.assertEqual(0.0, state["pan_sweep_reference_tilt_plane_degrees"])
                self.assertEqual(0, state["pan_sweep_reference_tilt_raw"])

        for index, measured in enumerate((270, 0, 90, 180, 270, 0, 90)):
            saved = controller.save_axis_mapping_v2_sample({"axis": "PAN", "measured_degrees": measured})
            self.assertTrue(saved["accepted"], saved)
            if index < 6:
                self.assertEqual(("PAN", index + 1), (
                    controller.venue_target_test_authority["axis"],
                    controller.venue_target_test_authority["sample_index"],
                ))
            else:
                self.assertIsNone(controller.venue_target_test_authority)
                self.assertEqual("VALIDATION", saved["axis_mapping_v2"]["workflow_phase"])
                self.assertEqual("VALIDATION_READY", saved["axis_mapping_v2"]["workflow_move_status"])
                self.assertEqual("CALIBRATED_CANDIDATE", saved["status"])
                self.assertFalse(saved["axis_mapping_v2"]["active"])

    def test_progressive_wizard_move_failure_preserves_saved_sample_once_and_is_retry_safe(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        self.assertTrue(controller.nudge_axis_mapping_v2_tilt_reference({
            "slot_id": slot_id, "axis": "PAN", "direction": "RIGHT", "granularity": "FINE",
        })["accepted"])
        self.assertTrue(controller.lock_axis_mapping_v2_tilt_reference({})["accepted"])
        original_activate = controller._activate_axis_mapping_v2_sample_locked

        def fail_second(slot, axis, index):
            if axis == "TILT" and index == 1:
                return {"accepted": False, "status": "NEXT_MOVE_FAILED", "reason": "synthetic move failure"}
            return original_activate(slot, axis, index)

        with patch.object(controller, "_activate_axis_mapping_v2_sample_locked", side_effect=fail_second):
            saved = controller.save_axis_mapping_v2_sample({"axis": "TILT", "measured_degrees": 0})
        self.assertTrue(saved["accepted"])
        self.assertEqual("NEXT_MOVE_FAILED", saved["status"])
        self.assertEqual("MOVE_FAILED", saved["axis_mapping_v2"]["workflow_move_status"])
        self.assertEqual(1, saved["axis_mapping_v2"]["workflow_sample_index"])
        self.assertIsNone(controller.venue_target_test_authority)
        first_evidence = json.loads(json.dumps(controller.config["slots"][slot_id]["axis_mapping_v2"]["tilt_samples"]["0"]))

        retry = controller.move_axis_mapping_v2_sample({"slot_id": slot_id, "axis": "TILT", "index": 1})
        self.assertTrue(retry["accepted"], retry)
        self.assertEqual(first_evidence, controller.config["slots"][slot_id]["axis_mapping_v2"]["tilt_samples"]["0"])
        self.assertFalse(controller.save_axis_mapping_v2_sample({"axis": "PAN", "measured_degrees": 0})["accepted"])
        self.assertEqual(first_evidence, controller.config["slots"][slot_id]["axis_mapping_v2"]["tilt_samples"]["0"])

    def test_progressive_wizard_phase_and_sample_survive_restart_without_restoring_lease(self):
        with tempfile.TemporaryDirectory() as directory, patch("beatbeam_app.CONFIG_PATH", Path(directory) / "config.json"):
            controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
            self.assertTrue(controller.nudge_axis_mapping_v2_tilt_reference({
                "slot_id": slot_id, "axis": "PAN", "direction": "RIGHT", "granularity": "FINE",
            })["accepted"])
            self.assertTrue(controller.lock_axis_mapping_v2_tilt_reference({})["accepted"])
            self.assertTrue(controller.save_axis_mapping_v2_sample({"axis": "TILT", "measured_degrees": 0})["accepted"])
            controller.flush_config()
            restarted = DmxController(MagicMock())
            state = axis_mapping_v2_state(slot_id, restarted.config["slots"][slot_id], restarted.config["venue_geometry"])
            self.assertEqual("TILT", state["workflow_phase"])
            self.assertEqual(1, state["workflow_sample_index"])
            self.assertEqual(1, state["workflow_saved_count"])
            self.assertIsNone(restarted.venue_target_test_authority)

    def test_tilt_reference_and_pan_reference_are_exact_locked_raw_positions(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        self.assertTrue(controller.nudge_axis_mapping_v2_tilt_reference({"slot_id": slot_id, "direction": "RIGHT", "granularity": "COARSE"})["accepted"])
        locked_pan = controller.venue_target_test_authority["sample_raw"]
        self.assertTrue(controller.lock_axis_mapping_v2_tilt_reference({})["accepted"])
        for index, direction in enumerate((0, 45, 90, 135, 180)):
            moved = controller.move_axis_mapping_v2_sample({"slot_id": slot_id, "axis": "TILT", "index": index})
            self.assertTrue(moved["accepted"]); self.assertEqual(locked_pan, controller.venue_target_test_authority["reference_raw"])
            self.assertTrue(controller.save_axis_mapping_v2_sample({"axis": "TILT", "measured_degrees": direction})["accepted"])
        unreachable = controller.set_axis_mapping_v2_pan_reference({"slot_id": slot_id, "tilt_plane_degrees": -90})
        self.assertFalse(unreachable["accepted"]); self.assertEqual("REFERENCE_TILT_DIRECTION_UNREACHABLE", unreachable["status"])
        self.assertTrue(controller.set_axis_mapping_v2_pan_reference({"slot_id": slot_id, "tilt_plane_degrees": 0})["accepted"])
        state = axis_mapping_v2_state(slot_id, controller.config["slots"][slot_id], controller.config["venue_geometry"])
        self.assertEqual(0, state["pan_sweep_reference_tilt_raw"])
        for index in range(7):
            moved = controller.move_axis_mapping_v2_sample({"slot_id": slot_id, "axis": "PAN", "index": index})
            self.assertTrue(moved["accepted"]); self.assertEqual(state["pan_sweep_reference_tilt_raw"], controller.venue_target_test_authority["reference_raw"])
            controller.release_venue_target_test()

    def test_reference_pose_pan_and_tilt_nudges_are_progressive_decodable_and_movement_only(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        baseline = controller._render_values(time.time())
        slot = controller.config["slots"][slot_id]
        mode = find_mode(find_fixture(__import__("beatbeam_app").FIXTURE_LIBRARY, slot["fixture"]), slot["mode"])
        movement_types = {"pan", "pan_fine", "tilt", "tilt_fine"}

        left = controller.nudge_axis_mapping_v2_tilt_reference({
            "slot_id": slot_id, "axis": "PAN", "direction": "LEFT", "granularity": "COARSE",
        })
        self.assertTrue(left["accepted"], left)
        first_pan_raw = controller.venue_target_test_authority["sample_raw"]
        self.assertIsNone(left["authority"]["selected_resolution"])
        json.dumps(controller.state())

        right = controller.nudge_axis_mapping_v2_tilt_reference({
            "slot_id": slot_id, "axis": "PAN", "direction": "RIGHT", "granularity": "FINE",
        })
        self.assertTrue(right["accepted"], right)
        self.assertGreater(controller.venue_target_test_authority["sample_raw"], first_pan_raw)

        up = controller.nudge_axis_mapping_v2_tilt_reference({
            "slot_id": slot_id, "axis": "TILT", "direction": "UP", "granularity": "COARSE",
        })
        self.assertTrue(up["accepted"], up)
        temporary_tilt_raw = controller.venue_target_test_authority["reference_raw"]
        down = controller.nudge_axis_mapping_v2_tilt_reference({
            "slot_id": slot_id, "axis": "TILT", "direction": "DOWN", "granularity": "FINE",
        })
        self.assertTrue(down["accepted"], down)
        self.assertLess(controller.venue_target_test_authority["reference_raw"], temporary_tilt_raw)
        json.dumps(controller.state())

        adjusted = controller._render_values(time.time())
        for channel in mode["channels"]:
            absolute = slot["address"] + channel["offset"] - 1
            if channel["type"] not in movement_types:
                self.assertEqual(baseline.get(absolute), adjusted.get(absolute))

        locked_pan_raw = controller.venue_target_test_authority["sample_raw"]
        self.assertTrue(controller.lock_axis_mapping_v2_tilt_reference({})["accepted"])
        mapping = axis_mapping_v2_state(slot_id, controller.config["slots"][slot_id], controller.config["venue_geometry"])
        self.assertEqual(locked_pan_raw, mapping["tilt_sweep_reference_pan_raw"])
        self.assertEqual({}, mapping["tilt_samples"])
        sample = controller.move_axis_mapping_v2_sample({"slot_id": slot_id, "axis": "TILT", "index": 0})
        self.assertTrue(sample["accepted"], sample)
        self.assertEqual(locked_pan_raw, controller.venue_target_test_authority["reference_raw"])
        self.assertEqual(0, controller.venue_target_test_authority["sample_raw"])

    def test_validation_failure_blocks_activation_and_three_passes_allow_it(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        self.persisted_mapping(controller, slot_id, validations=False)
        for target in ("AUDIENCE_NEAR_CENTER", "AUDIENCE_MID_LEFT", "AUDIENCE_FAR_RIGHT"):
            moved = controller.move_axis_mapping_v2_validation({"slot_id": slot_id, "target": target})
            self.assertTrue(moved["accepted"], moved)
            result = "FAIL" if target == "AUDIENCE_MID_LEFT" else "PASS"
            controller.record_axis_mapping_v2_validation({"result": result})
        self.assertEqual("VALIDATION_FAILED", axis_mapping_v2_state(slot_id, controller.config["slots"][slot_id], controller.config["venue_geometry"])["status"])
        self.assertFalse(controller.activate_axis_mapping_v2({"slot_id": slot_id})["accepted"])
        moved = controller.move_axis_mapping_v2_validation({"slot_id": slot_id, "target": "AUDIENCE_MID_LEFT"})
        self.assertTrue(moved["accepted"])
        controller.record_axis_mapping_v2_validation({"result": "PASS"})
        self.assertEqual("VALIDATED", axis_mapping_v2_state(slot_id, controller.config["slots"][slot_id], controller.config["venue_geometry"])["status"])

    def test_profile_or_remount_change_stales_mapping_but_position_change_does_not(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        self.persisted_mapping(controller, slot_id, active=True, validations=True)
        slot = controller.config["slots"][slot_id]
        slot["venue_calibration"]["position"]["x"] += .1
        position_state = axis_mapping_v2_state(slot_id, slot, controller.config["venue_geometry"])
        self.assertNotEqual("STALE", position_state["status"])
        self.assertTrue(position_state["validation_stale"])
        slot["axis_mapping_v2_remount_revision"] = 1
        self.assertEqual("STALE", axis_mapping_v2_state(slot_id, slot, controller.config["venue_geometry"])["status"])

    def test_active_v2_ignores_legacy_anchor_model_for_normal_target(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        self.persisted_mapping(controller, slot_id, active=True, validations=True)
        slot = controller.config["slots"][slot_id]
        slot["kinematic_calibration"] = {
            "geometry_signature": __import__("beatbeam_app").kinematic_calibration_signature(slot, TEST_GEOMETRY),
            "anchors": {}, "model": {"status": "CALIBRATED", "pan": {"slope_raw_per_degree": 0}}, "validation": None,
        }
        resolution = controller._venue_target_result_set_locked("AUDIENCE_FAR_RIGHT")["results"][0]["resolution"]
        self.assertEqual("AXIS_MAPPING_V2", resolution["mapping_source"])

    def test_mixed_fixture_mapping_authorities_resolve_independently(self):
        controller, first = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        second = "second_head"
        controller.config["slots"][second] = json.loads(json.dumps(controller.config["slots"][first]))
        controller.config["slots"][second]["address"] = 80
        controller.config["slots"][second]["label"] = "Second"
        controller.config["slot_order"].append(second)
        self.persisted_mapping(controller, first, active=True, validations=True)
        results = controller._venue_target_result_set_locked("AUDIENCE_NEAR_CENTER")["results"]
        sources = {item["slot_id"]: item["resolution"]["mapping_source"] for item in results}
        self.assertEqual("AXIS_MAPPING_V2", sources[first])
        self.assertNotEqual("AXIS_MAPPING_V2", sources[second])

    def test_reset_v2_preserves_venue_and_legacy_calibration(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        self.persisted_mapping(controller, slot_id, active=True, validations=True)
        slot = controller.config["slots"][slot_id]
        venue_before = json.loads(json.dumps(slot["venue_calibration"]))
        legacy_before = json.loads(json.dumps(slot.get("kinematic_calibration")))
        response = controller.reset_axis_mapping_v2({"slot_id": slot_id, "confirm": True})
        self.assertTrue(response["accepted"])
        self.assertEqual(venue_before, controller.config["slots"][slot_id]["venue_calibration"])
        self.assertEqual(legacy_before, controller.config["slots"][slot_id].get("kinematic_calibration"))


class MetricVenueSpaceAndNativeEffectV1Tests(unittest.TestCase):
    def test_metric_position_is_canonical_and_legacy_evidence_is_preserved(self):
        controller = DmxController(MagicMock())
        slot_id = controller.config["slot_order"][0]
        legacy = {"x": -0.3, "y": 0.2}
        cleaned = controller._merge_payload({
            "venue_geometry": geometry_dict(),
            "slot_id": slot_id,
            "slot": {"venue_calibration": {
                "position": legacy,
                "mounting_height_m": 3.4,
                "physical_forward": {"x": 0, "y": 1, "z": 0},
                "physical_up": {"x": 0, "y": 0, "z": 1},
            }},
        })
        frozen_position = cleaned["slots"][slot_id]["venue_calibration"]["position_m"]
        self.assertAlmostEqual(-1.5, frozen_position["x"])
        self.assertAlmostEqual(2.4, frozen_position["y"])
        self.assertAlmostEqual(3.4, frozen_position["z"])
        self.assertEqual(legacy, cleaned["slots"][slot_id]["venue_calibration"]["position"])
        state = fixture_calibration_state(slot_id, cleaned["slots"][slot_id], TEST_GEOMETRY)
        self.assertEqual("METER_SPACE", state["position_source"])
        self.assertAlmostEqual(-1.5, state["position_m"]["x"])
        self.assertAlmostEqual(2.4, state["position_m"]["y"])
        self.assertAlmostEqual(3.4, state["position_m"]["z"])

        controller.config = cleaned
        upgraded = controller._merge_payload({
            "venue_geometry": geometry_dict(),
            "slot_id": slot_id,
            "slot": {"venue_calibration": {"position_m": {"x": -1.82, "y": 3.17, "z": 2.64}}},
        })
        venue = upgraded["slots"][slot_id]["venue_calibration"]
        self.assertEqual({"x": -1.82, "y": 3.17, "z": 2.64}, venue["position_m"])
        self.assertEqual(legacy, venue["position"])

    def test_legacy_position_freezes_once_and_geometry_changes_only_move_targets(self):
        controller = DmxController(MagicMock())
        slot_id = controller.config["slot_order"][0]
        controller.config = controller._merge_payload({
            "venue_geometry": geometry_dict(),
            "slot_id": slot_id,
            "slot": {"venue_calibration": {
                "position": {"x": -0.3, "y": 0.2},
                "mounting_height_m": 3.4,
                "physical_forward": {"x": 0, "y": 1, "z": 0},
                "physical_up": {"x": 0, "y": 0, "z": 1},
            }},
        })
        frozen = copy.deepcopy(controller.config["slots"][slot_id]["venue_calibration"]["position_m"])
        widened = controller._merge_payload({
            "venue_geometry": geometry_dict(venue_width_m=20.0, venue_forward_depth_m=24.0),
        })
        self.assertEqual(frozen, widened["slots"][slot_id]["venue_calibration"]["position_m"])
        before = resolve_venue_target(
            _venue_calibration_for_slot(slot_id, controller.config["slots"][slot_id], TEST_GEOMETRY),
            VENUE_TARGETS["AUDIENCE_MID_CENTER"],
            TEST_GEOMETRY,
        )
        after = resolve_venue_target(
            _venue_calibration_for_slot(slot_id, widened["slots"][slot_id], VenueGeometry(20.0, 24.0, 3.0, 1.2)),
            VENUE_TARGETS["AUDIENCE_MID_CENTER"],
            VenueGeometry(20.0, 24.0, 3.0, 1.2),
        )
        self.assertEqual(before["fixture_xyz_m"], after["fixture_xyz_m"])
        self.assertNotEqual(before["target_xyz_m"], after["target_xyz_m"])

    def test_legacy_position_without_scale_fails_closed_for_migration(self):
        controller = DmxController(MagicMock())
        slot_id = controller.config["slot_order"][0]
        cleaned = controller._merge_payload({
            "slot_id": slot_id,
            "slot": {"venue_calibration": {
                "position": {"x": -0.3, "y": 0.2},
                "mounting_height_m": 3.4,
                "physical_forward": {"x": 0, "y": 1, "z": 0},
                "physical_up": {"x": 0, "y": 0, "z": 1},
            }},
        })
        state = fixture_calibration_state(slot_id, cleaned["slots"][slot_id], VenueGeometry())
        self.assertIsNone(cleaned["slots"][slot_id]["venue_calibration"]["position_m"])
        self.assertEqual("POSITION_MIGRATION_REQUIRES_VENUE_SCALE", state["status"])
        self.assertEqual("POSITION_MIGRATION_REQUIRES_VENUE_SCALE", state["position_migration_status"])

    def test_metric_position_needs_no_legacy_scale_but_legacy_position_fails_closed(self):
        physical = calibrated_fixture()
        physical = VenueFixtureCalibration(**{
            **physical.__dict__,
            "position_m": VenuePhysicalPoint(-1.75, 2.50, 2.80),
            "position": None,
            "mounting_height_m": None,
        })
        target = VenuePhysicalPoint(0.0, 7.0, 1.2)
        result = resolve_venue_target(physical, target, VenueGeometry())
        self.assertEqual("RESOLVED", result["status"])
        self.assertEqual({"x": -1.75, "y": 2.5, "z": 2.8}, result["fixture_xyz_m"])
        legacy = resolve_venue_target(calibrated_fixture(), target, VenueGeometry())
        self.assertEqual("MISSING_VENUE_SCALE", legacy["status"])

    def test_metric_position_round_trips_without_grid_rounding_or_drift(self):
        with tempfile.TemporaryDirectory() as directory, patch("beatbeam_app.CONFIG_PATH", Path(directory) / "config.json"):
            controller = DmxController(MagicMock())
            slot_id = controller.config["slot_order"][0]
            controller.config = controller._merge_payload({"slot_id": slot_id, "slot": {"venue_calibration": {
                "position_m": {"x": -1.82, "y": 3.17, "z": 2.64},
                "physical_forward": {"x": 0, "y": 1, "z": 0},
                "physical_up": {"x": 0, "y": 0, "z": 1},
            }}})
            controller._write_config(controller.config)
            restarted = DmxController(MagicMock())
            self.assertEqual(
                {"x": -1.82, "y": 3.17, "z": 2.64},
                restarted.config["slots"][slot_id]["venue_calibration"]["position_m"],
            )
            restarted._write_config(restarted.config)
            again = DmxController(MagicMock())
            self.assertEqual(
                {"x": -1.82, "y": 3.17, "z": 2.64},
                again.config["slots"][slot_id]["venue_calibration"]["position_m"],
            )

    def test_same_world_point_uses_fixture_specific_raw_values(self):
        target = VenuePhysicalPoint(0.0, 8.0, 1.2)
        base = calibrated_fixture()
        left_fixture = VenueFixtureCalibration(**{**base.__dict__, "position_m": VenuePhysicalPoint(-2.0, 0.0, 2.8), "position": None})
        right_fixture = VenueFixtureCalibration(**{**base.__dict__, "position_m": VenuePhysicalPoint(2.0, 0.0, 2.8), "position": None})
        left = resolve_venue_target(left_fixture, target, TEST_GEOMETRY)
        right = resolve_venue_target(right_fixture, target, TEST_GEOMETRY)
        self.assertEqual("RESOLVED", left["status"])
        self.assertEqual("RESOLVED", right["status"])
        self.assertNotEqual(left["chosen_pan_raw"] if "chosen_pan_raw" in left else left["predicted_output"]["pan"], right["chosen_pan_raw"] if "chosen_pan_raw" in right else right["predicted_output"]["pan"])
        self.assertGreater(left["target_vector_m"]["x"], 0)
        self.assertLess(right["target_vector_m"]["x"], 0)

    def test_audience_sweep_is_a_staged_continuous_metric_path(self):
        first = venue_native_effect_intent("fast_audience_sweep", 12.5, TEST_GEOMETRY, {
            "artistic_participant_index": 0, "artistic_participant_count": 4,
            "artistic_participant_centered": -1.0,
        })
        second = venue_native_effect_intent("fast_audience_sweep", 12.5, TEST_GEOMETRY, {
            "artistic_participant_index": 3, "artistic_participant_count": 4,
            "artistic_participant_centered": 1.0,
        })
        adjacent = venue_native_effect_intent("fast_audience_sweep", 12.51, TEST_GEOMETRY, {})
        self.assertNotEqual(first["world_target_xyz_m"], second["world_target_xyz_m"])
        self.assertNotEqual(first["world_target_xyz_m"]["x"], adjacent["world_target_xyz_m"]["x"])
        self.assertEqual(TEST_GEOMETRY.audience_target_height_m, first["world_target_xyz_m"]["z"])

    def test_audience_rise_is_a_world_target_and_snap_fan_is_a_world_direction(self):
        rise_low = venue_native_effect_intent("audience_riser", 0, TEST_GEOMETRY, {"member_centered": -1}, progress=0.0)
        rise_high = venue_native_effect_intent("audience_riser", 0, TEST_GEOMETRY, {"member_centered": -1}, progress=0.9)
        fan = venue_native_effect_intent("snap_fan", 0, TEST_GEOMETRY, {"member_centered": 1})
        self.assertGreater(rise_high["world_target_xyz_m"]["z"], rise_low["world_target_xyz_m"]["z"])
        self.assertGreater(rise_high["world_target_xyz_m"]["y"], rise_low["world_target_xyz_m"]["y"])
        self.assertEqual("WORLD_DIRECTION", fan["kind"])
        self.assertGreater(fan["world_direction"]["x"], 0)

    def test_shared_resolver_observes_per_fixture_fallback_authority(self):
        controller = DmxController(MagicMock())
        controller.config = controller._merge_payload({"venue_geometry": geometry_dict()})
        slot_id = controller.config["slot_order"][0]
        controller.config = controller._merge_payload({"slot_id": slot_id, "slot": {"venue_calibration": {
            "position_m": {"x": -1.0, "y": 0.0, "z": 2.8},
            "physical_forward": {"x": 0, "y": 1, "z": 0},
            "physical_up": {"x": 0, "y": 0, "z": 1},
        }}})
        intent = venue_native_effect_intent("fast_audience_sweep", 8, TEST_GEOMETRY, {})
        result = resolve_spatial_movement_intent(slot_id, controller.config["slots"][slot_id], TEST_GEOMETRY, intent)
        self.assertEqual("RESOLVED", result["status"])
        self.assertEqual("LEGACY_OR_THEORETICAL", result["movement_mapping_authority"])

    def test_active_v2_audience_effect_inverse_forward_round_trip(self):
        controller, slot_id = VenueTargetPhysicalTestV1Tests().make_ready_controller()
        controller.config = controller._merge_payload({"slot_id": slot_id, "slot": {"venue_calibration": {
            "position_m": {"x": -1.5, "y": 0.0, "z": 2.8},
        }}})
        PhysicalAxisMappingV2Tests.persisted_mapping(controller, slot_id, active=True, validations=True)
        intent = venue_native_effect_intent("fast_audience_sweep", 5.25, TEST_GEOMETRY, {})
        result = resolve_spatial_movement_intent(slot_id, controller.config["slots"][slot_id], TEST_GEOMETRY, intent)
        self.assertEqual("RESOLVED", result["status"])
        self.assertEqual("AXIS_MAPPING_V2", result["mapping_source"])
        self.assertEqual("V2_ACTIVE_CALIBRATED", result["movement_mapping_authority"])
        mapping = axis_mapping_v2_state(slot_id, controller.config["slots"][slot_id], TEST_GEOMETRY)["model"]
        pan = axis_mapping_v2_forward(result["chosen_pan_raw"], mapping["pan"])
        tilt = axis_mapping_v2_forward(result["chosen_tilt_raw"], mapping["tilt"])
        projected = __import__("beatbeam_app").axis_mapping_v2_world_direction(pan, tilt)
        desired = result["target_vector_m"]
        length = math.sqrt(sum(desired[key] ** 2 for key in ("x", "y", "z")))
        dot = sum(getattr(projected, key) * desired[key] / length for key in ("x", "y", "z"))
        self.assertGreater(dot, 0.999)

    def test_live_audience_sweep_renderer_tracks_distinct_artistic_samples(self):
        controller = DmxController(MagicMock())
        config = controller.default_config()
        config["slots"]["right"] = copy.deepcopy(config["slots"]["head"])
        config["slots"]["right"]["address"] = 50
        config["slots"]["right"]["label"] = "Right"
        config["slot_order"].append("right")
        config["venue_geometry"] = geometry_dict()
        for slot_id, x in (("head", -2.0), ("right", 2.0)):
            config["slots"][slot_id]["sync_enabled"] = True
            config["slots"][slot_id]["venue_calibration"] = {
                "position_m": {"x": x, "y": 0.0, "z": 2.8},
                "physical_forward": {"x": 0, "y": 1, "z": 0},
                "physical_up": {"x": 0, "y": 0, "z": 1},
            }
        config["auto_show"]["enabled"] = False
        config["auto_show"]["override_audience_sweep"] = True
        config = controller._clean_full_config(config)
        osc = {"phrase_current": "verse", "beat_value": 4.25, "stale": False, "bpm": 124}
        auto_show = controller._auto_show_state(osc, config["auto_show"])
        values = controller._render_values_with_context(1000.0, config, osc, auto_show, advance_motion=False)
        rendered = rendered_motion_projection(config, values)
        raw_pairs = []
        for slot_id in ("head", "right"):
            item = rendered[slot_id]
            raw_pairs.append((item["pan"], item["pan_fine"], item["tilt"], item["tilt_fine"]))
            context = controller._slot_context(config, slot_id, config["slots"][slot_id])
            intent = venue_native_effect_intent("live_audience_tilt_sweep", 4.25, TEST_GEOMETRY, context)
            target = intent["world_target_xyz_m"]
            position = item["fixture_position_m"]
            desired = [target[key] - position[key] for key in ("x", "y", "z")]
            length = math.sqrt(sum(value * value for value in desired))
            dot = sum(item["world_direction"][key] * value / length for key, value in zip(("x", "y", "z"), desired))
            self.assertGreater(dot, 0.999)
        self.assertNotEqual(raw_pairs[0], raw_pairs[1])


class PhysicalTiltLimitsV1Tests(unittest.TestCase):
    @staticmethod
    def _hanging_axis_model(local_maximum=90.0):
        raw_maximum = 65535
        pan = {
            str(index): {"index": index, "raw": round(raw_maximum * index / 6), "measured_azimuth_degrees": value}
            for index, value in enumerate((270, 0, 90, 180, 270, 0, 90))
        }
        # Local -range -> rear horizon, 0 -> down, +range -> front horizon.
        tilt_values = (180, -135, -90, -45, 0) if local_maximum == 90.0 else (160, -145, -90, -35, 20)
        tilt = {
            str(index): {"index": index, "raw": round(raw_maximum * index / 4), "measured_tilt_plane_degrees": value}
            for index, value in enumerate(tilt_values)
        }
        return fit_axis_mapping_v2(pan, tilt)

    def _calibration(self, maximum=90.0, current_tilt_raw=None):
        return VenueFixtureCalibration(
            supports_pan_tilt=True,
            position_m=VenuePhysicalPoint(0, 0, 2.5),
            physical_forward=VenueVector3(0, 1, 0),
            physical_up=VenueVector3(0, 0, 1),
            pan_min_degrees=-270, pan_max_degrees=270,
            tilt_min_degrees=-maximum, tilt_max_degrees=maximum,
            physical_tilt_min_deg=-maximum, physical_tilt_center_deg=0.0, physical_tilt_max_deg=maximum,
            supports_pan_fine=True, supports_tilt_fine=True,
            axis_mapping_v2=self._hanging_axis_model(maximum),
            current_tilt_raw=current_tilt_raw,
        )

    @staticmethod
    def _target(elevation_degrees, *, rear=False):
        distance = 10.0
        return VenuePhysicalPoint(0, -distance if rear else distance, 2.5 + distance * math.tan(math.radians(elevation_degrees)))

    def test_current_profile_declares_explicit_minus_90_zero_plus_90_limits(self):
        profile = find_fixture(__import__("beatbeam_app").FIXTURE_LIBRARY, "shehds_led_wash_7x12w_rgbw_moving_head")
        self.assertEqual(
            {"min_deg": -90.0, "center_deg": 0.0, "max_deg": 90.0, "source": "PROFILE_EXPLICIT"},
            fixture_physical_tilt_limits({"fixture": profile["id"]}),
        )

    def test_invalid_override_is_rejected_and_legacy_slot_uses_profile_default(self):
        controller = DmxController(MagicMock())
        slot_id = controller.config["slot_order"][0]
        with self.assertRaisesRegex(ValueError, "min < center < max"):
            controller._merge_payload({"slot_id": slot_id, "slot": {"venue_calibration": {
                "physical_tilt_limits": {"min_deg": 90, "center_deg": 0, "max_deg": -90},
            }}})
        self.assertEqual("PROFILE_EXPLICIT", fixture_calibration_state(slot_id, controller.config["slots"][slot_id])["capabilities"]["physical_tilt_limits_source"])

    def test_hanging_range_clamps_plus_110_at_plus_90_without_moving_target(self):
        target = self._target(20.0)
        result = resolve_venue_target(self._calibration(90, current_tilt_raw=65535), target)
        self.assertEqual("RESOLVED", result["status"])
        self.assertTrue(result["clamped"])
        self.assertEqual("PHYSICAL_TILT_BOUNDARY", result["clamp_reason"])
        self.assertAlmostEqual(110.0, result["requested_local_tilt_deg"], places=1)
        self.assertAlmostEqual(90.0, result["resolved_local_tilt_deg"], places=1)
        self.assertEqual(target.as_dict(), result["target_xyz_m"])

    def test_hanging_range_clamps_minus_120_at_minus_90(self):
        target = self._target(30.0, rear=True)
        result = resolve_venue_target(self._calibration(90, current_tilt_raw=0), target)
        self.assertEqual("RESOLVED", result["status"])
        self.assertTrue(result["clamped"])
        self.assertAlmostEqual(-120.0, result["requested_local_tilt_deg"], places=1)
        self.assertAlmostEqual(-90.0, result["resolved_local_tilt_deg"], places=1)

    def test_extended_range_allows_plus_105_and_clamps_plus_125_independently(self):
        calibration = self._calibration(110, current_tilt_raw=65535)
        reachable = resolve_venue_target(calibration, self._target(15.0))
        limited = resolve_venue_target(calibration, self._target(35.0))
        self.assertFalse(reachable["clamped"])
        self.assertAlmostEqual(105.0, reachable["resolved_local_tilt_deg"], places=1)
        self.assertTrue(limited["clamped"])
        self.assertAlmostEqual(125.0, limited["requested_local_tilt_deg"], places=1)
        self.assertAlmostEqual(110.0, limited["resolved_local_tilt_deg"], places=1)

    def test_same_world_target_resolves_independently_by_fixture_range(self):
        target = self._target(15.0)
        limited = resolve_venue_target(self._calibration(90, current_tilt_raw=65535), target)
        extended = resolve_venue_target(self._calibration(110, current_tilt_raw=65535), target)
        self.assertTrue(limited["clamped"])
        self.assertAlmostEqual(90.0, limited["resolved_local_tilt_deg"], places=1)
        self.assertFalse(extended["clamped"])
        self.assertAlmostEqual(105.0, extended["resolved_local_tilt_deg"], places=1)
        self.assertEqual(target.as_dict(), limited["target_xyz_m"])
        self.assertEqual(target.as_dict(), extended["target_xyz_m"])

    def test_upright_calibration_maps_local_center_to_up_without_mount_switch(self):
        maximum = 65535
        pan = {
            str(index): {"index": index, "raw": round(maximum * index / 6), "measured_azimuth_degrees": value}
            for index, value in enumerate((270, 0, 90, 180, 270, 0, 90))
        }
        tilt = {
            str(index): {"index": index, "raw": round(maximum * index / 4), "measured_tilt_plane_degrees": value}
            for index, value in enumerate((180, 135, 90, 45, 0))
        }
        calibration = VenueFixtureCalibration(
            supports_pan_tilt=True, position_m=VenuePhysicalPoint(0, 0, 2.5),
            physical_forward=VenueVector3(0, 1, 0), physical_up=VenueVector3(0, 0, 1),
            pan_min_degrees=-270, pan_max_degrees=270, tilt_min_degrees=-90, tilt_max_degrees=90,
            physical_tilt_min_deg=-90, physical_tilt_center_deg=0, physical_tilt_max_deg=90,
            supports_pan_fine=True, supports_tilt_fine=True, axis_mapping_v2=fit_axis_mapping_v2(pan, tilt),
        )
        result = resolve_venue_target(calibration, VenuePhysicalPoint(0, 0.001, 12.5))
        self.assertEqual("RESOLVED", result["status"])
        self.assertFalse(result["clamped"])
        self.assertAlmostEqual(0.0, result["resolved_local_tilt_deg"], places=1)

    def test_no_dmx_test_all_uses_mixed_fixture_bounds_and_final_rendered_motion(self):
        controller = DmxController(MagicMock())
        controller._schedule_save_locked = lambda: None
        controller.osc.snapshot_for_render.return_value = {"phrase_current": "verse", "stale": False, "beat_value": 0.0}
        controller.config = controller.default_config()
        ceiling = 2.5 + 4.4 * math.tan(math.radians(15.0))
        controller.config = controller._merge_payload({"venue_geometry": {
            "venue_width_m": 6.0, "venue_forward_depth_m": 8.0, "venue_rear_depth_m": 0.5,
            "audience_target_height_m": 1.0, "ceiling_height_m": ceiling,
        }})
        first = controller.config["slot_order"][0]
        second = "extended_tilt_head"
        controller.config["slots"][second] = copy.deepcopy(controller.config["slots"][first])
        controller.config["slots"][second]["address"] = 60
        controller.config["slots"][second]["label"] = "Extended Tilt"
        controller.config["slots"][second]["venue_calibration"] = {
            "position_m": {"x": 0.0, "y": 0.0, "z": 2.5},
            "physical_forward": {"x": 0, "y": 1, "z": 0},
            "physical_up": {"x": 0, "y": 0, "z": 1},
            "physical_tilt_limits": {"min_deg": -110, "center_deg": 0, "max_deg": 110},
        }
        controller.config["slots"][first]["venue_calibration"] = {
            "position_m": {"x": 0.0, "y": 0.0, "z": 2.5},
            "physical_forward": {"x": 0, "y": 1, "z": 0},
            "physical_up": {"x": 0, "y": 0, "z": 1},
        }
        controller.config["slot_order"] = [first, second]
        controller.config = controller._clean_full_config(controller.config)
        for slot_id, local_maximum in ((first, 90.0), (second, 110.0)):
            maximum = 65535
            pan = {
                str(index): {"index": index, "raw": round(maximum * index / 6), "measured_azimuth_degrees": value}
                for index, value in enumerate((270, 0, 90, 180, 270, 0, 90))
            }
            tilt_values = (180, -135, -90, -45, 0) if local_maximum == 90.0 else (160, -145, -90, -35, 20)
            tilt = {
                str(index): {"index": index, "raw": round(maximum * index / 4), "measured_tilt_plane_degrees": value}
                for index, value in enumerate(tilt_values)
            }
            model = fit_axis_mapping_v2(pan, tilt)
            pan_reference_tilt = round(axis_mapping_v2_inverse_tilt(0, model["tilt"]))
            tilt_reference_pan = round(maximum / 2)
            for sample in pan.values(): sample["reference_raw"] = pan_reference_tilt
            for sample in tilt.values(): sample["reference_raw"] = tilt_reference_pan
            signature = __import__("beatbeam_app").axis_mapping_v2_signature(controller.config["slots"][slot_id])
            evidence_signature = __import__("beatbeam_app").axis_mapping_v2_validation_signature(controller.config["slots"][slot_id], controller.config["venue_geometry"])
            controller.config["slots"][slot_id]["axis_mapping_v2"] = {
                "version": 2, "profile_signature": signature, "session_revision": 1,
                "pan_samples": pan, "tilt_samples": tilt, "model": model,
                "tilt_sweep_reference_pan_raw": tilt_reference_pan,
                "pan_sweep_reference_tilt_plane_degrees": 0.0,
                "pan_sweep_reference_tilt_raw": pan_reference_tilt,
                "pan_samples_review_required": False,
                "validations": {target: {"target": target, "result": "PASS", "venue_geometry_signature": evidence_signature}
                                for target in __import__("beatbeam_app").AXIS_MAPPING_V2_VALIDATION_TARGETS},
                "active": True,
            }
        controller.connected = False
        controller.dmx = None
        controller.render_active = True
        response = controller.activate_venue_target_preview_test({"target": "AUDIENCE_MID_CENTER", "vertical_layer": "CEILING"})
        self.assertTrue(response["accepted"], response)
        results = {item["slot_id"]: item["resolution"] for item in response["authority"]["result_set"]["results"]}
        self.assertTrue(results[first]["clamped"])
        self.assertFalse(results[second]["clamped"])
        self.assertEqual(results[first]["target_xyz_m"], results[second]["target_xyz_m"])
        final_values = controller._render_values(time.time())
        projected = rendered_motion_projection(controller.config, final_values)
        self.assertEqual(results[first]["chosen_tilt_raw"] >> 8, projected[first]["tilt"])
        self.assertEqual(results[second]["chosen_tilt_raw"] >> 8, projected[second]["tilt"])


if __name__ == "__main__":
    unittest.main()
