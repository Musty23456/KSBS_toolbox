"""
Endpoint tests for the AI questionnaire editor and version history (Phase 3).

The provider is the scripted fake from the Phase 2 tests, so no key or network is needed. These tests
cover what the pure engine tests cannot: authentication, size limits, "preview only - nothing is saved",
the audit trail, and the version-history API and save-path changes.
"""

import json

from app.models.survey import Survey, SurveyVersion
from app.models.sync import AuditLog
from tests.conftest import TestingSessionLocal, register_and_login
from tests.test_ai_edit_engine import base_data
from tests.test_ai_questionnaire import (  # noqa: F401 - fixtures are used by name
    FakeProvider,
    admin,
    ai_on,
    clean_state,
    enumerator,
    use_provider,
)
from tests.test_surveys import _sample_survey_payload

PROPOSE = "/api/ai/questionnaire/edit/propose"
PREVIEW = "/api/ai/questionnaire/edit/preview"


def reply(operations, message="Done."):
    return json.dumps({"message": message, "operations": operations})


def body(instruction="Make question 2 compulsory", data=None):
    return {"instruction": instruction, "snapshot": data or base_data()}


def survey_state():
    db = TestingSessionLocal()
    try:
        return db.query(Survey).count(), db.query(SurveyVersion).count()
    finally:
        db.close()


# ------------------------------------------------------------------ propose


def test_propose_requires_authentication(client):
    assert client.post(PROPOSE, json=body()).status_code == 401
    assert client.post(PREVIEW, json={"snapshot": base_data(), "operations": []}).status_code == 401


def test_propose_returns_a_preview_and_saves_nothing(client, ai_on):
    headers = admin(client)
    provider = use_provider(FakeProvider([reply([{"op": "UPDATE_VALIDATION", "code": "age", "validation": {"is_required": True}}])]))
    before = survey_state()
    resp = client.post(PROPOSE, json=body(), headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["operations"][0]["op"] == "UPDATE_VALIDATION"
    assert data["modified"][0]["key"] == "age" and data["has_changes"] is True
    assert next(q for q in data["result"]["questions"] if q["code"] == "age")["is_required"] is True
    assert survey_state() == before
    assert len(provider.calls) == 1


def test_any_signed_in_role_may_use_the_editor(client, ai_on):
    headers = enumerator(client)
    use_provider(FakeProvider([reply([])]))
    assert client.post(PROPOSE, json=body(), headers=headers).status_code == 200


def test_propose_is_audited_with_counts_only(client, ai_on):
    headers = admin(client)
    use_provider(FakeProvider([reply([{"op": "DELETE_QUESTION", "code": "clinic_visits"}])]))
    assert client.post(PROPOSE, json=body("Delete the clinic visits question"), headers=headers).status_code == 200
    db = TestingSessionLocal()
    try:
        row = db.query(AuditLog).filter(AuditLog.action == "AI_QUESTIONNAIRE_EDIT_PROPOSED").one()
        assert "clinic" not in (row.details or "")
        assert json.loads(row.details)["operations"] == 1
    finally:
        db.close()


def test_propose_when_ai_is_off_is_a_clean_error(client):
    headers = admin(client)
    resp = client.post(PROPOSE, json=body(), headers=headers)
    assert resp.status_code == 503


def test_propose_validates_its_input(client, ai_on):
    headers = admin(client)
    use_provider(FakeProvider([reply([])]))
    assert client.post(PROPOSE, json={"instruction": "x", "snapshot": base_data()}, headers=headers).status_code == 422
    bad = base_data()
    bad["questions"][0]["type"] = "NOT_A_TYPE"
    assert client.post(PROPOSE, json=body(data=bad), headers=headers).status_code == 422


def test_propose_rejects_oversized_requests(client, ai_on):
    headers = admin(client)
    use_provider(FakeProvider([reply([])]))
    big = base_data()
    big["questions"][0]["label"] = "x" * 300_000
    assert client.post(PROPOSE, json=body(data=big), headers=headers).status_code == 413


# ------------------------------------------------------------------ preview (no AI)


def test_preview_works_without_ai_and_never_calls_a_model(client):
    headers = admin(client)  # AI is switched off in this test
    ops = [{"op": "ADD_SECTION", "title": "Employment"}, {"op": "DELETE_QUESTION", "code": "ghost"}]
    resp = client.post(PREVIEW, json={"snapshot": base_data(), "operations": ops}, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["operations"]) == 1 and len(data["rejected"]) == 1
    assert [s["title"] for s in data["result"]["sections"]][-1] == "Employment"


def test_preview_blocks_wiping_a_questionnaire(client):
    headers = admin(client)
    ops = [{"op": "DELETE_QUESTION", "code": q["code"]} for q in base_data()["questions"]]
    data = client.post(PREVIEW, json={"snapshot": base_data(), "operations": ops}, headers=headers).json()
    assert data["blocked"] and data["operations"] == [] and len(data["result"]["questions"]) == 8


def test_preview_rejects_too_many_operations(client):
    headers = admin(client)
    ops = [{"op": "DELETE_QUESTION", "code": "age"}] * 500
    assert client.post(PREVIEW, json={"snapshot": base_data(), "operations": ops}, headers=headers).status_code == 422


# ------------------------------------------------------------------ version history & save path


def _create(client, headers, payload=None):
    resp = client.post("/api/surveys", json=payload or _sample_survey_payload(), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_version_history_lists_every_version_with_who_and_why(client):
    headers = admin(client)
    survey = _create(client, headers)
    payload = {**_sample_survey_payload(), "change_summary": "Added notes with the AI assistant", "change_source": "AI_EDIT"}
    payload["questions"].append({"code": "notes", "label": "Notes", "type": "LONG_TEXT", "order_index": 5})
    assert client.put(f"/api/surveys/{survey['id']}", json=payload, headers=headers).status_code == 200

    resp = client.get(f"/api/surveys/{survey['id']}/versions", headers=headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["version_number"] for r in rows] == [2, 1]
    assert rows[0]["is_current"] and rows[0]["change_source"] == "AI_EDIT"
    assert rows[0]["change_summary"] == "Added notes with the AI assistant"
    assert rows[0]["question_count"] == 5 and rows[1]["question_count"] == 4
    assert rows[0]["created_by_name"] == "Test Admin"


def test_old_versions_stay_intact_and_can_be_read(client):
    headers = admin(client)
    survey = _create(client, headers)
    payload = _sample_survey_payload()
    payload["questions"] = payload["questions"][:2]
    assert client.put(f"/api/surveys/{survey['id']}", json=payload, headers=headers).status_code == 200
    rows = client.get(f"/api/surveys/{survey['id']}/versions", headers=headers).json()
    v1 = next(r for r in rows if r["version_number"] == 1)
    detail = client.get(f"/api/surveys/{survey['id']}/versions/{v1['id']}", headers=headers).json()
    assert [q["code"] for q in detail["questions"]] == ["full_name", "age_years", "gender", "is_pregnant"]
    assert client.get(f"/api/surveys/{survey['id']}/versions/not-a-version", headers=headers).status_code == 404


def test_version_history_is_for_people_who_can_edit(client):
    headers = admin(client)
    survey = _create(client, headers)
    other = enumerator(client)
    assert client.get(f"/api/surveys/{survey['id']}/versions", headers=other).status_code in (403, 404)
    assert client.get(f"/api/surveys/{survey['id']}/versions").status_code == 401


def test_saving_an_empty_questionnaire_is_refused_and_nothing_is_lost(client):
    headers = admin(client)
    survey = _create(client, headers)
    payload = {**_sample_survey_payload(), "questions": []}
    resp = client.put(f"/api/surveys/{survey['id']}", json=payload, headers=headers)
    assert resp.status_code == 400
    current = client.get(f"/api/surveys/{survey['id']}", headers=headers).json()
    assert current["current_version_number"] == 1 and len(current["questions"]) == 4


def test_title_only_updates_do_not_create_versions(client):
    headers = admin(client)
    survey = _create(client, headers)
    resp = client.put(f"/api/surveys/{survey['id']}", json={"title": "Renamed"}, headers=headers)
    assert resp.status_code == 200 and resp.json()["current_version_number"] == 1


def test_resaving_keeps_questions_attached_to_their_sections(client):
    """Questions that carry a saved section's id must follow that section into the new version."""
    headers = admin(client)
    payload = _sample_survey_payload()
    payload["sections"] = [{"title": "A", "order_index": 1}, {"title": "B", "order_index": 2}]
    payload["questions"][0]["section_id"] = "local-0"
    for q in payload["questions"][1:]:
        q["section_id"] = "local-1"
    survey = _create(client, headers, payload)
    saved = {s["title"]: s["id"] for s in survey["sections"]}
    assert {q["code"]: q["section_id"] for q in survey["questions"]}["age_years"] == saved["B"]

    resave = {
        "title": survey["title"],
        "sections": [{**s, "order_index": i + 1} for i, s in enumerate(survey["sections"])],
        "groups": [],
        "questions": [{**q, "order_index": i + 1} for i, q in enumerate(survey["questions"])],
    }
    updated = client.put(f"/api/surveys/{survey['id']}", json=resave, headers=headers).json()
    new_sections = {s["title"]: s["id"] for s in updated["sections"]}
    assert new_sections["A"] != saved["A"]  # a new version has new rows
    by_code = {q["code"]: q["section_id"] for q in updated["questions"]}
    assert by_code["full_name"] == new_sections["A"] and by_code["age_years"] == new_sections["B"]
