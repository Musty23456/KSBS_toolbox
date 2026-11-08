import assert from "node:assert/strict";
import { test } from "node:test";
import type { Question, QuestionGroup, SurveySection } from "../../api/types";
import {
  clearBrokenSkipLogic,
  fallbackBrief,
  findBrokenSkipLogic,
  hasContent,
  itemKey,
  mergeRegeneratedSection,
  moveSection,
  precedingContext,
  previewToDraft,
  referencedCodes,
  removeGroup,
  removeSection,
  toContext,
} from "./aiDraft";

const q = (code: string, section_id: string | null, extra: Partial<Question> = {}): Question => ({
  code,
  label: `Label ${code}`,
  type: "SHORT_TEXT",
  order_index: 0,
  is_required: false,
  choices: [],
  section_id,
  group_id: null,
  ...extra,
});

function unsaved() {
  const sections: SurveySection[] = [
    { title: "A", order_index: 1 },
    { title: "B", order_index: 2 },
    { title: "C", order_index: 3 },
  ];
  const groups: QuestionGroup[] = [
    { title: "G-B", order_index: 1, section_id: "local-1", repeatable: false, min_repeats: 1 },
    { title: "G-C", order_index: 2, section_id: "local-2", repeatable: true, min_repeats: 1 },
  ];
  const questions = [
    q("a1", "local-0"),
    q("a2", "local-0"),
    q("b1", "local-1"),
    q("b2", "local-1", { group_id: "local-0" }),
    q("c1", "local-2", { group_id: "local-1" }),
  ];
  return { sections, groups, questions };
}

const sectionOf = (state: ReturnType<typeof unsaved>, code: string) => {
  const question = state.questions.find((x) => x.code === code)!;
  const index = state.sections.findIndex((s, i) => itemKey(s, i) === question.section_id);
  return state.sections[index]?.title;
};
const groupOf = (state: ReturnType<typeof unsaved>, code: string) => {
  const question = state.questions.find((x) => x.code === code)!;
  const index = state.groups.findIndex((g, i) => itemKey(g, i) === question.group_id);
  return state.groups[index]?.title;
};

test("moving a section keeps every question and group attached to the right section", () => {
  const next = moveSection(unsaved(), 0, 2); // A moves to the end: B, C, A
  assert.deepEqual(next.sections.map((s) => s.title), ["B", "C", "A"]);
  for (const [code, title] of [["a1", "A"], ["a2", "A"], ["b1", "B"], ["b2", "B"], ["c1", "C"]]) {
    assert.equal(sectionOf(next, code), title, code);
  }
  assert.equal(groupOf(next, "b2"), "G-B");
  assert.equal(groupOf(next, "c1"), "G-C");
  assert.equal(next.groups.find((g) => g.title === "G-B")!.section_id, "local-0"); // B is now first
  assert.equal(next.groups.find((g) => g.title === "G-C")!.section_id, "local-1");
  // question order follows the new section order, original order kept inside a section
  assert.deepEqual(next.questions.map((x) => x.code), ["b1", "b2", "c1", "a1", "a2"]);
});

test("moving sections is a no-op for bad indexes and never mutates the input", () => {
  const state = unsaved();
  const snapshot = JSON.stringify(state);
  assert.equal(moveSection(state, 1, 1), state);
  assert.equal(moveSection(state, -1, 0), state);
  assert.equal(moveSection(state, 0, 9), state);
  moveSection(state, 0, 1);
  assert.equal(JSON.stringify(state), snapshot);
});

test("saved sections (real ids) are not disturbed by a move", () => {
  const sections: SurveySection[] = [
    { id: "s-1", title: "A", order_index: 1 },
    { id: "s-2", title: "B", order_index: 2 },
  ];
  const questions = [q("a", "s-1"), q("b", "s-2")];
  const next = moveSection({ sections, groups: [], questions }, 0, 1);
  assert.deepEqual(next.sections.map((s) => s.id), ["s-2", "s-1"]);
  assert.deepEqual(next.questions.map((x) => [x.code, x.section_id]), [["b", "s-2"], ["a", "s-1"]]);
});

test("a question with no section stays with the original first section when sections move", () => {
  const state = unsaved();
  state.questions[0] = q("a1", null);
  const next = moveSection(state, 0, 2);
  assert.equal(sectionOf(next, "a1"), "A");
});

test("removing a section moves its content into the first remaining section", () => {
  const next = removeSection(unsaved(), 1); // remove B -> A, C
  assert.deepEqual(next.sections.map((s) => s.title), ["A", "C"]);
  assert.equal(sectionOf(next, "b1"), "A");
  assert.equal(sectionOf(next, "b2"), "A");
  assert.equal(sectionOf(next, "c1"), "C");
  assert.equal(next.questions.length, 5);
  assert.equal(groupOf(next, "b2"), "G-B");
  assert.equal(next.groups.find((g) => g.title === "G-B")!.section_id, "local-0");
  assert.equal(next.groups.find((g) => g.title === "G-C")!.section_id, "local-1");
});

test("removing the first section sends its questions to the new first section", () => {
  const next = removeSection(unsaved(), 0);
  assert.deepEqual(next.sections.map((s) => s.title), ["B", "C"]);
  assert.equal(sectionOf(next, "a1"), "B");
  assert.equal(sectionOf(next, "c1"), "C");
});

test("the last section cannot be removed", () => {
  const state = { sections: [{ title: "Only", order_index: 1 }], groups: [], questions: [q("x", "local-0")] };
  assert.equal(removeSection(state, 0), state);
});

test("removing a group ungroups its questions and re-points later groups", () => {
  const next = removeGroup(unsaved(), 0); // remove G-B
  assert.deepEqual(next.groups.map((g) => g.title), ["G-C"]);
  assert.equal(next.questions.find((x) => x.code === "b2")!.group_id, null);
  assert.equal(groupOf(next, "c1"), "G-C");
});

test("regenerating a section replaces only that section and keeps references valid", () => {
  const state = unsaved();
  const next = mergeRegeneratedSection(state, 1, {
    groups: [{ title: "New group", order_index: 1, repeatable: false, min_repeats: 1 }],
    questions: [q("n1", null), q("n2", null, { group_id: "local-0" })],
  });
  assert.deepEqual(next.questions.map((x) => x.code), ["a1", "a2", "n1", "n2", "c1"]); // reading order preserved
  assert.equal(sectionOf(next, "n1"), "B");
  assert.equal(sectionOf(next, "n2"), "B");
  assert.equal(groupOf(next, "n2"), "New group");
  assert.equal(next.questions.find((x) => x.code === "n1")!.group_id, null);
  assert.equal(groupOf(next, "c1"), "G-C"); // untouched group in another section survives re-indexing
  assert.equal(next.groups.find((g) => g.title === "G-B"), undefined);
  assert.equal(next.groups.find((g) => g.title === "New group")!.section_id, "local-1");
  assert.equal(next.sections, state.sections);
});

test("regenerating the first section works for questions that have no section id", () => {
  const state = unsaved();
  state.questions = state.questions.map((x) => (x.section_id === "local-0" ? { ...x, section_id: null } : x));
  const next = mergeRegeneratedSection(state, 0, { groups: [], questions: [q("only", null)] });
  assert.deepEqual(next.questions.map((x) => x.code), ["only", "b1", "b2", "c1"]);
  assert.equal(sectionOf(next, "only"), "A");
});

test("regenerating a section that had no questions appends the new ones", () => {
  const state = unsaved();
  state.questions = state.questions.filter((x) => x.section_id !== "local-1");
  state.groups = state.groups.filter((g) => g.section_id !== "local-1");
  const next = mergeRegeneratedSection(state, 1, { groups: [], questions: [q("fresh", null)] });
  assert.equal(next.questions[next.questions.length - 1].code, "fresh");
  assert.equal(sectionOf(next, "fresh"), "B");
});

test("referencedCodes ignores string literals and keywords", () => {
  assert.deepEqual(referencedCodes("gender == 'FEMALE' and age >= 12"), ["gender", "age"]);
  assert.deepEqual(referencedCodes("'MALARIA' in symptoms"), ["symptoms"]);
  assert.deepEqual(referencedCodes("not (a == \"x or y\") or b"), ["a", "b"]);
  assert.deepEqual(referencedCodes(null), []);
  assert.deepEqual(referencedCodes(""), []);
});

test("broken skip logic is detected: missing and later questions", () => {
  const list = [
    q("a", "local-0"),
    q("b", "local-0", { relevance_expression: "a == 'X'" }),
    q("c", "local-0", { relevance_expression: "ghost == 'X'" }),
    q("d", "local-0", { relevance_expression: "e == 'X'" }),
    q("e", "local-0"),
  ];
  assert.deepEqual(findBrokenSkipLogic(list), [
    { code: "c", reason: "missing", refers_to: "ghost" },
    { code: "d", reason: "later", refers_to: "e" },
  ]);
});

test("clearing broken skip logic only touches the broken questions", () => {
  const list = [
    q("a", "local-0"),
    q("b", "local-0", { relevance_expression: "a == 'X'" }),
    q("c", "local-0", { relevance_expression: "ghost == 'X'" }),
  ];
  const { questions, cleared } = clearBrokenSkipLogic(list);
  assert.deepEqual(cleared, ["c"]);
  assert.equal(questions[1].relevance_expression, "a == 'X'");
  assert.equal(questions[2].relevance_expression, null);
  const clean = clearBrokenSkipLogic([q("a", "local-0")]);
  assert.deepEqual(clean.cleared, []);
});

test("moving a section can create 'later' skip logic, which is detected", () => {
  const state = unsaved();
  state.questions[2] = q("b1", "local-1", { relevance_expression: "a1 == 'X'" });
  const next = moveSection(state, 0, 2);
  assert.deepEqual(findBrokenSkipLogic(next.questions).map((p) => p.reason), ["later"]);
});

test("context for the AI lists only earlier questions and their choice values", () => {
  const list = [
    q("sex", "local-0", { type: "SINGLE_CHOICE", choices: [{ value: "M", label: "Male", order_index: 1 }, { value: "F", label: "Female", order_index: 2 }] }),
    q("note", "local-0", { type: "SHORT_TEXT", choices: [{ value: "stale", label: "stale", order_index: 1 }] }),
    q("", "local-0"),
    q("later", "local-0"),
  ];
  const ctx = precedingContext(list, 3);
  assert.deepEqual(ctx.map((c) => c.code), ["sex", "note"]);
  assert.deepEqual(ctx[0].choice_values, ["M", "F"]);
  assert.deepEqual(ctx[1].choice_values, []);
  assert.equal(toContext(q("x", null, { label: "y".repeat(500) })).label.length, 300);
});

test("fallback brief is always long enough for the API", () => {
  assert.ok(fallbackBrief("", "").research_topic.length >= 3);
  assert.ok(fallbackBrief("A", "").research_topic.length >= 3);
  assert.equal(fallbackBrief("Household Survey", "About homes").survey_title, "Household Survey");
});

test("a preview becomes an unsaved draft with the composed description", () => {
  const draft = previewToDraft({
    title: "T",
    description: "D",
    introduction: "I",
    respondent_instructions: null,
    composed_description: "D\n\nIntroduction\nI",
    sections: [{ id: "x", title: "S", order_index: 9 }],
    groups: [],
    questions: [{ ...q("a", "local-0"), id: "stale", order_index: 7 }],
    skip_logic: [],
    warnings: [],
    model: "m",
    requested_question_count: 1,
  });
  assert.equal(draft.description, "D\n\nIntroduction\nI");
  assert.equal(draft.sections[0].id, undefined);
  assert.equal(draft.questions[0].id, undefined);
  assert.equal(draft.questions[0].order_index, 1);
});

test("hasContent distinguishes an untouched builder from real work", () => {
  assert.equal(hasContent("", [q("", null, { label: "" })]), false);
  assert.equal(hasContent("Title", []), true);
  assert.equal(hasContent("", [q("x", null)]), true);
});
