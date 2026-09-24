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
    save_storage_state,
    set_status,
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
from brand_engage_job import run_brand_engage
from profiles_store import list_profiles


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory login job status (name -> {status, logs, error})
_login_jobs: dict[str, dict[str, Any]] = {}
_login_locks: dict[str, asyncio.Lock] = {}
_automation_lock = asyncio.Lock()
_running_automation_id: str | None = None


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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


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
    max_requests: int = Field(default=10, ge=1, le=50)


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
    global _running_automation_id

    session = get_session(body.session_name)
    if not session:
        raise HTTPException(404, "session not found")
    cookies = (session.get("storage_state") or {}).get("cookies") or []
    if not cookies:
        raise HTTPException(400, "session is not logged in — complete Phase 1 login first")

    source = get_source(body.source_id)
    if not source or source.get("source_kind") != SOURCE_KIND_COMPANY_PEOPLES:
        raise HTTPException(404, "Company Peoples source not found")

    if _automation_lock.locked() or _running_automation_id:
        raise HTTPException(409, "another automation is already running")

    run = create_run(
        kind=AUTOMATION_KIND_COMPANY_PEOPLE,
        session_name=body.session_name,
        company=source.get("company") or "",
        source_id=body.source_id,
        source_link=source.get("link") or "",
        max_connections=body.max_connections,
    )
    _running_automation_id = run["id"]

    async def _guarded() -> None:
        global _running_automation_id
        async with _automation_lock:
            try:
                await run_company_people_fetch(
                    run_id=run["id"],
                    session_name=body.session_name,
                    company=source.get("company") or "",
                    source_link=source.get("link") or "",
                    max_connections=body.max_connections,
                    headless=False,
                )
            except Exception as exc:
                update_run(run["id"], status="error", error=str(exc))
                from automations_store import append_log

                append_log(run["id"], f"Failed: {exc}")
            finally:
                _running_automation_id = None

    asyncio.create_task(_guarded())
    return run


@app.post("/api/automations/build-connection")
async def api_activate_build_connection(body: ActivateBuildConnectionBody) -> dict:
    global _running_automation_id

    session = get_session(body.session_name)
    if not session:
        raise HTTPException(404, "session not found")
    cookies = (session.get("storage_state") or {}).get("cookies") or []
    if not cookies:
        raise HTTPException(400, "session is not logged in — complete Phase 1 login first")

    if _automation_lock.locked() or _running_automation_id:
        raise HTTPException(409, "another automation is already running")

    run = create_run(
        kind=AUTOMATION_KIND_BUILD_CONNECTION,
        session_name=body.session_name,
        max_requests=body.max_requests,
        company="",
        source_id="",
        source_link="",
    )
    _running_automation_id = run["id"]

    async def _guarded() -> None:
        global _running_automation_id
        async with _automation_lock:
            try:
                await run_build_connection(
                    run_id=run["id"],
                    session_name=body.session_name,
                    max_requests=body.max_requests,
                    headless=False,
                )
            except Exception as exc:
                update_run(run["id"], status="error", error=str(exc))
                from automations_store import append_log

                append_log(run["id"], f"Failed: {exc}")
            finally:
                _running_automation_id = None

    asyncio.create_task(_guarded())
    return run


@app.post("/api/automations/brand-engage")
async def api_activate_brand_engage() -> dict:
    """Type 3 — like, comment Insightful, repost latest posts for every session."""
    global _running_automation_id

    logged_in = [
        s
        for s in list_sessions()
        if s.get("has_storage_state")
    ]
    if not logged_in:
        raise HTTPException(
            400, "no logged-in sessions — complete Phase 1 login first"
        )

    if _automation_lock.locked() or _running_automation_id:
        raise HTTPException(409, "another automation is already running")

    run = create_run(
        kind=AUTOMATION_KIND_BRAND_ENGAGE,
        session_name="all",
        company="Brand Engage",
        source_id="",
        source_link="",
        max_connections=0,
        max_requests=0,
    )
    _running_automation_id = run["id"]

    async def _guarded() -> None:
        global _running_automation_id
        async with _automation_lock:
            try:
                await run_brand_engage(run_id=run["id"], headless=False)
            except Exception as exc:
                update_run(run["id"], status="error", error=str(exc))
                from automations_store import append_log

                append_log(run["id"], f"Failed: {exc}")
            finally:
                _running_automation_id = None

    asyncio.create_task(_guarded())
    return run


@app.get("/api/profiles")
async def api_list_profiles(
    source_company: str | None = None,
    automation_id: str | None = None,
) -> dict:
    return {
        "profiles": list_profiles(
            source_company=source_company,
            automation_id=automation_id,
        )
    }
