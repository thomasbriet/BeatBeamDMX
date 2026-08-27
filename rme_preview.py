"""Begrensde, preview-only interpretatie van bestaande Rich Musical Events.

Deze module kent geen fixtures, DMX of runtime-state.  Zij kiest uitsluitend
actuele RME-context en projecteert die op al bestaande Auto Show-parameters.
"""

from __future__ import annotations

import math


RME_PREVIEW_MODES = frozenset({"BASELINE", "RME_ENHANCED", "DYNAMIC_COMPOSER"})
INTERVAL_TYPES = frozenset({"BUILD", "BREAK"})
POINT_TYPES = frozenset({"RELEASE", "DROP", "ARRIVAL", "TRANSITION"})
POINT_CONTEXT_SECONDS = 0.75


def normalize_rme_preview_mode(value):
    mode = str(value or "").strip().upper()
    return mode if mode in RME_PREVIEW_MODES else "BASELINE"


def preview_rme_context(projection, position_seconds, mode="BASELINE"):
    """Selecteer exact de actuele RME-context of faal gesloten naar baseline."""
    selected_mode = normalize_rme_preview_mode(mode)
    result = {
        "mode": selected_mode,
        "valid": False,
        "current_rme": None,
        "next_rme": None,
        "rme_progress": None,
        "rme_modifier": "baseline",
        "reason": "mode_baseline" if selected_mode == "BASELINE" else "rme_unavailable",
    }
    if selected_mode == "BASELINE" or not isinstance(projection, dict):
        return result
    if projection.get("track_match") != "exact" or projection.get("availability") != "available_current":
        result["reason"] = "track_not_current"
        return result
    if projection.get("projection_status") not in {"in_segment", "in_final_segment"}:
        result["reason"] = "position_not_current"
        return result
    if isinstance(position_seconds, bool) or not isinstance(position_seconds, (int, float)) \
            or not math.isfinite(float(position_seconds)) or float(position_seconds) < 0:
        result["reason"] = "position_invalid"
        return result
    handoff = projection.get("rich_musical_events")
    if not isinstance(handoff, dict) or handoff.get("mode") != "SHADOW_ONLY" \
            or handoff.get("availability") != "available":
        return result
    events = handoff.get("events")
    if not isinstance(events, list):
        return result
    position = float(position_seconds)
    relevant = [event for event in events if isinstance(event, dict) and event.get("type") in INTERVAL_TYPES | POINT_TYPES]
    active_intervals = [event for event in relevant
                        if event.get("temporal_kind") == "INTERVAL"
                        and _number(event.get("start_seconds")) is not None
                        and _number(event.get("end_seconds")) is not None
                        and float(event["start_seconds"]) <= position < float(event["end_seconds"])]
    active_points = [event for event in relevant
                     if event.get("temporal_kind") != "INTERVAL"
                     and _number(event.get("start_seconds")) is not None
                     and float(event["start_seconds"]) <= position < float(event["start_seconds"]) + POINT_CONTEXT_SECONDS]
    current = _select_current(active_intervals, active_points)
    upcoming = sorted((event for event in relevant if _number(event.get("start_seconds")) is not None
                       and float(event["start_seconds"]) > position), key=_event_sort_key)
    result["valid"] = True
    result["reason"] = "current" if current else "no_current_relevant_event"
    result["current_rme"] = _event_payload(current) if current else None
    result["next_rme"] = _event_payload(upcoming[0]) if upcoming else None
    if current and current.get("temporal_kind") == "INTERVAL":
        start, end = float(current["start_seconds"]), float(current["end_seconds"])
        result["rme_progress"] = max(0.0, min(1.0, (position - start) / (end - start)))
    result["rme_modifier"] = _modifier_name(current)
    return result


def apply_rme_preview_modifier(base_auto_show, context):
    """Geef een nieuwe preview Show-state; de basis wordt nooit gemuteerd."""
    enhanced = dict(base_auto_show or {})
    enhanced["rme_preview"] = dict(context or {})
    if not isinstance(context, dict) or context.get("mode") != "RME_ENHANCED" \
            or context.get("valid") is not True or not isinstance(context.get("current_rme"), dict):
        return enhanced
    # Handmatige live-cues hebben altijd voorrang.  De Preview Map blijft dan
    # precies de bestaande handmatige show-intentie tonen.
    if enhanced.get("override_active"):
        enhanced["rme_preview"]["rme_modifier"] = "manual_override_baseline"
        return enhanced
    event_type = context["current_rme"].get("type")
    progress = context.get("rme_progress")
    progress = 0.0 if not isinstance(progress, (int, float)) else max(0.0, min(1.0, float(progress)))
    energy_delta = movement_delta = 0.0
    if event_type == "BUILD":
        energy_delta, movement_delta = 0.08 + 0.14 * progress, 0.05 + 0.16 * progress
    elif event_type == "BREAK":
        energy_delta, movement_delta = -0.18, -0.26
        enhanced["rhythm_mode"] = "soft_pulse"
        enhanced["beat_pulse"] = False
    elif event_type == "RELEASE":
        energy_delta, movement_delta = 0.10, 0.06
    elif event_type == "DROP":
        energy_delta, movement_delta = 0.15, 0.10
        enhanced["rhythm_mode"] = "strong_pulse"
        enhanced["beat_pulse"] = True
    elif event_type == "ARRIVAL":
        energy_delta, movement_delta = 0.04, 0.03
    elif event_type == "TRANSITION":
        movement_delta = 0.09
    else:
        return enhanced
    enhanced["energy"] = _unit(enhanced.get("energy"), energy_delta)
    enhanced["movement"] = _unit(enhanced.get("movement"), movement_delta)
    # Sommige bestaande motion-profielen leveren zelf een vaste dimmer.  Daar
    # normaliseert de fixture-interpreter bewust tegen, zodat een wijziging van
    # alleen `energy` daar visueel kan wegvallen.  Deze begrensde factor is nog
    # steeds show-intentie (geen fixture- of DMX-kanaal) en wordt uitsluitend in
    # de Preview Map na die bestaande normalisatie toegepast.
    enhanced["preview_intensity_multiplier"] = max(
        0.78, min(1.18, 1.0 + energy_delta * 0.70)
    )
    # Strobe, manual overrides, fixture constraints and DMX-output blijven de
    # bestaande downstream-routes gebruiken en worden hier bewust niet gewijzigd.
    enhanced["rme_preview"]["rme_modifier"] = _modifier_name(context["current_rme"])
    return enhanced


def apply_dynamic_composer_preview(base_auto_show, context, composition):
    """Projecteer pure compositie uitsluitend op de bestaande preview-showstate."""
    dynamic = dict(base_auto_show or {})
    dynamic["rme_preview"] = dict(context or {})
    if not isinstance(composition, dict):
        dynamic["preview_source"] = "baseline"
        dynamic["dynamic_composer_active"] = False
        dynamic["fallback_to_baseline"] = True
        dynamic["dynamic_composition_applied"] = False
        dynamic["baseline_scene_reused"] = True
        dynamic["baseline_scene_components_reused"] = [
            "look", "color_profile", "motion", "pulse", "wash",
        ]
        return dynamic
    dynamic["dynamic_composer"] = dict(composition)
    dynamic["continuous_musical_state"] = dict(
        composition.get("continuous_musical_state") or {}
    )
    dynamic["event_envelope"] = dict(composition.get("event_envelope") or {})
    dynamic["fixture_group_intents"] = dict(composition.get("fixture_group_intents") or {})
    dynamic["selected_primitives"] = dict(composition.get("selected_primitives") or {})
    dynamic["composition_signature"] = dict(composition.get("composition_signature") or {})
    dynamic["variation"] = dict(composition.get("variation") or {})
    dynamic["changed_dimensions"] = list(composition.get("changed_dimensions") or ())
    dynamic["preview_source"] = "dynamic_composer"
    dynamic["dynamic_composer_active"] = True
    dynamic["fallback_to_baseline"] = False
    dynamic["dynamic_composition_applied"] = True
    dynamic["baseline_scene_reused"] = False
    dynamic["baseline_scene_components_reused"] = []
    moving = dynamic["fixture_group_intents"].get("moving") or {}
    moving_primitives = dynamic["selected_primitives"].get("moving") or {}
    # Deze velden worden nog steeds uitsluitend door de bestaande renderer
    # geïnterpreteerd; er worden geen kanaalwaarden of safetygrenzen gecreëerd.
    if isinstance(moving, dict):
        intensity = moving.get("intensity")
        intensity = max(0.0, min(1.0, float(intensity))) if _number(intensity) is not None else 0.0
        movement = moving.get("movement_amount")
        movement = max(0.0, min(1.0, float(movement))) if _number(movement) is not None else 0.0
        dynamic["energy"] = intensity
        dynamic["movement"] = movement
        dynamic["preview_intensity_multiplier"] = max(
            0.78, min(1.18, 0.88 + intensity * 0.24)
        )
    motion_name = moving_primitives.get("movement_pattern") if isinstance(moving_primitives, dict) else None
    if isinstance(motion_name, str) and motion_name:
        dynamic["motion_name"] = motion_name
    dynamic["preview_cue"] = _dynamic_preview_cue(context, composition)
    dynamic["rme_preview"]["rme_modifier"] = composition.get("rme_modifier", "none")
    return dynamic


def _dynamic_preview_cue(context, composition):
    event = str((composition or {}).get("event_type") or "None").title()
    progress = (composition or {}).get("progress")
    modifier = f"{event} {int(round(float(progress) * 100))}%" \
        if _number(progress) is not None else event
    envelope = (composition or {}).get("event_envelope") or {}
    envelope_text = ""
    if isinstance(envelope, dict) and envelope.get("active"):
        phase = str(envelope.get("phase") or "").title()
        beats = _number(envelope.get("beats_since_event"))
        total = _number(envelope.get("total_beats"))
        if beats is not None and total is not None:
            envelope_text = f" • Envelope {phase} {beats / 4.0:.2g}/{total / 4.0:.2g} bars"
    primitives = (composition or {}).get("selected_primitives") or {}
    moving = primitives.get("moving") or {}
    par = primitives.get("par") or {}
    wash = primitives.get("wash") or {}
    signature = (composition or {}).get("composition_signature") or {}
    variation = (composition or {}).get("variation") or {}
    variation_text = ""
    if isinstance(signature, dict):
        variation_text = (
            f" • Variation {variation.get('selection', 'new')}: "
            f"{variation.get('repeat_classification', 'NEW_MATERIAL')} / "
            f"{signature.get('palette_relationship', 'complementary')}"
        )
    return (
        f"Dynamic Composer • RME {modifier}{envelope_text}{variation_text} • "
        f"Moving {moving.get('movement_pattern', 'neutral')} / {moving.get('dimmer_motif', 'static_full')} • "
        f"PAR {par.get('palette', 'neutral')} / {par.get('color_animation', 'all_same')} • "
        f"Wash {wash.get('wash_cue', wash.get('palette', 'neutral'))} / "
        f"{moving.get('fixture_partition', 'all_groups')}"
    )


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) else None


def _select_current(intervals, points):
    if intervals:
        return sorted(intervals, key=lambda event: (event.get("type") != "BUILD", _event_sort_key(event)))[0]
    if points:
        return sorted(points, key=lambda event: (event.get("type") != "DROP", _event_sort_key(event)))[0]
    return None


def _event_sort_key(event):
    return (float(event["start_seconds"]), str(event.get("type") or ""), str(event.get("origin_observation_id") or ""))


def _event_payload(event):
    if not event:
        return None
    result = {key: event.get(key) for key in ("type", "temporal_kind", "start_seconds", "end_seconds", "start_bar", "end_bar") if key in event}
    return result


def _modifier_name(event):
    return "baseline" if not event else str(event.get("type") or "baseline").lower()


def _unit(value, delta):
    base = float(value) if _number(value) is not None else 0.0
    return max(0.0, min(1.0, base + delta))
