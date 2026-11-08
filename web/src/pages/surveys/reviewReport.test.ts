import assert from "node:assert/strict";
import { test } from "node:test";
import type { ReviewFinding, ReviewReport } from "../../api/types";
import {
  canApply,
  groupFindings,
  isStale,
  openProblemCount,
  reportToMarkdown,
  scoreTone,
  SEVERITY_ORDER,
} from "./reviewReport";

function f(id: string, severity: ReviewFinding["severity"], extra: Partial<ReviewFinding> = {}): ReviewFinding {
  return {
    id, severity, category: "CLARITY", question_code: null, question_label: null, title: `Finding ${id}`,
    explanation: "", recommendation: "", fix: null, fix_summary: null, source: "RULE", ...extra,
  };
}

const findings = [f("a", "CRITICAL"), f("b", "WARNING", { fix: { op: "DELETE_QUESTION", code: "q1" } }), f("c", "SUGGESTION"), f("d", "GOOD"), f("e", "WARNING")];

function report(): ReviewReport {
  return {
    score: 72, grade: "Fair", summary: "Mixed.", counts: { CRITICAL: 1, WARNING: 2, SUGGESTION: 1, GOOD: 1 }, findings,
    coverage: [{ objective: "Measure clinic use", covered: false, question_codes: [], note: "None" }], objectives_checked: true,
    stats: { questions: 5, sections: 2, required_questions: 1, questions_with_hints: 0, choice_questions: 1, questions_with_skip_logic: 0 },
    score_breakdown: { critical_penalty: 10, warning_penalty: 8, suggestion_penalty: 1, good_practice_bonus: 0, size_scale: 1 },
    ai_used: false, ai_error: null, model: "", generated_at: "2026-01-01T00:00:00+00:00", limitations: ["Only rules ran."],
  };
}

test("findings are divided into the four groups in severity order", () => {
  const { groups, ignored } = groupFindings(findings, new Set());
  assert.deepEqual(SEVERITY_ORDER, ["CRITICAL", "WARNING", "SUGGESTION", "GOOD"]);
  assert.deepEqual(groups.CRITICAL.map((x) => x.id), ["a"]);
  assert.deepEqual(groups.WARNING.map((x) => x.id), ["b", "e"]);
  assert.deepEqual(groups.SUGGESTION.map((x) => x.id), ["c"]);
  assert.deepEqual(groups.GOOD.map((x) => x.id), ["d"]);
  assert.equal(ignored.length, 0);
});

test("ignoring a finding hides it from its group and keeps it restorable", () => {
  const { groups, ignored } = groupFindings(findings, new Set(["b"]));
  assert.deepEqual(groups.WARNING.map((x) => x.id), ["e"]);
  assert.deepEqual(ignored.map((x) => x.id), ["b"]);
  assert.equal(openProblemCount(findings, new Set(["b", "d"])), 3); // good practices never count as problems
});

test("only findings with a checked fix can be applied, never good practices", () => {
  assert.equal(canApply(findings[1]), true);
  assert.equal(canApply(findings[0]), false);
  assert.equal(canApply(f("g", "GOOD", { fix: { op: "DELETE_QUESTION", code: "q" } })), false);
});

test("a report is stale once the draft changed", () => {
  assert.equal(isStale(null, "x"), false);
  assert.equal(isStale("x", "x"), false);
  assert.equal(isStale("x", "y"), true);
});

test("score tone", () => {
  assert.equal(scoreTone(90), "good");
  assert.equal(scoreTone(60), "fair");
  assert.equal(scoreTone(30), "poor");
});

test("markdown report has score, groups, objectives, ignored items and limitations", () => {
  const md = reportToMarkdown(report(), new Set(["e"]));
  assert.match(md, /\*\*Quality score: 72\/100 \(Fair\)\*\*/);
  assert.match(md, /## Critical issues \(1\)/);
  assert.match(md, /## Warnings \(1\)/);
  assert.match(md, /## Good practices \(1\)/);
  assert.match(md, /❌ Measure clinic use/);
  assert.match(md, /## Ignored \(1\)\n\n- Finding e/);
  assert.match(md, /- Only rules ran\./);
  assert.ok(md.indexOf("Critical issues") < md.indexOf("Warnings") && md.indexOf("Warnings") < md.indexOf("Good practices"));
});
