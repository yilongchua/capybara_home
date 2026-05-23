from __future__ import annotations

import json
import logging
import math
import shutil
from pathlib import Path
from typing import Any

import requests

from src.config import get_app_config
from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from src.generation.models import GenerationJob, GenerationSnapshot, utcnow
from src.generation.store import GenerationJobStore

logger = logging.getLogger(__name__)


class GenerationService:
    def __init__(self, store: GenerationJobStore | None = None) -> None:
        self._store = store or GenerationJobStore()

    def _config(self):
        return get_app_config().generation

    def _workflows_dir(self) -> Path:
        return Path(self._config().workflow_api_dir).expanduser().resolve()

    @staticmethod
    def _repo_root() -> Path:
        # backend/src/generation/service.py -> backend/src/generation -> backend/src -> backend -> repo-root
        return Path(__file__).resolve().parents[3]

    def _workflow_path_for_kind(self, kind: str) -> Path:
        cfg = self._config()
        filename = cfg.image_workflow_file if kind == "image" else cfg.video_workflow_file
        configured = (self._workflows_dir() / filename).resolve()
        if configured.exists():
            return configured

        fallback = (
            self._repo_root()
            / "skills"
            / "public"
            / ("image-generation" if kind == "image" else "video-generation")
            / "assets"
            / Path(filename).name
        ).resolve()
        if fallback.exists():
            logger.info("Using fallback workflow file for %s generation: %s", kind, fallback)
            return fallback

        return configured

    def _comfy_output_dir(self) -> Path:
        return Path(self._config().comfy_output_dir).expanduser().resolve()

    def _prefix_root(self) -> str:
        return self._config().filename_prefix_root.strip("/") or "capyhome"

    @staticmethod
    def _parse_aspect_ratio(aspect_ratio: str) -> tuple[int, int]:
        try:
            left, right = aspect_ratio.split(":")
            w = int(left.strip())
            h = int(right.strip())
            if w <= 0 or h <= 0:
                raise ValueError("invalid ratio")
            return w, h
        except Exception:
            return 1, 1

    def _aspect_ratio_to_dims(self, aspect_ratio: str, area: int = 1024 * 1024) -> tuple[int, int]:
        w_ratio, h_ratio = self._parse_aspect_ratio(aspect_ratio)
        width = int(math.sqrt(area * (w_ratio / h_ratio)))
        height = int(math.sqrt(area * (h_ratio / w_ratio)))
        width = max(64, round(width / 64) * 64)
        height = max(64, round(height / 64) * 64)
        return width, height

    def _load_workflow(self, kind: str) -> dict[str, Any]:
        workflow_path = self._workflow_path_for_kind(kind)
        if not workflow_path.exists():
            raise FileNotFoundError(f"Workflow file not found: {workflow_path}")
        return json.loads(workflow_path.read_text(encoding="utf-8"))

    def _patch_image_workflow(self, workflow: dict[str, Any], prompt_text: str, filename_prefix: str, aspect_ratio: str) -> dict[str, Any]:
        for node in workflow.values():
            if node.get("class_type") == "CLIPTextEncode":
                node.setdefault("inputs", {})["text"] = prompt_text

        width, height = self._aspect_ratio_to_dims(aspect_ratio)
        for node in workflow.values():
            if node.get("class_type") == "EmptySD3LatentImage":
                node.setdefault("inputs", {})["width"] = width
                node.setdefault("inputs", {})["height"] = height

        save_nodes = [node for node in workflow.values() if node.get("class_type") == "SaveImage"]
        if not save_nodes:
            raise ValueError("No SaveImage node found in image workflow")
        for node in save_nodes:
            node.setdefault("inputs", {})["filename_prefix"] = filename_prefix
        return workflow

    def _patch_video_workflow(self, workflow: dict[str, Any], prompt_text: str, filename_prefix: str) -> dict[str, Any]:
        for node in workflow.values():
            if node.get("class_type") == "CLIPTextEncode":
                title = str(node.get("_meta", {}).get("title", "")).lower()
                if "positive" in title:
                    node.setdefault("inputs", {})["text"] = prompt_text

        save_nodes = [node for node in workflow.values() if node.get("class_type") == "SaveVideo"]
        if not save_nodes:
            raise ValueError("No SaveVideo node found in video workflow")
        for node in save_nodes:
            node.setdefault("inputs", {})["filename_prefix"] = filename_prefix
        return workflow

    def _submit_to_comfy(self, workflow_prompt: dict[str, Any]) -> str:
        cfg = self._config()
        endpoint = f"{cfg.comfy_base_url.rstrip('/')}/prompt"
        response = requests.post(endpoint, json={"prompt": workflow_prompt}, timeout=cfg.comfy_timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        prompt_id = payload.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise RuntimeError(f"ComfyUI returned invalid prompt_id: {payload}")
        return prompt_id

    def submit_job(
        self,
        *,
        thread_id: str,
        kind: str,
        prompt_text: str,
        output_name: str,
        aspect_ratio: str = "16:9",
    ) -> GenerationJob:
        cfg = self._config()
        if not cfg.enabled:
            raise ValueError("Async generation is disabled in config")
        kind = kind.strip().lower()
        if kind not in {"image", "video"}:
            raise ValueError(f"Unsupported generation kind: {kind}")
        if not output_name:
            raise ValueError("output_name is required")

        filename_prefix = f"{self._prefix_root()}/{output_name}"
        expected_virtual_path = f"{VIRTUAL_PATH_PREFIX}/workspace/{filename_prefix}"
        prompt_excerpt = prompt_text[:120]
        now = utcnow()

        job = GenerationJob(
            thread_id=thread_id,
            kind=kind,  # type: ignore[arg-type]
            status="queued",
            filename_prefix=filename_prefix,
            expected_virtual_path=expected_virtual_path,
            prompt_excerpt=prompt_excerpt,
            output_name=output_name,
            aspect_ratio=aspect_ratio,
            created_at=now,
            updated_at=now,
        )

        workflow = self._load_workflow(kind)
        if kind == "image":
            workflow = self._patch_image_workflow(workflow, prompt_text, filename_prefix, aspect_ratio)
        else:
            workflow = self._patch_video_workflow(workflow, prompt_text, filename_prefix)

        prompt_id = self._submit_to_comfy(workflow)
        now = utcnow()
        job.prompt_id = prompt_id
        job.status = "submitted"
        job.updated_at = now

        def mutate(snapshot: GenerationSnapshot) -> GenerationJob:
            snapshot.jobs[job.id] = job
            return job

        return self._store.mutate(mutate)

    def get_job(self, job_id: str) -> GenerationJob | None:
        snapshot = self._store.read()
        return snapshot.jobs.get(job_id)

    def list_jobs(self, *, thread_id: str | None = None, limit: int = 50) -> list[GenerationJob]:
        snapshot = self._store.read()
        items = list(snapshot.jobs.values())
        if thread_id:
            items = [item for item in items if item.thread_id == thread_id]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[: max(1, min(limit, 200))]

    def list_completions(self, *, thread_id: str, since_seq: int = 0, limit: int = 20) -> list[GenerationJob]:
        snapshot = self._store.read()
        completed = [
            job
            for job in snapshot.jobs.values()
            if job.thread_id == thread_id
            and job.completion_seq is not None
            and job.completion_seq > since_seq
            and job.status in {"completed", "failed", "timed_out"}
        ]
        completed.sort(key=lambda item: item.completion_seq or 0)
        return completed[: max(1, min(limit, 100))]

    def _mark_terminal(
        self,
        *,
        job_id: str,
        status: str,
        error: str | None = None,
        source_output_path: str | None = None,
        output_virtual_path: str | None = None,
    ) -> None:
        now = utcnow()

        def mutate(snapshot: GenerationSnapshot) -> None:
            job = snapshot.jobs.get(job_id)
            if job is None:
                return
            if job.status in {"completed", "failed", "timed_out"}:
                return
            job.status = status  # type: ignore[assignment]
            job.error = error
            job.source_output_path = source_output_path
            job.output_virtual_path = output_virtual_path
            job.updated_at = now
            job.completed_at = now
            job.completion_seq = snapshot.next_completion_seq
            snapshot.next_completion_seq += 1

        self._store.mutate(mutate)

    def _mark_running_if_needed(self, job_id: str) -> None:
        now = utcnow()

        def mutate(snapshot: GenerationSnapshot) -> None:
            job = snapshot.jobs.get(job_id)
            if job is None:
                return
            if job.status in {"submitted", "queued"}:
                job.status = "running"
                job.updated_at = now

        self._store.mutate(mutate)

    def _history_endpoint(self, prompt_id: str) -> str:
        cfg = self._config()
        return f"{cfg.comfy_base_url.rstrip('/')}/history/{prompt_id}"

    def _fetch_history_entry(self, prompt_id: str) -> dict[str, Any] | None:
        cfg = self._config()
        response = requests.get(self._history_endpoint(prompt_id), timeout=cfg.comfy_timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        return payload.get(prompt_id)

    def _extract_generated_files(self, history_entry: dict[str, Any]) -> list[Path]:
        files: list[Path] = []
        outputs = history_entry.get("outputs", {})
        output_dir = self._comfy_output_dir()
        for node_output in outputs.values():
            if not isinstance(node_output, dict):
                continue
            for payload in node_output.values():
                if not isinstance(payload, list):
                    continue
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    filename = item.get("filename")
                    if not filename:
                        continue
                    subfolder = item.get("subfolder", "")
                    files.append(output_dir / subfolder / filename)
        return files

    def _copy_to_thread_outputs(self, thread_id: str, source_file: Path) -> str:
        source_file = source_file.resolve()
        workspace_dir = get_paths().sandbox_work_dir(thread_id)
        target_dir = workspace_dir / self._prefix_root()
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / source_file.name
        shutil.copy2(source_file, target_path)
        return f"{VIRTUAL_PATH_PREFIX}/workspace/{self._prefix_root()}/{source_file.name}"

    def poll_pending_jobs_once(self) -> int:
        cfg = self._config()
        if not cfg.enabled:
            return 0

        snapshot = self._store.read()
        now = utcnow()
        processed = 0
        pending = [job for job in snapshot.jobs.values() if job.status in {"queued", "submitted", "running"}]

        for job in pending:
            processed += 1
            age = (now - job.created_at).total_seconds()
            if age > cfg.max_job_age_seconds:
                self._mark_terminal(job_id=job.id, status="timed_out", error="Generation exceeded maximum allowed runtime")
                continue

            if not job.prompt_id:
                self._mark_terminal(job_id=job.id, status="failed", error="Missing ComfyUI prompt_id")
                continue

            try:
                history_entry = self._fetch_history_entry(job.prompt_id)
            except Exception as exc:
                logger.warning("Failed to fetch ComfyUI history for %s: %s", job.id, exc)
                continue

            if not history_entry:
                self._mark_running_if_needed(job.id)
                continue

            status_str = str(history_entry.get("status", {}).get("status_str", "")).lower()
            if status_str in {"error", "failed"}:
                messages = history_entry.get("status", {}).get("messages")
                error = f"ComfyUI generation failed ({status_str})"
                if messages:
                    error = f"{error}: {messages}"
                self._mark_terminal(job_id=job.id, status="failed", error=error)
                continue

            generated_files = self._extract_generated_files(history_entry)
            if not generated_files:
                self._mark_running_if_needed(job.id)
                continue

            preferred = [p for p in generated_files if f"/{self._prefix_root()}/" in str(p).replace("\\", "/")]
            chosen = preferred[0] if preferred else generated_files[0]
            if not chosen.exists():
                self._mark_running_if_needed(job.id)
                continue

            try:
                output_virtual_path = self._copy_to_thread_outputs(job.thread_id, chosen)
                self._mark_terminal(
                    job_id=job.id,
                    status="completed",
                    source_output_path=str(chosen),
                    output_virtual_path=output_virtual_path,
                )
            except Exception as exc:
                self._mark_terminal(job_id=job.id, status="failed", error=f"Failed to copy output file: {exc}")

        return processed


_generation_service: GenerationService | None = None


def get_generation_service() -> GenerationService:
    global _generation_service
    if _generation_service is None:
        _generation_service = GenerationService()
    return _generation_service
