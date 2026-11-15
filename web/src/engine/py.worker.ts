/// <reference lib="webworker" />
// A Web Worker running PackTherm under Pyodide (Python compiled to WebAssembly).
// It answers {id, fn, args} messages by calling packtherm.browser.<fn>(...args).
import { PYODIDE_URL } from "./config";

type Msg = { id: number; fn: string; args: unknown[] };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mod: any = null;

async function init(wheelUrl: string): Promise<string> {
  const { loadPyodide } = await import(/* @vite-ignore */ `${PYODIDE_URL}pyodide.mjs`);
  const py = await loadPyodide({ indexURL: PYODIDE_URL });
  await py.loadPackage(["numpy", "scipy", "pandas", "pyyaml"]);
  const res = await fetch(wheelUrl);
  if (!res.ok) throw new Error(`could not load the PackTherm package (${res.status})`);
  py.unpackArchive(await res.arrayBuffer(), "wheel");
  mod = py.pyimport("packtherm.browser");
  return String(mod.version());
}

/**
 * What this worker downloaded: files fetched, bytes over the network, and bytes
 * that came from the browser's cache instead (a cache hit transfers nothing).
 */
function downloadStats(): string {
  const entries = performance.getEntriesByType("resource") as PerformanceResourceTiming[];
  let network = 0;
  let cached = 0;
  let unknown = 0;
  for (const e of entries) {
    if (e.transferSize > 0) network += e.transferSize;
    else if (e.encodedBodySize > 0) cached += e.encodedBodySize;
    else unknown += 1; // a cross-origin file without timing details
  }
  return JSON.stringify({ files: entries.length, network_bytes: network, cached_bytes: cached, unknown_files: unknown });
}

self.onmessage = async (e: MessageEvent<Msg>) => {
  const { id, fn, args } = e.data;
  try {
    const value =
      fn === "init" ? await init(String(args[0])) : fn === "stats" ? downloadStats() : String(mod[fn](...args));
    self.postMessage({ id, ok: true, value });
  } catch (err) {
    self.postMessage({ id, ok: false, error: err instanceof Error ? err.message : String(err) });
  }
};
