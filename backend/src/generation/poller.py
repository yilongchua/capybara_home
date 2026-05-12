from __future__ import annotations

import asyncio
import logging

from src.config import get_app_config
from src.generation.service import GenerationService

logger = logging.getLogger(__name__)


class GenerationPoller:
    def __init__(self, service: GenerationService | None = None) -> None:
        self._service = service or GenerationService()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        if not get_app_config().generation.enabled:
            logger.info("Generation poller is disabled by config")
            return
        self._task = asyncio.create_task(self._run_loop(), name="generation-poller")
        logger.info("Generation poller started")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("Generation poller stopped")

    async def _run_loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self._service.poll_pending_jobs_once)
            except Exception:
                logger.exception("Generation poller iteration failed")
            await asyncio.sleep(get_app_config().generation.poll_interval_seconds)


_generation_poller: GenerationPoller | None = None


async def start_generation_poller() -> GenerationPoller | None:
    global _generation_poller
    if not get_app_config().generation.enabled:
        return None
    if _generation_poller is None:
        _generation_poller = GenerationPoller()
    await _generation_poller.start()
    return _generation_poller


async def stop_generation_poller() -> None:
    global _generation_poller
    if _generation_poller is None:
        return
    await _generation_poller.stop()
    _generation_poller = None
