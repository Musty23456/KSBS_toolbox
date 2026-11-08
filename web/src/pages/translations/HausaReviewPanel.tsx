import { useState } from "react";
import { extractErrorMessage } from "../../api/client";
import { i18nApi } from "../../api/services";
import type { HausaFinding, HausaReport, I18nSaveItem } from "../../api/types";

/**
 * Special Hausa quality review. Read-only: it never changes a translation by itself. "Apply" saves the suggested
 * text as an edit by the person who pressed it, after the same safety checks as any manual edit.
 */
export function HausaReviewPanel({ surveyId, onChanged }: { surveyId: string; onChanged: () => void }) {
  const [report, setReport] = useState<HausaReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState<Set<string>>(new Set());

  const keyOf = (f: HausaFinding) => `${f.entity_type}|${f.entity_key}|${f.field}|${f.message}`;

  async function run(useAi: boolean) {
    setBusy(true);
    setError(null);
    try {
      setReport(await i18nApi.hausaReview(surveyId, useAi));
      setApplied(new Set());
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function apply(f: HausaFinding) {
    if (!f.suggestion) return;
    const item: I18nSaveItem = { entity_type: f.entity_type as I18nSaveItem["entity_type"], entity_key: f.entity_key, field: f.field as I18nSaveItem["field"], value: f.suggestion };
    try {
      await i18nApi.save(surveyId, "ha", [item]);
      setApplied((s) => new Set(s).add(keyOf(f)));
      onChanged();
    } catch (e) {
      setError(extractErrorMessage(e));
    }
  }

  return (
    <div className="tr-hausa">
      <div className="tr-hausa-head">
        <div>
          <h3>Hausa quality review</h3>
          <p className="tr-note">
            Checks accuracy, natural phrasing, spelling (hooked letters ɓ ɗ ƙ ƴ), register and consistency. It is an automatic aid, not a
            replacement for a native Hausa speaker.
          </p>
        </div>
        <div className="tr-actions">
          <button className="btn btn-primary" disabled={busy} onClick={() => run(true)}>
            {busy ? "Reviewing…" : "Review with AI"}
          </button>
          <button className="btn btn-secondary" disabled={busy} onClick={() => run(false)}>
            Rules only
          </button>
        </div>
      </div>
      {error && <div className="form-error">{error}</div>}
      {report && (
        <>
          <div className="tr-score">
            <strong>{report.score}</strong>
            <span>/100 · {report.grade}</span>
          </div>
          <p>{report.summary}</p>
          {report.ai_error && <p className="tr-note">AI pass: {report.ai_error}</p>}
          {report.findings.length === 0 && report.reviewed_units > 0 && <p className="tr-ok">No problems found in {report.reviewed_units} item(s).</p>}
          <ul className="tr-findings">
            {report.findings.map((f) => {
              const done = applied.has(keyOf(f));
              return (
                <li key={keyOf(f)} className={f.severity === "WARNING" ? "tr-warn" : "tr-sugg"}>
                  <div>
                    <span className="tr-chip">{f.severity === "WARNING" ? "Warning" : "Suggestion"}</span> <span className="tr-chip tr-cat">{f.category.toLowerCase()}</span>{" "}
                    <span className="tr-muted">{f.source === "AI" ? "AI" : "rule"}</span>
                  </div>
                  <div className="tr-label">{f.label}</div>
                  <div>{f.message}</div>
                  {f.suggestion && (
                    <div className="tr-suggestion">
                      <span lang="ha">{f.suggestion}</span>
                      <button className="btn btn-secondary" disabled={done} onClick={() => apply(f)}>
                        {done ? "Applied" : "Apply"}
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          <ul className="tr-limits">
            {report.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
