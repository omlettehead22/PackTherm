// Screens 2 and 3: a submitted study, while it runs and once it is done.
import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { JobStatus, Limits, Results as ResultsDoc } from "../types";
import { Results } from "./Results";

interface Props {
  id: string;
  limits: Limits;
  onEdit: (study: ResultsDoc["study"]) => void;
  onNew: () => void;
}

const POLL_MS = 1500;

export function StudyPage({ id, limits, onEdit, onNew }: Props) {
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [results, setResults] = useState<ResultsDoc | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [cancelling, setCancelling] = useState(false);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    setStatus(null);
    setResults(null);
    setError(null);
    const tick = async () => {
      try {
        const s = await api.status(id);
        if (stop) return;
        setStatus(s);
        if (s.state === "done") {
          const r = await api.results(id);
          if (!stop) setResults(r);
          return;
        }
        if (s.state === "queued" || s.state === "running") timer = setTimeout(tick, POLL_MS);
      } catch (e) {
        if (stop) return;
        const err = e instanceof ApiError ? e : new ApiError(String(e), 0);
        if (err.status === 0) timer = setTimeout(tick, POLL_MS * 3); // a dropped connection: keep trying
        setError(err);
      }
    };
    void tick();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [id]);

  if (results) return (
      <Results
        source={{ kind: "server", id, finished: status?.finished ?? null, keepH: limits.keep_h }}
        results={results}
        onEdit={onEdit}
        onNew={onNew}
      />
    );

  if (error && error.status !== 0)
    return (
      <section className="card">
        <h2>Study not found</h2>
        <p>{error.message}</p>
        <p className="muted">Results are kept for {limits.keep_h} hours after a study finishes.</p>
        <button type="button" className="button button--primary" onClick={onNew}>
          Set up a new study
        </button>
      </section>
    );

  if (status?.state === "failed" || status?.state === "cancelled")
    return (
      <section className="card">
        <h2>{status.state === "failed" ? "The study failed" : "The study was cancelled"}</h2>
        {status.error && <pre className="error-text">{firstLine(status.error)}</pre>}
        <button type="button" className="button button--primary" onClick={onNew}>
          Set up a new study
        </button>
      </section>
    );

  return (
    <Running
      status={status}
      reconnecting={error?.status === 0}
      cancelling={cancelling}
      onCancel={async () => {
        setCancelling(true);
        try {
          await api.cancel(id);
          setStatus(await api.status(id));
        } catch (e) {
          setError(e instanceof ApiError ? e : new ApiError(String(e), 0));
        } finally {
          setCancelling(false);
        }
      }}
    />
  );
}

const firstLine = (s: string) => s.split("\n\n")[0];

export function Running(props: {
  status: JobStatus | null;
  reconnecting: boolean;
  cancelling: boolean;
  onCancel: () => void;
}) {
  const s = props.status;
  const p = s?.progress;
  const stage = !s
    ? "Connecting…"
    : s.state === "queued"
      ? `Waiting to start: ${s.queue_position ?? "?"} in the queue`
      : !p
        ? "Starting…"
        : p.stage === "designs"
          ? `Simulating designs: ${p.done} of ${p.total}`
          : `Re-checking the picks at worst-case resistance: ${p.done} of ${p.total}`;
  const frac = p && p.total ? p.done / p.total : 0;
  // Designs are most of the work; the re-check is a short last step.
  const overall = !p ? 0 : p.stage === "designs" ? 0.9 * frac : 0.9 + 0.1 * frac;
  return (
    <section className="card running" aria-labelledby="running-h">
      <h2 id="running-h">Running the study</h2>
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
        <div className="progress__bar" style={{ width: `${overall * 100}%` }} />
      </div>
      <p className="muted">
        {s?.eta_s !== undefined ? `About ${formatDuration(s.eta_s)} left. ` : ""}
        {props.reconnecting ? "Lost the connection; retrying…" : "You can leave this page: the link keeps working."}
      </p>
      <button type="button" className="button button--secondary" onClick={props.onCancel} disabled={props.cancelling}>
        {props.cancelling ? "Cancelling…" : "Cancel the study"}
      </button>
    </section>
  );
}

export function formatDuration(s: number): string {
  if (s < 60) return `${Math.max(1, Math.round(s))} s`;
  const m = Math.round(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}
