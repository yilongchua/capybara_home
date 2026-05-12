#!/usr/bin/env python3
"""Manage a checkpoint file for batch-workflow progress tracking.

The checkpoint file is a JSON object that tracks which tasks are complete,
enabling interrupted runs to resume from exactly where they left off.

Checkpoint format:
{
  "total": 580,
  "completed": [1, 2, 3, ...],
  "last_done": 47,
  "started_at": "2025-04-27T10:00:00",
  "updated_at": "2025-04-27T10:45:23"
}

Usage:
  # Mark one task complete
  python checkpoint.py --file outputs/checkpoint.json --mark-done 47

  # Show progress summary
  python checkpoint.py --file outputs/checkpoint.json --status

  # Initialise a new checkpoint for a known total
  python checkpoint.py --file outputs/checkpoint.json --init --total 580
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _load(cp_path: Path) -> dict:
    if not cp_path.exists():
        return {"total": 0, "completed": [], "last_done": 0, "started_at": _now_iso(), "updated_at": _now_iso()}
    try:
        data = json.loads(cp_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"total": 0, "completed": [], "last_done": 0, "started_at": _now_iso(), "updated_at": _now_iso()}
        # Normalise completed to list of ints
        raw_completed = data.get("completed") or []
        data["completed"] = []
        for item in raw_completed:
            try:
                data["completed"].append(int(item))
            except (TypeError, ValueError):
                pass
        return data
    except Exception as exc:
        sys.exit(f"Failed to read checkpoint file {cp_path}: {exc}")


def _save(cp_path: Path, data: dict) -> None:
    cp_path.parent.mkdir(parents=True, exist_ok=True)
    cp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_init(cp_path: Path, total: int) -> None:
    data = _load(cp_path)
    data["total"] = total
    if not data.get("started_at"):
        data["started_at"] = _now_iso()
    data["updated_at"] = _now_iso()
    _save(cp_path, data)
    print(json.dumps({"action": "init", "total": total, "file": str(cp_path)}))


def cmd_mark_done(cp_path: Path, task_id: int) -> None:
    data = _load(cp_path)
    completed: list[int] = data.get("completed") or []
    if task_id not in completed:
        completed.append(task_id)
        completed.sort()
    data["completed"] = completed
    data["last_done"] = max(completed) if completed else 0
    data["updated_at"] = _now_iso()
    _save(cp_path, data)
    total = data.get("total") or 0
    done = len(completed)
    pct = f"{done / total * 100:.1f}%" if total else "?%"
    print(json.dumps({"action": "mark_done", "task_id": task_id, "done": done, "total": total, "progress": pct}))


def cmd_status(cp_path: Path) -> None:
    data = _load(cp_path)
    completed: list[int] = data.get("completed") or []
    total = data.get("total") or 0
    done = len(completed)
    remaining = max(0, total - done)
    pct = f"{done / total * 100:.1f}%" if total else "?%"
    last_done = data.get("last_done") or (max(completed) if completed else 0)

    # Find resume index (first task not in completed set)
    completed_set = set(completed)
    resume_index = total + 1  # default: all done
    for i in range(1, total + 1):
        if i not in completed_set:
            resume_index = i
            break

    summary = {
        "total": total,
        "done": done,
        "remaining": remaining,
        "progress_pct": pct,
        "last_done": last_done,
        "resume_index": resume_index,
        "all_done": remaining == 0,
        "started_at": data.get("started_at"),
        "updated_at": data.get("updated_at"),
    }
    print(json.dumps(summary, indent=2))
    # Human-readable line for easy reading in agent output
    print(f"Progress: {done} / {total} ({pct}) — next task: {resume_index}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage batch-workflow checkpoint file")
    parser.add_argument("--file", required=True, help="Path to checkpoint JSON file")

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--mark-done", type=int, metavar="TASK_ID", help="Mark a task as completed")
    action.add_argument("--status", action="store_true", help="Print progress summary")
    action.add_argument("--init", action="store_true", help="Initialise or reset the checkpoint")

    parser.add_argument("--total", type=int, default=0, help="Total task count (required with --init)")

    args = parser.parse_args()
    cp_path = Path(args.file)

    if args.mark_done is not None:
        cmd_mark_done(cp_path, args.mark_done)
    elif args.status:
        cmd_status(cp_path)
    elif args.init:
        if not args.total:
            sys.exit("--total is required with --init")
        cmd_init(cp_path, args.total)


if __name__ == "__main__":
    main()
