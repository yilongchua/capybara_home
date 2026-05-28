"""Tool catalog auditor.

Usage:
    PYTHONPATH=. uv run python -m src.tools.audit
    PYTHONPATH=. uv run python -m src.tools.audit --mode work --phase approved --vision --subagent
    PYTHONPATH=. uv run python -m src.tools.audit --mode plan

Renders a Markdown table of the LLM-facing tool surface for the given
mode/phase/vision/subagent triple. The mode argument also selects which
catalog file (`internal_tools_plan.json` vs `internal_tools_work.json`) is
loaded. Use this to review JSON edits before committing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.tools.loader import get_tool_policy, load_tool_definitions
from src.tools.tools import (
    INTERNAL_TOOLS_PLAN_JSON,
    INTERNAL_TOOLS_WORK_JSON,
    get_available_tools,
)


def _catalog_path_for_mode(mode: str | None) -> Path:
    if mode == "plan":
        return INTERNAL_TOOLS_PLAN_JSON
    return INTERNAL_TOOLS_WORK_JSON


def _format_row(tool) -> str:
    policy = get_tool_policy(tool)
    if policy is None:
        return f"| `{tool.name}` | (legacy) | — | — | — | — | {(tool.description or '').splitlines()[0][:80]} |"
    mode = ",".join(policy.mode) or "—"
    phase = ",".join(policy.phase) or "—"
    flags = []
    if policy.requires_vision:
        flags.append("vision")
    if policy.requires_subagent_enabled:
        flags.append("subagent")
    if policy.deprecated:
        flags.append("deprecated")
    return (
        f"| `{policy.name}` | {policy.endpoint} | {mode} | {phase} | "
        f"{','.join(policy.groups) or '—'} | {','.join(flags) or '—'} | "
        f"{policy.description.splitlines()[0][:80]} |"
    )


def render(mode: str | None, phase: str | None, supports_vision: bool, subagent_enabled: bool) -> str:
    catalog_path = _catalog_path_for_mode(mode)
    defns = load_tool_definitions(catalog_path)
    tools = get_available_tools(
        include_mcp=False,
        subagent_enabled=subagent_enabled,
        mode=mode,
    )

    lines: list[str] = []
    lines.append(f"# Tool audit (mode={mode or 'any'}, phase={phase or 'any'}, vision={supports_vision}, subagent={subagent_enabled})")
    lines.append("")
    lines.append(f"`{catalog_path.name}` entries: **{len(defns)}**")
    lines.append(f"Resolved catalog size: **{len(tools)}**")
    lines.append("")
    lines.append("| name | endpoint | mode | phase | groups | flags | description |")
    lines.append("| ---- | -------- | ---- | ----- | ------ | ----- | ----------- |")
    for tool in sorted(tools, key=lambda t: t.name):
        lines.append(_format_row(tool))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit the resolved tool catalog.")
    parser.add_argument("--mode", choices=["plan", "work", "auto"], default=None)
    parser.add_argument("--phase", choices=["draft", "approved"], default=None)
    parser.add_argument("--vision", action="store_true", help="Pretend the active model supports vision.")
    parser.add_argument("--subagent", action="store_true", help="Include subagent delegation tools (task).")
    args = parser.parse_args(argv)
    print(render(args.mode, args.phase, args.vision, args.subagent))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
