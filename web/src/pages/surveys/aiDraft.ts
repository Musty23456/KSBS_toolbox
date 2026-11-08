// Pure helpers for working with AI-generated (and manually edited) questionnaires
// inside the Survey Builder. No React, no network: everything here is unit tested.
//
// Background: the builder links questions to sections/groups with `section_id` /
// `group_id`. Saved rows carry real ids; unsaved ones use `local-<index>` (the
// position in the list), which is what the backend's save mapping expects. That
// means reordering or removing a section/group silently re-points every unsaved
// reference, so every structural change below goes through `remapRefs`.

import type {
  ContextQuestion,
  GeneratedQuestionnairePreview,
  Question,
  QuestionGroup,
  RegeneratedSection,
  SurveySection,
} from "../../api/types";
import { CHOICE_TYPES } from "../../api/types";

type Keyed = { id?: string };

export function itemKey(item: Keyed, index: number): string {
  return item.id ?? `local-${index}`;
}

export interface DraftStructure {
  sections: SurveySection[];
  groups: QuestionGroup[];
  questions: Question[];
}

/** Which section a question belongs to (no section means the first one, as on save). */
export function questionSectionKey(q: Question, sections: SurveySection[]): string | null {
  if (q.section_id) return q.section_id;
  return sections.length ? itemKey(sections[0], 0) : null;
}

/**
 * Re-point `section_id` / `group_id` after sections or groups changed order or
 * were removed. Surviving items are matched by object identity (so callers must
 * keep the same object when an item merely moves). References to removed items
 * become `fallbackSection` / null.
 */
export function remapRefs(
  prev: { sections: SurveySection[]; groups: QuestionGroup[] },
  next: { sections: SurveySection[]; groups: QuestionGroup[] },
  questions: Question[],
  fallbackSection: string | null = null
): { groups: QuestionGroup[]; questions: Question[] } {
  const sectionMap = new Map<string, string>();
  prev.sections.forEach((s, i) => {
    const ni = next.sections.indexOf(s);
    if (ni >= 0) sectionMap.set(itemKey(s, i), itemKey(next.sections[ni], ni));
  });
  const groupMap = new Map<string, string>();
  prev.groups.forEach((g, i) => {
    const ni = next.groups.indexOf(g);
    if (ni >= 0) groupMap.set(itemKey(g, i), itemKey(next.groups[ni], ni));
  });
  // A key that existed before is either carried to the item's new key or, if the item is gone,
  // replaced by the fallback. It must never be kept as-is: `local-1` may now name a different item.
  // Keys that were never in `prev` (ids we know nothing about) are left alone.
  const prevSectionKeys = new Set(prev.sections.map((s, i) => itemKey(s, i)));
  const prevGroupKeys = new Set(prev.groups.map((g, i) => itemKey(g, i)));
  const mapSection = (id: string | null | undefined) =>
    id ? (sectionMap.get(id) ?? (prevSectionKeys.has(id) ? fallbackSection : id)) : id;
  const mapGroup = (id: string | null | undefined) =>
    id ? (groupMap.get(id) ?? (prevGroupKeys.has(id) ? null : id)) : id;

  return {
    groups: next.groups.map((g) => ({ ...g, section_id: mapSection(g.section_id) })),
    questions: questions.map((q) => ({ ...q, section_id: mapSection(q.section_id), group_id: mapGroup(q.group_id) })),
  };
}

/**
 * "No section" means "the first section" only while the first section stays first. Before any
 * structural change, pin such questions and groups to the section they currently belong to.
 */
function pinToFirstSection(state: DraftStructure): { groups: QuestionGroup[]; questions: Question[] } {
  if (!state.sections.length) return { groups: state.groups, questions: state.questions };
  const first = itemKey(state.sections[0], 0);
  return {
    groups: state.groups.map((g) => (g.section_id ? g : { ...g, section_id: first })),
    questions: state.questions.map((q) => (q.section_id ? q : { ...q, section_id: first })),
  };
}

/** Move a section from one position to another. Questions and groups keep their section. */
export function moveSection(state: DraftStructure, from: number, to: number): DraftStructure {
  const { sections } = state;
  if (from === to || from < 0 || to < 0 || from >= sections.length || to >= sections.length) return state;
  const nextSections = [...sections];
  const [moved] = nextSections.splice(from, 1);
  nextSections.splice(to, 0, moved);
  const pinned = pinToFirstSection(state);
  const remapped = remapRefs(
    { sections, groups: pinned.groups },
    { sections: nextSections, groups: pinned.groups },
    pinned.questions
  );
  // The question list follows the section order so the form, skip logic and preview read top to bottom.
  const order = new Map(nextSections.map((s, i) => [itemKey(s, i), i] as const));
  const rank = (q: Question) => order.get(questionSectionKey(q, nextSections) ?? "") ?? 0;
  const questions = remapped.questions
    .map((q, i) => ({ q, i }))
    .sort((a, b) => rank(a.q) - rank(b.q) || a.i - b.i)
    .map((x) => x.q);
  return { sections: nextSections, groups: remapped.groups, questions };
}

/** Remove a section. Its questions and groups move into the first remaining section. Never removes the last one. */
export function removeSection(state: DraftStructure, index: number): DraftStructure {
  const { sections } = state;
  if (sections.length <= 1 || index < 0 || index >= sections.length) return state;
  const nextSections = sections.filter((_, i) => i !== index);
  const target = itemKey(nextSections[0], 0);
  const pinned = pinToFirstSection(state);
  const remapped = remapRefs(
    { sections, groups: pinned.groups },
    { sections: nextSections, groups: pinned.groups },
    pinned.questions,
    target
  );
  return { sections: nextSections, groups: remapped.groups, questions: remapped.questions };
}

/** Remove a group; its questions become ungrouped. */
export function removeGroup(state: DraftStructure, index: number): DraftStructure {
  if (index < 0 || index >= state.groups.length) return state;
  const nextGroups = state.groups.filter((_, i) => i !== index);
  const remapped = remapRefs(
    { sections: state.sections, groups: state.groups },
    { sections: state.sections, groups: nextGroups },
    state.questions
  );
  return { sections: state.sections, groups: remapped.groups, questions: remapped.questions };
}

/** Replace one section's questions and groups with regenerated content. */
export function mergeRegeneratedSection(
  state: DraftStructure,
  sectionIndex: number,
  result: Pick<RegeneratedSection, "groups" | "questions">
): DraftStructure {
  const { sections } = state;
  const key = itemKey(sections[sectionIndex], sectionIndex);
  const inSection = (q: Question) => questionSectionKey(q, sections) === key;

  const keptGroups = state.groups.filter((g) => (g.section_id ?? itemKey(sections[0], 0)) !== key);
  const newGroups: QuestionGroup[] = result.groups.map((g, i) => ({
    ...g,
    id: undefined,
    section_id: key,
    order_index: keptGroups.length + i + 1,
  }));
  const nextGroups = [...keptGroups, ...newGroups];

  // Keep every other question (re-pointed for the new group list), drop this section's.
  const firstRemoved = state.questions.findIndex(inSection);
  const others = state.questions.filter((q) => !inSection(q));
  const remapped = remapRefs(
    { sections, groups: state.groups },
    { sections, groups: nextGroups },
    others
  );

  const fresh: Question[] = result.questions.map((q) => {
    const rel = q.group_id && /^local-(\d+)$/.exec(q.group_id);
    const target = rel ? newGroups[Number(rel[1])] : undefined;
    return {
      ...q,
      id: undefined,
      section_id: key,
      group_id: target ? itemKey(target, nextGroups.indexOf(target)) : null,
    };
  });

  // Insert at the spot the old section's questions started, so reading order is preserved.
  const insertAt =
    firstRemoved < 0
      ? remapped.questions.length
      : state.questions.slice(0, firstRemoved).filter((q) => !inSection(q)).length;
  const questions = [...remapped.questions.slice(0, insertAt), ...fresh, ...remapped.questions.slice(insertAt)];
  return { sections, groups: remapped.groups, questions };
}

// ---------------------------------------------------------------- skip logic

const KEYWORDS = new Set(["and", "or", "not", "in", "true", "false", "none", "null", "True", "False", "None", "contains"]);

/** Question codes an expression refers to (string literals ignored). */
export function referencedCodes(expression: string | null | undefined): string[] {
  if (!expression) return [];
  const withoutStrings = expression.replace(/'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"/g, " ");
  const names = withoutStrings.match(/[A-Za-z_][A-Za-z0-9_]*/g) ?? [];
  return [...new Set(names.filter((n) => !KEYWORDS.has(n)))];
}

export interface SkipLogicProblem {
  code: string;
  reason: "missing" | "later";
  refers_to: string;
}

/**
 * Skip logic that can never work: it refers to a question that no longer exists
 * (which would hide the question forever) or one that comes *later* in the form.
 */
export function findBrokenSkipLogic(questions: Question[]): SkipLogicProblem[] {
  const position = new Map(questions.map((q, i) => [q.code, i] as const));
  const problems: SkipLogicProblem[] = [];
  questions.forEach((q, i) => {
    for (const ref of referencedCodes(q.relevance_expression)) {
      const at = position.get(ref);
      if (at === undefined) problems.push({ code: q.code, reason: "missing", refers_to: ref });
      else if (at >= i) problems.push({ code: q.code, reason: "later", refers_to: ref });
    }
  });
  return problems;
}

/** Remove broken skip logic so no question is hidden for good. Returns the codes that were cleared. */
export function clearBrokenSkipLogic(questions: Question[]): { questions: Question[]; cleared: string[] } {
  const broken = new Set(findBrokenSkipLogic(questions).map((p) => p.code));
  if (broken.size === 0) return { questions, cleared: [] };
  return {
    questions: questions.map((q) => (broken.has(q.code) ? { ...q, relevance_expression: null } : q)),
    cleared: [...broken],
  };
}

// ------------------------------------------------------------ AI request data

export function toContext(q: Question): ContextQuestion {
  return {
    code: q.code,
    label: (q.label ?? "").slice(0, 300),
    type: q.type,
    choice_values: CHOICE_TYPES.includes(q.type) ? q.choices.map((c) => c.value).filter(Boolean).slice(0, 60) : [],
  };
}

/** Questions before `index`, in the form the AI needs for skip logic (codes that exist only). */
export function precedingContext(questions: Question[], index: number): ContextQuestion[] {
  return questions
    .slice(0, Math.max(0, index))
    .filter((q) => q.code.trim())
    .slice(-300)
    .map(toContext);
}

export function otherCodes(questions: Question[], exclude: (q: Question, i: number) => boolean): string[] {
  return questions.filter((q, i) => !exclude(q, i) && q.code.trim()).map((q) => q.code).slice(0, 600);
}

/** The AI needs some study context even for surveys that were not generated; use the survey's own title. */
export function fallbackBrief(title: string, description: string, language = "English") {
  const topic = (title || description || "Survey").trim();
  return {
    research_topic: topic.length >= 3 ? topic.slice(0, 500) : `${topic} survey`.slice(0, 500),
    survey_title: title.trim() || null,
    research_objectives: description.trim().slice(0, 2000) || null,
    expected_question_count: 20,
    language,
  };
}

/** What the builder should show for a preview the user chose to use. */
export function previewToDraft(preview: GeneratedQuestionnairePreview): DraftStructure & { title: string; description: string } {
  return {
    title: preview.title,
    description: preview.composed_description || preview.description || "",
    sections: preview.sections.map((s, i) => ({ ...s, id: undefined, order_index: i + 1 })),
    groups: preview.groups.map((g, i) => ({ ...g, id: undefined, order_index: i + 1 })),
    questions: preview.questions.map((q, i) => ({ ...q, id: undefined, order_index: i + 1 })),
  };
}

export function hasContent(title: string, questions: Question[]): boolean {
  return questions.some((q) => q.label.trim() || q.code.trim()) || title.trim().length > 0;
}
