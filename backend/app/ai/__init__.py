"""
AI integration layer.

Layout (each piece is independent so providers can be swapped or added):

    config.py      - validated, read-only view of the AI settings
    errors.py      - AIError hierarchy with safe, client-facing messages
    schemas.py     - request/response models for the AI endpoints
    validation.py  - prompt validation and prompt-injection guards
    redaction.py   - scrubs secrets from anything that might be logged
    providers/     - AIProvider interface + concrete providers (Gemini)
    service.py     - AIService: validation -> provider -> response checks,
                     retries and usage logging
    rate_limit.py  - per-user sliding-window limiter for AI endpoints
    usage.py       - AIUsageLog persistence (no prompts or responses stored)
"""
