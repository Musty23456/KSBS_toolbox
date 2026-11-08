"""Phase 4 tests: rule checks, fixes and scoring on sample questionnaires (no AI, no database)."""

import copy
import json
from pathlib import Path

import pytest

from app.ai.questionnaire_edit.diff import preview_operations
from app.ai.questionnaire_edit.snapshot import Snapshot
from app.ai.questionnaire_review.fixes import verify_fixes
from app.ai.questionnaire_review.rules import keyword_coverage, mechanical_fix, run_rules, split_objectives
from app.ai.questionnaire_review.scoring import compute_score, count_by_severity, grade_for
from app.ai.questionnaire_review.schemas import Finding, finding_id

FIX = Path(__file__).parent / "fixtures" / "review"


def load(name):
    return json.loads((FIX / f"{name}.json").read_text())


def snap(name):
    return Snapshot.model_validate(load(name))


def review(name):
    s = snap(name)
    r = run_rules(s)
    return s, verify_fixes(s, r.findings)


def titles(findings, severity=None, category=None):
    return [f.title for f in findings if (severity is None or f.severity == severity) and (category is None or f.category == category)]


def find(findings, category, code, contains=""):
    hits = [f for f in findings if f.category == category and f.question_code == code and contains in f.title]
    assert hits, f"no {category} finding for {code} containing {contains!r}; have {[(f.category, f.question_code, f.title) for f in findings]}"
    return hits[0]


# ------------------------------------------------------------------ sample questionnaires


def test_well_designed_questionnaire_scores_high_with_no_critical_or_warning():
    s, findings = review("well_designed")
    counts = count_by_severity(findings)
    assert counts["CRITICAL"] == 0 and counts["WARNING"] == 0
    assert counts["GOOD"] >= 4
    assert compute_score(findings, len(s.questions))[0] >= 90


def test_flawed_questionnaire_finds_each_planted_problem():
    _, f = review("flawed")
    find(f, "CHOICES", "nochoices", "fewer than two")            # missing answer choices
    find(f, "SKIP_LOGIC", "bad_skip")                             # skip logic uses a later question
    find(f, "DUPLICATE", "age2", "Repeats")                       # repeated question
    find(f, "BIAS", "lead")                                       # leading wording
    find(f, "AMBIGUITY", "often", "often")                        # vague term
    find(f, "QUESTION_TYPE", "age", "number")                     # number as text
    find(f, "QUESTION_TYPE", "modes", "several answers")          # inappropriate type
    find(f, "CHOICES", "ageband", "Overlapping")                  # inconsistent/overlapping options
    find(f, "REQUIRED", "consent", "Consent")                     # missing required
    find(f, "REQUIRED", "income", "Sensitive")
    find(f, "GRAMMAR", "name")                                    # grammar clean-up
    find(f, "STRUCTURE", "S2", "no questions")                    # empty section
    assert {x.severity for x in f if x.category == "SKIP_LOGIC" and x.question_code == "bad_skip"} == {"CRITICAL"}


def test_flawed_questionnaire_scores_much_lower_than_the_good_one():
    sg, g = review("well_designed")
    sf, f = review("flawed")
    assert compute_score(f, len(sf.questions))[0] <= compute_score(g, len(sg.questions))[0] - 40


def test_empty_questionnaire_is_critical_and_scores_zero():
    s, f = review("minimal")
    assert titles(f, "CRITICAL") == ["The questionnaire has no questions"]
    assert compute_score(f, 0)[0] == 0


def test_how_many_is_not_called_vague():
    _, f = review("well_designed")
    assert not any("Vague term" in t for t in titles(f))


# ------------------------------------------------------------------ review never changes the input


def test_rules_never_mutate_the_questionnaire():
    data = load("flawed")
    before = copy.deepcopy(data)
    s = Snapshot.model_validate(data)
    verify_fixes(s, run_rules(s).findings)
    assert data == before
    assert Snapshot.model_validate(before).model_dump() == s.model_dump()


# ------------------------------------------------------------------ fixes


def test_every_fix_that_survives_verification_applies_cleanly_and_changes_something():
    s, f = review("flawed")
    fixes = [x for x in f if x.fix]
    assert len(fixes) >= 8
    for x in fixes:
        p = preview_operations(s, [x.fix])
        assert p.has_changes and not p.rejected and not p.blocked and not p.requires_confirmation, x.title
        assert x.fix_summary


def test_fix_changes_what_it_promises():
    s, f = review("flawed")
    p = preview_operations(s, [find(f, "QUESTION_TYPE", "age", "number").fix])
    changed = {m.code: {fc.field: fc.after for fc in m.fields} for m in p.modified}
    assert changed["age"]["type"] == "INTEGER"
    p = preview_operations(s, [find(f, "REQUIRED", "consent", "Consent").fix])
    assert {fc.field: fc.after for m in p.modified for fc in m.fields if m.code == "consent"}["is_required"] is True


def test_a_fix_that_the_engine_refuses_is_dropped_but_the_finding_stays():
    s = snap("flawed")
    bad = Finding(id="x", severity="WARNING", category="CLARITY", question_code="nope", title="t", fix={"op": "DELETE_QUESTION", "code": "does_not_exist"})
    worse = Finding(id="y", severity="WARNING", category="CLARITY", question_code="age", title="t2", fix={"op": "EXPLODE"})
    out = verify_fixes(s, [bad, worse])
    assert len(out) == 2 and all(x.fix is None for x in out)


def test_fix_that_would_need_confirmation_is_not_offered():
    data = load("well_designed")
    s = Snapshot.model_validate(data)
    f = Finding(id="z", severity="WARNING", category="DUPLICATE", question_code="has_children", title="t",
                fix={"op": "DELETE_QUESTION", "code": "has_children"})  # n_children's skip logic depends on it
    assert verify_fixes(s, [f])[0].fix is None


def test_mechanical_fix_only_does_mechanical_things():
    assert mechanical_fix("how old are you") == "How old are you?"
    assert mechanical_fix("What  is your  name ?") == "What is your name?"
    assert mechanical_fix("Do you you own a phone?") == "Do you own a phone?"
    assert mechanical_fix("Had had enough?") == "Had had enough?"
    assert mechanical_fix("Mene ne sunan ka?") == "Mene ne sunan ka?"  # other languages untouched
    assert mechanical_fix("Please describe the problem:") == "Please describe the problem:"


def test_finding_ids_are_stable_so_ignored_items_stay_ignored():
    _, a = review("flawed")
    _, b = review("flawed")
    assert [x.id for x in a] == [x.id for x in b]
    assert len({x.id for x in a}) == len(a)
    assert finding_id("BIAS", "q1", "A  Title!") == finding_id("BIAS", "q1", "a title")


# ------------------------------------------------------------------ scoring


def mk(sev, n=1):
    return [Finding(id=f"{sev}{i}", severity=sev, category="CLARITY", title="t") for i in range(n)]


def test_score_is_deterministic_bounded_and_ordered():
    assert compute_score([], 10)[0] == 100
    assert compute_score(mk("CRITICAL"), 20)[0] == 90
    assert compute_score(mk("WARNING"), 20)[0] == 96
    assert compute_score(mk("SUGGESTION"), 20)[0] == 99
    assert compute_score(mk("CRITICAL", 50), 20)[0] == 40       # critical penalty is capped
    assert 0 <= compute_score(mk("CRITICAL", 50) + mk("WARNING", 50) + mk("SUGGESTION", 50), 5)[0] <= 100
    assert compute_score(mk("CRITICAL"), 20)[0] < compute_score(mk("WARNING"), 20)[0] < compute_score(mk("SUGGESTION"), 20)[0]


def test_good_practices_raise_score_only_without_critical_issues():
    assert compute_score(mk("WARNING", 3) + mk("GOOD", 3), 20)[0] == 91
    assert compute_score(mk("CRITICAL") + mk("GOOD", 3), 20)[0] == 90
    assert compute_score(mk("GOOD", 9), 20)[0] == 100


def test_the_same_problem_costs_less_in_a_bigger_questionnaire():
    assert compute_score(mk("WARNING"), 80)[0] > compute_score(mk("WARNING"), 10)[0] - 1
    assert compute_score(mk("WARNING", 2), 80)[0] >= compute_score(mk("WARNING", 2), 20)[0]


@pytest.mark.parametrize("score,grade", [(100, "Excellent"), (90, "Excellent"), (89, "Good"), (75, "Good"), (60, "Fair"), (40, "Needs improvement"), (39, "Poor"), (0, "Poor")])
def test_grades(score, grade):
    assert grade_for(score) == grade


# ------------------------------------------------------------------ objectives


def test_split_objectives():
    assert split_objectives("1. Measure clinic use\n2) Understand satisfaction; 3. Household income") == [
        "Measure clinic use", "Understand satisfaction", "Household income"]
    assert split_objectives("   ") == [] and split_objectives(None) == []


def test_keyword_coverage_flags_an_objective_the_questions_do_not_address():
    from app.ai.questionnaire_edit.snapshot import WorkingState

    state = WorkingState.from_snapshot(snap("well_designed"))
    cov = keyword_coverage(state, ["Measure satisfaction with clinic service", "Assess access to clean drinking water"])
    assert cov[0].covered and "clinic_rating" in cov[0].question_codes
    assert not cov[1].covered
