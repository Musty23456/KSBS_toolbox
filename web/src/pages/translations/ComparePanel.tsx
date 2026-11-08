import { useEffect, useMemo, useState } from "react";
import { extractErrorMessage } from "../../api/client";
import { i18nApi } from "../../api/services";
import type { I18nCompareRow, I18nLanguage } from "../../api/types";
import { STATUS_LABEL } from "./translationUtils";

/** Read-only side by side: the original text and up to three languages. */
export function ComparePanel({ surveyId, languages, current }: { surveyId: string; languages: I18nLanguage[]; current: string }) {
  const others = languages.filter((l) => l.code !== "en");
  const [picked, setPicked] = useState<string[]>([current]);
  const [rows, setRows] = useState<I18nCompareRow[]>([]);
  const [shown, setShown] = useState<I18nLanguage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [onlyGaps, setOnlyGaps] = useState(false);

  useEffect(() => {
    setPicked((p) => (p.includes(current) ? p : [current, ...p].slice(0, 3)));
  }, [current]);

  useEffect(() => {
    if (picked.length === 0) return;
    let live = true;
    i18nApi
      .compare(surveyId, picked)
      .then((d) => {
        if (!live) return;
        setRows(d.rows);
        setShown(d.languages);
        setError(null);
      })
      .catch((e) => live && setError(extractErrorMessage(e)));
    return () => {
      live = false;
    };
  }, [surveyId, picked]);

  const visible = useMemo(
    () => (onlyGaps ? rows.filter((r) => Object.values(r.translations).some((t) => t.status === "MISSING" || t.status === "OUTDATED")) : rows),
    [rows, onlyGaps]
  );

  function toggle(code: string) {
    setPicked((p) => (p.includes(code) ? p.filter((c) => c !== code) : p.length >= 3 ? p : [...p, code]));
  }

  return (
    <div className="tr-compare">
      <div className="toolbar">
        {others.map((l) => (
          <label key={l.code} className="tr-check">
            <input type="checkbox" checked={picked.includes(l.code)} onChange={() => toggle(l.code)} /> {l.name}
          </label>
        ))}
        <label className="tr-check">
          <input type="checkbox" checked={onlyGaps} onChange={(e) => setOnlyGaps(e.target.checked)} /> Only rows with gaps
        </label>
      </div>
      <p className="tr-note">Compare up to three languages with the original. Differences in length or a gap in one language are easy to spot here.</p>
      {error && <div className="form-error">{error}</div>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Content</th>
              <th>Original</th>
              {shown.map((l) => (
                <th key={l.code}>{l.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={`${r.entity_type}|${r.entity_key}|${r.field}`}>
                <td className="tr-label">{r.label}</td>
                <td>{r.source}</td>
                {shown.map((l) => {
                  const cell = r.translations[l.code];
                  return (
                    <td key={l.code} dir={l.rtl ? "rtl" : "ltr"} className={cell?.status === "MISSING" ? "tr-gap" : ""}>
                      {cell?.value ?? <span className="tr-muted">—</span>}
                      <div>
                        <span className={`tr-chip tr-${(cell?.status ?? "MISSING").toLowerCase()}`}>{STATUS_LABEL[cell?.status ?? "MISSING"]}</span>
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
