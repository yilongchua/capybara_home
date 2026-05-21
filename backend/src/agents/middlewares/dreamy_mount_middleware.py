"""Middleware to inject mounted folder info for work-mode mounted threads."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage
from langgraph.runtime import Runtime

from src.agents.thread_state import ThreadDataState
from src.config.paths import get_paths

logger = logging.getLogger(__name__)

VIRTUAL_MOUNT_PATH = "/mnt/user-data/mounted"
VIRTUAL_ANALYSE_PATH = "/mnt/user-data/workspace/.analyse"


class DreamyMountState(AgentState):
    thread_data: NotRequired[ThreadDataState | None]


class DreamyMountMiddleware(AgentMiddleware[DreamyMountState]):
    """Inject mounted folder info into agent context for work mode only.

    Reads dreamy_mount.json, registers the real path under the virtual path
    /mnt/user-data/mounted so all sandbox tools (read_file, write_file, bash,
    str_replace) can access it.

    To reduce token bloat, the <mounted_folder> block is prepended only once per
    mounted path and only for work-mode runs. Plan mode relies on persistent
    lead-agent prompt instructions instead of per-turn injection.
    """

    state_schema = DreamyMountState

    def _mount_block(self, mounted_path_str: str) -> str:
        lines = [
            "<mounted_folder>",
            f"A local folder is mounted and accessible at"
            f"virtual path: {VIRTUAL_MOUNT_PATH}",
            f"Real path on host: {mounted_path_str}",
            f"Derived analysis artifacts such as 'repo_overview.md', 'failed_files.md', and 'file_catalog.md' are stored in {VIRTUAL_ANALYSE_PATH}.",
            f"Use {VIRTUAL_MOUNT_PATH}/<filename> with read_file, write_file, str_replace, bash, and ls.",
            f"When the user references @filename (e.g. @work.txt), resolve it to {VIRTUAL_MOUNT_PATH}/<filename>.",
            "You can read, edit, and create files directly in this folder — changes are persistent.",
        ]
        return "\n".join(lines)

    @override
    def before_agent(self, state: DreamyMountState, runtime: Runtime) -> dict | None:
        context = runtime.context if isinstance(runtime.context, dict) else {}
        mode = str(context.get("mode") or "").strip().lower() or "work"
        thread_id = context.get("thread_id")
        if not thread_id:
            return None

        paths = get_paths()
        mount_config = paths.sandbox_user_data_dir(thread_id) / "dreamy_mount.json"
        if not mount_config.exists():
            return None

        try:
            data = json.loads(mount_config.read_text(encoding="utf-8"))
            mounted_path_str = data.get("path")
        except Exception as exc:
            logger.warning("Failed to read dreamy mount config for thread %s: %s", thread_id, exc)
            return None

        if not mounted_path_str:
            return None

        folder = Path(mounted_path_str)
        if not folder.exists() or not folder.is_dir():
            logger.debug("Mounted folder does not exist or is not a directory: %s", mounted_path_str)
            return None

        # Update thread_data so the sandbox path-translation layer can resolve
        # /mnt/user-data/mounted/* → <real folder path>/*
        existing_thread_data: ThreadDataState = state.get("thread_data") or {}
        updated_thread_data: ThreadDataState = {**existing_thread_data, "mounted_path": mounted_path_str}

        if mode == "plan":
            return {"thread_data": updated_thread_data}

        return {"thread_data": updated_thread_data}

    def _with_ephemeral_mount_context(self, request: ModelRequest) -> ModelRequest:
        context = request.runtime.context if isinstance(request.runtime.context, dict) else {}
        mode = str(context.get("mode") or "").strip().lower() or "work"
        if mode == "plan":
            return request

        runtime_state = request.state if isinstance(getattr(request, "state", None), dict) else {}
        if not runtime_state:
            runtime_obj = getattr(request, "runtime", None)
            runtime_state = getattr(runtime_obj, "state", {}) if isinstance(getattr(runtime_obj, "state", None), dict) else {}
        thread_data = runtime_state.get("thread_data") if isinstance(runtime_state, dict) else None
        if not isinstance(thread_data, dict):
            return request

        mounted_path_str = str(thread_data.get("mounted_path") or "").strip()
        if not mounted_path_str:
            return request

        mount_msg = SystemMessage(content=self._mount_block(mounted_path_str), name="mounted_folder_context")
        return request.override(messages=[mount_msg, *request.messages])

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._with_ephemeral_mount_context(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._with_ephemeral_mount_context(request))
