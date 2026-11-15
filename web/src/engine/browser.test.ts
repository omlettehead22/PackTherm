// The in-browser engine's scheduling, with a stand-in for the Pyodide worker:
// designs spread over the pool, then the finish / re-check loop. (The real
// worker, Pyodide and packtherm.browser are checked end to end in CI.)
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BrowserEngine, poolSize } from "./browser";

const calls: { worker: number; fn: string; args: unknown[] }[] = [];
let workers = 0;

class FakeWorker {
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: ErrorEvent) => void) | null = null;
  n = ++workers;
  terminated = false;
  postMessage({ id, fn, args }: { id: number; fn: string; args: unknown[] }) {
    calls.push({ worker: this.n, fn, args });
    let value: string;
    if (fn === "init") value = "0.5.6";
    else if (fn === "check_study") value = JSON.stringify({ ok: true, designs: 5, mode: "fast", within_limits: true, problems: [] });
    else if (fn === "evaluate") value = `row${args[1]}${args[2] ? "-worst" : ""}`;
    else if (fn === "finish") {
      const rechecks = JSON.parse(String(args[2])) as Record<string, string>;
      value = Object.keys(rechecks).length
        ? JSON.stringify({ ok: true, results: { rows: JSON.parse(String(args[1])), rechecks } })
        : JSON.stringify({ ok: true, need: [3, 1] });
    } else value = JSON.stringify({ ok: false, error: "unknown", errors: [] });
    setTimeout(() => this.onmessage?.({ data: { id, ok: true, value } } as MessageEvent), 1);
  }
  terminate() {
    this.terminated = true;
  }
}

beforeEach(() => {
  calls.length = 0;
  workers = 0;
  vi.stubGlobal("Worker", FakeWorker);
  vi.stubGlobal("navigator", { hardwareConcurrency: 4 });
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ wheel: "packtherm-0.5.6-py3-none-any.whl" }))),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("the in-browser engine", () => {
  it("uses a worker per core, leaving one for the page, up to four", () => {
    expect([1, 2, 4, 8, 16].map(poolSize)).toEqual([1, 1, 3, 4, 4]);
  });

  it("spreads the designs over the pool, then re-checks what finish asks for", async () => {
    const engine = new BrowserEngine();
    const seen: string[] = [];
    const out = (await engine.run(
      { packtherm_study: 1, cell: "M50", duty: { type: "constant" } },
      (p) => seen.push(p.stage === "loading" ? "loading" : `${p.stage} ${p.done}/${p.total}`),
      new AbortController().signal,
    )) as unknown as { rows: string[]; rechecks: Record<string, string> };
    expect(out.rows).toEqual(["row0", "row1", "row2", "row3", "row4"]); // in design order
    expect(out.rechecks).toEqual({ "3": "row3-worst", "1": "row1-worst" });
    const evaluated = calls.filter((c) => c.fn === "evaluate" && c.args[2] === false);
    expect(new Set(evaluated.map((c) => c.worker)).size).toBe(3); // all three workers took designs
    expect(seen[0]).toBe("loading");
    expect(seen).toContain("designs 5/5");
    expect(seen).toContain("re-check 2/2");
  });

  it("turns a Python-side error into a message with its field errors", async () => {
    const engine = new BrowserEngine();
    const w = FakeWorker.prototype.postMessage;
    FakeWorker.prototype.postMessage = function (this: FakeWorker, m) {
      if (m.fn === "check_cell") {
        const value = JSON.stringify({ ok: false, error: "Invalid cell", errors: ["mass_g: in kg?"] });
        setTimeout(() => this.onmessage?.({ data: { id: m.id, ok: true, value } } as MessageEvent), 1);
      } else w.call(this, m);
    };
    await expect(engine.checkCell({})).rejects.toMatchObject({ message: "Invalid cell", problems: ["mass_g: in kg?"] });
    FakeWorker.prototype.postMessage = w;
  });

  it("stops every worker when cancelled", async () => {
    const engine = new BrowserEngine();
    const ctl = new AbortController();
    const run = engine.run({ packtherm_study: 1, cell: "M50", duty: { type: "constant" } }, () => ctl.abort(), ctl.signal);
    await expect(run).rejects.toMatchObject({ name: "AbortError" });
    expect(engine.getState().phase).toBe("idle");
  });
});
