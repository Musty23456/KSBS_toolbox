# AI questionnaire generator (Phase 2)

Describe a study in plain language; Gemini drafts a complete questionnaire that
opens in the existing Survey Builder for review, editing and saving.

**Nothing is saved or published automatically.** Generation returns a *preview*.
The user loads it into the builder, edits it, and saves through the normal
`POST /api/surveys` after confirming they reviewed it. Publishing an
AI-generated survey is refused by the server unless the request carries an
explicit review confirmation.

## How it works

```
Generate with AI (form) ──► POST /api/ai/questionnaire/generate
                                │ validate brief (Pydantic) → rate limit → size limit
                                │ Gemini, JSON mode, rules in the system instruction,
                                │ user text fenced as untrusted data
                                ▼
                    parse JSON ─► Pydantic envelope check ─► normalize.py
                    (one automatic repair attempt on bad output)
                                ▼
          SectionIn / QuestionGroupIn / QuestionIn  (the EXISTING schemas)
                                ▼
                       preview returned to the browser   (nothing written to the DB)
                                ▼
        Survey Builder: edit / reorder / regenerate ─► confirm ─► POST /api/surveys (DRAFT)
```

There is one questionnaire format. The preview uses the existing
`QuestionIn`, `SectionIn` and `QuestionGroupIn` models and is a valid
`SurveyCreate` payload, so it is saved by the existing endpoint and tables.

## What the user provides

Research topic (required), survey title, research objectives, target
respondents, study location, number of questions (3 – `AI_GENERATION_MAX_QUESTIONS`),
language, research methodology, additional instructions.
A title typed by the user is used as-is; otherwise the AI's title is used.

## What the AI produces

Title, description, introduction, respondent instructions, sections, question
groups (optionally repeatable), questions with types, answer choices, required
flags, validation rules (min/max value, min/max length, regex) and skip logic.

The `Survey` table has a single `description` column, so description,
introduction and instructions are stored together in it as labelled paragraphs
(`Introduction`, `Instructions for respondents`). They stay editable in the
builder's description box.

## Validation: nothing is trusted

Every reply goes through `app/ai/questionnaire/normalize.py` and the existing
schemas before it can reach the user:

| Check | Result |
|---|---|
| Not valid JSON (Markdown fences / chatter tolerated) | one repair attempt, then `AI_INVALID_JSON` |
| Wrong structure (sections not a list, …) | one repair attempt, then `AI_INVALID_QUESTIONNAIRE` |
| No usable questions left | `AI_INVALID_QUESTIONNAIRE` |
| Output cut off by the token limit | `AI_RESPONSE_TRUNCATED` (not parsed, not retried) |
| Unknown question type | mapped from a synonym (`radio` → `SINGLE_CHOICE`) or the question is dropped, with a warning |
| Choice question with < 2 choices | dropped, with a warning |
| Choices on a non-choice type / on `YES_NO` | removed |
| Duplicate / invalid / reserved codes | made `snake_case`, unique, expression-safe; reported |
| min > max, bad length rules | removed, reported |
| Regex invalid, too long or ReDoS-shaped (`(a+)+`) | removed, reported |
| Skip logic | parsed with a strict allow-list (see below); invalid rules removed, reported |
| Calculated fields, defaults, cascades | never generated |
| Counts | capped at the configured maximum; far-off counts produce a warning |

**Skip-logic allow-list** (understood by the backend, web and Android
evaluators): `== != < <= > >=`, `and`, `or`, `not`, parentheses, quoted text,
non-negative numbers, and `'VALUE' in code`. A rule may only reference
*earlier* questions, never itself, must compare against a real choice value
(`YES_NO` uses `'YES'`/`'NO'`), and ordering comparisons only apply to number
questions. Anything else is dropped with a warning instead of silently hiding a
question.

## API

All endpoints need a signed-in user (any role) and are rate-limited per user
(`AI_RATE_LIMIT_PER_MINUTE`). Errors are `{"detail": "<safe message>", "code": "<CODE>"}`.

| Method & path | Purpose |
|---|---|
| `GET /api/ai/questionnaire/availability` | Is generation usable? Never calls Google. |
| `POST /api/ai/questionnaire/generate` | Body: the brief. Returns `GeneratedQuestionnairePreview`. |
| `POST /api/ai/questionnaire/regenerate-question` | Rewrites one question; keeps its code, position, section and group. |
| `POST /api/ai/questionnaire/regenerate-section` | Returns replacement groups and questions for one section. |
| `POST /api/surveys` | Existing. Now accepts `ai_generated: true`. |
| `PUT /api/surveys/{id}` | Existing. `ai_generated: true` turns the flag on; it can never be turned off. |
| `POST /api/surveys/{id}/publish` | Existing. Optional body `{"confirm_ai_review": true}`; **required** when the survey is AI-generated, otherwise `409`. |

Additional error codes: `AI_RESPONSE_TRUNCATED` (422), `AI_INVALID_JSON` (502),
`AI_INVALID_QUESTIONNAIRE` (502). Phase 1 codes (`AI_DISABLED`,
`AI_NOT_CONFIGURED`, `AI_QUOTA_EXCEEDED`, `AI_TIMEOUT`, `AI_RATE_LIMITED`, …)
apply unchanged; see `ai-setup.md`.

## Using it (web dashboard)

1. Open **Surveys → New survey** (or edit a draft) and press **✨ Generate with AI**.
2. Fill in the form and press **Generate questionnaire**.
3. Review the preview (warnings, skip logic, every question). Use **Regenerate
   all**, **Edit brief**, or **Use in builder**.
4. In the builder, edit as usual. Extra tools: **↑ ↓ Remove** on sections,
   **✨ Regenerate** on a question or a section (with an optional instruction),
   Undo/Redo for question changes.
5. **Create survey / Save changes** asks you to confirm you reviewed the AI
   content and saves a **draft**. **Publish** asks again and only then publishes.

If AI is off or unconfigured the button is disabled and explains why.

## Configuration

New variables (all optional; defaults shown). Phase 1 variables are unchanged.

| Variable | Default | Meaning |
|---|---|---|
| `AI_GENERATION_TIMEOUT` | `90` | Seconds per Gemini call for generation (1–300). |
| `AI_GENERATION_MAX_REQUEST_BYTES` | `65536` | Largest request body for these endpoints. |
| `AI_GENERATION_MAX_PROMPT_CHARS` | `30000` | Longest prompt forwarded to Gemini. |
| `AI_GENERATION_MAX_OUTPUT_TOKENS` | `32768` | Ceiling on output tokens per call. The request asks for about `4096 + 350 × questions`, capped here. |
| `AI_GENERATION_MAX_QUESTIONS` | `100` | Most questions per request. |

Gemini 2.5 models spend part of the output budget on internal reasoning. If
long questionnaires come back as `AI_RESPONSE_TRUNCATED`, raise
`AI_GENERATION_MAX_OUTPUT_TOKENS` (up to the model's limit) or request fewer
questions. Worst case a request makes `AI_MAX_RETRIES + 1` calls per attempt and
up to two attempts; make sure your host's request timeout is long enough, or
lower `AI_GENERATION_TIMEOUT` / `AI_MAX_RETRIES`.

## Deployment

1. **Back up the database.** This release adds one column: `surveys.ai_generated`
   (boolean, default false). Existing surveys are unaffected.
2. **Deploy the backend.** Either:
   - run the migration: `cd backend && alembic upgrade head` (adds revision
     `0014_survey_ai_generated`), or
   - just start the app: on startup it runs
     `ALTER TABLE surveys ADD COLUMN IF NOT EXISTS ai_generated …` (PostgreSQL),
     the same mechanism earlier columns used.
3. Install dependencies if needed (`pip install -r backend/requirements.txt`;
   `google-genai` is already listed). No new Python packages.
4. Make sure Phase 1 is configured: `AI_ENABLED=true`, `GEMINI_API_KEY=…`
   (`docs/ai-setup.md`). Optionally set the `AI_GENERATION_*` variables above.
5. **Deploy the web app** (`cd web && npm install && npm run build`). Deploy the
   backend first: the new dashboard calls the new endpoints. An older dashboard
   keeps working against the new backend, except that it cannot publish an
   AI-generated survey (it never creates one).
6. The Android app needs no change: the extra `ai_generated` field in survey
   JSON is ignored by its Gson parsing.
7. Smoke test: log in → Overview → AI card → **Test connection**; then open
   **New survey → Generate with AI** with a small request (5 questions).

Rollback: deploy the previous backend/web builds. The extra column is harmless
to older code; `alembic downgrade 0013_survey_shares` removes it.

## Tests

```bash
cd backend && pip install -r requirements.txt && pytest
cd web     && npm install && npm test
```

* `backend/tests/test_ai_questionnaire_normalize.py` — 135 cases for the
  validation rules above (no DB, no network).
* `backend/tests/test_ai_questionnaire.py` — endpoints with a scripted fake
  provider: access control, limits, injection, JSON/fenced/truncated/invalid
  output, API failures, repair attempt, preview-only guarantee, saving through
  `POST /api/surveys`, publish confirmation, regenerate question/section,
  usage and audit logs. No API key needed.
* `web/src/pages/surveys/aiDraft.test.ts` — section/group reordering and
  removal, regenerate-section merging, skip-logic integrity.

## Security and privacy

* The API key stays on the server (Phase 1). New endpoints never return it.
* The study brief is untrusted: it is sanitised, length-limited, checked for
  override phrases and sent inside a fenced block; the rules live in the system
  instruction. Model output is never executed and is validated before use.
* Usage logs and audit entries record who/when/outcome and counts only — never
  the brief, prompts or generated questions.
* The brief you type is sent to Google Gemini. Do not put personal data or
  confidential information about real respondents in it.
