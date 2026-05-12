"""Artifact filesystem sub-service.

Owns the on-disk layout for pipeline run artifacts plus convenience writers
(``_write_json_artifact``, ``_write_text_artifact``) and the metadata-side
``_append_artifact`` mutation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.config import get_app_config, get_paths
from src.control_plane.models import utcnow
from src.control_plane.store import ControlPlaneStore


def _isoformat(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


class ArtifactsService:
    def __init__(self, store: ControlPlaneStore) -> None:
        self._store = store

    def artifact_root(self) -> Path:
        storage_dir = get_app_config().pipelines.storage_dir
        root = get_paths().base_dir / storage_dir / "runs"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def run_dir(self, run_id: str) -> Path:
        run_dir = self.artifact_root() / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def write_json_artifact(self, run_id: str, filename: str, data: Any) -> str:
        path = self.run_dir(run_id) / filename
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=_isoformat), encoding="utf-8")
        return str(path)

    def write_text_artifact(self, run_id: str, filename: str, content: str) -> str:
        path = self.run_dir(run_id) / filename
        path.write_text(content, encoding="utf-8")
        return str(path)

    def append_artifact(self, run_id: str, artifact_path: str) -> None:
        def mutate(snapshot):
            run = snapshot.runs[run_id]
            if artifact_path not in run.artifacts:
                run.artifacts.append(artifact_path)
                run.updated_at = utcnow()

        self._store.mutate(mutate)
