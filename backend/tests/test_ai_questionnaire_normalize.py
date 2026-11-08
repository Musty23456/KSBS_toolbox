"""
Unit tests for the deterministic validation of AI-generated questionnaires.

These need no database, no network and no API key: they feed hand-written
"model output" (including badly broken output) into ``normalize.py``.
"""

import pytest

from app.ai.errors import AIInvalidJsonError, AIInvalidQuestionnaireError
from app.ai.questionnaire import normalize as n
from app.ai.questionnaire.normalize import Context, QuestionInfo


def info(code, qtype, *values):
    return QuestionInfo(code=code, type=qtype, values=frozenset(values))


# --------------------------------------------------------------------------
# JSON extraction
# --------------------------------------------------------------------------


def test_extract_json_plain():
    assert n.extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_markdown_fence():
    assert n.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert n.extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_surrounding_chatter():
    assert n.extract_json('Sure! Here it is:\n{"a": {"b": 2}}\nHope that helps.') == {"a": {"b": 2}}


@pytest.mark.parametrize("bad", ["", "   ", "not json", '{"a": ', '{"a": 1', "[1, 2", None, 42])
def test_extract_json_rejects_garbage(bad):
    with pytest.raises(AIInvalidJsonError):
        n.extract_json(bad)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SHORT_TEXT", "SHORT_TEXT"),
        ("single_choice", "SINGLE_CHOICE"),
        ("radio", "SINGLE_CHOICE"),
        ("Checkbox", "MULTIPLE_CHOICE"),
        ("boolean", "YES_NO"),
        ("yes/no", "YES_NO"),
        ("number", "DECIMAL"),
        ("open-ended", "LONG_TEXT"),
        ("location", "GPS"),
        ("hologram", None),
        ("", None),
        (None, None),
        (7, None),
    ],
)
def test_normalize_type(raw, expected):
    assert n.normalize_type(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Household Size", "household_size"),
        ("  age-in-years!! ", "age_in_years"),
        ("Ƙauye Name", "auye_name"),  # non-ASCII is folded, not crashed on
        ("1st_visit", "q_1st_visit"),
        ("and", "q_and"),
        ("None", "q_none"),
        ("class", "q_class"),
        ("", ""),
        (None, ""),
        ("***", ""),
    ],
)
def test_slugify_code(raw, expected):
    assert n.slugify_code(raw) == expected


def test_slugify_code_is_length_limited():
    assert len(n.slugify_code("a" * 500)) <= n.MAX_CODE_LEN


def test_unique_code_suffixes():
    assert n.unique_code("age", set()) == "age"
    assert n.unique_code("age", {"age"}) == "age_2"
    assert n.unique_code("age", {"age", "age_2"}) == "age_3"
    long = "x" * n.MAX_CODE_LEN
    assert len(n.unique_code(long, {long})) <= n.MAX_CODE_LEN


def test_slugify_choice_value():
    assert n.slugify_choice_value("Very satisfied") == "VERY_SATISFIED"
    assert n.slugify_choice_value("Don't know") == "DON_T_KNOW"


@pytest.mark.parametrize("pattern", [r"^\d{11}$", r"^[A-Z]{2}-\d{4}$", r"^(\+234|0)\d{10}$"])
def test_safe_regex_accepts_normal_patterns(pattern):
    assert n.is_safe_regex(pattern)[0]


@pytest.mark.parametrize("pattern", ["(a+)+$", "(a*)*b", r"([a-z]+)*x", "[unclosed", "(" * 3, "x" * 501])
def test_safe_regex_rejects_bad_patterns(pattern):
    ok, reason = n.is_safe_regex(pattern)
    assert not ok and reason


def test_clean_text_strips_control_chars_and_limits():
    assert n.clean_text("  hello\x00 \n world  ", 50) == "hello world"
    assert n.clean_text("a" * 100, 10) == "a" * 10
    assert n.clean_text("", 10) is None
    assert n.clean_text(None, 10) is None
    assert n.clean_text({"x": 1}, 10) is None
    assert n.clean_text("line1\nline2", 50, allow_newlines=True) == "line1\nline2"


# --------------------------------------------------------------------------
# Skip-logic expressions
# --------------------------------------------------------------------------

KNOWN = {
    "age": info("age", "INTEGER"),
    "gender": info("gender", "SINGLE_CHOICE", "MALE", "FEMALE"),
    "consent": info("consent", "YES_NO"),
    "symptoms": info("symptoms", "MULTIPLE_CHOICE", "FEVER", "COUGH"),
    "village": info("village", "SHORT_TEXT"),
}


@pytest.mark.parametrize(
    "expr",
    [
        "gender == 'FEMALE'",
        "gender == 'FEMALE' and age >= 12",
        "age >= 18 or consent == 'YES'",
        "not (age < 5)",
        "consent != 'NO'",
        "'FEVER' in symptoms",
        "'COUGH' not in symptoms",
        '"FEMALE" == gender',
    ],
)
def test_expression_accepts_valid(expr):
    normalised, reason = n.check_expression(expr, known=KNOWN, self_code="q")
    assert normalised and reason is None


def test_expression_is_normalised_to_single_quotes():
    normalised, _ = n.check_expression('gender == "FEMALE"', known=KNOWN)
    assert normalised == "gender == 'FEMALE'"


def test_expression_blank_is_not_an_error():
    assert n.check_expression(None, known=KNOWN) == (None, None)
    assert n.check_expression("   ", known=KNOWN) == (None, None)


@pytest.mark.parametrize(
    "expr",
    [
        "gender ==",  # syntax error
        "__import__('os').system('x')",  # call
        "gender.upper() == 'X'",  # attribute + call
        "age + 1 > 3",  # arithmetic
        "[1, 2][0] == age",  # list / subscript
        "lambda: 1",  # lambda
        "age >= 18 if True else False",  # ternary
        "gender == True",  # boolean constant
        "gender == None",  # None
        "later == 'YES'",  # unknown / later question
        "x" * 600,  # too long
        "age == age",  # compares two questions
        "18 < 19",  # no question referenced
        "gender == 'ALIEN'",  # not a real choice
        "consent == 'MAYBE'",  # YES_NO values are YES/NO
        "consent == 1",
        "gender > 'A'",  # ordering on a choice question
        "village > 3",
        "age == 'ten'",  # number compared to text
        "symptoms == 'FEVER'",  # multi-choice must use 'in'
        "'ALIEN' in symptoms",
        "age in gender",
        "age > -1",  # the backend evaluator has no unary minus
        "'FEMALE' in age",
    ],
)
def test_expression_rejects_invalid(expr):
    normalised, reason = n.check_expression(expr, known=KNOWN, self_code="me")
    assert normalised is None and reason


def test_expression_cannot_reference_itself():
    normalised, reason = n.check_expression("me == 'YES'", known={**KNOWN, "me": info("me", "YES_NO")}, self_code="me")
    assert normalised is None and "itself" in reason


def test_expression_code_map_rewrites_model_codes():
    normalised, reason = n.check_expression(
        "Gender == 'FEMALE'", known=KNOWN, code_map={"Gender": "gender"}
    )
    assert reason is None and normalised == "gender == 'FEMALE'"


# --------------------------------------------------------------------------
# Single questions
# --------------------------------------------------------------------------


def q(**kw):
    base = {"code": "q1", "label": "A question?", "type": "SHORT_TEXT"}
    base.update(kw)
    return base


def test_question_basic_defaults():
    ctx = Context()
    out = n.normalize_question(q(), ctx)
    assert out["code"] == "q1" and out["type"] == "SHORT_TEXT"
    assert out["is_required"] is False and out["choices"] == []
    assert out["calculation_expression"] is None and out["cascade_parent_question_id"] is None
    assert "q1" in ctx.known and "q1" in ctx.taken_codes


@pytest.mark.parametrize("raw", [None, "text", 5, [], {}, {"label": ""}, {"label": "   "}, {"label": "x"}, {"label": "x", "type": "nope"}])
def test_question_unusable_is_dropped_with_warning(raw):
    ctx = Context()
    assert n.normalize_question(raw, ctx) is None
    assert ctx.warnings


def test_question_required_coercion():
    assert n.normalize_question(q(is_required="true"), Context())["is_required"] is True
    assert n.normalize_question(q(is_required="no"), Context())["is_required"] is False
    assert n.normalize_question(q(is_required=1), Context())["is_required"] is True


def test_choice_question_needs_two_choices():
    ctx = Context()
    assert n.normalize_question(q(type="SINGLE_CHOICE", label="One choice?", choices=[{"label": "Only"}]), ctx) is None
    assert n.normalize_question(q(type="MULTIPLE_CHOICE", label="No choices?"), ctx) is None
    assert len(ctx.warnings) == 2


def test_choices_are_cleaned_and_made_unique():
    out = n.normalize_question(
        q(
            type="DROPDOWN",
            choices=[
                {"value": "yes please", "label": "Yes"},  # malformed value -> derived
                {"label": "Maybe"},  # no value -> derived from label
                {"value": "MAYBE", "label": "Maybe again"},  # duplicate of derived value
                "Plain string",  # bare string tolerated as a label
                {"label": ""},  # dropped: nothing to show
                42,  # dropped: not text or an object
            ],
        ),
        Context(),
    )
    values = [c["value"] for c in out["choices"]]
    assert values == ["YES_PLEASE", "MAYBE", "MAYBE_2", "PLAIN_STRING"]
    assert [c["order_index"] for c in out["choices"]] == [1, 2, 3, 4]
    assert all(c["label"] for c in out["choices"])


def test_yes_no_never_keeps_choices():
    out = n.normalize_question(q(type="boolean", choices=[{"value": "Y", "label": "Y"}, {"value": "N", "label": "N"}]), Context())
    assert out["type"] == "YES_NO" and out["choices"] == []


def test_non_choice_types_drop_choices():
    out = n.normalize_question(q(type="SHORT_TEXT", choices=[{"value": "A", "label": "A"}]), Context())
    assert out["choices"] == []


def test_numeric_limits_kept_and_coerced():
    out = n.normalize_question(q(type="INTEGER", min_value="0", max_value=120.7), Context())
    assert (out["min_value"], out["max_value"]) == (0.0, 120.0)


def test_numeric_limits_inverted_are_removed():
    ctx = Context()
    out = n.normalize_question(q(type="DECIMAL", min_value=10, max_value=1), ctx)
    assert out["min_value"] is None and out["max_value"] is None and ctx.warnings


def test_numeric_limits_ignored_on_text_and_text_limits_ignored_on_numbers():
    text = n.normalize_question(q(type="SHORT_TEXT", min_value=1, max_value=5, min_length=2, max_length=20), Context())
    assert text["min_value"] is None and (text["min_length"], text["max_length"]) == (2, 20)
    num = n.normalize_question(q(type="INTEGER", min_length=2, max_length=20, regex_pattern="^a$"), Context())
    assert num["min_length"] is None and num["regex_pattern"] is None


@pytest.mark.parametrize("bad", ["nan", "inf", True, "abc", []])
def test_numeric_garbage_is_ignored(bad):
    out = n.normalize_question(q(type="INTEGER", min_value=bad), Context())
    assert out["min_value"] is None


def test_text_length_rules_validated():
    ctx = Context()
    out = n.normalize_question(q(min_length=50, max_length=5), ctx)
    assert out["min_length"] is None and out["max_length"] is None and ctx.warnings
    out = n.normalize_question(q(max_length=10**9), Context())
    assert out["max_length"] == n.MAX_TEXT_LENGTH_RULE


def test_regex_kept_when_safe_and_removed_when_not():
    assert n.normalize_question(q(regex_pattern=r"^\d{11}$"), Context())["regex_pattern"] == r"^\d{11}$"
    ctx = Context()
    assert n.normalize_question(q(regex_pattern="(a+)+$"), ctx)["regex_pattern"] is None
    assert ctx.warnings


def test_duplicate_codes_are_renamed():
    ctx = Context()
    first = n.normalize_question(q(code="age"), ctx)
    second = n.normalize_question(q(code="Age", label="Again?"), ctx)
    assert (first["code"], second["code"]) == ("age", "age_2")
    assert any("age_2" in w for w in ctx.warnings)


def test_missing_code_is_derived_from_label():
    out = n.normalize_question({"label": "How old are you?", "type": "INTEGER"}, Context())
    assert out["code"].startswith("how_old_are_you")


def test_forced_code_is_kept_even_if_taken():
    ctx = Context(taken_codes={"age"})
    out = n.normalize_question(q(code="something_else", type="INTEGER"), ctx, forced_code="age")
    assert out["code"] == "age"


def test_skip_logic_applied_to_earlier_questions_and_recorded():
    ctx = Context()
    n.normalize_question(q(code="gender", type="SINGLE_CHOICE", choices=[{"value": "MALE", "label": "M"}, {"value": "FEMALE", "label": "F"}]), ctx)
    out = n.normalize_question(
        q(code="pregnant", type="YES_NO", relevance_expression="gender == 'FEMALE'", skip_logic_note="Only for women"), ctx
    )
    assert out["relevance_expression"] == "gender == 'FEMALE'"
    assert ctx.skip_logic == [{"question_code": "pregnant", "expression": "gender == 'FEMALE'", "explanation": "Only for women"}]


def test_bad_skip_logic_is_removed_but_question_survives():
    ctx = Context()
    out = n.normalize_question(q(code="a", relevance_expression="ghost == 'YES'"), ctx)
    assert out is not None and out["relevance_expression"] is None
    assert ctx.skip_logic == [] and any("Skip logic" in w for w in ctx.warnings)


def test_skip_logic_follows_renamed_codes():
    ctx = Context()
    n.normalize_question(q(code="Consent Given", type="YES_NO"), ctx)  # becomes consent_given
    out = n.normalize_question(q(code="age", type="INTEGER", relevance_expression="Consent Given == 'YES'"), ctx)
    # a code with a space is not a valid identifier, so this must be dropped, not crash
    assert out["relevance_expression"] is None
    out = n.normalize_question(q(code="age2", type="INTEGER", relevance_expression="consent_given == 'YES'"), ctx)
    assert out["relevance_expression"] == "consent_given == 'YES'"


def test_calculations_and_defaults_are_never_generated():
    out = n.normalize_question(
        q(type="INTEGER", calculation_expression="1+1", default_value="5", cascade_parent_question_id="x"), Context()
    )
    assert out["calculation_expression"] is None and out["default_value"] is None and out["cascade_parent_question_id"] is None


# --------------------------------------------------------------------------
# Whole questionnaires
# --------------------------------------------------------------------------


def good_questionnaire():
    return {
        "title": "Household Health Survey",
        "description": "A survey.",
        "introduction": "Hello.",
        "respondent_instructions": "Answer honestly.",
        "sections": [
            {
                "title": "Consent",
                "questions": [
                    {"code": "consent", "label": "Do you agree?", "type": "YES_NO", "is_required": True},
                    {"code": "age", "label": "Age?", "type": "INTEGER", "min_value": 0, "max_value": 120, "relevance_expression": "consent == 'YES'"},
                ],
            },
            {
                "title": "Members",
                "groups": [
                    {
                        "title": "Each member",
                        "repeatable": True,
                        "min_repeats": 1,
                        "max_repeats": 10,
                        "questions": [
                            {"code": "m_name", "label": "Name?", "type": "SHORT_TEXT"},
                            {"code": "m_sex", "label": "Sex?", "type": "SINGLE_CHOICE", "choices": [{"value": "M", "label": "Male"}, {"value": "F", "label": "Female"}]},
                        ],
                    }
                ],
            },
        ],
    }


def test_whole_questionnaire_is_flattened_with_local_references():
    out = n.normalize_questionnaire(good_questionnaire(), expected_count=4)
    assert [s["order_index"] for s in out["sections"]] == [1, 2]
    assert [x["order_index"] for x in out["questions"]] == [1, 2, 3, 4]
    assert [x["section_id"] for x in out["questions"]] == ["local-0", "local-0", "local-1", "local-1"]
    assert [x["group_id"] for x in out["questions"]] == [None, None, "local-0", "local-0"]
    assert out["groups"][0]["section_id"] == "local-1" and out["groups"][0]["order_index"] == 1
    assert out["groups"][0]["repeatable"] is True and out["groups"][0]["max_repeats"] == 10
    assert out["warnings"] == []
    assert out["skip_logic"][0]["question_code"] == "age"


def test_group_numbering_continues_across_sections():
    raw = good_questionnaire()
    raw["sections"].append(
        {"title": "More", "groups": [{"title": "G2", "questions": [{"code": "z", "label": "Z?", "type": "SHORT_TEXT"}]}]}
    )
    out = n.normalize_questionnaire(raw)
    assert [g["title"] for g in out["groups"]] == ["Each member", "G2"]
    assert out["questions"][-1]["group_id"] == "local-1" and out["questions"][-1]["section_id"] == "local-2"


def test_non_repeatable_group_resets_repeat_settings():
    raw = good_questionnaire()
    group = raw["sections"][1]["groups"][0]
    group.update(repeatable=False, min_repeats=5, max_repeats=9)
    g = n.normalize_questionnaire(raw)["groups"][0]
    assert (g["repeatable"], g["min_repeats"], g["max_repeats"]) == (False, 1, None)


def test_group_with_max_below_min_is_repaired():
    raw = good_questionnaire()
    raw["sections"][1]["groups"][0].update(min_repeats=5, max_repeats=2)
    out = n.normalize_questionnaire(raw)
    assert out["groups"][0]["max_repeats"] is None and out["warnings"]


def test_empty_section_and_group_are_removed_and_references_stay_consistent():
    raw = good_questionnaire()
    raw["sections"].insert(0, {"title": "Empty", "questions": [{"label": ""}]})
    raw["sections"][2]["groups"].append({"title": "Empty group", "questions": []})
    out = n.normalize_questionnaire(raw)
    assert [s["title"] for s in out["sections"]] == ["Consent", "Members"]
    assert out["questions"][0]["section_id"] == "local-0"  # indexes follow the *kept* sections
    assert len(out["groups"]) == 1
    assert any("Empty" in w for w in out["warnings"])


@pytest.mark.parametrize(
    "raw",
    [None, [], "text", {}, {"sections": []}, {"sections": "x"}, {"sections": [{"title": "S", "questions": []}]}, {"sections": [{"title": "S", "questions": [{"label": "x", "type": "bad"}]}]}],
)
def test_unusable_questionnaire_raises(raw):
    with pytest.raises(AIInvalidQuestionnaireError):
        n.normalize_questionnaire(raw)


def test_max_questions_caps_the_total():
    raw = {
        "sections": [
            {"title": f"S{i}", "questions": [{"code": f"q{i}_{j}", "label": f"Q {i}.{j}", "type": "SHORT_TEXT"} for j in range(10)]}
            for i in range(3)
        ]
    }
    out = n.normalize_questionnaire(raw, max_questions=14)
    assert len(out["questions"]) == 14
    assert any("limit" in w for w in out["warnings"])


def test_far_too_few_questions_warns():
    out = n.normalize_questionnaire(good_questionnaire(), expected_count=40)
    assert any("40 were requested" in w for w in out["warnings"])


def test_far_too_many_questions_warns():
    out = n.normalize_questionnaire(good_questionnaire(), expected_count=1)
    assert any("more than the 1 requested" in w for w in out["warnings"])


def test_instructions_alias_and_missing_title():
    raw = good_questionnaire()
    del raw["respondent_instructions"], raw["title"]
    raw["instructions"] = "Alias text"
    out = n.normalize_questionnaire(raw)
    assert out["respondent_instructions"] == "Alias text" and out["title"] is None


def test_section_without_title_gets_a_default():
    raw = {"sections": [{"questions": [{"code": "a", "label": "A?", "type": "SHORT_TEXT"}]}]}
    assert n.normalize_questionnaire(raw)["sections"][0]["title"] == "Untitled section"


def test_normalize_section_standalone_has_no_section_reference():
    ctx = Context(taken_codes={"age"})
    section = n.normalize_section(
        {"title": "S", "questions": [{"code": "age", "label": "Age again", "type": "INTEGER"}]},
        ctx,
        section_ref=None,
    )
    assert section["questions"][0]["code"] == "age_2"  # collides with a code elsewhere in the survey
    assert section["questions"][0]["section_id"] is None


def test_compose_description():
    assert n.compose_description("D", "I", "X") == "D\n\nIntroduction\nI\n\nInstructions for respondents\nX"
    assert n.compose_description(None, "I", None) == "Introduction\nI"
    assert n.compose_description(None, None, None) == ""
