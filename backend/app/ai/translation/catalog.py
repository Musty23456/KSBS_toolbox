"""
Standard messages every questionnaire shows: validation messages and the texts around the form.

They are translatable like any other text (entity type SYSTEM) so a respondent who picks Hausa sees
"required" and "must be at least {min}" in Hausa too. {min}, {max}, {answered}, {total} and {count} are
placeholders the translation must keep.
"""

from __future__ import annotations

SYSTEM_MESSAGES: dict[str, str] = {
    "msg.required": "This question is required.",
    "msg.number": "Enter a valid number.",
    "msg.integer": "Enter a whole number.",
    "msg.min": "Must be at least {min}.",
    "msg.max": "Must be at most {max}.",
    "msg.min_length": "Write at least {min} characters.",
    "msg.max_length": "Write at most {max} characters.",
    "msg.fix_errors": "Please fix {count} highlighted question(s).",
    "ui.yes": "Yes",
    "ui.no": "No",
    "ui.select": "Select…",
    "ui.answer_earlier": "Answer the earlier question first.",
    "ui.progress": "{answered} of {total} answered",
    "ui.submit": "Submit response",
    "ui.submitting": "Submitting…",
    "ui.language": "Language",
}

VALIDATION_KEYS = tuple(k for k in SYSTEM_MESSAGES if k.startswith("msg."))


def describe(key: str) -> str:
    kind = "Validation message" if key.startswith("msg.") else "Respondent screen text"
    return f"{kind} ({key})"
