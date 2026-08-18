import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from beatbeam_app import (
    PLAYBACK_STATE_SCHEMA_VERSION,
    JsonPlaybackStateSource,
    PlaybackClock,
    PlaybackPositionReference,
    PlaybackQueryTiming,
    PlaybackSourceRead,
    PlaybackStateSnapshot,
    PlaybackTimingSnapshot,
    TransportController,
    DmxController,
    VirtualDjBeatPulsePlan,
    VirtualDjBeatPulsePlanner,
    VirtualDjBeatPulseScheduler,
    playback_system_monotonic_time,
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
    timing=None,
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
        timing,
    )


def timing(sampled_at, snapshot_started=None, snapshot_completed=None, position_reference=None):
    snapshot_started = sampled_at - 50 if snapshot_started is None else snapshot_started
    snapshot_completed = sampled_at + 50 if snapshot_completed is None else snapshot_completed
    return PlaybackTimingSnapshot(
        "system_monotonic_milliseconds",
        snapshot_started,
        snapshot_completed,
        sampled_at,
        snapshot_completed,
        (PlaybackQueryTiming("PositionMilliseconds", sampled_at - 50, sampled_at + 50),),
        position_reference,
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

    def test_timed_sample_is_projected_from_midpoint_to_consumption_time(self):
        self.publish(snapshot(1, position=1000, timing=timing(0)), 0.050)
        accepted = self.publish(snapshot(2, position=1250, beat_position=0.5, timing=timing(250)), 0.500)

        self.assertEqual("advancing", accepted["transport_state"])
        self.assertEqual(1500, accepted["beatbeam"]["estimated_position_milliseconds"])
        self.assertEqual(250.0, accepted["timing"]["sample_age_at_receive_milliseconds"])
        self.assertEqual("system_monotonic", accepted["timing"]["alignment"])
        self.assertEqual(1600, self.clock.state(0.600)["beatbeam"]["estimated_position_milliseconds"])

    def test_stationary_timed_snapshot_is_not_projected(self):
        self.publish(snapshot(1, position=1000, timing=timing(0)), 0.050)
        stationary = self.publish(snapshot(2, position=1000, timing=timing(250)), 0.500)

        self.assertEqual("stationary", stationary["transport_state"])
        self.assertEqual(1000, stationary["beatbeam"]["estimated_position_milliseconds"])

    def test_phase_and_bar_progression_cross_beat_four_to_one(self):
        self.publish(snapshot(1, position=1000, beat_position=3.5, beat_number=4, bar_number=9, timing=timing(0)), 0.050)
        self.publish(snapshot(2, position=1250, beat_position=4.0, beat_number=1, bar_number=10, timing=timing(250)), 0.300)

        state = self.clock.state(0.500)

        self.assertEqual(0.5, state["beatbeam"]["beat_phase"])
        self.assertEqual(1, state["beatbeam"]["beat_number"])
        self.assertEqual(10, state["beatbeam"]["bar_number"])
        self.assertEqual(250.0, state["beatbeam"]["time_until_next_beat_milliseconds"])
        self.assertEqual(1750.0, state["beatbeam"]["time_until_next_bar_milliseconds"])

    def test_local_beat_four_to_one_increments_the_bar(self):
        self.publish(snapshot(1, position=1000, beat_position=3.0, beat_number=4, bar_number=9, timing=timing(0)), 0.050)
        self.publish(snapshot(2, position=1250, beat_position=3.5, beat_number=4, bar_number=9, timing=timing(250)), 0.300)

        state = self.clock.state(0.500)

        self.assertEqual(1, state["beatbeam"]["beat_number"])
        self.assertEqual(10, state["beatbeam"]["bar_number"])
        self.assertEqual(0.0, state["beatbeam"]["beat_phase"])

    def test_small_timing_error_is_not_a_discontinuity(self):
        self.publish(snapshot(1, position=1000, timing=timing(0)), 0.050)
        accepted = self.publish(snapshot(2, position=1260, beat_position=0.52, timing=timing(250)), 0.300)

        self.assertEqual("advancing", accepted["transport_state"])
        self.assertIsNone(accepted["last_discontinuity"])

    def test_independent_position_reference_records_raw_and_compensated_delta(self):
        self.publish(snapshot(1, position=1000, timing=timing(0)), 0.050)
        reference = PlaybackPositionReference(
            1350,
            350,
            PlaybackQueryTiming("PositionMilliseconds", 300, 400),
        )
        self.publish(snapshot(2, position=1250, beat_position=0.5, timing=timing(250, position_reference=reference)), 0.350)

        metrics = self.clock.state(0.350)["metrics"]
        self.assertEqual(100.0, metrics["raw_position_delta_milliseconds"]["mean"])
        self.assertEqual(0.0, metrics["compensated_position_delta_milliseconds"]["mean"])

    def test_timing_with_an_unrelated_monotonic_epoch_falls_back_without_runaway(self):
        self.publish(snapshot(1, position=1000, timing=timing(10_000)), 0.050)
        second = self.publish(snapshot(2, position=1250, beat_position=0.5, timing=timing(10_250)), 0.300)

        self.assertEqual("untrusted_clock_epoch", second["timing"]["alignment"])
        self.assertEqual(1250, second["beatbeam"]["estimated_position_milliseconds"])

    def test_clock_uses_monotonic_time_not_the_wall_clock(self):
        self.source.snapshot = snapshot(1, position=1000)
        with patch("beatbeam_app.playback_system_monotonic_time", return_value=0.0), patch("beatbeam_app.time.time", return_value=1.0):
            self.clock.state()
        self.source.snapshot = snapshot(2, position=1250, beat_position=0.5)
        with patch("beatbeam_app.playback_system_monotonic_time", return_value=0.25), patch("beatbeam_app.time.time", return_value=9_999_999_999.0):
            self.clock.state()
        with patch("beatbeam_app.playback_system_monotonic_time", return_value=0.35), patch("beatbeam_app.time.time", return_value=-9_999_999_999.0):
            state = self.clock.state()

        self.assertEqual(1350, state["beatbeam"]["estimated_position_milliseconds"])

    def test_system_clock_prefers_the_shared_uptime_clock(self):
        with patch("beatbeam_app.time.clock_gettime", return_value=123.456) as clock_gettime:
            self.assertEqual(123.456, playback_system_monotonic_time())

        self.assertEqual(getattr(__import__("time"), "CLOCK_UPTIME_RAW"), clock_gettime.call_args.args[0])

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

            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["timing"] = {
                "clock": "system_monotonic_milliseconds",
                "snapshot_started_at_monotonic_milliseconds": 200,
                "snapshot_completed_at_monotonic_milliseconds": 100,
                "sampled_at_monotonic_milliseconds": 150,
                "published_at_monotonic_milliseconds": 200,
                "query_timings": [],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual("invalid", JsonPlaybackStateSource(path).read().status)

            payload["timing"] = {
                "clock": "system_monotonic_milliseconds",
                "snapshot_started_at_monotonic_milliseconds": 100,
                "snapshot_completed_at_monotonic_milliseconds": 300,
                "sampled_at_monotonic_milliseconds": 200,
                "published_at_monotonic_milliseconds": 300,
                "query_timings": [
                    {
                        "field": "PositionMilliseconds",
                        "request_started_at_monotonic_milliseconds": 150,
                        "response_received_at_monotonic_milliseconds": 250,
                    }
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            parsed = JsonPlaybackStateSource(path).read()
            self.assertEqual("available", parsed.status)
            self.assertEqual(200, parsed.snapshot.timing.sampled_at_monotonic_milliseconds)

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

    def test_structure_behavior_source_is_separate_from_playback_source_and_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "transport.json"
            fake_osc = FakeLegacyPlaybackSource()
            with patch("beatbeam_app.TRANSPORT_CONFIG_PATH", config_path):
                first = TransportController(fake_osc)
                first.update_config({
                    "active_playback_source": "virtualdj",
                    "structure_behavior_source": "song_analyzer",
                })
                reloaded = TransportController(fake_osc)

            self.assertEqual("virtualdj", reloaded.config["active_playback_source"])
            self.assertEqual("song_analyzer", reloaded.structure_behavior_source())
            reloaded.update_config({"structure_behavior_source": "not-a-source"})
            self.assertEqual("legacy", reloaded.structure_behavior_source())


def pulse_state(
    *,
    track_path="/Music/Track A.flac",
    deck_number=1,
    bar_number=8,
    beat_number=2,
    milliseconds_until_bar=500.0,
    transport_state="advancing",
    availability="available",
    discontinuity=None,
):
    return {
        "source": "virtualdj",
        "availability": availability,
        "transport_state": transport_state,
        "last_discontinuity": discontinuity,
        "timing": {"alignment": "system_monotonic"},
        "beatbeam": {
            "track_path": track_path,
            "deck_number": deck_number,
            "bar_number": bar_number,
            "beat_number": beat_number,
            "time_until_next_bar_milliseconds": milliseconds_until_bar,
        },
    }


class FakeDmxOutput:
    def __init__(self):
        self.frames = []

    def send(self, values):
        self.frames.append(dict(values))

    def close(self):
        pass


class FailFirstDmxOutput(FakeDmxOutput):
    def __init__(self):
        super().__init__()
        self.fail_next_send = True

    def send(self, values):
        self.frames.append(dict(values))
        if self.fail_next_send:
            self.fail_next_send = False
            raise RuntimeError("test output failure")


class FakeDmxTransport:
    def __init__(self, playback_state):
        self.playback_state = playback_state
        self.lock = threading.RLock()
        self.decks = {}

    def snapshot_for_render(self):
        return {
            "bpm": 120.0,
            "beat_value": 0.0,
            "phrase_current": "verse",
            "strobe_active": False,
        }

    def developer_playback_state(self):
        return self.playback_state


class FakeLegacyPlaybackSource:
    def __init__(self, render_snapshot=None):
        self.lock = threading.RLock()
        self.decks = {}
        self.render_snapshot = dict(render_snapshot or {
            "bpm": 128.0,
            "beat": 1.5,
            "beat_value": 0.5,
            "beat_display": 1.5,
            "time_seconds": 12.5,
            "time_display_seconds": 12.5,
            "phrase_current": "chorus",
            "phrase_next": "chorus",
            "track_title": "Legacy Track",
            "track_artist": "Legacy Artist",
            "track_album": "Legacy Album",
            "waveform_energy": 0.7,
            "waveform_bands": {"low": 0.7, "mid": 0.5, "high": 0.3},
            "waveform_lookahead": {"2": {}, "4": {}},
            "waveform_analysis": {},
            "audio_bands": {"low": 0.7, "mid": 0.5, "high": 0.3},
            "audio_drums": {},
            "drum_signals": {},
            "strobe_active": False,
            "strobe_count_in": None,
            "stale": False,
        })

    def snapshot_for_render(self):
        return dict(self.render_snapshot)

    def state(self):
        return dict(self.render_snapshot)


class FakeDeveloperPlayback:
    def __init__(self, state):
        self.current_state = state
        self.reset_count = 0

    def state(self):
        return self.current_state

    def reset(self):
        self.reset_count += 1


def virtualdj_state(
    *,
    path="/Music/Track A.flac",
    deck=1,
    position=12_500,
    bpm=128.0,
    beat_position=0.5,
    beat_number=1,
    bar_number=4,
    transport_state="advancing",
    availability="available",
    discontinuity=None,
):
    return {
        "source": "virtualdj",
        "availability": availability,
        "transport_state": transport_state,
        "last_discontinuity": discontinuity,
        "selection": "active_deck",
        "beatbeam": (
            {
                "track_path": path,
                "deck_number": deck,
                "estimated_position_milliseconds": position,
                "bpm": bpm,
                "beat_position": beat_position,
                "beat_number": beat_number,
                "bar_number": bar_number,
                "beat_phase": beat_position % 1.0,
            }
            if availability == "available"
            else None
        ),
    }


class ActivePlaybackSourceTests(unittest.TestCase):
    def make_transport(self, virtualdj=None):
        legacy = FakeLegacyPlaybackSource()
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "transport.json"
            with patch("beatbeam_app.TRANSPORT_CONFIG_PATH", config_path):
                transport = TransportController(legacy)
        transport.config = transport._clean_config(transport.default_config())
        transport._save_config = lambda _config: None
        transport.developer_playback = FakeDeveloperPlayback(
            virtualdj or virtualdj_state()
        )
        return transport, legacy

    def test_exactly_one_active_source_is_persisted_and_switching_resets_old_clock(self):
        transport, _legacy = self.make_transport()

        self.assertEqual("legacy", transport.config["active_playback_source"])
        transport.update_config({"active_playback_source": "virtualdj"})
        self.assertEqual("virtualdj", transport.config["active_playback_source"])
        self.assertEqual(1, transport.developer_playback.reset_count)

        transport.update_config({"active_playback_source": "legacy"})
        self.assertEqual("legacy", transport.config["active_playback_source"])
        self.assertEqual(2, transport.developer_playback.reset_count)

    def test_equivalent_legacy_and_virtualdj_trace_has_the_same_transport_values(self):
        transport, _legacy = self.make_transport()
        legacy = transport.snapshot_for_render()

        transport.update_config({"active_playback_source": "virtualdj"})
        virtualdj = transport.snapshot_for_render()

        for key in ("bpm", "beat", "beat_value", "beat_display", "time_seconds"):
            self.assertEqual(legacy[key], virtualdj[key], key)
        self.assertEqual("virtualdj", virtualdj["_active_playback_source"])
        self.assertEqual("/Music/Track A.flac", virtualdj["track_path"])

    def test_equivalent_trace_preserves_existing_beat_driven_rendering(self):
        transport, _legacy = self.make_transport()
        legacy = transport.snapshot_for_render()
        transport.update_config({"active_playback_source": "virtualdj"})
        virtualdj = transport.snapshot_for_render()

        legacy_controller = DmxController(transport)
        virtualdj_controller = DmxController(transport)
        config = legacy_controller._clean_full_config(legacy_controller.default_config())
        auto_show = legacy_controller._auto_show_state(legacy, config["auto_show"])
        legacy_values = legacy_controller._render_values(
            1000.0, config=config, osc=legacy, auto_show=auto_show
        )
        virtual_values = virtualdj_controller._render_values(
            1000.0,
            config=config,
            osc=virtualdj,
            auto_show=virtualdj_controller._auto_show_state(virtualdj, config["auto_show"]),
        )

        self.assertEqual(legacy_values, virtual_values)

    def test_virtualdj_pause_keeps_the_timeline_stationary(self):
        paused = virtualdj_state(position=55_000, beat_position=16.0, beat_number=1, transport_state="stationary")
        transport, _legacy = self.make_transport(paused)
        transport.update_config({"active_playback_source": "virtualdj"})

        first = transport.snapshot_for_render()
        second = transport.snapshot_for_render()
        self.assertEqual(55.0, first["time_display_seconds"])
        self.assertEqual(first["time_display_seconds"], second["time_display_seconds"])
        self.assertEqual(16.0, second["beat_value"])

    def test_seek_track_and_deck_changes_create_new_engine_generations(self):
        transport, _legacy = self.make_transport()
        transport.update_config({"active_playback_source": "virtualdj"})
        first = transport.snapshot_for_render()

        transport.developer_playback.current_state = virtualdj_state(
            position=120_000,
            beat_position=256.0,
            bar_number=65,
            discontinuity="position_jump_forward",
        )
        jumped = transport.snapshot_for_render()
        self.assertGreater(jumped["_playback_generation"], first["_playback_generation"])
        self.assertEqual("position_jump_forward", jumped["_playback_event"])

        transport.developer_playback.current_state = virtualdj_state(
            path="/Music/Deck B.flac",
            deck=2,
            position=2_000,
            bar_number=2,
            discontinuity="deck_changed",
        )
        switched = transport.snapshot_for_render()
        self.assertGreater(switched["_playback_generation"], jumped["_playback_generation"])
        self.assertEqual("/Music/Deck B.flac", switched["track_path"])

    def test_current_virtualdj_bpm_is_the_only_active_tempo(self):
        transport, _legacy = self.make_transport(virtualdj_state(bpm=126.0))
        transport.update_config({"active_playback_source": "virtualdj"})
        self.assertEqual(126.0, transport.snapshot_for_render()["bpm"])

        transport.developer_playback.current_state = virtualdj_state(bpm=131.0)
        self.assertEqual(131.0, transport.snapshot_for_render()["bpm"])

    def test_virtualdj_keeps_the_existing_native_transport_contract(self):
        transport, _legacy = self.make_transport(virtualdj_state(bpm=125.0))
        transport.update_config({"active_playback_source": "virtualdj"})

        state = transport.transport_state()
        for key in (
            "mode",
            "resolved_mode",
            "manual_bpm",
            "effective_bpm",
            "manual_phrase",
            "manual_phrase_label",
            "idle_animation_enabled",
            "tap_count",
            "tap_locked",
            "external_available",
        ):
            self.assertIn(key, state)
        self.assertEqual("virtualdj", state["resolved_mode"])
        self.assertEqual(125.0, state["effective_bpm"])

        source = transport.source_state()
        self.assertEqual("virtualdj", source["resolved_mode"])
        self.assertIsNone(source["port"])

    def test_virtualdj_disconnect_stops_music_timeline_and_clears_track_identity(self):
        transport, _legacy = self.make_transport()
        transport.update_config({"active_playback_source": "virtualdj"})
        transport.snapshot_for_render()
        transport.developer_playback.current_state = virtualdj_state(
            availability="disconnected",
            discontinuity="disconnected",
        )

        stopped = transport.snapshot_for_render()
        self.assertTrue(stopped["stale"])
        self.assertIsNone(stopped["bpm"])
        self.assertIsNone(stopped["track_path"])
        self.assertEqual("disconnected", stopped["_playback_event"])

    def test_unknown_virtualdj_track_cannot_fall_back_to_another_tracks_structure(self):
        transport, _legacy = self.make_transport()
        transport.update_config({"active_playback_source": "virtualdj"})
        controller = DmxController(transport)
        controller._all_track_preview_summaries = lambda: [
            {
                "title": "Different Track",
                "artist": "Someone Else",
                "segments": [{"index": 0}],
            }
        ]

        self.assertIsNone(
            controller._track_show_plan_for_osc(
                transport.snapshot_for_render(), "adaptive"
            )
        )

    def test_virtualdj_reuses_only_an_exact_path_matched_track_plan(self):
        transport, _legacy = self.make_transport()
        transport.update_config({"active_playback_source": "virtualdj"})
        controller = DmxController(transport)
        expected = {"segments": [{"section": "chorus"}]}
        controller._all_track_preview_summaries = lambda: [
            {"track_path": "/Music/Track A.flac", "segments": [{"index": 0}]},
            {"track_path": "/Music/Other.flac", "segments": [{"index": 0}]},
        ]
        controller._track_show_plan_for_summary = lambda summary, _style: (
            expected if summary.get("track_path") == "/Music/Track A.flac" else None
        )

        self.assertIs(
            expected,
            controller._track_show_plan_for_osc(
                transport.snapshot_for_render(), "adaptive"
            ),
        )

    def test_engine_runtime_is_reset_once_for_a_new_active_generation(self):
        transport, _legacy = self.make_transport()
        controller = DmxController(transport)
        controller.motion_states["head"] = {"value": 1}
        controller.slot_rhythm_states["head"] = {"mode": "beat_flash"}
        controller.active_one_shot_cue = {"id": "hit"}

        controller._observe_active_playback_generation(transport.snapshot_for_render())
        transport.update_config({"active_playback_source": "virtualdj"})
        controller._observe_active_playback_generation(transport.snapshot_for_render())

        self.assertEqual({}, controller.motion_states)
        self.assertEqual({}, controller.slot_rhythm_states)
        self.assertIsNone(controller.active_one_shot_cue)
        self.assertEqual(1, controller.playback_runtime_resets)


class VirtualDjBeatPulseTests(unittest.TestCase):
    def test_planner_targets_the_next_bar_beat_one_with_a_monotonic_deadline(self):
        plan, reason = VirtualDjBeatPulsePlanner.plan(
            pulse_state(bar_number=12, beat_number=3, milliseconds_until_bar=375.0),
            now=10.0,
            duration_milliseconds=100,
        )

        self.assertIsNone(reason)
        self.assertEqual((1, "/Music/Track A.flac", 13, 1), plan.identity)
        self.assertEqual(10.375, plan.deadline_monotonic_seconds)

    def test_planner_never_schedules_the_current_beats_two_three_or_four(self):
        for current_beat in (1, 2, 3, 4):
            with self.subTest(current_beat=current_beat):
                plan, reason = VirtualDjBeatPulsePlanner.plan(
                    pulse_state(bar_number=12, beat_number=current_beat, milliseconds_until_bar=250.0),
                    now=10.0,
                    duration_milliseconds=100,
                )

                self.assertIsNone(reason)
                self.assertEqual((1, "/Music/Track A.flac", 13, 1), plan.identity)

    def test_planner_does_not_create_pulses_for_stationary_or_discontinuous_transport(self):
        stationary, stationary_reason = VirtualDjBeatPulsePlanner.plan(
            pulse_state(transport_state="stationary"), 10.0, 100
        )
        jumped, jumped_reason = VirtualDjBeatPulsePlanner.plan(
            pulse_state(discontinuity="position_jump_forward"), 10.0, 100
        )

        self.assertIsNone(stationary)
        self.assertEqual("transport_not_advancing", stationary_reason)
        self.assertIsNone(jumped)
        self.assertEqual("awaiting_fresh_anchor", jumped_reason)

    def test_tempo_or_fresh_anchor_can_correct_the_future_deadline(self):
        first, _ = VirtualDjBeatPulsePlanner.plan(
            pulse_state(milliseconds_until_bar=500.0), 10.0, 100
        )
        corrected, _ = VirtualDjBeatPulsePlanner.plan(
            pulse_state(milliseconds_until_bar=420.0), 10.0, 100
        )

        self.assertEqual(first.identity, corrected.identity)
        self.assertEqual(10.500, first.deadline_monotonic_seconds)
        self.assertEqual(10.420, corrected.deadline_monotonic_seconds)

    def test_scheduler_deduplicates_multiple_updates_for_the_same_bar(self):
        dispatched = []
        completed = threading.Event()

        def dispatch(plan, generation, is_current):
            if not is_current(plan, generation):
                return None
            dispatched.append(plan.identity)
            completed.set()
            return time.monotonic()

        scheduler = VirtualDjBeatPulseScheduler(dispatch, lambda _reason: None, clock=time.monotonic)
        scheduler.start("par", 100)
        state = pulse_state(milliseconds_until_bar=30.0)
        scheduler.observe(state)
        scheduler.observe(state)
        scheduler.observe(state)

        self.assertTrue(completed.wait(0.5))
        scheduler.stop()
        self.assertEqual([(1, "/Music/Track A.flac", 9, 1)], dispatched)
        status = scheduler.state()
        self.assertEqual(1, status["scheduled_events"])
        self.assertEqual(1, status["executed_events"])
        self.assertEqual(0, status["duplicate_events"])
        self.assertEqual(1, status["last_event"]["beat_number"])
        self.assertEqual(9, status["last_event"]["bar_number"])
        self.assertIsNotNone(status["last_event"]["scheduler_wake_monotonic_milliseconds"])
        self.assertIsNotNone(status["last_event"]["dmx_dispatch_monotonic_milliseconds"])

    def test_scheduler_allows_the_next_bar_after_one_pulse(self):
        dispatched = []
        completed = threading.Event()

        def dispatch(plan, generation, is_current):
            if not is_current(plan, generation):
                return None
            dispatched.append(plan.identity)
            if len(dispatched) == 2:
                completed.set()
            return time.monotonic()

        scheduler = VirtualDjBeatPulseScheduler(dispatch, lambda _reason: None, clock=time.monotonic)
        scheduler.start("par", 100)
        scheduler.observe(pulse_state(bar_number=8, milliseconds_until_bar=20.0))
        deadline = time.monotonic() + 0.5
        while len(dispatched) < 1 and time.monotonic() < deadline:
            completed.wait(0.01)
        scheduler.observe(pulse_state(bar_number=9, milliseconds_until_bar=20.0))

        self.assertTrue(completed.wait(0.5))
        scheduler.stop()
        self.assertEqual(
            [
                (1, "/Music/Track A.flac", 9, 1),
                (1, "/Music/Track A.flac", 10, 1),
            ],
            dispatched,
        )

    def test_scheduler_dispatches_a_due_bar_before_a_refresh_can_replace_it(self):
        clock_now = [10.0]
        dispatched = []
        completed = threading.Event()

        def dispatch(plan, generation, is_current):
            if not is_current(plan, generation):
                return None
            dispatched.append(plan.identity)
            completed.set()
            return clock_now[0]

        scheduler = VirtualDjBeatPulseScheduler(dispatch, lambda _reason: None, clock=lambda: clock_now[0])
        scheduler.start("par", 100)
        scheduler.observe(pulse_state(bar_number=8, milliseconds_until_bar=500.0))

        # Simulate a 30 fps UI refresh immediately after the bar boundary. The
        # refresh naturally plans bar 10, but bar 9 must still be dispatched.
        clock_now[0] = 10.501
        scheduler.observe(pulse_state(bar_number=9, milliseconds_until_bar=500.0))

        self.assertTrue(completed.wait(0.25))
        scheduler.stop()
        self.assertEqual([(1, "/Music/Track A.flac", 9, 1)], dispatched)

    def test_scheduler_cancels_a_pending_event_when_playback_pauses(self):
        dispatched = threading.Event()
        cancelled = []

        def dispatch(plan, generation, is_current):
            if is_current(plan, generation):
                dispatched.set()
                return time.monotonic()
            return None

        scheduler = VirtualDjBeatPulseScheduler(dispatch, cancelled.append, clock=time.monotonic)
        scheduler.start("par", 100)
        scheduler.observe(pulse_state(milliseconds_until_bar=180.0))
        scheduler.observe(pulse_state(transport_state="stationary"))

        self.assertFalse(dispatched.wait(0.25))
        self.assertIn("transport_not_advancing", cancelled)
        self.assertGreaterEqual(scheduler.state()["cancelled_stale_events"], 1)
        scheduler.stop()

    def test_scheduler_discards_a_stale_track_plan_and_reanchors_to_the_new_deck(self):
        dispatched = []
        completed = threading.Event()

        def dispatch(plan, generation, is_current):
            if is_current(plan, generation):
                dispatched.append(plan.identity)
                completed.set()
                return time.monotonic()
            return None

        scheduler = VirtualDjBeatPulseScheduler(dispatch, lambda _reason: None, clock=time.monotonic)
        scheduler.start("par", 100)
        scheduler.observe(pulse_state(milliseconds_until_bar=220.0))
        scheduler.observe(
            pulse_state(
                track_path="/Music/Track B.flac",
                deck_number=2,
                bar_number=15,
                milliseconds_until_bar=25.0,
            )
        )

        self.assertTrue(completed.wait(0.5))
        scheduler.stop()
        self.assertEqual([(2, "/Music/Track B.flac", 16, 1)], dispatched)
        self.assertGreaterEqual(scheduler.state()["cancelled_stale_events"], 1)

    def test_scheduler_waits_for_a_fresh_plan_after_discontinuity_then_resumes(self):
        dispatched = []
        completed = threading.Event()
        cancelled = []

        def dispatch(plan, generation, is_current):
            if is_current(plan, generation):
                dispatched.append(plan.identity)
                completed.set()
                return time.monotonic()
            return None

        scheduler = VirtualDjBeatPulseScheduler(dispatch, cancelled.append, clock=time.monotonic)
        scheduler.start("par", 100)
        scheduler.observe(pulse_state(milliseconds_until_bar=180.0))
        scheduler.observe(pulse_state(discontinuity="position_jump_backward"))
        scheduler.observe(pulse_state(bar_number=11, milliseconds_until_bar=25.0))

        self.assertTrue(completed.wait(0.5))
        scheduler.stop()
        self.assertEqual([(1, "/Music/Track A.flac", 12, 1)], dispatched)
        self.assertIn("awaiting_fresh_anchor", cancelled)

    def test_scheduler_cancels_pending_events_for_both_seek_directions(self):
        for discontinuity in ("position_jump_forward", "position_jump_backward"):
            with self.subTest(discontinuity=discontinuity):
                cancelled = []
                scheduler = VirtualDjBeatPulseScheduler(
                    lambda *_args: None,
                    cancelled.append,
                    clock=time.monotonic,
                )
                scheduler.start("par", 100)
                scheduler.observe(pulse_state(milliseconds_until_bar=180.0))
                scheduler.observe(pulse_state(discontinuity=discontinuity))

                self.assertIn("awaiting_fresh_anchor", cancelled)
                self.assertFalse(scheduler.state()["pending"])
                scheduler.stop()

    def test_scheduler_cancels_on_disconnect_then_uses_only_a_fresh_reconnect_plan(self):
        dispatched = []
        completed = threading.Event()
        cancelled = []

        def dispatch(plan, generation, is_current):
            if is_current(plan, generation):
                dispatched.append(plan.identity)
                completed.set()
                return time.monotonic()
            return None

        scheduler = VirtualDjBeatPulseScheduler(dispatch, cancelled.append, clock=time.monotonic)
        scheduler.start("par", 100)
        scheduler.observe(pulse_state(milliseconds_until_bar=180.0))
        scheduler.observe(pulse_state(availability="unavailable"))
        scheduler.observe(pulse_state(bar_number=17, milliseconds_until_bar=25.0))

        self.assertTrue(completed.wait(0.5))
        scheduler.stop()
        self.assertIn("source_unavailable", cancelled)
        self.assertEqual([(1, "/Music/Track A.flac", 18, 1)], dispatched)

    def test_scheduler_handles_deck_one_to_two_to_one_without_old_events(self):
        dispatched = []
        two_dispatched = threading.Event()
        one_dispatched_again = threading.Event()

        def dispatch(plan, generation, is_current):
            if not is_current(plan, generation):
                return None
            dispatched.append(plan.identity)
            if len(dispatched) == 1:
                two_dispatched.set()
            if len(dispatched) == 2:
                one_dispatched_again.set()
            return time.monotonic()

        scheduler = VirtualDjBeatPulseScheduler(dispatch, lambda _reason: None, clock=time.monotonic)
        scheduler.start("par", 100)
        scheduler.observe(pulse_state(deck_number=1, bar_number=8, milliseconds_until_bar=220.0))
        scheduler.observe(pulse_state(deck_number=2, bar_number=14, milliseconds_until_bar=25.0))
        self.assertTrue(two_dispatched.wait(0.5))
        scheduler.observe(pulse_state(deck_number=1, bar_number=20, milliseconds_until_bar=25.0))
        self.assertTrue(one_dispatched_again.wait(0.5))
        scheduler.stop()

        self.assertEqual(
            [
                (2, "/Music/Track A.flac", 15, 1),
                (1, "/Music/Track A.flac", 21, 1),
            ],
            dispatched,
        )

    def test_direct_dmx_pulse_attempts_to_restore_the_baseline_after_a_send_failure(self):
        state = pulse_state()
        transport = FakeDmxTransport(state)
        with tempfile.TemporaryDirectory() as directory, patch(
            "beatbeam_app.CONFIG_PATH", Path(directory) / "config.json"
        ):
            controller = DmxController(transport)
        controller.config = controller._clean_full_config(controller.default_config())
        output = FailFirstDmxOutput()
        controller.dmx = output
        controller.connected = True
        controller.running = True
        controller.current_values = {1: 37, 2: 99}
        controller.virtualdj_beat_pulse_scheduler.start("par", 100)
        plan = VirtualDjBeatPulsePlan(
            (1, "/Music/Track A.flac", 9, 1),
            playback_system_monotonic_time(),
            "/Music/Track A.flac",
            1,
            9,
            100,
        )

        dispatched_at = controller._dispatch_virtualdj_beat_pulse(
            plan,
            1,
            lambda _plan, _generation: True,
        )
        controller.virtualdj_beat_pulse_scheduler.stop()

        self.assertIsNone(dispatched_at)
        self.assertIsNone(controller.active_virtualdj_beat_pulse)
        self.assertEqual({1: 37, 2: 99}, output.frames[-1])
        self.assertIn("test output failure", controller.error)

    def test_direct_dmx_pulse_uses_fixture_intensity_and_restores_the_previous_frame(self):
        state = pulse_state()
        transport = FakeDmxTransport(state)
        with tempfile.TemporaryDirectory() as directory, patch(
            "beatbeam_app.CONFIG_PATH", Path(directory) / "config.json"
        ):
            controller = DmxController(transport)
        controller.config = controller._clean_full_config(controller.default_config())
        output = FakeDmxOutput()
        controller.dmx = output
        controller.connected = True
        controller.running = True
        controller.current_values = {1: 37, 2: 99}
        controller.virtualdj_beat_pulse_scheduler.start("par", 100)
        plan = VirtualDjBeatPulsePlan(
            (1, "/Music/Track A.flac", 9, 1),
            playback_system_monotonic_time(),
            "/Music/Track A.flac",
            1,
            9,
            100,
        )

        dispatched_at = controller._dispatch_virtualdj_beat_pulse(
            plan,
            1,
            lambda _plan, _generation: True,
        )
        channels = controller._virtualdj_pulse_channels_locked(
            controller._clean_full_config(dict(controller.config)), "par"
        )
        controller._cancel_virtualdj_beat_pulse("stopped_by_user")
        controller.virtualdj_beat_pulse_scheduler.stop()

        self.assertIsNotNone(dispatched_at)
        self.assertTrue(all(output.frames[0][channel] == 255 for channel in channels))
        self.assertEqual({1: 37, 2: 99}, output.frames[-1])

    def test_preview_pulse_uses_the_same_scheduler_without_sending_a_dmx_frame(self):
        state = pulse_state()
        transport = FakeDmxTransport(state)
        with tempfile.TemporaryDirectory() as directory, patch(
            "beatbeam_app.CONFIG_PATH", Path(directory) / "config.json"
        ):
            controller = DmxController(transport)
        controller.config = controller._clean_full_config(controller.default_config())
        output = FakeDmxOutput()
        controller.dmx = output

        controller.virtualdj_beat_pulse_preview_scheduler.start("par", 500)
        plan = VirtualDjBeatPulsePlan(
            (1, "/Music/Track A.flac", 9, 1),
            playback_system_monotonic_time(),
            "/Music/Track A.flac",
            1,
            9,
            500,
        )
        dispatched_at = controller._dispatch_virtualdj_beat_pulse_preview(
            plan,
            1,
            lambda _plan, _generation: True,
        )

        previews = controller._build_slot_previews(
            controller._clean_full_config(dict(controller.config)),
            transport.snapshot_for_render(),
            time.time(),
        )
        pulsed = controller._apply_virtualdj_beat_pulse_preview_overlay_locked(previews)
        controller._cancel_virtualdj_beat_pulse_preview("stopped_by_user")
        restored = controller._apply_virtualdj_beat_pulse_preview_overlay_locked(previews)
        controller.virtualdj_beat_pulse_preview_scheduler.stop()

        self.assertIsNotNone(dispatched_at)
        self.assertEqual([], output.frames)
        self.assertEqual(255, pulsed["par"]["brightness"])
        self.assertEqual(255, pulsed["par"]["red"])
        self.assertTrue(pulsed["par"]["developer_virtualdj_beat_pulse_preview"])
        self.assertEqual(previews, restored)


if __name__ == "__main__":
    unittest.main()
