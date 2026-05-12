from __future__ import annotations

import asyncio
import logging

from src.config import get_app_config
from src.control_plane.service import get_control_plane_service

logger = logging.getLogger(__name__)


class ControlPlaneScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        config = get_app_config().scheduler
        if not config.enabled:
            logger.info("Control-plane scheduler disabled; skipping start.")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="control-plane-scheduler")
        logger.info("Control-plane scheduler started.")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Control-plane scheduler stopped.")

    async def _run_loop(self) -> None:
        while self._running:
            config = get_app_config().scheduler
            if not config.enabled:
                await asyncio.sleep(config.poll_interval_seconds)
                continue

            try:
                get_control_plane_service().run_scheduler_tick()
            except Exception:
                logger.exception("Control-plane scheduler tick failed.")

            await asyncio.sleep(config.poll_interval_seconds)


_scheduler: ControlPlaneScheduler | None = None


async def start_control_plane_scheduler() -> ControlPlaneScheduler | None:
    global _scheduler
    if _scheduler is None:
        _scheduler = ControlPlaneScheduler()
    await _scheduler.start()
    return _scheduler


async def stop_control_plane_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    await _scheduler.stop()
    _scheduler = None
