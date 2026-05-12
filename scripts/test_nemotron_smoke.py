#!/usr/bin/env python3
"""Simple Nemotron smoke test.

Checks both:
1) direct OpenAI-compatible call to local backend
2) Capybara Home workflow call with model alias from config

Usage:
  python scripts/test_nemotron_smoke.py
  python scripts/test_nemotron_smoke.py --model-name nemotron
  python scripts/test_nemotron_smoke.py --direct-only
  python scripts/test_nemotron_smoke.py --workflow-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"


def _post_json(url: str, payload: dict, headers: dict[str, str] | None = None, timeout: float = 120.0) -> tuple[int, dict]:
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=req_headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        parsed: dict = {"raw": body}
        try:
            parsed = json.loads(body)
        except Exception:
            pass
        return err.code, parsed


def run_direct(model_id: str, prompt: str) -> int:
    base_url = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:1234/v1").rstrip("/")
    url = f"{base_url}/chat/completions"

    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 128,
    }

    print(f"[direct] POST {url} model={model_id}")
    status, data = _post_json(url, payload, headers={"Authorization": "Bearer lm-studio"})
    text = ""
    if isinstance(data, dict):
        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            text = str(((choices[0].get("message") or {}).get("content") or "")).strip()

    print(f"[direct] status={status}")
    if text:
        print(f"[direct] reply={text[:240]}")
        return 0

    print(f"[direct] failed body={json.dumps(data, ensure_ascii=False)[:600]}")
    return 1


def run_workflow(model_name: str, prompt: str) -> int:
    os.chdir(BACKEND_DIR)
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    try:
        from src.client import CapybaraClient  # noqa: WPS433,E402
    except Exception as exc:
        print("[workflow] import_error=failed to load Capybara Home backend runtime")
        print(f"[workflow] details={exc}")
        print("[workflow] hint=run with: cd backend && uv run ../scripts/test_nemotron_smoke.py --workflow-only")
        return 1

    client = CapybaraClient(thinking_enabled=False)
    thread_id = f"nemotron-smoke-{uuid.uuid4().hex[:8]}"

    print(f"[workflow] thread_id={thread_id} model_name={model_name}")
    final_ai = ""
    saw_end = False
    try:
        for event in client.stream(
            prompt,
            thread_id=thread_id,
            model_name=model_name,
            thinking_enabled=False,
            subagent_enabled=False,
            recursion_limit=120,
        ):
            if event.type == "messages-tuple" and event.data.get("type") == "ai":
                content = str(event.data.get("content") or "").strip()
                if content:
                    final_ai = content
            elif event.type == "end":
                saw_end = True

        if saw_end and final_ai:
            print(f"[workflow] reply={final_ai[:240]}")
            return 0

        print(f"[workflow] failed saw_end={saw_end} final_ai={bool(final_ai)}")
        return 1
    except Exception as exc:
        print(f"[workflow] exception={exc}")
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simple Nemotron smoke test.")
    parser.add_argument("--model-id", default="nvidia/nemotron-3-super", help="Provider model id for direct test")
    parser.add_argument("--model-name", default="nemotron", help="Configured Capybara Home model name for workflow test")
    parser.add_argument("--prompt", default="Reply with exactly: NEMOTRON_OK", help="Prompt text")
    parser.add_argument("--direct-only", action="store_true", help="Run only direct local backend test")
    parser.add_argument("--workflow-only", action="store_true", help="Run only Capybara Home workflow test")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.direct_only and args.workflow_only:
        print("Choose only one of --direct-only or --workflow-only")
        return 2

    failures = 0
    if not args.workflow_only:
        failures += run_direct(args.model_id, args.prompt)
    if not args.direct_only:
        failures += run_workflow(args.model_name, args.prompt)

    if failures == 0:
        print("[summary] PASS")
        return 0

    print("[summary] FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
