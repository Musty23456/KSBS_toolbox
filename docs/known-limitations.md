# Known limitations / next steps

A single consolidated list, pulled from each component's README, so nothing
is buried in a sub-directory.

## Backend

- Media answers (photo/audio/signature) store a `media_reference` string
  (a file path or object-storage key) rather than accepting binary uploads
  directly. A `POST /api/media/upload` endpoint backed by S3-compatible
  object storage is the natural next addition, with the Android app
  uploading captured files there and sending back the resulting key.
- The in-process rate limiter in `app/main.py` is per-instance. A
  multi-instance production deployment should swap it for a shared store
  (e.g. Redis).

- AI (Phase 1): the per-user AI rate limiter and the "last connection result"
  shown by `/api/ai/status` are in-process, so they are per-instance and reset
  on restart. Use a shared store (e.g. Redis) for multi-instance deployments.
- AI (Phase 2): the `Survey` table has one `description` column, so the AI's
  introduction and respondent instructions are saved inside it as labelled
  paragraphs, not in dedicated fields. Dedicated fields (and showing them on
  the Android form) would need a schema change.
- AI (Phase 2): skip logic is limited to what every KBS evaluator understands
  (`== != < <= > >=`, `and/or/not`, `'VALUE' in code`; no arithmetic, no negative
  numbers). The AI never writes calculated fields or cascading selects.
- AI (Phase 2): one generation is one provider call (plus at most one automatic
  repair). Very large requests can hit the output-token limit; the user is told
  to ask for fewer questions or regenerate section by section.
- AI (Phase 2): regenerating a section replaces the whole section. Skip logic
  elsewhere that pointed at replaced questions is cleared (and reported).
- AI (Phase 1): prompt-injection protection is layered mitigation (limits,
  delimiters, a guard instruction, phrase tripwires), not a guarantee. Treat
  model output as untrusted and validate it before using it in later phases.
- AI (Phase 1): `google-genai` is range-pinned (`>=1,<2`); pin the exact
  version you deploy. The default model id may need updating as Google
  retires models.

## Web admin dashboard

- Question reordering uses simple up/down buttons instead of drag-and-drop,
  to avoid adding a drag-and-drop library as a dependency that couldn't be
  installed/tested in the authoring environment. Swap in something like
  `@dnd-kit/core` if true drag-and-drop is wanted.
- No CSV/Excel export button yet on the submissions page — the backend
  already returns everything needed via `GET /api/submissions`; adding an
  "Export" action is a small follow-up.
- No offline support (by design — offline-first is the Android app's job).

## Android app

- Same media-reference limitation as the backend: captured files are stored
  locally and referenced by path, not uploaded as binary data yet.
- `gradle/wrapper/gradle-wrapper.jar` (a binary) is not committed to the
  repository — run `gradle wrapper --gradle-version 8.7` once locally to
  generate it, or just use `gradle` directly (as CI does) instead of
  `./gradlew`.
- Manual dependency injection (`ServiceLocator`) is used instead of Hilt —
  a deliberate choice to avoid an annotation-processing build step that
  could not be verified in the authoring environment. This is a reasonable
  permanent choice for a project this size, not just a stopgap.
- Audio recording has no maximum duration or file-size cap.
- The signature pad captures reasonably fine strokes but has not been
  tuned for very large screens/tablets.

## Online enumerators (added in this update)

- "Online" is based on the app being open (heartbeat every minute). An
  enumerator whose app is closed or in the background shows as Recently
  active for up to 30 minutes, then Offline — even if the phone has
  internet.
- Presence is polled (every 15 seconds), not pushed in real time.
- Enumerators on the old APK are only seen about every 15 minutes.
- Dark mode is still on the wishlist; the new styling is light-theme only.

## Cross-cutting

- No end-to-end integration test exercises all three components together
  (e.g. a script that creates a survey via the web dashboard, downloads it
  on a simulated device, submits it, and confirms it appears in the
  submissions list). This would be a valuable addition once the individual
  pieces are confirmed to build and run correctly on their own.

- Multilingual (Phase 5): the Android app does not yet show translations or a language selector (web fill screen only). It needs translations in the
  sync payload, a Room migration and UI.
- Multilingual (Phase 5): validation messages returned by the server after submit stay in English; the web form's own messages are translated.
- Multilingual (Phase 5): sections and groups have no code, so their translations are keyed by a hash of the title: renaming one makes it untranslated,
  and two with an identical title share one translation.
- Multilingual (Phase 5): the Hausa quality rules are a small heuristic set plus an optional AI pass; they are an aid, not a native-speaker review.
