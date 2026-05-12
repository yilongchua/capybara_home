"""Gateway routes for Dreamy tab — workflow.json CRUD."""

import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from src.config.paths import get_paths

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["dreamy"])


def _workflow_path(thread_id: str) -> Path:
    return get_paths().sandbox_outputs_dir(thread_id) / "workflow.json"


def _mount_config_path(thread_id: str) -> Path:
    return get_paths().sandbox_user_data_dir(thread_id) / "dreamy_mount.json"


def _maybe_migrate_v1(data: dict) -> dict:
    """In-memory migration from v1 DAG schema to v2 steps schema. Does not rewrite the file."""
    if data.get("version") != "1":
        return data
    ts = data.get("task_source", {})
    es = data.get("execution_state", {})
    phase = es.get("phase", "design")
    if phase == "approval":
        phase = "awaiting_approval"
    return {
        "version": "2",
        "thread_id": data.get("thread_id"),
        "created_at": data.get("created_at"),
        "data_source": {
            "type": ts.get("type", "inline"),
            "filename": ts.get("filename", ""),
            "total_rows": ts.get("total_tasks", 0),
            "fields": ts.get("fields", []),
            "sample_rows": ts.get("sample_tasks", []),
        },
        "steps": [],
        "execution_state": {
            "phase": phase,
            "current_row_index": es.get("current_task_index", 0),
            "current_step_id": es.get("active_node_id"),
            "total_rows": es.get("total_tasks", 0),
            "poc_results": [],
            "seconds_per_row_estimate": None,
            "estimated_completion_iso": es.get("estimated_completion_iso"),
            "started_at": es.get("started_at"),
        },
    }


@router.get("/threads/{thread_id}/dreamy/workflow")
async def get_workflow(thread_id: str) -> dict:
    """Return the current workflow.json for a Dreamy thread (auto-migrates v1 → v2 in memory)."""
    path = _workflow_path(thread_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="workflow.json not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _maybe_migrate_v1(data)
    except Exception as exc:
        logger.error("Failed to read workflow.json for thread %s: %s", thread_id, exc)
        raise HTTPException(status_code=500, detail="Failed to read workflow.json") from exc


class WorkflowPatchRequest(BaseModel):
    workflow: dict


@router.patch("/threads/{thread_id}/dreamy/workflow")
async def patch_workflow(thread_id: str, req: WorkflowPatchRequest) -> dict:
    """Persist user edits to workflow.json from the node editor."""
    path = _workflow_path(thread_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(req.workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to write workflow.json for thread %s: %s", thread_id, exc)
        raise HTTPException(status_code=500, detail="Failed to write workflow.json") from exc
    return {"success": True}


class MountFolderRequest(BaseModel):
    path: str


@router.get("/threads/{thread_id}/dreamy/mount-folder")
async def get_mount_folder(thread_id: str) -> dict:
    path = _mount_config_path(thread_id)
    if not path.exists():
        return {"path": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to read dreamy mount config for thread %s: %s", thread_id, exc)
        raise HTTPException(status_code=500, detail="Failed to read mounted folder") from exc
    return {"path": data.get("path")}


@router.get("/threads/{thread_id}/dreamy/mount-folder/files")
async def list_mount_folder_files(thread_id: str) -> dict:
    """List files inside the mounted folder for a thread."""
    config_path = _mount_config_path(thread_id)
    if not config_path.exists():
        return {"files": [], "folder_path": None}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        folder_path_str = data.get("path")
    except Exception as exc:
        logger.error("Failed to read dreamy mount config for thread %s: %s", thread_id, exc)
        raise HTTPException(status_code=500, detail="Failed to read mounted folder config") from exc

    if not folder_path_str:
        return {"files": [], "folder_path": None}

    folder = Path(folder_path_str)
    if not folder.exists() or not folder.is_dir():
        return {"files": [], "folder_path": folder_path_str}

    try:
        files = []
        for p in sorted(folder.iterdir()):
            if p.is_file():
                stat = p.stat()
                files.append({
                    "name": p.name,
                    "size": stat.st_size,
                    "virtual_path": f"/mnt/user-data/mounted/{p.name}",
                    "full_path": str(p),
                    "is_dir": False,
                })
        # Expose /.docs explicitly and include its contents recursively so
        # /analyse outputs are visible in Artifact panels.
        docs_dir = folder / ".docs"
        if docs_dir.exists() and docs_dir.is_dir():
            files.append({
                "name": ".docs/",
                "size": 0,
                "virtual_path": "/mnt/user-data/mounted/.docs",
                "full_path": str(docs_dir),
                "is_dir": True,
            })
            for p in sorted(docs_dir.rglob("*")):
                if not p.is_file():
                    continue
                stat = p.stat()
                rel = p.relative_to(folder).as_posix()
                files.append({
                    "name": rel,
                    "size": stat.st_size,
                    "virtual_path": f"/mnt/user-data/mounted/{rel}",
                    "full_path": str(p),
                    "is_dir": False,
                })
        return {"files": files, "folder_path": folder_path_str}
    except Exception as exc:
        logger.error("Failed to list mounted folder for thread %s: %s", thread_id, exc)
        raise HTTPException(status_code=500, detail="Failed to list mounted folder files") from exc


@router.put("/threads/{thread_id}/dreamy/mount-folder")
async def put_mount_folder(thread_id: str, req: MountFolderRequest) -> dict:
    raw = (req.path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Path is required")
    if raw.startswith("/mnt/user-data/"):
        normalized_path = raw
    else:
        folder = Path(raw).expanduser().resolve()
        if not folder.exists() or not folder.is_dir():
            raise HTTPException(status_code=400, detail="Folder does not exist or is not a directory")
        normalized_path = str(folder)
    config_path = _mount_config_path(thread_id)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"path": normalized_path}
    try:
        config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to write dreamy mount config for thread %s: %s", thread_id, exc)
        raise HTTPException(status_code=500, detail="Failed to persist mounted folder") from exc
    return payload


@router.delete("/threads/{thread_id}/dreamy/mount-folder")
async def delete_mount_folder(thread_id: str) -> dict:
    config_path = _mount_config_path(thread_id)
    if not config_path.exists():
        return {"path": None}
    try:
        config_path.unlink()
    except Exception as exc:
        logger.error("Failed to delete dreamy mount config for thread %s: %s", thread_id, exc)
        raise HTTPException(status_code=500, detail="Failed to clear mounted folder") from exc
    return {"path": None}


# ─── Dreamy Executor control ──────────────────────────────────────────────────

def _signal_path(thread_id: str) -> Path:
    return get_paths().sandbox_outputs_dir(thread_id) / "pause_signal.json"


def _progress_path(thread_id: str) -> Path:
    return get_paths().sandbox_outputs_dir(thread_id) / "progress.json"


def _write_executor_signal(thread_id: str, signal: str) -> None:
    path = _signal_path(thread_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"signal": signal}), encoding="utf-8")


def _read_executor_progress(thread_id: str) -> dict:
    path = _progress_path(thread_id)
    if not path.exists():
        return {"state": "not_started"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"state": "unknown"}


@router.post("/threads/{thread_id}/dreamy/executor/pause")
async def pause_executor(thread_id: str) -> dict:
    """Signal the Dreamy Executor to stop at the next row boundary."""
    _write_executor_signal(thread_id, "pause")
    return {"signal": "pause", "thread_id": thread_id}


@router.post("/threads/{thread_id}/dreamy/executor/stop")
async def stop_executor(thread_id: str) -> dict:
    """Signal the Dreamy Executor to stop immediately after the current tool call."""
    _write_executor_signal(thread_id, "stop")
    return {"signal": "stop", "thread_id": thread_id}


@router.get("/threads/{thread_id}/dreamy/executor/status")
async def executor_status(thread_id: str) -> dict:
    """Return the current progress.json for the Dreamy Executor."""
    return _read_executor_progress(thread_id)


# ─── Native folder picker ─────────────────────────────────────────────────────

@router.get("/dreamy/pick-folder")
async def pick_folder() -> dict:
    """Open a native OS folder picker dialog and return the selected absolute path.

    macOS: uses osascript (always available).
    Linux: tries zenity, then kdialog, then yad.
    Returns {"path": "<absolute path>"} or {"path": null, "cancelled": true}.
    """
    import platform
    import subprocess as sp

    system = platform.system()
    try:
        if system == "Darwin":
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: sp.run(
                    ["osascript", "-e", "POSIX path of (choose folder)"],
                    capture_output=True, text=True, timeout=120,
                ),
            )
            if result.returncode != 0:
                return {"path": None, "cancelled": True}
            path = result.stdout.strip().rstrip("/")
            return {"path": path, "cancelled": False}

        if system == "Linux":
            pickers = [
                ["zenity", "--file-selection", "--directory", "--title=Select Folder"],
                ["kdialog", "--getexistingdirectory", "/"],
                ["yad", "--file", "--directory", "--title=Select Folder"],
            ]
            for cmd in pickers:
                try:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda c=cmd: sp.run(c, capture_output=True, text=True, timeout=120),
                    )
                    if result.returncode == 0:
                        return {"path": result.stdout.strip().rstrip("/"), "cancelled": False}
                    # Return code 1 typically means user cancelled
                    return {"path": None, "cancelled": True}
                except FileNotFoundError:
                    continue
            raise HTTPException(status_code=501, detail="No folder picker available — install zenity or kdialog")

        raise HTTPException(status_code=501, detail=f"Native folder picker not supported on {system}")

    except sp.TimeoutExpired:
        return {"path": None, "cancelled": True}


# ─── macOS file actions ───────────────────────────────────────────────────────

class FileActionRequest(BaseModel):
    path: str


def _require_macos() -> None:
    if sys.platform != "darwin":
        raise HTTPException(status_code=400, detail="This action is only supported on macOS")


def _resolve_safe_path(raw: str) -> Path:
    """Resolve and lightly validate a path — must be absolute and must exist."""
    p = Path(raw).expanduser().resolve()
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {raw}")
    return p


@router.post("/threads/{thread_id}/files/reveal")
async def reveal_in_finder(thread_id: str, req: FileActionRequest) -> dict:
    """Open the file's parent folder in Finder with the file selected (macOS only)."""
    _require_macos()
    p = _resolve_safe_path(req.path)
    asyncio.get_event_loop().run_in_executor(None, lambda: __import__("subprocess").Popen(["open", "-R", str(p)]))
    return {"success": True}


@router.post("/threads/{thread_id}/files/open")
async def open_in_default_app(thread_id: str, req: FileActionRequest) -> dict:
    """Open the file with its default application (macOS only)."""
    _require_macos()
    p = _resolve_safe_path(req.path)
    asyncio.get_event_loop().run_in_executor(None, lambda: __import__("subprocess").Popen(["open", str(p)]))
    return {"success": True}


@router.get("/threads/{thread_id}/files/thumbnail")
async def get_file_thumbnail(
    thread_id: str,
    path: str = Query(..., description="Absolute file path to generate thumbnail for"),
) -> Response:
    """Generate a Quick Look thumbnail for a file and return it as PNG (macOS only)."""
    _require_macos()
    p = _resolve_safe_path(path)

    with tempfile.TemporaryDirectory() as tmp_dir:
        proc = await asyncio.create_subprocess_exec(
            "qlmanage", "-t", "-s", "256", "-o", tmp_dir, str(p),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=10.0)
        except TimeoutError:
            proc.kill()
            raise HTTPException(status_code=504, detail="Thumbnail generation timed out")

        thumbnails = list(Path(tmp_dir).glob("*.png"))
        if not thumbnails:
            raise HTTPException(status_code=404, detail="No thumbnail could be generated for this file type")

        return Response(content=thumbnails[0].read_bytes(), media_type="image/png")
