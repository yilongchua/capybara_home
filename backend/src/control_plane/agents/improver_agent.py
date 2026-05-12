from __future__ import annotations

import difflib
import re
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml

from src.control_plane.agents.base import BaseControlPlaneAgent
from src.control_plane.agents.schemas import AgentExecutionContext, AgentExecutionResult
from src.control_plane.models import PipelineRun, PipelineStepDefinition, utcnow

_SKILL_FRONTMATTER_KEYS = {"name", "description", "license", "allowed-tools", "metadata"}


class ImproverAgent(BaseControlPlaneAgent):
    agent_id = "improver"

    @classmethod
    def supported_kinds(cls) -> set[str]:
        return {"improver_scan", "self_improver_draft"}

    def execute(self, context: AgentExecutionContext) -> AgentExecutionResult:
        if context.definition.kind == "improver_scan":
            report = self._service._run_improver_scan(context.definition)
            artifact = self._service._write_json_artifact(
                context.run_id,
                f"{context.step.step_id}-improver.json",
                report,
            )
            self._service._append_artifact(context.run_id, artifact)
            return self._result(
                context,
                output={"report": report, "artifact_path": artifact},
                details={"graph": ["inspect_repo", "collect_feedback_summary", "write_artifact"]},
            )

        if context.definition.kind == "self_improver_draft":
            report = self._service._run_self_improver_draft(run=context.run, definition=context.definition)
            artifact_name = f"{context.step.step_id}-self-improver-draft.json"
            artifact = self._service._write_json_artifact(context.run_id, artifact_name, report)
            self._service._append_artifact(context.run_id, artifact)
            return self._result(
                context,
                output={"report": report, "artifact_path": artifact, "artifact_name": artifact_name},
                details={
                    "graph": ["collect_signals", "score_skills", "draft_proposals", "write_artifact"],
                    "proposal_count": int(report.get("counts", {}).get("proposals") or 0),
                },
            )

        raise ValueError(f"Unsupported improver step kind: {context.definition.kind}")

    def validate_skill_markdown(self, content: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "frontmatter_ok": False,
            "parse_ok": False,
            "issues": [],
        }

        if not content.startswith("---"):
            result["issues"].append("Missing YAML frontmatter.")
            return result

        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not match:
            result["issues"].append("Invalid frontmatter format.")
            return result

        try:
            frontmatter = yaml.safe_load(match.group(1))
        except yaml.YAMLError as exc:
            result["issues"].append(f"Invalid YAML in frontmatter: {exc}")
            return result

        if not isinstance(frontmatter, dict):
            result["issues"].append("Frontmatter must be a YAML dictionary.")
            return result

        unexpected = set(frontmatter.keys()) - _SKILL_FRONTMATTER_KEYS
        if unexpected:
            result["issues"].append(f"Unexpected frontmatter keys: {', '.join(sorted(unexpected))}")

        name = frontmatter.get("name")
        description = frontmatter.get("description")
        if not isinstance(name, str) or not name.strip():
            result["issues"].append("Missing or invalid 'name' in frontmatter.")
        if not isinstance(description, str) or not description.strip():
            result["issues"].append("Missing or invalid 'description' in frontmatter.")

        result["frontmatter_ok"] = len(result["issues"]) == 0
        result["parse_ok"] = (
            isinstance(name, str)
            and bool(name.strip())
            and isinstance(description, str)
            and bool(description.strip())
        )
        return result

    def _clip_text(self, value: str, max_chars: int = 320) -> str:
        cleaned = self._service._redaction.redact_text(str(value)).strip()
        if len(cleaned) <= max_chars:
            return cleaned
        return f"{cleaned[: max_chars - 1]}…"

    def _skill_hint_from_metadata(self, metadata: dict[str, Any] | None) -> str | None:
        if not isinstance(metadata, dict):
            return None
        for key in ("skill_name", "target_skill", "skill", "skill_id"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        return None

    def _find_skill_from_text(self, text: str, skill_names: list[str]) -> str | None:
        lowered = text.lower()
        for skill_name in skill_names:
            if skill_name in lowered:
                return skill_name
        return None

    def _run_self_improver_draft(
        self,
        *,
        run: PipelineRun,
        definition: PipelineStepDefinition,
    ) -> dict[str, Any]:
        lookback_days = int(definition.config.get("lookback_days", 14))
        max_proposals = int(definition.config.get("max_proposals", 20))
        max_diff_lines = int(definition.config.get("max_diff_lines", 200))

        now = utcnow()
        since = now - timedelta(days=max(1, lookback_days))
        snapshot = self._service._store.read()

        from src.skills import load_skills

        skills = load_skills(enabled_only=False)
        skill_index = {
            skill.name.lower(): {
                "name": skill.name,
                "category": skill.category,
                "path": str(skill.skill_file),
                "skill_file": skill.skill_file,
            }
            for skill in skills
        }
        sorted_skill_names = sorted(skill_index.keys(), key=len, reverse=True)

        signals_by_skill: dict[str, dict[str, Any]] = {}
        skipped: list[dict[str, Any]] = []

        def bucket_for(skill_name: str) -> dict[str, Any]:
            bucket = signals_by_skill.get(skill_name)
            if bucket is not None:
                return bucket
            bucket = {
                "skill_name": skill_name,
                "completed_runs": 0,
                "failed_runs": 0,
                "cancelled_runs": 0,
                "rejected_approvals": 0,
                "thumbs_up": 0,
                "thumbs_down": 0,
                "alerts": 0,
                "error_steps": 0,
                "examples": [],
            }
            signals_by_skill[skill_name] = bucket
            return bucket

        def resolve_skill_name(*, metadata: dict[str, Any] | None, text: str) -> str | None:
            hint = self._skill_hint_from_metadata(metadata)
            if hint and hint in skill_index:
                return hint
            return self._find_skill_from_text(text, sorted_skill_names)

        for run_item in snapshot.runs.values():
            if run_item.created_at < since:
                continue

            step_errors = [step.error for step in run_item.steps if step.error]
            text_blob = " | ".join(
                part
                for part in [
                    run_item.template_name,
                    run_item.summary,
                    " ".join(run_item.alerts),
                    " ".join(str(step.name) for step in run_item.steps),
                    " ".join(str(err) for err in step_errors),
                ]
                if part
            )
            skill_name = resolve_skill_name(metadata=run_item.metadata, text=text_blob)
            if skill_name is None:
                continue

            bucket = bucket_for(skill_name)
            if run_item.status == "completed":
                bucket["completed_runs"] += 1
            if run_item.status == "failed":
                bucket["failed_runs"] += 1
            if run_item.status in {"cancelled", "rejected"}:
                bucket["cancelled_runs"] += 1
            bucket["alerts"] += len(run_item.alerts)
            bucket["error_steps"] += len(step_errors)
            if run_item.summary:
                bucket["examples"].append(self._clip_text(run_item.summary))

        for approval in snapshot.approvals.values():
            if approval.status != "rejected" or approval.resolved_at is None or approval.resolved_at < since:
                continue
            related_run = snapshot.runs.get(approval.pipeline_run_id)
            text_blob = " | ".join(
                part
                for part in [
                    approval.title,
                    approval.description,
                    approval.resolution_note or "",
                    related_run.summary if related_run else "",
                ]
                if part
            )
            metadata = approval.metadata if isinstance(approval.metadata, dict) else {}
            if related_run and isinstance(related_run.metadata, dict):
                metadata = {**related_run.metadata, **metadata}
            skill_name = resolve_skill_name(metadata=metadata, text=text_blob)
            if skill_name is None:
                continue
            bucket = bucket_for(skill_name)
            bucket["rejected_approvals"] += 1
            if approval.resolution_note:
                bucket["examples"].append(self._clip_text(approval.resolution_note))

        for feedback in snapshot.feedback.values():
            if feedback.created_at < since:
                continue

            related_run = (
                snapshot.runs.get(feedback.target_id)
                if feedback.target_type == "pipeline_run"
                else None
            )
            text_blob = " | ".join(
                part
                for part in [
                    feedback.comment,
                    related_run.summary if related_run else "",
                ]
                if part
            )
            metadata = feedback.metadata if isinstance(feedback.metadata, dict) else {}
            if related_run and isinstance(related_run.metadata, dict):
                metadata = {**related_run.metadata, **metadata}
            skill_name = resolve_skill_name(metadata=metadata, text=text_blob)
            if skill_name is None:
                continue
            bucket = bucket_for(skill_name)
            if feedback.value == "up":
                bucket["thumbs_up"] += 1
            if feedback.value == "down":
                bucket["thumbs_down"] += 1
            if feedback.comment:
                bucket["examples"].append(self._clip_text(feedback.comment))

        scored: list[tuple[int, dict[str, Any]]] = []
        for signal in signals_by_skill.values():
            score = (
                int(signal["failed_runs"])
                + int(signal["rejected_approvals"])
                + int(signal["thumbs_down"])
                + int(signal["error_steps"])
            )
            if score <= 0 and int(signal["thumbs_up"]) <= 0:
                continue
            scored.append((score, signal))

        scored.sort(key=lambda item: (item[0], item[1]["thumbs_down"], item[1]["failed_runs"]), reverse=True)

        proposals: list[dict[str, Any]] = []
        today = now.date().isoformat()
        for _, signal in scored:
            if len(proposals) >= max(1, max_proposals):
                break

            skill_name = str(signal["skill_name"])
            skill_meta = skill_index.get(skill_name)
            if skill_meta is None:
                skipped.append({"skill_name": skill_name, "reason": "skill_not_found"})
                continue

            skill_file = Path(str(skill_meta["skill_file"]))
            if not skill_file.exists():
                skipped.append({"skill_name": skill_name, "reason": "skill_file_missing"})
                continue

            original = skill_file.read_text(encoding="utf-8")
            validation = self.validate_skill_markdown(original)

            risk_score = (
                int(signal["failed_runs"])
                + int(signal["rejected_approvals"])
                + int(signal["thumbs_down"])
                + int(signal["error_steps"])
            )
            confidence = max(
                0.15,
                min(
                    0.95,
                    0.35
                    + 0.08 * risk_score
                    + 0.04 * int(signal["thumbs_up"])
                    - 0.02 * int(signal["alerts"]),
                ),
            )

            recommendation = (
                "Add a troubleshooting checklist and anti-pattern warning based on recent failed runs and down-votes."
                if risk_score > 0
                else "Reinforce best-practice guidance based on positive feedback."
            )
            evolution_block = (
                f"<!-- Evolution Draft: {today} | source: control-plane-signals -->\n"
                f"## Self-Improvement Draft ({today})\n"
                f"- Evidence: down={signal['thumbs_down']}, failed={signal['failed_runs']}, rejected={signal['rejected_approvals']}, errors={signal['error_steps']}\n"
                f"- Suggested update: {recommendation}\n"
            )

            updated = f"{original.rstrip()}\n\n{evolution_block}\n"
            diff_lines = list(
                difflib.unified_diff(
                    original.splitlines(),
                    updated.splitlines(),
                    fromfile="a/SKILL.md",
                    tofile="b/SKILL.md",
                    lineterm="",
                )
            )
            truncated = len(diff_lines) > max_diff_lines
            if truncated:
                diff_lines = diff_lines[:max_diff_lines] + ["...diff truncated..."]

            risk_flags: list[str] = []
            if not validation.get("frontmatter_ok"):
                risk_flags.append("frontmatter_invalid")
            if not validation.get("parse_ok"):
                risk_flags.append("skill_parse_risk")
            if truncated:
                risk_flags.append("diff_truncated")
            if confidence < 0.45:
                risk_flags.append("low_confidence")

            proposals.append(
                {
                    "id": f"draft-{len(proposals) + 1:03d}",
                    "skill_name": skill_meta["name"],
                    "category": skill_meta["category"],
                    "skill_path": skill_meta["path"],
                    "confidence": round(confidence, 2),
                    "summary": recommendation,
                    "recommended_addition": evolution_block.strip(),
                    "risk_flags": risk_flags,
                    "evidence": {
                        "completed_runs": signal["completed_runs"],
                        "failed_runs": signal["failed_runs"],
                        "cancelled_runs": signal["cancelled_runs"],
                        "rejected_approvals": signal["rejected_approvals"],
                        "thumbs_up": signal["thumbs_up"],
                        "thumbs_down": signal["thumbs_down"],
                        "alerts": signal["alerts"],
                        "error_steps": signal["error_steps"],
                        "examples": signal["examples"][:5],
                    },
                    "validation": validation,
                    "diff_preview": "\n".join(diff_lines),
                }
            )

        return {
            "version": "self-improver-draft.v1",
            "generated_at": now,
            "run_id": run.id,
            "signal_window": {
                "lookback_days": max(1, lookback_days),
                "since": since,
                "until": now,
            },
            "limits": {
                "max_proposals": max(1, max_proposals),
                "max_diff_lines": max(20, max_diff_lines),
            },
            "counts": {
                "skills_total": len(skill_index),
                "skills_with_signals": len(signals_by_skill),
                "proposals": len(proposals),
                "skipped": len(skipped),
            },
            "proposals": proposals,
            "skipped": skipped,
        }

    def _run_improver_scan(self, definition: PipelineStepDefinition) -> dict[str, Any]:
        repo_path = definition.config.get("repo_path")
        if not repo_path:
            raise ValueError("improver_scan step requires repo_path.")

        repo = Path(str(repo_path)).expanduser().resolve()
        if not repo.exists():
            raise FileNotFoundError(f"Repo path does not exist: {repo}")

        branch = self._run_command(["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"])
        status = self._run_command(["git", "-C", str(repo), "status", "--short"])
        remotes = self._run_command(["git", "-C", str(repo), "remote", "-v"])
        last_commit = self._run_command(["git", "-C", str(repo), "log", "-1", "--pretty=format:%H%n%cs%n%s"])

        return {
            "repo_path": str(repo),
            "branch": branch.strip(),
            "status": [line for line in status.splitlines() if line.strip()],
            "remotes": [line for line in remotes.splitlines() if line.strip()],
            "last_commit": last_commit.splitlines(),
            "feedback_summary": self._summarize_feedback_for_repo(str(repo)),
        }

    def _summarize_feedback_for_repo(self, repo_path: str) -> dict[str, Any]:
        relevant = [
            event
            for event in self._service.list_feedback()
            if event.metadata.get("repo_path") == repo_path or event.metadata.get("component") == repo_path
        ]
        return {
            "count": len(relevant),
            "thumbs_up": sum(1 for event in relevant if event.value == "up"),
            "thumbs_down": sum(1 for event in relevant if event.value == "down"),
        }

    def _run_command(self, args: list[str]) -> str:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "Unknown command error"
            raise RuntimeError(stderr)
        return result.stdout.strip()
