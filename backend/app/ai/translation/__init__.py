"""
Multilingual questionnaire translation (Phase 5).

Pure-Python core (no database, no Pydantic, no web framework), so it can be tested on its own:

    languages.py  - the six supported languages and per-language writing guidance
    protect.py    - placeholders / URLs / numbers that a translation must keep
    catalog.py    - standard validation messages and respondent-screen texts
    units.py      - a questionnaire -> list of translatable units with STABLE keys
    checks.py     - clean-up and safety checks for any translated text
    reconcile.py  - stored translations vs the current questionnaire: missing / outdated / reviewed,
                    completeness, side-by-side comparison, the payload the respondent screen uses
    hausa.py      - deterministic Hausa quality rules and scoring
    prompts.py    - server-authored AI instructions
    service.py    - TranslationService (AI translation) and HausaReviewer (AI review pass)
    schemas.py    - request/response models (the only Pydantic file)

Translations are stored against stable keys (question code, choice value, source-text hash for sections
and groups), never against row ids, because every save of a survey creates new rows with new ids.
Internal identifiers (question codes, choice values, field names, expressions, regex) are not units, so
they cannot be sent to the model or changed by a translation.
"""
