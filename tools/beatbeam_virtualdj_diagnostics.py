#!/usr/bin/env python3
"""Read-only developer console for BeatBeam's generic VirtualDJ playback state."""

import argparse
import json
import time
from urllib.request import urlopen


def value(mapping, key):
    return "-" if not mapping or mapping.get(key) is None else str(mapping[key])


def summary(mapping, key):
    stats = (mapping or {}).get(key) or {}
    if not stats or not stats.get("count"):
        return "-"
    return "mean {mean:.1f} | p50 {p50:.1f} | p95 {p95:.1f} | max {max:.1f} ms".format(**stats)


def print_state(state):
    virtualdj = state.get("virtualdj") or {}
    beatbeam = state.get("beatbeam") or {}
    delta = state.get("delta") or {}
    timing = state.get("timing") or {}
    metrics = state.get("metrics") or {}
    source_metrics = virtualdj.get("metrics") or {}
    print("\x1b[2J\x1b[H", end="")
    print("BeatBeam VirtualDJ developer diagnostics")
    print("Source: {} | availability: {} | transport: {} | selection: {}".format(
        value(state, "source"), value(state, "availability"), value(state, "transport_state"), value(state, "selection")
    ))
    print()
    print("VirtualDJ:")
    print("  Track: {}".format(value(virtualdj, "track_path")))
    print("  Position: {} ms | BPM: {} | BeatNumber: {} | Bar: {}".format(
        value(virtualdj, "position_milliseconds"), value(virtualdj, "bpm"),
        value(virtualdj, "beat_number"), value(virtualdj, "bar_number")
    ))
    print("BeatBeam:")
    print("  Track: {}".format(value(beatbeam, "track_path")))
    print("  EstimatedPosition: {} ms | BPM: {} | BeatNumber: {} | Bar: {}".format(
        value(beatbeam, "estimated_position_milliseconds"), value(beatbeam, "bpm"),
        value(beatbeam, "beat_number"), value(beatbeam, "bar_number")
    ))
    print("Delta:")
    print("  Local extrapolation: {} ms | Beat agreement: {} | Bar agreement: {}".format(
        value(delta, "position_milliseconds"), value(delta, "beat_agreement"), value(delta, "bar_agreement")
    ))
    print("  Probe raw / compensated: {} / {} ms".format(
        value(delta, "raw_received_position_milliseconds"), value(delta, "compensated_position_milliseconds")
    ))
    print("Timing:")
    print("  Clock: {} | sample age at receive: {} ms | alignment: {}".format(
        value(timing, "source_clock"), value(timing, "sample_age_at_receive_milliseconds"), value(timing, "alignment")
    ))
    query_timings = timing.get("query_timings") or []
    if query_timings:
        query_text = ", ".join("{}={} ms".format(value(item, "field"), value(item, "round_trip_milliseconds")) for item in query_timings)
        print("  Query RTT: {}".format(query_text))
    print("Metrics:")
    print("  VirtualDJ snapshot/query avg/p95: {} / {} / {} ms | source failures: {}".format(
        value(source_metrics, "snapshot_latency_milliseconds"),
        value(source_metrics, "query_average_latency_milliseconds"),
        value(source_metrics, "query_p95_latency_milliseconds"),
        value(source_metrics, "error_count"),
    ))
    print("  Snapshot interval: {} ms | extrapolation: {} ms | discontinuities: {} | reconnects: {}".format(
        value(metrics, "snapshot_interval_milliseconds"), value(metrics, "extrapolation_milliseconds"),
        value(metrics, "discontinuities"), value(metrics, "reconnects")
    ))
    print("  Accepted/invalid BeatBeam snapshots: {} / {}".format(
        value(metrics, "accepted_snapshots"), value(metrics, "invalid_snapshots")
    ))
    print("  Position probe raw error: {}".format(summary(metrics, "raw_position_delta_milliseconds")))
    print("  Position probe compensated error: {}".format(summary(metrics, "compensated_position_delta_milliseconds")))
    if state.get("last_discontinuity"):
        print("Last discontinuity: {}".format(state["last_discontinuity"]))


def main():
    parser = argparse.ArgumentParser(description="Read-only BeatBeam VirtualDJ timing diagnostics")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8781)
    parser.add_argument("--interval-ms", type=int, default=250)
    args = parser.parse_args()
    endpoint = "http://{}:{}/api/developer/playback".format(args.host, args.port)
    while True:
        try:
            with urlopen(endpoint, timeout=1.0) as response:
                print_state(json.loads(response.read().decode("utf-8")))
        except Exception as exc:
            print("BeatBeam diagnostics unavailable: {}".format(type(exc).__name__))
        time.sleep(max(0.1, args.interval_ms / 1000.0))


if __name__ == "__main__":
    main()
