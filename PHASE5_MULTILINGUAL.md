# Phase 5 – Multilingual AI Translation

Translate a whole questionnaire into **English, Hausa, Yoruba, Igbo, French and Arabic** with Gemini, then check,
edit, compare and review it. Respondents pick their language on the fill screen.

## Using it
1. Open **Languages** in the menu (administrators and supervisors: global surveys and their own; anyone else: their own personal surveys).
2. Pick a survey and a language tab. Each tab shows how complete it is.
3. **Translate missing & outdated** sends the work to the AI in chunks of 60 texts with a progress line. Results are saved as **AI draft**.
4. Correct any text in the table and press **Save** (or **Save N changes**). Status becomes **Edited**. **Mark reviewed** records that a person checked it.
5. **Compare** shows the original beside up to three languages. **Hausa quality review** appears on the Hausa tab.
6. Publish as usual. On the fill screen a **Language** selector appears for every language with at least one translated text.

## What is translated
Survey title and description (the AI generator stores introduction and instructions inside the description, so they are included),
section and group titles and descriptions, questions, hints, answer choices, and the **standard texts** every form shows:
validation messages ("required", "must be at least {min}", "enter a whole number"…), Yes/No, "Select…", the progress line and the
submit button.

## What is never translated (and cannot be)
Question codes, choice values, question types, required flags, min/max, regular expressions, skip-logic and calculation expressions,
cascading-select links, ids. They are not translation units, so they are never sent to the model and no translation can change them.
Submissions store the choice **value** (`YES`), never the label the respondent read (`Ee`), so collected data is the same in every language.
Translating creates **no new survey version**.

## Why keys, not row ids
Every save of a survey creates a new version with new row ids, so the older per-id `translations` table loses everything on each save.
Translations are stored in `questionnaire_translations` against stable keys:

| Text | Key |
|---|---|
| survey | `survey` |
| question | the question **code** |
| answer choice | `<question code>::<choice value>` |
| section / group | hash of its **title** (they have no code) |
| standard texts | `msg.required`, `ui.submit`, … |

Consequences: translations survive saves, reordering and insertions; renaming a section makes it a new, untranslated section; two
sections with the identical title share one translation.

## Status of each text
`MISSING` → nothing yet · `OUTDATED` → the original changed after it was translated · `AI_DRAFT` · `EDITED` · `REVIEWED`.
Detection compares a hash of the source text stored with each translation. **Mark reviewed / Still correct** on an outdated text
confirms it against the new wording.

Respondents only see usable text: missing and outdated texts fall back to the original, **field by field**, so a half-translated form works
and a changed question never shows a stale translation.

## Partial translation and updates
The translate request takes `scope` (`missing`, `outdated`, `missing_and_outdated`, `all`), optional `entity_types` (e.g. only answer choices)
and optional `units` (one question). A person's work (`EDITED`, `REVIEWED`) is **never overwritten by the AI** unless `overwrite_manual` is set.
A request handles at most `max_units` (default 60); the page repeats it, waits when the AI rate limit says so, and stops when no progress is made.

## Safety against breaking the questionnaire
Applied to AI output **and** manual edits (`app/ai/translation/checks.py`):
* **Blocked, not saved:** empty text; longer than the field allows (255 titles, 500 choices…); a lost or invented placeholder (`{min}`, `{{x}}`, `%s`), URL, e-mail or markup tag.
* **Warned:** a number in the source missing from the translation; paragraph structure changed; identical to the original; question mark missing; wrong script (Latin text for Arabic, Arabic script in Hausa…); two choices of one question with the same translated label.
* Text is tidied: control characters and invisible direction marks removed, whitespace normalised, NFC.
* Manual saves are **all-or-nothing**: if one text is blocked nothing is saved and every problem is listed.
* An AI answer that breaks a rule is asked for once more with the reason; if it still fails it is dropped and that text stays untranslated.
* Replies are untrusted: unknown ids are ignored, malformed JSON is repaired once, a cut-off reply is split and retried.

## Hausa quality review
`POST /api/surveys/{id}/i18n/ha/review` (read-only). Rule checks always run: left untranslated, English words left inside, wrong script,
a short list of very common words normally written with a hooked letter (`kudi` → `kuɗi`, `daya` → `ɗaya`, `kauye` → `ƙauye`…),
suspicious length, missing numbers / question marks, and the same short English text translated differently in different places.
The optional AI pass judges accuracy, natural phrasing, orthography, register, clarity and terminology; its suggestions must pass the same
safety checks or are dropped. Text a person already marked **Reviewed** is not re-reviewed by the AI. The score (0–100) is computed by code
(100 minus 6 per text with a warning or 2 per text with only suggestions, scaled by the number of texts), never by the AI.
**Apply** saves a suggestion as a normal manual edit. The report always says it is an automatic aid and that a native Hausa speaker should
read the final text; nothing marks a translation Reviewed automatically.

## API (all under `/api/surveys/{id}/i18n`)
| Method | Path | Who |
|---|---|---|
| GET | `/overview` | can edit the survey |
| GET | `/available` | anyone who can view the survey |
| GET | `/compare?languages=ha,fr` | can edit |
| GET | `/{lang}` | can edit |
| GET | `/{lang}/localized` | anyone who can view (respondent payload, keyed by current row ids) |
| PUT | `/{lang}/units` | can edit |
| POST | `/{lang}/translate` | can edit, rate-limited, AI |
| DELETE | `/{lang}` | can edit |
| POST | `/ha/review` | can edit, rate-limited, AI optional |
| POST | `/import-legacy` | can edit |

"Can edit" follows the existing rules: owner for personal surveys; administrators and supervisors for global surveys. People a personal survey is
shared with can read translations and fill the form, not edit. The audit log records counts and codes only, never questionnaire text.
The older `/api/surveys/{id}/translations` and `/localized` endpoints and table are unchanged; **Import older translations** copies matching rows across.

## Tests
* `backend/tests/test_translation_core.py` – 33 tests, no database: placeholders, stable keys, checks, status tracking, partial selection, comparison, Hausa rules, the AI services with a scripted fake AI.
* `backend/tests/test_translation_endpoints.py` – end-to-end API tests: keys across versions, outdated detection, chunking, manual edits, protection of human work, comparison, respondent payload, access rules, Hausa review, audit, legacy import, and that a fully translated survey still validates and stores the same values.
* `web/src/pages/translations/translationUtils.test.ts` – 7 tests (`npm test`).

## Limits
* **The Android app is not changed in this phase.** Language selection is on the web fill screen. Android works offline from Room, so it needs the translations added to sync, a Room migration and UI; that is a separate step.
* Validation messages returned by the **server** after submit (a second line of defence) stay in English; the form's own messages are translated.
* Translation quality depends on the Gemini model. Check the final text, especially Hausa, Yoruba and Igbo.
* The Hausa rules are deliberately modest (small word list, English-word heuristic); they catch obvious problems, not dialect or style questions.
* One translation serves all sections/groups with an identical title. Renaming a section requires translating it again.
* Orphaned translations (for deleted questions or renamed sections) are kept, not deleted, and counted in the overview.
