"""
AI questionnaire reviewer (Phase 4).

    schemas.py  - request and the review report (findings, score, coverage)
    rules.py    - deterministic checks that need no AI (skip logic, choices, types, duplicates, bias, grammar...)
    fixes.py    - turns a suggested fix into a validated Phase 3 edit operation (or drops it)
    scoring.py  - the 0-100 quality score, computed by code (never by the AI)
    prompts.py  - server-authored instructions for the AI pass
    service.py  - QuestionnaireReviewer: rules + AI -> merged, validated report

Safety model
* A review is READ-ONLY. It never changes the questionnaire and never writes to the database.
* A suggested fix is a Phase 3 edit operation. The person applies it through the same validated preview
  (original vs proposed) and undo as any other AI edit, one suggestion at a time.
* The rule checks always run. If the AI is off or fails, the report is still produced (and says so).
"""
