#!/usr/bin/env python3
"""Run prompt-tuning cycles with minimal human intervention.

Usage:
    cd prompt-tunning
    python test_prompt.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"
CONFIG_PATH = REPO_ROOT / "config.yaml"
DEFAULT_GATEWAY_URL = os.getenv("CAPYBARA_GATEWAY_URL", "http://localhost:8001")

sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("CAPYBARA_HOME", str(BACKEND_DIR / ".capybara-home"))
os.environ.setdefault("CAPYBARA_PROMPT_LOGGING_ENABLED", "1")

from src.agents.checkpointer import reset_checkpointer  # noqa: E402
from src.agents.memory.updater import clear_memory  # noqa: E402
from src.client import CapybaraClient  # noqa: E402
from src.config.paths import get_paths  # noqa: E402

PROMPTS: list[dict[str, str]] = [
    {
        "difficulty": "easy",
        "text": "Use web search to plan, analyse, and cross analyse three concise sources about prompt tuning loops. Return a short comparison and one improved prompt.",
    },
    {
        "difficulty": "easy",
        "text": "Run a web search, plan a simple evaluation checklist, analyse the top findings, and cross analyse the checklist against one weak prompt example.",
    },
    {
        "difficulty": "easy",
        "text": "Use web search to plan a beginner-friendly prompt refinement workflow, analyse the risks of vague instructions, and cross analyse two fixes.",
    },
    {
        "difficulty": "easy-medium",
        "text": "Use web search, then plan a lightweight A/B prompt test. Analyse the expected outcomes and cross analyse which version is clearer for autonomous agents.",
    },
    {
        "difficulty": "medium",
        "text": "Perform web search research on self-improving prompts, plan an iterative loop, analyse failure modes, and cross analyse how memory reset changes results.",
    },
    {
        "difficulty": "medium",
        "text": "Use web search to identify prompt evaluation metrics. Plan a scoring rubric, analyse tradeoffs, and cross analyse rubric quality across simple and complex tasks.",
    },
    {
        "difficulty": "medium",
        "text": "Use web search to plan a prompt-tuning experiment for plan mode versus work mode. Analyse mode behavior and cross analyse when auto mode is useful.",
    },
    {
        "difficulty": "medium",
        "text": "Use web search on agent benchmark design, plan a 3-cycle benchmark, analyse expected variance, and cross analyse how prompt difficulty affects output quality.",
    },
    {
        "difficulty": "medium-hard",
        "text": "Use web search to plan an automated prompt extraction pipeline. Analyse where prompt logs may be incomplete and cross analyse mitigation strategies.",
    },
    {
        "difficulty": "medium-hard",
        "text": "Use web search to plan a prompt suite for tool-using agents, analyse tool-call bias, and cross analyse prompts that encourage versus discourage unnecessary tools.",
    },
    {
        "difficulty": "hard",
        "text": "Use web search to plan a multi-agent prompt improvement protocol. Analyse conflict resolution between agents and cross analyse quality gates for final prompts.",
    },
    {
        "difficulty": "hard",
        "text": "Use web search to plan a no-human-intervention prompt tuning loop. Analyse autonomous failure recovery and cross analyse rollback policies after bad runs.",
    },
    {
        "difficulty": "hard",
        "text": "Use web search to plan an experiment that isolates system prompt effects. Analyse confounders and cross analyse outputs before and after memory deletion.",
    },
    {
        "difficulty": "hard",
        "text": "Use web search to plan a prompt regression suite for coding agents. Analyse correctness, safety, and latency, then cross analyse scoring conflicts.",
    },
    {
        "difficulty": "hard",
        "text": "Use web search to plan a prompt-tuning dataset schema. Analyse metadata needed for reproducibility and cross analyse JSON record designs.",
    },
    {
        "difficulty": "expert",
        "text": "Use web search to plan a closed-loop optimizer for prompts. Analyse exploration versus exploitation and cross analyse three scheduling strategies.",
    },
    {
        "difficulty": "expert",
        "text": "Use web search to plan a prompt tuning process for long-context agents. Analyse compaction effects and cross analyse prompt logs across cycles.",
    },
    {
        "difficulty": "expert",
        "text": "Use web search to plan an evaluation harness for autonomous prompt repair. Analyse error taxonomies and cross analyse repair prompts by severity.",
    },
    {
        "difficulty": "expert",
        "text": "Use web search to plan a reproducible prompt-tuning study. Analyse sampling bias, cross analyse run isolation methods, and recommend audit artifacts.",
    },
    {
        "difficulty": "expert-plus",
        "text": "Use web search to plan an end-to-end autonomous prompt fine tuning loop. Analyse memory, chat deletion, and timing controls, then cross analyse the strongest architecture.",
    },
]


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def request_without_body(method: str, url: str, timeout: float = 5.0) -> dict[str, Any]:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def clear_gateway_state(gateway_url: str) -> dict[str, Any]:
    base = gateway_url.rstrip("/")
    results: dict[str, Any] = {}
    memory_url = f"{base}/api/memory/clear?{urllib.parse.urlencode({'scope': 'global'})}"
    threads_url = f"{base}/api/threads"

    try:
        results["memory"] = request_without_body("POST", memory_url)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        results["memory_error"] = str(exc)

    try:
        results["threads"] = request_without_body("DELETE", threads_url, timeout=15.0)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        results["threads_error"] = str(exc)

    return results


def clear_local_state() -> dict[str, Any]:
    results: dict[str, Any] = {}

    try:
        results["memory"] = clear_memory(scope="global", source="prompt-tunning")
    except Exception as exc:  # noqa: BLE001 - cleanup should keep the loop moving
        results["memory_error"] = str(exc)

    threads_dir = get_paths().base_dir / "threads"
    try:
        shutil.rmtree(threads_dir, ignore_errors=True)
        results["threads_dir_removed"] = str(threads_dir)
    except Exception as exc:  # noqa: BLE001
        results["threads_error"] = str(exc)

    try:
        reset_checkpointer()
        results["checkpointer_reset"] = True
    except Exception as exc:  # noqa: BLE001
        results["checkpointer_error"] = str(exc)

    return results


def copy_prompt_logs(thread_id: str, prompt_dir: Path, cycle_id: int) -> list[dict[str, str]]:
    source_dir = get_paths().sandbox_work_dir(thread_id) / ".prompts"
    copied: list[dict[str, str]] = []
    if not source_dir.exists():
        return copied

    for index, source_path in enumerate(sorted(source_dir.iterdir()), start=1):
        if not source_path.is_file():
            continue
        target_path = prompt_dir / f"cycle_{cycle_id}_promptlog_{index:03d}{source_path.suffix}"
        shutil.copy2(source_path, target_path)
        copied.append(
            {
                "source": str(source_path),
                "copied_to": str(target_path.relative_to(SCRIPT_DIR)),
            }
        )
    return copied


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def run_prompt(client: CapybaraClient, *, cycle_id: int, prompt_id: int, prompt: dict[str, str]) -> None:
    prompt_dir = SCRIPT_DIR / f"prompt_id_{prompt_id}"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    thread_id = f"prompt_tunning_p{prompt_id:02d}_c{cycle_id}_{uuid.uuid4().hex[:8]}"
    purpose = f"cycle_{cycle_id}_prompt_{prompt_id}"
    metadata_path = prompt_dir / f"cycle_{cycle_id}_metadata.json"
    os.environ["CAPYBARA_PROMPT_LOG_PURPOSE"] = purpose

    metadata: dict[str, Any] = {
        "cycle_id": cycle_id,
        "prompt_id": prompt_id,
        "thread_id": thread_id,
        "initial_prompt": prompt["text"],
        "difficulty": prompt["difficulty"],
        "mode": "work",
        "auto_mode": True,
        "prompt_log_purpose": purpose,
        "started_at": utc_now(),
        "status": "running",
    }
    write_json(metadata_path, metadata)

    try:
        response = client.chat(
            prompt["text"],
            thread_id=thread_id,
            auto_mode=True,
            mode="work",
            plan_mode=False,
            subagent_enabled=True,
            recursion_limit=1000,
        )
        metadata["status"] = "completed"
        metadata["response_preview"] = response[:2000]
    except Exception as exc:  # noqa: BLE001 - record and continue to next prompt
        metadata["status"] = "failed"
        metadata["error"] = str(exc)
        metadata["traceback"] = traceback.format_exc()
    finally:
        metadata["completed_at"] = utc_now()
        metadata["copied_prompt_logs"] = copy_prompt_logs(thread_id, prompt_dir, cycle_id)
        write_json(metadata_path, metadata)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run 20 prompt-tuning prompts for 3 cycles.")
    parser.add_argument("--cycles", type=int, default=3, help="Number of full 20-prompt cycles.")
    parser.add_argument("--delay-seconds", type=float, default=20.0, help="Delay after each prompt completes.")
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL, help="Gateway URL used for best-effort memory/thread cleanup.")
    parser.add_argument("--skip-gateway-cleanup", action="store_true", help="Only clear local embedded-client state between cycles.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = str(CONFIG_PATH) if CONFIG_PATH.exists() else None
    client = CapybaraClient(
        config_path=config_path,
        thinking_enabled=True,
        subagent_enabled=True,
        plan_mode=False,
        auto_mode=True,
    )

    total_runs = args.cycles * len(PROMPTS)
    completed_runs = 0
    print(f"Starting {total_runs} prompt-tuning runs in {SCRIPT_DIR}")

    for cycle_id in range(1, args.cycles + 1):
        print(f"\nCycle {cycle_id}/{args.cycles}")
        for prompt_id, prompt in enumerate(PROMPTS, start=1):
            print(f"  Running prompt {prompt_id:02d}/20 ({prompt['difficulty']})")
            run_prompt(client, cycle_id=cycle_id, prompt_id=prompt_id, prompt=prompt)
            completed_runs += 1
            if completed_runs < total_runs and args.delay_seconds > 0:
                print(f"  Waiting {args.delay_seconds:g}s before next prompt...")
                time.sleep(args.delay_seconds)

        cleanup: dict[str, Any] = {"cycle_id": cycle_id, "started_at": utc_now()}
        if not args.skip_gateway_cleanup:
            cleanup["gateway"] = clear_gateway_state(args.gateway_url)
        cleanup["local"] = clear_local_state()
        cleanup["completed_at"] = utc_now()
        write_json(SCRIPT_DIR / f"cycle_{cycle_id}_cleanup.json", cleanup)
        client.reset_agent()

    print("\nPrompt-tuning loop complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
