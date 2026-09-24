"""In-process daily scheduler for automation mappings.

Designed for a long-running local uvicorn process (same machine that runs
Playwright). Tick loop checks enabled schedules and starts jobs through the
shared starter callbacks.

Reliability:
- Persisted `fired_on_date` prevents double-fire after restarts
- If the API was down at run_time, a catch-up fires once when time >= run_time
  and today has not been fired yet
- If the global automation lock is busy, we retry on later ticks the same day
- Pause (enabled=false) skips without consuming the day slot
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from schedules_store import (
    KIND_BRAND_ENGAGE,
    KIND_BUILD_CONNECTION,
    KIND_COMPANY_PEOPLE,
    get_schedule,
    list_schedules,
)

logger = logging.getLogger(__name__)

TICK_SECONDS = 20

StartFn = Callable[..., Awaitable[dict[str, Any] | None]]


class AutomationScheduler:
    def __init__(
        self,
        *,
        start_company_people: StartFn,
        start_build_connection: StartFn,
        start_brand_engage: StartFn,
    ) -> None:
        self._start_company_people = start_company_people
        self._start_build_connection = start_build_connection
        self._start_brand_engage = start_brand_engage
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="automation-scheduler")
        logger.info("Automation scheduler started (tick=%ss)", TICK_SECONDS)

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Automation scheduler stopped")

    async def _loop(self) -> None:
        # Small delay so FastAPI finishes startup before first tick.
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=2.0)
            return
        except asyncio.TimeoutError:
            pass

        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                logger.exception("Scheduler tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=TICK_SECONDS)
                return
            except asyncio.TimeoutError:
                continue

    async def _tick(self) -> None:
        now = datetime.now().astimezone()
        local_date = now.date().isoformat()
        local_hm = now.strftime("%H:%M")

        for row in list_schedules():
            kind = row.get("kind")
            if kind not in (
                KIND_COMPANY_PEOPLE,
                KIND_BUILD_CONNECTION,
                KIND_BRAND_ENGAGE,
            ):
                continue
            if not row.get("enabled"):
                continue
            if row.get("fired_on_date") == local_date:
                continue
            run_time = row.get("run_time") or "09:00"
            if local_hm < run_time:
                continue

            schedule_id = row["id"]
            fresh = get_schedule(schedule_id)
            if not fresh or not fresh.get("enabled"):
                continue
            if fresh.get("fired_on_date") == local_date:
                continue

            logger.info(
                "Scheduler due: %s kind=%s session=%s audience=%s time=%s",
                schedule_id,
                fresh.get("kind"),
                fresh.get("session_name"),
                fresh.get("company")
                or fresh.get("source_ids")
                or fresh.get("source_id"),
                run_time,
            )
            try:
                if fresh.get("kind") == KIND_BUILD_CONNECTION:
                    run = await self._start_build_connection(
                        session_name=fresh["session_name"],
                        source_id=fresh.get("source_id") or "",
                        max_requests=int(fresh.get("max_profiles") or 10),
                        schedule_id=schedule_id,
                        local_date=local_date,
                        headless=True,
                    )
                elif fresh.get("kind") == KIND_BRAND_ENGAGE:
                    run = await self._start_brand_engage(
                        session_name=fresh.get("session_name") or "",
                        source_ids=list(fresh.get("source_ids") or []),
                        actions=list(fresh.get("actions") or []),
                        schedule_id=schedule_id,
                        local_date=local_date,
                        headless=True,
                    )
                else:
                    run = await self._start_company_people(
                        session_name=fresh["session_name"],
                        source_id=fresh["source_id"],
                        max_connections=int(fresh.get("max_profiles") or 10),
                        schedule_id=schedule_id,
                        local_date=local_date,
                        headless=True,
                    )
            except Exception as exc:
                logger.exception("Scheduled start failed for %s", schedule_id)
                from schedules_store import mark_run_result

                mark_run_result(schedule_id, status="error", error=str(exc))
                continue

            if run is None:
                logger.info(
                    "Scheduler deferred %s (busy or unavailable)", schedule_id
                )
                continue

            logger.info(
                "Scheduler started run %s for schedule %s",
                run.get("id"),
                schedule_id,
            )
