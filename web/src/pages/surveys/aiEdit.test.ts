import assert from "node:assert/strict";
import { test } from "node:test";
import type { EditPreview, Question } from "../../api/types";
import {
  HISTORY_LIMIT,
  canRedoChange,
  canUndoChange,
  checkApply,
  emptyHistory,
  formatValue,
  recordChange,
  redoChange,
  selectedOperations,
  structureKey,
  summaryText,
  toSnapshot,
  undoChange,
  versionNote,
} from "./aiEdit";

const q = (code: string): Question => ({ code, label: code, type: "SHORT_TEXT", order_index: 1, is_required: false, choices: [] });
const draft = (...codes: string[]) => ({ sections: [{ title: "S", order_index: 1 }], groups: [], questions: codes.map(q) });

const preview = (over: Partial<EditPreview> = {}): EditPreview => ({
  operations: [
    { index: 0, op: "A", summary: "a", reason: null, raw: { op: "A" } },
    { index: 2, op: "B", summary: "b", reason: null, raw: { op: "B" } },
  ],
  rejected: [],
  warnings: [],
  added: [],
  modified: [],
  deleted: [],
  order_changes: [],
  summary: {
    added_questions: 0, modified_questions: 0, deleted_questions: 0, added_sections: 0, modified_sections: 0,
    deleted_sections: 0, reordered_questions: 0, reordered_sections: 0, questions_before: 2, questions_after: 2,
  },
  has_changes: true,
  blocked: null,
  requires_confirmation: false,
  confirmation_reasons: [],
  result: { sections: [], groups: [], questions: [] },
  ...over,
});

const ok = { draftUnchanged: true, confirmed: false, busy: false };

test("only the ticked operations are re-submitted, as originally proposed", () => {
  assert.deepEqual(selectedOperations(preview(), new Set()), [{ op: "A" }, { op: "B" }]);
  assert.deepEqual(selectedOperations(preview(), new Set([0])), [{ op: "B" }]);
  assert.deepEqual(selectedOperations(preview(), new Set([0, 2])), []);
});

test("snapshot carries exactly sections, groups and questions", () => {
  assert.deepEqual(Object.keys(toSnapshot(draft("a"))).sort(), ["groups", "questions", "sections"]);
});

test("apply is allowed only for a valid, unblocked, unchanged-base proposal", () => {
  assert.equal(checkApply(preview(), ok).ok, true);
  assert.equal(checkApply(null, ok).ok, false);
  assert.equal(checkApply(preview(), { ...ok, busy: true }).ok, false);
  assert.equal(checkApply(preview({ has_changes: false }), ok).ok, false);
  const blocked = checkApply(preview({ blocked: "would delete every question" }), ok);
  assert.equal(blocked.ok, false);
  assert.match(blocked.reason ?? "", /every question/);
});

test("apply is refused when the draft was edited after the proposal", () => {
  const r = checkApply(preview(), { ...ok, draftUnchanged: false });
  assert.equal(r.ok, false);
  assert.match(r.reason ?? "", /edited after/);
});

test("large deletions need the confirmation box", () => {
  const big = preview({ requires_confirmation: true, confirmation_reasons: ["This change deletes 5 of the 8 questions."] });
  assert.equal(checkApply(big, ok).ok, false);
  assert.equal(checkApply(big, { ...ok, confirmed: true }).ok, true);
});

test("summary text names every kind of change", () => {
  const s = preview().summary;
  assert.equal(summaryText(s), "No changes");
  assert.equal(
    summaryText({ ...s, added_questions: 5, modified_questions: 1, deleted_questions: 2, added_sections: 1, reordered_questions: 3 }),
    "5 questions added · 1 question changed · 2 questions deleted · 1 section added · order changed"
  );
});

test("values are shown in plain words", () => {
  assert.equal(formatValue(null), "(none)");
  assert.equal(formatValue(""), "(none)");
  assert.equal(formatValue(true), "Yes");
  assert.equal(formatValue(false), "No");
  assert.equal(formatValue(18), "18");
});

test("undo and redo walk back and forward through AI changes", () => {
  const d0 = draft("a", "b");
  const d1 = draft("a", "b", "c");
  const d2 = draft("a", "b", "c", "d");
  let h = recordChange(emptyHistory, "add c", d0, d1);
  h = recordChange(h, "add d", d1, d2);

  assert.equal(canUndoChange(h, d2), true);
  const u1 = undoChange(h, d2)!;
  assert.equal(structureKey(u1.structure), structureKey(d1));
  assert.equal(u1.entry.label, "add d");
  const u2 = undoChange(u1.history, d1)!;
  assert.equal(structureKey(u2.structure), structureKey(d0));
  assert.equal(undoChange(u2.history, d0), null);

  assert.equal(canRedoChange(u2.history, d0), true);
  const r1 = redoChange(u2.history, d0)!;
  assert.equal(structureKey(r1.structure), structureKey(d1));
});

test("undo never throws away edits made after the AI change", () => {
  const before = draft("a");
  const after = draft("a", "b");
  const h = recordChange(emptyHistory, "add b", before, after);
  const editedLater = draft("a", "b", "typed_by_hand");
  assert.equal(canUndoChange(h, editedLater), false);
  assert.equal(undoChange(h, editedLater), null);
  // ...but once those edits are undone by hand, the AI change can be undone again.
  assert.equal(canUndoChange(h, draft("a", "b")), true);
});

test("a new AI change clears the redo list and history is capped", () => {
  let h = recordChange(emptyHistory, "1", draft("a"), draft("a", "b"));
  const undone = undoChange(h, draft("a", "b"))!;
  assert.equal(undone.history.redo.length, 1);
  h = recordChange(undone.history, "2", draft("a"), draft("a", "z"));
  assert.equal(h.redo.length, 0);

  let long = emptyHistory;
  for (let i = 0; i < HISTORY_LIMIT + 5; i++) long = recordChange(long, `c${i}`, draft(`x${i}`), draft(`x${i}`, "y"));
  assert.equal(long.undo.length, HISTORY_LIMIT);
  assert.equal(long.undo[long.undo.length - 1].label, `c${HISTORY_LIMIT + 4}`);
});

test("version note lists the AI changes in the saved version and stays within the limit", () => {
  assert.equal(versionNote([]), undefined);
  assert.deepEqual(versionNote([{ text: "Add five questions about education", ai: true }]), {
    source: "AI_EDIT",
    summary: "AI assistant: Add five questions about education",
  });
  assert.deepEqual(versionNote([{ text: "Restored version 2", ai: false }]), { source: "MANUAL", summary: "Restored version 2" });
  const mixed = versionNote([{ text: "Restored version 2", ai: false }, { text: "Shorten all questions", ai: true }])!;
  assert.equal(mixed.source, "AI_EDIT");
  assert.match(mixed.summary, /^AI assistant: Shorten all questions\. Restored version 2$/);
  assert.ok(versionNote([{ text: "x".repeat(2000), ai: true }])!.summary.length <= 1000);
});
