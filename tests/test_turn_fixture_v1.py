import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from beatbeam_app import (
    DmxController,
    FIXTURE_LIBRARY,
    MountingOrientation,
    VenueFixtureCalibration,
    VenuePhysicalPoint,
    VenueVector3,
    _venue_calibration_for_slot,
    apply_mounting_orientation_to_world_direction,
    axis_mapping_v2_signature,
    axis_mapping_v2_world_direction,
    find_fixture,
    find_mode,
    fit_axis_mapping_v2,
    fixture_calibration_state,
    rendered_motion_projection,
    resolve_venue_target,
)


class _Osc:
    def snapshot_for_render(self):
        return {"stale": True, "beat_value": 0.0, "bpm": 120.0}

    def developer_playback_state(self):
        return {"source": "none"}


def _normalized(vector):
    length = math.sqrt(sum(component * component for component in vector))
    return tuple(component / length for component in vector)


def _fixture_config():
    config = DmxController.default_config()
    slot = config["slots"]["head"]
    slot["venue_calibration"] = {
        "version": 3,
        "position_m": {"x": 0.0, "y": 0.0, "z": 2.5},
        "position": None,
        "mounting_height_m": 2.5,
        "physical_forward": {"x": 0.0, "y": 1.0, "z": 0.0},
        "physical_up": {"x": 0.0, "y": 0.0, "z": 1.0},
        "pan_correction_degrees": 0.0,
        "tilt_correction_degrees": 0.0,
        "physical_tilt_limits": {"min_deg": -90.0, "center_deg": 0.0, "max_deg": 90.0},
    }
    return config


def _calibration(orientation=MountingOrientation.NORMAL, *, pan_limits=(-270.0, 270.0), tilt_limits=(-135.0, 135.0)):
    return VenueFixtureCalibration(
        supports_pan_tilt=True,
        position_m=VenuePhysicalPoint(0.0, 0.0, 2.5),
        physical_forward=VenueVector3(0.0, 1.0, 0.0),
        physical_up=VenueVector3(0.0, 0.0, 1.0),
        mounting_orientation=orientation,
        pan_min_degrees=pan_limits[0],
        pan_max_degrees=pan_limits[1],
        tilt_min_degrees=tilt_limits[0],
        tilt_max_degrees=tilt_limits[1],
        supports_pan_fine=True,
        supports_tilt_fine=True,
    )


class TurnFixturePersistenceTests(unittest.TestCase):
    def test_legacy_missing_property_is_normal_without_load_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            payload = _fixture_config()
            for slot in payload["slots"].values():
                slot.pop("mounting_orientation", None)
            original = json.dumps(payload, separators=(",", ":")).encode()
            path.write_bytes(original)

            controller = DmxController(_Osc(), config_path=path)
            self.assertEqual(original, path.read_bytes())
            self.assertNotIn("mounting_orientation", controller.config["slots"]["head"])
            self.assertEqual(
                "NORMAL",
                fixture_calibration_state("head", controller.config["slots"]["head"])["mounting_orientation"],
            )

            controller.flush_config()
            persisted = json.loads(path.read_text())
            self.assertNotIn("mounting_orientation", persisted["slots"]["head"])
            self.assertNotIn("mounting_orientation", persisted["slots"]["par"])

    def test_explicit_normal_and_rotated_180_round_trip(self):
        for orientation in ("NORMAL", "ROTATED_180"):
            with self.subTest(orientation=orientation), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "roundtrip.json"
                payload = _fixture_config()
                payload["slots"]["head"]["mounting_orientation"] = orientation
                path.write_text(json.dumps(payload))
                controller = DmxController(_Osc(), config_path=path)
                controller.flush_config()
                restarted = DmxController(_Osc(), config_path=path)
                self.assertEqual(orientation, restarted.config["slots"]["head"]["mounting_orientation"])

    def test_invalid_persisted_value_is_preserved_and_blocks_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            payload = _fixture_config()
            payload["slots"]["head"]["mounting_orientation"] = "SIDEWAYS"
            original = json.dumps(payload, sort_keys=True).encode()
            path.write_bytes(original)
            controller = DmxController(_Osc(), config_path=path)
            self.assertEqual("CONFIG_INVALID", controller.config_persistence_blocked_reason)
            controller.flush_config()
            self.assertEqual(original, path.read_bytes())

    def test_invalid_live_value_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = DmxController(_Osc(), config_path=Path(directory) / "isolated.json")
            with self.assertRaisesRegex(ValueError, "NORMAL or ROTATED_180"):
                controller._merge_payload({
                    "slot_id": "head",
                    "slot": {"mounting_orientation": "SIDEWAYS"},
                })

    def test_switch_preserves_fixture_identity_calibration_and_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = DmxController(_Osc(), config_path=Path(directory) / "isolated.json")
            controller.config = controller._clean_full_config(_fixture_config())
            before = copy.deepcopy(controller.config["slots"]["head"])
            protected = {
                key: copy.deepcopy(before[key])
                for key in ("fixture", "mode", "address", "venue_calibration", "axis_mapping_v2", "kinematic_calibration")
            }
            rotated = controller._merge_payload({
                "slot_id": "head", "slot": {"mounting_orientation": "ROTATED_180"}
            })
            self.assertEqual("ROTATED_180", rotated["slots"]["head"]["mounting_orientation"])
            normal = controller._merge_payload({
                "slot_id": "head", "slot": {"mounting_orientation": "NORMAL"}
            })
            self.assertEqual("NORMAL", normal["slots"]["head"]["mounting_orientation"])
            for key, value in protected.items():
                self.assertEqual(value, normal["slots"]["head"][key])

    def test_mounting_orientation_does_not_invalidate_axis_calibration_signature(self):
        slot = _fixture_config()["slots"]["head"]
        normal_signature = axis_mapping_v2_signature(slot)
        slot["mounting_orientation"] = "ROTATED_180"
        self.assertEqual(normal_signature, axis_mapping_v2_signature(slot))

    def test_existing_live_apply_path_updates_one_slot_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            osc = MagicMock()
            osc.snapshot_for_render.return_value = {
                "stale": False, "beat_value": 0.0, "bpm": 120.0,
                "phrase_current": "verse",
            }
            controller = DmxController(osc, config_path=Path(directory) / "isolated.json")
            controller._schedule_save_locked = lambda: None
            other_before = copy.deepcopy(controller.config["slots"]["par"])
            controller.update_config({
                "slot_id": "head", "slot": {"mounting_orientation": "ROTATED_180"}
            })
            self.assertEqual("ROTATED_180", controller.config["slots"]["head"]["mounting_orientation"])
            self.assertEqual(other_before, controller.config["slots"]["par"])


class TurnFixturePhysicalMathTests(unittest.TestCase):
    def assertDirectionAlmostEqual(self, actual, expected, places=5):
        for observed, wanted in zip(actual, expected):
            self.assertAlmostEqual(wanted, observed, places=places)

    def decoded_world_direction(self, result, orientation):
        pan = math.radians(result["pan_degrees"])
        tilt = math.radians(result["tilt_degrees"])
        nominal = VenueVector3(
            math.cos(tilt) * math.sin(pan),
            math.cos(tilt) * math.cos(pan),
            math.sin(tilt),
        )
        mounted = apply_mounting_orientation_to_world_direction(nominal, orientation)
        return (mounted.x, mounted.y, mounted.z)

    def test_world_vertical_half_turn_flips_xy_and_preserves_z(self):
        source = VenueVector3(0.25, -0.75, 0.5)
        normal = apply_mounting_orientation_to_world_direction(source, "NORMAL")
        rotated = apply_mounting_orientation_to_world_direction(source, "ROTATED_180")
        self.assertEqual(source, normal)
        self.assertEqual(VenueVector3(-0.25, 0.75, 0.5), rotated)
        self.assertEqual(source, apply_mounting_orientation_to_world_direction(rotated, "ROTATED_180"))

    def test_missing_and_explicit_normal_are_identical(self):
        target = VenuePhysicalPoint(1.75, 5.0, 1.0)
        implicit = resolve_venue_target(_calibration(), target)
        explicit = resolve_venue_target(_calibration(MountingOrientation.NORMAL), target)
        self.assertEqual(implicit, explicit)
        self.assertAlmostEqual(19.290046219188735, implicit["pan_degrees"])
        self.assertAlmostEqual(-15.809868034566579, implicit["tilt_degrees"])
        self.assertEqual(
            {"pan": 137, "tilt": 113, "pan_fine": 37, "tilt_fine": 2},
            implicit["predicted_output"],
        )

    def test_rotated_fixture_hits_left_right_audience_rear_and_vertical_directions(self):
        targets = (
            VenuePhysicalPoint(-2.0, 5.0, 1.0),
            VenuePhysicalPoint(2.0, 5.0, 1.0),
            VenuePhysicalPoint(0.5, 6.0, 4.0),
            VenuePhysicalPoint(-0.5, -3.0, 1.5),
            VenuePhysicalPoint(0.001, 2.0, 8.0),
        )
        calibration = _calibration(MountingOrientation.ROTATED_180)
        for target in targets:
            with self.subTest(target=target):
                result = resolve_venue_target(calibration, target)
                self.assertEqual("RESOLVED", result["status"])
                desired = _normalized((target.x, target.y, target.z - 2.5))
                self.assertDirectionAlmostEqual(
                    self.decoded_world_direction(result, MountingOrientation.ROTATED_180),
                    desired,
                )
                self.assertEqual(-target.x, result["solver_target_vector_m"]["x"])
                self.assertEqual(-target.y, result["solver_target_vector_m"]["y"])
                self.assertEqual(target.z - 2.5, result["solver_target_vector_m"]["z"])

    def test_pan_wrap_boundary_remains_reachable_on_both_sides(self):
        calibration = _calibration(MountingOrientation.ROTATED_180)
        results = [
            resolve_venue_target(calibration, VenuePhysicalPoint(x, 5.0, 2.5))
            for x in (-0.001, 0.001)
        ]
        self.assertTrue(all(result["status"] == "RESOLVED" for result in results))
        self.assertGreater(results[0]["pan_degrees"], 179.0)
        self.assertLess(results[1]["pan_degrees"], -179.0)

    def test_limits_still_fail_closed_and_tilt_center_is_preserved(self):
        target = VenuePhysicalPoint(0.0, 5.0, 2.5)
        normal = resolve_venue_target(
            _calibration(MountingOrientation.NORMAL, pan_limits=(-90.0, 90.0), tilt_limits=(-30.0, 30.0)),
            target,
        )
        rotated = resolve_venue_target(
            _calibration(MountingOrientation.ROTATED_180, pan_limits=(-90.0, 90.0), tilt_limits=(-30.0, 30.0)),
            target,
        )
        self.assertEqual("RESOLVED", normal["status"])
        self.assertAlmostEqual(0.0, normal["tilt_degrees"])
        self.assertEqual("UNREACHABLE", rotated["status"])

    def test_axis_mapping_v2_solver_uses_the_same_single_transform(self):
        maximum = 65535
        pan_samples = {
            str(index): {
                "index": index,
                "raw": round(maximum * index / 6),
                "measured_azimuth_degrees": value,
            }
            for index, value in enumerate((270, 0, 90, 180, 270, 0, 90))
        }
        tilt_samples = {
            str(index): {
                "index": index,
                "raw": round(maximum * index / 4),
                "measured_tilt_plane_degrees": value,
            }
            for index, value in enumerate((180, 135, 90, 45, 0))
        }
        calibration = _calibration(MountingOrientation.ROTATED_180)
        calibration = VenueFixtureCalibration(
            **{
                **calibration.__dict__,
                "physical_tilt_min_deg": -90.0,
                "physical_tilt_center_deg": 0.0,
                "physical_tilt_max_deg": 90.0,
                "axis_mapping_v2": fit_axis_mapping_v2(pan_samples, tilt_samples),
            }
        )
        for target in (
            VenuePhysicalPoint(-2.0, 5.0, 4.0),
            VenuePhysicalPoint(2.0, 5.0, 4.0),
            VenuePhysicalPoint(0.1, -3.0, 4.0),
            VenuePhysicalPoint(0.001, 2.0, 8.0),
        ):
            with self.subTest(target=target):
                result = resolve_venue_target(calibration, target)
                self.assertEqual("RESOLVED", result["status"])
                self.assertFalse(result["clamped"])
                nominal = axis_mapping_v2_world_direction(
                    result["predicted_physical_azimuth_degrees"],
                    result["predicted_physical_tilt_plane_degrees"],
                )
                mounted = apply_mounting_orientation_to_world_direction(
                    nominal, MountingOrientation.ROTATED_180
                )
                observed = (mounted.x, mounted.y, mounted.z)
                desired = _normalized((target.x, target.y, target.z - 2.5))
                self.assertDirectionAlmostEqual(observed, desired, places=3)

        bounded = resolve_venue_target(
            calibration, VenuePhysicalPoint(2.0, 5.0, 1.0)
        )
        self.assertEqual("RESOLVED", bounded["status"])
        self.assertTrue(bounded["clamped"])
        self.assertEqual("PHYSICAL_TILT_BOUNDARY", bounded["clamp_reason"])

    def test_rendered_motion_applies_mounting_transform_once(self):
        config = _fixture_config()
        slot = config["slots"]["head"]
        slot["mounting_orientation"] = "ROTATED_180"
        calibration = _venue_calibration_for_slot(
            "head", slot, config["venue_geometry"], use_kinematic=False, use_axis_mapping_v2=False
        )
        target = VenuePhysicalPoint(2.0, 5.0, 1.0)
        resolved = resolve_venue_target(calibration, target)
        self.assertEqual("RESOLVED", resolved["status"])

        fixture = find_fixture(FIXTURE_LIBRARY, slot["fixture"])
        mode = find_mode(fixture, slot["mode"])
        values = {}
        for channel in mode["channels"]:
            channel_type = channel["type"]
            if channel_type in resolved["predicted_output"]:
                value = resolved["predicted_output"][channel_type]
                if value is not None:
                    values[slot["address"] + channel["offset"] - 1] = value
        projected = rendered_motion_projection(config, values)["head"]
        self.assertEqual("AVAILABLE", projected["status"])
        self.assertEqual("ROTATED_180", projected["mounting_orientation"])
        desired = _normalized((target.x, target.y, target.z - 2.5))
        observed = tuple(projected["world_direction"][key] for key in ("x", "y", "z"))
        self.assertDirectionAlmostEqual(observed, desired, places=3)


class TurnFixtureNativeAuthorityTests(unittest.TestCase):
    def test_native_physical_setup_exposes_only_supported_options(self):
        source = Path("native/BeatBeamDMXApp.swift").read_text()
        panel = source[source.index("struct FixtureVenueCalibrationPanel"):source.index("private func physicalMovementLimits", source.index("struct FixtureVenueCalibrationPanel"))]
        self.assertIn('Text("MOUNTING ORIENTATION")', panel)
        self.assertIn('Text("Normal").tag("NORMAL")', panel)
        self.assertIn('Text("Rotated 180°").tag("ROTATED_180")', panel)

    def test_all_preview_modes_keep_rendered_world_direction_as_authority(self):
        source = Path("native/BeatBeamDMXApp.swift").read_text()
        beam = source[source.index("struct StageFixtureBeam"):source.index("private func stageBeamKindFor3D")]
        self.assertIn("state?.worldDirection", beam)
        self.assertIn("Do not reapply yaw or panFlip", beam)
        self.assertNotIn("mountingOrientation", beam)
        stage_state = source[source.index("var presentedStageMotionStates"):source.index("func venueTargetPreviewVisual")]
        self.assertIn("motion.worldDirection", stage_state)
        self.assertGreaterEqual(source.count("stageMotion?.worldDirection.map"), 2)
        self.assertGreaterEqual(source.count("stageMotion?.worldDirection == nil"), 2)


if __name__ == "__main__":
    unittest.main()
