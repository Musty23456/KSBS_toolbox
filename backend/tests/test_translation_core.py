"""
Phase 5 core tests: placeholders, checks, stable keys, translation status tracking, Hausa rules and the
AI translation / review services (with a scripted fake AI). No database, no web framework, no real AI.
"""

import json
from types import SimpleNamespace

from app.ai.errors import AIInvalidJsonError, AIQuotaExceededError
from app.ai.translation import checks, hausa, protect, reconcile
from app.ai.translation.catalog import SYSTEM_MESSAGES
from app.ai.translation.languages import LANGUAGE_CODES, get_language, list_languages
from app.ai.translation.service import HausaReviewer, TranslationService, make_batches, parse_translations
from app.ai.translation.units import build_units, choice_key, source_hash, title_key


def survey(**over):
    base = {
        "id": "s1",
        "title": "Malaria Survey",
        "description": "Intro\n\nInstructions for respondents\nAnswer for your household.",
        "sections": [{"id": "sec1", "title": "Household", "order_index": 0, "description": None}],
        "groups": [{"id": "g1", "title": "Members", "order_index": 0, "description": "People who live here"}],
        "questions": [
            {"id": "q1", "code": "age", "label": "How old are you?", "hint": "Age in years, 18 or over", "order_index": 0,
             "choices": []},
            {"id": "q2", "code": "net", "label": "Do you own a bed net?", "hint": None, "order_index": 1,
             "choices": [{"id": "c1", "value": "YES", "label": "Yes", "order_index": 0},
                         {"id": "c2", "value": "OTHER", "label": "Other", "order_index": 1}]},
        ],
    }
    base.update(over)
    return base


def row(unit, value, status="AI_DRAFT", hash_=None):
    return {"entity_type": unit.entity_type, "entity_key": unit.entity_key, "field": unit.field, "value": value,
            "source_hash": hash_ or unit.hash, "status": status, "source": "AI"}


def find(units, kind, key, field):
    return next(u for u in units if u.id == (kind, key, field))


# ------------------------------------------------------------------ languages


def test_the_six_languages_are_supported_and_arabic_is_rtl():
    assert set(LANGUAGE_CODES) == {"en", "ha", "yo", "ig", "ar", "fr"}
    assert get_language("AR").rtl is True and get_language("ha").rtl is False
    assert get_language("de") is None and get_language(None) is None
    assert all({"code", "name", "native_name", "rtl"} <= set(item) for item in list_languages())


# ------------------------------------------------------------------ placeholders


def test_placeholders_must_be_kept():
    assert protect.missing_tokens("Must be at least {min}.", "Dole ne ya zama akalla {mn}.") == ["{min}"]
    assert protect.added_tokens("Must be at least {min}.", "Dole {min} ko {max}.") == ["{max}"]
    assert protect.missing_tokens("Visit https://kbs.org now", "Ziyarci shafin") == ["https://kbs.org"]
    assert protect.missing_tokens("{a} and {a}", "{a}") == ["{a}"]  # repeat counts matter
    assert protect.missing_tokens("{min}", "{min}") == []


def test_arabic_indic_digits_count_as_the_same_number():
    assert protect.missing_numbers("Aged 18 or over", "١٨ سنة أو أكثر") == []
    assert protect.missing_numbers("Aged 18 or over", "Shekara goma sha takwas") == ["18"]


# ------------------------------------------------------------------ stable keys


def test_internal_identifiers_are_never_units():
    units = build_units(survey())
    texts = " | ".join(u.source for u in units)
    for identifier in ("age", "net", "YES", "OTHER"):
        assert identifier not in {u.source for u in units}, identifier  # codes and values are not texts
    assert all(u.field in ("title", "description", "label", "hint", "text") for u in units)
    assert "How old are you?" in texts and "Answer for your household" in texts


def test_keys_survive_a_resave_with_new_row_ids():
    first = build_units(survey())
    resaved = survey()
    resaved["sections"][0]["id"] = "NEW-sec"
    resaved["questions"][0]["id"] = "NEW-q"
    resaved["questions"][1]["choices"][0]["id"] = "NEW-c"
    second = build_units(resaved)
    assert [u.id for u in first] == [u.id for u in second]
    assert find(second, "QUESTION", "age", "label").ref_ids == ["NEW-q"]


def test_sections_are_keyed_by_title_so_reordering_cannot_misplace_a_translation():
    a = survey(sections=[{"id": "1", "title": "Household", "order_index": 0}, {"id": "2", "title": "Health", "order_index": 1}])
    b = survey(sections=[{"id": "9", "title": "Health", "order_index": 0}, {"id": "8", "title": "Household", "order_index": 1}])
    assert {u.entity_key for u in build_units(a) if u.entity_type == "SECTION"} == {title_key("Household"), title_key("Health")}
    assert {u.id for u in build_units(a)} == {u.id for u in build_units(b)}


def test_choice_keys_use_code_and_value_and_identical_titles_merge_into_one_unit():
    units = build_units(survey())
    assert find(units, "CHOICE", choice_key("net", "YES"), "label").source == "Yes"
    twins = survey(sections=[{"id": "1", "title": "Household", "order_index": 0},
                             {"id": "2", "title": "  Household ", "order_index": 1}])
    titles = [u for u in build_units(twins) if u.entity_type == "SECTION" and u.field == "title"]
    assert len(titles) == 1 and titles[0].ref_ids == ["1", "2"]  # one translation serves both sections


def test_empty_text_makes_no_unit_and_system_texts_are_included():
    units = build_units(survey())
    assert not any(u.source == "" for u in units)
    assert find(units, "QUESTION", "net", "label") and not any(u.id == ("QUESTION", "net", "hint") for u in units)
    assert {u.entity_key for u in units if u.entity_type == "SYSTEM"} == set(SYSTEM_MESSAGES)
    assert not any(u.entity_type == "SYSTEM" for u in build_units(survey(), include_system=False))


# ------------------------------------------------------------------ checks


def test_a_translation_that_loses_a_placeholder_is_blocked_and_cannot_be_saved():
    unit = find(build_units(survey()), "SYSTEM", "msg.min", "text")
    text, issues = checks.safe_value(unit, "Dole ne ya zama akalla {mn}.", "ha")
    assert text is None and any(i.code == "PLACEHOLDER_MISSING" for i in issues)
    text, issues = checks.safe_value(unit, "Dole ne ya zama akalla {min}.", "ha")
    assert text == "Dole ne ya zama akalla {min}." and not checks.has_blocking(issues)


def test_empty_and_too_long_are_blocked_and_whitespace_is_tidied():
    choice = find(build_units(survey()), "CHOICE", "net::YES", "label")
    assert checks.safe_value(choice, "   ", "ha")[0] is None
    assert checks.safe_value(choice, "a" * 501, "ha")[0] is None
    assert checks.safe_value(choice, "  Ee,\n  yana da  ", "ha")[0] == "Ee, yana da"  # single-line: collapsed


def test_multiline_text_keeps_its_paragraphs_and_warns_when_they_change():
    desc = find(build_units(survey()), "SURVEY", "survey", "description")
    ok, issues = checks.safe_value(desc, "Gabatarwa\n\nUmarni\nAmsa.", "ha")
    assert ok == "Gabatarwa\n\nUmarni\nAmsa." and not any(i.code == "STRUCTURE" for i in issues)
    _, issues = checks.safe_value(desc, "Gabatarwa Umarni Amsa.", "ha")
    assert any(i.code == "STRUCTURE" for i in issues)


def test_direction_marks_are_removed_and_wrong_script_is_flagged():
    q = find(build_units(survey()), "QUESTION", "age", "label")
    text, _ = checks.safe_value(q, "\u200fكم عمرك؟\u200f", "ar")
    assert text == "كم عمرك؟"
    _, issues = checks.safe_value(q, "How old are you? yes", "ar")
    assert any(i.code == "WRONG_SCRIPT" for i in issues)
    _, issues = checks.safe_value(q, "كم عمرك؟", "ha")
    assert any(i.code == "WRONG_SCRIPT" for i in issues)


def test_untranslated_and_missing_question_mark_and_missing_number_warn():
    units = build_units(survey())
    q = find(units, "QUESTION", "age", "label")
    assert any(i.code == "UNCHANGED" for i in checks.check_translation(q, q.source, "ha"))
    assert any(i.code == "QUESTION_MARK" for i in checks.check_translation(q, "Shekara nawa kake", "ha"))
    hint = find(units, "QUESTION", "age", "hint")
    assert any(i.code == "NUMBER_MISSING" for i in checks.check_translation(hint, "Shekaru, sama da goma sha takwas", "ha"))


def test_choices_with_identical_translations_are_flagged():
    units = build_units(survey())
    yes, other = find(units, "CHOICE", "net::YES", "label"), find(units, "CHOICE", "net::OTHER", "label")
    issues = checks.duplicate_choice_issues([(yes, "Ee"), (other, "ee")])
    assert yes.id in issues and other.id in issues
    assert not checks.duplicate_choice_issues([(yes, "Ee"), (other, "Wani")])


# ------------------------------------------------------------------ status tracking


def test_missing_outdated_and_orphaned_translations_are_detected():
    units = build_units(survey())
    title = find(units, "SURVEY", "survey", "title")
    q = find(units, "QUESTION", "age", "label")
    rows = [row(title, "Binciken Zazzabin Cizon Sauro"), row(q, "Shekara nawa kake?", hash_=source_hash("Old wording?")),
            {"entity_type": "QUESTION", "entity_key": "deleted_code", "field": "label", "value": "x",
             "source_hash": "a", "status": "EDITED", "source": "MANUAL"}]
    states, orphans = reconcile.evaluate(units, rows, "ha")
    status = {s.unit.id: s.status for s in states}
    assert status[title.id] == "AI_DRAFT" and status[q.id] == "OUTDATED"
    assert status[find(units, "QUESTION", "net", "label").id] == "MISSING"
    assert len(orphans) == 1
    summary = reconcile.summarize(states, orphans)
    assert summary["outdated"] == 1 and summary["ai_draft"] == 1 and summary["orphaned"] == 1
    assert summary["missing"] == len(units) - 2 and summary["needs_attention"] == summary["missing"] + 1


def test_a_partly_translated_survey_serves_only_current_text_and_the_rest_falls_back():
    units = build_units(survey())
    title, q = find(units, "SURVEY", "survey", "title"), find(units, "QUESTION", "age", "label")
    hint = find(units, "QUESTION", "age", "hint")
    rows = [row(title, "Bincike"), row(q, "Shekara nawa kake?"), row(hint, "Stale", hash_="old")]
    payload = reconcile.localized_payload("ha", reconcile.evaluate(units, rows, "ha")[0])
    assert payload["survey"] == {"title": "Bincike"}
    assert payload["questions"] == {"q1": {"label": "Shekara nawa kake?"}}  # the outdated hint is not served
    assert payload["choices"] == {} and payload["rtl"] is False and 0 < payload["percent_complete"] < 100
    stale = reconcile.localized_payload("ha", reconcile.evaluate(units, rows, "ha")[0], include_outdated=True)
    assert stale["questions"]["q1"]["hint"] == "Stale"


def test_localized_payload_is_keyed_by_the_current_row_ids_and_arabic_is_rtl():
    units = build_units(survey())
    yes = find(units, "CHOICE", "net::YES", "label")
    msg = find(units, "SYSTEM", "msg.required", "text")
    states, _ = reconcile.evaluate(units, [row(yes, "نعم"), row(msg, "هذا السؤال مطلوب.")], "ar")
    payload = reconcile.localized_payload("ar", states)
    assert payload["choices"] == {"c1": "نعم"} and payload["rtl"] is True
    assert payload["messages"]["msg.required"] == "هذا السؤال مطلوب."


def test_ai_never_overwrites_a_persons_work_unless_asked():
    units = build_units(survey())
    a, b, c = (find(units, "QUESTION", "age", "label"), find(units, "SURVEY", "survey", "title"),
               find(units, "QUESTION", "net", "label"))
    rows = [row(a, "x", status="EDITED"), row(b, "y", status="AI_DRAFT")]
    states, _ = reconcile.evaluate(units, rows, "ha")
    todo, protected = reconcile.select_for_translation(states, scope="all")
    assert a in protected and a not in todo and b in todo and c in todo
    todo, protected = reconcile.select_for_translation(states, scope="all", overwrite_manual=True)
    assert a in todo and not protected
    todo, _ = reconcile.select_for_translation(states, scope="missing")
    assert b not in todo and c in todo
    todo, _ = reconcile.select_for_translation(states, only={c.id})
    assert todo == [c]
    todo, _ = reconcile.select_for_translation(states, entity_types={"SYSTEM"})
    assert todo and all(u.entity_type == "SYSTEM" for u in todo)


def test_comparison_lines_up_source_and_each_language():
    units = build_units(survey(), include_system=False)
    q = find(units, "QUESTION", "age", "label")
    table = reconcile.compare(units, {"ha": [row(q, "Shekara nawa kake?")], "fr": [row(q, "Quel âge avez-vous ?")]})
    line = next(r for r in table if r["entity_key"] == "age" and r["field"] == "label")
    assert line["source"] == "How old are you?"
    assert line["translations"]["ha"]["value"] == "Shekara nawa kake?" and line["translations"]["fr"]["status"] == "AI_DRAFT"
    other = next(r for r in table if r["entity_key"] == "net" and r["field"] == "label")
    assert other["translations"]["ha"]["status"] == "MISSING"


# ------------------------------------------------------------------ Hausa rules


def hausa_findings(pairs):
    units = build_units(survey(), include_system=False)
    rows = [row(find(units, *key), value) for key, value in pairs]
    return hausa.review_rules(reconcile.evaluate(units, rows, "ha")[0])


def test_hausa_rules_flag_untranslated_english_left_over_and_missing_hooked_letters():
    q = ("QUESTION", "age", "label")
    assert any(f.category == "COMPLETENESS" for f in hausa_findings([(q, "How old are you?")]))
    assert any(f.category == "FLUENCY" for f in hausa_findings([(q, "Shekara nawa do you have?")]))
    found = [f for f in hausa_findings([(("QUESTION", "net", "label"), "Kana da kudi?")]) if f.category == "ORTHOGRAPHY"]
    assert found and found[0].suggestion == "Kana da kuɗi?"
    assert not hausa_findings([(q, "Shekara nawa kake?")])


def test_hausa_rules_flag_inconsistent_choice_translations():
    units = build_units(survey(), include_system=False)
    extra = survey()
    extra["questions"][0]["choices"] = [{"id": "c9", "value": "OTHER", "label": "Other", "order_index": 0}]
    units = build_units(extra, include_system=False)
    one, two = find(units, "CHOICE", "age::OTHER", "label"), find(units, "CHOICE", "net::OTHER", "label")
    findings = hausa.review_rules(reconcile.evaluate(units, [row(one, "Wani"), row(two, "Sauran")], "ha")[0])
    assert any(f.category == "CONSISTENCY" for f in findings)


def test_hausa_rules_skip_outdated_items_and_the_score_is_deterministic():
    units = build_units(survey(), include_system=False)
    q = find(units, "QUESTION", "age", "label")
    states, _ = reconcile.evaluate(units, [row(q, q.source, hash_="old")], "ha")
    assert hausa.review_rules(states) == []
    clean = hausa.score([], 10)
    assert clean == 100 and hausa.score([], 0) == 0
    warn = hausa.Finding("QUESTION", "age", "label", "Q", "WARNING", "FLUENCY", "m")
    sug = hausa.Finding("QUESTION", "age", "label", "Q", "SUGGESTION", "FLUENCY", "m")
    assert hausa.score([warn, sug], 10) == hausa.score([warn], 10) < 100  # one unit is penalised once, at its worst
    assert hausa.grade_for(95) == "Excellent" and hausa.grade_for(10) == "Poor"


# ------------------------------------------------------------------ fake AI


def items_of(prompt):
    return json.loads(prompt.split("ITEMS:\n", 1)[1].split("\n\nYour previous answer")[0])


class FakeAI:
    """Scripted stand-in for AIService: each call pops a handler(prompt) -> text | Exception | response."""

    def __init__(self, *handlers, max_tokens=32768):
        self.handlers = list(handlers)
        self.calls = []
        self.config = SimpleNamespace(generation_max_prompt_chars=30000, generation_max_output_tokens=max_tokens)

    def generate_text(self, prompt, **kw):
        self.calls.append(SimpleNamespace(prompt=prompt, **kw))
        handler = self.handlers.pop(0) if len(self.handlers) > 1 else self.handlers[0]
        out = handler(prompt) if callable(handler) else handler
        if isinstance(out, Exception):
            raise out
        if isinstance(out, str):
            return SimpleNamespace(text=out, model="fake", finish_reason="STOP")
        return out


def translating(transform):
    return lambda prompt: json.dumps({"translations": [{"id": i["id"], "text": transform(i["text"])} for i in items_of(prompt)]})


def units_to_translate(*keys):
    units = build_units(survey())
    return [find(units, *k) for k in keys]


def test_translation_service_translates_and_saves_nothing_it_was_not_asked_for():
    wanted = units_to_translate(("QUESTION", "age", "label"), ("CHOICE", "net::YES", "label"), ("SYSTEM", "msg.min", "text"))
    ai = FakeAI(translating(lambda t: {"How old are you?": "Shekara nawa kake?", "Yes": "Ee", "Must be at least {min}.": "Dole ne ya zama akalla {min}."}[t]))
    result = TranslationService(ai).translate("ha", wanted, survey_title="Malaria", user_id="u1")
    assert {k: v[0] for k, v in result.accepted.items()} == {
        ("QUESTION", "age", "label"): "Shekara nawa kake?", ("CHOICE", "net::YES", "label"): "Ee",
        ("SYSTEM", "msg.min", "text"): "Dole ne ya zama akalla {min}."}
    assert not result.rejected and not result.not_returned and result.ai_error is None and result.calls == 1
    sent = ai.calls[0]
    assert sent.request_type == "questionnaire_translation" and sent.json_mode is True
    for code in ("age", "net::YES", "msg.min", "YES"):  # identifiers are never sent to the model
        assert f'"{code}"' not in sent.prompt


def test_an_answer_that_breaks_a_placeholder_is_asked_again_with_the_reason():
    wanted = units_to_translate(("SYSTEM", "msg.min", "text"))
    ai = FakeAI(translating(lambda t: "Dole ne ya zama akalla {mn}."), translating(lambda t: "Dole ne ya zama akalla {min}."))
    result = TranslationService(ai).translate("ha", wanted, survey_title="S", user_id=None)
    assert result.accepted[("SYSTEM", "msg.min", "text")][0].endswith("{min}.") and not result.rejected
    assert "previous_attempt_problem" in ai.calls[1].prompt and "{min}" in ai.calls[1].prompt


def test_an_answer_that_keeps_breaking_is_rejected_never_saved():
    wanted = units_to_translate(("SYSTEM", "msg.min", "text"))
    result = TranslationService(FakeAI(translating(lambda t: "Babu wuri"))).translate("ha", wanted, survey_title="S", user_id=None)
    assert not result.accepted and len(result.rejected) == 1
    assert result.rejected[0][0].id == ("SYSTEM", "msg.min", "text") and result.rejected[0][1][0].severity == "BLOCK"


def test_unknown_ids_and_skipped_items_are_handled():
    wanted = units_to_translate(("QUESTION", "age", "label"), ("CHOICE", "net::YES", "label"))
    reply = json.dumps({"translations": [{"id": "1", "text": "Shekara nawa kake?"}, {"id": "99", "text": "ghost"}, {"id": "x"}]})
    result = TranslationService(FakeAI(reply)).translate("ha", wanted, survey_title="S", user_id=None)
    assert list(result.accepted) == [("QUESTION", "age", "label")]
    assert [u.id for u in result.not_returned] == [("CHOICE", "net::YES", "label")]


def test_invalid_json_is_repaired_once_and_a_truncated_answer_is_split():
    wanted = units_to_translate(("QUESTION", "age", "label"))
    ai = FakeAI("not json at all", translating(lambda t: "Shekara nawa kake?"))
    assert TranslationService(ai).translate("ha", wanted, survey_title="S", user_id=None).accepted
    assert "could not be used" in ai.calls[1].prompt

    two = units_to_translate(("QUESTION", "age", "label"), ("CHOICE", "net::YES", "label"))
    cut = SimpleNamespace(text='{"translations": [', model="fake", finish_reason="MAX_TOKENS")
    ai = FakeAI(cut, translating(lambda t: "Ee " + t))
    result = TranslationService(ai).translate("ha", two, survey_title="S", user_id=None)
    assert len(result.accepted) == 2 and len(ai.calls) == 3


def test_a_provider_failure_stops_the_run_and_reports_what_was_not_done():
    wanted = units_to_translate(("QUESTION", "age", "label"), ("CHOICE", "net::YES", "label"))
    result = TranslationService(FakeAI(AIQuotaExceededError())).translate("ha", wanted, survey_title="S", user_id=None)
    assert not result.accepted and len(result.not_returned) == 2 and "quota" in result.ai_error.lower()


def test_a_failed_batch_does_not_lose_the_other_batches():
    many = survey(questions=[
        {"id": f"q{i}", "code": f"q{i}", "label": f"Question number {i} " + "x" * 600, "hint": None, "order_index": i, "choices": []}
        for i in range(12)])
    units = [u for u in build_units(many, include_system=False) if u.entity_type == "QUESTION"]
    assert len(make_batches(units)) >= 2  # more than one AI call is needed
    ai = FakeAI(AIInvalidJsonError(), translating(lambda t: "Ee " + t))  # first batch fails, the rest succeed
    result = TranslationService(ai).translate("ha", units, survey_title="S", user_id=None)
    assert result.ai_error and result.not_returned and result.accepted
    assert len(result.accepted) + len(result.not_returned) == len(units)


def test_parse_translations_accepts_a_bare_list_and_rejects_rubbish():
    assert parse_translations('[{"id": 1, "text": "a"}]') == {"1": "a"}
    for bad in ('{"translations": "no"}', '{"translations": []}', "[]"):
        try:
            parse_translations(bad)
        except Exception as exc:  # noqa: BLE001
            assert getattr(exc, "code", "").startswith("AI_")
        else:
            raise AssertionError(bad)


# ------------------------------------------------------------------ Hausa review service


def hausa_states():
    units = build_units(survey(), include_system=False)
    q, hint, yes = (find(units, "QUESTION", "age", "label"), find(units, "QUESTION", "age", "hint"),
                    find(units, "CHOICE", "net::YES", "label"))
    rows = [row(q, "Shekara nawa kake?"), row(hint, "Shekaru, 18 ko fiye", status="REVIEWED"), row(yes, "Ee")]
    return reconcile.evaluate(units, rows, "ha")[0]


def test_hausa_review_keeps_only_valid_ai_findings_and_skips_reviewed_items():
    reply = json.dumps({"summary": "Mostly natural.", "findings": [
        {"id": "1", "severity": "SUGGESTION", "category": "REGISTER", "message": "Use the polite form.", "suggestion": "Shekaru nawa kuke da su?"},
        {"id": "1", "severity": "CRITICAL", "category": "ACCURACY", "message": "AI cannot raise critical."},
        {"id": "99", "severity": "WARNING", "category": "ACCURACY", "message": "unknown item"},
        {"id": "2", "severity": "WARNING", "category": "NONSENSE", "message": "bad category"},
        {"id": "2", "severity": "WARNING", "category": "ACCURACY", "message": "Meaning differs.", "suggestion": "   "},
    ]})
    ai = FakeAI(reply)
    report = HausaReviewer(ai).review(hausa_states(), survey_title="S", use_ai=True, user_id="u")
    sent_items = items_of(ai.calls[0].prompt)
    assert len(sent_items) == 2 and all(i["hausa"] != "Shekaru, 18 ko fiye" for i in sent_items)  # human-approved text is not re-reviewed
    assert report.ai_used and report.skipped_reviewed_by_ai == 1 and report.reviewed_units == 3
    messages = {(f.source, f.message) for f in report.findings}
    assert ("AI", "Use the polite form.") in messages and ("AI", "Meaning differs.") in messages
    assert not any(f.message in ("AI cannot raise critical.", "unknown item", "bad category") for f in report.findings)
    assert next(f for f in report.findings if f.message == "Use the polite form.").suggestion == "Shekaru nawa kuke da su?"
    assert "native-speaker" in " ".join(report.limitations) and "Mostly natural." in report.summary


def test_hausa_review_drops_a_suggestion_that_breaks_the_rules():
    units = build_units(survey())
    msg = find(units, "SYSTEM", "msg.min", "text")
    states = reconcile.evaluate(units, [row(msg, "Dole ne ya zama akalla {min}.")], "ha")[0]
    reply = json.dumps({"findings": [{"id": "1", "severity": "SUGGESTION", "category": "FLUENCY", "message": "Rephrase.",
                                      "suggestion": "Akalla {mn} ake bukata."}]})
    report = HausaReviewer(FakeAI(reply)).review(states, survey_title="S", use_ai=True, user_id=None)
    finding = next(f for f in report.findings if f.source == "AI")
    assert finding.suggestion is None  # the suggested text lost {min}, so it is never offered


def test_hausa_review_still_reports_when_the_ai_fails_or_is_off():
    report = HausaReviewer(FakeAI(AIQuotaExceededError())).review(hausa_states(), survey_title="S", use_ai=True, user_id=None)
    assert report.ai_used is False and report.ai_error and report.reviewed_units == 3 and 0 <= report.score <= 100
    off = HausaReviewer(FakeAI("{}")).review(hausa_states(), survey_title="S", use_ai=False, user_id=None)
    assert off.ai_used is False and "switched off" in off.ai_error
    empty = HausaReviewer(FakeAI("{}")).review(reconcile.evaluate(build_units(survey()), [], "ha")[0], survey_title="S", use_ai=True, user_id=None)
    assert empty.reviewed_units == 0 and empty.score == 0 and "no up-to-date" in empty.summary
