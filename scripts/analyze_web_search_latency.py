#!/usr/bin/env python3
"""Summarize web_search latency from trajectory JSONL logs."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def _iter_jsonl(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        if path.is_dir():
            candidates = sorted(path.rglob("*.jsonl"))
        else:
            candidates = [path]
        for candidate in candidates:
            with candidate.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return records


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze web_search duration_ms values from trajectory logs.")
    parser.add_argument("paths", nargs="+", type=Path, help="Trajectory JSONL files or directories containing them.")
    args = parser.parse_args()

    records = _iter_jsonl(args.paths)
    durations: list[float] = []
    timeout_count = 0
    total_ends = 0
    for record in records:
        if record.get("event") != "tool_call_end":
            continue
        payload = record.get("payload") or {}
        if payload.get("tool") != "web_search":
            continue
        total_ends += 1
        if payload.get("timed_out"):
            timeout_count += 1
            continue
        duration_ms = payload.get("duration_ms")
        if isinstance(duration_ms, (int, float)):
            durations.append(float(duration_ms))

    summary = {
        "web_search_tool_calls": total_ends,
        "successful_duration_count": len(durations),
        "timeout_count": timeout_count,
        "timeout_rate": round(timeout_count / total_ends, 4) if total_ends else 0,
        "mean_seconds": round(statistics.mean(durations) / 1000, 2) if durations else 0,
        "p75_seconds": round(_percentile(durations, 0.75) / 1000, 2) if durations else 0,
        "p90_seconds": round(_percentile(durations, 0.90) / 1000, 2) if durations else 0,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
