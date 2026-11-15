// End-to-end check of the public site's in-browser engine, in headless Chromium:
//   1. load the site and wait for Pyodide + PackTherm to start;
//   2. run a small study (opened from a share link) and save its results file,
//      which e2e/compare.py checks against `packtherm run`;
//   3. time the hot road-trip example (39 designs, fast mode) and record how
//      much was downloaded, for the step summary.
// Usage: node e2e/browser-engine.mjs <site dir> <out dir>   (site dir from build_pages.py)
import { spawn } from "node:child_process";
import { cpSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { chromium } from "playwright";

const [site, outDir] = process.argv.slice(2).map((p) => resolve(p));
mkdirSync(outDir, { recursive: true });
const root = join(tmpdir(), "packtherm-site");
rmSync(root, { recursive: true, force: true });
cpSync(site, join(root, "PackTherm"), { recursive: true }); // as GitHub serves it
const server = spawn("python3", ["-m", "http.server", "8123", "--bind", "127.0.0.1", "--directory", root], { stdio: "ignore" });
await new Promise((r) => setTimeout(r, 1500));
const URL0 = "http://127.0.0.1:8123/PackTherm/";

// The small study of tests/test_browser.py: three designs, with a worst-case re-check.
const STUDY = {
  packtherm_study: 1, cell: "M50", mode: "fast", ambient_C: 25,
  duty: { type: "constant", c_rate: 1.0, rest_h: 1 },
  design_space: { topologies: ["air", "ribbon"], fillers: ["none", "RT31"], air_flows_g_s: [0.3], coolant_flows_g_s: [0.03], chiller_C: [] },
};
const enc = Buffer.from(JSON.stringify(STUDY)).toString("base64url");

const log = [];
const say = (s) => { console.log(s); log.push(s); };
const browser = await chromium.launch();
const context = await browser.newContext({ acceptDownloads: true });
let bytes = 0;
context.on("requestfinished", async (req) => {
  try { bytes += (await req.sizes()).responseBodySize; } catch { /* ignore */ }
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

try {
  let t = Date.now();
  await page.goto(`${URL0}#/study/${enc}`);
  await page.getByText(/Engine ready/).waitFor({ timeout: 600_000 });
  say(`Engine ready (first load, one worker): ${((Date.now() - t) / 1000).toFixed(1)} s; downloaded ${(bytes / 1e6).toFixed(1)} MB`);
  const firstLoad = bytes;

  const run = page.getByRole("button", { name: "Run the study" });
  await page.getByText(/\d+ designs? in fast mode/).waitFor({ timeout: 120_000 });
  t = Date.now();
  await run.click();
  await page.getByRole("heading", { name: "Every design" }).waitFor({ timeout: 900_000 });
  say(`Small study (3 designs, fast, pool loads on first run): ${((Date.now() - t) / 1000).toFixed(1)} s`);
  const dl = page.waitForEvent("download");
  await page.getByRole("button", { name: "Results (JSON)" }).click();
  await (await dl).saveAs(join(outDir, "browser_results.json"));

  await page.getByRole("button", { name: "New study" }).click();
  await page.getByRole("button", { name: "Hot motorway road trip" }).click();
  await page.getByText(/39 designs in fast mode/).waitFor({ timeout: 120_000 });
  t = Date.now();
  await run.click();
  await page.getByRole("heading", { name: "Every design" }).waitFor({ timeout: 1_800_000 });
  const secs = (Date.now() - t) / 1000;
  const workers = await page.evaluate(() => Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 2) - 1)));
  say(`Hot road trip (39 designs, fast, ${workers} workers on ${await page.evaluate(() => navigator.hardwareConcurrency)} cores): ${secs.toFixed(0)} s`);
  // Counted per request, so a file every worker loads counts once per worker, whether or not
  // the browser served it from its cache.
  say(`Requested in all: ${(bytes / 1e6).toFixed(1)} MB over every worker (first load ${(firstLoad / 1e6).toFixed(1)} MB)`);
  await page.screenshot({ path: join(outDir, "results.png"), fullPage: true });
  if (errors.length) throw new Error(`errors in the page:\n${errors.join("\n")}`);
} finally {
  writeFileSync(join(outDir, "summary.md"), ["### In-browser engine", "", ...log.map((l) => `- ${l}`), ""].join("\n"));
  await browser.close();
  server.kill();
}
