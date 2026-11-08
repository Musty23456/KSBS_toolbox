"""
Tests for the AI questionnaire editor's structured editing engine (Phase 3).

These exercise the pure engine (no database, no web framework, no AI provider): every one of the nine
operations, their validation, the "never wipe a questionnaire" guards, and the preview diff.
"""

import copy

import pytest

from app.ai.questionnaire_edit.diff import preview_operations
from app.ai.questionnaire_edit.engine import MAX_TOTAL_QUESTIONS, run
from app.ai.questionnaire_edit.operations import (
    MAX_OPERATIONS,
    OPERATION_NAMES,
    OperationError,
    parse_operation,
)
from app.ai.questionnaire_edit.snapshot import Snapshot

# --------------------------------------------------------------------------
# Fixture questionnaire
# --------------------------------------------------------------------------


def _q(code, section, qtype="SHORT_TEXT", label=None, **extra):
    return {"code": code, "label": label or f"Label of {code}", "type": qtype, "section_id": section, **extra}


def _choices(*pairs):
    return [{"value": v, "label": l, "order_index": i + 1} for i, (v, l) in enumerate(pairs)]


def base_data():
    """3 unsaved sections (local-0..2), 8 questions in section order, one group, one skip-logic rule."""
    return {
        "sections": [
            {"title": "Demographics", "order_index": 1},
            {"title": "Health", "order_index": 2},
            {"title": "Household", "order_index": 3},
        ],
        "groups": [{"title": "Members", "order_index": 1, "section_id": "local-2", "repeatable": True, "min_repeats": 1}],
        "questions": [
            _q("full_name", "local-0", label="Full name"),
            _q("age", "local-0", "INTEGER", "How old are you?", min_value=0, max_value=120),
            _q("gender", "local-0", "SINGLE_CHOICE", "Gender", choices=_choices(("MALE", "Male"), ("FEMALE", "Female"), ("OTHER", "Other"))),
            _q("pregnant", "local-1", "YES_NO", "Currently pregnant?", relevance_expression="gender == 'FEMALE'"),
            _q("symptoms", "local-1", "MULTIPLE_CHOICE", "Symptoms in the last week", choices=_choices(("FEVER", "Fever"), ("COUGH", "Cough"), ("RASH", "Rash"))),
            _q("clinic_visits", "local-1", "INTEGER", "Clinic visits this year"),
            _q("household_size", "local-2", "INTEGER", "How many people live here?", group_id="local-0"),
            _q("water_source", "local-2", "DROPDOWN", "Main water source", choices=_choices(("TAP", "Tap"), ("WELL", "Well"), ("RIVER", "River"))),
        ],
    }


def snap(data=None):
    return Snapshot.model_validate(data or base_data())


def codes(result_dict):
    return [q["code"] for q in result_dict["questions"]]


def by_code(result_dict, code):
    return next(q for q in result_dict["questions"] if q["code"] == code)


def section_of(result_dict, code):
    return by_code(result_dict, code)["section_id"]


def section_titles(result_dict):
    return [s["title"] for s in result_dict["sections"]]


def apply(ops, data=None):
    return preview_operations(snap(data), ops)


def rejected_reasons(preview):
    return [r.reason for r in preview.rejected]


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def test_all_nine_operations_are_supported():
    assert set(OPERATION_NAMES) == {
        "ADD_QUESTION",
        "UPDATE_QUESTION",
        "DELETE_QUESTION",
        "ADD_SECTION",
        "UPDATE_SECTION",
        "DELETE_SECTION",
        "REORDER_QUESTIONS",
        "UPDATE_CHOICES",
        "UPDATE_VALIDATION",
    }


@pytest.mark.parametrize(
    "raw",
    [
        "not an object",
        {},
        {"op": 5},
        {"op": "DROP_TABLE"},
        {"op": "UPDATE_QUESTION", "code": "age"},  # no changes
        {"op": "UPDATE_QUESTION", "code": "age", "changes": {}},
        {"op": "UPDATE_QUESTION", "code": "age", "changes": {"code": "new_code"}},  # codes are permanent
        {"op": "UPDATE_QUESTION", "code": "age", "changes": {"choices": []}},  # choices have their own operation
        {"op": "DELETE_QUESTION"},
        {"op": "ADD_QUESTION", "question": {"label": "x"}},  # no type
        {"op": "UPDATE_CHOICES", "code": "gender", "mode": "REMOVE"},
        {"op": "UPDATE_CHOICES", "code": "gender", "mode": "ADD", "choices": []},
        {"op": "UPDATE_CHOICES", "code": "gender", "mode": "WIPE", "choices": [{"label": "x"}]},
        {"op": "UPDATE_VALIDATION", "code": "age", "validation": {}},
        {"op": "UPDATE_VALIDATION", "code": "age", "validation": {"is_required": None}},
        {"op": "REORDER_QUESTIONS", "ordered_codes": ["only_one"]},
        {"op": "DELETE_SECTION", "section_ref": "S1", "questions": "VANISH"},
    ],
)
def test_malformed_operations_are_rejected_with_a_reason(raw):
    with pytest.raises(OperationError):
        parse_operation(raw)
    preview = apply([raw])
    assert preview.operations == []
    assert len(preview.rejected) == 1 and preview.rejected[0].reason
    assert not preview.has_changes


def test_operation_names_are_case_insensitive_and_extra_keys_ignored():
    op = parse_operation({"op": "delete_question", "code": "age", "explanation": "harmless extra"})
    assert op.op == "DELETE_QUESTION"


def test_too_many_operations_is_refused():
    with pytest.raises(OperationError):
        run(snap(), [{"op": "DELETE_QUESTION", "code": "age"}] * (MAX_OPERATIONS + 1))


def test_operations_must_be_a_list():
    with pytest.raises(OperationError):
        run(snap(), {"op": "DELETE_QUESTION"})  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# ADD_QUESTION
# --------------------------------------------------------------------------


def test_add_question_goes_to_end_of_its_section_and_derives_values():
    p = apply(
        [
            {
                "op": "ADD_QUESTION",
                "section_ref": "S1",
                "question": {
                    "code": "education",
                    "label": "What is your highest level of education?",
                    "type": "SINGLE_CHOICE",
                    "choices": [{"label": "None"}, {"label": "Primary school"}, {"value": "SECONDARY", "label": "Secondary school"}],
                },
            }
        ]
    )
    assert len(p.operations) == 1 and not p.rejected
    assert codes(p.result) == ["full_name", "age", "gender", "education", "pregnant", "symptoms", "clinic_visits", "household_size", "water_source"]
    q = by_code(p.result, "education")
    assert q["section_id"] == "local-0"
    assert [c["value"] for c in q["choices"]] == ["NONE", "PRIMARY_SCHOOL", "SECONDARY"]
    assert [c["order_index"] for c in q["choices"]] == [1, 2, 3]
    assert p.summary.added_questions == 1 and p.summary.questions_after == 9
    assert p.added[0].key == "education" and p.added[0].position_after == 4


def test_add_question_after_code_is_placed_directly_after_it():
    p = apply([{"op": "ADD_QUESTION", "after_code": "age", "question": {"label": "Date of birth", "type": "DATE"}}])
    assert codes(p.result)[:4] == ["full_name", "age", "date_of_birth", "full_name"[:0] or "gender"]
    assert by_code(p.result, "date_of_birth")["section_id"] == "local-0"  # inherited from 'age'


def test_add_question_to_empty_section_lands_after_earlier_sections():
    data = base_data()
    data["sections"].append({"title": "Employment", "order_index": 4})
    p = apply([{"op": "ADD_QUESTION", "section_ref": "S4", "question": {"label": "Are you employed?", "type": "YES_NO", "code": "employed"}}], data)
    assert codes(p.result)[-1] == "employed"
    assert by_code(p.result, "employed")["section_id"] == "local-3"


def test_add_question_defaults_to_last_section_when_none_given():
    p = apply([{"op": "ADD_QUESTION", "question": {"label": "Any comments?", "type": "LONG_TEXT", "code": "comments"}}])
    assert by_code(p.result, "comments")["section_id"] == "local-2"


def test_add_question_code_collision_is_renamed_and_reported():
    p = apply([{"op": "ADD_QUESTION", "section_ref": "S1", "question": {"code": "age", "label": "Age in months", "type": "INTEGER"}}])
    assert "age_2" in codes(p.result)
    assert any("age_2" in w for w in p.warnings)


def test_later_operations_can_use_the_code_the_model_asked_for():
    p = apply(
        [
            {"op": "ADD_QUESTION", "section_ref": "S1", "question": {"code": "age", "label": "Age in months", "type": "INTEGER"}},
            {"op": "UPDATE_VALIDATION", "code": "age", "validation": {"max_value": 59}},  # 'age' now means the *existing* one
        ]
    )
    assert by_code(p.result, "age")["max_value"] == 59


def test_new_question_codes_are_made_safe_when_missing_or_messy():
    p = apply(
        [
            {"op": "ADD_QUESTION", "section_ref": "S1", "question": {"label": "Où habitez-vous ?", "type": "SHORT_TEXT"}},
            {"op": "ADD_QUESTION", "section_ref": "S1", "question": {"code": "9 Bad Code!", "label": "Another", "type": "SHORT_TEXT"}},
        ]
    )

    result_codes = codes(p.result)
    assert "ou_habitez_vous" in result_codes
    assert "q_9_bad_code" in result_codes


@pytest.mark.parametrize(
    "question,fragment",
    [
        ({"label": "x", "type": "TELEPATHY"}, "not a supported question type"),
        ({"label": "   ", "type": "SHORT_TEXT"}, "needs question text"),
        ({"label": "Pick one", "type": "SINGLE_CHOICE"}, "at least two answer options"),
        ({"label": "Pick one", "type": "SINGLE_CHOICE", "choices": [{"label": "Only"}]}, "at least two answer options"),
        ({"label": "Name?", "type": "SHORT_TEXT", "choices": [{"label": "a"}, {"label": "b"}]}, "cannot have answer options"),
        ({"label": "Next?", "type": "SHORT_TEXT", "relevance_expression": "nothing_like_this == 'X'"}, "Skip logic"),
        ({"label": "Next?", "type": "SHORT_TEXT", "relevance_expression": "__import__('os')"}, "Skip logic"),
        ({"label": "Rate", "type": "INTEGER", "min_value": 10, "max_value": 1}, "minimum value is above"),
        ({"label": "Free", "type": "SHORT_TEXT", "regex_pattern": "(a+)+$"}, "format rule"),
    ],
)
def test_invalid_new_questions_are_rejected(question, fragment):
    p = apply([{"op": "ADD_QUESTION", "section_ref": "S1", "question": {"code": "newq", **question}}])
    assert p.operations == [] and len(p.rejected) == 1
    assert fragment in p.rejected[0].reason
    assert len(p.result["questions"]) == 8 and codes(p.result) == codes(base_to_result())


def test_new_question_with_valid_skip_logic_is_accepted():
    p = apply([{"op": "ADD_QUESTION", "section_ref": "S3", "question": {"code": "adults", "label": "How many adults?", "type": "INTEGER", "relevance_expression": "age >= 18"}}])
    assert len(p.operations) == 1
    assert by_code(p.result, "adults")["relevance_expression"] == "age >= 18"


def test_yes_no_choices_are_ignored_with_a_warning_and_other_inapplicable_rules_dropped():
    p = apply(
        [
            {"op": "ADD_QUESTION", "section_ref": "S1", "question": {"code": "consent", "label": "Do you agree?", "type": "YES_NO", "choices": [{"label": "Yes"}, {"label": "No"}]}},
            {"op": "ADD_QUESTION", "section_ref": "S1", "question": {"code": "nickname", "label": "Nickname", "type": "SHORT_TEXT", "min_value": 1, "max_length": 20}},
        ]
    )
    assert by_code(p.result, "consent")["choices"] == []
    nick = by_code(p.result, "nickname")
    assert nick["min_value"] is None and nick["max_length"] == 20
    assert any("fixed answers" in w for w in p.warnings)
    assert any("minimum/maximum value rule was removed" in w for w in p.warnings)


def test_add_question_unknown_section_or_mismatched_after_code():
    p = apply(
        [
            {"op": "ADD_QUESTION", "section_ref": "S9", "question": {"label": "x", "type": "SHORT_TEXT"}},
            {"op": "ADD_QUESTION", "section_ref": "S2", "after_code": "age", "question": {"label": "x", "type": "SHORT_TEXT"}},
            {"op": "ADD_QUESTION", "after_code": "ghost", "question": {"label": "x", "type": "SHORT_TEXT"}},
        ]
    )
    assert p.operations == []
    assert "no section" in p.rejected[0].reason
    assert "different section" in p.rejected[1].reason
    assert "no question with the code" in p.rejected[2].reason


def test_add_question_respects_total_limit():
    data = base_data()
    data["questions"] = [_q(f"q{i}", "local-0") for i in range(MAX_TOTAL_QUESTIONS)]
    p = apply([{"op": "ADD_QUESTION", "section_ref": "S1", "question": {"label": "one more", "type": "SHORT_TEXT"}}], data)
    assert p.operations == [] and "more than" in p.rejected[0].reason


# --------------------------------------------------------------------------
# UPDATE_QUESTION
# --------------------------------------------------------------------------


def test_update_question_text_hint_and_required():
    p = apply([{"op": "UPDATE_QUESTION", "code": "full_name", "changes": {"label": "What is your full name?", "hint": "As on the ID card", "is_required": True}}])
    q = by_code(p.result, "full_name")
    assert (q["label"], q["hint"], q["is_required"]) == ("What is your full name?", "As on the ID card", True)
    assert [f.field for f in p.modified[0].fields] == ["label", "hint", "is_required"]
    assert p.modified[0].before["label"] == "Full name"  # the original is shown next to the proposal


def test_update_question_never_changes_the_code_or_order():
    p = apply([{"op": "UPDATE_QUESTION", "code": "age", "changes": {"code": "years"}}])
    assert p.operations == [] and "code" in p.rejected[0].reason
    assert codes(p.result) == codes(base_to_result())


def base_to_result():
    return preview_operations(snap(), []).result


def test_update_question_noop_is_reported_not_applied():
    p = apply([{"op": "UPDATE_QUESTION", "code": "full_name", "changes": {"label": "Full name"}}])
    assert p.operations == [] and p.rejected[0].no_change and not p.has_changes


def test_update_question_cannot_blank_the_text():
    p = apply([{"op": "UPDATE_QUESTION", "code": "full_name", "changes": {"label": "  "}}])
    assert p.operations == [] and "cannot be empty" in p.rejected[0].reason


def test_update_question_unknown_or_ambiguous_code():
    data = base_data()
    data["questions"].append(_q("age", "local-0", "INTEGER", "Duplicate code"))
    p = apply(
        [
            {"op": "UPDATE_QUESTION", "code": "ghost", "changes": {"hint": "x"}},
            {"op": "UPDATE_QUESTION", "code": "age", "changes": {"hint": "x"}},
        ],
        data,
    )
    assert p.operations == []
    assert "no question" in p.rejected[0].reason and "more than one" in p.rejected[1].reason


def test_change_type_between_choice_types_keeps_options():
    p = apply([{"op": "UPDATE_QUESTION", "code": "water_source", "changes": {"type": "MULTIPLE_CHOICE"}}])
    q = by_code(p.result, "water_source")
    assert q["type"] == "MULTIPLE_CHOICE" and len(q["choices"]) == 3


def test_change_text_to_multiple_choice_together_with_options():
    p = apply(
        [
            {"op": "UPDATE_QUESTION", "code": "full_name", "changes": {"type": "MULTIPLE_CHOICE"}},
            {"op": "UPDATE_CHOICES", "code": "full_name", "mode": "ADD", "choices": [{"label": "Alpha"}, {"label": "Beta"}]},
        ]
    )
    assert len(p.operations) == 2 and not p.rejected
    q = by_code(p.result, "full_name")
    assert q["type"] == "MULTIPLE_CHOICE" and [c["value"] for c in q["choices"]] == ["ALPHA", "BETA"]


def test_change_to_choice_type_without_options_is_rejected():
    p = apply([{"op": "UPDATE_QUESTION", "code": "full_name", "changes": {"type": "SINGLE_CHOICE"}}])
    assert p.operations == [] and "at least two answer options" in p.rejected[0].reason
    assert by_code(p.result, "full_name")["type"] == "SHORT_TEXT"


def test_change_choice_to_text_clears_options_visibly():
    p = apply([{"op": "UPDATE_QUESTION", "code": "water_source", "changes": {"type": "SHORT_TEXT"}}])
    assert by_code(p.result, "water_source")["choices"] == []
    assert any("answer option(s) were removed" in w for w in p.warnings)
    assert {c.kind for c in p.modified[0].choices} == {"REMOVED"}


def test_change_number_to_text_drops_numeric_limits_visibly():
    p = apply([{"op": "UPDATE_QUESTION", "code": "age", "changes": {"type": "SHORT_TEXT"}}])
    q = by_code(p.result, "age")
    assert q["min_value"] is None and q["max_value"] is None
    assert any("minimum/maximum value rule was removed" in w for w in p.warnings)


def test_type_change_that_would_break_other_skip_logic_is_rejected():
    # 'pregnant' shows only when gender == 'FEMALE'; a multiple-choice gender needs 'FEMALE' in gender.
    p = apply([{"op": "UPDATE_QUESTION", "code": "gender", "changes": {"type": "MULTIPLE_CHOICE"}}])
    assert p.operations == [] and "Skip logic on" in p.rejected[0].reason
    assert by_code(p.result, "gender")["type"] == "SINGLE_CHOICE"


def test_type_change_of_a_saved_question_warns_about_collected_answers():
    data = base_data()
    data["questions"][0]["id"] = "11111111-1111-1111-1111-111111111111"
    p = apply([{"op": "UPDATE_QUESTION", "code": "full_name", "changes": {"type": "LONG_TEXT"}}], data)
    assert any("already saved" in w for w in p.warnings)


def test_update_question_move_to_other_section_leaves_group_and_goes_to_end_of_section():
    p = apply([{"op": "UPDATE_QUESTION", "code": "household_size", "changes": {"section_ref": "S2"}}])
    q = by_code(p.result, "household_size")
    assert q["section_id"] == "local-1" and q["group_id"] is None
    assert codes(p.result) == ["full_name", "age", "gender", "pregnant", "symptoms", "clinic_visits", "household_size", "water_source"]
    assert any("left its group" in w for w in p.warnings)
    assert "Section" in {f.label for f in p.modified[0].fields}


def test_update_question_relevance_can_be_set_and_cleared_and_is_validated():
    p = apply(
        [
            {"op": "UPDATE_QUESTION", "code": "clinic_visits", "changes": {"relevance_expression": "age >= 18"}},
            {"op": "UPDATE_QUESTION", "code": "pregnant", "changes": {"relevance_expression": None}},
            {"op": "UPDATE_QUESTION", "code": "full_name", "changes": {"relevance_expression": "clinic_visits > 1"}},  # refers to a LATER question
        ]
    )
    assert len(p.operations) == 2 and len(p.rejected) == 1
    assert by_code(p.result, "clinic_visits")["relevance_expression"] == "age >= 18"
    assert by_code(p.result, "pregnant")["relevance_expression"] is None
    assert "Skip logic" in p.rejected[0].reason


def test_update_question_rejects_overlong_text_instead_of_cutting_it():
    p = apply([{"op": "UPDATE_QUESTION", "code": "full_name", "changes": {"label": "x" * 1500}}])
    assert p.operations == [] and "too long" in p.rejected[0].reason


# --------------------------------------------------------------------------
# DELETE_QUESTION
# --------------------------------------------------------------------------


def test_delete_question_is_shown_with_its_original_content():
    p = apply([{"op": "DELETE_QUESTION", "code": "clinic_visits"}])
    assert "clinic_visits" not in codes(p.result)
    assert len(p.deleted) == 1
    d = p.deleted[0]
    assert (d.key, d.title, d.position_before) == ("clinic_visits", "Clinic visits this year", 6)
    assert d.before["type"] == "INTEGER"
    assert p.summary.deleted_questions == 1 and not p.requires_confirmation


def test_deleting_a_question_clears_skip_logic_that_depended_on_it_visibly():
    p = apply([{"op": "DELETE_QUESTION", "code": "gender"}])
    assert by_code(p.result, "pregnant")["relevance_expression"] is None
    assert any("Skip logic on" in w and "pregnant" in w for w in p.warnings)
    assert [m.key for m in p.modified] == ["pregnant"]  # the side effect is itself shown as a modification


def test_cannot_delete_a_question_other_answers_cascade_from():
    data = base_data()
    data["questions"][2]["id"] = "gender-id"
    data["questions"][4]["cascade_parent_question_id"] = "gender-id"
    p = apply([{"op": "DELETE_QUESTION", "code": "gender"}], data)
    assert p.operations == [] and "depend on it" in p.rejected[0].reason


def test_cannot_delete_a_question_used_in_a_calculation():
    data = base_data()
    data["questions"][5]["calculation_expression"] = "age * 12"
    p = apply([{"op": "DELETE_QUESTION", "code": "age"}], data)
    assert p.operations == [] and "calculation" in p.rejected[0].reason


def test_delete_unknown_question_is_rejected():
    p = apply([{"op": "DELETE_QUESTION", "code": "ghost"}])
    assert p.operations == [] and not p.has_changes


# --------------------------------------------------------------------------
# ADD_SECTION
# --------------------------------------------------------------------------


def test_add_section_defaults_to_the_end():
    p = apply([{"op": "ADD_SECTION", "title": "Employment", "description": "Work and income"}])
    assert section_titles(p.result) == ["Demographics", "Health", "Household", "Employment"]
    assert p.result["sections"][3]["description"] == "Work and income"
    assert p.added[0].item_type == "section" and p.summary.added_sections == 1


def test_add_section_in_the_middle_keeps_every_question_in_its_own_section():
    """Unsaved sections are addressed as local-<index>; inserting one must not re-point anything."""
    p = apply([{"op": "ADD_SECTION", "title": "Consent", "position": 1}])
    assert section_titles(p.result) == ["Consent", "Demographics", "Health", "Household"]
    expected = {"full_name": "local-1", "age": "local-1", "gender": "local-1", "pregnant": "local-2", "symptoms": "local-2", "clinic_visits": "local-2", "household_size": "local-3", "water_source": "local-3"}
    assert {q["code"]: q["section_id"] for q in p.result["questions"]} == expected
    assert p.result["groups"][0]["section_id"] == "local-3"
    assert not p.modified  # nothing about the existing questions actually changed


def test_new_section_can_be_filled_in_the_same_batch_with_temp_ref():
    p = apply(
        [
            {"op": "ADD_SECTION", "title": "Employment", "temp_ref": "emp"},
            {"op": "ADD_QUESTION", "section_ref": "emp", "question": {"code": "employed", "label": "Do you work?", "type": "YES_NO"}},
            {"op": "ADD_QUESTION", "section_ref": "emp", "after_code": "employed", "question": {"code": "job", "label": "What is your job?", "type": "SHORT_TEXT", "relevance_expression": "employed == 'YES'"}},
        ]
    )
    assert len(p.operations) == 3 and not p.rejected
    assert codes(p.result)[-2:] == ["employed", "job"]
    assert by_code(p.result, "job")["section_id"] == "local-3"


def test_add_section_validation():
    p = apply(
        [
            {"op": "ADD_SECTION", "title": "   "},
            {"op": "ADD_SECTION", "title": "One", "temp_ref": "S2"},  # clashes with an existing alias
            {"op": "ADD_SECTION", "title": "Two", "temp_ref": "x"},
            {"op": "ADD_SECTION", "title": "Three", "temp_ref": "x"},  # duplicate temp ref
        ]
    )
    assert len(p.operations) == 1
    assert len(p.rejected) == 3


# --------------------------------------------------------------------------
# UPDATE_SECTION
# --------------------------------------------------------------------------


def test_update_section_title_and_description():
    p = apply([{"op": "UPDATE_SECTION", "section_ref": "S2", "changes": {"title": "Health status", "description": "Illness and clinic use"}}])
    assert p.result["sections"][1]["title"] == "Health status"
    assert p.modified[0].item_type == "section" and p.modified[0].key == "S2"
    assert [f.field for f in p.modified[0].fields] == ["title", "description"]


def test_update_section_cannot_blank_the_title():
    p = apply([{"op": "UPDATE_SECTION", "section_ref": "S1", "changes": {"title": ""}}])
    assert p.operations == [] and "cannot be empty" in p.rejected[0].reason


def test_moving_a_section_moves_its_questions_and_keeps_links_correct():
    p = apply([{"op": "UPDATE_SECTION", "section_ref": "S3", "changes": {"position": 1}}])
    assert section_titles(p.result) == ["Household", "Demographics", "Health"]
    assert codes(p.result) == ["household_size", "water_source", "full_name", "age", "gender", "pregnant", "symptoms", "clinic_visits"]
    sec = {q["code"]: q["section_id"] for q in p.result["questions"]}
    assert sec["household_size"] == "local-0" and sec["full_name"] == "local-1" and sec["clinic_visits"] == "local-2"
    assert p.result["groups"][0]["section_id"] == "local-0"
    assert p.summary.reordered_sections == 3
    assert {o.item_type for o in p.order_changes} == {"question", "section"}


def test_moving_a_section_past_the_one_its_skip_logic_depends_on_is_rejected():
    # Health's 'pregnant' depends on 'gender' in Demographics, so Health may not go before Demographics.
    p = apply([{"op": "UPDATE_SECTION", "section_ref": "S2", "changes": {"position": 1}}])
    assert p.operations == [] and "Skip logic on" in p.rejected[0].reason


def test_moving_a_section_leaves_a_deliberately_interleaved_list_alone():
    data = base_data()
    data["questions"][0], data["questions"][3] = data["questions"][3], data["questions"][0]  # no longer section-ordered
    before = [q["code"] for q in data["questions"]]
    p = apply([{"op": "UPDATE_SECTION", "section_ref": "S3", "changes": {"position": 1}}], data)
    assert codes(p.result) == before
    assert section_titles(p.result)[0] == "Household"


# --------------------------------------------------------------------------
# DELETE_SECTION
# --------------------------------------------------------------------------


def test_delete_section_moves_its_questions_by_default_and_nothing_is_lost():
    p = apply([{"op": "DELETE_SECTION", "section_ref": "S2"}])
    assert section_titles(p.result) == ["Demographics", "Household"]
    assert len(p.result["questions"]) == 8  # no question deleted
    assert by_code(p.result, "pregnant")["section_id"] == "local-0"  # first remaining section, like the builder's Remove
    assert [d.item_type for d in p.deleted] == ["section"] and p.deleted[0].before["question_count"] == 3
    assert any("were moved to" in w for w in p.warnings)
    assert not p.requires_confirmation


def test_delete_section_can_move_questions_to_a_chosen_section():
    p = apply([{"op": "DELETE_SECTION", "section_ref": "S2", "move_to_section_ref": "S3"}])
    assert by_code(p.result, "symptoms")["section_id"] == "local-1"  # S3 is now the second section
    assert section_titles(p.result) == ["Demographics", "Household"]
    assert section_of(p.result, "symptoms") == "local-1" and codes(p.result).count("symptoms") == 1


def test_delete_section_with_questions_delete_removes_them_visibly_and_asks_nothing_silently():
    p = apply([{"op": "DELETE_SECTION", "section_ref": "S3", "questions": "DELETE"}])
    assert section_titles(p.result) == ["Demographics", "Health"]
    assert p.result["groups"] == []  # the group lived in that section
    assert {d.key for d in p.deleted if d.item_type == "question"} == {"household_size", "water_source"}
    assert any("will be deleted" in w for w in p.warnings)


def test_delete_section_refuses_the_last_section_and_bad_combinations():
    data = base_data()
    data["sections"] = data["sections"][:1]
    for q in data["questions"]:
        q["section_id"] = "local-0"
    data["groups"] = []
    for q in data["questions"]:
        q.pop("group_id", None)
    p = apply([{"op": "DELETE_SECTION", "section_ref": "S1", "questions": "DELETE"}], data)
    assert p.operations == [] and "at least one section" in p.rejected[0].reason

    p = apply(
        [
            {"op": "DELETE_SECTION", "section_ref": "S2", "move_to_section_ref": "S2"},
            {"op": "DELETE_SECTION", "section_ref": "S2", "questions": "DELETE", "move_to_section_ref": "S1"},
        ]
    )
    assert p.operations == [] and len(p.rejected) == 2


def test_section_references_to_a_section_deleted_earlier_in_the_batch_are_rejected():
    p = apply(
        [
            {"op": "DELETE_SECTION", "section_ref": "S3"},
            {"op": "ADD_QUESTION", "section_ref": "S3", "question": {"label": "x", "type": "SHORT_TEXT"}},
        ]
    )
    assert len(p.operations) == 1 and "already removed" in p.rejected[0].reason


def test_saved_sections_are_addressed_by_alias_or_real_id_and_keep_their_ids():
    data = base_data()
    ids = ["sec-aaa", "sec-bbb", "sec-ccc"]
    for s, i in zip(data["sections"], ids):
        s["id"] = i
    for q in data["questions"]:
        q["section_id"] = ids[int(q["section_id"][-1])]
    data["groups"][0]["section_id"] = "sec-ccc"
    p = apply(
        [
            {"op": "ADD_SECTION", "title": "New one", "position": 1},
            {"op": "UPDATE_SECTION", "section_ref": "sec-bbb", "changes": {"title": "Health (edited)"}},
            {"op": "DELETE_SECTION", "section_ref": "S3"},  # = sec-ccc
        ],
        data,
    )
    assert len(p.operations) == 3
    assert [s.get("id") for s in p.result["sections"]] == [None, "sec-aaa", "sec-bbb"]
    assert by_code(p.result, "age")["section_id"] == "sec-aaa"  # saved sections keep real ids
    assert by_code(p.result, "water_source")["section_id"] == "sec-bbb"  # moved to the neighbouring section


# --------------------------------------------------------------------------
# REORDER_QUESTIONS
# --------------------------------------------------------------------------


def test_reorder_within_a_section_only_moves_the_listed_questions():
    p = apply([{"op": "REORDER_QUESTIONS", "ordered_codes": ["gender", "age", "full_name"]}])
    assert codes(p.result) == ["gender", "age", "full_name", "pregnant", "symptoms", "clinic_visits", "household_size", "water_source"]
    assert p.summary.reordered_questions >= 2
    assert not p.deleted and not p.added


def test_reorder_subset_leaves_the_others_where_they_are():
    p = apply([{"op": "REORDER_QUESTIONS", "ordered_codes": ["clinic_visits", "pregnant"]}])
    assert codes(p.result) == ["full_name", "age", "gender", "pregnant", "symptoms", "clinic_visits", "household_size", "water_source"][:3] + ["clinic_visits", "symptoms", "pregnant", "household_size", "water_source"]
    assert codes(p.result).index("clinic_visits") < codes(p.result).index("pregnant")


def test_reorder_across_sections_needs_a_target_section():
    p = apply([{"op": "REORDER_QUESTIONS", "ordered_codes": ["age", "clinic_visits"]}])
    assert p.operations == [] and "different sections" in p.rejected[0].reason


def test_reorder_with_section_ref_moves_questions_and_drops_stale_groups():
    p = apply([{"op": "REORDER_QUESTIONS", "ordered_codes": ["household_size", "clinic_visits"], "section_ref": "S2"}])
    assert by_code(p.result, "household_size")["section_id"] == "local-1"
    assert by_code(p.result, "household_size")["group_id"] is None
    assert by_code(p.result, "clinic_visits")["section_id"] == "local-1"
    sec = [q["section_id"] for q in p.result["questions"]]
    assert sec == sorted(sec)  # still reads top to bottom by section


def test_reorder_that_would_break_skip_logic_is_rejected():
    p = apply([{"op": "REORDER_QUESTIONS", "ordered_codes": ["pregnant", "gender"], "section_ref": "S2"}])
    assert p.operations == [] and "Skip logic on" in p.rejected[0].reason


def test_reorder_validation():
    p = apply(
        [
            {"op": "REORDER_QUESTIONS", "ordered_codes": ["age", "age"]},
            {"op": "REORDER_QUESTIONS", "ordered_codes": ["age", "ghost"]},
        ]
    )
    assert p.operations == [] and len(p.rejected) == 2


# --------------------------------------------------------------------------
# UPDATE_CHOICES
# --------------------------------------------------------------------------


def test_choices_add_appends_and_derives_values():
    p = apply([{"op": "UPDATE_CHOICES", "code": "gender", "mode": "ADD", "choices": [{"label": "Prefer not to say"}]}])
    assert [c["value"] for c in by_code(p.result, "gender")["choices"]] == ["MALE", "FEMALE", "OTHER", "PREFER_NOT_TO_SAY"]
    assert [(c.kind, c.value) for c in p.modified[0].choices] == [("ADDED", "PREFER_NOT_TO_SAY")]


def test_choices_add_refuses_an_existing_value():
    p = apply([{"op": "UPDATE_CHOICES", "code": "gender", "mode": "ADD", "choices": [{"value": "MALE", "label": "Man"}]}])
    assert p.operations == [] and "already exists" in p.rejected[0].reason


def test_choices_update_labels_translates_without_touching_values_or_ids():
    data = base_data()
    for i, c in enumerate(data["questions"][2]["choices"]):
        c["id"] = f"choice-{i}"
    p = apply(
        [
            {"op": "UPDATE_QUESTION", "code": "gender", "changes": {"label": "Jinsi"}},
            {"op": "UPDATE_CHOICES", "code": "gender", "mode": "UPDATE_LABELS", "choices": [{"value": "MALE", "label": "Namiji"}, {"value": "FEMALE", "label": "Mace"}]},
        ],
        data,
    )
    q = by_code(p.result, "gender")
    assert q["label"] == "Jinsi"
    assert [(c["value"], c["label"], c.get("id")) for c in q["choices"]] == [("MALE", "Namiji", "choice-0"), ("FEMALE", "Mace", "choice-1"), ("OTHER", "Other", "choice-2")]
    assert {c.kind for c in p.modified[0].choices} == {"CHANGED"}


def test_choices_update_labels_needs_existing_values():
    p = apply([{"op": "UPDATE_CHOICES", "code": "gender", "mode": "UPDATE_LABELS", "choices": [{"value": "NONSENSE", "label": "x"}]}])
    assert p.operations == [] and "no answer option" in p.rejected[0].reason


def test_choices_remove_and_the_two_option_minimum():
    p = apply([{"op": "UPDATE_CHOICES", "code": "water_source", "mode": "REMOVE", "remove_values": ["RIVER"]}])
    assert [c["value"] for c in by_code(p.result, "water_source")["choices"]] == ["TAP", "WELL"]
    assert any("removed" in w for w in p.warnings)

    p = apply([{"op": "UPDATE_CHOICES", "code": "water_source", "mode": "REMOVE", "remove_values": ["RIVER", "WELL"]}])
    assert p.operations == [] and "at least two" in p.rejected[0].reason

    p = apply([{"op": "UPDATE_CHOICES", "code": "water_source", "mode": "REMOVE", "remove_values": ["LAKE"]}])
    assert p.operations == [] and "no answer option" in p.rejected[0].reason


def test_choices_replace_keeps_existing_options_that_stay_and_reports_dropped_ones():
    data = base_data()
    for i, c in enumerate(data["questions"][4]["choices"]):
        c["id"] = f"sym-{i}"
    p = apply(
        [
            {
                "op": "UPDATE_CHOICES",
                "code": "symptoms",
                "mode": "REPLACE",
                "choices": [{"value": "COUGH", "label": "Dry cough"}, {"label": "Headache"}, {"value": "FEVER", "label": "Fever"}],
            }
        ],
        data,
    )
    choices = by_code(p.result, "symptoms")["choices"]
    assert [(c["value"], c["label"], c.get("id")) for c in choices] == [("COUGH", "Dry cough", "sym-1"), ("HEADACHE", "Headache", None), ("FEVER", "Fever", "sym-0")]
    assert any("RASH" in w for w in p.warnings)
    assert {(c.kind, c.value) for c in p.modified[0].choices} == {("CHANGED", "COUGH"), ("ADDED", "HEADACHE"), ("REMOVED", "RASH")}


def test_choices_replace_with_fewer_than_two_is_rejected():
    p = apply([{"op": "UPDATE_CHOICES", "code": "symptoms", "mode": "REPLACE", "choices": [{"label": "Only one"}]}])
    assert p.operations == [] and "at least two" in p.rejected[0].reason


def test_choices_on_a_non_choice_question_are_rejected():
    p = apply([{"op": "UPDATE_CHOICES", "code": "age", "mode": "ADD", "choices": [{"label": "x"}]}])
    assert p.operations == [] and "no answer options" in p.rejected[0].reason


def test_removing_an_option_that_skip_logic_uses_is_rejected():
    p = apply([{"op": "UPDATE_CHOICES", "code": "gender", "mode": "REMOVE", "remove_values": ["FEMALE"]}])
    assert p.operations == [] and "Skip logic on" in p.rejected[0].reason
    assert len(by_code(p.result, "gender")["choices"]) == 3


# --------------------------------------------------------------------------
# UPDATE_VALIDATION
# --------------------------------------------------------------------------


def test_validation_sets_changes_and_clears_ranges():
    p = apply(
        [
            {"op": "UPDATE_VALIDATION", "code": "age", "validation": {"min_value": 18, "max_value": 99, "is_required": True}},
            {"op": "UPDATE_VALIDATION", "code": "clinic_visits", "validation": {"min_value": 0}},
            {"op": "UPDATE_VALIDATION", "code": "full_name", "validation": {"min_length": 2, "max_length": 80, "regex_pattern": "^[A-Za-z ]+$"}},
        ]
    )
    assert len(p.operations) == 3
    age = by_code(p.result, "age")
    assert (age["min_value"], age["max_value"], age["is_required"]) == (18, 99, True)
    assert by_code(p.result, "full_name")["regex_pattern"] == "^[A-Za-z ]+$"

    cleared = apply([{"op": "UPDATE_VALIDATION", "code": "age", "validation": {"min_value": None}}])
    assert by_code(cleared.result, "age")["min_value"] is None and by_code(cleared.result, "age")["max_value"] == 120


def test_validation_is_checked_against_the_question_type_and_ranges():
    p = apply(
        [
            {"op": "UPDATE_VALIDATION", "code": "full_name", "validation": {"min_value": 1}},  # text question
            {"op": "UPDATE_VALIDATION", "code": "age", "validation": {"max_length": 5}},  # number question
            {"op": "UPDATE_VALIDATION", "code": "age", "validation": {"min_value": 200}},  # above existing max 120
            {"op": "UPDATE_VALIDATION", "code": "full_name", "validation": {"min_length": 50, "max_length": 5}},
            {"op": "UPDATE_VALIDATION", "code": "full_name", "validation": {"regex_pattern": "(a+)+$"}},
            {"op": "UPDATE_VALIDATION", "code": "full_name", "validation": {"regex_pattern": "([unclosed"}},
            {"op": "UPDATE_VALIDATION", "code": "age", "validation": {"max_value": 99.5}},  # whole numbers only
        ]
    )
    assert p.operations == [] and len(p.rejected) == 7
    assert not p.has_changes


def test_required_flag_through_validation_and_update_question():
    p = apply(
        [
            {"op": "UPDATE_VALIDATION", "code": "gender", "validation": {"is_required": True}},
            {"op": "UPDATE_QUESTION", "code": "symptoms", "changes": {"is_required": True}},
        ]
    )
    assert by_code(p.result, "gender")["is_required"] and by_code(p.result, "symptoms")["is_required"]


# --------------------------------------------------------------------------
# Batches, guards and safety
# --------------------------------------------------------------------------


def test_one_bad_operation_does_not_discard_the_good_ones():
    p = apply(
        [
            {"op": "UPDATE_QUESTION", "code": "age", "changes": {"hint": "In years"}},
            {"op": "DELETE_QUESTION", "code": "no_such_question"},
            {"op": "UPDATE_QUESTION", "code": "full_name", "changes": {"is_required": True}},
        ]
    )
    assert [o.index for o in p.operations] == [0, 2]
    assert [r.index for r in p.rejected] == [1]
    assert by_code(p.result, "age")["hint"] == "In years"


def test_a_rejected_operation_takes_its_dependants_with_it():
    p = apply(
        [
            {"op": "ADD_QUESTION", "section_ref": "S1", "question": {"code": "bad", "label": "Pick", "type": "SINGLE_CHOICE"}},  # no options -> invalid
            {"op": "UPDATE_QUESTION", "code": "bad", "changes": {"hint": "depends on the one above"}},
        ]
    )
    assert p.operations == [] and len(p.rejected) == 2
    assert "bad" not in codes(p.result)


def test_the_input_snapshot_is_never_modified():
    s = snap()
    before = copy.deepcopy(s.model_dump())
    run(
        s,
        [
            {"op": "DELETE_QUESTION", "code": "gender"},
            {"op": "UPDATE_SECTION", "section_ref": "S3", "changes": {"position": 1}},
            {"op": "UPDATE_CHOICES", "code": "water_source", "mode": "ADD", "choices": [{"label": "Borehole"}]},
        ],
    )
    assert s.model_dump() == before


def test_applying_no_operations_changes_nothing_and_the_result_round_trips():
    p = apply([])
    assert not p.has_changes and p.operations == [] and p.rejected == []
    again = preview_operations(Snapshot.model_validate(p.result), [])  # the result is a valid snapshot
    assert again.result == p.result
    assert [q["code"] for q in p.result["questions"]] == [q["code"] for q in base_data()["questions"]]


def test_unknown_fields_on_items_are_carried_through():
    data = base_data()
    data["questions"][0]["custom_flag"] = {"keep": "me"}
    data["sections"][0]["icon"] = "star"
    p = apply([{"op": "UPDATE_QUESTION", "code": "full_name", "changes": {"hint": "x"}}], data)
    assert by_code(p.result, "full_name")["custom_flag"] == {"keep": "me"}
    assert p.result["sections"][0]["icon"] == "star"


def test_existing_problems_in_the_questionnaire_are_not_blamed_on_the_edit():
    data = base_data()
    data["questions"][5]["relevance_expression"] = "age contains 4"  # already unsupported before any edit
    p = apply([{"op": "UPDATE_QUESTION", "code": "full_name", "changes": {"hint": "x"}}], data)
    assert len(p.operations) == 1 and not p.rejected


def test_blank_in_progress_questions_do_not_break_editing():
    data = base_data()
    data["questions"].append({"code": "", "label": "", "type": "SHORT_TEXT", "section_id": "local-2"})
    p = apply([{"op": "UPDATE_QUESTION", "code": "age", "changes": {"hint": "x"}}], data)
    assert len(p.operations) == 1
    assert len(p.result["questions"]) == 9


def test_deleting_every_question_is_blocked_and_nothing_changes():
    ops = [{"op": "DELETE_QUESTION", "code": c} for c in codes(base_to_result())]
    p = apply(ops)
    assert p.blocked and "every question" in p.blocked
    assert p.operations == [] and len(p.rejected) == 8
    assert not p.has_changes and p.deleted == []
    assert codes(p.result) == codes(base_to_result())


def test_blocking_also_covers_wiping_through_a_mix_of_operations():
    data = base_data()
    data["sections"] = data["sections"][:1]
    for q in data["questions"]:
        q["section_id"] = "local-0"
        q.pop("group_id", None)
    data["groups"] = []
    p = apply([{"op": "DELETE_QUESTION", "code": q["code"]} for q in data["questions"]], data)
    assert p.blocked and len(p.result["questions"]) == 8


def test_large_deletions_require_explicit_confirmation():
    ops = [{"op": "DELETE_QUESTION", "code": c} for c in ("full_name", "age", "symptoms")]
    p = apply(ops)
    assert len(p.operations) == 3 and p.requires_confirmation and "3 of the 8" in p.confirmation_reasons[0]

    p = apply([{"op": "DELETE_QUESTION", "code": "age"}])
    assert not p.requires_confirmation  # a single deletion is shown, but needs no extra step


def test_deleting_most_sections_requires_confirmation():
    p = apply([{"op": "DELETE_SECTION", "section_ref": "S2"}, {"op": "DELETE_SECTION", "section_ref": "S3"}])
    assert p.requires_confirmation and "sections" in p.confirmation_reasons[0]


def test_zero_question_questionnaires_can_still_be_extended():
    data = {"sections": [{"title": "Section 1"}], "groups": [], "questions": []}
    p = apply([{"op": "ADD_QUESTION", "question": {"label": "What is your name?", "type": "SHORT_TEXT", "code": "name"}}], data)
    assert codes(p.result) == ["name"] and p.result["questions"][0]["section_id"] == "local-0"


def test_missing_sections_are_synthesised_like_the_builder_does():
    data = {"sections": [], "groups": [], "questions": [_q("a", None)]}
    p = apply([{"op": "ADD_QUESTION", "question": {"label": "b?", "type": "SHORT_TEXT", "code": "b"}}], data)
    assert section_titles(p.result) == ["Section 1"] and codes(p.result) == ["a", "b"]


def test_dangling_section_references_are_reported_not_hidden():
    data = base_data()
    data["questions"][0]["section_id"] = "a-section-that-does-not-exist"
    p = apply([{"op": "UPDATE_QUESTION", "code": "age", "changes": {"hint": "x"}}], data)
    assert any("no longer exists" in w for w in p.warnings)


def test_snapshot_rejects_unknown_question_types():
    data = base_data()
    data["questions"][0]["type"] = "NOT_A_TYPE"
    with pytest.raises(Exception):
        snap(data)


# --------------------------------------------------------------------------
# Preview contents
# --------------------------------------------------------------------------


def test_preview_lists_added_modified_and_deleted_items_together():
    p = apply(
        [
            {"op": "ADD_QUESTION", "section_ref": "S1", "question": {"code": "edu", "label": "Education?", "type": "SHORT_TEXT"}},
            {"op": "UPDATE_QUESTION", "code": "age", "changes": {"label": "Age (years)"}},
            {"op": "DELETE_QUESTION", "code": "clinic_visits"},
            {"op": "ADD_SECTION", "title": "Employment"},
        ]
    )
    assert [i.key for i in p.added if i.item_type == "question"] == ["edu"]
    assert [i.key for i in p.modified] == ["age"]
    assert [i.key for i in p.deleted] == ["clinic_visits"]
    assert [i.title for i in p.added if i.item_type == "section"] == ["Employment"]
    s = p.summary
    assert (s.added_questions, s.modified_questions, s.deleted_questions, s.added_sections) == (1, 1, 1, 1)
    assert (s.questions_before, s.questions_after) == (8, 8)
    assert p.has_changes
    age = p.modified[0]
    assert age.before["label"] == "How old are you?" and age.after["label"] == "Age (years)"
    assert (age.fields[0].before, age.fields[0].after) == ("How old are you?", "Age (years)")


def test_every_applied_operation_can_be_resubmitted_verbatim():
    ops = [
        {"op": "UPDATE_QUESTION", "code": "age", "changes": {"hint": "In years"}},
        {"op": "ADD_SECTION", "title": "Employment", "temp_ref": "emp"},
        {"op": "ADD_QUESTION", "section_ref": "emp", "question": {"code": "job", "label": "Job?", "type": "SHORT_TEXT"}},
    ]
    first = apply(ops)
    again = apply([o.raw for o in first.operations])
    assert again.result == first.result
    # Unticking an operation others depend on is reported, not silently accepted.
    partial = apply([ops[0], ops[2]])
    assert [o.index for o in partial.operations] == [0] and "no section" in partial.rejected[0].reason
