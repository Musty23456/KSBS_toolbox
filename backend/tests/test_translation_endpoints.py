"""
Phase 5 endpoint tests: multilingual questionnaires end to end (stable keys across versions, partial and
outdated translation, manual edits, comparison, respondent payload, Hausa review, access rules, and that
translation can never break validation or collected data). The AI is a scripted fake.
"""

import json

from app.ai.providers.base import AIProvider, ProviderResponse
from app.models.questionnaire_translation import QuestionnaireTranslation
from app.models.survey import Survey, SurveyVersion
from app.models.sync import AuditLog
from tests.conftest import TestingSessionLocal, register_and_login
from tests.test_ai_questionnaire import (  # noqa: F401 - fixtures are used by name
    admin,
    ai_on,
    clean_state,
    enumerator,
    use_provider,
)


class Translator(AIProvider):
    """Translates by table lookup; anything not in the table becomes 'T:<text>' (placeholders are kept)."""

    name = "gemini"

    def __init__(self, table=None, override=None):
        super().__init__("gemini-test")
        self.table, self.override, self.calls = table or {}, override or {}, []

    def generate_text(self, prompt, *, system_instruction=None, max_output_tokens=None, json_mode=False):
        self.calls.append(prompt)
        items, _ = json.JSONDecoder().raw_decode(prompt.split("ITEMS:\n", 1)[1])
        out = []
        for item in items:
            text = item["text"]
            out.append({"id": item["id"], "text": self.override.get(text, self.table.get(text, "T:" + text))})
        return ProviderResponse(text=json.dumps({"translations": out}), model="gemini-test", finish_reason="STOP")


HAUSA = {"How old are you?": "Shekara nawa kake?", "Yes": "Ee", "No": "A'a", "Other": "Wani",
         "Must be at least {min}.": "Dole ne ya zama akalla {min}."}


def survey_payload(**over):
    payload = {
        "title": "Malaria Household Survey",
        "description": "Measures bed-net use.\n\nInstructions for respondents\nAnswer for your own household.",
        "sections": [{"title": "Household", "order_index": 1}],
        "questions": [
            {"code": "age_years", "label": "How old are you?", "hint": "Age in years, 18 or over", "type": "INTEGER",
             "order_index": 1, "is_required": True, "min_value": 18, "max_value": 120},
            {"code": "own_net", "label": "Do you own a bed net?", "type": "SINGLE_CHOICE", "order_index": 2, "is_required": True,
             "choices": [{"value": "YES", "label": "Yes", "order_index": 1}, {"value": "NO", "label": "No", "order_index": 2},
                         {"value": "OTHER", "label": "Other", "order_index": 3}]},
        ],
    }
    payload.update(over)
    return payload


def make_survey(client, headers, publish=False, **over):
    survey = client.post("/api/surveys", json=survey_payload(**over), headers=headers).json()
    if publish:
        survey = client.post(f"/api/surveys/{survey['id']}/publish", headers=headers).json()
    return survey


def base(survey):
    return f"/api/surveys/{survey['id']}/i18n"


def translate(client, headers, survey, language="ha", **body):
    return client.post(f"{base(survey)}/{language}/translate", json=body, headers=headers)


def units(client, headers, survey, language="ha"):
    data = client.get(f"{base(survey)}/{language}", headers=headers).json()
    return {(u["entity_type"], u["entity_key"], u["field"]): u for u in data["units"]}, data["summary"]


def resave(client, headers, survey, change=None):
    """Save the survey again, as the builder does: a NEW version whose rows all have new ids."""
    questions = []
    for q in survey["questions"]:
        item = {k: q[k] for k in ("code", "label", "hint", "type", "order_index", "is_required", "min_value", "max_value",
                                  "min_length", "max_length", "regex_pattern", "relevance_expression",
                                  "calculation_expression", "default_value")}
        item["choices"] = [{"value": c["value"], "label": c["label"], "order_index": c["order_index"]} for c in q["choices"]]
        questions.append(item)
    if change:
        change(questions)
    sections = [{"title": s["title"], "description": s.get("description"), "order_index": s["order_index"]} for s in survey["sections"]]
    return client.put(f"/api/surveys/{survey['id']}", json={"questions": questions, "sections": sections}, headers=headers)


def counts():
    db = TestingSessionLocal()
    try:
        return db.query(Survey).count(), db.query(SurveyVersion).count()
    finally:
        db.close()


# ------------------------------------------------------------------ access


def test_translation_endpoints_require_authentication(client):
    survey = make_survey(client, admin(client))
    for path in ("overview", "available", "ha", "ha/localized"):
        assert client.get(f"{base(survey)}/{path}").status_code == 401
    assert client.post(f"{base(survey)}/ha/translate", json={}).status_code == 401


def test_unknown_language_and_unknown_survey(client):
    headers = admin(client)
    survey = make_survey(client, headers)
    assert client.get(f"{base(survey)}/de", headers=headers).status_code == 404
    assert client.get("/api/surveys/nope/i18n/overview", headers=headers).status_code == 404


def test_the_existing_language_list_still_works_and_has_the_six_languages(client):
    langs = client.get("/api/surveys/languages", headers=admin(client)).json()
    assert [l["code"] for l in langs] == ["en", "ha", "yo", "ig", "fr", "ar"]
    assert all("name" in l for l in langs) and next(l for l in langs if l["code"] == "ar")["rtl"] is True


def test_personal_surveys_are_private_and_only_the_owner_edits_translations(client, ai_on):
    owner = register_and_login(client, email="own@test.local", role="ENUMERATOR", full_name="Own")
    other = register_and_login(client, email="oth@test.local", role="ENUMERATOR", full_name="Oth")
    boss = register_and_login(client, email="boss@test.local", role="ADMINISTRATOR", full_name="Boss")
    survey = make_survey(client, owner, publish=True)
    use_provider(Translator(HAUSA))
    assert translate(client, owner, survey).status_code == 200  # an owner translates their own survey
    assert client.get(f"{base(survey)}/available", headers=other).status_code == 404
    assert client.get(f"{base(survey)}/overview", headers=other).status_code == 404
    assert client.get(f"{base(survey)}/overview", headers=boss).status_code == 403  # may open, may not edit
    assert translate(client, other, survey).status_code == 404


def test_people_a_personal_survey_is_shared_with_can_read_translations_but_not_edit_them(client, ai_on):
    owner = register_and_login(client, email="own2@test.local", role="ENUMERATOR", full_name="Own")
    friend = register_and_login(client, email="fr2@test.local", role="ENUMERATOR", full_name="Friend")
    me = client.get("/api/auth/me", headers=friend).json()
    survey = make_survey(client, owner, publish=True)
    use_provider(Translator(HAUSA))
    translate(client, owner, survey)
    assert client.put(f"/api/surveys/{survey['id']}/shares", json={"user_ids": [me["id"]]}, headers=owner).status_code == 200
    assert client.get(f"{base(survey)}/available", headers=friend).status_code == 200
    assert client.get(f"{base(survey)}/ha/localized", headers=friend).status_code == 200
    put = client.put(f"{base(survey)}/ha/units", json={"units": [{"entity_type": "SURVEY", "entity_key": "survey", "field": "title", "value": "x"}]}, headers=friend)
    assert put.status_code == 403
    assert translate(client, friend, survey).status_code == 403


# ------------------------------------------------------------------ overview and AI translation


def test_overview_lists_the_six_languages_with_nothing_translated(client):
    headers = admin(client)
    survey = make_survey(client, headers)
    data = client.get(f"{base(survey)}/overview", headers=headers).json()
    assert [l["code"] for l in data["languages"]] == ["en", "ha", "yo", "ig", "fr", "ar"]
    assert all(l["translated"] == 0 and l["missing"] == data["total_units"] for l in data["languages"])
    assert data["total_units"] >= 10 and data["version_number"] == 1


def test_ai_translation_saves_drafts_and_leaves_the_questionnaire_untouched(client, ai_on):
    headers = admin(client)
    survey = make_survey(client, headers)
    provider = use_provider(Translator(HAUSA))
    before = (counts(), client.get(f"/api/surveys/{survey['id']}", headers=headers).json())

    resp = translate(client, headers, survey)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["translated"] > 0 and data["remaining"] == 0 and data["rejected"] == [] and data["ai_error"] is None

    after = (counts(), client.get(f"/api/surveys/{survey['id']}", headers=headers).json())
    assert after == before  # no new version, and every code, value, type and rule is exactly as it was
    table, summary = units(client, headers, survey)
    assert table[("QUESTION", "age_years", "label")]["value"] == "Shekara nawa kake?"
    assert table[("QUESTION", "age_years", "label")]["status"] == "AI_DRAFT"
    assert table[("CHOICE", "own_net::YES", "label")]["value"] == "Ee"
    assert table[("SURVEY", "survey", "description")]["value"].startswith("T:Measures")
    assert summary["missing"] == 0 and summary["percent_complete"] == 100
    for sent in provider.calls:  # identifiers never reach the model
        assert "age_years" not in sent and "own_net" not in sent and '"YES"' not in sent


def test_translation_covers_titles_descriptions_sections_questions_choices_hints_and_validation_messages(client, ai_on):
    headers = admin(client)
    survey = make_survey(client, headers)
    use_provider(Translator(HAUSA))
    translate(client, headers, survey)
    table, _ = units(client, headers, survey)
    kinds = {(t, f) for (t, _k, f) in table}
    assert {("SURVEY", "title"), ("SURVEY", "description"), ("SECTION", "title"), ("QUESTION", "label"),
            ("QUESTION", "hint"), ("CHOICE", "label"), ("SYSTEM", "text")} <= kinds
    assert table[("SYSTEM", "msg.min", "text")]["value"] == "Dole ne ya zama akalla {min}."  # the placeholder survived
    assert all(u["value"] for u in table.values())


def test_a_translation_survives_new_versions_and_only_edited_text_becomes_outdated(client, ai_on):
    headers = admin(client)
    survey = make_survey(client, headers)
    use_provider(Translator(HAUSA))
    translate(client, headers, survey)

    def change(questions):
        questions[0]["label"] = "What is your age?"  # the wording changed; the code did not

    saved = resave(client, headers, survey, change)
    assert saved.status_code == 200 and saved.json()["current_version_number"] == 2

    table, summary = units(client, headers, survey)
    assert table[("QUESTION", "age_years", "label")]["status"] == "OUTDATED"  # source changed after translation
    assert table[("CHOICE", "own_net::YES", "label")]["status"] == "AI_DRAFT"  # untouched text kept its translation
    assert table[("CHOICE", "own_net::YES", "label")]["value"] == "Ee"
    assert summary["outdated"] == 1 and summary["missing"] == 0

    # default translate call refreshes only what is outdated
    provider = use_provider(Translator({"What is your age?": "Shekarunka nawa?"}))
    data = translate(client, headers, survey).json()
    assert data["translated"] == 1 and len(provider.calls) == 1
    table, summary = units(client, headers, survey)
    assert table[("QUESTION", "age_years", "label")]["value"] == "Shekarunka nawa?" and summary["outdated"] == 0


def test_a_new_question_shows_as_missing_and_existing_translations_stay(client, ai_on):
    headers = admin(client)
    survey = make_survey(client, headers)
    use_provider(Translator(HAUSA))
    translate(client, headers, survey)

    def change(questions):
        questions.append({"code": "net_count", "label": "How many nets?", "type": "INTEGER", "order_index": 3,
                          "is_required": False, "choices": []})

    resave(client, headers, survey, change)
    table, summary = units(client, headers, survey)
    assert table[("QUESTION", "net_count", "label")]["status"] == "MISSING" and summary["missing"] == 1
    assert table[("QUESTION", "age_years", "label")]["value"] == "Shekara nawa kake?"


def test_partial_translation_by_kind_and_by_unit(client, ai_on):
    headers = admin(client)
    survey = make_survey(client, headers)
    use_provider(Translator(HAUSA))
    data = translate(client, headers, survey, entity_types=["CHOICE"]).json()
    table, _ = units(client, headers, survey)
    assert data["translated"] == 3
    assert all(u["status"] == "AI_DRAFT" for k, u in table.items() if k[0] == "CHOICE")
    assert all(u["status"] == "MISSING" for k, u in table.items() if k[0] != "CHOICE")

    one = [{"entity_type": "QUESTION", "entity_key": "age_years", "field": "label"}]
    assert translate(client, headers, survey, units=one).json()["translated"] == 1
    assert units(client, headers, survey)[0][("QUESTION", "age_years", "label")]["value"] == "Shekara nawa kake?"


def test_large_questionnaires_are_translated_in_chunks_until_remaining_is_zero(client, ai_on):
    headers = admin(client)
    survey = make_survey(client, headers)
    use_provider(Translator(HAUSA))
    first = translate(client, headers, survey, max_units=5).json()
    assert first["attempted"] == 5 and first["translated"] == 5 and first["remaining"] > 0
    while True:
        step = translate(client, headers, survey, max_units=5).json()
        assert step["translated"] > 0
        if step["remaining"] == 0:
            break
    assert units(client, headers, survey)[1]["missing"] == 0


def test_nothing_to_do_does_not_call_the_ai(client, ai_on):
    headers = admin(client)
    survey = make_survey(client, headers)
    provider = use_provider(Translator(HAUSA))
    translate(client, headers, survey)
    calls = len(provider.calls)
    again = translate(client, headers, survey).json()
    assert again["attempted"] == 0 and again["translated"] == 0 and len(provider.calls) == calls


def test_ai_output_that_would_break_the_questionnaire_is_never_saved(client, ai_on):
    headers = admin(client)
    survey = make_survey(client, headers)
    use_provider(Translator(HAUSA, override={"Must be at least {min}.": "Dole ne ya zama akalla {mn}."}))
    data = translate(client, headers, survey).json()
    assert [r["label"] for r in data["rejected"]] == ["Validation message (msg.min)"]
    table, _ = units(client, headers, survey)
    assert table[("SYSTEM", "msg.min", "text")]["status"] == "MISSING"  # the respondent keeps the English message


def test_ai_unavailable_is_reported_not_a_crash(client):
    headers = admin(client)
    survey = make_survey(client, headers)
    data = translate(client, headers, survey).json()  # AI is not configured in tests
    assert data["translated"] == 0 and data["ai_error"] and data["remaining"] > 0


# ------------------------------------------------------------------ manual edits


def save(client, headers, survey, *items, language="ha"):
    return client.put(f"{base(survey)}/{language}/units", json={"units": list(items)}, headers=headers)


def item(kind, key, field, value=None, status="EDITED"):
    body = {"entity_type": kind, "entity_key": key, "field": field, "status": status}
    if value is not None:
        body["value"] = value
    return body


def test_manual_edit_is_saved_as_edited_and_protected_from_the_ai(client, ai_on):
    headers = admin(client)
    survey = make_survey(client, headers)
    use_provider(Translator(HAUSA))
    translate(client, headers, survey)
    resp = save(client, headers, survey, item("QUESTION", "age_years", "label", "Shekarunka nawa?"))
    assert resp.status_code == 200 and resp.json()["saved"] == 1
    assert units(client, headers, survey)[0][("QUESTION", "age_years", "label")]["status"] == "EDITED"

    data = translate(client, headers, survey, scope="all").json()
    assert data["protected_skipped"] == 1
    assert units(client, headers, survey)[0][("QUESTION", "age_years", "label")]["value"] == "Shekarunka nawa?"
    translate(client, headers, survey, scope="all", overwrite_manual=True)
    assert units(client, headers, survey)[0][("QUESTION", "age_years", "label")]["value"] == "Shekara nawa kake?"


def test_a_manual_edit_that_would_break_the_questionnaire_saves_nothing(client):
    headers = admin(client)
    survey = make_survey(client, headers)
    resp = save(client, headers, survey,
                item("QUESTION", "age_years", "label", "Shekara nawa kake?"),
                item("SYSTEM", "msg.min", "text", "Dole ne ya zama akalla {mn}."))
    assert resp.status_code == 422
    assert "msg.min" in json.dumps(resp.json()) or "Validation message" in json.dumps(resp.json())
    table, summary = units(client, headers, survey)
    assert summary["translated"] == 0  # all-or-nothing: the good edit was not saved either


def test_manual_edit_rejects_text_that_is_not_in_the_questionnaire_and_overlong_text(client):
    headers = admin(client)
    survey = make_survey(client, headers)
    assert save(client, headers, survey, item("QUESTION", "no_such_code", "label", "x")).status_code == 422
    assert save(client, headers, survey, item("CHOICE", "own_net::YES", "label", "a" * 501)).status_code == 422
    assert save(client, headers, survey, item("QUESTION", "age_years", "label", "x", status="NOPE")).status_code == 422


def test_an_empty_value_removes_the_translation_and_status_only_marks_it_reviewed(client):
    headers = admin(client)
    survey = make_survey(client, headers)
    save(client, headers, survey, item("CHOICE", "own_net::YES", "label", "Ee"))
    assert save(client, headers, survey, item("CHOICE", "own_net::YES", "label", status="REVIEWED")).status_code == 200
    assert units(client, headers, survey)[0][("CHOICE", "own_net::YES", "label")]["status"] == "REVIEWED"
    assert save(client, headers, survey, item("CHOICE", "own_net::NO", "label", status="REVIEWED")).status_code == 422  # nothing to mark
    assert save(client, headers, survey, item("CHOICE", "own_net::YES", "label", "  ")).json()["removed"] == 1
    assert units(client, headers, survey)[0][("CHOICE", "own_net::YES", "label")]["status"] == "MISSING"


def test_confirming_an_outdated_translation_clears_the_outdated_flag(client, ai_on):
    headers = admin(client)
    survey = make_survey(client, headers)
    use_provider(Translator(HAUSA))
    translate(client, headers, survey)
    resave(client, headers, survey, lambda qs: qs[0].update(label="What is your age?"))
    assert units(client, headers, survey)[0][("QUESTION", "age_years", "label")]["status"] == "OUTDATED"
    save(client, headers, survey, item("QUESTION", "age_years", "label", status="REVIEWED"))  # a person confirms it still fits
    assert units(client, headers, survey)[0][("QUESTION", "age_years", "label")]["status"] == "REVIEWED"


def test_deleting_a_language_removes_only_that_language(client):
    headers = admin(client)
    survey = make_survey(client, headers)
    save(client, headers, survey, item("CHOICE", "own_net::YES", "label", "Ee"))
    save(client, headers, survey, item("CHOICE", "own_net::YES", "label", "Oui"), language="fr")
    assert client.delete(f"{base(survey)}/ha", headers=headers).status_code == 204
    assert units(client, headers, survey)[1]["translated"] == 0
    assert units(client, headers, survey, "fr")[1]["translated"] == 1


# ------------------------------------------------------------------ comparison, respondent payload


def test_comparison_shows_the_source_and_each_language_side_by_side(client):
    headers = admin(client)
    survey = make_survey(client, headers)
    save(client, headers, survey, item("QUESTION", "age_years", "label", "Shekara nawa kake?"))
    save(client, headers, survey, item("QUESTION", "age_years", "label", "Quel âge avez-vous ?"), language="fr")
    data = client.get(f"{base(survey)}/compare?languages=ha,fr,yo", headers=headers).json()
    row = next(r for r in data["rows"] if r["entity_key"] == "age_years" and r["field"] == "label")
    assert row["source"] == "How old are you?"
    assert row["translations"]["ha"]["value"] == "Shekara nawa kake?" and row["translations"]["fr"]["value"] == "Quel âge avez-vous ?"
    assert row["translations"]["yo"]["status"] == "MISSING"
    assert client.get(f"{base(survey)}/compare?languages=ha,xx", headers=headers).status_code == 422
    assert client.get(f"{base(survey)}/compare?languages=ha,fr,yo,ig,ar", headers=headers).status_code == 422


def test_the_respondent_payload_is_keyed_by_current_ids_and_falls_back_for_missing_text(client, ai_on):
    headers = admin(client)
    survey = make_survey(client, headers, publish=True)
    save(client, headers, survey, item("QUESTION", "age_years", "label", "Shekara nawa kake?"),
         item("CHOICE", "own_net::YES", "label", "Ee"), item("SYSTEM", "msg.required", "text", "Wannan tambayar wajibi ce."))
    payload = client.get(f"{base(survey)}/ha/localized", headers=headers).json()
    q = next(q for q in survey["questions"] if q["code"] == "age_years")
    yes = next(c for qq in survey["questions"] for c in qq["choices"] if c["value"] == "YES")
    assert payload["questions"][q["id"]]["label"] == "Shekara nawa kake?"
    assert payload["choices"][yes["id"]] == "Ee" and payload["messages"]["msg.required"] == "Wannan tambayar wajibi ce."
    assert payload["survey"] == {} and payload["rtl"] is False  # untranslated parts are simply absent
    assert 0 < payload["percent_complete"] < 100

    # after a new version the ids are new and the payload follows them
    new = resave(client, headers, survey).json()
    new_q = next(q for q in new["questions"] if q["code"] == "age_years")
    assert new_q["id"] != q["id"]
    again = client.get(f"{base(survey)}/ha/localized", headers=headers).json()
    assert again["questions"][new_q["id"]]["label"] == "Shekara nawa kake?" and q["id"] not in again["questions"]


def test_outdated_text_is_not_shown_to_respondents(client, ai_on):
    headers = admin(client)
    survey = make_survey(client, headers)
    use_provider(Translator(HAUSA))
    translate(client, headers, survey)
    survey = client.get(f"/api/surveys/{survey['id']}", headers=headers).json()
    new = resave(client, headers, survey, lambda qs: qs[0].update(label="What is your age?")).json()
    q = next(q for q in new["questions"] if q["code"] == "age_years")
    assert q["id"] not in client.get(f"{base(survey)}/ha/localized", headers=headers).json()["questions"] or \
        "label" not in client.get(f"{base(survey)}/ha/localized", headers=headers).json()["questions"][q["id"]]
    shown = client.get(f"{base(survey)}/ha/localized?include_outdated=true", headers=headers).json()
    assert shown["questions"][q["id"]]["label"] == "Shekara nawa kake?"


def test_arabic_is_right_to_left_and_available_lists_only_translated_languages(client):
    headers = admin(client)
    survey = make_survey(client, headers, publish=True)
    assert client.get(f"{base(survey)}/available", headers=headers).json() == []
    save(client, headers, survey, item("QUESTION", "age_years", "label", "كم عمرك؟"), language="ar")
    save(client, headers, survey, item("QUESTION", "age_years", "label", "Shekara nawa kake?"))
    available = client.get(f"{base(survey)}/available", headers=headers).json()
    assert [l["code"] for l in available] == ["ha", "ar"] and next(l for l in available if l["code"] == "ar")["rtl"] is True
    assert client.get(f"{base(survey)}/ar/localized", headers=headers).json()["rtl"] is True


# ------------------------------------------------------------------ validation and data stay intact


def test_a_fully_translated_survey_still_validates_and_stores_the_same_values(client, ai_on):
    headers = admin(client)
    survey = make_survey(client, headers, publish=True)
    use_provider(Translator(HAUSA))
    translate(client, headers, survey)
    detail = client.get(f"/api/surveys/{survey['id']}", headers=headers).json()
    qid = {q["code"]: q["id"] for q in detail["questions"]}

    def submit(uuid, age, net):
        return client.post("/api/submissions", headers=headers, json={
            "client_submission_uuid": uuid, "survey_id": survey["id"], "survey_version_id": detail["current_version_id"],
            "answers": [{"question_id": qid["age_years"], "value_text": age}, {"question_id": qid["own_net"], "value_text": net}]})

    ok = submit("aaaaaaaa-0000-0000-0000-000000000001", "30", "YES")  # the VALUE, not the Hausa label "Ee"
    assert ok.status_code == 201
    assert sorted(a["value_text"] for a in ok.json()["answers"]) == ["30", "YES"]
    assert submit("aaaaaaaa-0000-0000-0000-000000000002", "10", "YES").status_code == 422  # min_value 18 still enforced
    assert submit("aaaaaaaa-0000-0000-0000-000000000003", "30", "").status_code == 422  # required still enforced


# ------------------------------------------------------------------ Hausa review


def test_hausa_review_flags_problems_and_never_changes_anything(client):
    headers = admin(client)
    survey = make_survey(client, headers)
    save(client, headers, survey, item("QUESTION", "age_years", "label", "How old are you?"),
         item("QUESTION", "own_net", "label", "Kana da kudi?"),
         item("CHOICE", "own_net::YES", "label", "Ee"), item("CHOICE", "own_net::NO", "label", "Ee"))
    before = units(client, headers, survey)[0]
    resp = client.post(f"{base(survey)}/ha/review", json={"use_ai": False}, headers=headers)
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["ai_used"] is False and report["reviewed_units"] == 4 and 0 <= report["score"] < 100
    by_category = {f["category"] for f in report["findings"]}
    assert {"COMPLETENESS", "ORTHOGRAPHY", "CLARITY"} <= by_category
    fix = next(f for f in report["findings"] if f["category"] == "ORTHOGRAPHY")
    assert fix["suggestion"] == "Kana da kuɗi?" and "native-speaker" in " ".join(report["limitations"])
    assert units(client, headers, survey)[0] == before  # read-only


def test_hausa_review_uses_the_ai_when_available_and_survives_when_it_is_not(client, ai_on):
    headers = admin(client)
    survey = make_survey(client, headers)
    save(client, headers, survey, item("QUESTION", "age_years", "label", "Shekara nawa kake?"))

    class Reviewer(Translator):
        def generate_text(self, prompt, **kw):
            reply = {"summary": "Fine.", "findings": [{"id": "1", "severity": "SUGGESTION", "category": "REGISTER",
                                                        "message": "Use the polite form."}]}
            return ProviderResponse(text=json.dumps(reply), model="gemini-test", finish_reason="STOP")

    use_provider(Reviewer())
    report = client.post(f"{base(survey)}/ha/review", json={}, headers=headers).json()
    assert report["ai_used"] is True and any(f["source"] == "AI" for f in report["findings"])


def test_hausa_review_works_when_ai_is_not_configured(client):
    headers = admin(client)
    survey = make_survey(client, headers)
    save(client, headers, survey, item("QUESTION", "age_years", "label", "Shekara nawa kake?"))
    report = client.post(f"{base(survey)}/ha/review", json={}, headers=headers).json()
    assert report["ai_used"] is False and report["ai_error"] and report["reviewed_units"] == 1


# ------------------------------------------------------------------ audit and legacy


def test_audit_entries_hold_counts_only_never_translated_text(client, ai_on):
    headers = admin(client)
    survey = make_survey(client, headers)
    use_provider(Translator(HAUSA))
    translate(client, headers, survey)
    save(client, headers, survey, item("QUESTION", "age_years", "label", "SIRRIN-RUBUTUN-GWAJI"))
    client.post(f"{base(survey)}/ha/review", json={"use_ai": False}, headers=headers)
    db = TestingSessionLocal()
    try:
        rows = db.query(AuditLog).filter(AuditLog.action.in_(["AI_TRANSLATION_RUN", "TRANSLATION_EDITED", "HAUSA_REVIEW_RUN"])).all()
        assert {r.action for r in rows} == {"AI_TRANSLATION_RUN", "TRANSLATION_EDITED", "HAUSA_REVIEW_RUN"}
        blob = " ".join(str(r.details) for r in rows)
        assert "SIRRIN" not in blob and "Shekara" not in blob and "Malaria" not in blob
    finally:
        db.close()


def test_translations_from_the_older_page_can_be_imported_without_changing_it(client):
    headers = admin(client)
    survey = make_survey(client, headers)
    q = next(q for q in survey["questions"] if q["code"] == "age_years")
    legacy = {"entity_type": "QUESTION", "entity_id": q["id"], "field": "label", "language_code": "ha", "value": "Shekara nawa kake?"}
    assert client.put(f"/api/surveys/{survey['id']}/translations", json=legacy, headers=headers).status_code == 200
    first = client.post(f"{base(survey)}/import-legacy", headers=headers).json()
    assert first == {"imported": 1, "skipped_existing": 0, "not_matched": 0}
    assert units(client, headers, survey)[0][("QUESTION", "age_years", "label")]["status"] == "EDITED"
    assert client.post(f"{base(survey)}/import-legacy", headers=headers).json()["skipped_existing"] == 1
    assert len(client.get(f"/api/surveys/{survey['id']}/translations", headers=headers).json()) == 1  # old table untouched
    db = TestingSessionLocal()
    try:
        assert db.query(QuestionnaireTranslation).count() == 1
    finally:
        db.close()
