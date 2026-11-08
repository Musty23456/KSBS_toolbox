"""
Deterministic quality checks. No AI, no database: the same questionnaire always gives the same findings.

Two sources feed the report:
* the Phase 3 engine's own validity rules (``validate_state``) - these are CRITICAL because the questionnaire
  would be rejected or misbehave on save/collection;
* heuristics for common survey-design problems (wording, bias, types, choices, consistency, required fields...).

Heuristics are written for English wording; they never claim certainty ("may", "consider"), and the AI pass
covers other languages and subtler problems. A finding may carry a ``fix`` (a Phase 3 edit operation). Fixes are
only proposals - ``fixes.verify_fixes`` checks each against the questionnaire before the person ever sees it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from app.ai.questionnaire.normalize import CHOICE_TYPES, NUMERIC_TYPES, TEXT_TYPES
from app.ai.questionnaire_edit.engine import referenced_names, validate_state
from app.ai.questionnaire_edit.prompts import find_possible_duplicates
from app.ai.questionnaire_edit.snapshot import Snapshot, WorkingState, WQuestion
from app.ai.questionnaire_review.schemas import CoverageItem, Finding, ReviewStats, finding_id

# --------------------------------------------------------------------------- helpers


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+(?:'[^\W_]+)?", text or "", flags=re.UNICODE)


def _norm(text: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _short(text: Optional[str], n: int = 140) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def make_finding(
    severity: str,
    category: str,
    title: str,
    explanation: str,
    recommendation: str,
    q: Optional[WQuestion] = None,
    fix: Optional[dict[str, Any]] = None,
    fix_summary: Optional[str] = None,
    source: str = "RULE",
    code: Optional[str] = None,
) -> Finding:
    qcode = code if code is not None else (q.code if q is not None and q.code else None)
    return Finding(
        id=finding_id(category, qcode, title),
        severity=severity,  # type: ignore[arg-type]
        category=category,  # type: ignore[arg-type]
        question_code=qcode,
        question_label=_short(q.f.get("label")) if q is not None else None,
        title=title,
        explanation=explanation,
        recommendation=recommendation,
        fix=fix if fix and qcode or (fix and fix.get("op") in ("DELETE_SECTION",)) else None,
        fix_summary=fix_summary if fix else None,
        source=source,  # type: ignore[arg-type]
    )


def _update_question(code: str, **changes: Any) -> dict[str, Any]:
    return {"op": "UPDATE_QUESTION", "code": code, "changes": changes}


def _set_required(code: str, value: bool) -> dict[str, Any]:
    return {"op": "UPDATE_VALIDATION", "code": code, "validation": {"is_required": value}}


# --------------------------------------------------------------------------- wording

_LEADING = re.compile(
    r"\b(don'?t you (agree|think|believe)|do you (not )?(agree|think) that|wouldn'?t you|isn'?t it|aren'?t you|"
    r"surely|obviously|clearly|everyone knows|of course|as you know|it is well known|how (great|terrible|awful|wonderful)|"
    r"you must|you should|unfortunately|would you agree|"
    r"(excellent|terrible|awful|wonderful|amazing|horrible|outstanding|useless) (service|program|programme|policy|government|product))\b",
    re.IGNORECASE,
)
_LOADED = re.compile(r"\b(failed|corrupt|useless|incompetent|brilliant|heroic|shameful|disgraceful)\b", re.IGNORECASE)
_VAGUE = re.compile(
    r"\b(often|regularly|frequently|recently|sometimes|usually|occasionally|lately|a lot|(?<!how )many|few|several|soon|"
    r"in general|typically|normally)\b",
    re.IGNORECASE,
)
_TIMEFRAME = re.compile(r"\b(week|weeks|month|months|year|years|day|days|last|past|during|since|between|per|each)\b|\d", re.IGNORECASE)
_ABSOLUTE = re.compile(r"\b(always|never|everyone|nobody|everything|nothing|every time)\b", re.IGNORECASE)
_OPINION = re.compile(r"\b(satisfied|happy|agree|trust|like|useful|helpful|easy|rate|good|safe|affordable)\b", re.IGNORECASE)
_QUESTION_START = re.compile(
    r"^(what|which|who|whom|whose|when|where|why|how|do|does|did|is|are|was|were|have|has|had|can|could|will|would|should)\b",
    re.IGNORECASE,
)
_GENERIC_SECTION = re.compile(r"^(section|part|page|untitled|new section|group)\s*\d*$", re.IGNORECASE)
_SENSITIVE = re.compile(
    r"\b(income|salary|wage|religio\w*|ethnic\w*|tribe|hiv|aids|pregnan\w*|sexual\w*|political|vote|voting|disabilit\w*|"
    r"abuse|violence|criminal|arrest\w*|immigration|bank account|bvn|national id|nin|mental health|rape|assault)\b",
    re.IGNORECASE,
)
_REPEATED_WORD_OK = {"had", "that", "is", "do"}


def mechanical_fix(text: str) -> str:
    """Safe, mechanical wording clean-up only (spacing, capital letter, repeated word, '?'). Never rewords."""
    t = re.sub(r"\s+", " ", text or "").strip()
    t = re.sub(r"\s+([?!.,;:])", r"\1", t)
    t = re.sub(r"\?{2,}", "?", t)

    def _dedupe(m: re.Match) -> str:
        return m.group(0) if m.group(1).lower() in _REPEATED_WORD_OK else m.group(1)

    t = re.sub(r"\b([^\W\d_]{2,})(?:\s+\1\b)+", _dedupe, t, flags=re.IGNORECASE | re.UNICODE)
    t = re.sub(r"\bi (am|have|was|will|do|think|live|work)\b", r"I \1", t)
    if t and t[0].islower():
        t = t[0].upper() + t[1:]
    if t and _QUESTION_START.match(t) and t[-1] not in "?:)":
        t = (t[:-1] if t[-1] in ".!" else t) + "?"
    return t


def _wording_checks(q: WQuestion, out: list[Finding]) -> None:
    f = q.f
    label = (f.get("label") or "").strip()
    if not label:
        return
    words = _words(label)
    qtype = q.type

    if _LEADING.search(label) or _LOADED.search(label):
        out.append(make_finding(
            "WARNING", "BIAS", "Possible leading or loaded wording",
            "The wording pushes the respondent toward an answer or carries an opinion, which can bias results.",
            "Rewrite it neutrally so every answer feels equally acceptable, e.g. “How satisfied or dissatisfied are you with …?”.", q))

    if _has(r"\b(and|or)\b", label) and _OPINION.search(label) and len(words) >= 8 and qtype not in ("MULTIPLE_CHOICE",):
        out.append(make_finding(
            "SUGGESTION", "AMBIGUITY", "May ask about two things at once",
            "The question joins two ideas with “and/or”; a respondent who feels differently about each cannot answer accurately.",
            "Split it into separate questions, one idea each.", q))

    if _VAGUE.search(label) and not _TIMEFRAME.search(label) and qtype not in ("MULTIPLE_CHOICE",):
        word = _VAGUE.search(label).group(0)  # type: ignore[union-attr]
        out.append(make_finding(
            "SUGGESTION", "AMBIGUITY", f"Vague term “{word.lower()}” with no time frame",
            "Words like this mean different things to different people, so answers cannot be compared.",
            "State a period or quantity, e.g. “in the last 30 days” or “how many times”.", q))

    if _ABSOLUTE.search(label) and qtype in ("YES_NO", "SINGLE_CHOICE"):
        out.append(make_finding(
            "SUGGESTION", "AMBIGUITY", "Absolute wording (always / never / everyone)",
            "Absolutes are almost never literally true, so respondents hesitate or answer inaccurately.",
            "Use a frequency scale or a softer phrase.", q))

    if len(words) >= 45 or len(label) > 300:
        out.append(make_finding(
            "WARNING", "CLARITY", f"Question is very long ({len(words)} words)",
            "Long questions are hard to read aloud and understand, especially in face-to-face interviews.",
            "Shorten it, and move background detail into the hint.", q))
    elif len(words) <= 2 and not (f.get("hint") or "").strip() and qtype not in ("GPS", "PHOTO", "AUDIO", "SIGNATURE", "BARCODE"):
        out.append(make_finding(
            "SUGGESTION", "CLARITY", "Very short question with no hint",
            "A one or two word prompt may not tell the respondent or enumerator exactly what is wanted.",
            "Write it as a full question or add a hint (for example the expected format).", q))

    letters = [c for c in label if c.isalpha()]
    if len(letters) >= 8 and all(c.isupper() for c in letters):
        out.append(make_finding(
            "SUGGESTION", "GRAMMAR", "Question is written in capital letters",
            "All-capitals text is harder to read and can feel like shouting.",
            "Use normal sentence case.", q,
            fix=_update_question(q.code, label=label.capitalize()) if q.code else None,
            fix_summary="Convert the question text to sentence case"))
    else:
        fixed = mechanical_fix(label)
        if fixed != label:
            out.append(make_finding(
                "SUGGESTION", "GRAMMAR", "Spelling/punctuation clean-up available",
                f"Spacing, capitalisation, a repeated word or missing question mark. Suggested text: “{_short(fixed)}”.",
                "Use the corrected wording.", q,
                fix=_update_question(q.code, label=fixed) if q.code else None,
                fix_summary="Fix spacing, capital letter, repeated words and question mark"))


# --------------------------------------------------------------------------- types

_NUMBERISH = re.compile(r"\b(age|how old|how many|number of|how much|quantity|amount|income|salary|weight|height|distance|hours|days per)\b", re.IGNORECASE)
_INTEGERISH = re.compile(r"\b(age|how old|how many|number of|hours|days per)\b", re.IGNORECASE)
_DATEISH = re.compile(r"\b(date of birth|birth ?date|dob|what date|which date|when did|date of)\b", re.IGNORECASE)
_YESNOISH = re.compile(r"^(do|does|did|is|are|was|were|have|has|can|will|would|should)\b", re.IGNORECASE)
_NOT_YESNO = re.compile(r"\b(why|how|what|which|describe|explain|specify|where|when|who|name)\b", re.IGNORECASE)
_MULTI_HINT = re.compile(r"\b(select all|tick all|check all|all that apply|all of the following that|more than one|multiple answers)\b", re.IGNORECASE)
_SINGLE_HINT = re.compile(r"\b(main|primary|most important|best describes|one only|only one|single most)\b", re.IGNORECASE)
_SHORT_ANSWER = re.compile(r"\b(name|phone|telephone|mobile|email|e-mail|village|town|city|state|lga|ward|occupation)\b", re.IGNORECASE)


def _type_checks(q: WQuestion, out: list[Finding]) -> None:
    f = q.f
    label = (f.get("label") or "")
    qtype = q.type
    code = q.code
    choices = f.get("choices") or []

    if qtype in TEXT_TYPES:
        if _DATEISH.search(label):
            out.append(make_finding(
                "WARNING", "QUESTION_TYPE", "A date is collected as free text",
                "Typed dates come back in many formats and cannot be validated or analysed reliably.",
                "Use a Date question.", q, fix=_update_question(code, type="DATE") if code else None,
                fix_summary="Change the type to Date"))
        elif _NUMBERISH.search(label):
            integer = bool(_INTEGERISH.search(label))
            new_type = "INTEGER" if integer else "DECIMAL"
            out.append(make_finding(
                "WARNING", "QUESTION_TYPE", "A number is collected as free text",
                "Text answers such as “about 30” or “thirty” cannot be validated or summed.",
                f"Use a {'whole-number' if integer else 'decimal'} question.", q,
                fix=_update_question(code, type=new_type) if code else None,
                fix_summary=f"Change the type to {'Integer' if integer else 'Decimal'}"))
        elif _YESNOISH.match(label.strip()) and not _NOT_YESNO.search(label):
            out.append(make_finding(
                "SUGGESTION", "QUESTION_TYPE", "A yes/no question uses a text answer",
                "Free text invites inconsistent answers (“yes”, “Y”, “yeah”).",
                "Use a Yes/No question.", q, fix=_update_question(code, type="YES_NO") if code else None,
                fix_summary="Change the type to Yes/No"))

    if qtype == "LONG_TEXT" and _SHORT_ANSWER.search(label) and len(_words(label)) <= 8:
        out.append(make_finding(
            "SUGGESTION", "QUESTION_TYPE", "Long-text box for a short answer",
            "A short answer fits a single-line field, which is quicker to fill in and tidier to export.",
            "Use Short text.", q, fix=_update_question(code, type="SHORT_TEXT") if code else None,
            fix_summary="Change the type to Short text"))

    if qtype in ("SINGLE_CHOICE", "DROPDOWN") and _MULTI_HINT.search(label):
        out.append(make_finding(
            "WARNING", "QUESTION_TYPE", "Asks for several answers but allows only one",
            "The wording says to select all that apply, but this question type accepts a single answer.",
            "Change it to Multiple choice.", q, fix=_update_question(code, type="MULTIPLE_CHOICE") if code else None,
            fix_summary="Change the type to Multiple choice"))
    if qtype == "MULTIPLE_CHOICE" and _SINGLE_HINT.search(label) and not _MULTI_HINT.search(label):
        out.append(make_finding(
            "WARNING", "QUESTION_TYPE", "Asks for one answer but allows several",
            "Words such as “main” or “most important” call for exactly one answer.",
            "Change it to Single choice.", q, fix=_update_question(code, type="SINGLE_CHOICE") if code else None,
            fix_summary="Change the type to Single choice"))

    if qtype in ("SINGLE_CHOICE", "DROPDOWN") and len(choices) == 2 and {_norm(c.get("label")) for c in choices} == {"yes", "no"}:
        out.append(make_finding(
            "SUGGESTION", "QUESTION_TYPE", "Yes/No written as a choice list",
            "A built-in Yes/No question keeps answer values consistent (YES/NO) across the questionnaire.",
            "Use a Yes/No question.", q, fix=_update_question(code, type="YES_NO") if code else None,
            fix_summary="Change the type to Yes/No"))

    # validation gaps
    if qtype in NUMERIC_TYPES and f.get("min_value") is None and f.get("max_value") is None and _has(r"\b(age|how old)\b", label) and code:
        out.append(make_finding(
            "SUGGESTION", "VALIDATION", "Age has no allowed range",
            "Without limits, typing errors such as 250 or -3 are accepted.",
            "Limit age to a realistic range such as 0 to 120.", q,
            fix={"op": "UPDATE_VALIDATION", "code": code, "validation": {"min_value": 0, "max_value": 120}},
            fix_summary="Set the allowed range to 0–120"))
    if qtype in TEXT_TYPES and not f.get("regex_pattern") and _has(r"\b(phone|telephone|mobile|e-?mail)\b", label):
        out.append(make_finding(
            "SUGGESTION", "VALIDATION", "Phone/email has no format rule",
            "Without a format rule, mistyped contact details are accepted.",
            "Add a format rule (and a length limit) in the question's validation settings.", q))


# --------------------------------------------------------------------------- choices

_RANGE = re.compile(r"^\s*(\d+)\s*(?:-|–|—|to)\s*(\d+)\s*(?:[a-z%]+)?\s*$", re.IGNORECASE)
_ESCAPE = re.compile(r"\b(other|none|don'?t know|do not know|not applicable|n/?a|prefer not|no answer|refuse|not sure)\b", re.IGNORECASE)
_SCALE_WORD = re.compile(r"\b(agree|disagree|satisfied|dissatisfied|likely|unlikely|often|never|always|good|poor|excellent|very|neutral|important|rarely)\b", re.IGNORECASE)


def _choice_checks(q: WQuestion, out: list[Finding]) -> None:
    choices = q.f.get("choices") or []
    if q.type not in CHOICE_TYPES or not choices:
        return
    code = q.code

    seen: dict[str, str] = {}
    for c in choices:
        key = _norm(c.get("label"))
        if not key:
            continue
        if key in seen and code:
            out.append(make_finding(
                "WARNING", "CHOICES", f"Two answer options read “{_short(c.get('label'), 40)}”",
                "Identical option texts with different values split the same answer between two codes.",
                "Remove one of them.", q,
                fix={"op": "UPDATE_CHOICES", "code": code, "mode": "REMOVE", "remove_values": [c.get("value")]},
                fix_summary=f"Remove the duplicate option “{_short(c.get('label'), 40)}”"))
        else:
            seen[key] = c.get("value", "")

    ranges = []
    for c in choices:
        m = _RANGE.match(c.get("label") or "")
        if m:
            ranges.append((int(m.group(1)), int(m.group(2)), c.get("label") or ""))
    if len(ranges) >= 2 and len(ranges) >= len(choices) - 2:
        ranges.sort()
        for (lo1, hi1, l1), (lo2, hi2, l2) in zip(ranges, ranges[1:]):
            if lo2 <= hi1:
                out.append(make_finding(
                    "WARNING", "CHOICES", f"Overlapping ranges “{_short(l1, 20)}” and “{_short(l2, 20)}”",
                    "A respondent on the boundary fits two options, so the answer is ambiguous.",
                    "Make the ranges mutually exclusive (for example 18–25 and 26–35).", q))
                break
            if lo2 > hi1 + 1:
                out.append(make_finding(
                    "WARNING", "CHOICES", f"Gap between “{_short(l1, 20)}” and “{_short(l2, 20)}”",
                    "Values between the two ranges have no matching option.",
                    "Close the gap so every possible answer has an option.", q))
                break

    if q.type == "SINGLE_CHOICE" and len(choices) > 12:
        out.append(make_finding(
            "SUGGESTION", "CHOICES", f"{len(choices)} options in a single-choice list",
            "Long radio-button lists are tiring on a phone screen.",
            "Use a Dropdown, or group the options.", q,
            fix=_update_question(code, type="DROPDOWN") if code else None, fix_summary="Change the type to Dropdown"))

    labels = " ".join(c.get("label") or "" for c in choices)
    is_scale = bool(_SCALE_WORD.search(labels)) or sum(1 for c in choices if re.search(r"\d", c.get("label") or "")) >= len(choices) - 1
    if len(choices) >= 3 and not is_scale and not _ESCAPE.search(labels) and code:
        out.append(make_finding(
            "SUGGESTION", "CHOICES", "No “Other” / “Don't know” option",
            "If none of the options fits, respondents pick something wrong or abandon the question.",
            "Add an “Other” option (and a follow-up text question if you need the detail).", q,
            fix={"op": "UPDATE_CHOICES", "code": code, "mode": "ADD", "choices": [{"value": "OTHER", "label": "Other"}]},
            fix_summary="Add an “Other” option"))


def _consistency_checks(state: WorkingState, out: list[Finding]) -> None:
    items = []
    for q in state.questions:
        if q.type in CHOICE_TYPES and len(q.f.get("choices") or []) >= 3 and q.code:
            labels = [_norm(c.get("label")) for c in q.f["choices"]]
            items.append((q, labels, set(labels)))
    reported = 0
    for i, (qa, la, sa) in enumerate(items):
        for qb, lb, sb in items[i + 1:]:
            if reported >= 6:
                return
            union = sa | sb
            inter = sa & sb
            if not union or len(inter) < 3:
                continue
            if sa == sb and la != lb:
                out.append(make_finding(
                    "SUGGESTION", "CONSISTENCY", f"Same options in a different order as “{qa.code}”",
                    "Reordering the same scale between questions causes accidental wrong answers.",
                    "Keep the option order the same in both questions.", qb))
                reported += 1
            elif sa != sb and len(inter) / len(union) >= 0.6:
                diff = sorted((sa ^ sb) - {""})[:4]
                out.append(make_finding(
                    "SUGGESTION", "CONSISTENCY", f"Options differ slightly from “{qa.code}”",
                    f"These two questions use almost the same answer list but differ ({', '.join(diff)}); results cannot be compared directly.",
                    "Use one identical option list for both questions.", qb))
                reported += 1

    by_label: dict[str, dict[str, list[str]]] = {}
    for q in state.questions:
        if q.type in CHOICE_TYPES and q.code:
            for c in q.f.get("choices") or []:
                by_label.setdefault(_norm(c.get("label")), {}).setdefault(c.get("value", ""), []).append(q.code)
    n = 0
    for label, values in by_label.items():
        if label and len(values) > 1 and sum(len(v) for v in values.values()) >= 2 and n < 4:
            codes = sorted({c for v in values.values() for c in v})
            out.append(make_finding(
                "SUGGESTION", "CONSISTENCY", f"“{label[:40]}” is coded differently across questions",
                f"The same answer text uses different stored values ({', '.join(sorted(values))}) in {', '.join(codes[:4])}; analysis needs recoding.",
                "Use one value for the same answer everywhere.", None, code=codes[0]))
            n += 1


# --------------------------------------------------------------------------- required / skip logic / structure


def _required_checks(state: WorkingState, out: list[Finding]) -> None:
    qs = state.questions
    if qs and not any(q.f.get("is_required") for q in qs):
        out.append(make_finding(
            "WARNING", "REQUIRED", "No question is marked required",
            "Respondents can skip every question, leaving gaps in the key variables.",
            "Mark the questions you cannot analyse without as required.", None))
    for q in qs:
        label = q.f.get("label") or ""
        if q.code and _has(r"\b(consent|agree to participate|willing to participate|permission to (record|participate))\b", label) \
                and q.type in ("YES_NO",) + tuple(CHOICE_TYPES) and not q.f.get("is_required"):
            out.append(make_finding(
                "WARNING", "REQUIRED", "Consent question is not required",
                "Collection should not continue unless consent is explicitly answered.",
                "Make the consent question required.", q, fix=_set_required(q.code, True), fix_summary="Make this question required"))
        if q.f.get("is_required") and _SENSITIVE.search(label):
            out.append(make_finding(
                "SUGGESTION", "REQUIRED", "Sensitive question is compulsory",
                "Forcing an answer on a sensitive topic raises refusals and dishonest answers.",
                "Make it optional, or add a “Prefer not to say” option.", q,
                fix=_set_required(q.code, False) if q.code else None, fix_summary="Make this question optional"))


def _skip_logic_checks(state: WorkingState, out: list[Finding]) -> None:
    by_code = {q.code: q for q in state.questions if q.code}
    driven: dict[str, list[str]] = {}
    for q in state.questions:
        expr = q.f.get("relevance_expression")
        if expr and expr.strip():
            for name in referenced_names(expr):
                driven.setdefault(name, []).append(q.code or "?")
    for name, dependants in driven.items():
        src = by_code.get(name)
        if src is not None and not src.f.get("is_required"):
            out.append(make_finding(
                "SUGGESTION", "SKIP_LOGIC", "Question controlling skip logic is optional",
                f"If “{name}” is left blank, the questions that depend on it ({', '.join(dependants[:4])}) may be wrongly hidden or shown.",
                "Make the controlling question required.", src,
                fix=_set_required(src.code, True) if src.code else None, fix_summary="Make this question required"))


def _structure_checks(state: WorkingState, out: list[Finding]) -> None:
    n = len(state.questions)
    if n == 0:
        out.append(make_finding("CRITICAL", "STRUCTURE", "The questionnaire has no questions",
                                "There is nothing to review or to collect.", "Add questions before collecting data.", None))
        return
    for i, s in enumerate(state.sections, start=1):
        in_section = state.questions_in(s)
        if not in_section and len(state.sections) > 1:
            out.append(make_finding(
                "WARNING", "STRUCTURE", f"Section “{_short(s.title, 50)}” has no questions",
                "An empty section shows nothing to the respondent and clutters the form.",
                "Add questions to it or remove it.", None, code=f"S{i}",
                fix={"op": "DELETE_SECTION", "section_ref": f"S{i}", "questions": "MOVE"}, fix_summary="Remove the empty section"))
        if _GENERIC_SECTION.match((s.title or "").strip()) and len(state.sections) > 1:
            out.append(make_finding(
                "SUGGESTION", "STRUCTURE", f"Section title “{_short(s.title, 30)}” is generic",
                "Descriptive titles help respondents and enumerators know where they are.",
                "Name the section after its topic, e.g. “Household income”.", None, code=f"S{i}"))
        if len(in_section) > 25:
            out.append(make_finding(
                "SUGGESTION", "STRUCTURE", f"Section “{_short(s.title, 40)}” has {len(in_section)} questions",
                "Very long sections are hard to navigate and tiring.", "Split it into smaller topical sections.", None, code=f"S{i}"))
    if n > 50:
        out.append(make_finding(
            "SUGGESTION", "STRUCTURE", f"The questionnaire is long ({n} questions)",
            "Long surveys increase fatigue and drop-out; later answers are less reliable.",
            "Remove questions that do not serve a stated objective.", None))
    first = state.questions[0]
    if _SENSITIVE.search(first.f.get("label") or "") and n >= 5:
        out.append(make_finding(
            "SUGGESTION", "STRUCTURE", "The questionnaire opens with a sensitive question",
            "Starting with sensitive topics lowers trust and completion.",
            "Open with easy, neutral questions and place sensitive ones later.", first))


# --------------------------------------------------------------------------- engine validity -> findings

_RULE_CATEGORY = {
    "code_duplicate": "STRUCTURE", "code_too_long": "STRUCTURE", "label_empty": "CLARITY",
    "choices_required": "CHOICES", "choices_not_allowed": "CHOICES", "choice_blank": "CHOICES",
    "choice_duplicate": "CHOICES", "choice_too_long": "CHOICES", "rule_not_applicable": "VALIDATION",
    "range_invalid": "VALIDATION", "regex_invalid": "VALIDATION", "default_too_long": "VALIDATION",
    "expression": "SKIP_LOGIC", "section_title_empty": "STRUCTURE",
}
_RULE_TITLE = {
    "code_duplicate": "Duplicate question code", "code_too_long": "Question code too long", "label_empty": "Question has no text",
    "choices_required": "Choice question has fewer than two options", "choices_not_allowed": "Options on a question type that cannot have them",
    "choice_blank": "Answer option is blank", "choice_duplicate": "Duplicate answer option value", "choice_too_long": "Answer option too long",
    "rule_not_applicable": "Validation rule does not fit the question type", "range_invalid": "Invalid minimum/maximum",
    "regex_invalid": "Unusable format rule", "default_too_long": "Default value too long", "expression": "Invalid skip logic",
    "section_title_empty": "Section has no title",
}


def _engine_findings(state: WorkingState, out: list[Finding]) -> None:
    by_code = {q.code: q for q in state.questions if q.code}
    for issue in validate_state(state):
        q = by_code.get(issue.target[2:]) if issue.target.startswith("q:") else None
        tail = {
            "expression": "Fix or remove the skip logic: it may only use earlier questions and real answer values.",
            "choices_required": "Add at least two answer options, or change the question type.",
        }.get(issue.rule, "Correct this before saving or collecting data.")
        out.append(make_finding("CRITICAL", _RULE_CATEGORY.get(issue.rule, "STRUCTURE"), _RULE_TITLE.get(issue.rule, "Invalid setting"),
                                issue.message, tail, q, code=(q.code if q else None) or (issue.target[2:] if issue.target.startswith("q:#") else None) or None))


# --------------------------------------------------------------------------- duplicates


def _duplicate_checks(state: WorkingState, out: list[Finding]) -> None:
    by_code = {q.code: q for q in state.questions}
    for cluster in find_possible_duplicates(state):
        first = by_code[cluster[0]]
        for other_code in cluster[1:]:
            other = by_code[other_code]
            same = _norm(first.f.get("label")) == _norm(other.f.get("label"))
            out.append(make_finding(
                "WARNING", "DUPLICATE",
                f"{'Repeats' if same else 'Nearly repeats'} “{first.code}”",
                f"The wording is {'identical' if same else 'almost identical'} to “{_short(first.f.get('label'), 80)}”; respondents will be asked the same thing twice.",
                "Delete the later copy (or reword it if it really asks something different).", other,
                fix={"op": "DELETE_QUESTION", "code": other.code}, fix_summary=f"Delete the repeated question “{other.code}”"))


# --------------------------------------------------------------------------- good practices


def _good_practices(state: WorkingState, findings: list[Finding], out: list[Finding]) -> None:
    qs = state.questions
    n = len(qs)
    if n == 0:
        return
    cats = {f.category for f in findings if f.severity in ("CRITICAL", "WARNING")}
    cat_any = {f.category for f in findings if f.severity != "GOOD"}

    def good(title: str, why: str) -> None:
        out.append(make_finding("GOOD", "STRUCTURE", title, why, "Keep doing this.", None, code=None))

    def good_cat(cat: str, title: str, why: str) -> None:
        out.append(make_finding("GOOD", cat, title, why, "Keep doing this.", None))

    if len(state.sections) > 1 and not any(f.title.endswith("has no questions") for f in findings):
        good("Questions are organised into sections", f"{len(state.sections)} sections group related questions, which helps respondents follow the flow.")
    if sum(1 for q in qs if (q.f.get("hint") or "").strip()) / n >= 0.3:
        good_cat("CLARITY", "Helpful hints on many questions", "Hints reduce misunderstanding, especially for enumerators.")
    if n >= 5 and "DUPLICATE" not in cat_any:
        good_cat("DUPLICATE", "No repeated questions", "Every question asks something different.")
    if n >= 5 and "BIAS" not in cat_any:
        good_cat("BIAS", "Neutral wording", "No leading or loaded wording was detected.")
    if any(q.type in CHOICE_TYPES for q in qs) and "CHOICES" not in cats:
        good_cat("CHOICES", "Answer options are complete and well formed", "Every choice question has valid, distinct options.")
    if any((q.f.get("relevance_expression") or "").strip() for q in qs) and "SKIP_LOGIC" not in cats:
        good_cat("SKIP_LOGIC", "Skip logic is valid", "Every skip rule refers to earlier questions and real answer values.")
    typed = [q for q in qs if q.type in NUMERIC_TYPES or q.type in ("DATE", "YES_NO", "GPS", "PHOTO")]
    if len(typed) >= 2 and "QUESTION_TYPE" not in cats:
        good_cat("QUESTION_TYPE", "Specific question types used", "Numbers, dates and yes/no answers use dedicated types, which keeps the data clean.")
    num = [q for q in qs if q.type in NUMERIC_TYPES]
    if num and all(q.f.get("min_value") is not None or q.f.get("max_value") is not None for q in num):
        good_cat("VALIDATION", "Numeric answers have allowed ranges", "Range limits catch typing errors at the point of entry.")
    if any(q.f.get("is_required") for q in qs) and "REQUIRED" not in cats:
        good_cat("REQUIRED", "Key questions are marked required", "Essential data is protected from being skipped.")


# --------------------------------------------------------------------------- public API


@dataclass
class RuleResult:
    findings: list[Finding]
    stats: ReviewStats
    state: WorkingState


def compute_stats(state: WorkingState) -> ReviewStats:
    qs = state.questions
    return ReviewStats(
        questions=len(qs),
        sections=len(state.sections),
        required_questions=sum(1 for q in qs if q.f.get("is_required")),
        questions_with_hints=sum(1 for q in qs if (q.f.get("hint") or "").strip()),
        choice_questions=sum(1 for q in qs if q.type in CHOICE_TYPES),
        questions_with_skip_logic=sum(1 for q in qs if (q.f.get("relevance_expression") or "").strip()),
    )


def dedupe(findings: Iterable[Finding]) -> list[Finding]:
    seen: set[str] = set()
    out: list[Finding] = []
    for f in findings:
        if f.id in seen:
            continue
        seen.add(f.id)
        out.append(f)
    return out


def run_rules(snapshot: Snapshot) -> RuleResult:
    state = WorkingState.from_snapshot(snapshot)
    found: list[Finding] = []
    _engine_findings(state, found)
    _structure_checks(state, found)
    for q in state.questions:
        _wording_checks(q, found)
        _type_checks(q, found)
        _choice_checks(q, found)
    _duplicate_checks(state, found)
    _consistency_checks(state, found)
    _required_checks(state, found)
    _skip_logic_checks(state, found)
    found = dedupe(found)
    goods: list[Finding] = []
    _good_practices(state, found, goods)
    return RuleResult(findings=dedupe(found + goods), stats=compute_stats(state), state=state)


# --------------------------------------------------------------------------- objectives (keyword fallback)

_STOP = frozenset(
    "the and for with that this from into about their they them will have has had are was were been being what which who whom "
    "when where why how our your its not but can could should would may might also than then such these those through over "
    "under between among within without per each any all more most some other understand assess measure determine identify "
    "examine explore evaluate study survey questionnaire respondents people level levels".split()
)


def split_objectives(text: Optional[str]) -> list[str]:
    if not text or not text.strip():
        return []
    parts = re.split(r"(?:\r?\n)+|(?<=[.;])\s+(?=[A-Z0-9])|(?:^|\s)(?:\d+[.)]|[-•*])\s+", text)
    items = [re.sub(r"^\s*(?:\d+[.)]|[-•*])\s+", "", re.sub(r"\s+", " ", p or "")).strip(" -•*\t;") for p in parts]
    return [i for i in items if len(i) >= 4][:12]


def keyword_coverage(state: WorkingState, objectives: list[str]) -> list[CoverageItem]:
    """Rough fallback used when the AI is unavailable: does question wording mention the objective's key terms?"""
    corpus = []
    for q in state.questions:
        text = " ".join([q.f.get("label") or "", q.f.get("hint") or "", q.section.title or ""] + [c.get("label") or "" for c in q.f.get("choices") or []])
        corpus.append((q.code, {w.lower()[:5] for w in _words(text)}))
    out: list[CoverageItem] = []
    for obj in objectives:
        keys = {w.lower()[:5] for w in _words(obj) if len(w) > 3 and w.lower() not in _STOP}
        if not keys:
            out.append(CoverageItem(objective=obj, covered=False, note="Could not extract key terms to match."))
            continue
        hits = [code for code, stems in corpus if code and len(keys & stems) >= max(1, (len(keys) + 2) // 3)]
        covered = bool(hits)
        out.append(CoverageItem(
            objective=obj, covered=covered, question_codes=hits[:8],
            note="Matched by keywords only (AI check not used)." if covered else "No question wording matches this objective's key terms (keyword check)."))
    return out


def coverage_findings(coverage: list[CoverageItem], source: str = "RULE") -> list[Finding]:
    out: list[Finding] = []
    for item in coverage:
        if not item.covered:
            out.append(make_finding(
                "WARNING", "COVERAGE", f"Objective not covered: “{_short(item.objective, 90)}”",
                item.note or "No question appears to collect the information this objective needs.",
                "Add questions that measure this objective, or remove the objective if it is out of scope.", None, source=source))
    return out
