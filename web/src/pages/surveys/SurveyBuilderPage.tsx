import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { aiQuestionnaireApi, surveysApi, usersApi } from "../../api/services";
import type {
  EditPreview,
  GeneratedQuestionnairePreview,
  Question,
  QuestionGroup,
  QuestionnaireAvailability,
  QuestionnaireBrief,
  ShareTarget,
  SkipLogicSuggestion,
  SurveyDetail,
  SurveySection,
  SurveyVersionDetail,
  UserAccount,
} from "../../api/types";
import { AIEditorPanel } from "../../components/ai/AIEditorPanel";
import { GenerateWithAIModal } from "../../components/ai/GenerateWithAIModal";
import { VersionHistoryModal } from "../../components/ai/VersionHistoryModal";
import { ReviewModal, type ReviewState } from "../../components/ai/ReviewModal";
import { RegenerateModal } from "../../components/ai/RegenerateModal";
import { ReviewConfirmModal } from "../../components/ai/ReviewConfirmModal";
import {
  clearBrokenSkipLogic,
  fallbackBrief,
  hasContent,
  itemKey,
  mergeRegeneratedSection,
  moveSection,
  otherCodes,
  precedingContext,
  previewToDraft,
  questionSectionKey,
  removeGroup as removeGroupFrom,
  removeSection,
  toContext,
} from "./aiDraft";
import {
  canRedoChange,
  canUndoChange,
  emptyHistory,
  recordChange,
  redoChange,
  structureKey,
  undoChange,
  versionNote,
  type AIHistory,
  type VersionNote,
} from "./aiEdit";
import { QuestionEditor } from "../../components/QuestionEditor";
import { extractErrorMessage } from "../../api/client";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";

function blankQuestion(orderIndex: number): Question {
  return {
    code: "",
    label: "",
    type: "SHORT_TEXT",
    order_index: orderIndex,
    is_required: false,
    choices: [],
  };
}

export function SurveyBuilderPage() {
  const { surveyId } = useParams();
  const isNew = !surveyId || surveyId === "new";
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === "ADMINISTRATOR";
  const isStaff = isAdmin || user?.role === "SUPERVISOR";

  const [survey, setSurvey] = useState<SurveyDetail | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [questions, setQuestions] = useState<Question[]>([]);
  const [sections, setSections] = useState<SurveySection[]>([{ title: "Section 1", description: "", order_index: 1 }]);
  const [groups, setGroups] = useState<QuestionGroup[]>([]);
  const [enumerators, setEnumerators] = useState<UserAccount[]>([]);
  const [assignedIds, setAssignedIds] = useState<string[]>([]);
  // Only administrators can choose GLOBAL; everyone else always creates PERSONAL.
  const [newScope, setNewScope] = useState<"GLOBAL" | "PERSONAL">(isAdmin ? "GLOBAL" : "PERSONAL");
  const [shareTargets, setShareTargets] = useState<ShareTarget[]>([]);
  const [sharedIds, setSharedIds] = useState<string[]>([]);
  const [isSavingShares, setIsSavingShares] = useState(false);
  const [sharesMessage, setSharesMessage] = useState<string | null>(null);
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);
  const [previewValues, setPreviewValues] = useState<Record<string, string | string[]>>({});
  const [history, setHistory] = useState<Question[][]>([]);
  const [future, setFuture] = useState<Question[][]>([]);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(!isNew);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ---- AI questionnaire generator (Phase 2) ----
  const [aiAvailability, setAiAvailability] = useState<QuestionnaireAvailability | null>(null);
  const [isAIModalOpen, setIsAIModalOpen] = useState(false);
  const [aiBrief, setAiBrief] = useState<QuestionnaireBrief | null>(null);
  // True once AI content has been loaded in this session (the saved flag comes from the server).
  const [aiTouched, setAiTouched] = useState(false);
  const [aiNotes, setAiNotes] = useState<{ warnings: string[]; skipLogic: SkipLogicSuggestion[] } | null>(null);
  const [regenTarget, setRegenTarget] = useState<{ kind: "question" | "section"; index: number } | null>(null);
  const [regenBusy, setRegenBusy] = useState(false);
  const [regenError, setRegenError] = useState<string | null>(null);
  const [confirmMode, setConfirmMode] = useState<"save" | "publish" | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  // The person has confirmed they reviewed the AI content; reset whenever new AI content arrives.
  const [reviewAcknowledged, setReviewAcknowledged] = useState(false);
  // Async handlers read the latest editor state through this ref instead of a stale closure.
  const latest = useRef({ sections, groups, questions, title, description });
  latest.current = { sections, groups, questions, title, description };

  // ---- AI questionnaire editor (Phase 3) ----
  // Undo/redo of whole AI changes (sections + groups + questions). It only works while the draft still
  // equals what the change produced, so it can never discard edits made afterwards.
  const [aiHistory, setAiHistory] = useState<AIHistory>(emptyHistory);
  // What the next saved version should say about itself (AI edits applied, versions loaded).
  const [pendingNotes, setPendingNotes] = useState<VersionNote[]>([]);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [isReviewOpen, setIsReviewOpen] = useState(false);
  const [reviewState, setReviewState] = useState<ReviewState>({ objectives: "", report: null, reviewedKey: null });
  const [ignoredFindings, setIgnoredFindings] = useState<ReadonlySet<string>>(new Set());
  const currentKey = useMemo(() => structureKey({ sections, groups, questions }), [sections, groups, questions]);

  const scope: "GLOBAL" | "PERSONAL" = isNew ? newScope : survey?.scope ?? "GLOBAL";
  const isOwner = isNew || survey?.created_by_id === user?.id;
  // Mirrors backend can_edit(): owner edits personal surveys; staff edit global ones.
  const canEdit = isNew ? true : scope === "PERSONAL" ? isOwner : isStaff;
  // Enumerator assignment only makes sense for global surveys, and only staff can list users.
  const canAssign = isStaff && scope === "GLOBAL";

  useEffect(() => {
    if (!canAssign) return;
    usersApi
      .list()
      .then((all) => setEnumerators(all.filter((u) => u.role === "ENUMERATOR" && u.is_active)))
      .catch(() => setEnumerators([]));
  }, [canAssign]);

  const aiGenerated = aiTouched || survey?.ai_generated === true;
  const aiReady = aiAvailability === null || aiAvailability.available;

  useEffect(() => {
    if (!canEdit) return;
    aiQuestionnaireApi.availability().then(setAiAvailability).catch(() => setAiAvailability(null));
  }, [canEdit]);

  // Sharing: only the owner of a saved personal survey.
  const canShare = !isNew && scope === "PERSONAL" && survey?.created_by_id === user?.id;

  useEffect(() => {
    if (!canShare || !survey) return;
    Promise.all([surveysApi.shareTargets(), surveysApi.getShares(survey.id)])
      .then(([targets, ids]) => {
        setShareTargets(targets);
        setSharedIds(ids);
      })
      .catch(() => setShareTargets([]));
  }, [canShare, survey?.id]);

  function toggleShare(id: string) {
    setSharesMessage(null);
    setSharedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  async function handleSaveShares() {
    if (!survey) return;
    setError(null);
    setSharesMessage(null);
    setIsSavingShares(true);
    try {
      const saved = await surveysApi.setShares(survey.id, sharedIds);
      setSharedIds(saved);
      setSharesMessage(
        saved.length === 0
          ? "Sharing turned off."
          : `Shared with ${saved.length} ${saved.length === 1 ? "person" : "people"}.`
      );
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setIsSavingShares(false);
    }
  }

  useEffect(() => {
    if (isNew) return;
    (async () => {
      const data = await surveysApi.get(surveyId!);
      setSurvey(data);
      setTitle(data.title);
      setDescription(data.description ?? "");
      setQuestions(data.questions.length > 0 ? data.questions : [blankQuestion(1)]);
      setSections(data.sections?.length ? data.sections : [{ title: "Section 1", description: "", order_index: 1 }]);
      setGroups(data.groups ?? []);
      setAssignedIds(data.assigned_enumerator_ids ?? []);
      setIsLoading(false);
    })();
  }, [surveyId, isNew]);

  useEffect(() => {
    if (isNew && questions.length === 0) {
      setQuestions([blankQuestion(1)]);
      setSections([{ title: "Section 1", description: "", order_index: 1 }]);
      setGroups([]);
    }
  }, [isNew, questions.length]);

  function toggleEnumerator(id: string) {
    setAssignedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  function commitQuestions(updater: (prev: Question[]) => Question[]) {
    setQuestions((prev) => {
      const next = updater(prev);
      if (next === prev) return prev;
      setHistory((h) => [...h.slice(-19), prev]);
      setFuture([]);
      return next;
    });
  }

  function updateQuestion(index: number, next: Question) {
    commitQuestions((prev) => prev.map((q, i) => (i === index ? next : q)));
  }

  function removeQuestion(index: number) {
    commitQuestions((prev) => prev.filter((_, i) => i !== index));
  }

  function moveQuestion(index: number, direction: -1 | 1) {
    commitQuestions((prev) => {
      const next = [...prev];
      const target = index + direction;
      if (target < 0 || target >= next.length) return prev;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function duplicateQuestion(index: number) {
    commitQuestions((prev) => {
      const source = prev[index];
      const copy: Question = {
        ...source,
        id: undefined,
        code: source.code ? `${source.code}_copy` : "",
        label: source.label ? `${source.label} (copy)` : "",
        choices: source.choices.map((c) => ({ ...c, id: undefined })),
      };
      return [...prev.slice(0, index + 1), copy, ...prev.slice(index + 1)];
    });
  }

  function reorderQuestions(from: number, to: number) {
    commitQuestions((prev) => {
      if (from === to || from < 0 || to < 0 || from >= prev.length || to >= prev.length) return prev;
      const next = [...prev];
      const [item] = next.splice(from, 1);
      next.splice(to, 0, item);
      return next;
    });
  }

  function addQuestion() {
    commitQuestions((prev) => [...prev, { ...blankQuestion(prev.length + 1), section_id: sections[0]?.id }]);
  }

  function addGroup() {
    setGroups((prev) => [...prev, {
      title: `Group ${prev.length + 1}`, description: "", order_index: prev.length + 1,
      section_id: sections[0]?.id ?? `local-0`, repeatable: false, min_repeats: 1, max_repeats: null,
    }]);
  }

  function updateGroup(index: number, patch: Partial<QuestionGroup>) {
    setGroups((prev) => prev.map((g, i) => i === index ? { ...g, ...patch } : g));
  }

  function removeGroup(index: number) {
    const next = removeGroupFrom({ sections, groups, questions }, index);
    setGroups(next.groups);
    commitQuestions(() => next.questions);
  }

  function addSection() {
    setSections((prev) => [...prev, { title: `Section ${prev.length + 1}`, description: "", order_index: prev.length + 1 }]);
  }

  function updateSection(index: number, patch: Partial<SurveySection>) {
    setSections((prev) => prev.map((section, i) => i === index ? { ...section, ...patch } : section));
  }

  function undo() {
    setHistory((h) => {
      if (!h.length) return h;
      const previous = h[h.length - 1];
      setFuture((f) => [questions, ...f].slice(0, 20));
      setQuestions(previous);
      return h.slice(0, -1);
    });
  }

  function redo() {
    setFuture((f) => {
      if (!f.length) return f;
      const next = f[0];
      setHistory((h) => [...h.slice(-19), questions]);
      setQuestions(next);
      return f.slice(1);
    });
  }

  function setPreviewValue(code: string, value: string | string[]) {
    setPreviewValues((prev) => ({ ...prev, [code]: value }));
  }

  function handleMoveSection(index: number, direction: -1 | 1) {
    const next = moveSection({ sections, groups, questions }, index, index + direction);
    if (next.sections === sections) return;
    setSections(next.sections);
    setGroups(next.groups);
    commitQuestions(() => next.questions);
  }

  function handleRemoveSection(index: number) {
    if (sections.length <= 1) return;
    const target = sections[index === 0 ? 1 : 0];
    const count = questions.filter((q) => questionSectionKey(q, sections) === itemKey(sections[index], index)).length;
    const message = count
      ? `Remove this section? Its ${count} question${count === 1 ? "" : "s"} will move to "${target.title || "the first section"}".`
      : "Remove this empty section?";
    if (!window.confirm(message)) return;
    const next = removeSection({ sections, groups, questions }, index);
    setSections(next.sections);
    setGroups(next.groups);
    commitQuestions(() => next.questions);
  }

  function applyStructure(next: { sections: SurveySection[]; groups: QuestionGroup[]; questions: Question[] }) {
    setSections(next.sections);
    setGroups(next.groups);
    commitQuestions(() => next.questions);
  }

  function handleApplyAIEdit(preview: EditPreview, instruction: string) {
    // The server already validated this exact result against the draft the proposal was made for.
    const before = { sections: latest.current.sections, groups: latest.current.groups, questions: latest.current.questions };
    const after = preview.result;
    applyStructure(after);
    setAiHistory((h) => recordChange(h, instruction, before, after));
    setPendingNotes((n) => [...n, { text: instruction.slice(0, 120), ai: true }]);
    setAiTouched(true);
    setReviewAcknowledged(false);
    setAiNotes({ warnings: preview.warnings, skipLogic: [] });
    setError(null);
  }

  function handleAIUndo() {
    const current = { sections: latest.current.sections, groups: latest.current.groups, questions: latest.current.questions };
    const step = undoChange(aiHistory, current);
    if (!step) return;
    applyStructure(step.structure);
    setAiHistory(step.history);
  }

  function handleAIRedo() {
    const current = { sections: latest.current.sections, groups: latest.current.groups, questions: latest.current.questions };
    const step = redoChange(aiHistory, current);
    if (!step) return;
    applyStructure(step.structure);
    setAiHistory(step.history);
  }

  function handleLoadVersion(version: SurveyVersionDetail) {
    const message = `Load version ${version.version_number} into the editor? It replaces the sections, groups and questions you see now. Nothing is saved until you press Save changes, and Undo AI change brings your current draft back.`;
    if (!window.confirm(message)) return;
    const before = { sections: latest.current.sections, groups: latest.current.groups, questions: latest.current.questions };
    // Reuse the saved rows' ids: section_id / group_id on the questions point at them.
    const after = {
      sections: version.sections.length ? version.sections : [{ title: "Section 1", description: "", order_index: 1 }],
      groups: version.groups,
      questions: version.questions.length ? version.questions : [blankQuestion(1)],
    };
    applyStructure(after);
    setAiHistory((h) => recordChange(h, `Loaded version ${version.version_number}`, before, after));
    setPendingNotes((n) => [...n, { text: `Restored from version ${version.version_number}`, ai: false }]);
    setIsHistoryOpen(false);
  }

  function handleUsePreview(preview: GeneratedQuestionnairePreview, brief: QuestionnaireBrief) {
    if (hasContent(title, questions) && !window.confirm("Replace the current title, sections and questions with the AI-generated questionnaire? You can undo the question changes with Undo.")) {
      return;
    }
    const draft = previewToDraft(preview);
    setTitle(draft.title);
    setDescription(draft.description);
    setSections(draft.sections);
    setGroups(draft.groups);
    commitQuestions(() => draft.questions);
    setAiBrief(brief);
    setAiTouched(true);
    setReviewAcknowledged(false);
    setAiNotes({ warnings: preview.warnings, skipLogic: preview.skip_logic });
    setIsAIModalOpen(false);
    setError(null);
  }

  function closeRegenerate() {
    if (regenBusy) return;
    setRegenTarget(null);
    setRegenError(null);
  }

  async function handleRegenerate(instruction: string) {
    if (!regenTarget) return;
    const { sections: secs, groups: grps, questions: qs, title: t, description: d } = latest.current;
    const brief = aiBrief ?? fallbackBrief(t, d);
    setRegenBusy(true);
    setRegenError(null);
    try {
      if (regenTarget.kind === "question") {
        const index = regenTarget.index;
        const original = qs[index];
        const section = secs.find((s, si) => itemKey(s, si) === questionSectionKey(original, secs));
        const result = await aiQuestionnaireApi.regenerateQuestion({
          brief,
          section_title: section?.title ?? null,
          question: original,
          instruction: instruction || null,
          preceding_questions: precedingContext(qs, index),
          other_codes: otherCodes(qs, (_q, i) => i === index),
        });
        commitQuestions((prev) =>
          prev.map((q, i) => (i === index ? { ...result.question, id: original.id } : q))
        );
        setAiNotes({ warnings: result.warnings, skipLogic: result.skip_logic });
      } else {
        const si = regenTarget.index;
        const section = secs[si];
        const key = itemKey(section, si);
        const inSection = (q: Question) => questionSectionKey(q, secs) === key;
        const firstIdx = qs.findIndex(inSection);
        const before = firstIdx < 0 ? qs.filter((q) => !inSection(q)) : qs.slice(0, firstIdx).filter((q) => !inSection(q));
        const current = qs.filter(inSection);
        const result = await aiQuestionnaireApi.regenerateSection({
          brief,
          section_title: section.title || `Section ${si + 1}`,
          section_description: section.description || null,
          current_questions: current.map(toContext),
          preceding_questions: before.filter((q) => q.code.trim()).slice(-300).map(toContext),
          other_codes: otherCodes(qs, (q) => inSection(q)),
          question_count: current.length >= 1 ? Math.min(100, current.length) : null,
          instruction: instruction || null,
        });
        const merged = mergeRegeneratedSection({ sections: secs, groups: grps, questions: qs }, si, result);
        // Questions elsewhere may have pointed at questions that no longer exist; never leave them hidden for good.
        const checked = clearBrokenSkipLogic(merged.questions);
        setGroups(merged.groups);
        commitQuestions(() => checked.questions);
        const warnings = [...result.warnings];
        if (checked.cleared.length) {
          warnings.push(`Skip logic was cleared on ${checked.cleared.join(", ")} because it depended on questions that were replaced.`);
        }
        setAiNotes({ warnings, skipLogic: result.skip_logic });
      }
      setAiTouched(true);
      setReviewAcknowledged(false);
      setRegenTarget(null);
    } catch (err) {
      setRegenError(extractErrorMessage(err));
    } finally {
      setRegenBusy(false);
    }
  }

  function validateBeforeSave(): string | null {
    if (!title.trim()) return "Give the survey a title.";
    if (questions.length === 0) return "Add at least one question.";
    const codes = new Set<string>();
    for (const g of groups) { if (g.repeatable && g.max_repeats !== null && g.max_repeats !== undefined && g.max_repeats < g.min_repeats) return `Group "${g.title}" has a maximum below its minimum.`; }
    for (const q of questions) {
      if (!q.code.trim()) return "Every question needs a field code.";
      if (!q.label.trim()) return `Question "${q.code}" needs a label.`;
      if (codes.has(q.code)) return `Field code "${q.code}" is used more than once.`;
      codes.add(q.code);
    }
    return null;
  }

  function handleSave() {
    const validationError = validateBeforeSave();
    if (validationError) {
      setError(validationError);
      return;
    }
    // AI-generated content is only saved after the person confirms they reviewed it.
    if (aiGenerated && !reviewAcknowledged) {
      setConfirmMode("save");
      return;
    }
    void performSave();
  }

  async function performSave() {
    setError(null);
    setIsSaving(true);

    const orderedSections = sections.map((section, i) => ({ ...section, order_index: i + 1 }));
    const orderedGroups = groups.map((g, i) => ({ ...g, order_index: i + 1, section_id: g.section_id || orderedSections[0]?.id }));
    const orderedQuestions = questions.map((q, i) => ({ ...q, order_index: i + 1, section_id: q.section_id || orderedSections[0]?.id }));
    const note = versionNote(pendingNotes);

    try {
      if (isNew) {
        const created = await surveysApi.create({
          title,
          description,
          questions: orderedQuestions,
          sections: orderedSections,
          groups: orderedGroups,
          scope: newScope,
          assigned_enumerator_ids: canAssign ? assignedIds : [],
          ...(aiGenerated ? { ai_generated: true } : {}),
        });
        navigate(`/surveys/${created.id}`);
      } else {
        const updated = await surveysApi.update(surveyId!, {
          title,
          description,
          questions: orderedQuestions,
          sections: orderedSections,
          groups: orderedGroups,
          ...(canAssign ? { assigned_enumerator_ids: assignedIds } : {}),
          ...(aiGenerated ? { ai_generated: true } : {}),
          ...(note ? { change_source: note.source, change_summary: note.summary } : {}),
        });
        setSurvey(updated);
        setQuestions(updated.questions);
        // A new version has new section / group rows; the questions now point at them.
        if (updated.sections?.length) setSections(updated.sections);
        setGroups(updated.groups ?? []);
        setAssignedIds(updated.assigned_enumerator_ids ?? []);
        setAiHistory(emptyHistory);
        setPendingNotes([]);
      }
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setIsSaving(false);
    }
  }

  function handlePublish() {
    if (!survey) return;
    if (aiGenerated) {
      setConfirmMode("publish"); // never published without an explicit review confirmation
      return;
    }
    void performPublish(false);
  }

  async function performPublish(confirmReview: boolean) {
    if (!survey) return;
    setError(null);
    try {
      const updated = await surveysApi.publish(survey.id, confirmReview);
      setSurvey(updated);
    } catch (err) {
      setError(extractErrorMessage(err));
    }
  }

  async function handleConfirmReview() {
    const mode = confirmMode;
    if (!mode) return;
    setConfirmBusy(true);
    try {
      setReviewAcknowledged(true);
      if (mode === "save") await performSave();
      else await performPublish(true);
    } finally {
      setConfirmBusy(false);
      setConfirmMode(null);
    }
  }

  if (isLoading) {
    return <p className="loading-text">Loading survey…</p>;
  }

  function evaluateRelevance(expression: string | null | undefined): boolean {
    if (!expression?.trim()) return true;
    // Preview intentionally supports the same common comparison forms used by the builder.
    // Unsupported expressions remain visible rather than silently hiding a question.
    try {
      const normalized = expression.replace(/\bAND\b/gi, " and ").replace(/\bOR\b/gi, " or ");
      const parts = normalized.split(/\s+(and|or)\s+/i);
      let result: boolean | null = null;
      let pending: "and" | "or" = "and";
      for (const part of parts) {
        if (/^(and|or)$/i.test(part.trim())) { pending = part.trim().toLowerCase() as "and" | "or"; continue; }
        const m = part.trim().match(/^([A-Za-z_][\w]*)\s*(==|!=|>=|<=|>|<|contains)\s*(?:'([^']*)'|\"([^\"]*)\"|(-?\d+(?:\.\d+)?)|(true|false))$/i);
        if (!m) return true;
        const actual = previewValues[m[1]];
        const expected = m[3] ?? m[4] ?? m[5] ?? (m[6] ? m[6].toLowerCase() === "true" : "");
        const left = Array.isArray(actual) ? actual.join(",") : (actual ?? "");
        const a = Number(left), b = Number(expected);
        const numeric = left !== "" && expected !== "" && Number.isFinite(a) && Number.isFinite(b);
        let current = false;
        switch (m[2]) {
          case "==": current = numeric ? a === b : String(left) === String(expected); break;
          case "!=": current = numeric ? a !== b : String(left) !== String(expected); break;
          case ">": current = numeric ? a > b : false; break;
          case ">=": current = numeric ? a >= b : false; break;
          case "<": current = numeric ? a < b : false; break;
          case "<=": current = numeric ? a <= b : false; break;
          case "contains": current = String(left).includes(String(expected)); break;
        }
        result = result === null ? current : pending === "and" ? result && current : result || current;
      }
      return result ?? true;
    } catch { return true; }
  }

  if (!canEdit && !isNew) {
    return (
      <div>
        <div className="page-header">
          <div>
            <h1>{title}</h1>
            <p>{description}</p>
          </div>
          {survey && <StatusBadge status={survey.status} />}
        </div>
        <div className="panel" style={{ marginBottom: 24 }}>
        <div className="builder-toolbar" style={{ marginBottom: 12 }}>
          <div><h2 style={{ marginBottom: 4 }}>Sections / Pages</h2><span className="builder-meta">{sections.length} section{sections.length === 1 ? "" : "s"}</span></div>
          <button type="button" className="btn btn-secondary" onClick={addSection}>+ Add section</button>
        </div>
        {sections.map((section, i) => (
          <div key={section.id ?? i} className="section-editor-row">
            <input value={section.title} onChange={(e) => updateSection(i, { title: e.target.value })} placeholder="Section title" />
            <input value={section.description ?? ""} onChange={(e) => updateSection(i, { description: e.target.value })} placeholder="Description (optional)" />
          </div>
        ))}
      </div>

      <div className="builder-toolbar">
        <div>
          <h2 style={{ marginBottom: 4 }}>Questions</h2>
          <span className="builder-meta">{questions.length} question{questions.length === 1 ? "" : "s"}</span>
        </div>
        <div className="question-actions">
          <button type="button" className="btn btn-secondary" onClick={undo} disabled={!history.length}>↶ Undo</button>
          <button type="button" className="btn btn-secondary" onClick={redo} disabled={!future.length}>↷ Redo</button>
          <button type="button" className="btn btn-secondary" onClick={() => { setPreviewValues({}); setIsPreviewOpen(true); }}>👁 Preview</button>
        </div>
      </div>
        <table className="registry-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Label</th>
              <th>Type</th>
              <th>Required</th>
            </tr>
          </thead>
          <tbody>
            {questions.map((q, i) => (
              <tr key={i}>
                <td>{i + 1}</td>
                <td>{q.label}</td>
                <td>{q.type}</td>
                <td>{q.is_required ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>{isNew ? "New survey" : title || "Edit survey"}</h1>
          <p>
            {isNew
              ? "Define the questions your enumerators will fill in the field."
              : "Editing questions creates a new version — past submissions stay tied to the version they were collected with."}
          </p>
        </div>
        {survey && (
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <StatusBadge status={survey.status} />
            <span className="mono">v{survey.current_version_number}</span>
            {survey.status !== "PUBLISHED" && survey.status !== "ARCHIVED" && (
              <button className="btn btn-secondary" onClick={handlePublish}>
                Publish
              </button>
            )}
          </div>
        )}
      </div>

      {error && <div className="form-error">{error}</div>}

      <div className="ai-toolbar">
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => setIsAIModalOpen(true)}
          disabled={!aiReady}
          title={aiReady ? "Draft a complete questionnaire with AI" : aiAvailability?.message}
        >
          ✨ Generate with AI
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => setIsReviewOpen(true)}
          title="Check this questionnaire for quality problems. Nothing is changed unless you apply a suggestion."
        >
          🔍 Review with AI
        </button>
        {!aiReady && <small>{aiAvailability?.message}</small>}
      </div>

      {aiGenerated && (
        <div className="ai-banner" role="status">
          <strong>AI-assisted questionnaire</strong>
          <div>
            Check every question, answer choice and skip-logic rule before you rely on it. It is saved as a draft and is
            never published automatically; saving and publishing ask you to confirm.
          </div>
          {aiNotes && aiNotes.warnings.length > 0 && (
            <ul>
              {aiNotes.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
          {aiNotes && (
            <div className="ai-banner-actions">
              <button type="button" className="btn btn-secondary" onClick={() => setAiNotes(null)}>
                Dismiss notes
              </button>
            </div>
          )}
        </div>
      )}

      <AIEditorPanel
        aiAvailable={aiReady && aiAvailability !== null}
        unavailableMessage={aiAvailability?.message}
        surveyTitle={title}
        surveyDescription={description}
        getDraft={() => ({ sections: latest.current.sections, groups: latest.current.groups, questions: latest.current.questions })}
        currentKey={currentKey}
        canUndo={canUndoChange(aiHistory, { sections, groups, questions })}
        canRedo={canRedoChange(aiHistory, { sections, groups, questions })}
        undoLabel={aiHistory.undo[aiHistory.undo.length - 1]?.label}
        redoLabel={aiHistory.redo[aiHistory.redo.length - 1]?.label}
        onUndo={handleAIUndo}
        onRedo={handleAIRedo}
        onApply={handleApplyAIEdit}
        onOpenHistory={isNew ? undefined : () => setIsHistoryOpen(true)}
      />

      <div className="panel" style={{ marginBottom: 24 }}>
        <div className="field">
          <label>Survey title</label>
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Household Survey 2026" />
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>Description (optional)</label>
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
      </div>

      {isNew && isAdmin && (
        <div className="panel" style={{ marginBottom: 24 }}>
          <label style={{ display: "block", marginBottom: 8 }}>Survey type</label>
          <select value={newScope} onChange={(e) => setNewScope(e.target.value as "GLOBAL" | "PERSONAL")}>
            <option value="GLOBAL">Global — for the whole organisation</option>
            <option value="PERSONAL">Personal — only visible to me</option>
          </select>
        </div>
      )}

      {scope === "PERSONAL" && (
        <div className="panel" style={{ marginBottom: 24 }}>
          <strong>Personal survey</strong>
          <p style={{ margin: "4px 0 0", color: "var(--muted, #6b7280)" }}>
            {isOwner
              ? "Only you can fill this survey, unless you share it below. Publish it to make it available in your Android app."
              : "This survey was shared with you. You can fill it, but only its owner can change it."}
          </p>
        </div>
      )}

      {canShare && (
        <div className="panel" style={{ marginBottom: 24 }}>
          <label style={{ display: "block", marginBottom: 8 }}>Share this survey</label>
          <p style={{ marginTop: 0, color: "var(--muted, #6b7280)" }}>
            People you pick can fill this survey from their app once it is published. They cannot edit, publish or
            share it. Untick everyone to stop sharing.
          </p>
          {survey?.status !== "PUBLISHED" && (
            <p style={{ marginTop: 0, color: "var(--muted, #6b7280)" }}>
              This survey is not published yet, so they will only see it after you publish it.
            </p>
          )}
          {shareTargets.length === 0 ? (
            <p className="loading-text">No other enumerators to share with yet.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {shareTargets.map((u) => (
                <label key={u.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input type="checkbox" checked={sharedIds.includes(u.id)} onChange={() => toggleShare(u.id)} />
                  {u.full_name} <span style={{ color: "var(--muted, #6b7280)" }}>({u.email})</span>
                </label>
              ))}
            </div>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12 }}>
            <button type="button" className="btn btn-primary" onClick={handleSaveShares} disabled={isSavingShares}>
              {isSavingShares ? "Saving…" : "Save sharing"}
            </button>
            {sharesMessage && <span style={{ color: "var(--muted, #6b7280)" }}>{sharesMessage}</span>}
          </div>
        </div>
      )}

      {canAssign && (
      <div className="panel" style={{ marginBottom: 24 }}>
        <label style={{ display: "block", marginBottom: 8 }}>Who can collect this survey</label>
        <p style={{ marginTop: 0, color: "var(--muted, #6b7280)" }}>
          Leave everyone unchecked to keep this survey open to every enumerator. Check specific people to restrict it
          to only them.
        </p>
        {enumerators.length === 0 ? (
          <p className="loading-text">No enumerator accounts yet.</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {enumerators.map((u) => (
              <label key={u.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input type="checkbox" checked={assignedIds.includes(u.id)} onChange={() => toggleEnumerator(u.id)} />
                {u.full_name} <span style={{ color: "var(--muted, #6b7280)" }}>({u.email})</span>
              </label>
            ))}
          </div>
        )}
      </div>
      )}

      <div className="panel" style={{ marginBottom: 24 }}>
        <div className="builder-toolbar" style={{ marginBottom: 12 }}>
          <div><h2 style={{ marginBottom: 4 }}>Sections / Pages</h2><span className="builder-meta">{sections.length} section{sections.length === 1 ? "" : "s"}</span></div>
          <button type="button" className="btn btn-secondary" onClick={addSection}>+ Add section</button>
        </div>
        {sections.map((section, i) => (
          <div key={section.id ?? i} className="section-editor-row">
            <input value={section.title} onChange={(e) => updateSection(i, { title: e.target.value })} placeholder="Section title" />
            <input value={section.description ?? ""} onChange={(e) => updateSection(i, { description: e.target.value })} placeholder="Description (optional)" />
            <div className="section-tools">
              <button type="button" className="btn btn-icon" onClick={() => handleMoveSection(i, -1)} disabled={i === 0} title="Move section up" aria-label="Move section up">↑</button>
              <button type="button" className="btn btn-icon" onClick={() => handleMoveSection(i, 1)} disabled={i === sections.length - 1} title="Move section down" aria-label="Move section down">↓</button>
              {aiAvailability?.available && (
                <button type="button" className="btn btn-secondary btn-icon" onClick={() => { setRegenError(null); setRegenTarget({ kind: "section", index: i }); }} title="Ask the AI to rewrite this section">✨ Regenerate</button>
              )}
              <button type="button" className="btn btn-danger btn-icon" onClick={() => handleRemoveSection(i)} disabled={sections.length <= 1} title="Remove section">Remove</button>
            </div>
          </div>
        ))}
      </div>

      <div className="panel" style={{ marginBottom: 24 }}>
        <div className="builder-toolbar" style={{ marginBottom: 12 }}>
          <div><h2 style={{ marginBottom: 4 }}>Question Groups</h2><span className="builder-meta">{groups.length} group{groups.length === 1 ? "" : "s"}</span></div>
          <button type="button" className="btn btn-secondary" onClick={addGroup}>+ Add group</button>
        </div>
        {groups.map((group, i) => {
          const gid = group.id ?? `local-${i}`;
          return <div key={gid} className="section-editor-row" style={{ alignItems: "center" }}>
            <input value={group.title} onChange={(e) => updateGroup(i, { title: e.target.value })} placeholder="Group title" />
            <input value={group.description ?? ""} onChange={(e) => updateGroup(i, { description: e.target.value })} placeholder="Description (optional)" />
            <label style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
              <input type="checkbox" checked={group.repeatable} onChange={(e) => updateGroup(i, { repeatable: e.target.checked })} /> Repeatable
            </label>
            {group.repeatable && <>
              <input style={{ maxWidth: 80 }} type="number" min={1} value={group.min_repeats} onChange={(e) => updateGroup(i, { min_repeats: Math.max(1, Number(e.target.value) || 1) })} title="Minimum repeats" />
              <input style={{ maxWidth: 90 }} type="number" min={1} value={group.max_repeats ?? ""} onChange={(e) => updateGroup(i, { max_repeats: e.target.value ? Math.max(1, Number(e.target.value)) : null })} placeholder="Max" title="Maximum repeats" />
            </>}
            <button type="button" className="btn btn-danger btn-icon" onClick={() => removeGroup(i)}>Remove</button>
          </div>;
        })}
        {groups.length === 0 && <p className="loading-text">Groups let you keep related questions together. Mark a group repeatable for repeated household/member records.</p>}
      </div>

      <div className="builder-toolbar">
        <div>
          <h2 style={{ marginBottom: 4 }}>Questions</h2>
          <span className="builder-meta">{questions.length} question{questions.length === 1 ? "" : "s"}</span>
        </div>
        <div className="question-actions">
          <button type="button" className="btn btn-secondary" onClick={undo} disabled={!history.length}>↶ Undo</button>
          <button type="button" className="btn btn-secondary" onClick={redo} disabled={!future.length}>↷ Redo</button>
          <button type="button" className="btn btn-secondary" onClick={() => { setPreviewValues({}); setIsPreviewOpen(true); }}>👁 Preview</button>
        </div>
      </div>
      {questions.map((q, i) => (
        <div key={`wrap-${i}`} className="question-section-wrap">
          <label className="section-select-label">Section
            <select value={q.section_id ?? ""} onChange={(e) => updateQuestion(i, { ...q, section_id: e.target.value || null })}>
              <option value="">First section</option>
              {sections.map((section, si) => <option key={section.id ?? si} value={section.id ?? `local-${si}`}>{section.title || `Section ${si + 1}`}</option>)}
            </select>
          </label>
          <label className="section-select-label">Group
            <select value={q.group_id ?? ""} onChange={(e) => updateQuestion(i, { ...q, group_id: e.target.value || null })}>
              <option value="">No group</option>
              {groups.map((group, gi) => <option key={group.id ?? gi} value={group.id ?? `local-${gi}`}>{group.title || `Group ${gi + 1}`}{group.repeatable ? " · repeatable" : ""}</option>)}
            </select>
          </label>
        <QuestionEditor
          key={i}
          question={q}
          index={i}
          total={questions.length}
          otherQuestions={questions.filter((_, oi) => oi !== i)}
          onChange={(next) => updateQuestion(i, next)}
          onRemove={() => removeQuestion(i)}
          onMoveUp={() => moveQuestion(i, -1)}
          onMoveDown={() => moveQuestion(i, 1)}
          onDuplicate={() => duplicateQuestion(i)}
          onRegenerate={aiAvailability?.available ? () => { setRegenError(null); setRegenTarget({ kind: "question", index: i }); } : undefined}
          draggable
          onDragStart={() => setDragIndex(i)}
          onDragOver={(e) => e.preventDefault()}
          onDrop={() => {
            if (dragIndex !== null) reorderQuestions(dragIndex, i);
            setDragIndex(null);
          }}
        />
        </div>
      ))}

      <button type="button" className="btn btn-secondary" onClick={addQuestion} style={{ marginBottom: 32 }}>
        Add question
      </button>

      <div>
        <button type="button" className="btn btn-primary" onClick={handleSave} disabled={isSaving}>
          {isSaving ? "Saving…" : isNew ? "Create survey" : "Save changes"}
        </button>
      </div>

      {isPreviewOpen && (
        <div className="preview-backdrop" role="dialog" aria-modal="true" aria-label="Survey preview">
          <div className="preview-modal">
            <div className="preview-header">
              <div><strong>{title || "Untitled survey"}</strong><span>{description || "Preview mode"}</span></div>
              <button type="button" className="btn btn-icon" onClick={() => setIsPreviewOpen(false)} aria-label="Close preview">✕</button>
            </div>
            <div className="preview-progress">
              <span>Preview</span><span>{questions.length} questions</span>
            </div>
            <div className="preview-body">
              {questions.map((q, i) => {
                if (!evaluateRelevance(q.relevance_expression)) return null;
                const value = previewValues[q.code] ?? (q.type === "MULTIPLE_CHOICE" ? [] : "");
                const set = (v: string | string[]) => setPreviewValue(q.code, v);
                return (
                  <div className="preview-question" key={`${q.code}-${i}`}>
                    <label>{i + 1}. {q.label || "Untitled question"}{q.is_required && <span className="preview-required"> *</span>}</label>
                    {q.hint && <small>{q.hint}</small>}
                    {q.type === "LONG_TEXT" ? <textarea value={String(value)} onChange={(e) => set(e.target.value)} /> :
                    q.type === "SHORT_TEXT" || q.type === "BARCODE" ? <input value={String(value)} onChange={(e) => set(e.target.value)} placeholder={q.type === "BARCODE" ? "Scan or enter value" : "Type your answer"} /> :
                    q.type === "INTEGER" || q.type === "DECIMAL" ? <input type="number" value={String(value)} onChange={(e) => set(e.target.value)} min={q.min_value ?? undefined} max={q.max_value ?? undefined} /> :
                    q.type === "DATE" ? <input type="date" value={String(value)} onChange={(e) => set(e.target.value)} /> :
                    q.type === "TIME" ? <input type="time" value={String(value)} onChange={(e) => set(e.target.value)} /> :
                    q.type === "DATETIME" ? <input type="datetime-local" value={String(value)} onChange={(e) => set(e.target.value)} /> :
                    q.type === "YES_NO" ? <div className="preview-options">{["Yes", "No"].map((x) => <label key={x}><input type="radio" name={q.code} checked={value === x} onChange={() => set(x)} /> {x}</label>)}</div> :
                    q.type === "SINGLE_CHOICE" || q.type === "DROPDOWN" ? <select value={String(value)} onChange={(e) => set(e.target.value)}><option value="">Choose…</option>{q.choices.map((c) => <option key={c.value} value={c.value}>{c.label || c.value}</option>)}</select> :
                    q.type === "MULTIPLE_CHOICE" ? <div className="preview-options">{q.choices.map((c) => { const values = Array.isArray(value) ? value : []; return <label key={c.value}><input type="checkbox" checked={values.includes(c.value)} onChange={(e) => set(e.target.checked ? [...values, c.value] : values.filter((v) => v !== c.value))} /> {c.label || c.value}</label>; })}</div> :
                    q.type === "GPS" ? <div className="preview-placeholder">📍 GPS location will be captured on the Android device.</div> :
                    q.type === "PHOTO" ? <div className="preview-placeholder">📷 Camera capture will be available on Android.</div> :
                    q.type === "AUDIO" ? <div className="preview-placeholder">🎙 Audio recording will be available on Android.</div> :
                    q.type === "SIGNATURE" ? <div className="preview-placeholder">✍️ Signature pad will be available on Android.</div> : null}
                  </div>
                );
              })}
            </div>
            <div className="preview-footer"><button type="button" className="btn btn-secondary" onClick={() => setIsPreviewOpen(false)}>Close preview</button><button type="button" className="btn btn-primary" onClick={() => setPreviewValues({})}>Reset answers</button></div>
          </div>
        </div>
      )}

      {isAIModalOpen && (
        <GenerateWithAIModal
          maxQuestions={aiAvailability?.max_questions ?? 100}
          initialTitle={title}
          onClose={() => setIsAIModalOpen(false)}
          onUse={handleUsePreview}
        />
      )}

      {isReviewOpen && (
        <ReviewModal
          aiAvailable={aiReady && aiAvailability !== null}
          unavailableMessage={aiAvailability?.message}
          surveyTitle={title}
          surveyDescription={description}
          getDraft={() => ({ sections: latest.current.sections, groups: latest.current.groups, questions: latest.current.questions })}
          currentKey={currentKey}
          state={reviewState}
          onState={setReviewState}
          ignored={ignoredFindings}
          onIgnore={(id) => setIgnoredFindings((prev) => new Set(prev).add(id))}
          onRestore={(id) => setIgnoredFindings((prev) => { const next = new Set(prev); next.delete(id); return next; })}
          onApply={handleApplyAIEdit}
          onClose={() => setIsReviewOpen(false)}
        />
      )}

      {isHistoryOpen && survey && (
        <VersionHistoryModal surveyId={survey.id} onLoad={handleLoadVersion} onClose={() => setIsHistoryOpen(false)} />
      )}

      {regenTarget && (
        <RegenerateModal
          title={regenTarget.kind === "question" ? "Regenerate this question" : "Regenerate this section"}
          impact={
            regenTarget.kind === "question"
              ? `Question ${regenTarget.index + 1} will be rewritten. Its field code stays the same.`
              : `All questions and groups in "${sections[regenTarget.index]?.title || `Section ${regenTarget.index + 1}`}" will be replaced.`
          }
          busy={regenBusy}
          error={regenError}
          onConfirm={handleRegenerate}
          onClose={closeRegenerate}
        />
      )}

      {confirmMode && (
        <ReviewConfirmModal
          mode={confirmMode}
          busy={confirmBusy}
          onConfirm={handleConfirmReview}
          onClose={() => !confirmBusy && setConfirmMode(null)}
        />
      )}
    </div>
  );
}
