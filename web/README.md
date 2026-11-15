# PackTherm web app

A React + TypeScript app for setting up a study, watching it run and exploring the results. `packtherm serve` serves the built app at `/`; it talks only to the PackTherm HTTP API on the same address ([docs/API.md](../docs/API.md)).

## Build

Node 20 or later:

```bash
cd web
npm ci
npm run build      # type-checks, then writes the app to src/packtherm/web_static/
packtherm serve    # http://127.0.0.1:8000
```

The Docker image builds the app itself, so the image needs no Node.

## Develop

```bash
packtherm serve                 # the API, on port 8000
cd web && npm run dev           # the app with live reload, calling the API through a proxy
npm test                        # Vitest: form, study files, chart scales, results screen
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
src/components/StudyPage.tsx   a submitted study: progress, then results
src/components/Results.tsx     picks, chart, design table, notes, downloads, link
src/chart/                     the trade-off chart (hand-drawn SVG) and its scales
src/study.ts                   form state to study document, and the YAML writer
src/labels.ts                  what the form calls each key
src/generated/                 files shared with the Python package (see above)
```

Colours are the project's chart palette (the same as the PNG chart in `report.py`), with dark-mode steps; the cooling kinds are told apart by legend and shape as well as colour.
