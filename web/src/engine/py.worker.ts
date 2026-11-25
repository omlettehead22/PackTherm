/// <reference lib="webworker" />
// A Web Worker running PackTherm under Pyodide (Python compiled to WebAssembly).
// It answers {id, fn, args} messages by calling packtherm.browser.<fn>(...args).
import { PYODIDE_URL, PYODIDE_VERSION } from "./config";

type Msg = { id: number; fn: string; args: unknown[] };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mod: any = null;

// The engine's files (Python, NumPy, SciPy, pandas: about 28 MB) are kept in the
// page's Cache Storage, which every worker and later visit share. The browser's
// own HTTP cache may not keep a file as large as SciPy's 14 MB package, and then
// each worker would download it again.
const CACHE = `packtherm-pyodide-${PYODIDE_VERSION}`;
const KEEP = /\.(whl|zip|wasm|tar|json)$/;

function cacheEngineFiles() {
  if (typeof caches === "undefined") return; // not a secure context: plain downloads
  const plainFetch = self.fetch.bind(self);
  self.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (!url.startsWith(PYODIDE_URL) || !KEEP.test(new URL(url).pathname)) return plainFetch(input, init);
    try {
      const cache = await caches.open(CACHE);
      const hit = await cache.match(url);
      if (hit) return hit;
      const res = await plainFetch(input, init);
      if (res.ok) await cache.put(url, res.clone());
      return res;
    } catch {
      return plainFetch(input, init); // storage full or refused: download as usual
    }
  };
  // Files from older Pyodide versions are no longer needed.
  void caches
    .keys()
    .then((names) => Promise.all(names.filter((n) => n.startsWith("packtherm-pyodide-") && n !== CACHE).map((n) => caches.delete(n))))
    .catch(() => {});
}

async function init(wheelUrls: string[]): Promise<string> {
  cacheEngineFiles();
  const { loadPyodide } = await import(/* @vite-ignore */ `${PYODIDE_URL}pyodide.mjs`);
  const py = await loadPyodide({ indexURL: PYODIDE_URL });
  await py.loadPackage(["numpy", "scipy", "pandas", "pyyaml"]);
  // PackTherm's wheel, then pure-Python dependencies served beside it (ht and fluids since v0.6.12).
  for (const url of wheelUrls) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`could not load the PackTherm package (${res.status})`);
    py.unpackArchive(await res.arrayBuffer(), "wheel");
  }
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
  const fetched: [string, number][] = [];
  for (const e of entries) {
    if (e.transferSize > 0) fetched.push([e.name.split("/").pop() ?? e.name, e.transferSize]);
    if (e.transferSize > 0) network += e.transferSize;
    else if (e.encodedBodySize > 0) cached += e.encodedBodySize;
    else unknown += 1; // a cross-origin file without timing details
  }
  const largest = fetched.sort((x, y) => y[1] - x[1]).slice(0, 8);
  return JSON.stringify({
    files: entries.length,
    network_bytes: network,
    cached_bytes: cached,
    unknown_files: unknown,
    largest_downloads: largest.map(([n, b]) => `${n} ${(b / 1e6).toFixed(1)} MB`),
    initiators: [...new Set(entries.filter((e) => e.transferSize > 0).map((e) => e.initiatorType))],
  });
}

self.onmessage = async (e: MessageEvent<Msg>) => {
  const { id, fn, args } = e.data;
  try {
    const value =
      fn === "init" ? await init(args.map(String)) : fn === "stats" ? downloadStats() : String(mod[fn](...args));
    self.postMessage({ id, ok: true, value });
  } catch (err) {
    self.postMessage({ id, ok: false, error: err instanceof Error ? err.message : String(err) });
  }
};
