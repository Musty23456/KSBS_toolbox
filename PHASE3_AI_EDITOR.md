# Phase 3 — AI Questionnaire Editor

Edit an existing questionnaire in plain language ("Make question 5 compulsory", "Translate question 3 into
Hausa", "Remove duplicate questions", ...). The AI **proposes structured operations**; you see exactly what
would change and press **Apply changes** or **Reject changes**. Phases 1 and 2 are unchanged.

## How it works

```
command + builder draft ─▶ POST /api/ai/questionnaire/edit/propose
                              AI → JSON operations → engine applies them to a COPY → validated preview
preview (added / changed / deleted, original vs proposed) ─▶ you tick/untick operations
                              (POST /edit/preview re-validates the ticked set; no AI call)
Apply changes ─▶ replaces the builder DRAFT only ─▶ Save changes ─▶ new survey version
```

* The AI never writes to the database. Applying only changes the draft in the builder; nothing is saved
  until you press **Save changes**, which (as before) creates a new immutable version.
* Nothing is silent: every side effect (answer options dropped because a type changed, skip logic cleared
  because its question was deleted, a question leaving its group, ...) is listed under "Check these side
  effects" and appears in the changed list.

## Operations (all validated before they are shown)

`ADD_QUESTION`, `UPDATE_QUESTION`, `DELETE_QUESTION`, `ADD_SECTION`, `UPDATE_SECTION`, `DELETE_SECTION`,
`REORDER_QUESTIONS`, `UPDATE_CHOICES` (REPLACE / ADD / REMOVE / UPDATE_LABELS), `UPDATE_VALIDATION`.

Rules worth knowing: question **codes** and existing option **values** can never be changed by an edit;
`DELETE_SECTION` keeps its questions (moves them) unless the operation explicitly says to delete them;
a type change removes settings that no longer apply and says so; every result must pass the same checks as a
saved survey (choice counts, ranges, safe regexes, skip logic that only refers to earlier questions).
One invalid operation is rejected with a reason and the rest still work.

## Safety guards

* A change that would leave **zero questions** is blocked outright (archive the survey instead).
* Deleting **3+ questions and ≥30 %** (or 10+), or most sections, needs an extra "I understand" tick.
* A proposal only applies to the exact draft it was made for; if you edit meanwhile, apply is refused.
* **Undo AI change / Redo AI change** step through whole AI changes (sections, groups, questions). They only
  work while the draft still equals what that change produced, so they can never discard your own later edits
  (use the normal Undo for those). The builder's existing Undo/Redo is unchanged.
* The server also refuses `PUT /api/surveys/{id}` with an empty question list.

## Version history

Each save of the questions already created a version; they now also record **who**, **source** (manual or AI
assisted) and a **note** (the AI commands applied, or "Restored from version N").
`GET /api/surveys/{id}/versions` and `GET /api/surveys/{id}/versions/{version_id}` (people who can edit the
survey). In the builder: **Version history → View questions / Load into editor**. Loading copies an old
version into the draft (undoable); nothing is saved until you save.

## Files

Backend: `app/ai/questionnaire_edit/` (operations, snapshot, engine, diff, schemas, prompts, service),
`app/routers/ai_questionnaire_edit.py`, `app/routers/surveys.py` (history endpoints, empty-save guard),
`app/models/survey.py` + migration `0015_survey_version_history` (3 nullable columns), `app/schemas/survey.py`,
`app/config.py` / `app/ai/config.py` (`AI_EDIT_MAX_REQUEST_BYTES`, default 262144).

Web: `components/ai/AIEditorPanel.tsx`, `EditPreviewView.tsx`, `VersionHistoryModal.tsx`,
`pages/surveys/aiEdit.ts`, `SurveyBuilderPage.tsx`, `api/*`, `styles/ai.css`.

## One fix to the existing save path

`SectionIn` / `QuestionGroupIn` accept an optional `id`, and saving now maps a re-saved section's/group's old id
to its new row. Before, questions of an edited saved survey kept pointing at the *previous version's* sections.
The builder now also reloads sections/groups from the save response.

## Deploy

1. Backend: run `alembic upgrade head` (adds migration 0015). 2. Web. No new environment variables are required.

## Tests

* `backend/tests/test_ai_edit_engine.py` — every operation, validation, guards, diff (pure, no DB).
* `backend/tests/test_ai_edit_service.py` — command → fake AI → preview, repair attempts, truncation.
* `backend/tests/test_ai_edit_endpoints.py` — auth, size, audit, preview-only, version history, empty-save guard.
* `web/src/pages/surveys/aiEdit.test.ts` — apply rules, confirmation, undo/redo safety, version notes.

Run: `cd backend && pytest` and `cd web && npm test`.
