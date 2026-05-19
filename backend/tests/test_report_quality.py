from src.agents.report_quality import check_report_quality


def test_report_quality_detects_duplicate_table_rows() -> None:
    content = """
# Title

## Executive Summary
A summary paragraph that is intentionally long enough to pass minimum paragraph-length checks and provide useful context.

## 1. Market
| Year | Value |
|------|-------|
| 2024 | 10 |
| 2024 | 10 |

## 2. Technology
Another long paragraph that gives enough text for the checker and avoids false negatives.

## 3. Risks
More content.

## 4. Outlook
More content.
""".strip()
    result = check_report_quality("/mnt/user-data/workspace/report.md", content)
    assert not result.ok
    assert "duplicate_table_rows" in result.reasons


def test_report_quality_passes_clean_structure() -> None:
    content = """
# Title

## Executive Summary
A summary paragraph that is intentionally long enough to pass minimum paragraph-length checks and provide useful context.

## 1. Market
Detailed paragraph about the market conditions and current trends that remains sufficiently long for the heuristic to consider it significant.

## 2. Technology
Detailed paragraph about technical developments and model ecosystems that remains sufficiently long for heuristic quality checks.

## 3. Risks
Detailed paragraph about risks and constraints in deployment, governance, and operations that remains sufficiently long.

## 4. Outlook
Detailed paragraph about expected future developments and assumptions.
""".strip()
    result = check_report_quality("/mnt/user-data/workspace/report.md", content)
    assert result.ok
    assert result.reasons == []


def test_report_quality_does_not_require_executive_summary_for_ordinary_markdown() -> None:
    content = """
# Notes

## Findings
| Item | Value |
|------|-------|
| A | 1 |
| A | 1 |
""".strip()
    result = check_report_quality("/mnt/user-data/workspace/notes.md", content)
    assert result.ok
    assert result.reasons == []


def test_report_quality_requires_executive_summary_for_report_artifact() -> None:
    content = """
# Report

## 1. Market
Detailed paragraph about the market conditions and current trends that remains sufficiently long for the heuristic to consider it significant.

## 2. Technology
Detailed paragraph about technical developments and model ecosystems that remains sufficiently long for heuristic quality checks.

## 3. Risks
Detailed paragraph about risks and constraints in deployment, governance, and operations that remains sufficiently long.

## 4. Outlook
Detailed paragraph about expected future developments and assumptions.
""".strip()
    result = check_report_quality("/mnt/user-data/workspace/market-report.md", content)
    assert not result.ok
    assert "missing_required_sections:executive_summary" in result.reasons
