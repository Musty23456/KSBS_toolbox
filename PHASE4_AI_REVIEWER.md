# Phase 4 – AI Questionnaire Reviewer

"Review with AI" in the Survey Builder checks the questionnaire that is open (saved or not) and produces a
professional quality report. **A review never changes the questionnaire.**

## Using it
1. Open a survey in the builder and press **🔍 Review with AI**.
2. Optionally type your **research objectives** (one per line) to check coverage.
3. Press **Start review**. You get a **score from 0–100**, a grade, and findings in four groups:
   **Critical issues**, **Warnings**, **Suggestions**, **Good practices**. Each finding has an explanation and a recommended correction.
4. For findings that show **Apply: …**, press it. You see exactly what would change (the same original-vs-proposed
   preview as the Phase 3 editor). Confirm to apply to your *draft*. It can be undone with "Undo AI change";
   nothing is saved until you save (which creates a new version, noted as AI assisted).
5. **Ignore** hides a finding (remembered while the builder is open; **Restore** brings it back).
6. **Copy report / Download report** exports the report as Markdown.

## What is checked
| Area | Examples |
|---|---|
| Clarity / grammar | too long or too short, all capitals, spacing, repeated words, missing "?" |
| Repeated questions | identical or near-identical wording |
| Ambiguity | vague words with no time frame ("often"), absolutes, possible double-barrelled questions |
| Leading / biased | "Don't you agree…", loaded words |
| Answer choices | fewer than two, duplicates, overlapping ranges/gaps, no "Other/Don't know", very long lists |
| Question type | numbers/dates/yes-no typed as text, "select all" on single choice, "main" on multiple choice |
| Required fields | no required questions, consent not required, sensitive question compulsory |
| Consistency | similar option lists that differ, same answer coded differently |
| Skip logic | invalid logic (critical), controlling question left optional |
| Validation | numeric/format limits (age range, phone/email) |
| Objective coverage | does each stated objective have questions (AI; keyword fallback) |

Rule checks are deterministic and run on every review. The **AI pass** adds deeper judgement (any language,
logic, objectives). If AI is switched off, unavailable or returns unusable output, the report is still produced
from the rule checks and says so.

## The score
Computed by code, never by the AI, so the same findings always give the same score:

    score = 100 − penalties + bonus
    penalty per finding: critical 10, warning 4, suggestion 1 (capped at 60 / 30 / 10 per severity)
    penalties are scaled by min(1, 20 / questions), so one issue matters less in a big questionnaire
    bonus: +1 per good practice (max +5), only when there is no critical issue
    an empty questionnaire scores 0

Grades: 90+ Excellent · 75+ Good · 60+ Fair · 40+ Needs improvement · below 40 Poor.
Ignoring a finding hides it but does not change the score (the score describes the questionnaire as it is).

## Safety
- **Read-only endpoint** `POST /api/ai/questionnaire/review`: the questionnaire travels in the request; nothing is read from or written to a survey. The audit log records counts only.
- **Suggested fixes are Phase 3 edit operations.** The server replays every fix on a copy before showing it; a fix is dropped if the engine rejects it, it needs confirmation, it changes nothing, or it would touch any other question (for example, deleting a question that skip logic depends on is never offered as one click).
- AI findings are validated: unknown categories/codes dropped, AI cannot raise CRITICAL (reserved for defects the engine can prove), an AI fix must act on the question its finding names.
- Applying goes through `/api/ai/questionnaire/edit/preview` again against the *current* draft, then the builder's normal apply/undo/save.
- Rate-limited like the other AI endpoints; the same roles may use it.

## Limits
Rule checks use English wording patterns and can miss or over-flag; treat findings as advice. Quality of the AI pass depends on the configured model. The "ignored" list is kept in the open builder session only.

## Code map
Backend `backend/app/ai/questionnaire_review/` (`schemas`, `rules`, `fixes`, `scoring`, `prompts`, `service`), router `app/routers/ai_questionnaire_review.py`.
Web: `components/ai/ReviewModal.tsx`, `pages/surveys/reviewReport.ts`, `aiReviewApi` in `api/services.ts`.

## Tests
- `backend/tests/test_ai_review_rules.py`, `test_ai_review_service.py` (pure), `test_ai_review_endpoints.py` (needs the app's normal test setup)
- Sample questionnaires: `backend/tests/fixtures/review/{well_designed,flawed,minimal}.json`
- `web`: `npm test` (includes `reviewReport.test.ts`)
