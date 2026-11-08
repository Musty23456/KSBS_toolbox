import { useState } from "react";
import { aiEditApi, aiReviewApi } from "../../api/services";
import { extractErrorMessage } from "../../api/client";
import type { EditPreview, ReviewFinding, ReviewReport } from "../../api/types";
import type { DraftStructure } from "../../pages/surveys/aiDraft";
import { structureKey, toSnapshot } from "../../pages/surveys/aiEdit";
import {
  SEVERITY_ORDER,
  SEVERITY_TITLE,
  canApply,
  categoryLabel,
  groupFindings,
  isStale,
  openProblemCount,
  reportToMarkdown,
  scoreTone,
} from "../../pages/surveys/reviewReport";
import { EditPreviewView } from "./EditPreviewView";

export interface ReviewState {
  objectives: string;
  report: ReviewReport | null;
  /** structureKey() of the draft that was reviewed. */
  reviewedKey: string | null;
}

interface Props {
  aiAvailable: boolean;
  unavailableMessage?: string;
  surveyTitle: string;
  surveyDescription: string;
  getDraft: () => DraftStructure;
  currentKey: string;
  state: ReviewState;
  onState: (next: ReviewState) => void;
  ignored: ReadonlySet<string>;
  onIgnore: (id: string) => void;
  onRestore: (id: string) => void;
  /** Applies a validated preview to the builder's draft (undoable, saved only when the person saves). */
  onApply: (preview: EditPreview, label: string) => void;
  onClose: () => void;
}

interface Pending {
  finding: ReviewFinding;
  preview: EditPreview;
  key: string;
}

const NO_OPS: ReadonlySet<number> = new Set();
const NO_REASONS: ReadonlyMap<number, string> = new Map();

export function ReviewModal(props: Props) {
  const { aiAvailable, state, onState, ignored, getDraft, currentKey } = props;
  const [busy, setBusy] = useState(false);
  const [useAi, setUseAi] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [applied, setApplied] = useState<ReadonlySet<string>>(new Set());
  const [showIgnored, setShowIgnored] = useState(false);
  const { report } = state;

  async function run() {
    setBusy(true);
    setError(null);
    setNotice(null);
    setPending(null);
    try {
      const draft = getDraft();
      const result = await aiReviewApi.review({
        snapshot: toSnapshot(draft),
        objectives: state.objectives.trim() || null,
        survey_title: props.surveyTitle || null,
        survey_description: props.surveyDescription || null,
        use_ai: useAi && aiAvailable,
      });
      onState({ ...state, report: result, reviewedKey: structureKey(draft) });
      setApplied(new Set());
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function startApply(finding: ReviewFinding) {
    if (!finding.fix) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const draft = getDraft();
      const preview = await aiEditApi.preview(toSnapshot(draft), [finding.fix]);
      if (preview.blocked || preview.rejected.length > 0 || !preview.has_changes || preview.requires_confirmation) {
        setNotice(
          preview.rejected[0]?.reason ??
            preview.blocked ??
            "This suggestion no longer applies to the current questionnaire. Run the review again."
        );
        return;
      }
      setPending({ finding, preview, key: structureKey(draft) });
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  function confirmApply() {
    if (!pending) return;
    if (structureKey(getDraft()) !== pending.key) {
      setPending(null);
      setNotice("The questionnaire changed while you were looking at this suggestion. Open it again.");
      return;
    }
    props.onApply(pending.preview, `Review fix: ${pending.finding.fix_summary ?? pending.finding.title}`);
    setApplied((s) => new Set(s).add(pending.finding.id));
    setNotice("Applied to your draft. You can undo it with “Undo AI change”. Nothing is saved until you save.");
    setPending(null);
  }

  async function copyReport() {
    if (!report) return;
    try {
      await navigator.clipboard.writeText(reportToMarkdown(report, ignored, props.surveyTitle || "Questionnaire review"));
      setNotice("Report copied.");
    } catch {
      setError("Could not copy. Use “Download report” instead.");
    }
  }

  function downloadReport() {
    if (!report) return;
    const md = reportToMarkdown(report, ignored, props.surveyTitle || "Questionnaire review");
    const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "questionnaire-review.md";
    a.click();
    URL.revokeObjectURL(url);
  }

  const grouped = report ? groupFindings(report.findings, ignored) : null;
  const stale = isStale(state.reviewedKey, currentKey);

  return (
    <div className="preview-overlay" role="dialog" aria-modal="true" aria-label="Review with AI">
      <div className="preview-modal ai-modal">
        <div className="preview-header">
          <div>
            <strong>🔍 Review with AI</strong>
            <span>A read-only quality check. Nothing changes unless you press “Apply” on a suggestion.</span>
          </div>
          <button type="button" className="btn btn-icon" onClick={props.onClose} aria-label="Close">✕</button>
        </div>

        <div className="preview-body">
          {error && <div className="form-error" role="alert">{error}</div>}
          {notice && <div className="ai-edit-notice" role="status">{notice}</div>}

          {pending ? (
            <section className="ai-review-confirm">
              <h4>{pending.finding.title}</h4>
              <p className="ai-muted">This is exactly what will change in your draft:</p>
              <EditPreviewView
                preview={pending.preview}
                allOperations={pending.preview.operations}
                deselected={NO_OPS}
                droppedReasons={NO_REASONS}
                busy={false}
                onToggle={() => undefined}
              />
              <div className="ai-edit-actions">
                <button type="button" className="btn btn-primary" onClick={confirmApply}>Apply this suggestion</button>
                <button type="button" className="btn btn-secondary" onClick={() => setPending(null)}>Cancel</button>
              </div>
            </section>
          ) : (
            <>
              <div className="field">
                <label htmlFor="review-objectives">Research objectives (optional)</label>
                <textarea
                  id="review-objectives"
                  rows={3}
                  maxLength={3000}
                  value={state.objectives}
                  onChange={(e) => onState({ ...state, objectives: e.target.value })}
                  placeholder={"One per line, e.g.\nMeasure household use of health clinics\nUnderstand satisfaction with services"}
                  disabled={busy}
                />
                <small className="ai-muted">Add them to check whether the questionnaire collects what you need.</small>
              </div>
              <div className="ai-edit-actions">
                <button type="button" className="btn btn-primary" onClick={() => void run()} disabled={busy}>
                  {busy ? "Working…" : report ? "Review again" : "Start review"}
                </button>
                <label className="ai-inline-check" title={aiAvailable ? "" : unavailableText(props.unavailableMessage)}>
                  <input type="checkbox" checked={useAi && aiAvailable} onChange={(e) => setUseAi(e.target.checked)} disabled={!aiAvailable || busy} /> Include AI analysis
                </label>
                {report && (
                  <>
                    <button type="button" className="btn btn-secondary" onClick={() => void copyReport()}>Copy report</button>
                    <button type="button" className="btn btn-secondary" onClick={downloadReport}>Download report</button>
                  </>
                )}
              </div>
              {!aiAvailable && <p className="ai-muted">{unavailableText(props.unavailableMessage)} Built-in checks still run.</p>}

              {report && grouped && (
                <div className="ai-review-report">
                  {stale && (
                    <div className="ai-warnings" role="status">
                      <strong>The questionnaire changed after this review.</strong> Run it again to refresh the score and suggestions.
                    </div>
                  )}
                  <div className={`ai-score ai-score-${scoreTone(report.score)}`}>
                    <div className="ai-score-number" aria-label={`Quality score ${report.score} out of 100`}>{report.score}<span>/100</span></div>
                    <div>
                      <strong>{report.grade}</strong>
                      <p>{report.summary}</p>
                      <p className="ai-muted">
                        {openProblemCount(report.findings, ignored)} open · {ignored.size} ignored · {report.ai_used ? `AI used (${report.model})` : "built-in checks only"}
                      </p>
                    </div>
                  </div>
                  {report.ai_error && <div className="ai-warnings" role="status">AI analysis was skipped: {report.ai_error}</div>}

                  {report.coverage.length > 0 && (
                    <section className="ai-edit-group">
                      <h4>Research objectives</h4>
                      <ul className="ai-coverage">
                        {report.coverage.map((c) => (
                          <li key={c.objective} className={c.covered ? "ai-covered" : "ai-uncovered"}>
                            <span aria-hidden>{c.covered ? "✅" : "❌"}</span> {c.objective}
                            {c.question_codes.length > 0 && <code>{c.question_codes.join(", ")}</code>}
                            {c.note && <div className="ai-muted">{c.note}</div>}
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}

                  {SEVERITY_ORDER.map((sev) => {
                    const items = grouped.groups[sev];
                    if (!items.length) return null;
                    return (
                      <section key={sev} className={`ai-edit-group ai-sev-${sev.toLowerCase()}`}>
                        <h4>{SEVERITY_TITLE[sev]} ({items.length})</h4>
                        <ul className="ai-findings">
                          {items.map((f) => (
                            <FindingCard
                              key={f.id}
                              finding={f}
                              busy={busy}
                              applied={applied.has(f.id)}
                              onApply={() => void startApply(f)}
                              onIgnore={sev === "GOOD" ? undefined : () => props.onIgnore(f.id)}
                            />
                          ))}
                        </ul>
                      </section>
                    );
                  })}

                  {grouped.ignored.length > 0 && (
                    <section className="ai-edit-group">
                      <h4>
                        <button type="button" className="ai-link" onClick={() => setShowIgnored((v) => !v)}>
                          {showIgnored ? "Hide" : "Show"} ignored ({grouped.ignored.length})
                        </button>
                      </h4>
                      {showIgnored && (
                        <ul className="ai-findings">
                          {grouped.ignored.map((f) => (
                            <li key={f.id} className="ai-finding ai-finding-ignored">
                              <span>{f.title}{f.question_code && <code>{f.question_code}</code>}</span>
                              <button type="button" className="btn btn-secondary" onClick={() => props.onRestore(f.id)}>Restore</button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </section>
                  )}

                  {report.limitations.length > 0 && (
                    <details className="ai-limitations">
                      <summary>About this review</summary>
                      <ul>{report.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
                      <p className="ai-muted">
                        Score = 100 − penalties for issues (critical 10, warning 4, suggestion 1 each, scaled for questionnaire size) + up to 5 for good practices.
                      </p>
                    </details>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        <div className="preview-footer">
          <button type="button" className="btn btn-secondary" onClick={props.onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

function unavailableText(message?: string): string {
  return message || "AI is not available right now.";
}

function FindingCard(props: {
  finding: ReviewFinding;
  busy: boolean;
  applied: boolean;
  onApply: () => void;
  onIgnore?: () => void;
}) {
  const { finding: f } = props;
  return (
    <li className="ai-finding">
      <div className="ai-finding-head">
        <strong>{f.title}</strong>
        <span className="ai-tag">{categoryLabel(f.category)}</span>
        {f.source === "AI" && <span className="ai-tag">AI</span>}
        {f.question_code && <code>{f.question_code}</code>}
      </div>
      {f.question_label && <div className="ai-finding-q">“{f.question_label}”</div>}
      {f.explanation && <p>{f.explanation}</p>}
      {f.recommendation && <p className="ai-finding-rec"><strong>Recommended:</strong> {f.recommendation}</p>}
      <div className="ai-version-actions">
        {canApply(f) && !props.applied && (
          <button type="button" className="btn btn-secondary" onClick={props.onApply} disabled={props.busy}>
            Apply: {f.fix_summary ?? "suggested fix"}
          </button>
        )}
        {props.applied && <span className="ai-tag">applied</span>}
        {props.onIgnore && (
          <button type="button" className="btn btn-secondary" onClick={props.onIgnore} disabled={props.busy}>Ignore</button>
        )}
      </div>
    </li>
  );
}
