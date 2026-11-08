"""
QuestionnaireGenerator: brief -> Gemini (JSON) -> parse -> Pydantic -> normalise -> Pydantic.

Failure handling
* provider failures (key, quota, network, timeout, 5xx, blocked) are already
  mapped to safe ``AIError`` s by ``AIService`` / the provider and pass through;
* output cut off by the token limit raises ``AIResponseTruncatedError`` (never
  parsed, never repaired - asking again would be cut off again);
* invalid JSON, a wrong envelope, or a questionnaire with nothing usable gets
  ONE automatic repair attempt that tells the model what was wrong, then fails
  with ``AI_INVALID_JSON`` / ``AI_INVALID_QUESTIONNAIRE``.

Nothing here touches the database except the usage log written by AIService.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, TypeVar

from pydantic import ValidationError

from app.ai.errors import (
    AIInvalidJsonError,
    AIInvalidQuestionnaireError,
    AIInvalidRequestError,
    AIResponseTruncatedError,
)
from app.ai.questionnaire import normalize, prompts
from app.ai.questionnaire.schemas import (
    ContextQuestion,
    GeneratedQuestionnairePreview,
    QuestionnaireBrief,
    RegeneratedQuestion,
    RegeneratedSection,
    RegenerateQuestionRequest,
    RegenerateSectionRequest,
    SkipLogicSuggestion,
    WireQuestionnaire,
    WireSingleQuestion,
    WireSingleSection,
)
from app.ai.service import AIService
from app.schemas.survey import QuestionGroupIn, QuestionIn, SectionIn

logger = logging.getLogger("app.ai.questionnaire")

T = TypeVar("T")

MAX_ATTEMPTS = 2  # first try + one repair attempt
_TOKENS_BASE = 4096  # headroom for the model's own reasoning
_TOKENS_PER_QUESTION = 350
_TOKENS_SINGLE_QUESTION = 4096


def _truncated(finish_reason: Optional[str]) -> bool:
    return bool(finish_reason) and "MAX_TOKENS" in str(finish_reason).upper()


def _context_infos(items: list[ContextQuestion]) -> dict[str, normalize.QuestionInfo]:
    infos: dict[str, normalize.QuestionInfo] = {}
    for item in items:
        values = normalize.YES_NO_VALUES if item.type.value == "YES_NO" else frozenset(item.choice_values)
        infos[item.code] = normalize.QuestionInfo(code=item.code, type=item.type.value, values=frozenset(values))
    return infos


def _suggestions(items: list[dict[str, str]]) -> list[SkipLogicSuggestion]:
    return [SkipLogicSuggestion(**item) for item in items]


class QuestionnaireGenerator:
    def __init__(self, ai: AIService):
        self.ai = ai
        self.cfg = ai.config

    # ------------------------------------------------------------------ core

    def _run(
        self,
        *,
        prompt: str,
        system: str,
        user_id: Optional[str],
        request_type: str,
        max_tokens: int,
        parse: Callable[[str], T],
    ) -> tuple[T, str]:
        """Call the model, parse the reply, repair once on a bad reply. Returns (result, model)."""
        reason: Optional[str] = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            text = prompt if reason is None else prompt + prompts.repair_suffix(reason)
            response = self.ai.generate_text(
                text,
                user_id=user_id,
                request_type=request_type,
                system_instruction=system,
                max_output_tokens=max_tokens,
                json_mode=True,
                max_prompt_chars=self.cfg.generation_max_prompt_chars,
            )
            if _truncated(response.finish_reason):
                raise AIResponseTruncatedError()
            try:
                return parse(response.text), response.model
            except (AIInvalidJsonError, AIInvalidQuestionnaireError) as exc:
                logger.info("Questionnaire reply rejected (%s) on attempt %d/%d", exc.code, attempt, MAX_ATTEMPTS)
                if attempt == MAX_ATTEMPTS:
                    raise
                reason = exc.safe_message
        raise AIInvalidQuestionnaireError()  # pragma: no cover - loop always returns or raises

    @staticmethod
    def _wire(model_cls: type[T], raw: Any) -> T:
        try:
            return model_cls.model_validate(raw)  # type: ignore[attr-defined]
        except ValidationError as exc:
            # Only the *location* of the problem is used; never echo model text back.
            where = ".".join(str(p) for p in exc.errors()[0].get("loc", ())) if exc.errors() else "response"
            raise AIInvalidQuestionnaireError(
                f"The AI response had the wrong structure at '{where}'."
            ) from exc

    def _tokens_for(self, count: int) -> int:
        return min(self.cfg.generation_max_output_tokens, _TOKENS_BASE + _TOKENS_PER_QUESTION * max(1, count))

    # -------------------------------------------------------------- generate

    def generate(self, brief: QuestionnaireBrief, user_id: Optional[str]) -> GeneratedQuestionnairePreview:
        limit = self.cfg.generation_max_questions
        if brief.expected_question_count > limit:
            raise AIInvalidRequestError(f"You can ask for at most {limit} questions at a time.")

        def parse(text: str) -> dict[str, Any]:
            raw = normalize.extract_json(text)
            wire = self._wire(WireQuestionnaire, raw)
            return normalize.normalize_questionnaire(
                wire.model_dump(), expected_count=brief.expected_question_count, max_questions=limit
            )

        data, model = self._run(
            prompt=prompts.build_generate_prompt(brief),
            system=prompts.SYSTEM_GENERATE,
            user_id=user_id,
            request_type="questionnaire_generate",
            max_tokens=self._tokens_for(brief.expected_question_count),
            parse=parse,
        )

        try:
            sections = [SectionIn(**s) for s in data["sections"]]
            groups = [QuestionGroupIn(**g) for g in data["groups"]]
            questions = [QuestionIn(**q) for q in data["questions"]]
        except ValidationError as exc:  # normalisation should make this impossible; never let it through if not
            logger.error("Normalised questionnaire failed schema validation: %s", exc.errors()[:1])
            raise AIInvalidQuestionnaireError() from exc

        # A title the user typed wins; otherwise the model's, then the topic.
        title = brief.survey_title or data["title"] or brief.research_topic[:255]
        return GeneratedQuestionnairePreview(
            title=title[:255],
            description=data["description"],
            introduction=data["introduction"],
            respondent_instructions=data["respondent_instructions"],
            composed_description=normalize.compose_description(
                data["description"], data["introduction"], data["respondent_instructions"]
            ),
            sections=sections,
            groups=groups,
            questions=questions,
            skip_logic=_suggestions(data["skip_logic"]),
            warnings=data["warnings"],
            model=model,
            requested_question_count=brief.expected_question_count,
        )

    # -------------------------------------------------- regenerate question

    def regenerate_question(self, req: RegenerateQuestionRequest, user_id: Optional[str]) -> RegeneratedQuestion:
        original = req.question
        known = _context_infos(req.preceding_questions)

        def parse(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
            raw = normalize.extract_json(text)
            if isinstance(raw, dict) and "question" not in raw and "label" in raw:
                raw = {"question": raw}  # model returned the bare question
            wire = self._wire(WireSingleQuestion, raw)
            ctx = normalize.Context(taken_codes=set(req.other_codes), known=dict(known))
            question = normalize.normalize_question(wire.question, ctx, forced_code=original.code.strip() or None)
            if question is None:
                raise AIInvalidQuestionnaireError(
                    "; ".join(ctx.warnings) or "The AI response did not contain a usable question."
                )
            return question, {"skip_logic": ctx.skip_logic, "warnings": ctx.warnings}

        (question, extras), model = self._run(
            prompt=prompts.build_regenerate_question_prompt(
                req.brief,
                section_title=req.section_title,
                question=original.model_dump(
                    include={"code", "label", "hint", "type", "is_required", "choices", "relevance_expression"},
                    mode="json",
                ),
                instruction=req.instruction,
                preceding=req.preceding_questions,
            ),
            system=prompts.SYSTEM_REGENERATE_QUESTION,
            user_id=user_id,
            request_type="questionnaire_regenerate_question",
            max_tokens=_TOKENS_SINGLE_QUESTION,
            parse=parse,
        )

        try:
            # Position and ownership never change when a question is regenerated.
            built = QuestionIn(**question).model_copy(
                update={
                    "order_index": original.order_index,
                    "section_id": original.section_id,
                    "group_id": original.group_id,
                    "cascade_parent_question_id": original.cascade_parent_question_id,
                }
            )
        except ValidationError as exc:
            raise AIInvalidQuestionnaireError() from exc
        return RegeneratedQuestion(
            question=built, skip_logic=_suggestions(extras["skip_logic"]), warnings=extras["warnings"], model=model
        )

    # ---------------------------------------------------- regenerate section

    def regenerate_section(self, req: RegenerateSectionRequest, user_id: Optional[str]) -> RegeneratedSection:
        limit = self.cfg.generation_max_questions
        target = req.question_count or len(req.current_questions) or 5
        known = _context_infos(req.preceding_questions)

        def parse(text: str) -> dict[str, Any]:
            raw = normalize.extract_json(text)
            if isinstance(raw, dict) and "section" not in raw and ("questions" in raw or "groups" in raw):
                raw = {"section": raw}  # model returned the bare section
            wire = self._wire(WireSingleSection, raw)
            ctx = normalize.Context(taken_codes=set(req.other_codes), known=dict(known))
            section = normalize.normalize_section(
                wire.section.model_dump(), ctx, section_ref=None, group_offset=0, question_budget=limit
            )
            if section is None:
                raise AIInvalidQuestionnaireError(
                    "; ".join(ctx.warnings) or "The AI response did not contain a usable section."
                )
            for i, group in enumerate(section["groups"], start=1):
                group["order_index"] = i
            for i, question in enumerate(section["questions"], start=1):
                question["order_index"] = i
            section["skip_logic"], section["warnings"] = ctx.skip_logic, ctx.warnings
            return section

        data, model = self._run(
            prompt=prompts.build_regenerate_section_prompt(
                req.brief,
                section_title=req.section_title,
                section_description=req.section_description,
                current=req.current_questions,
                preceding=req.preceding_questions,
                question_count=req.question_count,
                instruction=req.instruction,
            ),
            system=prompts.SYSTEM_REGENERATE_SECTION,
            user_id=user_id,
            request_type="questionnaire_regenerate_section",
            max_tokens=self._tokens_for(target),
            parse=parse,
        )

        try:
            return RegeneratedSection(
                section=SectionIn(title=data["title"], description=data["description"], order_index=0),
                groups=[QuestionGroupIn(**g) for g in data["groups"]],
                questions=[QuestionIn(**q) for q in data["questions"]],
                skip_logic=_suggestions(data["skip_logic"]),
                warnings=data["warnings"],
                model=model,
            )
        except ValidationError as exc:
            raise AIInvalidQuestionnaireError() from exc
