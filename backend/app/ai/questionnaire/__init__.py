"""
AI questionnaire generator (Phase 2).

    normalize.py  - pure-Python clean-up/validation of model output (no DB, no Pydantic)
    schemas.py    - request/response models; reuses the existing QuestionIn / SectionIn /
                    QuestionGroupIn schemas so there is only one questionnaire format
    prompts.py    - server-authored system instructions and prompt builders
    service.py    - QuestionnaireGenerator: AIService -> JSON -> normalise -> Pydantic

Nothing in this package writes to the database. Generated content is only ever
returned to the client as a *preview*; saving goes through the existing
POST /api/surveys, which validates it again with SurveyCreate.
"""
