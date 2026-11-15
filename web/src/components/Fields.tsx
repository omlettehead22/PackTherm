// Form fields generated from the study format's rules (packtherm.study.schema()).
import { useEffect, useId, useState } from "react";
import { CHOICE_LABELS, label, TOPOLOGY_LABELS } from "../labels";
import type { Json, KeyRule } from "../types";

interface FieldProps {
  /** "section.key", for the label lookup. */
  path: string;
  rule: KeyRule;
  value: Json;
  onChange: (v: Json) => void;
}

const nullable = (r: KeyRule) => r.type.includes("null");

/** Problems with a number against its rule, in words. */
export function numberProblem(v: number, r: KeyRule, integer = false): string | null {
  if (!Number.isFinite(v)) return "Enter a number";
  if (integer && !Number.isInteger(v)) return "Enter a whole number";
  if (r.min !== undefined && (r.exclusive ? v <= r.min : v < r.min))
    return r.exclusive ? `Must be more than ${r.min}` : `Must be at least ${r.min}`;
  if (r.max !== undefined && v > r.max) return `Must be at most ${r.max}`;
  return null;
}

function Wrap(props: {
  id: string;
  path: string;
  problem?: string | null;
  /** Explain what leaving the field empty means (keys whose default is null). */
  showEmpty?: boolean;
  children: React.ReactNode;
}) {
  const l = label(props.path);
  return (
    <div className={"field" + (props.problem ? " field--bad" : "")}>
      <label htmlFor={props.id}>
        {l.label}
        {l.unit && <span className="unit"> ({l.unit})</span>}
      </label>
      {props.children}
      {props.problem ? (
        <p className="field__problem" id={`${props.id}-problem`} role="alert">
          {props.problem}
        </p>
      ) : (
        (l.help || (props.showEmpty && l.empty)) && (
          <p className="field__help" id={`${props.id}-help`}>
            {props.showEmpty && l.empty && <>Empty: {l.empty}. </>}
            {l.help}
          </p>
        )
      )}
    </div>
  );
}

/** A number, kept as text while typed so "1." or "-" are not lost. */
export function NumberField({ path, rule, value, onChange }: FieldProps) {
  const id = useId();
  const integer = rule.type.includes("integer") && !rule.type.includes("number");
  const [text, setText] = useState(value === null || value === undefined ? "" : String(value));
  useEffect(() => {
    // Follow outside changes (a preset), but not the parse of what is being typed.
    setText((t) => (t.trim() !== "" && Number(t) === value ? t : value === null ? "" : String(value)));
  }, [value]);
  const empty = text.trim() === "";
  const num = Number(text);
  const problem = empty ? (nullable(rule) ? null : "Required") : numberProblem(num, rule, integer);
  const l = label(path);
  return (
    <Wrap id={id} path={path} problem={problem} showEmpty={nullable(rule)}>
      <input
        id={id}
        type="text"
        inputMode="decimal"
        value={text}
        placeholder={l.empty ? "Automatic" : ""}
        aria-invalid={problem ? true : undefined}
        aria-describedby={problem ? `${id}-problem` : l.help || l.empty ? `${id}-help` : undefined}
        onChange={(e) => {
          const t = e.target.value;
          setText(t);
          if (t.trim() === "") onChange(nullable(rule) ? null : value);
          else if (numberProblem(Number(t), rule, integer) === null) onChange(Number(t));
        }}
      />
    </Wrap>
  );
}

/** A list of numbers, typed as "0.15, 0.3, 0.6". */
export function NumberListField({ path, rule, value, onChange }: FieldProps) {
  const id = useId();
  const show = (v: Json) => (Array.isArray(v) ? v.join(", ") : "");
  const [text, setText] = useState(show(value));
  useEffect(() => {
    setText((t) => (parseList(t).values?.join(",") === (value as number[] | null)?.join(",") ? t : show(value)));
  }, [value]);
  const parsed = parseList(text, rule.items);
  const l = label(path);
  return (
    <Wrap id={id} path={path} problem={parsed.problem}>
      <input
        id={id}
        type="text"
        inputMode="decimal"
        value={text}
        placeholder="none"
        aria-invalid={parsed.problem ? true : undefined}
        aria-describedby={parsed.problem ? `${id}-problem` : l.help ? `${id}-help` : undefined}
        onChange={(e) => {
          setText(e.target.value);
          const p = parseList(e.target.value, rule.items);
          if (!p.problem && p.values) onChange(p.values);
        }}
      />
    </Wrap>
  );
}

export function parseList(text: string, items?: KeyRule): { values?: number[]; problem: string | null } {
  const parts = text
    .split(/[,;\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  const values = parts.map(Number);
  for (let i = 0; i < values.length; i++) {
    const p = items ? numberProblem(values[i], items) : Number.isFinite(values[i]) ? null : "Enter a number";
    if (p) return { problem: `${parts[i]}: ${p.toLowerCase()}` };
  }
  return { values, problem: null };
}

export function ChoiceField({ path, rule, value, onChange }: FieldProps) {
  const id = useId();
  const choices = rule.choices ?? [];
  return (
    <Wrap id={id} path={path}>
      <select
        id={id}
        value={value === null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
      >
        {nullable(rule) && <option value="">{label(path).empty ?? "Not set"}</option>}
        {choices.map((c) => (
          <option key={String(c)} value={String(c)}>
            {CHOICE_LABELS[String(c)] ?? String(c)}
          </option>
        ))}
      </select>
    </Wrap>
  );
}

export function TextField({ path, rule, value, onChange }: FieldProps) {
  const id = useId();
  const l = label(path);
  return (
    <Wrap id={id} path={path}>
      <input
        id={id}
        type="text"
        value={value === null || value === undefined ? "" : String(value)}
        placeholder={l.empty ?? ""}
        aria-describedby={l.help ? `${id}-help` : undefined}
        onChange={(e) => onChange(e.target.value === "" && rule.default === null ? null : e.target.value)}
      />
    </Wrap>
  );
}

export function BoolField({ path, value, onChange }: FieldProps) {
  const id = useId();
  const l = label(path);
  return (
    <div className="field field--check">
      <input id={id} type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} />
      <label htmlFor={id}>{l.label}</label>
    </div>
  );
}

/** A list of choices, as a group of checkboxes. */
export function MultiChoiceField({ path, rule, value, onChange }: FieldProps) {
  const id = useId();
  const choices = rule.items?.choices ?? [];
  const chosen = Array.isArray(value) ? (value as string[]) : [];
  const l = label(path);
  const names = path === "design_space.topologies" ? TOPOLOGY_LABELS : CHOICE_LABELS;
  return (
    <fieldset className="field field--group">
      <legend>{l.label}</legend>
      <div className="checks">
        {choices.map((c) => {
          const cid = `${id}-${c}`;
          return (
            <span key={String(c)} className="check">
              <input
                id={cid}
                type="checkbox"
                checked={chosen.includes(String(c))}
                onChange={(e) => {
                  // Keep the schema's order, so the study reads the same however it was ticked.
                  const next = new Set(chosen);
                  if (e.target.checked) next.add(String(c));
                  else next.delete(String(c));
                  onChange(choices.map(String).filter((x) => next.has(x)));
                }}
              />
              <label htmlFor={cid}>{names[String(c)] ?? String(c)}</label>
            </span>
          );
        })}
      </div>
      {l.help && <p className="field__help">{l.help}</p>}
    </fieldset>
  );
}

/** A custom duty's segments: [duration_s, c_rate] rows. */
export function StepsField({ path, value, onChange }: FieldProps) {
  const rows = Array.isArray(value) ? (value as number[][]) : [];
  const l = label(path);
  const set = (i: number, j: number, v: string) => {
    const next = rows.map((r) => [...r]);
    next[i][j] = Number(v);
    onChange(next);
  };
  return (
    <fieldset className="field field--group">
      <legend>{l.label}</legend>
      {l.help && <p className="field__help">{l.help}</p>}
      <table className="steps">
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Duration (s)</th>
            <th scope="col">Current (C)</th>
            <th scope="col">
              <span className="visually-hidden">Remove</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{i + 1}</td>
              <td>
                <input
                  aria-label={`Segment ${i + 1} duration, seconds`}
                  type="number"
                  min={0}
                  step="any"
                  value={Number.isFinite(r[0]) ? r[0] : ""}
                  onChange={(e) => set(i, 0, e.target.value)}
                />
              </td>
              <td>
                <input
                  aria-label={`Segment ${i + 1} current, C`}
                  type="number"
                  step="any"
                  value={Number.isFinite(r[1]) ? r[1] : ""}
                  onChange={(e) => set(i, 1, e.target.value)}
                />
              </td>
              <td>
                <button
                  type="button"
                  className="button button--quiet"
                  aria-label={`Remove segment ${i + 1}`}
                  onClick={() => onChange(rows.filter((_, k) => k !== i))}
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        type="button"
        className="button button--quiet"
        onClick={() => onChange([...rows, rows.length ? [...rows[rows.length - 1]] : [600, 1]])}
      >
        Add a segment
      </button>
    </fieldset>
  );
}

/** The right field for a key of the study format. */
export function Field(props: FieldProps) {
  const t = props.rule.type;
  if (props.path === "duty.steps") return <StepsField {...props} />;
  if (t.includes("list")) {
    return props.rule.items?.choices ? <MultiChoiceField {...props} /> : <NumberListField {...props} />;
  }
  if (props.rule.choices) return <ChoiceField {...props} />;
  if (t.includes("boolean")) return <BoolField {...props} />;
  if (t.includes("number") || t.includes("integer")) return <NumberField {...props} />;
  return <TextField {...props} />;
}
