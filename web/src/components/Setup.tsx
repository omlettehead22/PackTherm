// Screen 1: set up a study.
import { useId, useState } from "react";
import { api, ApiError } from "../api";
import presets from "../generated/presets.json";
import { useServerCheck } from "../hooks";
import { CHOICE_LABELS } from "../labels";
import { formFromStudy, studyFromForm, toYaml, fileStem, type FormState, type Values } from "../study";
import type { Json, LibraryCell, Limits, Schema, Study } from "../types";
import { CellPicker } from "./CellPicker";
import { download } from "./download";
import { Field } from "./Fields";

interface Props {
  schema: Schema;
  limits: Limits;
  cells: Record<string, LibraryCell>;
  form: FormState;
  setForm: (f: FormState) => void;
  onSubmitted: (id: string) => void;
}

export function Setup({ schema, limits, cells, form, setForm, onSubmitted }: Props) {
  const id = useId();
  const update = (part: Partial<FormState>) => setForm({ ...form, ...part });
  const setIn = (section: "duty" | "requirements" | "design_space" | "options", k: string, v: Json) =>
    update({ [section]: { ...form[section], [k]: v } } as Partial<FormState>);
  const study = studyFromForm(form, schema);
  const check = useServerCheck<Study, Awaited<ReturnType<typeof api.checkStudy>>>(study, api.checkStudy);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<ApiError | null>(null);

  const type = String(form.duty.type);
  const dutyKeys = schema.duty.uses[type] ?? [];
  // Rest and pack size apply to every duty; show the duty's own keys first.
  const ordered = [
    ...Object.keys(schema.duty.keys).filter((k) => dutyKeys.includes(k) && !["rest_h", "pack_kWh"].includes(k)),
    "pack_kWh",
    "rest_h",
  ].filter((k) => dutyKeys.includes(k));
  const ds = form.design_space;
  const topologies = (ds.topologies as string[]) ?? [];
  const showDesign = (k: string) =>
    k === "air_flows_g_s"
      ? topologies.includes("air")
      : k === "coolant_flows_g_s" || k === "chiller_C"
        ? topologies.includes("bottom") || topologies.includes("ribbon")
        : true;

  const ready = check.state === "ok" && check.value.within_limits;
  const submit = async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const r = await api.submit(study);
      onSubmitted(r.id);
    } catch (e) {
      setSubmitError(e instanceof ApiError ? e : new ApiError(String(e), 0));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      className="setup"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready && !submitting) void submit();
      }}
    >
      <section className="card" aria-labelledby={`${id}-presets`}>
        <h2 id={`${id}-presets`}>Start from an example</h2>
        <p className="muted">The studies in the README, with the LG M50 cell. Each fills in the form below.</p>
        <div className="presets">
          {presets.map((p) => (
            <button
              key={p.file}
              type="button"
              className="button button--secondary"
              onClick={() => setForm(formFromStudy(schema, p.study as unknown as Record<string, Json>, form))}
            >
              {p.label}
            </button>
          ))}
        </div>
      </section>

      <section className="card" aria-labelledby={`${id}-study`}>
        <h2 id={`${id}-study`}>Study</h2>
        <div className="grid">
          <div className="field">
            <label htmlFor={`${id}-name`}>Study name</label>
            <input
              id={`${id}-name`}
              type="text"
              value={form.name}
              placeholder="Optional"
              onChange={(e) => update({ name: e.target.value })}
            />
          </div>
          <Field
            path="top.ambient_C"
            rule={schema.top.ambient_C}
            value={form.ambient_C}
            onChange={(v) => update({ ambient_C: v })}
          />
        </div>
        <fieldset className="field field--group">
          <legend>Mode</legend>
          <div className="segmented" role="radiogroup" aria-label="Mode">
            {(["fast", "normal"] as const).map((m) => (
              <label key={m} className={form.mode === m ? "on" : ""}>
                <input type="radio" name={`${id}-mode`} checked={form.mode === m} onChange={() => update({ mode: m })} />
                {CHOICE_LABELS[m]}
              </label>
            ))}
          </div>
          <p className="field__help">
            {form.mode === "fast"
              ? "About 5× quicker. In our checks, peak temperatures came within about 0.1 K of normal mode, with the same picks. Good for exploring."
              : "The reference resolution: slower, for final numbers."}
          </p>
        </fieldset>
      </section>

      <CellPicker schema={schema} cells={cells} form={form} update={update} />

      <section className="card" aria-labelledby={`${id}-duty`}>
        <h2 id={`${id}-duty`}>Duty</h2>
        <div className="grid">
          <Field
            path="duty.type"
            rule={schema.duty.keys.type}
            value={type}
            onChange={(v) => {
              const steps = form.duty.steps;
              // A custom duty starts with one segment to edit, rather than an error.
              const duty: Values = { ...form.duty, type: v };
              if (v === "segments" && !(Array.isArray(steps) && steps.length)) duty.steps = [[600, 1]];
              update({ duty });
            }}
          />
          {ordered
            .filter((k) => k !== "steps")
            .map((k) => (
              <Field
                key={k}
                path={`duty.${k}`}
                rule={schema.duty.keys[k]}
                value={form.duty[k] ?? null}
                onChange={(v) => setIn("duty", k, v)}
              />
            ))}
        </div>
        {dutyKeys.includes("steps") && (
          <Field
            path="duty.steps"
            rule={schema.duty.keys.steps}
            value={form.duty.steps ?? []}
            onChange={(v) => setIn("duty", "steps", v)}
          />
        )}
      </section>

      <section className="card" aria-labelledby={`${id}-req`}>
        <h2 id={`${id}-req`}>Limits</h2>
        <div className="grid">
          {Object.entries(schema.requirements).map(([k, r]) => (
            <Field
              key={k}
              path={`requirements.${k}`}
              rule={r}
              value={form.requirements[k] ?? null}
              onChange={(v) => setIn("requirements", k, v)}
            />
          ))}
        </div>
      </section>

      <section className="card" aria-labelledby={`${id}-ds`}>
        <h2 id={`${id}-ds`}>Designs to compare</h2>
        <p className="muted">Every combination is simulated.</p>
        <div className="grid">
          {Object.entries(schema.design_space)
            .filter(([k]) => showDesign(k))
            .map(([k, r]) => (
              <Field
                key={k}
                path={`design_space.${k}`}
                rule={r}
                value={ds[k] ?? null}
                onChange={(v) => setIn("design_space", k, v)}
              />
            ))}
        </div>
      </section>

      <details className="card">
        <summary>
          <h2>Advanced options</h2>
        </summary>
        <div className="grid">
          {Object.entries(schema.options).map(([k, r]) => (
            <Field
              key={k}
              path={`options.${k}`}
              rule={r}
              value={form.options[k] ?? null}
              onChange={(v) => setIn("options", k, v)}
            />
          ))}
        </div>
      </details>

      <div className="runbar" aria-live="polite">
        <StudyCheckView check={check} limits={limits} mode={form.mode} />
        {submitError && (
          <div className="notice notice--critical" role="alert">
            <p>
              <strong>{submitError.message}</strong>
              {submitError.retryAfterS !== undefined &&
                ` Try again in about ${Math.ceil(submitError.retryAfterS / 60)} min.`}
            </p>
            {submitError.problems.length > 0 && (
              <ul>
                {submitError.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="runbar__actions">
          <button
            type="button"
            className="button button--quiet"
            onClick={() => download(`${fileStem(study)}.yaml`, toYaml(study, YAML_HEAD), "application/yaml")}
          >
            Save as a study file
          </button>
          <button type="submit" className="button button--primary" disabled={!ready || submitting}>
            {submitting ? "Starting…" : "Run the study"}
          </button>
        </div>
      </div>
    </form>
  );
}

const YAML_HEAD = "PackTherm study, set up in the web app.\nRun it with: packtherm run <this file>";

function StudyCheckView({
  check,
  limits,
  mode,
}: {
  check: ReturnType<typeof useServerCheck<Study, Awaited<ReturnType<typeof api.checkStudy>>>>;
  limits: Limits;
  mode: string;
}) {
  const cap = mode === "fast" ? limits.max_designs_fast : limits.max_designs_normal;
  if (check.state === "idle" || check.state === "checking") return <p className="status">Checking the study…</p>;
  if (check.state === "error")
    return (
      <div className="notice notice--critical">
        <p>
          <strong>
            <span aria-hidden="true">✕ </span>
            {check.error.status === 422 ? "The study needs fixing:" : check.error.message}
          </strong>
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
  const c = check.value;
  if (!c.within_limits)
    return (
      <div className="notice notice--warning">
        <p>
          <strong>
            <span aria-hidden="true">! </span>Over the limits for this public server:
          </strong>
        </p>
        <ul>
          {c.problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
        <p className="muted">Remove some options, or save the study file and run it on your own machine.</p>
      </div>
    );
  return (
    <p className="status status--good">
      <span aria-hidden="true">✓ </span>
      {c.designs} design{c.designs === 1 ? "" : "s"} in {c.mode} mode (up to {cap} allowed).
    </p>
  );
}
