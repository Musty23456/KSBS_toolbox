"""
QuestionnaireReviewer: rule checks (always) + AI pass (optional) -> one validated report.

READ-ONLY: it never changes the questionnaire and writes nothing. If the AI is off, slow or returns rubbish,
the report is still produced from the rules and says the AI part was skipped.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from app.ai.errors import AIError, AIInvalidJsonError, AIInvalidQuestionnaireError, AIResponseTruncatedError
from app.ai.questionnaire import normalize
from app.ai.questionnaire_review import prompts
from app.ai.questionnaire_review.fixes import verify_fixes
from app.ai.questionnaire_review.rules import (
    coverage_findings,
    dedupe,
    keyword_coverage,
    make_finding,
    run_rules,
    split_objectives,
)
from app.ai.questionnaire_review.schemas import (
    CATEGORIES,
    SEVERITY_ORDER,
    CoverageItem,
    Finding,
    ReviewReport,
    ReviewRequest,
)
from app.ai.questionnaire_review.scoring import compute_score, count_by_severity, grade_for

if TYPE_CHECKING:  # pragma: no cover
    from app.ai.service import AIService

logger = logging.getLogger("app.ai.questionnaire_review")

MAX_ATTEMPTS = 2
_TOKENS_BASE = 3072
_TOKENS_PER_QUESTION = 60


def parse_review_reply(text: str) -> dict[str, Any]:
    raw = normalize.extract_json(text)
    if not isinstance(raw, dict):
        raise AIInvalidQuestionnaireError("The AI response was not a review object.")
    if not isinstance(raw.get("findings", []), list) or not isinstance(raw.get("coverage", []), list):
        raise AIInvalidQuestionnaireError("The AI review had the wrong structure.")
    return raw


def _text(value: Any, n: int) -> str:
    return normalize.clean_text(value, n, allow_newlines=False) or ""


def accept_ai_findings(raw_findings: list[Any], codes: dict[str, Any]) -> list[Finding]:
    """Turn the model's findings into Finding objects. Anything malformed is dropped, never trusted."""
    out: list[Finding] = []
    for raw in raw_findings[: prompts.MAX_AI_FINDINGS]:
        if not isinstance(raw, dict):
            continue
        severity = str(raw.get("severity", "")).strip().upper()
        if severity == "CRITICAL":  # CRITICAL is reserved for defects the engine can prove
            severity = "WARNING"
        category = str(raw.get("category", "")).strip().upper()
        title = _text(raw.get("title"), 90)
        if severity not in ("WARNING", "SUGGESTION", "GOOD") or category not in CATEGORIES or not title:
            continue
        code = raw.get("code")
        code = code.strip() if isinstance(code, str) and code.strip() in codes else None
        fix = raw.get("fix") if isinstance(raw.get("fix"), dict) and severity != "GOOD" else None
        if fix is not None and (code is None or fix.get("code") != code):
            fix = None  # a fix must act on the very question the finding is about
        out.append(
            make_finding(
                severity, category, title,
                _text(raw.get("explanation"), 500), _text(raw.get("recommendation"), 400),
                codes.get(code) if code else None, fix=fix, source="AI", code=code,
            )
        )
    return out


def accept_ai_coverage(raw_items: list[Any], objectives: list[str], codes: dict[str, Any]) -> list[CoverageItem]:
    by_objective: dict[str, dict[str, Any]] = {}
    for item in raw_items:
        if isinstance(item, dict) and isinstance(item.get("objective"), str):
            by_objective[item["objective"].strip().lower()] = item
    out: list[CoverageItem] = []
    for obj in objectives:
        item = by_objective.get(obj.strip().lower())
        if item is None:
            return []  # incomplete answer: let the caller fall back to the keyword check
        raw_codes = item.get("codes") if isinstance(item.get("codes"), list) else []
        out.append(CoverageItem(
            objective=obj, covered=bool(item.get("covered")),
            question_codes=[c for c in raw_codes if isinstance(c, str) and c in codes][:10],
            note=_text(item.get("note"), 300)))
    return out


def sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: SEVERITY_ORDER[f.severity])  # stable: keeps form order inside a severity


class QuestionnaireReviewer:
    def __init__(self, ai: "AIService"):
        self.ai = ai
        self.cfg = ai.config

    def review(self, req: ReviewRequest, user_id: Optional[str]) -> ReviewReport:
        rules = run_rules(req.snapshot)
        state = rules.state
        codes = {q.code: q for q in state.questions if q.code}
        findings = list(rules.findings)
        limitations: list[str] = []

        objectives = split_objectives(req.objectives)
        coverage: list[CoverageItem] = []
        ai_used, ai_error, model = False, None, ""

        if req.use_ai and state.questions:
            try:
                raw, model = self._ask_ai(req, state, [f.title for f in findings if f.severity != "GOOD"], user_id, len(state.questions))
                existing = {(f.category, f.question_code) for f in findings if f.severity != "GOOD"}
                extra = [f for f in accept_ai_findings(raw.get("findings", []), codes)
                         if f.severity == "GOOD" or (f.category, f.question_code) not in existing]
                findings += extra
                coverage = accept_ai_coverage(raw.get("coverage", []), objectives, codes) if objectives else []
                ai_used = True
                ai_summary = _text(raw.get("summary"), 600)
            except AIError as exc:
                ai_error = exc.safe_message
                logger.info("AI review skipped (%s)", exc.code)
                ai_summary = ""
        else:
            ai_summary = ""
            if not req.use_ai:
                ai_error = "AI analysis was switched off for this review."

        if objectives and not coverage:
            coverage = keyword_coverage(state, objectives)
            if ai_used:
                limitations.append("The AI did not return a usable objectives check, so objectives were matched by keywords only.")
        findings += coverage_findings(coverage, "AI" if ai_used and coverage and "keyword" not in coverage[0].note.lower() else "RULE")
        if not objectives:
            limitations.append("No research objectives were provided, so objective coverage was not checked.")
        if not ai_used:
            limitations.append("Only the built-in rule checks ran. Subtle wording, non-English text and deeper logic problems need the AI pass.")
        limitations.append("Rule checks use English wording patterns and can miss or over-flag. Treat findings as advice, not verdicts.")

        findings = verify_fixes(req.snapshot, sort_findings(dedupe(findings)))
        score, breakdown = compute_score(findings, len(state.questions))
        counts = count_by_severity(findings)
        grade = grade_for(score)
        summary = (
            f"Quality score {score}/100 ({grade}). "
            f"{counts['CRITICAL']} critical issue(s), {counts['WARNING']} warning(s), {counts['SUGGESTION']} suggestion(s), "
            f"{counts['GOOD']} good practice(s) across {rules.stats.questions} question(s)."
        )
        if ai_summary:
            summary += " " + ai_summary
        return ReviewReport(
            score=score, grade=grade, summary=summary, counts=counts, findings=findings, coverage=coverage,
            objectives_checked=bool(objectives), stats=rules.stats, score_breakdown=breakdown,
            ai_used=ai_used, ai_error=ai_error, model=model,
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), limitations=limitations,
        )

    # ------------------------------------------------------------------ AI call

    def _ask_ai(self, req, state, already_found, user_id, n_questions) -> tuple[dict[str, Any], str]:
        prompt = prompts.build_review_prompt(req, state, already_found, max_chars=self.cfg.generation_max_prompt_chars)
        max_tokens = min(self.cfg.generation_max_output_tokens, _TOKENS_BASE + _TOKENS_PER_QUESTION * max(10, n_questions))
        reason: Optional[str] = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            response = self.ai.generate_text(
                prompt if reason is None else prompt + prompts.repair_suffix(reason),
                user_id=user_id, request_type="questionnaire_review",
                system_instruction=prompts.SYSTEM_REVIEW, max_output_tokens=max_tokens,
                json_mode=True, max_prompt_chars=self.cfg.generation_max_prompt_chars,
            )
            if bool(response.finish_reason) and "MAX_TOKENS" in str(response.finish_reason).upper():
                raise AIResponseTruncatedError()
            try:
                return parse_review_reply(response.text), response.model
            except (AIInvalidJsonError, AIInvalidQuestionnaireError) as exc:
                if attempt == MAX_ATTEMPTS:
                    raise
                reason = exc.safe_message
        raise AIInvalidQuestionnaireError()  # pragma: no cover
