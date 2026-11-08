// Pure helpers for the AI questionnaire reviewer (Phase 4). No React, no network: unit tested.
//
// Safety rules these helpers encode:
//  * a review never changes the draft; only an explicit "Apply" does, through the Phase 3 preview;
//  * ignoring a finding only hides it (it is remembered by its stable id), nothing else changes;
//  * a report is "stale" once the draft differs from what was reviewed.

import type { ReviewFinding, ReviewReport, ReviewSeverity } from "../../api/types";

export const SEVERITY_ORDER: readonly ReviewSeverity[] = ["CRITICAL", "WARNING", "SUGGESTION", "GOOD"];

export const SEVERITY_TITLE: Record<ReviewSeverity, string> = {
  CRITICAL: "Critical issues",
  WARNING: "Warnings",
  SUGGESTION: "Suggestions",
  GOOD: "Good practices",
};

export const CATEGORY_LABEL: Record<string, string> = {
  CLARITY: "Clarity",
  GRAMMAR: "Grammar",
  DUPLICATE: "Repeated question",
  AMBIGUITY: "Ambiguity",
  BIAS: "Leading / biased",
  CHOICES: "Answer choices",
  QUESTION_TYPE: "Question type",
  REQUIRED: "Required fields",
  CONSISTENCY: "Consistency",
  SKIP_LOGIC: "Skip logic",
  VALIDATION: "Validation",
  COVERAGE: "Objectives coverage",
  STRUCTURE: "Structure",
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABEL[category] ?? category;
}

export interface GroupedFindings {
  groups: Record<ReviewSeverity, ReviewFinding[]>;
  /** Findings the person chose to ignore (any severity). */
  ignored: ReviewFinding[];
}

/** Split findings by severity; ignored ones are set apart so they never nag but can be restored. */
export function groupFindings(findings: readonly ReviewFinding[], ignoredIds: ReadonlySet<string>): GroupedFindings {
  const groups: Record<ReviewSeverity, ReviewFinding[]> = { CRITICAL: [], WARNING: [], SUGGESTION: [], GOOD: [] };
  const ignored: ReviewFinding[] = [];
  for (const f of findings) {
    if (ignoredIds.has(f.id)) ignored.push(f);
    else groups[f.severity].push(f);
  }
  return { groups, ignored };
}

export function canApply(f: ReviewFinding): boolean {
  return f.severity !== "GOOD" && f.fix !== null && typeof f.fix === "object";
}

/** True when the draft is no longer the one that was reviewed. */
export function isStale(reviewedKey: string | null, currentKey: string): boolean {
  return reviewedKey !== null && reviewedKey !== currentKey;
}

export function scoreTone(score: number): "good" | "fair" | "poor" {
  return score >= 75 ? "good" : score >= 55 ? "fair" : "poor";
}

/** The number of non-ignored problems still open (what the person still has to look at). */
export function openProblemCount(findings: readonly ReviewFinding[], ignoredIds: ReadonlySet<string>): number {
  return findings.filter((f) => f.severity !== "GOOD" && !ignoredIds.has(f.id)).length;
}

/** A plain-text report the person can copy or save. Ignored findings are listed separately. */
export function reportToMarkdown(report: ReviewReport, ignoredIds: ReadonlySet<string>, title = "Questionnaire review"): string {
  const { groups, ignored } = groupFindings(report.findings, ignoredIds);
  const out: string[] = [`# ${title}`, "", `**Quality score: ${report.score}/100 (${report.grade})**`, "", report.summary, ""];
  out.push(
    `Reviewed ${report.stats.questions} questions in ${report.stats.sections} sections` +
      (report.ai_used ? " with AI assistance." : " using built-in rule checks only.")
  );
  out.push("");
  for (const sev of SEVERITY_ORDER) {
    const items = groups[sev];
    if (!items.length) continue;
    out.push(`## ${SEVERITY_TITLE[sev]} (${items.length})`, "");
    for (const f of items) {
      out.push(`### ${f.title}`);
      out.push(`*${categoryLabel(f.category)}${f.question_code ? ` · ${f.question_code}` : ""}*`);
      if (f.question_label) out.push(`> ${f.question_label}`);
      if (f.explanation) out.push("", f.explanation);
      if (f.recommendation) out.push("", `**Recommended:** ${f.recommendation}`);
      out.push("");
    }
  }
  if (report.coverage.length) {
    out.push("## Research objectives", "");
    for (const c of report.coverage) {
      out.push(`- ${c.covered ? "✅" : "❌"} ${c.objective}${c.question_codes.length ? ` (${c.question_codes.join(", ")})` : ""}${c.note ? ` — ${c.note}` : ""}`);
    }
    out.push("");
  }
  if (ignored.length) {
    out.push(`## Ignored (${ignored.length})`, "", ...ignored.map((f) => `- ${f.title}${f.question_code ? ` (${f.question_code})` : ""}`), "");
  }
  if (report.limitations.length) out.push("## Limitations", "", ...report.limitations.map((l) => `- ${l}`), "");
  return out.join("\n");
}
