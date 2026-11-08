"""
The questionnaire quality score (0-100). Computed by code from the findings, never by the AI, so the
same findings always give the same score.

    penalty  = (10 x critical + 4 x warning + 1 x suggestion) x size_scale, each severity capped
    size_scale = min(1, 20 / number_of_questions)   - problems are judged by how common they are
    bonus    = +1 per good practice (max +5), only when there is no critical issue
"""

from __future__ import annotations

from app.ai.questionnaire_review.schemas import Finding, ScoreBreakdown

WEIGHTS = {"CRITICAL": 10.0, "WARNING": 4.0, "SUGGESTION": 1.0}
CAPS = {"CRITICAL": 60.0, "WARNING": 30.0, "SUGGESTION": 10.0}
MAX_BONUS = 5

GRADES: tuple[tuple[int, str], ...] = (
    (90, "Excellent"),
    (75, "Good"),
    (60, "Fair"),
    (40, "Needs improvement"),
    (0, "Poor"),
)


def grade_for(score: int) -> str:
    return next(label for floor, label in GRADES if score >= floor)


def count_by_severity(findings: list[Finding]) -> dict[str, int]:
    counts = {"CRITICAL": 0, "WARNING": 0, "SUGGESTION": 0, "GOOD": 0}
    for f in findings:
        counts[f.severity] += 1
    return counts


def compute_score(findings: list[Finding], n_questions: int) -> tuple[int, ScoreBreakdown]:
    counts = count_by_severity(findings)
    if n_questions == 0:  # nothing to collect: no quality to score
        return 0, ScoreBreakdown(critical_penalty=100.0)
    scale = min(1.0, 20.0 / max(1, n_questions))
    penalties = {sev: min(CAPS[sev], WEIGHTS[sev] * counts[sev] * scale) for sev in WEIGHTS}
    bonus = float(min(MAX_BONUS, counts["GOOD"])) if counts["CRITICAL"] == 0 else 0.0
    raw = 100.0 - sum(penalties.values()) + bonus
    score = int(round(max(0.0, min(100.0, raw))))
    return score, ScoreBreakdown(
        critical_penalty=round(penalties["CRITICAL"], 1),
        warning_penalty=round(penalties["WARNING"], 1),
        suggestion_penalty=round(penalties["SUGGESTION"], 1),
        good_practice_bonus=bonus,
        size_scale=round(scale, 3),
    )
