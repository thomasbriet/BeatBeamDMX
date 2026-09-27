import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from beatbeam_app import DmxController


class RecordingDmx:
    def __init__(self):
        self.frames = []

    def send(self, values):
        self.frames.append(dict(values))


class MultiVenueV1Tests(unittest.TestCase):
    def make_controller(self, config_path):
        osc = MagicMock()
        osc.snapshot_for_render.return_value = {
            "phrase_current": "verse", "stale": False, "beat_value": 0.0,
        }
        osc.developer_playback_state.return_value = {}
        return DmxController(osc, config_path=config_path)

    def test_legacy_config_bootstraps_one_current_venue_without_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "beatbeam_config.json"
            payload = DmxController.default_config()
            payload["slots"]["head"]["venue_calibration"] = {
                "version": 3,
                "position_m": {"x": -1.25, "y": 2.0, "z": 3.1},
                "position": None,
                "mounting_height_m": 3.1,
                "physical_forward": {"x": 0, "y": 1, "z": 0},
                "physical_up": {"x": 0, "y": 0, "z": 1},
                "pan_correction_degrees": 1.0,
                "tilt_correction_degrees": -1.0,
                "physical_tilt_limits": None,
            }
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            before = path.read_bytes()

            controller = self.make_controller(path)

            venue = controller.state()["venue"]
            self.assertEqual("current-venue", venue["active_venue_id"])
            self.assertEqual("Current Venue", venue["active_venue_name"])
            self.assertFalse(venue["storage_persisted"])
            self.assertEqual(1, len(venue["venues"]))
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(-1.25, controller.config["slots"]["head"]["venue_calibration"]["position_m"]["x"])

    def test_legacy_venue_status_contract_matches_native_status_decoder(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory) / "beatbeam_config.json")

            self.assertEqual({
                "schema_version": 1,
                "active_venue_id": "current-venue",
                "active_venue_name": "Current Venue",
                "switch_requires_rearm": False,
                "storage_persisted": False,
                "venues": [{
                    "id": "current-venue",
                    "name": "Current Venue",
                    "fixture_count": len(controller.config["slots"]),
                    "active": True,
                }],
            }, controller.state()["venue"])

    def test_crud_duplicate_is_deep_and_restart_recovers_active_physical_context(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "beatbeam_config.json"
            controller = self.make_controller(path)
            original_position = {"x": -1.0, "y": 2.0, "z": 3.0}
            controller.update_config({"slot_id": "head", "slot": {
                "mounting_orientation": "NORMAL",
                "address": 30,
                "venue_calibration": {
                    "position_m": original_position,
                    "mounting_height_m": 3.0,
                    "physical_forward": {"x": 0, "y": 1, "z": 0},
                    "physical_up": {"x": 0, "y": 0, "z": 1},
                },
            }})
            original = copy.deepcopy(controller.config["slots"]["head"])

            state = controller.duplicate_venue(name="Room B")
            duplicate_id = next(item["id"] for item in state["venues"] if item["name"] == "Room B")
            controller.switch_venue(duplicate_id)
            controller.update_config({
                "venue_geometry": {
                    "venue_width_m": 30.0,
                    "venue_forward_depth_m": 20.0,
                    "venue_rear_depth_m": 4.0,
                    "audience_target_height_m": 1.3,
                    "ceiling_height_m": 7.0,
                },
                "slot_id": "head",
                "slot": {
                    "address": 150,
                    "mounting_orientation": "ROTATED_180",
                    "venue_calibration": {
                        "position_m": {"x": 4.0, "y": 5.0, "z": 6.0},
                        "pan_correction_degrees": 4.0,
                    },
                },
            })
            duplicate = copy.deepcopy(controller.config["slots"]["head"])
            self.assertEqual("ROTATED_180", duplicate["mounting_orientation"])
            self.assertEqual(150, duplicate["address"])

            controller.switch_venue("current-venue")
            self.assertEqual(original, controller.config["slots"]["head"])
            controller.switch_venue(duplicate_id)
            self.assertEqual(duplicate, controller.config["slots"]["head"])
            self.assertEqual({"x": 4.0, "y": 5.0, "z": 6.0}, duplicate["venue_calibration"]["position_m"])
            controller.flush_config()

            restarted = self.make_controller(path)
            self.assertEqual(duplicate_id, restarted.state()["venue"]["active_venue_id"])
            self.assertEqual(duplicate, restarted.config["slots"]["head"])
            self.assertEqual(2, len(restarted.state()["venue"]["venues"]))

    def test_stage_map_publishes_all_fixture_position_m_across_geometry_venue_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "beatbeam_config.json"
            controller = self.make_controller(path)
            positions = {
                "head": {"x": -1.25, "y": 1.5, "z": 3.0},
                "par": {"x": 1.75, "y": -0.5, "z": 2.25},
            }
            identities = {
                slot_id: {
                    key: controller.config["slots"][slot_id][key]
                    for key in ("fixture", "mode", "address")
                }
                for slot_id in positions
            }
            controller.update_config({
                "slots": {
                    slot_id: {"venue_calibration": {"position_m": position}}
                    for slot_id, position in positions.items()
                },
            })

            def stage_map_positions(subject):
                return {
                    fixture["slot_id"]: fixture["position_m"]
                    for fixture in subject.state()["venue_space"]["fixtures"]
                }

            initial_presentation = stage_map_positions(controller)
            self.assertEqual(positions, {slot_id: initial_presentation[slot_id] for slot_id in positions})
            self.assertEqual("UNSUPPORTED", next(
                fixture["status"]
                for fixture in controller.state()["venue_space"]["fixtures"]
                if fixture["slot_id"] == "par"
            ))

            venue_state = controller.duplicate_venue(name="Different dimensions")
            duplicate_id = next(item["id"] for item in venue_state["venues"] if item["name"] == "Different dimensions")
            controller.switch_venue(duplicate_id)
            controller.update_config({"venue_geometry": {
                "venue_width_m": 24.0,
                "venue_forward_depth_m": 18.0,
                "venue_rear_depth_m": 4.0,
                "audience_target_height_m": 1.2,
                "ceiling_height_m": 6.0,
            }})
            self.assertEqual(positions, {slot_id: stage_map_positions(controller)[slot_id] for slot_id in positions})

            controller.switch_venue("current-venue")
            self.assertEqual(positions, {slot_id: stage_map_positions(controller)[slot_id] for slot_id in positions})
            self.assertEqual(identities, {
                slot_id: {key: controller.config["slots"][slot_id][key] for key in identity}
                for slot_id, identity in identities.items()
            })
            controller.flush_config()

            restarted = self.make_controller(path)
            self.assertEqual("current-venue", restarted.state()["venue"]["active_venue_id"])
            self.assertEqual(positions, {slot_id: stage_map_positions(restarted)[slot_id] for slot_id in positions})
            self.assertEqual(identities, {
                slot_id: {key: restarted.config["slots"][slot_id][key] for key in identity}
                for slot_id, identity in identities.items()
            })

    def test_create_is_empty_and_delete_protects_active_and_final_venue(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory) / "beatbeam_config.json")
            state = controller.create_venue("Empty setup")
            empty_id = next(item["id"] for item in state["venues"] if item["name"] == "Empty setup")
            self.assertEqual(0, next(item["fixture_count"] for item in state["venues"] if item["id"] == empty_id))
            with self.assertRaisesRegex(ValueError, "active venue"):
                controller.delete_venue("current-venue")
            controller.switch_venue(empty_id)
            with self.assertRaisesRegex(ValueError, "active venue"):
                controller.delete_venue(empty_id)
            controller.delete_venue("current-venue")
            with self.assertRaisesRegex(ValueError, "final venue"):
                controller.delete_venue(empty_id)

    def test_invalid_target_never_replaces_active_venue(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory) / "beatbeam_config.json")
            state = controller.duplicate_venue(name="Broken")
            broken_id = next(item["id"] for item in state["venues"] if item["name"] == "Broken")
            controller._venues[broken_id].slots["head"]["address"] = 0
            with self.assertRaises(ValueError):
                controller.switch_venue(broken_id)
            self.assertEqual("current-venue", controller.state()["venue"]["active_venue_id"])

    def test_corrupt_persisted_venue_document_is_preserved_and_blocks_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "beatbeam_config.json"
            controller = self.make_controller(path)
            controller.create_venue("Club A")
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["venues"][0]["slots"]["head"]["mounting_orientation"] = "SIDEWAYS"
            path.write_text(json.dumps(payload), encoding="utf-8")
            before = path.read_bytes()

            restarted = self.make_controller(path)
            restarted.flush_config()

            self.assertEqual("CONFIG_INVALID", restarted.config_persistence_blocked_reason)
            self.assertEqual(before, path.read_bytes())

    def test_connected_switch_sends_old_mapping_safe_frame_and_requires_explicit_rearm(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "beatbeam_config.json"
            controller = self.make_controller(path)
            state = controller.duplicate_venue(name="Address B")
            target_id = next(item["id"] for item in state["venues"] if item["name"] == "Address B")
            controller._venues[target_id].slots["head"]["address"] = 200
            dmx = RecordingDmx()
            controller.dmx = dmx
            controller.connected = True
            controller.running = True
            controller.manual_smoke_active = True
            controller.active_one_shot_cue = {"id": "full_white_flash"}
            controller.movement_lab_authority = {"effect_id": "fast_audience_circle"}

            controller.switch_venue(target_id)

            self.assertTrue(dmx.frames)
            self.assertIn(30, dmx.frames[0])
            self.assertNotIn(200, dmx.frames[0])
            venue = controller.state()["venue"]
            self.assertTrue(venue["switch_requires_rearm"])
            self.assertFalse(controller.manual_smoke_active)
            self.assertIsNone(controller.active_one_shot_cue)
            self.assertIsNone(controller.movement_lab_authority)
            self.assertEqual({}, controller.current_final_values)
            restarted = self.make_controller(path)
            self.assertTrue(restarted.state()["venue"]["switch_requires_rearm"])
            controller.rearm_active_venue()
            self.assertFalse(controller.state()["venue"]["switch_requires_rearm"])
            controller.render_active = True
            controller._render_tick()
            self.assertIn(200, controller.current_final_values)
            self.assertNotIn(30, controller.current_final_values)


if __name__ == "__main__":
    unittest.main()
