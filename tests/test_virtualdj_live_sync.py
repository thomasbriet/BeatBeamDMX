import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from beatbeam_app import (
    PLAYBACK_STATE_SCHEMA_VERSION,
    JsonPlaybackStateSource,
    PlaybackClock,
    PlaybackSourceRead,
    PlaybackStateSnapshot,
    TransportController,
)


class SequenceSource:
    def __init__(self):
        self.snapshot = None
        self.status = "unavailable"

    def read(self):
        return PlaybackSourceRead(self.snapshot, self.status)


def snapshot(
    sequence,
    position=1000,
    bpm=120.0,
    beat_position=0.0,
    beat_number=1,
    bar_number=1,
    track_path="/Music/Track A.flac",
    deck_number=1,
    status="available",
    is_connected=True,
):
    return PlaybackStateSnapshot(
        PLAYBACK_STATE_SCHEMA_VERSION,
        sequence,
        sequence * 1000,
        is_connected,
        status,
        "active_deck" if status == "available" else "none",
        deck_number if status == "available" else None,
        track_path if status == "available" else None,
        bpm if status == "available" else None,
        position if status == "available" else None,
        0.0 if status == "available" else None,
        beat_position if status == "available" else None,
        beat_number if status == "available" else None,
        bar_number if status == "available" else None,
        {"snapshot_latency_milliseconds": 12.0, "error_count": 0},
        None,
    )


class VirtualDjLiveSyncTests(unittest.TestCase):
    def setUp(self):
        self.source = SequenceSource()
        self.clock = PlaybackClock(self.source, grace_seconds=1.0)

    def publish(self, value, at):
        self.source.snapshot = value
        self.source.status = "available"
        return self.clock.state(at)

    def test_normal_playback_interpolates_and_authoritative_snapshot_corrects_drift(self):
        self.publish(snapshot(1, position=1000), 0.0)
        current = self.publish(snapshot(2, position=1250, beat_position=0.5), 0.25)
        self.assertEqual("advancing", current["transport_state"])

        interpolated = self.clock.state(0.35)
        self.assertEqual(1350, interpolated["beatbeam"]["estimated_position_milliseconds"])

        corrected = self.publish(snapshot(3, position=1510, beat_position=1.0), 0.50)
        self.assertEqual(1510, corrected["beatbeam"]["estimated_position_milliseconds"])
        self.assertEqual(0, corrected["delta"]["position_milliseconds"])

    def test_forward_seek_and_hot_cue_jump_replace_anchor_immediately(self):
        self.publish(snapshot(1, position=10_000), 0.0)
        jumped = self.publish(snapshot(2, position=90_000, beat_position=200.0, bar_number=51), 0.25)

        self.assertEqual("position_jump_forward", jumped["last_discontinuity"])
        self.assertEqual("unknown", jumped["transport_state"])
        self.assertEqual(90_000, jumped["beatbeam"]["estimated_position_milliseconds"])

    def test_backward_seek_replaces_anchor_immediately(self):
        self.publish(snapshot(1, position=90_000, beat_position=180.0, bar_number=46), 0.0)
        jumped = self.publish(snapshot(2, position=30_000, beat_position=60.0, bar_number=16), 0.25)

        self.assertEqual("position_jump_backward", jumped["last_discontinuity"])
        self.assertEqual(30_000, jumped["beatbeam"]["estimated_position_milliseconds"])

    def test_track_change_and_deck_switch_do_not_retain_old_anchor(self):
        self.publish(snapshot(1, track_path="/Music/Deck A.flac", deck_number=1, position=20_000), 0.0)
        deck_switched = self.publish(snapshot(2, track_path="/Music/Deck B.flac", deck_number=2, position=40_000), 0.25)

        self.assertEqual("deck_changed", deck_switched["last_discontinuity"])
        self.assertEqual("/Music/Deck B.flac", deck_switched["beatbeam"]["track_path"])
        self.assertEqual(2, deck_switched["beatbeam"]["deck_number"])

        track_changed = self.publish(snapshot(3, track_path="/Music/Deck C.flac", deck_number=2, position=1_000), 0.50)
        self.assertEqual("track_changed", track_changed["last_discontinuity"])
        self.assertEqual("/Music/Deck C.flac", track_changed["beatbeam"]["track_path"])

    def test_current_bpm_change_is_used_for_future_interpolation(self):
        self.publish(snapshot(1, bpm=120.0, position=1000), 0.0)
        self.publish(snapshot(2, bpm=128.0, position=1250, beat_position=0.5), 0.25)

        current = self.clock.state(0.50)
        self.assertEqual(128.0, current["beatbeam"]["bpm"])
        self.assertEqual(1500, current["beatbeam"]["estimated_position_milliseconds"])
        self.assertAlmostEqual(0.5 + (0.25 * 128.0 / 60.0), current["beatbeam"]["beat_position"])

    def test_stationary_snapshot_does_not_run_away_after_grace_period(self):
        self.publish(snapshot(1, position=1000), 0.0)
        stationary = self.publish(snapshot(2, position=1000), 0.25)
        self.assertEqual("stationary", stationary["transport_state"])
        self.assertEqual(1000, self.clock.state(0.75)["beatbeam"]["estimated_position_milliseconds"])

        unavailable = self.clock.state(1.30)
        self.assertEqual("unavailable", unavailable["availability"])
        self.assertIsNone(unavailable["beatbeam"])

    def test_disconnect_then_reconnect_discards_the_old_clock(self):
        self.publish(snapshot(1, position=5000), 0.0)
        disconnected = self.publish(snapshot(2, status="disconnected", is_connected=False), 0.25)
        self.assertEqual("disconnected", disconnected["availability"])
        self.assertIsNone(disconnected["beatbeam"])

        reconnected = self.publish(snapshot(3, position=75_000, track_path="/Music/Reconnected.flac"), 0.50)
        self.assertEqual("available", reconnected["availability"])
        self.assertEqual("reconnected", reconnected["last_discontinuity"])
        self.assertEqual(75_000, reconnected["beatbeam"]["estimated_position_milliseconds"])

    def test_unknown_track_path_still_has_timing_and_beat_bar_values(self):
        first = self.publish(
            snapshot(1, track_path="/Other/Unknown Éxample.flac", position=1000, beat_number=4, bar_number=9),
            0.0,
        )
        self.assertEqual("/Other/Unknown Éxample.flac", first["beatbeam"]["track_path"])
        second = self.publish(
            snapshot(2, track_path="/Other/Unknown Éxample.flac", position=1250, beat_number=1, bar_number=10),
            0.25,
        )
        self.assertEqual(1, second["beatbeam"]["beat_number"])
        self.assertEqual(10, second["beatbeam"]["bar_number"])

    def test_beat_and_bar_advance_from_an_advancing_anchor(self):
        self.publish(snapshot(1, position=1000, beat_number=4, bar_number=9), 0.0)
        self.publish(snapshot(2, position=1250, beat_number=1, bar_number=10), 0.25)

        estimated = self.clock.state(0.75)
        self.assertEqual(2, estimated["beatbeam"]["beat_number"])
        self.assertEqual(10, estimated["beatbeam"]["bar_number"])

    def test_json_source_requires_the_versioned_generic_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
            invalid = JsonPlaybackStateSource(path).read()
            self.assertEqual("invalid", invalid.status)

            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "sequence": 1,
                        "captured_at_unix_milliseconds": 1,
                        "is_connected": True,
                        "status": "available",
                        "selection": "active_deck",
                        "deck_number": 1,
                        "track_path": "/Music/O'Brien - Café.flac",
                        "bpm": 120.0,
                        "position_milliseconds": 1000,
                        "first_beat_milliseconds": 0.0,
                        "beat_position": 0.0,
                        "beat_number": 1,
                        "bar_number": 1,
                        "metrics": {"snapshot_latency_milliseconds": 5.0, "error_count": 0},
                        "error_kind": None,
                    }
                ),
                encoding="utf-8",
            )
            valid = JsonPlaybackStateSource(path).read()
            self.assertEqual("available", valid.status)
            self.assertEqual("/Music/O'Brien - Café.flac", valid.snapshot.track_path)

    def test_developer_source_switch_and_snapshot_path_are_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "transport.json"
            snapshot_path = Path(directory) / "virtualdj.json"
            fake_osc = SimpleNamespace(lock=threading.RLock(), decks={})
            with patch("beatbeam_app.TRANSPORT_CONFIG_PATH", config_path):
                first = TransportController(fake_osc)
                first.update_developer_playback(
                    {"source": "virtualdj", "snapshot_path": str(snapshot_path)}
                )
                reloaded = TransportController(fake_osc)

            self.assertEqual("virtualdj", reloaded.config["developer_playback_source"])
            self.assertEqual(str(snapshot_path), reloaded.config["developer_playback_state_path"])


if __name__ == "__main__":
    unittest.main()
