import type { EditItemChange, EditPreview, EditOperationView } from "../../api/types";
import { formatValue, summaryText } from "../../pages/surveys/aiEdit";

interface Props {
  /** The latest validated preview (reflects the ticked operations). */
  preview: EditPreview;
  /** Every operation the assistant proposed, in its original numbering. */
  allOperations: EditOperationView[];
  deselected: ReadonlySet<number>;
  /** Why a ticked operation can no longer be applied (e.g. it needed an operation that was unticked). */
  droppedReasons: ReadonlyMap<number, string>;
  busy: boolean;
  onToggle: (index: number) => void;
}

function Badge({ kind }: { kind: "ADDED" | "MODIFIED" | "DELETED" | "MOVED" }) {
  const text = { ADDED: "Added", MODIFIED: "Changed", DELETED: "Deleted", MOVED: "Moved" }[kind];
  return <span className={`ai-edit-badge ai-edit-badge-${kind.toLowerCase()}`}>{text}</span>;
}

function QuestionFacts({ item }: { item: EditItemChange }) {
  const data = item.after ?? item.before;
  if (!data) return null;
  const rules = [
    data.min_value != null && `min ${data.min_value}`,
    data.max_value != null && `max ${data.max_value}`,
    data.min_length != null && `min length ${data.min_length}`,
    data.max_length != null && `max length ${data.max_length}`,
    data.regex_pattern && "format rule",
  ].filter(Boolean);
  return (
    <div className="ai-edit-facts">
      <span>{String(data.type).replace(/_/g, " ").toLowerCase()}</span>
      {data.is_required && <span>required</span>}
      {data.section && <span>section: {data.section}</span>}
      {rules.length > 0 && <span>{rules.join(", ")}</span>}
      {data.relevance_expression && <span>skip logic: {data.relevance_expression}</span>}
      {Array.isArray(data.choices) && data.choices.length > 0 && (
        <span>options: {data.choices.map((c: { label: string }) => c.label).join(", ")}</span>
      )}
    </div>
  );
}

function ItemCard({ item }: { item: EditItemChange }) {
  const isSection = item.item_type === "section";
  const where = item.change === "ADDED" ? item.position_after : item.position_before;
  return (
    <li className={`ai-edit-item ai-edit-item-${item.change.toLowerCase()}`}>
      <div className="ai-edit-item-head">
        <Badge kind={item.change} />
        <strong>{isSection ? "Section" : "Question"}{where ? ` ${where}` : ""}</strong>
        <span className="ai-edit-title">{item.title || "(untitled)"}</span>
        {item.code && <code>{item.code}</code>}
      </div>

      {item.change === "MODIFIED" && (
        <table className="ai-edit-diff">
          <tbody>
            {item.fields.map((f) => (
              <tr key={f.field}>
                <th>{f.label}</th>
                <td className="ai-edit-before" title="Original">{formatValue(f.before)}</td>
                <td className="ai-edit-arrow" aria-hidden="true">→</td>
                <td className="ai-edit-after" title="Proposed">{formatValue(f.after)}</td>
              </tr>
            ))}
            {item.choices.map((c) => (
              <tr key={`${c.kind}-${c.value}`}>
                <th>Option {c.value}</th>
                <td className="ai-edit-before">{c.kind === "ADDED" ? "(none)" : formatValue(c.before_label)}</td>
                <td className="ai-edit-arrow" aria-hidden="true">→</td>
                <td className="ai-edit-after">{c.kind === "REMOVED" ? "(removed)" : formatValue(c.after_label)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {item.change !== "MODIFIED" && !isSection && <QuestionFacts item={item} />}
      {item.change === "DELETED" && isSection && item.before && (
        <div className="ai-edit-facts">
          <span>{item.before.question_count ?? 0} question(s) in this section</span>
        </div>
      )}
      {item.change === "ADDED" && isSection && item.after?.description && <div className="ai-edit-facts"><span>{item.after.description}</span></div>}
    </li>
  );
}

function Group({ title, items }: { title: string; items: EditItemChange[] }) {
  if (!items.length) return null;
  return (
    <section className="ai-edit-group">
      <h4>{title} ({items.length})</h4>
      <ul>{items.map((i) => <ItemCard key={`${i.item_type}-${i.change}-${i.key}`} item={i} />)}</ul>
    </section>
  );
}

export function EditPreviewView({ preview, allOperations, deselected, droppedReasons, busy, onToggle }: Props) {
  return (
    <div className="ai-edit-preview" aria-busy={busy}>
      <p className="ai-edit-summary"><strong>{summaryText(preview.summary)}</strong>
        <span className="ai-muted"> · {preview.summary.questions_before} → {preview.summary.questions_after} questions</span>
      </p>

      {preview.blocked && <div className="form-error" role="alert">{preview.blocked}</div>}

      {preview.warnings.length > 0 && (
        <div className="ai-warnings" role="status">
          <strong>Check these side effects</strong>
          <ul>{preview.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      )}

      {allOperations.length > 0 && (
        <section className="ai-edit-group">
          <h4>Proposed operations</h4>
          <p className="ai-muted">Untick any operation you do not want. Only ticked operations are applied.</p>
          <ul className="ai-edit-ops">
            {allOperations.map((op) => {
              const dropped = droppedReasons.get(op.index);
              const checked = !deselected.has(op.index);
              return (
                <li key={op.index} className={dropped ? "ai-edit-op-dropped" : undefined}>
                  <label>
                    <input type="checkbox" checked={checked} onChange={() => onToggle(op.index)} disabled={busy} />
                    <span><code>{op.op}</code> {op.summary}</span>
                  </label>
                  {op.reason && <small className="ai-muted">{op.reason}</small>}
                  {checked && dropped && <small className="ai-edit-reason">Will not be applied: {dropped}</small>}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <Group title="Added" items={preview.added} />
      <Group title="Changed (original → proposed)" items={preview.modified} />
      <Group title="Deleted" items={preview.deleted} />

      {preview.order_changes.length > 0 && (
        <section className="ai-edit-group">
          <h4>Order changed ({preview.order_changes.length})</h4>
          <ul>
            {preview.order_changes.map((o) => (
              <li key={`${o.item_type}-${o.key}`} className="ai-edit-item ai-edit-item-moved">
                <Badge kind="MOVED" /> <strong>{o.item_type === "section" ? "Section" : "Question"}</strong>{" "}
                <span className="ai-edit-title">{o.title}</span> <span className="ai-muted">{o.from_position} → {o.to_position}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {preview.rejected.length > 0 && (
        <section className="ai-edit-group">
          <h4>Not applied ({preview.rejected.length})</h4>
          <ul className="ai-edit-rejected">
            {preview.rejected.map((r) => (
              <li key={r.index}>
                <code>{r.op || "operation"}</code> {r.summary && <span>{r.summary}</span>}
                <small className="ai-muted"> {r.no_change ? "Nothing to change — " : ""}{r.reason}</small>
              </li>
            ))}
          </ul>
        </section>
      )}

      {!preview.has_changes && !preview.blocked && <p className="ai-muted">No changes were proposed.</p>}
    </div>
  );
}
