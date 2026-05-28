"""Drift validator: every entry in the per-mode tool catalogs must match its handler.

The catalog is now split into `internal_tools_plan.json` and
`internal_tools_work.json` so the LLM-facing description for a shared tool can
differ between plan and work without coupling the two surfaces. Both files
must independently pass the same drift / sanity checks, so every test here
is parametrised across whichever catalog files exist on disk.

Failures here mean the JSON description has diverged from the actual handler
signature — either rename the JSON parameter or update the handler. CI runs
this on every PR to keep the LLM-facing surface honest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tools.loader import build_structured_tool, load_tool_definitions, schema_drift_report

TOOLS_DIR = Path(__file__).resolve().parents[1] / "src" / "tools"
CATALOG_PATHS = [
    p
    for p in (
        TOOLS_DIR / "internal_tools_plan.json",
        TOOLS_DIR / "internal_tools_work.json",
    )
    if p.exists()
]


def _catalog_id(path: Path) -> str:
    return path.name


@pytest.fixture(scope="module", params=CATALOG_PATHS, ids=_catalog_id)
def definitions(request):
    defns = load_tool_definitions(request.param)
    assert defns, f"{request.param.name} is empty — Phase 2 migration not yet applied."
    return defns


def test_internal_tool_names_are_unique(definitions) -> None:
    names = [defn.name for defn in definitions]
    assert len(names) == len(set(names)), f"Duplicate tool names: {names}"


def test_all_handlers_resolve_to_basetool(definitions) -> None:
    for defn in definitions:
        # build_structured_tool raises ToolDefinitionError on any handler issue.
        tool = build_structured_tool(defn)
        assert tool.name == defn.name


def test_no_schema_drift_against_handlers(definitions) -> None:
    drift: list[str] = []
    for defn in definitions:
        tool = build_structured_tool(defn)
        drift.extend(schema_drift_report(defn, tool))
    assert not drift, "Schema drift detected:\n  - " + "\n  - ".join(drift)


def test_descriptions_are_non_trivial(definitions) -> None:
    """Doc 03 calls out terse descriptions on recall/setup_agent/write_todos. Guard against regression."""
    too_short: list[str] = []
    for defn in definitions:
        if len(defn.description.strip()) < 60:
            too_short.append(f"{defn.name}: {len(defn.description)} chars")
    assert not too_short, "Tool descriptions must be at least one sentence: " + ", ".join(too_short)


def test_every_tool_documents_return_value(definitions) -> None:
    missing = [defn.name for defn in definitions if not (defn.returns or "").strip()]
    assert not missing, f"Missing 'returns' documentation on: {missing}"


def test_every_tool_has_at_least_one_example(definitions) -> None:
    missing = [defn.name for defn in definitions if not defn.examples]
    assert not missing, f"Missing 'examples' on: {missing}"


def test_plan_catalog_excludes_execution_tools() -> None:
    """Plan-mode catalog must not expose execution tools (`bash`, `write_file`,
    `str_replace`, `task`). PhaseToolFilterMiddleware will hide them at runtime
    anyway, but keeping them out of the plan file is the whole point of the split.
    """
    plan_path = TOOLS_DIR / "internal_tools_plan.json"
    if not plan_path.exists():
        pytest.skip("internal_tools_plan.json not present")
    plan_defns = load_tool_definitions(plan_path)
    forbidden = {"bash", "write_file", "str_replace", "task"}
    leaked = {defn.name for defn in plan_defns} & forbidden
    assert not leaked, f"Execution tools leaked into plan catalog: {sorted(leaked)}"


def test_work_catalog_includes_execution_tools() -> None:
    """Work-mode catalog must expose the full execution surface."""
    work_path = TOOLS_DIR / "internal_tools_work.json"
    if not work_path.exists():
        pytest.skip("internal_tools_work.json not present")
    work_defns = load_tool_definitions(work_path)
    required = {"bash", "write_file", "str_replace", "task"}
    present = {defn.name for defn in work_defns}
    missing = required - present
    assert not missing, f"Execution tools missing from work catalog: {sorted(missing)}"
