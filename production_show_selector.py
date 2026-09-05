"""Pure fail-closed source selection for the production show-state seam."""

from __future__ import annotations

import math
import os


BASELINE_ONLY = "BASELINE_ONLY"
DYNAMIC_COMPOSER_SHADOW = "DYNAMIC_COMPOSER_SHADOW"
DYNAMIC_COMPOSER_ENABLED = "DYNAMIC_COMPOSER_ENABLED"
PRODUCTION_SHOW_MODES = frozenset({
    BASELINE_ONLY, DYNAMIC_COMPOSER_SHADOW, DYNAMIC_COMPOSER_ENABLED,
})

GROUP_NAMES = frozenset({"moving", "par", "wash", "static"})
GROUP_NUMBERS = (
    "activity", "intensity", "movement_amount", "movement_speed",
    "color_change_rate", "pulse_amount", "accent_strength",
)
PALETTE_ROLES = frozenset({"base", "tension", "space", "impact", "release"})
LEGACY_KNOWN_MOTIONS = frozenset({
    "break_soft_blue_center", "break_slow_pulse_circle", "sweep_narrow", "sweep_mid",
    "sweep_arc", "sweep_wide", "fast_audience_circle", "build_fastening_circle",
    "fast_audience_sweep", "fast_audience_figure_8", "build_rising_sweep",
    "build_audience_wave", "build_narrow_to_wide_fan", "drop_fast_circle_white",
})
# Production V3 identities are renderer-owned recipes.  The selector only
# admits their stable public identifiers; keeping this explicit avoids an
# import cycle with beatbeam_app, which imports this fail-closed boundary.
FULL_SPHERE_V3_PRODUCTION_MOTIONS = frozenset({
    "full_sphere_explode", "floor_hold_explode", "rear_hold_split",
    "full_sphere_cannon", "floor_forward_cannon", "dome_sweep_3d",
    "floor_forward_sweep", "forward_rear_arc", "cross_3d",
    "volumetric_orbit", "volumetric_figure_8", "energy_scatter", "fan_3d",
})
KNOWN_MOTIONS = LEGACY_KNOWN_MOTIONS | FULL_SPHERE_V3_PRODUCTION_MOTIONS
KNOWN_PALETTES = frozenset({
    "deep_blue_white", "cobalt_amber", "amber_teal", "rose_mint", "teal_orange",
    "magenta_cyan", "ice_fire", "violet_lime", "ruby_lime", "purple_gold",
    "pink_blue", "blue_amber",
})
KNOWN_PULSES = frozenset({"breathe", "soft_pulse", "strong_pulse", "lift", "hit"})
KNOWN_WASHES = frozenset({
    "center_glow_blue", "blue_white_split", "center_out_build", "white_pixel_hits",
    "wash_chase_forward", "wash_chase_reverse", "wash_bounce", "wash_center_out",
    "wash_outside_in", "wash_alternating_halves", "wash_zone_alternate",
    "wash_wave_forward", "wash_wave_reverse", "wash_ripple", "wash_color_wipe",
    "wash_zone_hits", "wash_build_fill", "wash_drop_explosion", "wash_mirror_chase",
    "wash_opposing_wave", "wash_cannon", "wash_call_response", "wash_cross_ripple",
})
PALETTE_RELATIONSHIPS = frozenset({
    "analogous", "complementary", "split_complementary", "monochromatic",
    "mono", "adjacent_hue", "two_color_split", "complementary_bright",
    "triad_bright", "warm_pair", "cool_pair", "warm_cool_contrast",
})
FIXTURE_ROLE_PATTERNS = frozenset({"all", "alternating"})
DIMMER_MOTIFS = frozenset({
    "static_full", "static_reduced", "beat_pulse", "half_bar_gate", "bar_gate",
    "alternate_a_b", "alternate_left_right", "chase_forward", "chase_reverse",
    "out_to_in", "in_to_out", "wave_forward", "wave_reverse", "stair_up",
    "stair_down", "burst_all", "burst_alternate", "syncopated_pulse",
})
COLOR_ANIMATIONS = frozenset({
    "all_same", "group_split", "alternate", "chase_color", "swap_on_bar",
    "swap_on_2_bars", "event_accent", "return_palette_recall",
})
FIXTURE_PARTITIONS = frozenset({
    "all_groups", "moving_lead", "par_lead", "wash_foundation", "moving_par",
    "par_wash", "alternating_groups", "call_response",
})
COMPLEXITY_LEVELS = frozenset({"low", "medium", "high"})
MOTION_PARAMETER_RANGES = {
    "range_scale": (.72, 1.0),
    "speed_scale": (.82, 1.16),
    "phase_offset": (-.34, .34),
    "phase_spread": (.12, .54),
    "horizontal_center_offset": (-12.0, 12.0),
    "vertical_center_offset": (-9.0, 9.0),
}
COMPOSITION_SIGNATURE_FIELDS = frozenset({
    "motion_family", "motion_parameters", "palette_family", "palette_relationship",
    "pulse", "wash", "fixture_roles", "dimmer_motif", "color_animation",
    "fixture_partition", "complexity",
})


def normalize_production_show_mode(value):
    mode = str(value or "").strip().upper()
    return mode if mode in PRODUCTION_SHOW_MODES else BASELINE_ONLY


def select_production_show_source(
    mode, baseline, candidate, projection, playback, composer_generation,
    *, renderer_healthy=True, safety_context=None,
):
    """Select one same-frame show state; never retains a previous candidate."""
    selected_mode = normalize_production_show_mode(mode)
    baseline = baseline if isinstance(baseline, dict) else {}
    candidate_available = isinstance(candidate, dict)
    playback = playback if isinstance(playback, dict) else {}
    projection = projection if isinstance(projection, dict) else {}
    safety_context = safety_context if isinstance(safety_context, dict) else {}
    playback_generation = _positive_int(playback.get("_playback_generation"))
    active_track = projection.get("active_track") if isinstance(projection.get("active_track"), dict) else {}
    handoff_generation = _positive_int(active_track.get("generation"))
    composer_generation = _positive_int(composer_generation)
    manual = _manual_override_active(baseline)
    reason = _eligibility_reason(
        baseline, candidate, projection, playback, playback_generation,
        handoff_generation, composer_generation, renderer_healthy, manual,
        safety_context,
    )
    eligible = reason is None
    active = selected_mode == DYNAMIC_COMPOSER_ENABLED and eligible
    if selected_mode == BASELINE_ONLY:
        fallback_reason = "mode_baseline"
    elif selected_mode == DYNAMIC_COMPOSER_SHADOW:
        fallback_reason = "mode_shadow" if eligible else reason
    else:
        fallback_reason = None if active else reason
    selected = candidate if active else baseline
    composition = candidate.get("dynamic_composer") if isinstance(candidate, dict) else None
    context = candidate.get("rme_preview") if isinstance(candidate, dict) else None
    envelope = candidate.get("event_envelope") if isinstance(candidate, dict) else None
    live = baseline.get("live_intensity") if isinstance(baseline.get("live_intensity"), dict) else {}
    source = "dynamic_composer" if active else "existing_autoshow"
    decision = {
        "production_mode": selected_mode,
        "production_source": source,
        "production_show_mode": selected_mode,
        "production_show_source": source,
        "decision_generation": playback_generation,
        "composer_candidate_available": candidate_available,
        "candidate_available": candidate_available,
        "composer_eligible": eligible,
        "dynamic_composer_eligible": eligible,
        "composer_active": active,
        "dynamic_composer_active": active,
        "fallback_active": not active,
        "fallback_reason": fallback_reason,
        "handoff_effect_hold": False,
        "handoff_effect_hold_remaining_seconds": None,
        "manual_override_active": manual,
        "blackout_active": safety_context.get("blackout_active") is True,
        "continuous_state_valid": _valid_continuous_state(
            candidate.get("continuous_musical_state") if isinstance(candidate, dict) else None
        ),
        "track_match": projection.get("track_match"),
        "handoff_availability": projection.get("availability"),
        "playback_generation": playback_generation,
        "handoff_generation": handoff_generation,
        "composer_generation": composer_generation,
        "renderer_healthy": bool(renderer_healthy),
        "current_rme": context.get("current_rme") if isinstance(context, dict) else None,
        "event_envelope": dict(envelope) if isinstance(envelope, dict) else {},
        "analyzed_intensity": baseline.get("energy"),
        "live_intensity_valid": live.get("source_valid"),
        "live_intensity_source_valid": live.get("source_valid"),
        "live_intensity_fallback_reason": live.get("fallback_reason"),
        "effective_intensity": live.get("effective_intensity", baseline.get("energy")),
        "baseline_signature": _baseline_signature(baseline),
        "candidate_show_signature": _baseline_signature(candidate or {}),
        "candidate_signature": dict(composition.get("composition_signature") or {})
            if isinstance(composition, dict) else {},
    }
    decision["baseline_candidate_signature_equal"] = (
        decision["baseline_signature"] == decision["candidate_show_signature"]
    )
    return selected, decision


def validate_dynamic_composer_candidate(candidate):
    if not isinstance(candidate, dict) or candidate.get("dynamic_composer_active") is not True \
            or candidate.get("dynamic_composition_applied") is not True \
            or candidate.get("fallback_to_baseline") is not False:
        return False
    if not _valid_continuous_state(candidate.get("continuous_musical_state")):
        return False
    groups = candidate.get("fixture_group_intents")
    if not isinstance(groups, dict) or set(groups) != GROUP_NAMES:
        return False
    for name, intent in groups.items():
        if not isinstance(intent, dict) or any(not _unit(intent.get(field)) for field in GROUP_NUMBERS) \
                or intent.get("palette_role") not in PALETTE_ROLES:
            return False
        if name != "moving" and any(float(intent.get(field, 0)) != 0.0
                for field in ("movement_amount", "movement_speed")):
            return False
    primitives = candidate.get("selected_primitives")
    if not isinstance(primitives, dict) or not set(primitives).issubset(GROUP_NAMES) \
            or not {"moving", "par", "wash"}.issubset(primitives):
        return False
    for name, primitive in primitives.items():
        if not isinstance(primitive, dict) or not _primitive_valid(name, primitive):
            return False
    signature = candidate.get("composition_signature")
    signature_motion_parameters = None
    if isinstance(signature, dict) and isinstance(signature.get("motion_parameters"), (list, tuple)):
        try:
            signature_motion_parameters = dict(signature["motion_parameters"])
        except (TypeError, ValueError):
            signature_motion_parameters = None
    return isinstance(signature, dict) \
        and set(signature) == COMPOSITION_SIGNATURE_FIELDS \
        and signature.get("motion_family") in KNOWN_MOTIONS \
        and signature.get("palette_family") in KNOWN_PALETTES \
        and signature.get("palette_relationship") in PALETTE_RELATIONSHIPS \
        and signature.get("pulse") in KNOWN_PULSES \
        and signature.get("wash") in KNOWN_WASHES \
        and signature.get("fixture_roles") in FIXTURE_ROLE_PATTERNS \
        and signature.get("dimmer_motif") in DIMMER_MOTIFS \
        and signature.get("color_animation") in COLOR_ANIMATIONS \
        and signature.get("fixture_partition") in FIXTURE_PARTITIONS \
        and signature.get("complexity") in COMPLEXITY_LEVELS \
        and _bounded_mapping(signature_motion_parameters, MOTION_PARAMETER_RANGES) \
        and _finite_tree(signature)


def _eligibility_reason(baseline, candidate, projection, playback, playback_generation,
                        handoff_generation, composer_generation, renderer_healthy, manual,
                        safety_context):
    if safety_context.get("blackout_active") is True:
        return "blackout_active"
    if manual:
        return "manual_override"
    if not renderer_healthy:
        return "renderer_unhealthy"
    if playback.get("_active_playback_source") != "virtualdj":
        return "lifecycle_ambiguous"
    if playback.get("stale") is True:
        return "transport_stale"
    if playback.get("playing") is False:
        return "transport_not_advancing"
    playback_state = playback.get("playback_state")
    if isinstance(playback_state, dict):
        if playback_state.get("availability") != "available":
            return "lifecycle_ambiguous"
        if playback_state.get("transport_state") != "advancing":
            return "transport_not_advancing"
    if not isinstance(candidate, dict):
        return "candidate_missing"
    if projection.get("availability") != "available_current" \
            or projection.get("projection_status") not in {"in_segment", "in_final_segment"}:
        return "handoff_not_current"
    if projection.get("track_match") != "exact":
        return "track_mismatch"
    playback_path = _canonical(playback.get("track_path"))
    projection_path = _canonical(projection.get("canonical_track_path"))
    active_track = projection.get("active_track") if isinstance(projection.get("active_track"), dict) else {}
    active_path = _canonical(active_track.get("canonical_path"))
    if not playback_path or projection_path != playback_path or active_path != playback_path:
        return "track_mismatch"
    if active_track.get("status") != "ready":
        return "handoff_not_current"
    playback_deck = _playback_deck(playback)
    active_deck = _positive_int(active_track.get("deck"))
    if (playback_deck is None) != (active_deck is None) \
            or playback_deck is not None and playback_deck != active_deck:
        return "deck_mismatch"
    # `active_track.generation` belongs to the bridge/prewarm handoff lifecycle,
    # whereas `_playback_generation` belongs to BeatBeam's transport lifecycle.
    # Both are required freshness witnesses, but they intentionally use separate
    # counters and therefore must never be compared for numeric equality.
    # Track path, deck, ready status and availability above establish that both
    # witnesses describe the same authoritative playback.
    if playback_generation is None or handoff_generation is None \
            or composer_generation != playback_generation:
        return "generation_mismatch"
    candidate_context = candidate.get("rme_preview") if isinstance(candidate, dict) else None
    if isinstance(candidate_context, dict) \
            and candidate_context.get("continuous_state_reason") == "composer_exception":
        return "composer_exception"
    if not _valid_continuous_state(candidate.get("continuous_musical_state")
                                   if isinstance(candidate, dict) else None):
        return "continuous_state_missing"
    if not validate_dynamic_composer_candidate(candidate):
        return "composition_invalid"
    return None


def _manual_override_active(show):
    return bool(
        show.get("override_active") or show.get("one_shot_active")
        or str(show.get("override_phrase") or "none").lower() != "none"
        or str(show.get("override_color") or "none").lower() != "none"
        or str(show.get("override_energy") or "none").lower() != "none"
        or any(show.get(name) for name in (
            "override_manual_strobe", "override_audience_sweep", "override_all_on",
            "override_par_chase", "override_par_snake",
        ))
    )


def _valid_continuous_state(value):
    if not isinstance(value, dict) or not str(value.get("observation_id") or "").strip():
        return False
    start, end = _number(value.get("section_start_seconds")), _number(value.get("section_end_seconds"))
    return start is not None and start >= 0 and end is not None and end > start \
        and _unit(value.get("section_progress")) and _unit(value.get("relative_energy"))


def _primitive_valid(name, primitive):
    allowed = {
        "moving": {"movement_pattern", "pulse", "palette", "motion_parameters",
                   "palette_parameters", "pulse_parameters", "dimmer_motif",
                   "color_animation", "fixture_partition", "complexity"},
        "par": {"pulse", "palette", "palette_parameters", "pulse_parameters",
                "dimmer_motif", "color_animation", "fixture_partition", "complexity"},
        "wash": {"palette", "wash_cue", "palette_parameters", "wash_parameters",
                 "dimmer_motif", "color_animation", "fixture_partition", "complexity"},
        "static": {"palette", "palette_parameters", "pulse_parameters", "dimmer_motif",
                   "color_animation", "fixture_partition", "complexity"},
    }.get(name, set())
    if not set(primitive).issubset(allowed):
        return False
    checks = []
    if name == "moving":
        checks.append(primitive.get("movement_pattern") in KNOWN_MOTIONS)
    if "palette" in primitive:
        checks.append(primitive.get("palette") in KNOWN_PALETTES)
    if "pulse" in primitive:
        checks.append(primitive.get("pulse") in KNOWN_PULSES)
    if "wash_cue" in primitive:
        checks.append(primitive.get("wash_cue") in KNOWN_WASHES)
    if "motion_parameters" in primitive and not _bounded_mapping(
            primitive.get("motion_parameters"), MOTION_PARAMETER_RANGES):
        return False
    palette = primitive.get("palette_parameters")
    if palette is not None and (
        not isinstance(palette, dict)
        or set(palette) != {"relationship", "balance", "phase_offset"}
        or palette.get("relationship") not in PALETTE_RELATIONSHIPS
        or not _range(palette.get("balance"), .32, .68)
        or not _bounded_int(palette.get("phase_offset"), 0, 3)
    ):
        return False
    pulse = primitive.get("pulse_parameters")
    if pulse is not None and (
        not isinstance(pulse, dict)
        or set(pulse) != {"amount", "participation"}
        or not _range(pulse.get("amount"), .42, .88)
        or pulse.get("participation") not in FIXTURE_ROLE_PATTERNS
    ):
        return False
    wash = primitive.get("wash_parameters")
    if wash is not None and (
        not isinstance(wash, dict)
        or set(wash) != {"phase_offset"}
        or not _bounded_int(wash.get("phase_offset"), 0, 2)
    ):
        return False
    for field, allowed_values in (
        ("dimmer_motif", DIMMER_MOTIFS),
        ("color_animation", COLOR_ANIMATIONS),
        ("fixture_partition", FIXTURE_PARTITIONS),
        ("complexity", COMPLEXITY_LEVELS),
    ):
        if field in primitive and primitive.get(field) not in allowed_values:
            return False
    return bool(checks) and all(checks) and _finite_tree(primitive)


def _bounded_mapping(value, ranges):
    return isinstance(value, dict) and set(value) == set(ranges) and all(
        _range(value.get(name), lower, upper)
        for name, (lower, upper) in ranges.items()
    )


def _range(value, lower, upper):
    number = _number(value)
    return number is not None and lower <= number <= upper


def _bounded_int(value, lower, upper):
    return isinstance(value, int) and not isinstance(value, bool) and lower <= value <= upper


def _playback_deck(playback):
    for value in (
        playback.get("deck"), playback.get("deck_number"),
        (playback.get("transport") or {}).get("virtualdj_deck_number")
            if isinstance(playback.get("transport"), dict) else None,
        ((playback.get("playback_state") or {}).get("beatbeam") or {}).get("deck_number")
            if isinstance(playback.get("playback_state"), dict)
            and isinstance((playback.get("playback_state") or {}).get("beatbeam"), dict) else None,
    ):
        deck = _positive_int(value)
        if deck is not None:
            return deck
    return None


def _finite_tree(value):
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, dict):
        return all(isinstance(key, str) and _finite_tree(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return all(_finite_tree(item) for item in value)
    return False


def _baseline_signature(show):
    return {key: show.get(key) for key in (
        "behavior_bucket", "energy", "movement", "motion_name", "pulse_name",
        "theme_name", "look_name", "color_profile_name", "wash_cue_name",
    )}


def _canonical(value):
    text = str(value or "").strip()
    return os.path.normpath(os.path.abspath(os.path.expanduser(text))) if text else None


def _positive_int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(float(value)) else None


def _unit(value):
    number = _number(value)
    return number is not None and 0.0 <= number <= 1.0
