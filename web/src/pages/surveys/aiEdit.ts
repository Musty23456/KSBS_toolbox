// Pure helpers for the AI questionnaire editor (Phase 3). No React, no network: unit tested.
//
// Safety rules these helpers encode:
//  * a proposal may only be applied to the exact draft it was made for (`baseKey`);
//  * a large deletion needs an explicit confirmation;
//  * "Undo AI change" only works while the draft still equals what that change produced, so it can
//    never throw away edits the person made afterwards (they have the normal Undo for those).

import type { EditChangeSummary, EditPreview, EditSnapshot } from "../../api/types";
import type { DraftStructure } from "./aiDraft";

export const HISTORY_LIMIT = 20;

/** What is sent to the server: the editable part of the draft, nothing else. */
export function toSnapshot(draft: DraftStructure): EditSnapshot {
  return { sections: draft.sections, groups: draft.groups, questions: draft.questions };
}

/** A stable fingerprint of a draft's structure (sections, groups, questions). */
export function structureKey(draft: DraftStructure): string {
  return JSON.stringify(toSnapshot(draft));
}

// ------------------------------------------------------------------ applying

export function selectedOperations(preview: Pick<EditPreview, "operations">, deselected: ReadonlySet<number>) {
  return preview.operations.filter((o) => !deselected.has(o.index)).map((o) => o.raw);
}

export interface ApplyCheck {
  ok: boolean;
  reason: string | null;
}

export function checkApply(
  preview: EditPreview | null,
  opts: { draftUnchanged: boolean; confirmed: boolean; busy: boolean }
): ApplyCheck {
  if (!preview) return { ok: false, reason: "There is nothing to apply." };
  if (opts.busy) return { ok: false, reason: "Checking your selection…" };
  if (preview.blocked) return { ok: false, reason: preview.blocked };
  if (!preview.has_changes) return { ok: false, reason: "No changes to apply." };
  if (!opts.draftUnchanged) {
    return { ok: false, reason: "The questionnaire was edited after this proposal was made. Reject it and ask again." };
  }
  if (preview.requires_confirmation && !opts.confirmed) {
    return { ok: false, reason: "Tick the box to confirm the deletions." };
  }
  return { ok: true, reason: null };
}

export function summaryText(s: EditChangeSummary): string {
  const parts: string[] = [];
  const q = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
  if (s.added_questions) parts.push(`${q(s.added_questions, "question")} added`);
  if (s.modified_questions) parts.push(`${q(s.modified_questions, "question")} changed`);
  if (s.deleted_questions) parts.push(`${q(s.deleted_questions, "question")} deleted`);
  if (s.added_sections) parts.push(`${q(s.added_sections, "section")} added`);
  if (s.modified_sections) parts.push(`${q(s.modified_sections, "section")} changed`);
  if (s.deleted_sections) parts.push(`${q(s.deleted_sections, "section")} deleted`);
  if (s.reordered_questions || s.reordered_sections) parts.push("order changed");
  return parts.length ? parts.join(" · ") : "No changes";
}

/** Short, human text for a value in the before/after view. */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "(none)";
  if (value === true) return "Yes";
  if (value === false) return "No";
  return String(value);
}

// ------------------------------------------------------------------- history

export interface AIHistoryEntry {
  label: string;
  before: DraftStructure;
  after: DraftStructure;
  beforeKey: string;
  afterKey: string;
}

export interface AIHistory {
  undo: AIHistoryEntry[];
  redo: AIHistoryEntry[];
}

export const emptyHistory: AIHistory = { undo: [], redo: [] };

export function recordChange(history: AIHistory, label: string, before: DraftStructure, after: DraftStructure): AIHistory {
  const entry: AIHistoryEntry = { label, before, after, beforeKey: structureKey(before), afterKey: structureKey(after) };
  return { undo: [...history.undo, entry].slice(-HISTORY_LIMIT), redo: [] };
}

export function canUndoChange(history: AIHistory, current: DraftStructure): boolean {
  const top = history.undo[history.undo.length - 1];
  return !!top && top.afterKey === structureKey(current);
}

export function canRedoChange(history: AIHistory, current: DraftStructure): boolean {
  const top = history.redo[history.redo.length - 1];
  return !!top && top.beforeKey === structureKey(current);
}

export function undoChange(history: AIHistory, current: DraftStructure) {
  if (!canUndoChange(history, current)) return null;
  const entry = history.undo[history.undo.length - 1];
  return { structure: entry.before, entry, history: { undo: history.undo.slice(0, -1), redo: [...history.redo, entry] } };
}

export function redoChange(history: AIHistory, current: DraftStructure) {
  if (!canRedoChange(history, current)) return null;
  const entry = history.redo[history.redo.length - 1];
  return { structure: entry.after, entry, history: { undo: [...history.undo, entry], redo: history.redo.slice(0, -1) } };
}

// ------------------------------------------------------------ version notes

export interface VersionNote {
  text: string;
  /** True for notes about AI-assistant changes. */
  ai: boolean;
}

/** The note stored with the next saved version, and whether it counts as an AI edit. */
export function versionNote(notes: VersionNote[]): { source: "MANUAL" | "AI_EDIT"; summary: string } | undefined {
  if (!notes.length) return undefined;
  const ai = notes.filter((n) => n.ai).map((n) => n.text);
  const other = notes.filter((n) => !n.ai).map((n) => n.text);
  const parts = [...(ai.length ? [`AI assistant: ${ai.join("; ")}`] : []), ...other];
  const text = parts.join(". ");
  return { source: ai.length ? "AI_EDIT" : "MANUAL", summary: text.length <= 1000 ? text : `${text.slice(0, 997)}…` };
}

export const EXAMPLE_COMMANDS: readonly string[] = [
  "Add five questions about education",
  "Translate question 3 into Hausa",
  "Make question 5 compulsory",
  "Remove duplicate questions",
  "Add a new section about employment",
  "Change question 4 to multiple choice",
  "Shorten all questions",
  "Add answer options to question 2",
  "Reorganize the sections in a logical order",
  "Improve the wording of all questions",
];
