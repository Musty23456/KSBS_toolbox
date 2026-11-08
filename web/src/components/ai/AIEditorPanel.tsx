import { useRef, useState } from "react";
import { aiEditApi } from "../../api/services";
import { extractErrorMessage } from "../../api/client";
import type { EditOperationView, EditPreview, EditProposal, EditSnapshot } from "../../api/types";
import type { DraftStructure } from "../../pages/surveys/aiDraft";
import { EXAMPLE_COMMANDS, checkApply, selectedOperations, structureKey, toSnapshot } from "../../pages/surveys/aiEdit";
import { EditPreviewView } from "./EditPreviewView";

interface Props {
  /** AI is switched on and configured. Version history and undo still work without it. */
  aiAvailable: boolean;
  unavailableMessage?: string;
  surveyTitle: string;
  surveyDescription: string;
  /** Always returns the latest draft (async handlers must not use a stale closure). */
  getDraft: () => DraftStructure;
  /** structureKey() of the draft right now, so the panel can tell when it changed. */
  currentKey: string;
  canUndo: boolean;
  canRedo: boolean;
  undoLabel?: string;
  redoLabel?: string;
  onUndo: () => void;
  onRedo: () => void;
  onApply: (preview: EditPreview, instruction: string) => void;
  onOpenHistory?: () => void;
}

interface Active {
  instruction: string;
  proposal: EditProposal;
  preview: EditPreview;
  base: EditSnapshot;
  baseKey: string;
}

export function AIEditorPanel(props: Props) {
  const { aiAvailable, getDraft, currentKey } = props;
  const [open, setOpen] = useState(true);
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [active, setActive] = useState<Active | null>(null);
  const [deselected, setDeselected] = useState<ReadonlySet<number>>(new Set());
  const [dropped, setDropped] = useState<ReadonlyMap<number, string>>(new Map());
  const [confirmed, setConfirmed] = useState(false);
  // Ignore answers that arrive after the person moved on (rejected, or ticked something else).
  const ticket = useRef(0);

  async function handleAsk() {
    const text = instruction.trim();
    if (text.length < 3 || busy) return;
    const draft = getDraft();
    const snapshot = toSnapshot(draft);
    const key = structureKey(draft);
    const mine = ++ticket.current;
    setBusy(true);
    setError(null);
    setNotice(null);
    setActive(null);
    try {
      const proposal = await aiEditApi.propose({
        instruction: text,
        snapshot,
        survey_title: props.surveyTitle || null,
        survey_description: props.surveyDescription || null,
      });
      if (mine !== ticket.current) return;
      setActive({ instruction: text, proposal, preview: proposal, base: snapshot, baseKey: key });
      setDeselected(new Set());
      setDropped(new Map());
      setConfirmed(false);
    } catch (err) {
      if (mine === ticket.current) setError(extractErrorMessage(err));
    } finally {
      if (mine === ticket.current) setBusy(false);
    }
  }

  async function handleToggle(index: number) {
    if (!active) return;
    const next = new Set(deselected);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    const ticked = active.proposal.operations.filter((o) => !next.has(o.index));
    const mine = ++ticket.current;
    setDeselected(next);
    setConfirmed(false);
    setChecking(true);
    setError(null);
    try {
      // The server re-validates exactly the ticked operations against the same base questionnaire.
      const preview = await aiEditApi.preview(active.base, selectedOperations(active.proposal, next));
      if (mine !== ticket.current) return;
      const why = new Map<number, string>();
      for (const r of preview.rejected) {
        const original: EditOperationView | undefined = ticked[r.index];
        if (original) why.set(original.index, r.reason);
      }
      setDropped(why);
      setActive({ ...active, preview });
    } catch (err) {
      if (mine === ticket.current) {
        setError(extractErrorMessage(err));
        setActive({ ...active, preview: { ...active.preview, has_changes: false } });
      }
    } finally {
      if (mine === ticket.current) setChecking(false);
    }
  }

  function handleReject() {
    ticket.current++;
    setActive(null);
    setDeselected(new Set());
    setDropped(new Map());
    setConfirmed(false);
    setChecking(false);
    setBusy(false);
    setNotice("Changes rejected. Nothing was changed.");
  }

  function handleApply() {
    if (!active) return;
    const verdict = checkApply(active.preview, { draftUnchanged: currentKey === active.baseKey, confirmed, busy: checking });
    if (!verdict.ok) return;
    props.onApply(active.preview, active.instruction);
    ticket.current++;
    setActive(null);
    setInstruction("");
    setNotice("Changes applied to your draft. Review them, then use Save changes. Undo AI change reverts them.");
  }

  const verdict = checkApply(active?.preview ?? null, {
    draftUnchanged: !active || currentKey === active.baseKey,
    confirmed,
    busy: checking,
  });

  return (
    <div className="panel ai-edit-panel" style={{ marginBottom: 24 }}>
      <div className="builder-toolbar" style={{ marginBottom: open ? 12 : 0 }}>
        <div>
          <h2 style={{ marginBottom: 4 }}>✨ AI Assistant</h2>
          <span className="builder-meta">Edit this questionnaire in plain language. You review every change before it is applied.</span>
        </div>
        <div className="question-actions">
          <button type="button" className="btn btn-secondary" onClick={props.onUndo} disabled={!props.canUndo} title={props.undoLabel ? `Undo: ${props.undoLabel}` : "Nothing to undo"}>↶ Undo AI change</button>
          <button type="button" className="btn btn-secondary" onClick={props.onRedo} disabled={!props.canRedo} title={props.redoLabel ? `Redo: ${props.redoLabel}` : "Nothing to redo"}>↷ Redo AI change</button>
          {props.onOpenHistory && <button type="button" className="btn btn-secondary" onClick={props.onOpenHistory}>🕘 Version history</button>}
          <button type="button" className="btn btn-icon" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label={open ? "Collapse AI Assistant" : "Expand AI Assistant"}>{open ? "−" : "+"}</button>
        </div>
      </div>

      {open && (
        <>
          {!aiAvailable && <p className="ai-muted">{props.unavailableMessage ?? "AI is not available right now."}</p>}
          {error && <div className="form-error" role="alert">{error}</div>}
          {notice && <div className="ai-edit-notice" role="status">{notice}</div>}

          <fieldset className="ai-fieldset" disabled={!aiAvailable || busy}>
            <div className="field" style={{ marginBottom: 8 }}>
              <label htmlFor="ai-edit-command">What should change?</label>
              <textarea
                id="ai-edit-command"
                rows={2}
                maxLength={1000}
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void handleAsk(); }}
                placeholder="e.g. Add five questions about education"
              />
            </div>
            <div className="ai-edit-chips" aria-label="Example commands">
              {EXAMPLE_COMMANDS.map((c) => (
                <button type="button" key={c} className="ai-edit-chip" onClick={() => setInstruction(c)}>{c}</button>
              ))}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12 }}>
              <button type="button" className="btn btn-primary" onClick={() => void handleAsk()} disabled={instruction.trim().length < 3}>
                {busy ? "Working…" : "Propose changes"}
              </button>
              {busy && <span className="ai-working" role="status"><span className="ai-spinner" aria-hidden="true" /> Asking the assistant…</span>}
            </div>
          </fieldset>

          {active && (
            <div className="ai-edit-review">
              <h3>Proposed changes</h3>
              {active.proposal.message && <p className="ai-edit-message">{active.proposal.message}</p>}
              <EditPreviewView
                preview={active.preview}
                allOperations={active.proposal.operations}
                deselected={deselected}
                droppedReasons={dropped}
                busy={checking}
                onToggle={(i) => void handleToggle(i)}
              />

              {active.preview.requires_confirmation && !active.preview.blocked && (
                <label className="ai-check ai-edit-confirm">
                  <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                  <span>
                    <strong>I understand this deletes content.</strong>{" "}
                    {active.preview.confirmation_reasons.join(" ")} You can undo it afterwards, but check the list above first.
                  </span>
                </label>
              )}

              {!verdict.ok && active.preview.has_changes && <p className="ai-muted" role="status">{verdict.reason}</p>}

              <div className="ai-edit-actions">
                <button type="button" className="btn btn-primary" onClick={handleApply} disabled={!verdict.ok}>Apply changes</button>
                <button type="button" className="btn btn-secondary" onClick={handleReject}>Reject changes</button>
              </div>
              <p className="ai-muted">Applying updates your draft only. Nothing is saved until you press Save changes, which creates a new version.</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
