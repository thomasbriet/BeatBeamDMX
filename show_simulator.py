"""Offline, read-only replay of the existing BeatBeam musical preview pipeline.

This module owns no DMX controller, transport authority, audio device or live
override.  It asks the existing SongAnalyzer handoff for a projection and then
uses the existing ContinuousMusicalState, RME, EventEnvelope and Dynamic
Composer functions unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Callable, Optional

from dynamic_composer import CompositionHistory, compose_dynamic_preview, project_continuous_musical_state
from musical_event_envelope import project_musical_event_envelope
from rme_preview import preview_rme_context


def _finite(value, default=0.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


@dataclass
class ShowSimulationSession:
    """A deterministic, non-authoritative transport for one current analysis."""

    handoff: object
    smart_cues: Optional[Callable] = None
    preview_frame_builder: Optional[Callable] = None
    track_path: str | None = None
    duration_seconds: float = 0.0
    bpm: float | None = None
    position_seconds: float = 0.0
    playing: bool = False
    generation: int = 0
    _history: CompositionHistory = field(default_factory=CompositionHistory, init=False)
    _last_monotonic: float = field(default_factory=time.monotonic, init=False)

    def tracks(self):
        catalog = getattr(self.handoff, "catalog", None)
        return catalog() if callable(catalog) else []

    def select(self, path):
        item = next((track for track in self.tracks() if track["path"] == path), None)
        if item is None:
            raise ValueError("simulator track is not a current analysis")
        self.track_path = item["path"]
        self.duration_seconds = _finite(item.get("duration_seconds"), 0.0)
        self.bpm = item.get("bpm")
        self.position_seconds = 0.0
        self.playing = False
        self.generation += 1
        self._history.reset()
        self._last_monotonic = time.monotonic()
        return self.state()

    def play(self):
        self._advance()
        if self.track_path and self.position_seconds < self.duration_seconds:
            self.playing = True
            self._last_monotonic = time.monotonic()
        return self.state()

    def pause(self):
        self._advance()
        self.playing = False
        return self.state()

    def restart(self):
        if not self.track_path:
            return self.state()
        self.position_seconds = 0.0
        self.playing = False
        self.generation += 1
        self._history.reset()
        self._last_monotonic = time.monotonic()
        return self.state()

    def seek(self, seconds):
        if not self.track_path:
            raise ValueError("select a simulator track first")
        target = min(self.duration_seconds, max(0.0, _finite(seconds, -1.0)))
        if target < 0:
            raise ValueError("simulator seek is invalid")
        self.position_seconds = target
        # Deterministic seek-reset: identity at T is a pure function of the
        # current section/event, never an accidental live playback history.
        self._history.reset()
        self.generation += 1
        self._last_monotonic = time.monotonic()
        return self.state()

    def jump_smart_cue(self, role):
        cue = next((cue for cue in self._cues() if cue.get("role") == str(role).upper()
                    and cue.get("planned") and _finite(cue.get("position_milliseconds"), -1) >= 0), None)
        if cue is None:
            raise ValueError("simulator Smart Cue is unavailable")
        return self.seek(_finite(cue["position_milliseconds"]) / 1000.0)

    def previous_section(self):
        return self._jump_marker("sections", previous=True)

    def next_section(self):
        return self._jump_marker("sections", previous=False)

    def previous_event(self):
        return self._jump_marker("events", previous=True)

    def next_event(self):
        return self._jump_marker("events", previous=False)

    def state(self):
        self._advance()
        base = {
            "mode": "SIMULATION",
            "physical_output": "NONE",
            "live_intensity": {"source_valid": False, "live_modifier": 0.0, "status": "ANALYZED_ONLY"},
            "track": None,
            "transport": {"playing": self.playing, "position_milliseconds": round(self.position_seconds * 1000),
                          "duration_milliseconds": round(self.duration_seconds * 1000), "bpm": self.bpm,
                          "beat": None, "bar": None, "generation": self.generation},
            "projection": None, "continuous_musical_state": None, "rme": None,
            "event_envelope": None, "composition": None, "smart_cues": [], "timeline": self._empty_timeline(),
            "simulation_slot_previews": {}, "preview_source": "simulation_slot_previews",
        }
        if not self.track_path:
            return base
        bpm = _finite(self.bpm, 0.0) or None
        beat_value = self.position_seconds * bpm / 60.0 if bpm else None
        beat = None if beat_value is None else int(math.floor(beat_value)) % 4 + 1
        bar = None if beat_value is None else int(math.floor(beat_value / 4.0)) + 1
        playback = {
            "_active_playback_source": "simulator", "track_path": self.track_path,
            "time_seconds": self.position_seconds, "bpm": bpm, "beat_value": beat_value,
            "transport": {"virtualdj_bar_number": bar, "virtualdj_beat_number": beat},
            "_playback_generation": self.generation,
        }
        projection = self.handoff.project(playback, include_shadow=True, include_rich_events=True)
        continuous, continuous_reason = project_continuous_musical_state(projection, self.position_seconds)
        envelope, envelope_reason = project_musical_event_envelope(projection, playback)
        context = preview_rme_context(projection, self.position_seconds, "DYNAMIC_COMPOSER")
        context.update({"continuous_state_reason": continuous_reason, "event_envelope_reason": envelope_reason})
        composition = compose_dynamic_preview(
            {"override_active": False, "live_intensity": base["live_intensity"]}, continuous, context,
            envelope, self._history, ("simulation", self.track_path, self.generation), base["live_intensity"]
        ) if continuous else None
        cues = self._cues()
        timeline = self._timeline(projection, cues, envelope)
        preview_frame = self.preview_frame_builder(playback) if callable(self.preview_frame_builder) else {}
        base.update({
            "track": {"path": self.track_path, "analysis_identity": projection.get("analysis_version"),
                      "availability": projection.get("availability")},
            "transport": {**base["transport"], "bpm": bpm, "beat": beat, "bar": bar},
            "projection": projection, "continuous_musical_state": None if continuous is None else composition.get("continuous_musical_state"),
            "rme": context.get("current_rme"), "event_envelope": None if envelope is None else envelope.as_dict(),
            "composition": composition, "smart_cues": cues, "timeline": timeline,
            "simulation_slot_previews": dict(preview_frame.get("slot_previews") or {}),
            "preview_source": preview_frame.get("preview_source", "simulation_slot_previews"),
        })
        return base

    def _advance(self):
        now = time.monotonic()
        elapsed = max(0.0, now - self._last_monotonic)
        self._last_monotonic = now
        if self.playing and self.track_path:
            self.position_seconds = min(self.duration_seconds, self.position_seconds + elapsed)
            if self.position_seconds >= self.duration_seconds:
                self.playing = False

    def _cues(self):
        return self.smart_cues(self.track_path) if self.track_path and callable(self.smart_cues) else []

    def _jump_marker(self, kind, previous):
        if not self.track_path:
            raise ValueError("select a simulator track first")
        markers = self.state()["timeline"].get(kind) or []
        current = self.position_seconds
        if previous:
            candidates = [item for item in markers if _finite(item.get("start_seconds"), -1) < current - 1e-6]
            target = candidates[-1] if candidates else None
        else:
            candidates = [item for item in markers if _finite(item.get("start_seconds"), -1) > current + 1e-6]
            target = candidates[0] if candidates else None
        if target is None:
            return self.state()
        return self.seek(target["start_seconds"])

    @staticmethod
    def _empty_timeline():
        return {"duration_seconds": 0.0, "playhead_seconds": 0.0, "sections": [], "events": [], "smart_cues": [], "envelope": None}

    def _timeline(self, projection, cues, envelope):
        shadow = (projection.get("shadow_analysis") or {}).get("section_characters") or []
        sections = [{"id": item.get("observation_id"), "start_seconds": item.get("start_seconds"),
                     "end_seconds": item.get("end_seconds"), "relative_energy": item.get("relative_energy"),
                     "recurrence_strength": item.get("recurrence_strength"), "family_salience": item.get("family_salience")}
                    for item in shadow if isinstance(item, dict)]
        events = (projection.get("rich_musical_events") or {}).get("events") or []
        events = [{"type": item.get("type"), "start_seconds": item.get("start_seconds"),
                   "end_seconds": item.get("end_seconds"), "temporal_kind": item.get("temporal_kind")}
                  for item in events if isinstance(item, dict)]
        cue_markers = [{"role": item.get("role"), "start_seconds": _finite(item.get("position_milliseconds"), 0.0) / 1000.0,
                        "planned": bool(item.get("planned"))} for item in cues]
        return {"duration_seconds": self.duration_seconds, "playhead_seconds": self.position_seconds,
                "sections": sections, "events": events, "smart_cues": cue_markers,
                "envelope": None if envelope is None else envelope.as_dict()}
