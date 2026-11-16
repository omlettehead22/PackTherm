// The in-browser engine: PackTherm running under Pyodide in a pool of Web
// Workers. One worker answers checks; a study's designs are spread over all
// of them, then the first one assembles the results (packtherm.browser).
import { ApiError } from "../api";
import type { CellCheck, Results, Study, StudyCheck } from "../types";
import { WHEEL_MANIFEST } from "./config";

export type EngineState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "ready"; version: string }
  | { phase: "failed"; message: string };

export type RunProgress =
  | { stage: "loading"; workers: number }
  | { stage: "designs" | "re-check"; done: number; total: number; etaS?: number };

class PyWorker {
  private worker: Worker;
  private next = 1;
  private pending = new Map<number, { resolve: (v: string) => void; reject: (e: Error) => void }>();
  readonly ready: Promise<string>;

  constructor(wheelUrl: string) {
    this.worker = new Worker(new URL("./py.worker.ts", import.meta.url), { type: "module" });
    this.worker.onmessage = (e: MessageEvent<{ id: number; ok: boolean; value?: string; error?: string }>) => {
      const p = this.pending.get(e.data.id);
      if (!p) return;
      this.pending.delete(e.data.id);
      if (e.data.ok) p.resolve(e.data.value ?? "");
      else p.reject(new Error(e.data.error ?? "the engine failed"));
    };
    this.worker.onerror = (e) => {
      for (const p of this.pending.values()) p.reject(new Error(e.message || "the engine stopped"));
      this.pending.clear();
    };
    this.ready = this.call("init", [wheelUrl]);
  }

  call(fn: string, args: unknown[]): Promise<string> {
    const id = this.next++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.worker.postMessage({ id, fn, args });
    });
  }

  terminate() {
    this.worker.terminate();
    for (const p of this.pending.values()) p.reject(new DOMException("Cancelled", "AbortError"));
    this.pending.clear();
  }
}

type Answer<T> = ({ ok: true } & T) | { ok: false; error: string; errors: string[] };

const parse = <T>(text: string): T => {
  const a = JSON.parse(text) as Answer<T>;
  if (!a.ok) throw new ApiError(a.error, 422, a.errors);
  return a as T;
};

/** How many workers to run designs on: one per core, leaving one for the page, at most 4 (memory). */
export function poolSize(cores = navigator.hardwareConcurrency || 2): number {
  return Math.max(1, Math.min(4, cores - 1));
}

export class BrowserEngine {
  readonly kind = "browser" as const;
  private main: PyWorker | null = null;
  private extra: PyWorker[] = [];
  private wheel: Promise<string> | null = null;
  private state: EngineState = { phase: "idle" };
  private listeners = new Set<(s: EngineState) => void>();

  getState = () => this.state;

  subscribe(fn: (s: EngineState) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private set(s: EngineState) {
    this.state = s;
    for (const fn of this.listeners) fn(s);
  }

  private wheelUrl(): Promise<string> {
    this.wheel ??= fetch(WHEEL_MANIFEST)
      .then((r) => {
        if (!r.ok) throw new Error(`no engine package here (${r.status})`);
        return r.json() as Promise<{ wheel: string }>;
      })
      .then((m) => new URL(m.wheel, new URL(WHEEL_MANIFEST, window.location.href)).href)
      .catch((e: unknown) => {
        this.wheel = null; // try again next time
        throw e;
      });
    return this.wheel;
  }

  /** Start the first worker (downloads Python and PackTherm on a first visit). */
  async start(): Promise<PyWorker> {
    try {
      return await this.startWorker();
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") throw e;
      // What a visitor can act on; the cause stays in the header's details.
      throw new ApiError(LOAD_FAILED, 0);
    }
  }

  private async startWorker(): Promise<PyWorker> {
    if (!this.main) {
      this.set({ phase: "loading" });
      const url = await this.wheelUrl().catch((e: Error) => {
        this.set({ phase: "failed", message: e.message });
        throw e;
      });
      const w = new PyWorker(url);
      this.main = w;
      // Only this worker's outcome counts: a cancelled one was replaced or stopped on purpose.
      w.ready.then(
        (version) => this.main === w && this.set({ phase: "ready", version }),
        (e: Error) => {
          if (this.main !== w) return;
          this.main = null;
          this.set({ phase: "failed", message: e.message });
        },
      );
    }
    await this.main.ready;
    return this.main;
  }

  async checkCell(cell: unknown): Promise<CellCheck> {
    const w = await this.start();
    return parse<CellCheck>(await w.call("check_cell", [JSON.stringify(cell)]));
  }

  async checkStudy(study: Study): Promise<StudyCheck> {
    const w = await this.start();
    return parse<StudyCheck>(await w.call("check_study", [JSON.stringify(study)]));
  }

  /** What each running worker downloaded (diagnostics: the end-to-end check reports it). */
  async downloadStats(): Promise<unknown[]> {
    const pool = [this.main, ...this.extra].filter((w): w is PyWorker => w !== null);
    return Promise.all(pool.map(async (w) => JSON.parse(await w.call("stats", [])) as unknown));
  }

  /** Run a study across the pool. Rejects with an AbortError if cancelled. */
  async run(study: Study, progress: (p: RunProgress) => void, signal: AbortSignal): Promise<Results> {
    const doc = JSON.stringify(study);
    const size = poolSize();
    const onAbort = () => this.stopAll();
    signal.addEventListener("abort", onAbort);
    try {
      progress({ stage: "loading", workers: size });
      if (signal.aborted) throw new DOMException("Cancelled", "AbortError");
      const main = await this.start();
      const url = await this.wheelUrl();
      while (this.extra.length < size - 1) this.extra.push(new PyWorker(url));
      // A worker that fails to load is left out rather than failing the run.
      const loaded = await Promise.allSettled(this.extra.map((w) => w.ready));
      this.extra = this.extra.filter((_, i) => loaded[i].status === "fulfilled");
      const pool = [main, ...this.extra];
      if (signal.aborted) throw new DOMException("Cancelled", "AbortError");

      const { designs: n } = parse<StudyCheck>(await main.call("check_study", [doc]));
      const t0 = performance.now();
      const rows = await this.spread(pool, n, (i) => ["evaluate", [doc, i, false]], (done) => {
        const per = (performance.now() - t0) / 1000 / done;
        progress({ stage: "designs", done, total: n, etaS: per * (n - done) });
      }, signal);

      const rechecks: Record<string, string> = {};
      for (;;) {
        const elapsed = (performance.now() - t0) / 1000;
        const out = parse<{ need?: number[]; results?: Results }>(
          await main.call("finish", [doc, JSON.stringify(rows), JSON.stringify(rechecks), elapsed]),
        );
        if (out.results) return out.results;
        const need = out.need ?? [];
        const got = await this.spread(pool, need.length, (k) => ["evaluate", [doc, need[k], true]], (done) =>
          progress({ stage: "re-check", done, total: need.length }), signal);
        need.forEach((i, k) => (rechecks[String(i)] = got[k]));
      }
    } finally {
      signal.removeEventListener("abort", onAbort);
    }
  }

  /** Jobs 0..n-1 over the pool, each worker taking the next job as it frees up; results in order. */
  private async spread(
    pool: PyWorker[],
    n: number,
    job: (k: number) => [string, unknown[]],
    onDone: (done: number) => void,
    signal: AbortSignal,
  ): Promise<string[]> {
    const out = new Array<string>(n);
    let nextJob = 0;
    let done = 0;
    await Promise.all(
      pool.map(async (w) => {
        while (nextJob < n) {
          if (signal.aborted) throw new DOMException("Cancelled", "AbortError");
          const k = nextJob++;
          const [fn, args] = job(k);
          out[k] = await w.call(fn, args);
          onDone(++done);
        }
      }),
    );
    return out;
  }

  /** Cancel: stop every worker. The next check or run starts fresh ones (from the browser's cache). */
  private stopAll() {
    this.main?.terminate();
    for (const w of this.extra) w.terminate();
    this.main = null;
    this.extra = [];
    this.set({ phase: "idle" });
  }
}

export const LOAD_FAILED =
  "The simulation engine could not load. Check your internet connection, then reload the page. (It needs a recent Chrome, Edge, Firefox or Safari.)";

export const browserEngine = new BrowserEngine();
