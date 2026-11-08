"""
QuestionnaireEditor: command -> AI -> operations -> engine -> preview.

    parse the reply (JSON, one automatic repair attempt) -> run the operations through the engine
    on a COPY of the questionnaire -> return a validated preview.

Nothing here writes to the database (apart from the usage log AIService keeps), and the AI
never sees or touches anything but the compact text of the questionnaire it was shown.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from app.ai.errors import (
    AIInvalidJsonError,
    AIInvalidQuestionnaireError,
    AIResponseTruncatedError,
)
from app.ai.questionnaire import normalize
from app.ai.questionnaire_edit import prompts
from app.ai.questionnaire_edit.diff import build_preview
from app.ai.questionnaire_edit.engine import EngineResult, run
from app.ai.questionnaire_edit.operations import MAX_OPERATIONS, OperationError
from app.ai.questionnaire_edit.schemas import EditProposal, EditRequest

if TYPE_CHECKING:  # pragma: no cover
    from app.ai.service import AIService

logger = logging.getLogger("app.ai.questionnaire_edit")

MAX_ATTEMPTS = 2  # first try + one repair attempt
_TOKENS_BASE = 4096
_TOKENS_PER_QUESTION = 120
_MESSAGE_MAX = 1000


class AIEditResponseTruncatedError(AIResponseTruncatedError):
    safe_message = (
        "The AI's answer was cut off because the change was too large. "
        "Try a smaller request, for example one section at a time."
    )


def _truncated(finish_reason: Optional[str]) -> bool:
    return bool(finish_reason) and "MAX_TOKENS" in str(finish_reason).upper()


def parse_reply(text: str) -> tuple[str, list[Any]]:
    """Return ``(message, operations)`` from the model's reply or raise a safe AI error."""
    raw = normalize.extract_json(text)
    if isinstance(raw, list):  # tolerate a bare list of operations
        raw = {"operations": raw}
    if not isinstance(raw, dict):
        raise AIInvalidQuestionnaireError("The AI response was not a set of edit operations.")
    operations = raw.get("operations", [])
    if operations is None:
        operations = []
    if not isinstance(operations, list):
        raise AIInvalidQuestionnaireError("The AI response had the wrong structure at 'operations'.")
    if len(operations) > MAX_OPERATIONS:
        raise AIInvalidQuestionnaireError(f"The AI proposed too many operations (the limit is {MAX_OPERATIONS}).")
    message = normalize.clean_text(raw.get("message") or raw.get("summary"), _MESSAGE_MAX, allow_newlines=False) or ""
    return message, operations


def _failure_reason(result: EngineResult) -> str:
    reasons = [r.reason for r in result.rejected if not r.no_change][:6]
    if result.blocked:
        return result.blocked
    return "None of your operations could be applied: " + " ".join(f"({i}) {reason}" for i, reason in enumerate(reasons, start=1))


class QuestionnaireEditor:
    def __init__(self, ai: "AIService"):
        self.ai = ai
        self.cfg = ai.config

    def propose(self, req: EditRequest, user_id: Optional[str]) -> EditProposal:
        prompt = prompts.build_edit_prompt(req, max_chars=self.cfg.generation_max_prompt_chars)
        max_tokens = min(
            self.cfg.generation_max_output_tokens,
            _TOKENS_BASE + _TOKENS_PER_QUESTION * max(10, len(req.snapshot.questions)),
        )

        reason: Optional[str] = None
        message, result, model = "", None, ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            text = prompt if reason is None else prompt + prompts.repair_suffix(reason)
            response = self.ai.generate_text(
                text,
                user_id=user_id,
                request_type="questionnaire_edit",
                system_instruction=prompts.SYSTEM_EDIT,
                max_output_tokens=max_tokens,
                json_mode=True,
                max_prompt_chars=self.cfg.generation_max_prompt_chars,
            )
            if _truncated(response.finish_reason):
                raise AIEditResponseTruncatedError()
            model = response.model
            try:
                message, operations = parse_reply(response.text)
            except (AIInvalidJsonError, AIInvalidQuestionnaireError) as exc:
                logger.info("Edit reply rejected (%s) on attempt %d/%d", exc.code, attempt, MAX_ATTEMPTS)
                if attempt == MAX_ATTEMPTS:
                    raise
                reason = exc.safe_message
                continue
            try:
                result = run(req.snapshot, operations)
            except OperationError as exc:  # e.g. too many operations
                if attempt == MAX_ATTEMPTS:
                    raise AIInvalidQuestionnaireError(str(exc)) from exc
                reason = str(exc)
                continue

            nothing_applied = not result.applied
            has_real_failures = any(not r.no_change for r in result.rejected) or bool(result.blocked)
            if operations and nothing_applied and has_real_failures and attempt < MAX_ATTEMPTS:
                reason = _failure_reason(result)
                continue
            break

        assert result is not None  # the loop either sets it or raises
        preview = build_preview(result)
        if not message:
            message = "No changes were proposed." if not preview.operations else "Here are the proposed changes."
        return EditProposal(**preview.model_dump(), message=message, model=model)
