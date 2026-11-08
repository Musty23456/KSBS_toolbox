import { useState } from "react";

interface Props {
  title: string;
  /** Plain-language description of what will be replaced. */
  impact: string;
  busy: boolean;
  error: string | null;
  onConfirm: (instruction: string) => void;
  onClose: () => void;
}

export function RegenerateModal({ title, impact, busy, error, onConfirm, onClose }: Props) {
  const [instruction, setInstruction] = useState("");
  return (
    <div className="preview-backdrop" role="dialog" aria-modal="true" aria-label={title}>
      <div className="preview-modal ai-modal ai-modal-small">
        <div className="preview-header">
          <div>
            <strong>✨ {title}</strong>
            <span>{impact}</span>
          </div>
          <button type="button" className="btn btn-icon" onClick={onClose} disabled={busy} aria-label="Close">✕</button>
        </div>
        <div className="preview-body">
          {error && <div className="form-error">{error}</div>}
          <div className="field" style={{ marginBottom: 0 }}>
            <label>What should change? (optional)</label>
            <textarea
              rows={3}
              maxLength={1000}
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              disabled={busy}
              placeholder="e.g. Make it simpler, use a 5-point scale, focus on children under five"
            />
          </div>
          {busy && <p className="ai-working" role="status"><span className="ai-spinner" aria-hidden="true" /> Working…</p>}
          <p className="ai-muted">You can undo a regenerated question with Undo. Regenerated sections replace the whole section.</p>
        </div>
        <div className="preview-footer">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={() => onConfirm(instruction.trim())} disabled={busy}>
            {busy ? "Regenerating…" : "Regenerate"}
          </button>
        </div>
      </div>
    </div>
  );
}
