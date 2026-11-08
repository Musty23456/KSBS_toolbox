"""Phase 4 tests: the reviewer service with a scripted fake AI (no provider, network or database)."""

import json
from types import SimpleNamespace

import pytest

from app.ai.errors import AIDisabledError, AIResponseTruncatedError
from app.ai.questionnaire_review.schemas import ReviewRequest
from app.ai.questionnaire_review.service import QuestionnaireReviewer, accept_ai_findings, parse_review_reply
from tests.test_ai_review_rules import load


class FakeAI:
    def __init__(self, replies):
        self.config = SimpleNamespace(generation_max_prompt_chars=30000, generation_max_output_tokens=32768)
        self.replies = list(replies)
        self.calls = []

    def generate_text(self, prompt, **kw):
        self.calls.append(SimpleNamespace(prompt=prompt, **kw))
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(r, Exception):
            raise r
        if isinstance(r, SimpleNamespace):
            return r
        return SimpleNamespace(text=r if isinstance(r, str) else json.dumps(r), finish_reason="STOP", model="fake-model")


def req(name="flawed", **kw):
    return ReviewRequest.model_validate({"snapshot": load(name), **kw})


def ai_reply(findings=(), coverage=(), summary="Mixed."):
    return {"summary": summary, "findings": list(findings), "coverage": list(coverage)}


def test_review_without_ai_still_produces_a_full_report():
    ai = FakeAI([ai_reply()])
    report = QuestionnaireReviewer(ai).review(req(use_ai=False), "u1")
    assert ai.calls == [] and not report.ai_used
    assert report.counts["CRITICAL"] >= 2 and 0 <= report.score <= 100
    assert [f.severity for f in report.findings] == sorted((f.severity for f in report.findings), key=["CRITICAL", "WARNING", "SUGGESTION", "GOOD"].index)
    assert any("Only the built-in rule checks" in x for x in report.limitations)


def test_ai_failure_degrades_to_rules_only_with_a_safe_message():
    ai = FakeAI([AIDisabledError()])
    report = QuestionnaireReviewer(ai).review(req(), "u1")
    assert not report.ai_used and report.ai_error and report.findings and report.score < 100


def test_truncated_ai_answer_degrades_gracefully():
    ai = FakeAI([SimpleNamespace(text="{", finish_reason="MAX_TOKENS", model="m")])
    report = QuestionnaireReviewer(ai).review(req(), "u1")
    assert not report.ai_used and report.ai_error


def test_ai_findings_are_validated_and_merged():
    good = {"severity": "WARNING", "category": "CLARITY", "code": "age", "title": "Ambiguous age question",
            "explanation": "Which age?", "recommendation": "Say completed years.",
            "fix": {"op": "UPDATE_QUESTION", "code": "age", "changes": {"hint": "Age in completed years"}}}
    junk = [
        "not an object",
        {"severity": "CRITICAL", "category": "CLARITY", "code": "ghost", "title": "Invented code is dropped to a whole-form finding"},
        {"severity": "SUGGESTION", "category": "NOT_A_CATEGORY", "title": "bad category"},
        {"severity": "SUGGESTION", "category": "CLARITY", "title": ""},
        {"severity": "SUGGESTION", "category": "CLARITY", "code": "age", "title": "Fix aimed at another question",
         "fix": {"op": "DELETE_QUESTION", "code": "income"}},
    ]
    ai = FakeAI([ai_reply([good, *junk])])
    report = QuestionnaireReviewer(ai).review(req(), "u1")
    assert report.ai_used and report.model == "fake-model"
    by_title = {f.title: f for f in report.findings}
    assert by_title["Ambiguous age question"].fix and by_title["Ambiguous age question"].source == "AI"
    inv = by_title["Invented code is dropped to a whole-form finding"]
    assert inv.question_code is None and inv.severity == "WARNING"      # CRITICAL is reserved for provable defects
    assert "bad category" not in by_title
    assert by_title["Fix aimed at another question"].fix is None
    assert all(f.fix is None or f.source == "RULE" or f.question_code for f in report.findings)


def test_ai_does_not_repeat_what_the_rules_already_found():
    dup = {"severity": "WARNING", "category": "DUPLICATE", "code": "age2", "title": "Same question twice"}
    report = QuestionnaireReviewer(FakeAI([ai_reply([dup])])).review(req(), "u1")
    assert sum(1 for f in report.findings if f.category == "DUPLICATE" and f.question_code == "age2") == 1


def test_objective_coverage_from_the_ai():
    objs = "Measure satisfaction with clinic service\nAssess access to clean drinking water"
    cov = [
        {"objective": "Measure satisfaction with clinic service", "covered": True, "codes": ["clinic_rating", "ghost"], "note": "ok"},
        {"objective": "Assess access to clean drinking water", "covered": False, "codes": [], "note": "No water questions."},
    ]
    report = QuestionnaireReviewer(FakeAI([ai_reply(coverage=cov)])).review(req("well_designed", objectives=objs), "u1")
    assert report.objectives_checked
    assert [c.covered for c in report.coverage] == [True, False]
    assert report.coverage[0].question_codes == ["clinic_rating"]        # invented codes removed
    assert any(f.category == "COVERAGE" and "drinking water" in f.title for f in report.findings)


def test_incomplete_ai_coverage_falls_back_to_keywords():
    objs = "Measure satisfaction with clinic service\nAssess access to clean drinking water"
    report = QuestionnaireReviewer(FakeAI([ai_reply(coverage=[])])).review(req("well_designed", objectives=objs), "u1")
    assert len(report.coverage) == 2 and report.coverage[1].covered is False
    assert any("keywords only" in x for x in report.limitations)


def test_no_objectives_means_coverage_is_not_checked_and_says_so():
    report = QuestionnaireReviewer(FakeAI([ai_reply()])).review(req("well_designed"), "u1")
    assert not report.objectives_checked and report.coverage == []
    assert any("No research objectives" in x for x in report.limitations)


def test_bad_json_gets_one_repair_attempt():
    ai = FakeAI(["not json", ai_reply()])
    report = QuestionnaireReviewer(ai).review(req(), "u1")
    assert report.ai_used and len(ai.calls) == 2 and "could not be used" in ai.calls[1].prompt


def test_prompt_is_server_authored_and_carries_the_questionnaire():
    ai = FakeAI([ai_reply()])
    QuestionnaireReviewer(ai).review(req("well_designed", objectives="Understand clinic use"), "u1")
    call = ai.calls[0]
    assert call.request_type == "questionnaire_review" and call.json_mode is True
    assert "You only REVIEW" in call.system_instruction
    assert "[clinic_rating]" in call.prompt and "Understand clinic use" in call.prompt


def test_the_empty_questionnaire_does_not_call_the_ai():
    ai = FakeAI([ai_reply()])
    report = QuestionnaireReviewer(ai).review(req("minimal"), "u1")
    assert ai.calls == [] and report.score == 0


def test_parse_review_reply_rejects_wrong_shapes():
    with pytest.raises(Exception):
        parse_review_reply("[1,2]")
    with pytest.raises(Exception):
        parse_review_reply('{"findings": "x"}')
