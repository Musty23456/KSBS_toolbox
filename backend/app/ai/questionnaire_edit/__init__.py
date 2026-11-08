"""
AI questionnaire editor (Phase 3).

    operations.py - the nine structured edit operations (ADD_QUESTION, UPDATE_QUESTION, ...)
                    and the parser that turns model JSON into them
    snapshot.py   - the questionnaire as the Survey Builder holds it (input and output shape)
    engine.py     - applies operations to a *copy* of a snapshot, validates the result,
                    enforces the "never wipe a questionnaire" guards
    diff.py       - original-vs-proposed comparison shown in the preview
    schemas.py    - request / response models for the endpoints
    prompts.py    - server-authored instructions and the compact questionnaire context
    service.py    - QuestionnaireEditor: instruction -> AI -> operations -> engine -> preview

Safety model
* The AI never touches the database. It can only *propose* operations.
* Operations are applied to an in-memory copy; the person sees the exact
  difference and must press Apply. Applying replaces the Survey Builder's
  draft; nothing is saved until the person saves, which creates a new
  immutable survey version.
* Every operation is validated. One bad operation is rejected (with a reason)
  without discarding the others, and nothing is ever dropped silently.

This package is plain Python + Pydantic (no database, no web framework) so the
whole editing engine can be unit tested on its own.
"""
