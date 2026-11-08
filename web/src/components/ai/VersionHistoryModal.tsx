import { useEffect, useState } from "react";
import { extractErrorMessage } from "../../api/client";
import { surveysApi } from "../../api/services";
import type { SurveyVersionDetail, SurveyVersionSummary } from "../../api/types";

interface Props {
  surveyId: string;
  onLoad: (version: SurveyVersionDetail) => void;
  onClose: () => void;
}

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function VersionHistoryModal({ surveyId, onLoad, onClose }: Props) {
  const [versions, setVersions] = useState<SurveyVersionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SurveyVersionDetail | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    surveysApi.versions(surveyId).then(setVersions).catch((e) => setError(extractErrorMessage(e)));
  }, [surveyId]);

  async function view(id: string) {
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
      return;
    }
    setBusyId(id);
    setError(null);
    try {
      setDetail(await surveysApi.getVersion(surveyId, id));
      setOpenId(id);
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setBusyId(null);
    }
  }

  async function load(id: string) {
    setBusyId(id);
    setError(null);
    try {
      onLoad(openId === id && detail ? detail : await surveysApi.getVersion(surveyId, id));
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="preview-backdrop" role="dialog" aria-modal="true" aria-label="Version history">
      <div className="preview-modal ai-modal">
        <div className="preview-header">
          <div>
            <strong>🕘 Version history</strong>
            <span>Every save of the questions creates a new version. Old versions are never changed.</span>
          </div>
          <button type="button" className="btn btn-icon" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="preview-body">
          {error && <div className="form-error">{error}</div>}
          {!versions && !error && <p className="loading-text">Loading…</p>}
          {versions && versions.length === 0 && <p className="ai-muted">No versions yet.</p>}
          <ul className="ai-version-list">
            {versions?.map((v) => (
              <li key={v.id} className="ai-version">
                <div className="ai-version-head">
                  <strong>Version {v.version_number}</strong>
                  {v.is_current && <span className="ai-tag">current</span>}
                  {v.change_source === "AI_EDIT" && <span className="ai-tag">AI assisted</span>}
                  <span className="ai-muted">{when(v.created_at)}{v.created_by_name ? ` · ${v.created_by_name}` : ""}</span>
                </div>
                <div className="ai-muted">{v.question_count} questions · {v.section_count} sections</div>
                {v.change_summary && <p className="ai-version-note">{v.change_summary}</p>}
                <div className="ai-version-actions">
                  <button type="button" className="btn btn-secondary" onClick={() => void view(v.id)} disabled={busyId === v.id}>
                    {openId === v.id ? "Hide questions" : "View questions"}
                  </button>
                  {!v.is_current && (
                    <button type="button" className="btn btn-secondary" onClick={() => void load(v.id)} disabled={busyId === v.id} title="Copies this version into the editor. Nothing is saved until you save.">
                      Load into editor
                    </button>
                  )}
                </div>
                {openId === v.id && detail && (
                  <ol className="ai-version-questions">
                    {detail.questions.map((q, i) => <li key={`${q.code}-${i}`}>{q.label || "(no text)"} <code>{q.code}</code> <span className="ai-muted">{q.type}</span></li>)}
                  </ol>
                )}
              </li>
            ))}
          </ul>
        </div>
        <div className="preview-footer">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
