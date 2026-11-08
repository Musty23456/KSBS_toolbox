import { useRef, useState } from "react";
import { aiQuestionnaireApi } from "../../api/services";
import { extractErrorMessage } from "../../api/client";
import { QUESTION_TYPE_LABELS } from "../../api/types";
import type { GeneratedQuestionnairePreview, QuestionnaireBrief } from "../../api/types";

interface Props {
  maxQuestions: number;
  initialTitle?: string;
  onClose: () => void;
  /** The user chose to load the preview into the Survey Builder. Nothing is saved yet. */
  onUse: (preview: GeneratedQuestionnairePreview, brief: QuestionnaireBrief) => void;
}

const LANGUAGES = ["English", "Hausa", "French", "Arabic", "Yoruba", "Igbo", "Swahili", "Portuguese", "Spanish"];
const METHODOLOGIES = [
  "Cross-sectional household survey",
  "Baseline / endline survey",
  "Facility assessment",
  "Key informant interview",
  "Customer satisfaction survey",
  "Longitudinal panel survey",
  "Rapid assessment",
];

type Phase = "form" | "loading" | "preview";

export function GenerateWithAIModal({ maxQuestions, initialTitle = "", onClose, onUse }: Props) {
  const [topic, setTopic] = useState("");
  const [title, setTitle] = useState(initialTitle);
  const [objectives, setObjectives] = useState("");
  const [respondents, setRespondents] = useState("");
  const [location, setLocation] = useState("");
  const [count, setCount] = useState(20);
  const [language, setLanguage] = useState("English");
  const [methodology, setMethodology] = useState("");
  const [extra, setExtra] = useState("");

  const [phase, setPhase] = useState<Phase>("form");
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<GeneratedQuestionnairePreview | null>(null);
  const [brief, setBrief] = useState<QuestionnaireBrief | null>(null);
  // Ignore the answer of a request the user already walked away from.
  const requestId = useRef(0);

  function buildBrief(): QuestionnaireBrief | string {
    if (topic.trim().length < 3) return "Describe the research topic (at least 3 characters).";
    if (!Number.isInteger(count) || count < 3) return "Ask for at least 3 questions.";
    if (count > maxQuestions) return `You can ask for at most ${maxQuestions} questions at a time.`;
    if (!language.trim()) return "Choose a language.";
    return {
      research_topic: topic.trim(),
      survey_title: title.trim() || null,
      research_objectives: objectives.trim() || null,
      target_respondents: respondents.trim() || null,
      study_location: location.trim() || null,
      expected_question_count: count,
      language: language.trim(),
      methodology: methodology.trim() || null,
      additional_instructions: extra.trim() || null,
    };
  }

  async function run(useBrief: QuestionnaireBrief) {
    const id = ++requestId.current;
    setError(null);
    setPhase("loading");
    try {
      const result = await aiQuestionnaireApi.generate(useBrief);
      if (id !== requestId.current) return;
      setBrief(useBrief);
      setPreview(result);
      setPhase("preview");
    } catch (err) {
      if (id !== requestId.current) return;
      setError(extractErrorMessage(err));
      setPhase("form");
    }
  }

  function handleGenerate() {
    const built = buildBrief();
    if (typeof built === "string") {
      setError(built);
      return;
    }
    void run(built);
  }

  function close() {
    requestId.current++; // drop any answer still on its way
    onClose();
  }

  const sectionOf = (key: string | null | undefined, i0: number) => key ?? `local-${i0}`;

  return (
    <div className="preview-backdrop" role="dialog" aria-modal="true" aria-label="Generate questionnaire with AI">
      <div className="preview-modal ai-modal">
        <div className="preview-header">
          <div>
            <strong>✨ Generate with AI</strong>
            <span>
              {phase === "preview"
                ? "Review the draft. Nothing is saved until you confirm in the builder."
                : "Describe your study and the AI will draft a complete questionnaire you can edit."}
            </span>
          </div>
          <button type="button" className="btn btn-icon" onClick={close} aria-label="Close">
            ✕
          </button>
        </div>

        {phase !== "preview" && (
          <div className="preview-body">
            {error && <div className="form-error">{error}</div>}
            <fieldset disabled={phase === "loading"} className="ai-fieldset">
              <div className="field">
                <label>Research topic *</label>
                <input value={topic} onChange={(e) => setTopic(e.target.value)} maxLength={500} placeholder="e.g. Malaria prevention practices in rural households" />
              </div>
              <div className="field">
                <label>Survey title</label>
                <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={255} placeholder="Leave empty to let the AI suggest one" />
              </div>
              <div className="field">
                <label>Research objectives</label>
                <textarea value={objectives} onChange={(e) => setObjectives(e.target.value)} maxLength={2000} rows={3} placeholder="What do you want to find out?" />
              </div>
              <div className="field-row">
                <div className="field">
                  <label>Target respondents</label>
                  <input value={respondents} onChange={(e) => setRespondents(e.target.value)} maxLength={1000} placeholder="e.g. Heads of household" />
                </div>
                <div className="field">
                  <label>Study location</label>
                  <input value={location} onChange={(e) => setLocation(e.target.value)} maxLength={500} placeholder="e.g. Kano State, Nigeria" />
                </div>
              </div>
              <div className="field-row">
                <div className="field">
                  <label>Number of questions (3–{maxQuestions})</label>
                  <input type="number" min={3} max={maxQuestions} value={count} onChange={(e) => setCount(Number(e.target.value))} />
                </div>
                <div className="field">
                  <label>Preferred language</label>
                  <input list="ai-languages" value={language} onChange={(e) => setLanguage(e.target.value)} maxLength={60} />
                  <datalist id="ai-languages">{LANGUAGES.map((l) => <option key={l} value={l} />)}</datalist>
                </div>
              </div>
              <div className="field">
                <label>Research methodology</label>
                <input list="ai-methodologies" value={methodology} onChange={(e) => setMethodology(e.target.value)} maxLength={1000} placeholder="Pick one or type your own" />
                <datalist id="ai-methodologies">{METHODOLOGIES.map((m) => <option key={m} value={m} />)}</datalist>
              </div>
              <div className="field" style={{ marginBottom: 0 }}>
                <label>Additional instructions</label>
                <textarea value={extra} onChange={(e) => setExtra(e.target.value)} maxLength={2000} rows={3} placeholder="Anything else: topics to include or avoid, sensitive issues, length of interview…" />
              </div>
            </fieldset>
            {phase === "loading" && (
              <p className="ai-working" role="status">
                <span className="ai-spinner" aria-hidden="true" /> Drafting your questionnaire… this can take up to a minute for longer surveys.
              </p>
            )}
          </div>
        )}

        {phase === "preview" && preview && (
          <div className="preview-body">
            <h2 style={{ marginTop: 0 }}>{preview.title}</h2>
            {preview.description && <p>{preview.description}</p>}
            {preview.introduction && (
              <div className="ai-block"><strong>Introduction</strong><p>{preview.introduction}</p></div>
            )}
            {preview.respondent_instructions && (
              <div className="ai-block"><strong>Instructions for respondents</strong><p>{preview.respondent_instructions}</p></div>
            )}

            {preview.warnings.length > 0 && (
              <div className="ai-warnings" role="alert">
                <strong>The AI output needed some clean-up</strong>
                <ul>{preview.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
              </div>
            )}

            {preview.skip_logic.length > 0 && (
              <div className="ai-block">
                <strong>Suggested skip logic ({preview.skip_logic.length})</strong>
                <ul>
                  {preview.skip_logic.map((s) => (
                    <li key={s.question_code}>
                      <code>{s.question_code}</code> is shown when <code>{s.expression}</code>
                      {s.explanation ? ` — ${s.explanation}` : ""}
                    </li>
                  ))}
                </ul>
                <small>You can edit or clear each rule under “Skip logic &amp; advanced” on the question.</small>
              </div>
            )}

            {preview.sections.map((section, si) => {
              const key = sectionOf(null, si);
              const inSection = preview.questions.filter((q) => q.section_id === key);
              return (
                <div key={key} className="ai-section">
                  <h3>{si + 1}. {section.title}</h3>
                  {section.description && <p className="ai-muted">{section.description}</p>}
                  {inSection.map((q) => {
                    const group = preview.groups.find((g, gi) => q.group_id === `local-${gi}` && g);
                    return (
                      <div key={q.code} className="ai-question">
                        <div>
                          <span>{q.label}{q.is_required && <span className="preview-required"> *</span>}</span>
                          {group && <span className="ai-tag">{group.title}{group.repeatable ? " · repeats" : ""}</span>}
                        </div>
                        <small>
                          {QUESTION_TYPE_LABELS[q.type]}
                          {q.choices.length > 0 && ` · ${q.choices.map((c) => c.label).join(" / ")}`}
                          {q.relevance_expression && ` · shown if ${q.relevance_expression}`}
                        </small>
                      </div>
                    );
                  })}
                </div>
              );
            })}
            <p className="ai-muted">{preview.questions.length} questions in {preview.sections.length} section{preview.sections.length === 1 ? "" : "s"}. AI can make mistakes: check the wording, choices and skip logic before you use it.</p>
          </div>
        )}

        <div className="preview-footer">
          {phase !== "preview" && (
            <>
              <button type="button" className="btn btn-secondary" onClick={close}>Cancel</button>
              <button type="button" className="btn btn-primary" onClick={handleGenerate} disabled={phase === "loading"}>
                {phase === "loading" ? "Generating…" : "Generate questionnaire"}
              </button>
            </>
          )}
          {phase === "preview" && preview && brief && (
            <>
              <button type="button" className="btn btn-secondary" onClick={() => setPhase("form")}>Edit brief</button>
              <button type="button" className="btn btn-secondary" onClick={() => void run(brief)}>Regenerate all</button>
              <button type="button" className="btn btn-primary" onClick={() => onUse(preview, brief)}>Use in builder</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
