#!/usr/bin/env python3
import argparse
import atexit
import colorsys
import json
import math
import mimetypes
import os
import secrets
import shutil
import socket
import struct
import subprocess
import threading
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from enttec_open_dmx import (
    DMX_CHANNELS,
    EnttecOpenDmx,
    clamp_dmx,
    find_fixture,
    find_mode,
    load_fixture_profiles,
    values_for_fixture,
)


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
APP_NAME = os.environ.get("BEATBEAM_APP_NAME") or "BeatBeam DMX"
APP_SLUG = os.environ.get("BEATBEAM_APP_SLUG") or "".join(ch for ch in APP_NAME if ch.isalnum()) or "BeatBeamDMX"
CONFIG_PATH = Path(os.environ.get("BEATBEAM_CONFIG_PATH") or (ROOT / "beatbeam_config.json"))
TRANSPORT_CONFIG_PATH = Path(
    os.environ.get("BEATBEAM_TRANSPORT_CONFIG_PATH") or (ROOT / "beatbeam_transport.json")
)
REMOTE_ACCESS_PATH = Path(os.environ.get("BEATBEAM_REMOTE_ACCESS_PATH") or (ROOT / "beatbeam_remote.json"))
TRIGGER_LOG_PATH = Path(os.environ.get("BEATBEAM_TRIGGER_LOG_PATH") or "/tmp/beatbeam-trigger.log")
TRACK_PREVIEW_CACHE_DIR = Path(
    os.environ.get("BEATBEAM_TRACK_PREVIEW_CACHE_DIR")
    or (Path.home() / "Library/Application Support" / "BeatBeamDMX" / "track_preview_cache")
)
TRACK_PREVIEW_CACHE_FALLBACK_DIR = (
    Path.home() / "Library/Application Support" / "BeatBeamDMX-user" / "track_preview_cache"
)
REMOTE_ADDRESS_CACHE_TTL = 3.0
DEFAULT_HTTP_PORT = 8780
DEFAULT_OSC_PORT = 4461
DEFAULT_DMX_FPS = 30.0
API_SCHEMA_VERSION = 4
DEFAULT_MANUAL_BPM = 124.0
DEFAULT_MANUAL_PHRASE = "verse"
PLAYBACK_STATE_SCHEMA_VERSION = 1
PLAYBACK_CLOCK_GRACE_SECONDS = 1.0
PLAYBACK_STATIONARY_TOLERANCE_MS = 45.0
PLAYBACK_DISCONTINUITY_MINIMUM_MS = 750.0
DEFAULT_VIRTUALDJ_BEAT_PULSE_DURATION_MILLISECONDS = 100
MINIMUM_VIRTUALDJ_BEAT_PULSE_DURATION_MILLISECONDS = 40
MAXIMUM_VIRTUALDJ_BEAT_PULSE_DURATION_MILLISECONDS = 500
# A state refresh can arrive just after a scheduled downbeat. Keep that
# already-due plan briefly so the refresh cannot replace it with the following
# bar before the scheduler thread has dispatched it.
MAXIMUM_VIRTUALDJ_BEAT_PULSE_LATE_DISPATCH_MILLISECONDS = 100
DEFAULT_VIRTUALDJ_PLAYBACK_STATE_PATH = (
    Path.home() / "Library/Application Support/MusicAnalyzer/virtualdj-playback.json"
)
SONG_ANALYZER_STRUCTURE_SCHEMA_VERSION = 2
SONG_ANALYZER_STRUCTURE_LEGACY_SCHEMA_VERSION = 1
SONG_ANALYZER_RICH_ANALYSIS_MODEL = "SongAnalyzerRichAnalysis"
SONG_ANALYZER_ENERGY_SCALE = "segment-normalized-rms-z-score"
# The source energy is a normalized-RMS z-score, not absolute loudness. Its
# effect is deliberately a small bounded modifier to the existing Auto Show.
SONG_ANALYZER_ENERGY_Z_SCORE_MODIFIER_PER_UNIT = 0.04
SONG_ANALYZER_MAX_ENERGY_MODIFIER = 0.08
DEFAULT_SONG_ANALYZER_STRUCTURE_PATH = Path(
    os.environ.get("BEATBEAM_SONG_ANALYZER_STRUCTURE_PATH")
    or (Path.home() / "Library/Application Support/MusicAnalyzer/beatbeam-structure-plan.json")
)
DEFAULT_SONG_ANALYZER_BRIDGE_SOCKET_PATH = Path(
    os.environ.get("BEATBEAM_SONG_ANALYZER_BRIDGE_SOCKET_PATH")
    or (Path.home() / "Library/Application Support/MusicAnalyzer/VirtualDJ/bridge.sock")
)
FIXTURE_LIBRARY = load_fixture_profiles()
SERVER_HOST = "127.0.0.1"
SERVER_PORT = DEFAULT_HTTP_PORT
REMOTE_ACCESS_CONFIG = None
REMOTE_ADDRESS_CACHE = {"updated_at": 0.0, "state": None}


def canonical_song_analyzer_track_path(value):
    """Mirror the handoff's absolute lexical path contract without resolving symlinks or case."""
    text = str(value or "").strip()
    if not text:
        return None
    return os.path.normpath(os.path.abspath(os.path.expanduser(text)))


@dataclass(frozen=True)
class SongAnalyzerStructureSegment:
    index: int
    start_seconds: float
    end_seconds: float
    label: str
    confidence: Optional[float] = None
    start_bar: Optional[int] = None
    end_bar: Optional[int] = None


@dataclass(frozen=True)
class SongAnalyzerRichSegment:
    index: int
    start_seconds: float
    end_seconds: float
    label: str
    level: str
    energy: float
    confidence: Optional[float] = None
    start_beat: Optional[int] = None
    end_beat: Optional[int] = None
    start_bar: Optional[int] = None
    end_bar: Optional[int] = None


@dataclass(frozen=True)
class SongAnalyzerStructureTrack:
    canonical_path: str
    content_sha256: Optional[str]
    analysis_hash: Optional[str]
    analysis_version: Optional[str]
    phrase_analysis_version: Optional[str]
    availability: str
    model: str
    segments: tuple
    rich_model: Optional[str] = None
    rich_energy_scale: Optional[str] = None
    rich_segments: tuple = ()


@dataclass(frozen=True)
class SongAnalyzerActiveTrack:
    canonical_path: str
    deck: int
    status: str
    generation: int
    activated_at_unix_milliseconds: Optional[int] = None


class SongAnalyzerStructureHandoff:
    """Read-only cached consumer for SongAnalyzer's small versioned structure index.

    This class has no link to the renderer or DMX controller. It is queried only
    by developer diagnostics, while the existing transport remains authoritative.
    """

    def __init__(self, path=DEFAULT_SONG_ANALYZER_STRUCTURE_PATH, check_interval_seconds=1.0):
        self.path = Path(path)
        self.check_interval_seconds = max(0.0, float(check_interval_seconds))
        self._lock = threading.RLock()
        self._last_check = 0.0
        self._signature = object()
        self._tracks = {}
        self._active_track = None
        self._schema_version = None
        self._load_status = "missing"
        self._load_error = None
        self._last_track_path = None
        self._metrics = {
            "structure_loads": 0,
            "cache_hits": 0,
            "lookup_failures": 0,
            "parse_failures": 0,
            "schema_failures": 0,
            "track_switches": 0,
        }

    @staticmethod
    def _number(value, name, minimum=None):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"{name} is invalid")
        number = float(value)
        if minimum is not None and number < minimum:
            raise ValueError(f"{name} is invalid")
        return number

    @staticmethod
    def _optional_text(value, name):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{name} is invalid")
        value = value.strip()
        return value or None

    @classmethod
    def _parse_document(cls, raw):
        if not isinstance(raw, dict):
            raise ValueError("document is invalid")
        schema = raw.get("schema_version")
        if isinstance(schema, bool) or not isinstance(schema, int) or schema not in {
            SONG_ANALYZER_STRUCTURE_LEGACY_SCHEMA_VERSION, SONG_ANALYZER_STRUCTURE_SCHEMA_VERSION
        }:
            raise RuntimeError("unsupported_schema")
        tracks_raw = raw.get("tracks")
        if not isinstance(tracks_raw, list):
            raise ValueError("tracks is invalid")
        tracks = {}
        for track_raw in tracks_raw:
            if not isinstance(track_raw, dict):
                raise ValueError("track is invalid")
            canonical_path = cls._optional_text(track_raw.get("canonical_path"), "canonical_path")
            if not canonical_path or canonical_song_analyzer_track_path(canonical_path) != canonical_path:
                raise ValueError("canonical_path is not canonical")
            if canonical_path in tracks:
                raise ValueError("canonical_path is duplicated")
            availability = track_raw.get("availability")
            if availability not in {"current", "stale", "missing"}:
                raise ValueError("availability is invalid")
            structure = track_raw.get("structure")
            if not isinstance(structure, dict):
                raise ValueError("structure is invalid")
            model = cls._optional_text(structure.get("model"), "structure.model")
            segments_raw = structure.get("segments")
            if not model or not isinstance(segments_raw, list):
                raise ValueError("structure is incomplete")
            if availability in {"current", "stale"} and not segments_raw:
                raise ValueError("available structure is empty")
            segments = []
            previous_end = -math.inf
            for expected_index, segment_raw in enumerate(segments_raw):
                if not isinstance(segment_raw, dict) or segment_raw.get("index") != expected_index:
                    raise ValueError("segment index is invalid")
                start = cls._number(segment_raw.get("start_seconds"), "segment.start_seconds", 0.0)
                end = cls._number(segment_raw.get("end_seconds"), "segment.end_seconds", 0.0)
                label = cls._optional_text(segment_raw.get("label"), "segment.label")
                if not label or end <= start or start < previous_end:
                    raise ValueError("segment timing is invalid")
                confidence = segment_raw.get("confidence")
                if confidence is not None:
                    confidence = cls._number(confidence, "segment.confidence", 0.0)
                    if confidence > 100.0:
                        raise ValueError("segment.confidence is invalid")
                start_bar = segment_raw.get("start_bar")
                end_bar = segment_raw.get("end_bar")
                if start_bar is not None and (isinstance(start_bar, bool) or not isinstance(start_bar, int) or start_bar < 1):
                    raise ValueError("segment.start_bar is invalid")
                if end_bar is not None and (isinstance(end_bar, bool) or not isinstance(end_bar, int) or end_bar <= 1):
                    raise ValueError("segment.end_bar is invalid")
                segments.append(SongAnalyzerStructureSegment(
                    expected_index, start, end, label, confidence, start_bar, end_bar
                ))
                previous_end = end
            rich_model = None
            rich_energy_scale = None
            rich_segments = ()
            rich = track_raw.get("rich_analysis")
            if rich is not None:
                if schema != SONG_ANALYZER_STRUCTURE_SCHEMA_VERSION or not isinstance(rich, dict):
                    raise ValueError("rich_analysis is invalid")
                rich_model = cls._optional_text(rich.get("model"), "rich_analysis.model")
                rich_energy_scale = cls._optional_text(rich.get("energy_scale"), "rich_analysis.energy_scale")
                rich_raw = rich.get("segments")
                if rich_model != SONG_ANALYZER_RICH_ANALYSIS_MODEL or rich_energy_scale != SONG_ANALYZER_ENERGY_SCALE \
                        or not isinstance(rich_raw, list):
                    raise ValueError("rich_analysis is incomplete")
                rich_values = []
                rich_previous_end = -math.inf
                for expected_index, segment_raw in enumerate(rich_raw):
                    if not isinstance(segment_raw, dict) or segment_raw.get("index") != expected_index:
                        raise ValueError("rich segment index is invalid")
                    start = cls._number(segment_raw.get("start_seconds"), "rich segment.start_seconds", 0.0)
                    end = cls._number(segment_raw.get("end_seconds"), "rich segment.end_seconds", 0.0)
                    label = cls._optional_text(segment_raw.get("label"), "rich segment.label")
                    level = cls._optional_text(segment_raw.get("level"), "rich segment.level")
                    energy = cls._number(segment_raw.get("energy"), "rich segment.energy")
                    confidence = segment_raw.get("confidence")
                    if confidence is not None:
                        confidence = cls._number(confidence, "rich segment.confidence", 0.0)
                        if confidence > 100.0:
                            raise ValueError("rich segment.confidence is invalid")
                    if not label or not level or end <= start or start < rich_previous_end:
                        raise ValueError("rich segment timing is invalid")
                    rich_values.append(SongAnalyzerRichSegment(
                        expected_index, start, end, label, level, energy, confidence,
                        segment_raw.get("start_beat"), segment_raw.get("end_beat"),
                        segment_raw.get("start_bar"), segment_raw.get("end_bar"),
                    ))
                    rich_previous_end = end
                rich_segments = tuple(rich_values)
            tracks[canonical_path] = SongAnalyzerStructureTrack(
                canonical_path,
                cls._optional_text(track_raw.get("content_sha256"), "content_sha256"),
                cls._optional_text(track_raw.get("analysis_hash"), "analysis_hash"),
                cls._optional_text(track_raw.get("analysis_version"), "analysis_version"),
                cls._optional_text(track_raw.get("phrase_analysis_version"), "phrase_analysis_version"),
                availability,
                model,
                tuple(segments), rich_model, rich_energy_scale, rich_segments,
            )
        active_raw = raw.get("active_track")
        active = None
        if active_raw is not None:
            if not isinstance(active_raw, dict):
                raise ValueError("active_track is invalid")
            active_path = cls._optional_text(active_raw.get("canonical_path"), "active_track.canonical_path")
            deck = active_raw.get("deck")
            status = active_raw.get("status")
            generation = active_raw.get("generation", 0)
            activated_at = active_raw.get("activated_at_unix_milliseconds")
            if not active_path or canonical_song_analyzer_track_path(active_path) != active_path \
                    or isinstance(deck, bool) or not isinstance(deck, int) or deck < 1 \
                    or status not in {"ready", "pending", "unavailable"} \
                    or isinstance(generation, bool) or not isinstance(generation, int) or generation < 0 \
                    or activated_at is not None and (isinstance(activated_at, bool) or not isinstance(activated_at, int) or activated_at < 0):
                raise ValueError("active_track is invalid")
            active = SongAnalyzerActiveTrack(active_path, deck, status, generation, activated_at)
        return schema, tracks, active

    def _file_signature(self):
        try:
            stat = self.path.stat()
            return stat.st_mtime_ns, stat.st_size
        except FileNotFoundError:
            return None
        except OSError as exc:
            return ("error", type(exc).__name__)

    def _refresh(self, force=False):
        now = time.monotonic()
        if not force and now - self._last_check < self.check_interval_seconds:
            return
        self._last_check = now
        signature = self._file_signature()
        if signature == self._signature:
            self._metrics["cache_hits"] += 1
            return
        self._signature = signature
        self._tracks = {}
        self._active_track = None
        self._schema_version = None
        self._load_error = None
        if signature is None:
            self._load_status = "missing"
            return
        if isinstance(signature, tuple) and signature[0] == "error":
            self._load_status = "unreadable"
            self._load_error = signature[1]
            self._metrics["parse_failures"] += 1
            return
        self._metrics["structure_loads"] += 1
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                schema, tracks, active = self._parse_document(json.load(handle))
            self._schema_version = schema
            self._tracks = tracks
            self._active_track = active
            self._load_status = "ready"
        except RuntimeError as exc:
            self._load_status = "unsupported_schema"
            self._load_error = str(exc)
            self._metrics["schema_failures"] += 1
        except Exception as exc:
            self._load_status = "invalid"
            self._load_error = type(exc).__name__
            self._metrics["parse_failures"] += 1

    @staticmethod
    def _segment_state(segment, position):
        duration = max(0.0, segment.end_seconds - segment.start_seconds)
        return {
            "index": segment.index,
            "label": segment.label,
            "start_seconds": segment.start_seconds,
            "end_seconds": segment.end_seconds,
            "start_bar": segment.start_bar,
            "end_bar": segment.end_bar,
            "confidence": segment.confidence,
            "elapsed_seconds": max(0.0, position - segment.start_seconds),
            "remaining_seconds": max(0.0, segment.end_seconds - position),
            "starts_in_seconds": max(0.0, segment.start_seconds - position),
            "progress": min(1.0, max(0.0, (position - segment.start_seconds) / duration)) if duration else 0.0,
        }

    @staticmethod
    def _rich_segment_state(segment, position):
        duration = max(0.0, segment.end_seconds - segment.start_seconds)
        return {
            "index": segment.index,
            "label": segment.label,
            "level": segment.level,
            "energy": segment.energy,
            "confidence": segment.confidence,
            "start_seconds": segment.start_seconds,
            "end_seconds": segment.end_seconds,
            "progress": min(1.0, max(0.0, (position - segment.start_seconds) / duration)) if duration else 0.0,
        }

    def project(self, playback):
        # The renderer and developer endpoint use this same cache concurrently.
        # Serialize refresh/projection so a reload cannot expose a half-updated
        # in-memory index to a DMX frame.
        with self._lock:
            state = dict(playback or {})
            source = state.get("_active_playback_source")
            raw_path = state.get("track_path")
            canonical_path = canonical_song_analyzer_track_path(raw_path)
            track_changed = canonical_path != self._last_track_path
            if track_changed:
                self._last_track_path = canonical_path
                self._metrics["track_switches"] += 1
            self._refresh(force=track_changed)
            result = {
                "source": "song_analyzer" if source == "virtualdj" else "none",
                "contract_path": str(self.path),
                "schema_version": self._schema_version,
                "load_status": self._load_status,
                "load_error": self._load_error,
                "track_match": "none",
                "availability": "inactive" if source != "virtualdj" else "unavailable",
                "projection_status": "unknown",
                "canonical_track_path": canonical_path,
                "analysis_version": None,
                "phrase_analysis_version": None,
                "model": None,
                "active_track": None,
                "rich_analysis": None,
                "rich_current": None,
                "segment_count": 0,
                "current": None,
                "previous": None,
                "next": None,
                "metrics": dict(self._metrics),
            }
            if source != "virtualdj":
                return result
            if self._load_status != "ready":
                return result
            active = self._active_track
            if active is not None:
                result["active_track"] = {
                    "canonical_path": active.canonical_path,
                    "deck": active.deck,
                    "status": active.status,
                    "generation": active.generation,
                    "activated_at_unix_milliseconds": active.activated_at_unix_milliseconds,
                }
                if active.status != "ready":
                    result["availability"] = active.status
                    result["track_match"] = "active_not_ready"
                    return result
                # The native VirtualDJ activation is the authoritative identity
                # when its lightweight live state has not supplied track_path
                # yet.  If a live path is available, retain the strict exact
                # match so a stale persisted active track can never project.
                if not canonical_path:
                    canonical_path = active.canonical_path
                    result["canonical_track_path"] = canonical_path
                elif active.canonical_path != canonical_path:
                    result["track_match"] = "not_active"
                    return result
            elif not canonical_path:
                return result
            track = self._tracks.get(canonical_path)
            if track is None:
                self._metrics["lookup_failures"] += 1
                result["metrics"] = dict(self._metrics)
                return result
            result.update({
                "track_match": "exact",
                "availability": "available_current" if track.availability == "current" else (
                    "available_stale" if track.availability == "stale" else "unavailable"
                ),
                "analysis_version": track.analysis_version,
                "phrase_analysis_version": track.phrase_analysis_version,
                "model": track.model,
                "segment_count": len(track.segments),
            })
            if track.rich_segments:
                result["rich_analysis"] = {
                    "model": track.rich_model,
                    "energy_scale": track.rich_energy_scale,
                    "segment_count": len(track.rich_segments),
                }
            if track.availability == "missing":
                return result
            position = state.get("time_seconds")
            if isinstance(position, bool) or not isinstance(position, (int, float)) or not math.isfinite(float(position)):
                result["projection_status"] = "position_unavailable"
                return result
            position = float(position)
            if not track.segments:
                return result
            if position < track.segments[0].start_seconds:
                result["projection_status"] = "before_structure"
                result["next"] = self._segment_state(track.segments[0], position)
                return result
            for index, segment in enumerate(track.segments):
                is_final_end = index == len(track.segments) - 1 and position == segment.end_seconds
                if segment.start_seconds <= position < segment.end_seconds or is_final_end:
                    result["projection_status"] = "in_final_segment" if is_final_end else "in_segment"
                    result["current"] = self._segment_state(segment, position)
                    if index < len(track.rich_segments):
                        rich = track.rich_segments[index]
                        if rich.start_seconds <= position <= rich.end_seconds:
                            result["rich_current"] = self._rich_segment_state(rich, position)
                    if index:
                        result["previous"] = self._segment_state(track.segments[index - 1], position)
                    if index + 1 < len(track.segments):
                        result["next"] = self._segment_state(track.segments[index + 1], position)
                    return result
                if index + 1 < len(track.segments) and position < track.segments[index + 1].start_seconds:
                    result["projection_status"] = "between_segments"
                    result["previous"] = self._segment_state(segment, position)
                    result["next"] = self._segment_state(track.segments[index + 1], position)
                    return result
            result["projection_status"] = "after_structure"
            result["previous"] = self._segment_state(track.segments[-1], position)
            return result


class SongAnalyzerBridgeDiagnostics:
    """Small read-only diagnostics client with a one-second bounded cache."""

    def __init__(self, socket_path=DEFAULT_SONG_ANALYZER_BRIDGE_SOCKET_PATH, refresh_seconds=1.0):
        self.socket_path = str(socket_path)
        self.refresh_seconds = max(0.5, float(refresh_seconds))
        self._lock = threading.Lock()
        self._next_refresh = 0.0
        self._snapshot = {"status": "unavailable", "error": None, "diagnostics": None}

    def snapshot(self):
        with self._lock:
            now = time.monotonic()
            if now < self._next_refresh:
                return dict(self._snapshot)
            self._next_refresh = now + self.refresh_seconds
            try:
                request = json.dumps({"protocolVersion": 1, "requestId": "beatbeam-debug", "type": "diagnostics"}) + "\n"
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(0.2)
                    client.connect(self.socket_path)
                    client.sendall(request.encode("utf-8"))
                    payload = client.recv(65536)
                response = json.loads(payload.decode("utf-8"))
                diagnostics = response.get("diagnostics") if response.get("success") else None
                self._snapshot = {
                    "status": "connected" if isinstance(diagnostics, dict) else "unavailable",
                    "error": None if isinstance(diagnostics, dict) else "invalid_response",
                    "diagnostics": diagnostics if isinstance(diagnostics, dict) else None,
                }
            except Exception as exc:
                self._snapshot = {"status": "unavailable", "error": type(exc).__name__, "diagnostics": None}
            return dict(self._snapshot)


def playback_system_monotonic_time():
    """Use the macOS uptime clock shared with .NET Environment.TickCount64."""
    clock_id = getattr(time, "CLOCK_UPTIME_RAW", None)
    if clock_id is not None:
        try:
            return time.clock_gettime(clock_id)
        except OSError:
            pass
    return time.monotonic()


def _track_preview_cache_dirs():
    dirs = [TRACK_PREVIEW_CACHE_DIR]
    if "BEATBEAM_TRACK_PREVIEW_CACHE_DIR" not in os.environ:
        dirs.append(TRACK_PREVIEW_CACHE_FALLBACK_DIR)
    ordered = []
    seen = set()
    for path in dirs:
        path_str = str(path)
        if path_str in seen:
            continue
        seen.add(path_str)
        ordered.append(path)
    return ordered


def _track_preview_cache_dir_is_writable(path):
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False
    probe = path / ".beatbeam_write_test"
    try:
        with probe.open("w", encoding="utf-8") as handle:
            handle.write("ok")
    except Exception:
        return False
    with suppress(Exception):
        probe.unlink()
    return True


def track_preview_cache_write_dir():
    for path in _track_preview_cache_dirs():
        if _track_preview_cache_dir_is_writable(path):
            return path
    return _track_preview_cache_dirs()[0]


def track_preview_summary_existing_paths_for_cache_key(cache_key):
    paths = []
    name = f"{str(cache_key or '').strip()}.json"
    for cache_dir in _track_preview_cache_dirs():
        path = cache_dir / name
        try:
            if path.exists():
                paths.append(path)
        except OSError:
            continue
    return paths


def track_preview_summary_best_path_for_cache_key(cache_key):
    existing = []
    for path in track_preview_summary_existing_paths_for_cache_key(cache_key):
        try:
            existing.append((path.stat().st_mtime, path))
        except OSError:
            continue
    if existing:
        existing.sort(key=lambda item: item[0], reverse=True)
        return existing[0][1]
    return track_preview_cache_write_dir() / f"{str(cache_key or '').strip()}.json"


class TriggerLogger:
    def __init__(self, path=TRIGGER_LOG_PATH):
        self.path = Path(path)
        self.lock = threading.Lock()

    def log(self, event, **fields):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        millis = int((time.time() % 1.0) * 1000.0)
        parts = [f"{key}={self._format_value(value)}" for key, value in fields.items()]
        line = f"{timestamp}.{millis:03d} {event}"
        if parts:
            line += " " + " ".join(parts)
        line += "\n"
        with self.lock:
            try:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
            except Exception:
                pass

    @staticmethod
    def _format_value(value):
        if value is None:
            return "-"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float):
            return f"{value:.4f}"
        text = str(value).strip().replace("\n", " ")
        return text if text else "-"


TRIGGER_LOG = TriggerLogger()

COLOR_PRESETS = {
    "manual": None,
    "intro": (70, 145, 255, 0),
    "verse": (50, 190, 120, 0),
    "build": (255, 190, 40, 0),
    "chorus": (255, 70, 135, 0),
    "drop": (255, 55, 170, 0),
    "break": (60, 80, 255, 0),
    "outro": (255, 110, 45, 0),
    "low": (45, 90, 255, 0),
    "mid": (60, 210, 150, 0),
    "high": (255, 70, 80, 0),
}

COLOR_BANKS = {
    1: (70, 145, 255, 0),
    2: (130, 210, 255, 0),
    3: (255, 235, 180, 80),
    4: (255, 90, 55, 0),
    5: (190, 120, 255, 0),
    6: (255, 70, 160, 0),
    7: (40, 255, 225, 0),
    8: (255, 255, 255, 255),
}

VIVID_COLOR_ANCHORS = [
    (255, 0, 0, 0),
    (255, 120, 0, 0),
    (255, 220, 0, 0),
    (0, 255, 0, 0),
    (0, 255, 255, 0),
    (0, 80, 255, 0),
    (170, 0, 255, 0),
    (255, 0, 180, 0),
]

PURE_SHOW_COLORS = [
    (255, 0, 0, 0),
    (0, 255, 0, 0),
    (0, 0, 255, 0),
    (255, 0, 180, 0),
    (0, 255, 255, 0),
    (255, 140, 0, 0),
]

FIXTURE_PRESETS = {
    "shehds_flat_par_12x3w_rgbw": {
        "label_base": "PAR",
        "mode": "8ch",
        "color_source": "phrase",
    },
    "generic_smart_bee_eye_pattern_moving_head": {
        "label_base": "Bee Eye Head",
        "mode": "15ch",
        "color_source": "phrase",
    },
    "shehds_led_wash_7x12w_rgbw_moving_head": {
        "label_base": "Moving Head",
        "mode": "15ch",
        "color": {"red": 255, "green": 255, "blue": 255, "white": 255},
        "beat_pulse_enabled": False,
        "color_source": "phrase",
    },
    "uking_zq06016": {
        "label_base": "Wall Wash",
        "mode": "P001",
        "color_source": "phrase",
    },
}

WW_BLACK = (0, 0, 0)
WW_WHITE = (255, 255, 255)
WW_SOFT_WHITE = (120, 120, 120)
WW_DEEP_BLUE = (0, 0, 255)
WW_BLUE = (0, 80, 255)
WW_SOFT_BLUE = (0, 60, 255)
WW_PURPLE = (180, 0, 255)
WW_CYAN = (0, 255, 255)
WW_AMBER = (255, 120, 0)
WW_RED = (255, 0, 0)

INDEXED_COLOR_RGBW = {
    "white": (255, 255, 255, 255),
    "open": (255, 255, 255, 255),
    "red": (255, 0, 0, 0),
    "green": (0, 255, 0, 0),
    "blue": (0, 0, 255, 0),
    "yellow": (255, 255, 0, 0),
    "cyan": (0, 255, 255, 0),
    "orange": (255, 128, 0, 0),
    "amber": (255, 120, 0, 0),
    "purple": (180, 0, 255, 0),
    "pink": (255, 0, 180, 0),
}
BEE_EYE_PATTERN_FIXTURE_ID = "generic_smart_bee_eye_pattern_moving_head"
WW_WARM_GLOW_LOW = (80, 20, 0)
WW_WARM_GLOW_MID = (140, 50, 0)
WW_WARM_GLOW_HIGH = (220, 90, 0)
WW_WARM_GLOW_PEAK = (255, 140, 0)

WALL_WASH_CUES = {
    "full_white_wash": {
        "label": "Full White Wash",
        "frames": [[WW_WHITE] * 8],
    },
    "soft_white_wash": {
        "label": "Soft White Wash",
        "frames": [[WW_SOFT_WHITE] * 8],
    },
    "deep_blue_wash": {
        "label": "Deep Blue Wash",
        "frames": [[WW_DEEP_BLUE] * 8],
    },
    "soft_blue_wash": {
        "label": "Soft Blue Wash",
        "frames": [[(0, 60, 255)] * 8],
    },
    "purple_wash": {
        "label": "Purple Wash",
        "frames": [[WW_PURPLE] * 8],
    },
    "cyan_wash": {
        "label": "Cyan Wash",
        "frames": [[WW_CYAN] * 8],
    },
    "amber_wash": {
        "label": "Amber Wash",
        "frames": [[WW_AMBER] * 8],
    },
    "red_wash": {
        "label": "Red Wash",
        "frames": [[WW_RED] * 8],
    },
    "red_blue_split": {
        "label": "Red Blue Split",
        "frames": [[WW_RED, WW_RED, WW_RED, WW_RED, WW_DEEP_BLUE, WW_DEEP_BLUE, WW_DEEP_BLUE, WW_DEEP_BLUE]],
    },
    "blue_white_split": {
        "label": "Blue White Split",
        "frames": [[WW_SOFT_BLUE, WW_SOFT_BLUE, WW_SOFT_BLUE, WW_SOFT_BLUE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE]],
    },
    "purple_cyan_split": {
        "label": "Purple Cyan Split",
        "frames": [[WW_PURPLE, WW_PURPLE, WW_PURPLE, WW_PURPLE, WW_CYAN, WW_CYAN, WW_CYAN, WW_CYAN]],
    },
    "alternating_blue_purple": {
        "label": "Alternating Blue Purple",
        "frames": [[WW_SOFT_BLUE, WW_PURPLE, WW_SOFT_BLUE, WW_PURPLE, WW_SOFT_BLUE, WW_PURPLE, WW_SOFT_BLUE, WW_PURPLE]],
    },
    "center_glow_blue": {
        "label": "Center Glow Blue",
        "frames": [[(0, 0, 40), (0, 0, 80), (0, 40, 160), (0, 100, 255), (0, 100, 255), (0, 40, 160), (0, 0, 80), (0, 0, 40)]],
    },
    "edge_glow_white": {
        "label": "Edge Glow White",
        "frames": [[WW_WHITE, (120, 180, 255), (0, 80, 255), (0, 0, 80), (0, 0, 80), (0, 80, 255), (120, 180, 255), WW_WHITE]],
    },
    "warm_center_glow": {
        "label": "Warm Center Glow",
        "frames": [[WW_WARM_GLOW_LOW, WW_WARM_GLOW_MID, WW_WARM_GLOW_HIGH, WW_WARM_GLOW_PEAK, WW_WARM_GLOW_PEAK, WW_WARM_GLOW_HIGH, WW_WARM_GLOW_MID, WW_WARM_GLOW_LOW]],
    },
    "rainbow_static": {
        "label": "Rainbow Static",
        "frames": [[WW_RED, (255, 80, 0), (255, 255, 0), (0, 255, 0), WW_CYAN, WW_DEEP_BLUE, WW_PURPLE, (255, 0, 120)]],
    },
    "blue_chase_left_to_right": {
        "label": "Blue Chase Left To Right",
        "frames": [
            [WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE],
        ],
        "beats_per_frame": 0.5,
        "mirror_on_odd": True,
    },
    "blue_chase_right_to_left": {
        "label": "Blue Chase Right To Left",
        "frames": [
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
        ],
        "beats_per_frame": 0.5,
        "mirror_on_odd": True,
    },
    "knight_rider_red": {
        "label": "Knight Rider Red",
        "frames": [
            [WW_RED, (80, 0, 0), WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [(80, 0, 0), WW_RED, (80, 0, 0), WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, (80, 0, 0), WW_RED, (80, 0, 0), WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, (80, 0, 0), WW_RED, (80, 0, 0), WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, (80, 0, 0), WW_RED, (80, 0, 0), WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, (80, 0, 0), WW_RED, (80, 0, 0), WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, (80, 0, 0), WW_RED, (80, 0, 0)],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, (80, 0, 0), WW_RED],
        ],
        "beats_per_frame": 0.5,
        "mirror_on_odd": True,
    },
    "white_pixel_hits": {
        "label": "White Pixel Hits",
        "frames": [
            [WW_WHITE, WW_BLACK, WW_BLACK, WW_BLACK, WW_WHITE, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_WHITE, WW_BLACK, WW_BLACK, WW_BLACK, WW_WHITE, WW_BLACK],
            [WW_BLACK, WW_WHITE, WW_BLACK, WW_WHITE, WW_BLACK, WW_BLACK, WW_BLACK, WW_WHITE],
            [WW_WHITE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_WHITE, WW_WHITE, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_WHITE, WW_WHITE, WW_BLACK, WW_BLACK, WW_BLACK],
        ],
        "beats_per_frame": 0.5,
    },
    "purple_blue_bounce": {
        "label": "Purple Blue Bounce",
        "frames": [
            [WW_PURPLE, WW_SOFT_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_SOFT_BLUE, WW_PURPLE],
            [WW_BLACK, WW_PURPLE, WW_SOFT_BLUE, WW_BLACK, WW_BLACK, WW_SOFT_BLUE, WW_PURPLE, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_PURPLE, WW_SOFT_BLUE, WW_SOFT_BLUE, WW_PURPLE, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_SOFT_BLUE, WW_PURPLE, WW_PURPLE, WW_SOFT_BLUE, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_PURPLE, WW_SOFT_BLUE, WW_BLACK, WW_BLACK, WW_SOFT_BLUE, WW_PURPLE, WW_BLACK],
            [WW_PURPLE, WW_SOFT_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_SOFT_BLUE, WW_PURPLE],
        ],
        "beats_per_frame": 0.5,
    },
    "center_out_build": {
        "label": "Center Out Build",
        "frames": [
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLUE, (0, 120, 255), (0, 120, 255), WW_BLUE, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLUE, (0, 120, 255), (80, 180, 255), (80, 180, 255), (0, 120, 255), WW_BLUE, WW_BLACK],
            [WW_BLUE, (0, 120, 255), (80, 180, 255), (180, 220, 255), (180, 220, 255), (80, 180, 255), (0, 120, 255), WW_BLUE],
            [WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE],
        ],
        "beats_per_frame": 0.5,
    },
    "left_to_right_build": {
        "label": "Left To Right Build",
        "frames": [
            [WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [(0, 100, 255), (0, 100, 255), WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [(0, 130, 255), (0, 130, 255), (0, 130, 255), WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [(60, 160, 255), (60, 160, 255), (60, 160, 255), (60, 160, 255), WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [(100, 190, 255), (100, 190, 255), (100, 190, 255), (100, 190, 255), (100, 190, 255), WW_BLACK, WW_BLACK, WW_BLACK],
            [(160, 220, 255), (160, 220, 255), (160, 220, 255), (160, 220, 255), (160, 220, 255), (160, 220, 255), WW_BLACK, WW_BLACK],
            [(220, 240, 255), (220, 240, 255), (220, 240, 255), (220, 240, 255), (220, 240, 255), (220, 240, 255), (220, 240, 255), WW_BLACK],
            [WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE],
        ],
        "beats_per_frame": 0.5,
        "mirror_on_odd": True,
    },
    "right_to_left_build": {
        "label": "Right To Left Build",
        "frames": [
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, (0, 100, 255), (0, 100, 255)],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, (0, 130, 255), (0, 130, 255), (0, 130, 255)],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, (60, 160, 255), (60, 160, 255), (60, 160, 255), (60, 160, 255)],
            [WW_BLACK, WW_BLACK, WW_BLACK, (100, 190, 255), (100, 190, 255), (100, 190, 255), (100, 190, 255), (100, 190, 255)],
            [WW_BLACK, WW_BLACK, (160, 220, 255), (160, 220, 255), (160, 220, 255), (160, 220, 255), (160, 220, 255), (160, 220, 255)],
            [WW_BLACK, (220, 240, 255), (220, 240, 255), (220, 240, 255), (220, 240, 255), (220, 240, 255), (220, 240, 255), (220, 240, 255)],
            [WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE],
        ],
        "beats_per_frame": 0.5,
        "mirror_on_odd": True,
    },
    "full_white_flash": {
        "label": "Full White Flash",
        "frames": [[WW_WHITE] * 8],
        "beats_per_frame": 1.0,
        "flash": True,
        "flash_hold": 0.16,
    },
    "full_blue_flash": {
        "label": "Full Blue Flash",
        "frames": [[WW_BLUE] * 8],
        "beats_per_frame": 1.0,
        "flash": True,
        "flash_hold": 0.16,
    },
    "full_red_flash": {
        "label": "Full Red Flash",
        "frames": [[WW_RED] * 8],
        "beats_per_frame": 1.0,
        "flash": True,
        "flash_hold": 0.16,
    },
    "alternating_white_blue": {
        "label": "Alternating White Blue",
        "frames": [
            [WW_WHITE, WW_BLUE, WW_WHITE, WW_BLUE, WW_WHITE, WW_BLUE, WW_WHITE, WW_BLUE],
            [WW_BLUE, WW_WHITE, WW_BLUE, WW_WHITE, WW_BLUE, WW_WHITE, WW_BLUE, WW_WHITE],
        ],
        "beats_per_frame": 0.5,
    },
    "alternating_red_blue": {
        "label": "Alternating Red Blue",
        "frames": [
            [WW_RED, WW_DEEP_BLUE, WW_RED, WW_DEEP_BLUE, WW_RED, WW_DEEP_BLUE, WW_RED, WW_DEEP_BLUE],
            [WW_DEEP_BLUE, WW_RED, WW_DEEP_BLUE, WW_RED, WW_DEEP_BLUE, WW_RED, WW_DEEP_BLUE, WW_RED],
        ],
        "beats_per_frame": 0.5,
    },
    "center_white_punch": {
        "label": "Center White Punch",
        "frames": [[WW_BLACK, (0, 0, 80), WW_BLUE, WW_WHITE, WW_WHITE, WW_BLUE, (0, 0, 80), WW_BLACK]],
        "beats_per_frame": 1.0,
        "flash": True,
        "flash_hold": 0.18,
    },
    "edge_white_punch": {
        "label": "Edge White Punch",
        "frames": [[WW_WHITE, WW_BLUE, (0, 0, 80), WW_BLACK, WW_BLACK, (0, 0, 80), WW_BLUE, WW_WHITE]],
        "beats_per_frame": 1.0,
        "flash": True,
        "flash_hold": 0.18,
    },
    "blackout": {
        "label": "Blackout",
        "frames": [[WW_BLACK] * 8],
    },
}

LIVE_OVERRIDE_COLORS = {
    "none": None,
    "red": (255, 0, 0, 0),
    "yellow": (255, 220, 0, 0),
    "green": (0, 255, 0, 0),
    "lime": (140, 255, 0, 0),
    "purple": (180, 0, 255, 0),
    "pink": (255, 0, 180, 0),
    "cyan": (0, 255, 255, 0),
    "orange": (255, 120, 0, 0),
    "blue": (0, 80, 255, 0),
    "white": (255, 255, 255, 255),
    "rainbow": None,
}

AUTO_SHOW_STYLES = {
    "adaptive": {
        "label": "Adaptive",
        "energy_bias": 0.00,
        "brightness_bias": 0.00,
        "motion_bias": 0.00,
        "pulse_bias": 0.00,
        "strobe_bias": 0.00,
        "preferred_color_source": "hybrid",
    },
    "club": {
        "label": "Club",
        "energy_bias": 0.12,
        "brightness_bias": 0.10,
        "motion_bias": 0.16,
        "pulse_bias": 0.16,
        "strobe_bias": 0.20,
        "preferred_color_source": "color_bank",
    },
    "cinematic": {
        "label": "Cinematic",
        "energy_bias": -0.10,
        "brightness_bias": -0.16,
        "motion_bias": -0.12,
        "pulse_bias": -0.14,
        "strobe_bias": -1.00,
        "preferred_color_source": "mood",
    },
    "warm": {
        "label": "Warm",
        "energy_bias": -0.02,
        "brightness_bias": -0.05,
        "motion_bias": -0.06,
        "pulse_bias": -0.08,
        "strobe_bias": -0.70,
        "preferred_color_source": "manual",
    },
    "festival": {
        "label": "Festival",
        "energy_bias": 0.20,
        "brightness_bias": 0.16,
        "motion_bias": 0.24,
        "pulse_bias": 0.28,
        "strobe_bias": 0.34,
        "preferred_color_source": "color_bank",
    },
    "minimal": {
        "label": "Minimal",
        "energy_bias": -0.18,
        "brightness_bias": -0.20,
        "motion_bias": -0.18,
        "pulse_bias": -0.20,
        "strobe_bias": -1.00,
        "preferred_color_source": "mood",
    },
}

AUTO_SHOW_STYLE_VARIANT_RULES = {
    "club": {
        "looks": {
            "*": {"prefer": ["bank_echo", "neon_split", "ultraviolet"], "avoid": ["warm_glow"]},
            "build": {"prefer": ["neon_split", "ultraviolet", "bank_echo"]},
            "chorus": {"prefer": ["neon_split", "ultraviolet", "bank_echo"]},
            "drop": {"prefer": ["neon_split", "ultraviolet", "bank_echo"]},
        },
        "color_profiles": {
            "*": {"prefer": ["magenta_cyan", "pink_blue", "ice_fire", "teal_orange"], "avoid": ["amber_violet"]},
            "intro": {"prefer": ["blue_amber", "teal_orange"]},
            "drop": {"prefer": ["ice_fire", "pink_blue", "red_white"]},
        },
        "textures": {
            "*": {"prefer": ["split", "shuffle", "ripple", "ladder"], "avoid": ["steady"]},
        },
        "motions": {
            "intro": {"prefer": ["slow_audience_sweep_blue", "slow_audience_circle"]},
            "verse": {"prefer": ["slow_audience_sweep_blue", "slow_audience_oval", "slow_random_searchlight"]},
            "build": {"prefer": ["build_audience_wave", "build_fastening_circle", "build_color_chase", "build_rising_sweep"]},
            "chorus": {"prefer": ["fast_audience_sweep", "fast_audience_circle", "fast_audience_figure_8", "snap_position_hits", "random_search_hits"]},
            "drop": {"prefer": ["drop_crossing_beams", "drop_snap_fan", "drop_fast_circle_white", "drop_strobe_sweep", "drop_full_audience_hit"]},
            "break": {"prefer": ["slow_audience_sweep_blue", "slow_audience_oval"]},
            "outro": {"prefer": ["slow_audience_sweep_blue", "slow_audience_oval"]},
        },
        "pulses": {
            "verse": {"prefer": ["alternate_whole", "offbeat_flash", "soft_pulse"]},
            "build": {"prefer": ["gallop", "double_hit", "chase", "snake", "pivot", "ramp_up"], "avoid": ["breathing"]},
            "chorus": {"prefer": ["gallop", "double_hit", "chase", "snake", "beat_flash", "pivot"], "avoid": ["breathing"]},
            "drop": {"prefer": ["drop_blinder", "snake", "gallop", "double_hit", "chase", "beat_flash", "blackout_hit"]},
            "break": {"prefer": ["alternate_whole", "offbeat_flash", "soft_pulse"]},
            "outro": {"prefer": ["alternate_whole", "soft_pulse"]},
        },
        "washes": {
            "verse": {"prefer": ["purple_cyan_split", "alternating_blue_purple", "blue_white_split"]},
            "build": {"prefer": ["center_out_build", "left_to_right_build", "right_to_left_build", "blue_chase_left_to_right"]},
            "chorus": {"prefer": ["alternating_red_blue", "purple_blue_bounce", "white_pixel_hits", "knight_rider_red", "blue_white_split"]},
            "drop": {"prefer": ["full_white_flash", "alternating_red_blue", "center_white_punch", "edge_white_punch"]},
        },
        "accents": {
            "*": {"prefer": ["mover_focus", "alternating", "edges"]},
        },
    },
    "cinematic": {
        "looks": {
            "*": {"prefer": ["cool_air", "mood_wash", "warm_glow"], "avoid": ["neon_split", "ultraviolet"]},
            "drop": {"prefer": ["cool_air", "mood_wash", "bank_echo"]},
        },
        "color_profiles": {
            "*": {"prefer": ["deep_blue_white", "amber_violet", "purple_gold", "cobalt_amber", "rose_mint"], "avoid": ["pink_blue", "ice_fire", "red_white"]},
        },
        "textures": {
            "*": {"prefer": ["drift", "bloom", "ripple"], "avoid": ["shuffle"]},
        },
        "motions": {
            "intro": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval"]},
            "verse": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval", "slow_audience_figure_8"]},
            "build": {"prefer": ["build_rising_sweep", "build_narrow_to_wide_fan", "build_fastening_circle"], "avoid": ["build_strobe_ramp", "build_white_flash_prep", "build_color_chase"]},
            "chorus": {"prefer": ["slow_high_audience_sweep", "slow_audience_oval", "slow_audience_circle"], "avoid": ["snap_position_hits", "random_search_hits"]},
            "drop": {"prefer": ["drop_crossing_beams", "drop_snap_fan", "drop_full_audience_hit"], "avoid": ["drop_strobe_sweep", "drop_white_blinder"]},
            "down": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval"]},
            "break": {"prefer": ["break_slow_pulse_circle", "break_purple_oval", "break_high_cool_sweep"]},
            "outro": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "break_high_cool_sweep"]},
        },
        "pulses": {
            "intro": {"prefer": ["slow_fade_in", "soft_pulse", "breathing"]},
            "verse": {"prefer": ["breathing", "soft_pulse", "alternate_whole"], "avoid": ["chase", "snake"]},
            "build": {"prefer": ["soft_pulse", "alternate_whole", "pivot", "ramp_up"], "avoid": ["chase", "snake", "gallop", "drop_blinder", "blackout_hit", "tremolo_dimmer"]},
            "chorus": {"prefer": ["soft_pulse", "alternate_whole", "pivot", "double_hit"], "avoid": ["chase", "snake", "gallop", "drop_blinder", "blackout_hit"]},
            "drop": {"prefer": ["full_on", "alternate_whole", "double_hit", "pivot"], "avoid": ["snake", "gallop", "blackout_hit", "tremolo_dimmer"]},
            "down": {"prefer": ["breathing", "soft_pulse", "slow_fade_out"]},
            "break": {"prefer": ["breathing", "soft_pulse", "slow_fade_out"]},
            "outro": {"prefer": ["slow_fade_out", "breathing", "soft_pulse"]},
        },
        "washes": {
            "verse": {"prefer": ["deep_blue_wash", "soft_blue_wash", "center_glow_blue", "edge_glow_white"]},
            "build": {"prefer": ["center_glow_blue", "edge_glow_white", "warm_center_glow"], "avoid": ["blue_chase_left_to_right", "blue_chase_right_to_left"]},
            "chorus": {"prefer": ["blue_white_split", "purple_cyan_split", "edge_glow_white"], "avoid": ["white_pixel_hits", "knight_rider_red"]},
            "drop": {"prefer": ["center_white_punch", "edge_glow_white", "blue_white_split"], "avoid": ["full_red_flash", "alternating_red_blue"]},
            "break": {"prefer": ["deep_blue_wash", "soft_blue_wash", "warm_center_glow"]},
            "outro": {"prefer": ["edge_glow_white", "deep_blue_wash", "warm_center_glow"]},
        },
        "accents": {
            "*": {"prefer": ["center", "wash_lift", "edges"]},
        },
    },
    "warm": {
        "looks": {
            "*": {"prefer": ["warm_glow", "sunset_push", "bank_echo"], "avoid": ["white_bloom"]},
            "build": {"prefer": ["sunset_push", "warm_glow", "bank_echo"]},
            "drop": {"prefer": ["sunset_push", "bank_echo", "warm_glow"]},
        },
        "color_profiles": {
            "*": {"prefer": ["amber_violet", "purple_gold", "teal_orange", "blue_amber", "cobalt_amber"], "avoid": ["ice_fire"]},
        },
        "textures": {
            "*": {"prefer": ["drift", "bloom", "ripple"], "avoid": ["shuffle"]},
        },
        "motions": {
            "intro": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval"]},
            "verse": {"prefer": ["slow_audience_sweep_white", "slow_high_audience_sweep", "slow_audience_oval", "slow_audience_figure_8"]},
            "build": {"prefer": ["build_rising_sweep", "build_narrow_to_wide_fan", "build_audience_wave"], "avoid": ["build_strobe_ramp", "build_white_flash_prep"]},
            "chorus": {"prefer": ["fast_audience_sweep", "fast_audience_figure_8", "slow_audience_oval"], "avoid": ["snap_position_hits", "random_search_hits"]},
            "drop": {"prefer": ["drop_snap_fan", "drop_full_audience_hit", "drop_crossing_beams", "fast_audience_figure_8"], "avoid": ["drop_strobe_sweep"]},
            "down": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval"]},
            "break": {"prefer": ["break_slow_pulse_circle", "break_purple_oval", "slow_audience_oval"]},
            "outro": {"prefer": ["slow_audience_sweep_blue", "slow_high_audience_sweep", "slow_audience_oval"]},
        },
        "pulses": {
            "intro": {"prefer": ["slow_fade_in", "soft_pulse"]},
            "verse": {"prefer": ["soft_pulse", "offbeat_flash", "alternate_whole"], "avoid": ["snake"]},
            "build": {"prefer": ["ramp_up", "soft_pulse", "alternate_whole", "double_hit", "pivot"], "avoid": ["snake", "gallop", "blackout_hit", "tremolo_dimmer"]},
            "chorus": {"prefer": ["alternate_whole", "double_hit", "soft_pulse", "offbeat_flash", "beat_flash"], "avoid": ["snake", "gallop", "blackout_hit"]},
            "drop": {"prefer": ["full_on", "double_hit", "alternate_whole", "beat_flash", "drop_blinder"], "avoid": ["snake", "blackout_hit", "tremolo_dimmer"]},
            "down": {"prefer": ["soft_pulse", "breathing", "slow_fade_out"]},
            "break": {"prefer": ["breathing", "soft_pulse", "slow_fade_out"]},
            "outro": {"prefer": ["slow_fade_out", "soft_pulse", "breathing"]},
        },
        "washes": {
            "intro": {"prefer": ["warm_center_glow", "amber_wash", "soft_white_wash"]},
            "verse": {"prefer": ["warm_center_glow", "amber_wash", "purple_wash", "blue_white_split"]},
            "build": {"prefer": ["warm_center_glow", "amber_wash", "center_out_build"]},
            "chorus": {"prefer": ["warm_center_glow", "purple_wash", "alternating_white_blue"]},
            "drop": {"prefer": ["warm_center_glow", "full_white_flash", "center_white_punch", "alternating_white_blue"]},
            "down": {"prefer": ["warm_center_glow", "amber_wash", "purple_wash"]},
            "break": {"prefer": ["warm_center_glow", "amber_wash", "purple_wash", "soft_white_wash"]},
            "outro": {"prefer": ["warm_center_glow", "amber_wash", "soft_white_wash"]},
        },
        "accents": {
            "*": {"prefer": ["center", "wash_lift", "mover_focus"]},
        },
    },
    "festival": {
        "looks": {
            "*": {"prefer": ["neon_split", "ultraviolet", "bank_echo", "cool_air"], "avoid": ["warm_glow", "white_bloom"]},
            "intro": {"prefer": ["cool_air", "bank_echo"]},
            "break": {"prefer": ["bank_echo", "cool_air"]},
        },
        "color_profiles": {
            "*": {"prefer": ["ice_fire", "red_white", "pink_blue", "magenta_cyan", "teal_orange"], "avoid": ["amber_violet"]},
        },
        "textures": {
            "*": {"prefer": ["shuffle", "split", "ladder", "ripple"], "avoid": ["steady", "bloom"]},
        },
        "motions": {
            "intro": {"prefer": ["slow_audience_sweep_blue", "slow_random_searchlight"]},
            "verse": {"prefer": ["slow_audience_sweep_blue", "slow_random_searchlight", "slow_deep_audience_sweep"]},
            "build": {"prefer": ["build_strobe_ramp", "build_white_flash_prep", "build_color_chase", "build_fastening_circle", "build_audience_wave"]},
            "chorus": {"prefer": ["fast_audience_sweep", "snap_position_hits", "fast_diagonal_sweep", "random_search_hits", "fast_audience_circle"]},
            "drop": {"prefer": ["drop_white_blinder", "drop_strobe_sweep", "drop_snap_fan", "drop_crossing_beams", "drop_full_audience_hit"]},
            "down": {"prefer": ["slow_audience_sweep_blue", "slow_random_searchlight"]},
            "break": {"prefer": ["slow_audience_sweep_blue", "slow_random_searchlight"]},
            "outro": {"prefer": ["slow_audience_sweep_blue", "slow_random_searchlight"]},
        },
        "pulses": {
            "intro": {"prefer": ["soft_pulse", "offbeat_flash"]},
            "verse": {"prefer": ["alternate_whole", "offbeat_flash", "beat_flash"]},
            "build": {"prefer": ["chase", "snake", "gallop", "double_hit", "tremolo_dimmer", "ramp_up", "beat_flash"]},
            "chorus": {"prefer": ["chase", "snake", "gallop", "double_hit", "beat_flash", "pivot"]},
            "drop": {"prefer": ["drop_blinder", "blackout_hit", "snake", "gallop", "double_hit", "chase", "tremolo_dimmer"]},
            "down": {"prefer": ["alternate_whole", "soft_pulse", "offbeat_flash"]},
            "break": {"prefer": ["alternate_whole", "offbeat_flash", "soft_pulse"]},
            "outro": {"prefer": ["alternate_whole", "soft_pulse"]},
        },
        "washes": {
            "verse": {"prefer": ["red_blue_split", "alternating_blue_purple", "purple_cyan_split"]},
            "build": {"prefer": ["center_out_build", "left_to_right_build", "right_to_left_build", "blue_chase_left_to_right", "blue_chase_right_to_left"]},
            "chorus": {"prefer": ["alternating_red_blue", "white_pixel_hits", "knight_rider_red", "purple_blue_bounce", "blue_white_split"]},
            "drop": {"prefer": ["full_white_flash", "full_red_flash", "alternating_red_blue", "center_white_punch", "edge_white_punch"]},
        },
        "accents": {
            "*": {"prefer": ["mover_focus", "edges", "alternating"]},
        },
    },
    "minimal": {
        "looks": {
            "*": {"prefer": ["cool_air", "mood_wash", "warm_glow"], "avoid": ["white_bloom", "neon_split", "ultraviolet"]},
        },
        "color_profiles": {
            "*": {"prefer": ["deep_blue_white", "rose_mint", "cobalt_amber", "blue_amber"], "avoid": ["red_white", "ice_fire", "pink_blue"]},
        },
        "textures": {
            "*": {"prefer": ["steady", "drift", "bloom"], "avoid": ["shuffle", "split"]},
        },
        "motions": {
            "intro": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval"]},
            "verse": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval", "slow_audience_figure_8"]},
            "build": {"prefer": ["build_rising_sweep", "build_narrow_to_wide_fan", "build_audience_wave"], "avoid": ["build_strobe_ramp", "build_white_flash_prep", "build_color_chase"]},
            "chorus": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval"], "avoid": ["snap_position_hits", "random_search_hits", "fast_diagonal_sweep"]},
            "drop": {"prefer": ["drop_snap_fan", "drop_crossing_beams", "drop_full_audience_hit"], "avoid": ["drop_strobe_sweep", "drop_white_blinder"]},
            "down": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval"]},
            "break": {"prefer": ["break_high_cool_sweep", "break_slow_pulse_circle", "break_purple_oval"]},
            "outro": {"prefer": ["slow_high_audience_sweep", "break_high_cool_sweep", "slow_audience_circle"]},
        },
        "pulses": {
            "intro": {"prefer": ["slow_fade_in", "soft_pulse", "breathing"]},
            "verse": {"prefer": ["breathing", "soft_pulse", "alternate_whole"]},
            "build": {"prefer": ["soft_pulse", "alternate_whole", "pivot"], "avoid": ["chase", "snake", "gallop", "blackout_hit", "drop_blinder", "tremolo_dimmer"]},
            "chorus": {"prefer": ["soft_pulse", "alternate_whole", "pivot", "offbeat_flash"], "avoid": ["chase", "snake", "gallop", "blackout_hit"]},
            "drop": {"prefer": ["full_on", "alternate_whole", "pivot", "double_hit"], "avoid": ["snake", "gallop", "blackout_hit", "tremolo_dimmer"]},
            "down": {"prefer": ["breathing", "soft_pulse", "slow_fade_out"]},
            "break": {"prefer": ["breathing", "soft_pulse", "slow_fade_out"]},
            "outro": {"prefer": ["slow_fade_out", "breathing", "soft_pulse"]},
        },
        "washes": {
            "intro": {"prefer": ["deep_blue_wash", "soft_blue_wash", "center_glow_blue"]},
            "verse": {"prefer": ["deep_blue_wash", "soft_blue_wash", "blue_white_split", "center_glow_blue"]},
            "build": {"prefer": ["center_glow_blue", "edge_glow_white", "warm_center_glow"]},
            "chorus": {"prefer": ["blue_white_split", "purple_cyan_split", "edge_glow_white"]},
            "drop": {"prefer": ["center_white_punch", "edge_glow_white", "blue_white_split"]},
            "down": {"prefer": ["deep_blue_wash", "soft_blue_wash", "center_glow_blue"]},
            "break": {"prefer": ["deep_blue_wash", "soft_blue_wash", "warm_center_glow"]},
            "outro": {"prefer": ["deep_blue_wash", "edge_glow_white", "warm_center_glow"]},
        },
        "accents": {
            "*": {"prefer": ["center", "wash_lift"]},
        },
    },
}

AUTO_SHOW_SECTIONS = {
    "intro": {"energy": 0.34, "motion": 0.22, "pulse": 0.06, "strobe": False},
    "verse": {"energy": 0.56, "motion": 0.42, "pulse": 0.20, "strobe": False},
    "build": {"energy": 0.76, "motion": 0.70, "pulse": 0.48, "strobe": False},
    "chorus": {"energy": 0.88, "motion": 0.84, "pulse": 0.62, "strobe": False},
    "drop": {"energy": 1.00, "motion": 0.98, "pulse": 0.80, "strobe": True},
    "down": {"energy": 0.58, "motion": 0.50, "pulse": 0.18, "strobe": False},
    "break": {"energy": 0.48, "motion": 0.40, "pulse": 0.16, "strobe": False},
    "outro": {"energy": 0.40, "motion": 0.30, "pulse": 0.10, "strobe": False},
    "unknown": {"energy": 0.60, "motion": 0.48, "pulse": 0.28, "strobe": False},
}

AUTO_SHOW_LOOK_POOLS = {
    "intro": ["warm_glow", "cool_air", "mood_wash", "sunset_push"],
    "verse": ["bank_echo", "cool_air", "sunset_push", "mood_wash", "neon_split"],
    "build": ["sunset_push", "neon_split", "ultraviolet", "bank_echo"],
    "chorus": ["neon_split", "ultraviolet", "bank_echo", "sunset_push", "mood_wash"],
    "drop": ["neon_split", "ultraviolet", "bank_echo", "sunset_push"],
    "down": ["cool_air", "mood_wash", "bank_echo", "sunset_push"],
    "break": ["cool_air", "mood_wash", "warm_glow", "bank_echo"],
    "outro": ["warm_glow", "sunset_push", "mood_wash", "cool_air"],
    "unknown": ["bank_echo", "mood_wash", "neon_split", "cool_air"],
}

AUTO_SHOW_COLOR_PROFILE_POOLS = {
    "intro": ["blue_amber", "teal_orange", "purple_gold", "amber_violet"],
    "verse": ["blue_amber", "magenta_cyan", "teal_orange", "cobalt_amber", "rose_mint", "amber_teal", "violet_lime"],
    "build": ["purple_gold", "blue_amber", "magenta_cyan", "teal_orange", "amber_violet", "rose_mint", "ruby_lime"],
    "chorus": ["magenta_cyan", "teal_orange", "blue_amber", "purple_gold", "pink_blue", "amber_violet", "ice_fire", "violet_lime"],
    "drop": ["magenta_cyan", "blue_amber", "pink_blue", "ice_fire", "teal_orange", "ruby_lime"],
    "down": ["blue_amber", "magenta_cyan", "teal_orange", "rose_mint", "amber_teal", "violet_lime"],
    "break": ["blue_amber", "magenta_cyan", "teal_orange", "purple_gold", "rose_mint", "amber_teal"],
    "outro": ["blue_amber", "purple_gold", "teal_orange", "amber_violet"],
    "unknown": ["blue_amber", "magenta_cyan", "teal_orange", "purple_gold", "rose_mint", "amber_teal"],
}

AUTO_SHOW_TEXTURE_POOLS = {
    "intro": ["steady", "drift", "bloom"],
    "verse": ["drift", "ripple", "split", "ladder"],
    "build": ["ladder", "split", "shuffle", "ripple"],
    "chorus": ["ripple", "shuffle", "split", "bloom"],
    "drop": ["shuffle", "split", "ladder", "ripple"],
    "down": ["drift", "bloom", "ripple"],
    "break": ["steady", "drift", "bloom"],
    "outro": ["steady", "drift", "bloom"],
    "unknown": ["drift", "ripple", "split", "ladder"],
}

AUTO_SHOW_WASH_CUE_POOLS = {
    "intro": [
        "soft_white_wash",
        "soft_blue_wash",
        "center_glow_blue",
        "warm_center_glow",
        "deep_blue_wash",
    ],
    "verse": [
        "deep_blue_wash",
        "soft_blue_wash",
        "purple_wash",
        "cyan_wash",
        "blue_white_split",
        "purple_cyan_split",
        "alternating_blue_purple",
        "center_glow_blue",
        "warm_center_glow",
        "rainbow_static",
    ],
    "build": [
        "center_out_build",
        "left_to_right_build",
        "right_to_left_build",
        "blue_chase_left_to_right",
        "blue_chase_right_to_left",
    ],
    "chorus": [
        "alternating_white_blue",
        "alternating_red_blue",
        "purple_blue_bounce",
        "white_pixel_hits",
        "knight_rider_red",
        "red_blue_split",
        "blue_white_split",
    ],
    "drop": [
        "full_white_flash",
        "full_blue_flash",
        "full_red_flash",
        "alternating_white_blue",
        "alternating_red_blue",
        "center_white_punch",
        "edge_white_punch",
    ],
    "down": [
        "deep_blue_wash",
        "soft_blue_wash",
        "purple_wash",
        "blue_white_split",
        "alternating_blue_purple",
        "center_glow_blue",
        "warm_center_glow",
    ],
    "break": [
        "deep_blue_wash",
        "soft_blue_wash",
        "purple_wash",
        "blue_white_split",
        "alternating_blue_purple",
        "center_glow_blue",
        "warm_center_glow",
        "soft_white_wash",
    ],
    "outro": [
        "soft_white_wash",
        "deep_blue_wash",
        "edge_glow_white",
        "alternating_blue_purple",
        "center_glow_blue",
        "warm_center_glow",
    ],
    "unknown": [
        "soft_blue_wash",
        "center_glow_blue",
        "purple_wash",
        "blue_white_split",
        "alternating_blue_purple",
    ],
}

AUTO_SHOW_MOTION_POOLS = {
    "intro": [
        "slow_high_audience_sweep",
        "slow_audience_sweep_blue",
        "slow_audience_circle",
        "slow_audience_oval",
        "break_high_cool_sweep",
        "break_cyan_figure_8",
    ],
    "verse": [
        "slow_audience_sweep_blue",
        "slow_deep_audience_sweep",
        "slow_high_audience_sweep",
        "slow_audience_circle",
        "slow_audience_oval",
        "slow_audience_figure_8",
        "slow_random_searchlight",
    ],
    "build": [
        "build_rising_sweep",
        "build_dimmer_pulse",
        "build_fastening_circle",
        "build_narrow_to_wide_fan",
        "build_strobe_ramp",
        "build_color_chase",
        "build_audience_wave",
        "build_white_flash_prep",
    ],
    "chorus": [
        "fast_audience_sweep",
        "fast_audience_circle",
        "fast_audience_figure_8",
        "snap_position_hits",
        "fast_diagonal_sweep",
        "random_search_hits",
    ],
    "drop": [
        "drop_white_blinder",
        "drop_strobe_sweep",
        "drop_snap_fan",
        "drop_crossing_beams",
        "drop_full_audience_hit",
        "fast_audience_figure_8",
        "fast_audience_circle",
    ],
    "down": [
        "slow_high_audience_sweep",
        "slow_audience_sweep_blue",
        "slow_audience_circle",
        "slow_audience_oval",
        "slow_random_searchlight",
        "break_high_cool_sweep",
        "break_cyan_figure_8",
    ],
    "break": [
        "break_slow_pulse_circle",
        "break_purple_oval",
        "break_high_cool_sweep",
        "slow_high_audience_sweep",
        "slow_audience_oval",
        "slow_random_searchlight",
        "break_cyan_figure_8",
        "slow_audience_circle",
        "slow_audience_figure_8",
    ],
    "outro": [
        "slow_audience_sweep_blue",
        "slow_high_audience_sweep",
        "break_high_cool_sweep",
        "break_cyan_figure_8",
        "slow_audience_circle",
        "slow_audience_oval",
        "slow_random_searchlight",
    ],
    "unknown": [
        "slow_audience_sweep_white",
        "slow_audience_circle",
        "fast_audience_sweep",
        "slow_audience_oval",
        "slow_random_searchlight",
    ],
}

AUTO_SHOW_MEMBER_MIRROR_MOTIONS = {
    "slow_left_right_sweep",
    "fast_left_right_sweep",
    "audience_sweep",
    "ceiling_sweep",
    "up_down_sweep",
    "slow_circle",
    "fast_circle",
    "oval_circle",
    "figure_8",
    "small_figure_8",
    "mirror_bounce",
}

AUTO_SHOW_PULSE_POOLS = {
    "intro": ["slow_fade_in", "soft_pulse", "offbeat_flash"],
    "verse": ["soft_pulse", "offbeat_flash", "breathing", "alternate_whole"],
    "build": ["ramp_up", "soft_pulse", "beat_flash", "alternate_whole", "double_hit", "gallop", "pivot", "chase", "snake", "tremolo_dimmer"],
    "chorus": ["soft_pulse", "offbeat_flash", "beat_flash", "alternate_whole", "double_hit", "gallop", "pivot", "chase", "snake"],
    "drop": ["full_on", "beat_flash", "drop_blinder", "blackout_hit", "alternate_whole", "double_hit", "gallop", "pivot", "chase", "snake", "tremolo_dimmer"],
    "down": ["soft_pulse", "offbeat_flash", "breathing", "slow_fade_out", "alternate_whole"],
    "break": ["breathing", "soft_pulse", "offbeat_flash", "slow_fade_out"],
    "outro": ["soft_pulse", "offbeat_flash", "breathing", "slow_fade_out"],
    "unknown": ["soft_pulse", "offbeat_flash", "breathing", "alternate_whole"],
}

AUTO_SHOW_ACCENT_POOLS = {
    "intro": ["wash_lift", "center", "alternating"],
    "verse": ["alternating", "center", "edges", "wash_lift"],
    "build": ["edges", "mover_focus", "alternating"],
    "chorus": ["mover_focus", "alternating", "center", "edges"],
    "drop": ["mover_focus", "edges", "alternating"],
    "down": ["wash_lift", "center", "alternating"],
    "break": ["wash_lift", "center"],
    "outro": ["center", "wash_lift", "alternating"],
    "unknown": ["alternating", "center", "edges"],
}

AUTO_SHOW_PULSE_PROFILES = {
    "full_on": {"depth": 0, "decay": 0, "movement": 0.00, "mode": "full_on"},
    "low_glow": {"depth": 0, "decay": 0, "movement": -0.02, "mode": "low_glow"},
    "medium": {"depth": 0, "decay": 0, "movement": 0.00, "mode": "medium"},
    "slow_fade_in": {"depth": 0, "decay": 0, "movement": -0.01, "mode": "fade_in"},
    "slow_fade_out": {"depth": 0, "decay": 0, "movement": -0.02, "mode": "fade_out"},
    "soft_pulse": {"depth": 18, "decay": 140, "movement": 0.00, "mode": "soft_pulse"},
    "strong_pulse": {"depth": 46, "decay": 80, "movement": 0.00, "mode": "strong_pulse"},
    "beat_flash": {"depth": 60, "decay": 42, "movement": 0.00, "mode": "beat_flash"},
    "offbeat_flash": {"depth": 44, "decay": 56, "movement": 0.00, "mode": "offbeat_flash"},
    "drop_blinder": {"depth": 72, "decay": 80, "movement": 0.00, "mode": "drop_blinder"},
    "blackout_hit": {"depth": 0, "decay": 36, "movement": 0.00, "mode": "blackout_hit"},
    "ramp_up": {"depth": 0, "decay": 0, "movement": 0.00, "mode": "ramp_up"},
    "ramp_down": {"depth": 0, "decay": 0, "movement": 0.00, "mode": "ramp_down"},
    "breathing": {"depth": 20, "decay": 180, "movement": -0.01, "mode": "breathing"},
    "tremolo_dimmer": {"depth": 38, "decay": 34, "movement": 0.00, "mode": "tremolo"},
    "alternate_whole": {"depth": 26, "decay": 76, "movement": 0.00, "mode": "alternate_whole"},
    "double_hit": {"depth": 54, "decay": 44, "movement": 0.00, "mode": "double_hit"},
    "gallop": {"depth": 44, "decay": 54, "movement": 0.00, "mode": "gallop"},
    "pivot": {"depth": 30, "decay": 72, "movement": 0.00, "mode": "pivot"},
    "chase": {"depth": 26, "decay": 60, "movement": 0.00, "mode": "chase"},
    "snake": {"depth": 30, "decay": 60, "movement": 0.00, "mode": "snake"},
}

TRACK_SHOW_THEMES = {
    "solar_dusk": {
        "label": "Solar Dusk",
        "color_profiles": ["blue_amber", "purple_gold", "amber_violet", "teal_orange"],
        "looks": ["sunset_push", "warm_glow", "bank_echo"],
        "accents": ["center", "alternating", "wash_lift"],
        "textures": ["drift", "bloom", "ladder"],
        "energy_bias": 0.03,
        "motion_bias": -0.02,
        "pulse_bias": -0.05,
        "contrast": 0.18,
        "white_bias": -0.03,
    },
    "ocean_drive": {
        "label": "Ocean Drive",
        "color_profiles": ["teal_orange", "blue_amber", "cobalt_amber", "amber_teal"],
        "looks": ["cool_air", "bank_echo", "mood_wash"],
        "accents": ["edges", "center", "alternating"],
        "textures": ["ripple", "drift", "split"],
        "energy_bias": -0.02,
        "motion_bias": 0.02,
        "pulse_bias": -0.08,
        "contrast": 0.24,
        "white_bias": -0.01,
    },
    "neon_wire": {
        "label": "Neon Wire",
        "color_profiles": ["magenta_cyan", "pink_blue", "ice_fire", "violet_lime"],
        "looks": ["neon_split", "ultraviolet", "bank_echo"],
        "accents": ["alternating", "mover_focus", "edges"],
        "textures": ["split", "shuffle", "ripple"],
        "energy_bias": 0.06,
        "motion_bias": 0.05,
        "pulse_bias": -0.04,
        "contrast": 0.32,
        "white_bias": 0.00,
    },
    "velvet_heat": {
        "label": "Velvet Heat",
        "color_profiles": ["amber_violet", "purple_gold", "magenta_cyan", "amber_teal"],
        "looks": ["warm_glow", "sunset_push", "ultraviolet"],
        "accents": ["center", "wash_lift", "mover_focus"],
        "textures": ["drift", "bloom", "ripple"],
        "energy_bias": 0.00,
        "motion_bias": -0.01,
        "pulse_bias": -0.07,
        "contrast": 0.22,
        "white_bias": -0.01,
    },
    "citrus_pop": {
        "label": "Citrus Pop",
        "color_profiles": ["blue_amber", "yellow_blue", "teal_orange", "amber_teal"],
        "looks": ["bank_echo", "mood_wash", "sunset_push"],
        "accents": ["alternating", "edges", "center"],
        "textures": ["ladder", "split", "shuffle"],
        "energy_bias": 0.05,
        "motion_bias": 0.01,
        "pulse_bias": -0.06,
        "contrast": 0.28,
        "white_bias": -0.01,
    },
    "polar_haze": {
        "label": "Polar Haze",
        "color_profiles": ["ice_fire", "blue_amber", "magenta_cyan", "rose_mint"],
        "looks": ["cool_air", "bank_echo", "mood_wash"],
        "accents": ["center", "edges", "wash_lift"],
        "textures": ["steady", "drift", "bloom"],
        "energy_bias": -0.04,
        "motion_bias": -0.03,
        "pulse_bias": -0.12,
        "contrast": 0.18,
        "white_bias": 0.00,
    },
    "acid_arc": {
        "label": "Acid Arc",
        "color_profiles": ["magenta_cyan", "pink_blue", "blue_amber", "teal_orange"],
        "looks": ["neon_split", "bank_echo", "ultraviolet"],
        "accents": ["alternating", "edges", "mover_focus"],
        "textures": ["split", "ladder", "shuffle"],
        "energy_bias": 0.08,
        "motion_bias": 0.06,
        "pulse_bias": -0.03,
        "contrast": 0.34,
        "white_bias": -0.02,
    },
    "ember_storm": {
        "label": "Ember Storm",
        "color_profiles": ["ruby_lime", "blue_amber", "ice_fire", "amber_violet"],
        "looks": ["sunset_push", "ultraviolet", "bank_echo"],
        "accents": ["mover_focus", "edges", "center"],
        "textures": ["ripple", "split", "ladder"],
        "energy_bias": 0.04,
        "motion_bias": 0.03,
        "pulse_bias": -0.05,
        "contrast": 0.30,
        "white_bias": -0.01,
    },
    "candy_night": {
        "label": "Candy Night",
        "color_profiles": ["magenta_cyan", "pink_blue", "purple_gold", "rose_mint"],
        "looks": ["neon_split", "warm_glow", "mood_wash"],
        "accents": ["alternating", "wash_lift", "center"],
        "textures": ["shuffle", "drift", "bloom"],
        "energy_bias": 0.01,
        "motion_bias": 0.00,
        "pulse_bias": -0.08,
        "contrast": 0.26,
        "white_bias": -0.01,
    },
    "steel_lotus": {
        "label": "Steel Lotus",
        "color_profiles": ["blue_amber", "teal_orange", "purple_gold", "rose_mint"],
        "looks": ["cool_air", "ultraviolet", "bank_echo"],
        "accents": ["edges", "mover_focus", "center"],
        "textures": ["ripple", "steady", "split"],
        "energy_bias": -0.01,
        "motion_bias": 0.04,
        "pulse_bias": -0.09,
        "contrast": 0.27,
        "white_bias": -0.01,
    },
}

TRACK_SHOW_THEME_SEQUENCE = list(TRACK_SHOW_THEMES.keys())

TRACK_SHOW_THEME_CHARACTER = {
    "solar_dusk": {
        "motions": {
            "verse": ["slow_audience_oval", "slow_audience_circle", "slow_high_audience_sweep"],
            "build": ["build_rising_sweep", "build_narrow_to_wide_fan", "build_audience_wave"],
            "chorus": ["fast_audience_sweep", "fast_audience_circle", "drop_crossing_beams"],
            "drop": ["drop_crossing_beams", "drop_snap_fan", "drop_full_audience_hit"],
        },
        "pulses": {
            "build": ["ramp_up", "alternate_whole", "pivot"],
            "chorus": ["alternate_whole", "double_hit", "pivot"],
            "drop": ["double_hit", "gallop", "beat_flash"],
        },
        "mirror_bias": 0.14,
        "white_bias": -0.06,
    },
    "ocean_drive": {
        "motions": {
            "verse": ["slow_high_audience_sweep", "slow_audience_circle", "slow_random_searchlight"],
            "build": ["build_rising_sweep", "build_audience_wave", "build_fastening_circle"],
            "chorus": ["fast_audience_circle", "fast_audience_sweep", "random_search_hits"],
            "drop": ["drop_fast_circle_white", "drop_crossing_beams", "fast_audience_figure_8"],
        },
        "pulses": {
            "build": ["soft_pulse", "ramp_up", "alternate_whole"],
            "chorus": ["alternate_whole", "pivot", "double_hit"],
            "drop": ["gallop", "double_hit", "snake"],
        },
        "mirror_bias": 0.18,
        "white_bias": -0.03,
    },
    "neon_wire": {
        "motions": {
            "verse": ["slow_audience_figure_8", "slow_random_searchlight", "slow_audience_oval"],
            "build": ["build_fastening_circle", "build_color_chase", "build_audience_wave"],
            "chorus": ["fast_diagonal_sweep", "fast_audience_figure_8", "random_search_hits"],
            "drop": ["drop_crossing_beams", "drop_strobe_sweep", "drop_snap_fan"],
        },
        "pulses": {
            "build": ["alternate_whole", "double_hit", "gallop"],
            "chorus": ["gallop", "pivot", "snake"],
            "drop": ["double_hit", "gallop", "snake", "beat_flash"],
        },
        "mirror_bias": 0.26,
        "white_bias": -0.02,
    },
    "velvet_heat": {
        "motions": {
            "verse": ["slow_audience_oval", "slow_audience_circle", "slow_deep_audience_sweep"],
            "build": ["build_rising_sweep", "build_narrow_to_wide_fan", "build_fastening_circle"],
            "chorus": ["fast_audience_sweep", "fast_audience_circle", "drop_crossing_beams"],
            "drop": ["drop_snap_fan", "drop_crossing_beams", "drop_full_audience_hit"],
        },
        "pulses": {
            "build": ["ramp_up", "soft_pulse", "alternate_whole"],
            "chorus": ["pivot", "double_hit", "chase_whole"],
            "drop": ["double_hit", "gallop", "drop_blinder"],
        },
        "mirror_bias": 0.12,
        "white_bias": -0.05,
    },
    "citrus_pop": {
        "motions": {
            "verse": ["slow_audience_sweep_blue", "slow_high_audience_sweep", "slow_audience_figure_8"],
            "build": ["build_rising_sweep", "build_audience_wave", "build_narrow_to_wide_fan"],
            "chorus": ["fast_audience_sweep", "fast_diagonal_sweep", "snap_position_hits"],
            "drop": ["drop_snap_fan", "drop_crossing_beams", "drop_full_audience_hit"],
        },
        "pulses": {
            "build": ["alternate_whole", "ramp_up", "double_hit"],
            "chorus": ["alternate_whole", "double_hit", "gallop"],
            "drop": ["gallop", "double_hit", "snake"],
        },
        "mirror_bias": 0.20,
        "white_bias": -0.04,
    },
    "polar_haze": {
        "motions": {
            "verse": ["slow_high_audience_sweep", "slow_audience_circle", "break_high_cool_sweep"],
            "build": ["build_rising_sweep", "build_fastening_circle", "build_audience_wave"],
            "chorus": ["fast_audience_circle", "fast_audience_sweep", "fast_audience_figure_8"],
            "drop": ["drop_fast_circle_white", "drop_crossing_beams", "drop_full_audience_hit"],
        },
        "pulses": {
            "build": ["soft_pulse", "alternate_whole", "ramp_up"],
            "chorus": ["alternate_whole", "pivot", "beat_flash"],
            "drop": ["double_hit", "drop_blinder", "chase_whole"],
        },
        "mirror_bias": 0.10,
        "white_bias": -0.02,
    },
    "acid_arc": {
        "motions": {
            "verse": ["slow_random_searchlight", "slow_audience_figure_8", "slow_audience_oval"],
            "build": ["build_color_chase", "build_fastening_circle", "build_audience_wave"],
            "chorus": ["fast_diagonal_sweep", "random_search_hits", "fast_audience_figure_8"],
            "drop": ["drop_crossing_beams", "drop_strobe_sweep", "drop_fast_circle_white"],
        },
        "pulses": {
            "build": ["alternate_whole", "gallop", "double_hit"],
            "chorus": ["gallop", "snake", "pivot"],
            "drop": ["snake", "gallop", "double_hit", "tremolo_dimmer"],
        },
        "mirror_bias": 0.28,
        "white_bias": -0.03,
    },
    "ember_storm": {
        "motions": {
            "verse": ["slow_deep_audience_sweep", "slow_audience_circle", "slow_random_searchlight"],
            "build": ["build_rising_sweep", "build_audience_wave", "build_narrow_to_wide_fan"],
            "chorus": ["fast_audience_sweep", "fast_diagonal_sweep", "snap_position_hits"],
            "drop": ["drop_full_audience_hit", "drop_crossing_beams", "drop_strobe_sweep"],
        },
        "pulses": {
            "build": ["ramp_up", "double_hit", "alternate_whole"],
            "chorus": ["double_hit", "gallop", "pivot"],
            "drop": ["drop_blinder", "gallop", "snake", "beat_flash"],
        },
        "mirror_bias": 0.18,
        "white_bias": -0.04,
    },
    "candy_night": {
        "motions": {
            "verse": ["slow_audience_oval", "slow_audience_figure_8", "slow_high_audience_sweep"],
            "build": ["build_fastening_circle", "build_narrow_to_wide_fan", "build_audience_wave"],
            "chorus": ["fast_audience_circle", "fast_audience_figure_8", "fast_audience_sweep"],
            "drop": ["drop_crossing_beams", "drop_fast_circle_white", "drop_snap_fan"],
        },
        "pulses": {
            "build": ["soft_pulse", "alternate_whole", "pivot"],
            "chorus": ["pivot", "double_hit", "gallop"],
            "drop": ["double_hit", "snake", "beat_flash"],
        },
        "mirror_bias": 0.16,
        "white_bias": -0.05,
    },
    "steel_lotus": {
        "motions": {
            "verse": ["slow_high_audience_sweep", "slow_audience_circle", "slow_random_searchlight"],
            "build": ["build_rising_sweep", "build_fastening_circle", "build_narrow_to_wide_fan"],
            "chorus": ["fast_audience_sweep", "fast_audience_circle", "random_search_hits"],
            "drop": ["drop_crossing_beams", "drop_fast_circle_white", "drop_full_audience_hit"],
        },
        "pulses": {
            "build": ["alternate_whole", "ramp_up", "soft_pulse"],
            "chorus": ["alternate_whole", "pivot", "double_hit"],
            "drop": ["gallop", "double_hit", "chase_whole"],
        },
        "mirror_bias": 0.22,
        "white_bias": -0.03,
    },
}

for _theme_name, _character in TRACK_SHOW_THEME_CHARACTER.items():
    if _theme_name in TRACK_SHOW_THEMES:
        TRACK_SHOW_THEMES[_theme_name].update(_character)


def _motion_profile(pattern, **overrides):
    profile = {
        "pattern": pattern,
        "phase_scale": 1.0,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "lock_color": False,
    }
    profile.update(overrides)
    return profile


def _profile_tilt_phase_scale(profile, default=1.0):
    try:
        return max(0.1, float(profile.get("tilt_phase_scale", default)))
    except (TypeError, ValueError):
        return float(default)


def _profile_tilt_phase_offset(profile, default=0.0):
    try:
        return float(profile.get("tilt_phase_offset", default))
    except (TypeError, ValueError):
        return float(default)

AUTO_SHOW_MOTION_PROFILES = {
    "center": {
        "pattern": "center_hold",
        "phase_scale": 0.0,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 0,
        "speed_max": 30,
        "pan_center": 128,
        "tilt_center": 176,
        "tilt_floor": 164,
    },
    "slow_left_right_sweep": {
        "pattern": "horizontal_sweep",
        "phase_scale": 0.42,
        "spread": 0.22,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": True,
        "use_taught_poses": False,
        "speed_min": 140,
        "speed_max": 180,
        "pan_center": 128,
        "pan_wave": 88,
        "tilt_center": 176,
        "tilt_wave": 0,
        "tilt_floor": 164,
    },
    "fast_left_right_sweep": {
        "pattern": "horizontal_sweep",
        "phase_scale": 0.92,
        "spread": 0.24,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": True,
        "use_taught_poses": False,
        "speed_min": 0,
        "speed_max": 40,
        "pan_center": 128,
        "pan_wave": 98,
        "tilt_center": 178,
        "tilt_wave": 0,
        "tilt_floor": 166,
    },
    "up_down_sweep": {
        "pattern": "vertical_sweep",
        "use_full_tilt_range": True,
        "phase_scale": 0.62,
        "spread": 0.10,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 100,
        "speed_max": 140,
        "pan_center": 128,
        "pan_wave": 0,
        "tilt_min": 0,
        "tilt_max": 255,
    },
    "audience_sweep": {
        "pattern": "horizontal_sweep",
        "phase_scale": 0.62,
        "spread": 0.34,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": True,
        "use_taught_poses": False,
        "speed_min": 60,
        "speed_max": 100,
        "pan_center": 128,
        "pan_wave": 88,
        "tilt_center": 198,
        "tilt_wave": 0,
        "tilt_floor": 182,
        "rgbw": [255, 120, 0, 0],
    },
    "ceiling_sweep": {
        "pattern": "horizontal_sweep",
        "phase_scale": 0.58,
        "spread": 0.34,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": True,
        "use_taught_poses": False,
        "speed_min": 80,
        "speed_max": 120,
        "pan_center": 128,
        "pan_wave": 88,
        "tilt_center": 0,
        "tilt_wave": 0,
        "rgbw": [0, 80, 255, 100],
    },
    "diagonal_sweep": {
        "pattern": "diagonal_sweep",
        "phase_scale": 0.66,
        "spread": 0.18,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 60,
        "speed_max": 100,
        "pan_center": 128,
        "pan_wave": 88,
        "tilt_center": 184,
        "tilt_wave": 34,
        "tilt_floor": 164,
    },
    "reverse_diagonal_sweep": {
        "pattern": "reverse_diagonal_sweep",
        "phase_scale": 0.66,
        "spread": 0.18,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 60,
        "speed_max": 100,
        "pan_center": 128,
        "pan_wave": 88,
        "tilt_center": 184,
        "tilt_wave": 34,
        "tilt_floor": 164,
    },
    "slow_circle": {
        "pattern": "circle",
        "phase_scale": 0.34,
        "spread": 0.10,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 120,
        "speed_max": 160,
        "pan_center": 128,
        "pan_wave": 60,
        "tilt_center": 184,
        "tilt_wave": 28,
        "tilt_floor": 166,
        "rgbw": [0, 0, 255, 0],
    },
    "fast_circle": {
        "pattern": "circle",
        "phase_scale": 0.82,
        "spread": 0.10,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 0,
        "speed_max": 40,
        "pan_center": 128,
        "pan_wave": 78,
        "tilt_center": 186,
        "tilt_wave": 34,
        "tilt_floor": 168,
        "rgbw": [255, 255, 255, 255],
    },
    "oval_circle": {
        "pattern": "circle",
        "phase_scale": 0.52,
        "spread": 0.12,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 60,
        "speed_max": 100,
        "pan_center": 128,
        "pan_wave": 88,
        "tilt_center": 186,
        "tilt_wave": 18,
        "tilt_floor": 170,
        "rgbw": [180, 0, 255, 0],
    },
    "figure_8": {
        "pattern": "figure_8",
        "phase_scale": 0.56,
        "spread": 0.12,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 40,
        "speed_max": 80,
        "pan_center": 128,
        "pan_wave": 70,
        "tilt_center": 186,
        "tilt_wave": 34,
        "tilt_floor": 168,
        "rgbw": [255, 255, 255, 255],
    },
    "small_figure_8": {
        "pattern": "figure_8",
        "phase_scale": 0.42,
        "spread": 0.10,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 100,
        "speed_max": 140,
        "pan_center": 128,
        "pan_wave": 38,
        "tilt_center": 184,
        "tilt_wave": 24,
        "tilt_floor": 170,
        "rgbw": [0, 80, 255, 0],
    },
    "random_searchlight": {
        "pattern": "random_searchlight",
        "phase_scale": 1.0,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 20,
        "speed_max": 60,
        "window_beats": 8.0,
        "pan_min": 30,
        "pan_max": 225,
        "tilt_min": 50,
        "tilt_max": 210,
    },
    "slow_searchlight": {
        "pattern": "random_searchlight",
        "phase_scale": 1.0,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 150,
        "speed_max": 210,
        "window_beats": 24.0,
        "pan_min": 60,
        "pan_max": 196,
        "tilt_min": 70,
        "tilt_max": 190,
    },
    "snap_position_hits": {
        "pattern": "snap_hits",
        "phase_scale": 1.0,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 0,
        "speed_max": 0,
    },
    "strobe_sweep": {
        "pattern": "horizontal_sweep",
        "phase_scale": 0.90,
        "spread": 0.24,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": True,
        "use_taught_poses": False,
        "speed_min": 20,
        "speed_max": 60,
        "pan_center": 128,
        "pan_wave": 88,
        "tilt_center": 182,
        "tilt_wave": 0,
        "tilt_floor": 170,
        "strobe_min": 180,
        "strobe_max": 255,
    },
    "blinder_flash": {
        "pattern": "blinder_flash",
        "phase_scale": 1.0,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 0,
        "speed_max": 0,
        "tilt_center": 255,
    },
    "fan_open": {
        "pattern": "fan_open",
        "phase_scale": 0.0,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 20,
        "speed_max": 60,
        "fan_width": 88,
        "tilt_center": 182,
        "tilt_floor": 172,
        "fan_positions_4": [60, 105, 150, 195],
        "fan_positions_2": [105, 150],
    },
    "fan_close": {
        "pattern": "center_hold",
        "phase_scale": 0.0,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 20,
        "speed_max": 60,
        "pan_center": 128,
        "tilt_center": 176,
        "tilt_floor": 166,
    },
    "fan_wave": {
        "pattern": "fan_wave",
        "phase_scale": 0.60,
        "spread": 0.08,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 60,
        "speed_max": 100,
        "fan_width": 92,
        "fan_wave_pan_positions_4": [70, 110, 150, 190],
        "fan_wave_pan_positions_2": [110, 150],
        "fan_wave_tilt_min": 0,
        "fan_wave_tilt_max": 255,
        "rgbw": [0, 120, 255, 120],
    },
    "crossing_beams": {
        "pattern": "crossing_beams",
        "phase_scale": 0.70,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 40,
        "speed_max": 80,
        "crossing_frames_4": [(60, 182), (100, 182), (156, 182), (196, 182)],
        "crossing_frames_2": [(100, 182), (156, 182)],
        "tilt_floor": 174,
        "rgbw": [255, 255, 255, 255],
    },
    "mirror_bounce": {
        "pattern": "mirror_bounce",
        "use_full_tilt_range": True,
        "phase_scale": 0.72,
        "spread": 0.20,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "member_mirror": True,
        "use_taught_poses": False,
        "speed_min": 10,
        "speed_max": 50,
        "pan_center": 128,
        "pan_wave": 68,
        "tilt_center": 184,
        "tilt_wave": 20,
        "tilt_floor": 170,
        "rgbw": [255, 0, 255, 0],
    },
    "color_chase_movement": {
        "pattern": "horizontal_sweep",
        "phase_scale": 0.62,
        "spread": 0.22,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": True,
        "use_taught_poses": False,
        "speed_min": 60,
        "speed_max": 100,
        "pan_center": 128,
        "pan_wave": 88,
        "tilt_center": 182,
        "tilt_wave": 18,
        "tilt_floor": 170,
        "color_program_min": 232,
        "color_program_max": 255,
        "color_speed_min": 80,
        "color_speed_max": 180,
        "rgbw": [0, 0, 0, 0],
    },
    "pulse_circle": {
        "pattern": "pulse_circle",
        "phase_scale": 0.52,
        "spread": 0.10,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 70,
        "speed_max": 110,
        "pan_center": 128,
        "pan_wave": 55,
        "tilt_center": 184,
        "tilt_wave": 24,
        "tilt_floor": 170,
        "rgbw": [0, 80, 255, 80],
    },
    "sweep_narrow": {"pattern": "smooth_sweep", "phase_scale": 0.46, "spread": 0.52, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 12, "edge_drop": 4, "snap": 0, "mirror": True, "pan_base": 34, "pan_extra": 22, "tilt_base": 174, "tilt_wave": 20, "tilt_extra": 10},
    "sweep_mid": {"pattern": "smooth_sweep", "phase_scale": 0.58, "spread": 0.78, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 10, "edge_drop": 6, "snap": 0, "mirror": True, "pan_base": 50, "pan_extra": 30, "tilt_base": 162, "tilt_wave": 28, "tilt_extra": 14},
    "sweep_wide": {"pattern": "smooth_sweep", "phase_scale": 0.72, "spread": 1.08, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 8, "edge_drop": 8, "snap": 0, "mirror": True, "pan_base": 68, "pan_extra": 42, "tilt_base": 152, "tilt_wave": 34, "tilt_extra": 16},
    "sweep_arc": {"pattern": "arc_sweep", "phase_scale": 0.64, "spread": 0.96, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 14, "edge_drop": 6, "snap": 0, "mirror": True, "pan_base": 58, "pan_extra": 34, "tilt_base": 160, "tilt_wave": 38, "tilt_extra": 18},
    "sweep_high": {"pattern": "tilt_sweep", "use_full_tilt_range": True, "phase_scale": 0.50, "spread": 0.66, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 18, "edge_drop": 4, "snap": 0, "mirror": True, "pan_base": 40, "pan_extra": 24, "tilt_base": 176, "tilt_wave": 20, "tilt_extra": 10},
    "sweep_narrow_mirror": {"pattern": "smooth_sweep", "phase_scale": 0.46, "spread": 0.52, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 12, "edge_drop": 4, "snap": 0, "mirror": True, "member_mirror": True, "pan_base": 34, "pan_extra": 22, "tilt_base": 174, "tilt_wave": 20, "tilt_extra": 10},
    "sweep_mid_mirror": {"pattern": "smooth_sweep", "phase_scale": 0.58, "spread": 0.78, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 10, "edge_drop": 6, "snap": 0, "mirror": True, "member_mirror": True, "pan_base": 50, "pan_extra": 30, "tilt_base": 162, "tilt_wave": 28, "tilt_extra": 14},
    "sweep_wide_mirror": {"pattern": "smooth_sweep", "phase_scale": 0.72, "spread": 1.08, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 8, "edge_drop": 8, "snap": 0, "mirror": True, "member_mirror": True, "pan_base": 68, "pan_extra": 42, "tilt_base": 152, "tilt_wave": 34, "tilt_extra": 16},
    "sweep_arc_mirror": {"pattern": "arc_sweep", "phase_scale": 0.64, "spread": 0.96, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 14, "edge_drop": 6, "snap": 0, "mirror": True, "member_mirror": True, "pan_base": 58, "pan_extra": 34, "tilt_base": 160, "tilt_wave": 38, "tilt_extra": 18},
    "sweep_high_mirror": {"pattern": "tilt_sweep", "use_full_tilt_range": True, "phase_scale": 0.50, "spread": 0.66, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 18, "edge_drop": 4, "snap": 0, "mirror": True, "member_mirror": True, "pan_base": 40, "pan_extra": 24, "tilt_base": 176, "tilt_wave": 20, "tilt_extra": 10},
}

AUTO_SHOW_MOTION_PROFILES.update({
    "center_audience_white": _motion_profile("center_hold", pan_center=128, tilt_center=175, pan_tilt_speed_static=20, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "center_audience_blue": _motion_profile("center_hold", pan_center=128, tilt_center=175, pan_tilt_speed_static=20, dimmer_static=180, rgbw=[0, 40, 255, 80]),
    "wide_fan_white": _motion_profile("static_positions", positions_4=[60, 105, 150, 195], positions_2=[105, 150], tilt_static=180, pan_tilt_speed_static=40, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "wide_fan_blue": _motion_profile("static_positions", positions_4=[60, 105, 150, 195], positions_2=[105, 150], tilt_static=180, pan_tilt_speed_static=40, dimmer_static=200, rgbw=[0, 80, 255, 120]),
    "narrow_fan_white": _motion_profile("static_positions", positions_4=[100, 120, 136, 156], positions_2=[120, 136], tilt_static=180, pan_tilt_speed_static=40, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "crossing_static_beams": _motion_profile("static_positions", positions_4=[196, 156, 100, 60], positions_2=[156, 100], tilt_static=185, pan_tilt_speed_static=50, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "low_audience_amber": _motion_profile("center_hold", pan_center=128, tilt_center=194, pan_tilt_speed_static=20, dimmer_static=180, rgbw=[255, 120, 0, 0]),
    "high_audience_cool_white": _motion_profile("center_hold", pan_center=128, tilt_center=145, pan_tilt_speed_static=20, dimmer_static=220, rgbw=[120, 180, 255, 255]),
    "slow_audience_sweep_white": _motion_profile("horizontal_sweep", phase_scale=0.42, tilt_phase_scale=3.4, full_tilt_curve=0.64, spread=0.0, pan_center=128, pan_wave=88, tilt_center=180, tilt_wave=0, pan_tilt_speed_static=160, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "slow_audience_sweep_blue": _motion_profile("horizontal_sweep", phase_scale=0.40, tilt_phase_scale=3.6, full_tilt_curve=0.62, spread=0.0, pan_center=128, pan_wave=88, tilt_center=180, tilt_wave=0, pan_tilt_speed_static=170, dimmer_static=200, rgbw=[0, 80, 255, 100]),
    "slow_deep_audience_sweep": _motion_profile("horizontal_sweep", phase_scale=0.44, tilt_phase_scale=3.2, full_tilt_curve=0.62, spread=0.0, pan_center=128, pan_wave=88, tilt_center=192, tilt_wave=0, pan_tilt_speed_static=150, dimmer_static=220, rgbw=[255, 120, 0, 0]),
    "slow_high_audience_sweep": _motion_profile("horizontal_sweep", phase_scale=0.40, tilt_phase_scale=3.4, full_tilt_curve=0.62, spread=0.0, pan_center=128, pan_wave=88, tilt_center=145, tilt_wave=0, pan_tilt_speed_static=160, dimmer_static=220, rgbw=[100, 160, 255, 255]),
    "slow_audience_circle": _motion_profile("circle", phase_scale=0.34, tilt_phase_scale=2.4, full_tilt_curve=0.64, spread=0.0, pan_center=128, pan_wave=60, tilt_center=180, tilt_wave=35, pan_tilt_speed_static=140, dimmer_static=220, rgbw=[0, 0, 255, 80]),
    "slow_audience_oval": _motion_profile("circle", phase_scale=0.44, tilt_phase_scale=2.1, full_tilt_curve=0.66, spread=0.0, pan_center=128, pan_wave=88, tilt_center=180, tilt_wave=25, pan_tilt_speed_static=120, dimmer_static=220, rgbw=[160, 0, 255, 40]),
    "slow_audience_figure_8": _motion_profile("figure_8", phase_scale=0.34, tilt_phase_scale=2.0, full_tilt_curve=0.64, spread=0.0, pan_center=128, pan_wave=70, tilt_center=178, tilt_wave=36, pan_tilt_speed_static=130, dimmer_static=220, rgbw=[150, 210, 255, 80]),
    "slow_random_searchlight": _motion_profile("random_searchlight", window_beats=24.0, pan_min=60, pan_max=196, tilt_min=148, tilt_max=198, pan_tilt_speed_static=180, dimmer_static=200, rgbw=[80, 120, 255, 80]),
    "fast_audience_sweep": _motion_profile("horizontal_sweep", phase_scale=0.92, tilt_phase_scale=2.2, full_tilt_curve=0.60, spread=0.0, pan_center=128, pan_wave=98, tilt_center=180, tilt_wave=0, pan_tilt_speed_static=20, dimmer_static=255, rgbw=[255, 120, 35, 0]),
    "fast_audience_circle": _motion_profile("circle", phase_scale=0.82, tilt_phase_scale=1.8, full_tilt_curve=0.60, spread=0.0, pan_center=128, pan_wave=78, tilt_center=180, tilt_wave=34, pan_tilt_speed_static=20, dimmer_static=255, rgbw=[0, 120, 255, 60]),
    "fast_audience_figure_8": _motion_profile("figure_8", phase_scale=0.86, tilt_phase_scale=1.7, full_tilt_curve=0.60, spread=0.0, pan_center=128, pan_wave=80, tilt_center=182, tilt_wave=36, pan_tilt_speed_static=25, dimmer_static=255, rgbw=[255, 60, 200, 0]),
    "snap_position_hits": _motion_profile("snap_hits", use_full_tilt_range=True, pan_tilt_speed_static=0, dimmer_static=255, rgbw=[255, 255, 255, 255], snap_positions=[(40, 155), (216, 155), (216, 215), (40, 215), (128, 180)]),
    "fast_diagonal_sweep": _motion_profile("diagonal_sweep", phase_scale=0.84, tilt_phase_scale=1.8, full_tilt_curve=0.58, spread=0.0, pan_center=128, pan_wave=88, tilt_center=185, tilt_wave=40, pan_tilt_speed_static=30, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "reverse_fast_diagonal": _motion_profile("reverse_diagonal_sweep", phase_scale=0.84, tilt_phase_scale=1.8, full_tilt_curve=0.58, spread=0.0, pan_center=128, pan_wave=88, tilt_center=185, tilt_wave=40, pan_tilt_speed_static=30, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "mirror_bounce_show": _motion_profile("mirror_bounce", use_full_tilt_range=True, phase_scale=0.82, tilt_phase_scale=1.6, full_tilt_curve=0.60, spread=0.0, pan_center=128, pan_wave=78, tilt_center=188, tilt_wave=35, pan_tilt_speed_static=30, dimmer_static=255, rgbw=[255, 0, 255, 0], member_mirror=True),
    "random_search_hits": _motion_profile("random_searchlight", window_beats=4.0, pan_min=30, pan_max=225, tilt_min=148, tilt_max=198, pan_tilt_speed_static=20, dimmer_static=255, rgbw=[255, 110, 40, 0]),
    "build_rising_sweep": _motion_profile("rising_sweep", use_full_tilt_range=True, phase_scale=0.62, tilt_phase_scale=1.8, full_tilt_curve=0.60, pan_center=128, pan_wave=88, tilt_min=150, tilt_max=196, pan_tilt_speed_static=70, dimmer_min=120, dimmer_max=255, rgbw=[255, 170, 45, 0]),
    "build_dimmer_pulse": _motion_profile("hold_pulse", pan_center=128, tilt_center=178, pulse_phase_scale=0.50, pan_tilt_speed_static=60, dimmer_min=80, dimmer_max=255, rgbw=[255, 120, 40, 0]),
    "build_fastening_circle": _motion_profile("pulse_circle", phase_scale=0.70, tilt_phase_scale=1.7, full_tilt_curve=0.60, spread=0.0, pan_center=128, pan_wave=65, tilt_center=178, tilt_wave=28, pan_tilt_speed_static=80, dimmer_min=150, dimmer_max=255, rgbw=[150, 80, 255, 0]),
    "build_narrow_to_wide_fan": _motion_profile("fan_morph", positions_start_4=[115, 125, 135, 145], positions_mid_4=[90, 115, 140, 165], positions_end_4=[60, 105, 150, 195], positions_start_2=[122, 134], positions_mid_2=[112, 144], positions_end_2=[105, 150], tilt_static=178, phase_scale=0.45, pan_tilt_speed_static=70, dimmer_min=150, dimmer_max=255, rgbw=[0, 160, 255, 40]),
    "build_strobe_ramp": _motion_profile("horizontal_sweep", phase_scale=0.76, tilt_phase_scale=2.2, full_tilt_curve=0.60, spread=0.0, pan_center=128, pan_wave=88, tilt_center=178, tilt_wave=0, pan_tilt_speed_static=30, dimmer_static=255, strobe_min=40, strobe_max=220, rgbw=[255, 160, 55, 0]),
    "build_color_chase": _motion_profile("horizontal_sweep", phase_scale=0.62, tilt_phase_scale=2.0, full_tilt_curve=0.60, spread=0.0, pan_center=128, pan_wave=88, tilt_center=185, tilt_wave=25, pan_tilt_speed_static=80, dimmer_static=255, color_program_min=232, color_program_max=255, color_speed_min=80, color_speed_max=180, rgbw=[0, 0, 0, 0], lock_color=True),
    "build_audience_wave": _motion_profile("fan_wave", phase_scale=0.60, tilt_phase_scale=2.3, full_tilt_curve=0.58, spread=0.0, fan_wave_pan_positions_4=[70, 110, 150, 190], fan_wave_pan_positions_2=[110, 150], fan_wave_tilt_min=154, fan_wave_tilt_max=202, pan_tilt_speed_static=80, dimmer_min=180, dimmer_max=255, rgbw=[0, 120, 255, 120]),
    "build_white_flash_prep": _motion_profile("hold_pulse", pan_center=128, tilt_center=184, pulse_phase_scale=1.00, pan_tilt_speed_static=0, dimmer_min=0, dimmer_max=220, rgbw=[255, 255, 255, 255], lock_color=True),
    "drop_white_blinder": _motion_profile("center_hold", pan_center=128, tilt_center=198, pan_tilt_speed_static=0, dimmer_static=255, rgbw=[255, 255, 255, 255], lock_color=True),
    "drop_strobe_sweep": _motion_profile("horizontal_sweep", phase_scale=0.96, tilt_phase_scale=2.4, full_tilt_curve=0.58, spread=0.0, pan_center=128, pan_wave=98, tilt_center=185, tilt_wave=0, pan_tilt_speed_static=20, dimmer_static=255, strobe_min=200, strobe_max=255, rgbw=[255, 255, 255, 255], lock_color=True),
    "drop_snap_fan": _motion_profile("static_positions", positions_4=[50, 100, 155, 205], positions_2=[100, 155], tilt_static=188, pan_tilt_speed_static=0, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "drop_fast_circle_white": _motion_profile("circle", phase_scale=1.00, tilt_phase_scale=1.9, full_tilt_curve=0.58, spread=0.0, pan_center=128, pan_wave=85, tilt_center=182, tilt_wave=36, pan_tilt_speed_static=10, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "drop_crossing_beams": _motion_profile("crossing_beams", phase_scale=0.92, spread=0.0, crossing_frames_4=[(196, 185), (156, 185), (100, 185), (60, 185)], crossing_frames_2=[(156, 185), (100, 185)], pan_tilt_speed_static=20, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "drop_red_blue_bounce": _motion_profile("mirror_bounce", use_full_tilt_range=True, phase_scale=0.92, tilt_phase_scale=1.8, full_tilt_curve=0.58, spread=0.0, pan_center=128, pan_wave=78, tilt_center=184, tilt_wave=28, pan_tilt_speed_static=20, dimmer_static=255, rgbw=[255, 0, 255, 0], member_mirror=True),
    "drop_full_audience_hit": _motion_profile("center_hold", pan_center=128, tilt_center=202, pan_tilt_speed_static=0, dimmer_static=255, rgbw=[255, 255, 255, 255], lock_color=True),
    "drop_blackout_hit": _motion_profile("blackout_hit", pan_center=128, tilt_center=202, pan_tilt_speed_static=0, dimmer_min=0, dimmer_max=255, rgbw=[255, 255, 255, 255], lock_color=True),
    "break_soft_blue_center": _motion_profile("center_hold", pan_center=128, tilt_center=165, pan_tilt_speed_static=160, dimmer_static=100, rgbw=[0, 40, 255, 40]),
    "break_slow_pulse_circle": _motion_profile("pulse_circle", phase_scale=0.34, tilt_phase_scale=2.0, full_tilt_curve=0.64, spread=0.0, pan_center=128, pan_wave=55, tilt_center=180, tilt_wave=35, pan_tilt_speed_static=160, dimmer_min=60, dimmer_max=180, rgbw=[0, 80, 255, 80]),
    "break_purple_oval": _motion_profile("circle", phase_scale=0.34, tilt_phase_scale=2.1, full_tilt_curve=0.66, spread=0.0, pan_center=128, pan_wave=70, tilt_center=170, tilt_wave=20, pan_tilt_speed_static=170, dimmer_static=140, rgbw=[180, 0, 255, 0]),
    "break_high_cool_sweep": _motion_profile("horizontal_sweep", phase_scale=0.38, tilt_phase_scale=3.4, full_tilt_curve=0.62, spread=0.0, pan_center=128, pan_wave=78, tilt_center=145, tilt_wave=0, pan_tilt_speed_static=180, dimmer_static=130, rgbw=[100, 180, 255, 180]),
    "break_dimmed_fan": _motion_profile("static_positions", positions_4=[70, 110, 150, 190], positions_2=[110, 150], tilt_static=165, pan_tilt_speed_static=120, dimmer_static=90, rgbw=[0, 80, 255, 80]),
    "break_cyan_figure_8": _motion_profile("figure_8", phase_scale=0.32, tilt_phase_scale=2.0, full_tilt_curve=0.64, spread=0.0, pan_center=128, pan_wave=45, tilt_center=175, tilt_wave=25, pan_tilt_speed_static=170, dimmer_static=120, rgbw=[0, 255, 255, 60]),
    "break_warm_low_glow": _motion_profile("center_hold", pan_center=128, tilt_center=195, pan_tilt_speed_static=180, dimmer_static=100, rgbw=[255, 130, 20, 80]),
    "break_no_movement_fade": _motion_profile("hold_pulse", pan_center=128, tilt_center=170, pulse_phase_scale=0.22, pan_tilt_speed_static=200, dimmer_min=0, dimmer_max=160, rgbw=[0, 60, 255, 80]),
    "live_audience_tilt_sweep": _motion_profile("tilt_sweep", use_full_tilt_range=True, tilt_phase_scale=2.0, full_tilt_curve=0.58, pan_base=12, pan_extra=10, tilt_base=188, tilt_wave=34, tilt_extra=12, pan_tilt_speed_static=26, dimmer_static=255, rgbw=[255, 255, 255, 255]),
})

AUTO_SHOW_COLOR_PROFILES = {
    "yellow_blue": {
        "label": "Yellow Blue",
        "primary": (255, 210, 0, 0),
        "secondary": (0, 95, 255, 0),
        "accent": (255, 245, 120, 0),
        "white": (255, 255, 255, 60),
        "base_mix": 0.38,
        "accent_mix": 0.08,
        "white_mix": 0.005,
        "split_mix": 0.32,
    },
    "magenta_cyan": {
        "label": "Magenta Cyan",
        "primary": (255, 30, 190, 0),
        "secondary": (0, 220, 255, 0),
        "accent": (255, 140, 230, 0),
        "white": (255, 255, 255, 60),
        "base_mix": 0.40,
        "accent_mix": 0.08,
        "white_mix": 0.005,
        "split_mix": 0.34,
    },
    "amber_teal": {
        "label": "Amber Teal",
        "primary": (255, 150, 20, 0),
        "secondary": (0, 210, 185, 0),
        "accent": (255, 215, 120, 0),
        "white": (255, 250, 235, 50),
        "base_mix": 0.36,
        "accent_mix": 0.08,
        "white_mix": 0.004,
        "split_mix": 0.28,
    },
    "amber_violet": {
        "label": "Amber Violet",
        "primary": (255, 165, 30, 0),
        "secondary": (145, 70, 255, 0),
        "accent": (255, 210, 140, 0),
        "white": (255, 248, 240, 55),
        "base_mix": 0.36,
        "accent_mix": 0.08,
        "white_mix": 0.004,
        "split_mix": 0.30,
    },
    "teal_orange": {
        "label": "Teal Orange",
        "primary": (0, 210, 200, 0),
        "secondary": (255, 110, 15, 0),
        "accent": (255, 190, 95, 0),
        "white": (250, 255, 255, 55),
        "base_mix": 0.38,
        "accent_mix": 0.08,
        "white_mix": 0.005,
        "split_mix": 0.31,
    },
    "violet_lime": {
        "label": "Violet Lime",
        "primary": (165, 65, 255, 0),
        "secondary": (180, 255, 30, 0),
        "accent": (235, 200, 255, 0),
        "white": (255, 255, 240, 45),
        "base_mix": 0.33,
        "accent_mix": 0.07,
        "white_mix": 0.003,
        "split_mix": 0.30,
    },
    "ice_fire": {
        "label": "Ice Fire",
        "primary": (90, 215, 255, 0),
        "secondary": (255, 75, 0, 0),
        "accent": (255, 240, 215, 0),
        "white": (255, 255, 255, 120),
        "base_mix": 0.40,
        "accent_mix": 0.07,
        "white_mix": 0.010,
        "split_mix": 0.34,
    },
    "rose_mint": {
        "label": "Rose Mint",
        "primary": (255, 90, 150, 0),
        "secondary": (45, 245, 190, 0),
        "accent": (255, 205, 225, 0),
        "white": (250, 255, 248, 45),
        "base_mix": 0.35,
        "accent_mix": 0.07,
        "white_mix": 0.004,
        "split_mix": 0.28,
    },
    "cobalt_amber": {
        "label": "Cobalt Amber",
        "primary": (0, 85, 255, 0),
        "secondary": (255, 170, 25, 0),
        "accent": (175, 210, 255, 0),
        "white": (255, 248, 235, 60),
        "base_mix": 0.40,
        "accent_mix": 0.07,
        "white_mix": 0.005,
        "split_mix": 0.32,
    },
    "ruby_lime": {
        "label": "Ruby Lime",
        "primary": (255, 40, 60, 0),
        "secondary": (175, 255, 35, 0),
        "accent": (255, 190, 90, 0),
        "white": (255, 255, 235, 45),
        "base_mix": 0.35,
        "accent_mix": 0.07,
        "white_mix": 0.003,
        "split_mix": 0.30,
    },
    "lilac_gold": {
        "label": "Lilac Gold",
        "primary": (170, 110, 255, 0),
        "secondary": (255, 205, 55, 0),
        "accent": (240, 210, 255, 0),
        "white": (255, 252, 235, 55),
        "base_mix": 0.35,
        "accent_mix": 0.07,
        "white_mix": 0.004,
        "split_mix": 0.28,
    },
    "blue_amber": {
        "label": "Blue Amber",
        "primary": (0, 85, 255, 0),
        "secondary": (255, 150, 20, 0),
        "accent": (255, 215, 110, 0),
        "white": (255, 250, 235, 55),
        "base_mix": 0.40,
        "accent_mix": 0.07,
        "white_mix": 0.005,
        "split_mix": 0.34,
    },
    "purple_gold": {
        "label": "Purple Gold",
        "primary": (155, 65, 255, 0),
        "secondary": (255, 205, 35, 0),
        "accent": (230, 205, 255, 0),
        "white": (255, 250, 235, 55),
        "base_mix": 0.37,
        "accent_mix": 0.07,
        "white_mix": 0.004,
        "split_mix": 0.31,
    },
    "deep_blue_white": {
        "label": "Deep Blue White",
        "primary": (0, 70, 255, 0),
        "secondary": (235, 245, 255, 90),
        "accent": (140, 180, 255, 0),
        "white": (255, 255, 255, 90),
        "base_mix": 0.36,
        "accent_mix": 0.06,
        "white_mix": 0.010,
        "split_mix": 0.28,
    },
    "red_white": {
        "label": "Red White",
        "primary": (255, 35, 35, 0),
        "secondary": (255, 255, 255, 120),
        "accent": (255, 155, 155, 0),
        "white": (255, 255, 255, 90),
        "base_mix": 0.34,
        "accent_mix": 0.06,
        "white_mix": 0.012,
        "split_mix": 0.26,
    },
    "pink_blue": {
        "label": "Pink Blue",
        "primary": (255, 40, 180, 0),
        "secondary": (0, 105, 255, 0),
        "accent": (255, 145, 215, 0),
        "white": (245, 250, 255, 55),
        "base_mix": 0.39,
        "accent_mix": 0.07,
        "white_mix": 0.005,
        "split_mix": 0.33,
    },
}


def fixture_preset(fixture_id):
    fixture = find_fixture(FIXTURE_LIBRARY, fixture_id)
    preset = dict(FIXTURE_PRESETS.get(fixture_id, {}))
    preset.setdefault("label_base", fixture["model"])
    preset.setdefault("mode", fixture["modes"][0]["name"])
    return preset


def slot_sequence_index(slot_id, base_id):
    slot_id = str(slot_id or "")
    base_id = str(base_id or "")
    if slot_id == "head":
        return 0
    if slot_id == base_id:
        return 1
    prefix = f"{base_id}_"
    if slot_id.startswith(prefix):
        suffix = slot_id[len(prefix) :]
        with suppress(Exception):
            return int(suffix)
    return None


def default_group_name_for_slot(slot_id, fixture_id, label=""):
    fixture_id = str(fixture_id or "")
    label_text = str(label or "").lower()
    if fixture_id == "shehds_led_wash_7x12w_rgbw_moving_head" or "moving head" in label_text:
        moving_index = slot_sequence_index(slot_id, "moving_head")
        pair_index = 0 if moving_index is None else max(0, moving_index // 2)
        pair_index = min(pair_index, 25)
        return f"movers_{chr(ord('a') + pair_index)}"
    if fixture_id == "shehds_flat_par_12x3w_rgbw" or "par" in label_text:
        return "pars"
    if fixture_id == "uking_zq06016" or "wash" in label_text:
        return "washes"
    return "fixtures"


def mode_capabilities(mode):
    channel_types = {channel["type"] for channel in mode["channels"]}
    color_components = {
        channel.get("component")
        for channel in mode["channels"]
        if channel["type"] == "color"
    }
    return {
        "dimmer": "intensity" in channel_types,
        "strobe": "strobe" in channel_types,
        "program": any(
            channel_type in channel_types
            for channel_type in ("program", "color_program", "auto_mode")
        ),
        "speed": any(channel_type in channel_types for channel_type in ("speed", "color_speed")),
        "pan": "pan" in channel_types,
        "pan_fine": "pan_fine" in channel_types,
        "tilt": "tilt" in channel_types,
        "tilt_fine": "tilt_fine" in channel_types,
        "pan_tilt_speed": "pan_tilt_speed" in channel_types,
        "white": "white" in color_components or "coolwhite" in color_components,
    }


def mode_custom_controls(mode):
    if not isinstance(mode, dict):
        return []
    controls = []
    seen = set()
    for channel in mode.get("channels", []):
        if channel.get("type") != "custom":
            continue
        control_id = str(
            channel.get("control")
            or channel.get("id")
            or channel.get("name")
            or f"custom_{channel.get('offset', 0)}"
        ).strip()
        if not control_id or control_id in seen:
            continue
        seen.add(control_id)
        controls.append(
            {
                "id": control_id,
                "name": str(channel.get("name") or control_id),
                "offset": int(channel.get("offset", 0) or 0),
                "default": clamp_dmx(channel.get("default", 0) or 0),
                "ranges": list(channel.get("ranges") or []),
            }
        )
    return controls


def custom_control_channel(mode, control_id):
    if not isinstance(mode, dict):
        return None
    requested = str(control_id or "").strip().lower()
    if not requested:
        return None
    for channel in mode.get("channels", []):
        if channel.get("type") != "custom":
            continue
        current = str(
            channel.get("control")
            or channel.get("id")
            or channel.get("name")
            or ""
        ).strip().lower()
        if current == requested:
            return channel
    return None


def indexed_color_rgbw(channel, value):
    if not isinstance(channel, dict):
        return None
    entries = list(channel.get("indexed_colors") or [])
    if not entries:
        return None
    try:
        dmx_value = clamp_dmx(value)
    except Exception:
        dmx_value = 0
    chosen = None
    for entry in entries:
        try:
            entry_value = clamp_dmx(entry.get("value", 0))
        except Exception:
            continue
        if entry_value <= dmx_value:
            chosen = entry
        else:
            break
    if chosen is None:
        chosen = entries[0]
    name = str(chosen.get("name", "")).strip().lower()
    return INDEXED_COLOR_RGBW.get(name)


def indexed_color_value_for_rgbw(channel, rgbw):
    if not isinstance(channel, dict):
        return None
    entries = list(channel.get("indexed_colors") or [])
    if not entries:
        return None
    try:
        red = clamp_dmx(rgbw[0])
        green = clamp_dmx(rgbw[1])
        blue = clamp_dmx(rgbw[2])
        white = clamp_dmx(rgbw[3] if len(rgbw) > 3 else 0)
    except Exception:
        return None
    if white >= max(red, green, blue) + 32 or white >= 170:
        for entry in entries:
            if str(entry.get("name", "")).strip().lower() in ("white", "open"):
                return clamp_dmx(entry.get("value", 0))
    best_value = None
    best_distance = None
    for entry in entries:
        name = str(entry.get("name", "")).strip().lower()
        reference = INDEXED_COLOR_RGBW.get(name)
        if not reference:
            continue
        rr, rg, rb, rw = reference
        distance = (
            (red - rr) ** 2
            + (green - rg) ** 2
            + (blue - rb) ** 2
            + ((white - rw) * 0.8) ** 2
        )
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_value = clamp_dmx(entry.get("value", 0))
    return best_value


def preview_token(text, fallback="item"):
    raw = str(text or "").strip().lower()
    if not raw:
        return fallback
    pieces = []
    current = []
    for char in raw:
        if char.isalnum():
            current.append(char)
        elif current:
            pieces.append("".join(current))
            current = []
    if current:
        pieces.append("".join(current))
    token = "_".join(piece for piece in pieces if piece)
    return token or fallback


def indexed_wheel_entries(channel, key):
    if not isinstance(channel, dict):
        return []
    entries = []
    for index, entry in enumerate(list(channel.get(key) or [])):
        label = str(entry.get("name") or f"Item {index + 1}").strip() or f"Item {index + 1}"
        try:
            value = clamp_dmx(entry.get("value", 0))
        except Exception:
            value = 0
        entries.append(
            {
                "index": index,
                "value": value,
                "label": label,
                "token": preview_token(label, fallback=f"item_{index + 1}"),
            }
        )
    return entries


def indexed_wheel_cycle_rate(value):
    dmx_value = clamp_dmx(value)
    if dmx_value < 128:
        return 0.0
    normalized = (dmx_value - 128) / 127.0
    return 5.6 - normalized * 4.8


def indexed_wheel_preview_state(channel, value, key):
    entries = indexed_wheel_entries(channel, key)
    if not entries:
        return None
    dmx_value = clamp_dmx(value)
    if dmx_value < 128:
        chosen = entries[0]
        for entry in entries:
            if entry["value"] <= dmx_value:
                chosen = entry
            else:
                break
        return {
            "index": chosen["index"],
            "label": chosen["label"],
            "token": chosen["token"],
            "cycle": False,
            "cycle_rate": 0.0,
            "count": len(entries),
        }
    base = entries[0]
    return {
        "index": base["index"],
        "label": base["label"],
        "token": base["token"],
        "cycle": True,
        "cycle_rate": indexed_wheel_cycle_rate(dmx_value),
        "count": len(entries),
    }


def preview_spin_state(value):
    dmx_value = clamp_dmx(value)
    if dmx_value <= 127:
        return {
            "degrees": (dmx_value / 127.0) * 360.0,
            "spin_dps": 0.0,
        }
    if dmx_value <= 191:
        normalized = (dmx_value - 128) / 63.0
        return {
            "degrees": 0.0,
            "spin_dps": 28.0 + normalized * 164.0,
        }
    normalized = (dmx_value - 192) / 63.0
    return {
        "degrees": 0.0,
        "spin_dps": -(184.0 - normalized * 160.0),
    }


def fixture_preview_kind(fixture, mode):
    fixture_id = str((fixture or {}).get("id") or "").strip()
    if fixture_id == BEE_EYE_PATTERN_FIXTURE_ID:
        return "bee_eye_pattern"
    control_ids = {
        str(control.get("id") or "").strip()
        for control in mode_custom_controls(mode or {})
    }
    if {"spot_dimmer", "color_disk", "pattern_plate", "z_rotation"}.issubset(control_ids):
        return "bee_eye_pattern"
    return "generic"


def indexed_wheel_value_for_token(channel, key, token, fallback=None):
    requested = preview_token(token, fallback="item")
    for entry in indexed_wheel_entries(channel, key):
        if entry["token"] == requested:
            return int(entry["value"])
    return fallback


def bee_eye_rotation_dmx(speed_unit, direction=1):
    speed = clamp_unit(speed_unit)
    if direction >= 0:
        return clamp_dmx(round(128 + speed * 63))
    return clamp_dmx(round(255 - speed * 63))


def wave_sine(position):
    return math.sin(position * math.tau)


def wave_cosine(position):
    return math.cos(position * math.tau)


def wave_triangle(position):
    fraction = position % 1.0
    return 1.0 - 4.0 * abs(fraction - 0.5)


def wave_square(position):
    return 1.0 if (position % 1.0) < 0.5 else -1.0


def clamp_motion(center, amplitude, wave):
    return clamp_dmx(round(center + amplitude * wave))


def phrase_motion(phrase, beat_value):
    key = normalize_phrase(phrase)
    beat_value = float(beat_value or 0.0)

    if key.startswith("intro"):
        cycle = beat_value / 8.0
        return {
            "pan": clamp_motion(116, 28, wave_sine(cycle)),
            "tilt": clamp_motion(176, 10, wave_triangle(cycle)),
            "pan_tilt_speed": 0,
        }
    if key.startswith("verse"):
        cycle = beat_value / 4.0
        return {
            "pan": clamp_motion(127, 52, wave_sine(cycle)),
            "tilt": clamp_motion(150, 18, wave_triangle(cycle + 0.25)),
            "pan_tilt_speed": 0,
        }
    if key.startswith("up") or key.startswith("build"):
        cycle = beat_value / 2.0
        return {
            "pan": clamp_motion(127, 34, wave_triangle(cycle)),
            "tilt": clamp_motion(118, 34, wave_sine(cycle + 0.25)),
            "pan_tilt_speed": 0,
        }
    if key.startswith("chorus"):
        cycle = beat_value / 2.0
        return {
            "pan": clamp_motion(127, 72, wave_sine(cycle)),
            "tilt": clamp_motion(134, 26, wave_sine(cycle * 2.0)),
            "pan_tilt_speed": 0,
        }
    if key.startswith("drop"):
        cycle = beat_value
        return {
            "pan": clamp_motion(127, 82, wave_square(cycle)),
            "tilt": clamp_motion(108, 22, wave_triangle(cycle / 2.0)),
            "pan_tilt_speed": 0,
        }
    if key.startswith("bridge"):
        cycle = beat_value / 4.0
        return {
            "pan": clamp_motion(127, 24, wave_sine(cycle)),
            "tilt": clamp_motion(160, 28, wave_sine(cycle + 0.25)),
            "pan_tilt_speed": 0,
        }
    if key.startswith("down") or key.startswith("break"):
        cycle = beat_value / 8.0
        return {
            "pan": clamp_motion(127, 18, wave_sine(cycle)),
            "tilt": clamp_motion(188, 10, wave_triangle(cycle)),
            "pan_tilt_speed": 0,
        }
    if key.startswith("outro"):
        cycle = beat_value / 8.0
        return {
            "pan": clamp_motion(110, 46, wave_triangle(cycle)),
            "tilt": clamp_motion(178, 12, wave_sine(cycle)),
            "pan_tilt_speed": 0,
        }
    return None


def parse_osc_string(data, index):
    end = data.find(b"\0", index)
    if end < 0:
        return None, index
    text = data[index:end].decode("utf-8", "replace")
    index = (end + 4) & ~3
    return text, index


def parse_osc_message(data):
    index = 0
    address, index = parse_osc_string(data, index)
    if not address or not address.startswith("/"):
        return None

    tags, index = parse_osc_string(data, index)
    if not tags or not tags.startswith(","):
        return {"address": address, "numeric": None, "text": None}

    numeric = None
    text = None
    for tag in tags[1:]:
        if tag == "f" and index + 4 <= len(data):
            value = struct.unpack(">f", data[index : index + 4])[0]
            index += 4
            if numeric is None:
                numeric = float(value)
                text = f"{value:.4f}"
        elif tag == "i" and index + 4 <= len(data):
            value = struct.unpack(">i", data[index : index + 4])[0]
            index += 4
            if numeric is None:
                numeric = float(value)
                text = str(value)
        elif tag == "s":
            value, index = parse_osc_string(data, index)
            if text is None:
                text = value
        else:
            break

    return {"address": address, "numeric": numeric, "text": text}


def normalize_phrase(text):
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def color_for_phrase(phrase):
    key = normalize_phrase(phrase)
    if key.startswith("intro"):
        return COLOR_PRESETS["intro"]
    if key.startswith("verse"):
        return COLOR_PRESETS["verse"]
    if key.startswith("up") or key.startswith("build"):
        return COLOR_PRESETS["build"]
    if key.startswith("chorus"):
        return COLOR_PRESETS["chorus"]
    if key.startswith("drop"):
        return COLOR_PRESETS["drop"]
    if key.startswith("down") or key.startswith("break"):
        return COLOR_PRESETS["break"]
    if key.startswith("outro"):
        return COLOR_PRESETS["outro"]
    return None


def color_for_mood(mood):
    if mood is None:
        return None
    value = int(round(mood))
    if value <= 1:
        return COLOR_PRESETS["high"]
    if value == 2:
        return COLOR_PRESETS["mid"]
    return COLOR_PRESETS["low"]


AUTO_SHOW_PHRASE_OVERRIDES = {
    "none": "Auto",
    "intro": "Intro",
    "verse": "Verse",
    "build": "Build",
    "chorus": "Chorus",
    "drop": "Drop",
    "down": "Down",
    "break": "Break",
    "outro": "Outro",
}

TRANSPORT_SOURCE_MODES = {
    "auto",
    "external_osc",
    "manual_tap",
}

DEVELOPER_PLAYBACK_SOURCES = {
    "current",
    "virtualdj",
}

ACTIVE_PLAYBACK_SOURCES = {
    "legacy",
    "virtualdj",
}

STRUCTURE_BEHAVIOR_SOURCES = {
    "legacy",
    "song_analyzer",
}

# This is deliberately an explicit contract, rather than another loose
# startswith check in the renderer. It mirrors every currently exported native
# SongAnalyzer/Rekordbox label and leaves unknown future labels fail-closed.
SONG_ANALYZER_BEHAVIOR_BUCKETS = {
    "Intro 1": "intro",
    "Intro 2": "intro",
    "Intro": "intro",
    "Up 1": "build",
    "Up 2": "build",
    "Up 3": "build",
    "Build": "build",
    "Down": "down",
    "Chorus 1": "chorus",
    "Chorus 2": "chorus",
    "Chorus": "chorus",
    "Outro 1": "outro",
    "Outro 2": "outro",
    "Outro": "outro",
    "Verse 1": "verse",
    "Verse 2": "verse",
    "Verse 3": "verse",
    "Verse 4": "verse",
    "Verse 5": "verse",
    "Verse 6": "verse",
    "Verse": "verse",
    "Bridge": "down",
    "Drop": "drop",
    "Break": "break",
}


def song_analyzer_behavior_bucket(label):
    """Return the existing behavior bucket for one known handoff label."""
    return SONG_ANALYZER_BEHAVIOR_BUCKETS.get(str(label or "").strip())


@dataclass(frozen=True)
class EffectiveBehaviorContext:
    selected_source: str
    effective_source: str
    eligible: bool
    fallback_reason: Optional[str]
    legacy_phrase: Optional[str]
    mapped_behavior_bucket: Optional[str]
    song_analyzer_label: Optional[str]
    projection: Optional[dict]

    def as_dict(self):
        return {
            "selected_source": self.selected_source,
            "effective_source": self.effective_source,
            "eligible": self.eligible,
            "fallback_reason": self.fallback_reason,
            "legacy_phrase": self.legacy_phrase,
            "mapped_behavior_bucket": self.mapped_behavior_bucket,
            "song_analyzer_label": self.song_analyzer_label,
            "projection": self.projection,
        }


class StructureBehaviorBridge:
    """Fail-closed adapter from a projected SongAnalyzer segment to behavior."""

    def __init__(self, handoff):
        self.handoff = handoff

    def resolve(self, selected_source, transport_state, include_shadow=False):
        selected_source = str(selected_source or "legacy").strip().lower()
        if selected_source not in STRUCTURE_BEHAVIOR_SOURCES:
            selected_source = "legacy"

        state = dict(transport_state or {})
        legacy_phrase = state.get("phrase_current")
        if selected_source == "legacy" and not include_shadow:
            return EffectiveBehaviorContext(
                selected_source, "legacy", False, "legacy_selected", legacy_phrase, None, None, None
            ).as_dict()

        if state.get("_active_playback_source") != "virtualdj":
            return EffectiveBehaviorContext(
                selected_source, "legacy", False, "legacy_selected" if selected_source == "legacy" else "virtualdj_inactive",
                legacy_phrase, None, None, None,
            ).as_dict()
        track_path = canonical_song_analyzer_track_path(state.get("track_path"))
        if not track_path:
            return EffectiveBehaviorContext(
                selected_source, "legacy", False, "legacy_selected" if selected_source == "legacy" else "track_unavailable",
                legacy_phrase, None, None, None,
            ).as_dict()

        projection = self.handoff.project(state)
        if projection.get("track_match") != "exact":
            load_status = projection.get("load_status")
            fallback_reason = {
                "unsupported_schema": "unsupported_schema",
                "invalid": "structure_invalid",
                "unreadable": "structure_unreadable",
                "missing": "structure_missing",
            }.get(load_status, "track_not_exact")
            return EffectiveBehaviorContext(
                selected_source, "legacy", False,
                "legacy_selected" if selected_source == "legacy" else fallback_reason,
                legacy_phrase, None, None, projection,
            ).as_dict()
        if projection.get("availability") != "available_current":
            return EffectiveBehaviorContext(
                selected_source, "legacy", False,
                "legacy_selected" if selected_source == "legacy" else "structure_not_current",
                legacy_phrase, None, None, projection,
            ).as_dict()
        if projection.get("projection_status") not in {"in_segment", "in_final_segment"}:
            projection_status = projection.get("projection_status")
            fallback_reason = "no_playback_position" if projection_status == "position_unavailable" else "no_current_segment"
            return EffectiveBehaviorContext(
                selected_source, "legacy", False,
                "legacy_selected" if selected_source == "legacy" else fallback_reason,
                legacy_phrase, None, None, projection,
            ).as_dict()
        if projection.get("canonical_track_path") != track_path:
            return EffectiveBehaviorContext(
                selected_source, "legacy", False,
                "legacy_selected" if selected_source == "legacy" else "track_path_mismatch",
                legacy_phrase, None, None, projection,
            ).as_dict()
        current = projection.get("current") or {}
        label = current.get("label")
        bucket = song_analyzer_behavior_bucket(label)
        if bucket is None:
            return EffectiveBehaviorContext(
                selected_source, "legacy", False,
                "legacy_selected" if selected_source == "legacy" else "unknown_song_analyzer_label",
                legacy_phrase, None, label, projection,
            ).as_dict()

        return EffectiveBehaviorContext(
            selected_source,
            "legacy" if selected_source == "legacy" else "song_analyzer",
            True,
            "legacy_selected" if selected_source == "legacy" else None,
            legacy_phrase,
            bucket,
            label,
            projection,
        ).as_dict()


@dataclass(frozen=True)
class PlaybackQueryTiming:
    field: str
    request_started_at_monotonic_milliseconds: int
    response_received_at_monotonic_milliseconds: int

    @property
    def round_trip_milliseconds(self):
        return max(0, self.response_received_at_monotonic_milliseconds - self.request_started_at_monotonic_milliseconds)


@dataclass(frozen=True)
class PlaybackPositionReference:
    position_milliseconds: int
    sampled_at_monotonic_milliseconds: int
    query_timing: PlaybackQueryTiming


@dataclass(frozen=True)
class PlaybackTimingSnapshot:
    clock: str
    snapshot_started_at_monotonic_milliseconds: int
    snapshot_completed_at_monotonic_milliseconds: int
    sampled_at_monotonic_milliseconds: int
    published_at_monotonic_milliseconds: int
    query_timings: tuple
    position_reference: object = None


@dataclass(frozen=True)
class PlaybackStateSnapshot:
    schema_version: int
    sequence: int
    captured_at_unix_milliseconds: int
    is_connected: bool
    status: str
    selection: str
    deck_number: object
    track_path: object
    bpm: object
    position_milliseconds: object
    first_beat_milliseconds: object
    beat_position: object
    beat_number: object
    bar_number: object
    metrics: dict
    error_kind: object
    timing: object = None
    decks: object = None

    def fingerprint(self):
        return (
            self.sequence,
            self.captured_at_unix_milliseconds,
            self.is_connected,
            self.status,
            self.deck_number,
            self.track_path,
            self.position_milliseconds,
            self.bpm,
            self.beat_position,
            self.beat_number,
            self.bar_number,
        )


@dataclass(frozen=True)
class PlaybackSourceRead:
    snapshot: object
    status: str
    error: object = None


class PlaybackStateSource:
    """Source-neutral state reader used only by developer playback diagnostics."""

    def read(self):
        raise NotImplementedError


class BridgePlaybackStateSource(PlaybackStateSource):
    """Bounded read-only consumer of the bridge's ephemeral native transport."""

    def __init__(self, socket_path=DEFAULT_SONG_ANALYZER_BRIDGE_SOCKET_PATH, refresh_seconds=0.10):
        self.socket_path = str(socket_path)
        self.refresh_seconds = max(0.05, float(refresh_seconds))
        self._lock = threading.Lock()
        self._next_refresh = 0.0
        self._cached = PlaybackSourceRead(None, "unavailable")
        self._request_sequence = 0

    def read(self):
        with self._lock:
            now = time.monotonic()
            if now < self._next_refresh:
                return self._cached
            self._next_refresh = now + self.refresh_seconds
            self._request_sequence += 1
            try:
                request = json.dumps({
                    "protocolVersion": 1,
                    "requestId": f"beatbeam-transport-{self._request_sequence}",
                    "type": "transportSnapshot",
                }) + "\n"
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(0.05)
                    client.connect(self.socket_path)
                    client.sendall(request.encode("utf-8"))
                    response = json.loads(client.recv(65536).decode("utf-8"))
                transport = response.get("transport") if response.get("success") else None
                self._cached = PlaybackSourceRead(
                    self._parse_transport(transport) if isinstance(transport, dict) else None,
                    "available" if isinstance(transport, dict) else "unavailable",
                )
            except Exception as exc:
                self._cached = PlaybackSourceRead(None, "unavailable", type(exc).__name__)
            return self._cached

    @staticmethod
    def _parse_transport(raw):
        sequence = JsonPlaybackStateSource._positive_int(raw.get("sequence"), "transport sequence")
        deck = JsonPlaybackStateSource._positive_int(raw.get("deck"), "transport deck")
        path = JsonPlaybackStateSource._optional_text(raw.get("filePath"), "transport filePath")
        playing = raw.get("playing")
        observed = JsonPlaybackStateSource._non_negative_int(raw.get("observedAtUnixMilliseconds"), "transport observedAtUnixMilliseconds")
        if not path or not isinstance(playing, bool):
            raise ValueError("Transport mist identity.")
        position = JsonPlaybackStateSource._optional_non_negative_int(raw.get("positionMilliseconds"), "transport positionMilliseconds")
        bpm = JsonPlaybackStateSource._optional_positive_float(raw.get("bpm"), "transport bpm")
        beat_position = JsonPlaybackStateSource._optional_non_negative_float(raw.get("beatPosition"), "transport beatPosition")
        beat_number = JsonPlaybackStateSource._optional_range_int(raw.get("beatNumber"), "transport beatNumber", 1, 4)
        bar_number = JsonPlaybackStateSource._optional_positive_int(raw.get("barNumber"), "transport barNumber")
        available = playing and position is not None and bpm is not None
        deck_state = {
            "deck_number": deck, "is_loaded": True, "track_path": path,
            "file_name": Path(path).name or None, "artist": None, "title": Path(path).stem or None,
            "bpm": bpm, "position_milliseconds": position, "beat_position": beat_position,
            "beat_number": beat_number, "bar_number": bar_number,
            "captured_at_unix_milliseconds": observed, "is_playing": playing,
        }
        return PlaybackStateSnapshot(
            PLAYBACK_STATE_SCHEMA_VERSION, sequence, observed, True,
            "available" if available else "unavailable", "active_deck", deck, path if available else None,
            bpm if available else None, position if available else None, None,
            beat_position if available else None, beat_number if available else None, bar_number if available else None,
            {"snapshot_latency_milliseconds": 0.0, "error_count": 0}, None, None, (deck_state,),
        )


class JsonPlaybackStateSource(PlaybackStateSource):
    def __init__(self, path):
        self.path = Path(path).expanduser()

    def read(self):
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return PlaybackSourceRead(None, "unavailable")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return PlaybackSourceRead(None, "invalid", type(exc).__name__)
        try:
            return PlaybackSourceRead(self._parse(payload), "available")
        except ValueError as exc:
            return PlaybackSourceRead(None, "invalid", str(exc))

    @staticmethod
    def _parse(payload):
        if not isinstance(payload, dict):
            raise ValueError("Playback snapshot must be an object.")
        if payload.get("schema_version") != PLAYBACK_STATE_SCHEMA_VERSION:
            raise ValueError("Unsupported playback snapshot schema.")
        sequence = JsonPlaybackStateSource._positive_int(payload.get("sequence"), "sequence")
        captured_at = JsonPlaybackStateSource._non_negative_int(
            payload.get("captured_at_unix_milliseconds"), "captured_at_unix_milliseconds"
        )
        is_connected = payload.get("is_connected")
        if not isinstance(is_connected, bool):
            raise ValueError("is_connected must be boolean.")
        status = str(payload.get("status") or "").strip().lower()
        if status not in {"available", "unavailable", "disconnected"}:
            raise ValueError("Invalid playback snapshot status.")
        selection = str(payload.get("selection") or "").strip().lower()
        if selection not in {"active_deck", "configured_deck", "none"}:
            raise ValueError("Invalid playback deck selection.")
        deck_number = JsonPlaybackStateSource._optional_positive_int(payload.get("deck_number"), "deck_number")
        track_path = JsonPlaybackStateSource._optional_text(payload.get("track_path"), "track_path")
        bpm = JsonPlaybackStateSource._optional_positive_float(payload.get("bpm"), "bpm")
        position = JsonPlaybackStateSource._optional_non_negative_int(
            payload.get("position_milliseconds"), "position_milliseconds"
        )
        first_beat = JsonPlaybackStateSource._optional_non_negative_float(
            payload.get("first_beat_milliseconds"), "first_beat_milliseconds"
        )
        beat_position = JsonPlaybackStateSource._optional_non_negative_float(
            payload.get("beat_position"), "beat_position"
        )
        beat_number = JsonPlaybackStateSource._optional_range_int(payload.get("beat_number"), "beat_number", 1, 4)
        bar_number = JsonPlaybackStateSource._optional_positive_int(payload.get("bar_number"), "bar_number")
        metrics = payload.get("metrics")
        if not isinstance(metrics, dict):
            raise ValueError("Playback snapshot metrics must be an object.")
        if status == "available" and (
            not is_connected
            or deck_number is None
            or track_path is None
            or bpm is None
            or position is None
        ):
            raise ValueError("Available playback snapshot misses required timing values.")
        timing = JsonPlaybackStateSource._optional_timing(payload.get("timing"))
        decks = JsonPlaybackStateSource._optional_decks(payload.get("decks"))
        return PlaybackStateSnapshot(
            PLAYBACK_STATE_SCHEMA_VERSION,
            sequence,
            captured_at,
            is_connected,
            status,
            selection,
            deck_number,
            track_path,
            bpm,
            position,
            first_beat,
            beat_position,
            beat_number,
            bar_number,
            dict(metrics),
            JsonPlaybackStateSource._optional_text(payload.get("error_kind"), "error_kind"),
            timing,
            decks,
        )

    @staticmethod
    def _positive_int(value, name):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer.")
        return value

    @staticmethod
    def _non_negative_int(value, name):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer.")
        return value

    @staticmethod
    def _optional_positive_int(value, name):
        if value is None:
            return None
        return JsonPlaybackStateSource._positive_int(value, name)

    @staticmethod
    def _optional_non_negative_int(value, name):
        if value is None:
            return None
        return JsonPlaybackStateSource._non_negative_int(value, name)

    @staticmethod
    def _optional_range_int(value, name, minimum, maximum):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"{name} is outside its valid range.")
        return value

    @staticmethod
    def _optional_positive_float(value, name):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be a positive finite number.")
        return float(value)

    @staticmethod
    def _optional_non_negative_float(value, name):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a non-negative finite number.")
        return float(value)

    @staticmethod
    def _optional_finite_float(value, name):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number.")
        return float(value)

    @staticmethod
    def _optional_int(value, name):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer.")
        return value

    @staticmethod
    def _optional_text(value, name):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{name} must be text.")
        value = value.strip()
        return value or None

    @staticmethod
    def _optional_decks(value):
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("decks must be a list.")
        result = []
        for raw in value:
            if not isinstance(raw, dict):
                raise ValueError("deck overview items must be objects.")
            deck_number = JsonPlaybackStateSource._positive_int(raw.get("deck_number"), "deck_number")
            is_loaded = raw.get("is_loaded")
            if not isinstance(is_loaded, bool):
                raise ValueError("deck is_loaded must be boolean.")
            result.append({
                "deck_number": deck_number,
                "is_loaded": is_loaded,
                "track_path": JsonPlaybackStateSource._optional_text(raw.get("track_path"), "deck.track_path"),
                "file_name": JsonPlaybackStateSource._optional_text(raw.get("file_name"), "deck.file_name"),
                "artist": JsonPlaybackStateSource._optional_text(raw.get("artist"), "deck.artist"),
                "title": JsonPlaybackStateSource._optional_text(raw.get("title"), "deck.title"),
                "bpm": JsonPlaybackStateSource._optional_positive_float(raw.get("bpm"), "deck.bpm"),
                "position_milliseconds": JsonPlaybackStateSource._optional_non_negative_int(raw.get("position_milliseconds"), "deck.position_milliseconds"),
                "beat_position": JsonPlaybackStateSource._optional_finite_float(raw.get("beat_position"), "deck.beat_position"),
                "beat_number": JsonPlaybackStateSource._optional_range_int(raw.get("beat_number"), "deck.beat_number", 1, 4),
                "bar_number": JsonPlaybackStateSource._optional_int(raw.get("bar_number"), "deck.bar_number"),
                "captured_at_unix_milliseconds": JsonPlaybackStateSource._non_negative_int(raw.get("captured_at_unix_milliseconds"), "deck.captured_at_unix_milliseconds"),
                "is_playing": raw.get("is_playing") if isinstance(raw.get("is_playing"), bool) else None,
            })
        return tuple(result)

    @staticmethod
    def _optional_timing(value):
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("timing must be an object.")
        clock = JsonPlaybackStateSource._optional_text(value.get("clock"), "timing.clock")
        if clock != "system_monotonic_milliseconds":
            raise ValueError("Unsupported playback timing clock.")
        started = JsonPlaybackStateSource._non_negative_int(
            value.get("snapshot_started_at_monotonic_milliseconds"), "timing.snapshot_started_at_monotonic_milliseconds"
        )
        completed = JsonPlaybackStateSource._non_negative_int(
            value.get("snapshot_completed_at_monotonic_milliseconds"), "timing.snapshot_completed_at_monotonic_milliseconds"
        )
        sampled = JsonPlaybackStateSource._non_negative_int(
            value.get("sampled_at_monotonic_milliseconds"), "timing.sampled_at_monotonic_milliseconds"
        )
        published = JsonPlaybackStateSource._non_negative_int(
            value.get("published_at_monotonic_milliseconds"), "timing.published_at_monotonic_milliseconds"
        )
        if completed < started or sampled < started or sampled > completed or published < completed:
            raise ValueError("Playback timing values are not chronological.")
        query_timings = value.get("query_timings")
        if not isinstance(query_timings, list):
            raise ValueError("timing.query_timings must be a list.")
        parsed_queries = tuple(JsonPlaybackStateSource._parse_query_timing(item) for item in query_timings)
        if any(query.request_started_at_monotonic_milliseconds < started
               or query.response_received_at_monotonic_milliseconds > completed
               for query in parsed_queries):
            raise ValueError("Playback query timing falls outside its snapshot.")
        position_queries = [query for query in parsed_queries if query.field == "PositionMilliseconds"]
        if len(position_queries) != 1:
            raise ValueError("Playback timing requires exactly one position query.")
        position_query = position_queries[0]
        if not position_query.request_started_at_monotonic_milliseconds <= sampled <= position_query.response_received_at_monotonic_milliseconds:
            raise ValueError("Playback position sample falls outside its position query.")
        reference = value.get("position_reference")
        parsed_reference = None if reference is None else JsonPlaybackStateSource._parse_position_reference(reference)
        if parsed_reference is not None:
            reference_query = parsed_reference.query_timing
            if reference_query.request_started_at_monotonic_milliseconds < completed:
                raise ValueError("Playback position reference must follow its transport snapshot.")
            if not reference_query.request_started_at_monotonic_milliseconds <= parsed_reference.sampled_at_monotonic_milliseconds <= reference_query.response_received_at_monotonic_milliseconds:
                raise ValueError("Playback position reference sample falls outside its query.")
        return PlaybackTimingSnapshot(clock, started, completed, sampled, published, parsed_queries, parsed_reference)

    @staticmethod
    def _parse_query_timing(value):
        if not isinstance(value, dict):
            raise ValueError("timing.query_timings items must be objects.")
        field = JsonPlaybackStateSource._optional_text(value.get("field"), "timing query field")
        if field is None:
            raise ValueError("timing query field is required.")
        started = JsonPlaybackStateSource._non_negative_int(
            value.get("request_started_at_monotonic_milliseconds"), "timing query request start"
        )
        completed = JsonPlaybackStateSource._non_negative_int(
            value.get("response_received_at_monotonic_milliseconds"), "timing query response finish"
        )
        if completed < started:
            raise ValueError("timing query values are not chronological.")
        return PlaybackQueryTiming(field, started, completed)

    @staticmethod
    def _parse_position_reference(value):
        if not isinstance(value, dict):
            raise ValueError("timing.position_reference must be an object.")
        position = JsonPlaybackStateSource._non_negative_int(
            value.get("position_milliseconds"), "timing.position_reference.position_milliseconds"
        )
        sampled = JsonPlaybackStateSource._non_negative_int(
            value.get("sampled_at_monotonic_milliseconds"), "timing.position_reference.sampled_at_monotonic_milliseconds"
        )
        query = JsonPlaybackStateSource._parse_query_timing(value.get("query_timing"))
        if not query.field == "PositionMilliseconds":
            raise ValueError("timing.position_reference must be a position query.")
        return PlaybackPositionReference(position, sampled, query)


class PlaybackClock:
    """Latency-aware developer clock, anchored only by authoritative read-only samples."""

    def __init__(self, source, grace_seconds=PLAYBACK_CLOCK_GRACE_SECONDS):
        self.source = source
        self.grace_seconds = float(grace_seconds)
        self.anchor = None
        self.anchor_at = None
        self.anchor_sample_age_milliseconds = 0.0
        self.previous = None
        self.previous_at = None
        self.last_fingerprint = None
        self.availability = "unavailable"
        self.transport_state = "unknown"
        self.last_discontinuity = None
        self.discontinuity_count = 0
        self.reconnect_count = 0
        self.accepted_snapshot_count = 0
        self.invalid_snapshot_count = 0
        self.snapshot_intervals_ms = deque(maxlen=120)
        self.position_query_rtt_ms = deque(maxlen=120)
        self.snapshot_assembly_ms = deque(maxlen=120)
        self.sample_age_at_receive_ms = deque(maxlen=120)
        self.raw_position_delta_ms = deque(maxlen=120)
        self.compensated_position_delta_ms = deque(maxlen=120)
        self.last_source_error = None
        self.overview_decks = None
        self.was_disconnected = False
        self.last_timing_alignment = "legacy_or_unavailable"
        self.last_received_at_monotonic_milliseconds = None
        self.last_raw_position_delta_milliseconds = None
        self.last_compensated_position_delta_milliseconds = None

    def state(self, now=None):
        now = playback_system_monotonic_time() if now is None else float(now)
        source_read = self.source.read()
        if source_read.snapshot is not None:
            self.overview_decks = (
                list(source_read.snapshot.decks)
                if source_read.snapshot.status != "disconnected" and source_read.snapshot.decks is not None
                else None
            )
            fingerprint = source_read.snapshot.fingerprint()
            if fingerprint != self.last_fingerprint:
                self._accept(source_read.snapshot, now)
                self.last_fingerprint = fingerprint
        else:
            # A missing or malformed atomic state file must not leave the last
            # deck cards visible after the producer has disappeared.
            self.overview_decks = None
        if source_read.snapshot is None and source_read.status == "invalid":
            self.invalid_snapshot_count += 1
            self.last_source_error = source_read.error
        return self._estimated_state(now, source_read)

    def reset(self):
        """Discard an old transport anchor before a source is made active again."""
        self.anchor = None
        self.anchor_at = None
        self.anchor_sample_age_milliseconds = 0.0
        self.previous = None
        self.previous_at = None
        self.last_fingerprint = None
        self.availability = "unavailable"
        self.transport_state = "unknown"
        self.last_discontinuity = None
        self.was_disconnected = False
        self.last_source_error = None
        self.overview_decks = None

    def _accept(self, snapshot, now):
        if snapshot.status != "available" or not snapshot.is_connected:
            self.anchor = None
            self.anchor_at = None
            self.previous = None
            self.previous_at = None
            self.anchor_sample_age_milliseconds = 0.0
            self.last_raw_position_delta_milliseconds = None
            self.last_compensated_position_delta_milliseconds = None
            self.availability = "disconnected" if snapshot.status == "disconnected" else "unavailable"
            self.transport_state = "unknown"
            self.was_disconnected = True
            self.last_discontinuity = "disconnected" if self.availability == "disconnected" else "source_unavailable"
            self.last_source_error = snapshot.error_kind
            return

        source_elapsed = self._source_elapsed_since_previous(snapshot, now)
        if self.previous_at is not None:
            self.snapshot_intervals_ms.append(source_elapsed)
        discontinuity = self._discontinuity_reason(snapshot, source_elapsed)
        if discontinuity is not None:
            self.last_discontinuity = discontinuity
            self.discontinuity_count += 1
            self.transport_state = "unknown"
        elif self.previous is not None:
            observed_ms = snapshot.position_milliseconds - self.previous.position_milliseconds
            stationary_tolerance = max(PLAYBACK_STATIONARY_TOLERANCE_MS, source_elapsed * 0.15)
            self.transport_state = "stationary" if abs(observed_ms) <= stationary_tolerance else "advancing"
            self.last_discontinuity = None
        elif self.was_disconnected:
            self.last_discontinuity = "reconnected"
            self.reconnect_count += 1
            self.transport_state = "unknown"
        else:
            self.transport_state = "unknown"

        self.last_raw_position_delta_milliseconds = None
        self.last_compensated_position_delta_milliseconds = None
        self.anchor_sample_age_milliseconds = self._sample_age_at_receive(snapshot, now)
        self._record_timing(snapshot)
        self.anchor = snapshot
        self.anchor_at = now
        self.previous = snapshot
        self.previous_at = now
        self.availability = "available"
        self.accepted_snapshot_count += 1
        self.last_source_error = None
        self.was_disconnected = False
        self.last_received_at_monotonic_milliseconds = int(round(now * 1000.0))

    def _source_elapsed_since_previous(self, snapshot, now):
        if self.previous is None or self.previous_at is None:
            return 0.0
        current_sample_at = self._sampled_at(snapshot)
        previous_sample_at = self._sampled_at(self.previous)
        if current_sample_at is not None and previous_sample_at is not None:
            return max(0.0, current_sample_at - previous_sample_at)
        return max(0.0, (now - self.previous_at) * 1000.0)

    def _discontinuity_reason(self, snapshot, elapsed_ms):
        if self.previous is None:
            return None
        if snapshot.deck_number != self.previous.deck_number:
            return "deck_changed"
        if snapshot.track_path != self.previous.track_path:
            return "track_changed"
        observed_ms = snapshot.position_milliseconds - self.previous.position_milliseconds
        tolerance = max(PLAYBACK_DISCONTINUITY_MINIMUM_MS, elapsed_ms * 2.0)
        if observed_ms < -PLAYBACK_STATIONARY_TOLERANCE_MS:
            return "position_jump_backward"
        if abs(observed_ms - elapsed_ms) > tolerance:
            return "position_jump_forward"
        return None

    def _sample_age_at_receive(self, snapshot, now):
        sampled_at = self._sampled_at(snapshot)
        if sampled_at is None:
            self.last_timing_alignment = "legacy_or_unavailable"
            return 0.0
        received_at = int(round(now * 1000.0))
        age = received_at - sampled_at
        if age < 0 or age > 5_000:
            self.last_timing_alignment = "untrusted_clock_epoch"
            return 0.0
        self.last_timing_alignment = "system_monotonic"
        self.sample_age_at_receive_ms.append(float(age))
        return float(age)

    @staticmethod
    def _sampled_at(snapshot):
        timing = snapshot.timing if snapshot is not None else None
        return timing.sampled_at_monotonic_milliseconds if timing is not None else None

    def _record_timing(self, snapshot):
        timing = snapshot.timing
        if timing is None:
            return
        self.snapshot_assembly_ms.append(float(
            timing.snapshot_completed_at_monotonic_milliseconds - timing.snapshot_started_at_monotonic_milliseconds
        ))
        position_query = next((item for item in timing.query_timings if item.field == "PositionMilliseconds"), None)
        if position_query is not None:
            self.position_query_rtt_ms.append(float(position_query.round_trip_milliseconds))
        reference = timing.position_reference
        if reference is None or self.transport_state != "advancing":
            return
        raw_delta = reference.position_milliseconds - snapshot.position_milliseconds
        elapsed_from_sample = max(0, reference.sampled_at_monotonic_milliseconds - timing.sampled_at_monotonic_milliseconds)
        compensated_position = snapshot.position_milliseconds + elapsed_from_sample
        compensated_delta = reference.position_milliseconds - compensated_position
        self.last_raw_position_delta_milliseconds = raw_delta
        self.last_compensated_position_delta_milliseconds = compensated_delta
        self.raw_position_delta_ms.append(float(abs(raw_delta)))
        self.compensated_position_delta_ms.append(float(abs(compensated_delta)))

    def _estimated_state(self, now, source_read):
        if self.anchor is None:
            return self._unavailable_state(source_read.status)
        age = max(0.0, now - self.anchor_at)
        if age > self.grace_seconds:
            return self._unavailable_state("unavailable")

        elapsed_milliseconds = 0.0
        if self.transport_state == "advancing":
            elapsed_milliseconds = self.anchor_sample_age_milliseconds + age * 1000.0
        estimated_position = self.anchor.position_milliseconds + int(round(elapsed_milliseconds))
        estimated_beat_position = self.anchor.beat_position
        estimated_beat_number = self.anchor.beat_number
        estimated_bar_number = self.anchor.bar_number
        beat_phase = self._beat_phase(self.anchor.beat_position)
        extrapolated_beats = 0.0
        if self.transport_state == "advancing" and self.anchor.bpm is not None:
            extrapolated_beats = elapsed_milliseconds * self.anchor.bpm / 60_000.0
            if estimated_beat_position is not None:
                estimated_beat_position += extrapolated_beats
            estimated_beat_number, estimated_bar_number, beat_phase = self._advance_beat_and_bar(
                estimated_beat_number,
                estimated_bar_number,
                beat_phase,
                extrapolated_beats,
            )
        virtualdj = self._snapshot_fields(self.anchor)
        beatbeam = {
            "track_path": self.anchor.track_path,
            "estimated_position_milliseconds": estimated_position,
            "bpm": self.anchor.bpm,
            "beat_position": estimated_beat_position,
            "beat_number": estimated_beat_number,
            "bar_number": estimated_bar_number,
            "beat_phase": beat_phase,
            "time_until_next_beat_milliseconds": self._time_until_next_beat(beat_phase, self.anchor.bpm),
            "time_until_next_bar_milliseconds": self._time_until_next_bar(estimated_beat_number, beat_phase, self.anchor.bpm),
            "first_beat_milliseconds": self.anchor.first_beat_milliseconds,
            "deck_number": self.anchor.deck_number,
        }
        return {
            "source": "virtualdj",
            "availability": "available",
            "transport_state": self.transport_state,
            "virtualdj": virtualdj,
            "beatbeam": beatbeam,
            "delta": {
                "position_milliseconds": estimated_position - self.anchor.position_milliseconds,
                "raw_received_position_milliseconds": self.last_raw_position_delta_milliseconds,
                "compensated_position_milliseconds": self.last_compensated_position_delta_milliseconds,
                "beat_agreement": estimated_beat_number == self.anchor.beat_number,
                "bar_agreement": estimated_bar_number == self.anchor.bar_number,
            },
            "timing": self._timing_state(now),
            "metrics": self._metrics(elapsed_milliseconds),
            "last_discontinuity": self.last_discontinuity,
            "selection": self.anchor.selection,
            "decks": list(self.anchor.decks or ()),
        }

    def _unavailable_state(self, status):
        effective_status = self.availability if self.availability in {"disconnected", "unavailable"} else status
        return {
            "source": "virtualdj",
            "availability": effective_status,
            "transport_state": "unknown",
            "virtualdj": None,
            "beatbeam": None,
            "delta": {
                "position_milliseconds": None,
                "raw_received_position_milliseconds": None,
                "compensated_position_milliseconds": None,
                "beat_agreement": None,
                "bar_agreement": None,
            },
            "timing": self._timing_state(None),
            "metrics": self._metrics(None),
            "last_discontinuity": self.last_discontinuity,
            "selection": None,
            "error": self.last_source_error,
            "decks": list(self.overview_decks or ()),
        }

    @staticmethod
    def _beat_phase(beat_position):
        if beat_position is None or not math.isfinite(beat_position):
            return 0.0
        return beat_position - math.floor(beat_position)

    @staticmethod
    def _advance_beat_and_bar(beat_number, bar_number, beat_phase, elapsed_beats):
        if beat_number is None:
            return None, bar_number, beat_phase
        total_beats = max(0.0, beat_phase + elapsed_beats)
        completed = int(math.floor(total_beats + 1e-9))
        offset = (beat_number - 1) + completed
        advanced_bar = None if bar_number is None else bar_number + (offset // 4)
        return (offset % 4) + 1, advanced_bar, total_beats - math.floor(total_beats)

    @staticmethod
    def _time_until_next_beat(beat_phase, bpm):
        if bpm is None or bpm <= 0:
            return None
        return (1.0 - beat_phase) * 60_000.0 / bpm

    @staticmethod
    def _time_until_next_bar(beat_number, beat_phase, bpm):
        if bpm is None or bpm <= 0 or beat_number is None:
            return None
        beats_remaining = (5 - beat_number) - beat_phase
        return max(0.0, beats_remaining) * 60_000.0 / bpm

    @staticmethod
    def _snapshot_fields(snapshot):
        return {
            "track_path": snapshot.track_path,
            "position_milliseconds": snapshot.position_milliseconds,
            "bpm": snapshot.bpm,
            "beat_position": snapshot.beat_position,
            "beat_number": snapshot.beat_number,
            "bar_number": snapshot.bar_number,
            "first_beat_milliseconds": snapshot.first_beat_milliseconds,
            "deck_number": snapshot.deck_number,
            "captured_at_unix_milliseconds": snapshot.captured_at_unix_milliseconds,
            "metrics": dict(snapshot.metrics),
        }

    def _timing_state(self, now):
        timing = self.anchor.timing if self.anchor is not None else None
        return {
            "source_clock": timing.clock if timing is not None else None,
            "sample_age_at_receive_milliseconds": self.anchor_sample_age_milliseconds if self.anchor is not None else None,
            "received_at_monotonic_milliseconds": self.last_received_at_monotonic_milliseconds,
            "consumed_at_monotonic_milliseconds": None if now is None else int(round(now * 1000.0)),
            "alignment": self.last_timing_alignment,
            "query_timings": [] if timing is None else [
                {
                    "field": query.field,
                    "round_trip_milliseconds": query.round_trip_milliseconds,
                    "request_started_at_monotonic_milliseconds": query.request_started_at_monotonic_milliseconds,
                    "response_received_at_monotonic_milliseconds": query.response_received_at_monotonic_milliseconds,
                }
                for query in timing.query_timings
            ],
        }

    @staticmethod
    def _summary(values):
        if not values:
            return {"count": 0, "mean": None, "p50": None, "p95": None, "max": None}
        ordered = sorted(values)
        percentile = lambda fraction: ordered[min(len(ordered) - 1, int(math.ceil(len(ordered) * fraction)) - 1)]
        return {
            "count": len(ordered),
            "mean": sum(ordered) / len(ordered),
            "p50": percentile(.50),
            "p95": percentile(.95),
            "max": ordered[-1],
        }

    def _metrics(self, extrapolation_ms):
        interval_average = (
            sum(self.snapshot_intervals_ms) / len(self.snapshot_intervals_ms)
            if self.snapshot_intervals_ms
            else None
        )
        return {
            "snapshot_interval_milliseconds": interval_average,
            "extrapolation_milliseconds": extrapolation_ms,
            "accepted_snapshots": self.accepted_snapshot_count,
            "invalid_snapshots": self.invalid_snapshot_count,
            "discontinuities": self.discontinuity_count,
            "reconnects": self.reconnect_count,
            "position_query_rtt_milliseconds": self._summary(self.position_query_rtt_ms),
            "snapshot_assembly_milliseconds": self._summary(self.snapshot_assembly_ms),
            "sample_age_at_receive_milliseconds": self._summary(self.sample_age_at_receive_ms),
            "raw_position_delta_milliseconds": self._summary(self.raw_position_delta_ms),
            "compensated_position_delta_milliseconds": self._summary(self.compensated_position_delta_ms),
        }


@dataclass(frozen=True)
class VirtualDjBeatPulsePlan:
    identity: tuple
    deadline_monotonic_seconds: float
    track_path: str
    deck_number: int
    bar_number: int
    duration_milliseconds: int


class VirtualDjBeatPulsePlanner:
    """Creates only future beat-1 plans from the accepted M19C clock."""

    @staticmethod
    def plan(playback_state, now, duration_milliseconds):
        playback_state = playback_state or {}
        beatbeam = playback_state.get("beatbeam") or {}
        timing = playback_state.get("timing") or {}
        if playback_state.get("source") != "virtualdj":
            return None, "source_not_virtualdj"
        if playback_state.get("availability") != "available":
            return None, "source_unavailable"
        if playback_state.get("transport_state") != "advancing":
            return None, "transport_not_advancing"
        if timing.get("alignment") != "system_monotonic":
            return None, "untrusted_clock"
        if playback_state.get("last_discontinuity") is not None:
            return None, "awaiting_fresh_anchor"

        track_path = str(beatbeam.get("track_path") or "").strip()
        deck_number = beatbeam.get("deck_number")
        bar_number = beatbeam.get("bar_number")
        beat_number = beatbeam.get("beat_number")
        milliseconds_until_bar = beatbeam.get("time_until_next_bar_milliseconds")
        if not track_path or not isinstance(deck_number, int) or deck_number < 1:
            return None, "missing_track_identity"
        if not isinstance(bar_number, int) or bar_number < 1:
            return None, "missing_bar"
        if not isinstance(beat_number, int) or not 1 <= beat_number <= 4:
            return None, "missing_beat"
        if not isinstance(milliseconds_until_bar, (int, float)) or not math.isfinite(milliseconds_until_bar):
            return None, "missing_beat_deadline"
        if milliseconds_until_bar <= 0:
            return None, "invalid_beat_deadline"

        next_bar = bar_number + 1
        return (
            VirtualDjBeatPulsePlan(
                identity=(deck_number, track_path, next_bar, 1),
                deadline_monotonic_seconds=float(now) + (float(milliseconds_until_bar) / 1000.0),
                track_path=track_path,
                deck_number=deck_number,
                bar_number=next_bar,
                duration_milliseconds=int(duration_milliseconds),
            ),
            None,
        )


class VirtualDjBeatPulseScheduler:
    """Developer-only monotonic deadline scheduler for one deduplicated beat-1 pulse."""

    def __init__(self, dispatch, cancel, clock=playback_system_monotonic_time):
        self._dispatch = dispatch
        self._cancel = cancel
        self._clock = clock
        self._condition = threading.Condition()
        self._enabled = False
        self._slot_id = None
        self._duration_milliseconds = DEFAULT_VIRTUALDJ_BEAT_PULSE_DURATION_MILLISECONDS
        self._plan = None
        self._generation = 0
        self._thread = None
        self._last_dispatched_identity = None
        self._last_planned_identity = None
        self._last_reason = "disabled"
        self._scheduled_events = 0
        self._executed_events = 0
        self._duplicate_events = 0
        self._cancelled_stale_events = 0
        self._failed_dispatches = 0
        self._dispatch_errors_milliseconds = deque(maxlen=240)
        self._last_event = None

    def start(self, slot_id, duration_milliseconds):
        with self._condition:
            self._enabled = True
            self._slot_id = str(slot_id)
            self._duration_milliseconds = int(duration_milliseconds)
            self._plan = None
            self._generation += 1
            self._last_dispatched_identity = None
            self._last_planned_identity = None
            self._last_reason = "awaiting_transport"
            self._scheduled_events = 0
            self._executed_events = 0
            self._duplicate_events = 0
            self._cancelled_stale_events = 0
            self._failed_dispatches = 0
            self._dispatch_errors_milliseconds.clear()
            self._last_event = None
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run,
                    name="virtualdj-beat-pulse",
                    daemon=True,
                )
                self._thread.start()
            self._condition.notify_all()
        self._cancel("restarted")
        return self.state()

    def stop(self, reason="stopped"):
        with self._condition:
            if self._plan is not None:
                self._cancelled_stale_events += 1
            self._enabled = False
            self._plan = None
            self._generation += 1
            self._last_reason = str(reason)
            self._condition.notify_all()
        self._cancel(str(reason))
        return self.state()

    def observe(self, playback_state):
        cancel_reason = None
        with self._condition:
            if not self._enabled:
                return
            now = float(self._clock())
            plan, reason = VirtualDjBeatPulsePlanner.plan(
                playback_state,
                now,
                self._duration_milliseconds,
            )
            if self._should_dispatch_due_plan_before_replanning(plan, now):
                self._last_reason = "dispatching_due_plan"
                self._condition.notify_all()
                return
            if plan is None:
                if self._plan is not None:
                    self._plan = None
                    self._generation += 1
                    self._cancelled_stale_events += 1
                    cancel_reason = str(reason)
                self._last_reason = str(reason)
                self._condition.notify_all()
            elif plan.identity == self._last_dispatched_identity:
                self._last_reason = "awaiting_next_bar"
            else:
                previous_plan = self._plan
                if previous_plan is not None and previous_plan.identity != plan.identity:
                    self._cancelled_stale_events += 1
                if plan.identity != self._last_planned_identity:
                    self._scheduled_events += 1
                    self._last_planned_identity = plan.identity
                self._plan = plan
                self._generation += 1
                self._last_reason = "scheduled"
                self._condition.notify_all()
        if cancel_reason is not None:
            self._cancel(cancel_reason)

    def _should_dispatch_due_plan_before_replanning(self, next_plan, now):
        current_plan = self._plan
        if current_plan is None or next_plan is None:
            return False
        if (
            current_plan.track_path != next_plan.track_path
            or current_plan.deck_number != next_plan.deck_number
            or next_plan.bar_number != current_plan.bar_number + 1
        ):
            return False
        late_milliseconds = (float(now) - current_plan.deadline_monotonic_seconds) * 1000.0
        return 0.0 <= late_milliseconds <= MAXIMUM_VIRTUALDJ_BEAT_PULSE_LATE_DISPATCH_MILLISECONDS

    def state(self):
        with self._condition:
            plan = self._plan
            return {
                "enabled": self._enabled,
                "slot_id": self._slot_id,
                "duration_milliseconds": self._duration_milliseconds,
                "pending": plan is not None,
                "pending_event": None if plan is None else {
                    "deck_number": plan.deck_number,
                    "track_path": plan.track_path,
                    "bar_number": plan.bar_number,
                    "beat_number": 1,
                    "deadline_monotonic_milliseconds": int(round(plan.deadline_monotonic_seconds * 1000.0)),
                },
                "last_reason": self._last_reason,
                "scheduled_events": self._scheduled_events,
                "executed_events": self._executed_events,
                "duplicate_events": self._duplicate_events,
                "cancelled_stale_events": self._cancelled_stale_events,
                "failed_dispatches": self._failed_dispatches,
                "dispatch_error_milliseconds": self._summary(self._dispatch_errors_milliseconds),
                "last_event": self._last_event,
            }

    def _run(self):
        while True:
            with self._condition:
                while not self._enabled or self._plan is None:
                    self._condition.wait()
                plan = self._plan
                generation = self._generation
                delay = plan.deadline_monotonic_seconds - float(self._clock())
                if delay > 0:
                    self._condition.wait(timeout=delay)
                    continue
                if not self._enabled or generation != self._generation or plan != self._plan:
                    continue
                self._plan = None
                if plan.identity == self._last_dispatched_identity:
                    self._duplicate_events += 1
                    self._last_reason = "duplicate_suppressed"
                    continue

            scheduler_wake_at = float(self._clock())
            dispatched_at = self._dispatch(plan, generation, self._is_current_dispatch)
            with self._condition:
                self._last_dispatched_identity = plan.identity
                self._last_event = {
                    "deck_number": plan.deck_number,
                    "track_path": plan.track_path,
                    "bar_number": plan.bar_number,
                    "beat_number": 1,
                    "predicted_deadline_monotonic_milliseconds": int(
                        round(plan.deadline_monotonic_seconds * 1000.0)
                    ),
                    "scheduler_wake_monotonic_milliseconds": int(
                        round(scheduler_wake_at * 1000.0)
                    ),
                    "scheduler_wake_error_milliseconds": (
                        scheduler_wake_at - plan.deadline_monotonic_seconds
                    ) * 1000.0,
                    "dmx_dispatch_monotonic_milliseconds": None if dispatched_at is None else int(
                        round(float(dispatched_at) * 1000.0)
                    ),
                    "dmx_dispatch_error_milliseconds": None if dispatched_at is None else (
                        float(dispatched_at) - plan.deadline_monotonic_seconds
                    ) * 1000.0,
                }
                if dispatched_at is None:
                    self._failed_dispatches += 1
                    self._last_reason = "dispatch_failed"
                    continue
                error = (float(dispatched_at) - plan.deadline_monotonic_seconds) * 1000.0
                self._dispatch_errors_milliseconds.append(abs(error))
                self._executed_events += 1
                self._last_reason = "dispatched"

    def _is_current_dispatch(self, plan, generation):
        with self._condition:
            return self._enabled and generation == self._generation and plan.identity != self._last_dispatched_identity

    @staticmethod
    def _summary(values):
        values = list(values)
        if not values:
            return {"count": 0, "mean": None, "p50": None, "p95": None, "max": None}
        ordered = sorted(values)

        def percentile(fraction):
            return ordered[min(len(ordered) - 1, int(math.ceil(len(ordered) * fraction)) - 1)]

        return {
            "count": len(ordered),
            "mean": sum(ordered) / len(ordered),
            "p50": percentile(0.50),
            "p95": percentile(0.95),
            "max": ordered[-1],
        }


class DeveloperPlaybackController:
    def __init__(self, state_path):
        self.state_path = None
        self.clock = None
        self.configure(state_path)

    def configure(self, state_path):
        path = str(Path(state_path).expanduser())
        if path == self.state_path:
            return
        self.state_path = path
        # Native VirtualDJ transport is ephemeral bridge IPC. The historical
        # snapshot path remains a developer setting, but is never polled for
        # normal playback position.
        self.clock = PlaybackClock(BridgePlaybackStateSource())

    def state(self):
        return self.clock.state()

    def reset(self):
        self.clock.reset()

MANUAL_TRANSPORT_PROFILES = {
    "intro": {
        "energy": 0.24,
        "low": 0.18,
        "mid": 0.22,
        "high": 0.16,
        "state": "calm",
    },
    "verse": {
        "energy": 0.48,
        "low": 0.40,
        "mid": 0.38,
        "high": 0.28,
        "state": "neutral",
    },
    "build": {
        "energy": 0.66,
        "low": 0.58,
        "mid": 0.54,
        "high": 0.42,
        "state": "attack",
    },
    "chorus": {
        "energy": 0.78,
        "low": 0.66,
        "mid": 0.62,
        "high": 0.50,
        "state": "sustain",
    },
    "drop": {
        "energy": 0.92,
        "low": 0.84,
        "mid": 0.74,
        "high": 0.58,
        "state": "attack",
    },
    "down": {
        "energy": 0.38,
        "low": 0.30,
        "mid": 0.28,
        "high": 0.20,
        "state": "breakdown",
    },
    "break": {
        "energy": 0.30,
        "low": 0.22,
        "mid": 0.24,
        "high": 0.18,
        "state": "calm",
    },
    "outro": {
        "energy": 0.34,
        "low": 0.24,
        "mid": 0.28,
        "high": 0.20,
        "state": "breakdown",
    },
}


def auto_show_phrase_override_name(value):
    normalized = str(value or "none").strip().lower()
    if normalized in {"", "auto"}:
        normalized = "none"
    return normalized if normalized in AUTO_SHOW_PHRASE_OVERRIDES else "none"


def auto_show_phrase_override_label(value):
    return AUTO_SHOW_PHRASE_OVERRIDES.get(
        auto_show_phrase_override_name(value),
        AUTO_SHOW_PHRASE_OVERRIDES["none"],
    )


def manual_transport_phrase_name(value):
    normalized = auto_show_phrase_override_name(value)
    return DEFAULT_MANUAL_PHRASE if normalized == "none" else normalized


def manual_transport_phrase_profile(value):
    phrase_name = manual_transport_phrase_name(value)
    return MANUAL_TRANSPORT_PROFILES.get(
        phrase_name,
        MANUAL_TRANSPORT_PROFILES[DEFAULT_MANUAL_PHRASE],
    )


def manual_transport_trigger(phase, width=0.12, scale=1.0):
    try:
        phase_value = float(phase) % 1.0
    except (TypeError, ValueError):
        return 0.0
    pulse_width = max(0.02, float(width))
    if phase_value >= pulse_width:
        return 0.0
    return clamp_unit((1.0 - (phase_value / pulse_width)) * float(scale))


def manual_transport_waveform_state(phrase, beat_value):
    phrase_name = manual_transport_phrase_name(phrase)
    profile = manual_transport_phrase_profile(phrase_name)
    beat_floor = int(math.floor(float(beat_value or 0.0)))
    beat_phase = float(beat_value or 0.0) % 1.0
    half_phase = (float(beat_value or 0.0) * 2.0) % 1.0
    bar_phase = float(beat_value or 0.0) % 8.0
    beat_index = beat_floor % 4 + 1

    kick = manual_transport_trigger(beat_phase, width=0.14, scale=1.0)
    snare = manual_transport_trigger(beat_phase, width=0.12, scale=0.92) if beat_index in (2, 4) else 0.0
    hihat = manual_transport_trigger(half_phase, width=0.09, scale=0.68)

    low = clamp_unit(float(profile["low"]) + kick * 0.28 + snare * 0.05)
    mid = clamp_unit(float(profile["mid"]) + snare * 0.22 + kick * 0.04)
    high = clamp_unit(float(profile["high"]) + hihat * 0.22 + snare * 0.04)
    energy = clamp_unit(
        float(profile["energy"])
        + kick * 0.12
        + snare * 0.08
        + hihat * 0.04
    )

    anticipation_boost = 0.0
    if phrase_name in {"build", "chorus", "drop"} and bar_phase >= 6.0:
        anticipation_boost = clamp_unit((bar_phase - 6.0) / 2.0) * 0.12

    lookahead_2 = {
        "low": clamp_unit(low + anticipation_boost * 0.55),
        "mid": clamp_unit(mid + anticipation_boost * 0.70),
        "high": clamp_unit(high + anticipation_boost * 0.45),
    }
    lookahead_4 = {
        "low": clamp_unit(low + anticipation_boost * 0.85),
        "mid": clamp_unit(mid + anticipation_boost),
        "high": clamp_unit(high + anticipation_boost * 0.65),
    }

    state_name = str(profile.get("state") or "neutral")
    sustained_high = state_name == "sustain"
    attack = state_name == "attack"
    calm = state_name == "calm"
    breakdown = state_name == "breakdown"
    mood_hint = None
    if attack or sustained_high:
        mood_hint = 1.0
    elif calm or breakdown:
        mood_hint = 3.0
    else:
        mood_hint = 2.0

    transient = clamp_unit(max(kick, snare * 0.92, hihat * 0.64))
    volatility = clamp_unit(0.10 + hihat * 0.22 + anticipation_boost * 1.2)
    short_avg = clamp_unit((energy * 0.78) + max(kick, snare) * 0.08)
    mid_avg = clamp_unit((energy * 0.66) + max(kick, snare) * 0.05)
    long_avg = clamp_unit((energy * 0.54) + anticipation_boost * 0.08)

    return {
        "energy": energy,
        "bands": {
            "low": low,
            "mid": mid,
            "high": high,
        },
        "lookahead": {
            "2": lookahead_2,
            "4": lookahead_4,
        },
        "analysis": {
            "instant": energy,
            "short_avg": short_avg,
            "mid_avg": mid_avg,
            "long_avg": long_avg,
            "lift": clamp_unit(max(0.0, energy - long_avg)),
            "crest": clamp_unit(max(0.0, energy - short_avg)),
            "transient": transient,
            "volatility": volatility,
            "sustained_high": sustained_high,
            "attack": attack,
            "calm": calm,
            "breakdown": breakdown,
            "mood_hint": mood_hint,
            "state": state_name,
        },
        "drums": {
            "kick": kick,
            "snare": snare,
            "hihat": hihat,
            "low_onset": kick,
            "mid_onset": snare,
            "high_onset": hihat,
        },
    }


def track_color_signature(track_title=None, track_artist=None, track_album=None):
    parts = [
        str(track_title or "").strip(),
        str(track_artist or "").strip(),
        str(track_album or "").strip(),
    ]
    meaningful = [part for part in parts if part and part != "-"]
    if not meaningful:
        return None
    return "|".join(parts)


def color_phrase_group(phrase):
    key = normalize_phrase(phrase)
    if key.startswith("intro"):
        return "intro"
    if key.startswith("verse") or key.startswith("up"):
        return "verse"
    if key.startswith("chorus"):
        return "chorus"
    if key in {"bridge", "down", "break", "build", "drop"}:
        return "bridge"
    if key.startswith("outro"):
        return "outro"
    return None


def themed_bank_options(theme, group):
    if theme == 0:
        return {
            "intro": [1, 4],
            "verse": [2, 1],
            "chorus": [3, 6],
            "bridge": [4, 1],
            "outro": [5, 1],
        }.get(group, [2])
    if theme == 1:
        return {
            "intro": [5, 1],
            "verse": [5, 2],
            "chorus": [3, 5, 8],
            "bridge": [4, 5],
            "outro": [5],
        }.get(group, [5])
    if theme == 2:
        return {
            "intro": [6, 1],
            "verse": [2, 6],
            "chorus": [6, 3, 8],
            "bridge": [4, 6],
            "outro": [5, 6],
        }.get(group, [6])
    if theme == 3:
        return {
            "intro": [7, 1],
            "verse": [2, 7],
            "chorus": [7, 8, 3],
            "bridge": [4, 7],
            "outro": [5, 7],
        }.get(group, [7])
    if theme == 4:
        return {
            "intro": [1, 4],
            "verse": [4, 2],
            "chorus": [3, 4, 5],
            "bridge": [4, 1],
            "outro": [5, 4],
        }.get(group, [4])
    return {
        "intro": [1, 6],
        "verse": [2, 5],
        "chorus": [8, 3, 6],
        "bridge": [4, 8],
        "outro": [5, 1],
    }.get(group, [8])


def themed_color_bank_for_phrase(phrase, track_title=None, track_artist=None, track_album=None):
    group = color_phrase_group(phrase)
    if not group:
        return None
    signature = track_color_signature(track_title, track_artist, track_album)
    if not signature:
        return None
    theme = int(stable_hash(signature) % 6)
    options = themed_bank_options(theme, group)
    if not options:
        return None
    variant = int(stable_hash(f"{signature}|{group}|{normalize_phrase(phrase)}") % len(options))
    return options[variant]


def track_fallback_color_bank(track_title=None, track_artist=None, track_album=None):
    signature = track_color_signature(track_title, track_artist, track_album)
    if not signature:
        return None
    return int(stable_hash(signature) % 8) + 1


def derive_color_bank_value(color_bank, phrase=None, track_title=None, track_artist=None, track_album=None):
    if color_bank is not None:
        try:
            value = int(round(float(color_bank)))
        except (TypeError, ValueError):
            value = None
        if value is not None:
            if value != 0:
                return value
    themed = themed_color_bank_for_phrase(
        phrase,
        track_title=track_title,
        track_artist=track_artist,
        track_album=track_album,
    )
    if themed is not None:
        return themed
    fallback = track_fallback_color_bank(
        track_title=track_title,
        track_artist=track_artist,
        track_album=track_album,
    )
    if fallback is not None:
        return fallback
    return 1


def mood_value_for_phrase(phrase):
    key = normalize_phrase(phrase)
    if key in {
        "intro1",
        "intro2",
        "up1",
        "up2",
        "up3",
        "down",
        "chorus1",
        "chorus2",
        "outro1",
        "outro2",
    }:
        return 1.0
    if key in {"verse3", "verse4", "verse5", "verse6"}:
        return 2.0
    if key in {
        "intro",
        "verse",
        "verse1",
        "verse2",
        "bridge",
        "chorus",
        "outro",
    }:
        return 2.0
    return None


def derive_mood_value(mood, phrase=None, color_bank=None):
    if mood is not None:
        try:
            value = float(mood)
        except (TypeError, ValueError):
            value = None
        if value is not None and math.isfinite(value):
            clamped = min(3.0, max(1.0, value))
            return clamped

    derived_from_phrase = mood_value_for_phrase(phrase)
    if derived_from_phrase is not None:
        return derived_from_phrase

    if color_bank is not None:
        return 2.0

    return None


def mood_factor_from_value(mood):
    if mood is None:
        return 0.5
    value = min(3.0, max(1.0, float(mood)))
    # BPM Trigger / Rekordbox semantics:
    # 1 = high, 2 = mid, 3 = low
    return clamp_unit((3.0 - value) / 2.0)


def clamp_unit(value):
    return max(0.0, min(1.0, float(value)))


def clamp_rgbw(rgbw):
    return tuple(clamp_dmx(component) for component in rgbw)


def mix_rgbw(base, target, amount):
    amount = clamp_unit(amount)
    return clamp_rgbw(
        round(base[index] + (target[index] - base[index]) * amount)
        for index in range(4)
    )


def saturate_rgbw(rgbw, minimum_saturation=0.0, white_cap=None):
    r, g, b, w = (clamp_dmx(component) for component in rgbw)
    if white_cap is not None:
        w = min(w, clamp_dmx(white_cap))
    maximum = max(r, g, b)
    minimum = min(r, g, b)
    chroma = maximum - minimum
    if maximum <= 0 or chroma < 12:
        return (r, g, b, w)

    hue, saturation, value = colorsys.rgb_to_hsv(
        float(r) / 255.0,
        float(g) / 255.0,
        float(b) / 255.0,
    )
    if saturation >= minimum_saturation:
        return (r, g, b, w)

    boosted = colorsys.hsv_to_rgb(hue, minimum_saturation, value)
    return (
        clamp_dmx(round(boosted[0] * 255.0)),
        clamp_dmx(round(boosted[1] * 255.0)),
        clamp_dmx(round(boosted[2] * 255.0)),
        w,
    )


def normalize_rgbw_peak(rgbw, peak_target=255, white_cap=None, minimum_peak=96):
    r, g, b, w = (clamp_dmx(component) for component in rgbw)
    if white_cap is not None:
        w = min(w, clamp_dmx(white_cap))
    current_peak = max(r, g, b)
    if current_peak < max(1, int(minimum_peak)):
        return (r, g, b, w)
    if current_peak >= peak_target:
        return (r, g, b, w)
    scale = float(peak_target) / float(current_peak)
    return (
        clamp_dmx(round(r * scale)),
        clamp_dmx(round(g * scale)),
        clamp_dmx(round(b * scale)),
        w,
    )


def _rgb_hue(rgbw):
    r, g, b = (float(clamp_dmx(component)) / 255.0 for component in rgbw[:3])
    hue, _saturation, _value = colorsys.rgb_to_hsv(r, g, b)
    return hue


def clarify_rgbw(rgbw, anchor_strength=0.72, white_cap=None):
    r, g, b, w = (clamp_dmx(component) for component in rgbw)
    if white_cap is not None:
        w = min(w, clamp_dmx(white_cap))
    peak = max(r, g, b)
    chroma = peak - min(r, g, b)
    if peak < 96 or chroma < 36:
        return (r, g, b, w)

    hue = _rgb_hue((r, g, b, 0))
    anchor = min(
        VIVID_COLOR_ANCHORS,
        key=lambda candidate: min(
            abs(_rgb_hue(candidate) - hue),
            1.0 - abs(_rgb_hue(candidate) - hue),
        ),
    )
    clarified = mix_rgbw((r, g, b, 0), anchor, anchor_strength)
    clarified = saturate_rgbw(clarified, minimum_saturation=0.84, white_cap=0)
    clarified = normalize_rgbw_peak(clarified, peak_target=255, white_cap=0, minimum_peak=96)
    return clarified


def stable_hash(text):
    value = 0
    for char in str(text or ""):
        value = ((value * 131) + ord(char)) & 0xFFFFFFFF
    return value


def track_preview_identity(track_title=None, track_artist=None, track_album=None):
    return "|".join(
        [
            str(track_title or "").strip(),
            str(track_artist or "").strip(),
            str(track_album or "").strip(),
        ]
    )


def track_preview_cache_key(track_title=None, track_artist=None, track_album=None):
    return f"{stable_hash(track_preview_identity(track_title, track_artist, track_album)):08x}"


def track_preview_summary_path(track_title=None, track_artist=None, track_album=None):
    return track_preview_summary_best_path_for_cache_key(
        track_preview_cache_key(track_title, track_artist, track_album)
    )


def track_preview_summary_path_for_cache_key(cache_key):
    return track_preview_summary_best_path_for_cache_key(cache_key)


def pick_variant(options, seed, fallback):
    if not options:
        return fallback
    return options[int(seed) % len(options)]


def merge_variant_pools(*pools):
    merged = []
    for pool in pools:
        for item in pool or []:
            if item not in merged:
                merged.append(item)
    return merged


def titleize_variant(name):
    return str(name or "").replace("_", " ").title()


def phrase_bucket(phrase):
    key = normalize_phrase(phrase)
    if key.startswith("intro"):
        return "intro"
    if key.startswith("verse"):
        return "verse"
    if key.startswith("bridge"):
        return "down"
    if key.startswith("up") or key.startswith("build"):
        return "build"
    if key.startswith("chorus"):
        return "chorus"
    if key.startswith("drop"):
        return "drop"
    if key.startswith("down"):
        return "down"
    if key.startswith("break"):
        return "break"
    if key.startswith("outro"):
        return "outro"
    return "unknown"


def build_phrase_stage(phrase):
    key = normalize_phrase(phrase)
    if not (key.startswith("up") or key.startswith("build")):
        return None
    digits = "".join(ch for ch in key if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except (TypeError, ValueError):
        return None


def is_early_build_phrase(phrase):
    stage = build_phrase_stage(phrase)
    return stage is not None and stage <= 2


def waveform_analysis_from_samples(samples, now):
    if not samples:
        return None

    recent = [(ts, clamp_unit(value)) for ts, value in samples if now - ts <= 8.0]
    if not recent:
        return None

    def window_values(seconds):
        values = [value for ts, value in recent if now - ts <= seconds]
        return values or [recent[-1][1]]

    def average(values):
        return sum(values) / len(values) if values else 0.0

    short_values = window_values(0.85)
    mid_values = window_values(2.8)
    long_values = window_values(6.5)
    instant = recent[-1][1]
    short_avg = average(short_values)
    mid_avg = average(mid_values)
    long_avg = average(long_values)

    volatility_values = []
    transient = 0.0
    for index in range(1, len(short_values)):
        delta = short_values[index] - short_values[index - 1]
        volatility_values.append(abs(delta))
        transient = max(transient, delta)

    lift = short_avg - long_avg
    crest = short_avg - mid_avg
    volatility = clamp_unit(average(volatility_values) * 4.0) if volatility_values else 0.0
    sustained_high = short_avg >= 0.72 and mid_avg >= 0.60
    attack = transient >= 0.09 and instant >= 0.64 and lift >= 0.08
    calm = short_avg <= 0.26 and mid_avg <= 0.30 and volatility <= 0.08
    breakdown = short_avg <= 0.22 and mid_avg <= 0.28 and lift <= -0.07

    if sustained_high or attack or (short_avg >= 0.80 and lift >= 0.06):
        mood_hint = 1.0
    elif breakdown or calm:
        mood_hint = 3.0
    elif short_avg >= 0.52 or mid_avg >= 0.48 or lift >= 0.08:
        mood_hint = 2.0
    else:
        mood_hint = None

    return {
        "instant": instant,
        "short_avg": short_avg,
        "mid_avg": mid_avg,
        "long_avg": long_avg,
        "lift": lift,
        "crest": crest,
        "transient": transient,
        "volatility": volatility,
        "sustained_high": sustained_high,
        "attack": attack,
        "calm": calm,
        "breakdown": breakdown,
        "mood_hint": mood_hint,
    }


def refine_mood_with_waveform(mood, phrase=None, analysis=None):
    if not analysis:
        return mood

    section = phrase_bucket(phrase)
    base = None
    if mood is not None:
        try:
            base = min(3.0, max(1.0, float(mood)))
        except (TypeError, ValueError):
            base = None

    hint = analysis.get("mood_hint")
    if hint is None:
        return base

    short_avg = float(analysis.get("short_avg") or 0.0)
    mid_avg = float(analysis.get("mid_avg") or 0.0)
    lift = float(analysis.get("lift") or 0.0)
    transient = float(analysis.get("transient") or 0.0)
    calm = bool(analysis.get("calm"))
    breakdown = bool(analysis.get("breakdown"))
    sustained_high = bool(analysis.get("sustained_high"))
    attack = bool(analysis.get("attack"))

    target = None
    if section in ("intro", "down", "break", "outro") and (calm or breakdown):
        target = 3.0
    elif section == "verse":
        if sustained_high and (lift >= 0.10 or transient >= 0.08):
            target = 1.0
        elif breakdown and short_avg <= 0.20:
            target = 3.0
    elif section in ("build", "chorus", "drop"):
        if attack or sustained_high or short_avg >= 0.74 or mid_avg >= 0.62:
            target = 1.0
        elif breakdown and not attack:
            target = 2.0

    if target is None:
        return base

    if base is None:
        return target

    if target < base:
        return max(target, base - 1.0)
    if target > base:
        return min(target, base + 1.0)
    return base


def osc_waveform_band_profile(osc):
    audio_bands = osc.get("audio_bands") or {}
    preview_bands = osc.get("waveform_bands") or {}
    bands = (
        audio_bands
        if any(audio_bands.get(key) is not None for key in ("low", "mid", "high"))
        else preview_bands
    )

    def band_value(key):
        value = bands.get(key)
        if value is None:
            return None
        try:
            return clamp_unit(float(value))
        except (TypeError, ValueError):
            return None

    low = band_value("low")
    mid = band_value("mid")
    high = band_value("high")
    return {
        "low": low,
        "mid": mid,
        "high": high,
        "has_data": any(value is not None for value in (low, mid, high)),
        "low_focus": clamp_unit((low or 0.0) * 1.00 + (mid or 0.0) * 0.20),
        "mid_focus": clamp_unit((mid or 0.0) * 1.00 + (high or 0.0) * 0.18),
        "high_focus": clamp_unit((high or 0.0) * 1.00 + (mid or 0.0) * 0.12),
    }


def weighted_band_activity(profile):
    if not profile or not profile.get("has_data"):
        return None
    return clamp_unit(
        (profile.get("low") or 0.0) * 0.52
        + (profile.get("mid") or 0.0) * 0.30
        + (profile.get("high") or 0.0) * 0.18
    )


def osc_waveform_lookahead_profile(osc, beats_ahead):
    lookahead = osc.get("waveform_lookahead") or {}
    bands = lookahead.get(str(int(beats_ahead))) or {}

    def band_value(key):
        value = bands.get(key)
        if value is None:
            return None
        try:
            return clamp_unit(float(value))
        except (TypeError, ValueError):
            return None

    low = band_value("low")
    mid = band_value("mid")
    high = band_value("high")
    profile = {
        "low": low,
        "mid": mid,
        "high": high,
        "has_data": any(value is not None for value in (low, mid, high)),
        "beats_ahead": int(beats_ahead),
    }
    profile["activity"] = weighted_band_activity(profile)
    return profile


def osc_drum_profile(osc):
    audio_signals = osc.get("audio_drums") or {}
    preview_signals = osc.get("drum_signals") or {}
    signals = (
        audio_signals
        if any(
            audio_signals.get(key) is not None
            for key in ("kick", "snare", "hihat", "low_onset", "mid_onset", "high_onset")
        )
        else preview_signals
    )

    def signal_value(key):
        value = signals.get(key)
        if value is None:
            return 0.0
        try:
            return clamp_unit(float(value))
        except (TypeError, ValueError):
            return 0.0

    # Treat drum extraction as guidance, not a hard driver for the autoshow.
    kick = clamp_unit(max(signal_value("kick"), signal_value("low_onset")) * 0.72)
    snare = clamp_unit(max(signal_value("snare"), signal_value("mid_onset")) * 0.66)
    hihat = clamp_unit(max(signal_value("hihat"), signal_value("high_onset")) * 0.58)
    impact = clamp_unit(kick * 0.82 + snare * 0.48)
    motion = clamp_unit(kick * 0.28 + snare * 0.32 + hihat * 0.20)
    sparkle = clamp_unit(hihat * 0.42 + snare * 0.16)
    return {
        "kick": kick,
        "snare": snare,
        "hihat": hihat,
        "impact": impact,
        "motion": motion,
        "sparkle": sparkle,
        "percussive": max(kick, snare, hihat),
        "busy": clamp_unit(impact * 0.60 + sparkle * 0.40),
    }


def osc_dimmer_activity_profile(osc, drums=None):
    waveform = osc.get("waveform_analysis") or {}
    drums = drums or osc_drum_profile(osc)
    waveform_energy = osc.get("waveform_energy")
    try:
        waveform_energy = (
            None if waveform_energy is None else clamp_unit(float(waveform_energy))
        )
    except (TypeError, ValueError):
        waveform_energy = None

    short_avg = clamp_unit(float(waveform.get("short_avg") or 0.0))
    mid_avg = clamp_unit(float(waveform.get("mid_avg") or 0.0))
    transient = clamp_unit(float(waveform.get("transient") or 0.0) * 4.5)
    volatility = clamp_unit(float(waveform.get("volatility") or 0.0) * 4.0)
    impact = clamp_unit(float(drums.get("impact") or 0.0))
    motion = clamp_unit(float(drums.get("motion") or 0.0))
    sparkle = clamp_unit(float(drums.get("sparkle") or 0.0))

    activity = clamp_unit(
        (0.28 * short_avg)
        + (0.18 * mid_avg)
        + (0.16 * (waveform_energy if waveform_energy is not None else short_avg))
        + (0.14 * transient)
        + (0.08 * volatility)
        + (0.10 * impact)
        + (0.04 * motion)
        + (0.02 * sparkle)
    )
    calm = bool(waveform.get("calm")) or activity <= 0.28
    breakdown = bool(waveform.get("breakdown")) or activity <= 0.22
    active = activity >= 0.48
    peak = activity >= 0.66
    return {
        "activity": activity,
        "calm": calm,
        "breakdown": breakdown,
        "active": active,
        "peak": peak,
    }


def auto_show_style(style_name):
    return AUTO_SHOW_STYLES.get(style_name, AUTO_SHOW_STYLES["adaptive"])


def weighted_variant_pool(base_options, prefer=None, avoid=None, prefer_weight=3):
    avoid_set = {str(item) for item in (avoid or [])}
    filtered = [item for item in (base_options or []) if str(item) not in avoid_set]
    if not prefer:
        return filtered
    weighted = []
    for item in prefer:
        if str(item) in avoid_set:
            continue
        weighted.extend([item] * prefer_weight)
    weighted.extend(filtered)
    return weighted or list(base_options or [])


def auto_show_style_variant_pool(style_name, category, section, base_options):
    rules = AUTO_SHOW_STYLE_VARIANT_RULES.get(style_name, {})
    category_rules = rules.get(category, {})
    wildcard = category_rules.get("*", {})
    specific = category_rules.get(section, {})
    prefer = list(wildcard.get("prefer", [])) + list(specific.get("prefer", []))
    avoid = list(wildcard.get("avoid", [])) + list(specific.get("avoid", []))
    weight = int(specific.get("prefer_weight") or wildcard.get("prefer_weight") or 3)
    return weighted_variant_pool(base_options, prefer=prefer, avoid=avoid, prefer_weight=weight)


def auto_show_profile(section):
    return AUTO_SHOW_SECTIONS.get(section, AUTO_SHOW_SECTIONS["unknown"])


def auto_show_effective_section(
    section,
    osc,
    waveform_factor=None,
    waveform_bands=None,
    waveform_lookahead_2=None,
    waveform_lookahead_4=None,
    drum_profile=None,
    waveform_analysis=None,
):
    if section != "outro":
        return section

    activity = auto_show_outro_activity_score(
        osc,
        waveform_factor=waveform_factor,
        waveform_bands=waveform_bands,
        waveform_lookahead_2=waveform_lookahead_2,
        waveform_lookahead_4=waveform_lookahead_4,
        drum_profile=drum_profile,
        waveform_analysis=waveform_analysis,
    )
    return auto_show_outro_bucket_for_activity(activity)


def auto_show_outro_activity_score(
    osc,
    waveform_factor=None,
    waveform_bands=None,
    waveform_lookahead_2=None,
    waveform_lookahead_4=None,
    drum_profile=None,
    waveform_analysis=None,
):
    waveform_bands = waveform_bands or osc_waveform_band_profile(osc)
    waveform_lookahead_2 = waveform_lookahead_2 or osc_waveform_lookahead_profile(osc, 2)
    waveform_lookahead_4 = waveform_lookahead_4 or osc_waveform_lookahead_profile(osc, 4)
    drum_profile = drum_profile or osc_drum_profile(osc)
    analysis = waveform_analysis or osc.get("waveform_analysis") or {}

    def optional_unit(value):
        if value is None:
            return None
        try:
            return clamp_unit(float(value))
        except (TypeError, ValueError):
            return None

    activity_sum = 0.0
    weight_sum = 0.0

    def add_component(value, weight):
        nonlocal activity_sum, weight_sum
        unit = optional_unit(value)
        if unit is None:
            return
        activity_sum += unit * weight
        weight_sum += weight

    add_component(waveform_factor, 0.34)
    add_component(analysis.get("short_avg"), 0.24)
    add_component(analysis.get("mid_avg"), 0.18)
    add_component((waveform_bands or {}).get("low"), 0.08)
    add_component((waveform_bands or {}).get("mid"), 0.07)
    add_component((waveform_bands or {}).get("high"), 0.05)
    add_component((waveform_lookahead_2 or {}).get("activity"), 0.07)
    add_component((waveform_lookahead_4 or {}).get("activity"), 0.04)
    add_component((drum_profile or {}).get("impact"), 0.10)
    add_component((drum_profile or {}).get("motion"), 0.06)

    activity = activity_sum / weight_sum if weight_sum > 0.0 else 0.0
    activity = clamp_unit(
        activity
        + (0.05 if analysis.get("sustained_high") else 0.0)
        + (0.03 if analysis.get("attack") else 0.0)
        - (0.05 if analysis.get("calm") else 0.0)
        - (0.07 if analysis.get("breakdown") else 0.0)
    )

    return activity


def auto_show_outro_bucket_for_activity(activity):
    activity = clamp_unit(activity)
    if activity >= 0.76:
        return "chorus"
    if activity >= 0.62:
        return "build"
    if activity >= 0.52:
        return "verse"
    return "outro"


def auto_show_color_source(style_name, section, osc):
    preferred = auto_show_style(style_name)["preferred_color_source"]
    has_phrase = bool(osc.get("phrase_current"))
    has_mood = osc.get("mood") is not None
    has_bank = osc.get("color_bank") in COLOR_BANKS

    if preferred == "color_bank" and has_bank:
        return "color_bank"
    if preferred == "mood" and has_mood:
        return "mood"
    if preferred == "manual":
        return "manual"

    if section in ("chorus", "drop") and has_bank:
        return "color_bank"
    if section in ("build", "chorus", "drop") and has_phrase:
        return "phrase"
    if section in ("verse", "down", "break") and has_mood:
        return "mood"
    if has_phrase:
        return "phrase"
    if has_mood:
        return "mood"
    if has_bank:
        return "color_bank"
    return "manual"


def auto_show_manual_color(style_name, section, osc):
    scene = auto_show_scene_variants(style_name, section, osc)
    color_profile = auto_show_color_profile(scene["color_profile_name"])
    pair_a = color_profile["primary"]
    pair_b = color_profile["secondary"]
    pair_mix = mix_rgbw(pair_a, pair_b, 0.5)

    if style_name == "warm":
        palette = {
            "intro": mix_rgbw(pair_a, (255, 130, 40, 0), 0.40),
            "verse": mix_rgbw(pair_a, (255, 165, 65, 0), 0.42),
            "build": mix_rgbw(pair_a, (255, 200, 55, 0), 0.45),
            "chorus": mix_rgbw(pair_mix, (255, 120, 70, 30), 0.50),
            "drop": mix_rgbw(pair_mix, (255, 220, 170, 255), 0.55),
            "break": mix_rgbw(pair_b, (255, 115, 55, 0), 0.32),
            "outro": mix_rgbw(pair_a, (255, 110, 45, 0), 0.40),
            "unknown": mix_rgbw(pair_mix, (255, 150, 55, 0), 0.40),
        }
        return palette.get(section, palette["unknown"])

    if style_name == "festival":
        palette = {
            "intro": mix_rgbw(pair_mix, (80, 130, 255, 0), 0.46),
            "verse": mix_rgbw(pair_mix, (255, 70, 170, 0), 0.42),
            "build": mix_rgbw(pair_a, (255, 80, 60, 0), 0.44),
            "chorus": mix_rgbw(pair_b, (255, 60, 210, 18), 0.50),
            "drop": mix_rgbw(pair_mix, (255, 235, 255, 255), 0.62),
            "break": mix_rgbw(pair_b, (80, 140, 255, 0), 0.42),
            "outro": mix_rgbw(pair_mix, (255, 95, 150, 0), 0.42),
            "unknown": mix_rgbw(pair_mix, (180, 90, 255, 0), 0.46),
        }
        return palette.get(section, palette["unknown"])

    if style_name == "minimal":
        palette = {
            "intro": mix_rgbw(pair_b, (60, 95, 170, 0), 0.44),
            "verse": mix_rgbw(pair_mix, (70, 110, 150, 0), 0.40),
            "build": mix_rgbw(pair_a, (160, 150, 120, 0), 0.28),
            "chorus": mix_rgbw(pair_b, (150, 145, 210, 8), 0.36),
            "drop": mix_rgbw(pair_mix, (210, 220, 245, 120), 0.44),
            "break": mix_rgbw(pair_b, (55, 85, 165, 0), 0.46),
            "outro": mix_rgbw(pair_mix, (95, 105, 135, 0), 0.38),
            "unknown": mix_rgbw(pair_mix, (90, 120, 155, 0), 0.40),
        }
        return palette.get(section, palette["unknown"])

    if style_name == "cinematic":
        palette = {
            "intro": mix_rgbw(pair_b, (55, 90, 180, 0), 0.52),
            "verse": mix_rgbw(pair_mix, (60, 150, 125, 0), 0.46),
            "build": mix_rgbw(pair_a, (255, 180, 65, 0), 0.35),
            "chorus": mix_rgbw(pair_b, (210, 110, 255, 20), 0.46),
            "drop": mix_rgbw(pair_mix, (220, 235, 255, 255), 0.58),
            "break": mix_rgbw(pair_b, (50, 80, 190, 0), 0.54),
            "outro": mix_rgbw(pair_mix, (90, 95, 150, 0), 0.44),
            "unknown": mix_rgbw(pair_mix, (85, 125, 190, 0), 0.48),
        }
        return palette.get(section, palette["unknown"])

    if style_name == "club":
        return (
            COLOR_BANKS.get(osc.get("color_bank"))
            or mix_rgbw(pair_a, pair_b, 0.35)
            or color_for_phrase(osc.get("phrase_current"))
            or pair_a
        )

    return (
        mix_rgbw(
            color_for_phrase(osc.get("phrase_current"))
            or color_for_mood(osc.get("mood"))
            or COLOR_BANKS.get(osc.get("color_bank"))
            or COLOR_PRESETS["mid"],
            pair_mix,
            0.24,
        )
    )


def auto_show_section_accent(section):
    palette = {
        "intro": (255, 175, 110, 0),
        "verse": (45, 210, 165, 0),
        "build": (255, 185, 35, 0),
        "chorus": (255, 80, 200, 0),
        "drop": (255, 90, 200, 0),
        "break": (95, 100, 255, 0),
        "outro": (255, 140, 75, 24),
        "unknown": (95, 215, 185, 20),
    }
    return palette.get(section, palette["unknown"])


def auto_show_color_profile(name):
    return AUTO_SHOW_COLOR_PROFILES.get(name, AUTO_SHOW_COLOR_PROFILES["yellow_blue"])


def osc_track_identity(osc):
    title = str(osc.get("track_title") or "").strip()
    artist = str(osc.get("track_artist") or "").strip()
    album = str(osc.get("track_album") or "").strip()
    meaningful = [value for value in (title, artist, album) if value and value != "-"]
    if meaningful:
        return track_preview_identity(title, artist, album)
    return "|".join(
        [
            "fallback",
            str(round(float(osc.get("bpm") or 0.0))),
            str(int(round(float(osc.get("mood") or 0.0))) if osc.get("mood") is not None else ""),
            str(int(round(float(osc.get("color_bank") or 0.0))) if osc.get("color_bank") is not None else ""),
        ]
    )


def auto_show_track_theme(theme_name):
    return TRACK_SHOW_THEMES.get(theme_name, TRACK_SHOW_THEMES[TRACK_SHOW_THEME_SEQUENCE[0]])


def track_show_theme_for_identity(identity):
    theme_name = TRACK_SHOW_THEME_SEQUENCE[
        stable_hash(identity) % max(1, len(TRACK_SHOW_THEME_SEQUENCE))
    ]
    return theme_name, auto_show_track_theme(theme_name)


def track_show_theme_for_osc(osc):
    identity = osc_track_identity(osc)
    return track_show_theme_for_identity(identity)


def osc_track_signature(osc):
    return "|".join(
        [
            osc_track_identity(osc),
            str(round(float(osc.get("bpm") or 0.0))),
            str(phrase_bucket(osc.get("phrase_current"))),
        ]
    )


def auto_show_scene_selection(
    style_name,
    section,
    track_signature,
    theme_name,
    bpm_bucket=0,
    mood_bucket=0,
    scene_window=0,
    motion_window=0,
    mirror_window=0,
    color_window=0,
    texture_window=0,
    wash_window=0,
):
    theme = auto_show_track_theme(theme_name)
    base_seed = stable_hash(
        f"{track_signature}|{style_name}|{section}|{theme_name}|{bpm_bucket}|{mood_bucket}"
    )

    theme_motion_options = (
        ((theme.get("motions") or {}).get(section, []))
        if isinstance(theme.get("motions"), dict)
        else []
    )
    theme_pulse_options = (
        ((theme.get("pulses") or {}).get(section, []))
        if isinstance(theme.get("pulses"), dict)
        else []
    )
    look_options = merge_variant_pools(
        theme.get("looks"),
        AUTO_SHOW_LOOK_POOLS.get(section, AUTO_SHOW_LOOK_POOLS["unknown"]),
    )
    color_options = merge_variant_pools(
        theme.get("color_profiles"),
        AUTO_SHOW_COLOR_PROFILE_POOLS.get(section, AUTO_SHOW_COLOR_PROFILE_POOLS["unknown"]),
    )
    accent_options = merge_variant_pools(
        theme.get("accents"),
        AUTO_SHOW_ACCENT_POOLS.get(section, AUTO_SHOW_ACCENT_POOLS["unknown"]),
    )
    texture_options = merge_variant_pools(
        theme.get("textures"),
        AUTO_SHOW_TEXTURE_POOLS.get(section, AUTO_SHOW_TEXTURE_POOLS["unknown"]),
    )
    motion_options = merge_variant_pools(
        theme_motion_options,
        AUTO_SHOW_MOTION_POOLS.get(section, AUTO_SHOW_MOTION_POOLS["unknown"]),
    )
    pulse_options = merge_variant_pools(
        theme_pulse_options,
        AUTO_SHOW_PULSE_POOLS.get(section, AUTO_SHOW_PULSE_POOLS["unknown"]),
    )
    wash_options = AUTO_SHOW_WASH_CUE_POOLS.get(section, AUTO_SHOW_WASH_CUE_POOLS["unknown"])

    look_options = auto_show_style_variant_pool(style_name, "looks", section, look_options)
    color_options = auto_show_style_variant_pool(style_name, "color_profiles", section, color_options)
    accent_options = auto_show_style_variant_pool(style_name, "accents", section, accent_options)
    texture_options = auto_show_style_variant_pool(style_name, "textures", section, texture_options)
    motion_options = auto_show_style_variant_pool(style_name, "motions", section, motion_options)
    pulse_options = auto_show_style_variant_pool(style_name, "pulses", section, pulse_options)
    wash_options = auto_show_style_variant_pool(style_name, "washes", section, wash_options)

    look_name = pick_variant(
        look_options,
        base_seed + scene_window,
        "bank_echo",
    )
    pulse_name = pick_variant(
        pulse_options,
        (base_seed >> 5) + scene_window,
        "medium",
    )
    accent_name = pick_variant(
        accent_options,
        (base_seed >> 11) + scene_window,
        "center",
    )
    color_profile_name = pick_variant(
        color_options,
        (base_seed >> 13) + color_window,
        "yellow_blue",
    )
    motion_name = pick_variant(
        motion_options,
        (base_seed >> 17) + motion_window,
        "center",
    )
    wash_cue_name = pick_variant(
        wash_options,
        (base_seed >> 29) + wash_window,
        "soft_blue_wash",
    )
    texture_name = pick_variant(
        texture_options,
        (base_seed >> 19) + texture_window,
        "steady",
    )
    mirror_seed_unit = (((base_seed >> 23) + mirror_window) % 1000) / 999.0
    mirror_threshold = clamp_unit(
        float(theme.get("mirror_bias", 0.20))
        * {
            "intro": 0.55,
            "verse": 0.80,
            "build": 1.00,
            "chorus": 1.00,
            "drop": 0.82,
            "down": 0.72,
            "break": 0.60,
            "outro": 0.55,
            "unknown": 0.76,
        }.get(section, 0.76)
    )
    mirror_within_group = (
        motion_name in AUTO_SHOW_MEMBER_MIRROR_MOTIONS
        and mirror_seed_unit <= mirror_threshold
    )

    return {
        "theme_name": theme_name,
        "theme_label": theme["label"],
        "look_name": look_name,
        "look_label": titleize_variant(look_name),
        "color_profile_name": color_profile_name,
        "color_profile_label": auto_show_color_profile(color_profile_name)["label"],
        "motion_name": motion_name,
        "motion_label": titleize_variant(motion_name),
        "wash_cue_name": wash_cue_name,
        "wash_cue_label": auto_show_wall_wash_cue(wash_cue_name)["label"],
        "texture_name": texture_name,
        "texture_label": titleize_variant(texture_name),
        "mirror_within_group": mirror_within_group,
        "pulse_name": pulse_name,
        "accent_name": accent_name,
        "scene_window": scene_window,
        "motion_window": motion_window,
        "mirror_window": mirror_window,
        "color_window": color_window,
        "texture_window": texture_window,
        "wash_window": wash_window,
        "track_signature": track_signature,
    }


def auto_show_scene_variants(style_name, section, osc):
    beat_value = float(osc.get("beat_value") or 0.0)
    track_signature = osc_track_signature(osc)
    theme_name, _theme = track_show_theme_for_osc(osc)
    scene_window = int(beat_value // 64.0)
    motion_window_size = {
        "intro": 128.0,
        "verse": 128.0,
        "build": 96.0,
        "chorus": 96.0,
        "drop": 64.0,
        "down": 128.0,
        "break": 128.0,
        "outro": 128.0,
        "unknown": 128.0,
    }.get(section, 128.0)
    motion_window = int(beat_value // motion_window_size)
    mirror_window = int(beat_value // 128.0)
    color_window = int(beat_value // 32.0)
    texture_window = int(beat_value // 32.0)
    wash_window_size = {
        "intro": 64.0,
        "verse": 64.0,
        "build": 32.0,
        "chorus": 32.0,
        "drop": 16.0,
        "down": 64.0,
        "break": 64.0,
        "outro": 64.0,
        "unknown": 64.0,
    }.get(section, 64.0)
    wash_window = int(beat_value // wash_window_size)
    bpm_bucket = int(round(float(osc.get("bpm") or 0.0) / 4.0))
    mood_bucket = (
        int(round(float(osc.get("mood") or 0.0))) if osc.get("mood") is not None else 0
    )
    return auto_show_scene_selection(
        style_name,
        section,
        track_signature,
        theme_name,
        bpm_bucket=bpm_bucket,
        mood_bucket=mood_bucket,
        scene_window=scene_window,
        motion_window=motion_window,
        mirror_window=mirror_window,
        color_window=color_window,
        texture_window=texture_window,
        wash_window=wash_window,
    )


def auto_show_motion_profile(name):
    return AUTO_SHOW_MOTION_PROFILES.get(name, AUTO_SHOW_MOTION_PROFILES["center"])


def auto_show_wall_wash_cue(name):
    return WALL_WASH_CUES.get(name, WALL_WASH_CUES["soft_blue_wash"])


def live_override_color_name(value):
    key = str(value or "none").strip().lower()
    return key if key in LIVE_OVERRIDE_COLORS else "none"


def live_override_color_label(value):
    labels = {
        "none": "Auto",
        "red": "Red",
        "yellow": "Yellow",
        "green": "Green",
        "lime": "Lime",
        "purple": "Purple",
        "pink": "Pink",
        "cyan": "Cyan",
        "orange": "Orange",
        "blue": "Blue",
        "white": "White",
        "rainbow": "Rainbow",
    }
    return labels.get(live_override_color_name(value), "Auto")


def live_override_energy_name(value):
    key = str(value or "none").strip().lower()
    return key if key in {"none", "low", "mid", "high"} else "none"


def live_override_energy_label(value):
    labels = {
        "none": "Auto",
        "low": "Low",
        "mid": "Mid",
        "high": "High",
    }
    return labels.get(live_override_energy_name(value), "Auto")


ONE_SHOT_CUES = {
    "audience_riser": {
        "label": "Audience Rise",
        "duration_beats": 16.0,
    },
    "white_hit": {
        "label": "White Hit",
        "duration_beats": 4.0,
    },
    "color_burst": {
        "label": "Color Burst",
        "duration_beats": 4.0,
    },
    "snap_fan": {
        "label": "Snap Fan",
        "duration_beats": 4.0,
    },
    "mirror_bounce": {
        "label": "Mirror Bounce",
        "duration_beats": 8.0,
    },
    "par_chase_burst": {
        "label": "PAR Chase",
        "duration_beats": 8.0,
    },
}


def one_shot_cue_name(value):
    key = str(value or "").strip().lower()
    return key if key in ONE_SHOT_CUES else "none"


def one_shot_cue_label(value):
    cue_name = one_shot_cue_name(value)
    if cue_name == "none":
        return "None"
    return ONE_SHOT_CUES[cue_name]["label"]


def one_shot_cue_definition(value):
    cue_name = one_shot_cue_name(value)
    if cue_name == "none":
        return None
    return ONE_SHOT_CUES[cue_name]


def apply_live_energy_override(level, value, *, low_target, mid_target, high_target, mix=0.68):
    name = live_override_energy_name(level)
    targets = {
        "low": low_target,
        "mid": mid_target,
        "high": high_target,
    }
    target = targets.get(name)
    if target is None:
        return clamp_unit(value)
    return clamp_unit(value * (1.0 - mix) + target * mix)


def auto_show_refined_mood_factor(level, mood_factor):
    return apply_live_energy_override(
        level,
        mood_factor,
        low_target=0.22,
        mid_target=0.50,
        high_target=0.82,
        mix=0.74,
    )


def auto_show_refined_pulse_name(section, pulse_name, style_name, osc, mood_factor, energy, override_energy="none"):
    beat_value = float(osc.get("beat_value") or 0.0)
    scene_window = int(beat_value // 64.0)
    even_window = scene_window % 2 == 0
    rare_window = scene_window % 4 == 3
    early_build = is_early_build_phrase(osc.get("phrase_current"))
    waveform = osc.get("waveform_analysis") or {}
    drums = osc_drum_profile(osc)
    attack = bool(waveform.get("attack"))
    sustained_high = bool(waveform.get("sustained_high"))
    calm = bool(waveform.get("calm"))
    breakdown = bool(waveform.get("breakdown"))
    transient = float(waveform.get("transient") or 0.0)
    kick = float(drums.get("kick") or 0.0)
    snare = float(drums.get("snare") or 0.0)
    hihat = float(drums.get("hihat") or 0.0)
    impact = float(drums.get("impact") or 0.0)
    percussive = float(drums.get("percussive") or 0.0)
    activity = osc_dimmer_activity_profile(osc, drums)
    high_mood = mood_factor >= 0.78
    peak_mood = mood_factor >= 0.90
    high_energy = energy >= 0.80
    peak_energy = energy >= 0.995
    override_energy = live_override_energy_name(override_energy)
    low_override = override_energy == "low"
    high_override = override_energy == "high"

    quiet_modes = {"low_glow", "medium", "slow_fade_in", "slow_fade_out", "breathing", "soft_pulse"}
    active_modes = {"strong_pulse", "beat_flash", "offbeat_flash", "drop_blinder", "blackout_hit", "ramp_up", "ramp_down", "tremolo_dimmer", "alternate_whole", "double_hit", "gallop", "pivot", "chase", "snake", "full_on"}

    if style_name == "festival":
        if pulse_name in {"breathing", "slow_fade_in", "slow_fade_out"}:
            pulse_name = "alternate_whole" if section in {"build", "chorus", "drop"} else "offbeat_flash"
        elif pulse_name == "soft_pulse" and section in {"build", "chorus", "drop"}:
            pulse_name = "beat_flash"
    elif style_name == "minimal":
        if pulse_name in {"snake", "chase", "drop_blinder", "blackout_hit", "gallop", "tremolo_dimmer"}:
            pulse_name = "alternate_whole" if section in {"build", "chorus", "drop"} else "soft_pulse"
        elif pulse_name == "double_hit" and section != "drop":
            pulse_name = "pivot"
    elif style_name == "cinematic":
        if pulse_name in {"snake", "chase", "drop_blinder", "blackout_hit", "gallop", "tremolo_dimmer"}:
            pulse_name = "pivot" if section in {"build", "chorus", "drop"} else "soft_pulse"
        elif pulse_name == "double_hit" and section != "drop":
            pulse_name = "alternate_whole"
    elif style_name == "warm":
        if pulse_name in {"snake", "chase", "tremolo_dimmer", "blackout_hit"}:
            pulse_name = "double_hit" if section in {"chorus", "drop"} else "alternate_whole"
        elif pulse_name == "gallop":
            pulse_name = "double_hit"
    elif style_name == "club":
        if section in {"build", "chorus", "drop"} and pulse_name in {"breathing", "slow_fade_in", "slow_fade_out"}:
            pulse_name = "alternate_whole"

    if low_override:
        if section == "intro":
            return "soft_pulse"
        if section == "outro":
            return "slow_fade_out" if even_window else "breathing"
        if section in {"down", "break"}:
            return "breathing" if even_window else "soft_pulse"
        if section == "verse":
            return "soft_pulse"
        if section == "build":
            return "breathing" if early_build or calm or breakdown else "soft_pulse"
        if section == "chorus":
            return "alternate_whole" if activity["active"] or snare >= 0.42 else "soft_pulse"
        if section == "drop":
            return "alternate_whole" if activity["active"] or impact >= 0.42 else "soft_pulse"

    if high_override and pulse_name in quiet_modes:
        if section == "build":
            pulse_name = "ramp_up" if early_build else ("double_hit" if snare >= 0.42 else "chase")
        elif section == "chorus":
            pulse_name = "double_hit" if snare >= 0.46 else ("gallop" if hihat >= 0.44 else "chase")
        elif section == "drop":
            pulse_name = "drop_blinder" if impact >= 0.52 else ("snake" if kick >= 0.46 else "chase")

    if section == "intro":
        if pulse_name in {"slow_fade_in", "soft_pulse", "offbeat_flash"}:
            return pulse_name
        return "soft_pulse"

    if section == "outro":
        if breakdown or calm:
            return "slow_fade_out" if even_window else "breathing"
        if (high_mood and transient >= 0.09 and rare_window) or (snare >= 0.58 and rare_window):
            return "offbeat_flash"
        if pulse_name in {"slow_fade_out", "breathing", "soft_pulse", "offbeat_flash"}:
            return pulse_name
        return "soft_pulse"

    if section == "down":
        if breakdown or calm:
            return "breathing" if even_window else "soft_pulse"
        if (high_mood and transient >= 0.09 and rare_window) or (hihat >= 0.54 and rare_window):
            return "offbeat_flash"
        if pulse_name in {"breathing", "soft_pulse", "offbeat_flash", "slow_fade_out"}:
            return pulse_name
        return "soft_pulse"

    if section == "break":
        if breakdown or calm:
            return "slow_fade_out" if even_window else "breathing"
        if (high_mood and transient >= 0.09 and rare_window) or (hihat >= 0.56 and rare_window):
            return "offbeat_flash"
        if pulse_name in {"breathing", "slow_fade_out", "soft_pulse", "offbeat_flash"}:
            return pulse_name
        return "breathing"

    if section == "verse":
        if breakdown or calm:
            return "soft_pulse"
        if snare >= 0.60 and rare_window:
            return "offbeat_flash"
        if pulse_name in {"breathing", "soft_pulse", "offbeat_flash"}:
            return pulse_name
        return "soft_pulse"

    if section == "build":
        if activity["breakdown"]:
            return "soft_pulse"
        if activity["calm"] and not attack:
            if high_override:
                return "ramp_up" if early_build else ("double_hit" if snare >= 0.24 else "chase")
            return "breathing" if early_build and even_window else "soft_pulse"
        if early_build and not activity["peak"]:
            if pulse_name in {"chase", "snake", "strong_pulse", "beat_flash", "tremolo_dimmer", "drop_blinder", "double_hit", "gallop"}:
                if activity["active"] or attack or kick >= 0.46 or snare >= 0.46:
                    return "ramp_up"
                return "breathing"
        if peak_mood and peak_energy and (attack or sustained_high or kick >= 0.58):
            return "drop_blinder"
        if not activity["active"] and pulse_name in {"chase", "snake", "strong_pulse", "beat_flash", "ramp_up", "double_hit", "gallop", "pivot"}:
            if high_override:
                return "ramp_up" if early_build else ("double_hit" if snare >= 0.24 else "chase")
            return "breathing" if early_build else "soft_pulse"
        if kick >= 0.60 and snare >= 0.48:
            return "chase" if even_window else "ramp_up"
        if snare >= 0.58:
            return "double_hit" if hihat >= 0.36 else "strong_pulse"
        if hihat >= 0.56 and (not early_build or activity["peak"] or attack):
            return "gallop" if kick >= 0.34 else "offbeat_flash"
        if high_mood and high_energy and attack:
            return pulse_name if pulse_name in active_modes else "ramp_up"
        if early_build and not activity["peak"] and pulse_name == "ramp_up":
            return "soft_pulse"
        if pulse_name in {"ramp_up", "strong_pulse", "soft_pulse", "breathing"}:
            return pulse_name
        return "ramp_up"

    if section == "chorus":
        if breakdown and not peak_mood:
            return "soft_pulse"
        if activity["breakdown"]:
            return "breathing"
        if activity["calm"] and not sustained_high:
            if high_override:
                return "alternate_whole" if kick < 0.24 and snare < 0.24 else ("double_hit" if snare >= hihat else "chase")
            return "soft_pulse"
        if not activity["active"] and pulse_name in {"chase", "snake", "beat_flash", "strong_pulse", "double_hit", "gallop", "pivot"}:
            if high_override:
                return "alternate_whole" if kick < 0.24 and snare < 0.24 else ("double_hit" if snare >= hihat else "chase")
            return "soft_pulse"
        if kick >= 0.56 and snare >= 0.48:
            return "gallop" if hihat >= 0.44 else ("chase" if even_window else "snake")
        if snare >= 0.60:
            return "double_hit"
        if hihat >= 0.54:
            return "pivot" if kick >= 0.36 else "offbeat_flash"
        if high_mood and high_energy and (attack or sustained_high):
            return pulse_name if pulse_name in {"chase", "snake", "beat_flash", "offbeat_flash", "strong_pulse", "alternate_whole", "double_hit", "gallop", "pivot"} else "beat_flash"
        if pulse_name in {"soft_pulse", "offbeat_flash", "beat_flash", "alternate_whole", "double_hit", "gallop", "pivot"}:
            return pulse_name
        return "soft_pulse"

    if section == "drop":
        if activity["breakdown"]:
            return "soft_pulse"
        if activity["calm"] and not peak_energy:
            if high_override:
                return "alternate_whole" if impact < 0.28 else ("snake" if kick >= 0.28 else "beat_flash")
            return "breathing"
        if not activity["active"] and pulse_name in {"snake", "chase", "beat_flash", "tremolo_dimmer", "drop_blinder", "double_hit", "gallop", "pivot"}:
            if high_override:
                return "alternate_whole" if impact < 0.28 else ("snake" if kick >= 0.28 else "chase")
            return "soft_pulse"
        if peak_mood and peak_energy and (attack or sustained_high or impact >= 0.56):
            return pulse_name if pulse_name in {"drop_blinder", "blackout_hit", "beat_flash", "snake", "chase", "tremolo_dimmer", "double_hit", "gallop", "pivot"} else "drop_blinder"
        if kick >= 0.62 and snare >= 0.46:
            return "gallop" if hihat >= 0.40 else "snake"
        if kick >= 0.58:
            return "drop_blinder"
        if snare >= 0.58:
            return "double_hit"
        if hihat >= 0.56:
            return "pivot"
        if high_mood and high_energy:
            return pulse_name if pulse_name in active_modes else "beat_flash"
        return "full_on"

    if percussive >= 0.62 and pulse_name not in quiet_modes:
        return "chase"
    if pulse_name in quiet_modes or pulse_name in active_modes:
        return pulse_name
    return "soft_pulse"


def auto_show_refined_motion_name(section, motion_name, style_name, osc, energy, movement, override_energy="none"):
    if section != "build":
        return motion_name

    beat_value = float(osc.get("beat_value") or 0.0)
    motion_window = int(beat_value // 32.0)
    early_build = is_early_build_phrase(osc.get("phrase_current"))
    waveform = osc.get("waveform_analysis") or {}
    drums = osc_drum_profile(osc)
    activity = osc_dimmer_activity_profile(osc, drums)
    kick = float(drums.get("kick") or 0.0)
    snare = float(drums.get("snare") or 0.0)
    hihat = float(drums.get("hihat") or 0.0)
    transient = float(waveform.get("transient") or 0.0)
    attack = bool(waveform.get("attack"))
    override_energy = live_override_energy_name(override_energy)
    low_override = override_energy == "low"
    high_override = override_energy == "high"

    calm_variants = [
        "build_rising_sweep",
        "build_narrow_to_wide_fan",
        "build_audience_wave",
    ]
    mid_variants = [
        "build_rising_sweep",
        "build_narrow_to_wide_fan",
        "build_audience_wave",
        "build_fastening_circle",
        "build_color_chase",
    ]
    aggressive_variants = {"build_strobe_ramp", "build_white_flash_prep"}
    flashy_variants = aggressive_variants | {"build_dimmer_pulse", "build_fastening_circle", "build_color_chase"}

    if style_name == "festival":
        calm_variants = [
            "build_audience_wave",
            "build_rising_sweep",
            "build_fastening_circle",
        ]
        mid_variants = [
            "build_fastening_circle",
            "build_color_chase",
            "build_audience_wave",
            "build_rising_sweep",
            "build_dimmer_pulse",
        ]
    elif style_name == "minimal":
        calm_variants = [
            "build_rising_sweep",
            "build_narrow_to_wide_fan",
            "build_audience_wave",
        ]
        mid_variants = [
            "build_rising_sweep",
            "build_narrow_to_wide_fan",
            "build_audience_wave",
            "build_fastening_circle",
        ]
        aggressive_variants = {"build_strobe_ramp", "build_white_flash_prep", "build_color_chase"}
        flashy_variants = aggressive_variants | {"build_dimmer_pulse", "build_fastening_circle"}
    elif style_name == "cinematic":
        calm_variants = [
            "build_rising_sweep",
            "build_narrow_to_wide_fan",
            "build_fastening_circle",
        ]
        mid_variants = [
            "build_rising_sweep",
            "build_narrow_to_wide_fan",
            "build_fastening_circle",
            "build_audience_wave",
        ]
        aggressive_variants = {"build_strobe_ramp", "build_white_flash_prep", "build_color_chase"}
        flashy_variants = aggressive_variants | {"build_dimmer_pulse"}
    elif style_name == "warm":
        calm_variants = [
            "build_rising_sweep",
            "build_narrow_to_wide_fan",
            "build_audience_wave",
        ]
        mid_variants = [
            "build_rising_sweep",
            "build_narrow_to_wide_fan",
            "build_audience_wave",
            "build_fastening_circle",
        ]
        aggressive_variants = {"build_strobe_ramp", "build_white_flash_prep"}
        flashy_variants = aggressive_variants | {"build_dimmer_pulse", "build_color_chase"}
    elif style_name == "club":
        calm_variants = [
            "build_audience_wave",
            "build_rising_sweep",
            "build_fastening_circle",
        ]
        mid_variants = [
            "build_audience_wave",
            "build_fastening_circle",
            "build_color_chase",
            "build_rising_sweep",
            "build_dimmer_pulse",
        ]

    calm_choice = calm_variants[motion_window % len(calm_variants)]
    mid_choice = mid_variants[motion_window % len(mid_variants)]

    if low_override:
        return calm_choice if early_build or activity["calm"] or not activity["active"] else mid_choice
    if high_override and motion_name in flashy_variants and not (attack or kick >= 0.42 or snare >= 0.42 or movement >= 0.58 or energy >= 0.68):
        return mid_choice

    if activity["breakdown"]:
        return calm_choice
    if activity["calm"] and not attack:
        return calm_choice
    if early_build and not activity["peak"] and motion_name in flashy_variants:
        return calm_choice if not activity["active"] else mid_choice
    if not activity["active"] and motion_name in flashy_variants:
        return mid_choice if (kick >= 0.42 or snare >= 0.42 or transient >= 0.09) else calm_choice
    if motion_name in aggressive_variants and not (attack or kick >= 0.56 or snare >= 0.56 or hihat >= 0.62 or movement >= 0.72 or energy >= 0.82):
        return mid_choice
    return motion_name


def auto_show_par_rhythm_mode(section, base_mode, style_name, osc, slot_context, override_energy="none"):
    activity = osc_dimmer_activity_profile(osc)
    override_energy = live_override_energy_name(override_energy)
    low_override = override_energy == "low"
    high_override = override_energy == "high"
    if low_override:
        if section == "drop":
            return "pair_hold" if activity["active"] else "breathing"
        if section in {"build", "chorus"}:
            return "pair_hold" if activity["active"] else "soft_pulse"
        if section in {"break", "down", "outro"}:
            return "breathing"
        if section == "verse":
            return "soft_pulse"
    elif high_override:
        if section == "build" and base_mode in {"soft_pulse", "breathing", "slow_fade_out", "slow_fade_in", "medium"}:
            base_mode = "pair_swap"
        elif section == "chorus" and base_mode in {"soft_pulse", "breathing", "medium", "full_on"}:
            base_mode = "pair_swap"
        elif section == "drop" and base_mode in {"soft_pulse", "breathing", "medium", "full_on"}:
            base_mode = "pair_bounce"
    if style_name == "festival":
        if section in {"build", "chorus", "drop"} and base_mode in {"soft_pulse", "breathing", "slow_fade_out"}:
            base_mode = "pair_swap"
        if base_mode in {"pair_hold", "alternate_whole"} and section == "drop":
            base_mode = "pair_bounce"
    elif style_name == "minimal":
        if base_mode in {"snake", "chase", "tremolo_dimmer", "gallop", "drop_blinder", "blackout_hit"}:
            base_mode = "pair_hold" if section in {"build", "chorus", "drop"} else "soft_pulse"
        elif base_mode == "double_hit" and section != "drop":
            base_mode = "pair_hold"
    elif style_name == "cinematic":
        if base_mode in {"snake", "chase", "tremolo_dimmer", "gallop", "drop_blinder", "blackout_hit"}:
            base_mode = "pair_hold" if section in {"build", "chorus", "drop"} else "soft_pulse"
        elif base_mode == "double_hit" and section != "drop":
            base_mode = "pair_hold"
    elif style_name == "warm":
        if base_mode in {"snake", "chase", "tremolo_dimmer", "gallop", "blackout_hit"}:
            base_mode = "pair_swap" if section in {"chorus", "drop"} else "pair_hold"
    elif style_name == "club":
        if section in {"build", "chorus", "drop"} and base_mode in {"soft_pulse", "breathing", "slow_fade_out"}:
            base_mode = "pair_swap"
    if section == "intro":
        return base_mode if base_mode in {"slow_fade_in", "soft_pulse", "offbeat_flash"} else "soft_pulse"
    if section == "outro":
        return base_mode if base_mode in {"slow_fade_out", "breathing", "soft_pulse", "offbeat_flash"} else "soft_pulse"
    if section == "down":
        return base_mode if base_mode in {"breathing", "soft_pulse", "offbeat_flash", "slow_fade_out"} else "soft_pulse"
    if section == "break":
        return base_mode if base_mode in {"breathing", "soft_pulse", "offbeat_flash", "slow_fade_out"} else "breathing"
    if section == "verse":
        return base_mode if base_mode in {"breathing", "soft_pulse", "offbeat_flash"} else "soft_pulse"
    if section == "build":
        if activity["breakdown"]:
            return "soft_pulse"
        if activity["calm"] and not high_override and base_mode in {"pair_swap", "pair_bounce", "chase", "beat_flash", "strong_pulse", "snake", "alternate_whole", "double_hit", "gallop", "pivot"}:
            return "soft_pulse"
        if base_mode == "snake":
            return "pair_bounce"
        if base_mode == "gallop":
            return "pair_bounce"
        if base_mode == "pivot":
            return "pair_hold"
        if base_mode == "alternate_whole":
            return "pair_hold"
        if base_mode == "double_hit":
            return "pair_swap"
        if base_mode in {"chase", "beat_flash", "strong_pulse"}:
            return "pair_swap"
        if base_mode in {"ramp_up", "medium"}:
            return "pair_hold"
        return "pair_swap"
    if section == "chorus":
        if activity["breakdown"]:
            return "breathing"
        if activity["calm"] and not high_override and base_mode in {"pair_swap", "pair_bounce", "chase", "beat_flash", "snake", "alternate_whole", "double_hit", "gallop", "pivot"}:
            return "soft_pulse"
        if base_mode == "snake":
            return "pair_bounce"
        if base_mode == "gallop":
            return "pair_bounce"
        if base_mode == "pivot":
            return "pair_hold"
        if base_mode == "alternate_whole":
            return "pair_hold"
        if base_mode == "double_hit":
            return "pair_swap"
        if base_mode in {"chase", "offbeat_flash", "beat_flash"}:
            return "pair_swap"
        if base_mode in {"medium", "soft_pulse", "full_on"}:
            return "pair_hold"
        return "pair_swap"
    if section == "drop":
        if activity["breakdown"]:
            return "soft_pulse"
        if activity["calm"] and not high_override and base_mode in {"pair_swap", "pair_bounce", "chase", "beat_flash", "snake", "tremolo_dimmer", "alternate_whole", "double_hit", "gallop", "pivot"}:
            return "breathing"
        if base_mode == "full_on":
            return "full_on"
        if base_mode in {"drop_blinder", "blackout_hit"}:
            return base_mode
        if base_mode == "snake":
            return "pair_bounce"
        if base_mode == "gallop":
            return "pair_bounce"
        if base_mode == "pivot":
            return "pair_hold"
        if base_mode == "alternate_whole":
            return "pair_hold"
        if base_mode == "double_hit":
            return "pair_swap"
        if base_mode in {"chase", "beat_flash", "tremolo_dimmer"}:
            return "pair_swap"
        return "pair_hold"
    return "soft_pulse"


def auto_show_moving_rhythm_mode(section, base_mode, style_name, osc, slot_context, energy, movement, override_energy="none"):
    activity = osc_dimmer_activity_profile(osc)
    override_energy = live_override_energy_name(override_energy)
    low_override = override_energy == "low"
    high_override = override_energy == "high"
    if section == "intro":
        return base_mode if base_mode in {"slow_fade_in", "soft_pulse", "offbeat_flash"} else "soft_pulse"
    if section == "outro":
        return base_mode if base_mode in {"slow_fade_out", "breathing", "soft_pulse", "offbeat_flash"} else "soft_pulse"
    if section == "down":
        return base_mode if base_mode in {"breathing", "soft_pulse", "offbeat_flash", "slow_fade_out"} else "soft_pulse"
    if section == "break":
        return base_mode if base_mode in {"breathing", "slow_fade_out", "soft_pulse", "offbeat_flash"} else "breathing"
    if section == "verse":
        return base_mode if base_mode in {"breathing", "soft_pulse", "offbeat_flash"} else "soft_pulse"
    drums = osc_drum_profile(osc)
    kick = float(drums.get("kick") or 0.0)
    snare = float(drums.get("snare") or 0.0)
    hihat = float(drums.get("hihat") or 0.0)
    early_build = is_early_build_phrase(osc.get("phrase_current"))
    active_window = activity["active"] or movement >= 0.62 or energy >= 0.74 or kick >= 0.40 or snare >= 0.42
    peak_window = activity["peak"] or movement >= 0.78 or energy >= 0.88 or kick >= 0.52 or snare >= 0.52
    moderate_window = active_window and not peak_window
    surge_window = peak_window or kick >= 0.60 or snare >= 0.62 or hihat >= 0.66
    if low_override:
        surge_window = False
        peak_window = False
        active_window = active_window and energy >= 0.58 and kick >= 0.34
    elif high_override:
        active_window = active_window or (section in {"build", "chorus", "drop"} and (energy >= 0.62 or kick >= 0.34 or snare >= 0.34))
        peak_window = peak_window or (section in {"build", "chorus", "drop"} and (energy >= 0.78 or kick >= 0.44 or snare >= 0.44))
        surge_window = surge_window or (section in {"build", "chorus", "drop"} and (energy >= 0.84 or kick >= 0.52 or snare >= 0.52 or hihat >= 0.56))
        if section == "build" and base_mode in {"soft_pulse", "breathing", "slow_fade_out", "medium", "offbeat_flash"}:
            base_mode = "chase_whole"
        elif section == "chorus" and base_mode in {"soft_pulse", "breathing", "medium", "offbeat_flash"}:
            base_mode = "chase_whole"
        elif section == "drop" and base_mode in {"soft_pulse", "breathing", "medium", "offbeat_flash", "full_on"}:
            base_mode = "snake_whole" if kick >= 0.28 else "chase_whole"
    if style_name == "festival":
        active_window = active_window or (section in {"build", "chorus", "drop"} and (energy >= 0.64 or kick >= 0.34 or snare >= 0.34))
        peak_window = peak_window or (section in {"build", "chorus", "drop"} and (kick >= 0.44 or snare >= 0.46 or hihat >= 0.48))
        surge_window = surge_window or (section in {"build", "chorus", "drop"} and (kick >= 0.48 or snare >= 0.50 or hihat >= 0.54))
        if base_mode in {"soft_pulse", "breathing", "slow_fade_out"} and section in {"build", "chorus", "drop"}:
            base_mode = "chase_whole"
    elif style_name == "minimal":
        if base_mode in {"snake", "snake_whole", "chase", "chase_whole", "gallop", "drop_blinder", "blackout_hit", "tremolo_dimmer"}:
            base_mode = "alternate_whole" if section in {"build", "chorus", "drop"} else "soft_pulse"
        elif base_mode == "double_hit" and section != "drop":
            base_mode = "pivot"
        surge_window = False
        peak_window = peak_window and energy >= 0.94 and kick >= 0.60
    elif style_name == "cinematic":
        if base_mode in {"snake", "snake_whole", "chase", "chase_whole", "gallop", "drop_blinder", "blackout_hit", "tremolo_dimmer"}:
            base_mode = "alternate_whole" if section in {"build", "chorus", "drop"} else "soft_pulse"
        elif base_mode == "double_hit" and section != "drop":
            base_mode = "pivot"
        surge_window = False
        peak_window = peak_window and energy >= 0.92 and kick >= 0.56
    elif style_name == "warm":
        if base_mode in {"snake", "snake_whole", "chase", "chase_whole", "gallop", "tremolo_dimmer", "blackout_hit"}:
            base_mode = "double_hit" if section in {"chorus", "drop"} else "alternate_whole"
    elif style_name == "club":
        active_window = active_window or (section in {"build", "chorus", "drop"} and (energy >= 0.66 or kick >= 0.36 or snare >= 0.36))
        peak_window = peak_window or (section in {"chorus", "drop"} and (kick >= 0.48 or snare >= 0.50 or hihat >= 0.54))
        surge_window = surge_window or (section in {"build", "chorus", "drop"} and (kick >= 0.54 or snare >= 0.56))

    # Keep restrained dimmer FX actually restrained. The previous logic could
    # label a cue as Soft Pulse / Alternate Whole while moving-head slots still
    # escalated to Beat Flash or faster modes inside chorus/build.
    if base_mode == "soft_pulse":
        if low_override or activity["breakdown"] or activity["calm"]:
            return "soft_pulse"
        if section in {"build", "chorus"} and not active_window:
            return "soft_pulse"
        if section == "drop" and not active_window:
            return "soft_pulse"
    if base_mode == "alternate_whole":
        if low_override:
            return "alternate_whole" if section in {"build", "chorus", "drop"} else "soft_pulse"
        if section in {"build", "chorus"} and not active_window:
            return "alternate_whole"
        if section == "drop" and not active_window:
            return "alternate_whole"

    if low_override:
        if section == "drop":
            if base_mode in {"snake", "snake_whole", "chase", "chase_whole", "beat_flash", "drop_blinder", "tremolo_dimmer", "double_hit", "gallop"}:
                return "alternate_whole" if activity["active"] else "breathing"
        elif section in {"build", "chorus"}:
            if base_mode in {"snake", "snake_whole", "chase", "chase_whole", "beat_flash", "strong_pulse", "ramp_up", "double_hit", "gallop", "pivot", "drop_blinder", "blackout_hit"}:
                return "soft_pulse" if section == "chorus" else "breathing"
    if section == "build":
        if activity["breakdown"]:
            return "soft_pulse"
        if activity["calm"] and not high_override and base_mode in {"snake", "snake_whole", "chase", "chase_whole", "beat_flash", "strong_pulse", "ramp_up", "alternate_whole", "double_hit", "gallop", "pivot"}:
            return "breathing" if early_build else "soft_pulse"
        if early_build and not peak_window and base_mode in {"snake", "snake_whole", "chase", "chase_whole", "beat_flash", "strong_pulse", "double_hit", "gallop"}:
            return "chase_whole" if active_window and (kick >= 0.44 or snare >= 0.44) else "soft_pulse"
        if base_mode in {"drop_blinder", "blackout_hit"}:
            return "beat_flash"
        if base_mode in {"alternate_whole", "pivot"}:
            return base_mode if active_window else "soft_pulse"
        if base_mode == "double_hit":
            return "double_hit" if surge_window or snare >= 0.48 else "alternate_whole"
        if base_mode == "gallop":
            return "gallop" if surge_window or hihat >= 0.44 else "alternate_whole"
        if base_mode == "snake":
            return "snake" if surge_window else "snake_whole"
        if base_mode == "snake_whole":
            return "snake" if surge_window else "snake_whole"
        if base_mode == "chase":
            return "chase" if surge_window else "chase_whole"
        if base_mode == "chase_whole":
            return "chase" if surge_window else "chase_whole"
        if active_window and base_mode in {"medium", "soft_pulse", "offbeat_flash", "strong_pulse", "ramp_up"}:
            if kick >= snare or hihat < 0.38:
                return "chase" if surge_window else "chase_whole"
            return "beat_flash"
        return "beat_flash" if peak_window else base_mode
    if section == "chorus":
        if activity["breakdown"]:
            return "breathing"
        if activity["calm"] and not high_override and base_mode in {"snake", "snake_whole", "chase", "chase_whole", "beat_flash", "strong_pulse", "alternate_whole", "double_hit", "gallop", "pivot"}:
            return "soft_pulse"
        if base_mode == "soft_pulse":
            if not active_window:
                return "soft_pulse"
            return "alternate_whole" if not surge_window else "chase_whole"
        if base_mode in {"alternate_whole", "pivot"}:
            return base_mode if active_window else "soft_pulse"
        if base_mode == "double_hit":
            return "double_hit" if peak_window or snare >= 0.46 else "alternate_whole"
        if base_mode == "gallop":
            return "gallop" if surge_window or hihat >= 0.48 else "pivot"
        if base_mode == "snake":
            return "snake" if surge_window else "snake_whole"
        if base_mode == "snake_whole":
            return "snake" if surge_window else "snake_whole"
        if base_mode == "chase":
            return "chase" if surge_window else "chase_whole"
        if base_mode == "chase_whole":
            return "chase" if surge_window else "chase_whole"
        if base_mode in {"medium", "soft_pulse", "offbeat_flash", "beat_flash", "strong_pulse"}:
            if peak_window:
                return "snake"
            if active_window:
                return "chase" if surge_window else "chase_whole"
            return "soft_pulse" if base_mode == "soft_pulse" else "beat_flash"
        return base_mode
    if section == "drop":
        if activity["breakdown"]:
            return "soft_pulse"
        if activity["calm"] and not high_override and base_mode in {"snake", "snake_whole", "chase", "chase_whole", "beat_flash", "tremolo_dimmer", "drop_blinder", "alternate_whole", "double_hit", "gallop", "pivot"}:
            return "breathing"
        if base_mode in {"drop_blinder", "blackout_hit"}:
            return base_mode
        if base_mode == "alternate_whole":
            return "alternate_whole"
        if base_mode == "pivot":
            return "pivot" if active_window else "alternate_whole"
        if base_mode == "double_hit":
            return "double_hit" if active_window else "alternate_whole"
        if base_mode == "gallop":
            return "gallop" if active_window else "alternate_whole"
        if peak_window:
            return "snake"
        if active_window:
            if kick >= 0.44:
                return "snake" if surge_window else "snake_whole"
            return "chase" if surge_window else "chase_whole"
        if base_mode in {"full_on", "tremolo_dimmer", "medium", "soft_pulse"}:
            return "beat_flash"
        return base_mode
    return "soft_pulse"


def _slot_pose(config, key):
    if not isinstance(config, dict):
        return None
    pose = config.get(key)
    if not isinstance(pose, dict):
        return None
    pan = pose.get("pan")
    tilt = pose.get("tilt")
    if pan is None or tilt is None:
        return None
    return {
        "pan": clamp_dmx(pan),
        "tilt": clamp_dmx(tilt),
    }


def _interpolate_pose(pose_a, pose_b, amount):
    if not pose_a or not pose_b:
        return None
    amount = clamp_unit(amount)
    return {
        "pan": clamp_dmx(round(pose_a["pan"] + (pose_b["pan"] - pose_a["pan"]) * amount)),
        "tilt": clamp_dmx(round(pose_a["tilt"] + (pose_b["tilt"] - pose_a["tilt"]) * amount)),
    }


def _interpolate_pose_path(left_pose, center_pose, right_pose, amount):
    amount = clamp_unit(amount)
    if left_pose and center_pose and right_pose:
        if amount <= 0.5:
            return _interpolate_pose(left_pose, center_pose, amount * 2.0)
        return _interpolate_pose(center_pose, right_pose, (amount - 0.5) * 2.0)
    if left_pose and right_pose:
        return _interpolate_pose(left_pose, right_pose, amount)
    if center_pose and left_pose:
        return _interpolate_pose(left_pose, center_pose, amount)
    if center_pose and right_pose:
        return _interpolate_pose(center_pose, right_pose, amount)
    return center_pose or left_pose or right_pose


def _interpolate_scalar_path(left_value, center_value, right_value, amount):
    amount = clamp_unit(amount)
    if left_value is not None and center_value is not None and right_value is not None:
        if amount <= 0.5:
            local = amount * 2.0
            return round(left_value + (center_value - left_value) * local)
        local = (amount - 0.5) * 2.0
        return round(center_value + (right_value - center_value) * local)
    if left_value is not None and right_value is not None:
        return round(left_value + (right_value - left_value) * amount)
    if center_value is not None and left_value is not None:
        return round(left_value + (center_value - left_value) * amount)
    if center_value is not None and right_value is not None:
        return round(center_value + (right_value - center_value) * amount)
    return center_value if center_value is not None else left_value if left_value is not None else right_value


def _fallback_pose_from_config(config):
    for key in ("pose_center", "pose_audience_center", "pose_ceiling_center", "pose_audience_left", "pose_audience_right"):
        pose = _slot_pose(config, key)
        if pose:
            return pose
    return {"pan": 128, "tilt": 128}


def _reference_mid(low_value, high_value, fallback):
    if low_value is not None and high_value is not None:
        return round((float(low_value) + float(high_value)) * 0.5)
    return fallback


def _safe_pose_tilt(pose, fallback, lower=0, upper=255):
    if pose and lower <= int(pose.get("tilt", -1)) <= upper:
        return int(pose["tilt"])
    return fallback


def _vertical_pose_ready(audience_pose, ceiling_pose, minimum_delta=12):
    if not audience_pose or not ceiling_pose:
        return False
    return abs(int(ceiling_pose["tilt"]) - int(audience_pose["tilt"])) >= minimum_delta


FULL_TILT_MOTION_PATTERNS = {
    "horizontal_sweep",
    "vertical_sweep",
    "diagonal_sweep",
    "reverse_diagonal_sweep",
    "circle",
    "figure_8",
    "random_searchlight",
    "snap_hits",
    "rising_sweep",
    "fan_wave",
    "crossing_beams",
    "mirror_bounce",
    "pulse_circle",
    "smooth_sweep",
    "arc_sweep",
    "tilt_sweep",
}


def _motion_profile_tilt_wave(pattern, profile, movement_scale, default_wave=0.0):
    try:
        base_wave = float(profile.get("tilt_wave", default_wave))
    except (TypeError, ValueError):
        base_wave = float(default_wave)
    if pattern == "horizontal_sweep" and abs(base_wave) < 1.0:
        base_wave = 18.0 + movement_scale * 14.0
    if pattern in {"smooth_sweep", "arc_sweep", "tilt_sweep"}:
        try:
            base_wave += movement_scale * float(profile.get("tilt_extra", 0.0))
        except (TypeError, ValueError):
            pass
    return abs(base_wave)


def _motion_profile_tilt_source_range(pattern, profile, movement_scale, default_tilt_center):
    if pattern not in FULL_TILT_MOTION_PATTERNS:
        return None
    if not bool(profile.get("use_full_tilt_range", False)):
        return None

    if pattern == "vertical_sweep":
        tilt_min = profile.get("tilt_min")
        tilt_max = profile.get("tilt_max")
        if tilt_min is not None and tilt_max is not None:
            return float(tilt_min), float(tilt_max)
        center = float(profile.get("tilt_center", default_tilt_center))
        wave = _motion_profile_tilt_wave(pattern, profile, movement_scale, 80.0)
        return center - wave, center + wave

    if pattern == "random_searchlight":
        return float(profile.get("tilt_min", 50)), float(profile.get("tilt_max", 210))

    if pattern == "rising_sweep":
        return float(profile.get("tilt_min", 145)), float(profile.get("tilt_max", 220))

    if pattern == "fan_wave":
        tilt_min = profile.get("fan_wave_tilt_min")
        tilt_max = profile.get("fan_wave_tilt_max")
        if tilt_min is not None and tilt_max is not None:
            return float(tilt_min), float(tilt_max)
        center = float(profile.get("tilt_center", default_tilt_center))
        wave = float(profile.get("fan_wave_tilt_wave", 40))
        return center - wave, center + wave

    if pattern == "crossing_beams":
        frames = list(profile.get("crossing_frames_4", [])) + list(profile.get("crossing_frames_2", []))
        tilts = [float(frame[1]) for frame in frames if isinstance(frame, (list, tuple)) and len(frame) >= 2]
        if tilts:
            return min(tilts), max(tilts)
        center = float(profile.get("tilt_center", default_tilt_center))
        return center, center

    if pattern == "snap_hits":
        positions = profile.get("snap_positions", [])
        tilts = [float(position[1]) for position in positions if isinstance(position, (list, tuple)) and len(position) >= 2]
        if tilts:
            return min(tilts), max(tilts)
        center = float(profile.get("tilt_center", default_tilt_center))
        return center, center

    if pattern in {"smooth_sweep", "arc_sweep", "tilt_sweep"}:
        default_centers = {
            "smooth_sweep": 152.0,
            "arc_sweep": 148.0,
            "tilt_sweep": 178.0,
        }
        default_waves = {
            "smooth_sweep": 10.0,
            "arc_sweep": 16.0,
            "tilt_sweep": 8.0,
        }
        center = float(profile.get("tilt_base", default_centers[pattern]))
        wave = _motion_profile_tilt_wave(pattern, profile, movement_scale, default_waves[pattern])
        return center - wave, center + wave

    default_waves = {
        "horizontal_sweep": 0.0,
        "diagonal_sweep": 88.0,
        "reverse_diagonal_sweep": 88.0,
        "circle": 38.0,
        "figure_8": 58.0,
        "mirror_bounce": 55.0,
        "pulse_circle": 35.0,
    }
    center = float(profile.get("tilt_center", default_tilt_center))
    wave = _motion_profile_tilt_wave(pattern, profile, movement_scale, default_waves.get(pattern, 0.0))
    return center - wave, center + wave


def _bias_normalized_tilt_toward_extremes(normalized, curve=0.72):
    centered = clamp_unit(float(normalized)) * 2.0 - 1.0
    biased = math.copysign(abs(centered) ** max(0.35, float(curve)), centered)
    return clamp_unit(0.5 + 0.5 * biased)


def _expand_motion_tilt_range(tilt_value, pattern, profile, movement_scale, default_tilt_center):
    source_range = _motion_profile_tilt_source_range(
        pattern,
        profile,
        movement_scale,
        default_tilt_center,
    )
    if not source_range:
        return clamp_dmx(int(round(float(tilt_value))))
    source_min, source_max = source_range
    span = float(source_max) - float(source_min)
    if span < 1.0:
        return clamp_dmx(int(round(float(tilt_value))))
    normalized = clamp_unit((float(tilt_value) - float(source_min)) / span)
    normalized = _bias_normalized_tilt_toward_extremes(
        normalized,
        curve=profile.get("full_tilt_curve", 0.72),
    )
    return clamp_dmx(round(normalized * 255.0))


def _motion_profile_uses_full_tilt_range(profile):
    pattern = str((profile or {}).get("pattern", "") or "")
    if pattern not in FULL_TILT_MOTION_PATTERNS:
        return False
    return bool((profile or {}).get("use_full_tilt_range", False))


def _full_tilt_motion_speed_cap(profile, section):
    if not _motion_profile_uses_full_tilt_range(profile):
        return None
    default_caps = {
        "intro": 56,
        "verse": 44,
        "build": 32,
        "chorus": 32,
        "drop": 24,
        "down": 40,
        "break": 48,
        "outro": 56,
        "unknown": 38,
    }
    try:
        override = profile.get("pan_tilt_speed_cap")
        if override is not None:
            return clamp_dmx(int(override))
    except (TypeError, ValueError):
        pass
    return int(default_caps.get(section, 38))


AUDIENCE_PAN_FOCUS_SOURCE_MIN = 30
AUDIENCE_PAN_FOCUS_SOURCE_MAX = 225
AUDIENCE_TILT_BRANCH_BLEND = 20


def _default_turn_audience_pan_limits(target_min, target_max):
    center = (float(target_min) + float(target_max)) / 2.0
    half_turn_span = 85.0
    direction = -1.0 if center >= 127.5 else 1.0
    turn_min = clamp_dmx(round(float(target_min) + direction * half_turn_span))
    turn_max = clamp_dmx(round(float(target_max) + direction * half_turn_span))
    if turn_max < turn_min:
        turn_min, turn_max = turn_max, turn_min
    return turn_min, turn_max


def _audience_pan_focus_limits(config):
    enabled = bool(config.get("_auto_show_audience_pan_focus_enabled", True))
    try:
        target_min = clamp_dmx(int(config.get("_auto_show_audience_pan_min", 135)))
    except (TypeError, ValueError):
        target_min = 135
    try:
        target_max = clamp_dmx(int(config.get("_auto_show_audience_pan_max", 205)))
    except (TypeError, ValueError):
        target_max = 205
    if target_max < target_min:
        target_min, target_max = target_max, target_min
    default_turn_min, default_turn_max = _default_turn_audience_pan_limits(
        target_min,
        target_max,
    )
    try:
        turn_min = clamp_dmx(
            int(config.get("_auto_show_audience_turn_pan_min", default_turn_min))
        )
    except (TypeError, ValueError):
        turn_min = default_turn_min
    try:
        turn_max = clamp_dmx(
            int(config.get("_auto_show_audience_turn_pan_max", default_turn_max))
        )
    except (TypeError, ValueError):
        turn_max = default_turn_max
    if turn_max < turn_min:
        turn_min, turn_max = turn_max, turn_min
    try:
        tilt_split = clamp_dmx(int(config.get("_auto_show_audience_tilt_split", 127)))
    except (TypeError, ValueError):
        tilt_split = 127
    return enabled, target_min, target_max, turn_min, turn_max, tilt_split


def _focused_audience_pan_value(pan_value, tilt_value=None, config=None):
    try:
        pan_value = float(pan_value)
    except (TypeError, ValueError):
        return clamp_dmx(170)
    try:
        tilt_value = float(tilt_value)
    except (TypeError, ValueError):
        tilt_value = 170.0
    (
        enabled,
        target_min,
        target_max,
        turn_min,
        turn_max,
        tilt_split,
    ) = _audience_pan_focus_limits(config or {})
    if not enabled:
        return clamp_dmx(round(pan_value))
    source_min = float(AUDIENCE_PAN_FOCUS_SOURCE_MIN)
    source_max = float(AUDIENCE_PAN_FOCUS_SOURCE_MAX)
    if source_max <= source_min:
        return clamp_dmx(round(target_min))
    normalized = (max(source_min, min(source_max, pan_value)) - source_min) / (source_max - source_min)
    front_pan = float(target_min) + normalized * (float(target_max) - float(target_min))
    turn_pan = float(turn_min) + normalized * (float(turn_max) - float(turn_min))
    blend_lower = float(tilt_split) - AUDIENCE_TILT_BRANCH_BLEND
    blend_upper = float(tilt_split) + AUDIENCE_TILT_BRANCH_BLEND
    if blend_upper <= blend_lower:
        front_mix = 1.0 if tilt_value >= float(tilt_split) else 0.0
    else:
        front_mix = clamp_unit((tilt_value - blend_lower) / (blend_upper - blend_lower))
    focused = turn_pan + (front_pan - turn_pan) * front_mix
    return clamp_dmx(round(focused))


def _apply_audience_pan_focus_to_motion(motion, slot_context, config=None):
    if not motion or not slot_context:
        return motion
    if str(slot_context.get("role", "")) != "moving":
        return motion
    focused = dict(motion)
    focused["pan"] = _focused_audience_pan_value(
        focused.get("pan", 170),
        tilt_value=focused.get("tilt", 170),
        config=config,
    )
    return focused


def styled_phrase_motion(phrase, beat_value, family, slot_context, movement_scale, config=None):
    profile = auto_show_motion_profile(family)
    slot_context = slot_context or {}
    role = str(slot_context.get("role", ""))
    group_index = int(slot_context.get("group_index", 0))
    group_centered = float(slot_context.get("group_centered", slot_context.get("centered", 0.0)))
    group_edge_bias = float(slot_context.get("group_edge_bias", slot_context.get("edge_bias", 0.0)))
    group_center_bias = float(slot_context.get("group_center_bias", slot_context.get("center_bias", 1.0)))
    group_alternate = float(slot_context.get("group_alternate", slot_context.get("alternate", 1.0)))
    member_index = int(slot_context.get("member_index", 0))
    role_index = int(slot_context.get("role_index", member_index))
    member_centered = float(slot_context.get("member_centered", 0.0))
    member_alternate = float(slot_context.get("member_alternate", slot_context.get("alternate", 1.0)))
    member_count = max(1, int(slot_context.get("member_count", 1)))
    role_count = max(1, int(slot_context.get("role_count", member_count)))
    beat_value = float(beat_value or 0.0)
    movement_scale = float(movement_scale or 0.0)
    pattern = profile.get("pattern", "base")
    use_taught_poses = bool(profile.get("use_taught_poses", False))
    span_index = role_index if role == "moving" and role_count >= 4 else member_index
    span_count = role_count if role == "moving" and role_count >= 4 else member_count

    adjusted_beat = beat_value * profile["phase_scale"]
    pose_center = _slot_pose(config, "pose_center") or _slot_pose(config, "pose_audience_center")
    pose_audience_left = _slot_pose(config, "pose_audience_left")
    pose_audience_center = _slot_pose(config, "pose_audience_center") or pose_center
    pose_audience_right = _slot_pose(config, "pose_audience_right")
    pose_ceiling_center = _slot_pose(config, "pose_ceiling_center")
    fallback_pose = _fallback_pose_from_config(config)
    raw_pan_left = config.get("pan_left_value") if isinstance(config, dict) else None
    raw_pan_right = config.get("pan_right_value") if isinstance(config, dict) else None
    raw_tilt_back = config.get("tilt_back_value") if isinstance(config, dict) else None
    raw_tilt_front = config.get("tilt_front_value") if isinstance(config, dict) else None
    raw_pan_center = None
    if pose_center:
        raw_pan_center = pose_center["pan"]
    elif pose_audience_center:
        raw_pan_center = pose_audience_center["pan"]
    raw_tilt_center = None
    if pose_center:
        raw_tilt_center = pose_center["tilt"]
    elif pose_audience_center:
        raw_tilt_center = pose_audience_center["tilt"]
    raw_vertical_path_available = (
        raw_tilt_back is not None
        and raw_tilt_front is not None
        and raw_tilt_center is not None
    )
    if use_taught_poses:
        default_pan_center = raw_pan_center if raw_pan_center is not None else _reference_mid(raw_pan_left, raw_pan_right, 128)
        default_tilt_center = _safe_pose_tilt(
            pose_audience_center or pose_center,
            int(profile.get("tilt_center", 128)),
        )
    else:
        default_pan_center = int(profile.get("pan_center", 128))
        default_tilt_center = int(profile.get("tilt_center", 128))
    vertical_pose_available = _vertical_pose_ready(pose_audience_center or pose_center, pose_ceiling_center)
    motion = None
    if pattern == "base":
        motion = phrase_motion(phrase, adjusted_beat)
    elif pattern == "center_hold":
        if use_taught_poses and (pose_center or fallback_pose):
            learned = pose_center or fallback_pose
            motion = {
                "pan": learned["pan"],
                "tilt": _safe_pose_tilt(learned, default_tilt_center),
                "pan_tilt_speed": 0,
            }
        else:
            motion = {
                "pan": int(profile.get("pan_center", 128)),
                "tilt": int(profile.get("tilt_center", 128)),
                "pan_tilt_speed": 0,
            }
    elif pattern == "static_positions":
        if span_count >= 4:
            positions = profile.get("positions_4", [60, 105, 150, 195])
        elif span_count == 2:
            positions = profile.get("positions_2", [105, 150])
        else:
            positions = [int(profile.get("pan_center", 128))]
        pan_value = positions[min(len(positions) - 1, span_index if len(positions) > 1 else 0)]
        motion = {
            "pan": clamp_dmx(pan_value),
            "tilt": clamp_dmx(int(profile.get("tilt_static", profile.get("tilt_center", 180)))),
            "pan_tilt_speed": 0,
        }
    elif pattern == "horizontal_sweep":
        sweep_phase = adjusted_beat / 24.0
        tilt_phase = sweep_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        profile_tilt_center = int(profile.get("tilt_center", default_tilt_center))
        profile_tilt_wave = _motion_profile_tilt_wave(
            pattern,
            profile,
            movement_scale,
            0.0,
        )
        base_tilt_center = _safe_pose_tilt(pose_audience_center or pose_center, profile_tilt_center)
        if use_taught_poses and pose_audience_left and (pose_audience_center or pose_center or pose_audience_right):
            amount = 0.5 + 0.5 * wave_sine(sweep_phase)
            sweep_pose = _interpolate_pose_path(
                pose_audience_left,
                pose_audience_center or pose_center,
                pose_audience_right,
                amount,
            )
            tilt_value = clamp_motion(base_tilt_center, profile_tilt_wave, wave_sine(tilt_phase))
            if family == "ceiling_sweep" and vertical_pose_available:
                tilt_wave = wave_sine(tilt_phase)
                ceiling_wave = profile.get("tilt_wave", 0)
                tilt_value = clamp_dmx(round(pose_ceiling_center["tilt"] + tilt_wave * ceiling_wave))
            motion = {
                "pan": sweep_pose["pan"],
                "tilt": tilt_value,
                "pan_tilt_speed": 0,
            }
        else:
            motion = {
                "pan": clamp_motion(
                    profile.get("pan_center", 128),
                    profile.get("pan_wave", 88),
                    wave_sine(sweep_phase),
                ),
                "tilt": clamp_motion(
                    profile_tilt_center,
                    profile_tilt_wave,
                    wave_sine(tilt_phase),
                ),
                "pan_tilt_speed": 0,
            }
        if use_taught_poses and raw_pan_left is not None and raw_pan_right is not None:
            amount = 0.5 + 0.5 * wave_sine(sweep_phase)
            pan_value = _interpolate_scalar_path(raw_pan_left, raw_pan_center, raw_pan_right, amount)
            if pan_value is not None:
                motion["pan"] = clamp_dmx(pan_value)
    elif pattern == "vertical_sweep":
        sweep_phase = adjusted_beat / 24.0
        tilt_phase = sweep_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        if use_taught_poses and vertical_pose_available:
            amount = 0.5 + 0.5 * wave_sine(tilt_phase)
            vertical_pose = _interpolate_pose(pose_audience_center or pose_center, pose_ceiling_center, amount)
            motion = {
                "pan": (pose_audience_center or pose_center)["pan"],
                "tilt": vertical_pose["tilt"],
                "pan_tilt_speed": 0,
            }
        else:
            tilt_min = profile.get("tilt_min")
            tilt_max = profile.get("tilt_max")
            if tilt_min is not None and tilt_max is not None:
                tilt_amount = 0.5 + 0.5 * wave_sine(tilt_phase)
                tilt_value = round(float(tilt_min) + (float(tilt_max) - float(tilt_min)) * tilt_amount)
            else:
                tilt_value = clamp_motion(
                    int(profile.get("tilt_center", default_tilt_center)),
                    profile.get("tilt_wave", 80),
                    wave_sine(tilt_phase),
                )
            motion = {
                "pan": clamp_motion(
                    default_pan_center,
                    profile.get("pan_wave", 0),
                    wave_sine(sweep_phase / 3.0),
                ),
                "tilt": clamp_dmx(tilt_value),
                "pan_tilt_speed": 0,
            }
        if use_taught_poses and raw_vertical_path_available:
            amount = 0.5 + 0.5 * wave_sine(tilt_phase)
            tilt_value = _interpolate_scalar_path(raw_tilt_back, raw_tilt_center, raw_tilt_front, amount)
            if tilt_value is not None:
                motion["tilt"] = clamp_dmx(tilt_value)
            if raw_pan_center is not None:
                motion["pan"] = clamp_dmx(raw_pan_center)
    elif pattern == "diagonal_sweep":
        sweep_phase = adjusted_beat / 24.0
        tilt_phase = sweep_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        diagonal_wave = wave_sine(sweep_phase)
        motion = {
            "pan": clamp_motion(
                profile.get("pan_center", 128),
                profile.get("pan_wave", 88),
                diagonal_wave,
            ),
            "tilt": clamp_motion(
                profile.get("tilt_center", 128),
                profile.get("tilt_wave", 88),
                wave_sine(tilt_phase),
            ),
            "pan_tilt_speed": 0,
        }
    elif pattern == "reverse_diagonal_sweep":
        sweep_phase = adjusted_beat / 24.0
        tilt_phase = sweep_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        diagonal_wave = wave_sine(sweep_phase)
        motion = {
            "pan": clamp_motion(
                profile.get("pan_center", 128),
                profile.get("pan_wave", 88),
                -diagonal_wave,
            ),
            "tilt": clamp_motion(
                profile.get("tilt_center", 128),
                profile.get("tilt_wave", 88),
                wave_sine(tilt_phase),
            ),
            "pan_tilt_speed": 0,
        }
    elif pattern == "circle":
        circle_phase = adjusted_beat / 28.0
        tilt_phase = circle_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        pan_center = profile.get("pan_center", 128)
        pan_wave = profile.get("pan_wave", 58)
        tilt_center = profile.get("tilt_center", 128)
        tilt_wave = profile.get("tilt_wave", 38)
        motion = {
            "pan": clamp_motion(pan_center, pan_wave, wave_sine(circle_phase)),
            "tilt": clamp_motion(tilt_center, tilt_wave, wave_cosine(tilt_phase)),
            "pan_tilt_speed": 0,
        }
    elif pattern == "figure_8":
        fig_phase = adjusted_beat / 28.0
        tilt_phase = fig_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        motion = {
            "pan": clamp_motion(
                profile.get("pan_center", 128),
                profile.get("pan_wave", 68),
                wave_sine(fig_phase),
            ),
            "tilt": clamp_motion(
                profile.get("tilt_center", 128),
                profile.get("tilt_wave", 58),
                wave_sine(tilt_phase * 2.0),
            ),
            "pan_tilt_speed": 0,
        }
    elif pattern == "random_searchlight":
        window_beats = max(1.0, float(profile.get("window_beats", 8.0)))
        window_index = int(math.floor(beat_value / window_beats))
        seed_base = f"{family}|{window_index}|{group_index}|{member_count}|{group_centered:.3f}"
        pan_seed = stable_hash(seed_base + "|pan")
        tilt_seed = stable_hash(seed_base + "|tilt")
        pan_min = int(profile.get("pan_min", 30))
        pan_max = int(profile.get("pan_max", 225))
        tilt_min = int(profile.get("tilt_min", 50))
        tilt_max = int(profile.get("tilt_max", 210))
        pan_value = pan_min + ((pan_seed % 1000) / 999.0) * max(1, pan_max - pan_min)
        tilt_value = tilt_min + ((tilt_seed % 1000) / 999.0) * max(1, tilt_max - tilt_min)
        motion = {
            "pan": clamp_dmx(round(pan_value)),
            "tilt": clamp_dmx(round(tilt_value)),
            "pan_tilt_speed": 0,
        }
    elif pattern == "snap_hits":
        positions = profile.get(
            "snap_positions",
            [
                (40, 80),
                (216, 80),
                (216, 190),
                (40, 190),
                (128, 128),
            ],
        )
        step = int(math.floor(beat_value)) % len(positions)
        pan_value, tilt_value = positions[step]
        motion = {
            "pan": pan_value,
            "tilt": tilt_value,
            "pan_tilt_speed": 0,
            "rgbw": (255, 255, 255, 255),
        }
    elif pattern == "blinder_flash":
        flash_phase = beat_value % 1.0
        flash_open = flash_phase < 0.18
        motion = {
            "pan": 128,
            "tilt": int(profile.get("tilt_center", 170)),
            "pan_tilt_speed": 0,
            "dimmer": 255 if flash_open else 0,
            "rgbw": (255, 255, 255, 255),
        }
    elif pattern == "hold_pulse":
        pulse_phase = (0.5 + 0.5 * wave_sine(beat_value * float(profile.get("pulse_phase_scale", 0.5)))) if beat_value is not None else 0.5
        dimmer_min = int(profile.get("dimmer_min", 80))
        dimmer_max = int(profile.get("dimmer_max", 255))
        motion = {
            "pan": int(profile.get("pan_center", 128)),
            "tilt": int(profile.get("tilt_center", default_tilt_center)),
            "pan_tilt_speed": 0,
            "dimmer": clamp_dmx(round(dimmer_min + (dimmer_max - dimmer_min) * pulse_phase)),
        }
    elif pattern == "blackout_hit":
        hit_phase = beat_value % 1.0
        blackout_open = hit_phase < float(profile.get("blackout_window", 0.14))
        dimmer_min = int(profile.get("dimmer_min", 0))
        dimmer_max = int(profile.get("dimmer_max", 255))
        motion = {
            "pan": int(profile.get("pan_center", 128)),
            "tilt": int(profile.get("tilt_center", default_tilt_center)),
            "pan_tilt_speed": 0,
            "dimmer": dimmer_min if blackout_open else dimmer_max,
        }
    elif pattern == "rising_sweep":
        sweep_phase = adjusted_beat / 24.0
        tilt_amount = 0.5 + 0.5 * wave_triangle(sweep_phase / 1.8)
        tilt_min = int(profile.get("tilt_min", 145))
        tilt_max = int(profile.get("tilt_max", 220))
        dimmer_min = int(profile.get("dimmer_min", 120))
        dimmer_max = int(profile.get("dimmer_max", 255))
        motion = {
            "pan": clamp_motion(
                profile.get("pan_center", 128),
                profile.get("pan_wave", 88),
                wave_sine(sweep_phase),
            ),
            "tilt": clamp_dmx(round(tilt_min + (tilt_max - tilt_min) * tilt_amount)),
            "pan_tilt_speed": 0,
            "dimmer": clamp_dmx(round(dimmer_min + (dimmer_max - dimmer_min) * tilt_amount)),
        }
    elif pattern == "fan_morph":
        morph_phase = 0.5 + 0.5 * wave_sine(adjusted_beat / 20.0)
        if morph_phase <= 0.5:
            amount = morph_phase * 2.0
            positions_a = profile.get("positions_start_4", [115, 125, 135, 145]) if span_count >= 4 else profile.get("positions_start_2", [122, 134])
            positions_b = profile.get("positions_mid_4", [90, 115, 140, 165]) if span_count >= 4 else profile.get("positions_mid_2", [112, 144])
        else:
            amount = (morph_phase - 0.5) * 2.0
            positions_a = profile.get("positions_mid_4", [90, 115, 140, 165]) if span_count >= 4 else profile.get("positions_mid_2", [112, 144])
            positions_b = profile.get("positions_end_4", [60, 105, 150, 195]) if span_count >= 4 else profile.get("positions_end_2", [105, 150])
        pan_a = positions_a[min(len(positions_a) - 1, span_index if len(positions_a) > 1 else 0)]
        pan_b = positions_b[min(len(positions_b) - 1, span_index if len(positions_b) > 1 else 0)]
        dimmer_min = int(profile.get("dimmer_min", 150))
        dimmer_max = int(profile.get("dimmer_max", 255))
        motion = {
            "pan": clamp_dmx(round(pan_a + (pan_b - pan_a) * amount)),
            "tilt": clamp_dmx(int(profile.get("tilt_static", 180))),
            "pan_tilt_speed": 0,
            "dimmer": clamp_dmx(round(dimmer_min + (dimmer_max - dimmer_min) * morph_phase)),
        }
    elif pattern == "fan_open":
        fan_anchor = member_centered if span_count > 1 else group_centered
        fan_width = profile.get("fan_width", 88)
        if use_taught_poses and pose_audience_left and (pose_audience_center or pose_center or pose_audience_right):
            center_tilt = _safe_pose_tilt(pose_audience_center or pose_center, default_tilt_center)
            if span_count == 2:
                fraction = [0.35, 0.65][min(1, span_index)]
            else:
                fraction = 0.5 if span_count <= 1 else span_index / max(1, span_count - 1)
            fan_pose = _interpolate_pose_path(
                pose_audience_left,
                pose_audience_center or pose_center,
                pose_audience_right,
                fraction,
            )
            motion = {
                "pan": fan_pose["pan"],
                "tilt": center_tilt,
                "pan_tilt_speed": 0,
            }
        elif span_count >= 4:
            fan_positions = profile.get("fan_positions_4", [60, 105, 150, 195])
            fan_position = fan_positions[min(len(fan_positions) - 1, span_index)]
            motion = {
                "pan": fan_position,
                "tilt": int(profile.get("tilt_center", default_tilt_center)),
                "pan_tilt_speed": 0,
            }
        elif span_count == 2:
            fan_positions = profile.get("fan_positions_2", [105, 150])
            motion = {
                "pan": fan_positions[min(len(fan_positions) - 1, span_index)],
                "tilt": int(profile.get("tilt_center", default_tilt_center)),
                "pan_tilt_speed": 0,
            }
        else:
            motion = {
                "pan": clamp_motion(128, fan_width * 0.5, fan_anchor * 2.0),
                "tilt": default_tilt_center,
                "pan_tilt_speed": 0,
            }
        if use_taught_poses and raw_pan_left is not None and raw_pan_right is not None:
            if span_count == 2:
                fraction = [0.35, 0.65][min(1, span_index)]
            else:
                fraction = 0.5 if span_count <= 1 else span_index / max(1, span_count - 1)
            pan_value = _interpolate_scalar_path(raw_pan_left, raw_pan_center, raw_pan_right, fraction)
            if pan_value is not None:
                motion["pan"] = clamp_dmx(pan_value)
            motion["tilt"] = clamp_dmx(default_tilt_center)
    elif pattern == "fan_wave":
        fan_phase = adjusted_beat / 24.0
        tilt_phase_scale = _profile_tilt_phase_scale(profile, 1.0)
        fan_anchor = member_centered if span_count > 1 else group_centered
        fan_width = profile.get("fan_width", 92)
        fan_tilt_min = profile.get("fan_wave_tilt_min")
        fan_tilt_max = profile.get("fan_wave_tilt_max")
        fan_tilt_wave = wave_sine(
            (fan_phase * tilt_phase_scale) / 1.8
            + fan_anchor * 0.12
            + _profile_tilt_phase_offset(profile, 0.0)
        )
        if use_taught_poses and pose_audience_left and (pose_audience_center or pose_center or pose_audience_right):
            if span_count == 2:
                fraction = [0.35, 0.65][min(1, span_index)]
            else:
                fraction = 0.5 if span_count <= 1 else span_index / max(1, span_count - 1)
            base_pose = _interpolate_pose_path(
                pose_audience_left,
                pose_audience_center or pose_center,
                pose_audience_right,
                fraction,
            )
            if vertical_pose_available:
                low_tilt = int((pose_audience_center or pose_center)["tilt"])
                high_tilt = int(pose_ceiling_center["tilt"])
                tilt_center = round((low_tilt + high_tilt) * 0.5)
                tilt_wave = max(8, abs(high_tilt - low_tilt) // 2)
            else:
                tilt_center = default_tilt_center
                tilt_wave = 24
            if fan_tilt_min is not None and fan_tilt_max is not None:
                tilt_value = round(float(fan_tilt_min) + (float(fan_tilt_max) - float(fan_tilt_min)) * (0.5 + 0.5 * fan_tilt_wave))
            else:
                tilt_value = clamp_motion(
                    tilt_center,
                    tilt_wave,
                    fan_tilt_wave,
                )
            motion = {
                "pan": clamp_motion(
                    base_pose["pan"],
                    10 + movement_scale * 8,
                    wave_sine(fan_phase),
                ),
                "tilt": clamp_dmx(tilt_value),
                "pan_tilt_speed": 0,
            }
        elif span_count >= 4:
            pan_positions = profile.get("fan_wave_pan_positions_4", [70, 110, 150, 190])
            pan_center = pan_positions[min(len(pan_positions) - 1, span_index)]
            if fan_tilt_min is not None and fan_tilt_max is not None:
                tilt_value = round(float(fan_tilt_min) + (float(fan_tilt_max) - float(fan_tilt_min)) * (0.5 + 0.5 * fan_tilt_wave))
            else:
                tilt_centers = profile.get("fan_wave_tilt_centers_4", [130, 150, 130, 150])
                tilt_center = tilt_centers[min(len(tilt_centers) - 1, span_index)]
                tilt_value = clamp_motion(
                    tilt_center,
                    int(profile.get("fan_wave_tilt_wave", 40)),
                    fan_tilt_wave,
                )
            motion = {
                "pan": clamp_motion(
                    pan_center,
                    10 + movement_scale * 8,
                    wave_sine(fan_phase),
                ),
                "tilt": clamp_dmx(tilt_value),
                "pan_tilt_speed": 0,
            }
        elif span_count == 2:
            pan_positions = profile.get("fan_wave_pan_positions_2", [110, 150])
            pan_center = pan_positions[min(len(pan_positions) - 1, span_index)]
            if fan_tilt_min is not None and fan_tilt_max is not None:
                tilt_value = round(float(fan_tilt_min) + (float(fan_tilt_max) - float(fan_tilt_min)) * (0.5 + 0.5 * fan_tilt_wave))
            else:
                tilt_centers = profile.get("fan_wave_tilt_centers_2", [130, 150])
                tilt_center = tilt_centers[min(len(tilt_centers) - 1, span_index)]
                tilt_value = clamp_motion(
                    tilt_center,
                    int(profile.get("fan_wave_tilt_wave", 40)),
                    fan_tilt_wave,
                )
            motion = {
                "pan": clamp_motion(
                    pan_center,
                    8 + movement_scale * 6,
                    wave_sine(fan_phase),
                ),
                "tilt": clamp_dmx(tilt_value),
                "pan_tilt_speed": 0,
            }
        else:
            if fan_tilt_min is not None and fan_tilt_max is not None:
                tilt_value = round(float(fan_tilt_min) + (float(fan_tilt_max) - float(fan_tilt_min)) * (0.5 + 0.5 * fan_tilt_wave))
            else:
                tilt_value = clamp_motion(
                    216,
                    30,
                    fan_tilt_wave,
                )
            motion = {
                "pan": clamp_motion(
                    128 + fan_anchor * fan_width * 0.45,
                    18 + movement_scale * 14,
                    wave_sine(fan_phase),
                ),
                "tilt": clamp_dmx(tilt_value),
                "pan_tilt_speed": 0,
            }
        if use_taught_poses and raw_pan_left is not None and raw_pan_right is not None:
            if span_count == 2:
                fraction = [0.35, 0.65][min(1, span_index)]
            else:
                fraction = 0.5 if span_count <= 1 else span_index / max(1, span_count - 1)
            base_pan = _interpolate_scalar_path(raw_pan_left, raw_pan_center, raw_pan_right, fraction)
            if base_pan is not None:
                motion["pan"] = clamp_dmx(round(base_pan + wave_sine(fan_phase) * (10 + movement_scale * 8)))
            if raw_vertical_path_available:
                low_tilt = default_tilt_center
                high_tilt = pose_ceiling_center["tilt"] if pose_ceiling_center else raw_tilt_back
                if fan_tilt_min is not None and fan_tilt_max is not None:
                    motion["tilt"] = clamp_dmx(
                        round(float(fan_tilt_min) + (float(fan_tilt_max) - float(fan_tilt_min)) * (0.5 + 0.5 * fan_tilt_wave))
                    )
                else:
                    tilt_center = round((low_tilt + high_tilt) * 0.5)
                    tilt_wave = max(8, abs(high_tilt - low_tilt) // 2)
                    motion["tilt"] = clamp_motion(
                        tilt_center,
                        tilt_wave,
                        fan_tilt_wave,
                    )
    elif pattern == "crossing_beams":
        if use_taught_poses and pose_audience_left and (pose_audience_center or pose_center or pose_audience_right):
            fractions_a = [0.0, 0.28, 0.72, 1.0]
            fractions_b = list(reversed(fractions_a))
            fractions = fractions_a if (int(math.floor(beat_value / 4.0)) % 2 == 0) else fractions_b
            if span_count == 2:
                pair_fractions = [0.28, 0.72] if (int(math.floor(beat_value / 4.0)) % 2 == 0) else [0.72, 0.28]
                fraction = pair_fractions[min(1, span_index)]
            else:
                fraction = fractions[min(len(fractions) - 1, span_index)]
            cross_pose = _interpolate_pose_path(
                pose_audience_left,
                pose_audience_center or pose_center,
                pose_audience_right,
                fraction,
            )
            pan_value = cross_pose["pan"]
            tilt_value = _safe_pose_tilt(pose_audience_center or pose_center, 214)
        else:
            state_a = profile.get("crossing_frames_4", [(60, 150), (100, 150), (156, 150), (196, 150)])
            state_b = list(reversed(state_a))
            frame = state_a if (int(math.floor(beat_value / 4.0)) % 2 == 0) else state_b
            if span_count == 2:
                compact_frame = profile.get("crossing_frames_2", [(100, 150), (156, 150)])
                compact_frame = compact_frame if (int(math.floor(beat_value / 4.0)) % 2 == 0) else list(reversed(compact_frame))
                pan_value, tilt_value = compact_frame[min(len(compact_frame) - 1, span_index)]
            else:
                pan_value, tilt_value = frame[min(len(frame) - 1, span_index)]
        motion = {
            "pan": pan_value,
            "tilt": tilt_value,
            "pan_tilt_speed": 0,
            "rgbw": (255, 255, 255, 255),
        }
        if use_taught_poses and raw_pan_left is not None and raw_pan_right is not None:
            fractions_a = [0.0, 0.28, 0.72, 1.0]
            fractions_b = list(reversed(fractions_a))
            fractions = fractions_a if (int(math.floor(beat_value / 4.0)) % 2 == 0) else fractions_b
            if span_count == 2:
                pair_fractions = [0.28, 0.72] if (int(math.floor(beat_value / 4.0)) % 2 == 0) else [0.72, 0.28]
                fraction = pair_fractions[min(1, span_index)]
            else:
                fraction = fractions[min(len(fractions) - 1, span_index)]
            raw_pan = _interpolate_scalar_path(raw_pan_left, raw_pan_center, raw_pan_right, fraction)
            if raw_pan is not None:
                motion["pan"] = clamp_dmx(raw_pan)
            motion["tilt"] = clamp_dmx(default_tilt_center)
    elif pattern == "mirror_bounce":
        bounce_phase = adjusted_beat / 16.0
        motion = {
            "pan": clamp_motion(
                profile.get("pan_center", 128),
                profile.get("pan_wave", 68),
                wave_triangle(bounce_phase),
            ),
            "tilt": clamp_motion(
                profile.get("tilt_center", 125),
                profile.get("tilt_wave", 55),
                wave_triangle(
                    (
                        bounce_phase * _profile_tilt_phase_scale(profile, 1.0)
                        + _profile_tilt_phase_offset(profile, 0.0)
                    )
                    / 1.9
                ),
            ),
            "pan_tilt_speed": 0,
        }
    elif pattern == "pulse_circle":
        circle_phase = adjusted_beat / 28.0
        tilt_phase = circle_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        dimmer_phase = 0.5 + 0.5 * wave_sine(circle_phase)
        dimmer_min = int(profile.get("dimmer_min", 80))
        dimmer_max = int(profile.get("dimmer_max", 255))
        motion = {
            "pan": clamp_motion(
                profile.get("pan_center", 128),
                profile.get("pan_wave", 55),
                wave_sine(circle_phase),
            ),
            "tilt": clamp_motion(
                profile.get("tilt_center", 128),
                profile.get("tilt_wave", 35),
                wave_cosine(tilt_phase),
            ),
            "pan_tilt_speed": 0,
            "dimmer": clamp_dmx(round(dimmer_min + dimmer_phase * (dimmer_max - dimmer_min))),
            "rgbw": tuple(profile.get("rgbw", (0, 80, 255, 80))),
        }
    elif pattern == "smooth_sweep":
        sweep_phase = adjusted_beat / 28.0
        tilt_phase = sweep_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        pan_amount = profile.get("pan_base", 32) + movement_scale * profile.get("pan_extra", 18)
        tilt_base = profile.get("tilt_base", 152)
        tilt_wave = profile.get("tilt_wave", 10) + movement_scale * profile.get("tilt_extra", 0)
        motion = {
            "pan": clamp_motion(127, pan_amount, wave_sine(sweep_phase)),
            "tilt": clamp_motion(
                tilt_base,
                tilt_wave,
                wave_sine(tilt_phase / 2.0),
            ),
            "pan_tilt_speed": 0,
        }
    elif pattern == "arc_sweep":
        sweep_phase = adjusted_beat / 28.0
        tilt_phase = sweep_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        pan_amount = profile.get("pan_base", 36) + movement_scale * profile.get("pan_extra", 20)
        tilt_base = profile.get("tilt_base", 148)
        tilt_wave = profile.get("tilt_wave", 16) + movement_scale * profile.get("tilt_extra", 0)
        motion = {
            "pan": clamp_motion(127, pan_amount, wave_sine(sweep_phase)),
            "tilt": clamp_motion(
                tilt_base,
                tilt_wave,
                wave_triangle(tilt_phase / 1.8),
            ),
            "pan_tilt_speed": 0,
        }
    elif pattern == "tilt_sweep":
        sweep_phase = adjusted_beat / 32.0
        tilt_phase = sweep_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        pan_amount = profile.get("pan_base", 26) + movement_scale * profile.get("pan_extra", 14)
        tilt_base = profile.get("tilt_base", 178)
        tilt_wave = profile.get("tilt_wave", 8) + movement_scale * profile.get("tilt_extra", 0)
        motion = {
            "pan": clamp_motion(127, pan_amount, wave_sine(sweep_phase)),
            "tilt": clamp_motion(
                tilt_base,
                tilt_wave,
                wave_sine(tilt_phase / 2.4),
            ),
            "pan_tilt_speed": 0,
        }
    elif pattern == "pendulum":
        motion = {
            "pan": clamp_motion(127, 42 + movement_scale * 54, wave_triangle(adjusted_beat / 2.0)),
            "tilt": clamp_motion(150, 12 + movement_scale * 18, wave_sine(adjusted_beat / 5.0 + group_centered * 0.6)),
            "pan_tilt_speed": 0,
        }
    elif pattern == "ripple":
        motion = {
            "pan": clamp_motion(127, 46 + movement_scale * 44, wave_sine(adjusted_beat / 2.4 + group_index * 0.35)),
            "tilt": clamp_motion(142, 16 + movement_scale * 18, wave_triangle(adjusted_beat / 3.8 + group_index * 0.22)),
            "pan_tilt_speed": 0,
        }
    elif pattern == "helix":
        motion = {
            "pan": clamp_motion(127, 52 + movement_scale * 42, wave_sine(adjusted_beat / 1.8 + group_centered * 0.4)),
            "tilt": clamp_motion(132, 24 + movement_scale * 24, wave_sine(adjusted_beat / 1.8 + 0.25 + group_index * 0.18)),
            "pan_tilt_speed": 0,
        }
    elif pattern == "criss_cross":
        motion = {
            "pan": clamp_motion(127, 62 + movement_scale * 34, wave_triangle(adjusted_beat / 1.4 + group_index * 0.12)),
            "tilt": clamp_motion(136, 16 + movement_scale * 16, wave_square(adjusted_beat / 2.0 + group_alternate * 0.1)),
            "pan_tilt_speed": 0,
        }
    elif pattern == "ladder":
        step_phase = int((adjusted_beat * 0.75 + group_index * 0.25) % 4)
        pan_steps = [72, 112, 148, 188]
        tilt_steps = [156, 142, 128, 116]
        motion = {
            "pan": clamp_dmx(pan_steps[step_phase]),
            "tilt": clamp_dmx(tilt_steps[(step_phase + group_index) % 4]),
            "pan_tilt_speed": 0,
        }
    if not motion:
        return None

    pan = float(motion["pan"])
    tilt = float(motion["tilt"])
    if profile["mirror"] and group_alternate < 0:
        pan = 254.0 - pan

    spread = (18.0 + movement_scale * 28.0) * profile["spread"]
    pan += group_centered * spread

    phase = beat_value * math.tau * profile["phase_scale"] * 0.18
    pan += math.sin(phase) * profile["orbit_pan"] * (0.45 + movement_scale)
    tilt += math.cos(phase * 0.72 + group_centered * 0.20) * profile["orbit_tilt"] * (0.35 + movement_scale)
    tilt += group_center_bias * profile["tilt_lift"]
    tilt -= group_edge_bias * profile["edge_drop"] * (0.60 + movement_scale)

    if profile["snap"]:
        pan += wave_square(beat_value * 0.5 + group_index * 0.17) * profile["snap"] * (
            0.35 + movement_scale
        )

    result = {
        "pan": clamp_dmx(round(pan)),
        "tilt": clamp_dmx(round(tilt)),
        "pan_tilt_speed": motion["pan_tilt_speed"],
    }
    result["tilt"] = _expand_motion_tilt_range(
        result["tilt"],
        pattern,
        profile,
        movement_scale,
        default_tilt_center,
    )
    for key in ("dimmer", "strobe", "program", "speed", "rgbw"):
        if key in motion:
            result[key] = motion[key]

    if "rgbw" not in result and profile.get("rgbw") is not None:
        result["rgbw"] = tuple(profile.get("rgbw"))

    if "dimmer" not in result and profile.get("dimmer_static") is not None:
        result["dimmer"] = clamp_dmx(profile.get("dimmer_static"))

    if "program" not in result and profile.get("program_static") is not None:
        result["program"] = clamp_dmx(profile.get("program_static"))

    if "speed" not in result and profile.get("program_speed_static") is not None:
        result["speed"] = clamp_dmx(profile.get("program_speed_static"))

    if "strobe" not in result and profile.get("strobe_static") is not None:
        result["strobe"] = clamp_dmx(profile.get("strobe_static"))

    if "strobe" not in result and "strobe_min" in profile:
        strobe_min = int(profile.get("strobe_min", 0))
        strobe_max = int(profile.get("strobe_max", strobe_min))
        result["strobe"] = clamp_dmx(
            round(strobe_min + movement_scale * max(0, strobe_max - strobe_min))
        )

    if "program" not in result and "color_program_min" in profile:
        program_min = int(profile.get("color_program_min", 232))
        program_max = int(profile.get("color_program_max", program_min))
        jump_phase = 0.5 + 0.5 * wave_sine(adjusted_beat / 5.0 + group_index * 0.11)
        result["program"] = clamp_dmx(
            round(program_min + jump_phase * max(0, program_max - program_min))
        )

    if "speed" not in result and "color_speed_min" in profile:
        color_speed_min = int(profile.get("color_speed_min", 80))
        color_speed_max = int(profile.get("color_speed_max", color_speed_min))
        result["speed"] = clamp_dmx(
            round(color_speed_max - movement_scale * max(0, color_speed_max - color_speed_min))
        )

    return result


def maybe_apply_member_mirror(motion, slot_context, enabled, config=None):
    if not motion or not enabled or not slot_context:
        return motion
    member_count = max(1, int(slot_context.get("member_count", 1)))
    if member_count != 2:
        return motion
    member_alternate = float(slot_context.get("member_alternate", slot_context.get("alternate", 1.0)))
    if member_alternate >= 0:
        return motion
    mirror_center_pan = None
    if isinstance(config, dict):
        pose_center = _slot_pose(config, "pose_center") or _slot_pose(config, "pose_audience_center")
        if pose_center:
            mirror_center_pan = pose_center["pan"]
        elif config.get("pan_left_value") is not None and config.get("pan_right_value") is not None:
            mirror_center_pan = round((int(config.get("pan_left_value")) + int(config.get("pan_right_value"))) / 2.0)
    if mirror_center_pan is None:
        mirror_center_pan = 127
    mirrored = dict(motion)
    mirrored["pan"] = clamp_dmx(round(float(mirror_center_pan) * 2.0 - int(motion["pan"])))
    mirrored["tilt"] = clamp_dmx(int(motion["tilt"]))
    return mirrored


class OscListener:
    def __init__(self, port=DEFAULT_OSC_PORT):
        self.port = port
        self.debug_log = TRIGGER_LOG
        self.lock = threading.Lock()
        self.socket = None
        self.thread = None
        self.running = False
        self.error = None
        self.message_count = 0
        self.last_received_at = None
        self.last_message = None
        self.bpm = None
        self.beat = None
        self.beat_total = None
        self.beat_cycle_offset = 0.0
        self.beat_updated_at = None
        self.last_tick_index = None
        self.last_tick_at = None
        self.time_seconds = None
        self.time_updated_at = None
        self.phrase_current = None
        self.phrase_next = None
        self.phrase_count_in = None
        self.phrase_count_in_updated_at = None
        self.mood = None
        self.color_bank = None
        self.waveform_energy = None
        self.waveform_energy_updated_at = None
        self.audio_bands = self._empty_band_state()
        self.audio_bands_updated_at = None
        self.audio_drums = self._empty_trigger_state()
        self.waveform_bands = self._empty_band_state()
        self.waveform_bands_updated_at = None
        self.waveform_lookahead = self._empty_lookahead_state()
        self.waveform_samples = deque(maxlen=480)
        self.waveform_state_name = "neutral"
        self.waveform_state_changed_at = 0.0
        self.waveform_state_candidate = None
        self.waveform_state_candidate_since = None
        self.drum_signals = self._empty_trigger_state()
        self.strobe_active = False
        self.strobe_count_in = None
        self.track_title = None
        self.track_artist = None
        self.track_album = None
        self.decks = {}
        self.last_beat_index = None
        self.last_beat_at = None

    def start(self):
        self.stop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self.port))
        sock.settimeout(0.25)

        with self.lock:
            self.socket = sock
            self.running = True
            self.error = None

        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        with self.lock:
            sock = self.socket
            thread = self.thread
            self.running = False
            self.socket = None
            self.thread = None

        if sock:
            with suppress(Exception):
                sock.close()
        if thread and thread.is_alive():
            thread.join(timeout=1.0)

    def state(self):
        with self.lock:
            now = time.time()
            stale = (
                self.last_received_at is None
                or now - self.last_received_at > 3.0
            )
            beat_display = self._continuous_beat_display(now)
            beat_phase_age_seconds = self._continuous_beat_phase_age_seconds(now)
            phrase_countdown_beats = self._continuous_phrase_countdown(now)
            phrase_countdown_seconds = None
            if phrase_countdown_beats is not None and self.bpm and self.bpm > 0:
                phrase_countdown_seconds = phrase_countdown_beats * 60.0 / self.bpm
            time_display_seconds = self._resolved_time_display_seconds(now)
            track_title = self.track_title or self._deck_fallback_value("track_title")
            track_artist = self.track_artist or self._deck_fallback_value("track_artist")
            track_album = self.track_album or self._deck_fallback_value("track_album")
            phrase_current = self._resolved_phrase_current()
            phrase_next = self._resolved_phrase_next()
            raw_color_bank = (
                self.color_bank
                if self.color_bank is not None
                else self._deck_fallback_value("color_bank")
            )
            color_bank = derive_color_bank_value(
                raw_color_bank,
                phrase=phrase_current or phrase_next,
                track_title=track_title,
                track_artist=track_artist,
                track_album=track_album,
            )
            base_mood = derive_mood_value(
                self.mood if self.mood is not None else self._deck_fallback_value("mood"),
                phrase=phrase_current,
                color_bank=color_bank,
            )
            waveform_energy = self._resolved_waveform_energy(now)
            audio_bands = self._resolved_audio_bands(now)
            waveform_bands = self._resolved_waveform_bands(now)
            waveform_lookahead = self._resolved_waveform_lookahead(now)
            waveform_analysis = self._resolved_waveform_analysis(now)
            audio_drums = self._resolved_audio_drums(now)
            drum_signals = self._resolved_drum_signals(now)
            mood = refine_mood_with_waveform(
                base_mood,
                phrase=phrase_current or phrase_next,
                analysis=waveform_analysis,
            )
            return {
                "port": self.port,
                "running": self.running,
                "stale": stale,
                "error": self.error,
                "message_count": self.message_count,
                "last_received_at": self.last_received_at,
                "last_message": self.last_message,
                "bpm": self.bpm,
                "beat": self.beat,
                "beat_display": beat_display,
                "beat_phase_age_seconds": beat_phase_age_seconds,
                "time_seconds": self._resolved_time_seconds(),
                "time_display_seconds": time_display_seconds,
                "phrase_current": phrase_current,
                "phrase_next": phrase_next,
                "phrase_count_in": self.phrase_count_in,
                "phrase_countdown_beats": phrase_countdown_beats,
                "phrase_countdown_seconds": phrase_countdown_seconds,
                "mood": mood,
                "color_bank": color_bank,
                "waveform_energy": waveform_energy,
                "audio_bands": audio_bands,
                "waveform_bands": waveform_bands,
                "waveform_lookahead": waveform_lookahead,
                "waveform_analysis": waveform_analysis,
                "audio_drums": audio_drums,
                "drum_signals": drum_signals,
                "strobe_active": self.strobe_active,
                "strobe_count_in": self.strobe_count_in,
                "track_title": track_title,
                "track_artist": track_artist,
                "track_album": track_album,
                "decks": {
                    deck_id: self._public_deck_state(deck_state, now)
                    for deck_id, deck_state in sorted(
                        self.decks.items(),
                        key=lambda item: (
                            0,
                            int(item[0]),
                        )
                        if item[0].isdigit()
                        else (1, str(item[0])),
                    )
                },
                "last_beat_at": self.last_beat_at,
            }

    def snapshot_for_render(self):
        with self.lock:
            now = time.time()
            track_title = self.track_title or self._deck_fallback_value("track_title")
            track_artist = self.track_artist or self._deck_fallback_value("track_artist")
            track_album = self.track_album or self._deck_fallback_value("track_album")
            phrase_current = self._resolved_phrase_current()
            phrase_next = self._resolved_phrase_next()
            raw_color_bank = (
                self.color_bank
                if self.color_bank is not None
                else self._deck_fallback_value("color_bank")
            )
            color_bank = derive_color_bank_value(
                raw_color_bank,
                phrase=phrase_current or phrase_next,
                track_title=track_title,
                track_artist=track_artist,
                track_album=track_album,
            )
            base_mood = derive_mood_value(
                self.mood if self.mood is not None else self._deck_fallback_value("mood"),
                phrase=phrase_current,
                color_bank=color_bank,
            )
            waveform_energy = self._resolved_waveform_energy(now)
            audio_bands = self._resolved_audio_bands(now)
            waveform_bands = self._resolved_waveform_bands(now)
            waveform_lookahead = self._resolved_waveform_lookahead(now)
            waveform_analysis = self._resolved_waveform_analysis(now)
            audio_drums = self._resolved_audio_drums(now)
            drum_signals = self._resolved_drum_signals(now)
            mood = refine_mood_with_waveform(
                base_mood,
                phrase=phrase_current or phrase_next,
                analysis=waveform_analysis,
            )
            return {
                "bpm": self.bpm,
                "beat": self.beat,
                "beat_value": self._continuous_beat_value(now),
                "beat_display": self._continuous_beat_display(now),
                "beat_phase_age_seconds": self._continuous_beat_phase_age_seconds(now),
                "time_seconds": self._resolved_time_seconds(),
                "time_display_seconds": self._resolved_time_display_seconds(now),
                "phrase_current": phrase_current,
                "phrase_next": phrase_next,
                "mood": mood,
                "color_bank": color_bank,
                "waveform_energy": waveform_energy,
                "audio_bands": audio_bands,
                "waveform_bands": waveform_bands,
                "waveform_lookahead": waveform_lookahead,
                "waveform_analysis": waveform_analysis,
                "audio_drums": audio_drums,
                "drum_signals": drum_signals,
                "strobe_active": self.strobe_active,
                "strobe_count_in": self.strobe_count_in,
                "track_title": track_title,
                "track_artist": track_artist,
                "track_album": track_album,
                "last_beat_at": self.last_beat_at,
                "stale": self.last_received_at is None or now - self.last_received_at > 3.0,
            }

    def _loop(self):
        while True:
            with self.lock:
                if not self.running or not self.socket:
                    return
                sock = self.socket
            try:
                data, source = sock.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                return
            except Exception as exc:
                with self.lock:
                    self.error = str(exc)
                continue

            message = parse_osc_message(data)
            if message:
                self._handle_message(message, source)

    def _handle_message(self, message, source):
        address = message["address"]
        numeric = message["numeric"]
        text = message["text"]
        now = time.time()

        with self.lock:
            self.message_count += 1
            self.last_received_at = now
            self.last_message = {
                "address": address,
                "numeric": numeric,
                "text": text,
                "source": f"{source[0]}:{source[1]}",
            }

            parts = [part for part in address.split("/") if part]
            if address in ("/bpm/master/current", "/master/bpm/current") and numeric:
                self.bpm = numeric
            elif address in ("/beat/master", "/master/beat") and numeric is not None:
                previous_beat = self.beat
                self.beat = numeric
                if previous_beat is not None:
                    # Rekordbox/BPM Trigger stuurt beat doorgaans als een 4-beat fase
                    # (0..4). Voor bewegingen hebben we een doorlopende teller nodig,
                    # anders resetten sweeps elke maat terug naar hun beginpunt.
                    if numeric < 1.0 and previous_beat > 3.0:
                        self.beat_cycle_offset += 4.0
                    elif numeric + 2.0 < previous_beat:
                        # Veilige fallback bij onregelmatige wrap/jitter.
                        self.beat_cycle_offset += 4.0
                self.beat_total = self.beat_cycle_offset + float(numeric)
                self.beat_updated_at = now
                tick_index = int(math.floor(max(0.0, self.beat_total) * 24.0))
                if self.last_tick_index is None or tick_index != self.last_tick_index:
                    self.last_tick_index = tick_index
                    self.last_tick_at = now
                beat_index = tick_index // 24
                if self.last_beat_index is None or beat_index != self.last_beat_index:
                    self.last_beat_index = beat_index
                    self.last_beat_at = now
            elif address == "/master/time" and numeric is not None:
                self.time_seconds = numeric
                self.time_updated_at = now
            elif address == "/master/track/title":
                if text != self.track_title:
                    self.debug_log.log("OSC_TRACK", scope="master", title=text)
                self.track_title = text
            elif address == "/master/track/artist":
                self.track_artist = text
            elif address == "/master/track/album":
                self.track_album = text
            elif address in ("/master/phrase/current", "/phrase/master/current"):
                phrase_value = text if text not in (None, "") else numeric
                if phrase_value != self.phrase_current:
                    self.debug_log.log("OSC_PHRASE", scope="master", current=phrase_value)
                self.phrase_current = phrase_value
            elif address in ("/master/phrase/next", "/phrase/master/next"):
                phrase_value = text if text not in (None, "") else numeric
                if phrase_value != self.phrase_next:
                    self.debug_log.log("OSC_PHRASE_NEXT", scope="master", next=phrase_value)
                self.phrase_next = phrase_value
            elif address == "/master/phrase/countin" and numeric is not None:
                count_in = max(0, int(round(numeric)))
                if count_in != self.phrase_count_in:
                    self.debug_log.log("OSC_COUNTIN", scope="master", beats=count_in)
                self.phrase_count_in = count_in
                self.phrase_count_in_updated_at = now
            elif address in ("/master/mood", "/mood/master") and numeric is not None:
                if numeric != self.mood:
                    self.debug_log.log("OSC_MOOD", scope="master", value=numeric)
                self.mood = numeric
            elif address in ("/master/color_bank", "/color_bank/master") and numeric is not None:
                bank_value = int(round(numeric))
                if bank_value != self.color_bank:
                    self.debug_log.log("OSC_BANK", scope="master", value=bank_value)
                self.color_bank = bank_value
            elif address in ("/master/waveform/energy", "/waveform/master/energy") and numeric is not None:
                self.waveform_energy = clamp_unit(numeric)
                self.waveform_energy_updated_at = now
                self._append_waveform_sample(self.waveform_samples, now, self.waveform_energy)
            elif address in ("/master/audio/low_energy", "/audio/master/low_energy") and numeric is not None:
                self._update_waveform_band(self.audio_bands, self.audio_drums, "low", numeric, now)
                self.audio_bands_updated_at = now
            elif address in ("/master/audio/mid_energy", "/audio/master/mid_energy") and numeric is not None:
                self._update_waveform_band(self.audio_bands, self.audio_drums, "mid", numeric, now)
                self.audio_bands_updated_at = now
            elif address in ("/master/audio/high_energy", "/audio/master/high_energy") and numeric is not None:
                self._update_waveform_band(self.audio_bands, self.audio_drums, "high", numeric, now)
                self.audio_bands_updated_at = now
            elif address in ("/master/audio/kick", "/audio/master/kick") and numeric is not None:
                self._set_trigger_signal(self.audio_drums, "kick", numeric, now)
            elif address in ("/master/audio/snare", "/audio/master/snare") and numeric is not None:
                self._set_trigger_signal(self.audio_drums, "snare", numeric, now)
            elif address in ("/master/audio/hihat", "/audio/master/hihat") and numeric is not None:
                self._set_trigger_signal(self.audio_drums, "hihat", numeric, now)
            elif address in ("/master/waveform/low_energy", "/waveform/master/low_energy") and numeric is not None:
                self._update_waveform_band(self.waveform_bands, self.drum_signals, "low", numeric, now)
                self.waveform_bands_updated_at = now
            elif address in ("/master/waveform/mid_energy", "/waveform/master/mid_energy") and numeric is not None:
                self._update_waveform_band(self.waveform_bands, self.drum_signals, "mid", numeric, now)
                self.waveform_bands_updated_at = now
            elif address in ("/master/waveform/high_energy", "/waveform/master/high_energy") and numeric is not None:
                self._update_waveform_band(self.waveform_bands, self.drum_signals, "high", numeric, now)
                self.waveform_bands_updated_at = now
            elif (
                len(parts) >= 5
                and (
                    parts[:3] == ["master", "waveform", "lookahead"]
                    or parts[:3] == ["waveform", "master", "lookahead"]
                )
                and numeric is not None
            ):
                beats_ahead = str(parts[3])
                band_key = parts[4]
                if beats_ahead in self.waveform_lookahead and band_key in ("low_energy", "mid_energy", "high_energy"):
                    channel = band_key.split("_", 1)[0]
                    lookahead_state = self.waveform_lookahead[beats_ahead]
                    self._update_waveform_band(lookahead_state, None, channel, numeric, now)
            elif address in ("/master/waveform/low_onset", "/waveform/master/low_onset") and numeric is not None:
                self._set_trigger_signal(self.drum_signals, "low_onset", numeric, now)
            elif address in ("/master/waveform/mid_onset", "/waveform/master/mid_onset") and numeric is not None:
                self._set_trigger_signal(self.drum_signals, "mid_onset", numeric, now)
            elif address in ("/master/waveform/high_onset", "/waveform/master/high_onset") and numeric is not None:
                self._set_trigger_signal(self.drum_signals, "high_onset", numeric, now)
            elif address in ("/master/drums/kick", "/drums/master/kick") and numeric is not None:
                self._set_trigger_signal(self.drum_signals, "kick", numeric, now)
            elif address in ("/master/drums/snare", "/drums/master/snare") and numeric is not None:
                self._set_trigger_signal(self.drum_signals, "snare", numeric, now)
            elif address in ("/master/drums/hihat", "/drums/master/hihat") and numeric is not None:
                self._set_trigger_signal(self.drum_signals, "hihat", numeric, now)
            elif address in ("/master/strobe/active", "/strobe/master/active") and numeric is not None:
                active = int(round(numeric)) != 0
                if active != self.strobe_active:
                    self.debug_log.log("OSC_STROBE", scope="master", active=active)
                self.strobe_active = active
            elif address in ("/master/strobe/countin", "/strobe/master/countin") and numeric is not None:
                count_in = max(0, int(round(numeric)))
                if count_in != self.strobe_count_in:
                    self.debug_log.log("OSC_STROBE_COUNTIN", scope="master", beats=count_in)
                self.strobe_count_in = count_in
            elif len(parts) >= 2 and parts[0].isdigit():
                deck_id = parts[0]
                deck = self._deck_state(deck_id)
                key = "/".join(parts[1:])
                if key == "phrase/current":
                    phrase_value = text if text not in (None, "") else numeric
                    if phrase_value != deck.get("phrase_current"):
                        self.debug_log.log("OSC_PHRASE", scope=f"deck{deck_id}", current=phrase_value)
                    deck["phrase_current"] = phrase_value
                elif key == "phrase/next":
                    phrase_value = text if text not in (None, "") else numeric
                    if phrase_value != deck.get("phrase_next"):
                        self.debug_log.log("OSC_PHRASE_NEXT", scope=f"deck{deck_id}", next=phrase_value)
                    deck["phrase_next"] = phrase_value
                elif key == "track/title":
                    if text != deck.get("track_title"):
                        self.debug_log.log("OSC_TRACK", scope=f"deck{deck_id}", title=text)
                    deck["track_title"] = text
                elif key == "track/artist":
                    deck["track_artist"] = text
                elif key == "track/album":
                    deck["track_album"] = text
                elif key == "time" and numeric is not None:
                    deck["time_seconds"] = numeric
                    deck["time_updated_at"] = now
                elif key == "mood" and numeric is not None:
                    if numeric != deck.get("mood"):
                        self.debug_log.log("OSC_MOOD", scope=f"deck{deck_id}", value=numeric)
                    deck["mood"] = numeric
                elif key == "color_bank" and numeric is not None:
                    bank_value = int(round(numeric))
                    if bank_value != deck.get("color_bank"):
                        self.debug_log.log("OSC_BANK", scope=f"deck{deck_id}", value=bank_value)
                    deck["color_bank"] = bank_value
                elif key == "waveform/energy" and numeric is not None:
                    deck["waveform_energy"] = clamp_unit(numeric)
                    deck["waveform_energy_updated_at"] = now
                    self._append_waveform_sample(
                        deck.setdefault("waveform_samples", deque(maxlen=480)),
                        now,
                        deck["waveform_energy"],
                    )
                elif key == "waveform/low_energy" and numeric is not None:
                    self._update_waveform_band(deck["waveform_bands"], deck["drum_signals"], "low", numeric, now)
                    deck["waveform_bands_updated_at"] = now
                elif key == "waveform/mid_energy" and numeric is not None:
                    self._update_waveform_band(deck["waveform_bands"], deck["drum_signals"], "mid", numeric, now)
                    deck["waveform_bands_updated_at"] = now
                elif key == "waveform/high_energy" and numeric is not None:
                    self._update_waveform_band(deck["waveform_bands"], deck["drum_signals"], "high", numeric, now)
                    deck["waveform_bands_updated_at"] = now
                elif len(parts) >= 5 and parts[1] == "waveform" and parts[2] == "lookahead" and numeric is not None:
                    beats_ahead = str(parts[3])
                    band_key = parts[4]
                    if beats_ahead in deck["waveform_lookahead"] and band_key in ("low_energy", "mid_energy", "high_energy"):
                        channel = band_key.split("_", 1)[0]
                        self._update_waveform_band(deck["waveform_lookahead"][beats_ahead], None, channel, numeric, now)
                elif key == "waveform/low_onset" and numeric is not None:
                    self._set_trigger_signal(deck["drum_signals"], "low_onset", numeric, now)
                elif key == "waveform/mid_onset" and numeric is not None:
                    self._set_trigger_signal(deck["drum_signals"], "mid_onset", numeric, now)
                elif key == "waveform/high_onset" and numeric is not None:
                    self._set_trigger_signal(deck["drum_signals"], "high_onset", numeric, now)
                elif key == "drums/kick" and numeric is not None:
                    self._set_trigger_signal(deck["drum_signals"], "kick", numeric, now)
                elif key == "drums/snare" and numeric is not None:
                    self._set_trigger_signal(deck["drum_signals"], "snare", numeric, now)
                elif key == "drums/hihat" and numeric is not None:
                    self._set_trigger_signal(deck["drum_signals"], "hihat", numeric, now)

    def _empty_deck_state(self):
        return {
            "track_title": None,
            "track_artist": None,
            "track_album": None,
            "time_seconds": None,
            "time_updated_at": None,
            "phrase_current": None,
            "phrase_next": None,
            "mood": None,
            "color_bank": None,
            "waveform_energy": None,
            "waveform_energy_updated_at": None,
            "waveform_bands": self._empty_band_state(),
            "waveform_bands_updated_at": None,
            "waveform_lookahead": self._empty_lookahead_state(),
            "waveform_samples": deque(maxlen=480),
            "drum_signals": self._empty_trigger_state(),
        }

    def _empty_band_state(self):
        return {"low": None, "mid": None, "high": None}

    def _empty_lookahead_state(self):
        return {"2": self._empty_band_state(), "4": self._empty_band_state()}

    def _empty_trigger_state(self):
        return {
            "kick": {"value": 0.0, "updated_at": None},
            "snare": {"value": 0.0, "updated_at": None},
            "hihat": {"value": 0.0, "updated_at": None},
            "low_onset": {"value": 0.0, "updated_at": None},
            "mid_onset": {"value": 0.0, "updated_at": None},
            "high_onset": {"value": 0.0, "updated_at": None},
        }

    def _estimated_band_onset(self, band_key, current, previous):
        energy_floor = {"low": 0.05, "mid": 0.03, "high": 0.02}.get(band_key, 0.03)
        delta_floor = {"low": 0.008, "mid": 0.006, "high": 0.005}.get(band_key, 0.006)
        delta = max(0.0, current - previous)
        if current < energy_floor or delta <= delta_floor:
            return 0.0
        delta_score = clamp_unit((delta - delta_floor) / 0.08)
        energy_score = clamp_unit((current - energy_floor) / 0.24)
        return clamp_unit(delta_score * 0.75 + energy_score * 0.25)

    def _update_waveform_band(self, band_target, trigger_target, key, value, now):
        if band_target is None:
            return
        try:
            numeric = clamp_unit(float(value))
        except (TypeError, ValueError):
            return
        previous = float(band_target.get(key) or 0.0)
        band_target[key] = numeric
        onset_key = {
            "low": "low_onset",
            "mid": "mid_onset",
            "high": "high_onset",
        }.get(key)
        if onset_key and trigger_target is not None:
            onset_value = self._estimated_band_onset(key, numeric, previous)
            if onset_value > 0.0:
                self._set_trigger_signal(trigger_target, onset_key, onset_value, now)

    def _set_trigger_signal(self, target, key, value, now):
        if target is None or key not in target:
            return
        try:
            numeric = clamp_unit(float(value))
        except (TypeError, ValueError):
            return
        if numeric <= 0.001:
            return
        entry = target[key]
        previous = float(entry.get("value") or 0.0)
        entry["value"] = max(numeric, previous * 0.72)
        entry["updated_at"] = now

    def _deck_state(self, deck_id):
        deck_id = str(deck_id)
        if deck_id not in self.decks:
            self.decks[deck_id] = self._empty_deck_state()
        return self.decks[deck_id]

    def _deck_fallback_value(self, key):
        for deck_id in sorted(
            self.decks.keys(),
            key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value)),
        ):
            value = self.decks[deck_id].get(key)
            if value not in (None, ""):
                return value
        return None

    def _resolved_time_seconds(self):
        if self.time_seconds is not None:
            return self.time_seconds
        return self._deck_fallback_value("time_seconds")

    def _resolved_time_display_seconds(self, now):
        value = self._continuous_time_seconds(now)
        if value is not None:
            return value
        for deck_id in sorted(
            self.decks.keys(),
            key=lambda key: (0, int(key)) if str(key).isdigit() else (1, str(key)),
        ):
            deck_value = self._continuous_deck_time_seconds(self.decks[deck_id], now)
            if deck_value is not None:
                return deck_value
        return None

    def _resolved_waveform_energy(self, now):
        if (
            self.waveform_energy is not None
            and self.waveform_energy_updated_at is not None
            and now - self.waveform_energy_updated_at < 3.0
        ):
            return self.waveform_energy

        for deck_id in sorted(
            self.decks.keys(),
            key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value)),
        ):
            deck = self.decks[deck_id]
            value = deck.get("waveform_energy")
            updated_at = deck.get("waveform_energy_updated_at")
            if value is not None and updated_at is not None and now - updated_at < 3.0:
                return value
        return None

    def _resolved_waveform_bands(self, now):
        if (
            self.waveform_bands_updated_at is not None
            and now - self.waveform_bands_updated_at < 3.0
            and any(self.waveform_bands.get(key) is not None for key in ("low", "mid", "high"))
        ):
            return {
                key: self.waveform_bands.get(key)
                for key in ("low", "mid", "high")
            }

        for deck_id in sorted(
            self.decks.keys(),
            key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value)),
        ):
            deck = self.decks[deck_id]
            updated_at = deck.get("waveform_bands_updated_at")
            band_state = deck.get("waveform_bands") or {}
            if (
                updated_at is not None
                and now - updated_at < 3.0
                and any(band_state.get(key) is not None for key in ("low", "mid", "high"))
            ):
                return {
                    key: band_state.get(key)
                    for key in ("low", "mid", "high")
                }
        return None

    def _resolved_audio_bands(self, now):
        if (
            self.audio_bands_updated_at is not None
            and now - self.audio_bands_updated_at < 3.0
            and any(self.audio_bands.get(key) is not None for key in ("low", "mid", "high"))
        ):
            return {
                key: self.audio_bands.get(key)
                for key in ("low", "mid", "high")
            }
        return None

    def _resolved_waveform_lookahead(self, now):
        master_has_data = (
            self.waveform_bands_updated_at is not None
            and now - self.waveform_bands_updated_at < 3.0
            and any(
                any((self.waveform_lookahead.get(str(beats)) or {}).get(key) is not None for key in ("low", "mid", "high"))
                for beats in (2, 4)
            )
        )
        if master_has_data:
            return {
                str(beats): {
                    key: (self.waveform_lookahead.get(str(beats)) or {}).get(key)
                    for key in ("low", "mid", "high")
                }
                for beats in (2, 4)
            }

        for deck_id in sorted(
            self.decks.keys(),
            key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value)),
        ):
            lookahead_state = (self.decks[deck_id] or {}).get("waveform_lookahead") or {}
            has_data = (
                (self.decks[deck_id] or {}).get("waveform_bands_updated_at") is not None
                and now - float((self.decks[deck_id] or {}).get("waveform_bands_updated_at") or 0.0) < 3.0
                and any(
                    any((lookahead_state.get(str(beats)) or {}).get(key) is not None for key in ("low", "mid", "high"))
                    for beats in (2, 4)
                )
            )
            if has_data:
                return {
                    str(beats): {
                        key: (lookahead_state.get(str(beats)) or {}).get(key)
                        for key in ("low", "mid", "high")
                    }
                    for beats in (2, 4)
                }
        return None

    def _resolved_trigger_state(self, target, now):
        result = {}
        decay_map = {
            "kick": 0.36,
            "snare": 0.28,
            "hihat": 0.20,
            "low_onset": 0.36,
            "mid_onset": 0.28,
            "high_onset": 0.20,
        }
        for key, entry in (target or {}).items():
            value = float(entry.get("value") or 0.0)
            updated_at = entry.get("updated_at")
            if updated_at is None or value <= 0.0:
                result[key] = 0.0
                continue
            age = max(0.0, now - updated_at)
            decay = decay_map.get(key, 0.18)
            result[key] = clamp_unit(value * max(0.0, 1.0 - (age / decay)))
        return result

    def _resolved_drum_signals(self, now):
        master_state = self._resolved_trigger_state(self.drum_signals, now)
        if max(master_state.values(), default=0.0) > 0.0:
            return master_state

        for deck_id in sorted(
            self.decks.keys(),
            key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value)),
        ):
            deck_state = self._resolved_trigger_state(
                (self.decks[deck_id] or {}).get("drum_signals"),
                now,
            )
            if max(deck_state.values(), default=0.0) > 0.0:
                return deck_state
        return master_state

    def _resolved_audio_drums(self, now):
        if (
            self.audio_bands_updated_at is not None
            and now - self.audio_bands_updated_at < 3.0
        ):
            return self._resolved_trigger_state(self.audio_drums, now)
        return None

    def _resolved_waveform_analysis(self, now):
        if (
            self.waveform_energy is not None
            and self.waveform_energy_updated_at is not None
            and now - self.waveform_energy_updated_at < 3.0
        ):
            analysis = self._stabilize_waveform_analysis(
                waveform_analysis_from_samples(self.waveform_samples, now),
                now,
            )
            if analysis:
                return analysis

        for deck_id in sorted(
            self.decks.keys(),
            key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value)),
        ):
            deck = self.decks[deck_id]
            updated_at = deck.get("waveform_energy_updated_at")
            if updated_at is None or now - updated_at >= 3.0:
                continue
            analysis = self._stabilize_waveform_analysis(
                waveform_analysis_from_samples(deck.get("waveform_samples"), now),
                now,
            )
            if analysis:
                return analysis
        return None

    def _resolved_phrase_current(self):
        return (
            self.phrase_current
            or self._deck_fallback_value("phrase_current")
            or self.phrase_next
            or self._deck_fallback_value("phrase_next")
        )

    def _resolved_phrase_next(self):
        return self.phrase_next or self._deck_fallback_value("phrase_next")

    def _continuous_deck_time_seconds(self, deck_state, now):
        value = deck_state.get("time_seconds")
        if value is None:
            return None
        updated_at = deck_state.get("time_updated_at")
        if updated_at and self.last_received_at and now - self.last_received_at < 1.0:
            return value + max(0.0, now - updated_at)
        return value

    def _public_deck_state(self, deck_state, now):
        phrase_current = deck_state.get("phrase_current")
        phrase_next = deck_state.get("phrase_next")
        color_bank = derive_color_bank_value(
            deck_state.get("color_bank"),
            phrase=phrase_current or phrase_next,
            track_title=deck_state.get("track_title"),
            track_artist=deck_state.get("track_artist"),
            track_album=deck_state.get("track_album"),
        )
        base_mood = derive_mood_value(
            deck_state.get("mood"),
            phrase=phrase_current,
            color_bank=color_bank,
        )
        mood = refine_mood_with_waveform(
            base_mood,
            phrase=phrase_current or phrase_next,
            analysis=waveform_analysis_from_samples(
                deck_state.get("waveform_samples"), now
            ),
        )
        return {
            "track_title": deck_state.get("track_title"),
            "track_artist": deck_state.get("track_artist"),
            "track_album": deck_state.get("track_album"),
            "time_seconds": deck_state.get("time_seconds"),
            "time_display_seconds": self._continuous_deck_time_seconds(deck_state, now),
            "phrase_current": phrase_current,
            "phrase_next": phrase_next,
            "mood": mood,
            "color_bank": color_bank,
            "waveform_energy": deck_state.get("waveform_energy"),
            "waveform_bands": dict(deck_state.get("waveform_bands") or {}),
            "waveform_lookahead": {
                "2": dict(((deck_state.get("waveform_lookahead") or {}).get("2")) or {}),
                "4": dict(((deck_state.get("waveform_lookahead") or {}).get("4")) or {}),
            },
            "drum_signals": self._resolved_trigger_state(deck_state.get("drum_signals"), now),
        }

    def _append_waveform_sample(self, target, now, value):
        if target is None or value is None:
            return
        try:
            numeric = clamp_unit(float(value))
        except (TypeError, ValueError):
            return
        target.append((now, numeric))

    def _classify_waveform_state(self, analysis):
        if not analysis:
            return "neutral"
        if analysis.get("attack"):
            return "attack"
        if analysis.get("breakdown"):
            return "breakdown"
        if analysis.get("sustained_high"):
            return "sustain"
        if analysis.get("calm"):
            return "calm"
        return "neutral"

    def _stabilize_waveform_analysis(self, analysis, now):
        if not analysis:
            return None

        raw_state = self._classify_waveform_state(analysis)
        current_state = self.waveform_state_name or "neutral"

        if raw_state == current_state:
            self.waveform_state_candidate = None
            self.waveform_state_candidate_since = None
        else:
            if self.waveform_state_candidate != raw_state:
                self.waveform_state_candidate = raw_state
                self.waveform_state_candidate_since = now
            hold_seconds = 2.0 if current_state == "neutral" else 2.6
            if raw_state == "neutral":
                hold_seconds = 3.2
            elif raw_state in ("attack", "breakdown"):
                hold_seconds = 2.1
            if (
                self.waveform_state_candidate_since is not None
                and now - self.waveform_state_candidate_since >= hold_seconds
            ):
                self.waveform_state_name = raw_state
                self.waveform_state_changed_at = now
                self.debug_log.log(
                    "WAVEFORM_STATE",
                    state=raw_state,
                    instant=analysis.get("instant"),
                    short=analysis.get("short_avg"),
                    mid=analysis.get("mid_avg"),
                    long=analysis.get("long_avg"),
                    transient=analysis.get("transient"),
                    volatility=analysis.get("volatility"),
                )
                current_state = raw_state
                self.waveform_state_candidate = None
                self.waveform_state_candidate_since = None

        stabilized = dict(analysis)
        stabilized["attack"] = current_state == "attack"
        stabilized["breakdown"] = current_state == "breakdown"
        stabilized["sustained_high"] = current_state == "sustain"
        stabilized["calm"] = current_state == "calm"
        stabilized["state"] = current_state
        if current_state in ("attack", "sustain"):
            stabilized["mood_hint"] = 1.0
        elif current_state in ("calm", "breakdown"):
            stabilized["mood_hint"] = 3.0
        elif analysis.get("mood_hint") == 2.0:
            stabilized["mood_hint"] = 2.0
        else:
            stabilized["mood_hint"] = None
        return stabilized

    def _continuous_beat_value(self, now):
        if self.beat_total is None:
            return None
        value = float(self.beat_total)
        if self.bpm and self.bpm > 0 and self.beat_updated_at and now - self.beat_updated_at < 1.0:
            beat_seconds = 60.0 / self.bpm
            if beat_seconds > 0:
                delta_beats = (now - self.beat_updated_at) / beat_seconds
                value += delta_beats
        return value

    def _continuous_beat_display(self, now):
        value = self._continuous_beat_value(now)
        if value is None:
            return None
        phase = value % 1.0
        beat_index = int(math.floor(value)) % 4 + 1
        return beat_index + phase

    def _continuous_beat_phase_age_seconds(self, now):
        value = self._continuous_beat_value(now)
        if value is None or not self.bpm or self.bpm <= 0:
            return None
        beat_seconds = 60.0 / self.bpm
        return (value % 1.0) * beat_seconds

    def _continuous_phrase_countdown(self, now):
        if self.phrase_count_in is None:
            return None
        value = float(self.phrase_count_in)
        if self.bpm and self.bpm > 0 and self.phrase_count_in_updated_at and now - self.phrase_count_in_updated_at < 1.0:
            beat_seconds = 60.0 / self.bpm
            if beat_seconds > 0:
                value = max(0.0, value - ((now - self.phrase_count_in_updated_at) / beat_seconds))
        return value

    def _continuous_time_seconds(self, now):
        if self.time_seconds is None:
            return None
        if self.time_updated_at and self.last_received_at and now - self.last_received_at < 1.0:
            return self.time_seconds + max(0.0, now - self.time_updated_at)
        return self.time_seconds


class TransportController:
    def __init__(self, osc_listener):
        self.osc = osc_listener
        self.lock = osc_listener.lock
        self.decks = osc_listener.decks
        self._lock = threading.Lock()
        self.config = self._load_config()
        self.developer_playback = DeveloperPlaybackController(
            self.config["developer_playback_state_path"]
        )
        self.tap_times = deque(maxlen=8)
        self.manual_clock_anchor_at = None
        self.manual_clock_beat_at_anchor = 0.0
        self.manual_clock_time_at_anchor = 0.0
        self.manual_tap_locked = False
        self.last_tap_at = None
        self._active_playback_generation = 0
        self._active_playback_signature = None
        self._active_playback_event = "initial"
        self._active_playback_source_switches = 0
        self._active_playback_discontinuities = 0
        self._last_active_playback_source = None

    @staticmethod
    def default_config():
        return {
            "mode": "auto",
            "manual_bpm": DEFAULT_MANUAL_BPM,
            "manual_phrase": DEFAULT_MANUAL_PHRASE,
            "idle_animation_enabled": True,
            "active_playback_source": "legacy",
            "developer_playback_source": "current",
            "developer_playback_state_path": str(DEFAULT_VIRTUALDJ_PLAYBACK_STATE_PATH),
            "structure_behavior_source": "legacy",
        }

    def start(self):
        self.osc.start()

    def stop(self):
        self.osc.stop()

    def _clean_config(self, config):
        defaults = self.default_config()
        cleaned = {**defaults, **(config or {})}
        mode = str(cleaned.get("mode", defaults["mode"])).strip().lower()
        if mode not in TRANSPORT_SOURCE_MODES:
            mode = defaults["mode"]
        cleaned["mode"] = mode
        try:
            cleaned["manual_bpm"] = max(
                40.0,
                min(220.0, float(cleaned.get("manual_bpm", defaults["manual_bpm"]))),
            )
        except (TypeError, ValueError):
            cleaned["manual_bpm"] = defaults["manual_bpm"]
        cleaned["manual_phrase"] = manual_transport_phrase_name(
            cleaned.get("manual_phrase", defaults["manual_phrase"])
        )
        cleaned["idle_animation_enabled"] = bool(
            cleaned.get("idle_animation_enabled", defaults["idle_animation_enabled"])
        )
        active_source = str(
            cleaned.get("active_playback_source", defaults["active_playback_source"])
        ).strip().lower()
        cleaned["active_playback_source"] = (
            active_source
            if active_source in ACTIVE_PLAYBACK_SOURCES
            else defaults["active_playback_source"]
        )
        developer_source = str(
            cleaned.get("developer_playback_source", defaults["developer_playback_source"])
        ).strip().lower()
        cleaned["developer_playback_source"] = (
            developer_source
            if developer_source in DEVELOPER_PLAYBACK_SOURCES
            else defaults["developer_playback_source"]
        )
        behavior_source = str(
            cleaned.get("structure_behavior_source", defaults["structure_behavior_source"])
        ).strip().lower()
        cleaned["structure_behavior_source"] = (
            behavior_source
            if behavior_source in STRUCTURE_BEHAVIOR_SOURCES
            else defaults["structure_behavior_source"]
        )
        configured_path = str(
            cleaned.get("developer_playback_state_path", defaults["developer_playback_state_path"])
        ).strip()
        candidate_path = Path(configured_path).expanduser() if configured_path else DEFAULT_VIRTUALDJ_PLAYBACK_STATE_PATH
        cleaned["developer_playback_state_path"] = str(
            candidate_path if candidate_path.is_absolute() else DEFAULT_VIRTUALDJ_PLAYBACK_STATE_PATH
        )
        return cleaned

    def _load_config(self):
        defaults = self.default_config()
        if not TRANSPORT_CONFIG_PATH.exists():
            return defaults
        try:
            payload = json.loads(TRANSPORT_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return defaults
        return self._clean_config(payload)

    def _save_config(self, config):
        cleaned = self._clean_config(config)
        TRANSPORT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = TRANSPORT_CONFIG_PATH.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
        tmp_path.replace(TRANSPORT_CONFIG_PATH)

    def _recent_tap_count_locked(self, now):
        return len([tap for tap in self.tap_times if now - tap <= 2.8])

    def _ensure_manual_clock_locked(self, now):
        if self.manual_clock_anchor_at is None:
            self.manual_clock_anchor_at = float(now)
            self.manual_clock_beat_at_anchor = 0.0
            self.manual_clock_time_at_anchor = 0.0

    def _manual_clock_state_locked(self, now):
        self._ensure_manual_clock_locked(now)
        bpm = float(self.config.get("manual_bpm", DEFAULT_MANUAL_BPM))
        beat_seconds = 60.0 / max(1e-6, bpm)
        elapsed = max(0.0, float(now) - float(self.manual_clock_anchor_at or now))
        beat_value = float(self.manual_clock_beat_at_anchor) + (elapsed / beat_seconds)
        time_seconds = float(self.manual_clock_time_at_anchor) + elapsed
        return bpm, beat_value, time_seconds

    def _set_manual_bpm_locked(self, bpm, now, align_downbeat=False):
        bpm = max(40.0, min(220.0, float(bpm)))
        if self.manual_clock_anchor_at is None or align_downbeat:
            beat_value = 0.0
            time_seconds = 0.0
        else:
            _current_bpm, beat_value, time_seconds = self._manual_clock_state_locked(now)
        self.config["manual_bpm"] = bpm
        self.manual_clock_anchor_at = float(now)
        self.manual_clock_beat_at_anchor = float(beat_value)
        self.manual_clock_time_at_anchor = float(time_seconds)

    def update_config(self, payload):
        payload = payload or {}
        now = time.time()
        persist_config = None
        with self._lock:
            previous_active_source = self.config.get("active_playback_source", "legacy")
            merged = {**self.config, **payload}
            cleaned = self._clean_config(merged)
            manual_bpm_changed = (
                "manual_bpm" in payload
                and abs(float(cleaned["manual_bpm"]) - float(self.config.get("manual_bpm", DEFAULT_MANUAL_BPM))) > 0.0001
            )
            self.config = cleaned
            if manual_bpm_changed:
                self._set_manual_bpm_locked(
                    cleaned["manual_bpm"],
                    now,
                    align_downbeat=not self.manual_tap_locked,
                )
                self.manual_tap_locked = True
            if cleaned["active_playback_source"] != previous_active_source:
                self.developer_playback.reset()
                self._active_playback_signature = None
                self._active_playback_event = "source_switched"
            persist_config = dict(self.config)
        self._save_config(persist_config)
        return self.transport_state()

    def update_developer_playback(self, payload):
        payload = payload or {}
        persist_config = None
        with self._lock:
            merged = dict(self.config)
            if "source" in payload:
                merged["developer_playback_source"] = payload["source"]
            if "snapshot_path" in payload:
                merged["developer_playback_state_path"] = payload["snapshot_path"]
            if "active_playback_source" in payload:
                merged["active_playback_source"] = payload["active_playback_source"]
            previous_active_source = self.config.get("active_playback_source", "legacy")
            self.config = self._clean_config(merged)
            self.developer_playback.configure(self.config["developer_playback_state_path"])
            if self.config["active_playback_source"] != previous_active_source:
                self.developer_playback.reset()
                self._active_playback_signature = None
                self._active_playback_event = "source_switched"
            persist_config = dict(self.config)
        self._save_config(persist_config)
        return self.developer_playback_state()

    def tap(self, now=None):
        now = float(time.time() if now is None else now)
        persist_config = None
        with self._lock:
            if self.tap_times and now - self.tap_times[-1] > 2.5:
                self.tap_times.clear()
                self.manual_tap_locked = False
            self.tap_times.append(now)
            self.last_tap_at = now
            if len(self.tap_times) >= 4:
                recent = list(self.tap_times)[-4:]
                intervals = [
                    recent[index] - recent[index - 1]
                    for index in range(1, len(recent))
                ]
                if intervals and all(0.25 <= interval <= 2.0 for interval in intervals):
                    bpm = 60.0 / (sum(intervals) / len(intervals))
                    align_downbeat = not self.manual_tap_locked
                    self._set_manual_bpm_locked(bpm, now, align_downbeat=align_downbeat)
                    self.manual_tap_locked = True
                    persist_config = dict(self.config)
        if persist_config is not None:
            self._save_config(persist_config)
        return self.transport_state()

    def reset_manual_clock(self):
        with self._lock:
            self.tap_times.clear()
            self.last_tap_at = None
            self.manual_tap_locked = False
            self.manual_clock_anchor_at = None
            self.manual_clock_beat_at_anchor = 0.0
            self.manual_clock_time_at_anchor = 0.0
        return self.transport_state()

    def _resolved_mode(self, selected_mode, external_timing_available, tap_locked, idle_enabled):
        if selected_mode == "external_osc":
            return "external_osc" if external_timing_available else ("manual_tap" if tap_locked else "idle")
        if selected_mode == "manual_tap":
            return "manual_tap" if tap_locked else "idle"
        if external_timing_available:
            return "external_osc"
        if tap_locked:
            return "manual_tap"
        if idle_enabled:
            return "idle"
        return "external_osc"

    def _manual_snapshot(self, now, transport_meta, external_snapshot):
        with self._lock:
            bpm, beat_value, time_seconds = self._manual_clock_state_locked(now)
            manual_phrase = self.config.get("manual_phrase", DEFAULT_MANUAL_PHRASE)
        beat_phase = beat_value % 1.0
        beat_index = int(math.floor(beat_value)) % 4 + 1
        beat_display = beat_index + beat_phase
        phrase_count_in = max(0, 8 - (int(math.floor(beat_value)) % 8))
        waveform = manual_transport_waveform_state(manual_phrase, beat_value)
        snapshot = dict(external_snapshot or {})
        external_audio_fresh = not bool(snapshot.get("stale"))
        external_waveform_energy = snapshot.get("waveform_energy") if external_audio_fresh else None
        external_audio_bands = snapshot.get("audio_bands") if external_audio_fresh else None
        external_waveform_bands = snapshot.get("waveform_bands") if external_audio_fresh else None
        external_waveform_lookahead = snapshot.get("waveform_lookahead") if external_audio_fresh else None
        external_waveform_analysis = snapshot.get("waveform_analysis") if external_audio_fresh else None
        external_audio_drums = snapshot.get("audio_drums") if external_audio_fresh else None
        external_drum_signals = snapshot.get("drum_signals") if external_audio_fresh else None
        snapshot.update(
            {
                "port": self.osc.port,
                "running": True,
                "stale": False,
                "error": None,
                "bpm": bpm,
                "beat": beat_display,
                "beat_value": beat_value,
                "beat_display": beat_display,
                "beat_phase_age_seconds": beat_phase * (60.0 / max(1e-6, bpm)),
                "time_seconds": time_seconds,
                "time_display_seconds": time_seconds,
                "phrase_current": manual_phrase,
                "phrase_next": manual_phrase,
                "phrase_count_in": phrase_count_in,
                "phrase_countdown_beats": float(phrase_count_in),
                "phrase_countdown_seconds": float(phrase_count_in) * 60.0 / max(1e-6, bpm),
                "mood": snapshot.get("mood"),
                "color_bank": snapshot.get("color_bank"),
                "waveform_energy": external_waveform_energy if external_waveform_energy is not None else waveform["energy"],
                "audio_bands": dict(external_audio_bands or waveform["bands"]),
                "waveform_bands": dict(external_waveform_bands or waveform["bands"]),
                "waveform_lookahead": (
                    {
                        "2": dict(((external_waveform_lookahead or {}).get("2")) or waveform["lookahead"]["2"]),
                        "4": dict(((external_waveform_lookahead or {}).get("4")) or waveform["lookahead"]["4"]),
                    }
                ),
                "waveform_analysis": dict(external_waveform_analysis or waveform["analysis"]),
                "audio_drums": dict(external_audio_drums or waveform["drums"]),
                "drum_signals": dict(external_drum_signals or waveform["drums"]),
                "strobe_active": False,
                "strobe_count_in": None,
                "last_beat_at": now - (beat_phase * (60.0 / max(1e-6, bpm))),
                "transport": transport_meta,
            }
        )
        return snapshot

    def _active_snapshot(self, now, external_snapshot):
        external_snapshot = dict(external_snapshot or {})
        with self._lock:
            selected_mode = self.config.get("mode", "auto")
            idle_enabled = bool(self.config.get("idle_animation_enabled", True))
            tap_locked = bool(self.manual_tap_locked)
            manual_bpm = float(self.config.get("manual_bpm", DEFAULT_MANUAL_BPM))
            manual_phrase = self.config.get("manual_phrase", DEFAULT_MANUAL_PHRASE)
            tap_count = self._recent_tap_count_locked(now)
            last_tap_at = self.last_tap_at
        external_fresh = not bool(external_snapshot.get("stale"))
        external_timing_available = bool(
            external_fresh
            and external_snapshot.get("bpm")
            and (
                external_snapshot.get("beat_display") is not None
                or external_snapshot.get("beat") is not None
            )
        )
        resolved_mode = self._resolved_mode(
            selected_mode,
            external_timing_available,
            tap_locked,
            idle_enabled,
        )
        transport_meta = {
            "mode": selected_mode,
            "resolved_mode": resolved_mode,
            "manual_bpm": manual_bpm,
            "effective_bpm": external_snapshot.get("bpm") if resolved_mode == "external_osc" else manual_bpm,
            "manual_phrase": manual_phrase,
            "manual_phrase_label": auto_show_phrase_override_label(manual_phrase),
            "idle_animation_enabled": idle_enabled,
            "tap_count": tap_count,
            "tap_locked": tap_locked,
            "external_available": external_fresh,
            "external_timing_available": external_timing_available,
            "last_tap_at": last_tap_at,
        }
        if resolved_mode == "external_osc":
            external_snapshot["transport"] = transport_meta
            return external_snapshot
        return self._manual_snapshot(now, transport_meta, external_snapshot)

    def snapshot_for_render(self):
        now = time.time()
        external_snapshot = self.osc.snapshot_for_render()
        return self._active_render_snapshot(now, external_snapshot)

    def state(self):
        now = time.time()
        external_state = self.osc.state()
        return self._active_render_snapshot(now, external_state)

    def _active_render_snapshot(self, now, legacy_snapshot):
        with self._lock:
            configured_source = self.config.get("active_playback_source", "legacy")
            selected_mode = self.config.get("mode", "auto")
        playback_state = self.developer_playback.state()
        virtualdj_available = playback_state.get("availability") == "available"
        active_source = "virtualdj" if configured_source == "virtualdj" or (
            selected_mode == "auto" and virtualdj_available
        ) else "legacy"
        if active_source == "virtualdj":
            # Start with the existing transport contract so native clients keep
            # receiving its required mode and manual-clock fields. VirtualDJ
            # below replaces only the active timing source.
            snapshot = self._virtualdj_render_snapshot(
                self._active_snapshot(now, legacy_snapshot), playback_state
            )
        else:
            snapshot = self._active_snapshot(now, legacy_snapshot)
        return self._annotate_active_playback(snapshot, active_source)

    @staticmethod
    def _virtualdj_track_title(track_path):
        path = str(track_path or "").strip()
        if not path:
            return None
        return Path(path).stem or None

    def _virtualdj_render_snapshot(self, legacy_snapshot, playback_state):
        """Project the accepted generic clock onto the existing render contract.

        The legacy snapshot still owns fresh waveform and phrase inputs. A
        VirtualDJ path has no safe metadata-to-analysis mapping in the current cache, so
        track-specific plans stay disabled unless a future cache stores that
        exact path.
        """
        snapshot = dict(legacy_snapshot or {})
        legacy_structure_available = not bool(snapshot.get("stale"))
        beatbeam = dict((playback_state or {}).get("beatbeam") or {})
        available = (
            (playback_state or {}).get("availability") == "available"
            and bool(beatbeam.get("track_path"))
            and isinstance(beatbeam.get("bpm"), (int, float))
        )
        transport = dict(snapshot.get("transport") or {})
        transport.update(
            {
                "active_playback_source": "virtualdj",
                "active_source_available": available,
                "active_source_transport_state": (playback_state or {}).get("transport_state"),
                "active_source_selection": (playback_state or {}).get("selection"),
            }
        )
        if not available:
            snapshot.update(
                {
                    "bpm": None,
                    "beat": None,
                    "beat_value": None,
                    "beat_display": None,
                    "beat_phase_age_seconds": None,
                    "time_seconds": None,
                    "time_display_seconds": None,
                    "track_path": None,
                    "track_title": None,
                    "track_artist": None,
                    "track_album": None,
                    "phrase_current": None,
                    "phrase_next": None,
                    "strobe_active": False,
                    "strobe_count_in": None,
                    "stale": True,
                    "transport": transport,
                    "playback_state": playback_state,
                    "decks": (playback_state or {}).get("decks"),
                }
            )
            return snapshot

        bpm = float(beatbeam["bpm"])
        beat_value = beatbeam.get("beat_position")
        beat_number = beatbeam.get("beat_number")
        beat_phase = beatbeam.get("beat_phase")
        if not isinstance(beat_phase, (int, float)):
            try:
                beat_phase = float(beat_value) % 1.0
            except (TypeError, ValueError):
                beat_phase = 0.0
        beat_display = (
            beat_number + float(beat_phase)
            if isinstance(beat_number, int) and 1 <= beat_number <= 4
            else None
        )
        position_milliseconds = beatbeam.get("estimated_position_milliseconds")
        time_seconds = (
            float(position_milliseconds) / 1000.0
            if isinstance(position_milliseconds, (int, float))
            else None
        )
        track_path = str(beatbeam.get("track_path") or "").strip()
        transport.update(
            {
                "resolved_mode": "virtualdj",
                "effective_bpm": bpm,
                "virtualdj_deck_number": beatbeam.get("deck_number"),
                "virtualdj_track_path": track_path,
                "virtualdj_bar_number": beatbeam.get("bar_number"),
                "virtualdj_beat_number": beat_number,
            }
        )
        snapshot.update(
            {
                "bpm": bpm,
                "beat": beat_display,
                "beat_value": beat_value,
                "beat_display": beat_display,
                "beat_phase_age_seconds": float(beat_phase) * 60.0 / max(1e-6, bpm),
                "time_seconds": time_seconds,
                "time_display_seconds": time_seconds,
                "track_path": track_path,
                "track_title": self._virtualdj_track_title(track_path),
                "track_artist": None,
                "track_album": None,
                # Preserve the existing structure source only while it is fresh.
                # A stale source must never leak an old track's phrase state.
                "phrase_current": snapshot.get("phrase_current") if legacy_structure_available else None,
                "phrase_next": snapshot.get("phrase_next") if legacy_structure_available else None,
                "stale": False,
                "transport": transport,
                "playback_state": playback_state,
                "decks": (playback_state or {}).get("decks"),
            }
        )
        return snapshot

    def _annotate_active_playback(self, snapshot, active_source):
        playback_state = snapshot.get("playback_state") or {}
        if active_source == "virtualdj":
            beatbeam = playback_state.get("beatbeam") or {}
            signature = (
                active_source,
                playback_state.get("availability"),
                beatbeam.get("deck_number"),
                beatbeam.get("track_path"),
                playback_state.get("last_discontinuity"),
            )
            event = playback_state.get("last_discontinuity") or "virtualdj_active"
        else:
            signature = (
                active_source,
                snapshot.get("track_title"),
                snapshot.get("track_artist"),
                snapshot.get("track_album"),
            )
            event = "legacy_active"
        with self._lock:
            if signature != self._active_playback_signature:
                if (
                    self._last_active_playback_source is not None
                    and active_source != self._last_active_playback_source
                ):
                    self._active_playback_source_switches += 1
                if event not in {"legacy_active", "virtualdj_active", "source_switched"}:
                    self._active_playback_discontinuities += 1
                self._active_playback_generation += 1
                self._active_playback_signature = signature
                self._active_playback_event = event
                self._last_active_playback_source = active_source
            generation = self._active_playback_generation
            current_event = self._active_playback_event
        snapshot["_active_playback_source"] = active_source
        snapshot["_playback_generation"] = generation
        snapshot["_playback_event"] = current_event
        return snapshot

    def transport_state(self):
        state = self.state()
        return dict(state.get("transport") or {})

    def structure_behavior_source(self):
        with self._lock:
            return self.config.get("structure_behavior_source", "legacy")

    def developer_playback_state(self, current_state=None):
        with self._lock:
            source = self.config.get("developer_playback_source", "current")
        if source == "virtualdj":
            return self.developer_playback.state()
        current_state = dict(current_state or self.state())
        bpm = current_state.get("bpm")
        beat_display = current_state.get("beat_display")
        beat_number = None
        if isinstance(beat_display, (int, float)):
            beat_number = int(math.floor(beat_display))
            beat_number = beat_number if 1 <= beat_number <= 4 else None
        return {
            "source": "current",
            "availability": "available" if bpm else "unavailable",
            "transport_state": "current",
            "virtualdj": None,
            "beatbeam": {
                "track_path": None,
                "estimated_position_milliseconds": (
                    int(round(float(current_state["time_display_seconds"]) * 1000.0))
                    if current_state.get("time_display_seconds") is not None
                    else None
                ),
                "bpm": bpm,
                "beat_position": current_state.get("beat_value"),
                "beat_number": beat_number,
                "bar_number": None,
                "first_beat_milliseconds": None,
                "deck_number": None,
            },
            "delta": {
                "position_milliseconds": None,
                "beat_agreement": None,
                "bar_agreement": None,
            },
            "metrics": {
                "snapshot_interval_milliseconds": None,
                "extrapolation_milliseconds": None,
                "accepted_snapshots": 0,
                "invalid_snapshots": 0,
                "discontinuities": 0,
                "reconnects": 0,
            },
            "last_discontinuity": None,
            "selection": None,
        }

    def source_state(self):
        state = self.state()
        transport = state.get("transport") or {}
        active_source = str(transport.get("active_playback_source") or "legacy")
        if active_source == "virtualdj":
            playback = state.get("playback_state") or {}
            beatbeam = playback.get("beatbeam") or {}
            return {
                "mode": transport.get("mode") or "auto",
                "resolved_mode": "virtualdj",
                "active_playback_source": "virtualdj",
                "app": "VirtualDJ",
                "port": None,
                "expected_destination": "MusicAnalyzer playback snapshot",
                "last_source": None,
                "available": playback.get("availability") == "available",
                "deck_number": beatbeam.get("deck_number"),
                "track_path": beatbeam.get("track_path"),
                "playback_generation": state.get("_playback_generation"),
                "source_switches": self._active_playback_source_switches,
                "discontinuities": self._active_playback_discontinuities,
            }
        resolved_mode = str(transport.get("resolved_mode") or "external_osc")
        if resolved_mode == "external_osc":
            app = "External OSC / Rekordbox"
            expected_destination = f"127.0.0.1:{self.osc.port}"
            last_source = (state.get("last_message") or {}).get("source")
        else:
            app = "BeatBeam Internal Clock"
            expected_destination = "internal"
            last_source = None
        return {
            "mode": transport.get("mode") or "auto",
            "resolved_mode": resolved_mode,
            "app": app,
            "port": self.osc.port,
            "expected_destination": expected_destination,
            "last_source": last_source,
            "active_playback_source": "legacy",
            "available": not bool(state.get("stale")),
            "playback_generation": state.get("_playback_generation"),
            "source_switches": self._active_playback_source_switches,
            "discontinuities": self._active_playback_discontinuities,
        }


class DmxController:
    def __init__(self, osc_listener, structure_behavior_bridge=None):
        self.osc = osc_listener
        self.structure_behavior_bridge = structure_behavior_bridge
        self.debug_log = TRIGGER_LOG
        self.lock = threading.Lock()
        self.dmx_send_lock = threading.Lock()
        self.dmx = None
        self.thread = None
        self.running = False
        self.connected = False
        self.port = None
        self.fps = DEFAULT_DMX_FPS
        self.error = None
        self.dmx_dispatch_failures = 0
        self.last_sent = None
        self.current_values = {}
        self.current_slot_previews = {}
        self.conflicts = []
        self.motion_states = {}
        self.slot_rhythm_states = {}
        self.save_timer = None
        self.last_auto_show_signature = None
        self.last_slot_trigger_signatures = {}
        self.last_slot_rhythm_signatures = {}
        self.last_slot_strobe_outputs = {}
        self.outro_behavior_state = None
        self.active_one_shot_cue = None
        self.track_preview_summaries = {}
        self.track_show_plans = {}
        self.track_path_plan_cache = {}
        self.last_track_plan_prewarm_at = 0.0
        self.last_playback_generation = None
        self.last_structure_behavior_source = None
        self.playback_runtime_resets = 0
        self.active_virtualdj_beat_pulse = None
        self.active_virtualdj_beat_pulse_preview = None
        self.config = self._load_config()
        self.virtualdj_beat_pulse_scheduler = VirtualDjBeatPulseScheduler(
            self._dispatch_virtualdj_beat_pulse,
            self._cancel_virtualdj_beat_pulse,
        )
        # This uses the same accepted VirtualDJ clock path as the DMX test, but
        # only changes the native application's preview payload.
        self.virtualdj_beat_pulse_preview_scheduler = VirtualDjBeatPulseScheduler(
            self._dispatch_virtualdj_beat_pulse_preview,
            self._cancel_virtualdj_beat_pulse_preview,
        )

    @staticmethod
    def default_config():
        return {
            "active_slot": "head",
            "blackout_active": False,
            "auto_show": DmxController.default_auto_show_config(),
            "slot_order": ["head", "par"],
            "slots": {
                "head": DmxController.default_slot_config("head"),
                "par": DmxController.default_slot_config("par"),
            },
        }

    @staticmethod
    def default_auto_show_config():
        default_turn_min, default_turn_max = _default_turn_audience_pan_limits(135, 205)
        return {
            "enabled": False,
            "style": "adaptive",
            "audience_pan_focus_enabled": True,
            "audience_pan_min": 135,
            "audience_pan_max": 205,
            "audience_turn_pan_min": default_turn_min,
            "audience_turn_pan_max": default_turn_max,
            "audience_tilt_split": 127,
            "override_phrase": "none",
            "override_color": "none",
            "override_energy": "none",
            "override_manual_strobe": False,
            "override_audience_sweep": False,
            "override_all_on": False,
            "override_par_chase": False,
            "override_par_snake": False,
        }

    @staticmethod
    def default_slot_config(slot_id, fixture_id=None, label=None, address=None, mode=None):
        common = {
            "enabled": True,
            "color": {"red": 255, "green": 0, "blue": 0, "white": 0},
            "dimmer": 255,
            "strobe": 0,
            "program": 0,
            "speed": 0,
            "extra_values": {},
            "pan": 127,
            "tilt": 127,
            "pan_tilt_speed": 0,
            "sync_enabled": True,
            "beat_pulse_enabled": True,
            "beat_depth": 65,
            "beat_decay_ms": 180,
            "color_source": "manual",
            "osc_strobe_enabled": True,
            "use_fine_pan_tilt": True,
            "pan_invert": False,
            "tilt_invert": False,
            "pan_offset_deg": 0,
            "tilt_offset_deg": 0,
            "pan_span_percent": 100,
            "tilt_span_percent": 100,
            "pan_left_value": None,
            "pan_right_value": None,
            "tilt_back_value": None,
            "tilt_front_value": None,
            "pose_center": None,
            "pose_audience_left": None,
            "pose_audience_center": None,
            "pose_audience_right": None,
            "pose_ceiling_center": None,
        }
        if fixture_id is None:
            fixture_id = (
                "shehds_led_wash_7x12w_rgbw_moving_head"
                if slot_id == "head"
                else "shehds_flat_par_12x3w_rgbw"
            )
        preset = fixture_preset(fixture_id)
        common.update(
            {
                "label": label or preset["label_base"],
                "fixture": fixture_id,
                "mode": mode or preset["mode"],
                "address": address if address is not None else (30 if fixture_id == "shehds_led_wash_7x12w_rgbw_moving_head" else 1),
            }
        )
        common["group"] = default_group_name_for_slot(
            slot_id,
            fixture_id,
            common["label"],
        )
        for key in (
            "color",
            "dimmer",
            "strobe",
            "program",
            "speed",
            "pan",
            "tilt",
            "pan_tilt_speed",
            "sync_enabled",
            "beat_pulse_enabled",
            "beat_depth",
            "beat_decay_ms",
            "color_source",
            "osc_strobe_enabled",
            "use_fine_pan_tilt",
        ):
            if key in preset:
                common[key] = preset[key]
        return common

    def start_virtualdj_beat_pulse_test(self, payload=None):
        payload = payload or {}
        slot_id = str(payload.get("slot_id") or "").strip()
        if not slot_id:
            raise ValueError("Kies een bestaande fixture-slot voor de VirtualDJ Beat Pulse Test.")
        raw_duration = payload.get(
            "duration_milliseconds",
            DEFAULT_VIRTUALDJ_BEAT_PULSE_DURATION_MILLISECONDS,
        )
        try:
            duration_milliseconds = int(raw_duration)
        except (TypeError, ValueError) as exc:
            raise ValueError("Pulseduur moet een geheel aantal milliseconden zijn.") from exc
        duration_milliseconds = max(
            MINIMUM_VIRTUALDJ_BEAT_PULSE_DURATION_MILLISECONDS,
            min(MAXIMUM_VIRTUALDJ_BEAT_PULSE_DURATION_MILLISECONDS, duration_milliseconds),
        )

        with self.lock:
            if not self.connected or not self.running or self.dmx is None:
                raise ValueError("Verbind eerst de bestaande DMX-output voordat je de Beat Pulse Test start.")
            config = self._clean_full_config(dict(self.config))
            if config["blackout_active"]:
                raise ValueError("Schakel blackout uit voordat je de Beat Pulse Test start.")
            self._virtualdj_pulse_channels_locked(config, slot_id)

        playback_state = self.osc.developer_playback_state()
        if playback_state.get("source") != "virtualdj":
            raise ValueError("Selecteer eerst VirtualDJ als developer playback-bron.")
        self.virtualdj_beat_pulse_scheduler.start(slot_id, duration_milliseconds)
        self.virtualdj_beat_pulse_scheduler.observe(playback_state)
        self.debug_log.log(
            "VIRTUALDJ_BEAT_PULSE_START",
            slot=slot_id,
            duration_milliseconds=duration_milliseconds,
        )
        return self.virtualdj_beat_pulse_scheduler.state()

    def stop_virtualdj_beat_pulse_test(self):
        state = self.virtualdj_beat_pulse_scheduler.stop("stopped_by_user")
        self.debug_log.log("VIRTUALDJ_BEAT_PULSE_STOP")
        return state

    def virtualdj_beat_pulse_test_state(self):
        return self.virtualdj_beat_pulse_scheduler.state()

    def start_virtualdj_beat_pulse_preview_test(self, payload=None):
        payload = payload or {}
        slot_id = str(payload.get("slot_id") or "").strip()
        if not slot_id:
            raise ValueError("Kies een bestaande fixture-slot voor de VirtualDJ Beat Pulse Preview.")
        raw_duration = payload.get(
            "duration_milliseconds",
            DEFAULT_VIRTUALDJ_BEAT_PULSE_DURATION_MILLISECONDS,
        )
        try:
            duration_milliseconds = int(raw_duration)
        except (TypeError, ValueError) as exc:
            raise ValueError("Pulseduur moet een geheel aantal milliseconden zijn.") from exc
        duration_milliseconds = max(
            MINIMUM_VIRTUALDJ_BEAT_PULSE_DURATION_MILLISECONDS,
            min(MAXIMUM_VIRTUALDJ_BEAT_PULSE_DURATION_MILLISECONDS, duration_milliseconds),
        )

        with self.lock:
            config = self._clean_full_config(dict(self.config))
            self._virtualdj_pulse_channels_locked(config, slot_id)

        playback_state = self.osc.developer_playback_state()
        if playback_state.get("source") != "virtualdj":
            raise ValueError("Selecteer eerst VirtualDJ als developer playback-bron.")
        self.virtualdj_beat_pulse_preview_scheduler.start(slot_id, duration_milliseconds)
        self.virtualdj_beat_pulse_preview_scheduler.observe(playback_state)
        self.debug_log.log(
            "VIRTUALDJ_BEAT_PULSE_PREVIEW_START",
            slot=slot_id,
            duration_milliseconds=duration_milliseconds,
        )
        return self.virtualdj_beat_pulse_preview_test_state()

    def stop_virtualdj_beat_pulse_preview_test(self):
        state = self.virtualdj_beat_pulse_preview_scheduler.stop("stopped_by_user")
        self.debug_log.log("VIRTUALDJ_BEAT_PULSE_PREVIEW_STOP")
        return self.virtualdj_beat_pulse_preview_test_state(state)

    def virtualdj_beat_pulse_preview_test_state(self, scheduler_state=None):
        state = dict(scheduler_state or self.virtualdj_beat_pulse_preview_scheduler.state())
        state["mode"] = "preview_only"
        state["physical_dmx_output"] = False
        return state

    def _virtualdj_pulse_channels_locked(self, config, slot_id):
        slot_config = (config.get("slots") or {}).get(slot_id)
        if not isinstance(slot_config, dict):
            raise ValueError("Het gekozen fixture-slot bestaat niet.")
        if not slot_config.get("enabled"):
            raise ValueError("Het gekozen fixture-slot is uitgeschakeld.")
        fixture = find_fixture(FIXTURE_LIBRARY, slot_config["fixture"])
        mode = find_mode(fixture, slot_config["mode"])
        address = int(slot_config["address"])
        channels = tuple(
            address + int(channel["offset"]) - 1
            for channel in mode["channels"]
            if channel.get("type") == "intensity"
        )
        if not channels:
            raise ValueError("Het gekozen fixtureprofiel heeft geen veilige dimmer/intensity-kanaalroute.")
        return channels

    def _observe_virtualdj_beat_pulse_test(self, playback_state):
        self.virtualdj_beat_pulse_scheduler.observe(playback_state)

    def _observe_virtualdj_beat_pulse_preview_test(self, playback_state):
        self.virtualdj_beat_pulse_preview_scheduler.observe(playback_state)

    def _apply_virtualdj_beat_pulse_overlay_locked(self, values):
        active = self.active_virtualdj_beat_pulse
        if not active:
            return values
        output = dict(values)
        for channel in active["channels"]:
            output[channel] = 255
        return output

    def _apply_virtualdj_beat_pulse_preview_overlay_locked(self, slot_previews):
        active = self.active_virtualdj_beat_pulse_preview
        if not active or time.monotonic() >= active["expires_at_monotonic_seconds"]:
            return slot_previews
        slot_id = active["slot_id"]
        preview = slot_previews.get(slot_id)
        if not isinstance(preview, dict):
            return slot_previews

        # Deliberately use an unmistakable white flash. This is a visual timing
        # simulator only; it neither reuses nor changes the DMX output frame.
        output = dict(slot_previews)
        output[slot_id] = {
            **preview,
            "red": 255,
            "green": 255,
            "blue": 255,
            "white": 255,
            "brightness": 255,
            "strobe": 0,
            "strobe_active": False,
            "strobe_external": False,
            "developer_virtualdj_beat_pulse_preview": True,
        }
        return output

    def _send_dmx_frame(self, dmx, values):
        with self.dmx_send_lock:
            dispatched_at = playback_system_monotonic_time()
            dmx.send(values)
            return dispatched_at

    def _dispatch_virtualdj_beat_pulse(self, plan, generation, is_current):
        if not is_current(plan, generation):
            return None
        slot_id = self.virtualdj_beat_pulse_scheduler.state()["slot_id"]
        with self.lock:
            if not is_current(plan, generation) or not self.connected or not self.running or self.dmx is None:
                return None
            config = self._clean_full_config(dict(self.config))
            if config["blackout_active"]:
                return None
            try:
                channels = self._virtualdj_pulse_channels_locked(config, slot_id)
            except Exception as exc:
                self.error = str(exc)
                return None
            baseline_values = dict(self.current_values)
            if not baseline_values:
                render_now = time.time()
                osc = self.osc.snapshot_for_render()
                auto_show = self._auto_show_state(osc, config["auto_show"])
                baseline_values = self._render_values(
                    render_now,
                    config=config,
                    osc=osc,
                    auto_show=auto_show,
                )
                self.current_values = dict(baseline_values)
            pulse_values = dict(baseline_values)
            for channel in channels:
                pulse_values[channel] = 255
            dmx = self.dmx
            self.active_virtualdj_beat_pulse = {
                "identity": plan.identity,
                "channels": channels,
                "baseline_values": baseline_values,
                "expires_at_monotonic_seconds": (
                    float(plan.deadline_monotonic_seconds)
                    + (float(plan.duration_milliseconds) / 1000.0)
                ),
                "restore_timer": None,
            }

            try:
                dispatched_at = self._send_dmx_frame(dmx, pulse_values)
            except Exception as exc:
                if self.active_virtualdj_beat_pulse and self.active_virtualdj_beat_pulse["identity"] == plan.identity:
                    self.active_virtualdj_beat_pulse = None
                self.error = str(exc)
                with suppress(Exception):
                    self._send_dmx_frame(dmx, baseline_values)
                self.debug_log.log("VIRTUALDJ_BEAT_PULSE_DISPATCH_FAILED", error=str(exc))
                return None

        restore_timer = threading.Timer(
            float(plan.duration_milliseconds) / 1000.0,
            self._restore_virtualdj_beat_pulse,
            args=(plan.identity, "pulse_complete"),
        )
        restore_timer.daemon = True
        with self.lock:
            active = self.active_virtualdj_beat_pulse
            if active is None or active["identity"] != plan.identity:
                return dispatched_at
            active["restore_timer"] = restore_timer
        restore_timer.start()
        self.debug_log.log(
            "VIRTUALDJ_BEAT_PULSE_DISPATCH",
            deck=plan.deck_number,
            bar=plan.bar_number,
            deadline_monotonic_milliseconds=int(round(plan.deadline_monotonic_seconds * 1000.0)),
            dispatch_monotonic_milliseconds=int(round(dispatched_at * 1000.0)),
            error_milliseconds=(dispatched_at - plan.deadline_monotonic_seconds) * 1000.0,
        )
        return dispatched_at

    def _restore_virtualdj_beat_pulse(self, identity, reason):
        with self.lock:
            active = self.active_virtualdj_beat_pulse
            if active is None or active["identity"] != identity:
                return
            self.active_virtualdj_beat_pulse = None
            timer = active.get("restore_timer")
            if timer is not None and timer is not threading.current_thread():
                timer.cancel()
            dmx = self.dmx
            baseline_values = dict(active["baseline_values"])
            if dmx is None or reason in {"blackout", "dmx_disconnected"}:
                return
            try:
                self._send_dmx_frame(dmx, baseline_values)
                self.debug_log.log("VIRTUALDJ_BEAT_PULSE_RESTORE", reason=reason)
            except Exception as exc:
                self.error = str(exc)
                self.debug_log.log("VIRTUALDJ_BEAT_PULSE_RESTORE_FAILED", error=str(exc))

    def _cancel_virtualdj_beat_pulse(self, reason):
        with self.lock:
            active = self.active_virtualdj_beat_pulse
            identity = None if active is None else active["identity"]
        if identity is not None:
            self._restore_virtualdj_beat_pulse(identity, reason)

    def _dispatch_virtualdj_beat_pulse_preview(self, plan, generation, is_current):
        if not is_current(plan, generation):
            return None
        slot_id = self.virtualdj_beat_pulse_preview_scheduler.state()["slot_id"]
        with self.lock:
            if not is_current(plan, generation):
                return None
            config = self._clean_full_config(dict(self.config))
            try:
                self._virtualdj_pulse_channels_locked(config, slot_id)
            except Exception as exc:
                self.error = str(exc)
                return None
            dispatched_at = playback_system_monotonic_time()
            self.active_virtualdj_beat_pulse_preview = {
                "identity": plan.identity,
                "slot_id": slot_id,
                "expires_at_monotonic_seconds": (
                    float(plan.deadline_monotonic_seconds)
                    + (float(plan.duration_milliseconds) / 1000.0)
                ),
                "restore_timer": None,
            }

        restore_timer = threading.Timer(
            float(plan.duration_milliseconds) / 1000.0,
            self._clear_virtualdj_beat_pulse_preview,
            args=(plan.identity, "preview_complete"),
        )
        restore_timer.daemon = True
        with self.lock:
            active = self.active_virtualdj_beat_pulse_preview
            if active is None or active["identity"] != plan.identity:
                return dispatched_at
            active["restore_timer"] = restore_timer
        restore_timer.start()
        self.debug_log.log(
            "VIRTUALDJ_BEAT_PULSE_PREVIEW_DISPATCH",
            deck=plan.deck_number,
            bar=plan.bar_number,
            deadline_monotonic_milliseconds=int(round(plan.deadline_monotonic_seconds * 1000.0)),
            dispatch_monotonic_milliseconds=int(round(dispatched_at * 1000.0)),
            error_milliseconds=(dispatched_at - plan.deadline_monotonic_seconds) * 1000.0,
        )
        return dispatched_at

    def _clear_virtualdj_beat_pulse_preview(self, identity, reason):
        with self.lock:
            active = self.active_virtualdj_beat_pulse_preview
            if active is None or active["identity"] != identity:
                return
            self.active_virtualdj_beat_pulse_preview = None
            timer = active.get("restore_timer")
            if timer is not None and timer is not threading.current_thread():
                timer.cancel()
        self.debug_log.log("VIRTUALDJ_BEAT_PULSE_PREVIEW_CLEAR", reason=reason)

    def _cancel_virtualdj_beat_pulse_preview(self, reason):
        with self.lock:
            active = self.active_virtualdj_beat_pulse_preview
            identity = None if active is None else active["identity"]
        if identity is not None:
            self._clear_virtualdj_beat_pulse_preview(identity, reason)


    def _preview_track_candidates(self, osc):
        candidates = {}

        def add_candidate(track_title=None, track_artist=None, track_album=None):
            title = str(track_title or "").strip()
            artist = str(track_artist or "").strip()
            album = str(track_album or "").strip()
            if not any(value and value != "-" for value in (title, artist, album)):
                return
            cache_key = track_preview_cache_key(title, artist, album)
            candidates[cache_key] = (title, artist, album)

        add_candidate(
            osc.get("track_title"),
            osc.get("track_artist"),
            osc.get("track_album"),
        )

        with self.osc.lock:
            deck_states = [
                dict(deck_state or {})
                for _deck_id, deck_state in sorted(
                    self.osc.decks.items(),
                    key=lambda item: (
                        0,
                        int(item[0]),
                    )
                    if str(item[0]).isdigit()
                    else (1, str(item[0])),
                )
            ]

        for deck_state in deck_states:
            add_candidate(
                deck_state.get("track_title"),
                deck_state.get("track_artist"),
                deck_state.get("track_album"),
            )

        return list(candidates.values())

    @staticmethod
    def _same_track_path(left, right):
        return str(left or "").strip() == str(right or "").strip()

    def _load_track_preview_summary(
        self,
        track_title=None,
        track_artist=None,
        track_album=None,
    ):
        cache_key = track_preview_cache_key(track_title, track_artist, track_album)
        cache_path = track_preview_summary_path(track_title, track_artist, track_album)
        try:
            cache_mtime = cache_path.stat().st_mtime
        except FileNotFoundError:
            cache_mtime = None
        except OSError:
            cache_mtime = None

        cached_entry = self.track_preview_summaries.get(cache_key)
        if cached_entry and cached_entry.get("mtime") == cache_mtime:
            return cached_entry.get("summary")

        if cache_mtime is None:
            self.track_preview_summaries[cache_key] = {"mtime": None, "summary": None}
            stale_plan_keys = [
                plan_key
                for plan_key in self.track_show_plans.keys()
                if plan_key[0] == cache_key
            ]
            for plan_key in stale_plan_keys:
                self.track_show_plans.pop(plan_key, None)
            return None

        summary = None
        try:
            with cache_path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict) and isinstance(loaded.get("segments"), list):
                loaded.setdefault("cache_key", cache_key)
                loaded.setdefault(
                    "identity",
                    track_preview_identity(track_title, track_artist, track_album),
                )
                loaded.setdefault("dense_samples", [])
                summary = loaded
        except Exception as exc:
            self.debug_log.log(
                "TRACK_PREVIEW_LOAD_ERROR",
                key=cache_key,
                error=str(exc),
            )

        self.track_preview_summaries[cache_key] = {
            "mtime": cache_mtime,
            "summary": summary,
        }

        stale_plan_keys = [
            plan_key
            for plan_key, plan_entry in self.track_show_plans.items()
            if plan_key[0] == cache_key
            and plan_entry.get("summary_mtime") != cache_mtime
        ]
        for plan_key in stale_plan_keys:
            self.track_show_plans.pop(plan_key, None)

        return summary

    def _all_track_preview_summaries(self):
        summaries = []
        path_map = {}
        for cache_dir in _track_preview_cache_dirs():
            try:
                raw_paths = sorted(cache_dir.glob("*.json"))
            except Exception:
                continue
            for path in raw_paths:
                cache_key = path.stem
                try:
                    cache_mtime = path.stat().st_mtime
                except OSError:
                    continue
                current = path_map.get(cache_key)
                if current is None or cache_mtime >= current[0]:
                    path_map[cache_key] = (cache_mtime, path)
        paths = [item[1] for item in sorted(path_map.values(), key=lambda item: item[1].stem)]
        for path in paths:
            cache_key = path.stem
            try:
                cache_mtime = path.stat().st_mtime
            except OSError:
                continue
            cached_entry = self.track_preview_summaries.get(cache_key)
            if cached_entry and cached_entry.get("mtime") == cache_mtime:
                summary = cached_entry.get("summary")
            else:
                summary = None
                try:
                    with path.open("r", encoding="utf-8") as handle:
                        loaded = json.load(handle)
                    if isinstance(loaded, dict) and isinstance(loaded.get("segments"), list):
                        loaded.setdefault("cache_key", cache_key)
                        loaded.setdefault("dense_samples", [])
                        summary = loaded
                except Exception:
                    summary = None
                self.track_preview_summaries[cache_key] = {
                    "mtime": cache_mtime,
                    "summary": summary,
                }
            if summary:
                summaries.append(summary)
        return summaries

    def _preview_summary_segment_for_seconds(self, preview_summary, current_seconds):
        try:
            current_seconds = max(0.0, float(current_seconds))
        except (TypeError, ValueError):
            return None
        segments = preview_summary.get("segments") or []
        if not segments:
            return None
        selected = segments[-1]
        for segment in segments:
            start_seconds = float(segment.get("start_seconds") or 0.0)
            end_seconds = float(segment.get("end_seconds") or start_seconds)
            if current_seconds < start_seconds:
                selected = segment
                break
            if start_seconds <= current_seconds < end_seconds:
                selected = segment
                break
        return selected

    def _preview_summary_dense_sample_for_seconds(self, preview_summary, current_seconds):
        try:
            current_seconds = max(0.0, float(current_seconds))
        except (TypeError, ValueError):
            return None
        dense_samples = preview_summary.get("dense_samples") or []
        if not dense_samples:
            return None
        previous = None
        for sample in dense_samples:
            try:
                sample_seconds = max(0.0, float(sample.get("seconds") or 0.0))
            except (TypeError, ValueError):
                continue
            if current_seconds <= sample_seconds:
                if previous is None:
                    return sample
                try:
                    previous_seconds = max(0.0, float(previous.get("seconds") or 0.0))
                except (TypeError, ValueError):
                    return sample
                if abs(current_seconds - previous_seconds) <= abs(sample_seconds - current_seconds):
                    return previous
                return sample
            previous = sample
        return previous

    def _preview_summary_signal_for_seconds(self, preview_summary, current_seconds):
        return self._preview_summary_dense_sample_for_seconds(
            preview_summary,
            current_seconds,
        ) or self._preview_summary_segment_for_seconds(preview_summary, current_seconds)

    def _preview_summary_match_score(self, preview_summary, osc_like):
        current_seconds = osc_like.get("time_display_seconds")
        if current_seconds is None:
            current_seconds = osc_like.get("time_seconds")
        try:
            current_seconds = (
                None if current_seconds is None else max(0.0, float(current_seconds))
            )
        except (TypeError, ValueError):
            current_seconds = None
        if current_seconds is None:
            return None

        duration_seconds = float(preview_summary.get("duration_seconds") or 0.0)
        if duration_seconds <= 0.0:
            return None

        time_penalty = 0.0
        if current_seconds > duration_seconds:
            time_penalty = min(1.0, (current_seconds - duration_seconds) / 18.0)

        signal = self._preview_summary_signal_for_seconds(
            preview_summary,
            min(current_seconds, duration_seconds),
        )
        if not signal:
            return None

        score = 0.55 - time_penalty * 0.70
        band_state = osc_like.get("waveform_bands") or {}
        segment_pairs = [
            (band_state.get("low"), signal.get("low")),
            (band_state.get("mid"), signal.get("mid")),
            (band_state.get("high"), signal.get("high")),
        ]
        diffs = []
        for current_value, segment_value in segment_pairs:
            if current_value is None or segment_value is None:
                continue
            try:
                diffs.append(abs(float(current_value) - float(segment_value)))
            except (TypeError, ValueError):
                continue
        if diffs:
            score += max(0.0, 1.0 - (sum(diffs) / len(diffs))) * 0.95

        current_energy = osc_like.get("waveform_energy")
        if current_energy is not None and signal.get("energy") is not None:
            try:
                score += max(
                    0.0,
                    1.0 - abs(float(current_energy) - float(signal.get("energy"))),
                ) * 0.35
            except (TypeError, ValueError):
                pass

        phrase_now = phrase_bucket(osc_like.get("phrase_current"))
        phrase_segment = phrase_bucket(signal.get("phrase"))
        if phrase_now != "unknown":
            if phrase_now == phrase_segment:
                score += 0.35
            elif phrase_now in {"break", "down"} and phrase_segment in {"break", "down"}:
                score += 0.20
            elif phrase_now == "outro" and phrase_segment in {"outro", "down", "break"}:
                score += 0.20
            else:
                score -= 0.12

        lookahead_state = osc_like.get("waveform_lookahead") or {}
        lookahead_2 = lookahead_state.get("2") or {}
        if any(lookahead_2.get(key) is not None for key in ("low", "mid", "high")):
            next_signal = None
            try:
                bpm = float(osc_like.get("bpm") or 0.0)
            except (TypeError, ValueError):
                bpm = 0.0
            if bpm > 0.0:
                next_signal = self._preview_summary_signal_for_seconds(
                    preview_summary,
                    min(duration_seconds, current_seconds + (120.0 / bpm)),
                )
            if next_signal is None:
                next_index = min(
                    len(preview_summary.get("segments") or []) - 1,
                    int(self._preview_summary_segment_for_seconds(preview_summary, min(current_seconds, duration_seconds)).get("index") or 0) + 1,
                )
                next_signal = (preview_summary.get("segments") or [signal])[next_index]
            diffs = []
            for key in ("low", "mid", "high"):
                current_value = lookahead_2.get(key)
                next_value = next_signal.get(key)
                if current_value is None or next_value is None:
                    continue
                try:
                    diffs.append(abs(float(current_value) - float(next_value)))
                except (TypeError, ValueError):
                    continue
            if diffs:
                score += max(0.0, 1.0 - (sum(diffs) / len(diffs))) * 0.45

        lookahead_4 = lookahead_state.get("4") or {}
        if any(lookahead_4.get(key) is not None for key in ("low", "mid", "high")):
            future_signal = None
            try:
                bpm = float(osc_like.get("bpm") or 0.0)
            except (TypeError, ValueError):
                bpm = 0.0
            if bpm > 0.0:
                future_signal = self._preview_summary_signal_for_seconds(
                    preview_summary,
                    min(duration_seconds, current_seconds + (240.0 / bpm)),
                )
            if future_signal is not None:
                diffs = []
                for key in ("low", "mid", "high"):
                    current_value = lookahead_4.get(key)
                    next_value = future_signal.get(key)
                    if current_value is None or next_value is None:
                        continue
                    try:
                        diffs.append(abs(float(current_value) - float(next_value)))
                    except (TypeError, ValueError):
                        continue
                if diffs:
                    score += max(0.0, 1.0 - (sum(diffs) / len(diffs))) * 0.22

        return score

    def _matched_track_preview_summary(self, osc_like):
        best_score = None
        best_summary = None
        for preview_summary in self._all_track_preview_summaries():
            score = self._preview_summary_match_score(preview_summary, osc_like)
            if score is None:
                continue
            if best_score is None or score > best_score:
                best_score = score
                best_summary = preview_summary
        if best_score is None or best_score < 1.05:
            return None
        return best_summary

    def _planned_section_for_preview_segment(self, segment):
        section = phrase_bucket(segment.get("phrase"))
        activity = clamp_unit(segment.get("activity") or 0.0)
        energy = clamp_unit(segment.get("energy") or activity)
        rise = clamp_unit(segment.get("rise") if segment.get("rise") is not None else 0.5)
        rising = rise >= 0.58
        falling = rise <= 0.42

        if section == "unknown":
            if activity <= 0.24:
                return "intro"
            if activity <= 0.46:
                return "verse"
            if activity <= 0.66:
                return "build"
            if activity <= 0.86:
                return "chorus"
            return "drop"

        if section == "intro":
            if activity >= 0.58 and rising:
                return "build"
            if activity >= 0.40:
                return "verse"
            return "intro"

        if section == "verse":
            if activity >= 0.80 and energy >= 0.76:
                return "chorus"
            if activity >= 0.60 and rising:
                return "build"
            return "verse"

        if section == "build":
            if activity >= 0.90 and energy >= 0.84:
                return "drop"
            if activity >= 0.76 and not falling:
                return "chorus"
            return "build"

        if section == "chorus":
            if activity >= 0.94 and energy >= 0.88 and rising:
                return "drop"
            if activity <= 0.50 and falling:
                return "build"
            return "chorus"

        if section == "drop":
            if activity <= 0.58 and falling:
                return "chorus"
            return "drop"

        if section == "down":
            if activity >= 0.74 and rising:
                return "build"
            return "down"

        if section == "break":
            if activity >= 0.70 and rising:
                return "build"
            if activity >= 0.46:
                return "down"
            return "break"

        if section == "outro":
            if activity >= 0.82:
                return "chorus"
            if activity >= 0.68:
                return "build"
            if activity >= 0.52:
                return "down" if falling else "verse"
            return "outro"

        return section

    def _build_track_show_plan(self, preview_summary, style_name):
        segments = preview_summary.get("segments") or []
        if not segments:
            return None

        title = str(preview_summary.get("title") or "").strip()
        artist = str(preview_summary.get("artist") or "").strip()
        album = str(preview_summary.get("album") or "").strip()
        cache_key = str(
            preview_summary.get("cache_key")
            or track_preview_cache_key(title, artist, album)
        )
        identity = str(
            preview_summary.get("identity")
            or track_preview_identity(title, artist, album)
        )
        theme_name, theme = track_show_theme_for_identity(identity)
        plan_segments = []

        for raw_segment in segments:
            segment_index = int(raw_segment.get("index") or len(plan_segments))
            segment_section = self._planned_section_for_preview_segment(raw_segment)
            segment_activity = clamp_unit(raw_segment.get("activity") or 0.0)
            segment_energy = clamp_unit(raw_segment.get("energy") or segment_activity)
            segment_rise = clamp_unit(
                raw_segment.get("rise") if raw_segment.get("rise") is not None else 0.5
            )
            scene = auto_show_scene_selection(
                style_name,
                segment_section,
                (
                    f"{cache_key}|segment:{segment_index}|"
                    f"{segment_section}|{round(segment_activity, 3)}|{round(segment_rise, 3)}"
                ),
                theme_name,
                scene_window=segment_index,
                motion_window=segment_index + int(segment_activity * 6.0) + (1 if segment_rise >= 0.60 else 0),
                mirror_window=(segment_index // 2) + (1 if segment_rise >= 0.64 else 0),
                color_window=segment_index + int(segment_energy * 5.0) + (1 if segment_activity >= 0.72 else 0),
                texture_window=segment_index + int(segment_activity * 4.0) + (1 if segment_energy >= 0.78 else 0),
                wash_window=segment_index + int(max(segment_rise, 1.0 - segment_rise) * 3.0),
            )
            scene.update(
                {
                    "section": segment_section,
                    "plan_segment_index": segment_index,
                    "plan_start_seconds": float(raw_segment.get("start_seconds") or 0.0),
                    "plan_end_seconds": float(raw_segment.get("end_seconds") or 0.0),
                    "plan_start_beat": int(raw_segment.get("start_beat") or 0),
                    "plan_end_beat": int(raw_segment.get("end_beat") or 0),
                    "plan_phrase": str(raw_segment.get("phrase") or ""),
                    "plan_activity": segment_activity,
                    "plan_energy": segment_energy,
                    "plan_rise": segment_rise,
                }
            )
            plan_segments.append(scene)

        if not plan_segments:
            return None

        return {
            "cache_key": cache_key,
            "identity": identity,
            "style_name": style_name,
            "theme_name": theme_name,
            "theme_label": theme["label"],
            "title": title,
            "artist": artist,
            "album": album,
            "duration_seconds": float(preview_summary.get("duration_seconds") or 0.0),
            "total_beats": int(preview_summary.get("total_beats") or 0),
            "segment_beats": max(1, int(preview_summary.get("segment_beats") or 8)),
            "segments": plan_segments,
        }

    def _track_show_plan_for_summary(self, preview_summary, style_name):
        if not preview_summary:
            return None
        cache_key = str(preview_summary.get("cache_key") or "").strip()
        summary_entry = self.track_preview_summaries.get(cache_key) or {}
        summary_mtime = summary_entry.get("mtime")
        plan_key = (cache_key, style_name)
        cached_plan = self.track_show_plans.get(plan_key)
        if cached_plan and cached_plan.get("summary_mtime") == summary_mtime:
            return cached_plan.get("plan")
        plan = self._build_track_show_plan(preview_summary, style_name)
        self.track_show_plans[plan_key] = {
            "summary_mtime": summary_mtime,
            "plan": plan,
        }
        if plan:
            self.debug_log.log(
                "TRACK_PLAN_BUILD",
                key=cache_key,
                style=style_name,
                segments=len(plan.get("segments") or []),
            )
        return plan

    def _track_show_plan(
        self,
        track_title=None,
        track_artist=None,
        track_album=None,
        style_name="adaptive",
    ):
        cache_key = track_preview_cache_key(track_title, track_artist, track_album)
        preview_summary = self._load_track_preview_summary(
            track_title,
            track_artist,
            track_album,
        )
        if not preview_summary:
            return None
        return self._track_show_plan_for_summary(preview_summary, style_name)

    def _track_show_plan_for_osc(self, osc, style_name):
        if osc.get("_active_playback_source") == "virtualdj":
            track_path = str(osc.get("track_path") or "").strip()
            if not track_path:
                return None
            cache_key = (track_path, style_name)
            if cache_key in self.track_path_plan_cache:
                return self.track_path_plan_cache[cache_key]
            plan = None
            for summary in self._all_track_preview_summaries():
                candidate_path = summary.get("track_path") or summary.get("source_path")
                if self._same_track_path(candidate_path, track_path):
                    plan = self._track_show_plan_for_summary(summary, style_name)
                    break
            # Existing cache files have no path field. Do not guess from title
            # or waveform data: an unknown VDJ track must not inherit another
            # track's structure.
            self.track_path_plan_cache[cache_key] = plan
            return plan
        title = str(osc.get("track_title") or "").strip()
        artist = str(osc.get("track_artist") or "").strip()
        album = str(osc.get("track_album") or "").strip()
        if any(value and value != "-" for value in (title, artist, album)):
            return self._track_show_plan(
                title,
                artist,
                album,
                style_name=style_name,
            )

        matched_summary = self._matched_track_preview_summary(osc)
        if matched_summary:
            return self._track_show_plan_for_summary(matched_summary, style_name)
        return None

    def _current_track_plan_segment(self, plan, osc):
        segments = (plan or {}).get("segments") or []
        if not segments:
            return None

        current_seconds = osc.get("time_display_seconds")
        if current_seconds is None:
            current_seconds = osc.get("time_seconds")
        try:
            current_seconds = (
                None if current_seconds is None else max(0.0, float(current_seconds))
            )
        except (TypeError, ValueError):
            current_seconds = None

        if current_seconds is None:
            beat_value = osc.get("beat_value")
            try:
                beat_value = (
                    None if beat_value is None else max(0.0, float(beat_value))
                )
            except (TypeError, ValueError):
                beat_value = None
            if beat_value is None:
                return dict(segments[0])
            segment_beats = max(1, int(plan.get("segment_beats") or 8))
            segment_index = min(
                len(segments) - 1,
                max(0, int(beat_value // float(segment_beats))),
            )
            return dict(segments[segment_index])

        selected = segments[-1]
        for segment in segments:
            start_seconds = float(segment.get("plan_start_seconds") or 0.0)
            end_seconds = float(segment.get("plan_end_seconds") or start_seconds)
            if current_seconds < start_seconds:
                selected = segment
                break
            if start_seconds <= current_seconds < end_seconds:
                selected = segment
                break
        return dict(selected)

    def _planned_scene_variants(self, style_name, osc):
        plan = self._track_show_plan_for_osc(osc, style_name)
        if not plan:
            return None
        return self._current_track_plan_segment(plan, osc)

    def _prewarm_track_show_plans(self, style_name, osc):
        now = time.time()
        if now - self.last_track_plan_prewarm_at < 0.75:
            return
        self.last_track_plan_prewarm_at = now
        for track_title, track_artist, track_album in self._preview_track_candidates(osc):
            self._track_show_plan(
                track_title,
                track_artist,
                track_album,
                style_name=style_name,
            )
        if not self._preview_track_candidates(osc):
            matched_summary = self._matched_track_preview_summary(osc)
            if matched_summary:
                self._track_show_plan_for_summary(matched_summary, style_name)

    def connect(self, port, fps=DEFAULT_DMX_FPS):
        self.disconnect()
        dmx = EnttecOpenDmx(port)
        with self.lock:
            self.dmx = dmx
            self.port = port
            self.fps = max(1.0, min(60.0, float(fps)))
            self.running = True
            self.connected = True
            self.error = None
            self.debug_log.log("DMX_CONNECT", port=port, fps=self.fps)
        self.thread = threading.Thread(target=self._send_loop, daemon=True)
        self.thread.start()

    def disconnect(self):
        self.flush_config()
        with self.lock:
            dmx = self.dmx
            thread = self.thread
            fps = self.fps
            self.running = False
            self.active_one_shot_cue = None

        self.virtualdj_beat_pulse_scheduler.stop("dmx_disconnected")

        if thread and thread.is_alive():
            thread.join(timeout=1.5)

        if dmx:
            interval = 1 / fps if fps else 1 / DEFAULT_DMX_FPS
            with suppress(Exception):
                for _ in range(5):
                    self._send_dmx_frame(dmx, {})
                    time.sleep(interval)
            with suppress(Exception):
                dmx.close()

        with self.lock:
            self.dmx = None
            self.thread = None
            self.connected = False
            self.port = None
            self.running = False
            self.debug_log.log("DMX_DISCONNECT")

    def update_config(self, payload):
        stop_beat_pulse_test = False
        with self.lock:
            self.config = self._merge_payload(payload)
            now = time.time()
            config = self._clean_full_config(dict(self.config))
            osc = self.osc.snapshot_for_render()
            auto_show = self._auto_show_state(osc, config["auto_show"])
            values = self._render_values(
                now,
                config=config,
                osc=osc,
                auto_show=auto_show,
            )
            self.current_values = values
            self.current_slot_previews = self._build_slot_previews(
                config,
                osc,
                now,
                auto_show=auto_show,
            )
            self._schedule_save_locked()
            stop_beat_pulse_test = bool(config["blackout_active"])
            self.debug_log.log(
                "CONFIG_UPDATE",
                active_slot=self.config.get("active_slot"),
                blackout=self.config.get("blackout_active"),
                auto_show_enabled=(self.config.get("auto_show") or {}).get("enabled"),
                auto_show_style=(self.config.get("auto_show") or {}).get("style"),
            )
        if stop_beat_pulse_test:
            self.virtualdj_beat_pulse_scheduler.stop("blackout")
        return values

    def trigger_one_shot_cue(self, cue_id):
        cue_name = one_shot_cue_name(cue_id)
        cue = one_shot_cue_definition(cue_name)
        if not cue:
            raise ValueError("Onbekende cue-trigger")
        with self.lock:
            now = time.time()
            osc = self.osc.snapshot_for_render()
            start_beat = osc.get("beat_value")
            try:
                start_beat = None if start_beat is None else float(start_beat)
            except (TypeError, ValueError):
                start_beat = None
            try:
                bpm = float(osc.get("bpm") or 0.0)
            except (TypeError, ValueError):
                bpm = 0.0
            self.active_one_shot_cue = {
                "id": cue_name,
                "started_at": now,
                "start_beat": start_beat,
                "bpm": bpm,
            }
            self.config["blackout_active"] = False
            config = self._clean_full_config(dict(self.config))
            auto_show = self._auto_show_state(osc, config["auto_show"])
            self.current_values = self._render_values(
                now,
                config=config,
                osc=osc,
                auto_show=auto_show,
            )
            self.current_slot_previews = self._build_slot_previews(
                config,
                osc,
                now,
                auto_show=auto_show,
            )
            self.debug_log.log("ONE_SHOT_TRIGGER", cue=cue_name)
            return dict(self.current_values)

    def blackout(self):
        with self.lock:
            self.config["blackout_active"] = True
            self.active_one_shot_cue = None
            self.current_values = {}
            self.current_slot_previews = {}
            self.debug_log.log("BLACKOUT", active=True)
        self.virtualdj_beat_pulse_scheduler.stop("blackout")
        self.virtualdj_beat_pulse_preview_scheduler.stop("blackout")

    def _resolved_one_shot_cue_state(self, osc, now=None):
        raw = self.active_one_shot_cue
        if not raw:
            return None
        cue = one_shot_cue_definition(raw.get("id"))
        if not cue:
            self.active_one_shot_cue = None
            return None
        now = time.time() if now is None else float(now)
        elapsed_beats = None
        start_beat = raw.get("start_beat")
        current_beat = osc.get("beat_value")
        try:
            if start_beat is not None and current_beat is not None:
                elapsed_beats = float(current_beat) - float(start_beat)
                if elapsed_beats < -0.25:
                    elapsed_beats = None
        except (TypeError, ValueError):
            elapsed_beats = None
        if elapsed_beats is None:
            try:
                bpm = float(osc.get("bpm") or raw.get("bpm") or 120.0)
            except (TypeError, ValueError):
                bpm = 120.0
            bpm = max(60.0, bpm)
            elapsed_beats = max(
                0.0,
                (now - float(raw.get("started_at") or now)) * bpm / 60.0,
            )
        duration_beats = max(0.25, float(cue.get("duration_beats") or 1.0))
        progress = elapsed_beats / duration_beats
        if progress >= 1.0:
            self.active_one_shot_cue = None
            return None
        return {
            "id": str(raw.get("id")),
            "label": cue["label"],
            "duration_beats": duration_beats,
            "elapsed_beats": elapsed_beats,
            "progress": clamp_unit(progress),
        }

    def state(self):
        developer_playback_state = self.osc.developer_playback_state()
        self._observe_virtualdj_beat_pulse_preview_test(developer_playback_state)
        with self.lock:
            config = self._clean_full_config(dict(self.config))
            now = time.time()
            osc = self.osc.snapshot_for_render()
            self._observe_active_playback_generation(osc)
            auto_show = self._auto_show_state(osc, config["auto_show"])
            try:
                if self.connected and self.running:
                    live_values = dict(self.current_values)
                    slot_previews = dict(self.current_slot_previews)
                    if not slot_previews:
                        slot_previews = self._build_slot_previews(
                            config,
                            osc,
                            now,
                            auto_show=auto_show,
                        )
                else:
                    live_values = self._render_values(
                        now,
                        advance_motion=True,
                        config=config,
                        osc=osc,
                        auto_show=auto_show,
                    )
                    self.current_values = live_values
                    slot_previews = self._build_slot_previews(
                        config,
                        osc,
                        now,
                        auto_show=auto_show,
                    )
                    self.current_slot_previews = slot_previews
            except Exception:
                live_values = dict(self.current_values)
                slot_previews = dict(self.current_slot_previews)
            slot_previews = self._apply_virtualdj_beat_pulse_preview_overlay_locked(slot_previews)
            values = dict(sorted(live_values.items()))
            return {
                "connected": self.connected,
                "port": self.port,
                "fps": self.fps,
                "error": self.error,
                "last_sent": self.last_sent,
                "active_slot": config["active_slot"],
                "blackout_active": config["blackout_active"],
                "auto_show": auto_show,
                "slot_order": list(config["slot_order"]),
                "slots": config["slots"],
                "slot_ranges": {
                    slot_id: self._range_for_slot(slot_id, slot_config)
                    for slot_id, slot_config in config["slots"].items()
                },
                "slot_capabilities": {
                    slot_id: self._capabilities_for_slot(slot_config)
                    for slot_id, slot_config in config["slots"].items()
                },
                "slot_previews": slot_previews,
                "conflicts": list(self.conflicts),
                "values": values,
                "developer_virtualdj_beat_pulse_test": self.virtualdj_beat_pulse_test_state(),
                "developer_virtualdj_beat_pulse_preview": self.virtualdj_beat_pulse_preview_test_state(),
                "playback": {
                    "source": osc.get("_active_playback_source", "legacy"),
                    "generation": osc.get("_playback_generation"),
                    "event": osc.get("_playback_event"),
                    "runtime_resets": self.playback_runtime_resets,
                    "dmx_dispatch_failures": self.dmx_dispatch_failures,
                },
            }

    def add_slot(self, fixture_id, mode=None):
        fixture = find_fixture(FIXTURE_LIBRARY, fixture_id)
        selected_mode = mode or fixture_preset(fixture_id)["mode"]
        find_mode(fixture, selected_mode)
        with self.lock:
            config = self._clean_full_config(dict(self.config))
            slot_id = self._next_slot_id(config, fixture_id)
            label = self._next_slot_label(config, fixture_preset(fixture_id)["label_base"])
            address = self._next_available_address(config, fixture, selected_mode)
            slot_config = self.default_slot_config(
                slot_id,
                fixture_id=fixture_id,
                label=label,
                address=address,
                mode=selected_mode,
            )
            config["slots"][slot_id] = self._clean_slot_config(slot_id, slot_config)
            config["slot_order"].append(slot_id)
            config["active_slot"] = slot_id
            config["blackout_active"] = False
            self.config = self._clean_full_config(config)
            now = time.time()
            full_config = self._clean_full_config(dict(self.config))
            osc = self.osc.snapshot_for_render()
            auto_show = self._auto_show_state(osc, full_config["auto_show"])
            self.current_values = self._render_values(
                now,
                config=full_config,
                osc=osc,
                auto_show=auto_show,
            )
            self.current_slot_previews = self._build_slot_previews(
                full_config,
                osc,
                now,
                auto_show=auto_show,
            )
            self._schedule_save_locked()
            self.debug_log.log(
                "SLOT_ADD",
                slot=slot_id,
                fixture=fixture_id,
                mode=selected_mode,
                address=address,
                label=label,
            )
            return dict(self.current_values)

    def remove_slot(self, slot_id):
        slot_id = str(slot_id or "").strip()
        if not slot_id:
            raise ValueError("Geen fixture geselecteerd om te verwijderen")
        with self.lock:
            config = self._clean_full_config(dict(self.config))
            if slot_id not in config["slots"]:
                raise ValueError(f"Fixture '{slot_id}' bestaat niet")
            if len(config["slot_order"]) <= 1:
                raise ValueError("Minimaal 1 fixture moet aanwezig blijven")
            removed_slot = dict(config["slots"][slot_id])
            previous_order = list(config["slot_order"])
            removed_index = previous_order.index(slot_id)
            del config["slots"][slot_id]
            config["slot_order"] = [current for current in previous_order if current != slot_id]
            if config["active_slot"] == slot_id or config["active_slot"] not in config["slots"]:
                fallback_index = min(removed_index, len(config["slot_order"]) - 1)
                config["active_slot"] = config["slot_order"][fallback_index]
            config["blackout_active"] = False
            self.config = self._clean_full_config(config)
            now = time.time()
            full_config = self._clean_full_config(dict(self.config))
            osc = self.osc.snapshot_for_render()
            auto_show = self._auto_show_state(osc, full_config["auto_show"])
            self.current_values = self._render_values(
                now,
                config=full_config,
                osc=osc,
                auto_show=auto_show,
            )
            self.current_slot_previews = self._build_slot_previews(
                full_config,
                osc,
                now,
                auto_show=auto_show,
            )
            self._schedule_save_locked()
            self.debug_log.log(
                "SLOT_REMOVE",
                slot=slot_id,
                fixture=removed_slot.get("fixture"),
                address=removed_slot.get("address"),
                label=removed_slot.get("label"),
            )
            return dict(self.current_values)

    def flush_config(self):
        with self.lock:
            timer = self.save_timer
            self.save_timer = None
            config = self._clean_full_config(dict(self.config))
        if timer:
            timer.cancel()
        self._write_config(config)

    def _merge_payload(self, payload):
        config = self._clean_full_config(dict(self.config))
        active_slot = str(payload.get("active_slot") or config["active_slot"])
        if active_slot not in config["slots"]:
            active_slot = config["slot_order"][0]
        config["active_slot"] = active_slot

        if "blackout_active" in payload:
            config["blackout_active"] = bool(payload["blackout_active"])

        if "auto_show" in payload and isinstance(payload["auto_show"], dict):
            merged_auto_show = {**config["auto_show"], **payload["auto_show"]}
            config["auto_show"] = self._clean_auto_show_config(merged_auto_show)

        slot_id = payload.get("slot_id")
        slot_payload = payload.get("slot")
        if slot_id and slot_id in config["slots"] and isinstance(slot_payload, dict):
            merged = {**config["slots"][slot_id], **slot_payload}
            config["slots"][slot_id] = self._clean_slot_config(slot_id, merged)
            config["blackout_active"] = False

        if "slots" in payload and isinstance(payload["slots"], dict):
            for current_slot_id, current_payload in payload["slots"].items():
                if current_slot_id in config["slots"] and isinstance(current_payload, dict):
                    merged = {**config["slots"][current_slot_id], **current_payload}
                    config["slots"][current_slot_id] = self._clean_slot_config(
                        current_slot_id, merged
                    )
            config["blackout_active"] = False

        return self._clean_full_config(config)

    def _load_config(self):
        defaults = self.default_config()
        if not CONFIG_PATH.exists():
            return defaults
        try:
            payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"{APP_NAME}: config load failed, using defaults: {exc}")
            return defaults
        try:
            return self._clean_full_config(payload)
        except Exception as exc:
            print(f"{APP_NAME}: config invalid, using defaults: {exc}")
            return defaults

    def _schedule_save_locked(self):
        if self.save_timer:
            self.save_timer.cancel()
        timer = threading.Timer(0.35, self._save_config_worker)
        timer.daemon = True
        self.save_timer = timer
        timer.start()

    def _save_config_worker(self):
        with self.lock:
            self.save_timer = None
            config = self._clean_full_config(dict(self.config))
        self._write_config(config)

    def _write_config(self, config):
        persistable = self._persistable_config(config)
        tmp_path = CONFIG_PATH.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(persistable, indent=2), encoding="utf-8")
        tmp_path.replace(CONFIG_PATH)

    def _persistable_config(self, config):
        persistable = self._clean_full_config(dict(config))
        persistable["blackout_active"] = False
        return persistable

    def _clean_slot_config(self, slot_id, config):
        fixture_id = (config or {}).get("fixture")
        if not any(fixture["id"] == fixture_id for fixture in FIXTURE_LIBRARY):
            fixture_id = None
        defaults = self.default_slot_config(slot_id, fixture_id=fixture_id)
        cleaned = {**defaults, **config}
        color = config.get("color") or {}
        cleaned["color"] = {
            "red": clamp_dmx(color.get("red", 255)),
            "green": clamp_dmx(color.get("green", 0)),
            "blue": clamp_dmx(color.get("blue", 0)),
            "white": clamp_dmx(color.get("white", 0)),
        }
        for key in (
            "dimmer",
            "strobe",
            "program",
            "speed",
            "pan",
            "tilt",
            "pan_tilt_speed",
            "beat_depth",
        ):
            cleaned[key] = clamp_dmx(cleaned.get(key, defaults.get(key, 0)))
        cleaned["pan_offset_deg"] = max(
            -180, min(180, int(cleaned.get("pan_offset_deg", defaults["pan_offset_deg"])))
        )
        cleaned["tilt_offset_deg"] = max(
            -90, min(90, int(cleaned.get("tilt_offset_deg", defaults["tilt_offset_deg"])))
        )
        cleaned["pan_span_percent"] = max(
            5, min(160, int(cleaned.get("pan_span_percent", defaults["pan_span_percent"])))
        )
        cleaned["tilt_span_percent"] = max(
            5, min(160, int(cleaned.get("tilt_span_percent", defaults["tilt_span_percent"])))
        )
        for key in ("pan_left_value", "pan_right_value", "tilt_back_value", "tilt_front_value"):
            raw_value = cleaned.get(key, defaults.get(key))
            if raw_value is None or raw_value == "":
                cleaned[key] = None
            else:
                cleaned[key] = clamp_dmx(raw_value)
        for key in (
            "pose_center",
            "pose_audience_left",
            "pose_audience_center",
            "pose_audience_right",
            "pose_ceiling_center",
        ):
            raw_pose = cleaned.get(key, defaults.get(key))
            if not isinstance(raw_pose, dict):
                cleaned[key] = None
                continue
            pan = raw_pose.get("pan")
            tilt = raw_pose.get("tilt")
            if pan is None or tilt is None:
                cleaned[key] = None
                continue
            cleaned[key] = {
                "pan": clamp_dmx(pan),
                "tilt": clamp_dmx(tilt),
            }
        cleaned["beat_decay_ms"] = max(
            30, min(1500, int(cleaned.get("beat_decay_ms", defaults["beat_decay_ms"])))
        )
        cleaned["address"] = max(1, min(512, int(cleaned.get("address", defaults["address"]))))
        for key in (
            "sync_enabled",
            "beat_pulse_enabled",
            "osc_strobe_enabled",
            "use_fine_pan_tilt",
            "pan_invert",
            "tilt_invert",
        ):
            cleaned[key] = bool(cleaned.get(key, False))
        cleaned["enabled"] = bool(cleaned.get("enabled", True))
        cleaned["label"] = str(cleaned.get("label", defaults["label"]))
        requested_fixture = str(cleaned.get("fixture", defaults["fixture"]))
        if not any(fixture["id"] == requested_fixture for fixture in FIXTURE_LIBRARY):
            requested_fixture = defaults["fixture"]
        cleaned["fixture"] = requested_fixture
        fixture = find_fixture(FIXTURE_LIBRARY, cleaned["fixture"])
        requested_mode = str(cleaned.get("mode", defaults["mode"]))
        if cleaned["fixture"] == "uking_zq06016" and requested_mode.upper() == "H001":
            requested_mode = "P001"
        with suppress(Exception):
            requested_mode = find_mode(fixture, requested_mode)["name"]
        if not any(mode["name"].lower() == requested_mode.lower() for mode in fixture["modes"]):
            requested_mode = fixture["modes"][0]["name"]
        cleaned["mode"] = requested_mode
        selected_mode = find_mode(fixture, cleaned["mode"])
        raw_extra_values = cleaned.get("extra_values")
        if not isinstance(raw_extra_values, dict):
            raw_extra_values = {}
        cleaned["extra_values"] = {
            control["id"]: clamp_dmx(raw_extra_values.get(control["id"], control["default"]))
            for control in mode_custom_controls(selected_mode)
        }
        cleaned["color_source"] = str(cleaned.get("color_source", "manual"))
        raw_group = str(cleaned.get("group", "") or "").strip().lower()
        raw_group = "".join(ch if (ch.isalnum() or ch in ("_", "-")) else "_" for ch in raw_group)
        raw_group = raw_group.strip("_-")
        if not raw_group:
            raw_group = default_group_name_for_slot(
                slot_id,
                cleaned["fixture"],
                cleaned.get("label", ""),
            )
        cleaned["group"] = raw_group
        return cleaned

    def _clean_auto_show_config(self, config):
        defaults = self.default_auto_show_config()
        cleaned = {**defaults, **(config or {})}
        cleaned["enabled"] = bool(cleaned.get("enabled", defaults["enabled"]))
        style = str(cleaned.get("style", defaults["style"])).lower()
        if style not in AUTO_SHOW_STYLES:
            style = defaults["style"]
        cleaned["style"] = style
        cleaned["audience_pan_focus_enabled"] = bool(
            cleaned.get("audience_pan_focus_enabled", defaults["audience_pan_focus_enabled"])
        )
        try:
            cleaned["audience_pan_min"] = clamp_dmx(
                int(cleaned.get("audience_pan_min", defaults["audience_pan_min"]))
            )
        except (TypeError, ValueError):
            cleaned["audience_pan_min"] = defaults["audience_pan_min"]
        try:
            cleaned["audience_pan_max"] = clamp_dmx(
                int(cleaned.get("audience_pan_max", defaults["audience_pan_max"]))
            )
        except (TypeError, ValueError):
            cleaned["audience_pan_max"] = defaults["audience_pan_max"]
        if cleaned["audience_pan_max"] < cleaned["audience_pan_min"]:
            cleaned["audience_pan_min"], cleaned["audience_pan_max"] = (
                cleaned["audience_pan_max"],
                cleaned["audience_pan_min"],
            )
        default_turn_min, default_turn_max = _default_turn_audience_pan_limits(
            cleaned["audience_pan_min"],
            cleaned["audience_pan_max"],
        )
        try:
            cleaned["audience_turn_pan_min"] = clamp_dmx(
                int(cleaned.get("audience_turn_pan_min", default_turn_min))
            )
        except (TypeError, ValueError):
            cleaned["audience_turn_pan_min"] = default_turn_min
        try:
            cleaned["audience_turn_pan_max"] = clamp_dmx(
                int(cleaned.get("audience_turn_pan_max", default_turn_max))
            )
        except (TypeError, ValueError):
            cleaned["audience_turn_pan_max"] = default_turn_max
        if cleaned["audience_turn_pan_max"] < cleaned["audience_turn_pan_min"]:
            cleaned["audience_turn_pan_min"], cleaned["audience_turn_pan_max"] = (
                cleaned["audience_turn_pan_max"],
                cleaned["audience_turn_pan_min"],
            )
        try:
            cleaned["audience_tilt_split"] = clamp_dmx(
                int(cleaned.get("audience_tilt_split", defaults["audience_tilt_split"]))
            )
        except (TypeError, ValueError):
            cleaned["audience_tilt_split"] = defaults["audience_tilt_split"]
        cleaned["override_phrase"] = auto_show_phrase_override_name(
            cleaned.get("override_phrase", defaults["override_phrase"])
        )
        cleaned["override_color"] = live_override_color_name(
            cleaned.get("override_color", defaults["override_color"])
        )
        cleaned["override_energy"] = live_override_energy_name(
            cleaned.get("override_energy", defaults["override_energy"])
        )
        for key in (
            "override_manual_strobe",
            "override_audience_sweep",
            "override_all_on",
            "override_par_chase",
            "override_par_snake",
        ):
            cleaned[key] = bool(cleaned.get(key, defaults[key]))
        if cleaned["override_par_snake"]:
            cleaned["override_par_chase"] = False
        return cleaned

    def _clean_full_config(self, config):
        defaults = self.default_config()
        raw_slots = config.get("slots") if isinstance(config.get("slots"), dict) else {}
        if not raw_slots:
            raw_slots = dict(defaults["slots"])
        raw_order = config.get("slot_order") if isinstance(config.get("slot_order"), list) else []
        if not raw_order:
            raw_order = [slot_id for slot_id in defaults["slot_order"] if slot_id in raw_slots]
        cleaned = {
            "active_slot": str(config.get("active_slot", defaults["active_slot"])),
            "blackout_active": bool(config.get("blackout_active", False)),
            "auto_show": self._clean_auto_show_config(config.get("auto_show")),
            "slot_order": [],
            "slots": {},
        }
        seen = set()
        for slot_id in raw_order:
            slot_id = str(slot_id)
            if slot_id in seen or slot_id not in raw_slots:
                continue
            cleaned["slots"][slot_id] = self._clean_slot_config(slot_id, raw_slots.get(slot_id, {}))
            cleaned["slot_order"].append(slot_id)
            seen.add(slot_id)
        for slot_id, slot_config in raw_slots.items():
            slot_id = str(slot_id)
            if slot_id in seen:
                continue
            cleaned["slots"][slot_id] = self._clean_slot_config(slot_id, slot_config)
            cleaned["slot_order"].append(slot_id)
        if not cleaned["slot_order"]:
            for slot_id in defaults["slot_order"]:
                cleaned["slots"][slot_id] = self._clean_slot_config(slot_id, defaults["slots"][slot_id])
                cleaned["slot_order"].append(slot_id)
        if cleaned["active_slot"] not in cleaned["slots"]:
            cleaned["active_slot"] = cleaned["slot_order"][0]
        return cleaned

    def _capabilities_for_slot(self, config):
        fixture = find_fixture(FIXTURE_LIBRARY, config["fixture"])
        mode = find_mode(fixture, config["mode"])
        return mode_capabilities(mode)

    def _role_for_slot(self, config, capabilities=None):
        capabilities = capabilities or self._capabilities_for_slot(config)
        fixture = find_fixture(FIXTURE_LIBRARY, config["fixture"])
        label_text = f"{fixture['manufacturer']} {fixture['model']} {config.get('label', '')}".lower()
        beam_layout = str(fixture.get("beam_layout", {}).get("type", "")).lower()
        if capabilities["pan"] or capabilities["tilt"]:
            return "moving"
        if "wall wash" in label_text or beam_layout == "strip":
            return "wash"
        if "par" in label_text:
            return "par"
        return "static"

    def _slot_context(self, full_config, slot_id, config):
        capabilities = self._capabilities_for_slot(config)
        role = self._role_for_slot(config, capabilities)
        slot_order = list(full_config.get("slot_order") or [])
        if slot_id not in slot_order:
            slot_order.append(slot_id)
        global_index = slot_order.index(slot_id)
        slots = full_config.get("slots") or {}

        role_slot_ids = []
        for current_slot_id in slot_order:
            current_config = slots.get(current_slot_id)
            if current_config is None:
                if current_slot_id != slot_id:
                    continue
                current_config = config
            current_capabilities = self._capabilities_for_slot(current_config)
            if self._role_for_slot(current_config, current_capabilities) == role:
                role_slot_ids.append(current_slot_id)

        if slot_id not in role_slot_ids:
            role_slot_ids.append(slot_id)

        group_name = str(config.get("group") or default_group_name_for_slot(
            slot_id,
            config.get("fixture"),
            config.get("label", ""),
        ))
        grouped_role_slot_ids = []
        role_group_names = []
        for current_slot_id in role_slot_ids:
            current_config = slots.get(current_slot_id)
            if current_config is None:
                if current_slot_id != slot_id:
                    continue
                current_config = config
            current_group = str(current_config.get("group") or default_group_name_for_slot(
                current_slot_id,
                current_config.get("fixture"),
                current_config.get("label", ""),
            ))
            if current_group == group_name:
                grouped_role_slot_ids.append(current_slot_id)
            if current_group not in role_group_names:
                role_group_names.append(current_group)

        if slot_id not in grouped_role_slot_ids:
            grouped_role_slot_ids.append(slot_id)
        if group_name not in role_group_names:
            role_group_names.append(group_name)

        role_index = grouped_role_slot_ids.index(slot_id)
        role_count = len(grouped_role_slot_ids)
        if role_count <= 1:
            normalized = 0.5
            centered = 0.0
        else:
            normalized = role_index / max(1, role_count - 1)
            centered = normalized * 2.0 - 1.0

        group_index = role_group_names.index(group_name)
        group_count = len(role_group_names)
        if group_count <= 1:
            group_normalized = 0.5
            group_centered = 0.0
        else:
            group_normalized = group_index / max(1, group_count - 1)
            group_centered = group_normalized * 2.0 - 1.0

        member_seed = stable_hash(slot_id)
        seed_unit = ((member_seed % 1000) / 999.0) * 2.0 - 1.0
        group_seed = stable_hash(f"{role}:{group_name}")
        group_seed_unit = ((group_seed % 1000) / 999.0) * 2.0 - 1.0

        return {
            "role": role,
            "group": group_name,
            "global_index": global_index,
            "global_count": len(slot_order),
            "role_index": role_index,
            "role_count": role_count,
            "normalized": normalized,
            "centered": centered,
            "center_bias": 1.0 - abs(centered),
            "edge_bias": abs(centered),
            "alternate": -1.0 if role_index % 2 == 0 else 1.0,
            "member_index": role_index,
            "member_count": role_count,
            "member_normalized": normalized,
            "member_centered": centered,
            "member_center_bias": 1.0 - abs(centered),
            "member_edge_bias": abs(centered),
            "member_alternate": -1.0 if role_index % 2 == 0 else 1.0,
            "group_index": group_index,
            "group_count": group_count,
            "group_normalized": group_normalized,
            "group_centered": group_centered,
            "group_center_bias": 1.0 - abs(group_centered),
            "group_edge_bias": abs(group_centered),
            "group_alternate": -1.0 if group_index % 2 == 0 else 1.0,
            "seed_unit": seed_unit,
            "member_seed_unit": seed_unit,
            "group_seed_unit": group_seed_unit,
        }

    def _accent_dimmer_offset(self, role, slot_context, accent_name, movement):
        center_bias = slot_context.get("group_center_bias", slot_context["center_bias"])
        edge_bias = slot_context.get("group_edge_bias", slot_context["edge_bias"])
        alternate = slot_context.get("group_alternate", slot_context["alternate"])

        if accent_name == "center":
            return round(center_bias * (18 if role == "moving" else 12) - edge_bias * 6)
        if accent_name == "edges":
            return round(edge_bias * (24 if role == "moving" else 16) - center_bias * 8)
        if accent_name == "alternating":
            return round(alternate * (10 if role == "moving" else 7))
        if accent_name == "wash_lift":
            if role == "wash":
                return 20
            if role == "moving":
                return -10
            return 4
        if accent_name == "mover_focus":
            if role == "moving":
                return round(16 + movement * 12 - edge_bias * 4)
            if role == "wash":
                return -8
            return -2
        return 0

    def _rhythm_envelope(self, mode, beat_value, slot_context, movement_scale, osc, now, decay, energy=0.0):
        if mode == "none":
            return 0.0

        if mode in ("pulse", "gate", "lift"):
            age = osc.get("beat_phase_age_seconds")
            if age is None:
                last_beat_at = osc.get("last_beat_at")
                if not last_beat_at:
                    return 0.0
                age = now - last_beat_at
            envelope = max(0.0, 1.0 - (age / decay)) if decay > 0 else 0.0
            if mode == "lift":
                return envelope ** 0.72
            if mode == "gate":
                return envelope ** 0.45
            return envelope

        if mode in ("hit", "cut"):
            if beat_value is None:
                return 0.0
            age = osc.get("beat_phase_age_seconds")
            if age is None:
                last_beat_at = osc.get("last_beat_at")
                if not last_beat_at:
                    return 0.0
                age = now - last_beat_at
            envelope = max(0.0, 1.0 - (age / decay)) if decay > 0 else 0.0
            cycle_length = 8
            beat_step = int(math.floor(float(beat_value))) % cycle_length
            group_key = str(slot_context.get("group") or slot_context.get("role") or "moving")
            window = int(math.floor(float(beat_value) / cycle_length))
            pattern_seed = stable_hash(f"{osc_track_signature(osc)}|{group_key}|{window}")
            if energy >= 0.96:
                patterns = [(0, 2, 4, 6), (0, 3, 4, 7), (1, 3, 5, 7)]
            elif energy >= 0.88:
                patterns = [(0, 4), (0, 3, 6), (1, 5), (0, 5)]
            else:
                patterns = [(0, 4), (1, 5), (0, 6)]
            active_hits = patterns[pattern_seed % len(patterns)]
            if beat_step not in active_hits:
                return 0.0
            if mode == "cut":
                return envelope ** 0.22
            return envelope ** 0.34

        if beat_value is None:
            return 0.0

        role = str(slot_context.get("role", ""))
        if role == "par":
            member_count = max(1, int(slot_context.get("member_count", 1)))
            member_index = int(slot_context.get("member_index", 0))
            role_count = max(1, (member_count + 1) // 2)
            role_index = min(member_index, member_count - 1 - member_index)
            centered = (
                ((role_index / max(1, role_count - 1)) * 2.0) - 1.0
                if role_count > 1
                else 0.0
            )
        else:
            role_count = max(
                1,
                int(slot_context.get("group_count", slot_context.get("role_count", 1))),
            )
            role_index = int(slot_context.get("group_index", slot_context.get("role_index", 0)))
            centered = float(
                slot_context.get("group_centered", slot_context.get("centered", 0.0))
            )
        movement_scale = float(movement_scale or 0.0)
        beat_value = float(beat_value)

        if mode == "breathe":
            return 0.50 + 0.50 * wave_sine(beat_value / 8.0 + centered * 0.12)

        if mode == "stagger":
            step = (int(math.floor(beat_value * 2.0)) + role_index) % 2
            return 1.0 if step == 0 else 0.28 + movement_scale * 0.12

        if mode == "alternate_whole":
            phase = int(math.floor(beat_value / 2.0)) % 2 if role == "moving" else int(math.floor(beat_value)) % 2
            if role == "par":
                active_side = role_index % 2
            elif role_count <= 2:
                active_side = role_index % 2
            else:
                active_side = 0 if centered <= 0 else 1
            return 1.0 if phase == active_side else 0.0

        if mode == "double_hit":
            phase = beat_value % 1.0
            if phase < 0.16:
                return 1.0
            if 0.46 <= phase < 0.60:
                return 1.0 if ((int(math.floor(beat_value)) + role_index) % 2 == 0) else 0.0
            return 0.0

        if mode == "gallop":
            phase = (beat_value + role_index * 0.18) % 1.0
            if phase < 0.18:
                return 1.0
            if 0.34 <= phase < 0.46:
                return 1.0
            if phase >= 0.72 and phase < 0.82 and energy >= 0.72:
                return 1.0 if role != "moving" or role_index % 2 == 0 else 0.0
            return 0.0

        if mode == "pivot":
            phase = int(math.floor(beat_value)) % 4
            if role_count <= 2:
                return 1.0 if phase in ((0, 3) if role_index % 2 == 0 else (1, 2)) else 0.0
            is_center = abs(centered) < 0.34
            return 1.0 if (phase in (0, 2) and is_center) or (phase in (1, 3) and not is_center) else 0.0

        if mode == "pair_swap" and role == "par":
            step = int(math.floor(beat_value)) % role_count
            return 1.0 if role_index == step else 0.0

        if mode == "pair_hold" and role == "par":
            step = int(math.floor(beat_value / 2.0)) % role_count
            return 1.0 if role_index == step else 0.0

        if mode == "pair_bounce" and role == "par":
            phase = int(math.floor(beat_value)) % 4
            if phase == 0:
                return 1.0 if role_index == 0 else 0.0
            if phase == 1:
                return 1.0
            if phase == 2:
                return 1.0 if role_index == min(1, role_count - 1) else 0.0
            return 1.0

        if mode == "par_snake" and role == "par":
            member_count = max(1, int(slot_context.get("member_count", 1)))
            member_index = int(slot_context.get("member_index", 0))
            cycle = max(2, member_count * 2 - 2)
            raw_step = int(math.floor(beat_value)) % cycle
            step = raw_step if raw_step < member_count else (cycle - raw_step)
            return 1.0 if member_index == step else 0.0

        if mode in {"chase", "chase_whole"}:
            subdivision = 1 if mode == "chase_whole" and role == "moving" else 2 if role == "moving" else 1 if role == "par" else 2
            step = int(math.floor(beat_value * subdivision)) % role_count
            return 1.0 if role_index == step else 0.0

        if mode in {"snake", "snake_whole"}:
            subdivision = 1 if mode == "snake_whole" and role == "moving" else 2 if role == "moving" else 1 if role == "par" else 2
            cycle = max(2, role_count * 2 - 2)
            raw_step = int(math.floor(beat_value * subdivision)) % cycle
            step = raw_step if raw_step < role_count else (cycle - raw_step)
            width = 0 if role == "moving" else 1 if role_count >= 4 else 0
            return 1.0 if abs(role_index - step) <= width else 0.0

        if mode == "ripple":
            return 0.50 + 0.50 * wave_sine(
                beat_value / (2.8 - movement_scale * 0.6)
                + role_index * 0.35
                + centered * 0.18
            )

        if mode == "split":
            phase = int(math.floor(beat_value * 1.5)) % 2
            return 1.0 if phase == (0 if centered <= 0 else 1) else 0.32 + movement_scale * 0.10

        if mode == "ladder":
            step_count = max(2, role_count)
            step = (int(math.floor(beat_value * 2.0)) + role_index) % step_count
            return 1.0 - (step / max(1, step_count - 1)) * 0.64

        if mode == "bloom":
            return 0.36 + (1.0 - abs(centered)) * 0.56 + 0.08 * wave_sine(beat_value / 6.0 + role_index * 0.11)

        return 0.0

    def _texture_multiplier(self, config, osc, now):
        texture_name = str(config.get("_auto_show_texture_name", "steady"))
        slot_context = config.get("_slot_context") or {}
        role = str(slot_context.get("role", "static"))
        if role == "moving":
            return 1.0
        if role == "par":
            return 1.0
        beat_value = osc.get("beat_value")
        beat_value = float(beat_value if beat_value is not None else now * 1.6)
        member_index = int(slot_context.get("member_index", slot_context.get("group_index", 0)))
        member_count = max(1, int(slot_context.get("member_count", slot_context.get("group_count", 1))))
        centered = float(slot_context.get("member_centered", slot_context.get("group_centered", 0.0)))
        center_bias = float(slot_context.get("member_center_bias", slot_context.get("group_center_bias", 0.0)))
        alternate = float(slot_context.get("member_alternate", slot_context.get("group_alternate", 0.0)))
        seed_unit = float(slot_context.get("member_seed_unit", slot_context.get("seed_unit", 0.0)))
        group_seed_unit = float(slot_context.get("group_seed_unit", seed_unit))
        role_depth = {
            "moving": 0.08,
            "par": 0.28,
            "wash": 0.18,
            "static": 0.14,
        }.get(role, 0.14)
        base = 1.0 - role_depth
        phase_seed = seed_unit * 0.37 + group_seed_unit * 0.21

        if texture_name == "steady":
            multiplier = 0.96 + center_bias * 0.04 - abs(seed_unit) * 0.02
        elif texture_name == "drift":
            multiplier = base + role_depth * (0.40 + 0.60 * (0.5 + 0.5 * wave_sine(beat_value / 12.0 + phase_seed)))
        elif texture_name == "ripple":
            multiplier = base + role_depth * (
                0.24 + 0.76 * (0.5 + 0.5 * wave_sine(beat_value / 4.0 + member_index * 0.42 + phase_seed))
            )
        elif texture_name == "split":
            active = (int(math.floor(beat_value * 1.5)) % 2) == (0 if alternate < 0 else 1)
            multiplier = 1.0 if active else base + role_depth * 0.10
        elif texture_name == "ladder":
            step = (int(math.floor(beat_value * 2.0)) + member_index) % max(2, member_count)
            gradient = 1.0 - (step / max(1, member_count - 1)) * 0.82
            multiplier = base + role_depth * max(0.18, gradient)
        elif texture_name == "shuffle":
            window = int(math.floor(beat_value * 1.25))
            random_unit = ((stable_hash(f"{window}|{member_index}|{group_seed_unit:.3f}") % 1000) / 999.0)
            multiplier = base + role_depth * (0.18 + 0.82 * random_unit)
        elif texture_name == "bloom":
            bloom = 0.28 + 0.72 * center_bias
            bloom += 0.10 * wave_sine(beat_value / 6.0 + phase_seed)
            multiplier = base + role_depth * clamp_unit(bloom)
        else:
            multiplier = 1.0

        return max(0.62 if role == "par" else 0.74, min(1.04, multiplier))

    def _resolved_sync_rgbw(self, config, osc):
        manual = config["color"]
        rgbw = (manual["red"], manual["green"], manual["blue"], manual["white"])
        if not config["sync_enabled"]:
            return rgbw

        source = config["color_source"]
        if source == "phrase":
            return color_for_phrase(osc["phrase_current"]) or rgbw
        if source == "mood":
            return color_for_mood(osc["mood"]) or rgbw
        if source == "color_bank":
            return COLOR_BANKS.get(osc["color_bank"], rgbw)
        return rgbw

    def _auto_show_rgbw_for_slot(self, base_rgbw, slot_context, auto_show):
        role = slot_context["role"]
        section = auto_show.get("behavior_bucket", auto_show["phrase_bucket"])
        beat_step = int(auto_show.get("beat_step", 1) or 1)
        energy = auto_show["energy"]
        alternate = slot_context.get("group_alternate", slot_context["alternate"])
        edge_bias = slot_context.get("group_edge_bias", slot_context["edge_bias"])
        center_bias = slot_context.get("group_center_bias", slot_context["center_bias"])
        seed_unit = slot_context.get("group_seed_unit", slot_context.get("seed_unit", 0.0))
        member_seed_unit = slot_context.get("member_seed_unit", slot_context.get("seed_unit", 0.0))
        style = auto_show["style"]
        track_theme = auto_show_track_theme(
            auto_show.get("theme_name", TRACK_SHOW_THEME_SEQUENCE[0])
        )
        look_name = auto_show.get("look_name", "bank_echo")
        color_profile = auto_show_color_profile(
            auto_show.get("color_profile_name", "yellow_blue")
        )
        pulse_name = auto_show.get("pulse_name", "medium")
        drum_signals = auto_show.get("drum_signals") or {}
        kick = clamp_unit(float(drum_signals.get("kick") or 0.0))
        snare = clamp_unit(float(drum_signals.get("snare") or 0.0))
        hihat = clamp_unit(float(drum_signals.get("hihat") or 0.0))
        section_accent = auto_show_section_accent(section)
        theme_contrast = float(track_theme.get("contrast", 0.0))
        theme_white_bias = float(track_theme.get("white_bias", 0.0)) * 0.40

        warm_fill = color_profile["primary"]
        cool_fill = color_profile["secondary"]
        accent = color_profile["accent"]
        white_peak = color_profile["white"]
        warm_mix = float(color_profile["base_mix"])
        cool_mix = float(color_profile["base_mix"])
        accent_mix = float(color_profile["accent_mix"])
        white_mix = float(color_profile["white_mix"])
        split_mix = float(color_profile["split_mix"])

        if style == "festival":
            accent = mix_rgbw(accent, (255, 80, 200, 0), 0.22)
            accent_mix += 0.07
            split_mix += 0.10
            white_mix -= 0.02
        elif style == "minimal":
            warm_fill = mix_rgbw(warm_fill, (170, 150, 120, 0), 0.22)
            cool_fill = mix_rgbw(cool_fill, (100, 125, 190, 0), 0.26)
            accent_mix -= 0.04
            split_mix -= 0.04
            white_mix -= 0.02
        elif style == "warm":
            cool_fill = mix_rgbw(cool_fill, warm_fill, 0.45)
        elif style == "cinematic":
            warm_fill = mix_rgbw(warm_fill, (220, 150, 110, 20), 0.28)
            cool_fill = mix_rgbw(cool_fill, (120, 145, 255, 16), 0.24)

        if look_name == "warm_glow":
            accent = mix_rgbw(accent, warm_fill, 0.55)
            warm_mix += 0.08
            cool_mix -= 0.08
            accent_mix -= 0.01
            white_mix -= 0.01
        elif look_name == "cool_air":
            accent = mix_rgbw(accent, cool_fill, 0.50)
            warm_mix -= 0.08
            cool_mix += 0.08
            white_mix -= 0.01
        elif look_name == "white_bloom":
            accent = mix_rgbw(accent, white_peak, 0.18)
            warm_mix -= 0.02
            cool_mix -= 0.02
            accent_mix -= 0.01
            white_mix += 0.02
        elif look_name == "sunset_push":
            accent = mix_rgbw(accent, warm_fill, 0.38)
            warm_mix += 0.08
            cool_mix -= 0.08
            accent_mix += 0.05
        elif look_name == "ultraviolet":
            accent = mix_rgbw(accent, (205, 110, 255, 10), 0.44)
            warm_mix -= 0.08
            cool_mix += 0.06
            accent_mix += 0.06
            split_mix += 0.04
        elif look_name == "mood_wash":
            accent_mix -= 0.03
            warm_mix -= 0.02
            cool_mix -= 0.02
            white_mix -= 0.02
        elif look_name == "bank_echo":
            accent_mix += 0.03
            warm_mix -= 0.02
            cool_mix -= 0.02
            white_mix -= 0.01
        elif look_name == "neon_split":
            accent = mix_rgbw(accent, (255, 95, 180, 0), 0.32)
            warm_mix -= 0.08
            cool_mix -= 0.08
            accent_mix += 0.04
            white_mix -= 0.02
            split_mix += 0.06

        warm_mix = max(0.02, warm_mix)
        cool_mix = max(0.02, cool_mix)
        accent_mix = max(0.02, accent_mix)
        white_mix = max(0.0, white_mix)
        split_mix = max(0.08, split_mix)
        split_mix += theme_contrast * 0.12
        accent_mix += theme_contrast * 0.05
        white_mix = max(0.0, white_mix + theme_white_bias)

        if section in ("intro", "verse", "down", "break", "outro", "unknown"):
            white_mix = min(white_mix, 0.003)
        elif section == "chorus":
            white_mix = min(white_mix, 0.008)
        elif section == "build":
            white_mix = min(white_mix, 0.012)
        elif section == "drop":
            white_mix = min(white_mix, 0.020)

        accent_mix += abs(seed_unit) * 0.03 + abs(member_seed_unit) * 0.012
        warm_mix += max(0.0, -seed_unit) * 0.05
        cool_mix += max(0.0, seed_unit) * 0.05
        if pulse_name in {"chase", "snake", "gallop"}:
            split_mix += 0.08
            accent_mix += 0.03
            white_mix = max(0.0, white_mix - 0.02)
        elif pulse_name in {"beat_flash", "drop_blinder", "strong_pulse", "double_hit"}:
            white_mix += 0.005
            accent_mix += 0.01
        elif pulse_name in {"low_glow", "slow_fade_out"}:
            white_mix = max(0.0, white_mix - 0.01)
            accent_mix = max(0.03, accent_mix - 0.02)

        if role == "moving":
            palette_shift = int(abs(stable_hash(auto_show.get("theme_name", ""))) % 4)
            moving_palette = [warm_fill, cool_fill, accent, section_accent]
            group_index = int(slot_context.get("group_index", 0))
            member_index = int(slot_context.get("member_index", 0))
            member_count = max(1, int(slot_context.get("member_count", 1)))
            moving_variant_seed = stable_hash(
                "|".join(
                    [
                        str(auto_show.get("theme_name", "")),
                        str(section),
                        str(auto_show.get("motion_name", "")),
                        str(auto_show.get("look_name", "")),
                        str(auto_show.get("color_profile_name", "")),
                        str(auto_show.get("pulse_name", "")),
                    ]
                )
            )
            moving_variant_unit = (moving_variant_seed % 1000) / 999.0
            primary_bias = {
                "intro": 0.06,
                "verse": 0.12,
                "build": 0.24,
                "chorus": 0.30,
                "drop": 0.34,
                "break": 0.10,
                "outro": 0.08,
                "unknown": 0.18,
            }.get(section, 0.16)
            primary_bias += {
                "festival": 0.14,
                "club": 0.10,
                "adaptive": 0.04,
                "warm": -0.04,
                "cinematic": -0.08,
                "minimal": -0.10,
            }.get(style, 0.0)
            primary_hit_active = moving_variant_unit < clamp_unit(primary_bias)
            primary_base = stable_hash(
                "|".join(
                    [
                        str(auto_show.get("theme_name", "")),
                        str(section),
                        str(auto_show.get("color_profile_name", "")),
                    ]
                )
            ) % len(PURE_SHOW_COLORS)
            group_split_threshold = {
                "intro": 0.18,
                "verse": 0.48,
                "build": 0.68,
                "chorus": 0.80,
                "drop": 0.86,
                "break": 0.34,
                "outro": 0.28,
                "unknown": 0.54,
            }.get(section, 0.46)
            member_split_threshold = {
                "intro": 0.00,
                "verse": 0.16,
                "build": 0.44,
                "chorus": 0.60,
                "drop": 0.66,
                "break": 0.10,
                "outro": 0.08,
                "unknown": 0.28,
            }.get(section, 0.20)
            group_split_active = moving_variant_unit <= group_split_threshold
            member_split_active = (
                group_split_active
                and (
                    moving_variant_unit <= member_split_threshold
                    or pulse_name in {"chase", "snake", "beat_flash", "drop_blinder"}
                )
            )
            common_tint = moving_palette[palette_shift % len(moving_palette)]
            pair_base = (group_index * 2 + palette_shift) % len(moving_palette)
            group_tint = moving_palette[pair_base] if group_split_active else common_tint
            secondary_tint = (
                moving_palette[(pair_base + 1) % len(moving_palette)]
                if member_split_active
                else group_tint
            )
            if primary_hit_active:
                group_tint = PURE_SHOW_COLORS[(primary_base + group_index) % len(PURE_SHOW_COLORS)]
                secondary_tint = PURE_SHOW_COLORS[
                    (primary_base + group_index + 2 + member_index) % len(PURE_SHOW_COLORS)
                ]
                if not group_split_active:
                    common_tint = group_tint
            member_phase = member_index / max(1, member_count - 1) if member_count > 1 else 0.5
            member_tint = group_tint if (member_index % 2 == 0 or not member_split_active) else secondary_tint
            group_tint_mix = (
                max(warm_mix, cool_mix)
                * (0.68 if group_split_active else 0.82)
                + split_mix * (0.12 + edge_bias * (0.18 if group_split_active else 0.10))
                + abs(seed_unit) * 0.03
                + theme_contrast * 0.08
            )
            member_tint_mix = (
                (0.18 if member_split_active else 0.04)
                + split_mix * ((0.12 + member_phase * 0.10) if member_split_active else 0.03)
                + abs(member_seed_unit) * 0.03
                + energy * (0.04 if member_split_active else 0.01)
            )
            rgbw = mix_rgbw(base_rgbw, accent, accent_mix + energy * 0.04 + center_bias * 0.02)
            rgbw = mix_rgbw(rgbw, group_tint, group_tint_mix)
            rgbw = mix_rgbw(rgbw, member_tint, member_tint_mix)
            rgbw = mix_rgbw(
                rgbw,
                section_accent,
                0.03 + edge_bias * 0.05 + max(0.0, member_seed_unit) * 0.03,
            )
            if section in ("build", "chorus", "drop"):
                rgbw = mix_rgbw(
                    rgbw,
                    white_peak,
                    white_mix * 0.10 + energy * 0.003 + center_bias * 0.002 + max(0.0, seed_unit) * 0.002,
                )
            if section == "chorus":
                beat_palette = (
                    [
                        PURE_SHOW_COLORS[(primary_base + member_index) % len(PURE_SHOW_COLORS)],
                        PURE_SHOW_COLORS[(primary_base + member_index + 2) % len(PURE_SHOW_COLORS)],
                        PURE_SHOW_COLORS[(primary_base + member_index + 4) % len(PURE_SHOW_COLORS)],
                    ]
                    if primary_hit_active
                    else [group_tint, secondary_tint, accent]
                )
                beat_color = beat_palette[(beat_step - 1 + member_index + group_index) % len(beat_palette)]
                beat_mix = 0.20 if beat_step in (2, 4) and group_split_active else 0.10
                rgbw = mix_rgbw(rgbw, beat_color, beat_mix)
                if beat_step == 1:
                    rgbw = mix_rgbw(rgbw, accent, 0.08)
            elif section in ("build", "drop") and group_split_active:
                beat_palette = (
                    [
                        PURE_SHOW_COLORS[(primary_base + member_index) % len(PURE_SHOW_COLORS)],
                        PURE_SHOW_COLORS[(primary_base + member_index + 3) % len(PURE_SHOW_COLORS)],
                    ]
                    if primary_hit_active
                    else [group_tint, secondary_tint]
                )
                beat_color = beat_palette[(beat_step + member_index) % len(beat_palette)]
                rgbw = mix_rgbw(rgbw, beat_color, 0.12 if beat_step in (1, 3) else 0.06)
            if section in ("build", "chorus", "drop"):
                if snare > 0.0:
                    rgbw = mix_rgbw(rgbw, accent, 0.02 + snare * 0.07)
                if hihat > 0.0:
                    rgbw = mix_rgbw(
                        rgbw,
                        secondary_tint if member_split_active else cool_fill,
                        0.01 + hihat * 0.04,
                    )
                if kick > 0.44 and section in ("build", "drop"):
                    rgbw = mix_rgbw(rgbw, white_peak, 0.002 + kick * 0.006)
            saturation_floor = {
                "intro": 0.68,
                "verse": 0.72,
                "build": 0.78,
                "chorus": 0.80,
                "drop": 0.84,
                "break": 0.70,
                "outro": 0.68,
                "unknown": 0.74,
            }.get(section, 0.74)
            rgbw = saturate_rgbw(rgbw, minimum_saturation=saturation_floor, white_cap=0)
            rgbw = normalize_rgbw_peak(rgbw, peak_target=255, white_cap=0, minimum_peak=110)
            return clarify_rgbw(rgbw, anchor_strength=0.76, white_cap=0)

        if role == "par":
            palette_shift = int(abs(stable_hash(auto_show.get("theme_name", ""))) % 4)
            par_palette = [warm_fill, cool_fill, accent, section_accent]
            member_index = int(slot_context.get("member_index", 0))
            member_count = max(1, int(slot_context.get("member_count", 1)))
            pair_index = min(member_index, member_count - 1 - member_index)
            par_variant_seed = stable_hash(
                "|".join(
                    [
                        str(auto_show.get("theme_name", "")),
                        str(section),
                        str(auto_show.get("color_profile_name", "")),
                        "par",
                    ]
                )
            )
            par_variant_unit = (par_variant_seed % 1000) / 999.0
            par_primary_bias = {
                "intro": 0.04,
                "verse": 0.10,
                "build": 0.22,
                "chorus": 0.28,
                "drop": 0.32,
                "break": 0.08,
                "outro": 0.06,
                "unknown": 0.16,
            }.get(section, 0.14)
            par_primary_bias += {
                "festival": 0.12,
                "club": 0.08,
                "adaptive": 0.04,
                "warm": -0.04,
                "cinematic": -0.08,
                "minimal": -0.10,
            }.get(style, 0.0)
            par_primary_active = par_variant_unit < clamp_unit(par_primary_bias)
            par_primary_base = par_variant_seed % len(PURE_SHOW_COLORS)
            pair_count = max(1, (member_count + 1) // 2)
            pair_phase = pair_index / max(1, pair_count - 1) if pair_count > 1 else 0.0
            tint = par_palette[(pair_index + palette_shift) % len(par_palette)]
            secondary_tint = par_palette[(pair_index + palette_shift + 1) % len(par_palette)]
            if par_primary_active:
                tint = PURE_SHOW_COLORS[(par_primary_base + pair_index) % len(PURE_SHOW_COLORS)]
                secondary_tint = PURE_SHOW_COLORS[(par_primary_base + pair_index + 2) % len(PURE_SHOW_COLORS)]
            tint_mix = (
                max(warm_mix, cool_mix) * 0.96
                + 0.08
                + abs(seed_unit) * 0.06
                + abs(member_seed_unit) * 0.012
                + edge_bias * 0.06
                + theme_contrast * 0.10
            )
            rgbw = mix_rgbw(base_rgbw, tint, tint_mix)
            rgbw = mix_rgbw(
                rgbw,
                secondary_tint,
                0.01 + split_mix * (0.04 + pair_phase * 0.06),
            )
            rgbw = mix_rgbw(
                rgbw,
                accent,
                accent_mix * (0.18 + pair_phase * 0.10) + energy * 0.03,
            )
            if section == "chorus":
                beat_palette = (
                    [
                        PURE_SHOW_COLORS[(par_primary_base + pair_index) % len(PURE_SHOW_COLORS)],
                        PURE_SHOW_COLORS[(par_primary_base + pair_index + 3) % len(PURE_SHOW_COLORS)],
                    ]
                    if par_primary_active
                    else [warm_fill, cool_fill]
                )
                beat_color = beat_palette[(beat_step - 1 + pair_index) % len(beat_palette)]
                beat_mix = 0.22 if beat_step in (2, 4) else 0.12
                rgbw = mix_rgbw(rgbw, beat_color, beat_mix)
                if beat_step == 1:
                    rgbw = mix_rgbw(rgbw, accent, 0.08)
            if section in ("build", "chorus", "drop"):
                if snare > 0.0:
                    rgbw = mix_rgbw(rgbw, accent, 0.015 + snare * 0.05)
                if hihat > 0.0:
                    rgbw = mix_rgbw(rgbw, cool_fill, 0.01 + hihat * 0.03)
            if section in ("intro", "down", "break", "outro"):
                rgbw = mix_rgbw(rgbw, warm_fill, warm_mix * 0.28)
            saturation_floor = {
                "intro": 0.56,
                "verse": 0.62,
                "build": 0.72,
                "chorus": 0.76,
                "drop": 0.80,
                "break": 0.60,
                "outro": 0.56,
                "unknown": 0.64,
            }.get(section, 0.64)
            rgbw = saturate_rgbw(rgbw, minimum_saturation=saturation_floor, white_cap=0)
            rgbw = normalize_rgbw_peak(rgbw, peak_target=255, white_cap=0, minimum_peak=110)
            return clarify_rgbw(rgbw, anchor_strength=0.70, white_cap=0)

        if role == "wash":
            wash_palette = [cool_fill, warm_fill, section_accent]
            tint = wash_palette[(int(slot_context.get("group_index", 0)) + (0 if section in ("verse", "down", "break") else 1)) % len(wash_palette)]
            tint_mix = (
                max(warm_mix, cool_mix)
                + 0.10
                + edge_bias * 0.10
                + abs(seed_unit) * 0.05
                + abs(member_seed_unit) * 0.010
                + theme_contrast * 0.06
            )
            rgbw = mix_rgbw(base_rgbw, tint, tint_mix)
            rgbw = mix_rgbw(rgbw, white_peak, white_mix * 0.35 + (1.0 - energy) * 0.015)
            if section == "chorus":
                beat_palette = [cool_fill, warm_fill]
                beat_color = beat_palette[(beat_step - 1 + int(slot_context.get("group_index", 0))) % len(beat_palette)]
                rgbw = mix_rgbw(rgbw, beat_color, 0.10 if beat_step in (1, 3) else 0.18)
            if section in ("build", "chorus", "drop") and hihat > 0.0:
                rgbw = mix_rgbw(rgbw, section_accent, 0.01 + hihat * 0.04)
            rgbw = saturate_rgbw(rgbw, minimum_saturation=0.46, white_cap=0)
            return normalize_rgbw_peak(rgbw, peak_target=255, white_cap=0, minimum_peak=96)

        rgbw = saturate_rgbw(
            mix_rgbw(base_rgbw, accent, accent_mix + energy * 0.06),
            minimum_saturation=0.60,
            white_cap=0,
        )
        return normalize_rgbw_peak(rgbw, peak_target=255, white_cap=0, minimum_peak=110)

    def _wall_wash_zone_rgb_for_slot(self, slot_context, auto_show, osc):
        cue_name = str(auto_show.get("wash_cue_name", "soft_blue_wash"))
        cue = auto_show_wall_wash_cue(cue_name)
        frames = cue.get("frames") or [[[0, 0, 0]] * 8]
        beats_per_frame = max(0.125, float(cue.get("beats_per_frame", 1.0) or 1.0))
        beat_value = float(osc.get("beat_value") or 0.0)
        frame_index = int(math.floor(beat_value / beats_per_frame)) % max(1, len(frames))
        segments = list(frames[frame_index])

        if cue.get("mirror_on_odd") and int(slot_context.get("member_index", 0)) % 2 == 1:
            segments = list(reversed(segments))

        if cue.get("flash"):
            flash_hold = max(0.04, min(1.0, float(cue.get("flash_hold", 0.18) or 0.18)))
            phase = (beat_value / beats_per_frame) % 1.0
            if phase > flash_hold:
                segments = [WW_BLACK] * 8

        zone_rgb = []
        for segment in segments[:8]:
            red = clamp_dmx(segment[0] if len(segment) > 0 else 0)
            green = clamp_dmx(segment[1] if len(segment) > 1 else 0)
            blue = clamp_dmx(segment[2] if len(segment) > 2 else 0)
            zone_rgb.append((red, green, blue, 0))
        while len(zone_rgb) < 8:
            zone_rgb.append((0, 0, 0, 0))
        return zone_rgb

    def _wall_wash_average_rgbw(self, zone_rgb):
        if not zone_rgb:
            return (0, 0, 0, 0)
        count = max(1, len(zone_rgb))
        return (
            clamp_dmx(round(sum(int(segment[0]) for segment in zone_rgb) / count)),
            clamp_dmx(round(sum(int(segment[1]) for segment in zone_rgb) / count)),
            clamp_dmx(round(sum(int(segment[2]) for segment in zone_rgb) / count)),
            0,
        )

    def _one_shot_intensity(self, cue_id, progress):
        progress = clamp_unit(progress)
        if cue_id == "audience_riser":
            if progress >= 0.98:
                return 0.0
            if progress <= 0.02:
                return 0.0
            return clamp_unit((min(progress, 0.90) - 0.02) / 0.88)
        if cue_id == "white_hit":
            if progress <= 0.12:
                return 1.0
            return clamp_unit(1.0 - ((progress - 0.12) / 0.88)) ** 0.36
        if cue_id == "color_burst":
            if progress >= 0.92:
                return 0.0
            return 0.70 + 0.30 * math.sin(min(1.0, progress / 0.92) * math.pi)
        if cue_id == "snap_fan":
            if progress >= 0.86:
                return 0.0
            if progress <= 0.10:
                return 1.0
            return clamp_unit(1.0 - ((progress - 0.10) / 0.76)) ** 0.24
        if cue_id == "mirror_bounce":
            if progress >= 0.96:
                return 0.0
            swing = 0.5 + 0.5 * wave_sine(progress * 4.0)
            return 0.52 + swing * 0.48
        if cue_id == "par_chase_burst":
            if progress >= 0.96:
                return 0.0
            return 1.0
        return 0.0

    def _one_shot_rgbw(self, cue_id, slot_context, progress):
        alternate = float(slot_context.get("group_alternate", slot_context.get("alternate", 1.0)))
        role = str(slot_context.get("role", "static"))
        if cue_id == "white_hit":
            return (255, 255, 255, 255)
        if cue_id == "audience_riser":
            white = clamp_dmx(round(80 + min(1.0, progress / 0.88) * 140))
            return (255, 180, 70, white)
        if cue_id == "color_burst":
            return (255, 40, 150, 0) if alternate >= 0 else (0, 180, 255, 0)
        if cue_id == "snap_fan":
            return (255, 255, 255, 180)
        if cue_id == "mirror_bounce":
            return (255, 0, 190, 0) if alternate >= 0 else (0, 190, 255, 0)
        if cue_id == "par_chase_burst":
            if role == "moving":
                return (255, 170, 50, 0)
            return (0, 120, 255, 0) if alternate >= 0 else (255, 0, 160, 0)
        return None

    def _one_shot_zone_rgb(self, cue_id, slot_context, progress):
        if cue_id == "white_hit":
            return [(255, 255, 255, 255)] * 8
        if cue_id == "audience_riser":
            build = clamp_unit(min(progress, 0.90) / 0.90)
            inner = (
                clamp_dmx(round(90 + build * 165)),
                clamp_dmx(round(50 + build * 150)),
                clamp_dmx(round(20 + build * 120)),
                0,
            )
            outer = (
                clamp_dmx(round(10 + build * 80)),
                clamp_dmx(round(4 + build * 36)),
                clamp_dmx(round(build * 24)),
                0,
            )
            return [outer, outer, inner, inner, inner, inner, outer, outer]
        if cue_id == "color_burst":
            color_a = (255, 40, 150, 0)
            color_b = (0, 180, 255, 0)
            return [color_a if index % 2 == 0 else color_b for index in range(8)]
        if cue_id == "par_chase_burst":
            step = int(math.floor(progress * 8.0)) % 8
            trailing = (step - 1) % 8
            segments = []
            for index in range(8):
                if index == step:
                    segments.append((0, 140, 255, 0))
                elif index == trailing:
                    segments.append((0, 50, 140, 0))
                else:
                    segments.append((0, 0, 0, 0))
            if int(slot_context.get("member_index", 0)) % 2 == 1:
                segments.reverse()
            return segments
        return None

    def _one_shot_motion_for_config(self, cue_id, progress, slot_context, config, beat_value):
        if cue_id == "audience_riser":
            role_count = max(1, int(slot_context.get("role_count", slot_context.get("member_count", 1))))
            role_index = int(slot_context.get("role_index", slot_context.get("member_index", 0)))
            start_positions = [158, 164, 170, 176]
            end_positions = [135, 158, 182, 205]
            if role_count == 2:
                start_positions = [164, 172]
                end_positions = [148, 192]
            elif role_count <= 1:
                start_positions = [166]
                end_positions = [170]
            slot_position = min(len(start_positions) - 1, role_index if role_count > 1 else 0)
            move = clamp_unit(min(progress, 0.98) / 0.98)
            pan = round(
                start_positions[slot_position]
                + (end_positions[slot_position] - start_positions[slot_position]) * move
            )
            tilt = round(127 + (0 - 127) * move)
            return {
                "pan": clamp_dmx(pan),
                "tilt": clamp_dmx(tilt),
                "pan_tilt_speed": 32,
            }

        motion_map = {
            "snap_fan": "drop_snap_fan",
            "mirror_bounce": "mirror_bounce_show",
        }
        motion_name = motion_map.get(cue_id)
        if not motion_name:
            return None
        motion = styled_phrase_motion(
            "one_shot",
            float(beat_value or 0.0),
            motion_name,
            slot_context,
            0.92 if cue_id == "mirror_bounce" else 0.78,
            config,
        )
        return maybe_apply_member_mirror(
            motion,
            slot_context,
            cue_id == "mirror_bounce",
            config=config,
        )

    def _apply_one_shot_cue_to_effective_slot(self, effective, auto_show, osc, slot_context, capabilities):
        cue_id = one_shot_cue_name(auto_show.get("one_shot_cue"))
        if cue_id == "none" or not auto_show.get("one_shot_active"):
            return effective
        progress = clamp_unit(auto_show.get("one_shot_progress") or 0.0)
        role = str(slot_context.get("role", "static"))
        intensity = self._one_shot_intensity(cue_id, progress)

        effective["_one_shot_cue_id"] = cue_id
        effective["_one_shot_cue_progress"] = progress
        effective["osc_strobe_enabled"] = False
        effective["strobe"] = 0

        rgbw = self._one_shot_rgbw(cue_id, slot_context, progress)
        if rgbw is not None:
            effective["_auto_show_rgbw"] = rgbw
            effective["_force_rgbw_override"] = True
            effective["color"] = {
                "red": int(rgbw[0]),
                "green": int(rgbw[1]),
                "blue": int(rgbw[2]),
                "white": int(rgbw[3]),
            }

        zone_rgb = self._one_shot_zone_rgb(cue_id, slot_context, progress)
        if role == "wash" and zone_rgb is not None:
            effective["_auto_show_zone_rgb"] = zone_rgb
            effective["_auto_show_rgbw"] = self._wall_wash_average_rgbw(zone_rgb)

        if cue_id == "par_chase_burst" and role == "par":
            effective["_auto_show_rhythm_mode"] = "pair_swap"
            effective["beat_pulse_enabled"] = True
            effective["beat_depth"] = 255
            effective["beat_decay_ms"] = 90
            effective["dimmer"] = max(effective["dimmer"], 230)
            return effective

        effective["beat_pulse_enabled"] = False
        effective["_auto_show_rhythm_mode"] = "full_on"

        if role == "moving" and cue_id in {"audience_riser", "snap_fan", "mirror_bounce"}:
            if cue_id == "snap_fan":
                effective["pan_tilt_speed"] = 0
            elif cue_id == "mirror_bounce":
                effective["pan_tilt_speed"] = 24
            else:
                effective["pan_tilt_speed"] = 32

        if cue_id == "par_chase_burst":
            effective["dimmer"] = clamp_dmx(round((220 if role == "moving" else 255) * intensity))
        else:
            base_peak = 255 if role != "wash" else 220
            effective["dimmer"] = clamp_dmx(round(base_peak * intensity))
        return effective

    def _live_override_active(self, auto_show):
        return bool(
            live_override_color_name(auto_show.get("override_color")) != "none"
            or auto_show.get("override_manual_strobe")
            or auto_show.get("override_audience_sweep")
            or auto_show.get("override_all_on")
            or auto_show.get("override_par_chase")
            or auto_show.get("override_par_snake")
            or auto_show.get("one_shot_active")
        )

    def _live_override_rainbow_rgbw(self, osc, slot_context):
        palette = [
            (255, 0, 0, 0),
            (255, 220, 0, 0),
            (0, 255, 0, 0),
            (0, 255, 255, 0),
            (0, 80, 255, 0),
            (180, 0, 255, 0),
            (255, 120, 0, 0),
            (255, 255, 255, 255),
        ]
        beat_value = osc.get("beat_value")
        beat_step = int(math.floor(float(beat_value or 0.0)))
        fixture_index = int(
            slot_context.get(
                "global_index",
                slot_context.get("group_index", slot_context.get("member_index", 0)),
            )
        )
        return palette[(beat_step + fixture_index) % len(palette)]

    def _live_override_rgbw_for_slot(self, override_color, slot_context, osc):
        color_name = live_override_color_name(override_color)
        if color_name == "none":
            return None
        if color_name != "rainbow":
            return LIVE_OVERRIDE_COLORS[color_name]

        return self._live_override_rainbow_rgbw(osc, slot_context)

    def _live_override_zone_rgb_for_slot(self, override_color, slot_context, osc):
        color_name = live_override_color_name(override_color)
        if color_name == "none":
            return None
        if color_name == "rainbow":
            rgbw = self._live_override_rainbow_rgbw(osc, slot_context)
            return [rgbw] * 8
        rgbw = LIVE_OVERRIDE_COLORS[color_name]
        return [rgbw] * 8

    def _slot_key_base_for_fixture(self, fixture_id):
        label_base = fixture_preset(fixture_id)["label_base"].lower()
        normalized = "".join(ch if ch.isalnum() else "_" for ch in label_base).strip("_")
        if not normalized:
            normalized = "fixture"
        return normalized

    def _next_slot_id(self, config, fixture_id):
        base = self._slot_key_base_for_fixture(fixture_id)
        if base not in config["slots"]:
            return base
        suffix = 2
        while f"{base}_{suffix}" in config["slots"]:
            suffix += 1
        return f"{base}_{suffix}"

    def _next_slot_label(self, config, label_base):
        used = {slot_config["label"] for slot_config in config["slots"].values()}
        if label_base not in used:
            return label_base
        suffix = 2
        while f"{label_base} {suffix}" in used:
            suffix += 1
        return f"{label_base} {suffix}"

    def _next_available_address(self, config, fixture, mode_name):
        footprint = int(find_mode(fixture, mode_name)["footprint"])
        ranges = []
        for slot_id, slot_config in config["slots"].items():
            slot_range = self._range_for_slot(slot_id, slot_config)
            if slot_range:
                ranges.append((slot_range["address"], slot_range["last_channel"]))
        candidate = 1
        for start, end in sorted(ranges):
            if candidate + footprint - 1 < start:
                return candidate
            candidate = max(candidate, end + 1)
        if candidate + footprint - 1 <= DMX_CHANNELS:
            return candidate
        return max(1, DMX_CHANNELS - footprint + 1)

    def _range_for_slot(self, slot_id, config):
        try:
            fixture = find_fixture(FIXTURE_LIBRARY, config["fixture"])
            mode = find_mode(fixture, config["mode"])
            address = int(config["address"])
            return {
                "slot_id": slot_id,
                "label": config["label"],
                "enabled": config["enabled"],
                "fixture_label": f"{fixture['manufacturer']} {fixture['model']}",
                "mode": mode["name"],
                "address": address,
                "last_channel": address + int(mode["footprint"]) - 1,
            }
        except Exception:
            return None

    def _fixture_motion_ranges(self, fixture):
        pan_range = float(fixture.get("pan_range") or 180.0)
        tilt_range = float(fixture.get("tilt_range") or 90.0)
        return max(90.0, pan_range), max(45.0, tilt_range)

    @staticmethod
    def _dmx_to_degrees(value, axis_range):
        return ((float(value) / 255.0) - 0.5) * float(axis_range)

    @staticmethod
    def _degrees_to_dmx(value, axis_range):
        axis_range = max(1.0, float(axis_range))
        normalized = (float(value) / axis_range) + 0.5
        return clamp_dmx(round(normalized * 255.0))

    @staticmethod
    def _degrees_to_dmx16(value, axis_range):
        axis_range = max(1.0, float(axis_range))
        normalized = (float(value) / axis_range) + 0.5
        normalized = max(0.0, min(1.0, normalized))
        return max(0, min(65535, int(round(normalized * 65535.0))))

    @staticmethod
    def _apply_axis_calibration(logical_degrees, axis_range, invert, offset_deg, span_percent):
        calibrated = float(logical_degrees) * max(0.01, float(span_percent) / 100.0)
        if invert:
            calibrated *= -1.0
        calibrated += float(offset_deg)
        half_range = max(1.0, float(axis_range) / 2.0)
        return max(-half_range, min(half_range, calibrated))

    @staticmethod
    def _remove_axis_calibration(calibrated_degrees, axis_range, invert, offset_deg, span_percent):
        logical = float(calibrated_degrees) - float(offset_deg)
        if invert:
            logical *= -1.0
        logical /= max(0.01, float(span_percent) / 100.0)
        half_range = max(1.0, float(axis_range) / 2.0)
        return max(-half_range, min(half_range, logical))

    def _axis_motion_profile(self, axis_range, speed_value, axis_name):
        speed_ratio = 1.0 - clamp_unit(float(speed_value or 0) / 255.0)
        if axis_name == "pan":
            # Realistic, but still visibly responsive for compact moving heads:
            # full 540 degree travel usually lands around 3-7 seconds depending on speed.
            fast_travel_seconds = 2.8
            slow_travel_seconds = 5.2
        else:
            # Tilt travel is typically faster than pan on these fixtures.
            fast_travel_seconds = 1.7
            slow_travel_seconds = 3.3
        travel_seconds = slow_travel_seconds - (
            (slow_travel_seconds - fast_travel_seconds) * speed_ratio
        )
        max_speed = float(axis_range) / max(0.5, travel_seconds)
        max_accel = max_speed * (1.08 + speed_ratio * 0.62)
        response_window = max(0.18, 0.42 - speed_ratio * 0.12)
        return max_speed, max_accel, response_window

    @staticmethod
    def _step_motion_axis(current, velocity, target, dt, max_speed, max_accel, response_window):
        if dt <= 0:
            return current, velocity

        delta = target - current
        if abs(delta) < 0.01 and abs(velocity) < 0.01:
            return target, 0.0

        desired_velocity = max(
            -max_speed,
            min(max_speed, delta / max(response_window, dt)),
        )
        if desired_velocity > velocity:
            velocity = min(desired_velocity, velocity + max_accel * dt)
        else:
            velocity = max(desired_velocity, velocity - max_accel * dt)

        next_value = current + velocity * dt
        if (target - current) == 0 or ((target - current) > 0) != ((target - next_value) > 0):
            next_value = target
            velocity = 0.0
        return next_value, velocity

    def _realized_motion(self, slot_id, fixture, config, desired_pan, desired_tilt, motion_active, now, advance=True):
        pan_range, tilt_range = self._fixture_motion_ranges(fixture)
        logical_target_pan_deg = self._dmx_to_degrees(desired_pan, pan_range)
        logical_target_tilt_deg = self._dmx_to_degrees(desired_tilt, tilt_range)
        target_pan_deg = self._apply_axis_calibration(
            logical_target_pan_deg,
            pan_range,
            bool(config.get("pan_invert")),
            int(config.get("pan_offset_deg", 0) or 0),
            int(config.get("pan_span_percent", 100) or 100),
        )
        target_tilt_deg = self._apply_axis_calibration(
            logical_target_tilt_deg,
            tilt_range,
            bool(config.get("tilt_invert")),
            int(config.get("tilt_offset_deg", 0) or 0),
            int(config.get("tilt_span_percent", 100) or 100),
        )
        speed_value = int(config.get("pan_tilt_speed", 0) or 0)
        state = self.motion_states.get(slot_id)

        if state is None:
            state = {
                "pan_deg": target_pan_deg,
                "tilt_deg": target_tilt_deg,
                "pan_velocity": 0.0,
                "tilt_velocity": 0.0,
                "updated_at": now,
            }
            self.motion_states[slot_id] = state

        current_pan_deg = float(state.get("pan_deg", target_pan_deg))
        current_tilt_deg = float(state.get("tilt_deg", target_tilt_deg))
        pan_velocity = float(state.get("pan_velocity", 0.0))
        tilt_velocity = float(state.get("tilt_velocity", 0.0))
        pan_speed_dps = abs(pan_velocity)
        tilt_speed_dps = abs(tilt_velocity)

        if advance:
            dt = max(1.0 / 240.0, min(0.20, now - float(state.get("updated_at", now))))
            pan_profile = self._axis_motion_profile(pan_range, speed_value, "pan")
            tilt_profile = self._axis_motion_profile(tilt_range, speed_value, "tilt")
            current_pan_deg, pan_velocity = self._step_motion_axis(
                current_pan_deg,
                pan_velocity,
                target_pan_deg,
                dt,
                *pan_profile,
            )
            current_tilt_deg, tilt_velocity = self._step_motion_axis(
                current_tilt_deg,
                tilt_velocity,
                target_tilt_deg,
                dt,
                *tilt_profile,
            )
            pan_speed_dps = abs(pan_velocity)
            tilt_speed_dps = abs(tilt_velocity)
            state.update(
                {
                    "pan_deg": current_pan_deg,
                    "tilt_deg": current_tilt_deg,
                    "pan_velocity": pan_velocity,
                    "tilt_velocity": tilt_velocity,
                    "updated_at": now,
                }
            )

        still_moving = (
            abs(target_pan_deg - current_pan_deg) > 0.35
            or abs(target_tilt_deg - current_tilt_deg) > 0.35
            or pan_speed_dps > 0.5
            or tilt_speed_dps > 0.5
        )
        logical_current_pan_deg = self._remove_axis_calibration(
            current_pan_deg,
            pan_range,
            bool(config.get("pan_invert")),
            int(config.get("pan_offset_deg", 0) or 0),
            int(config.get("pan_span_percent", 100) or 100),
        )
        logical_current_tilt_deg = self._remove_axis_calibration(
            current_tilt_deg,
            tilt_range,
            bool(config.get("tilt_invert")),
            int(config.get("tilt_offset_deg", 0) or 0),
            int(config.get("tilt_span_percent", 100) or 100),
        )
        pan_16bit = self._degrees_to_dmx16(current_pan_deg, pan_range)
        tilt_16bit = self._degrees_to_dmx16(current_tilt_deg, tilt_range)

        return {
            "pan": (pan_16bit >> 8) & 0xFF,
            "pan_fine": pan_16bit & 0xFF,
            "tilt": (tilt_16bit >> 8) & 0xFF,
            "tilt_fine": tilt_16bit & 0xFF,
            "target_pan": clamp_dmx(desired_pan),
            "target_tilt": clamp_dmx(desired_tilt),
            "pan_range": pan_range,
            "tilt_range": tilt_range,
            "pan_degrees": current_pan_deg,
            "tilt_degrees": current_tilt_deg,
            "target_pan_degrees": target_pan_deg,
            "target_tilt_degrees": target_tilt_deg,
            "logical_pan_degrees": logical_current_pan_deg,
            "logical_tilt_degrees": logical_current_tilt_deg,
            "logical_target_pan_degrees": logical_target_pan_deg,
            "logical_target_tilt_degrees": logical_target_tilt_deg,
            "pan_speed_dps": pan_speed_dps,
            "tilt_speed_dps": tilt_speed_dps,
            "motion_active": bool(motion_active or still_moving),
        }

    def _render_values(self, now, advance_motion=True, config=None, osc=None, auto_show=None):
        config = config or self._clean_full_config(dict(self.config))
        osc = osc or self.osc.snapshot_for_render()
        auto_show = auto_show or self._auto_show_state(osc, config["auto_show"])
        osc = self._behavior_osc(osc, auto_show)
        return self._render_values_with_context(
            now,
            config,
            osc,
            auto_show,
            advance_motion=advance_motion,
        )

    def _observe_active_playback_generation(self, osc):
        generation = osc.get("_playback_generation")
        if not isinstance(generation, int):
            return
        if self.last_playback_generation == generation:
            return
        previous_generation = self.last_playback_generation
        self.last_playback_generation = generation
        if previous_generation is None:
            return
        self.motion_states.clear()
        self.slot_rhythm_states.clear()
        self.last_slot_trigger_signatures.clear()
        self.last_slot_rhythm_signatures.clear()
        self.last_slot_strobe_outputs.clear()
        self.last_auto_show_signature = None
        self.outro_behavior_state = None
        self.active_one_shot_cue = None
        self.playback_runtime_resets += 1
        self.debug_log.log(
            "PLAYBACK_SOURCE_RESET",
            source=osc.get("_active_playback_source"),
            generation=generation,
            transition=osc.get("_playback_event"),
        )

    def _build_slot_previews(self, config, osc, now, auto_show=None):
        auto_show = auto_show or self._auto_show_state(osc, config.get("auto_show", {}))
        osc = self._behavior_osc(osc, auto_show)
        return {
            slot_id: self._preview_for_slot(
                slot_id,
                slot_config,
                osc,
                now,
                full_config=config,
                auto_show=auto_show,
            )
            for slot_id, slot_config in config["slots"].items()
        }

    def _render_values_with_context(self, now, config, osc, auto_show, advance_motion=True):
        if config["blackout_active"]:
            self.conflicts = []
            return {}
        osc = self._behavior_osc(osc, auto_show)
        self._observe_structure_behavior_source(auto_show)
        self._log_auto_show_transition(auto_show, osc)
        merged_values = {}
        owners = {}
        conflicts = []
        for slot_id in config["slot_order"]:
            slot_config = config["slots"][slot_id]
            if not slot_config["enabled"]:
                continue
            effective_slot_config = self._effective_slot_config(
                slot_id, slot_config, osc, auto_show, full_config=config
            )
            self._log_slot_trigger_state(slot_id, effective_slot_config, auto_show, osc)
            slot_values = self._render_slot_values(
                slot_id,
                effective_slot_config,
                osc,
                now,
                advance_motion=advance_motion,
            )
            for channel, value in slot_values.items():
                previous_owner = owners.get(channel)
                if previous_owner and previous_owner != slot_id:
                    conflicts.append(
                        {
                            "channel": channel,
                            "first": previous_owner,
                            "second": slot_id,
                        }
                    )
                owners[channel] = slot_id
                merged_values[channel] = value
        self.conflicts = conflicts
        return merged_values

    def _structure_behavior_state(self, osc):
        source_getter = getattr(self.osc, "structure_behavior_source", None)
        selected_source = source_getter() if callable(source_getter) else "legacy"
        if self.structure_behavior_bridge is None:
            return {
                "selected_source": selected_source,
                "effective_source": "legacy",
                "eligible": False,
                "fallback_reason": "structure_bridge_unavailable",
                "legacy_phrase": osc.get("phrase_current"),
                "mapped_behavior_bucket": None,
                "song_analyzer_label": None,
                "projection": None,
            }
        return self.structure_behavior_bridge.resolve(selected_source, osc)

    def _observe_structure_behavior_source(self, auto_show):
        behavior = (auto_show or {}).get("structure_behavior") or {}
        source = (
            behavior.get("selected_source", "legacy"),
            behavior.get("effective_source", "legacy"),
        )
        if self.last_structure_behavior_source == source:
            return
        previous = self.last_structure_behavior_source
        self.last_structure_behavior_source = source
        if previous is None:
            return
        self.motion_states.clear()
        self.slot_rhythm_states.clear()
        self.last_slot_trigger_signatures.clear()
        self.last_slot_rhythm_signatures.clear()
        self.last_slot_strobe_outputs.clear()
        self.outro_behavior_state = None
        self.debug_log.log(
            "STRUCTURE_BEHAVIOR_SOURCE_RESET",
            previous_selected=previous[0],
            previous_effective=previous[1],
            selected=source[0],
            effective=source[1],
        )

    @staticmethod
    def _behavior_osc(osc, auto_show):
        effective = dict(osc or {})
        behavior = (auto_show or {}).get("structure_behavior") or {}
        if behavior.get("effective_source") == "song_analyzer":
            effective["phrase_current"] = behavior.get("mapped_behavior_bucket")
        return effective

    def _log_auto_show_transition(self, auto_show, osc):
        signature = (
            bool(auto_show.get("enabled")),
            str(auto_show.get("style")),
            str(auto_show.get("phrase_bucket")),
            str(auto_show.get("cue_label")),
            str(auto_show.get("rhythm_mode")),
            bool(auto_show.get("beat_pulse")),
            bool(auto_show.get("strobe_window")),
            bool(auto_show.get("external_strobe")),
            str((auto_show.get("structure_behavior") or {}).get("effective_source")),
            str((auto_show.get("structure_behavior") or {}).get("song_analyzer_label")),
            str((auto_show.get("waveform_analysis") or {}).get("state", "neutral")),
        )
        if signature == self.last_auto_show_signature:
            return
        self.last_auto_show_signature = signature
        self.debug_log.log(
            "AUTOSHOW",
            enabled=auto_show.get("enabled"),
            style=auto_show.get("style"),
            phrase=osc.get("phrase_current"),
            structure_source=(auto_show.get("structure_behavior") or {}).get("effective_source"),
            structure_label=(auto_show.get("structure_behavior") or {}).get("song_analyzer_label"),
            cue=auto_show.get("cue_label"),
            rhythm=auto_show.get("rhythm_mode"),
            beat=auto_show.get("beat_pulse"),
            strobe=auto_show.get("strobe_window"),
            external_strobe=auto_show.get("external_strobe"),
            waveform=(auto_show.get("waveform_analysis") or {}).get("state", "neutral"),
            mood=osc.get("mood"),
            bank=osc.get("color_bank"),
        )

    def _log_slot_trigger_state(self, slot_id, config, auto_show, osc):
        slot_context = config.get("_slot_context") or {}
        role = slot_context.get("role", "static")
        signature = (
            str(config.get("_auto_show_motion_name", "")),
            str(config.get("_auto_show_rhythm_mode", "")),
            bool(config.get("beat_pulse_enabled")),
            bool(config.get("osc_strobe_enabled")),
            bool(osc.get("strobe_active")),
            int(config.get("strobe", 0) or 0),
        )
        if self.last_slot_trigger_signatures.get(slot_id) == signature:
            return
        self.last_slot_trigger_signatures[slot_id] = signature
        self.debug_log.log(
            "SLOT_TRIGGER",
            slot=slot_id,
            label=config.get("label"),
            role=role,
            motion=config.get("_auto_show_motion_name"),
            rhythm=config.get("_auto_show_rhythm_mode"),
            beat=config.get("beat_pulse_enabled"),
            osc_strobe=config.get("osc_strobe_enabled"),
            strobe_active=osc.get("strobe_active"),
            cue=auto_show.get("cue_label"),
        )

    def _external_strobe_gate(self, osc, role):
        count_in = osc.get("strobe_count_in")
        active = bool(osc.get("strobe_active"))
        if active:
            return True
        if count_in not in (1, 2):
            return False

        age = osc.get("beat_phase_age_seconds")
        if age is None:
            last_beat_at = osc.get("last_beat_at")
            if not last_beat_at:
                return False
            age = time.time() - last_beat_at

        beat_value = osc.get("beat_value")
        if beat_value is None:
            return False

        section = phrase_bucket(osc.get("phrase_current"))
        beat_step = int(math.floor(float(beat_value))) % 8

        if count_in in (1, 2):
            hit_steps = (0, 2, 4, 6)
            if section == "drop":
                open_window = 0.18 if role in ("moving", "par") else 0.14
            elif section in ("build", "chorus"):
                open_window = 0.16 if role in ("moving", "par") else 0.12
            else:
                open_window = 0.14 if role in ("moving", "par") else 0.10
        else:
            return False

        return beat_step in hit_steps and float(age) <= open_window

    def _effective_strobe_state(self, config, osc):
        strobe = int(config.get("strobe", 0) or 0)
        external_strobe_applied = False
        role = str((config.get("_slot_context") or {}).get("role", "static"))
        if (
            config["sync_enabled"]
            and config["osc_strobe_enabled"]
            and self._external_strobe_gate(osc, role)
        ):
            strobe_floor = 235 if role in ("par", "moving") else 220
            strobe = max(strobe, strobe_floor)
            external_strobe_applied = True
        return strobe, external_strobe_applied

    def _motion_uses_locked_rgbw(self, motion, config):
        if not motion or bool(config.get("_force_rgbw_override")):
            return False
        return bool(motion.get("lock_color"))

    def _effective_brightness_with_motion(self, config, motion, osc, now):
        rhythm_brightness = self._brightness_for_config(config, osc, now)
        if not motion or motion.get("dimmer") is None:
            return rhythm_brightness

        motion_dimmer = clamp_dmx(motion.get("dimmer"))
        configured_dimmer = max(1, int(config.get("dimmer", 0) or 0))
        rhythm_ratio = max(0.0, float(rhythm_brightness) / float(configured_dimmer))
        return clamp_dmx(round(motion_dimmer * rhythm_ratio))

    def _render_slot_values(self, slot_id, config, osc, now, advance_motion=True):
        fixture = find_fixture(FIXTURE_LIBRARY, config["fixture"])
        mode = find_mode(fixture, config["mode"])
        address = int(config["address"])
        last_channel = address + int(mode["footprint"]) - 1
        if last_channel > DMX_CHANNELS:
            raise ValueError(
                f"{config['label']} ends at channel {last_channel}, outside DMX universe"
            )

        motion = self._motion_for_config(slot_id, config, osc)
        capabilities = self._capabilities_for_slot(config)
        if self._motion_uses_locked_rgbw(motion, config):
            rgbw = tuple(motion.get("rgbw", self._rgbw_for_config(config, osc)))
        else:
            rgbw = self._rgbw_for_config(config, osc)
        brightness = self._effective_brightness_with_motion(config, motion, osc, now)
        if capabilities.get("dimmer"):
            output_rgbw = tuple(clamp_dmx(component) for component in rgbw)
        else:
            output_rgbw = tuple(round(component * brightness / 255) for component in rgbw)
        zone_rgb = config.get("_auto_show_zone_rgb")
        output_zone_rgb = None
        if zone_rgb is not None:
            output_zone_rgb = [
                (
                    round(int(segment[0]) * brightness / 255),
                    round(int(segment[1]) * brightness / 255),
                    round(int(segment[2]) * brightness / 255),
                    round(int(segment[3]) * brightness / 255) if len(segment) > 3 else 0,
                )
                for segment in zone_rgb
            ]
        desired_pan = motion["pan"] if motion else config["pan"]
        desired_tilt = motion["tilt"] if motion else config["tilt"]
        realized_motion = self._realized_motion(
            slot_id,
            fixture,
            config,
            desired_pan,
            desired_tilt,
            bool(motion),
            now,
            advance=advance_motion,
        )

        strobe_input = int(config.get("strobe", 0) or 0)
        if motion and motion.get("strobe") is not None:
            strobe_input = max(strobe_input, clamp_dmx(motion.get("strobe")))
        strobe_config = config if strobe_input == int(config.get("strobe", 0) or 0) else {**config, "strobe": strobe_input}
        strobe, external_strobe_applied = self._effective_strobe_state(strobe_config, osc)
        program_value = (
            clamp_dmx(motion.get("program"))
            if motion and motion.get("program") is not None
            else config["program"]
        )
        speed_value = (
            clamp_dmx(motion.get("speed"))
            if motion and motion.get("speed") is not None
            else config["speed"]
        )
        previous_strobe_state = self.last_slot_strobe_outputs.get(slot_id)
        current_strobe_state = (external_strobe_applied, int(strobe))
        if previous_strobe_state != current_strobe_state:
            self.last_slot_strobe_outputs[slot_id] = current_strobe_state
            self.debug_log.log(
                "SLOT_STROBE",
                slot=slot_id,
                label=config.get("label"),
                active=external_strobe_applied,
                value=strobe,
            )

        use_fine_pan_tilt = bool(config.get("use_fine_pan_tilt", True))
        resolved_extra_values = self._resolved_fixture_extra_values(
            config,
            mode,
            rgbw,
            brightness,
            strobe,
            osc,
        )
        return values_for_fixture(
            mode,
            address,
            output_rgbw,
            brightness,
            realized_motion["pan"],
            realized_motion["tilt"],
            pan_fine=realized_motion.get("pan_fine", 0) if use_fine_pan_tilt else 0,
            tilt_fine=realized_motion.get("tilt_fine", 0) if use_fine_pan_tilt else 0,
            strobe=strobe,
            speed=speed_value,
            program=program_value,
            auto_mode=0,
            pan_tilt_speed=config["pan_tilt_speed"],
            reset=0,
            zone_rgb=output_zone_rgb,
            extra_values=resolved_extra_values,
        )

    def _preview_for_slot(self, slot_id, config, osc, now, full_config=None, auto_show=None):
        full_config = full_config or self._clean_full_config(dict(self.config))
        auto_show = auto_show or self._auto_show_state(
            osc, full_config.get("auto_show", {})
        )
        effective_config = self._effective_slot_config(
            slot_id,
            config,
            osc,
            auto_show,
            full_config=full_config,
        )
        fixture = find_fixture(FIXTURE_LIBRARY, effective_config["fixture"])
        motion = self._motion_for_config(slot_id, effective_config, osc)
        desired_pan = motion["pan"] if motion else effective_config["pan"]
        desired_tilt = motion["tilt"] if motion else effective_config["tilt"]
        realized_motion = self._realized_motion(
            slot_id,
            fixture,
            effective_config,
            desired_pan,
            desired_tilt,
            bool(motion),
            now,
            advance=False,
        )
        rgbw = (
            tuple(motion.get("rgbw", self._rgbw_for_config(effective_config, osc)))
            if self._motion_uses_locked_rgbw(motion, effective_config)
            else self._rgbw_for_config(effective_config, osc)
        )
        brightness = 0
        if effective_config["enabled"]:
            brightness = self._effective_brightness_with_motion(
                effective_config,
                motion,
                osc,
                now,
            )
        output_rgbw = tuple(round(component * brightness / 255) for component in rgbw)
        strobe_input = int(effective_config.get("strobe", 0) or 0)
        if motion and motion.get("strobe") is not None:
            strobe_input = max(strobe_input, clamp_dmx(motion.get("strobe")))
        strobe_config = (
            effective_config
            if strobe_input == int(effective_config.get("strobe", 0) or 0)
            else {**effective_config, "strobe": strobe_input}
        )
        strobe, external_strobe_applied = self._effective_strobe_state(strobe_config, osc)
        resolved_extra_values = self._resolved_fixture_extra_values(
            effective_config,
            find_mode(fixture, effective_config["mode"]),
            rgbw,
            brightness,
            strobe,
            osc,
        )
        spot_preview = self._fixture_preview_payload(
            fixture,
            find_mode(fixture, effective_config["mode"]),
            resolved_extra_values,
        )
        return {
            "enabled": bool(effective_config["enabled"]),
            "red": output_rgbw[0],
            "green": output_rgbw[1],
            "blue": output_rgbw[2],
            "white": output_rgbw[3],
            **spot_preview,
            "brightness": brightness,
            "strobe": strobe,
            "strobe_active": bool(strobe > 0 and effective_config["enabled"]),
            "strobe_external": external_strobe_applied,
            "pan": realized_motion["pan"],
            "tilt": realized_motion["tilt"],
            "target_pan": realized_motion["target_pan"],
            "target_tilt": realized_motion["target_tilt"],
            "pan_range": realized_motion["pan_range"],
            "tilt_range": realized_motion["tilt_range"],
            "pan_degrees": realized_motion["pan_degrees"],
            "tilt_degrees": realized_motion["tilt_degrees"],
            "target_pan_degrees": realized_motion["target_pan_degrees"],
            "target_tilt_degrees": realized_motion["target_tilt_degrees"],
            "logical_pan_degrees": realized_motion["logical_pan_degrees"],
            "logical_tilt_degrees": realized_motion["logical_tilt_degrees"],
            "logical_target_pan_degrees": realized_motion["logical_target_pan_degrees"],
            "logical_target_tilt_degrees": realized_motion["logical_target_tilt_degrees"],
            "pan_speed_dps": realized_motion["pan_speed_dps"],
            "tilt_speed_dps": realized_motion["tilt_speed_dps"],
            "pan_tilt_speed": effective_config["pan_tilt_speed"],
            "motion_active": realized_motion["motion_active"],
        }

    def _auto_show_state(self, osc, auto_show_config):
        config = self._clean_auto_show_config(auto_show_config)
        now = time.time()
        override_phrase = auto_show_phrase_override_name(config.get("override_phrase"))
        override_color = live_override_color_name(config.get("override_color"))
        override_energy = live_override_energy_name(config.get("override_energy"))
        override_manual_strobe = bool(config.get("override_manual_strobe"))
        override_audience_sweep = bool(config.get("override_audience_sweep"))
        override_all_on = bool(config.get("override_all_on"))
        override_par_chase = bool(config.get("override_par_chase"))
        override_par_snake = bool(config.get("override_par_snake"))
        one_shot = self._resolved_one_shot_cue_state(osc, now)
        audience_pan_focus_enabled = bool(config.get("audience_pan_focus_enabled", True))
        try:
            audience_pan_min = clamp_dmx(int(config.get("audience_pan_min", 135)))
        except (TypeError, ValueError):
            audience_pan_min = 135
        try:
            audience_pan_max = clamp_dmx(int(config.get("audience_pan_max", 205)))
        except (TypeError, ValueError):
            audience_pan_max = 205
        if audience_pan_max < audience_pan_min:
            audience_pan_min, audience_pan_max = audience_pan_max, audience_pan_min
        default_turn_min, default_turn_max = _default_turn_audience_pan_limits(
            audience_pan_min,
            audience_pan_max,
        )
        try:
            audience_turn_pan_min = clamp_dmx(
                int(config.get("audience_turn_pan_min", default_turn_min))
            )
        except (TypeError, ValueError):
            audience_turn_pan_min = default_turn_min
        try:
            audience_turn_pan_max = clamp_dmx(
                int(config.get("audience_turn_pan_max", default_turn_max))
            )
        except (TypeError, ValueError):
            audience_turn_pan_max = default_turn_max
        if audience_turn_pan_max < audience_turn_pan_min:
            audience_turn_pan_min, audience_turn_pan_max = (
                audience_turn_pan_max,
                audience_turn_pan_min,
            )
        try:
            audience_tilt_split = clamp_dmx(int(config.get("audience_tilt_split", 127)))
        except (TypeError, ValueError):
            audience_tilt_split = 127
        override_active = bool(
            override_color != "none"
            or override_manual_strobe
            or override_audience_sweep
            or override_all_on
            or override_par_chase
            or override_par_snake
            or one_shot
        )
        style_name = config["style"]
        style = auto_show_style(style_name)
        osc_effective = dict(osc)
        structure_behavior = self._structure_behavior_state(osc)
        if override_phrase != "none":
            osc_effective["phrase_current"] = override_phrase
        elif structure_behavior["effective_source"] == "song_analyzer":
            osc_effective["phrase_current"] = structure_behavior["mapped_behavior_bucket"]
        if structure_behavior["effective_source"] != "song_analyzer":
            self._prewarm_track_show_plans(style_name, osc_effective)
        section = (
            override_phrase
            if override_phrase != "none"
            else phrase_bucket(osc_effective.get("phrase_current"))
        )
        beat_value = float(osc.get("beat_value") or 0.0)
        beat_step = int(math.floor(beat_value)) % 4 + 1
        bpm = float(osc.get("bpm") or 0.0)
        bpm_factor = clamp_unit((bpm - 92.0) / 48.0) if bpm > 0 else 0.45
        mood = osc.get("mood")
        mood_factor = mood_factor_from_value(mood)
        effective_mood_factor = auto_show_refined_mood_factor(
            override_energy,
            mood_factor,
        )
        waveform_analysis = osc.get("waveform_analysis") or {}
        waveform_bands = osc_waveform_band_profile(osc_effective)
        waveform_lookahead_2 = osc_waveform_lookahead_profile(osc_effective, 2)
        waveform_lookahead_4 = osc_waveform_lookahead_profile(osc_effective, 4)
        drum_profile = osc_drum_profile(osc_effective)
        current_band_activity = weighted_band_activity(waveform_bands) or 0.0
        lookahead_activity_2 = waveform_lookahead_2.get("activity")
        lookahead_activity_4 = waveform_lookahead_4.get("activity")
        anticipation = clamp_unit(
            max(
                0.0,
                (lookahead_activity_2 or current_band_activity) - current_band_activity,
                ((lookahead_activity_4 or current_band_activity) - current_band_activity) * 0.75,
            )
        )
        waveform_energy = osc.get("waveform_energy")
        waveform_factor = (
            clamp_unit(waveform_energy)
            if waveform_energy is not None
            else None
        )
        live_behavior_section, outro_activity = self._resolved_behavior_section(
            section,
            beat_value,
            osc_effective,
            waveform_factor=waveform_factor,
            waveform_bands=waveform_bands,
            waveform_lookahead_2=waveform_lookahead_2,
            waveform_lookahead_4=waveform_lookahead_4,
            drum_profile=drum_profile,
            waveform_analysis=waveform_analysis,
        )
        # A current exact SongAnalyzer segment is the structure authority. Do
        # not let the older preview-derived plan replace that same input.
        planned_scene = (
            None
            if structure_behavior["effective_source"] == "song_analyzer"
            else self._planned_scene_variants(style_name, osc_effective)
        )
        behavior_section = (
            str(planned_scene.get("section") or live_behavior_section)
            if planned_scene
            else live_behavior_section
        )
        profile = auto_show_profile(behavior_section)
        scene = planned_scene or auto_show_scene_variants(style_name, behavior_section, osc)
        track_theme = auto_show_track_theme(scene["theme_name"])
        base_energy = clamp_unit(
            profile["energy"]
            + (bpm_factor - 0.5) * 0.18
            + (effective_mood_factor - 0.5) * 0.10
            + style["energy_bias"]
            + float(track_theme.get("energy_bias", 0.0))
        )
        if waveform_factor is not None:
            base_energy = clamp_unit(base_energy + (waveform_factor - 0.5) * 0.05)
        if waveform_bands["has_data"]:
            base_energy = clamp_unit(
                base_energy
                + ((waveform_bands["low"] or 0.0) - 0.5) * 0.06
                + ((waveform_bands["mid"] or 0.0) - 0.5) * 0.025
                + ((waveform_bands["high"] or 0.0) - 0.5) * 0.015
            )
        if anticipation > 0.0 and behavior_section in {"build", "chorus", "drop", "down", "outro"}:
            base_energy = clamp_unit(base_energy + anticipation * 0.035)
        base_energy = clamp_unit(
            base_energy
            + float(waveform_analysis.get("lift") or 0.0) * 0.06
            + float(waveform_analysis.get("transient") or 0.0) * 0.03
            + drum_profile["impact"] * 0.04
            + drum_profile["sparkle"] * 0.015
        )
        rich_current = ((structure_behavior.get("projection") or {}).get("rich_current") or {}) \
            if structure_behavior["effective_source"] == "song_analyzer" else {}
        song_analyzer_energy = rich_current.get("energy")
        if isinstance(song_analyzer_energy, bool) or not isinstance(song_analyzer_energy, (int, float)) \
                or not math.isfinite(float(song_analyzer_energy)):
            song_analyzer_energy = None
        song_analyzer_energy_modifier = 0.0 if song_analyzer_energy is None else max(
            -SONG_ANALYZER_MAX_ENERGY_MODIFIER,
            min(SONG_ANALYZER_MAX_ENERGY_MODIFIER,
                float(song_analyzer_energy) * SONG_ANALYZER_ENERGY_Z_SCORE_MODIFIER_PER_UNIT),
        )
        # Rich SongAnalyzer energy is additive and bounded: phrase buckets and
        # all existing fixture safety controls remain authoritative.
        base_energy = clamp_unit(base_energy + song_analyzer_energy_modifier)
        base_energy = apply_live_energy_override(
            override_energy,
            base_energy,
            low_target=0.34,
            mid_target=0.58,
            high_target=0.86,
            mix=0.72,
        )
        pulse_name = auto_show_refined_pulse_name(
            behavior_section,
            scene["pulse_name"],
            style_name,
            osc_effective,
            effective_mood_factor,
            base_energy,
            override_energy,
        )
        movement_seed = clamp_unit(
            profile["motion"]
            + style["motion_bias"]
            + float(track_theme.get("motion_bias", 0.0))
            + ((waveform_factor - 0.5) * 0.025 if waveform_factor is not None else 0.0)
            + float(waveform_analysis.get("volatility") or 0.0) * 0.025
            + drum_profile["motion"] * 0.05
            + drum_profile["sparkle"] * 0.02
            + (anticipation * 0.045 if behavior_section in {"build", "chorus", "drop", "down", "outro"} else 0.0)
        )
        movement_seed = apply_live_energy_override(
            override_energy,
            movement_seed,
            low_target=0.28,
            mid_target=0.50,
            high_target=0.76,
            mix=0.62,
        )
        motion_name = auto_show_refined_motion_name(
            behavior_section,
            scene["motion_name"],
            style_name,
            osc_effective,
            base_energy,
            movement_seed,
            override_energy,
        )
        pulse_profile = AUTO_SHOW_PULSE_PROFILES.get(
            pulse_name, AUTO_SHOW_PULSE_PROFILES["medium"]
        )
        energy = base_energy
        movement = clamp_unit(movement_seed + pulse_profile["movement"])
        pulse_amount = clamp_unit(
            profile["pulse"]
            + style["pulse_bias"]
            + float(track_theme.get("pulse_bias", 0.0))
            + ((waveform_factor - 0.5) * 0.02 if waveform_factor is not None else 0.0)
            + max(0.0, float(waveform_analysis.get("transient") or 0.0) - 0.06) * 0.05
            + drum_profile["impact"] * 0.06
            + drum_profile["snare"] * 0.04
            + (anticipation * 0.025 if behavior_section in {"build", "chorus", "drop"} else 0.0)
        )
        pulse_amount = apply_live_energy_override(
            override_energy,
            pulse_amount,
            low_target=0.18,
            mid_target=0.42,
            high_target=0.74,
            mix=0.66,
        )
        rhythm_mode = str(pulse_profile.get("mode", "full_on"))
        dynamic_level = rhythm_mode != "none"
        beat_pulse = rhythm_mode in {"beat_flash", "drop_blinder", "strong_pulse"}
        external_strobe = bool(osc.get("strobe_active"))
        imminent_strobe = (
            osc.get("strobe_count_in") is not None
            and int(osc.get("strobe_count_in") or 0) <= 2
        )
        strobe_window = bool(
            external_strobe
            or (
                profile["strobe"]
                and style["strobe_bias"] > -0.5
                and (
                    energy > 0.90
                    or pulse_name in {"beat_flash", "drop_blinder"}
                    or imminent_strobe
                    or drum_profile["impact"] >= 0.46
                )
            )
        )
        if override_energy == "low" and not external_strobe:
            strobe_window = False
        elif override_energy == "high" and not external_strobe:
            strobe_window = bool(
                strobe_window
                or (
                    behavior_section in {"build", "chorus", "drop"}
                    and (
                        energy >= 0.76
                        or pulse_name in {"beat_flash", "drop_blinder", "chase", "snake", "double_hit", "gallop"}
                        or drum_profile["impact"] >= 0.36
                    )
                )
            )
        color_source = auto_show_color_source(style_name, behavior_section, osc_effective)
        manual_color = auto_show_manual_color(style_name, behavior_section, osc_effective)
        if override_phrase != "none":
            section_label = f"{section.title()} Override"
        elif behavior_section != section:
            section_label = f"{section.title()} -> {behavior_section.title()}"
        elif live_behavior_section != section:
            section_label = f"{section.title()} -> {live_behavior_section.title()}"
        else:
            section_label = section.title()
        cue_label = (
            f"{style['label']} • {scene['theme_label']} • {section_label} • "
            f"{scene['look_label']} / {scene['color_profile_label']} / {titleize_variant(motion_name)}"
            f"{' Mirror' if scene.get('mirror_within_group') else ''} / {scene['texture_label']} / {titleize_variant(pulse_name)}"
        )
        override_parts = []
        if override_phrase != "none":
            override_parts.append(f"Phrase {auto_show_phrase_override_label(override_phrase)}")
        if override_color != "none":
            override_parts.append(live_override_color_label(override_color))
        if override_energy != "none":
            override_parts.append(f"{live_override_energy_label(override_energy)} Energy")
        if override_manual_strobe:
            override_parts.append("Manual Strobe")
        if override_audience_sweep:
            override_parts.append("Audience Sweep")
        if override_all_on:
            override_parts.append("All On")
        if override_par_chase:
            override_parts.append("PAR Chase")
        if override_par_snake:
            override_parts.append("PAR Snake")
        if one_shot:
            override_parts.append(f"Cue {one_shot['label']}")
        if override_parts:
            cue_label += " • Override: " + " / ".join(override_parts)
        return {
            "enabled": bool(config["enabled"]),
            "available": override_active or not bool(osc.get("stale")),
            "style": style_name,
            "style_label": style["label"],
            "audience_pan_focus_enabled": audience_pan_focus_enabled,
            "audience_pan_min": audience_pan_min,
            "audience_pan_max": audience_pan_max,
            "audience_turn_pan_min": audience_turn_pan_min,
            "audience_turn_pan_max": audience_turn_pan_max,
            "audience_tilt_split": audience_tilt_split,
            "phrase_bucket": section,
            "structure_behavior": structure_behavior,
            "override_phrase": override_phrase,
            "override_phrase_label": auto_show_phrase_override_label(override_phrase),
            "behavior_bucket": behavior_section,
            "live_behavior_bucket": live_behavior_section,
            "outro_activity": outro_activity if section == "outro" else None,
            "beat_step": beat_step,
            "cue_label": cue_label,
            "color_source": color_source,
            "energy": energy,
            "song_analyzer_energy": song_analyzer_energy,
            "song_analyzer_energy_modifier": song_analyzer_energy_modifier,
            "waveform_energy": waveform_factor,
            "waveform_bands": {
                "low": waveform_bands["low"],
                "mid": waveform_bands["mid"],
                "high": waveform_bands["high"],
            },
            "waveform_lookahead": {
                "2": {
                    "low": waveform_lookahead_2["low"],
                    "mid": waveform_lookahead_2["mid"],
                    "high": waveform_lookahead_2["high"],
                },
                "4": {
                    "low": waveform_lookahead_4["low"],
                    "mid": waveform_lookahead_4["mid"],
                    "high": waveform_lookahead_4["high"],
                },
            },
            "waveform_analysis": waveform_analysis,
            "drum_signals": {
                "kick": drum_profile["kick"],
                "snare": drum_profile["snare"],
                "hihat": drum_profile["hihat"],
                "impact": drum_profile["impact"],
                "sparkle": drum_profile["sparkle"],
                "motion": drum_profile["motion"],
            },
            "anticipation": anticipation,
            "movement": movement,
            "beat_pulse": beat_pulse,
            "dynamic_level": dynamic_level,
            "rhythm_mode": rhythm_mode,
            "dimmer_fx_name": pulse_name,
            "dimmer_fx_label": titleize_variant(pulse_name),
            "strobe_window": strobe_window,
            "external_strobe": external_strobe,
            "beat_depth": clamp_dmx(
                round(70 + pulse_amount * 140 + pulse_profile["depth"])
            ),
            "beat_decay_ms": max(
                60,
                min(520, int(round(220 - energy * 110 + pulse_profile["decay"]))),
            ),
            "manual_color": {
                "red": int(manual_color[0]),
                "green": int(manual_color[1]),
                "blue": int(manual_color[2]),
                "white": int(manual_color[3]),
            },
            "theme_name": scene["theme_name"],
            "theme_label": scene["theme_label"],
            "look_name": scene["look_name"],
            "color_profile_name": scene["color_profile_name"],
            "color_profile_label": scene["color_profile_label"],
            "motion_name": motion_name,
            "texture_name": scene["texture_name"],
            "wash_cue_name": scene["wash_cue_name"],
            "wash_cue_label": auto_show_wall_wash_cue(scene["wash_cue_name"])["label"],
            "mirror_within_group": bool(scene.get("mirror_within_group")),
            "pulse_name": pulse_name,
            "accent_name": scene["accent_name"],
            "track_plan_active": bool(planned_scene),
            "track_plan_segment_index": scene.get("plan_segment_index"),
            "track_plan_section": scene.get("section") if planned_scene else None,
            "track_plan_phrase": scene.get("plan_phrase") if planned_scene else None,
            "track_plan_start_seconds": scene.get("plan_start_seconds") if planned_scene else None,
            "track_plan_end_seconds": scene.get("plan_end_seconds") if planned_scene else None,
            "override_active": override_active,
            "override_color": override_color,
            "override_color_label": live_override_color_label(override_color),
            "override_energy": override_energy,
            "override_energy_label": live_override_energy_label(override_energy),
            "override_manual_strobe": override_manual_strobe,
            "override_audience_sweep": override_audience_sweep,
            "override_all_on": override_all_on,
            "override_par_chase": override_par_chase,
            "override_par_snake": override_par_snake,
            "one_shot_active": bool(one_shot),
            "one_shot_cue": one_shot["id"] if one_shot else "none",
            "one_shot_label": one_shot["label"] if one_shot else "None",
            "one_shot_progress": one_shot["progress"] if one_shot else 0.0,
        }

    def _resolved_behavior_section(
        self,
        section,
        beat_value,
        osc,
        waveform_factor=None,
        waveform_bands=None,
        waveform_lookahead_2=None,
        waveform_lookahead_4=None,
        drum_profile=None,
        waveform_analysis=None,
    ):
        if section != "outro":
            self.outro_behavior_state = None
            return section, None

        activity_raw = auto_show_outro_activity_score(
            osc,
            waveform_factor=waveform_factor,
            waveform_bands=waveform_bands,
            waveform_lookahead_2=waveform_lookahead_2,
            waveform_lookahead_4=waveform_lookahead_4,
            drum_profile=drum_profile,
            waveform_analysis=waveform_analysis,
        )

        levels = ["outro", "verse", "build", "chorus"]
        previous = self.outro_behavior_state or {}
        previous_smoothed = previous.get("activity")
        try:
            previous_smoothed = (
                None if previous_smoothed is None else clamp_unit(float(previous_smoothed))
            )
        except (TypeError, ValueError):
            previous_smoothed = None
        smoothed = activity_raw if previous_smoothed is None else clamp_unit(previous_smoothed * 0.76 + activity_raw * 0.24)
        current = previous.get("section")

        if current not in levels:
            current = auto_show_outro_bucket_for_activity(smoothed)
            self.outro_behavior_state = {
                "section": current,
                "activity": smoothed,
                "lock_until_beat": float(beat_value) + 8.0,
            }
            return current, smoothed

        lock_until_beat = float(previous.get("lock_until_beat") or 0.0)
        if float(beat_value) < lock_until_beat:
            self.outro_behavior_state = {
                "section": current,
                "activity": smoothed,
                "lock_until_beat": lock_until_beat,
            }
            return current, smoothed

        if current == "outro":
            if smoothed >= 0.82:
                next_section = "chorus"
            elif smoothed >= 0.66:
                next_section = "build"
            elif smoothed >= 0.54:
                next_section = "verse"
            else:
                next_section = "outro"
        elif current == "verse":
            if smoothed >= 0.86:
                next_section = "chorus"
            elif smoothed >= 0.70:
                next_section = "build"
            elif smoothed < 0.42:
                next_section = "outro"
            else:
                next_section = "verse"
        elif current == "build":
            if smoothed >= 0.88:
                next_section = "chorus"
            elif smoothed < 0.38:
                next_section = "outro"
            elif smoothed < 0.52:
                next_section = "verse"
            else:
                next_section = "build"
        else:
            if smoothed < 0.40:
                next_section = "outro"
            elif smoothed < 0.54:
                next_section = "verse"
            elif smoothed < 0.68:
                next_section = "build"
            else:
                next_section = "chorus"

        if next_section != current:
            lock_until_beat = float(beat_value) + 8.0

        self.outro_behavior_state = {
            "section": next_section,
            "activity": smoothed,
            "lock_until_beat": lock_until_beat,
        }
        return next_section, smoothed

    @staticmethod
    def _rhythm_change_gate_seconds(bpm):
        try:
            beat_seconds = 60.0 / max(1.0, float(bpm or 120.0))
        except (TypeError, ValueError):
            beat_seconds = 0.5
        return max(0.05, min(0.14, beat_seconds * 0.22))

    @staticmethod
    def _rhythm_hold_beats(role, mode, section):
        role = str(role or "static")
        mode = str(mode or "full_on")
        section = str(section or "unknown")
        calm_sections = {"intro", "verse", "down", "break", "outro"}
        if mode in {"soft_pulse", "alternate_whole", "pair_hold", "breathing"}:
            if role == "moving":
                return 8.0 if section in calm_sections else 4.0
            if role == "par":
                return 4.0 if section in calm_sections else 2.0
            return 4.0 if section in calm_sections else 2.0
        if mode in {"slow_fade_in", "slow_fade_out", "offbeat_flash", "medium", "full_on"}:
            return 2.0 if section in calm_sections else 1.0
        if role == "moving" and mode in {"chase_whole", "snake_whole", "pivot"}:
            return 1.0
        return 1.0

    def _stabilize_slot_rhythm_mode(self, slot_id, role, section, proposed_mode, osc):
        slot_id = str(slot_id or "").strip()
        role = str(role or "static")
        section = str(section or "unknown")
        proposed_mode = str(proposed_mode or "full_on")
        if not slot_id:
            return proposed_mode

        beat_value = osc.get("beat_value")
        try:
            beat_value = None if beat_value is None else float(beat_value)
        except (TypeError, ValueError):
            beat_value = None

        bpm = osc.get("bpm")
        try:
            bpm = None if bpm is None else float(bpm)
        except (TypeError, ValueError):
            bpm = None

        beat_age = osc.get("beat_phase_age_seconds")
        try:
            beat_age = None if beat_age is None else max(0.0, float(beat_age))
        except (TypeError, ValueError):
            beat_age = None

        state = dict(self.slot_rhythm_states.get(slot_id) or {})
        current_mode = str(state.get("mode") or proposed_mode)
        lock_until_beat = state.get("lock_until_beat")
        try:
            lock_until_beat = (
                None if lock_until_beat is None else float(lock_until_beat)
            )
        except (TypeError, ValueError):
            lock_until_beat = None

        pending = False
        resolved_mode = current_mode if state else proposed_mode

        if beat_value is None:
            resolved_mode = current_mode if state else proposed_mode
        elif proposed_mode != current_mode:
            gate_seconds = self._rhythm_change_gate_seconds(bpm)
            phase = beat_value % 1.0
            at_beat_edge = (
                beat_age <= gate_seconds
                if beat_age is not None
                else phase <= 0.18
            )
            if lock_until_beat is not None and beat_value < lock_until_beat:
                pending = True
                resolved_mode = current_mode
            elif not at_beat_edge:
                pending = True
                resolved_mode = current_mode
            else:
                resolved_mode = proposed_mode
        else:
            resolved_mode = current_mode

        if beat_value is not None:
            if not state or resolved_mode != current_mode:
                hold_beats = self._rhythm_hold_beats(role, resolved_mode, section)
                next_beat = math.floor(beat_value) + 1.0
                lock_until_beat = next_beat + max(0.0, hold_beats - 1.0)
            self.slot_rhythm_states[slot_id] = {
                "mode": resolved_mode,
                "lock_until_beat": lock_until_beat,
            }
        else:
            self.slot_rhythm_states[slot_id] = {"mode": resolved_mode}

        signature = (
            proposed_mode,
            resolved_mode,
            bool(pending),
            section,
        )
        if self.last_slot_rhythm_signatures.get(slot_id) != signature:
            self.last_slot_rhythm_signatures[slot_id] = signature
            self.debug_log.log(
                "SLOT_RHYTHM",
                slot=slot_id,
                role=role,
                section=section,
                proposed=proposed_mode,
                resolved=resolved_mode,
                pending=pending,
                beat=beat_value,
                hold_until=lock_until_beat,
            )
        return resolved_mode

    def _effective_slot_config(self, slot_id, config, osc, auto_show, full_config=None):
        effective = {
            **config,
            "color": dict(config["color"]),
            "extra_values": dict(config.get("extra_values") or {}),
        }
        full_config = full_config or self._clean_full_config(dict(self.config))
        override_active = self._live_override_active(auto_show)
        if ((not auto_show["enabled"] and not override_active) or not config["enabled"] or (not auto_show["available"] and not override_active)):
            return effective
        if not config["sync_enabled"]:
            return effective

        capabilities = self._capabilities_for_slot(config)
        slot_context = self._slot_context(full_config, slot_id, config)
        role = slot_context["role"]
        energy = auto_show["energy"]
        movement = auto_show["movement"]
        section = auto_show.get("behavior_bucket", auto_show["phrase_bucket"])
        style_name = auto_show.get("style", "adaptive")
        theme_name = auto_show.get("theme_name", TRACK_SHOW_THEME_SEQUENCE[0])
        track_theme = auto_show_track_theme(theme_name)
        look_name = auto_show.get("look_name", "bank_echo")
        color_profile_name = auto_show.get("color_profile_name", "yellow_blue")
        motion_name = auto_show.get("motion_name", "center")
        texture_name = auto_show.get("texture_name", "steady")
        accent_name = auto_show.get("accent_name", "center")
        pulse_name = auto_show.get("pulse_name", "medium")
        rhythm_mode = auto_show.get("rhythm_mode", "full_on")
        override_energy = live_override_energy_name(auto_show.get("override_energy"))
        role_profiles = {
            "moving": {"base": 96, "span": 128, "energy_bias": 0.08, "pulse": 26, "decay": -40},
            "par": {"base": 84, "span": 142, "energy_bias": -0.04, "pulse": -6, "decay": 32},
            "wash": {"base": 76, "span": 136, "energy_bias": -0.12, "pulse": -22, "decay": 78},
            "static": {"base": 88, "span": 138, "energy_bias": -0.02, "pulse": -4, "decay": 18},
        }
        role_profile = role_profiles.get(role, role_profiles["static"])

        effective["sync_enabled"] = True
        effective["color_source"] = auto_show["color_source"]
        effective["color"] = dict(auto_show["manual_color"])
        effective["beat_pulse_enabled"] = auto_show["dynamic_level"]
        effective["osc_strobe_enabled"] = auto_show["strobe_window"] and capabilities["strobe"]
        effective["strobe"] = 0
        effective["speed"] = 0
        effective["program"] = 0
        effective["_slot_context"] = slot_context
        effective["_auto_show_movement"] = movement
        effective["_auto_show_motion_name"] = motion_name
        motion_profile = auto_show_motion_profile(motion_name)
        effective["_auto_show_member_mirror"] = bool(
            motion_profile.get("member_mirror")
            or (auto_show.get("mirror_within_group") and motion_name in AUTO_SHOW_MEMBER_MIRROR_MOTIONS)
        )
        effective["_auto_show_theme_name"] = theme_name
        effective["_auto_show_section"] = section
        effective["_auto_show_style_name"] = style_name
        effective["_auto_show_look_name"] = look_name
        effective["_auto_show_color_profile_name"] = color_profile_name
        effective["_auto_show_texture_name"] = texture_name
        effective["_auto_show_accent_name"] = accent_name
        effective["_auto_show_pulse_name"] = pulse_name
        effective["_auto_show_energy"] = energy
        effective["_auto_show_rhythm_mode"] = rhythm_mode
        effective["_auto_show_audience_pan_focus_enabled"] = bool(
            auto_show.get("audience_pan_focus_enabled", True)
        )
        try:
            effective["_auto_show_audience_pan_min"] = clamp_dmx(
                int(auto_show.get("audience_pan_min", 135))
            )
        except (TypeError, ValueError):
            effective["_auto_show_audience_pan_min"] = 135
        try:
            effective["_auto_show_audience_pan_max"] = clamp_dmx(
                int(auto_show.get("audience_pan_max", 205))
            )
        except (TypeError, ValueError):
            effective["_auto_show_audience_pan_max"] = 205
        default_turn_min, default_turn_max = _default_turn_audience_pan_limits(
            effective["_auto_show_audience_pan_min"],
            effective["_auto_show_audience_pan_max"],
        )
        try:
            effective["_auto_show_audience_turn_pan_min"] = clamp_dmx(
                int(auto_show.get("audience_turn_pan_min", default_turn_min))
            )
        except (TypeError, ValueError):
            effective["_auto_show_audience_turn_pan_min"] = default_turn_min
        try:
            effective["_auto_show_audience_turn_pan_max"] = clamp_dmx(
                int(auto_show.get("audience_turn_pan_max", default_turn_max))
            )
        except (TypeError, ValueError):
            effective["_auto_show_audience_turn_pan_max"] = default_turn_max
        if effective["_auto_show_audience_turn_pan_max"] < effective["_auto_show_audience_turn_pan_min"]:
            (
                effective["_auto_show_audience_turn_pan_min"],
                effective["_auto_show_audience_turn_pan_max"],
            ) = (
                effective["_auto_show_audience_turn_pan_max"],
                effective["_auto_show_audience_turn_pan_min"],
            )
        try:
            effective["_auto_show_audience_tilt_split"] = clamp_dmx(
                int(auto_show.get("audience_tilt_split", 127))
            )
        except (TypeError, ValueError):
            effective["_auto_show_audience_tilt_split"] = 127
        if role == "par":
            effective["_auto_show_texture_name"] = "steady"
            effective["_auto_show_rhythm_mode"] = auto_show_par_rhythm_mode(
                section,
                rhythm_mode,
                style_name,
                osc,
                slot_context,
                override_energy,
            )
        elif role == "moving":
            effective["_auto_show_texture_name"] = "steady"
            effective["_auto_show_rhythm_mode"] = auto_show_moving_rhythm_mode(
                section,
                rhythm_mode,
                style_name,
                osc,
                slot_context,
                energy,
                movement,
                override_energy,
            )
        effective["_auto_show_rhythm_mode"] = self._stabilize_slot_rhythm_mode(
            slot_id,
            role,
            section,
            effective["_auto_show_rhythm_mode"],
            osc,
        )

        base_rgbw = self._resolved_sync_rgbw(effective, osc)
        effective["_auto_show_rgbw"] = self._auto_show_rgbw_for_slot(
            base_rgbw, slot_context, auto_show
        )
        if role == "wash":
            zone_rgb = self._wall_wash_zone_rgb_for_slot(slot_context, auto_show, osc)
            effective["_auto_show_zone_rgb"] = zone_rgb
            effective["_auto_show_rgbw"] = self._wall_wash_average_rgbw(zone_rgb)

        slot_energy = energy + role_profile["energy_bias"]
        slot_energy += float(track_theme.get("energy_bias", 0.0)) * (0.45 if role == "moving" else 0.28)
        if role == "moving":
            slot_energy += slot_context.get("group_edge_bias", slot_context["edge_bias"]) * 0.04
        elif role == "par":
            slot_energy = 0.0
        elif role == "wash":
            slot_energy -= slot_context.get("group_edge_bias", slot_context["edge_bias"]) * 0.05
            slot_energy += slot_context.get("group_alternate", slot_context["alternate"]) * 0.04
        slot_energy = clamp_unit(slot_energy)

        if role == "par":
            par_section_dimmer = {
                "intro": 180,
                "verse": 210,
                "build": 228,
                "chorus": 255,
                "drop": 255,
                "down": 170,
                "break": 132,
                "outro": 118,
                "unknown": 210,
            }
            effective["dimmer"] = int(par_section_dimmer.get(section, 210))
        else:
            effective["dimmer"] = clamp_dmx(
                round(role_profile["base"] + role_profile["span"] * slot_energy)
            )
        effective["dimmer"] = clamp_dmx(
            effective["dimmer"]
            + self._accent_dimmer_offset(role, slot_context, accent_name, movement)
        )
        if role == "par":
            effective["dimmer"] = int(par_section_dimmer.get(section, 210))
        group_seed_unit = float(slot_context.get("group_seed_unit", slot_context.get("seed_unit", 0.0)))
        member_seed_unit = float(slot_context.get("member_seed_unit", slot_context.get("seed_unit", 0.0)))
        dimmer_variation = group_seed_unit * (10 if role == "moving" else 16 if role == "par" else 12)
        dimmer_variation += member_seed_unit * (4 if role == "moving" else 6 if role == "par" else 5)
        if role == "moving":
            dimmer_variation += slot_context.get("group_alternate", slot_context["alternate"]) * 8
            dimmer_variation += slot_context.get("group_edge_bias", slot_context["edge_bias"]) * 6
            dimmer_variation += slot_context.get("member_centered", 0.0) * 3
        elif role == "par":
            dimmer_variation = 0.0
        elif role == "wash":
            dimmer_variation += slot_context.get("group_alternate", slot_context["alternate"]) * 7
            dimmer_variation -= slot_context.get("group_edge_bias", slot_context["edge_bias"]) * 8
            dimmer_variation += slot_context.get("member_centered", 0.0) * 2
        if rhythm_mode in {"chase", "chase_whole"}:
            chase_spread = slot_context.get("group_centered", slot_context["centered"]) * (
                18 if role == "moving" else 24
            )
            dimmer_variation += chase_spread
        elif rhythm_mode == "stagger":
            dimmer_variation += slot_context.get("group_alternate", slot_context["alternate"]) * (
                16 if role != "wash" else 10
            )
        elif rhythm_mode == "split":
            dimmer_variation += slot_context.get("member_alternate", slot_context["alternate"]) * (
                18 if role == "par" else 8
            )
        elif rhythm_mode == "ladder":
            dimmer_variation += slot_context.get("member_centered", 0.0) * (
                -14 if role == "par" else -6
            )
        elif rhythm_mode == "ripple":
            dimmer_variation += group_seed_unit * (12 if role == "par" else 5)
        effective["dimmer"] = clamp_dmx(round(effective["dimmer"] + dimmer_variation))
        if role == "moving" and section in ("build", "chorus", "drop"):
            effective["dimmer"] = clamp_dmx(
                round(
                    effective["dimmer"]
                    + 6
                    + movement * 12
                    + slot_context.get("group_alternate", slot_context["alternate"]) * 10
                    - slot_context.get("group_edge_bias", slot_context["edge_bias"]) * 8
                )
            )
        elif role == "par" and section == "drop":
            effective["dimmer"] = clamp_dmx(max(effective["dimmer"], 220))
        elif role in ("par", "wash") and section in ("break", "outro"):
            effective["dimmer"] = clamp_dmx(round(effective["dimmer"] * 0.82))

        pulse_depth = auto_show["beat_depth"] + role_profile["pulse"]
        if role == "moving":
            pulse_depth += round(slot_context.get("group_edge_bias", slot_context["edge_bias"]) * 16)
        elif role == "wash":
            pulse_depth -= round(slot_context.get("group_center_bias", slot_context["center_bias"]) * 12)
        rhythm_mode = effective["_auto_show_rhythm_mode"]
        effective["beat_pulse_enabled"] = rhythm_mode != "none"
        if rhythm_mode == "none":
            pulse_depth = 0
        elif rhythm_mode == "breathe":
            pulse_depth = round(pulse_depth * 0.16)
        elif rhythm_mode == "lift":
            pulse_depth = clamp_dmx(round(30 + pulse_depth * 0.20))
        elif rhythm_mode == "hit":
            pulse_depth = clamp_dmx(
                round(124 + energy * 56 + movement * 24)
            )
        elif rhythm_mode == "cut":
            pulse_depth = clamp_dmx(
                round(176 + energy * 42 + movement * 18)
            )
        elif rhythm_mode in {"snake", "snake_whole"}:
            pulse_depth += 20 if role == "moving" else 10
        elif rhythm_mode in {"chase", "chase_whole"}:
            pulse_depth += 30 if role == "par" else 20 if role != "moving" else 10
        elif rhythm_mode == "stagger":
            pulse_depth += 24 if role == "par" else 14
        elif rhythm_mode == "split":
            pulse_depth += 26 if role == "par" else 12
        elif rhythm_mode == "ladder":
            pulse_depth += 22 if role == "par" else 10
        elif rhythm_mode == "ripple":
            pulse_depth += 18 if role == "par" else 8
        elif rhythm_mode == "bloom":
            pulse_depth = round(pulse_depth * 0.22)
        effective["beat_depth"] = clamp_dmx(pulse_depth)
        effective["beat_decay_ms"] = max(
            60,
            min(
                650,
                auto_show["beat_decay_ms"]
                + role_profile["decay"]
                + (-90 if role == "moving" and rhythm_mode == "cut" else 0)
                + (-48 if role == "moving" and rhythm_mode == "hit" else 0)
                + (-36 if role == "par" and rhythm_mode == "chase" else 0)
                + (-12 if role == "par" and rhythm_mode == "stagger" else 0),
            ),
        )

        if role == "moving" and capabilities["pan_tilt_speed"]:
            section_speed_base = {
                "intro": 82,
                "verse": 56,
                "build": 40,
                "chorus": 28,
                "drop": 22,
                "down": 64,
                "break": 72,
                "outro": 96,
                "unknown": 52,
            }
            speed_static = motion_profile.get("pan_tilt_speed_static")
            speed_min = motion_profile.get("speed_min")
            speed_max = motion_profile.get("speed_max")
            if speed_static is not None:
                speed_base = int(speed_static)
            elif speed_min is not None and speed_max is not None:
                speed_min = int(speed_min)
                speed_max = int(speed_max)
                if speed_max < speed_min:
                    speed_min, speed_max = speed_max, speed_min
                speed_span = speed_max - speed_min
                speed_base = speed_max - (movement * speed_span)
            else:
                speed_base = section_speed_base.get(section, 72)
                speed_adjust = movement * -16 + abs(
                    slot_context.get("group_centered", slot_context["centered"])
                ) * 4
                speed_base = speed_base + speed_adjust
            effective["pan_tilt_speed"] = clamp_dmx(round(speed_base))
            speed_cap = _full_tilt_motion_speed_cap(motion_profile, section)
            if speed_cap is not None:
                effective["pan_tilt_speed"] = clamp_dmx(
                    min(int(effective["pan_tilt_speed"]), int(speed_cap))
                )
            if section in ("break", "intro", "outro", "down"):
                if section == "outro":
                    effective["tilt"] = 184
                elif section == "down":
                    effective["tilt"] = 176
                else:
                    effective["tilt"] = 170
            elif section == "drop":
                effective["tilt"] = 110
            else:
                effective["tilt"] = 136

        override_color = live_override_color_name(auto_show.get("override_color"))
        if override_color != "none":
            override_rgbw = self._live_override_rgbw_for_slot(override_color, slot_context, osc)
            if override_rgbw is not None:
                effective["_auto_show_rgbw"] = override_rgbw
                effective["_force_rgbw_override"] = True
                effective["color"] = {
                    "red": int(override_rgbw[0]),
                    "green": int(override_rgbw[1]),
                    "blue": int(override_rgbw[2]),
                    "white": int(override_rgbw[3]),
                }
            if role == "wash":
                override_zone_rgb = self._live_override_zone_rgb_for_slot(
                    override_color, slot_context, osc
                )
                if override_zone_rgb is not None:
                    effective["_auto_show_zone_rgb"] = override_zone_rgb
                    effective["_auto_show_rgbw"] = self._wall_wash_average_rgbw(
                        override_zone_rgb
                    )

        if role == "par":
            if auto_show.get("override_par_snake"):
                effective["_auto_show_rhythm_mode"] = "par_snake"
                effective["_auto_show_texture_name"] = "steady"
                effective["beat_pulse_enabled"] = True
                effective["dimmer"] = max(effective["dimmer"], 220)
            elif auto_show.get("override_par_chase"):
                effective["_auto_show_rhythm_mode"] = "pair_swap"
                effective["_auto_show_texture_name"] = "steady"
                effective["beat_pulse_enabled"] = True
                effective["dimmer"] = max(effective["dimmer"], 220)

        if auto_show.get("override_audience_sweep") and role == "moving":
            override_motion_profile = auto_show_motion_profile("live_audience_tilt_sweep")
            effective["_auto_show_motion_name"] = "live_audience_tilt_sweep"
            effective["_auto_show_member_mirror"] = False
            effective["_live_override_audience_sweep"] = True
            if override_motion_profile.get("pan_tilt_speed_static") is not None:
                effective["pan_tilt_speed"] = clamp_dmx(
                    int(override_motion_profile["pan_tilt_speed_static"])
                )
            effective["dimmer"] = max(effective["dimmer"], 220)

        if auto_show.get("override_all_on"):
            effective["_auto_show_rhythm_mode"] = "full_on"
            effective["beat_pulse_enabled"] = False
            effective["dimmer"] = 255

        if auto_show.get("override_manual_strobe") and capabilities["strobe"]:
            effective["osc_strobe_enabled"] = False
            effective["strobe"] = max(int(effective.get("strobe", 0) or 0), 220)
            effective["dimmer"] = max(effective["dimmer"], 255 if role != "wash" else 220)

        if auto_show.get("one_shot_active"):
            effective = self._apply_one_shot_cue_to_effective_slot(
                effective,
                auto_show,
                osc,
                slot_context,
                capabilities,
            )

        return effective

    def _resolved_fixture_extra_values(self, config, mode, rgbw, brightness, strobe, osc=None):
        resolved = {}
        for control in mode_custom_controls(mode):
            resolved[control["id"]] = clamp_dmx(
                (config.get("extra_values") or {}).get(control["id"], control["default"])
            )

        if "_auto_show_rgbw" not in config and not config.get("_force_rgbw_override"):
            return resolved

        color_disk_channel = custom_control_channel(mode, "color_disk")
        if color_disk_channel is not None:
            indexed_value = indexed_color_value_for_rgbw(color_disk_channel, rgbw)
            if indexed_value is not None:
                resolved["color_disk"] = clamp_dmx(indexed_value)

        if "macro_function" in resolved:
            resolved["macro_function"] = 0

        if "spot_dimmer" in resolved:
            if brightness <= 10:
                resolved["spot_dimmer"] = 0
            else:
                resolved["spot_dimmer"] = clamp_dmx(round(brightness * 0.74))

        if "spot_strobe" in resolved:
            resolved["spot_strobe"] = clamp_dmx(strobe if strobe > 0 else 0)

        if fixture_preview_kind(find_fixture(FIXTURE_LIBRARY, config.get("fixture")), mode) == "bee_eye_pattern":
            self._apply_auto_show_bee_eye_fx(config, mode, resolved, brightness, osc)

        return resolved

    def _apply_auto_show_bee_eye_fx(self, config, mode, resolved, brightness, osc=None):
        if "_auto_show_rgbw" not in config and not config.get("_force_rgbw_override"):
            return

        section = str(config.get("_auto_show_section") or "unknown")
        style_name = str(config.get("_auto_show_style_name") or "adaptive")
        theme_name = str(config.get("_auto_show_theme_name") or "")
        look_name = str(config.get("_auto_show_look_name") or "")
        pulse_name = str(config.get("_auto_show_pulse_name") or "medium")
        motion_name = str(config.get("_auto_show_motion_name") or "center")
        rhythm_mode = str(config.get("_auto_show_rhythm_mode") or "full_on")
        slot_context = config.get("_slot_context") or {}
        energy = clamp_unit(float(config.get("_auto_show_energy", 0.0) or 0.0))
        movement = clamp_unit(float(config.get("_auto_show_movement", 0.0) or 0.0))
        beat_value = float((osc or {}).get("beat_value") or 0.0)
        group_name = str(slot_context.get("group") or slot_context.get("role") or "moving")
        group_index = int(slot_context.get("group_index", 0))
        member_index = int(slot_context.get("member_index", 0))
        quiet_sections = {"intro", "break", "down", "outro"}
        peak_sections = {"chorus", "drop"}

        if brightness <= 12:
            if "pattern_plate" in resolved:
                resolved["pattern_plate"] = clamp_dmx(0)
            if "z_rotation" in resolved:
                resolved["z_rotation"] = clamp_dmx(0)
            resolved["_bee_effect_mode"] = "wash"
            resolved["_bee_spread"] = 0.92
            resolved["_bee_background_level"] = 0.88
            resolved["_bee_softness"] = 0.78
            resolved["_bee_shape_transition"] = 0.22
            return

        if section in peak_sections:
            bee_mode = "fx"
        elif section == "build":
            bee_mode = "beam" if energy < 0.54 and movement < 0.58 else "fx"
        elif section == "verse":
            bee_mode = "beam" if energy < 0.62 and movement < 0.70 else "fx"
        elif section in quiet_sections:
            bee_mode = "wash" if energy < 0.48 and movement < 0.52 else "beam"
        else:
            bee_mode = "beam"

        if pulse_name in {"snake", "chase", "gallop", "double_hit", "beat_flash"} and section not in quiet_sections:
            bee_mode = "fx"
        elif motion_name in {"hold", "center"} and section in quiet_sections and energy < 0.42:
            bee_mode = "wash"

        if bee_mode == "wash":
            bee_spread = min(1.10, max(0.82, 0.88 + movement * 0.10))
            bee_background_level = clamp_unit(0.82 + (1.0 - energy) * 0.12)
            bee_softness = clamp_unit(0.70 + movement * 0.10)
            bee_shape_transition = clamp_unit(0.18 + movement * 0.08)
        elif bee_mode == "fx":
            bee_spread = min(1.34, max(0.98, 1.02 + movement * 0.22))
            bee_background_level = clamp_unit(0.50 + energy * 0.18)
            bee_softness = clamp_unit(0.38 + movement * 0.22)
            bee_shape_transition = clamp_unit(0.36 + energy * 0.24)
        else:
            bee_spread = min(1.18, max(0.90, 0.94 + movement * 0.12))
            bee_background_level = clamp_unit(0.34 + energy * 0.12)
            bee_softness = clamp_unit(0.24 + movement * 0.10)
            bee_shape_transition = clamp_unit(0.14 + energy * 0.08)

        resolved["_bee_effect_mode"] = bee_mode
        resolved["_bee_spread"] = bee_spread
        resolved["_bee_background_level"] = bee_background_level
        resolved["_bee_softness"] = bee_softness
        resolved["_bee_shape_transition"] = bee_shape_transition

        pattern_channel = custom_control_channel(mode, "pattern_plate")
        rotation_channel = custom_control_channel(mode, "z_rotation")

        if pattern_channel is not None:
            if section in quiet_sections:
                hold_beats = 32.0
            elif section in {"verse", "unknown"}:
                hold_beats = 16.0
            else:
                hold_beats = 8.0

            signature = "|".join(
                [
                    theme_name,
                    style_name,
                    section,
                    look_name,
                    pulse_name,
                    motion_name,
                    group_name,
                    str(group_index),
                    str(member_index),
                    str(int(math.floor(beat_value / max(1.0, hold_beats)))),
                ]
            )
            seed = stable_hash(signature)

            if bee_mode == "wash":
                if section == "intro":
                    options = ["open", "open", "flower", "pinwheel_flower"]
                else:
                    options = ["open", "flower", "pinwheel_flower", "open"]
            elif bee_mode == "fx":
                if section == "drop":
                    options = ["spoke_star", "triskelion", "dot_cluster", "swirl"]
                elif section == "chorus":
                    options = ["pinwheel_flower", "swirl", "flower", "triskelion"]
                elif section == "build":
                    options = ["flower", "dot_star", "swirl", "triskelion"]
                else:
                    options = ["flower", "swirl", "dot_star", "triskelion"]
            else:
                if section == "build":
                    options = ["open", "dot_star", "spoke_star", "flower"]
                elif section == "verse":
                    options = ["open", "open", "dot_star", "flower", "spoke_star"]
                else:
                    options = ["open", "dot_star", "spoke_star", "flower"]

            if pulse_name in {"snake", "chase", "gallop", "double_hit", "beat_flash"} and section not in quiet_sections:
                options = [token for token in options if token != "open"] or options
            if energy < 0.28 and section in quiet_sections:
                options = ["open", "flower"]
            elif energy < 0.40 and section == "verse":
                options = ["open", "flower", "pinwheel_flower"]
            elif section in peak_sections and energy >= 0.74:
                options = [token for token in options if token != "open"] or options

            pattern_token = options[seed % len(options)]
            pattern_value = indexed_wheel_value_for_token(
                pattern_channel,
                "indexed_patterns",
                pattern_token,
                fallback=resolved.get("pattern_plate", 0),
            )
            if pattern_value is not None:
                resolved["pattern_plate"] = clamp_dmx(pattern_value)
        else:
            pattern_token = "open"

        if "spot_dimmer" in resolved:
            if bee_mode == "wash":
                multiplier = 0.10 if pattern_token == "open" else 0.26
            elif bee_mode == "fx":
                multiplier = 0.56 if pattern_token == "open" else 0.82
            else:
                multiplier = 0.78 if pattern_token == "open" else 0.66
            resolved["spot_dimmer"] = clamp_dmx(round(brightness * multiplier))

        if rotation_channel is not None:
            rotation_signature = "|".join(
                [
                    theme_name,
                    section,
                    pulse_name,
                    group_name,
                    str(group_index),
                ]
            )
            direction = -1 if stable_hash(rotation_signature) % 2 else 1

            if bee_mode == "wash":
                if pattern_token == "open" and movement < 0.40:
                    static_angle = stable_hash(rotation_signature + "|wash-open") % 128
                    resolved["z_rotation"] = clamp_dmx(static_angle)
                elif pattern_token == "open":
                    resolved["z_rotation"] = bee_eye_rotation_dmx(0.06 + energy * 0.05 + movement * 0.03, direction)
                else:
                    resolved["z_rotation"] = bee_eye_rotation_dmx(0.08 + energy * 0.06 + movement * 0.04, direction)
                return

            if bee_mode == "beam":
                if pattern_token == "open" and movement < 0.52:
                    static_angle = stable_hash(rotation_signature + "|beam-open") % 128
                    resolved["z_rotation"] = clamp_dmx(static_angle)
                else:
                    resolved["z_rotation"] = bee_eye_rotation_dmx(0.10 + energy * 0.08 + movement * 0.06, direction)
                return

            if section == "intro":
                resolved["z_rotation"] = bee_eye_rotation_dmx(0.10 + energy * 0.08, direction)
            elif section in {"break", "down", "outro"}:
                resolved["z_rotation"] = bee_eye_rotation_dmx(0.12 + energy * 0.10 + movement * 0.08, direction)
            elif section == "verse":
                resolved["z_rotation"] = bee_eye_rotation_dmx(0.18 + energy * 0.14 + movement * 0.10, direction)
            elif section == "build":
                resolved["z_rotation"] = bee_eye_rotation_dmx(0.30 + energy * 0.22 + movement * 0.16, direction)
            elif section == "chorus":
                resolved["z_rotation"] = bee_eye_rotation_dmx(0.38 + energy * 0.24 + movement * 0.18, direction)
            elif section == "drop":
                resolved["z_rotation"] = bee_eye_rotation_dmx(0.48 + energy * 0.26 + movement * 0.18, direction)
            else:
                resolved["z_rotation"] = bee_eye_rotation_dmx(0.20 + energy * 0.14, direction)

    def _fixture_preview_payload(self, fixture, mode, extra_values):
        values = dict(extra_values or {})
        dimmer = clamp_dmx(values.get("spot_dimmer", 0))
        color_disk_channel = custom_control_channel(mode, "color_disk")
        rgbw = indexed_color_rgbw(color_disk_channel, values.get("color_disk", 0))
        if rgbw is None:
            rgbw = (255, 255, 255, 255)
        payload = {
            "fixture_kind": fixture_preview_kind(fixture, mode),
            "spot_red": int(rgbw[0]),
            "spot_green": int(rgbw[1]),
            "spot_blue": int(rgbw[2]),
            "spot_white": int(rgbw[3]),
            "spot_brightness": dimmer,
        }
        if payload["fixture_kind"] != "bee_eye_pattern":
            return payload

        color_state = indexed_wheel_preview_state(
            color_disk_channel,
            values.get("color_disk", 0),
            "indexed_colors",
        )
        pattern_state = indexed_wheel_preview_state(
            custom_control_channel(mode, "pattern_plate"),
            values.get("pattern_plate", 0),
            "indexed_patterns",
        )
        rotation_state = preview_spin_state(values.get("z_rotation", 0))
        if color_state:
            payload.update(
                {
                    "spot_color_index": int(color_state["index"]),
                    "spot_color_label": str(color_state["label"]),
                    "spot_color_token": str(color_state["token"]),
                    "spot_color_cycle": bool(color_state["cycle"]),
                    "spot_color_cycle_rate": float(color_state["cycle_rate"]),
                    "spot_color_count": int(color_state["count"]),
                }
            )
        if pattern_state:
            payload.update(
                {
                    "spot_pattern_index": int(pattern_state["index"]),
                    "spot_pattern_label": str(pattern_state["label"]),
                    "spot_pattern_id": str(pattern_state["token"]),
                    "spot_pattern_open": str(pattern_state["token"]) == "open",
                    "spot_pattern_cycle": bool(pattern_state["cycle"]),
                    "spot_pattern_cycle_rate": float(pattern_state["cycle_rate"]),
                    "spot_pattern_count": int(pattern_state["count"]),
                }
            )
        payload.update(
            {
                "spot_pattern_rotation_degrees": float(rotation_state["degrees"]),
                "spot_pattern_spin_dps": float(rotation_state["spin_dps"]),
                "bee_effect_mode": str(values.get("_bee_effect_mode") or "beam"),
                "bee_spread": float(values.get("_bee_spread", 1.0) or 1.0),
                "bee_background_level": float(values.get("_bee_background_level", 0.42) or 0.42),
                "bee_softness": float(values.get("_bee_softness", 0.30) or 0.30),
                "bee_shape_transition": float(values.get("_bee_shape_transition", 0.18) or 0.18),
            }
        )
        return payload

    def _rgbw_for_config(self, config, osc):
        if "_auto_show_rgbw" in config:
            return tuple(config["_auto_show_rgbw"])
        return self._resolved_sync_rgbw(config, osc)

    def _brightness_for_config(self, config, osc, now):
        dimmer = config["dimmer"]
        if not config["sync_enabled"]:
            return dimmer
        mode = str(config.get("_auto_show_rhythm_mode", "full_on"))
        slot_context = config.get("_slot_context") or {}
        role = str(slot_context.get("role", "static"))
        texture_multiplier = self._texture_multiplier(config, osc, now)
        par_pair_index = 0
        if role == "par":
            par_member_count = max(1, int(slot_context.get("member_count", 1)))
            par_member_index = int(slot_context.get("member_index", 0))
            par_pair_index = min(par_member_index, par_member_count - 1 - par_member_index)

        if mode in ("none", "full_on") or not config["beat_pulse_enabled"]:
            return clamp_dmx(round(dimmer * texture_multiplier))

        beat_value = float(osc.get("beat_value") or 0.0)
        cycle_16 = (beat_value % 16.0) / 16.0
        cycle_32 = (beat_value % 32.0) / 32.0
        age = osc.get("beat_phase_age_seconds")
        if age is None:
            last_beat_at = osc.get("last_beat_at")
            age = (now - last_beat_at) if last_beat_at else None

        def beat_envelope(local_decay):
            if age is None:
                return 0.0
            return max(0.0, 1.0 - (age / local_decay)) if local_decay > 0 else 0.0

        texture_blend = {
            "moving": 0.12,
            "par": 0.30,
            "wash": 0.22,
            "static": 0.18,
        }.get(role, 0.18)

        direct_multiplier = None
        if mode == "low_glow":
            direct_multiplier = 0.30
        elif mode == "medium":
            direct_multiplier = 0.68
        elif mode == "fade_in":
            direct_multiplier = 0.16 + 0.84 * cycle_32
        elif mode == "fade_out":
            direct_multiplier = 1.0 - 0.84 * cycle_32
        elif mode == "ramp_up":
            direct_multiplier = 0.35 + 0.65 * cycle_16
        elif mode == "ramp_down":
            direct_multiplier = 1.0 - 0.65 * cycle_16
        elif mode == "breathing":
            pair_phase = par_pair_index * 1.0 if role == "par" else 0.0
            direct_multiplier = 0.32 + 0.36 * (
                0.5 + 0.5 * wave_sine((beat_value + pair_phase) / 4.0)
            )
        elif mode == "soft_pulse":
            pair_phase = par_pair_index * 1.0 if role == "par" else 0.0
            pulse_divisor = 4.0 if role == "moving" else 2.0
            direct_multiplier = 0.55 + 0.25 * (
                0.5 + 0.5 * wave_sine((beat_value + pair_phase) / pulse_divisor)
            )
        elif mode == "strong_pulse":
            envelope = beat_envelope(max(0.08, config["beat_decay_ms"] / 1000.0))
            if role == "moving":
                direct_multiplier = 1.0 if envelope >= 0.22 else 0.0
            else:
                direct_multiplier = 0.12 + 0.88 * (envelope ** 0.42)
        elif mode == "beat_flash":
            envelope = beat_envelope(max(0.05, config["beat_decay_ms"] / 1000.0))
            if role == "moving":
                direct_multiplier = 1.0 if envelope >= 0.26 else 0.0
            else:
                direct_multiplier = envelope ** 0.24
        elif mode == "offbeat_flash":
            pair_phase = par_pair_index * 0.5 if role == "par" else 0.0
            off_phase = (beat_value + 0.5 + pair_phase) % 1.0
            if off_phase <= 0.18:
                if role == "moving":
                    direct_multiplier = 1.0
                else:
                    direct_multiplier = max(0.0, 1.0 - (off_phase / 0.18))
            else:
                direct_multiplier = 0.0
        elif mode == "drop_blinder":
            downbeat = int(math.floor(beat_value)) % 4 == 0
            if downbeat:
                envelope = beat_envelope(max(0.06, config["beat_decay_ms"] / 1000.0))
                if role == "moving":
                    direct_multiplier = 1.0 if envelope >= 0.20 else 0.0
                else:
                    direct_multiplier = 0.18 + 0.82 * (envelope ** 0.18)
            else:
                direct_multiplier = 0.12
        elif mode == "blackout_hit":
            downbeat = int(math.floor(beat_value)) % 4 == 0
            if downbeat and age is not None and age <= 0.10:
                direct_multiplier = 0.0
            else:
                direct_multiplier = 1.0
        elif mode == "tremolo":
            direct_multiplier = 0.35 + 0.65 * (0.5 + 0.5 * wave_sine(beat_value * 4.0))

        if direct_multiplier is not None:
            multiplier = max(0.0, min(1.08, direct_multiplier))
            multiplier *= (1.0 - texture_blend) + texture_multiplier * texture_blend
            multiplier = max(0.0, min(1.08, multiplier))
            return clamp_dmx(round(dimmer * multiplier))

        decay = config["beat_decay_ms"] / 1000.0
        movement_scale = float(config.get("_auto_show_movement", 0.0) or 0.0)
        envelope = self._rhythm_envelope(
            mode,
            osc.get("beat_value"),
            slot_context,
            movement_scale,
            osc,
            now,
            decay,
            float(config.get("_auto_show_energy", 0.0) or 0.0),
        )

        depth = clamp_unit(config["beat_depth"] / 255.0)
        if mode == "breathe":
            center = 0.94 + depth * 0.02
            swing = 0.02 + depth * 0.05
            multiplier = center + (envelope - 0.5) * 2.0 * swing
        elif mode == "lift":
            baseline = 0.80
            multiplier = baseline + 0.20 * envelope
        elif mode == "hit":
            baseline = max(0.08, 0.40 - depth * 0.34)
            multiplier = baseline + (1.0 - baseline) * envelope
        elif mode == "cut":
            baseline = max(0.0, 0.18 - depth * 0.24)
            multiplier = baseline + (1.0 - baseline) * envelope
        elif mode in {"pair_swap", "pair_hold", "pair_bounce", "par_snake"}:
            multiplier = 1.0 if envelope >= 0.5 else 0.0
        elif mode in {"snake", "snake_whole"}:
            multiplier = 1.0 if envelope >= 0.5 else 0.0
        elif mode == "stagger":
            baseline = max(0.40, 1.0 - depth * 0.68)
            multiplier = baseline + depth * 0.60 * envelope
        elif mode in {"chase", "chase_whole"}:
            multiplier = 1.0 if envelope >= 0.5 else 0.0
        elif mode == "split":
            baseline = max(0.42, 1.0 - depth * 0.62)
            multiplier = baseline + depth * 0.58 * envelope
        elif mode == "ladder":
            baseline = max(0.46, 1.0 - depth * 0.58)
            multiplier = baseline + depth * 0.52 * envelope
        elif mode == "ripple":
            baseline = max(0.52, 1.0 - depth * 0.44)
            multiplier = baseline + depth * 0.36 * envelope
        elif mode == "bloom":
            baseline = max(0.58, 1.0 - depth * 0.34)
            multiplier = baseline + depth * 0.22 * envelope
        elif mode == "gate":
            baseline = 0.78
            multiplier = baseline + 0.22 * (envelope ** 0.55)
        else:
            baseline = 0.80
            multiplier = baseline + 0.20 * envelope

        multiplier *= (1.0 - texture_blend) + texture_multiplier * texture_blend
        multiplier = max(0.0, min(1.08, multiplier))
        return clamp_dmx(round(dimmer * multiplier))

    def _motion_for_config(self, slot_id, config, osc):
        if not config["sync_enabled"]:
            return None
        fixture = find_fixture(FIXTURE_LIBRARY, config["fixture"])
        mode = find_mode(fixture, config["mode"])
        capabilities = mode_capabilities(mode)
        if not capabilities["pan"] or not capabilities["tilt"]:
            return None
        one_shot_cue_id = one_shot_cue_name(config.get("_one_shot_cue_id"))
        phrase = osc.get("phrase_current")
        if not phrase and (config.get("_live_override_audience_sweep") or one_shot_cue_id != "none"):
            phrase = "override"
        if not phrase:
            return None
        beat_value = osc.get("beat_value")
        if beat_value is None and (config.get("_live_override_audience_sweep") or one_shot_cue_id != "none"):
            beat_value = time.time() * 0.9
        slot_context = config.get("_slot_context")
        movement_scale = float(config.get("_auto_show_movement", 0.0) or 0.0)
        if one_shot_cue_id != "none":
            motion = self._one_shot_motion_for_config(
                one_shot_cue_id,
                float(config.get("_one_shot_cue_progress", 0.0) or 0.0),
                slot_context or {},
                config,
                beat_value,
            )
            if motion:
                return _apply_audience_pan_focus_to_motion(motion, slot_context, config=config)
        motion_name = config.get("_auto_show_motion_name")
        if motion_name:
            motion = styled_phrase_motion(
                phrase,
                beat_value,
                motion_name,
                slot_context,
                movement_scale,
                config,
            )
            motion = maybe_apply_member_mirror(
                motion,
                slot_context,
                bool(config.get("_auto_show_member_mirror")),
                config=config,
            )
            return _apply_audience_pan_focus_to_motion(motion, slot_context, config=config)
        phase_offset = 0.0
        if slot_context and slot_context.get("group_count", slot_context.get("role_count", 1)) > 1:
            phase_offset = (
                slot_context.get("group_centered", slot_context["centered"]) * (0.48 + movement_scale * 0.70)
                + slot_context.get("group_alternate", slot_context["alternate"]) * 0.14
            )
        motion = phrase_motion(phrase, (beat_value or 0.0) + phase_offset)
        if not motion or not slot_context or slot_context.get("group_count", slot_context.get("role_count", 1)) <= 1:
            return motion

        pan = motion["pan"]
        tilt = motion["tilt"]
        if slot_context.get("group_alternate", slot_context["alternate"]) < 0:
            pan = 254 - pan
        pan = clamp_dmx(
            round(
                pan
                + slot_context.get("group_centered", slot_context["centered"]) * (18 + movement_scale * 28)
                + slot_context.get("member_centered", 0.0) * 8
            )
        )
        tilt = clamp_dmx(
            round(
                tilt
                - slot_context.get("group_edge_bias", slot_context["edge_bias"]) * (8 + movement_scale * 12)
                + slot_context.get("member_centered", 0.0) * 4
            )
        )
        motion = {
            "pan": pan,
            "tilt": tilt,
            "pan_tilt_speed": motion["pan_tilt_speed"],
        }
        motion = maybe_apply_member_mirror(
            motion,
            slot_context,
            bool(config.get("_auto_show_member_mirror")),
            config=config,
        )
        return _apply_audience_pan_focus_to_motion(motion, slot_context, config=config)

    def _send_loop(self):
        while True:
            developer_playback_state = None
            with self.lock:
                if not self.running or not self.dmx:
                    return
                dmx = self.dmx
                fps = self.fps
                try:
                    render_now = time.time()
                    config = self._clean_full_config(dict(self.config))
                    osc = self.osc.snapshot_for_render()
                    self._observe_active_playback_generation(osc)
                    auto_show = self._auto_show_state(osc, config["auto_show"])
                    values = self._render_values(
                        render_now,
                        config=config,
                        osc=osc,
                        auto_show=auto_show,
                    )
                    self.current_values = values
                    self.current_slot_previews = self._build_slot_previews(
                        config,
                        osc,
                        render_now,
                        auto_show=auto_show,
                    )
                    developer_playback_state = self.osc.developer_playback_state()
                except Exception as exc:
                    self.error = str(exc)
                    values = dict(self.current_values)

            self._observe_virtualdj_beat_pulse_test(developer_playback_state)
            started = time.monotonic()
            try:
                with self.lock:
                    if not self.running or self.dmx is not dmx:
                        continue
                    values = self._apply_virtualdj_beat_pulse_overlay_locked(values)
                    self._send_dmx_frame(dmx, values)
                    self.error = None
                    self.last_sent = time.time()
            except Exception as exc:
                with self.lock:
                    self.error = str(exc)
                    self.dmx_dispatch_failures += 1
                time.sleep(0.25)
            elapsed = time.monotonic() - started
            time.sleep(max(0, (1 / fps) - elapsed))


OSC = OscListener()
TRANSPORT = TransportController(OSC)
SONG_ANALYZER_STRUCTURE = SongAnalyzerStructureHandoff()
STRUCTURE_BEHAVIOR = StructureBehaviorBridge(SONG_ANALYZER_STRUCTURE)
SONG_ANALYZER_BRIDGE_DIAGNOSTICS = SongAnalyzerBridgeDiagnostics()
DMX = DmxController(TRANSPORT, STRUCTURE_BEHAVIOR)


def serial_ports():
    try:
        from serial.tools import list_ports
    except ModuleNotFoundError:
        return []
    ports = []
    for port in list_ports.comports():
        details = []
        if port.manufacturer:
            details.append(port.manufacturer)
        if port.product:
            details.append(port.product)
        label = port.device
        if details:
            label = f"{label} ({', '.join(details)})"
        ports.append(
            {
                "device": port.device,
                "label": label,
                "manufacturer": port.manufacturer,
                "product": port.product,
                "serial_number": port.serial_number,
            }
        )
    return ports


def _hardware_port_labels():
    labels = {}
    with suppress(Exception):
        result = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
        hardware_port = None
        for raw_line in (result.stdout or "").splitlines():
            line = raw_line.strip()
            if line.startswith("Hardware Port:"):
                hardware_port = line.partition(":")[2].strip()
            elif line.startswith("Device:"):
                device = line.partition(":")[2].strip()
                if hardware_port and device:
                    labels[device] = hardware_port
    return labels


def _interface_kind(name, label):
    text = f"{name} {label}".lower()
    if (
        name.startswith(("lo", "utun", "awdl", "llw", "gif", "stf", "anpi"))
        or "loopback" in text
        or "tailscale" in text
    ):
        return None
    if any(token in text for token in ("iphone usb", "ipad usb", " usb", "usb ")):
        return "usb"
    if any(token in text for token in ("ethernet", "lan", "thunderbolt")):
        return "wired"
    if any(token in text for token in ("wi-fi", "wifi", "airport")):
        return "wifi"
    return "network"


def _interface_ipv4_candidates():
    labels = _hardware_port_labels()
    candidates = []
    seen_ips = set()
    for _, name in socket.if_nameindex():
        label = labels.get(name, name)
        kind = _interface_kind(name, label)
        if not kind:
            continue
        with suppress(Exception):
            result = subprocess.run(
                ["ifconfig", name],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            text = result.stdout or ""
            if "status: inactive" in text and "status: active" not in text:
                continue
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line.startswith("inet "):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                ip = parts[1].strip()
                if (
                    not ip
                    or ip == "127.0.0.1"
                    or "." not in ip
                    or ip.startswith("169.254.")
                    or ip in seen_ips
                ):
                    continue
                seen_ips.add(ip)
                candidates.append(
                    {
                        "name": name,
                        "label": label,
                        "kind": kind,
                        "ip": ip,
                    }
                )
    kind_rank = {"usb": 0, "wired": 1, "wifi": 2, "network": 3}
    candidates.sort(
        key=lambda item: (
            kind_rank.get(item["kind"], 9),
            item["label"],
            item["ip"],
        )
    )
    return candidates


def default_remote_access_config():
    return {
        "require_token": True,
        "token": secrets.token_urlsafe(24),
        "pairing_code": "".join(secrets.choice("0123456789") for _ in range(6)),
    }


def load_remote_access_config():
    if REMOTE_ACCESS_PATH.exists():
        with suppress(Exception):
            payload = json.loads(REMOTE_ACCESS_PATH.read_text(encoding="utf-8"))
            token = str((payload or {}).get("token") or "").strip()
            require_token = bool((payload or {}).get("require_token", True))
            pairing_code = str((payload or {}).get("pairing_code") or "").strip()
            if token:
                return {
                    "require_token": require_token,
                    "token": token,
                    "pairing_code": pairing_code if pairing_code.isdigit() and len(pairing_code) == 6 else default_remote_access_config()["pairing_code"],
                }
    config = default_remote_access_config()
    save_remote_access_config(config)
    return config


def save_remote_access_config(config):
    payload = {
        "require_token": bool(config.get("require_token", True)),
        "token": str(config.get("token") or "").strip(),
        "pairing_code": str(config.get("pairing_code") or "").strip(),
    }
    if not payload["token"]:
        payload["token"] = secrets.token_urlsafe(24)
    if not (payload["pairing_code"].isdigit() and len(payload["pairing_code"]) == 6):
        payload["pairing_code"] = "".join(secrets.choice("0123456789") for _ in range(6))
    REMOTE_ACCESS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def tailscale_ipv4():
    tailscale_path = shutil.which("tailscale")
    if not tailscale_path:
        for candidate in ("/opt/homebrew/bin/tailscale", "/usr/local/bin/tailscale"):
            if Path(candidate).exists():
                tailscale_path = candidate
                break
    if not tailscale_path:
        return None
    with suppress(Exception):
        completed = subprocess.run(
            [tailscale_path, "ip", "-4"],
            capture_output=True,
            check=True,
            text=True,
            timeout=1.5,
        )
        for line in completed.stdout.splitlines():
            ip = line.strip()
            if ip.startswith("100.") and "." in ip:
                return ip
    return None


def is_loopback_client(address):
    text = str(address or "").strip()
    return text in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost")


def remote_access_token():
    config = REMOTE_ACCESS_CONFIG or {}
    token = str(config.get("token") or "").strip()
    return token or None


def remote_access_requires_token():
    config = REMOTE_ACCESS_CONFIG or {}
    return bool(config.get("require_token", True))


def remote_access_pairing_code():
    config = REMOTE_ACCESS_CONFIG or {}
    code = str(config.get("pairing_code") or "").strip()
    return code if code.isdigit() and len(code) == 6 else None


def remote_access_state():
    now = time.time()
    cached = REMOTE_ADDRESS_CACHE.get("state")
    if cached and (now - float(REMOTE_ADDRESS_CACHE.get("updated_at") or 0.0)) < REMOTE_ADDRESS_CACHE_TTL:
        return cached

    local_url = f"http://127.0.0.1:{SERVER_PORT}/remote"
    bind_host = SERVER_HOST
    token = remote_access_token()
    token_suffix = f"?token={token}" if token and remote_access_requires_token() else ""
    interface_urls = []
    usb_url = None
    lan_url = None
    if bind_host in ("0.0.0.0", "::"):
        for interface in _interface_ipv4_candidates():
            url = f"http://{interface['ip']}:{SERVER_PORT}/remote{token_suffix}"
            interface_urls.append(
                {
                    "name": interface["name"],
                    "label": interface["label"],
                    "kind": interface["kind"],
                    "ip": interface["ip"],
                    "url": url,
                }
            )
            if interface["kind"] == "usb" and not usb_url:
                usb_url = url
            elif not lan_url:
                lan_url = url
    elif bind_host not in ("127.0.0.1", "localhost"):
        lan_url = f"http://{bind_host}:{SERVER_PORT}/remote{token_suffix}"
        interface_urls.append(
            {
                "name": "bind",
                "label": "Configured host",
                "kind": "network",
                "ip": bind_host,
                "url": lan_url,
            }
        )

    tailscale_ip = tailscale_ipv4()
    tailscale_url = (
        f"http://{tailscale_ip}:{SERVER_PORT}/remote{token_suffix}"
        if tailscale_ip
        else None
    )
    preferred_url = usb_url or tailscale_url or lan_url or (
        f"{local_url}{token_suffix}" if token_suffix else local_url
    )
    payload = {
        "enabled": bind_host not in ("127.0.0.1", "localhost"),
        "bind_host": bind_host,
        "port": SERVER_PORT,
        "path": "/remote",
        "local_url": f"{local_url}{token_suffix}" if token_suffix else local_url,
        "lan_url": lan_url,
        "usb_url": usb_url,
        "tailscale_url": tailscale_url,
        "preferred_url": preferred_url,
        "interface_urls": interface_urls,
        "auth_required": bool(token_suffix),
    }
    REMOTE_ADDRESS_CACHE["updated_at"] = now
    REMOTE_ADDRESS_CACHE["state"] = payload
    return payload


def bars_to_next(remaining_seconds, bpm, epsilon=1e-9):
    """Return the conservative whole-bar countdown for the native UI.

    This is presentation-only. It deliberately uses the current VirtualDJ
    position and BPM, never a second clock or a phrase-side estimate.
    """
    try:
        remaining = float(remaining_seconds)
        tempo = float(bpm)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(remaining) or not math.isfinite(tempo) or tempo <= 0 or remaining < -epsilon:
        return None
    if remaining <= epsilon:
        return 0
    exact_bars = remaining / (240.0 / tempo)
    return max(1, int(math.ceil(exact_bars - epsilon)))


def _live_ui_structure(track_path, position_milliseconds, bpm):
    if not track_path or position_milliseconds is None or bpm is None:
        return None
    try:
        position_seconds = float(position_milliseconds) / 1000.0
        if not math.isfinite(position_seconds) or position_seconds < 0:
            return None
    except (TypeError, ValueError):
        return None
    projection = SONG_ANALYZER_STRUCTURE.project({
        "_active_playback_source": "virtualdj",
        "track_path": track_path,
        "time_seconds": position_seconds,
    })
    if projection.get("track_match") != "exact" or projection.get("availability") != "available_current":
        return None
    if projection.get("projection_status") not in {"in_segment", "in_final_segment"}:
        return None
    current = projection.get("current") or {}
    next_segment = projection.get("next") or {}
    next_label = next_segment.get("label")
    remaining = None
    countdown = None
    if next_label is not None:
        remaining = float(next_segment.get("start_seconds", position_seconds)) - position_seconds
        countdown = bars_to_next(remaining, bpm)
    return {
        "phrase": current.get("label"),
        "next_phrase": next_label,
        "bars_to_next": countdown,
        "structure_status": projection.get("projection_status"),
        "structure_reason": None,
    }


def _live_ui_deck(raw, active_deck_number, active_transport=None):
    raw = dict(raw or {})
    deck_number = raw.get("deck_number")
    if deck_number is None:
        return None
    is_active = deck_number == active_deck_number
    active_transport = active_transport or {}
    path = raw.get("track_path") if raw.get("is_loaded") else None
    if is_active and active_transport.get("track_path"):
        path = active_transport.get("track_path")
    loaded = bool(raw.get("is_loaded") and path)
    bpm = raw.get("bpm") if loaded else None
    position = raw.get("position_milliseconds") if loaded else None
    beat_number = raw.get("beat_number") if loaded else None
    bar_number = raw.get("bar_number") if loaded else None
    if is_active:
        bpm = active_transport.get("bpm") if active_transport.get("bpm") is not None else bpm
        position = active_transport.get("position_milliseconds") if active_transport.get("position_milliseconds") is not None else position
        beat_number = active_transport.get("beat_number") if active_transport.get("beat_number") is not None else beat_number
        bar_number = active_transport.get("bar_number") if active_transport.get("bar_number") is not None else bar_number
    title = raw.get("title") or (Path(path).stem if path else None)
    artist = raw.get("artist")
    structure = _live_ui_structure(path, position, bpm) if loaded else None
    return {
        "deck_number": deck_number,
        "is_loaded": loaded,
        "is_active": is_active,
        "track_path": path,
        "track_title": title,
        "track_artist": artist,
        "bpm": bpm,
        "position_milliseconds": position,
        "beat_number": beat_number,
        "bar_number": bar_number,
        "phrase": None if structure is None else structure["phrase"],
        "next_phrase": None if structure is None else structure["next_phrase"],
        "bars_to_next": None if structure is None else structure["bars_to_next"],
        "structure_status": None if structure is None else structure["structure_status"],
        "structure_reason": None if structure is None else structure["structure_reason"],
    }


def live_ui_state(transport_state=None):
    """Build the typed, read-only projection consumed by the native UI."""
    state = dict(transport_state or {})
    playback = dict(state.get("playback_state") or {})
    beatbeam = dict(playback.get("beatbeam") or {})
    source = playback.get("source") or state.get("_active_playback_source")
    active_deck_number = beatbeam.get("deck_number")
    active_transport = {
        "track_path": beatbeam.get("track_path"),
        "position_milliseconds": beatbeam.get("estimated_position_milliseconds"),
        "bpm": beatbeam.get("bpm"),
        "beat_number": beatbeam.get("beat_number"),
        "bar_number": beatbeam.get("bar_number"),
    }
    raw_decks = playback.get("decks")
    if not isinstance(raw_decks, list):
        raw_decks = []
    rendered_decks = [
        deck for deck in (_live_ui_deck(raw, active_deck_number, active_transport) for raw in raw_decks)
        if deck is not None
    ]
    if not rendered_decks and active_deck_number is not None and active_transport.get("track_path"):
        rendered_decks = [_live_ui_deck({
            "deck_number": active_deck_number,
            "is_loaded": True,
            "track_path": active_transport["track_path"],
            "title": None,
            "artist": None,
            "bpm": active_transport["bpm"],
            "position_milliseconds": active_transport["position_milliseconds"],
            "beat_number": active_transport["beat_number"],
            "bar_number": active_transport["bar_number"],
        }, active_deck_number, active_transport)]
    rendered_decks.sort(key=lambda deck: deck["deck_number"])
    active_deck = next((deck for deck in rendered_decks if deck["is_active"]), None)
    path = active_transport.get("track_path")
    title = active_deck.get("track_title") if active_deck else (Path(path).stem if path else None)
    artist = active_deck.get("track_artist") if active_deck else None
    structure = _live_ui_structure(path, active_transport.get("position_milliseconds"), active_transport.get("bpm"))
    return {
        "source": source,
        "availability": playback.get("availability", "unavailable"),
        "transport_state": playback.get("transport_state"),
        "active_deck_number": active_deck_number,
        "track_path": path,
        "track_title": title,
        "track_artist": artist,
        "bpm": active_transport.get("bpm"),
        "beat_number": active_transport.get("beat_number"),
        "bar_number": active_transport.get("bar_number"),
        "fractional_beat": beatbeam.get("beat_position"),
        "position_milliseconds": active_transport.get("position_milliseconds"),
        "phrase": None if structure is None else structure["phrase"],
        "next_phrase": None if structure is None else structure["next_phrase"],
        "bars_to_next": None if structure is None else structure["bars_to_next"],
        "structure_status": None if structure is None else structure["structure_status"],
        "structure_reason": None if structure is None else structure["structure_reason"],
        "decks": rendered_decks,
        "clock_metrics": playback.get("metrics") or {},
    }


def full_state():
    osc_state = TRANSPORT.state()
    return {
        "app": {"name": APP_NAME, "api_schema_version": API_SCHEMA_VERSION},
        "dmx": DMX.state(),
        "osc": osc_state,
        "remote": remote_access_state(),
        "source": TRANSPORT.source_state(),
        "transport": TRANSPORT.transport_state(),
        "developer_playback": TRANSPORT.developer_playback_state(osc_state),
        "developer_structure_behavior": structure_behavior_state(osc_state),
        "live_ui": live_ui_state(osc_state),
        "debug": beatbeam_debug_state(osc_state),
    }


def beatbeam_debug_state(osc_state=None):
    state = TRANSPORT.state() if osc_state is None else osc_state
    playback = dict(state.get("playback_state") or {})
    live_transport = dict(playback.get("beatbeam") or {})
    observed_at = ((playback.get("virtualdj") or {}).get("captured_at_unix_milliseconds"))
    position_age = None
    if isinstance(observed_at, int) and observed_at >= 0:
        position_age = max(0, int(time.time() * 1000) - observed_at)
    projection = SONG_ANALYZER_STRUCTURE.project(state)
    behavior = structure_behavior_state(state)
    auto_show = (DMX.state().get("auto_show") or {})
    bridge = SONG_ANALYZER_BRIDGE_DIAGNOSTICS.snapshot()
    current = projection.get("current") or {}
    rich = projection.get("rich_current") or {}
    active = projection.get("active_track") or {}
    fallback = behavior.get("fallback_reason")
    return {
        "virtualdj": {
            "transport_source": state.get("_active_playback_source"),
            "active_deck": live_transport.get("deck_number"),
            "track_path": live_transport.get("track_path"),
            "playing": playback.get("availability") == "available",
            "position_milliseconds": live_transport.get("estimated_position_milliseconds"),
            "position_age_milliseconds": position_age,
            "transport_state": playback.get("transport_state"),
            "bridge_status": bridge.get("status"),
        },
        "active_track": active or None,
        "analysis": {
            "schema_version": projection.get("schema_version"),
            "model": projection.get("model"),
            "segment": current or None,
            "rich_current": rich or None,
            "energy_modifier": auto_show.get("song_analyzer_energy_modifier"),
        },
        "handoff": {
            "track_match": projection.get("track_match"),
            "availability": projection.get("availability"),
            "rich_analysis": projection.get("rich_analysis"),
            "fallback_reason": fallback,
            "effective_source": behavior.get("effective_source"),
            "selected_source": behavior.get("selected_source"),
        },
        "bridge_diagnostics": bridge,
    }


def song_analyzer_structure_state():
    return SONG_ANALYZER_STRUCTURE.project(TRANSPORT.state())


def structure_behavior_state(osc_state=None):
    state = TRANSPORT.state() if osc_state is None else osc_state
    return STRUCTURE_BEHAVIOR.resolve(
        TRANSPORT.structure_behavior_source(), state, include_shadow=True
    )


def remote_state():
    osc_state = TRANSPORT.state()
    dmx_state = DMX.state()
    return {
        "dmx": {
            "connected": dmx_state.get("connected", False),
            "blackout_active": dmx_state.get("blackout_active", False),
            "active_slot": dmx_state.get("active_slot", "head"),
            "auto_show": dmx_state.get("auto_show", {}),
        },
        "osc": {
            "bpm": osc_state.get("bpm"),
            "beat_display": osc_state.get("beat_display"),
            "phrase_current": osc_state.get("phrase_current"),
            "phrase_next": osc_state.get("phrase_next"),
            "track_title": osc_state.get("track_title"),
            "track_artist": osc_state.get("track_artist"),
            "stale": osc_state.get("stale", True),
        },
        "transport": TRANSPORT.transport_state(),
    }


class AppHandler(BaseHTTPRequestHandler):
    server_version = os.environ.get("BEATBEAM_SERVER_VERSION") or f"{APP_SLUG}/1.2-dev"
    protocol_version = "HTTP/1.1"

    def request_context(self):
        parsed = urlparse(self.path)
        query = {}
        raw_query = parsed.query or ""
        if raw_query:
            for pair in raw_query.split("&"):
                if not pair:
                    continue
                key, _, value = pair.partition("=")
                query[key] = value
        return parsed.path, query

    def is_authorized_remote_request(self, query):
        client_ip = self.client_address[0] if self.client_address else ""
        if is_loopback_client(client_ip):
            return True
        if not remote_access_requires_token():
            return True
        expected = remote_access_token()
        if not expected:
            return True
        provided = (
            self.headers.get("X-BeatBeam-Token")
            or self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            or query.get("token")
        )
        return str(provided or "").strip() == expected

    def deny_remote_request(self, path):
        if path.startswith("/api/"):
            self.send_json({"error": "remote access token required"}, status=403)
            return
        body = (
            "<!doctype html><html><body style='font-family:system-ui;background:#111;color:#eee;padding:24px'>"
            "<h1>Access denied</h1><p>Open de volledige remote-URL vanuit BeatBeam, inclusief token.</p>"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path, query = self.request_context()
        if path in ("/remote", "/live-remote") and not self.is_authorized_remote_request(query):
            self.deny_remote_request(path)
            return
        if path.startswith("/api/") and not self.is_authorized_remote_request(query):
            self.deny_remote_request(path)
            return
        if path == "/api/remote-state":
            self.send_json(remote_state())
            return
        if path == "/api/remote-events":
            self.send_event_stream(remote_state)
            return
        if path == "/api/state":
            self.send_json(full_state())
            return
        if path == "/api/developer/playback":
            self.send_json(TRANSPORT.developer_playback_state())
            return
        if path == "/api/developer/structure":
            self.send_json(song_analyzer_structure_state())
            return
        if path == "/api/developer/structure-behavior":
            self.send_json(structure_behavior_state())
            return
        if path == "/api/developer/virtualdj-beat-pulse":
            self.send_json(DMX.virtualdj_beat_pulse_test_state())
            return
        if path == "/api/developer/virtualdj-beat-pulse-preview":
            self.send_json(DMX.virtualdj_beat_pulse_preview_test_state())
            return
        if path == "/api/ports":
            self.send_json({"ports": serial_ports()})
            return
        if path == "/api/fixtures":
            self.send_json({"fixtures": load_fixture_profiles()})
            return
        if path == "/":
            path = "/index.html"
        elif path in ("/remote", "/live-remote"):
            path = "/remote.html"
        self.send_static(path)

    def do_POST(self):
        path, query = self.request_context()
        if path.startswith("/api/") and not self.is_authorized_remote_request(query):
            self.deny_remote_request(path)
            return
        try:
            payload = self.read_json()
            if path == "/api/dmx/connect":
                DMX.connect(payload["port"], payload.get("fps", DEFAULT_DMX_FPS))
                self.send_json(full_state())
                return
            if path == "/api/dmx/disconnect":
                DMX.disconnect()
                self.send_json(full_state())
                return
            if path == "/api/dmx/update":
                DMX.update_config(payload)
                self.send_json(full_state())
                return
            if path == "/api/dmx/trigger-cue":
                DMX.trigger_one_shot_cue(payload.get("cue_id"))
                self.send_json(full_state())
                return
            if path == "/api/dmx/add-slot":
                DMX.add_slot(payload["fixture_id"], payload.get("mode"))
                self.send_json(full_state())
                return
            if path == "/api/dmx/remove-slot":
                DMX.remove_slot(payload["slot_id"])
                self.send_json(full_state())
                return
            if path == "/api/dmx/blackout":
                DMX.blackout()
                self.send_json(full_state())
                return
            if path == "/api/transport/update":
                TRANSPORT.update_config(payload)
                self.send_json(full_state())
                return
            if path == "/api/transport/tap":
                TRANSPORT.tap()
                self.send_json(full_state())
                return
            if path == "/api/transport/reset":
                TRANSPORT.reset_manual_clock()
                self.send_json(full_state())
                return
            if path == "/api/developer/playback/update":
                TRANSPORT.update_developer_playback(payload)
                self.send_json(full_state())
                return
            if path == "/api/developer/structure-behavior":
                source = payload.get("source")
                if source not in STRUCTURE_BEHAVIOR_SOURCES:
                    raise ValueError("source must be legacy or song_analyzer")
                TRANSPORT.update_config({"structure_behavior_source": source})
                self.send_json(structure_behavior_state())
                return
            if path == "/api/developer/virtualdj-beat-pulse/start":
                self.send_json(DMX.start_virtualdj_beat_pulse_test(payload))
                return
            if path == "/api/developer/virtualdj-beat-pulse/stop":
                self.send_json(DMX.stop_virtualdj_beat_pulse_test())
                return
            if path == "/api/developer/virtualdj-beat-pulse-preview/start":
                self.send_json(DMX.start_virtualdj_beat_pulse_preview_test(payload))
                return
            if path == "/api/developer/virtualdj-beat-pulse-preview/stop":
                self.send_json(DMX.stop_virtualdj_beat_pulse_preview_test())
                return
        except Exception as exc:
            self.send_json({"error": str(exc), "state": full_state()}, status=400)
            return
        self.send_json({"error": "not found"}, status=404)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_event_stream(self, payload_provider, interval_seconds=0.05):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last_payload = None
        last_keepalive_at = 0.0
        try:
            while True:
                payload = payload_provider()
                encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
                if encoded != last_payload:
                    chunk = f"event: state\ndata: {encoded}\n\n".encode("utf-8")
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    last_payload = encoded
                    last_keepalive_at = time.time()
                elif time.time() - last_keepalive_at >= 10.0:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    last_keepalive_at = time.time()
                time.sleep(interval_seconds)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return

    def send_static(self, route_path):
        relative = route_path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


def shutdown():
    DMX.disconnect()
    TRANSPORT.stop()


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} local controller")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_HTTP_PORT)
    parser.add_argument("--osc-port", type=int, default=DEFAULT_OSC_PORT)
    args = parser.parse_args()

    global SERVER_HOST, SERVER_PORT, REMOTE_ACCESS_CONFIG
    SERVER_HOST = str(args.host)
    SERVER_PORT = int(args.port)
    REMOTE_ACCESS_CONFIG = load_remote_access_config()
    OSC.port = args.osc_port
    TRANSPORT.start()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    TRIGGER_LOG.log("BACKEND_START", host=args.host, port=args.port, osc_port=args.osc_port)
    print(f"{APP_NAME} running at http://{args.host}:{args.port}")
    print(f"OSC input listening on UDP {args.osc_port}")
    print(f"Trigger log: {TRIGGER_LOG_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()
        server.server_close()


atexit.register(shutdown)


if __name__ == "__main__":
    main()
