# Hexawealth LinkedIn Marketing Automator

Phase 1: create named LinkedIn sessions, log in manually once, store cookies for later use.

## Stack

- **Backend:** FastAPI + Playwright (headed Chromium)
- **Frontend:** React + Vite
- **Storage:** JSON files under `data/sessions/` (Playwright `storage_state`)

## Setup

```bash
# Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Frontend
cd ../frontend
npm install
```

## Run

Terminal 1 — API (port 8000). For **scheduled** automations, prefer without
`--reload` so the in-process scheduler is not restarted on file changes:

```bash
cd backend
source .venv/bin/activate
uvicorn main:app --port 8000
```

Dev with hot-reload (manual Activate still works; scheduler restarts on save):

```bash
uvicorn main:app --reload --port 8000
```

Terminal 2 — UI (port 5173):

```bash
cd ../frontend
npm run dev
```

Open http://127.0.0.1:5173

## Flow

1. Create a session (e.g. `li-account-1`)
2. Click **Login** — a Chromium window opens on LinkedIn login
3. Sign in with email/password (prefer not Google SSO)
4. When the feed/nav appears, cookies are saved automatically
5. Session shows “Logged in” and is ready for later phases
6. Open **Sources** → add Company Peoples URLs like
   `https://www.linkedin.com/company/google/people/`
7. Open **Automations** → Type 1 Company People Fetch:
   - **Manual** — pick session, company source, max → **Activate**
   - **Schedule** — add session→source mappings with daily local time,
     profile count, and Pause/Start; the API process fires them automatically

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/sessions` | List sessions |
| POST | `/api/sessions` | Create `{ "name": "..." }` |
| DELETE | `/api/sessions/{name}` | Delete |
| POST | `/api/sessions/{name}/login` | Start manual login |
| GET | `/api/sessions/{name}/login-status` | Poll logs / result |
| GET | `/api/sources` | List sources |
| POST | `/api/sources/company-peoples` | Add Company Peoples source |
| POST | `/api/sources/influencer` | Add Influencer source |
| POST | `/api/sources/individual` | Add Individual source |
| DELETE | `/api/sources/{id}` | Delete source |
| POST | `/api/automations/company-people` | Activate Type 1 fetch |
| GET | `/api/automations` | List automation runs |
| GET | `/api/automations/{id}` | Poll run status / logs |
| GET | `/api/profiles` | List scraped profiles |
| GET | `/api/schedules` | List schedule mappings |
| POST | `/api/schedules/company-people` | Create Type 1 daily schedule |
| POST | `/api/schedules/brand-engage` | Create Type 3 daily schedule |
| PATCH | `/api/schedules/{id}` | Update mapping |
| POST | `/api/schedules/{id}/start` | Enable mapping |
| POST | `/api/schedules/{id}/pause` | Pause mapping |
| DELETE | `/api/schedules/{id}` | Remove mapping |
| GET | `/api/audiences` | Audiences for Build Connection |
| GET | `/api/brand-sources` | Fixed brand audiences + actions |

### Source models

**Company Peoples**

| Field | Example |
|-------|---------|
| `type` | `individual` |
| `company` | `Google` |
| `link` | `https://www.linkedin.com/company/google/people/` |
| `use_case` | `increase_network` |

**Influencer**

| Field | Example |
|-------|---------|
| `type` | `influencer` |
| `company` | Influencer name |
| `link` | `https://www.linkedin.com/in/username/` |
| `use_case` | `increase_visibility` |

**Individual**

| Field | Example |
|-------|---------|
| `type` | `individual` |
| `company` | Person name |
| `link` | `https://www.linkedin.com/in/username/` |
| `use_case` | `reach_out` |

Saved state lives at `data/sessions/{name}.json`, `data/sources/{id}.json`,
and schedule mappings at `data/schedules/{id}.json`.
