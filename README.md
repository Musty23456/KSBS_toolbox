# KBS Toolbox

An original, offline-first survey and field data-collection platform —
inspired by the day-to-day workflow of tools like KoboToolbox, but with its
own architecture, branding, and code throughout. Built for KBS by Musty.

KBS Toolbox has three parts, each a complete, independent project:

| Component | Stack | Location |
|---|---|---|
| **Backend API** | Python, FastAPI, PostgreSQL, Alembic, JWT | [`backend/`](backend/) |
| **Web admin dashboard** | React, TypeScript, Vite | [`web/`](web/) |
| **Android field app** | Kotlin, Jetpack Compose, Room, WorkManager | [`android/`](android/) |

Each has its own README with full setup instructions. This file covers how
the pieces fit together and how to get everything running end-to-end.
## Phase 3 — AI questionnaire editor

Edit questionnaires in plain language with a reviewed, reversible preview, plus version history. See [PHASE3_AI_EDITOR.md](PHASE3_AI_EDITOR.md).

**AI Questionnaire Reviewer (Phase 4).** "Review with AI" gives a 0–100 quality score and a report of critical issues, warnings, suggestions and good practices, with one-click, previewed, undoable fixes. Read-only. See [PHASE4_AI_REVIEWER.md](PHASE4_AI_REVIEWER.md).

## What's new in this update

**Live "Online enumerators" for Admin/Supervisor**

- New web page **Online enumerators** (sidebar → *Online enumerators*).
  It shows every active enumerator as **Online** (seen in the last 3
  minutes), **Recently active** (last 30 minutes) or **Offline**, with
  last-seen time, last sync, and app version.
- The page refreshes itself every 15 seconds, and has a name/email search
  plus one-click filters (tap the Online / Recently active / Offline cards).
- Backend: new endpoint `GET /api/devices/online-enumerators`
  (Administrator and Supervisor only). Nothing existing was changed — it is
  added to `backend/app/routers/devices.py`. No database migration needed;
  it reuses the existing `devices.last_seen_at` column.
- Android: while the app is open and signed in, it now sends a "heartbeat"
  every minute (`MainActivity.kt` → `SyncRepository.sendHeartbeat()`), and
  stops when the app goes to the background. **Enumerators must install the
  new APK for this to work** — with the old APK they only ping about every
  15 minutes and will mostly show as Offline.

**New professional design & animations (web dashboard)**

- All new styling lives in one additive file, `web/src/styles/polish.css`,
  loaded after the original `global.css`. No existing style or page logic
  was edited.
- Includes: animated page entrances, staggered stat cards, gradient
  buttons with a hover shine, refined tables, soft focus rings, glass
  login screen with animated background, branded sidebar with sliding
  active indicator, blurred modal backdrop, custom scrollbars.
- The sidebar is now sticky on desktop, and on phones (under 860px) it
  shows as a scrollable menu strip — previously it was hidden completely.
- Users with "reduce motion" enabled on their device get no animations.
- **To undo the whole redesign:** delete `web/src/styles/polish.css` and
  the line `import "./styles/polish.css";` in `web/src/main.tsx`.

**Files changed or added in this update**

| File | Change |
|---|---|
| `backend/app/routers/devices.py` | added `GET /api/devices/online-enumerators` |
| `web/src/pages/devices/OnlineEnumeratorsPage.tsx` | new page |
| `web/src/styles/polish.css` | new design/animation layer |
| `web/src/main.tsx` | imports `polish.css` |
| `web/src/App.tsx` | new route `/online-enumerators` |
| `web/src/components/Layout.tsx` | new sidebar link |
| `android/.../MainActivity.kt` | 1-minute heartbeat while app is open |
| `android/.../data/repository/SyncRepository.kt` | new `sendHeartbeat()` |

**How to deploy this update (GitHub web editor, in this order)**

1. Backend first: replace `backend/app/routers/devices.py` → wait for
   Render to redeploy.
2. Web: add the two new files, replace `main.tsx`, `App.tsx`, `Layout.tsx`
   → Vercel redeploys automatically.
3. Android: replace `MainActivity.kt` and `SyncRepository.kt`, let the
   *Android Build* workflow finish, download the new APK, and install it on
   the enumerators' phones.


## Architecture

```
┌─────────────────┐         ┌──────────────────┐
│  Web dashboard   │ ───────▶│                  │
│ (admins/         │  REST   │   Backend API    │──────▶ PostgreSQL
│  supervisors)    │◀─────── │   (FastAPI)      │
└─────────────────┘         │                  │
                             └────────▲─────────┘
                                      │ REST
                                      │ (sync/download, sync/upload)
                             ┌────────┴─────────┐
                             │   Android app     │──────▶ Room (offline
                             │  (enumerators,    │        local database)
                             │   offline-first)  │
                             └──────────────────┘
```

- The **backend** is the single source of truth: users, surveys, questions,
  submissions, all validation, and all authentication/authorization.
- The **web dashboard** is a thin, always-online client for administrators
  and supervisors: building surveys, publishing them, reviewing submissions,
  managing staff accounts.
- The **Android app** is offline-first: it downloads published survey
  definitions while online, lets enumerators fill them out with zero
  connectivity, and syncs completed submissions automatically once a
  connection returns. See [`android/README.md`](android/README.md) for the
  full offline/sync design.

## Quick start (local, all three pieces)

```bash
# 1. Backend
cd backend
cp .env.example .env   # edit JWT_SECRET_KEY at minimum
docker compose up --build
# API now running at http://localhost:8000, demo data seeded automatically

# 2. Web dashboard (new terminal)
cd web
npm install
cp .env.example .env   # defaults to http://localhost:8000, fine for local dev
npm run dev
# Dashboard at http://localhost:5173 — log in with admin@kbstoolbox.app / ChangeMe123!

# 3. Android app (Android Studio, or see android/README.md for CLI build)
# Point it at the backend running on your machine:
#   emulator:        http://10.0.2.2:8000  (already the default)
#   physical device:  http://<your-machine-LAN-IP>:8000
```

## Building the Android APK via GitHub Actions (no local Android Studio needed)

1. Create a new GitHub repository and push this entire project to it.
2. Go to the repo's **Actions** tab. The `Android Build` workflow
   (`.github/workflows/android-build.yml`) runs automatically on every push
   to `main` that touches `android/`, or trigger it manually via
   **Run workflow** (the "workflow_dispatch" button) and optionally supply
   your deployed backend's URL as `apiBaseUrl`.
3. Once the run finishes, open it and download the `kbs-toolbox-debug-apk`
   artifact from the **Artifacts** section at the bottom of the run summary
   — that's your installable APK.
4. For a signed release build, push a version tag (e.g. `git tag v1.0.0 &&
   git push --tags`) to trigger `.github/workflows/android-release.yml`,
   which also attaches the APK to a new GitHub Release. Signing is optional
   — see that workflow's comments for the three repository secrets
   (`RELEASE_KEYSTORE_BASE64`, `RELEASE_KEYSTORE_PASSWORD`,
   `RELEASE_KEY_ALIAS`, `RELEASE_KEY_PASSWORD`) that enable a properly
   signed build; without them it still produces an installable
   debug-signed APK.

## Demo credentials

Seeded automatically by the backend (`python -m app.seed`, or automatically
via `docker compose up`):

| Role          | Email                          | Password      |
|---------------|---------------------------------|---------------|
| Administrator | admin@kbstoolbox.app           | ChangeMe123!  |
| Supervisor    | supervisor@kbstoolbox.app      | ChangeMe123!  |
| Enumerator    | enumerator@kbstoolbox.app      | ChangeMe123!  |

Three demo surveys (Household Survey 2026, Business Survey 2026, Population
Survey 2026) are seeded with real skip logic, validation rules, and a
cascading State→LGA location select, so the platform is testable immediately
without building a survey from scratch.

**Change or remove these before any production deployment.**

## Deployment

- **Backend**: any host that runs a Docker container or a Python process
  behind Postgres (Render, Railway, Fly.io, a VPS). See
  [`backend/README.md`](backend/README.md).
- **Web dashboard**: any static host with SPA fallback routing — Netlify and
  Vercel configs are included; GitHub Pages/Cloudflare Pages both work with
  a small extra step (see [`web/README.md`](web/README.md)).
- **Android**: distribute the APK directly (sideload, MDM, internal app
  sharing), or publish to the Play Store once you have a proper signing
  keystore configured in the release workflow.

## Project structure

```
KBS-Toolbox/
├── backend/            FastAPI + PostgreSQL API
├── web/                React admin dashboard
├── android/            Kotlin/Compose field app
├── docs/               Additional documentation (see below)
├── .github/workflows/  CI: android-build, android-release, web-build
└── README.md           This file
```

## Documentation index

- [`backend/README.md`](backend/README.md) — API setup, environment
  variables, running tests, endpoint list, design notes on versioning/sync/
  validation.
- [`web/README.md`](web/README.md) — dashboard setup, deployment configs,
  design rationale.
- [`android/README.md`](android/README.md) — app architecture, offline-sync
  design in detail, build instructions, and an explicit "verification
  status" section.
- [`docs/ai-setup.md`](docs/ai-setup.md) — Gemini AI integration (Phase 1):
  getting a key, environment variables, enabling AI, testing, troubleshooting.
- [`docs/ai-questionnaire.md`](docs/ai-questionnaire.md) — AI questionnaire generator (Phase 2):
  how it works, API, validation rules, errors, deployment, tests.
- [`docs/known-limitations.md`](docs/known-limitations.md) — a single
  consolidated list of every documented limitation/next-step across all
  three components, so nothing is buried in a sub-README.
- [`docs/verification-notes.md`](docs/verification-notes.md) — exactly what
  was and wasn't possible to verify in the environment this project was
  built in, and what to check first when you build it for real.

## A note on how this was built

This project was authored in a sandboxed environment with **no network
access** (no `pip`/`npm`/Gradle dependency downloads) and **no Android
SDK, emulator, or Kotlin compiler**. That means:

- The **backend** was syntax-checked (all files parse) and manually
  traced for import/reference consistency, but its test suite has not
  actually been executed.
- The **web dashboard** was checked with `tsc --noEmit` against the source
  (catching real structural errors independent of installed packages), but
  never actually built with `npm run build`.
- The **Android app** was checked for balanced brackets, valid XML, and
  manually cross-referenced constructor/method calls against their
  declarations, but never compiled.

None of this is a substitute for actually building each piece. Treat your
first `docker compose up`, `npm run build`, and `gradle build` as the real
tests, and see `docs/verification-notes.md` for more detail on what to
watch for.
