"""Question ledger for the autoresearch agentic loop.

Structurally mirrors the lead-agent todo graph (id, content, status,
depends_on) so the frontend can render it with the same primitives used for
plan todos.

Persisted as both ``ledger.json`` (structured, machine-read) and
``ledger.md`` (human-readable) under
``{vault_root}/03_ops/autoresearch/objectives/{objective_slug}/``.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypedDict

QuestionStatus = Literal[
    "pending",        # waiting to be researched
    "in_progress",    # researcher dispatched
    "answered",       # vault entry written
    "duplicate",      # collapsed into existing question / vault entry
    "rejected",       # off-topic / drift filter
    "blocked",        # researcher failed
]


class QuestionNode(TypedDict, total=False):
    id: str
    content: str
    status: QuestionStatus
    depends_on: list[str]
    cluster: int
    level: int
    asked_by: Literal["generator", "reflector", "user"]
    novelty: float
    loop_iteration: int
    vault_entries: list[str]
    duplicate_of: str | None
    researcher_summary: str
    sources_used: int
    error: str | None
    created_at: str
    updated_at: str


_LOCK = threading.RLock()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _slugify(text: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").lower()).strip("-")
    return base[:80] or "question"


def _question_id(content: str, taken: set[str]) -> str:
    base = _slugify(content)
    candidate = f"q-{base}"
    suffix = 2
    while candidate in taken:
        candidate = f"q-{base}-{suffix}"
        suffix += 1
    return candidate


class QuestionLedger:
    """File-backed ledger of generated/researched questions for one objective.

    The ledger is rebuilt from disk on every operation; concurrent writers in
    the same process are serialised by a module-level lock. Different
    processes are not coordinated — the autoresearch loop iterates inside
    the scheduler's pipeline-run path, which is itself single-writer per
    objective.
    """

    def __init__(self, *, vault_root: Path, objective_slug: str) -> None:
        self._vault_root = vault_root
        self._objective_slug = _slugify(objective_slug)
        self._dir = vault_root / "03_ops" / "autoresearch" / "objectives" / self._objective_slug
        self._dir.mkdir(parents=True, exist_ok=True)
        self.json_path = self._dir / "ledger.json"
        self.md_path = self._dir / "ledger.md"

    # ------------------------------------------------------------------ I/O

    def load(self) -> dict[str, Any]:
        with _LOCK:
            return self._load_locked()

    def _load_locked(self) -> dict[str, Any]:
        if not self.json_path.exists():
            return {
                "objective_slug": self._objective_slug,
                "loop_iteration": 0,
                "questions": [],
                "iterations": [],
                "updated_at": _utc_now_iso(),
            }
        try:
            data = json.loads(self.json_path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "objective_slug": self._objective_slug,
                "loop_iteration": 0,
                "questions": [],
                "iterations": [],
                "updated_at": _utc_now_iso(),
            }
        data.setdefault("questions", [])
        data.setdefault("iterations", [])
        data.setdefault("loop_iteration", 0)
        return data

    def _save_locked(self, data: dict[str, Any], *, topic: str | None = None, endpoint_goal: str | None = None) -> None:
        data["updated_at"] = _utc_now_iso()
        self.json_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self._write_markdown(data, topic=topic, endpoint_goal=endpoint_goal)

    # ----------------------------------------------------------------- ops

    def append_questions(
        self,
        *,
        items: list[dict[str, Any]],
        loop_iteration: int,
        topic: str | None = None,
        endpoint_goal: str | None = None,
    ) -> list[QuestionNode]:
        """Append normalised question nodes to the ledger; returns the added nodes."""
        if not items:
            return []
        added: list[QuestionNode] = []
        with _LOCK:
            data = self._load_locked()
            taken: set[str] = {str(node.get("id", "")) for node in data["questions"]}
            now = _utc_now_iso()
            for raw in items:
                content = str(raw.get("content") or "").strip()
                if not content:
                    continue
                node: QuestionNode = {
                    "id": _question_id(content, taken),
                    "content": content,
                    "status": str(raw.get("status") or "pending"),  # type: ignore[typeddict-item]
                    "depends_on": [str(d) for d in (raw.get("depends_on") or []) if str(d).strip()],
                    "cluster": int(raw.get("cluster") or 0),
                    "level": int(raw.get("level") or 1),
                    "asked_by": str(raw.get("asked_by") or "generator"),  # type: ignore[typeddict-item]
                    "novelty": float(raw.get("novelty") or 1.0),
                    "loop_iteration": int(loop_iteration),
                    "vault_entries": list(raw.get("vault_entries") or []),
                    "duplicate_of": raw.get("duplicate_of") or None,
                    "researcher_summary": str(raw.get("researcher_summary") or ""),
                    "sources_used": int(raw.get("sources_used") or 0),
                    "error": raw.get("error") or None,
                    "created_at": now,
                    "updated_at": now,
                }
                taken.add(node["id"])
                data["questions"].append(node)
                added.append(node)
            data["loop_iteration"] = max(int(data.get("loop_iteration") or 0), int(loop_iteration))
            self._save_locked(data, topic=topic, endpoint_goal=endpoint_goal)
        return added

    def update_question(
        self,
        question_id: str,
        *,
        topic: str | None = None,
        endpoint_goal: str | None = None,
        **fields: Any,
    ) -> QuestionNode | None:
        with _LOCK:
            data = self._load_locked()
            target: QuestionNode | None = None
            for node in data["questions"]:
                if str(node.get("id")) == question_id:
                    target = node  # type: ignore[assignment]
                    break
            if target is None:
                return None
            for key, value in fields.items():
                target[key] = value  # type: ignore[literal-required]
            target["updated_at"] = _utc_now_iso()
            self._save_locked(data, topic=topic, endpoint_goal=endpoint_goal)
            return target

    def record_iteration(
        self,
        *,
        loop_iteration: int,
        summary: dict[str, Any],
        topic: str | None = None,
        endpoint_goal: str | None = None,
    ) -> None:
        with _LOCK:
            data = self._load_locked()
            entry = {"iteration": int(loop_iteration), "at": _utc_now_iso(), **summary}
            data["iterations"].append(entry)
            data["loop_iteration"] = max(int(data.get("loop_iteration") or 0), int(loop_iteration))
            self._save_locked(data, topic=topic, endpoint_goal=endpoint_goal)

    # ------------------------------------------------------------- queries

    def questions(self) -> list[QuestionNode]:
        return list(self.load().get("questions", []))

    def find_by_content(self, content: str) -> QuestionNode | None:
        normalized = content.strip().lower()
        if not normalized:
            return None
        for node in self.questions():
            if str(node.get("content", "")).strip().lower() == normalized:
                return node
        return None

    def recent_questions(self, limit: int = 10) -> list[QuestionNode]:
        items = self.questions()
        items.sort(key=lambda q: str(q.get("created_at") or ""))
        return items[-limit:]

    def cluster_coverage(self) -> dict[int, int]:
        """Return the deepest answered level per cluster id."""
        coverage: dict[int, int] = {}
        for node in self.questions():
            if str(node.get("status")) != "answered":
                continue
            cluster = int(node.get("cluster") or 0)
            level = int(node.get("level") or 0)
            if cluster <= 0:
                continue
            coverage[cluster] = max(coverage.get(cluster, 0), level)
        return coverage

    # --------------------------------------------------------- markdown view

    def _write_markdown(
        self,
        data: dict[str, Any],
        *,
        topic: str | None,
        endpoint_goal: str | None,
    ) -> None:
        questions: list[QuestionNode] = list(data.get("questions") or [])
        iterations = list(data.get("iterations") or [])
        coverage = self.cluster_coverage() if questions else {}

        lines: list[str] = []
        lines.append(f"# Autoresearch Ledger: {topic or self._objective_slug}")
        lines.append("")
        if endpoint_goal:
            lines.append(f"**Objective:** {endpoint_goal}")
            lines.append("")
        lines.append(f"- Loop iterations completed: `{data.get('loop_iteration') or 0}`")
        lines.append(f"- Questions tracked: `{len(questions)}`")
        if coverage:
            covered = sorted(coverage.items())
            coverage_str = ", ".join(f"C{cid} L{lvl}" for cid, lvl in covered)
            lines.append(f"- Cluster coverage: `{coverage_str}`")
        lines.append("")

        lines.append("## Questions")
        if not questions:
            lines.append("- _no questions yet_")
        else:
            status_icon = {
                "answered": "[x]",
                "pending": "[ ]",
                "in_progress": "[~]",
                "duplicate": "[d]",
                "rejected": "[!]",
                "blocked": "[b]",
            }
            for node in questions:
                icon = status_icon.get(str(node.get("status")), "[?]")
                cluster = node.get("cluster") or 0
                level = node.get("level") or 0
                tag = f"C{cluster}L{level}" if cluster else "C?"
                lines.append(f"- {icon} `{node.get('id')}` ({tag}) {node.get('content')}")
                if node.get("status") == "duplicate" and node.get("duplicate_of"):
                    lines.append(f"  - duplicate of `{node['duplicate_of']}`")
                if node.get("error"):
                    lines.append(f"  - error: {node['error']}")
                if node.get("vault_entries"):
                    refs = ", ".join(f"`{ref}`" for ref in node["vault_entries"][:3])
                    lines.append(f"  - vault: {refs}")
        lines.append("")

        lines.append("## Iterations")
        if not iterations:
            lines.append("- _no iterations yet_")
        else:
            for entry in iterations[-20:]:
                lines.append(
                    f"- #{entry.get('iteration')} ({entry.get('at')}): "
                    f"generated={entry.get('generated', 0)}, "
                    f"answered={entry.get('answered', 0)}, "
                    f"duplicates={entry.get('duplicates', 0)}, "
                    f"novelty={entry.get('novelty_rate', 0):.2f}"
                )
        lines.append("")

        self.md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
