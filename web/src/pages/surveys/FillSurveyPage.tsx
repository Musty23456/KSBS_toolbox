import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { i18nApi, surveysApi } from "../../api/services";
import type { Choice, I18nLanguage, I18nLocalized, Question, QuestionGroup, SurveyDetail, SurveySection } from "../../api/types";
import { extractErrorMessage } from "../../api/client";
import { mediaApi, webSubmissionsApi } from "../../api/media";
import type { CapturedFile, MediaKind, WebAnswerIn } from "../../api/media";
import { VoiceRecorder } from "../../components/VoiceRecorder";
import { PhotoCapture } from "../../components/PhotoCapture";
import { SignatureCanvas } from "../../components/SignatureCanvas";
import { coerceAnswer, isRelevant } from "./relevance";
import type { ExpressionValue } from "./relevance";
import { initialLanguage, languageStorageKey, message, pickText } from "../translations/translationUtils";
import "../../styles/fill.css";

const MEDIA_TYPES = new Set(["PHOTO", "AUDIO", "SIGNATURE"]);

type Block =
  | { kind: "section"; section: SurveySection }
  | { kind: "question"; question: Question }
  | { kind: "group"; group: QuestionGroup };

function keyOf(questionId: string, instance: number | null): string {
  return instance === null ? questionId : `${questionId}#${instance}`;
}

function byOrder(a: { order_index: number }, b: { order_index: number }) {
  return a.order_index - b.order_index;
}

export function FillSurveyPage() {
  const { surveyId } = useParams();
  const [survey, setSurvey] = useState<SurveyDetail | null>(null);
  const [text, setText] = useState<Record<string, string>>({});
  const [multi, setMulti] = useState<Record<string, string[]>>({});
  const [media, setMedia] = useState<Record<string, CapturedFile>>({});
  const [instances, setInstances] = useState<Record<string, number[]>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [uploadWarning, setUploadWarning] = useState<string | null>(null);
  // Language the respondent reads the form in. "" = the original text. Answers never depend on it: they are stored by value.
  const [offered, setOffered] = useState<(I18nLanguage & { percent_complete: number })[]>([]);
  const [lang, setLang] = useState("");
  const [loc, setLoc] = useState<I18nLocalized | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await surveysApi.get(surveyId!);
        setSurvey(data);
        const initial: Record<string, number[]> = {};
        data.groups.forEach((g) => {
          if (!g.id) return;
          const count = g.repeatable ? Math.max(g.min_repeats || 0, 1) : 1;
          initial[g.id] = Array.from({ length: count }, (_, i) => i);
        });
        setInstances(initial);
        try {
          const languages = await i18nApi.available(data.id);
          setOffered(languages);
          const start = initialLanguage(localStorage.getItem(languageStorageKey(data.id)), languages.map((l) => l.code));
          if (start) {
            setLoc(await i18nApi.localized(data.id, start));
            setLang(start);
          }
        } catch {
          setOffered([]); // translations are optional: the form works in its original language without them
        }
      } catch {
        setSurvey(null);
      } finally {
        setIsLoading(false);
      }
    })();
  }, [surveyId]);

  async function chooseLanguage(code: string) {
    if (!survey) return;
    try {
      setLoc(code ? await i18nApi.localized(survey.id, code) : null);
      setLang(code);
      localStorage.setItem(languageStorageKey(survey.id), code);
      setErrors({});
      setError(null);
    } catch {
      setError("Could not load that language. The form stays in its current language.");
    }
  }

  // Text in the chosen language, field by field, falling back to the original.
  const tr = {
    survey: (f: "title" | "description", original: string | null) => pickText(loc?.survey?.[f], original),
    section: (s: { id?: string | null; title: string; description?: string | null }, f: "title" | "description") =>
      pickText(s.id ? loc?.sections?.[s.id]?.[f] : undefined, s[f] ?? null),
    group: (g: { id?: string | null; title: string; description?: string | null }, f: "title" | "description") =>
      pickText(g.id ? loc?.groups?.[g.id]?.[f] : undefined, g[f] ?? null),
    label: (q: Question) => pickText(q.id ? loc?.questions?.[q.id]?.label : undefined, q.label),
    hint: (q: Question) => pickText(q.id ? loc?.questions?.[q.id]?.hint : undefined, q.hint ?? null),
    choice: (c: Choice) => pickText(c.id ? loc?.choices?.[c.id] : undefined, c.label),
    msg: (key: string, fallback: string, vars: Record<string, string | number> = {}) => message(loc, key, fallback, vars),
  };

  // ---------- layout: sections -> questions / repeating groups ----------
  const blocks = useMemo<Block[]>(() => {
    if (!survey) return [];
    const sections = [...survey.sections].sort(byOrder);
    const groups = [...survey.groups].sort(byOrder);
    const questions = [...survey.questions].sort(byOrder);
    const sectionIds = new Set(sections.map((s) => s.id).filter((x): x is string => !!x));
    const groupIds = new Set(groups.map((g) => g.id).filter((x): x is string => !!x));
    const sectionOf = (id: string | null | undefined) => (id && sectionIds.has(id) ? id : null);

    const result: Block[] = [];
    const pushContent = (sectionId: string | null) => {
      const items: { order: number; block: Block }[] = [];
      questions
        .filter((q) => (!q.group_id || !groupIds.has(q.group_id)) && sectionOf(q.section_id) === sectionId)
        .forEach((q) => items.push({ order: q.order_index, block: { kind: "question", question: q } }));
      groups
        .filter((g) => sectionOf(g.section_id) === sectionId)
        .forEach((g) => items.push({ order: g.order_index, block: { kind: "group", group: g } }));
      items.sort((a, b) => a.order - b.order).forEach((i) => result.push(i.block));
    };
    pushContent(null);
    sections.forEach((s) => {
      if (!s.id) return;
      result.push({ kind: "section", section: s });
      pushContent(s.id);
    });
    return result;
  }, [survey]);

  const questionNumbers = useMemo(() => {
    const map: Record<string, number> = {};
    let n = 0;
    blocks.forEach((b) => {
      if (b.kind === "question" && b.question.id) map[b.question.id] = ++n;
    });
    return map;
  }, [blocks]);

  // ---------- answers helpers ----------
  function isAnswered(q: Question, instance: number | null): boolean {
    const k = keyOf(q.id ?? "", instance);
    if (q.type === "MULTIPLE_CHOICE") return (multi[k] ?? []).length > 0;
    if (MEDIA_TYPES.has(q.type)) return !!media[k];
    return (text[k] ?? "").trim() !== "";
  }

  function expressionVars(groupId: string | null, instance: number | null): Record<string, ExpressionValue> {
    const vars: Record<string, ExpressionValue> = {};
    if (!survey) return vars;
    survey.questions.forEach((q) => {
      const id = q.id ?? "";
      if (!q.group_id) {
        const v = q.type === "MULTIPLE_CHOICE" ? multi[id] : text[id];
        if (v !== undefined) vars[q.code] = coerceAnswer(v);
      } else if (instance !== null && q.group_id === groupId) {
        const k = keyOf(id, instance);
        const v = q.type === "MULTIPLE_CHOICE" ? multi[k] : text[k];
        if (v !== undefined) vars[q.code] = coerceAnswer(v);
      }
    });
    return vars;
  }

  function isVisible(q: Question, instance: number | null): boolean {
    return isRelevant(q.relevance_expression, expressionVars(q.group_id ?? null, instance));
  }

  function choicesFor(q: Question, instance: number | null): Choice[] {
    const sorted = [...q.choices].sort(byOrder);
    const parentId = q.cascade_parent_question_id;
    if (!parentId || !survey) return sorted;
    const parent = survey.questions.find((x) => x.id === parentId);
    const parentKey = instance !== null && parent?.group_id ? keyOf(parentId, instance) : parentId;
    const parentValue = text[parentKey];
    if (!parentValue) return [];
    return sorted.filter((c) => !c.cascade_parent_value || c.cascade_parent_value === parentValue);
  }

  function visibleQuestionSlots(): { q: Question; instance: number | null }[] {
    const slots: { q: Question; instance: number | null }[] = [];
    if (!survey) return slots;
    blocks.forEach((b) => {
      if (b.kind === "question") {
        if (isVisible(b.question, null)) slots.push({ q: b.question, instance: null });
      } else if (b.kind === "group" && b.group.id) {
        const groupQuestions = survey.questions.filter((q) => q.group_id === b.group.id).sort(byOrder);
        (instances[b.group.id] ?? [0]).forEach((idx) => {
          groupQuestions.forEach((q) => {
            if (isVisible(q, idx)) slots.push({ q, instance: idx });
          });
        });
      }
    });
    return slots;
  }

  const slots = survey ? visibleQuestionSlots() : [];
  const answeredCount = slots.filter((s) => isAnswered(s.q, s.instance)).length;
  const progress = slots.length === 0 ? 0 : Math.round((answeredCount / slots.length) * 100);

  function setValue(q: Question, instance: number | null, value: string) {
    const k = keyOf(q.id ?? "", instance);
    setText((prev) => ({ ...prev, [k]: value }));
    clearError(k);
  }

  function toggleMulti(q: Question, instance: number | null, value: string) {
    const k = keyOf(q.id ?? "", instance);
    setMulti((prev) => {
      const current = prev[k] ?? [];
      const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value];
      return { ...prev, [k]: next };
    });
    clearError(k);
  }

  function setMediaValue(q: Question, instance: number | null, value: CapturedFile | null) {
    const k = keyOf(q.id ?? "", instance);
    setMedia((prev) => {
      const next = { ...prev };
      if (value) next[k] = value;
      else delete next[k];
      return next;
    });
    clearError(k);
  }

  function clearError(k: string) {
    setErrors((prev) => {
      if (!(k in prev)) return prev;
      const next = { ...prev };
      delete next[k];
      return next;
    });
  }

  function captureGps(q: Question, instance: number | null) {
    if (!navigator.geolocation) {
      setError("This browser doesn't support location capture.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => setValue(q, instance, `${pos.coords.latitude.toFixed(6)},${pos.coords.longitude.toFixed(6)}`),
      () => setError("Couldn't get your location. Check the location permission for this site.")
    );
  }

  function addInstance(group: QuestionGroup) {
    if (!group.id) return;
    const gid = group.id;
    setInstances((prev) => {
      const current = prev[gid] ?? [0];
      if (group.max_repeats != null && current.length >= group.max_repeats) return prev;
      const next = (current.length ? Math.max(...current) : -1) + 1;
      return { ...prev, [gid]: [...current, next] };
    });
  }

  function removeInstance(group: QuestionGroup, instance: number) {
    if (!group.id || !survey) return;
    const gid = group.id;
    const current = instances[gid] ?? [0];
    if (current.length <= Math.max(group.min_repeats || 0, 1)) return;
    setInstances((prev) => ({ ...prev, [gid]: (prev[gid] ?? []).filter((i) => i !== instance) }));
    const suffix = `#${instance}`;
    // only remove answers that belong to this group's questions
    const groupQuestionIds = new Set(survey.questions.filter((q) => q.group_id === gid).map((q) => q.id));
    const belongs = (k: string) => k.endsWith(suffix) && groupQuestionIds.has(k.slice(0, k.length - suffix.length));
    setText((prev) => Object.fromEntries(Object.entries(prev).filter(([k]) => !belongs(k))));
    setMulti((prev) => Object.fromEntries(Object.entries(prev).filter(([k]) => !belongs(k))));
    setMedia((prev) => Object.fromEntries(Object.entries(prev).filter(([k]) => !belongs(k))));
  }

  // ---------- validation ----------
  function validate(): Record<string, string> {
    const found: Record<string, string> = {};
    slots.forEach(({ q, instance }) => {
      const k = keyOf(q.id ?? "", instance);
      if (!isAnswered(q, instance)) {
        if (q.is_required) found[k] = tr.msg("msg.required", "This question is required.");
        return;
      }
      const value = text[k] ?? "";
      if (q.type === "INTEGER" || q.type === "DECIMAL") {
        const n = Number(value);
        if (!Number.isFinite(n)) found[k] = tr.msg("msg.number", "Enter a valid number.");
        else if (q.type === "INTEGER" && !Number.isInteger(n)) found[k] = tr.msg("msg.integer", "Enter a whole number.");
        else if (q.min_value != null && n < q.min_value) found[k] = tr.msg("msg.min", "Must be at least {min}.", { min: q.min_value });
        else if (q.max_value != null && n > q.max_value) found[k] = tr.msg("msg.max", "Must be at most {max}.", { max: q.max_value });
      }
      if (q.type === "SHORT_TEXT" || q.type === "LONG_TEXT") {
        if (q.min_length != null && value.trim().length < q.min_length) found[k] = tr.msg("msg.min_length", "Write at least {min} characters.", { min: q.min_length });
        else if (q.max_length != null && value.trim().length > q.max_length) found[k] = tr.msg("msg.max_length", "Write at most {max} characters.", { max: q.max_length });
      }
    });
    return found;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!survey || !survey.current_version_id) return;
    setError(null);

    const found = validate();
    if (Object.keys(found).length > 0) {
      setErrors(found);
      setError(tr.msg("msg.fix_errors", "Please fix {count} highlighted question(s).", { count: Object.keys(found).length }));
      const firstKey = slots.map((s) => keyOf(s.q.id ?? "", s.instance)).find((k) => k in found);
      if (firstKey) document.getElementById(`q-${firstKey}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }

    const payload: WebAnswerIn[] = [];
    const uploads: { questionId: string; instance: number | null; kind: MediaKind; file: CapturedFile }[] = [];
    let gpsLat: number | null = null;
    let gpsLng: number | null = null;

    slots.forEach(({ q, instance }) => {
      const id = q.id ?? "";
      const k = keyOf(id, instance);
      if (q.type === "MULTIPLE_CHOICE") {
        const picked = multi[k] ?? [];
        if (picked.length > 0) {
          payload.push({ question_id: id, value_text: JSON.stringify(picked), group_instance_index: instance });
        }
      } else if (MEDIA_TYPES.has(q.type)) {
        const file = media[k];
        if (file) {
          // the real file is uploaded right after the submission is created
          payload.push({ question_id: id, value_text: null, media_reference: "pending-upload", group_instance_index: instance });
          uploads.push({ questionId: id, instance, kind: q.type as MediaKind, file });
        }
      } else {
        const value = (text[k] ?? "").trim();
        if (value) {
          payload.push({ question_id: id, value_text: value, group_instance_index: instance });
          if (q.type === "GPS" && gpsLat === null) {
            const [lat, lng] = value.split(",").map(Number);
            if (Number.isFinite(lat) && Number.isFinite(lng)) {
              gpsLat = lat;
              gpsLng = lng;
            }
          }
        }
      }
    });

    setIsSubmitting(true);
    try {
      const created = await webSubmissionsApi.create({
        client_submission_uuid: crypto.randomUUID(),
        survey_id: survey.id,
        survey_version_id: survey.current_version_id,
        collected_at: new Date().toISOString(),
        gps_latitude: gpsLat,
        gps_longitude: gpsLng,
        answers: payload,
      });

      let failed = 0;
      for (const item of uploads) {
        try {
          await mediaApi.upload({
            submissionId: created.id,
            questionId: item.questionId,
            kind: item.kind,
            file: item.file.blob,
            filename: item.file.filename,
            groupInstanceIndex: item.instance,
          });
        } catch {
          failed += 1;
        }
      }
      if (failed > 0) {
        setUploadWarning(`Your answers were saved, but ${failed} file(s) (voice / photo / signature) could not be uploaded.`);
      }
      setSubmitted(true);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  // ---------- rendering ----------
  function renderInput(q: Question, instance: number | null) {
    const id = q.id ?? "";
    const k = keyOf(id, instance);
    const value = text[k] ?? "";
    switch (q.type) {
      case "LONG_TEXT":
        return <textarea rows={4} value={value} onChange={(e) => setValue(q, instance, e.target.value)} />;
      case "INTEGER":
        return <input type="number" step="1" inputMode="numeric" value={value} onChange={(e) => setValue(q, instance, e.target.value)} />;
      case "DECIMAL":
        return <input type="number" step="any" inputMode="decimal" value={value} onChange={(e) => setValue(q, instance, e.target.value)} />;
      case "DATE":
        return <input type="date" value={value} onChange={(e) => setValue(q, instance, e.target.value)} />;
      case "TIME":
        return <input type="time" value={value} onChange={(e) => setValue(q, instance, e.target.value)} />;
      case "DATETIME":
        return <input type="datetime-local" value={value} onChange={(e) => setValue(q, instance, e.target.value)} />;
      case "YES_NO":
        return (
          <div className="yesno">
            {["YES", "NO"].map((opt) => (
              <button
                key={opt}
                type="button"
                className={value === opt ? "selected" : ""}
                onClick={() => setValue(q, instance, opt)}
              >
                {opt === "YES" ? tr.msg("ui.yes", "Yes") : tr.msg("ui.no", "No")}
              </button>
            ))}
          </div>
        );
      case "SINGLE_CHOICE": {
        const options = choicesFor(q, instance);
        if (options.length === 0) return <p className="media-note">{tr.msg("ui.answer_earlier", "Answer the earlier question first.")}</p>;
        return (
          <div className="choice-list">
            {options.map((c) => (
              <label key={c.value} className={`choice-item ${value === c.value ? "selected" : ""}`}>
                <input type="radio" name={`r-${k}`} checked={value === c.value} onChange={() => setValue(q, instance, c.value)} />
                {tr.choice(c)}
              </label>
            ))}
          </div>
        );
      }
      case "DROPDOWN": {
        const options = choicesFor(q, instance);
        return (
          <select value={value} onChange={(e) => setValue(q, instance, e.target.value)} disabled={options.length === 0}>
            <option value="">{options.length === 0 ? tr.msg("ui.answer_earlier", "Answer the earlier question first.") : tr.msg("ui.select", "Select…")}</option>
            {options.map((c) => (
              <option key={c.value} value={c.value}>
                {tr.choice(c)}
              </option>
            ))}
          </select>
        );
      }
      case "MULTIPLE_CHOICE": {
        const picked = multi[k] ?? [];
        return (
          <div className="choice-list">
            {choicesFor(q, instance).map((c) => (
              <label key={c.value} className={`choice-item ${picked.includes(c.value) ? "selected" : ""}`}>
                <input type="checkbox" checked={picked.includes(c.value)} onChange={() => toggleMulti(q, instance, c.value)} />
                {tr.choice(c)}
              </label>
            ))}
          </div>
        );
      }
      case "GPS":
        return (
          <div className="voice-row">
            <button type="button" className="btn btn-secondary" onClick={() => captureGps(q, instance)}>
              📍 {value ? "Update location" : "Get current location"}
            </button>
            {value && <span className="mono">{value}</span>}
          </div>
        );
      case "AUDIO":
        return <VoiceRecorder value={media[k]} onChange={(v) => setMediaValue(q, instance, v)} />;
      case "PHOTO":
        return <PhotoCapture value={media[k]} onChange={(v) => setMediaValue(q, instance, v)} />;
      case "SIGNATURE":
        return <SignatureCanvas value={media[k]} onChange={(v) => setMediaValue(q, instance, v)} />;
      case "BARCODE":
        return (
          <div>
            <input
              type="text"
              value={value}
              placeholder="Type the code, or scan it with a handheld scanner"
              onChange={(e) => setValue(q, instance, e.target.value)}
            />
          </div>
        );
      default:
        return <input type="text" value={value} onChange={(e) => setValue(q, instance, e.target.value)} />;
    }
  }

  function renderQuestion(q: Question, instance: number | null) {
    if (!isVisible(q, instance)) return null;
    const id = q.id ?? "";
    const k = keyOf(id, instance);
    const number = instance === null ? questionNumbers[id] : undefined;
    return (
      <div key={k} id={`q-${k}`} className={`q-card ${errors[k] ? "q-has-error" : ""}`}>
        <div className="q-head">
          {number !== undefined && <span className="q-num">{number}</span>}
          <div>
            <p className="q-label">
              {tr.label(q)}
              {q.is_required && <span className="q-required">*</span>}
            </p>
            {q.hint && <p className="q-hint">{tr.hint(q)}</p>}
          </div>
        </div>
        <div className="q-body">
          {renderInput(q, instance)}
          {errors[k] && <p className="q-error-text">{errors[k]}</p>}
        </div>
      </div>
    );
  }

  if (isLoading) return <p className="loading-text">Loading survey…</p>;
  if (!survey) return <p className="loading-text">Survey not found.</p>;

  if (submitted) {
    return (
      <div className="empty-state">
        <h3>Submitted, thank you!</h3>
        <p>Your response to "{survey.title}" has been recorded.</p>
        {uploadWarning && <div className="form-error">{uploadWarning}</div>}
        <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
          <button className="btn btn-primary" onClick={() => window.location.reload()}>
            Fill another response
          </button>
          <Link to="/surveys" className="btn btn-secondary">
            Back to surveys
          </Link>
        </div>
      </div>
    );
  }

  if (survey.status !== "PUBLISHED") {
    return (
      <div className="empty-state">
        <h3>This survey isn't published</h3>
        <p>Only published surveys can be filled in.</p>
        <Link to="/surveys" className="btn btn-secondary">
          Back to surveys
        </Link>
      </div>
    );
  }

  return (
    <div className="fill-page" dir={loc?.rtl ? "rtl" : "ltr"} lang={lang || undefined}>
      <div className="fill-hero">
        {offered.length > 0 && (
          <label className="fill-language">
            <span>{tr.msg("ui.language", "Language")}</span>
            <select value={lang} onChange={(e) => chooseLanguage(e.target.value)}>
              <option value="">Original</option>
              {offered.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.native_name}
                  {l.percent_complete < 100 ? ` (${l.percent_complete}%)` : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        <h1>{tr.survey("title", survey.title)}</h1>
        {survey.description && <p className="fill-description">{tr.survey("description", survey.description)}</p>}
        <div className="fill-progress">
          <div style={{ width: `${progress}%` }} />
        </div>
        <div className="fill-progress-text">
          {tr.msg("ui.progress", "{answered} of {total} answered", { answered: answeredCount, total: slots.length })}
        </div>
      </div>

      {error && <div className="form-error">{error}</div>}

      <form onSubmit={handleSubmit} noValidate>
        {blocks.map((b) => {
          if (b.kind === "section") {
            return (
              <div className="fill-section" key={`s-${b.section.id}`}>
                <h2>{tr.section(b.section, "title")}</h2>
                {b.section.description && <p>{tr.section(b.section, "description")}</p>}
              </div>
            );
          }
          if (b.kind === "question") return renderQuestion(b.question, null);

          const group = b.group;
          const gid = group.id ?? "";
          const groupQuestions = survey.questions.filter((q) => q.group_id === gid).sort(byOrder);
          const list = instances[gid] ?? [0];
          return (
            <div key={`g-${gid}`}>
              <div className="fill-section">
                <h2>{tr.group(group, "title")}</h2>
                {group.description && <p>{tr.group(group, "description")}</p>}
              </div>
              {list.map((idx, position) => (
                <div className="group-card" key={`g-${gid}-${idx}`}>
                  {group.repeatable && <div className="group-title">{tr.group(group, "title")} #{position + 1}</div>}
                  {groupQuestions.map((q) => renderQuestion(q, idx))}
                  {group.repeatable && list.length > Math.max(group.min_repeats || 0, 1) && (
                    <div className="group-actions">
                      <button type="button" className="btn btn-danger" onClick={() => removeInstance(group, idx)}>
                        Remove #{position + 1}
                      </button>
                    </div>
                  )}
                </div>
              ))}
              {group.repeatable && (group.max_repeats == null || list.length < group.max_repeats) && (
                <div className="group-actions">
                  <button type="button" className="btn btn-secondary" onClick={() => addInstance(group)}>
                    + Add another {tr.group(group, "title")}
                  </button>
                </div>
              )}
            </div>
          );
        })}

        <div className="fill-submitbar">
          <span>{tr.msg("ui.progress", "{answered} of {total} answered", { answered: answeredCount, total: slots.length })}</span>
          <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
            {isSubmitting ? tr.msg("ui.submitting", "Submitting…") : tr.msg("ui.submit", "Submit response")}
          </button>
        </div>
      </form>
    </div>
  );
}
