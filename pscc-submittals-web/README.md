# PSCC Submittal Extractor — Web (React + FastAPI + PostgreSQL)

This is a parallel, from-scratch React/FastAPI/Postgres build of the same
product as `../pscc-submittals-agent` (the Streamlit app). **The Streamlit
app is untouched** — this lives in its own folder so the two can run side
by side while this one matures. The end goal (per the team's Azure Static
Web Apps direction) is to retire Streamlit once this reaches parity.

## Live deployment

| Piece | URL | Where |
|---|---|---|
| Frontend | https://zealous-bay-074acaa0f.7.azurestaticapps.net | Azure Static Web Apps, Free tier, `pscc-submittals-web-rg` |
| Backend API | https://pscc-submittals-web-api.azurewebsites.net | Azure App Service (Linux, Python 3.12), F1 Free tier, `pscc-submittals-web-rg` |
| Database | Neon Postgres project "PSCC Submittal Extraction" | Free tier, `neon.tech` — connection string lives only in the backend App Service's `DATABASE_URL` app setting, not in this repo |
| Extraction API (unchanged, reused) | https://psc-submittals-g8fwfhf7cjcqaccm.canadacentral-01.azurewebsites.net | Alekhya's existing deployment, `psc-submittals_group` — untouched |

All Azure pieces are on free tiers — **$0/month** from Azure for this project. The
only non-Azure cost is Neon, also on its free tier.

**To redeploy after code changes:**
```
# Backend
cd backend
# zip everything except venv/, data/, .env, __pycache__
az webapp deploy --name pscc-submittals-web-api --resource-group pscc-submittals-web-rg --src-path deploy.zip --type zip

# Frontend (rebuild with the prod API URL baked in, then deploy)
cd frontend
VITE_API_URL=https://pscc-submittals-web-api.azurewebsites.net npm run build
npx @azure/static-web-apps-cli deploy ./dist --deployment-token <token> --env production
# get the token with: az staticwebapp secrets list --name pscc-submittals-web-frontend --resource-group pscc-submittals-web-rg --query properties.apiKey -o tsv
```

**To re-sync data** from the Streamlit app's SQLite file into Neon, run
`scripts/migrate_sqlite_to_postgres.py` with `DATABASE_URL` pointed at the
Neon connection string (get it from Azure App Service's app settings, or
`npx neonctl connection-string`). Note: for tables with thousands of rows
(activity_log), the row-by-row script gets slow over the internet — a
bulk `psycopg2.extras.execute_values` insert is dramatically faster if
re-migrating from scratch.

## Why this exists

Same reasoning as Vikas's SQLite → Postgres recommendation from the
2026-07-22 meeting, plus the team's separate decision to move the frontend
to React on Azure Static Web Apps for free hosting and an easier path to
Teams integration later. This project does both at once: a proper
Postgres-backed REST API, and a React SPA in front of it.

## Architecture

```
frontend/   React + TypeScript (Vite). Talks to backend/ over /api/*.
backend/    FastAPI + SQLAlchemy + PostgreSQL. Owns all persistence
            (users, projects, roles, submittals, vendors, activity,
            notifications) — this is where pscc-submittals-agent/db.py's
            logic now lives, adapted into REST endpoints.
```

The **existing extraction API** (`../psc-submittals-git`, Alekhya's
FastAPI service — PDF → Excel/Word extraction) is reused as-is, unmodified.
`backend/` calls it over HTTP (`EXTRACTION_BACKEND_URL`), exactly like the
Streamlit app's `app.py` does today. Nothing about that service changed.

```
React (5173) → backend (8001) → Postgres (5432)
                              ↘ psc-submittals-git (8000)  [PDF extraction]
                              ↘ QnA_Agent (8100)            [optional, Q&A]
```

## What's implemented

- Full schema parity with the Streamlit app's collaboration model: projects,
  roles (owner_admin/admin/assignee), specification sections, submittal
  items, organizations/vendors, attachments, comments, activity log,
  notifications, section-code anomaly flags.
- Upload → scan (irregular code review + AI project-info extraction) →
  confirm (runs the full extraction pipeline: sections/log/structure calls,
  anomaly detection, legacy migration, section-text capture, AI summaries,
  ZIP bundling) — a direct port of the Streamlit app's upload flow.
- Workspace grid (section-grouped, role-gated editing — admins edit
  everything, assignees are limited to Status), Manage Team, Manage
  Vendors, submittal Details (attachments/comments/history), project
  activity log, notifications, Q&A chat proxy.
- One-time migration script that copied the real production data from the
  Streamlit app's SQLite file into this Postgres database (see below) —
  **already run**; this Postgres instance has the same 8 projects, 273
  submittal items, and full activity history as the live Streamlit app.

## What's NOT done yet (be aware before demoing this specific track)

- **Auth is dev-mode only** (manual name/email entry, no verification) —
  this matches the Streamlit app's *current* state exactly (`_auth_configured
  = False` in its `app.py`), so it's not a regression, but it's also not
  fixed. Wiring real Microsoft Entra ID / Azure AD is still open on both
  tracks.
- No background-job/progress-streaming for the extraction step — it's a
  single long synchronous request (a few minutes for large spec books),
  same blocking behavior as Streamlit's `st.status`, just without the
  incremental step-by-step UI.
- Revision-letter incrementing on resubmittal (A → B → C...) is still
  pending Alekhya's reference sheet — same open item as the Streamlit
  version's `db.py` docstring already flagged.
- UI is functional but not pixel-matched to the Streamlit app's styling.

---

## Local development

### 1. Prerequisites

- Python 3.12+, Node 20+
- PostgreSQL running locally. On this machine it was installed via:
  ```
  winget install PostgreSQL.PostgreSQL.17
  ```
  which installs a Windows service (`postgresql-x64-17`) and `psql`/`pgAdmin`
  under `C:\Program Files\PostgreSQL\17\bin`. Default superuser password
  from that install is `postgres`. The `pscc_submittals` database has
  already been created:
  ```
  "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -h localhost -c "CREATE DATABASE pscc_submittals;"
  ```

### 2. Backend

```
cd backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # already done locally; fill in OPENAI_API_KEY if missing
venv\Scripts\python -m uvicorn app.main:app --port 8001 --reload
```

`backend/.env` key settings:
- `DATABASE_URL` — points at the local Postgres (default already matches
  the winget install above).
- `EXTRACTION_BACKEND_URL` — where `psc-submittals-git`'s FastAPI service
  runs (default `http://localhost:8000`).
- `OPENAI_API_KEY` — reused from the Streamlit app's key for local testing.

On startup, `db.init_db()` creates all tables (idempotent — safe to restart
freely).

### 3. Migrate existing data (already run once)

The Streamlit app's real production data (8 projects, 273 submittal items,
~23k activity log rows) was copied over with:

```
cd backend
venv\Scripts\python scripts\migrate_sqlite_to_postgres.py
```

This is safe to re-run — every insert is `ON CONFLICT DO NOTHING`, so it
only picks up rows that don't already exist in Postgres (e.g. if the
Streamlit app keeps being used and you want to re-sync later). It also
copies each project's referenced PDF/ZIP/Excel files into `backend/data/`.

### 4. Extraction backend (Alekhya's repo — required for uploads to work)

```
cd ../../psc-submittals-git
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python -m uvicorn app:app --port 8000
```

### 5. Frontend

```
cd frontend
npm install
npm run dev
```

Opens at http://localhost:5173. The Vite dev server proxies `/api/*` to
`http://localhost:8001` (see `vite.config.ts`) so no `.env` is needed for
local dev.

### 6. Sign in

Dev-mode login just takes any name + email — same as the Streamlit app.
Use an email that's already a member of a migrated project (e.g.
`charles@pscc.com`) to see real data immediately, since that's the
bootstrap admin on every project.

---

## Known non-blocking dev-tooling note

`npm audit` flags `react-router-dom` (currently pinned to the latest
7.18.2) against several advisories that are all specific to React Router's
server/RSC/SSR modes (single-fetch server actions, RSC prerendering, SSR
hydration). This app is a plain client-rendered SPA (`BrowserRouter`, no
server-side rendering or server actions), so none of those code paths are
reachable here. Worth re-checking if this ever grows a server-rendering
mode.

---

## Deploying to Azure

Matches the team's direction from the 2026-07-22 meeting (React + Azure
Static Web Apps, free hosting, path to Teams integration).

### Frontend → Azure Static Web Apps

1. Push this repo to GitHub (or Azure DevOps).
2. Create a Static Web App resource, pointing at `pscc-submittals-web/frontend`
   as the app location, `dist` as the output location.
3. Set the build environment variable `VITE_API_URL` to the deployed
   backend's URL (see below) — Static Web Apps' free tier can also proxy
   `/api/*` to a **Managed Functions** backend, but since this backend is a
   full FastAPI app (not Azure Functions), point `VITE_API_URL` at a
   separately-hosted backend instead and skip the "linked backend" feature.
4. Add the Static Web App's `*.azurestaticapps.net` origin to the backend's
   `CORS_ORIGINS`.

### Backend + extraction API → Azure App Service (or Container Apps)

Both `backend/` and `psc-submittals-git` are plain FastAPI/uvicorn apps —
either works as an Azure App Service (Linux, Python runtime) or a
containerized Azure Container App. Set `DATABASE_URL` to the Azure Database
for PostgreSQL connection string (see below), and `EXTRACTION_BACKEND_URL`
on the `backend/` service to the deployed `psc-submittals-git` URL.

### Database → Azure Database for PostgreSQL Flexible Server

Local Postgres was only ever meant as the "start simple while the schema is
still simple" step from the meeting notes. For the deployed environment,
provision an Azure Database for PostgreSQL Flexible Server (burstable tier
is plenty for this data volume) and point `DATABASE_URL` at it. Run
`db.init_db()` once (the app already does this on every startup) to create
the schema, then re-run the migration script if there's newer Streamlit
data to carry over.

### File storage

`backend/data/{uploads,outputs,attachments,scans}` are local disk right
now — fine for a single-instance App Service, but won't survive a restart
or scale-out. Before going multi-instance, swap these for Azure Blob
Storage (this is the same "unify with SharePoint" open question from the
meeting notes — worth resolving both at once rather than building two
separate storage integrations).
