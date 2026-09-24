"""Phase 1 API: create LinkedIn sessions, manual login, persist cookies."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from browser import BrowserManager, wait_for_manual_login
from store import (
    create_session,
    delete_session,
    get_session,
    get_session_public,
    list_sessions,
    load_storage_state,
    save_storage_state,
    set_status,
    validate_storage_state,
)
from sources_store import (
    SOURCE_KIND_COMPANY_PEOPLES,
    SOURCE_KIND_INDIVIDUAL,
    SOURCE_KIND_INFLUENCER,
    TYPE_INDIVIDUAL,
    TYPE_INFLUENCER,
    USE_CASE_INCREASE_NETWORK,
    USE_CASE_INCREASE_VISIBILITY,
    USE_CASE_REACH_OUT,
    create_company_peoples_source,
    create_individual_source,
    create_influencer_source,
    delete_source,
    get_source,
    list_sources,
)
from automations_store import (
    AUTOMATION_KIND_BRAND_ENGAGE,
    AUTOMATION_KIND_BUILD_CONNECTION,
    AUTOMATION_KIND_COMPANY_PEOPLE,
    create_run,
    get_run_public,
    list_runs,
    update_run,
)
from company_people_job import run_company_people_fetch
from build_connection_job import run_build_connection
from brand_engage_job import (
    ENGAGE_SOURCES,
    normalize_actions,
    resolve_sources,
    run_brand_engage,
)
from profiles_store import list_profiles
from schedules_store import (
    KIND_BRAND_ENGAGE as SCHEDULE_KIND_BRAND_ENGAGE,
    KIND_BUILD_CONNECTION as SCHEDULE_KIND_BUILD_CONNECTION,
    KIND_COMPANY_PEOPLE as SCHEDULE_KIND_COMPANY_PEOPLE,
    create_schedule,
    delete_schedule,
    get_schedule_public,
    list_schedules,
    mark_fired,
    mark_run_result,
    set_enabled,
    update_schedule,
)
from scheduler import AutomationScheduler
from db import init_db


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory login job status (name -> {status, logs, error})
_login_jobs: dict[str, dict[str, Any]] = {}
_login_locks: dict[str, asyncio.Lock] = {}
_automation_lock = asyncio.Lock()
_running_automation_id: str | None = None
_scheduler: AutomationScheduler | None = None


def _job(name: str) -> dict[str, Any]:
    return _login_jobs.setdefault(
        name, {"status": "idle", "logs": [], "error": None}
    )


def _log(name: str, msg: str) -> None:
    job = _job(name)
    job["logs"].append(msg)
    logger.info("[%s] %s", name, msg)


async def _run_login(name: str) -> None:
    job = _job(name)
    job["status"] = "running"
    job["logs"] = []
    job["error"] = None
    set_status(name, "logging_in")
    try:
        _log(name, "Opening LinkedIn login — use email/password (not Google)")
        async with BrowserManager(headless=False) as browser:
            await browser.page.goto(
                "https://www.linkedin.com/login", wait_until="domcontentloaded"
            )
            _log(name, "Waiting for you to finish login (up to 5 minutes)…")
            await wait_for_manual_login(browser.page, timeout_ms=300_000)
            state = await browser.export_session_state()
            cookies = state.get("cookies") or []
            save_storage_state(name, state)
            _log(name, f"Saved session with {len(cookies)} cookies")
        job["status"] = "done"
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        set_status(name, "missing")
        _log(name, f"Login failed: {exc}")


async def _start_company_people_fetch(
    *,
    session_name: str,
    source_id: str,
    max_connections: int,
    schedule_id: str | None = None,
    local_date: str | None = None,
    headless: bool = False,
    raise_on_busy: bool = True,
) -> dict[str, Any] | None:
    """Shared starter for manual Activate and the daily scheduler.

    Returns the public run dict when started. When raise_on_busy is False
    (scheduler path), returns None if another automation is already running.
    """
    global _running_automation_id

    session = get_session(session_name)
    if not session:
        raise ValueError("session not found")
    cookies = (session.get("storage_state") or {}).get("cookies") or []
    if not cookies:
        raise ValueError("session is not logged in — complete Phase 1 login first")

    source = get_source(source_id)
    if not source or source.get("source_kind") != SOURCE_KIND_COMPANY_PEOPLES:
        raise ValueError("Company Peoples source not found")

    if _automation_lock.locked() or _running_automation_id:
        if raise_on_busy:
            raise RuntimeError("another automation is already running")
        return None

    trigger = "schedule" if schedule_id else "manual"
    run = create_run(
        kind=AUTOMATION_KIND_COMPANY_PEOPLE,
        session_name=session_name,
        company=source.get("company") or "",
        source_id=source_id,
        source_link=source.get("link") or "",
        max_connections=max_connections,
        schedule_id=schedule_id,
        trigger=trigger,
    )
    _running_automation_id = run["id"]

    if schedule_id and local_date:
        mark_fired(schedule_id, local_date=local_date, run_id=run["id"])

    async def _guarded() -> None:
        global _running_automation_id
        async with _automation_lock:
            try:
                await run_company_people_fetch(
                    run_id=run["id"],
                    session_name=session_name,
                    company=source.get("company") or "",
                    source_link=source.get("link") or "",
                    max_connections=max_connections,
                    source_id=source_id,
                    headless=headless,
                )
                if schedule_id:
                    final = get_run_public(run["id"])
                    status = (final or {}).get("status") or "done"
                    mark_run_result(
                        schedule_id,
                        status=status,
                        error=(final or {}).get("error"),
                    )
            except Exception as exc:
                update_run(run["id"], status="error", error=str(exc))
                from automations_store import append_log

                append_log(run["id"], f"Failed: {exc}")
                if schedule_id:
                    mark_run_result(schedule_id, status="error", error=str(exc))
            finally:
                _running_automation_id = None

    asyncio.create_task(_guarded())
    return run


async def _scheduler_start_company_people(**kwargs: Any) -> dict[str, Any] | None:
    try:
        return await _start_company_people_fetch(
            raise_on_busy=False,
            **kwargs,
        )
    except ValueError as exc:
        schedule_id = kwargs.get("schedule_id")
        local_date = kwargs.get("local_date")
        if schedule_id:
            # Consume the day so a bad mapping does not spam every tick.
            fields: dict[str, Any] = {
                "last_run_status": "error",
                "last_error": str(exc),
            }
            if local_date:
                fields["fired_on_date"] = local_date
            update_schedule(schedule_id, **fields)
        logger.warning("Scheduled company people skipped: %s", exc)
        return None


async def _start_build_connection(
    *,
    session_name: str,
    max_requests: int,
    source_id: str = "",
    schedule_id: str | None = None,
    local_date: str | None = None,
    headless: bool = False,
    raise_on_busy: bool = True,
) -> dict[str, Any] | None:
    """Shared starter for manual Activate and scheduled Build Connection."""
    global _running_automation_id

    session = get_session(session_name)
    if not session:
        raise ValueError("session not found")
    cookies = (session.get("storage_state") or {}).get("cookies") or []
    if not cookies:
        raise ValueError("session is not logged in — complete Phase 1 login first")

    company = ""
    source_link = ""
    if source_id:
        source = get_source(source_id)
        if not source or source.get("source_kind") != SOURCE_KIND_COMPANY_PEOPLES:
            raise ValueError("Audience source not found — pick a Company Peoples source")
        company = source.get("company") or ""
        source_link = source.get("link") or ""
    else:
        raise ValueError("audience (source_id) is required")

    if _automation_lock.locked() or _running_automation_id:
        if raise_on_busy:
            raise RuntimeError("another automation is already running")
        return None

    trigger = "schedule" if schedule_id else "manual"
    run = create_run(
        kind=AUTOMATION_KIND_BUILD_CONNECTION,
        session_name=session_name,
        max_requests=max_requests,
        company=company,
        source_id=source_id,
        source_link=source_link,
        schedule_id=schedule_id,
        trigger=trigger,
    )
    _running_automation_id = run["id"]

    if schedule_id and local_date:
        mark_fired(schedule_id, local_date=local_date, run_id=run["id"])

    async def _guarded() -> None:
        global _running_automation_id
        async with _automation_lock:
            try:
                await run_build_connection(
                    run_id=run["id"],
                    session_name=session_name,
                    max_requests=max_requests,
                    source_id=source_id,
                    source_company=company,
                    headless=headless,
                )
                if schedule_id:
                    final = get_run_public(run["id"])
                    status = (final or {}).get("status") or "done"
                    mark_run_result(
                        schedule_id,
                        status=status,
                        error=(final or {}).get("error"),
                    )
            except Exception as exc:
                update_run(run["id"], status="error", error=str(exc))
                from automations_store import append_log

                append_log(run["id"], f"Failed: {exc}")
                if schedule_id:
                    mark_run_result(schedule_id, status="error", error=str(exc))
            finally:
                _running_automation_id = None

    asyncio.create_task(_guarded())
    return run


async def _scheduler_start_build_connection(**kwargs: Any) -> dict[str, Any] | None:
    try:
        return await _start_build_connection(raise_on_busy=False, **kwargs)
    except ValueError as exc:
        schedule_id = kwargs.get("schedule_id")
        local_date = kwargs.get("local_date")
        if schedule_id:
            fields: dict[str, Any] = {
                "last_run_status": "error",
                "last_error": str(exc),
            }
            if local_date:
                fields["fired_on_date"] = local_date
            update_schedule(schedule_id, **fields)
        logger.warning("Scheduled build connection skipped: %s", exc)
        return None


async def _start_brand_engage(
    *,
    session_name: str,
    source_ids: list[str] | None = None,
    actions: list[str] | None = None,
    schedule_id: str | None = None,
    local_date: str | None = None,
    headless: bool = False,
    raise_on_busy: bool = True,
) -> dict[str, Any] | None:
    global _running_automation_id

    session = get_session(session_name)
    if not session:
        raise ValueError("session not found")
    cookies = (session.get("storage_state") or {}).get("cookies") or []
    if not cookies:
        raise ValueError("session is not logged in — complete Phase 1 login first")

    sources = resolve_sources(source_ids=source_ids or None)
    action_list = normalize_actions(actions)

    if _automation_lock.locked() or _running_automation_id:
        if raise_on_busy:
            raise RuntimeError("another automation is already running")
        return None

    labels = ", ".join(s["label"] for s in sources)
    trigger = "schedule" if schedule_id else "manual"
    run = create_run(
        kind=AUTOMATION_KIND_BRAND_ENGAGE,
        session_name=session_name,
        company=f"Brand Engage · {len(sources)} audience(s)",
        source_id=",".join(s["id"] for s in sources),
        source_link=labels,
        max_connections=0,
        max_requests=0,
        schedule_id=schedule_id,
        trigger=trigger,
    )
    _running_automation_id = run["id"]

    if schedule_id and local_date:
        mark_fired(schedule_id, local_date=local_date, run_id=run["id"])

    async def _guarded() -> None:
        global _running_automation_id
        async with _automation_lock:
            try:
                await run_brand_engage(
                    run_id=run["id"],
                    session_name=session_name,
                    source_ids=[s["id"] for s in sources],
                    actions=action_list,
                    headless=headless,
                )
                if schedule_id:
                    final = get_run_public(run["id"])
                    status = (final or {}).get("status") or "done"
                    mark_run_result(
                        schedule_id,
                        status=status,
                        error=(final or {}).get("error"),
                    )
            except Exception as exc:
                update_run(run["id"], status="error", error=str(exc))
                from automations_store import append_log

                append_log(run["id"], f"Failed: {exc}")
                if schedule_id:
                    mark_run_result(schedule_id, status="error", error=str(exc))
            finally:
                _running_automation_id = None

    asyncio.create_task(_guarded())
    return run


async def _scheduler_start_brand_engage(**kwargs: Any) -> dict[str, Any] | None:
    try:
        return await _start_brand_engage(raise_on_busy=False, **kwargs)
    except ValueError as exc:
        schedule_id = kwargs.get("schedule_id")
        local_date = kwargs.get("local_date")
        if schedule_id:
            fields: dict[str, Any] = {
                "last_run_status": "error",
                "last_error": str(exc),
            }
            if local_date:
                fields["fired_on_date"] = local_date
            update_schedule(schedule_id, **fields)
        logger.warning("Scheduled brand engage skipped: %s", exc)
        return None


def _backfill_profile_source_ids() -> int:
    """Attach source_id to older profiles that only have source_company."""
    from profiles_store import backfill_source_ids

    by_company: dict[str, str] = {}
    for src in list_sources(source_kind=SOURCE_KIND_COMPANY_PEOPLES):
        name = (src.get("company") or "").strip().lower()
        if name and name not in by_company:
            by_company[name] = src["id"]
    return backfill_source_ids(by_company)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _scheduler
    try:
        path = init_db()
        logger.info("Database ready: %s", path)
    except Exception:
        logger.exception("Database init failed")
        raise

    try:
        n = _backfill_profile_source_ids()
        if n:
            logger.info("Backfilled source_id on %s profile(s)", n)
    except Exception:
        logger.exception("Profile source_id backfill failed")

    _scheduler = AutomationScheduler(
        start_company_people=_scheduler_start_company_people,
        start_build_connection=_scheduler_start_build_connection,
        start_brand_engage=_scheduler_start_brand_engage,
    )
    _scheduler.start()
    try:
        yield
    finally:
        if _scheduler:
            await _scheduler.stop()
        _scheduler = None


app = FastAPI(title="Hexawealth LinkedIn Marketing", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateSessionBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class ImportStorageStateBody(BaseModel):
    """Manual upload of Playwright storage_state (cookies + optional origins).

    Use this to dump a session captured locally into another environment (e.g. prod)
    without opening a headed browser on the target machine.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Session label; created if it does not exist",
    )
    storage_state: dict[str, Any] = Field(
        ...,
        description="Playwright storage_state JSON with a non-empty cookies array",
    )


class CreateCompanyPeoplesSourceBody(BaseModel):
    """Type 1 · Company Peoples — paste a company /people/ URL."""

    link: str = Field(..., min_length=8)
    company: str = Field(default="", max_length=120)
    type: str = Field(default=TYPE_INDIVIDUAL)
    use_case: str = Field(default=USE_CASE_INCREASE_NETWORK)


class CreateInfluencerSourceBody(BaseModel):
    """Type 2 · Influencer — paste a profile URL; company = their name."""

    link: str = Field(..., min_length=8)
    company: str = Field(default="", max_length=120, description="Influencer name")
    type: str = Field(default=TYPE_INFLUENCER)
    use_case: str = Field(default=USE_CASE_INCREASE_VISIBILITY)


class CreateIndividualSourceBody(BaseModel):
    """Type 3 · Individual — paste a profile URL; company = their name."""

    link: str = Field(..., min_length=8)
    company: str = Field(default="", max_length=120, description="Person name")
    type: str = Field(default=TYPE_INDIVIDUAL)
    use_case: str = Field(default=USE_CASE_REACH_OUT)


class ActivateCompanyPeopleBody(BaseModel):
    """Type 1 automation — fetch + scrape people from a Company Peoples source."""

    session_name: str = Field(..., min_length=1)
    source_id: str = Field(..., min_length=1)
    max_connections: int = Field(default=10, ge=1, le=100)


class ActivateBuildConnectionBody(BaseModel):
    """Type 2 automation — send connection requests to stored profiles."""

    session_name: str = Field(..., min_length=1)
    source_id: str = Field(
        ..., min_length=1, description="Audience = Company Peoples source id"
    )
    max_requests: int = Field(default=10, ge=1, le=50)


class CreateCompanyPeopleScheduleBody(BaseModel):
    """Daily schedule mapping: session → Company Peoples source."""

    session_name: str = Field(..., min_length=1)
    source_id: str = Field(..., min_length=1)
    max_profiles: int = Field(default=10, ge=1, le=100)
    run_time: str = Field(default="09:00", description="Local HH:MM (24h)")
    enabled: bool = True


class CreateBuildConnectionScheduleBody(BaseModel):
    """Daily schedule: session → audience (fetched profiles from a source)."""

    session_name: str = Field(..., min_length=1)
    source_id: str = Field(
        ..., min_length=1, description="Audience = Company Peoples source id"
    )
    max_profiles: int = Field(
        default=10, ge=1, le=50, description="Max connection requests per run"
    )
    run_time: str = Field(default="10:00", description="Local HH:MM (24h)")
    enabled: bool = True


class ActivateBrandEngageBody(BaseModel):
    """Type 3 — engage latest posts for selected brand audiences + actions."""

    session_name: str = Field(..., min_length=1)
    source_ids: list[str] = Field(
        default_factory=list,
        description="Brand source ids; empty = all",
    )
    actions: list[str] = Field(
        default_factory=lambda: ["like", "comment", "repost"],
        description="Subset of like, comment, repost",
    )


class CreateBrandEngageScheduleBody(BaseModel):
    """Daily Brand Engage schedule: session + audiences + actions + local time."""

    session_name: str = Field(..., min_length=1)
    source_ids: list[str] = Field(
        default_factory=list,
        description="Brand source ids; empty = all four",
    )
    actions: list[str] = Field(
        default_factory=lambda: ["like", "comment", "repost"],
    )
    run_time: str = Field(default="11:00", description="Local HH:MM (24h)")
    enabled: bool = True


class UpdateScheduleBody(BaseModel):
    session_name: str | None = Field(default=None, min_length=1)
    source_id: str | None = Field(default=None, min_length=1)
    max_profiles: int | None = Field(default=None, ge=0, le=100)
    run_time: str | None = None
    enabled: bool | None = None
    source_ids: list[str] | None = None
    actions: list[str] | None = None


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/api/sessions")
async def api_list_sessions() -> dict:
    return {"sessions": list_sessions()}


@app.post("/api/sessions")
async def api_create_session(body: CreateSessionBody) -> dict:
    try:
        return create_session(body.name)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/sessions/{name}")
async def api_delete_session(name: str) -> dict:
    if not delete_session(name):
        raise HTTPException(404, "session not found")
    _login_jobs.pop(name, None)
    return {"ok": True}


@app.post("/api/sessions/{name}/login")
async def api_start_login(name: str) -> dict:
    if not get_session(name):
        raise HTTPException(404, "session not found — create it first")
    lock = _login_locks.setdefault(name, asyncio.Lock())
    if lock.locked() or _job(name)["status"] == "running":
        raise HTTPException(409, "login already in progress for this session")

    async def _guarded() -> None:
        async with lock:
            await _run_login(name)

    asyncio.create_task(_guarded())
    return {"ok": True, "session_name": name, "message": "browser opening…"}


@app.get("/api/sessions/{name}/login-status")
async def api_login_status(name: str) -> dict:
    job = _job(name)
    return {
        "session_name": name,
        "status": job["status"],
        "logs": job["logs"],
        "error": job["error"],
        "session": get_session_public(name),
    }


@app.get("/api/sessions/{name}/storage-state")
async def api_export_storage_state(name: str) -> dict:
    """Download full Playwright storage_state for transfer to another environment."""
    if not get_session(name):
        raise HTTPException(404, "session not found")
    try:
        state = load_storage_state(name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "name": name,
        "storage_state": state,
        "cookie_count": len(state.get("cookies") or []),
    }


@app.put("/api/sessions/{name}/storage-state")
async def api_import_storage_state_for_name(
    name: str, body: dict[str, Any]
) -> dict:
    """Import cookies onto an existing or new session name (path param)."""
    try:
        state = validate_storage_state(body)
        return save_storage_state(name, state)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/sessions/import")
async def api_import_storage_state(body: ImportStorageStateBody) -> dict:
    """Create-or-update a session from pasted/uploaded Playwright storage_state."""
    try:
        state = validate_storage_state(body.storage_state)
        return save_storage_state(body.name, state)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# —— Phase 2 · Sources ——


@app.get("/api/sources")
async def api_list_sources(source_kind: str | None = None) -> dict:
    return {"sources": list_sources(source_kind=source_kind)}


@app.post("/api/sources/company-peoples")
async def api_create_company_peoples(body: CreateCompanyPeoplesSourceBody) -> dict:
    try:
        return create_company_peoples_source(
            link=body.link,
            company=body.company,
            type_=body.type,
            use_case=body.use_case,
        )
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/sources/influencer")
async def api_create_influencer(body: CreateInfluencerSourceBody) -> dict:
    try:
        return create_influencer_source(
            link=body.link,
            company=body.company,
            type_=body.type,
            use_case=body.use_case,
        )
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/sources/individual")
async def api_create_individual(body: CreateIndividualSourceBody) -> dict:
    try:
        return create_individual_source(
            link=body.link,
            company=body.company,
            type_=body.type,
            use_case=body.use_case,
        )
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/sources/{source_id}")
async def api_delete_source(source_id: str) -> dict:
    if not delete_source(source_id):
        raise HTTPException(404, "source not found")
    return {"ok": True}


@app.get("/api/source-kinds")
async def api_source_kinds() -> dict:
    return {
        "kinds": [
            {
                "id": SOURCE_KIND_COMPANY_PEOPLES,
                "label": "Company Peoples",
                "type_default": TYPE_INDIVIDUAL,
                "use_case_default": USE_CASE_INCREASE_NETWORK,
                "example_url": "https://www.linkedin.com/company/google/people/",
            },
            {
                "id": SOURCE_KIND_INFLUENCER,
                "label": "Influencer",
                "type_default": TYPE_INFLUENCER,
                "use_case_default": USE_CASE_INCREASE_VISIBILITY,
                "example_url": "https://www.linkedin.com/in/example/",
            },
            {
                "id": SOURCE_KIND_INDIVIDUAL,
                "label": "Individual",
                "type_default": TYPE_INDIVIDUAL,
                "use_case_default": USE_CASE_REACH_OUT,
                "example_url": "https://www.linkedin.com/in/example/",
            },
        ]
    }


# —— Phase 3 · Automations ——


@app.get("/api/automations")
async def api_list_automations(kind: str | None = None) -> dict:
    return {"runs": list_runs(kind=kind)}


@app.get("/api/automations/{run_id}")
async def api_get_automation(run_id: str) -> dict:
    row = get_run_public(run_id)
    if not row:
        raise HTTPException(404, "automation run not found")
    return row


@app.post("/api/automations/company-people")
async def api_activate_company_people(body: ActivateCompanyPeopleBody) -> dict:
    try:
        run = await _start_company_people_fetch(
            session_name=body.session_name,
            source_id=body.source_id,
            max_connections=body.max_connections,
            headless=False,
            raise_on_busy=True,
        )
    except ValueError as exc:
        msg = str(exc)
        code = 404 if "not found" in msg else 400
        raise HTTPException(code, msg) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    assert run is not None
    return run


# —— Schedules (daily automation mappings) ——


@app.get("/api/schedules")
async def api_list_schedules(kind: str | None = None) -> dict:
    return {"schedules": list_schedules(kind=kind)}


@app.post("/api/schedules/company-people")
async def api_create_company_people_schedule(
    body: CreateCompanyPeopleScheduleBody,
) -> dict:
    session = get_session(body.session_name)
    if not session:
        raise HTTPException(404, "session not found")
    cookies = (session.get("storage_state") or {}).get("cookies") or []
    if not cookies:
        raise HTTPException(
            400, "session is not logged in — complete Phase 1 login first"
        )

    source = get_source(body.source_id)
    if not source or source.get("source_kind") != SOURCE_KIND_COMPANY_PEOPLES:
        raise HTTPException(404, "Company Peoples source not found")

    try:
        return create_schedule(
            kind=SCHEDULE_KIND_COMPANY_PEOPLE,
            session_name=body.session_name,
            source_id=body.source_id,
            company=source.get("company") or "",
            source_link=source.get("link") or "",
            max_profiles=body.max_profiles,
            run_time=body.run_time,
            enabled=body.enabled,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/schedules/build-connection")
async def api_create_build_connection_schedule(
    body: CreateBuildConnectionScheduleBody,
) -> dict:
    session = get_session(body.session_name)
    if not session:
        raise HTTPException(404, "session not found")
    cookies = (session.get("storage_state") or {}).get("cookies") or []
    if not cookies:
        raise HTTPException(
            400, "session is not logged in — complete Phase 1 login first"
        )

    source = get_source(body.source_id)
    if not source or source.get("source_kind") != SOURCE_KIND_COMPANY_PEOPLES:
        raise HTTPException(404, "Audience source not found")

    try:
        return create_schedule(
            kind=SCHEDULE_KIND_BUILD_CONNECTION,
            session_name=body.session_name,
            source_id=body.source_id,
            company=source.get("company") or "",
            source_link=source.get("link") or "",
            max_profiles=body.max_profiles,
            run_time=body.run_time,
            enabled=body.enabled,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/schedules/brand-engage")
async def api_create_brand_engage_schedule(
    body: CreateBrandEngageScheduleBody,
) -> dict:
    session = get_session(body.session_name)
    if not session:
        raise HTTPException(404, "session not found")
    cookies = (session.get("storage_state") or {}).get("cookies") or []
    if not cookies:
        raise HTTPException(
            400, "session is not logged in — complete Phase 1 login first"
        )
    try:
        sources = resolve_sources(source_ids=body.source_ids or None)
        actions = normalize_actions(body.actions)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    labels = ", ".join(s["label"] for s in sources)
    try:
        return create_schedule(
            kind=SCHEDULE_KIND_BRAND_ENGAGE,
            session_name=body.session_name,
            source_id="",
            company=labels,
            source_link="",
            max_profiles=0,
            run_time=body.run_time,
            enabled=body.enabled,
            source_ids=[s["id"] for s in sources],
            actions=actions,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.patch("/api/schedules/{schedule_id}")
async def api_update_schedule(schedule_id: str, body: UpdateScheduleBody) -> dict:
    existing = get_schedule_public(schedule_id)
    if not existing:
        raise HTTPException(404, "schedule not found")

    fields: dict[str, Any] = {}
    if body.session_name is not None:
        session = get_session(body.session_name)
        if not session:
            raise HTTPException(404, "session not found")
        cookies = (session.get("storage_state") or {}).get("cookies") or []
        if not cookies:
            raise HTTPException(
                400, "session is not logged in — complete Phase 1 login first"
            )
        fields["session_name"] = body.session_name

    if body.source_id is not None:
        source = get_source(body.source_id)
        if not source or source.get("source_kind") != SOURCE_KIND_COMPANY_PEOPLES:
            raise HTTPException(404, "Company Peoples source not found")
        fields["source_id"] = body.source_id
        fields["company"] = source.get("company") or ""
        fields["source_link"] = source.get("link") or ""

    if body.max_profiles is not None:
        fields["max_profiles"] = body.max_profiles
    if body.run_time is not None:
        fields["run_time"] = body.run_time
    if body.enabled is not None:
        fields["enabled"] = body.enabled
    if body.source_ids is not None:
        try:
            sources = resolve_sources(source_ids=body.source_ids or None)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        fields["source_ids"] = [s["id"] for s in sources]
        fields["company"] = ", ".join(s["label"] for s in sources)
    if body.actions is not None:
        try:
            fields["actions"] = normalize_actions(body.actions)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    try:
        updated = update_schedule(schedule_id, **fields)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not updated:
        raise HTTPException(404, "schedule not found")
    return updated


@app.post("/api/schedules/{schedule_id}/start")
async def api_start_schedule(schedule_id: str) -> dict:
    row = set_enabled(schedule_id, True)
    if not row:
        raise HTTPException(404, "schedule not found")
    return row


@app.post("/api/schedules/{schedule_id}/pause")
async def api_pause_schedule(schedule_id: str) -> dict:
    row = set_enabled(schedule_id, False)
    if not row:
        raise HTTPException(404, "schedule not found")
    return row


@app.delete("/api/schedules/{schedule_id}")
async def api_delete_schedule(schedule_id: str) -> dict:
    if not delete_schedule(schedule_id):
        raise HTTPException(404, "schedule not found")
    return {"ok": True}


@app.post("/api/automations/build-connection")
async def api_activate_build_connection(body: ActivateBuildConnectionBody) -> dict:
    try:
        run = await _start_build_connection(
            session_name=body.session_name,
            source_id=body.source_id,
            max_requests=body.max_requests,
            headless=False,
            raise_on_busy=True,
        )
    except ValueError as exc:
        msg = str(exc)
        code = 404 if "not found" in msg.lower() else 400
        raise HTTPException(code, msg) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    assert run is not None
    return run


@app.post("/api/automations/brand-engage")
async def api_activate_brand_engage(body: ActivateBrandEngageBody) -> dict:
    """Type 3 — like / comment / repost latest posts for one session."""
    try:
        run = await _start_brand_engage(
            session_name=body.session_name,
            source_ids=body.source_ids or None,
            actions=body.actions,
            headless=False,
            raise_on_busy=True,
        )
    except ValueError as exc:
        msg = str(exc)
        code = 404 if "not found" in msg.lower() else 400
        raise HTTPException(code, msg) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    assert run is not None
    return run


@app.get("/api/brand-sources")
async def api_list_brand_sources() -> dict:
    return {
        "sources": ENGAGE_SOURCES,
        "actions": ["like", "comment", "repost"],
    }


@app.get("/api/profiles")
async def api_list_profiles(
    source_company: str | None = None,
    source_id: str | None = None,
    automation_id: str | None = None,
) -> dict:
    return {
        "profiles": list_profiles(
            source_company=source_company,
            source_id=source_id,
            automation_id=automation_id,
        )
    }


@app.get("/api/audiences")
async def api_list_audiences() -> dict:
    """Audiences available for Build Connection (Company Peoples sources + counts)."""
    from profiles_store import count_eligible_for_connect, list_audiences as profile_audiences

    sources = list_sources(source_kind=SOURCE_KIND_COMPANY_PEOPLES)
    profile_rows = profile_audiences()
    by_id = {a["source_id"]: a for a in profile_rows if a.get("source_id")}
    by_name = {
        (a.get("company") or "").lower(): a
        for a in profile_rows
        if not a.get("source_id") and a.get("company")
    }

    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for src in sources:
        sid = src["id"]
        seen_ids.add(sid)
        company = src.get("company") or ""
        bucket = by_id.get(sid) or by_name.get(company.lower()) or {}
        rows.append(
            {
                "source_id": sid,
                "company": company,
                "audience": company,
                "source_link": src.get("link") or "",
                "eligible": count_eligible_for_connect(
                    source_id=sid, source_company=company
                ),
                "total": int(bucket.get("total") or 0),
            }
        )

    for a in profile_rows:
        sid = a.get("source_id") or ""
        company = a.get("company") or ""
        if sid and sid in seen_ids:
            continue
        if not sid and any(
            (r.get("company") or "").lower() == company.lower() for r in rows
        ):
            continue
        rows.append(
            {
                "source_id": sid,
                "company": company,
                "audience": a.get("audience") or company,
                "source_link": "",
                "eligible": int(a.get("eligible") or 0),
                "total": int(a.get("total") or 0),
            }
        )
    rows.sort(key=lambda r: (r.get("company") or "").lower())
    return {"audiences": rows}
