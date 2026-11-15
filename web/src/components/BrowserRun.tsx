// Screens 2 and 3 with the in-browser engine: the study runs in this page.
import { useEffect, useRef, useState } from "react";
import { browserEngine, type RunProgress } from "../engine/browser";
import type { Results as ResultsDoc, Study } from "../types";
import { Results } from "./Results";
import { formatDuration } from "./StudyPage";

interface Props {
  study: Study;
  onEdit: (study: ResultsDoc["study"]) => void;
  onNew: () => void;
}

export function BrowserRun({ study, onEdit, onNew }: Props) {
  const [progress, setProgress] = useState<RunProgress | null>(null);
  const [results, setResults] = useState<ResultsDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelled, setCancelled] = useState(false);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    abort.current = ctl;
    let running = true;
    browserEngine
      .run(study, setProgress, ctl.signal)
      .then((r) => !ctl.signal.aborted && setResults(r))
      .catch((e: unknown) => {
        if (ctl.signal.aborted) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => (running = false));
    // Leaving the page stops a run still going; finished, the workers stay warm for the next one.
    return () => {
      if (running) ctl.abort();
    };
  }, [study]);

  if (results) return <Results source={{ kind: "browser" }} results={results} onEdit={onEdit} onNew={onNew} />;

  if (error || cancelled)
    return (
      <section className="card">
        <h2>{cancelled ? "The study was cancelled" : "The study failed"}</h2>
        {error && <pre className="error-text">{error.split("\n").slice(-3).join("\n")}</pre>}
        <div className="runbar__actions">
          <button type="button" className="button button--secondary" onClick={() => onEdit(study as never)}>
            Back to the study
          </button>
        </div>
      </section>
    );

  const p = progress;
  const stage = !p
    ? "Starting…"
    : p.stage === "loading"
      ? `Loading the simulation engine on ${p.workers} worker${p.workers === 1 ? "" : "s"}. A first visit downloads Python and PackTherm; later visits load them from your browser's cache.`
      : p.stage === "designs"
        ? `Simulating designs: ${p.done} of ${p.total}`
        : `Re-checking the picks at worst-case resistance: ${p.done} of ${p.total}`;
  const frac = p && p.stage !== "loading" && p.total ? p.done / p.total : 0;
  const overall = !p || p.stage === "loading" ? 0 : p.stage === "designs" ? 0.9 * frac : 0.9 + 0.1 * frac;
  const eta = p && p.stage === "designs" && p.done > 0 ? p.etaS : undefined;
  return (
    <section className="card running" aria-labelledby="running-h">
      <h2 id="running-h">Running the study in your browser</h2>
      <p className="status" aria-live="polite">
        {stage}
      </p>
      <div
        className="progress"
        role="progressbar"
        aria-label="Study progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(overall * 100)}
      >
        <div className={"progress__bar" + (p?.stage === "loading" ? " progress__bar--busy" : "")} style={{ width: p?.stage === "loading" ? "100%" : `${overall * 100}%` }} />
      </div>
      <p className="muted">
        {eta !== undefined ? `About ${formatDuration(eta)} left. ` : ""}
        Keep this tab open: the study runs on this computer.
      </p>
      <button
        type="button"
        className="button button--secondary"
        onClick={() => {
          abort.current?.abort();
          setCancelled(true);
        }}
      >
        Cancel the study
      </button>
    </section>
  );
}
