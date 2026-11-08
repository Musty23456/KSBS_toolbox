import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { extractErrorMessage } from "../../api/client";
import { i18nApi, surveysApi } from "../../api/services";
import type { I18nLanguageData, I18nOverview, I18nSaveItem, I18nTranslateRequest, I18nUnit, SurveySummary } from "../../api/types";
import { useAuth } from "../../context/AuthContext";
import { ComparePanel } from "./ComparePanel";
import { HausaReviewPanel } from "./HausaReviewPanel";
import { STATUS_LABEL, filterUnits, needsAttention, unitKey } from "./translationUtils";
import type { UnitFilter } from "./translationUtils";
import "../../styles/translations.css";

const CHUNK = 60;
const FILTERS: { id: UnitFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "attention", label: "Needs attention" },
  { id: "missing", label: "Missing" },
  { id: "outdated", label: "Outdated" },
  { id: "issues", label: "Has warnings" },
  { id: "unreviewed", label: "Not reviewed" },
];

type Tab = "edit" | "compare" | "hausa";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function TranslationsPage() {
  const { user } = useAuth();
  const [surveys, setSurveys] = useState<SurveySummary[]>([]);
  const [surveyId, setSurveyId] = useState("");
  const [overview, setOverview] = useState<I18nOverview | null>(null);
  const [language, setLanguage] = useState("ha");
  const [data, setData] = useState<I18nLanguageData | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState<UnitFilter>("attention");
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<Tab>("edit");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [rejected, setRejected] = useState<{ label: string; reason: string }[]>([]);
  const [overwriteManual, setOverwriteManual] = useState(false);

  // Surveys this person may translate: administrators and supervisors, global surveys and their own; everyone else, their own.
  useEffect(() => {
    surveysApi.list().then((all) => {
      const mine = all.filter((s) =>
        s.scope === "PERSONAL" ? s.created_by_id === user?.id : user?.role === "ADMINISTRATOR" || user?.role === "SUPERVISOR"
      );
      setSurveys(mine);
      setSurveyId((current) => current || mine[0]?.id || "");
    });
  }, [user]);

  const refresh = useCallback(async () => {
    if (!surveyId) return;
    const [o, d] = await Promise.all([i18nApi.overview(surveyId), i18nApi.language(surveyId, language)]);
    setOverview(o);
    setData(d);
    setDrafts({});
  }, [surveyId, language]);

  useEffect(() => {
    setData(null);
    setNotice(null);
    setRejected([]);
    refresh().catch((e) => setNotice({ kind: "error", text: extractErrorMessage(e) }));
  }, [refresh]);

  const languages = overview?.languages ?? [];
  const current = overview?.languages.find((l) => l.code === language);
  const rows = useMemo(() => (data ? filterUnits(data.units, filter, search) : []), [data, filter, search]);
  const dirty = useMemo(
    () => (data ? data.units.filter((u) => unitKey(u) in drafts && drafts[unitKey(u)] !== (u.value ?? "")) : []),
    [data, drafts]
  );

  const fail = (e: unknown) => setNotice({ kind: "error", text: extractErrorMessage(e) });

  // ---------------------------------------------------------------- editing

  async function save(items: I18nSaveItem[], what: string) {
    if (!surveyId || items.length === 0) return;
    setBusy(what);
    setNotice(null);
    try {
      const res = await i18nApi.save(surveyId, language, items);
      setNotice({ kind: "ok", text: `Saved ${res.saved}${res.removed ? `, removed ${res.removed}` : ""}.` });
      await refresh();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }

  const asItem = (u: I18nUnit, value: string): I18nSaveItem => ({ entity_type: u.entity_type, entity_key: u.entity_key, field: u.field, value, status: "EDITED" });

  // ---------------------------------------------------------------- AI translation (chunked, resumable)

  async function runTranslate(label: string, targets: I18nUnit[]) {
    if (!surveyId || targets.length === 0) {
      setNotice({ kind: "ok", text: "Nothing to translate." });
      return;
    }
    setBusy(label);
    setNotice(null);
    setRejected([]);
    let done = 0;
    const problems: { label: string; reason: string }[] = [];
    let skippedProtected = 0;
    try {
      for (let start = 0; start < targets.length; start += CHUNK) {
        const body: I18nTranslateRequest = {
          scope: "all",
          overwrite_manual: overwriteManual,
          max_units: CHUNK,
          units: targets.slice(start, start + CHUNK).map((u) => ({ entity_type: u.entity_type, entity_key: u.entity_key, field: u.field })),
        };
        let result = null;
        for (let attempt = 0; attempt < 4 && !result; attempt++) {
          try {
            result = await i18nApi.translate(surveyId, language, body);
          } catch (e) {
            if (axios.isAxiosError(e) && e.response?.status === 429 && attempt < 3) {
              const wait = Number(e.response.headers?.["retry-after"]) || 20;
              setBusy(`${label} — waiting ${wait}s for the AI rate limit…`);
              await sleep(wait * 1000);
              setBusy(label);
            } else {
              throw e;
            }
          }
        }
        if (!result) break;
        done += result.translated;
        skippedProtected += result.protected_skipped;
        problems.push(...result.rejected);
        setBusy(`${label} — ${Math.min(start + CHUNK, targets.length)} of ${targets.length}`);
        if (result.ai_error) {
          setNotice({ kind: "error", text: result.ai_error });
          break;
        }
        if (result.translated === 0 && result.protected_skipped === 0) break; // no progress: stop instead of looping
      }
      setRejected(problems);
      setNotice((n) =>
        n?.kind === "error"
          ? { kind: "error", text: `${n.text} ${done} item(s) were translated before it stopped.` }
          : { kind: "ok", text: `Translated ${done} item(s) as AI drafts.${skippedProtected ? ` ${skippedProtected} edited by a person were kept.` : ""}${problems.length ? ` ${problems.length} could not be used and are still untranslated.` : ""}` }
      );
      await refresh();
    } catch (e) {
      fail(e);
      await refresh().catch(() => undefined);
    } finally {
      setBusy(null);
    }
  }

  const needing = () => (data?.units ?? []).filter((u) => u.status === "MISSING" || u.status === "OUTDATED");
  const everything = () => (data?.units ?? []).filter((u) => overwriteManual || (u.status !== "EDITED" && u.status !== "REVIEWED"));

  async function removeLanguage() {
    if (!current || !window.confirm(`Delete the whole ${current.name} version of this questionnaire? The original questions are not affected.`)) return;
    setBusy("delete");
    try {
      await i18nApi.remove(surveyId, language);
      setNotice({ kind: "ok", text: `${current.name} translation deleted.` });
      await refresh();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }

  async function importOlder() {
    setBusy("import");
    try {
      const r = await i18nApi.importLegacy(surveyId);
      setNotice({ kind: "ok", text: `Imported ${r.imported}; ${r.skipped_existing} already existed; ${r.not_matched} did not match the current questionnaire.` });
      await refresh();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }

  // ---------------------------------------------------------------- render

  if (surveys.length === 0 && !surveyId) {
    return (
      <div>
        <div className="page-header"><div><h1>Multilingual surveys</h1></div></div>
        <p className="loading-text">No surveys you can translate yet.</p>
      </div>
    );
  }

  const summary = data?.summary;
  return (
    <div className="tr-page">
      <div className="page-header">
        <div>
          <h1>Multilingual surveys</h1>
          <p>Translate a whole questionnaire with AI, then check and correct it. Question codes, answer values and rules are never translated, so collected data stays consistent.</p>
        </div>
      </div>

      <div className="toolbar">
        <select value={surveyId} onChange={(e) => setSurveyId(e.target.value)} aria-label="Survey">
          {surveys.map((s) => (
            <option key={s.id} value={s.id}>{s.title}</option>
          ))}
        </select>
        {overview && <span className="tr-muted">version {overview.version_number} · {overview.total_units} texts</span>}
      </div>

      <div className="tr-langs" role="tablist">
        {languages.filter((l) => l.code !== "en").map((l) => (
          <button key={l.code} role="tab" aria-selected={l.code === language} className={`tr-lang ${l.code === language ? "active" : ""}`} onClick={() => setLanguage(l.code)}>
            <strong>{l.name}</strong>
            <span>{l.percent_complete}%</span>
            <div className="tr-bar"><div style={{ width: `${l.percent_complete}%` }} /></div>
            {needsAttention(l) && l.translated > 0 && <em>{l.missing + l.outdated} to do</em>}
          </button>
        ))}
      </div>

      {notice && <div className={notice.kind === "ok" ? "tr-ok" : "form-error"}>{notice.text}</div>}
      {busy && <div className="tr-busy">{busy}…</div>}

      <div className="tr-tabs">
        {(["edit", "compare", ...(language === "ha" ? ["hausa"] : [])] as Tab[]).map((t) => (
          <button key={t} className={`tr-tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {t === "edit" ? "Translate & edit" : t === "compare" ? "Compare" : "Hausa quality review"}
          </button>
        ))}
      </div>

      {tab === "compare" && surveyId && <ComparePanel surveyId={surveyId} languages={languages} current={language} />}
      {tab === "hausa" && language === "ha" && <HausaReviewPanel surveyId={surveyId} onChanged={() => refresh().catch(fail)} />}

      {tab === "edit" && (
        <>
          {summary && (
            <div className="tr-stats">
              <span>{summary.translated} of {summary.total} translated</span>
              <span className="tr-chip tr-missing">{summary.missing} missing</span>
              <span className="tr-chip tr-outdated">{summary.outdated} outdated</span>
              <span className="tr-chip tr-ai_draft">{summary.ai_draft} AI draft</span>
              <span className="tr-chip tr-edited">{summary.edited} edited</span>
              <span className="tr-chip tr-reviewed">{summary.reviewed} reviewed</span>
              {summary.with_issues > 0 && <span className="tr-chip tr-warn">{summary.with_issues} with warnings</span>}
            </div>
          )}

          <div className="tr-actions">
            <button className="btn btn-primary" disabled={!!busy || !data} onClick={() => runTranslate(`Translating ${current?.name}`, needing())}>
              Translate missing &amp; outdated ({needing().length})
            </button>
            <button className="btn btn-secondary" disabled={!!busy || !data} onClick={() => {
              if (window.confirm(`Re-translate everything${overwriteManual ? ", including text written or reviewed by a person" : " that a person has not edited"}?`)) runTranslate(`Re-translating ${current?.name}`, everything());
            }}>
              Re-translate all
            </button>
            <label className="tr-check" title="Off by default: your own edits are never overwritten">
              <input type="checkbox" checked={overwriteManual} onChange={(e) => setOverwriteManual(e.target.checked)} /> Also overwrite edited / reviewed text
            </label>
            {dirty.length > 0 && (
              <button className="btn btn-primary" disabled={!!busy} onClick={() => save(dirty.map((u) => asItem(u, drafts[unitKey(u)])), "save")}>
                Save {dirty.length} change{dirty.length === 1 ? "" : "s"}
              </button>
            )}
            <button className="btn btn-secondary" disabled={!!busy} onClick={importOlder} title="Copy translations from the older Languages page">Import older translations</button>
            {summary && summary.translated > 0 && <button className="btn btn-danger" disabled={!!busy} onClick={removeLanguage}>Delete {current?.name}</button>}
          </div>

          {rejected.length > 0 && (
            <div className="form-error">
              The AI's answer was not used for: {rejected.map((r) => `${r.label} (${r.reason})`).join("; ")}. Translate those by hand.
            </div>
          )}

          <div className="toolbar">
            {FILTERS.map((f) => (
              <button key={f.id} className={`tr-filter ${filter === f.id ? "active" : ""}`} onClick={() => setFilter(f.id)}>{f.label}</button>
            ))}
            <input type="search" placeholder="Search text…" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>

          {!data ? (
            <p className="loading-text">Loading…</p>
          ) : rows.length === 0 ? (
            <p className="loading-text">{filter === "attention" ? "Nothing needs attention." : "No texts match."}</p>
          ) : (
            <div className="table-wrap">
              <table className="tr-table">
                <thead>
                  <tr><th>Content</th><th>Original</th><th>{current?.name}</th><th></th></tr>
                </thead>
                <tbody>
                  {rows.map((u) => {
                    const k = unitKey(u);
                    const value = k in drafts ? drafts[k] : u.value ?? "";
                    const changed = value !== (u.value ?? "");
                    return (
                      <tr key={k}>
                        <td className="tr-label">{u.label}<div><span className={`tr-chip tr-${u.status.toLowerCase()}`}>{STATUS_LABEL[u.status]}</span></div></td>
                        <td className="tr-source">{u.source}</td>
                        <td>
                          <textarea
                            dir={current?.rtl ? "rtl" : "ltr"}
                            rows={u.multiline ? 3 : 2}
                            value={value}
                            maxLength={u.max_len}
                            placeholder={u.status === "MISSING" ? "Not translated yet" : ""}
                            onChange={(e) => setDrafts({ ...drafts, [k]: e.target.value })}
                          />
                          {u.issues.map((i) => (
                            <div key={i.code} className={i.severity === "BLOCK" ? "tr-issue-block" : "tr-issue"}>{i.message}</div>
                          ))}
                        </td>
                        <td className="tr-rowact">
                          <button className="btn btn-secondary" disabled={!!busy || !changed} onClick={() => save([asItem(u, value)], "save")}>Save</button>
                          {u.value !== null && u.status !== "REVIEWED" && !changed && (
                            <button className="btn btn-secondary" disabled={!!busy} onClick={() => save([{ entity_type: u.entity_type, entity_key: u.entity_key, field: u.field, status: "REVIEWED" }], "review")}>
                              {u.status === "OUTDATED" ? "Still correct" : "Mark reviewed"}
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
