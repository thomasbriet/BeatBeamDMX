#!/usr/bin/env python3
"""Read-only, in-place developer dashboard for VirtualDJ and SongAnalyzer state."""

import argparse
import json
import os
import sys
import time
from urllib.request import urlopen


CLEAR_AND_HOME = "\x1b[2J\x1b[H"


def value(mapping, key):
    return "-" if not mapping or mapping.get(key) is None else str(mapping[key])


def number(value_to_convert, default=0.0):
    try:
        return float(value_to_convert)
    except (TypeError, ValueError):
        return default


def percentage(value_to_convert):
    return "{}%".format(round(number(value_to_convert) * 100))


def timestamp(seconds):
    milliseconds = max(0, round(number(seconds) * 1000))
    total_seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return "{:02d}:{:02d}:{:02d}.{:03d}".format(hours, minutes, seconds, milliseconds)
    return "{:02d}:{:02d}.{:03d}".format(minutes, seconds, milliseconds)


def compact_track(path, maximum=68):
    text = os.path.basename(str(path or "")) or "-"
    return text if len(text) <= maximum else text[: maximum - 3] + "..."


def segment_line(segment):
    if not segment:
        return "-"
    return "#{} {} | {} - {}".format(
        value(segment, "index"), value(segment, "label"),
        timestamp(segment.get("start_seconds")), timestamp(segment.get("end_seconds")),
    )


class TransitionObserver:
    """Developer-only transition history; it does not feed the effect engine."""

    def __init__(self):
        self._last_path = None
        self._last_position = None
        self._last_current = None
        self.last_transition = None

    def observe(self, playback, structure, observed_monotonic=None):
        observed_monotonic = time.monotonic() if observed_monotonic is None else observed_monotonic
        current = (structure or {}).get("current") or None
        path = (structure or {}).get("canonical_track_path")
        beatbeam = (playback or {}).get("beatbeam") or {}
        position = number(beatbeam.get("estimated_position_milliseconds")) / 1000.0
        current_key = None if current is None else (current.get("index"), current.get("label"))
        if self._last_path == path and self._last_current is not None and current_key != self._last_current:
            jumped = bool((playback or {}).get("last_discontinuity")) or position < (self._last_position or 0.0)
            if jumped:
                description = "SEEK/JUMP -> {}".format(value(current, "label"))
            else:
                description = "{} -> {}".format(self._last_current[1], value(current, "label"))
            self.last_transition = {
                "description": description,
                "boundary_seconds": None if jumped else current.get("start_seconds"),
                "observed_seconds": position,
                "observed_monotonic": observed_monotonic,
                "kind": "seek_jump" if jumped else "natural",
            }
        self._last_path = path
        self._last_position = position
        self._last_current = current_key


def render_dashboard(playback, structure, behavior=None, observer=None):
    playback = playback or {}
    structure = structure or {}
    behavior = behavior or {}
    if observer is not None:
        observer.observe(playback, structure)

    virtualdj = playback.get("virtualdj") or {}
    beatbeam = playback.get("beatbeam") or {}
    current = structure.get("current") or None
    previous = structure.get("previous") or None
    following = structure.get("next") or None
    metrics = structure.get("metrics") or {}
    track = beatbeam.get("track_path") or virtualdj.get("track_path")
    position_seconds = number(beatbeam.get("estimated_position_milliseconds")) / 1000.0
    transition = None if observer is None else observer.last_transition

    lines = [
        "BeatBeam M19F Structure Diagnostics",
        "===================================",
        "",
        "VirtualDJ",
        "---------",
        "Connected: {}".format("YES" if playback.get("availability") == "available" else "NO"),
        "Deck: {} | Track: {}".format(
            value(beatbeam, "deck_number") if beatbeam.get("deck_number") is not None else value(virtualdj, "deck_number"),
            compact_track(track),
        ),
        "Position: {} | BPM: {} | Beat: {} | Bar: {}".format(
            timestamp(position_seconds), value(beatbeam, "bpm"), value(beatbeam, "beat_number"), value(beatbeam, "bar_number")
        ),
        "",
        "SongAnalyzer Structure",
        "----------------------",
        "Match: {} | Status: {} | Schema: {}".format(
            value(structure, "track_match").upper(), value(structure, "availability").upper(), value(structure, "schema_version")
        ),
        "Analysis: {} | Phrase analysis: {} | Segments: {}".format(
            value(structure, "analysis_version"), value(structure, "phrase_analysis_version"), value(structure, "segment_count")
        ),
        "",
        "Behavior Control",
        "----------------",
        "Selected: {} | Effective: {} | Eligible: {}".format(
            value(behavior, "selected_source").upper(),
            value(behavior, "effective_source").upper(),
            "YES" if behavior.get("eligible") else "NO",
        ),
        "Legacy phrase: {} | SongAnalyzer label: {} | Mapped behavior: {}".format(
            value(behavior, "legacy_phrase"),
            value(behavior, "song_analyzer_label"),
            value(behavior, "mapped_behavior_bucket"),
        ),
        "Fallback: {}".format(value(behavior, "fallback_reason")),
        "",
        "Previous",
        "--------",
        segment_line(previous),
        "",
        ">>> CURRENT: {} <<<".format(value(current, "label").upper() if current else "-"),
        "{}".format(segment_line(current)),
        "Progress: {} | Remaining: {}".format(
            percentage(current.get("progress")) if current else "-",
            "{} s".format(round(number(current.get("remaining_seconds")), 1)) if current else "-",
        ),
        "",
        "Next",
        "----",
        "{}".format(segment_line(following)),
        "Starts in: {}".format(
            "{} s".format(round(number(following.get("starts_in_seconds")), 1)) if following else "-"
        ),
        "",
        "Last Transition",
        "---------------",
    ]
    if transition is None:
        lines.append("-")
    else:
        boundary = "-" if transition["boundary_seconds"] is None else timestamp(transition["boundary_seconds"])
        lines.append("{} | boundary: {} | observed: {} | monotonic: {:.3f}".format(
            transition["description"], boundary, timestamp(transition["observed_seconds"]), transition["observed_monotonic"]
        ))
    lines.extend([
        "",
        "Health",
        "------",
        "Cache loads/hits: {} / {} | Parse errors: {} | Schema errors: {}".format(
            value(metrics, "structure_loads"), value(metrics, "cache_hits"),
            value(metrics, "parse_failures"), value(metrics, "schema_failures"),
        ),
        "Behavior input: {} | VirtualDJ writes: NO".format(
            value(behavior, "effective_source").upper()
        ),
    ])
    return "\n".join(lines)


def fetch_json(endpoint, opener=urlopen):
    with opener(endpoint, timeout=1.0) as response:
        return json.loads(response.read().decode("utf-8"))


def run_dashboard(args, output=None, opener=urlopen, is_tty=None, sleep_fn=time.sleep, maximum_iterations=None):
    output = output or sys.stdout
    is_tty = output.isatty() if is_tty is None else is_tty
    should_clear = is_tty and not args.no_clear and not args.once
    endpoint = "http://{}:{}/api/developer/playback".format(args.host, args.port)
    structure_endpoint = "http://{}:{}/api/developer/structure".format(args.host, args.port)
    behavior_endpoint = "http://{}:{}/api/developer/structure-behavior".format(args.host, args.port)
    observer = TransitionObserver()
    iteration = 0
    while maximum_iterations is None or iteration < maximum_iterations:
        try:
            playback = fetch_json(endpoint, opener)
            structure = fetch_json(structure_endpoint, opener)
            behavior = fetch_json(behavior_endpoint, opener)
            dashboard = render_dashboard(playback, structure, behavior, observer)
        except Exception as exc:
            dashboard = "BeatBeam M19F Structure Diagnostics\n\nBeatBeam diagnostics unavailable: {}".format(type(exc).__name__)
        if should_clear:
            output.write(CLEAR_AND_HOME)
        output.write(dashboard + "\n")
        output.flush()
        iteration += 1
        if args.once:
            break
        sleep_fn(max(0.25, args.interval_ms / 1000.0))


def main(argv=None, output=None, opener=urlopen, is_tty=None, sleep_fn=time.sleep, maximum_iterations=None):
    parser = argparse.ArgumentParser(description="Read-only BeatBeam VirtualDJ and SongAnalyzer diagnostics")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8781)
    parser.add_argument("--interval-ms", type=int, default=250)
    parser.add_argument("--once", action="store_true", help="Print one copyable snapshot and exit")
    parser.add_argument("--no-clear", action="store_true", help="Keep plain scrolling output for logs")
    args = parser.parse_args(argv)
    run_dashboard(args, output, opener, is_tty, sleep_fn, maximum_iterations)


if __name__ == "__main__":
    main()
