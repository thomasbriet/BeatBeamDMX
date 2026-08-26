"""Pure, begrensde compositie voor de experimentele Preview Map.

De composer kent uitsluitend software-onafhankelijke muzikale state,
eventmodulatie en bestaande benoemde showprimitives. Hij kent geen fixtures,
kanalen, DMX-waarden of production-runtime-state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import math
import numbers

from musical_event_envelope import MusicalEventEnvelope


DYNAMIC_COMPOSER_MODE = "DYNAMIC_COMPOSER"
GROUP_NAMES = ("moving", "par", "wash", "static")
INTERVAL_EVENT_TYPES = frozenset({"BUILD", "BREAK"})
COMPOSITION_HISTORY_CAPACITY = 6


def _number(value):
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _unit(value, default=0.0):
    value = _number(value)
    return max(0.0, min(1.0, value)) if value is not None else default


@dataclass(frozen=True)
class ContinuousMusicalState:
    """Minimale software-onafhankelijke backbone voor één actuele sectie."""

    observation_id: str
    section_start_seconds: float
    section_end_seconds: float
    section_progress: float
    relative_energy: float
    energy_trajectory: float | None = None
    recurrence_strength: float | None = None
    family_salience: float | None = None

    def __post_init__(self):
        observation_id = str(self.observation_id or "").strip()
        start = _number(self.section_start_seconds)
        end = _number(self.section_end_seconds)
        progress = _number(self.section_progress)
        energy = _number(self.relative_energy)
        if not observation_id or start is None or start < 0 or end is None or end <= start:
            raise ValueError("continuous musical section is invalid")
        if progress is None or not 0.0 <= progress <= 1.0:
            raise ValueError("continuous musical section progress is invalid")
        if energy is None or not 0.0 <= energy <= 1.0:
            raise ValueError("continuous musical relative energy is invalid")
        object.__setattr__(self, "observation_id", observation_id)
        object.__setattr__(self, "section_start_seconds", start)
        object.__setattr__(self, "section_end_seconds", end)
        object.__setattr__(self, "section_progress", progress)
        object.__setattr__(self, "relative_energy", energy)
        trajectory = self.energy_trajectory
        if trajectory is not None:
            trajectory = _number(trajectory)
            if trajectory is None or not -1.0 <= trajectory <= 1.0:
                raise ValueError("continuous musical energy trajectory is invalid")
            object.__setattr__(self, "energy_trajectory", trajectory)
        for name in ("recurrence_strength", "family_salience"):
            value = getattr(self, name)
            if value is not None:
                value = _number(value)
                if value is None or not 0.0 <= value <= 1.0:
                    raise ValueError(f"continuous musical {name} is invalid")
                object.__setattr__(self, name, value)


@dataclass(frozen=True)
class FixtureGroupIntent:
    """Kleine, fixture-onafhankelijke intent; ontbrekende capabilities zijn neutraal."""

    activity: float
    intensity: float
    movement_amount: float
    movement_speed: float
    color_change_rate: float
    palette_role: str
    pulse_amount: float
    accent_strength: float

    def __post_init__(self):
        for name in (
            "activity", "intensity", "movement_amount", "movement_speed",
            "color_change_rate", "pulse_amount", "accent_strength",
        ):
            object.__setattr__(self, name, _unit(getattr(self, name)))
        palette = str(self.palette_role or "base").strip().lower()
        object.__setattr__(self, "palette_role", palette if palette in {
            "base", "tension", "space", "impact", "release"
        } else "base")


@dataclass(frozen=True)
class CompositionSignature:
    """Leesbare, compacte preview-identiteit; geen opaque hash als debug-output."""

    motion_family: str
    motion_parameters: tuple
    palette_family: str
    palette_relationship: str
    pulse: str
    wash: str
    fixture_roles: str

    def as_dict(self):
        return asdict(self)

    def key(self):
        return (self.motion_family, self.motion_parameters, self.palette_family,
                self.palette_relationship, self.pulse, self.wash, self.fixture_roles)


class CompositionHistory:
    """Kleine, niet-persistente track-local keuzehistorie voor de Preview Map."""

    def __init__(self, capacity=COMPOSITION_HISTORY_CAPACITY):
        self.capacity = max(1, int(capacity))
        self._context = None
        self._recent = []
        self._by_observation = {}

    def reset(self, context=None):
        self._context = context
        self._recent = []
        self._by_observation = {}

    def select(self, state, candidates, context=None):
        if context != self._context:
            self.reset(context)
        cached = self._by_observation.get(state.observation_id)
        if cached is not None:
            return cached["primitives"], cached["signature"], {
                "selection": "retained", "history_size": len(self._recent),
            }
        # Een terugkerende sectie mag een leesbare eerdere identiteit hernemen.
        if not self._recent:
            selected = min(candidates, key=lambda candidate: candidate["order"])
            selection = "new"
        else:
            recent_keys = {entry["signature"].key() for entry in self._recent}
            last_key = self._recent[-1]["signature"].key()
            reusable = next((
                entry for entry in reversed(self._recent[:-1])
                if entry["signature"].key() != last_key
            ), None) if state.recurrence_strength is not None \
                and state.recurrence_strength >= .70 else None
            if reusable is not None:
                selected = reusable
                selection = "recurrence_reuse"
            else:
                fresh = [candidate for candidate in candidates if candidate["signature"].key() not in recent_keys]
                pool = fresh or candidates
                selected = min(pool, key=lambda candidate: (
                    sum(candidate["signature"].motion_family == item["signature"].motion_family
                        for item in self._recent),
                    sum(candidate["signature"].palette_family == item["signature"].palette_family
                        for item in self._recent),
                    candidate["order"],
                ))
                selection = "anti_repeat_alternative" if fresh else "continuity_reuse"
        entry = {"primitives": selected["primitives"], "signature": selected["signature"]}
        self._by_observation[state.observation_id] = entry
        self._recent.append(entry)
        if len(self._recent) > self.capacity:
            self._recent.pop(0)
        return entry["primitives"], entry["signature"], {
            "selection": selection, "history_size": len(self._recent),
        }


def project_continuous_musical_state(projection, position_seconds):
    """Projecteer de actuele shadow-sectie of geef ``(None, reason)`` terug."""
    if not isinstance(projection, dict):
        return None, "projection_unavailable"
    if projection.get("track_match") != "exact" or projection.get("availability") != "available_current":
        return None, "track_not_current"
    if projection.get("projection_status") not in {"in_segment", "in_final_segment"}:
        return None, "position_not_current"
    position = _number(position_seconds)
    if position is None or position < 0:
        return None, "position_invalid"
    shadow = projection.get("shadow_analysis")
    if not isinstance(shadow, dict) or shadow.get("model") != "SectionCharacterProfileShadow":
        return None, "continuous_state_unavailable"
    sections = shadow.get("section_characters")
    if not isinstance(sections, list) or not sections:
        return None, "continuous_state_unavailable"
    current = None
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        start, end = _number(section.get("start_seconds")), _number(section.get("end_seconds"))
        if start is None or end is None:
            continue
        final_end = index == len(sections) - 1 and position == end
        if start <= position < end or final_end:
            current = section
            break
    if current is None:
        return None, "continuous_section_not_current"
    start, end = _number(current.get("start_seconds")), _number(current.get("end_seconds"))
    energy = _number(current.get("relative_energy"))
    if start is None or end is None or energy is None:
        return None, "continuous_state_essential_missing"
    raw_rise = _number(current.get("energy_rise"))
    # energy_rise is bestaande signed evidence met een open bereik. tanh houdt
    # teken en ordening intact en maakt de compositorinput veilig begrensd.
    trajectory = math.tanh(raw_rise) if raw_rise is not None else None
    try:
        return ContinuousMusicalState(
            observation_id=current.get("observation_id"),
            section_start_seconds=start,
            section_end_seconds=end,
            section_progress=max(0.0, min(1.0, (position - start) / (end - start))),
            relative_energy=energy,
            energy_trajectory=trajectory,
            recurrence_strength=current.get("recurrence_strength"),
            family_salience=current.get("family_salience"),
        ), "current"
    except (TypeError, ValueError):
        return None, "continuous_state_invalid"


def compose_dynamic_preview(base_show, continuous_state, rme_context=None, event_envelope=None,
                            composition_history=None, lifecycle_context=None, live_intensity=None):
    """Composeer de continuous backbone met een optionele RME-modifier.

    ``None`` betekent echte baseline-fallback. Afwezigheid van een actuele RME
    is daar uitdrukkelijk geen reden voor.
    """
    if not isinstance(base_show, dict) or not isinstance(continuous_state, ContinuousMusicalState):
        return None
    if base_show.get("override_active"):
        return None
    if rme_context is not None and (
        not isinstance(rme_context, dict) or rme_context.get("mode") != DYNAMIC_COMPOSER_MODE
    ):
        return None
    if event_envelope is not None and not isinstance(event_envelope, MusicalEventEnvelope):
        return None

    groups, primitives, signature, variation = _continuous_composition(
        continuous_state, composition_history, lifecycle_context
    )
    event_type = None
    progress = None
    envelope_payload = None
    # Een point-envelope neemt tijdelijk de intervalmodifier over. Daarmee wordt
    # een BUILD + RELEASE/DROP-boundary niet dubbel opgeteld; de continuous
    # musical state blijft in alle gevallen de onderliggende backbone.
    if event_envelope is not None:
        event_type = event_envelope.event_type
        progress = event_envelope.progress
        envelope_payload = event_envelope.as_dict()
        groups, primitives = _event_envelope_modulation(groups, primitives, event_envelope)
    else:
        event = rme_context.get("current_rme") if isinstance(rme_context, dict) and rme_context.get("valid") is True else None
        if isinstance(event, dict) and event.get("type") in INTERVAL_EVENT_TYPES:
            event_type = event["type"]
            progress = _unit(rme_context.get("rme_progress"), 0.0)
            groups, primitives = _event_modulation(groups, primitives, event_type, progress)

    groups = _live_intensity_modulation(groups, live_intensity)

    return {
        "continuous_musical_state": asdict(continuous_state),
        "event_type": event_type,
        "progress": progress,
        "rme_modifier": event_type.lower() if event_type else "none",
        "event_envelope": envelope_payload,
        "fixture_group_intents": {name: asdict(intent) for name, intent in groups.items()},
        "selected_primitives": primitives,
        "composition_signature": signature.as_dict(),
        "variation": variation,
        "changed_dimensions": _changed_dimensions(event_type),
        "live_intensity": dict(live_intensity or {}),
    }


def _stable_index(state, namespace, length):
    payload = f"{state.observation_id}|{namespace}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") % length


def _stable_unit(state, namespace, offset=0):
    payload = f"{state.observation_id}|{namespace}|{offset}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") / 0xFFFFFFFF


def _continuous_composition(state, composition_history=None, lifecycle_context=None):
    energy = state.relative_energy
    trajectory = state.energy_trajectory if state.energy_trajectory is not None else 0.0
    recurrence = state.recurrence_strength if state.recurrence_strength is not None else 0.0
    salience = state.family_salience if state.family_salience is not None else 0.0
    lift = max(0.0, trajectory)
    fall = max(0.0, -trajectory)
    moving = FixtureGroupIntent(
        .30 + .52 * energy + .06 * recurrence,
        .20 + .66 * energy + .08 * lift - .06 * fall,
        .16 + .52 * energy + .10 * abs(trajectory) + .05 * recurrence,
        .15 + .50 * energy + .12 * lift,
        .08 + .40 * energy + .06 * state.section_progress,
        "base", .10 + .38 * energy + .08 * recurrence,
        .06 + .28 * energy + .10 * salience,
    )
    par = FixtureGroupIntent(
        .36 + .50 * energy + .05 * salience,
        .18 + .68 * energy + .06 * lift - .05 * fall,
        0, 0, .10 + .38 * energy + .05 * state.section_progress,
        "base", .12 + .40 * energy + .08 * recurrence,
        .08 + .32 * energy + .10 * salience,
    )
    wash_intent = FixtureGroupIntent(
        .34 + .42 * energy + .06 * recurrence,
        .16 + .62 * energy + .04 * lift - .04 * fall,
        0, 0, .06 + .28 * energy + .04 * state.section_progress,
        "base", .08 + .24 * energy,
        .05 + .24 * energy + .08 * salience,
    )
    static = FixtureGroupIntent(.28 + .44 * energy, .18 + .62 * energy, 0, 0, 0, "base", .08 + .24 * energy, .04 + .20 * energy)

    if energy < .34:
        motions = ("break_soft_blue_center", "break_slow_pulse_circle")
        palettes = ("deep_blue_white", "cobalt_amber")
        pulses = ("breathe", "soft_pulse")
        washes = ("center_glow_blue", "blue_white_split")
    elif energy < .68:
        motions = ("sweep_narrow", "sweep_mid", "sweep_arc")
        palettes = ("cobalt_amber", "amber_teal", "rose_mint")
        pulses = ("soft_pulse", "breathe")
        washes = ("blue_white_split", "center_glow_blue")
    else:
        motions = ("sweep_mid", "sweep_wide", "fast_audience_circle")
        palettes = ("amber_teal", "teal_orange", "magenta_cyan")
        pulses = ("soft_pulse", "strong_pulse")
        washes = ("blue_white_split", "center_out_build")
    candidates = []
    relationships = ("analogous", "complementary", "split_complementary", "monochromatic")
    for order in range(4):
        motion = motions[(_stable_index(state, "motion", len(motions)) + order) % len(motions)]
        palette = palettes[(_stable_index(state, "palette", len(palettes)) + order) % len(palettes)]
        pulse = pulses[(_stable_index(state, "pulse", len(pulses)) + order) % len(pulses)]
        wash_cue = washes[(_stable_index(state, "wash", len(washes)) + order) % len(washes)]
        motion_parameters = {
            "range_scale": round(.72 + .28 * _stable_unit(state, "motion-range", order), 3),
            "speed_scale": round(.82 + .34 * _stable_unit(state, "motion-speed", order), 3),
            "phase_offset": round(-.34 + .68 * _stable_unit(state, "motion-phase", order), 3),
            "phase_spread": round(.12 + .42 * _stable_unit(state, "motion-spread", order), 3),
            "horizontal_center_offset": round(-12 + 24 * _stable_unit(state, "motion-horizontal", order), 2),
            "vertical_center_offset": round(-9 + 18 * _stable_unit(state, "motion-vertical", order), 2),
        }
        palette_parameters = {
            "relationship": relationships[(_stable_index(state, "palette-relation", len(relationships)) + order) % len(relationships)],
            "balance": round(.32 + .36 * _stable_unit(state, "palette-balance", order), 3),
            "phase_offset": int(_stable_unit(state, "palette-phase", order) * 3),
        }
        pulse_parameters = {
            "amount": round(.42 + .46 * _stable_unit(state, "pulse-amount", order), 3),
            "participation": "alternating" if _stable_unit(state, "pulse-participation", order) > .58 else "all",
        }
        wash_parameters = {"phase_offset": int(_stable_unit(state, "wash-phase", order) * 3)}
        primitives = {
            "moving": {"movement_pattern": motion, "pulse": pulse, "palette": palette,
                       "motion_parameters": motion_parameters, "palette_parameters": palette_parameters,
                       "pulse_parameters": pulse_parameters},
            "par": {"pulse": pulse, "palette": palette, "palette_parameters": palette_parameters,
                    "pulse_parameters": pulse_parameters},
            "wash": {"palette": palette, "wash_cue": wash_cue, "palette_parameters": palette_parameters,
                     "wash_parameters": wash_parameters},
        }
        signature = CompositionSignature(
            motion, tuple(sorted(motion_parameters.items())),
            palette, palette_parameters["relationship"], pulse, wash_cue,
            pulse_parameters["participation"],
        )
        candidates.append({"order": order, "primitives": primitives, "signature": signature})
    if isinstance(composition_history, CompositionHistory):
        primitives, signature, variation = composition_history.select(state, candidates, lifecycle_context)
    else:
        selected = candidates[0]
        primitives, signature = selected["primitives"], selected["signature"]
        variation = {"selection": "new", "history_size": 0}
    return {"moving": moving, "par": par, "wash": wash_intent, "static": static}, primitives, signature, variation


def _adjust(intent, *, activity=0, intensity=0, movement=0, speed=0, color=0, pulse=0, accent=0, palette=None):
    return replace(
        intent,
        activity=intent.activity + activity,
        intensity=intent.intensity + intensity,
        movement_amount=intent.movement_amount + movement,
        movement_speed=intent.movement_speed + speed,
        color_change_rate=intent.color_change_rate + color,
        palette_role=palette or intent.palette_role,
        pulse_amount=intent.pulse_amount + pulse,
        accent_strength=intent.accent_strength + accent,
    )


def _live_intensity_modulation(groups, live_intensity):
    """Apply a small continuous correction without changing RME semantics."""
    if not isinstance(live_intensity, dict) or not live_intensity.get("source_valid"):
        return groups
    modifier = _number(live_intensity.get("live_modifier"))
    if modifier is None:
        return groups
    modifier = max(-0.06, min(0.06, modifier))
    adjusted = dict(groups)
    for name, intent in adjusted.items():
        role_scale = 1.0 if name in {"moving", "par"} else 0.65
        adjusted[name] = _adjust(
            intent,
            activity=modifier * 0.24 * role_scale,
            intensity=modifier * 0.55,
            movement=modifier * (0.30 if name == "moving" else 0.0),
            speed=modifier * (0.30 if name == "moving" else 0.0),
            pulse=modifier * 0.40 * role_scale,
        )
    return adjusted


def _event_modulation(groups, base_primitives, event_type, progress):
    groups = dict(groups)
    primitives = {name: dict(value) for name, value in base_primitives.items()}
    if event_type == "BUILD":
        ramp = .35 + .65 * progress
        groups["moving"] = _adjust(groups["moving"], activity=.12*ramp, intensity=.22*ramp, movement=.24*ramp, speed=.34*ramp, color=.25*ramp, pulse=.24*ramp, accent=.30*ramp, palette="tension")
        groups["par"] = _adjust(groups["par"], activity=.14*ramp, intensity=.18*ramp, color=.22*ramp, pulse=.24*ramp, accent=.24*ramp, palette="tension")
        groups["wash"] = _adjust(groups["wash"], activity=.12*ramp, intensity=.14*ramp, color=.16*ramp, pulse=.12*ramp, accent=.18*ramp, palette="tension")
        primitives = {
            "moving": {"movement_pattern": "build_fastening_circle", "pulse": "lift", "palette": "amber_teal"},
            "par": {"pulse": "lift", "palette": "amber_teal"},
            "wash": {"palette": "amber_teal", "wash_cue": "center_out_build"},
        }
    elif event_type == "BREAK":
        groups["moving"] = _adjust(groups["moving"], activity=-.24, intensity=-.28, movement=-.34, speed=-.30, color=-.22, pulse=-.22, accent=-.20, palette="space")
        groups["par"] = _adjust(groups["par"], activity=-.20, intensity=-.24, color=-.20, pulse=-.22, accent=-.18, palette="space")
        groups["wash"] = _adjust(groups["wash"], activity=-.10, intensity=-.18, color=-.14, pulse=-.14, accent=-.12, palette="space")
        primitives = {
            "moving": {"movement_pattern": "break_soft_blue_center", "pulse": "breathe", "palette": "deep_blue_white"},
            "par": {"pulse": "breathe", "palette": "deep_blue_white"},
            "wash": {"palette": "deep_blue_white", "wash_cue": "center_glow_blue"},
        }
    return groups, primitives


def _event_envelope_modulation(groups, base_primitives, envelope):
    """Leg één bounded point-eventaccent boven de bestaande backbone."""
    groups = dict(groups)
    strength = envelope.strength
    if envelope.event_type == "ARRIVAL":
        # Duidelijker dan de normale release, maar aantoonbaar onder DROP:
        # geen strobe-route, geen nieuwe primitives en dezelfde 2-bar settle.
        groups["moving"] = _adjust(groups["moving"], activity=.20*strength, intensity=.18*strength, movement=.18*strength, speed=.16*strength, color=.26*strength, pulse=.28*strength, accent=.36*strength, palette="release")
        groups["par"] = _adjust(groups["par"], activity=.22*strength, intensity=.20*strength, color=.28*strength, pulse=.30*strength, accent=.38*strength, palette="release")
        groups["wash"] = _adjust(groups["wash"], activity=.14*strength, intensity=.13*strength, color=.20*strength, pulse=.14*strength, accent=.22*strength, palette="release")
        primitives = {
            "moving": {"movement_pattern": "sweep_mid", "pulse": "soft_pulse", "palette": "cobalt_amber"},
            "par": {"pulse": "soft_pulse", "palette": "cobalt_amber"},
            "wash": {"palette": "cobalt_amber", "wash_cue": "blue_white_split"},
        }
    elif envelope.event_type == "DROP":
        groups["moving"] = _adjust(groups["moving"], activity=.28*strength, intensity=.28*strength, movement=.26*strength, speed=.34*strength, color=.28*strength, pulse=.36*strength, accent=.52*strength, palette="impact")
        groups["par"] = _adjust(groups["par"], activity=.30*strength, intensity=.30*strength, color=.28*strength, pulse=.40*strength, accent=.56*strength, palette="impact")
        groups["wash"] = _adjust(groups["wash"], activity=.22*strength, intensity=.22*strength, color=.20*strength, pulse=.24*strength, accent=.40*strength, palette="impact")
        primitives = {
            "moving": {"movement_pattern": "drop_fast_circle_white", "pulse": "hit", "palette": "ice_fire"},
            "par": {"pulse": "hit", "palette": "ice_fire"},
            "wash": {"palette": "ice_fire", "wash_cue": "white_pixel_hits"},
        }
    elif envelope.event_type == "RELEASE":
        groups["moving"] = _adjust(groups["moving"], activity=.10*strength, intensity=.10*strength, movement=.12*strength, speed=.12*strength, color=.10*strength, pulse=.12*strength, accent=.16*strength, palette="release")
        groups["par"] = _adjust(groups["par"], activity=.10*strength, intensity=.10*strength, color=.08*strength, pulse=.10*strength, accent=.14*strength, palette="release")
        groups["wash"] = _adjust(groups["wash"], activity=.08*strength, intensity=.08*strength, color=.06*strength, pulse=.08*strength, accent=.10*strength, palette="release")
        primitives = {
            "moving": {"movement_pattern": "sweep_mid", "pulse": "soft_pulse", "palette": "cobalt_amber"},
            "par": {"pulse": "soft_pulse", "palette": "cobalt_amber"},
            "wash": {"palette": "cobalt_amber", "wash_cue": "blue_white_split"},
        }
    elif envelope.event_type == "TRANSITION":
        groups["moving"] = _adjust(groups["moving"], activity=.12*strength, intensity=.08*strength, movement=.16*strength, speed=.12*strength, color=.18*strength, pulse=.10*strength, accent=.14*strength, palette="release")
        groups["par"] = _adjust(groups["par"], activity=.12*strength, intensity=.08*strength, color=.18*strength, pulse=.10*strength, accent=.14*strength, palette="release")
        groups["wash"] = _adjust(groups["wash"], activity=.10*strength, intensity=.08*strength, color=.16*strength, pulse=.08*strength, accent=.12*strength, palette="release")
        primitives = {
            "moving": {"movement_pattern": "sweep_arc", "pulse": "soft_pulse", "palette": "teal_orange"},
            "par": {"pulse": "soft_pulse", "palette": "teal_orange"},
            "wash": {"palette": "teal_orange", "wash_cue": "blue_white_split"},
        }
    else:  # Future-ready FILL: accent only; no direct strobe semantics or DMX path.
        groups["moving"] = _adjust(groups["moving"], activity=.16*strength, intensity=.12*strength, movement=.12*strength, speed=.18*strength, color=.20*strength, pulse=.28*strength, accent=.30*strength, palette="tension")
        groups["par"] = _adjust(groups["par"], activity=.18*strength, intensity=.14*strength, color=.20*strength, pulse=.30*strength, accent=.32*strength, palette="tension")
        groups["wash"] = _adjust(groups["wash"], activity=.10*strength, intensity=.08*strength, color=.12*strength, pulse=.12*strength, accent=.14*strength, palette="tension")
        primitives = {
            "moving": {"movement_pattern": "sweep_mid", "pulse": "strong_pulse", "palette": "amber_teal"},
            "par": {"pulse": "strong_pulse", "palette": "amber_teal"},
            "wash": {"palette": "amber_teal", "wash_cue": "blue_white_split"},
        }
    return groups, primitives


def _changed_dimensions(event_type):
    continuous = ("fixture_activity", "intensity", "movement", "movement_speed", "color_change_rate", "palette", "pulse")
    if event_type == "DROP":
        return continuous + ("accent", "event_envelope", "rme_modifier")
    if event_type in {"ARRIVAL", "RELEASE", "TRANSITION", "FILL"}:
        return continuous + ("event_envelope", "rme_modifier")
    if event_type in INTERVAL_EVENT_TYPES:
        return continuous + ("rme_modifier",)
    return continuous
