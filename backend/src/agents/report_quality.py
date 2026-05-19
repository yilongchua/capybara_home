"""Deterministic checks for long-form markdown report artifacts."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass


@dataclass
class QualityCheckResult:
    ok: bool
    reasons: list[str]


def _is_report_target(path: str) -> bool:
    lowered = path.lower()
    if not lowered.endswith(".md"):
        return False
    filename = lowered.rsplit("/", 1)[-1]
    return "report" in filename


def _extract_heading_numbers(lines: list[str]) -> list[str]:
    nums: list[str] = []
    pattern = re.compile(r"^#{1,6}\s+([0-9]+(?:\.[0-9]+)*)")
    for line in lines:
        m = pattern.match(line.strip())
        if m:
            nums.append(m.group(1))
    return nums


def _normalized_paragraphs(text: str) -> list[str]:
    paras = [p.strip() for p in text.split("\n\n")]
    out: list[str] = []
    for p in paras:
        if len(p) < 120:
            continue
        p_norm = re.sub(r"\s+", " ", p).strip().lower()
        out.append(p_norm)
    return out


def _table_rows(text: str) -> list[str]:
    rows: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|") and len(s) > 3:
            # Ignore markdown separator rows
            if re.fullmatch(r"\|[-:| ]+\|", s):
                continue
            rows.append(s)
    return rows


def check_report_quality(path: str, content: str) -> QualityCheckResult:
    if not _is_report_target(path):
        return QualityCheckResult(ok=True, reasons=[])

    reasons: list[str] = []
    lines = content.splitlines()

    # Duplicate table rows
    row_counts = Counter(_table_rows(content))
    duplicates = [r for r, n in row_counts.items() if n > 1]
    if duplicates:
        reasons.append("duplicate_table_rows")

    # Heading numbering inconsistencies (duplicate numbering token)
    heading_nums = _extract_heading_numbers(lines)
    if heading_nums:
        dup_nums = [n for n, c in Counter(heading_nums).items() if c > 1]
        if dup_nums:
            reasons.append("heading_numbering_inconsistency")

    # Repeated long paragraphs
    para_counts = Counter(_normalized_paragraphs(content))
    repeated_paras = [p for p, n in para_counts.items() if n > 1]
    if repeated_paras:
        reasons.append("repeated_section_blocks")

    # Required sections for report-like output
    top_level = [line.strip().lower() for line in lines if line.startswith("## ")]
    has_exec_summary = any("executive summary" in h for h in top_level)
    if not has_exec_summary:
        reasons.append("missing_required_sections:executive_summary")
    if len(top_level) < 4:
        reasons.append("missing_required_sections:insufficient_sections")

    return QualityCheckResult(ok=len(reasons) == 0, reasons=reasons)
