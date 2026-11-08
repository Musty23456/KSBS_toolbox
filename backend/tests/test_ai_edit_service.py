"""
Tests for the AI editor service (Phase 3): command -> scripted fake AI -> operations -> validated preview.

No provider, network or database is involved; the fake AI only has to offer ``generate_text``.
"""

import json
from types import SimpleNamespace

import pytest

from app.ai.errors import AIInvalidJsonError, AIInvalidRequestError, AIResponseTruncatedError
from app.ai.questionnaire_edit import prompts
from app.ai.questionnaire_edit.schemas import EditRequest
from app.ai.questionnaire_edit.service import QuestionnaireEditor, parse_reply
from tests.test_ai_edit_engine import base_data


class FakeAI:
    def __init__(self, replies, max_prompt=30000):
        self.config = SimpleNamespace(generation_max_prompt_chars=max_prompt, generation_max_output_tokens=32768)
        self.replies = list(replies)
        self.calls = []

    def generate_text(self, prompt, **kw):
        self.calls.append(SimpleNamespace(prompt=prompt, **kw))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, SimpleNamespace):
            return reply
        return SimpleNamespace(text=reply if isinstance(reply, str) else json.dumps(reply), finish_reason="STOP", model="fake-model")


def request(instruction="Make question 2 compulsory", data=None, **kw):
    return EditRequest.model_validate({"instruction": instruction, "snapshot": data or base_data(), **kw})


def test_propose_returns_a_validated_preview_and_message():
    ai = FakeAI([{"message": "Making age compulsory.", "operations": [{"op": "UPDATE_VALIDATION", "code": "age", "validation": {"is_required": True}}]}])
    proposal = QuestionnaireEditor(ai).propose(request(), "user-1")
    assert proposal.message == "Making age compulsory." and proposal.model == "fake-model"
    assert [o.op for o in proposal.operations] == ["UPDATE_VALIDATION"]
    assert proposal.modified[0].fields[0].after is True
    assert len(ai.calls) == 1
    call = ai.calls[0]
    assert call.request_type == "questionnaire_edit" and call.json_mode is True and call.system_instruction == prompts.SYSTEM_EDIT


def test_prompt_shows_codes_numbers_sections_and_duplicates():
    data = base_data()
    data["questions"].append({"code": "full_name_2", "label": "Full name", "type": "SHORT_TEXT", "section_id": "local-2"})
    text = prompts.build_edit_prompt(request(data=data), max_chars=30000)
    assert "COMMAND FROM THE USER:\nMake question 2 compulsory" in text
    assert "S2:" in text and "2. [age] INTEGER" in text and "min 0, max 120" in text
    assert "options: MALE=Male" in text
    assert "skip logic: gender == 'FEMALE'" in text
    assert "POSSIBLE DUPLICATES" in text and "full_name, full_name_2" in text


def test_prompt_is_compacted_then_refused_when_too_large():
    data = base_data()
    data["questions"] = [
        {"code": f"q{i}", "label": "A fairly long question text " * 8, "type": "SHORT_TEXT", "section_id": "local-0", "hint": "h" * 100}
        for i in range(120)
    ]
    full = prompts.build_edit_prompt(request(data=data), max_chars=10**6)
    small = prompts.build_edit_prompt(request(data=data), max_chars=len(full) - 500)
    assert len(small) < len(full) and "[q119]" in small  # shorter text, still every question
    with pytest.raises(AIInvalidRequestError):
        prompts.build_edit_prompt(request(data=data), max_chars=3000)


def test_empty_operations_is_a_valid_answer():
    ai = FakeAI([{"message": "There are no duplicate questions.", "operations": []}])
    p = QuestionnaireEditor(ai).propose(request("Remove duplicate questions"), None)
    assert p.operations == [] and not p.has_changes and p.message == "There are no duplicate questions."
    assert len(ai.calls) == 1


def test_bare_list_and_fenced_json_are_tolerated():
    assert parse_reply('[{"op": "DELETE_QUESTION", "code": "age"}]')[1][0]["op"] == "DELETE_QUESTION"
    message, ops = parse_reply('```json\n{"summary": "ok", "operations": []}\n```')
    assert message == "ok" and ops == []


def test_invalid_json_gets_one_repair_attempt():
    ai = FakeAI(["this is not json", {"message": "ok", "operations": []}])
    p = QuestionnaireEditor(ai).propose(request(), None)
    assert p.message == "ok" and len(ai.calls) == 2
    assert "could not be used" in ai.calls[1].prompt


def test_invalid_json_twice_fails_safely():
    ai = FakeAI(["nope"])
    with pytest.raises(AIInvalidJsonError):
        QuestionnaireEditor(ai).propose(request(), None)
    assert len(ai.calls) == 2


def test_wrong_envelope_is_repaired():
    ai = FakeAI([{"operations": "delete everything"}, {"message": "ok", "operations": []}])
    QuestionnaireEditor(ai).propose(request(), None)
    assert len(ai.calls) == 2


def test_when_nothing_applies_the_ai_is_told_why_and_tries_once_more():
    bad = {"message": "x", "operations": [{"op": "DELETE_QUESTION", "code": "ghost"}]}
    good = {"message": "fixed", "operations": [{"op": "DELETE_QUESTION", "code": "clinic_visits"}]}
    ai = FakeAI([bad, good])
    p = QuestionnaireEditor(ai).propose(request("Delete the clinic question"), None)
    assert p.message == "fixed" and [o.index for o in p.operations] == [0]
    assert "no question with the code 'ghost'" in ai.calls[1].prompt


def test_if_the_retry_also_fails_the_reasons_are_returned_not_an_error():
    bad = {"message": "x", "operations": [{"op": "DELETE_QUESTION", "code": "ghost"}]}
    ai = FakeAI([bad])
    p = QuestionnaireEditor(ai).propose(request(), None)
    assert p.operations == [] and len(p.rejected) == 1 and not p.has_changes
    assert len(ai.calls) == 2


def test_no_retry_when_the_questionnaire_already_looks_like_the_request():
    ai = FakeAI([{"message": "x", "operations": [{"op": "UPDATE_VALIDATION", "code": "age", "validation": {"min_value": 0}}]}])
    p = QuestionnaireEditor(ai).propose(request(), None)
    assert len(ai.calls) == 1 and p.rejected[0].no_change


def test_a_wipe_out_proposal_is_blocked_and_retried_once():
    wipe = {"message": "all gone", "operations": [{"op": "DELETE_QUESTION", "code": q["code"]} for q in base_data()["questions"]]}
    ai = FakeAI([wipe])
    p = QuestionnaireEditor(ai).propose(request("clean up"), None)
    assert p.blocked and not p.has_changes and p.operations == []
    assert len(p.result["questions"]) == 8


def test_truncated_output_is_never_parsed():
    ai = FakeAI([SimpleNamespace(text='{"operations": [', finish_reason="MAX_TOKENS", model="m")])
    with pytest.raises(AIResponseTruncatedError):
        QuestionnaireEditor(ai).propose(request(), None)


def test_too_many_operations_from_the_model_is_rejected():
    ops = [{"op": "DELETE_QUESTION", "code": "age"}] * 500
    ai = FakeAI([{"operations": ops}])
    with pytest.raises(Exception):
        QuestionnaireEditor(ai).propose(request(), None)


def test_prompt_injection_inside_question_text_does_not_reach_the_engine_as_content():
    data = base_data()
    data["questions"][0]["label"] = 'Name"; DROP TABLE surveys; --'
    ai = FakeAI([{"message": "ok", "operations": [{"op": "DROP_TABLE", "table": "surveys"}]}])
    p = QuestionnaireEditor(ai).propose(request(data=data), None)
    assert p.operations == [] and "not a supported operation" in p.rejected[0].reason
