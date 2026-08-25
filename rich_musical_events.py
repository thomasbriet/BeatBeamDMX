"""Pure shadow-consumer voor software-onafhankelijke Rich Musical Events."""

from __future__ import annotations

from dataclasses import dataclass
import math
import numbers


BEATBEAM_RICH_EVENT_MODE = "SHADOW_ONLY"
CONTRACT = "rich-musical-events"
SCHEMA_VERSION = 1

EVENT_TYPES = frozenset({
    "SECTION_START", "SECTION_END", "BUILD", "RELEASE", "DROP", "BREAK",
    "ARRIVAL", "DEPARTURE", "RETURN", "TRANSITION",
})
TEMPORAL_KINDS = frozenset({"POINT", "INTERVAL", "BOUNDARY_TRANSITION"})
EVENT_ORDER = {
    "SECTION_END": 10,
    "RELEASE": 20,
    "DEPARTURE": 30,
    "TRANSITION": 40,
    "ARRIVAL": 50,
    "RETURN": 60,
    "DROP": 70,
    "BREAK": 80,
    "SECTION_START": 90,
    "BUILD": 100,
}


@dataclass(frozen=True)
class RichMusicalEventStructuralContext:
    family_id: str | None
    has_earlier_family_occurrence: bool | None
    structural_route: str | None


@dataclass(frozen=True)
class RichMusicalEventCharacterContext:
    origin_relative_energy: float | None
    destination_relative_energy: float | None
    energy_trajectory: float | None
    energy_direction: float | None
    onset_direction: float | None
    silence_direction: float | None
    entry_contrast: float | None
    boundary_novelty: float | None


@dataclass(frozen=True)
class RichMusicalEventProvenance:
    source_category: str
    derivation: str
    reasons: tuple[str, ...]
    required_inputs: tuple[str, ...]


@dataclass(frozen=True)
class RichMusicalEvent:
    event_type: str
    temporal_kind: str
    start_seconds: float
    end_seconds: float | None
    start_bar: int | None
    end_bar: int | None
    origin_observation_id: str
    destination_observation_id: str | None
    structural_context: RichMusicalEventStructuralContext
    character_context: RichMusicalEventCharacterContext
    provenance: RichMusicalEventProvenance


@dataclass(frozen=True)
class RichMusicalEventHandoff:
    track_key: str
    availability: str
    events: tuple[RichMusicalEvent, ...]
    mode: str = "shadow_only"


def parse_rich_musical_event_handoff(payload):
    """Parseer schema 1 atomisch; één malformed event wijst het document af."""
    if not isinstance(payload, dict):
        raise ValueError("Rich-eventhandoff moet een object zijn.")
    required = {"schema_version", "contract", "mode", "track_key", "availability", "events"}
    if set(payload) != required:
        raise ValueError("Rich-eventhandoff heeft ontbrekende of onbekende top-level velden.")
    if payload["schema_version"] != SCHEMA_VERSION or payload["contract"] != CONTRACT:
        raise ValueError("Onbekende rich-eventcontractversie.")
    if payload["mode"] != "shadow_only":
        raise ValueError("Alleen shadow_only is toegestaan.")
    track_key = _text(payload["track_key"], "track_key")
    availability = payload["availability"]
    if availability not in {"available", "unavailable"}:
        raise ValueError("Ongeldige availability.")
    raw_events = payload["events"]
    if not isinstance(raw_events, list):
        raise ValueError("events moet een lijst zijn.")
    events = tuple(_event(value) for value in raw_events)
    if availability == "unavailable" and events:
        raise ValueError("Unavailable handoff mag geen events bevatten.")
    if availability == "available" and not events:
        raise ValueError("Available handoff moet events bevatten.")
    keys = [_sort_key(value) for value in events]
    if keys != sorted(keys) or len({_identity(value) for value in events}) != len(events):
        raise ValueError("Events zijn niet deterministisch geordend of bevatten duplicaten.")
    return RichMusicalEventHandoff(track_key, availability, events)


def observe_rich_musical_events(handoff, position_seconds):
    """Geef uitsluitend read-only diagnostics; er bestaat geen show-outputpad."""
    if not isinstance(handoff, RichMusicalEventHandoff):
        raise TypeError("handoff moet een gevalideerde RichMusicalEventHandoff zijn.")
    position = _number(position_seconds, "position_seconds", minimum=0)
    active = tuple(event.event_type for event in handoff.events
                   if event.temporal_kind == "INTERVAL"
                   and event.end_seconds is not None
                   and event.start_seconds <= position < event.end_seconds)
    boundary = tuple(event.event_type for event in handoff.events
                     if event.temporal_kind != "INTERVAL"
                     and abs(event.start_seconds - position) <= 1e-6)
    next_event = next((event for event in handoff.events if event.start_seconds > position), None)
    return {
        "mode": BEATBEAM_RICH_EVENT_MODE,
        "availability": handoff.availability,
        "event_count": len(handoff.events),
        "active_interval_events": active,
        "boundary_events": boundary,
        "next_event": None if next_event is None else {
            "type": next_event.event_type,
            "start_seconds": next_event.start_seconds,
            "start_bar": next_event.start_bar,
        },
    }


def _event(value):
    if not isinstance(value, dict):
        raise ValueError("Event moet een object zijn.")
    required = {"type", "temporal_kind", "start_seconds", "origin_observation_id", "provenance"}
    allowed = required | {"end_seconds", "start_bar", "end_bar", "destination_observation_id",
                          "structural_context", "character_context"}
    if not required.issubset(value) or not set(value).issubset(allowed):
        raise ValueError("Event heeft ontbrekende of onbekende velden.")
    event_type = value["type"]
    temporal_kind = value["temporal_kind"]
    if event_type not in EVENT_TYPES or temporal_kind not in TEMPORAL_KINDS:
        raise ValueError("Onbekend eventtype of temporaliteit.")
    start = _number(value["start_seconds"], "start_seconds", minimum=0)
    end = _optional_number(value.get("end_seconds"), "end_seconds", minimum=0)
    start_bar = _optional_integer(value.get("start_bar"), "start_bar", minimum=1)
    end_bar = _optional_integer(value.get("end_bar"), "end_bar", minimum=1)
    if temporal_kind == "INTERVAL":
        if end is None or end <= start or start_bar is not None and end_bar is not None and end_bar < start_bar:
            raise ValueError("Interval heeft ongeldige eindlocatie.")
    elif end is not None or end_bar is not None:
        raise ValueError("Point/boundary-event mag geen intervaleinde hebben.")
    origin_id = _text(value["origin_observation_id"], "origin_observation_id")
    destination_id = _optional_text(value.get("destination_observation_id"), "destination_observation_id")
    structural = _structural_context(value.get("structural_context", {}))
    character = _character_context(value.get("character_context", {}))
    provenance = _provenance(value["provenance"])
    return RichMusicalEvent(event_type, temporal_kind, start, end, start_bar, end_bar,
                            origin_id, destination_id, structural, character, provenance)


def _structural_context(value):
    if not isinstance(value, dict) or not set(value).issubset({
            "family_id", "has_earlier_family_occurrence", "structural_route"}):
        raise ValueError("Ongeldige structural_context.")
    earlier = value.get("has_earlier_family_occurrence")
    if earlier is not None and not isinstance(earlier, bool):
        raise ValueError("has_earlier_family_occurrence moet boolean of null zijn.")
    return RichMusicalEventStructuralContext(
        _optional_text(value.get("family_id"), "family_id"), earlier,
        _optional_text(value.get("structural_route"), "structural_route"))


def _character_context(value):
    names = {
        "origin_relative_energy", "destination_relative_energy", "energy_trajectory",
        "energy_direction", "onset_direction", "silence_direction", "entry_contrast", "boundary_novelty",
    }
    if not isinstance(value, dict) or not set(value).issubset(names):
        raise ValueError("Ongeldige character_context.")
    relative = {name: _optional_number(value.get(name), name, minimum=0, maximum=1)
                for name in ("origin_relative_energy", "destination_relative_energy")}
    directional = {name: _optional_number(value.get(name), name)
                   for name in ("energy_trajectory", "energy_direction", "onset_direction", "silence_direction")}
    bounded = {name: _optional_number(value.get(name), name, minimum=0, maximum=1)
               for name in ("entry_contrast", "boundary_novelty")}
    return RichMusicalEventCharacterContext(
        relative["origin_relative_energy"], relative["destination_relative_energy"],
        directional["energy_trajectory"], directional["energy_direction"],
        directional["onset_direction"], directional["silence_direction"],
        bounded["entry_contrast"], bounded["boundary_novelty"])


def _provenance(value):
    if not isinstance(value, dict) or set(value) != {
            "source_category", "derivation", "reasons", "required_inputs"}:
        raise ValueError("Ongeldige provenance.")
    if value["source_category"] != "software_independent_structure_character":
        raise ValueError("Ongeldige source_category.")
    if value["derivation"] not in {"direct", "derived"}:
        raise ValueError("Ongeldige derivation.")
    reasons = _text_tuple(value["reasons"], "reasons")
    required_inputs = _text_tuple(value["required_inputs"], "required_inputs")
    if tuple(sorted(reasons)) != reasons or tuple(sorted(required_inputs)) != required_inputs:
        raise ValueError("Provenance-lijsten moeten deterministisch gesorteerd zijn.")
    return RichMusicalEventProvenance(value["source_category"], value["derivation"], reasons, required_inputs)


def _text_tuple(value, name):
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} moet een niet-lege lijst zijn.")
    result = tuple(_text(item, name) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} bevat duplicaten.")
    return result


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} moet niet-lege tekst zijn.")
    return value


def _optional_text(value, name):
    return None if value is None else _text(value, name)


def _number(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(value):
        raise ValueError(f"{name} moet een eindig getal zijn.")
    result = float(value)
    if minimum is not None and result < minimum or maximum is not None and result > maximum:
        raise ValueError(f"{name} valt buiten bereik.")
    return result


def _optional_number(value, name, minimum=None, maximum=None):
    return None if value is None else _number(value, name, minimum, maximum)


def _optional_integer(value, name, minimum=None):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or minimum is not None and value < minimum:
        raise ValueError(f"{name} moet een geldige integer zijn.")
    return value


def _sort_key(value):
    return (value.start_seconds, EVENT_ORDER[value.event_type], value.origin_observation_id,
            value.destination_observation_id or "")


def _identity(value):
    return (value.event_type, value.start_seconds, value.end_seconds,
            value.origin_observation_id, value.destination_observation_id)
