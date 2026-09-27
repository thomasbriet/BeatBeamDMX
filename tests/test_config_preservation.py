import json
import tempfile
import threading
import unittest
from pathlib import Path

from beatbeam_app import DmxController


class _Osc:
    def snapshot_for_render(self):
        return {"stale": True, "beat_value": 0.0, "bpm": 120.0}

    def developer_playback_state(self):
        return {"source": "none"}


def fixture_config(slot_id, address, x, *, legacy_position=False):
    slot = DmxController.default_slot_config(
        slot_id,
        fixture_id="shehds_led_wash_7x12w_rgbw_moving_head",
        mode="15ch",
        address=address,
    )
    slot["venue_calibration"] = {
        "version": 3 if legacy_position else 4,
        "position_m": None if legacy_position else {"x": x, "y": 2.5, "z": 3.0},
        "position": {"x": x / 5.0, "y": 0.25},
        "mounting_height_m": 3.0,
        "physical_forward": {"x": 0.0, "y": 1.0, "z": 0.0},
        "physical_up": {"x": 0.0, "y": 0.0, "z": 1.0},
        "pan_correction_degrees": 2.5,
        "tilt_correction_degrees": -1.5,
        "physical_tilt_limits": {
            "min_deg": -70.0,
            "center_deg": 0.0,
            "max_deg": 65.0,
        },
    }
    slot["compatible_unknown_fixture_field"] = f"owned-{slot_id}"
    return slot


def config_with_slots(slot_count, *, legacy_position=False):
    slot_ids = [f"fixture_{index + 1}" for index in range(slot_count)]
    slots = {
        slot_id: fixture_config(
            slot_id,
            1 + index * 16,
            -1.5 + index,
            legacy_position=legacy_position,
        )
        for index, slot_id in enumerate(slot_ids)
    }
    return {
        "active_slot": slot_ids[0] if slot_ids else "",
        "blackout_active": False,
        "master_dimmer": 1.0,
        "production_show_mode": "BASELINE_ONLY",
        "venue_geometry": {
            "venue_width_m": 10.0,
            "venue_forward_depth_m": 10.0,
            "venue_rear_depth_m": 2.0,
            "audience_target_height_m": 1.0,
            "ceiling_height_m": 4.0,
        },
        "auto_show": {},
        "slot_order": slot_ids,
        "slots": slots,
        "compatible_unknown_top_level": "preserve-me",
    }


class ConfigPreservationTests(unittest.TestCase):
    def test_existing_small_valid_config_keeps_physical_fixture_state(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "beatbeam_config.json"
            expected = config_with_slots(2)
            config_path.write_text(json.dumps(expected), encoding="utf-8")

            controller = DmxController(_Osc(), config_path=config_path)
            controller.disconnect()
            persisted = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertEqual(expected["slot_order"], persisted["slot_order"])
            for slot_id in expected["slot_order"]:
                self.assertEqual(expected["slots"][slot_id]["fixture"], persisted["slots"][slot_id]["fixture"])
                self.assertEqual(expected["slots"][slot_id]["address"], persisted["slots"][slot_id]["address"])
                self.assertEqual(
                    expected["slots"][slot_id]["venue_calibration"]["position_m"],
                    persisted["slots"][slot_id]["venue_calibration"]["position_m"],
                )
                self.assertEqual(
                    expected["slots"][slot_id]["venue_calibration"]["physical_tilt_limits"],
                    persisted["slots"][slot_id]["venue_calibration"]["physical_tilt_limits"],
                )
                self.assertEqual(
                    expected["slots"][slot_id]["compatible_unknown_fixture_field"],
                    persisted["slots"][slot_id]["compatible_unknown_fixture_field"],
                )
            self.assertEqual("preserve-me", persisted["compatible_unknown_top_level"])

    def test_existing_larger_valid_config_remains_authoritative(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "beatbeam_config.json"
            expected = config_with_slots(5)
            config_path.write_text(json.dumps(expected), encoding="utf-8")

            controller = DmxController(_Osc(), config_path=config_path)
            controller.flush_config()

            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(expected["slot_order"], persisted["slot_order"])
            self.assertEqual(
                [expected["slots"][slot_id]["address"] for slot_id in expected["slot_order"]],
                [persisted["slots"][slot_id]["address"] for slot_id in persisted["slot_order"]],
            )

    def test_missing_config_initializes_only_at_explicit_test_path(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "nested" / "beatbeam_config.json"
            controller = DmxController(_Osc(), config_path=config_path)
            self.assertFalse(config_path.exists())
            controller.disconnect()
            self.assertTrue(config_path.exists())
            self.assertEqual(["head", "par"], json.loads(config_path.read_text())["slot_order"])

    def test_corrupt_config_is_preserved_and_shutdown_cannot_replace_it(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "beatbeam_config.json"
            corrupt = b'{"slots": '
            config_path.write_bytes(corrupt)

            controller = DmxController(_Osc(), config_path=config_path)
            self.assertEqual("CONFIG_LOAD_FAILED", controller.config_persistence_blocked_reason)
            controller.config["master_dimmer"] = 0.25
            controller.shutdown()

            self.assertEqual(corrupt, config_path.read_bytes())
            self.assertFalse(config_path.with_suffix(".tmp").exists())

    def test_structurally_invalid_config_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "beatbeam_config.json"
            invalid = json.dumps({"slot_order": [], "slots": []}).encode()
            config_path.write_bytes(invalid)

            controller = DmxController(_Osc(), config_path=config_path)
            self.assertEqual("CONFIG_INVALID", controller.config_persistence_blocked_reason)
            controller.flush_config()

            self.assertEqual(invalid, config_path.read_bytes())

    def test_unknown_fixture_identity_is_preserved_instead_of_defaulted(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "beatbeam_config.json"
            invalid = config_with_slots(1)
            invalid["slots"]["fixture_1"]["fixture"] = "unknown-user-fixture"
            original = json.dumps(invalid, sort_keys=True).encode()
            config_path.write_bytes(original)

            controller = DmxController(_Osc(), config_path=config_path)
            self.assertEqual("CONFIG_INVALID", controller.config_persistence_blocked_reason)
            controller.disconnect()

            self.assertEqual(original, config_path.read_bytes())

    def test_positive_legacy_position_migration_is_lossless_for_protected_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "beatbeam_config.json"
            legacy = config_with_slots(1, legacy_position=True)
            config_path.write_text(json.dumps(legacy), encoding="utf-8")

            controller = DmxController(_Osc(), config_path=config_path)
            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            slot_id = legacy["slot_order"][0]
            before_slot = legacy["slots"][slot_id]
            after_slot = persisted["slots"][slot_id]

            self.assertIsNone(controller.config_persistence_blocked_reason)
            self.assertEqual(before_slot["fixture"], after_slot["fixture"])
            self.assertEqual(before_slot["address"], after_slot["address"])
            self.assertEqual(before_slot["venue_calibration"]["position"], after_slot["venue_calibration"]["position"])
            self.assertEqual(before_slot["venue_calibration"]["physical_tilt_limits"], after_slot["venue_calibration"]["physical_tilt_limits"])
            self.assertEqual(before_slot["compatible_unknown_fixture_field"], after_slot["compatible_unknown_fixture_field"])
            self.assertEqual("preserve-me", persisted["compatible_unknown_top_level"])
            self.assertIsNotNone(after_slot["venue_calibration"]["position_m"])

    def test_explicit_zero_fixture_config_is_not_replaced_with_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "beatbeam_config.json"
            expected = config_with_slots(0)
            config_path.write_text(json.dumps(expected), encoding="utf-8")

            controller = DmxController(_Osc(), config_path=config_path)
            self.assertEqual([], controller.config["slot_order"])
            self.assertEqual({}, controller.config["slots"])
            controller.disconnect()

            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual([], persisted["slot_order"])
            self.assertEqual({}, persisted["slots"])

    def test_disconnect_writes_only_the_injected_test_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sentinel_path = root / "authoritative-user-config.json"
            sentinel = b"DO-NOT-TOUCH"
            sentinel_path.write_bytes(sentinel)
            test_path = root / "isolated" / "beatbeam_config.json"

            controller = DmxController(_Osc(), config_path=test_path)
            controller.disconnect()

            self.assertEqual(sentinel, sentinel_path.read_bytes())
            self.assertTrue(test_path.exists())

    def test_parallel_instances_have_independent_atomic_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / "one" / "config.json", root / "two" / "config.json"]
            controllers = [DmxController(_Osc(), config_path=path) for path in paths]
            controllers[0].config["compatible_unknown_top_level"] = "one"
            controllers[1].config["compatible_unknown_top_level"] = "two"

            threads = [threading.Thread(target=controller.disconnect) for controller in controllers]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2.0)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual("one", json.loads(paths[0].read_text())["compatible_unknown_top_level"])
            self.assertEqual("two", json.loads(paths[1].read_text())["compatible_unknown_top_level"])


if __name__ == "__main__":
    unittest.main()
