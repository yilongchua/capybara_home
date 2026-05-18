#!/usr/bin/env python3
"""Run prompt-tuning cycles with minimal human intervention.

Usage:
    cd prompt-tunning
    python test_prompt.py
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
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
from pathlib import Path
from typing import Any

UTC = getattr(dt, "UTC", dt.timezone.utc)  # noqa: UP017 - supports old Python before venv handoff

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"
CONFIG_PATH = REPO_ROOT / "config.yaml"
DEFAULT_GATEWAY_URL = os.getenv("CAPYBARA_GATEWAY_URL", "http://localhost:8001")
DEFAULT_LANGGRAPH_URL = os.getenv("CAPYBARA_LANGGRAPH_URL", "http://localhost:2026/api/langgraph")
DEFAULT_APP_URL = os.getenv("CAPYBARA_APP_URL", "http://localhost:2026")


def ensure_backend_python() -> None:
    """Keep `python test_prompt.py` on the repo's backend environment."""
    if os.getenv("CAPYBARA_PROMPT_TUNNING_REEXEC") == "1":
        return
    backend_python = BACKEND_DIR / ".venv" / "bin" / "python"
    if not backend_python.exists():
        return
    if Path(sys.executable).resolve() == backend_python.resolve():
        return

    os.environ["CAPYBARA_PROMPT_TUNNING_REEXEC"] = "1"
    os.execv(str(backend_python), [str(backend_python), *sys.argv])


ensure_backend_python()
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
        "text": "I'm thinking of taking a 12 day trip to Greece with my partner in September. Can you make a realistic itinerary with places to stay, travel time between islands, and a rough budget?",
    },
    {
        "difficulty": "easy",
        "text": "What is actually happening with the Iran war right now? Give me a clear current-state analysis, the main actors, what changed recently, and what could happen next.",
    },
    {
        "difficulty": "easy",
        "text": "Can you research crystals that people use for karma protection, spiritual protection, and bad energy? I want beginner-friendly explanations, not just a list of names.",
    },
    {
        "difficulty": "easy-medium",
        "text": "I want to buy a standing desk for a small apartment. Compare a few good options, explain what specs matter, and tell me what you would choose under $400.",
    },
    {
        "difficulty": "medium",
        "text": "Help me plan a 30 day routine to get better sleep and reduce phone scrolling at night. Include practical steps, what to track, and how to adjust if I miss days.",
    },
    {
        "difficulty": "medium",
        "text": "I'm confused about whether renting or buying is smarter in my city. Walk me through the numbers I need, the non-financial tradeoffs, and a simple decision framework.",
    },
    {
        "difficulty": "medium",
        "text": "Can you compare intermittent fasting, calorie counting, and just eating more whole foods for weight loss? I want the pros, cons, risks, and who each approach fits.",
    },
    {
        "difficulty": "medium",
        "text": "Plan a weekend in Tokyo for someone who likes food, bookstores, quiet neighborhoods, and one nice cocktail bar. Keep it realistic and avoid overpacked tourist routes.",
    },
    {
        "difficulty": "medium-hard",
        "text": "Do a balanced deep dive on whether AI will replace junior software engineers. Include the strongest arguments on both sides, recent evidence, and what juniors should do now.",
    },
    {
        "difficulty": "medium-hard",
        "text": "I'm starting a small home coffee setup. Compare espresso, pour-over, AeroPress, and moka pot for taste, cost, learning curve, and daily convenience.",
    },
    {
        "difficulty": "hard",
        "text": "Research the current state of the Ukraine war and explain it like a geopolitical brief: front lines, military capacity, diplomacy, sanctions, and realistic scenarios for the next 6 months.",
    },
    {
        "difficulty": "hard",
        "text": "I want to build an emergency kit for a family of four in an apartment. Make a prioritized checklist, explain quantities, and separate must-haves from nice-to-haves.",
    },
    {
        "difficulty": "hard",
        "text": "Give me a serious research summary on creatine: benefits, dosing, safety, myths, who should avoid it, and what the evidence actually says.",
    },
    {
        "difficulty": "hard",
        "text": "Help me choose between Bali, Chiang Mai, Lisbon, and Mexico City for 2 months of remote work. Compare cost, internet, safety, community, weather, and visa basics.",
    },
    {
        "difficulty": "hard",
        "text": "Analyse the electric vehicle market right now. Cover major brands, battery trends, charging issues, government incentives, and whether buying used makes sense.",
    },
    {
        "difficulty": "expert",
        "text": "Do a deep research report on crystals for protection, grounding, luck, love, and karma cleansing. Include traditional uses, cultural context, safety notes, and how to evaluate claims critically.",
    },
    {
        "difficulty": "expert",
        "text": "I need to understand the current Israel-Palestine conflict without propaganda. Summarize the recent timeline, humanitarian situation, political constraints, and where sources disagree.",
    },
    {
        "difficulty": "expert",
        "text": "Create a 6 month learning plan for becoming employable in machine learning engineering. Assume I know Python but not much math. Include projects, milestones, and how to prove skill.",
    },
    {
        "difficulty": "expert",
        "text": "Compare the best approaches to investing $10,000 as a beginner in 2026. Explain index funds, bonds, cash, crypto, risk tolerance, taxes, and what not to do.",
    },
    {
        "difficulty": "expert-plus",
        "text": "Act like a research assistant for someone deciding whether to move from Singapore to London, Dubai, or Sydney. Compare taxes, career opportunity, rent, healthcare, lifestyle, climate, and long-term tradeoffs.",
    },
]


def utc_now() -> str:
    return dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")


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


def extract_response_text(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    messages = result.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        message_type = message.get("type") or message.get("role")
        if message_type not in {"ai", "assistant"}:
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [block.get("text") for block in content if isinstance(block, dict) and isinstance(block.get("text"), str)]
            return "\n".join(parts)
    return ""


async def run_prompt_server(
    *,
    cycle_id: int,
    prompt_id: int,
    prompt: dict[str, str],
    langgraph_url: str,
    app_url: str,
) -> None:
    from langgraph_sdk import get_client

    prompt_dir = SCRIPT_DIR / f"prompt_id_{prompt_id}"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    purpose = f"cycle_{cycle_id}_prompt_{prompt_id}"
    metadata_path = prompt_dir / f"cycle_{cycle_id}_metadata.json"
    client = get_client(url=langgraph_url.rstrip("/"))
    thread = await client.threads.create()
    thread_id = str(thread["thread_id"])

    metadata: dict[str, Any] = {
        "cycle_id": cycle_id,
        "prompt_id": prompt_id,
        "thread_id": thread_id,
        "chat_url": f"{app_url.rstrip('/')}/workspace/chats/{thread_id}",
        "initial_prompt": prompt["text"],
        "difficulty": prompt["difficulty"],
        "runtime": "server",
        "langgraph_url": langgraph_url,
        "mode": "work",
        "auto_mode": True,
        "prompt_log_purpose": purpose,
        "started_at": utc_now(),
        "status": "running",
    }
    write_json(metadata_path, metadata)

    try:
        result = await client.runs.wait(
            thread_id,
            "lead_agent",
            input={"messages": [{"role": "human", "content": prompt["text"]}]},
            config={"recursion_limit": 1000},
            context={
                "thread_id": thread_id,
                "thinking_enabled": True,
                "is_plan_mode": False,
                "mode": "work",
                "subagent_enabled": True,
                "plan_behavior": "work_interactive",
                "auto_mode": True,
            },
        )
        metadata["status"] = "completed"
        metadata["response_preview"] = extract_response_text(result)[:2000]
    except Exception as exc:  # noqa: BLE001 - record and continue to next prompt
        metadata["status"] = "failed"
        metadata["error"] = str(exc)
        metadata["traceback"] = traceback.format_exc()
    finally:
        metadata["completed_at"] = utc_now()
        metadata["copied_prompt_logs"] = copy_prompt_logs(thread_id, prompt_dir, cycle_id)
        write_json(metadata_path, metadata)


def run_prompt_embedded(client: CapybaraClient, *, cycle_id: int, prompt_id: int, prompt: dict[str, str]) -> None:
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
        "chat_url": None,
        "initial_prompt": prompt["text"],
        "difficulty": prompt["difficulty"],
        "runtime": "embedded",
        "mode": "work",
        "auto_mode": True,
        "prompt_log_purpose": purpose,
        "started_at": utc_now(),
        "status": "running",
    }
    write_json(metadata_path, metadata)

    try:
        response = asyncio.run(client.achat(
            prompt["text"],
            thread_id=thread_id,
            auto_mode=True,
            mode="work",
            plan_mode=False,
            subagent_enabled=True,
            recursion_limit=1000,
        ))
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
    parser.add_argument("--delay-seconds", type=float, default=20.0, help="Delay after a run completes, immediately before submitting the next prompt.")
    parser.add_argument("--limit-prompts", type=int, default=None, help="Run only the first N prompts from each cycle. Useful for smoke tests.")
    parser.add_argument("--runtime", choices=["server", "embedded"], default="server", help="Execution runtime. Server mode matches the browser/LangGraph app.")
    parser.add_argument("--langgraph-url", default=DEFAULT_LANGGRAPH_URL, help="LangGraph server URL used by --runtime server.")
    parser.add_argument("--app-url", default=DEFAULT_APP_URL, help="Base app URL used to write chat_url metadata.")
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL, help="Gateway URL used for best-effort memory/thread cleanup.")
    parser.add_argument("--skip-gateway-cleanup", action="store_true", help="Only clear local embedded-client state between cycles.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = None
    if args.runtime == "embedded":
        config_path = str(CONFIG_PATH) if CONFIG_PATH.exists() else None
        client = CapybaraClient(
            config_path=config_path,
            thinking_enabled=True,
            subagent_enabled=True,
            plan_mode=False,
            auto_mode=True,
        )

    prompts = PROMPTS[: args.limit_prompts] if args.limit_prompts is not None else PROMPTS
    if not prompts:
        print("No prompts selected.")
        return 0

    total_runs = args.cycles * len(prompts)
    completed_runs = 0
    previous_run_completed = False
    print(f"Starting {total_runs} prompt-tuning runs in {SCRIPT_DIR} using {args.runtime} runtime")

    for cycle_id in range(1, args.cycles + 1):
        print(f"\nCycle {cycle_id}/{args.cycles}")
        for prompt_id, prompt in enumerate(prompts, start=1):
            if previous_run_completed and args.delay_seconds > 0:
                print(f"  Waiting {args.delay_seconds:g}s before submitting prompt {prompt_id:02d}/{len(prompts)}...")
                time.sleep(args.delay_seconds)

            print(f"  Submitting prompt {prompt_id:02d}/{len(prompts)} ({prompt['difficulty']})")
            if args.runtime == "server":
                asyncio.run(
                    run_prompt_server(
                        cycle_id=cycle_id,
                        prompt_id=prompt_id,
                        prompt=prompt,
                        langgraph_url=args.langgraph_url,
                        app_url=args.app_url,
                    )
                )
            else:
                if client is None:
                    raise RuntimeError("Embedded client was not initialized.")
                run_prompt_embedded(client, cycle_id=cycle_id, prompt_id=prompt_id, prompt=prompt)
            completed_runs += 1
            previous_run_completed = completed_runs < total_runs

        cleanup: dict[str, Any] = {"cycle_id": cycle_id, "started_at": utc_now()}
        if not args.skip_gateway_cleanup:
            cleanup["gateway"] = clear_gateway_state(args.gateway_url)
        cleanup["local"] = clear_local_state()
        cleanup["completed_at"] = utc_now()
        write_json(SCRIPT_DIR / f"cycle_{cycle_id}_cleanup.json", cleanup)
        if client is not None:
            client.reset_agent()

    print("\nPrompt-tuning loop complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
