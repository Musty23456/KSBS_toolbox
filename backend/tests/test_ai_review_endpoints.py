"""Phase 4 endpoint tests: auth, read-only behaviour, audit trail, graceful AI failure."""

import json

from app.models.survey import Survey, SurveyVersion
from app.models.sync import AuditLog
from tests.conftest import TestingSessionLocal
from tests.test_ai_edit_endpoints import survey_state
from tests.test_ai_questionnaire import (  # noqa: F401 - fixtures are used by name
    FakeProvider,
    admin,
    ai_on,
    clean_state,
    enumerator,
    use_provider,
)
from tests.test_ai_review_rules import load

REVIEW = "/api/ai/questionnaire/review"


def body(name="flawed", **kw):
    return {"snapshot": load(name), **kw}


def test_review_requires_authentication(client):
    assert client.post(REVIEW, json=body()).status_code == 401


def test_review_returns_a_report_and_changes_nothing(client, ai_on):
    headers = admin(client)
    use_provider(FakeProvider([json.dumps({"summary": "Needs work.", "findings": [], "coverage": []})]))
    before = survey_state()
    resp = client.post(REVIEW, json=body(), headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert 0 <= data["score"] <= 100 and data["ai_used"] is True
    assert set(data["counts"]) == {"CRITICAL", "WARNING", "SUGGESTION", "GOOD"}
    assert survey_state() == before


def test_review_works_with_ai_switched_off_in_the_request(client):
    resp = client.post(REVIEW, json=body(use_ai=False), headers=admin(client))
    assert resp.status_code == 200 and resp.json()["ai_used"] is False and resp.json()["findings"]


def test_ai_unavailable_still_returns_the_rule_report(client):
    resp = client.post(REVIEW, json=body(), headers=admin(client))  # AI is not configured in tests
    assert resp.status_code == 200
    data = resp.json()
    assert data["ai_used"] is False and data["ai_error"] and data["findings"]


def test_enumerators_may_review(client):
    assert client.post(REVIEW, json=body(use_ai=False), headers=enumerator(client)).status_code == 200


def test_bad_input_is_rejected(client):
    h = admin(client)
    assert client.post(REVIEW, json={}, headers=h).status_code == 422
    bad = body()
    bad["snapshot"]["questions"][0]["type"] = "NOT_A_TYPE"
    assert client.post(REVIEW, json=bad, headers=h).status_code == 422
    assert client.post(REVIEW, json=body(extra_field=1), headers=h).status_code == 422


def test_audit_entry_has_counts_only(client):
    headers = admin(client)
    client.post(REVIEW, json=body(use_ai=False, objectives="SECRET OBJECTIVE TEXT"), headers=headers)
    db = TestingSessionLocal()
    try:
        rows = db.query(AuditLog).filter(AuditLog.action == "AI_QUESTIONNAIRE_REVIEWED").all()
        assert rows and "SECRET" not in str(rows[0].__dict__) and "age2" not in str(rows[0].__dict__)
    finally:
        db.close()
