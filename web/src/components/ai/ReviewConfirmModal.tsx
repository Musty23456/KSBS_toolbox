import { useState } from "react";

interface Props {
  mode: "save" | "publish";
  busy: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

/** Explicit human sign-off before AI-generated content is saved or published. */
export function ReviewConfirmModal({ mode, busy, onConfirm, onClose }: Props) {
  const [reviewed, setReviewed] = useState(false);
  const publishing = mode === "publish";
  return (
    <div className="preview-backdrop" role="dialog" aria-modal="true" aria-label="Confirm AI-generated content">
      <div className="preview-modal ai-modal ai-modal-small">
        <div className="preview-header">
          <div>
            <strong>{publishing ? "Publish AI-generated survey?" : "Save AI-generated questionnaire?"}</strong>
            <span>
              {publishing
                ? "Publishing makes this survey available to enumerators for data collection."
                : "It is saved as a draft. It will not be published."}
            </span>
          </div>
        </div>
        <div className="preview-body">
          <p>
            Parts of this questionnaire were written by AI. AI can be wrong, biased or miss local context, so a person
            must check it before it is used in the field.
          </p>
          <label className="ai-check">
            <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} disabled={busy} />
            I have reviewed the questions, answer choices, validation rules and skip logic.
          </label>
        </div>
        <div className="preview-footer">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={onConfirm} disabled={!reviewed || busy}>
            {busy ? "Working…" : publishing ? "Publish survey" : "Save as draft"}
          </button>
        </div>
      </div>
    </div>
  );
}
