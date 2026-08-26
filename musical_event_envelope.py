"""Pure, beatgebaseerde preview-envelope voor puntvormige muzikale events.

De envelope verlengt geen SongAnalyzer-event. Zij projecteert uitsluitend de
bestaande boundary op een tijdelijke show-intentie boven de continuous backbone.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import numbers


POINT_ENVELOPE_EVENT_TYPES = frozenset({"ARRIVAL", "DROP", "RELEASE", "TRANSITION", "FILL"})
_ENVELOPE_SPECS = {
    # total/attack/impact zijn muzikale beats; settle vult het restant.
    "ARRIVAL": (8.0, 0.25, 0.75),
    "DROP": (6.0, 0.25, 0.75),
    "RELEASE": (8.0, 0.0, 0.50),
    "TRANSITION": (8.0, 0.25, 0.75),
    # Alleen future-ready: geen detector of renderer-strobe-route in deze milestone.
    "FILL": (2.0, 0.125, 0.375),
}
# Eén boundary kan meerdere beschrijvende RME's dragen (bijvoorbeeld RELEASE,
# ARRIVAL en DROP). Per boundary is precies één envelope toegestaan; deze kleine
# semantische voorrang voorkomt stacking en houdt DROP duidelijker dan ARRIVAL.
_BOUNDARY_PRIORITY = {"DROP": 4, "FILL": 3, "RELEASE": 2, "ARRIVAL": 1, "TRANSITION": 0}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _unit(value):
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class MusicalEventEnvelope:
    """Kleine fixture-onafhankelijke eventmodifier, volledig afleidbaar uit playback."""

    event_type: str
    phase: str
    progress: float
    strength: float
    beats_since_event: float
    total_beats: float
    timing_source: str
    active: bool = True

    def __post_init__(self):
        event_type = str(self.event_type or "").strip().upper()
        phase = str(self.phase or "").strip().upper()
        if event_type not in POINT_ENVELOPE_EVENT_TYPES:
            raise ValueError("musical event envelope type is invalid")
        if phase not in {"ATTACK", "IMPACT", "SETTLE"}:
            raise ValueError("musical event envelope phase is invalid")
        for name in ("progress", "strength"):
            value = _number(getattr(self, name))
            if value is None or not 0.0 <= value <= 1.0:
                raise ValueError(f"musical event envelope {name} is invalid")
            object.__setattr__(self, name, value)
        beats = _number(self.beats_since_event)
        total = _number(self.total_beats)
        if beats is None or beats < 0 or total is None or total <= 0 or beats >= total:
            raise ValueError("musical event envelope beat span is invalid")
        source = str(self.timing_source or "").strip().lower()
        if source not in {"bar", "bpm"}:
            raise ValueError("musical event envelope timing source is invalid")
        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "beats_since_event", beats)
        object.__setattr__(self, "total_beats", total)
        object.__setattr__(self, "timing_source", source)
        object.__setattr__(self, "active", True)

    def as_dict(self):
        return asdict(self)


def project_musical_event_envelope(projection, playback):
    """Projecteer de nieuwste actieve point-event-envelope of ``(None, reason)``.

    Bar/beat-context heeft voorrang. Alleen wanneer die niet beschikbaar is,
    rekent de bestaande playback-BPM de bestaande elapsed time om naar beats.
    """
    if not isinstance(projection, dict) or not isinstance(playback, dict):
        return None, "projection_unavailable"
    if projection.get("track_match") != "exact" or projection.get("availability") != "available_current":
        return None, "track_not_current"
    if projection.get("projection_status") not in {"in_segment", "in_final_segment"}:
        return None, "position_not_current"
    position = _number(playback.get("time_seconds"))
    if position is None or position < 0:
        return None, "position_invalid"
    handoff = projection.get("rich_musical_events")
    if not isinstance(handoff, dict) or handoff.get("mode") != "SHADOW_ONLY" \
            or handoff.get("availability") != "available" or not isinstance(handoff.get("events"), list):
        return None, "rme_unavailable"

    candidates = []
    for event in handoff["events"]:
        if not isinstance(event, dict) or event.get("type") not in POINT_ENVELOPE_EVENT_TYPES:
            continue
        start = _number(event.get("start_seconds"))
        if start is None or start > position:
            continue
        beats, timing_source = _beats_since_event(event, playback, position, start)
        if beats is None:
            continue
        candidates.append((start, event, beats, timing_source))
    if not candidates:
        return None, "complete_or_no_point_event"
    # Selecteer eerst de nieuwste boundary en daarbinnen exact één semantische
    # winnaar. Completion wordt pas daarna getoetst: een lager-prioritaire
    # beschrijving op dezelfde boundary of een oudere boundary mag nooit na de
    # winnaar opnieuw opduiken.
    _start, event, beats, timing_source = max(
        candidates, key=lambda item: (item[0], _BOUNDARY_PRIORITY[item[1]["type"]])
    )
    total, attack, impact = _ENVELOPE_SPECS[event["type"]]
    if beats >= total:
        return None, "complete_or_no_point_event"
    phase, strength = _phase_and_strength(beats, total, attack, impact)
    return MusicalEventEnvelope(
        event_type=event["type"],
        phase=phase,
        progress=_unit(beats / total),
        strength=strength,
        beats_since_event=beats,
        total_beats=total,
        timing_source=timing_source,
    ), "active"


def _beats_since_event(event, playback, position, start_seconds):
    transport = playback.get("transport") or {}
    current_bar = transport.get("virtualdj_bar_number")
    current_beat = transport.get("virtualdj_beat_number")
    beat_value = _number(playback.get("beat_value"))
    start_bar = event.get("start_bar")
    if isinstance(start_bar, int) and start_bar >= 1 and isinstance(current_bar, int) and current_bar >= start_bar \
            and isinstance(current_beat, int) and 1 <= current_beat <= 4:
        beat_phase = 0.0 if beat_value is None else beat_value - math.floor(beat_value)
        return (current_bar - start_bar) * 4.0 + (current_beat - 1) + beat_phase, "bar"
    bpm = _number(playback.get("bpm"))
    if bpm is None or bpm <= 0:
        return None, None
    return max(0.0, position - start_seconds) * bpm / 60.0, "bpm"


def _phase_and_strength(beats, total, attack, impact):
    if attack > 0 and beats < attack:
        return "ATTACK", _unit(0.70 + 0.30 * beats / attack)
    if beats < attack + impact:
        return "IMPACT", 1.0
    settle_span = max(1e-6, total - attack - impact)
    return "SETTLE", _unit(1.0 - (beats - attack - impact) / settle_span)
