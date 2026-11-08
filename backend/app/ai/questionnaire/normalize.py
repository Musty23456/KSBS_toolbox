"""
Deterministic clean-up and validation of AI-generated questionnaire content.

This module is deliberately plain Python (no Pydantic, no database): it takes
the JSON the model returned (already ``json.loads``-ed) and produces dicts that
are then re-validated by the *existing* ``QuestionIn`` / ``SectionIn`` /
``QuestionGroupIn`` schemas. Model output is never trusted:

* unknown question types are mapped to a KBS type or the question is dropped;
* codes are normalised to ``snake_case`` and made unique;
* choices are required for choice types and removed from all others;
* validation rules (min/max, length, regex) are checked against the type;
* skip-logic expressions are parsed with a strict AST allow-list that every
  KBS evaluator (backend, web, Android) understands, must only reference
  *earlier* questions, and may only compare against real choice values.

Anything repairable is repaired and reported in ``warnings``; anything that
cannot be made safe is dropped (also reported). Nothing here raises for a bad
individual question - only for output that is unusable as a whole.
"""

from __future__ import annotations

import ast
import json
import keyword
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

from app.ai.errors import AIInvalidJsonError, AIInvalidQuestionnaireError
from app.services.expressions import ExpressionError, evaluate_expression

# Must stay in sync with app.models.question.QuestionType (a test enforces it).
VALID_TYPES: tuple[str, ...] = (
    "SHORT_TEXT",
    "LONG_TEXT",
    "INTEGER",
    "DECIMAL",
    "DATE",
    "TIME",
    "DATETIME",
    "SINGLE_CHOICE",
    "MULTIPLE_CHOICE",
    "DROPDOWN",
    "YES_NO",
    "GPS",
    "PHOTO",
    "AUDIO",
    "SIGNATURE",
    "BARCODE",
)
CHOICE_TYPES = frozenset({"SINGLE_CHOICE", "MULTIPLE_CHOICE", "DROPDOWN"})
SINGLE_VALUE_CHOICE_TYPES = frozenset({"SINGLE_CHOICE", "DROPDOWN", "YES_NO"})
NUMERIC_TYPES = frozenset({"INTEGER", "DECIMAL"})
TEXT_TYPES = frozenset({"SHORT_TEXT", "LONG_TEXT"})
YES_NO_VALUES = frozenset({"YES", "NO"})

_TYPE_SYNONYMS = {
    "TEXT": "SHORT_TEXT",
    "STRING": "SHORT_TEXT",
    "OPEN_TEXT": "LONG_TEXT",
    "OPEN_ENDED": "LONG_TEXT",
    "PARAGRAPH": "LONG_TEXT",
    "TEXTAREA": "LONG_TEXT",
    "NUMBER": "DECIMAL",
    "NUMERIC": "DECIMAL",
    "FLOAT": "DECIMAL",
    "INT": "INTEGER",
    "WHOLE_NUMBER": "INTEGER",
    "RADIO": "SINGLE_CHOICE",
    "SELECT_ONE": "SINGLE_CHOICE",
    "MULTIPLE_CHOICE_SINGLE": "SINGLE_CHOICE",
    "LIKERT": "SINGLE_CHOICE",
    "RATING": "SINGLE_CHOICE",
    "CHECKBOX": "MULTIPLE_CHOICE",
    "CHECKBOXES": "MULTIPLE_CHOICE",
    "SELECT_MULTIPLE": "MULTIPLE_CHOICE",
    "MULTI_SELECT": "MULTIPLE_CHOICE",
    "SELECT": "DROPDOWN",
    "BOOLEAN": "YES_NO",
    "BOOL": "YES_NO",
    "YESNO": "YES_NO",
    "LOCATION": "GPS",
    "GEOPOINT": "GPS",
    "IMAGE": "PHOTO",
    "PICTURE": "PHOTO",
    "VOICE": "AUDIO",
    "QR": "BARCODE",
    "QR_CODE": "BARCODE",
    "TIMESTAMP": "DATETIME",
}

_RESERVED_CODES = frozenset(
    {"and", "or", "not", "in", "is", "true", "false", "none", "null"}
)

# Limits that mirror the database / existing schema.
MAX_CODE_LEN = 60  # DB allows 100; leave room for de-duplication suffixes
MAX_LABEL_LEN = 1000
MAX_HINT_LEN = 500
MAX_CHOICE_LABEL_LEN = 500
MAX_CHOICE_VALUE_LEN = 255
MAX_CHOICES = 60
MAX_TITLE_LEN = 255
MAX_SECTION_TITLE_LEN = 255
MAX_TEXT_BLOCK_LEN = 4000
MAX_REGEX_LEN = 500
MAX_EXPRESSION_LEN = 500
MAX_SECTIONS = 30
MAX_TEXT_LENGTH_RULE = 10000

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Nested quantifiers such as (a+)+ , (a*)* , (a+){2,} are the classic ReDoS shape.
_NESTED_QUANTIFIER = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)\s*(?:[+*]|\{\d*,\d*\})")


# --------------------------------------------------------------------------
# JSON extraction
# --------------------------------------------------------------------------


def extract_json(text: str) -> Any:
    """Parse the model's reply as JSON, tolerating Markdown fences and chatter."""
    if not isinstance(text, str) or not text.strip():
        raise AIInvalidJsonError()
    candidate = text.strip()
    fence = re.match(r"^```(?:json|JSON)?\s*(.*?)\s*```$", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost {...} block (model added a sentence around it).
    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise AIInvalidJsonError()


# --------------------------------------------------------------------------
# Small text helpers
# --------------------------------------------------------------------------


def clean_text(value: Any, max_len: int, *, allow_newlines: bool = False) -> Optional[str]:
    """Return a trimmed string (or None when empty / not text)."""
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = str(value)
    text = _CONTROL_CHARS.sub("", text)
    if not allow_newlines:
        text = re.sub(r"\s+", " ", text)
    text = text.strip()
    if not text:
        return None
    return text[:max_len].rstrip()


def normalize_type(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    key = re.sub(r"[\s\-/]+", "_", raw.strip().upper())
    if key in VALID_TYPES:
        return key
    return _TYPE_SYNONYMS.get(key)


def _ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def slugify_code(raw: Any) -> str:
    """snake_case identifier safe to use inside an expression ('' when nothing usable)."""
    if raw is None:
        return ""
    text = _ascii_fold(str(raw)).lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    text = text[:MAX_CODE_LEN].strip("_")
    if not text:
        return ""
    if text[0].isdigit():
        text = f"q_{text}"[:MAX_CODE_LEN]
    if text in _RESERVED_CODES or keyword.iskeyword(text):
        text = f"q_{text}"
    return text


def slugify_choice_value(raw: Any) -> str:
    text = _ascii_fold(str(raw)).upper()
    text = re.sub(r"[^A-Z0-9]+", "_", text).strip("_")
    return text[:MAX_CHOICE_VALUE_LEN].strip("_")


def unique_code(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    n = 2
    while True:
        suffix = f"_{n}"
        candidate = f"{base[: MAX_CODE_LEN - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
        n += 1


def is_safe_regex(pattern: str) -> tuple[bool, str]:
    if len(pattern) > MAX_REGEX_LEN:
        return False, "pattern is too long"
    try:
        re.compile(pattern)
    except re.error:
        return False, "pattern is not a valid regular expression"
    if _NESTED_QUANTIFIER.search(pattern):
        return False, "pattern could be very slow (nested repetition)"
    return True, ""


# --------------------------------------------------------------------------
# Skip-logic expression validation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class QuestionInfo:
    code: str
    type: str
    values: frozenset[str] = frozenset()


_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Name,
    ast.Load,
    ast.Constant,
)
_ORDERING_OPS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)


class _Renamer(ast.NodeTransformer):
    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping

    def visit_Name(self, node: ast.Name):  # noqa: N802 - ast API
        return ast.copy_location(ast.Name(id=self.mapping.get(node.id, node.id), ctx=ast.Load()), node)


def _constant_kind(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or node.value is None:
            return None
        if isinstance(node.value, str):
            return "str"
        if isinstance(node.value, (int, float)):
            return "num"
    return None


def _check_pair(left: ast.AST, op: ast.cmpop, right: ast.AST, known: dict[str, QuestionInfo]) -> Optional[str]:
    """Return a reason string when one comparison is nonsensical for the referenced question."""
    left_name = left if isinstance(left, ast.Name) else None
    right_name = right if isinstance(right, ast.Name) else None
    if left_name is None and right_name is None:
        return "compare an earlier question's answer to a value"
    if left_name is not None and right_name is not None:
        return "compare a question to a fixed value, not to another question"

    if isinstance(op, (ast.In, ast.NotIn)):
        # 'VALUE' in question  (the question must be on the right)
        if right_name is None or _constant_kind(left) != "str":
            return "'in' must look like 'VALUE' in question_code"
        info = known[right_name.id]
        literal = left.value  # type: ignore[attr-defined]
        if info.type in CHOICE_TYPES or info.type == "YES_NO":
            allowed = YES_NO_VALUES if info.type == "YES_NO" else info.values
            if literal not in allowed:
                return f"'{literal}' is not a choice of '{info.code}'"
            return None
        if info.type in TEXT_TYPES:
            return None
        return f"'in' cannot be used with the {info.type} question '{info.code}'"

    # Normalise so the question is on the left and the literal on the right.
    name_node = left_name or right_name
    literal_node = right if left_name is not None else left
    info = known[name_node.id]  # type: ignore[union-attr]
    kind = _constant_kind(literal_node)
    if kind is None:
        return "compare to a plain text or number value"

    if isinstance(op, _ORDERING_OPS):
        if info.type not in NUMERIC_TYPES:
            return f"'<' / '>' only work on number questions, but '{info.code}' is {info.type}"
        if kind != "num":
            return "number questions must be compared to a number"
        return None

    # == / !=
    if info.type in NUMERIC_TYPES:
        return None if kind == "num" else f"'{info.code}' is a number question; compare it to a number"
    if info.type == "YES_NO":
        if kind != "str" or literal_node.value not in YES_NO_VALUES:  # type: ignore[attr-defined]
            return f"'{info.code}' is Yes/No; compare it to 'YES' or 'NO'"
        return None
    if info.type in SINGLE_VALUE_CHOICE_TYPES:
        if kind != "str" or literal_node.value not in info.values:  # type: ignore[attr-defined]
            return f"{literal_node.value!r} is not a choice of '{info.code}'"  # type: ignore[attr-defined]
        return None
    if info.type == "MULTIPLE_CHOICE":
        return "use 'VALUE' in question_code for multiple-choice questions"
    return None


def check_expression(
    expression: Any,
    *,
    known: dict[str, QuestionInfo],
    code_map: Optional[dict[str, str]] = None,
    self_code: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Validate a skip-logic expression written by the model.

    ``known`` holds the questions that appear *before* this one (final codes);
    ``code_map`` translates the model's original codes to final codes.
    Returns ``(normalised_expression, None)`` or ``(None, reason)``.
    """
    text = clean_text(expression, MAX_EXPRESSION_LEN * 2)
    if text is None:
        return None, None  # no expression at all is not an error
    if len(text) > MAX_EXPRESSION_LEN:
        return None, "expression is too long"
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return None, "expression has a syntax error"

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return None, "expression uses unsupported syntax (only and / or / not, comparisons and 'in' are allowed)"
        if isinstance(node, ast.Constant) and (isinstance(node.value, bool) or node.value is None):
            return None, "expression uses True/False/None; compare to 'YES'/'NO' or a choice value instead"
        if isinstance(node, ast.Constant) and not isinstance(node.value, (str, int, float)):
            return None, "expression uses an unsupported value"
        if isinstance(node, ast.UnaryOp) and not isinstance(node.op, ast.Not):
            # No unary minus: the backend evaluator (app/services/expressions.py) does not support it.
            return None, "expression uses unsupported syntax (negative numbers are not supported)"

    if code_map:
        tree = ast.fix_missing_locations(_Renamer(code_map).visit(tree))

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id == self_code:
                return None, "a question cannot depend on itself"
            if node.id not in known:
                return None, f"it refers to '{node.id}', which is not an earlier question"

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            for i, op in enumerate(node.ops):
                problem = _check_pair(operands[i], op, operands[i + 1], known)
                if problem:
                    return None, problem

    normalised = ast.unparse(tree)
    if len(normalised) > MAX_EXPRESSION_LEN:
        return None, "expression is too long"
    try:
        evaluate_expression(normalised, {})  # the real evaluator must accept it too
    except ExpressionError:
        return None, "expression is not supported by the survey engine"
    return normalised, None


# --------------------------------------------------------------------------
# Question / section normalisation
# --------------------------------------------------------------------------


@dataclass
class Context:
    """State shared while normalising one questionnaire, section or question."""

    taken_codes: set[str] = field(default_factory=set)
    known: dict[str, QuestionInfo] = field(default_factory=dict)  # earlier questions, final codes
    code_map: dict[str, str] = field(default_factory=dict)  # model's code -> final code
    warnings: list[str] = field(default_factory=list)
    skip_logic: list[dict[str, str]] = field(default_factory=list)

    def warn(self, message: str) -> None:
        if message not in self.warnings and len(self.warnings) < 50:
            self.warnings.append(message)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "required"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _to_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _normalise_choices(raw: Any, ctx: Context, label_for_warning: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    choices: list[dict[str, Any]] = []
    seen_values: set[str] = set()
    for item in raw[:MAX_CHOICES]:
        if isinstance(item, str):  # model sent a bare string: treat as label
            item = {"label": item}
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label"), MAX_CHOICE_LABEL_LEN) or clean_text(item.get("value"), MAX_CHOICE_LABEL_LEN)
        if not label:
            continue
        value = clean_text(item.get("value"), MAX_CHOICE_VALUE_LEN)
        # Keep a well-formed model-supplied value; otherwise derive one from the label.
        if not value or not re.fullmatch(r"[A-Za-z0-9_.\-]+", value):
            value = slugify_choice_value(value or label)
        if not value:
            continue
        base, n = value, 2
        while value in seen_values:
            value = f"{base}_{n}"[:MAX_CHOICE_VALUE_LEN]
            n += 1
        seen_values.add(value)
        choices.append({"value": value, "label": label, "order_index": len(choices) + 1, "cascade_parent_value": None})
    if len(raw) > MAX_CHOICES:
        ctx.warn(f"'{label_for_warning}' had more than {MAX_CHOICES} choices; the extras were removed.")
    return choices


def normalize_question(
    raw: Any,
    ctx: Context,
    *,
    forced_code: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Return a ``QuestionIn``-shaped dict (without ordering / section / group) or None if unusable."""
    if not isinstance(raw, dict):
        ctx.warn("A generated question was not an object and was skipped.")
        return None

    label = clean_text(raw.get("label"), MAX_LABEL_LEN)
    if not label:
        ctx.warn("A generated question had no text and was skipped.")
        return None

    qtype = normalize_type(raw.get("type"))
    if qtype is None:
        ctx.warn(f"Question '{label[:60]}' had an unsupported type ({clean_text(raw.get('type'), 30)!r}) and was skipped.")
        return None

    original_code = clean_text(raw.get("code"), 200) or ""
    if forced_code is not None:
        code = forced_code
    else:
        base = slugify_code(original_code) or slugify_code(label[:40]) or "question"
        code = unique_code(base, ctx.taken_codes)
        if code != base:
            ctx.warn(f"Question code '{base}' was used more than once; renamed to '{code}'.")

    choices: list[dict[str, Any]] = []
    if qtype in CHOICE_TYPES:
        choices = _normalise_choices(raw.get("choices"), ctx, label[:60])
        if len(choices) < 2:
            ctx.warn(f"Question '{label[:60]}' needs at least two answer choices and was skipped.")
            return None
    # YES_NO has fixed YES/NO answers; every other type has no choices.

    question: dict[str, Any] = {
        "code": code,
        "label": label,
        "hint": clean_text(raw.get("hint"), MAX_HINT_LEN),
        "type": qtype,
        "is_required": _to_bool(raw.get("is_required")),
        "min_value": None,
        "max_value": None,
        "min_length": None,
        "max_length": None,
        "regex_pattern": None,
        "relevance_expression": None,
        "calculation_expression": None,  # the generator never writes calculations
        "default_value": None,
        "cascade_parent_question_id": None,
        "choices": choices,
    }

    if qtype in NUMERIC_TYPES:
        lo, hi = _to_number(raw.get("min_value")), _to_number(raw.get("max_value"))
        if qtype == "INTEGER":
            lo = float(int(lo)) if lo is not None else None
            hi = float(int(hi)) if hi is not None else None
        if lo is not None and hi is not None and lo > hi:
            ctx.warn(f"Question '{label[:60]}' had a minimum above its maximum; the limits were removed.")
            lo = hi = None
        question["min_value"], question["max_value"] = lo, hi
    elif qtype in TEXT_TYPES:
        lo_len, hi_len = _to_number(raw.get("min_length")), _to_number(raw.get("max_length"))
        lo_i = int(lo_len) if lo_len is not None and lo_len >= 0 else None
        hi_i = int(hi_len) if hi_len is not None and hi_len >= 1 else None
        if hi_i is not None:
            hi_i = min(hi_i, MAX_TEXT_LENGTH_RULE)
        if lo_i is not None:
            lo_i = min(lo_i, MAX_TEXT_LENGTH_RULE)
        if lo_i is not None and hi_i is not None and lo_i > hi_i:
            ctx.warn(f"Question '{label[:60]}' had a minimum length above its maximum; the limits were removed.")
            lo_i = hi_i = None
        question["min_length"], question["max_length"] = lo_i or None, hi_i
        pattern = clean_text(raw.get("regex_pattern"), MAX_REGEX_LEN * 2)
        if pattern:
            ok, reason = is_safe_regex(pattern)
            if ok:
                question["regex_pattern"] = pattern
            else:
                ctx.warn(f"Question '{label[:60]}': the format rule was removed ({reason}).")

    # ---- skip logic -------------------------------------------------------
    expression = raw.get("relevance_expression")
    if clean_text(expression, MAX_EXPRESSION_LEN * 2):
        normalised, reason = check_expression(expression, known=ctx.known, code_map=ctx.code_map, self_code=code)
        if normalised:
            question["relevance_expression"] = normalised
            ctx.skip_logic.append(
                {
                    "question_code": code,
                    "expression": normalised,
                    "explanation": clean_text(raw.get("skip_logic_note"), 300) or "",
                }
            )
        else:
            ctx.warn(f"Skip logic on '{label[:60]}' was removed: {reason}.")

    # Register for later questions' expressions.
    values = YES_NO_VALUES if qtype == "YES_NO" else frozenset(c["value"] for c in choices)
    ctx.known[code] = QuestionInfo(code=code, type=qtype, values=frozenset(values))
    ctx.taken_codes.add(code)
    if original_code:
        ctx.code_map.setdefault(original_code, code)
        ctx.code_map.setdefault(slugify_code(original_code) or original_code, code)
    return question


def _normalise_group_meta(raw: dict[str, Any], ctx: Context) -> dict[str, Any]:
    title = clean_text(raw.get("title"), MAX_SECTION_TITLE_LEN) or "Question group"
    repeatable = _to_bool(raw.get("repeatable"))
    min_repeats = _to_number(raw.get("min_repeats"))
    max_repeats = _to_number(raw.get("max_repeats"))
    min_r = max(1, int(min_repeats)) if min_repeats is not None else 1
    max_r = int(max_repeats) if max_repeats is not None and max_repeats >= 1 else None
    if not repeatable:
        min_r, max_r = 1, None
    elif max_r is not None and max_r < min_r:
        ctx.warn(f"Group '{title}' had a maximum below its minimum; the maximum was removed.")
        max_r = None
    return {
        "title": title,
        "description": clean_text(raw.get("description"), MAX_TEXT_BLOCK_LEN, allow_newlines=True),
        "repeatable": repeatable,
        "min_repeats": min_r,
        "max_repeats": max_r,
    }


def normalize_section(
    raw: Any,
    ctx: Context,
    *,
    section_ref: Optional[str],
    group_offset: int = 0,
    question_budget: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """
    Normalise one section. Returns::

        {"title", "description", "groups": [group dicts], "questions": [question dicts]}

    where each group has ``section_id=section_ref`` and each question carries
    ``section_id=section_ref`` and ``group_id="local-<index>"`` (index counted
    from ``group_offset`` so callers can number groups across sections).
    ``question_budget`` caps how many questions may be produced.
    """
    if not isinstance(raw, dict):
        ctx.warn("A generated section was not an object and was skipped.")
        return None

    title = clean_text(raw.get("title"), MAX_SECTION_TITLE_LEN) or "Untitled section"
    out_groups: list[dict[str, Any]] = []
    out_questions: list[dict[str, Any]] = []

    def room() -> bool:
        return question_budget is None or len(out_questions) < question_budget

    raw_questions = raw.get("questions")
    for rq in raw_questions if isinstance(raw_questions, list) else []:
        if not room():
            ctx.warn(f"Section '{title}' was shortened to the question limit.")
            break
        q = normalize_question(rq, ctx)
        if q is not None:
            q["section_id"], q["group_id"] = section_ref, None
            out_questions.append(q)

    raw_groups = raw.get("groups")
    for rg in raw_groups if isinstance(raw_groups, list) else []:
        if not isinstance(rg, dict):
            continue
        meta = _normalise_group_meta(rg, ctx)
        group_ref = f"local-{group_offset + len(out_groups)}"
        members: list[dict[str, Any]] = []
        raw_members = rg.get("questions")
        for rq in raw_members if isinstance(raw_members, list) else []:
            if not room():
                ctx.warn(f"Section '{title}' was shortened to the question limit.")
                break
            q = normalize_question(rq, ctx)
            if q is not None:
                q["section_id"], q["group_id"] = section_ref, group_ref
                members.append(q)
                out_questions.append(q)
        if not members:
            ctx.warn(f"Group '{meta['title']}' had no usable questions and was removed.")
            continue
        out_groups.append({**meta, "section_id": section_ref})

    if not out_questions:
        ctx.warn(f"Section '{title}' had no usable questions and was removed.")
        return None
    return {
        "title": title,
        "description": clean_text(raw.get("description"), MAX_TEXT_BLOCK_LEN, allow_newlines=True),
        "groups": out_groups,
        "questions": out_questions,
    }


def normalize_questionnaire(
    raw: Any,
    *,
    expected_count: Optional[int] = None,
    max_questions: int = 100,
) -> dict[str, Any]:
    """
    Normalise a whole generated questionnaire into flat, ``SurveyCreate``-shaped
    lists. Raises ``AIInvalidQuestionnaireError`` when nothing usable remains.
    """
    if not isinstance(raw, dict):
        raise AIInvalidQuestionnaireError()
    raw_sections = raw.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise AIInvalidQuestionnaireError("The AI response did not contain any sections.")

    ctx = Context()
    sections_out: list[dict[str, Any]] = []
    groups_out: list[dict[str, Any]] = []
    questions_out: list[dict[str, Any]] = []

    if len(raw_sections) > MAX_SECTIONS:
        ctx.warn(f"Only the first {MAX_SECTIONS} sections were kept.")
    for raw_section in raw_sections[:MAX_SECTIONS]:
        remaining = max_questions - len(questions_out)
        if remaining <= 0:
            ctx.warn(f"The questionnaire was shortened to the limit of {max_questions} questions.")
            break
        section_ref = f"local-{len(sections_out)}"
        section = normalize_section(
            raw_section,
            ctx,
            section_ref=section_ref,
            group_offset=len(groups_out),
            question_budget=remaining,
        )
        if section is None:
            continue
        sections_out.append(
            {"title": section["title"], "description": section["description"], "order_index": len(sections_out) + 1}
        )
        groups_out.extend(section["groups"])
        questions_out.extend(section["questions"])

    if not questions_out:
        raise AIInvalidQuestionnaireError("The AI response did not contain any usable questions.")

    for i, group in enumerate(groups_out, start=1):
        group["order_index"] = i
    for i, question in enumerate(questions_out, start=1):
        question["order_index"] = i

    if expected_count:
        got = len(questions_out)
        if got < max(1, int(expected_count * 0.6)):
            ctx.warn(
                f"The AI produced {got} questions but {expected_count} were requested. "
                "Use 'Regenerate section' or add questions to fill the gaps."
            )
        elif got > int(expected_count * 1.5) + 2:
            ctx.warn(f"The AI produced {got} questions, more than the {expected_count} requested. Delete any you do not need.")

    title = clean_text(raw.get("title"), MAX_TITLE_LEN)
    return {
        "title": title,
        "description": clean_text(raw.get("description"), MAX_TEXT_BLOCK_LEN, allow_newlines=True),
        "introduction": clean_text(raw.get("introduction"), MAX_TEXT_BLOCK_LEN, allow_newlines=True),
        "respondent_instructions": clean_text(
            raw.get("respondent_instructions") or raw.get("instructions"), MAX_TEXT_BLOCK_LEN, allow_newlines=True
        ),
        "sections": sections_out,
        "groups": groups_out,
        "questions": questions_out,
        "skip_logic": ctx.skip_logic,
        "warnings": ctx.warnings,
    }


def compose_description(
    description: Optional[str], introduction: Optional[str], instructions: Optional[str]
) -> str:
    """
    The Survey model has a single ``description`` column, so the introduction
    and respondent instructions are stored together in it, clearly labelled.
    """
    parts: list[str] = []
    if description:
        parts.append(description.strip())
    if introduction:
        parts.append(f"Introduction\n{introduction.strip()}")
    if instructions:
        parts.append(f"Instructions for respondents\n{instructions.strip()}")
    return "\n\n".join(parts)
