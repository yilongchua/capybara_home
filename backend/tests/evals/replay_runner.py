"""Phase-B trajectory replay helpers."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.config.benchmarks_config import get_benchmarks_config


def load_trajectory(path: Path) -> list[dict[str, Any]]:
    """Load JSONL trajectory records."""
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            records.append(payload)
    return records


def assert_replay_fixture(fixture_path: Path) -> None:
    """Replay a fixture and validate required/forbidden events."""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    trajectory_file = fixture_path.parent / fixture["trajectory_file"]
    events = load_trajectory(trajectory_file)
    event_names = [event.get("event") for event in events]
    for required in fixture.get("required_events", []):
        assert required in event_names, f"Missing required event: {required}"
    for forbidden in fixture.get("forbidden_events", []):
        assert forbidden not in event_names, f"Forbidden event present: {forbidden}"


def run_benchmark_suite(manifest_path: Path, *, report_path: Path | None = None) -> dict[str, Any]:
    """Run a benchmark suite manifest over replay fixtures and emit a scorecard."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fixtures = manifest.get("fixtures", []) or []
    baseline_pass_rate = float(manifest.get("baseline_pass_rate", 0.0))
    suite_name = str(manifest.get("name") or "benchmark")

    total = 0
    passed = 0
    details: list[dict[str, Any]] = []
    for fixture_item in fixtures:
        relative = fixture_item.get("path") if isinstance(fixture_item, dict) else fixture_item
        if not isinstance(relative, str):
            continue
        total += 1
        fixture_path = manifest_path.parent / relative
        try:
            assert_replay_fixture(fixture_path)
            passed += 1
            details.append({"fixture": relative, "status": "pass"})
        except Exception as exc:
            details.append({"fixture": relative, "status": "fail", "error": str(exc)})

    pass_rate = (passed / total) if total else 0.0
    regression = max(0.0, baseline_pass_rate - pass_rate)
    cfg = get_benchmarks_config()
    status = "pass"
    if cfg.fail_on_regression and regression > cfg.regression_threshold:
        status = "fail"
    scorecard = {
        "suite": suite_name,
        "ts": time.time(),
        "total": total,
        "passed": passed,
        "pass_rate": pass_rate,
        "baseline_pass_rate": baseline_pass_rate,
        "regression": regression,
        "status": status,
        "details": details,
    }
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")
    return scorecard
