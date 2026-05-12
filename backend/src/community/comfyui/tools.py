from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from langchain.tools import tool

from src.config import get_app_config


def _load_workflow_template(default_workflow_path: str | None) -> dict[str, Any] | None:
    if not default_workflow_path:
        return None
    workflow_path = Path(default_workflow_path).expanduser().resolve()
    if not workflow_path.exists():
        raise FileNotFoundError(f"ComfyUI workflow template not found: {workflow_path}")
    return json.loads(workflow_path.read_text(encoding="utf-8"))


def _replace_prompt_tokens(value: Any, prompt: str) -> Any:
    if isinstance(value, dict):
        return {key: _replace_prompt_tokens(item, prompt) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_prompt_tokens(item, prompt) for item in value]
    if isinstance(value, str):
        if "{{prompt}}" in value:
            return value.replace("{{prompt}}", prompt)
        return value
    return value


def _inject_prompt_fields(value: Any, prompt: str) -> Any:
    if isinstance(value, dict):
        updated = {}
        for key, item in value.items():
            if key in {"text", "prompt", "positive", "positive_prompt"} and isinstance(item, str) and not item.strip():
                updated[key] = prompt
            else:
                updated[key] = _inject_prompt_fields(item, prompt)
        return updated
    if isinstance(value, list):
        return [_inject_prompt_fields(item, prompt) for item in value]
    return value


@tool("comfyui_generate", parse_docstring=True)
def comfyui_generate_tool(prompt: str, workflow_json: str = "") -> str:
    """Submit a generation request to a local ComfyUI server.

    Args:
        prompt: Prompt text to inject into the workflow.
        workflow_json: Optional workflow JSON string. If omitted, uses tool_backends.comfyui.default_workflow_path when configured.
    """
    try:
        backend = get_app_config().tool_backends.comfyui
        base_url = backend.base_url or os.getenv("COMFYUI_BASE_URL")
        if not backend.enabled and not base_url:
            return "Error: ComfyUI backend is not enabled. Configure tool_backends.comfyui or COMFYUI_BASE_URL."
        if not base_url:
            return "Error: ComfyUI base URL is not configured."

        default_workflow_path = None
        if backend.model_extra:
            default_workflow_path = backend.model_extra.get("default_workflow_path")

        workflow_data: dict[str, Any] | None = None
        if workflow_json.strip():
            workflow_data = json.loads(workflow_json)
        else:
            workflow_data = _load_workflow_template(default_workflow_path)

        if workflow_data is None:
            return "Error: Provide workflow_json or configure tool_backends.comfyui.default_workflow_path."

        workflow_data = _replace_prompt_tokens(workflow_data, prompt)
        workflow_data = _inject_prompt_fields(workflow_data, prompt)

        endpoint = f"{base_url.rstrip('/')}/prompt"
        with httpx.Client(timeout=backend.timeout_seconds if backend.enabled else 45.0) as client:
            response = client.post(
                endpoint,
                json={"prompt": workflow_data},
                headers={"Content-Type": "application/json", **backend.headers},
            )
            response.raise_for_status()
            data = response.json()

        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception as exc:
        return f"Error: {exc}"
