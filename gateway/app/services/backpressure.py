import asyncio
from typing import Optional

from .settings import Settings


class BackpressureManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.inflight: Optional[asyncio.Semaphore] = None
        self.buffer_slots: Optional[asyncio.Semaphore] = None

    def configure(self) -> None:
        if self._settings.BACKPRESSURE_MAX_INFLIGHT > 0:
            self.inflight = asyncio.Semaphore(self._settings.BACKPRESSURE_MAX_INFLIGHT)
        if self._settings.BACKPRESSURE_GLOBAL_BUFFER > 0:
            self.buffer_slots = asyncio.Semaphore(self._settings.BACKPRESSURE_GLOBAL_BUFFER)

    async def try_acquire_inflight(self) -> bool:
        if not self.inflight:
            return True
        try:
            await asyncio.wait_for(self.inflight.acquire(), timeout=0)
            return True
        except asyncio.TimeoutError:
            return False

    async def acquire_inflight(self) -> None:
        if self.inflight:
            await self.inflight.acquire()

    def release_inflight(self) -> None:
        if self.inflight:
            self.inflight.release()

    async def try_acquire_buffer_slot(self) -> bool:
        if not self.buffer_slots:
            return True
        try:
            await asyncio.wait_for(self.buffer_slots.acquire(), timeout=0)
            return True
        except asyncio.TimeoutError:
            return False

    def release_buffer_slot(self) -> None:
        if self.buffer_slots:
            self.buffer_slots.release()
