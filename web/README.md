# PackTherm web app

A React + TypeScript app for setting up a study, watching it run and exploring the results. It runs studies on one of two engines, chosen when it is built:

- **Server** (the default): `packtherm serve` serves the app at `/`, and it talks only to the PackTherm HTTP API on the same address ([docs/API.md](../docs/API.md)).
- **Browser** (the public site): PackTherm itself runs in the page, under [Pyodide](https://pyodide.org) (Python compiled to WebAssembly), so the site is static files with no server. GitHub Pages publishes it from `main` once CI passes.

## Build

Node 20 or later:

```bash
cd web
npm ci
npm run build      # type-checks, then writes the app to src/packtherm/web_static/
packtherm serve    # http://127.0.0.1:8000
```

The Docker image builds the app itself, so the image needs no Node. Each version tag attaches a wheel with the app inside to a GitHub release.

The public site:

```bash
python web/scripts/build_pages.py --out web/dist-pages   # the app with VITE_ENGINE=browser, plus py/<PackTherm wheel>
python -m http.server -d web/dist-pages 8123   # then open http://127.0.0.1:8123/ (the site uses relative paths)
```

## The in-browser engine

- `src/engine/py.worker.ts` is a Web Worker that loads Pyodide (pinned in `src/engine/config.ts`) and NumPy, SciPy, pandas and PyYAML from the Pyodide CDN, unpacks the PackTherm wheel and imports `packtherm.browser`.
- `src/engine/browser.ts` runs a pool of these workers: one per core, leaving one for the page, at most four (each holds its own Python, a few hundred MB). The first worker answers the form's checks. A study's designs are spread over the pool; then the first worker assembles the results, asking for any worst-case re-checks it needs, which run on the pool too.
- `packtherm.browser` (Python) is the other side: the study in steps, with every value crossing as JSON text written by Python, so floats round-trip exactly. `tests/test_browser.py` drives it as the workers do and checks the results equal `packtherm run`'s exactly.
- CI's `browser-engine` job builds the site, runs a study in headless Chromium, checks the results file against `packtherm run` (`e2e/compare.py`), and times the hot road-trip example; the timings are in the job summary.
- Without a server, a share link carries the study (`#/study/<base64url JSON>`) and fills in the form; a downloaded results file opens with "Open a results file".

## Develop

```bash
packtherm serve                 # the API, on port 8000
cd web && npm run dev           # the app with live reload, calling the API through a proxy
npm test                        # Vitest: form, study files, chart scales, results screen, engine scheduling
npm run typecheck
```

## How it stays in step with PackTherm

- **The form is built from the study format.** `src/generated/schema.json` is `packtherm.study.schema()`; the presets and example cells are the files in `docs/examples/`. Regenerate them with `python web/scripts/export_contract.py`. A Python test (`tests/test_web.py`) fails if they are out of date, and a web test fails if a key in the format has no label in `src/labels.ts`.
- **The numbers on screen are the results file's.** The results screen reads the results document as the API returns it, with no recalculation. Its tests run against the committed example results.
- **Study checks come from the server.** As the form changes, the app asks `POST /studies/check` (and `POST /cells/check` for your own cell), so the design count, limits and errors are PackTherm's own.

## Layout

```
src/App.tsx                    pages (set up, running, results) and the header
src/components/Setup.tsx       the set-up form: presets, study, duty, limits, designs, options
src/components/CellPicker.tsx  library cell or your own, checked by the server
src/components/Fields.tsx      form fields generated from the format's rules
src/components/StudyPage.tsx   a study on the server: progress, then results
src/components/BrowserRun.tsx  a study running in the page: progress, then results
src/engine/                    the engines: server checks, the in-browser worker pool and its Pyodide worker
src/share.ts                   links that carry a study
src/components/Results.tsx     picks, chart, design table, notes, downloads, link
src/chart/                     the trade-off chart (hand-drawn SVG) and its scales
src/study.ts                   form state to study document, and the YAML writer
src/labels.ts                  what the form calls each key
src/generated/                 files shared with the Python package (see above)
```

Colours are the project's chart palette (the same as the PNG chart in `report.py`), with dark-mode steps; the cooling kinds are told apart by legend and shape as well as colour.
