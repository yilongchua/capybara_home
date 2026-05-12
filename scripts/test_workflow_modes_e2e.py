#!/usr/bin/env python3
"""End-to-end workflow smoke test across chat modes.

Runs a direct Capybara Home workflow invocation for:
  - ultra
  - pro
  - reason (alias of thinking)
  - fast (alias of flash)

For each mode, the script sends a test message, streams events to completion,
and validates that:
  1) an ``end`` event is emitted
  2) the final AI response is non-empty

Exit code is non-zero if any mode fails.

Usage:
  python scripts/test_workflow_modes_e2e.py
  python scripts/test_workflow_modes_e2e.py --message "Reply with exactly: OK"
  python scripts/test_workflow_modes_e2e.py --modes ultra,pro,reason,fast --model qwen3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
os.chdir(BACKEND_DIR)
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.client import CapybaraClient  # noqa: E402


MODE_ALIASES = {
    "fast": "flash",
    "reason": "thinking",
}


MODE_CONFIG = {
    "flash": {"thinking_enabled": False, "subagent_enabled": False, "label": "fast"},
    "thinking": {"thinking_enabled": True, "subagent_enabled": False, "label": "reason"},
    "pro": {"thinking_enabled": True, "subagent_enabled": False, "label": "pro"},
    "ultra": {"thinking_enabled": True, "subagent_enabled": True, "label": "ultra"},
}


@dataclass
class ModeResult:
    requested_mode: str
    normalized_mode: str
    ok: bool
    duration_seconds: float
    thread_id: str
    event_types: list[str]
    ai_message_count: int
    tool_event_count: int
    final_ai_text: str
    error: str | None = None


def _normalize_mode(mode: str) -> str:
    key = mode.strip().lower()
    if key in MODE_ALIASES:
        return MODE_ALIASES[key]
    return key


def _run_mode(
    client: CapybaraClient,
    *,
    requested_mode: str,
    message: str,
    model_name: str | None,
    recursion_limit: int,
) -> ModeResult:
    normalized_mode = _normalize_mode(requested_mode)
    if normalized_mode not in MODE_CONFIG:
        return ModeResult(
            requested_mode=requested_mode,
            normalized_mode=normalized_mode,
            ok=False,
            duration_seconds=0.0,
            thread_id="",
            event_types=[],
            ai_message_count=0,
            tool_event_count=0,
            final_ai_text="",
            error=f"Unsupported mode '{requested_mode}'. Supported: ultra, pro, reason, fast.",
        )

    cfg = MODE_CONFIG[normalized_mode]
    thread_id = f"e2e-mode-{normalized_mode}-{uuid.uuid4().hex[:8]}"

    started = time.perf_counter()
    event_types: list[str] = []
    ai_texts: list[str] = []
    tool_event_count = 0
    saw_end = False

    try:
        stream_kwargs: dict[str, Any] = {
            "thinking_enabled": cfg["thinking_enabled"],
            "subagent_enabled": cfg["subagent_enabled"],
            "recursion_limit": recursion_limit,
        }
        if model_name:
            stream_kwargs["model_name"] = model_name

        for event in client.stream(message, thread_id=thread_id, **stream_kwargs):
            event_types.append(event.type)
            if event.type == "end":
                saw_end = True
            elif event.type == "messages-tuple":
                etype = event.data.get("type")
                if etype == "ai":
                    text = str(event.data.get("content") or "").strip()
                    if text:
                        ai_texts.append(text)
                elif etype == "tool":
                    tool_event_count += 1

        duration = time.perf_counter() - started
        final_ai_text = ai_texts[-1] if ai_texts else ""
        ok = saw_end and bool(final_ai_text)
        err = None
        if not saw_end:
            err = "Stream ended without an 'end' event."
        elif not final_ai_text:
            err = "No non-empty final AI response was produced."

        return ModeResult(
            requested_mode=requested_mode,
            normalized_mode=normalized_mode,
            ok=ok,
            duration_seconds=duration,
            thread_id=thread_id,
            event_types=event_types,
            ai_message_count=len(ai_texts),
            tool_event_count=tool_event_count,
            final_ai_text=final_ai_text,
            error=err,
        )
    except Exception as exc:
        duration = time.perf_counter() - started
        return ModeResult(
            requested_mode=requested_mode,
            normalized_mode=normalized_mode,
            ok=False,
            duration_seconds=duration,
            thread_id=thread_id,
            event_types=event_types,
            ai_message_count=len(ai_texts),
            tool_event_count=tool_event_count,
            final_ai_text=ai_texts[-1] if ai_texts else "",
            error=str(exc),
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Capybara Home mode-based workflow E2E smoke tests.")
    parser.add_argument(
        "--modes",
        default="ultra,pro,reason,fast",
        help="Comma-separated modes. Supported names: ultra, pro, reason, fast.",
    )
    parser.add_argument(
        "--message",
        default="Reply with exactly: E2E_WORKFLOW_OK",
        help="Test message to send to each mode.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Optional model_name override from config.yaml.",
    )
    parser.add_argument(
        "--recursion-limit",
        type=int,
        default=200,
        help="Runnable recursion limit for each workflow run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    if not modes:
        print("No modes provided.")
        return 2

    client = CapybaraClient(thinking_enabled=True)
    results: list[ModeResult] = []

    print(f"Running workflow E2E test for modes: {', '.join(modes)}")
    for mode in modes:
        print(f"\n[RUN] mode={mode}")
        result = _run_mode(
            client,
            requested_mode=mode,
            message=args.message,
            model_name=args.model,
            recursion_limit=args.recursion_limit,
        )
        results.append(result)
        if result.ok:
            print(
                f"[PASS] mode={mode} normalized={result.normalized_mode} "
                f"duration={result.duration_seconds:.2f}s ai_messages={result.ai_message_count}"
            )
            print(f"       final_ai_text={result.final_ai_text[:160]}")
        else:
            print(
                f"[FAIL] mode={mode} normalized={result.normalized_mode} "
                f"duration={result.duration_seconds:.2f}s error={result.error}"
            )

    passed = sum(1 for r in results if r.ok)
    failed = len(results) - passed

    print("\n=== Summary ===")
    print(f"passed={passed} failed={failed} total={len(results)}")

    if args.json:
        payload = {
            "passed": passed,
            "failed": failed,
            "total": len(results),
            "results": [asdict(r) for r in results],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
