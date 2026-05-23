"""Harness kill-switch API.

Exposes a single toggle that flips the lead agent between "full middleware
chain" (default) and "minimal plumbing subset" — an incident-response lever
without per-middleware fiddling. See
``src/config/harness_config.py`` for the underlying contract.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.config.harness_config import (
    HarnessConfig,
    get_harness_config,
    set_harness_config,
    write_harness_sidecar,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["harness"])


class HarnessConfigResponse(BaseModel):
    """Current harness kill-switch state."""

    enabled: bool = Field(description="False = agent runs with only the minimal plumbing subset.")


class HarnessConfigUpdateRequest(BaseModel):
    """Request model for toggling the harness kill switch."""

    enabled: bool = Field(description="True restores the full middleware chain; False drops to the minimal subset.")


@router.get(
    "/harness/config",
    response_model=HarnessConfigResponse,
    summary="Get Harness Configuration",
    description="Read the current harness-level kill-switch state.",
)
async def get_harness_configuration() -> HarnessConfigResponse:
    config = get_harness_config()
    return HarnessConfigResponse(enabled=config.enabled)


@router.put(
    "/harness/config",
    response_model=HarnessConfigResponse,
    summary="Update Harness Configuration",
    description=(
        "Toggle the harness kill switch. Writes the override to the "
        "`harness_runtime.json` sidecar so the LangGraph Server (separate process) "
        "picks it up on its next run via mtime detection — no restart required."
    ),
)
async def update_harness_configuration(request: HarnessConfigUpdateRequest) -> HarnessConfigResponse:
    try:
        new_config = HarnessConfig(enabled=request.enabled)
        path = write_harness_sidecar(new_config)
        set_harness_config(new_config)

        # Embedded CapyHomeClient instances include get_harness_config().enabled
        # in their agent cache key, so the toggle auto-invalidates any cached
        # agent on the next invoke. The LangGraph Server (separate process)
        # picks up the change through the sidecar mtime refresh in
        # get_harness_config(). No explicit reset required.
        logger.info("HarnessConfig updated via Gateway: enabled=%s (sidecar=%s)", new_config.enabled, path)
        return HarnessConfigResponse(enabled=new_config.enabled)
    except Exception as exc:
        logger.error("Failed to update harness configuration: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update harness configuration: {exc}")
