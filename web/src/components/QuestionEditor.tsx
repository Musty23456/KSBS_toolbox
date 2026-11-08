import type { DragEvent } from "react";
import { CHOICE_TYPES, QUESTION_TYPE_LABELS } from "../api/types";
import type { Choice, Question, QuestionType } from "../api/types";

interface Props {
  question: Question;
  index: number;
  total: number;
  otherQuestions: Question[];
  onChange: (next: Question) => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onDuplicate: () => void;
  /** Present only when AI is available: asks the AI to rewrite this question. */
  onRegenerate?: () => void;
  draggable?: boolean;
  onDragStart?: () => void;
  onDragOver?: (event: DragEvent<HTMLDivElement>) => void;
  onDrop?: () => void;
}

const QUESTION_TYPES = Object.keys(QUESTION_TYPE_LABELS) as QuestionType[];

export function QuestionEditor({ question, index, total, otherQuestions, onChange, onRemove, onMoveUp, onMoveDown, onDuplicate, onRegenerate, draggable, onDragStart, onDragOver, onDrop }: Props) {
  const isChoiceType = CHOICE_TYPES.includes(question.type);
  const isNumeric = question.type === "INTEGER" || question.type === "DECIMAL";
  const isText = question.type === "SHORT_TEXT" || question.type === "LONG_TEXT";

  function update<K extends keyof Question>(key: K, value: Question[K]) {
    onChange({ ...question, [key]: value });
  }

  function updateChoice(choiceIndex: number, next: Partial<Choice>) {
    const choices = question.choices.map((c, i) => (i === choiceIndex ? { ...c, ...next } : c));
    update("choices", choices);
  }

  function addChoice() {
    const nextOrder = question.choices.length + 1;
    update("choices", [...question.choices, { value: "", label: "", order_index: nextOrder }]);
  }

  function removeChoice(choiceIndex: number) {
    update(
      "choices",
      question.choices.filter((_, i) => i !== choiceIndex)
    );
  }

  return (
    <div className="question-card" draggable={draggable} onDragStart={onDragStart} onDragOver={onDragOver} onDrop={onDrop}>
      <div className="question-card-header">
        <span className="question-number">{index + 1}</span>
        <select
          value={question.type}
          onChange={(e) => update("type", e.target.value as QuestionType)}
          style={{ width: 190 }}
        >
          {QUESTION_TYPES.map((t) => (
            <option key={t} value={t}>
              {QUESTION_TYPE_LABELS[t]}
            </option>
          ))}
        </select>
        <div className="question-actions">
          <button type="button" className="btn btn-icon" onClick={onMoveUp} disabled={index === 0} title="Move up">
            ↑
          </button>
          <button
            type="button"
            className="btn btn-icon"
            onClick={onMoveDown}
            disabled={index === total - 1}
            title="Move down"
          >
            ↓
          </button>
          {onRegenerate && (
            <button type="button" className="btn btn-secondary btn-icon" onClick={onRegenerate} title="Ask the AI to rewrite this question">
              ✨ Regenerate
            </button>
          )}
          <button type="button" className="btn btn-secondary btn-icon" onClick={onDuplicate} title="Duplicate question">
            Duplicate
          </button>
          <button type="button" className="btn btn-danger btn-icon" onClick={onRemove} title="Remove question">
            Remove
          </button>
        </div>
      </div>

      <div className="field-row">
        <div className="field">
          <label>Question label</label>
          <input
            type="text"
            value={question.label}
            onChange={(e) => update("label", e.target.value)}
            placeholder="What should the enumerator ask?"
          />
        </div>
        <div className="field" style={{ maxWidth: 220 }}>
          <label>Field code</label>
          <input
            type="text"
            value={question.code}
            onChange={(e) => update("code", e.target.value.replace(/\s+/g, "_"))}
            placeholder="e.g. household_size"
          />
        </div>
      </div>

      <div className="field">
        <label>Hint (optional)</label>
        <input
          type="text"
          value={question.hint ?? ""}
          onChange={(e) => update("hint", e.target.value)}
          placeholder="Extra guidance shown to the enumerator"
        />
      </div>

      <div className="checkbox-row">
        <input
          type="checkbox"
          id={`required-${index}`}
          checked={question.is_required}
          onChange={(e) => update("is_required", e.target.checked)}
        />
        <label htmlFor={`required-${index}`}>Required</label>
      </div>

      {isNumeric && (
        <div className="field-row">
          <div className="field">
            <label>Minimum value</label>
            <input
              type="number"
              value={question.min_value ?? ""}
              onChange={(e) => update("min_value", e.target.value === "" ? null : Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label>Maximum value</label>
            <input
              type="number"
              value={question.max_value ?? ""}
              onChange={(e) => update("max_value", e.target.value === "" ? null : Number(e.target.value))}
            />
          </div>
        </div>
      )}

      {isText && (
        <div className="field-row">
          <div className="field">
            <label>Minimum length</label>
            <input
              type="number"
              value={question.min_length ?? ""}
              onChange={(e) => update("min_length", e.target.value === "" ? null : Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label>Maximum length</label>
            <input
              type="number"
              value={question.max_length ?? ""}
              onChange={(e) => update("max_length", e.target.value === "" ? null : Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label>Regex pattern (optional)</label>
            <input
              type="text"
              value={question.regex_pattern ?? ""}
              onChange={(e) => update("regex_pattern", e.target.value || null)}
              placeholder="^[A-Z0-9-]+$"
            />
          </div>
        </div>
      )}

      {isChoiceType && (
        <div className="field">
          <label>Choices</label>
          {question.choices.map((choice, ci) => (
            <div className="field-row" key={ci} style={{ marginBottom: 6 }}>
              <input
                type="text"
                value={choice.value}
                onChange={(e) => updateChoice(ci, { value: e.target.value })}
                placeholder="Stored value (e.g. FEMALE)"
              />
              <input
                type="text"
                value={choice.label}
                onChange={(e) => updateChoice(ci, { label: e.target.value })}
                placeholder="Shown to enumerator (e.g. Female)"
              />
              <button type="button" className="btn btn-icon" onClick={() => removeChoice(ci)}>
                ✕
              </button>
            </div>
          ))}
          <button type="button" className="btn btn-secondary" onClick={addChoice}>
            Add choice
          </button>
        </div>
      )}

      <details style={{ marginTop: 14 }}>
        <summary style={{ cursor: "pointer", fontSize: 13, color: "var(--muted)" }}>Skip logic &amp; advanced</summary>
        <div style={{ marginTop: 12 }}>
          <div className="field">
            <label>Show this question when</label>
            <div className="logic-builder">
              <select id={`logic-q-${index}`} defaultValue="">
                <option value="">Choose a question…</option>
                {otherQuestions.map((q) => <option key={q.code} value={q.code}>{q.label || q.code}</option>)}
              </select>
              <select id={`logic-op-${index}`} defaultValue="==">
                <option value="==">equals</option>
                <option value="!=">does not equal</option>
                <option value=">">is greater than</option>
                <option value=">=">is greater than or equal to</option>
                <option value="<">is less than</option>
                <option value="<=">is less than or equal to</option>
                <option value="contains">contains</option>
              </select>
              <input id={`logic-value-${index}`} placeholder="Value (e.g. FEMALE)" />
              <button type="button" className="btn btn-secondary" onClick={() => {
                const q = (document.getElementById(`logic-q-${index}`) as HTMLSelectElement).value;
                const op = (document.getElementById(`logic-op-${index}`) as HTMLSelectElement).value;
                const raw = (document.getElementById(`logic-value-${index}`) as HTMLInputElement).value.trim();
                if (!q || !raw) return;
                const quoted = /^-?\d+(\.\d+)?$/.test(raw) || raw === "true" || raw === "false" ? raw : `'${raw.replace(/'/g, "\\'")}'`;
                const expr = op === "contains" ? `${q} contains '${raw.replace(/'/g, "\\'")}'` : `${q} ${op} ${quoted}`;
                update("relevance_expression", expr);
              }}>Add rule</button>
            </div>
          </div>
          <div className="field">
            <label>Generated relevance expression</label>
            <input
              type="text"
              value={question.relevance_expression ?? ""}
              onChange={(e) => update("relevance_expression", e.target.value || null)}
              placeholder="e.g. gender == 'FEMALE' and age_years >= 12"
            />
            <small style={{ color: "var(--muted)" }}>You can still edit the expression manually for advanced logic.</small>
          </div>
          <div className="field">
            <label>Calculated value (optional)</label>
            <input
              type="text"
              value={question.calculation_expression ?? ""}
              onChange={(e) => update("calculation_expression", e.target.value || null)}
              placeholder="e.g. household_size * 12"
            />
          </div>
          <div className="field">
            <label>Default value (optional)</label>
            <input
              type="text"
              value={question.default_value ?? ""}
              onChange={(e) => update("default_value", e.target.value || null)}
            />
          </div>
          {isChoiceType && otherQuestions.length > 0 && (
            <div className="field">
              <label>Cascade from parent question (for location-style cascades)</label>
              <select
                value={question.cascade_parent_question_id ?? ""}
                onChange={(e) => update("cascade_parent_question_id", e.target.value || null)}
              >
                <option value="">None</option>
                {otherQuestions
                  .filter((q) => CHOICE_TYPES.includes(q.type))
                  .map((q) => (
                    <option key={q.code} value={q.id ?? q.code}>
                      {q.label || q.code}
                    </option>
                  ))}
              </select>
            </div>
          )}
        </div>
      </details>
    </div>
  );
}
