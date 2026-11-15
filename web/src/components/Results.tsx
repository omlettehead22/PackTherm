// Screen 3: a finished study's results.
import { useId, useMemo, useState } from "react";
import { api } from "../api";
import { failWords, PICK_LABEL, pickNumbers, TradeoffChart } from "../chart/TradeoffChart";
import { fileStem, toYaml } from "../study";
import { studyLink } from "../share";
import type { Design, Pick, Results as ResultsDoc } from "../types";
import { designsCsv, download } from "./download";

/** Where the results came from, which decides how they are downloaded and shared. */
export type ResultsSource =
  /** A study run by the PackTherm server: its files are on the server for keepH hours after it finished. */
  | { kind: "server"; id: string; finished: number | null; keepH: number }
  /** A study run in this browser, or a results file opened here. */
  | { kind: "browser" | "file" };

interface Props {
  source: ResultsSource;
  results: ResultsDoc;
  onEdit: (study: ResultsDoc["study"]) => void;
  onNew: () => void;
}

// Older results files (before 0.5.5) carry no labels; these are the module study's.
const FALLBACK_LABELS = {
  mass_axis: "Mass added per cell (filler + cooling hardware), % of cell mass",
  energy_axis: "Fan, pump and chiller energy, % of energy moved by the cell",
  filler: "Filler between the cans",
  kinds: { natural: "no cooling", air: "forced air", liquid: "liquid" } as Record<string, string>,
};

export function Results({ source, results, onEdit, onNew }: Props) {
  const [active, setActive] = useState<number | null>(null);
  const labels = results.labels ?? FALLBACK_LABELS;
  const s = results.summary;
  const fast = s.mode === "fast";
  const userCell = (s.cell_model ?? "").startsWith("user-defined");

  return (
    <div className="results">
      <section className="card">
        <h2>{typeof results.study.name === "string" ? results.study.name : "Study results"}</h2>
        <p className="lede">
          {s.cell}, {s.duty}, ambient {String(results.study.ambient_C ?? 25)} °C.
        </p>
        <p>
          <strong>{s.designs}</strong> designs simulated, <strong>{s.feasible}</strong> meet the limits
          {s.T_limit_C !== null && ` (peak ≤ ${s.T_limit_C} °C)`}, <strong>{s.on_front}</strong> on the trade-off
          front. Took {results.elapsed_s.toFixed(0)} s.
        </p>
        <ul className="tags" aria-label="How these results were made">
          <li className={fast ? "tag tag--note" : "tag"}>{fast ? "Fast mode" : "Normal mode"}</li>
          {s.cell_model && <li className={userCell ? "tag tag--note" : "tag"}>Cell model: {s.cell_model}</li>}
          <li className="tag">PackTherm {results.packtherm_version}</li>
        </ul>
        {fast && (
          <p className="muted">
            Fast mode: in our checks, peaks came within about 0.1 K of normal mode. Re-run in normal mode for final numbers.
          </p>
        )}
      </section>

      {results.picks.length > 0 ? (
        <PickCards picks={results.picks} designs={results.designs} />
      ) : (
        <section className="notice notice--critical" role="status">
          <p>
            <strong>No design meets the limits.</strong> See the notes below for the closest one, and try more cooling,
            a filler, or looser limits.
          </p>
        </section>
      )}

      <section className="card">
        <TradeoffChart
          designs={results.designs}
          picks={results.picks}
          kindNames={labels.kinds}
          xLabel={labels.mass_axis}
          yLabel={labels.energy_axis}
          active={active}
          setActive={setActive}
        />
      </section>

      <DesignTable designs={results.designs} picks={results.picks} active={active} setActive={setActive} />

      {results.notes.length > 0 && (
        <section className="card">
          <h2>Notes</h2>
          <ul className="notes">
            {results.notes.map((n) => {
              const warn = n.startsWith("WARNING");
              return (
                <li key={n} className={warn ? "note note--warning" : "note"}>
                  <span className="note__tag">{warn ? "Warning" : "Note"}</span> {n.replace(/^(WARNING|NOTE):\s*/, "")}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <section className="card">
        <h2>Download and share</h2>
        <div className="downloads">
          {source.kind === "server" ? (
            <>
              <a className="button button--secondary" href={api.resultsUrl(source.id)} download>
                Results (JSON)
              </a>
              <a className="button button--secondary" href={api.csvUrl(source.id)} download>
                Every design (CSV)
              </a>
              <a className="button button--secondary" href={api.chartUrl(source.id)} download>
                Chart (PNG)
              </a>
            </>
          ) : (
            <>
              <button
                type="button"
                className="button button--secondary"
                onClick={() =>
                  download(`${fileStem(results.study)}_results.json`, JSON.stringify(results, null, 1), "application/json")
                }
              >
                Results (JSON)
              </button>
              <button
                type="button"
                className="button button--secondary"
                onClick={() => download(`${fileStem(results.study)}_designs.csv`, designsCsv(results.designs), "text/csv")}
              >
                Every design (CSV)
              </button>
            </>
          )}
          <button
            type="button"
            className="button button--secondary"
            onClick={() =>
              download(
                `${fileStem(results.study)}.yaml`,
                toYaml(results.study, "PackTherm study, as run (every default filled in).\nRun it with: packtherm run <this file>"),
                "application/yaml",
              )
            }
          >
            Study file (YAML)
          </button>
        </div>
        {source.kind === "server" ? (
          <ShareLink
            link={`${window.location.origin}${window.location.pathname}#/studies/${source.id}`}
            help={`Works until ${new Date(((source.finished ?? Date.now() / 1000) + source.keepH * 3600) * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}, then the results are deleted. Download them to keep them.`}
          />
        ) : (
          <ShareLink
            link={studyLink(results.study)}
            help="Opens this study, set up and ready to run in the browser of whoever opens it. To share these exact numbers, send the results file: the app opens it."
          />
        )}
        <div className="runbar__actions">
          <button type="button" className="button button--quiet" onClick={onNew}>
            New study
          </button>
          <button type="button" className="button button--primary" onClick={() => onEdit(results.study)}>
            Change this study and run again
          </button>
        </div>
      </section>
    </div>
  );
}

function ShareLink({ link, help }: { link: string; help: string }) {
  const id = useId();
  const [copied, setCopied] = useState(false);
  return (
    <div className="field share">
      <label htmlFor={id}>Link to share</label>
      <div className="share__row">
        <input id={id} type="text" readOnly value={link} onFocus={(e) => e.target.select()} />
        <button
          type="button"
          className="button button--secondary"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(link);
              setCopied(true);
              setTimeout(() => setCopied(false), 2000);
            } catch {
              /* the field is selectable as a fallback */
            }
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <p className="field__help">{help}</p>
    </div>
  );
}

const fmt = (v: unknown, d = 1) => (typeof v === "number" ? v.toFixed(d) : "–");

/** One card per design: a design that is two picks (often lightest and balanced) gets one card with both names. */
function PickCards({ picks, designs }: { picks: Pick[]; designs: Design[] }) {
  const numbers = pickNumbers(designs, picks);
  const cards: { p: Pick; names: string[] }[] = [];
  for (const p of picks) {
    const same = cards.find((c) => c.p.design === p.design);
    if (same) same.names.push(PICK_LABEL[p.pick] ?? p.pick);
    else cards.push({ p, names: [PICK_LABEL[p.pick] ?? p.pick] });
  }
  return (
    <section aria-label="Recommended designs" className="picks">
      {cards.map(({ p, names }) => {
        const n = numbers.get(designs.findIndex((d) => d.design === p.design))?.n;
        return (
          <article key={p.pick} className="pick-card">
            <p className="pick-card__kicker">
              {n !== undefined && <span className="badge">{n}</span>} {names.join(" and ")}
            </p>
            <h3>{p.design}</h3>
            <dl className="pick-card__nums">
              <div>
                <dt>Peak</dt>
                <dd>{fmt(p.T_peak_C)} °C</dd>
              </div>
              <div>
                <dt>Mass added</dt>
                <dd>+{fmt(p.mass_overhead_pct)} %</dd>
              </div>
              <div>
                <dt>Running energy</dt>
                <dd>{fmt(p.aux_energy_pct, 2)} %</dd>
              </div>
              <div>
                <dt>Ready again in</dt>
                <dd>{typeof p.recovery_min === "number" ? `${p.recovery_min.toFixed(0)} min` : "–"}</dd>
              </div>
            </dl>
            {p.robust === false && (
              <p className="pick-card__warn">
                <span aria-hidden="true">! </span>Fails at worst-case resistance
                {typeof p.T_peak_worst_C === "number" ? ` (${p.T_peak_worst_C.toFixed(1)} °C)` : ""}.
              </p>
            )}
            {p.robust === true && (
              <p className="pick-card__ok">
                <span aria-hidden="true">✓ </span>Still passes at worst-case resistance.
              </p>
            )}
          </article>
        );
      })}
    </section>
  );
}

type SortKey = "design" | "T_peak_C" | "dT_cell_C" | "cell_to_cell_K" | "recovery_min" | "mass_overhead_pct" | "aux_energy_pct" | "feasible";

const COLUMNS: { key: SortKey; label: string; unit?: string; digits?: number }[] = [
  { key: "design", label: "Design" },
  { key: "T_peak_C", label: "Peak", unit: "°C" },
  { key: "dT_cell_C", label: "In-cell spread", unit: "°C", digits: 2 },
  { key: "cell_to_cell_K", label: "Cell to cell", unit: "K" },
  { key: "recovery_min", label: "Ready again", unit: "min", digits: 0 },
  { key: "mass_overhead_pct", label: "Mass added", unit: "%" },
  { key: "aux_energy_pct", label: "Running energy", unit: "%", digits: 2 },
  { key: "feasible", label: "Result" },
];

type Filter = "all" | "feasible" | "front";

export function DesignTable({
  designs,
  picks,
  active,
  setActive,
}: {
  designs: Design[];
  picks: Pick[];
  active: number | null;
  setActive: (i: number | null) => void;
}) {
  const id = useId();
  const [sort, setSort] = useState<{ key: SortKey; asc: boolean }>({ key: "mass_overhead_pct", asc: true });
  const [filter, setFilter] = useState<Filter>("all");
  const numbers = pickNumbers(designs, picks);
  const rows = useMemo(() => {
    const r = designs
      .map((d, i) => ({ d, i }))
      .filter(({ d }) => filter === "all" || (filter === "feasible" ? d.feasible : d.pareto && d.feasible));
    const val = (d: Design) => d[sort.key];
    r.sort((a, b) => {
      const x = val(a.d);
      const y = val(b.d);
      if (x === y) return 0;
      if (x === null || x === undefined) return 1; // blanks last either way
      if (y === null || y === undefined) return -1;
      const c = typeof x === "string" ? x.localeCompare(String(y)) : Number(x) - Number(y);
      return sort.asc ? c : -c;
    });
    return r;
  }, [designs, sort, filter]);

  return (
    <section className="card" aria-labelledby={`${id}-h`}>
      <div className="table-head">
        <h2 id={`${id}-h`}>Every design</h2>
        <div className="segmented" role="radiogroup" aria-label="Show">
          {(
            [
              ["all", `All (${designs.length})`],
              ["feasible", `Meet the limits (${designs.filter((d) => d.feasible).length})`],
              ["front", "On the front"],
            ] as [Filter, string][]
          ).map(([f, text]) => (
            <label key={f} className={filter === f ? "on" : ""}>
              <input type="radio" name={`${id}-filter`} checked={filter === f} onChange={() => setFilter(f)} />
              {text}
            </label>
          ))}
        </div>
      </div>
      <div className="table-scroll">
        <table className="designs">
          <thead>
            <tr>
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={sort.key === c.key ? (sort.asc ? "ascending" : "descending") : undefined}
                  className={c.key === "design" || c.key === "feasible" ? "" : "num"}
                >
                  <button
                    type="button"
                    onClick={() => setSort((s) => ({ key: c.key, asc: s.key === c.key ? !s.asc : true }))}
                  >
                    {c.label}
                    {c.unit && <span className="unit"> {c.unit}</span>}
                    <span aria-hidden="true" className="sort">
                      {sort.key === c.key ? (sort.asc ? " ▲" : " ▼") : ""}
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ d, i }) => (
              <tr
                key={i}
                className={(active === i ? "active " : "") + (d.feasible ? "" : "failed")}
                onMouseEnter={() => setActive(i)}
                onMouseLeave={() => setActive(null)}
              >
                <th scope="row">
                  {numbers.has(i) && <span className="badge">{numbers.get(i)!.n}</span>} {d.design}
                </th>
                {COLUMNS.slice(1, -1).map((c) => (
                  <td key={c.key} className="num">
                    {fmt(d[c.key], c.digits ?? 1)}
                  </td>
                ))}
                <td>
                  {d.feasible ? (
                    <span className="ok">
                      <span aria-hidden="true">✓ </span>Meets
                    </span>
                  ) : (
                    <span className="bad">
                      <span aria-hidden="true">✕ </span>
                      {failWords(d.fail_reason)}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
