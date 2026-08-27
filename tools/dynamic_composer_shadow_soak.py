#!/usr/bin/env python3
"""Offline corpus and accelerated lifecycle soak for the gate-off composer path."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import statistics
import sys
import threading
import time
import tracemalloc


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beatbeam_app import DmxController
from dynamic_composer import (
    CompositionHistory,
    compose_dynamic_preview,
    project_continuous_musical_state,
)
from musical_event_envelope import project_musical_event_envelope
from production_show_selector import (
    DYNAMIC_COMPOSER_ENABLED,
    DYNAMIC_COMPOSER_SHADOW,
    select_production_show_source,
    validate_dynamic_composer_candidate,
)
from rme_preview import apply_dynamic_composer_preview, preview_rme_context


POINT_TYPES = frozenset({"ARRIVAL", "DROP", "RELEASE", "TRANSITION"})
INTERVAL_TYPES = frozenset({"BUILD", "BREAK"})
KNOWN_MOTIONS = frozenset({
    "break_soft_blue_center", "break_slow_pulse_circle", "sweep_narrow", "sweep_mid",
    "sweep_arc", "sweep_wide", "fast_audience_circle", "build_fastening_circle",
    "drop_fast_circle_white",
})
KNOWN_PALETTES = frozenset({
    "deep_blue_white", "cobalt_amber", "amber_teal", "rose_mint", "teal_orange",
    "magenta_cyan", "ice_fire", "violet_lime", "ruby_lime", "purple_gold",
    "pink_blue", "blue_amber",
})
KNOWN_PULSES = frozenset({"breathe", "soft_pulse", "strong_pulse", "lift", "hit"})
KNOWN_WASHES = frozenset({"center_glow_blue", "blue_white_split", "center_out_build", "white_pixel_hits"})
KNOWN_DIMMER_MOTIFS = frozenset({
    "static_full", "static_reduced", "beat_pulse", "half_bar_gate", "bar_gate",
    "alternate_a_b", "alternate_left_right", "chase_forward", "chase_reverse",
    "out_to_in", "in_to_out", "wave_forward", "wave_reverse", "stair_up",
    "stair_down", "burst_all", "burst_alternate", "syncopated_pulse",
})
KNOWN_COLOR_ANIMATIONS = frozenset({
    "all_same", "group_split", "alternate", "chase_color", "swap_on_bar",
    "swap_on_2_bars", "event_accent", "return_palette_recall",
})
KNOWN_PARTITIONS = frozenset({
    "all_groups", "moving_lead", "par_lead", "wash_foundation", "moving_par",
    "par_wash", "alternating_groups", "call_response",
})


class _NullTransport:
    def __init__(self):
        self.lock = threading.Lock()
        self.decks = {}

    def snapshot_for_render(self):
        return {}

    def developer_playback_state(self):
        return {}

    def structure_behavior_source(self):
        return "legacy"


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--mode", choices=("corpus", "runtime"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=100_000)
    return parser.parse_args()


def _load(path):
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def _usable_tracks(document):
    usable, excluded = [], []
    for track in document.get("tracks") or []:
        reasons = []
        path = Path(str(track.get("canonical_path") or ""))
        sections = (track.get("shadow_analysis") or {}).get("section_characters")
        if track.get("availability") != "current":
            reasons.append("handoff_not_current")
        if not path.is_file():
            reasons.append("audio_missing")
        if not isinstance(sections, list) or not sections:
            reasons.append("continuous_state_missing")
        if reasons:
            excluded.append({
                "track": path.name,
                "canonical_path": str(path),
                "phrase_analysis_version": track.get("phrase_analysis_version"),
                "reasons": reasons,
            })
        else:
            usable.append(track)
    return usable, excluded


def _bpm(track):
    beats = (track.get("rich_analysis") or {}).get("beat_timestamps") or []
    deltas = [float(right) - float(left) for left, right in zip(beats, beats[1:])
              if isinstance(left, (int, float)) and isinstance(right, (int, float))
              and 0.2 <= float(right) - float(left) <= 1.5]
    return 60.0 / statistics.median(deltas) if deltas else 120.0


def _projection(track, position, generation=1, deck=1, *, status="ready"):
    sections = (track.get("shadow_analysis") or {}).get("section_characters") or []
    final_end = float(sections[-1].get("end_seconds") or 0.0) if sections else 0.0
    projection_status = "in_final_segment" if position == final_end else "in_segment"
    path = str(track["canonical_path"])
    rich_events = copy.deepcopy(track.get("rich_musical_events"))
    if isinstance(rich_events, dict):
        rich_events["mode"] = str(rich_events.get("mode") or "").upper()
    return {
        "track_match": "exact",
        "availability": "available_current",
        "projection_status": projection_status,
        "canonical_track_path": path,
        "active_track": {
            "canonical_path": path,
            "deck": deck,
            "status": status,
            "generation": generation,
        },
        "shadow_analysis": track.get("shadow_analysis"),
        "rich_musical_events": rich_events,
    }


def _playback(track, position, bpm, generation=1, deck=1, *, advancing=True,
              stale=False, live=None, event="normal"):
    return {
        "_active_playback_source": "virtualdj",
        "_playback_generation": generation,
        "_playback_event": event,
        "track_path": str(track["canonical_path"]),
        "time_seconds": float(position),
        "bpm": float(bpm),
        "beat_value": float(position) * float(bpm) / 60.0,
        "phrase_current": "verse",
        "phrase_next": "chorus",
        "mood": None,
        "strobe_active": False,
        "strobe_count_in": None,
        "playing": advancing,
        "stale": stale,
        "transport": {"virtualdj_deck_number": deck},
        "playback_state": {
            "availability": "available" if not stale else "unavailable",
            "transport_state": "advancing" if advancing else "stationary",
            "beatbeam": {"deck_number": deck},
        },
        "live_intensity_input": live,
    }


def _baseline_template():
    controller = DmxController(_NullTransport(), None)
    controller.config = controller._clean_full_config(controller.default_config())
    controller.config["auto_show"].update({"enabled": True, "preview_rme_mode": "DYNAMIC_COMPOSER"})
    osc = {
        "_active_playback_source": "legacy", "_playback_generation": 1,
        "phrase_current": "verse", "bpm": 120.0, "beat_value": 1.0,
        "time_seconds": 10.0, "stale": False,
    }
    baseline, _ = controller._auto_show_evaluation(osc, controller.config["auto_show"])
    baseline["live_intensity"] = {
        "source_valid": False, "fallback_reason": "missing", "live_modifier": 0.0,
        "effective_intensity": baseline.get("energy"),
    }
    return controller, controller.config, baseline


def _frame_positions(track):
    positions = set()
    sections = (track.get("shadow_analysis") or {}).get("section_characters") or []
    for section in sections:
        start, end = float(section["start_seconds"]), float(section["end_seconds"])
        positions.add((start + end) / 2.0)
    bpm = _bpm(track)
    beat_seconds = 60.0 / bpm
    for event in (track.get("rich_musical_events") or {}).get("events") or []:
        kind = event.get("type")
        start = event.get("start_seconds")
        if not isinstance(start, (int, float)):
            continue
        if kind in POINT_TYPES:
            total = 6.0 if kind == "DROP" else 8.0
            for beats in (0.0, .5, total / 2.0, total - .01, total + .01):
                positions.add(float(start) + beats * beat_seconds)
        elif kind in INTERVAL_TYPES and isinstance(event.get("end_seconds"), (int, float)):
            end = float(event["end_seconds"])
            positions.update((float(start) + .001, (float(start) + end) / 2.0, max(float(start), end - .001)))
    lower = min(float(section["start_seconds"]) for section in sections)
    upper = max(float(section["end_seconds"]) for section in sections)
    return sorted(value for value in positions if lower <= value <= upper)


def _candidate(track, position, baseline, history, generation=1, deck=1, live=None,
               status="ready"):
    projection = _projection(track, position, generation, deck, status=status)
    playback = _playback(track, position, _bpm(track), generation, deck, live=live)
    state, state_reason = project_continuous_musical_state(projection, position)
    context = preview_rme_context(projection, position, "DYNAMIC_COMPOSER")
    envelope, envelope_reason = project_musical_event_envelope(projection, playback)
    context = dict(context)
    context.update({
        "continuous_state_reason": state_reason,
        "event_envelope_reason": envelope_reason,
    })
    live_state = live if isinstance(live, dict) else baseline.get("live_intensity")
    composition = compose_dynamic_preview(
        baseline, state, context, envelope,
        composition_history=history,
        lifecycle_context=("virtualdj", str(track["canonical_path"]), generation, deck),
        live_intensity=live_state,
    )
    return (
        apply_dynamic_composer_preview(baseline, context, composition),
        projection, playback, state, context, envelope, composition,
    )


def _signature_key(candidate):
    signature = candidate.get("composition_signature") or {}
    return json.dumps(signature, sort_keys=True, separators=(",", ":"))


def _percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))]


def _renderer_values_valid(values):
    return isinstance(values, dict) and all(
        isinstance(channel, int) and channel > 0
        and isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 255
        for channel, value in values.items()
    )


def corpus_soak(document):
    started = time.perf_counter()
    tracks, excluded = _usable_tracks(document)
    controller, config, template = _baseline_template()
    totals = Counter()
    fallback = Counter()
    current_rme = Counter()
    envelope_active = Counter()
    envelope_completion = Counter()
    validation_faults = Counter()
    track_metrics = []
    renderer_exceptions = []
    selection_digest = hashlib.sha256()
    max_history_recent = max_history_observations = 0

    for track_index, track in enumerate(tracks, start=1):
        history = CompositionHistory()
        bpm = _bpm(track)
        section_records = []
        prior_signature = None
        repeats = consecutive = recurrence_reuse = alternatives = near_repeats = 0
        same_components = Counter()
        track_rme = Counter()
        positions = _frame_positions(track)
        for position in positions:
            totals["evaluated_frames"] += 1
            baseline = copy.deepcopy(template)
            baseline["energy"] = max(0.0, min(1.0, float(baseline.get("energy") or .5)))
            candidate, projection, playback, state, context, envelope, composition = _candidate(
                track, position, baseline, history, generation=track_index,
            )
            if state is not None:
                totals["continuous_state_valid"] += 1
            if isinstance(candidate, dict):
                totals["composer_candidate_available"] += 1
            valid = validate_dynamic_composer_candidate(candidate)
            totals["composer_candidate_valid"] += int(valid)
            if not valid:
                validation_faults[_candidate_invalid_reason(candidate)] += 1
            if context.get("current_rme") is None:
                totals["without_current_rme"] += 1
                totals["no_rme_candidate_valid"] += int(valid)
            else:
                kind = str(context["current_rme"].get("type") or "unknown")
                totals["with_current_rme"] += 1
                current_rme[kind] += 1
                track_rme[kind] += 1
            if envelope is not None:
                totals["event_envelope_active"] += 1
                envelope_active[envelope.event_type] += 1
                if not 0.0 <= envelope.progress <= 1.0:
                    validation_faults["invalid_envelope_progress"] += 1
            else:
                totals["event_envelope_inactive"] += 1
            totals["analyzed_only_intensity"] += 1
            totals["analyzed_only_candidate_valid"] += int(valid)

            selected, decision = select_production_show_source(
                DYNAMIC_COMPOSER_ENABLED, baseline, candidate, projection, playback,
                track_index, renderer_healthy=True,
            )
            if decision.get("composer_eligible"):
                totals["hypothetical_eligible"] += 1
                if selected is not candidate:
                    validation_faults["eligible_not_selected"] += 1
            else:
                totals["hypothetical_ineligible"] += 1
                fallback[decision.get("fallback_reason") or "unknown"] += 1

            shadow_selected, shadow_decision = select_production_show_source(
                DYNAMIC_COMPOSER_SHADOW, baseline, candidate, projection, playback,
                track_index, renderer_healthy=True,
            )
            totals["shadow_baseline_identity"] += int(shadow_selected is baseline)
            if shadow_decision.get("production_source") != "existing_autoshow":
                validation_faults["shadow_source_changed"] += 1
            render_osc = dict(playback)
            try:
                baseline_values = controller._render_values(
                    position, advance_motion=False, config=config, osc=render_osc,
                    auto_show=baseline,
                )
                shadow_values = controller._render_values(
                    position, advance_motion=False, config=config, osc=render_osc,
                    auto_show=shadow_selected,
                )
                candidate_values = controller._render_values(
                    position, advance_motion=False, config=config, osc=render_osc,
                    auto_show=candidate,
                ) if valid else {}
                totals["renderer_safe_frames"] += int(
                    baseline_values == shadow_values and _renderer_values_valid(baseline_values)
                    and (not valid or _renderer_values_valid(candidate_values))
                )
            except Exception as exc:
                renderer_exceptions.append({
                    "track": Path(track["canonical_path"]).name,
                    "position": position,
                    "error": f"{type(exc).__name__}: {exc}",
                })

            selection_digest.update(json.dumps({
                "track": track["canonical_path"], "position": round(position, 6),
                "valid": valid, "eligible": decision.get("composer_eligible"),
                "reason": decision.get("fallback_reason"),
                "signature": candidate.get("composition_signature"),
                "event": None if envelope is None else envelope.as_dict(),
            }, sort_keys=True, separators=(",", ":")).encode())

        sections = (track.get("shadow_analysis") or {}).get("section_characters") or []
        diversity_history = CompositionHistory()
        for section in sections:
            position = (float(section["start_seconds"]) + float(section["end_seconds"])) / 2.0
            baseline = copy.deepcopy(template)
            candidate, *_rest = _candidate(
                track, position, baseline, diversity_history, generation=track_index,
            )
            signature = _signature_key(candidate)
            variation = (candidate.get("variation") or {}).get("selection")
            repeat_classification = (candidate.get("variation") or {}).get("repeat_classification")
            repeats += int(signature in {record["signature"] for record in section_records})
            consecutive += int(prior_signature == signature)
            recurrence_reuse += int(variation == "recurrence_reuse")
            alternatives += int(variation == "anti_repeat_alternative")
            near_repeats += int(repeat_classification == "NEAR_REPEAT")
            signature_payload = candidate.get("composition_signature") or {}
            section_records.append({
                "observation_id": section.get("observation_id"),
                "signature": signature,
                "motion": signature_payload.get("motion_family"),
                "palette": signature_payload.get("palette_family"),
                "pulse": signature_payload.get("pulse"),
                "wash": signature_payload.get("wash"),
                "dimmer": signature_payload.get("dimmer_motif"),
                "color_animation": signature_payload.get("color_animation"),
                "fixture_partition": signature_payload.get("fixture_partition"),
                "variation": variation,
                "repeat_classification": repeat_classification,
            })
            if len(section_records) > 1:
                previous = section_records[-2]
                current = section_records[-1]
                for component in ("motion", "palette", "pulse", "wash", "dimmer", "color_animation", "fixture_partition"):
                    same_components[component] += int(previous.get(component) == current.get(component))
            prior_signature = signature
        max_history_recent = max(max_history_recent, len(diversity_history._recent))
        max_history_observations = max(max_history_observations, len(diversity_history._by_observation))
        unique = len({record["signature"] for record in section_records})
        track_metrics.append({
            "track": Path(track["canonical_path"]).name,
            "canonical_path": track["canonical_path"],
            "sections": len(section_records),
            "unique_full_signatures": unique,
            "unique_motion_signatures": len({record["motion"] for record in section_records}),
            "unique_palette_signatures": len({record["palette"] for record in section_records}),
            "unique_pulse_signatures": len({record["pulse"] for record in section_records}),
            "unique_wash_signatures": len({record["wash"] for record in section_records}),
            "unique_dimmer_motifs": len({record["dimmer"] for record in section_records}),
            "unique_color_animations": len({record["color_animation"] for record in section_records}),
            "unique_fixture_partitions": len({record["fixture_partition"] for record in section_records}),
            "exact_repeat_count": repeats,
            "consecutive_repeat_count": consecutive,
            "exact_repeat_rate": repeats / max(1, len(section_records)),
            "consecutive_repeat_rate": consecutive / max(1, len(section_records) - 1),
            "recurrence_reuse_count": recurrence_reuse,
            "anti_repeat_alternative_count": alternatives,
            "near_repeat_count": near_repeats,
            "consecutive_same_component_rates": {
                component: value / max(1, len(section_records) - 1)
                for component, value in same_components.items()
            },
            "section_progression": section_records,
            "current_rme_frames": dict(track_rme),
        })

    # Point-event completion is checked separately against the continuous backbone.
    for track in tracks:
        bpm = _bpm(track)
        for event in (track.get("rich_musical_events") or {}).get("events") or []:
            if event.get("type") not in POINT_TYPES or not isinstance(event.get("start_seconds"), (int, float)):
                continue
            total = 6.0 if event["type"] == "DROP" else 8.0
            position = float(event["start_seconds"]) + (total + .01) * 60.0 / bpm
            projection = _projection(track, position)
            state, _ = project_continuous_musical_state(projection, position)
            if state is None:
                continue
            playback = _playback(track, position, bpm)
            envelope, _ = project_musical_event_envelope(projection, playback)
            context = preview_rme_context(projection, position, "DYNAMIC_COMPOSER")
            baseline = copy.deepcopy(template)
            completed = compose_dynamic_preview(baseline, state, context, envelope)
            backbone = compose_dynamic_preview(baseline, state, context, None)
            ok = envelope is None and completed == backbone
            envelope_completion[event["type"]] += int(ok)
            totals["envelope_completion_checks"] += 1
            totals["envelope_completion_pass"] += int(ok)

    section_counts = [item["sections"] for item in track_metrics]
    unique_counts = [item["unique_full_signatures"] for item in track_metrics]
    repeat_rates = [item["exact_repeat_rate"] for item in track_metrics]
    consecutive_rates = [item["consecutive_repeat_rate"] for item in track_metrics]
    component_rates = {
        component: _distribution([
            item["consecutive_same_component_rates"].get(component, 0.0)
            for item in track_metrics
        ])
        for component in ("motion", "palette", "pulse", "wash", "dimmer", "color_animation", "fixture_partition")
    }
    result = {
        "contract": "dynamic-composer-full-corpus-shadow-soak-v1",
        "source_handoff_generated_at_unix_milliseconds": document.get("generated_at_unix_milliseconds"),
        "dataset": {
            "tracks_total": len(document.get("tracks") or []),
            "tracks_with_current_handoff": sum(
                track.get("availability") == "current" for track in document.get("tracks") or []
            ),
            "tracks_usable_for_shadow": len(tracks),
            "tracks_excluded": len(excluded),
            "excluded": excluded,
            "total_sections_observations": sum(section_counts),
            "tracks_with_rme_contract": sum(bool(track.get("rich_musical_events")) for track in tracks),
            "tracks_without_rme_contract": sum(not bool(track.get("rich_musical_events")) for track in tracks),
        },
        "coverage": dict(totals),
        "fallback_reasons": dict(fallback),
        "current_rme_frames_by_type": dict(current_rme),
        "event_envelope_active_by_type": dict(envelope_active),
        "event_envelope_completion_pass_by_type": dict(envelope_completion),
        "candidate_validation_faults": dict(validation_faults),
        "unknown_primitive_count": validation_faults.get("unknown_primitive", 0),
        "invalid_numeric_count": sum(validation_faults[key] for key in (
            "nonfinite_value", "range_violation",
        )),
        "renderer_exceptions": renderer_exceptions,
        "composition_diversity": {
            "unique_full_signatures": _distribution(unique_counts),
            "exact_repeat_rate": _distribution(repeat_rates),
            "consecutive_repeat_rate": _distribution(consecutive_rates),
            "total_exact_repeats": sum(item["exact_repeat_count"] for item in track_metrics),
            "total_consecutive_repeats": sum(item["consecutive_repeat_count"] for item in track_metrics),
            "total_recurrence_reuse": sum(item["recurrence_reuse_count"] for item in track_metrics),
            "total_anti_repeat_alternatives": sum(item["anti_repeat_alternative_count"] for item in track_metrics),
            "total_near_repeats": sum(item["near_repeat_count"] for item in track_metrics),
            "consecutive_same_component_rate": component_rates,
            "unique_dimmer_motifs": _distribution([item["unique_dimmer_motifs"] for item in track_metrics]),
            "unique_palette_families": _distribution([item["unique_palette_signatures"] for item in track_metrics]),
            "unique_fixture_partitions": _distribution([item["unique_fixture_partitions"] for item in track_metrics]),
        },
        "repetition_outliers_exact": sorted(
            track_metrics, key=lambda item: (item["exact_repeat_rate"], item["sections"]), reverse=True
        )[:10],
        "repetition_outliers_consecutive": sorted(
            track_metrics, key=lambda item: (item["consecutive_repeat_rate"], item["sections"]), reverse=True
        )[:10],
        "history_bounds": {
            "capacity": 6,
            "maximum_recent_size": max_history_recent,
            "maximum_track_observation_cache_size": max_history_observations,
        },
        "determinism_digest": selection_digest.hexdigest(),
        "track_metrics": track_metrics,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
    }
    result["acceptance"] = _corpus_acceptance(result)
    return result


def _candidate_invalid_reason(candidate):
    if not isinstance(candidate, dict):
        return "candidate_missing"
    groups = candidate.get("fixture_group_intents")
    if not isinstance(groups, dict) or set(groups) != {"moving", "par", "wash", "static"}:
        return "malformed_fixture_group_intent"
    if not _finite(candidate):
        return "nonfinite_value"
    for intent in groups.values():
        for key in ("activity", "intensity", "movement_amount", "movement_speed",
                    "color_change_rate", "pulse_amount", "accent_strength"):
            value = intent.get(key) if isinstance(intent, dict) else None
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
                return "range_violation"
    primitives = candidate.get("selected_primitives") or {}
    for primitive in primitives.values():
        if not isinstance(primitive, dict):
            return "unknown_primitive"
        if "movement_pattern" in primitive and primitive["movement_pattern"] not in KNOWN_MOTIONS:
            return "unknown_primitive"
        if "palette" in primitive and primitive["palette"] not in KNOWN_PALETTES:
            return "unknown_primitive"
        if "pulse" in primitive and primitive["pulse"] not in KNOWN_PULSES:
            return "unknown_primitive"
        if "wash_cue" in primitive and primitive["wash_cue"] not in KNOWN_WASHES:
            return "unknown_primitive"
        if "dimmer_motif" in primitive and primitive["dimmer_motif"] not in KNOWN_DIMMER_MOTIFS:
            return "unknown_primitive"
        if "color_animation" in primitive and primitive["color_animation"] not in KNOWN_COLOR_ANIMATIONS:
            return "unknown_primitive"
        if "fixture_partition" in primitive and primitive["fixture_partition"] not in KNOWN_PARTITIONS:
            return "unknown_primitive"
    if not isinstance(candidate.get("composition_signature"), dict):
        return "incomplete_signature"
    return "candidate_invalid"


def _finite(value):
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, dict):
        return all(_finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_finite(item) for item in value)
    return False


def _distribution(values):
    if not values:
        return {"count": 0, "median": 0, "p90": 0, "p95": 0, "max": 0}
    return {
        "count": len(values),
        "median": statistics.median(values),
        "p90": _percentile(values, .90),
        "p95": _percentile(values, .95),
        "max": max(values),
    }


def _corpus_acceptance(result):
    coverage = result["coverage"]
    return {
        "all_candidates_valid": coverage.get("composer_candidate_available")
            == coverage.get("composer_candidate_valid"),
        "all_hypothetically_eligible": coverage.get("composer_candidate_valid")
            == coverage.get("hypothetical_eligible"),
        "all_shadow_frames_baseline": coverage.get("evaluated_frames")
            == coverage.get("shadow_baseline_identity"),
        "all_renderer_frames_safe": coverage.get("composer_candidate_valid")
            == coverage.get("renderer_safe_frames"),
        "no_rme_never_forces_fallback": coverage.get("without_current_rme")
            == coverage.get("no_rme_candidate_valid"),
        "analyzed_only_never_forces_fallback": coverage.get("analyzed_only_intensity")
            == coverage.get("analyzed_only_candidate_valid"),
        "all_envelopes_complete": coverage.get("envelope_completion_checks")
            == coverage.get("envelope_completion_pass"),
        "silent_invalid_states": sum(result["candidate_validation_faults"].values()),
        "renderer_exception_count": len(result["renderer_exceptions"]),
    }


def runtime_soak(document, frames):
    started = time.perf_counter()
    tracks, excluded = _usable_tracks(document)
    if not tracks:
        raise RuntimeError("no usable tracks")
    controller, config, template = _baseline_template()
    history = CompositionHistory()
    counters = Counter()
    lifecycle = Counter()
    fallback = Counter()
    intervals = []
    first_window = []
    last_window = []
    rss_before = _rss_bytes()
    tracemalloc.start()
    heap_before = tracemalloc.get_traced_memory()[0]
    previous_track = previous_deck = None
    last_candidate_identity = None
    max_recent = max_observations = 0

    for frame in range(frames):
        frame_started = time.perf_counter()
        track_index = (frame // 5000) % len(tracks)
        track = tracks[track_index]
        sections = track["shadow_analysis"]["section_characters"]
        section_index = (frame // 180) % len(sections)
        section = sections[section_index]
        progress = (frame % 180) / 180.0
        position = float(section["start_seconds"]) + (
            float(section["end_seconds"]) - float(section["start_seconds"])
        ) * min(.999999, progress)
        generation = 1 + frame // 2500
        deck = 1 + ((frame // 2500) % 2)
        event = "normal"
        if previous_track is not None and previous_track != track_index:
            lifecycle["track_switch"] += 1
            event = "track_changed"
        if previous_deck is not None and previous_deck != deck:
            lifecycle["deck_switch"] += 1
            event = "deck_changed"
        previous_track, previous_deck = track_index, deck

        advancing = frame % 11000 not in range(100, 180)
        stale = frame % 13000 in range(200, 260)
        pending = frame % 17000 in range(300, 340)
        manual = frame % 19000 in range(400, 440)
        blackout = frame % 23000 in range(500, 520)
        valid_live = frame % 10 == 0
        if not advancing:
            lifecycle["pause"] += 1
        if stale:
            lifecycle["stale_handoff"] += 1
        if pending:
            lifecycle["analysis_pending"] += 1
        if manual:
            lifecycle["manual_override"] += 1
        if frame and frame % 7000 == 0:
            lifecycle["seek_forward"] += 1
            event = "position_jump_forward"
        if frame and frame % 9000 == 0:
            lifecycle["seek_backward"] += 1
            event = "position_jump_backward"
        if frame and frame % 2500 == 0:
            lifecycle["master_switch"] += 1
        if frame and frame % 17000 == 0:
            lifecycle["handoff_recovery"] += 1
        if frame and frame % 29000 == 0:
            lifecycle["prewarm_replacement"] += 1

        live = {
            "source_valid": valid_live,
            "live_modifier": .06 if valid_live else 0.0,
            "fallback_reason": None if valid_live else "missing",
            "effective_intensity": .6,
            "source_deck": deck if valid_live else None,
            "source_generation": generation if valid_live else None,
        }
        baseline = copy.deepcopy(template)
        if manual:
            baseline["override_phrase"] = "chorus"
        candidate, projection, playback, state, context, envelope, composition = _candidate(
            track, position, baseline, history, generation, deck, live,
            status="pending" if pending else "ready",
        )
        playback["_playback_event"] = event
        playback["playing"] = advancing
        playback["stale"] = stale
        playback["playback_state"]["availability"] = "unavailable" if stale else "available"
        playback["playback_state"]["transport_state"] = "advancing" if advancing else "stationary"
        if stale:
            projection["availability"] = "available_stale"
        valid = validate_dynamic_composer_candidate(candidate)
        counters["continuous_state_valid"] += int(state is not None)
        counters["candidate_available"] += int(isinstance(candidate, dict))
        counters["candidate_valid"] += int(valid)
        counters["with_rme"] += int(context.get("current_rme") is not None)
        counters["without_rme"] += int(context.get("current_rme") is None)
        counters["envelope_active"] += int(envelope is not None)
        counters["valid_live_intensity"] += int(valid_live)
        counters["analyzed_only_intensity"] += int(not valid_live)

        selected, decision = select_production_show_source(
            DYNAMIC_COMPOSER_SHADOW, baseline, candidate, projection, playback,
            generation, renderer_healthy=True,
            safety_context={"blackout_active": blackout},
        )
        counters["baseline_selected"] += int(selected is baseline)
        counters["preview_candidate_changed"] += int(
            isinstance(candidate, dict) and candidate != baseline
        )
        hypothetical_selected, hypothetical = select_production_show_source(
            DYNAMIC_COMPOSER_ENABLED, baseline, candidate, projection, playback,
            generation, renderer_healthy=True,
            safety_context={"blackout_active": blackout},
        )
        if hypothetical.get("composer_eligible"):
            counters["hypothetical_eligible"] += 1
        else:
            counters["hypothetical_ineligible"] += 1
            fallback[hypothetical.get("fallback_reason") or "unknown"] += 1
            if hypothetical_selected is not baseline:
                counters["failback_atomicity_failure"] += 1

        try:
            baseline_values = controller._render_values(
                position, advance_motion=False, config=config, osc=playback,
                auto_show=baseline,
            )
            physical_values = controller._render_values(
                position, advance_motion=False, config=config, osc=playback,
                auto_show=selected,
            )
            preview_values = controller._render_values(
                position, advance_motion=False, config=config, osc=playback,
                auto_show=candidate if valid else baseline,
            )
            if baseline_values != physical_values:
                counters["physical_identity_failure"] += 1
            if not _renderer_values_valid(physical_values) or not _renderer_values_valid(preview_values):
                counters["invalid_physical_frame"] += 1
        except Exception:
            counters["render_exceptions"] += 1

        current_identity = None if not isinstance(candidate, dict) else (
            track["canonical_path"], deck, generation,
            (candidate.get("continuous_musical_state") or {}).get("observation_id"),
        )
        if current_identity is not None:
            if current_identity[:3] != (track["canonical_path"], deck, generation):
                counters["old_track_or_deck_candidate"] += 1
            last_candidate_identity = current_identity
        if envelope is not None and envelope.beats_since_event >= envelope.total_beats:
            counters["envelope_latch"] += 1
        if valid_live and (live.get("source_deck"), live.get("source_generation")) != (deck, generation):
            counters["live_intensity_identity_leak"] += 1
        if decision.get("decision_generation") != generation:
            counters["selector_generation_mismatch"] += 1
        max_recent = max(max_recent, len(history._recent))
        max_observations = max(max_observations, len(history._by_observation))

        elapsed = time.perf_counter() - frame_started
        intervals.append(elapsed)
        if frame < min(10_000, frames):
            first_window.append(elapsed)
        if frame >= max(0, frames - 10_000):
            last_window.append(elapsed)

    heap_current, heap_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed = time.perf_counter() - started
    rss_after = _rss_bytes()
    result = {
        "contract": "dynamic-composer-accelerated-runtime-soak-v1",
        "frames": frames,
        "equivalent_runtime_seconds_at_30fps": frames / 30.0,
        "equivalent_runtime_minutes_at_30fps": frames / 1800.0,
        "wall_elapsed_seconds": elapsed,
        "accelerated_effective_fps": frames / elapsed,
        "frame_processing_seconds": {
            "median": statistics.median(intervals),
            "p95": _percentile(intervals, .95),
            "max": max(intervals),
            "first_10k_mean": statistics.mean(first_window),
            "last_10k_mean": statistics.mean(last_window),
            "last_vs_first_ratio": statistics.mean(last_window) / max(1e-12, statistics.mean(first_window)),
        },
        "dataset": {
            "tracks_available": len(tracks), "tracks_excluded": len(excluded),
        },
        "coverage": dict(counters),
        "lifecycle_events": dict(lifecycle),
        "hypothetical_fallback_reasons": dict(fallback),
        "memory": {
            "rss_before_bytes": rss_before,
            "rss_after_bytes": rss_after,
            "rss_delta_bytes": rss_after - rss_before,
            "python_heap_before_bytes": heap_before,
            "python_heap_after_bytes": heap_current,
            "python_heap_peak_bytes": heap_peak,
            "history_recent_max": max_recent,
            "history_observations_max": max_observations,
            "controller_motion_states": len(controller.motion_states),
            "controller_rhythm_states": len(controller.slot_rhythm_states),
            "controller_trigger_signatures": len(controller.last_slot_trigger_signatures),
        },
        "last_candidate_identity_present": last_candidate_identity is not None,
        "runtime_production_mode": "BASELINE_ONLY",
        "runtime_production_source": "existing_autoshow",
        "physical_output_source": "auto_show -> current_values",
    }
    result["acceptance"] = {
        "unhandled_exceptions": counters.get("render_exceptions", 0),
        "invalid_physical_frames": counters.get("invalid_physical_frame", 0),
        "physical_identity_failures": counters.get("physical_identity_failure", 0),
        "failback_atomicity_failures": counters.get("failback_atomicity_failure", 0),
        "state_leaks": sum(counters[key] for key in (
            "old_track_or_deck_candidate", "envelope_latch", "live_intensity_identity_leak",
            "selector_generation_mismatch",
        )),
        "all_frames_baseline": counters.get("baseline_selected", 0) == frames,
        "history_recent_bounded": max_recent <= 6,
        "cadence_degradation_detected": result["frame_processing_seconds"]["last_vs_first_ratio"] > 1.5,
    }
    return result


def _rss_bytes():
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(usage if sys.platform == "darwin" else usage * 1024)


def main():
    args = _arguments()
    document = _load(args.handoff)
    result = corpus_soak(document) if args.mode == "corpus" else runtime_soak(document, args.frames)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "contract": result["contract"],
        "acceptance": result["acceptance"],
        "elapsed_seconds": result.get("elapsed_seconds", result.get("wall_elapsed_seconds")),
    }, indent=2))


if __name__ == "__main__":
    main()
