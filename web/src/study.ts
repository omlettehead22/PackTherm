// The setup form's state, and turning it into a study document (and back).
import type { Json, KeyRule, Schema, Section, Study } from "./types";

export type Values = Record<string, Json>;

export interface FormState {
  name: string;
  mode: "fast" | "normal";
  ambient_C: Json;
  cellSource: "library" | "own";
  libraryCell: string;
  ownCell: Values;
  duty: Values;
  requirements: Values;
  design_space: Values;
  options: Values;
}

export const SECTIONS: Section[] = ["requirements", "design_space", "options"];

const defaults = (keys: Record<string, KeyRule>): Values =>
  Object.fromEntries(Object.entries(keys).map(([k, r]) => [k, structuredClone(r.default)]));

/** A fresh form: every key at its default, fast mode, the M50 from the library. */
export function initialForm(schema: Schema): FormState {
  return {
    name: "",
    mode: "fast",
    ambient_C: schema.top.ambient_C.default,
    cellSource: "library",
    libraryCell: "M50",
    ownCell: defaults(schema.cell.keys),
    duty: { ...defaults(schema.duty.keys), type: "constant" },
    requirements: defaults(schema.requirements),
    design_space: defaults(schema.design_space),
    options: defaults(schema.options),
  };
}

/** The form for an existing study (a preset or a results file); the mode is kept unless the study sets one. */
export function formFromStudy(schema: Schema, study: Record<string, Json>, current?: FormState): FormState {
  const f = initialForm(schema);
  if (current) f.mode = current.mode;
  if (typeof study.name === "string") f.name = study.name;
  if (study.mode === "fast" || study.mode === "normal") f.mode = study.mode;
  if (typeof study.ambient_C === "number") f.ambient_C = study.ambient_C;
  if (typeof study.cell === "string") {
    f.cellSource = "library";
    f.libraryCell = study.cell;
  } else if (study.cell && typeof study.cell === "object" && !Array.isArray(study.cell)) {
    f.cellSource = "own";
    f.ownCell = { ...f.ownCell, ...study.cell };
  }
  const merge = (target: Values, src: Json | undefined) => {
    if (src && typeof src === "object" && !Array.isArray(src)) {
      for (const [k, v] of Object.entries(src)) if (k in target) target[k] = structuredClone(v);
    }
  };
  merge(f.duty, study.duty);
  for (const s of SECTIONS) merge(f[s], study[s]);
  return f;
}

const same = (a: Json, b: Json) => JSON.stringify(a) === JSON.stringify(b);

/** Only the keys that differ from their defaults: what a person would write in a study file. */
function changed(values: Values, keys: Record<string, KeyRule>, only?: string[]): Values {
  const out: Values = {};
  for (const [k, rule] of Object.entries(keys)) {
    if (only && !only.includes(k)) continue;
    if (!(k in values) || same(values[k], rule.default)) continue;
    out[k] = values[k];
  }
  return out;
}

/** The user's own cell as a definition: the keys they filled in. */
export function ownCellDoc(cell: Values, schema: Schema): Values {
  const out: Values = {};
  for (const [k, rule] of Object.entries(schema.cell.keys)) {
    const v = cell[k];
    if (v === null || v === undefined || v === "") continue;
    if (!schema.cell.required.includes(k) && same(v, rule.default)) continue;
    out[k] = v;
  }
  return out;
}

/** The study document the form describes. */
export function studyFromForm(f: FormState, schema: Schema): Study {
  const type = String(f.duty.type);
  const study: Study = {
    packtherm_study: 1,
    ...(f.name.trim() ? { name: f.name.trim() } : {}),
    cell: f.cellSource === "library" ? f.libraryCell : ownCellDoc(f.ownCell, schema),
    mode: f.mode,
    duty: { type, ...changed(f.duty, schema.duty.keys, schema.duty.uses[type] ?? []) },
  };
  if (!same(f.ambient_C, schema.top.ambient_C.default)) study.ambient_C = f.ambient_C as number;
  for (const s of SECTIONS) {
    const c = changed(f[s], schema[s]);
    if (Object.keys(c).length) study[s] = c;
  }
  return study;
}

// -- YAML ---------------------------------------------------------------------
// A small writer for study documents (mappings, lists and scalars), so a study
// set up in the browser can be saved and run with `packtherm run`.

const PLAIN = /^[A-Za-z_][A-Za-z0-9 _.,()°%/+-]*$/;
const RESERVED = /^(true|false|yes|no|on|off|null|~|y|n)$/i;

function scalar(v: Json): string {
  if (v === null) return "null";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "null";
  const s = String(v);
  if (PLAIN.test(s) && !RESERVED.test(s) && !s.endsWith(" ") && !/: |, | #/.test(s) && !/[,]$/.test(s)) return s;
  return JSON.stringify(s); // a double-quoted JSON string is valid YAML
}

const isScalarList = (v: Json[]) => v.every((x) => x === null || typeof x !== "object");

function block(v: Json, indent: string): string[] {
  if (v === null || typeof v !== "object") return [scalar(v)];
  if (Array.isArray(v)) {
    if (isScalarList(v)) return [`[${v.map(scalar).join(", ")}]`];
    if (v.every((x) => Array.isArray(x) && isScalarList(x as Json[])))
      return ["", ...v.map((x) => `${indent}- [${(x as Json[]).map(scalar).join(", ")}]`)];
    return [
      "",
      ...v.flatMap((x) => {
        const inner = block(x, indent + "  ");
        if (inner[0] !== "") return [`${indent}- ${inner[0]}`, ...inner.slice(1)];
        const rest = inner.slice(1); // a mapping: its first key goes on the dash line
        return rest.map((l, i) => (i === 0 ? `${indent}- ${l.slice(indent.length + 2)}` : l));
      }),
    ];
  }
  const lines: string[] = [""];
  for (const [k, x] of Object.entries(v)) {
    const inner = block(x, indent + "  ");
    if (inner[0] === "" && inner.length > 1) lines.push(`${indent}${k}:`, ...inner.slice(1));
    else if (inner[0] === "") lines.push(`${indent}${k}: {}`);
    else lines.push(`${indent}${k}: ${inner[0]}`, ...inner.slice(1));
  }
  return lines;
}

export function toYaml(study: Study | Record<string, Json>, comment?: string): string {
  const head = comment ? comment.split("\n").map((l) => `# ${l}`.trimEnd()) : [];
  return [...head, ...block(study as Json, "").slice(1)].join("\n") + "\n";
}

/** A file name from the study name. */
export function fileStem(study: { name?: Json }): string {
  const s = typeof study.name === "string" ? study.name : "study";
  return (
    s
      .toLowerCase()
      .replace(/[^a-z0-9.]+/g, "_")
      .replace(/^_+|_+$/g, "") || "study"
  );
}
