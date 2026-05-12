from __future__ import annotations

from typing import Any

__all__ = ["ControlPlaneService", "get_control_plane_service"]


def __getattr__(name: str) -> Any:
    if name in {"ControlPlaneService", "get_control_plane_service"}:
        from .service import ControlPlaneService, get_control_plane_service

        return {
            "ControlPlaneService": ControlPlaneService,
            "get_control_plane_service": get_control_plane_service,
        }[name]
    raise AttributeError(name)
