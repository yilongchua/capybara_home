#!/usr/bin/env python3
"""Run prompt-tuning cycles with minimal human intervention.

All runs use plan mode, matching the LangGraph ``context`` the browser sends on
``thread.submit`` (see ``frontend/src/core/threads/hooks.ts``) and the embedded
``CapyHomeClient`` stream context (see ``backend/src/client.py``).

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
os.environ.setdefault("CAPYBARA_HOME", str(BACKEND_DIR / ".capyhome"))
os.environ.setdefault("CAPYBARA_PROMPT_LOGGING_ENABLED", "1")

from src.agents.checkpointer import reset_checkpointer  # noqa: E402
from src.agents.memory.updater import clear_memory  # noqa: E402
from src.client import CapyHomeClient  # noqa: E402
from src.config.paths import get_paths  # noqa: E402

PROMPTS: list[dict[str, str]] = [
    {
        "text": "My partner and I are doing Greece for exactly 12 days in mid-September — Athens plus maybe 2 islands, nothing crazy. Can you map out day by day with where to sleep, realistic ferry times, and a rough total budget in EUR? Please name actual areas or hotels you'd actually book, not just 'stay in Plaka'.",
    },
    {
        "text": "I keep ending up around town after work and craving bubble tea but I never know where to go. What are some good bubble tea spots in Singapore? I don't need a huge ranked list — just somewhere you'd genuinely stop if you were already in the area.",
    },
    {
        "text": "Can you look into crystals people use for karma protection and warding off bad energy? I'm pretty new to this — explain what each one is supposed to do and how people actually use them, not just throw names at me.",
    },
    {
        "text": "Anniversary next Friday — want Japanese for date night in Singapore, somewhere that feels nice but not stiff. Budget around $80–120 per person, preferably not too loud. Give me 2–3 specific places and one dish you'd order at each.",
    },
    {
        "text": "My sleep's been rubbish and I scroll on my phone way too late. I don't want a military schedule — just something sensible for about a month that I can actually stick to when work gets messy.",
    },
    {
        "text": "Renting vs buying in Singapore — I'm on an HDB waitlist but also looking at resale. Walk me through what numbers actually matter, what people regret, and a simple way to decide without pretending we can predict the market.",
    },
    {
        "text": "Trying to lose a bit of weight and torn between intermittent fasting, counting calories, or just eating cleaner. Pros, cons, who each works for — keep it practical, I'm not looking for a lecture.",
    },
    {
        "text": "First time in Tokyo for a long weekend. I like food, small bookshops, quieter neighbourhoods, and maybe one good cocktail bar — not the hit-every-famous-spot-in-48-hours thing. Sketch something that feels doable.",
    },
    {
        "text": "Honest question: is AI actually going to wipe out junior dev jobs or is that overblown? I want both sides with real recent examples (hiring, tools, startups), and what you'd tell a junior engineer to focus on this year.",
    },
    {
        "text": "Setting up coffee at home in a tiny kitchen. Espresso machine vs pour-over vs AeroPress vs moka pot — taste, cost, how annoying they are day to day. If you had to pick one for a beginner, what and why?",
    },
    {
        "text": "I've had soba in Singapore a few times and I'm going to Japan next month. How different is 'real' soba there vs what we get here? Compare a few specific places in SG vs what you'd expect in Tokyo — broth, noodle texture, the whole vibe.",
    },
    {
        "text": "Want a proper emergency kit for a family of four in a high-rise apartment in Singapore. Prioritised list with quantities, and be clear what's essential vs nice-to-have — we don't have a storeroom, so space matters.",
    },
    {
        "text": "Thinking about creatine — I'm 70kg, lift 3x a week, otherwise healthy. Benefits, how much to take, safety, common myths, and who should skip it. Cite what the evidence actually says, not bro-science.",
    },
    {
        "text": "Might do two months remote somewhere — Bali, Chiang Mai, Lisbon, or Mexico City. I care about decent internet and not feeling isolated, but I'm fuzzy on the rest. Help me get a feel for each without a giant comparison table.",
    },
    {
        "text": "Shopping for an EV in 2026, probably used (under 5 years). Which brands are solid, what's going on with batteries and charging in SG, incentives, and whether used is a trap right now.",
    },
    {
        "text": "Doing a deeper read on crystals — protection, grounding, luck, love, karma cleansing. Traditional use, cultural context, how to be skeptical without being dismissive, and anything safety-related people miss.",
    },
    {
        "text": "Where's good for Burmese food in Singapore? I'm usually around Joo Chiat / Geylang side. Must-try dishes and a couple of specific shops — skip the generic 'try mohinga' with no names.",
    },
    {
        "text": "Six months to get employable as an ML engineer. I know Python, math is rusty at best. Week-by-week-ish plan with projects I'd actually put on a CV and how to show I can ship, not just finish courses.",
    },
    {
        "text": "I've got about $10k sitting around and I've never really invested. Index funds, bonds, cash, crypto — what's worth understanding in 2026? Explain it like you're talking to a friend, not a finance textbook.",
    },
    {
        "text": "My 6-year-old wants to learn to cycle but he's scared of falling and we only have a small condo corridor — no space for training wheels indoors. What's a sane step-by-step way to teach him outside? Gear, timing, how long it usually takes — be realistic, not 'he'll get it in a day'.",
    },
]

# Mirrors frontend thread.submit context when mode === "plan":
#   frontend/src/core/threads/hooks.ts (context block on submit)
# Embedded client derives the same fields via CapyHomeClient._get_runnable_config.
RUN_MODE = "plan"
RUN_PLAN_BEHAVIOR = "plan_foreground"
RUN_RECURSION_LIMIT = 3000
# config.yaml models[].name — mlx-community/qwen3.6-35b-a3b @ http://192.168.1.21:1234/v1
DEFAULT_MODEL_NAME = "qwen3.6-remote"


def langgraph_run_context(
    *,
    thread_id: str,
    prompt_text: str,
    model_name: str,
    auto_mode: bool = True,
) -> dict[str, Any]:
    """Build the LangGraph run ``context`` dict (server + embedded stream)."""
    return {
        "thread_id": thread_id,
        "thinking_enabled": True,
        "is_plan_mode": True,
        "mode": RUN_MODE,
        "subagent_enabled": True,
        "plan_behavior": RUN_PLAN_BEHAVIOR,
        "auto_mode": auto_mode,
        "model_name": model_name,
        "current_turn_text": prompt_text,
        "original_user_request": prompt_text,
    }


def run_config_snapshot(*, model_name: str, auto_mode: bool = True) -> dict[str, Any]:
    """Serializable config recorded in per-run metadata for auditing."""
    return {
        "mode": RUN_MODE,
        "is_plan_mode": True,
        "plan_behavior": RUN_PLAN_BEHAVIOR,
        "thinking_enabled": True,
        "subagent_enabled": True,
        "auto_mode": auto_mode,
        "model_name": model_name,
        "recursion_limit": RUN_RECURSION_LIMIT,
        "langgraph_alignment": "frontend/src/core/threads/hooks.ts#thread.submit.context",
    }


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
    model_name: str,
) -> str:
    from langgraph_sdk import get_client

    prompt_dir = SCRIPT_DIR / f"prompt_id_{prompt_id}"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    purpose = f"cycle_{cycle_id}_prompt_{prompt_id}"
    metadata_path = prompt_dir / f"cycle_{cycle_id}_metadata.json"
    client = get_client(url=langgraph_url.rstrip("/"))
    assistants = await client.assistants.search()
    assistant_id = next(
        (
            str(item["assistant_id"])
            for item in assistants
            if item.get("graph_id") == "lead_agent" or item.get("name") == "lead_agent"
        ),
        "lead_agent",
    )
    thread = await client.threads.create()
    thread_id = str(thread["thread_id"])

    run_config = run_config_snapshot(model_name=model_name)
    metadata: dict[str, Any] = {
        "cycle_id": cycle_id,
        "prompt_id": prompt_id,
        "thread_id": thread_id,
        "chat_url": f"{app_url.rstrip('/')}/workspace/chats/{thread_id}",
        "initial_prompt": prompt["text"],
        "runtime": "server",
        "langgraph_url": langgraph_url,
        "assistant_id": assistant_id,
        "prompt_log_purpose": purpose,
        "run_config": run_config,
        "started_at": utc_now(),
        "status": "running",
    }
    write_json(metadata_path, metadata)

    try:
        result = await client.runs.wait(
            thread_id,
            assistant_id,
            input={"messages": [{"role": "human", "content": prompt["text"]}]},
            config={"recursion_limit": run_config["recursion_limit"]},
            context=langgraph_run_context(
                thread_id=thread_id,
                prompt_text=prompt["text"],
                model_name=model_name,
            ),
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
    return str(metadata["status"])


def run_prompt_embedded(client: CapyHomeClient, *, cycle_id: int, prompt_id: int, prompt: dict[str, str], model_name: str) -> str:
    prompt_dir = SCRIPT_DIR / f"prompt_id_{prompt_id}"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    thread_id = f"prompt_tunning_p{prompt_id:02d}_c{cycle_id}_{uuid.uuid4().hex[:8]}"
    purpose = f"cycle_{cycle_id}_prompt_{prompt_id}"
    metadata_path = prompt_dir / f"cycle_{cycle_id}_metadata.json"
    os.environ["CAPYBARA_PROMPT_LOG_PURPOSE"] = purpose

    run_config = run_config_snapshot(model_name=model_name)
    metadata: dict[str, Any] = {
        "cycle_id": cycle_id,
        "prompt_id": prompt_id,
        "thread_id": thread_id,
        "chat_url": None,
        "initial_prompt": prompt["text"],
        "runtime": "embedded",
        "prompt_log_purpose": purpose,
        "run_config": run_config,
        "started_at": utc_now(),
        "status": "running",
    }
    write_json(metadata_path, metadata)

    try:
        response = asyncio.run(client.achat(
            prompt["text"],
            thread_id=thread_id,
            auto_mode=True,
            mode=RUN_MODE,
            plan_mode=True,
            subagent_enabled=True,
            model_name=model_name,
            recursion_limit=run_config["recursion_limit"],
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
    return str(metadata["status"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run 20 prompt-tuning prompts for 3 cycles.")
    parser.add_argument("--cycles", type=int, default=3, help="Number of full 20-prompt cycles.")
    parser.add_argument("--delay-seconds", type=float, default=60.0, help="Delay after a run completes, immediately before submitting the next prompt.")
    parser.add_argument("--limit-prompts", type=int, default=None, help="Run only the first N prompts from each cycle. Useful for smoke tests.")
    parser.add_argument("--runtime", choices=["server", "embedded"], default="server", help="Execution runtime. Server mode matches the browser/LangGraph app.")
    parser.add_argument(
        "--model-name",
        default=DEFAULT_MODEL_NAME,
        help=f"config.yaml models[].name (default: {DEFAULT_MODEL_NAME})",
    )
    parser.add_argument("--langgraph-url", default=DEFAULT_LANGGRAPH_URL, help="LangGraph server URL used by --runtime server.")
    parser.add_argument("--app-url", default=DEFAULT_APP_URL, help="Base app URL used to write chat_url metadata.")
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL, help="Gateway URL used for best-effort memory/thread cleanup.")
    parser.add_argument("--cleanup-partial-cycles", action="store_true", help="Also clear memory/thread state when --limit-prompts runs fewer than all prompts.")
    parser.add_argument("--continue-on-failure", action="store_true", help="Continue submitting prompts after a failed run.")
    parser.add_argument("--skip-gateway-cleanup", action="store_true", help="Only clear local embedded-client state between cycles.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = None
    if args.runtime == "embedded":
        config_path = str(CONFIG_PATH) if CONFIG_PATH.exists() else None
        client = CapyHomeClient(
            config_path=config_path,
            model_name=args.model_name,
            thinking_enabled=True,
            subagent_enabled=True,
            plan_mode=True,
            auto_mode=True,
        )

    prompts = PROMPTS[: args.limit_prompts] if args.limit_prompts is not None else PROMPTS
    if not prompts:
        print("No prompts selected.")
        return 0

    total_runs = args.cycles * len(prompts)
    completed_runs = 0
    previous_run_completed = False
    print(
        f"Starting {total_runs} prompt-tuning runs in {SCRIPT_DIR} "
        f"using {args.runtime} runtime, model={args.model_name}, "
        f"recursion_limit={RUN_RECURSION_LIMIT}, mode={RUN_MODE}"
    )

    for cycle_id in range(1, args.cycles + 1):
        print(f"\nCycle {cycle_id}/{args.cycles}")
        for prompt_id, prompt in enumerate(prompts, start=1):
            if previous_run_completed and args.delay_seconds > 0:
                print(f"  Waiting {args.delay_seconds:g}s before submitting prompt {prompt_id:02d}/{len(prompts)}...")
                time.sleep(args.delay_seconds)

            print(f"  Submitting prompt {prompt_id:02d}/{len(prompts)}")
            if args.runtime == "server":
                status = asyncio.run(
                    run_prompt_server(
                        cycle_id=cycle_id,
                        prompt_id=prompt_id,
                        prompt=prompt,
                        langgraph_url=args.langgraph_url,
                        app_url=args.app_url,
                        model_name=args.model_name,
                    )
                )
            else:
                if client is None:
                    raise RuntimeError("Embedded client was not initialized.")
                status = run_prompt_embedded(client, cycle_id=cycle_id, prompt_id=prompt_id, prompt=prompt, model_name=args.model_name)
            completed_runs += 1
            previous_run_completed = completed_runs < total_runs
            if status != "completed" and not args.continue_on_failure:
                print(f"  Prompt {prompt_id:02d} ended with status={status}; stopping. Use --continue-on-failure to keep going.")
                return 1

        should_cleanup = len(prompts) == len(PROMPTS) or args.cleanup_partial_cycles
        if should_cleanup:
            cleanup: dict[str, Any] = {"cycle_id": cycle_id, "started_at": utc_now()}
            if not args.skip_gateway_cleanup:
                cleanup["gateway"] = clear_gateway_state(args.gateway_url)
            cleanup["local"] = clear_local_state()
            cleanup["completed_at"] = utc_now()
            write_json(SCRIPT_DIR / f"cycle_{cycle_id}_cleanup.json", cleanup)
            if client is not None:
                client.reset_agent()
        else:
            print("  Skipping cleanup for partial smoke-test cycle.")

    print("\nPrompt-tuning loop complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
