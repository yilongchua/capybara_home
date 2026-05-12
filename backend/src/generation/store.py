from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TypeVar

from src.config import get_app_config
from src.config.paths import get_paths
from src.generation.models import GenerationSnapshot

T = TypeVar("T")


class GenerationJobStore:
    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            storage_dir = get_app_config().generation.storage_dir
            path = get_paths().base_dir / storage_dir / "state.json"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def read(self) -> GenerationSnapshot:
        with self._lock:
            if not self.path.exists():
                return GenerationSnapshot()
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return GenerationSnapshot.model_validate(data)

    def write(self, snapshot: GenerationSnapshot) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                suffix=".tmp",
                delete=False,
            ) as temp:
                json.dump(snapshot.model_dump(mode="json"), temp, indent=2)
                temp_path = Path(temp.name)
            temp_path.replace(self.path)

    def mutate(self, fn: Callable[[GenerationSnapshot], T]) -> T:
        with self._lock:
            snapshot = self.read()
            result = fn(snapshot)
            self.write(snapshot)
            return result
