"""Bounded, preview-only live intensity correction.

The input is a fresh, deck-bound, already normalised 0..1 observation. It is
never a master selector and it never carries section/event semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


LIVE_INTENSITY_MAX_MODIFIER = 0.06


def _unit(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return max(0.0, min(1.0, value))


@dataclass
class LiveIntensityFeedback:
    """Small stateful attack/release filter, reset on authoritative lifecycle."""

    lifecycle: tuple | None = None
    baseline: float | None = None
    smoothed: float | None = None
    observed_at: float | None = None

    def observe(self, analyzed_intensity, source, now):
        analyzed = _unit(analyzed_intensity)
        analyzed = 0.5 if analyzed is None else analyzed
        payload = source if isinstance(source, dict) else {}
        value = _unit(payload.get("value"))
        lifecycle = payload.get("lifecycle")
        valid = bool(payload.get("valid")) and value is not None and isinstance(lifecycle, tuple) and lifecycle
        reason = str(payload.get("reason") or ("missing" if value is None else "invalid"))
        if not valid:
            self.lifecycle = self.baseline = self.smoothed = self.observed_at = None
            return self._state(analyzed, None, 0.0, False, reason, payload)
        if lifecycle != self.lifecycle or self.baseline is None or self.smoothed is None or self.observed_at is None:
            self.lifecycle, self.baseline, self.smoothed, self.observed_at = lifecycle, value, value, float(now)
            return self._state(analyzed, value, 0.0, True, "current", payload)
        elapsed = max(0.0, min(2.0, float(now) - self.observed_at))
        self.observed_at = float(now)
        time_constant = 0.16 if value >= self.smoothed else 0.85
        alpha = 1.0 - math.exp(-elapsed / time_constant) if elapsed > 0 else 0.0
        self.smoothed += (value - self.smoothed) * alpha
        baseline_alpha = 1.0 - math.exp(-elapsed / 5.0) if elapsed > 0 else 0.0
        self.baseline += (self.smoothed - self.baseline) * baseline_alpha
        relative = max(-1.0, min(1.0, (self.smoothed - self.baseline) / 0.35))
        modifier = max(-LIVE_INTENSITY_MAX_MODIFIER, min(LIVE_INTENSITY_MAX_MODIFIER, relative * LIVE_INTENSITY_MAX_MODIFIER))
        return self._state(analyzed, self.smoothed, modifier, True, "current", payload)

    @staticmethod
    def _state(analyzed, live, modifier, valid, reason, source):
        return {
            "analyzed_intensity": analyzed,
            "raw_source_level": _unit(source.get("value")),
            "live_intensity": live,
            "effective_intensity": max(0.0, min(1.0, analyzed + modifier)),
            "live_modifier": modifier,
            "source_age_milliseconds": source.get("age_milliseconds"),
            "source_deck": source.get("deck_number"),
            "source_generation": source.get("generation"),
            "source_kind": source.get("source_kind"),
            "source_valid": valid,
            "fallback_reason": None if valid else reason,
        }
