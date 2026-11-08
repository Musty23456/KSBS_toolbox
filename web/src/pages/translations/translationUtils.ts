/** Pure helpers for the multilingual screens (no React), so they can be unit tested. */

import type { I18nLocalized, I18nUnit, TranslationStatus } from "../../api/types";

export const STATUS_LABEL: Record<TranslationStatus, string> = {
  MISSING: "Missing",
  OUTDATED: "Outdated",
  AI_DRAFT: "AI draft",
  EDITED: "Edited",
  REVIEWED: "Reviewed",
};

export type UnitFilter = "all" | "attention" | "missing" | "outdated" | "issues" | "ai_draft" | "unreviewed";

/** Which units a filter keeps. "attention" = needs a person: missing, outdated or has a warning. */
export function filterUnits(units: I18nUnit[], filter: UnitFilter, search = ""): I18nUnit[] {
  const needle = search.trim().toLowerCase();
  return units.filter((u) => {
    const hasIssue = u.value !== null && u.issues.length > 0;
    const keep =
      filter === "all" ||
      (filter === "missing" && u.status === "MISSING") ||
      (filter === "outdated" && u.status === "OUTDATED") ||
      (filter === "issues" && hasIssue) ||
      (filter === "ai_draft" && u.status === "AI_DRAFT") ||
      (filter === "unreviewed" && (u.status === "AI_DRAFT" || u.status === "EDITED")) ||
      (filter === "attention" && (u.status === "MISSING" || u.status === "OUTDATED" || hasIssue));
    if (!keep) return false;
    if (!needle) return true;
    return u.source.toLowerCase().includes(needle) || (u.value ?? "").toLowerCase().includes(needle) || u.label.toLowerCase().includes(needle);
  });
}

export function unitKey(u: { entity_type: string; entity_key: string; field: string }): string {
  return `${u.entity_type}|${u.entity_key}|${u.field}`;
}

/** Fill {name} placeholders. A placeholder with no value is left as written. */
export function fillTemplate(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{([A-Za-z_][A-Za-z0-9_.]*)\}/g, (whole, name: string) => (name in vars ? String(vars[name]) : whole));
}

/** A standard message in the chosen language, or the English fallback. */
export function message(
  loc: I18nLocalized | null,
  key: string,
  fallback: string,
  vars: Record<string, string | number> = {}
): string {
  return fillTemplate(loc?.messages?.[key] || fallback, vars);
}

/** Text of a question / section / group / survey in the chosen language, field by field, falling back to the original. */
export function pickText(translated: string | undefined, original: string): string;
export function pickText(translated: string | undefined, original: string | null | undefined): string | null | undefined;
export function pickText(translated: string | undefined, original: string | null | undefined) {
  return translated && translated.trim() ? translated : original;
}

export function languageStorageKey(surveyId: string): string {
  return `kbs_fill_language:${surveyId}`;
}

/** The language to start in: the person's last choice for this survey if it is still offered, else the original. */
export function initialLanguage(stored: string | null, offered: string[]): string {
  return stored && offered.includes(stored) ? stored : "";
}

/** True when a translation needs a person's attention before the survey goes to the field. */
export function needsAttention(summary: { missing: number; outdated: number; blocked: number }): boolean {
  return summary.missing + summary.outdated + summary.blocked > 0;
}
