# KBS Toolbox — Backend API

FastAPI + PostgreSQL backend for KBS Toolbox, an offline-first survey and
data-collection platform. This service is the single source of truth for
surveys, users, and submissions, consumed by both the Android app and the
web admin dashboard.

## Stack

- **Python 3.12 / FastAPI** — REST API
- **SQLAlchemy 2.0** — ORM
- **Alembic** — database migrations
- **PostgreSQL** — production database (SQLite supported for local/dev/test)
- **JWT (python-jose)** — authentication, with server-side revocation on logout
- **passlib[bcrypt]** — password hashing

## Project layout

```
backend/
├── app/
│   ├── main.py            # FastAPI app, CORS, rate limiting, router wiring
│   ├── config.py          # Settings loaded from environment variables
│   ├── database.py        # SQLAlchemy engine/session
│   ├── security.py        # Password hashing, JWT issue/verify
│   ├── dependencies.py    # Auth guard + role-based access control
│   ├── seed.py            # Demo users + 3 demo surveys
│   ├── ai/                # AI layer: config, errors, providers/, service, validation, usage
│   ├── models/            # SQLAlchemy models (one file per entity)
│   ├── schemas/           # Pydantic request/response schemas
│   ├── routers/           # auth, users, surveys, submissions, sync
│   └── services/          # expressions (skip logic), validation, audit log
├── alembic/                # Migrations (0001_initial_schema creates all tables)
├── tests/                  # pytest suite (auth, surveys, submissions, sync, expressions)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml      # Postgres + API for local dev
└── .env.example
```

## Running locally with Docker (recommended)

```bash
cd backend
cp .env.example .env
# Edit .env: set a real JWT_SECRET_KEY at minimum
docker compose up --build
```

This starts Postgres, runs migrations, seeds demo data, and starts the API
at `http://localhost:8000`. Interactive API docs: `http://localhost:8000/docs`.

## Running locally without Docker

Requires Python 3.12+ and a running PostgreSQL instance (or use SQLite for
a zero-install quick start).

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# For a zero-dependency quick start, edit .env and set:
#   DATABASE_URL=sqlite:///./kbs_toolbox.db

alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload
```

## Running tests

```bash
pip install -r requirements.txt
pytest -v
```

Tests run against an isolated SQLite database and never touch your
development database.

## Environment variables

See `.env.example` for the full list. At minimum, change `JWT_SECRET_KEY`
before any non-local deployment — generate one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

### AI integration (Google Gemini)

AI is off by default. Variables: `AI_ENABLED`, `AI_PROVIDER`, `GEMINI_API_KEY`,
`GEMINI_MODEL`, `AI_REQUEST_TIMEOUT`, `AI_MAX_RETRIES`, plus limits
`AI_RATE_LIMIT_PER_MINUTE`, `AI_MAX_REQUEST_BYTES`, `AI_MAX_PROMPT_CHARS`.
The key never leaves the server. Full guide: [`../docs/ai-setup.md`](../docs/ai-setup.md).

## Demo credentials

After running the seed script (`python -m app.seed`, or automatically via
`docker compose up`):

| Role          | Email                          | Password      |
|---------------|---------------------------------|---------------|
| Administrator | admin@kbstoolbox.app           | ChangeMe123!  |
| Supervisor    | supervisor@kbstoolbox.app      | ChangeMe123!  |
| Enumerator    | enumerator@kbstoolbox.app      | ChangeMe123!  |

**Change or remove these before any production deployment.**

## API overview

All endpoints are prefixed `/api`. Full interactive documentation (with
request/response schemas) is auto-generated at `/docs` (Swagger) and
`/redoc` once the server is running.

- `POST /api/auth/register`, `/login`, `/login-json`, `/logout`, `GET /me`
- `GET/POST/PUT/DELETE /api/users` (admin-only management)
- `GET/POST/PUT/DELETE /api/surveys`, plus `/publish` and `/unpublish`
- `POST/GET /api/submissions`
- `POST /api/sync/upload` — batch upload of an Android device's offline queue
- `GET /api/sync/download` — full definitions of all published surveys, for
  offline caching on-device

**AI (Phase 1 infrastructure)**

- `GET /api/ai/status` — Administrator/Supervisor. Enabled flag, provider,
  model and last known connection result. Never calls the provider; never
  returns secrets.
- `POST /api/ai/test-connection` — Administrator only. One tiny Gemini call to
  verify key, model and network. Per-user rate limited.

**Devices / presence**

- `POST /api/devices/heartbeat` — sent by the Android app (about once a
  minute while open) to record that the device is online.
- `GET /api/devices/online-enumerators` — Administrator/Supervisor only.
  Returns each active enumerator with `status` = `ONLINE` (seen ≤ 3 min
  ago), `AWAY` (≤ 30 min) or `OFFLINE`, plus counts and last-seen/last-sync
  times. The thresholds are the constants `ONLINE_WINDOW_SECONDS` and
  `AWAY_WINDOW_SECONDS` in `app/routers/devices.py`.


## Design notes

- **Survey versioning**: editing a published survey's questions creates a
  new immutable `SurveyVersion` rather than mutating the old one, so past
  submissions always remain interpretable against the exact form they were
  collected with.
- **Skip logic / calculated fields**: `relevance_expression` and
  `calculation_expression` on each question use a small restricted
  expression language (see `app/services/expressions.py`) — never Python's
  `eval()` — so survey authors can write conditions like
  `gender == 'FEMALE' and age_years >= 12` safely.
- **Offline sync idempotency**: every submission carries a
  `client_submission_uuid` generated on-device at capture time. Retried
  uploads (e.g. after a dropped connection) are deduplicated server-side by
  this key — the sync endpoint is safe to retry an entire batch.
- **Server-side re-validation**: submission answers are re-validated against
  the survey's rules on the server, not trusted from the client, so a
  tampered or buggy offline client can't bypass required-field or
  range/regex rules.

## Known limitations / next steps

- Media answers (photo/audio/signature) currently store a `media_reference`
  string (an object-storage key or path) rather than accepting binary
  uploads directly — a `/api/media/upload` endpoint backed by S3-compatible
  object storage is a natural next addition.
- The in-process rate limiter in `main.py` is per-instance; a multi-instance
  production deployment should swap it for a shared store (e.g. Redis).
- `cascade_parent_question_id` / `cascade_parent_value` model the data
  needed for cascading selects (e.g. State → LGA); the actual cascade
  filtering logic belongs in the client (Android/web) form renderer, which
  reads these fields from the downloaded survey definition.
