"""Tests for phase-B trajectory replay harness."""

from pathlib import Path

from src.config.benchmarks_config import BenchmarksConfig, set_benchmarks_config
from tests.evals.replay_runner import assert_replay_fixture, run_benchmark_suite


def test_phase_b_replay_fixture_passes():
    fixture = Path("tests/evals/fixtures/phase_b_replay_fixture.json")
    assert fixture.exists()
    assert_replay_fixture(fixture)


def test_benchmark_suite_writes_scorecard(tmp_path: Path):
    set_benchmarks_config(
        BenchmarksConfig(
            enabled=True,
            suite="coding",
            report_dir=str(tmp_path),
            fail_on_regression=True,
            regression_threshold=0.5,
        )
    )
    manifest = Path("tests/evals/fixtures/phase_c_benchmark_manifest.json")
    report = tmp_path / "benchmark_report.json"
    scorecard = run_benchmark_suite(manifest, report_path=report)
    assert scorecard["suite"] == "coding"
    assert report.exists()
