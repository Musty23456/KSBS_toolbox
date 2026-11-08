"""
TranslationService (AI translation) and HausaReviewer (AI review pass).

Both go through ``AIService.generate_text`` so validation, retries, error mapping and usage logging apply as for
every other AI feature. Neither touches the database: they take units and return results. The caller saves.

Nothing the model returns is trusted. A translation is accepted only if its id was one we asked for, it is
text, and it passes ``checks`` (placeholders kept, within length, not empty). Anything else is rejected with
the reason, and the person sees the original text for that item in the respondent form until it is fixed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from app.ai.errors import AIError, AIInvalidJsonError, AIInvalidQuestionnaireError, AIResponseTruncatedError
from app.ai.questionnaire import normalize
from app.ai.translation import checks, hausa, prompts
from app.ai.translation.languages import Language, get_language
from app.ai.translation.reconcile import UnitState
from app.ai.translation.units import Unit, UnitId

if TYPE_CHECKING:  # pragma: no cover
    from app.ai.service import AIService

logger = logging.getLogger("app.ai.translation")

MAX_BATCH_ITEMS = 30
MAX_BATCH_CHARS = 6000
ROUNDS = 2  # the first try, then one more for items whose answer broke a rule
REVIEW_MAX_UNITS = 120

# If the AI itself is unavailable there is no point trying the next batch.
_ITEM_LEVEL_CODES = {"AI_INVALID_JSON", "AI_INVALID_QUESTIONNAIRE", "AI_RESPONSE_TRUNCATED", "AI_CONTENT_BLOCKED", "AI_INVALID_RESPONSE"}


def make_batches(units: list[Unit], max_items: int = MAX_BATCH_ITEMS, max_chars: int = MAX_BATCH_CHARS) -> list[list[Unit]]:
    batches: list[list[Unit]] = []
    current: list[Unit] = []
    size = 0
    for unit in units:
        weight = len(unit.source) + len(unit.context[:300])
        if current and (len(current) >= max_items or size + weight > max_chars):
            batches.append(current)
            current, size = [], 0
        current.append(unit)
        size += weight
    if current:
        batches.append(current)
    return batches


def _truncated(response: Any) -> bool:
    return bool(response.finish_reason) and "MAX_TOKENS" in str(response.finish_reason).upper()


@dataclass
class TranslateResult:
    accepted: dict[UnitId, tuple[str, list[checks.Issue]]] = field(default_factory=dict)
    rejected: list[tuple[Unit, list[checks.Issue]]] = field(default_factory=list)
    not_returned: list[Unit] = field(default_factory=list)  # the AI skipped them, or their batch failed
    ai_error: Optional[str] = None
    model: str = ""
    calls: int = 0


class TranslationService:
    def __init__(self, ai: "AIService"):
        self.ai = ai
        self.cfg = ai.config

    # ------------------------------------------------------------------ public

    def translate(self, language_code: str, units: list[Unit], *, survey_title: str, user_id: Optional[str]) -> TranslateResult:
        language = get_language(language_code)
        if language is None:
            raise ValueError("unsupported language")
        result = TranslateResult()
        pending = list(units)
        notes: dict[UnitId, str] = {}  # why an earlier answer for a unit was refused (shown to the model on the retry)
        max_chars = max(1000, min(MAX_BATCH_CHARS, self.cfg.generation_max_prompt_chars // 3))

        def reject(items: list[Unit]) -> None:
            for unit in items:
                result.rejected.append((unit, [checks.Issue("BLOCK", "REJECTED", notes.get(unit.id, "Rejected."))]))

        for _round in range(ROUNDS):
            if not pending:
                break
            broke_a_rule: list[Unit] = []
            batches = make_batches(pending, max_chars=max_chars)
            for index, batch in enumerate(batches):
                try:
                    answers = self._ask_batch(language, batch, survey_title, user_id, notes, result)
                except AIError as exc:
                    result.ai_error = exc.safe_message
                    if exc.code in _ITEM_LEVEL_CODES:
                        logger.info("Translation batch skipped (%s)", exc.code)
                        result.not_returned.extend(batch)
                        continue
                    # The AI itself is unavailable (key, quota, network...): this batch and the rest are not done.
                    for rest in batches[index:]:
                        result.not_returned.extend(rest)
                    reject(broke_a_rule)
                    return result
                for unit in batch:
                    if unit.id not in answers:
                        result.not_returned.append(unit)
                        continue
                    text, issues = checks.safe_value(unit, answers[unit.id], language.code)
                    if text is None:
                        notes[unit.id] = "; ".join(i.message for i in issues if i.severity == "BLOCK")
                        broke_a_rule.append(unit)
                    else:
                        result.accepted[unit.id] = (text, [i for i in issues if i.severity == "WARN"])
            pending = broke_a_rule  # only answers that broke a rule are asked again
        reject(pending)  # still broken after the last round
        return result

    # ------------------------------------------------------------------ one batch

    def _ask_batch(self, language: Language, batch: list[Unit], survey_title: str, user_id: Optional[str],
                   notes: dict[UnitId, str], result: TranslateResult) -> dict[UnitId, str]:
        items = [(str(i + 1), unit) for i, unit in enumerate(batch)]
        by_item_id = {item_id: unit for item_id, unit in items}
        item_notes = {item_id: notes[unit.id] for item_id, unit in items if unit.id in notes}
        prompt = prompts.build_translate_prompt(language, items, survey_title, item_notes)
        chars = sum(len(u.source) for u in batch)
        max_tokens = min(self.cfg.generation_max_output_tokens, 1024 + 3 * chars + 60 * len(batch))

        reason: Optional[str] = None
        for attempt in (1, 2):
            response = self.ai.generate_text(
                prompt if reason is None else prompt + prompts.repair_suffix(reason),
                user_id=user_id, request_type="questionnaire_translation",
                system_instruction=prompts.SYSTEM_TRANSLATE, max_output_tokens=max_tokens, json_mode=True,
                max_prompt_chars=self.cfg.generation_max_prompt_chars,
            )
            result.calls += 1
            result.model = response.model or result.model
            if _truncated(response):
                if len(batch) > 1:  # the answer was cut off: ask for each half separately
                    middle = len(batch) // 2
                    merged = self._ask_batch(language, batch[:middle], survey_title, user_id, notes, result)
                    merged.update(self._ask_batch(language, batch[middle:], survey_title, user_id, notes, result))
                    return merged
                raise AIResponseTruncatedError()
            try:
                raw = parse_translations(response.text)
            except (AIInvalidJsonError, AIInvalidQuestionnaireError) as exc:
                if attempt == 2:
                    raise
                reason = exc.safe_message
                continue
            return {by_item_id[i].id: text for i, text in raw.items() if i in by_item_id}
        raise AIInvalidQuestionnaireError()  # pragma: no cover


def parse_translations(text: str) -> dict[str, str]:
    """{"translations": [{"id": "1", "text": "..."}]} -> {"1": "..."}. Malformed items are dropped."""
    raw = normalize.extract_json(text)
    items = raw.get("translations") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise AIInvalidQuestionnaireError("The AI response was not a list of translations.")
    out: dict[str, str] = {}
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("text"), str) and item.get("id") is not None:
            out[str(item["id"]).strip()] = item["text"]
    if not out:
        raise AIInvalidQuestionnaireError("The AI response contained no usable translations.")
    return out


# ====================================================================== Hausa review


@dataclass
class HausaReport:
    score: int
    grade: str
    summary: str
    findings: list[hausa.Finding]
    reviewed_units: int
    skipped_outdated: int
    skipped_reviewed_by_ai: int
    ai_used: bool
    ai_units: int
    ai_error: Optional[str]
    model: str
    limitations: list[str]


class HausaReviewer:
    def __init__(self, ai: "AIService"):
        self.ai = ai
        self.cfg = ai.config

    def review(self, states: list[UnitState], *, survey_title: str, use_ai: bool, user_id: Optional[str]) -> HausaReport:
        reviewed = [st for st in states if st.row is not None and st.status != "OUTDATED"]
        findings = hausa.review_rules(states)
        skipped_outdated = sum(1 for st in states if st.status == "OUTDATED")

        ai_used, ai_error, model, ai_summary, ai_units = False, None, "", "", 0
        # People already signed these off, so the AI pass spends its effort on the rest.
        candidates = [st for st in reviewed if st.status != "REVIEWED"][:REVIEW_MAX_UNITS]
        skipped_reviewed = sum(1 for st in reviewed if st.status == "REVIEWED")
        if use_ai and candidates:
            try:
                extra, model, ai_summary = self._ai_pass(candidates, survey_title, user_id)
                findings += extra
                ai_used, ai_units = True, len(candidates)
            except AIError as exc:
                ai_error = exc.safe_message
                logger.info("Hausa AI review skipped (%s)", exc.code)
        elif not use_ai:
            ai_error = "AI review was switched off for this review."

        findings = _dedupe(hausa.sort_findings(findings))
        value = hausa.score(findings, len(reviewed))
        warnings = sum(1 for f in findings if f.severity == "WARNING")
        summary = (f"Hausa quality score {value}/100 ({hausa.grade_for(value)}): {warnings} warning(s) and "
                   f"{len(findings) - warnings} suggestion(s) across {len(reviewed)} translated item(s).")
        if not reviewed:
            summary = "There is no up-to-date Hausa translation to review yet."
        if ai_summary:
            summary += " " + ai_summary

        limitations = ["This is an automatic check, not a native-speaker review. Have a Hausa speaker read the final text before the survey is used in the field."]
        if not ai_used:
            limitations.append("Only the built-in rule checks ran. Accuracy, natural phrasing and register need the AI pass.")
        if len(reviewed) - skipped_reviewed > REVIEW_MAX_UNITS and use_ai:
            limitations.append(f"The AI pass reads at most {REVIEW_MAX_UNITS} items per review. Run it again after fixing these to check the rest.")
        if skipped_outdated:
            limitations.append(f"{skipped_outdated} item(s) were skipped because the English text changed after they were translated.")
        return HausaReport(
            score=value, grade=hausa.grade_for(value), summary=summary, findings=findings, reviewed_units=len(reviewed),
            skipped_outdated=skipped_outdated, skipped_reviewed_by_ai=skipped_reviewed, ai_used=ai_used, ai_units=ai_units,
            ai_error=ai_error, model=model, limitations=limitations,
        )

    # ------------------------------------------------------------------ AI pass

    def _ai_pass(self, candidates: list[UnitState], survey_title: str, user_id: Optional[str]) -> tuple[list[hausa.Finding], str, str]:
        findings: list[hausa.Finding] = []
        model, summary = "", ""
        max_chars = max(1000, min(MAX_BATCH_CHARS, self.cfg.generation_max_prompt_chars // 3))
        by_unit = {st.unit.id: st for st in candidates}
        for batch in make_batches([st.unit for st in candidates], max_chars=max_chars):
            items = [(str(i + 1), by_unit[u.id].unit, by_unit[u.id].row["value"]) for i, u in enumerate(batch)]
            lookup = {item_id: by_unit[unit.id] for item_id, unit, _ in items}
            prompt = prompts.build_hausa_review_prompt(items, survey_title)
            max_tokens = min(self.cfg.generation_max_output_tokens, 2048 + 120 * len(batch))
            reason: Optional[str] = None
            for attempt in (1, 2):
                response = self.ai.generate_text(
                    prompt if reason is None else prompt + prompts.repair_suffix(reason),
                    user_id=user_id, request_type="hausa_review", system_instruction=prompts.SYSTEM_HAUSA_REVIEW,
                    max_output_tokens=max_tokens, json_mode=True, max_prompt_chars=self.cfg.generation_max_prompt_chars,
                )
                model = response.model
                if _truncated(response):
                    raise AIResponseTruncatedError()
                try:
                    raw = normalize.extract_json(response.text)
                    if not isinstance(raw, dict) or not isinstance(raw.get("findings", []), list):
                        raise AIInvalidQuestionnaireError("The AI review had the wrong structure.")
                except (AIInvalidJsonError, AIInvalidQuestionnaireError) as exc:
                    if attempt == 2:
                        raise
                    reason = exc.safe_message
                    continue
                findings += accept_ai_findings(raw.get("findings", []), lookup)
                if not summary and isinstance(raw.get("summary"), str):
                    summary = normalize.clean_text(raw["summary"], 300) or ""
                break
        return findings, model, summary


def accept_ai_findings(raw_findings: list[Any], lookup: dict[str, UnitState]) -> list[hausa.Finding]:
    """Keep only well-formed findings about items we asked about. A suggested text must pass the same checks."""
    out: list[hausa.Finding] = []
    for raw in raw_findings:
        if not isinstance(raw, dict):
            continue
        st = lookup.get(str(raw.get("id", "")).strip())
        severity = str(raw.get("severity", "")).strip().upper()
        category = str(raw.get("category", "")).strip().upper()
        message = normalize.clean_text(raw.get("message"), 300)
        if st is None or severity not in hausa.SEVERITIES or category not in hausa.CATEGORIES or not message:
            continue
        suggestion = None
        if isinstance(raw.get("suggestion"), str) and raw["suggestion"].strip():
            cleaned, _issues = checks.safe_value(st.unit, raw["suggestion"], "ha")
            if cleaned is not None and cleaned != st.row["value"]:
                suggestion = cleaned
        u = st.unit
        out.append(hausa.Finding(u.entity_type, u.entity_key, u.field, u.label, severity, category, message, suggestion, "AI"))
    return out


def _dedupe(findings: list[hausa.Finding]) -> list[hausa.Finding]:
    seen: set[tuple] = set()
    out = []
    for f in findings:
        key = (f.unit_id, f.category, f.message.lower())
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out
