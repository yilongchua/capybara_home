"""Middleware to inject uploaded files information into agent context.

The ``<uploaded_files>`` block is injected **ephemerally** via
``wrap_model_call`` (per LLM call) rather than written into the canonical
message history. This is critical: the original implementation rewrote the
last ``HumanMessage`` content in place, so once a user uploaded a file the
upload bookkeeping would persist forever in thread state — every future
summarization snapshot would reference the upload, even if the user later
deleted the file. The ephemeral pattern mirrors ``MountFolderMiddleware``.
"""

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from src.config.paths import Paths, get_paths

logger = logging.getLogger(__name__)


class UploadsMiddlewareState(AgentState):
    """State schema for uploads middleware."""

    uploaded_files: NotRequired[list[dict] | None]


class UploadsMiddleware(AgentMiddleware[UploadsMiddlewareState]):
    """Middleware to inject uploaded files information into the agent context.

    Reads file metadata from the current message's additional_kwargs.files
    (set by the frontend after upload) and prepends an <uploaded_files> block
    to the last human message so the model knows which files are available.
    """

    state_schema = UploadsMiddlewareState

    def __init__(self, base_dir: str | None = None):
        """Initialize the middleware.

        Args:
            base_dir: Base directory for thread data. Defaults to Paths resolution.
        """
        super().__init__()
        self._paths = Paths(base_dir) if base_dir else get_paths()

    def _create_files_message(self, new_files: list[dict], historical_files: list[dict]) -> str:
        """Create a formatted message listing uploaded files.

        Args:
            new_files: Files uploaded in the current message.
            historical_files: Files uploaded in previous messages.

        Returns:
            Formatted string inside <uploaded_files> tags.
        """
        lines = ["<uploaded_files>"]

        lines.append("The following files were uploaded in this message:")
        lines.append("")
        if new_files:
            for file in new_files:
                size_kb = file["size"] / 1024
                size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
                lines.append(f"- {file['filename']} ({size_str})")
                lines.append(f"  Path: {file['path']}")
                lines.append("")
        else:
            lines.append("(empty)")

        if historical_files:
            lines.append("The following files were uploaded in previous messages and are still available:")
            lines.append("")
            for file in historical_files:
                size_kb = file["size"] / 1024
                size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
                lines.append(f"- {file['filename']} ({size_str})")
                lines.append(f"  Path: {file['path']}")
                lines.append("")

        lines.append("You can read these files using the `read_file` tool with the paths shown above.")
        lines.append("</uploaded_files>")

        return "\n".join(lines)

    def _files_from_kwargs(self, message: HumanMessage, uploads_dir: Path | None = None) -> list[dict] | None:
        """Extract file info from message additional_kwargs.files.

        The frontend sends uploaded file metadata in additional_kwargs.files
        after a successful upload. Each entry has: filename, size (bytes),
        path (virtual path), status.

        Args:
            message: The human message to inspect.
            uploads_dir: Physical uploads directory used to verify file existence.
                         When provided, entries whose files no longer exist are skipped.

        Returns:
            List of file dicts with virtual paths, or None if the field is absent or empty.
        """
        kwargs_files = (message.additional_kwargs or {}).get("files")
        if not isinstance(kwargs_files, list) or not kwargs_files:
            return None

        files = []
        for f in kwargs_files:
            if not isinstance(f, dict):
                continue
            filename = f.get("filename") or ""
            if not filename or Path(filename).name != filename:
                continue
            if uploads_dir is not None and not (uploads_dir / filename).is_file():
                continue
            files.append(
                {
                    "filename": filename,
                    "size": int(f.get("size") or 0),
                    "path": f"/mnt/user-data/workspace/uploads/{filename}",
                    "extension": Path(filename).suffix,
                }
            )
        return files if files else None

    def _scan_uploaded_files(self, runtime: Runtime, last_message: HumanMessage | None) -> tuple[list[dict], list[dict]]:
        """Compute (new_files, historical_files) for ephemeral injection.

        Pure computation — never mutates state.
        """
        thread_id = (getattr(runtime, "context", None) or {}).get("thread_id") if runtime else None
        uploads_dir = self._paths.sandbox_uploads_dir(thread_id) if thread_id else None

        new_files: list[dict] = (
            self._files_from_kwargs(last_message, uploads_dir) or []
            if isinstance(last_message, HumanMessage)
            else []
        )

        new_filenames = {f["filename"] for f in new_files}
        historical_files: list[dict] = []
        if uploads_dir and uploads_dir.exists():
            for file_path in sorted(uploads_dir.iterdir()):
                if file_path.is_file() and file_path.name not in new_filenames:
                    stat = file_path.stat()
                    historical_files.append(
                        {
                            "filename": file_path.name,
                            "size": stat.st_size,
                            "path": f"/mnt/user-data/workspace/uploads/{file_path.name}",
                            "extension": file_path.suffix,
                        }
                    )
        return new_files, historical_files

    @staticmethod
    def _extract_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            return "\n".join(parts)
        return str(content)

    @override
    def before_agent(self, state: dict, runtime: Runtime) -> dict | None:
        """Record newly-uploaded files in state for downstream consumers (frontend
        stream, memory filter). Does NOT mutate message content — the
        ``<uploaded_files>`` block is injected ephemerally in
        ``wrap_model_call``.
        """
        messages = state.get("messages", [])
        if not messages:
            return None
        last_message = messages[-1]
        if not isinstance(last_message, HumanMessage):
            return None

        thread_id = (getattr(runtime, "context", None) or {}).get("thread_id")
        uploads_dir = self._paths.sandbox_uploads_dir(thread_id) if thread_id else None
        new_files = self._files_from_kwargs(last_message, uploads_dir) or []
        if not new_files:
            return None

        logger.debug("Recorded new uploads: %s", [f["filename"] for f in new_files])
        return {"uploaded_files": new_files}

    def _inject_uploads_ephemerally(self, request: ModelRequest) -> ModelRequest:
        runtime = getattr(request, "runtime", None)
        messages = list(getattr(request, "messages", []) or [])
        if not messages:
            return request

        # Find the last HumanMessage in the model request.
        last_human_idx: int | None = None
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                last_human_idx = i
                break
        if last_human_idx is None:
            return request

        last_human = messages[last_human_idx]

        # If the prompt already contains the block (e.g. legacy thread state
        # written by the old in-place mutation), don't double-inject.
        original_content = self._extract_text(last_human.content)
        if "<uploaded_files>" in original_content:
            return request

        new_files, historical_files = self._scan_uploaded_files(runtime, last_human)
        if not new_files and not historical_files:
            return request

        files_message = self._create_files_message(new_files, historical_files)
        injected = HumanMessage(
            content=f"{files_message}\n\n{original_content}",
            id=last_human.id,
            additional_kwargs=last_human.additional_kwargs,
        )
        messages[last_human_idx] = injected
        return request.override(messages=messages)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._inject_uploads_ephemerally(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._inject_uploads_ephemerally(request))
