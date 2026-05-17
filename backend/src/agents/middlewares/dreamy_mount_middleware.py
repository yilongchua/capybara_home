"""Middleware to inject mounted folder info for work-mode mounted threads."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
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

        if existing_thread_data.get("mounted_prompt_injected_path") == mounted_path_str:
            return {"thread_data": updated_thread_data}

        messages = list(state.get("messages", []))
        if not messages:
            return {"thread_data": updated_thread_data}

        last_idx = len(messages) - 1
        last_msg = messages[last_idx]
        if not isinstance(last_msg, HumanMessage):
            return {"thread_data": updated_thread_data}

        lines = [
            "<mounted_folder>",
            f"A local folder is mounted and accessible at the virtual path: {VIRTUAL_MOUNT_PATH}",
            f"Real path on host: {mounted_path_str}",
            "",
            f"Derived analysis artifacts such as repo_overview.md, failed_files.md, and file_catalog.md are stored in {VIRTUAL_ANALYSE_PATH}.",
            "",
            f"Use {VIRTUAL_MOUNT_PATH}/<filename> with read_file, write_file, str_replace, bash, and ls.",
            "When the user references @filename (e.g. @work.txt), resolve it to "
            f"{VIRTUAL_MOUNT_PATH}/<filename>.",
            "You can read, edit, and create files directly in this folder — changes are persistent.",
            "</mounted_folder>",
        ]
        block = "\n".join(lines)

        original_content = last_msg.content
        if isinstance(original_content, str):
            updated_content = f"{block}\n\n{original_content}"
        elif isinstance(original_content, list):
            text_parts = [p.get("text", "") for p in original_content if isinstance(p, dict) and p.get("type") == "text"]
            updated_content = f"{block}\n\n" + "\n".join(text_parts)
        else:
            updated_content = f"{block}\n\n{original_content!s}"

        messages[last_idx] = HumanMessage(
            content=updated_content,
            id=last_msg.id,
            additional_kwargs=last_msg.additional_kwargs,
        )
        return {
            "thread_data": {**updated_thread_data, "mounted_prompt_injected_path": mounted_path_str},
            "messages": messages,
        }
