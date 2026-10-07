# KSBS TOOLBOX — Android App

Kotlin + Jetpack Compose offline-first field data-collection app. Enumerators
download published surveys while online, fill them out with zero
connectivity, and the app syncs completed submissions automatically once a
connection returns.

## Stack

- Kotlin, Jetpack Compose, Material 3
- Room (offline database — surveys, questions, choices, submissions, answers)
- Retrofit + OkHttp (talks to the [backend](../backend))
- WorkManager (background sync, retried automatically on failure)
- EncryptedSharedPreferences (secure token storage)
- Manual dependency injection (`di/ServiceLocator.kt`) — see "Design notes" below
- ZXing (`zxing-android-embedded`) for barcode/QR scanning
- Play Services Location (`FusedLocationProviderClient`) for GPS capture

## Project layout

```
android/
├── app/src/main/java/com/kbstoolbox/app/
│   ├── data/
│   │   ├── local/          # Room entities, DAOs, database
│   │   ├── remote/         # Retrofit API + DTOs mirroring the backend schemas
│   │   └── repository/     # Auth, Survey (offline cache), Submission, Sync
│   ├── di/                 # ServiceLocator (manual DI container)
│   ├── expressions/        # Safe skip-logic evaluator + client-side validation
│   ├── session/            # Encrypted token/session storage
│   ├── sync/               # WorkManager SyncWorker, connectivity observer
│   ├── ui/                 # Compose screens, one package per feature
│   └── util/               # GPS/photo/audio/file helpers
├── app/src/test/           # JUnit unit tests (expression evaluator, validator)
├── build.gradle.kts, settings.gradle.kts, gradle.properties
└── gradle/wrapper/gradle-wrapper.properties
```

## Building

### In CI (GitHub Actions) — no local setup required

See `.github/workflows/android-build.yml` at the repo root. It installs a
JDK and the Android SDK, then runs `gradle build` directly (see note on the
Gradle wrapper below) and uploads the resulting APK as a workflow artifact.

### Locally

Requires JDK 17, Android SDK (API 34), and Gradle 8.7 (matching
`gradle/wrapper/gradle-wrapper.properties`).

```bash
cd android
gradle assembleDebug -PapiBaseUrl=http://10.0.2.2:8000
```

`10.0.2.2` is the Android emulator's alias for your host machine's
`localhost` — use your backend's real address for a physical device (e.g.
`http://192.168.1.50:8000`), or its public URL for a release build:

```bash
gradle assembleRelease -PapiBaseUrl=https://api.yourdomain.com
```

**Note on the Gradle wrapper**: `gradlew` / `gradlew.bat` are included, but
`gradle/wrapper/gradle-wrapper.jar` (a binary) is not, since it could not be
fetched in the environment this project was authored in without network
access. Either:
- run `gradle wrapper --gradle-version 8.7` once (with any locally installed
  Gradle) to generate it, or
- just invoke `gradle` directly, as the CI workflow does, instead of `./gradlew`.

## Demo login

Use the same accounts seeded by the backend (`python -m app.seed`):

| Role          | Email                          | Password      |
|---------------|---------------------------------|---------------|
| Administrator | admin@kbstoolbox.app           | ChangeMe123!  |
| Enumerator    | enumerator@kbstoolbox.app      | ChangeMe123!  |

## How offline-first works here

1. **Download**: on the dashboard, "Download / refresh surveys" calls
   `GET /api/sync/download` and fully replaces each survey's cached
   definition in Room (`SurveyDao.replaceSurveyDefinition`) — questions and
   choices are always in sync with what was just downloaded, never merged
   with stale data.
2. **Fill offline**: `FormFillScreen` reads only from Room. Answers save to
   Room on every "Save draft" tap and are never lost if the app is killed.
   Skip logic (`relevance_expression`) is evaluated on-device by
   `ExpressionEvaluator`, a small hand-rolled safe expression parser that
   mirrors the backend's `app/services/expressions.py` exactly — including
   edge cases like "any comparison against an unanswered question is false,"
   so a question's visibility never disagrees between the field and the
   server.
3. **Complete**: tapping "Complete submission" runs the same validation
   rules as the backend (`AnswerValidator`), then flips the submission's
   local status to `PENDING_SYNC` and immediately requests a `SyncWorker` run.
4. **Sync**: `SyncWorker` (WorkManager, constrained to `NetworkType.CONNECTED`)
   batches every `PENDING_SYNC`/`FAILED` submission into one
   `POST /api/sync/upload` call. Each submission carries the
   `client_submission_uuid` it was created with, so a retried upload (after a
   dropped connection, or a periodic worker re-run) never creates a
   duplicate — the same idempotency key the backend expects. A periodic
   15-minute background sync is scheduled from `KbsToolboxApplication`, so
   sync eventually happens even without opening the app, and a manual sync
   is also triggered right after completing a submission.
5. **Never lose data**: a submission's local row is only ever marked
   `SYNCED` after the server explicitly confirms it in the upload response;
   until then it stays `PENDING_SYNC` or `FAILED` (which is retried
   automatically), and nothing is deleted locally.

## Live presence (heartbeat)

While the app is on screen and the user is signed in, `MainActivity`
sends `POST /api/devices/heartbeat` every 60 seconds (via
`SyncRepository.sendHeartbeat()`), so the web dashboard can show who is
online. The loop is tied to the activity lifecycle (`repeatOnLifecycle`),
so it stops automatically in the background. Network failures are ignored.
The 15-minute background sync (`SyncWorker`) still sends its own heartbeat.

## Design notes / deliberate simplifications

- **Manual DI instead of Hilt** (`di/ServiceLocator.kt`): Hilt's
  KSP/annotation-processing setup is a common source of build failures that
  only surface when actually compiled. Since this project could not be
  compiled in the environment it was authored in, a plain hand-written
  singleton container was judged a better trade than the boilerplate Hilt
  would have saved.
- **Media answers store a file path, not binary data**: photo/audio/signature
  capture write to the app's private external-files directory and the
  submission's `media_reference` field stores that path — matching the
  backend's schema, which treats `media_reference` as an opaque string
  reference rather than accepting binary uploads. Actually uploading the
  file bytes to object storage is flagged as a next step in the backend
  README too; wiring it up would mean adding a `POST /api/media/upload`
  call here before/alongside `sync/upload`.
- **Barcode scanning** uses ZXing's embedded scanner via its `ScanContract`
  (Jetpack Activity Result API), not a custom camera integration.
- **Cascading selects** (e.g. State → LGA) filter choices client-side in
  `FormFillViewModel.choicesFor()` based on the parent question's current
  answer and each choice's `cascade_parent_value`, exactly mirroring how the
  web admin's form builder records that relationship.

## Verification status (please read)

This project was authored in a sandbox with **no network access and no
Android SDK/emulator available**, so it was never compiled or run. What was
possible, and was done:

- Every `.kt` file's brackets/braces/parens were checked for balance
  programmatically.
- Every cross-file reference (constructor calls, DAO/repository method
  calls, DTO field names, Compose function call sites) was traced by hand
  against its declaration to catch name/arity mismatches.
- The client-side expression evaluator and validator have real JUnit tests
  in `app/src/test/`, but these have **not been run** — please run
  `gradle test` and treat the first real build as the actual verification
  this code has not yet had.

Please treat the first `gradle build` you run as the real test — file an
issue (or just note it back to the assistant) with whatever errors surface;
the review above catches structural mistakes, not everything a compiler and
the Android/Compose/Room annotation processors check.
