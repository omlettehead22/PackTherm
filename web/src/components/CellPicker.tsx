// Choosing the cell: one from the library, or the user's own, checked by the server as it is typed.
import { useId } from "react";
import exampleCells from "../generated/cells.json";
import { useServerCheck } from "../hooks";
import { ownCellDoc, type FormState, type Values } from "../study";
import type { CellCheck, LibraryCell, Schema } from "../types";
import { Field } from "./Fields";

const REQUIRED_ORDER = ["name", "format", "chemistry", "capacity_Ah", "V_nominal", "mass_g", "DCIR_mOhm"];

const DERIVED: [string, string, (v: number) => string][] = [
  ["energy_Wh", "Energy", (v) => `${v.toFixed(1)} Wh`],
  ["specific_energy_Wh_kg", "Specific energy", (v) => `${v.toFixed(0)} Wh/kg`],
  ["energy_density_Wh_L", "Energy density", (v) => `${v.toFixed(0)} Wh/L`],
  ["density_g_cm3", "Density", (v) => `${v.toFixed(2)} g/cm³`],
  ["max_discharge_C", "Max discharge", (v) => `${v.toFixed(1)}C`],
  ["max_charge_C", "Max charge", (v) => `${v.toFixed(1)}C`],
  ["resistance_rise_at_0C", "Resistance at 0 °C", (v) => `×${v.toFixed(2)}`],
  ["slow_resistance_share", "Slow losses (steady current)", (v) => `+${(v * 100).toFixed(0)} % of the DCIR`],
  ["slow_time_constant_s", "Slow losses build over", (v) => `${(v / 60).toFixed(0)} min (time constant)`],
];

interface Props {
  schema: Schema;
  cells: Record<string, LibraryCell>;
  form: FormState;
  update: (f: Partial<FormState>) => void;
  checkCell: (cell: Values) => Promise<CellCheck>;
}

export function CellPicker({ schema, cells, form, update, checkCell }: Props) {
  const id = useId();
  const own = form.cellSource === "own";
  const doc = own ? ownCellDoc(form.ownCell, schema) : null;
  const check = useServerCheck(doc, checkCell);
  const setOwn = (k: string, v: Values[string]) => update({ ownCell: { ...form.ownCell, [k]: v } });
  const optional = Object.keys(schema.cell.keys).filter((k) => !REQUIRED_ORDER.includes(k));
  const lib = cells[form.libraryCell];

  return (
    <section className="card" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>Cell</h2>
      <div className="segmented" role="radiogroup" aria-label="Cell source">
        {(["library", "own"] as const).map((s) => (
          <label key={s} className={form.cellSource === s ? "on" : ""}>
            <input
              type="radio"
              name={`${id}-source`}
              checked={form.cellSource === s}
              onChange={() => update({ cellSource: s })}
            />
            {s === "library" ? "From the library" : "Your own cell"}
          </label>
        ))}
      </div>

      {!own && (
        <>
          <div className="field">
            <label htmlFor={`${id}-lib`}>Library cell</label>
            <select id={`${id}-lib`} value={form.libraryCell} onChange={(e) => update({ libraryCell: e.target.value })}>
              {Object.entries(cells)
                .filter(([, c]) => c.group !== "comparison")
                .map(([k, c]) => (
                  <option key={k} value={k}>
                    {k}: {c.name}
                  </option>
                ))}
              {Object.values(cells).some((c) => c.group === "comparison") && (
                <optgroup label="For comparison only (not for design)">
                  {Object.entries(cells)
                    .filter(([, c]) => c.group === "comparison")
                    .map(([k, c]) => (
                      <option key={k} value={k}>
                        {k}: {c.name}
                      </option>
                    ))}
                </optgroup>
              )}
            </select>
          </div>
          {lib && (
            <p className="muted">
              {lib.format}, {lib.capacity_Ah} Ah, {lib.V_nominal} V, {lib.mass_g.toFixed(1)} g, DC resistance{" "}
              {lib.DCIR_25C_mOhm.toFixed(0)} mΩ. Model: {lib.model}.
              {lib.group === "comparison" &&
                " For comparison only: an earlier or simpler model of a library cell (a lumped one has no voltage limits, so no cut-off or charge taper). Design with the cell above it."}
            </p>
          )}
        </>
      )}

      {own && (
        <>
          <p className="muted">
            Enter the datasheet values. Start from an example:{" "}
            {exampleCells.map((c, i) => (
              <span key={c.file}>
                {i > 0 && " or "}
                <button
                  type="button"
                  className="link"
                  onClick={() => update({ ownCell: { ...form.ownCell, ...blank(schema), ...(c.cell as Values) } })}
                >
                  {c.label}
                </button>
              </span>
            ))}
            .
          </p>
          <div className="grid">
            {REQUIRED_ORDER.map((k) => (
              <Field
                key={k}
                path={`cell.${k}`}
                rule={schema.cell.keys[k]}
                value={form.ownCell[k] ?? null}
                onChange={(v) => setOwn(k, v)}
              />
            ))}
          </div>
          <details>
            <summary>More datasheet values (optional)</summary>
            <div className="grid">
              {optional.map((k) => (
                <Field
                  key={k}
                  path={`cell.${k}`}
                  rule={schema.cell.keys[k]}
                  value={form.ownCell[k] ?? null}
                  onChange={(v) => setOwn(k, v)}
                />
              ))}
            </div>
          </details>
          <CellCheckView check={check} />
        </>
      )}
    </section>
  );
}

const blank = (schema: Schema): Values =>
  Object.fromEntries(Object.entries(schema.cell.keys).map(([k, r]) => [k, structuredClone(r.default)]));

function CellCheckView({ check }: { check: ReturnType<typeof useServerCheck<Values, CellCheck>> }) {
  if (check.state === "idle") return null;
  if (check.state === "checking")
    return (
      <p className="status" aria-live="polite">
        Checking the cell…
      </p>
    );
  if (check.state === "error")
    return (
      <div className="notice notice--critical" role="alert">
        <p>
          <strong>Not a valid cell yet.</strong> {check.error.problems.length ? "" : check.error.message}
        </p>
        {check.error.problems.length > 0 && (
          <ul>
            {check.error.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
      </div>
    );
  const d = check.value.derived;
  return (
    <div className="cell-check" aria-live="polite">
      <p className="status status--good">
        <span aria-hidden="true">✓</span> Valid cell: {String(d.name)}, modelled as {String(d.model)}.
      </p>
      <dl className="derived">
        {DERIVED.filter(([k]) => typeof d[k] === "number").map(([k, name, fmt]) => (
          <div key={k}>
            <dt>{name}</dt>
            <dd>{fmt(d[k] as number)}</dd>
          </div>
        ))}
      </dl>
      {check.value.warnings.length > 0 && (
        <div className="notice notice--warning">
          <p>
            <strong>Check these values</strong>
          </p>
          <ul>
            {check.value.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
