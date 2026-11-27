import { useEffect, useState, useSyncExternalStore } from "react";
import { api, ApiError } from "./api";
import { BrowserRun } from "./components/BrowserRun";
import { Intro } from "./components/Intro";
import { Results } from "./components/Results";
import { Setup } from "./components/Setup";
import { StudyPage } from "./components/StudyPage";
import { browserEngine, engine, ENGINE } from "./engine";
import library from "./generated/library.json";
import schemaJson from "./generated/schema.json";
import { decodeStudy } from "./share";
import { formFromStudy, initialForm, type FormState } from "./study";
import type { Json, LibraryCell, Limits, Results as ResultsDoc, Schema, Study } from "./types";

type Route =
  | { page: "setup" }
  | { page: "study"; id: string } // a study on the server
  | { page: "shared"; study: Record<string, Json> } // a link carrying a study
  | { page: "run" } // running in this browser
  | { page: "results" }; // a results file opened here

export function route(hash: string): Route {
  const m = /^#\/studies\/([A-Za-z0-9_-]+)$/.exec(hash);
  if (m) return { page: "study", id: m[1] };
  const s = /^#\/study\/([A-Za-z0-9_-]+)$/.exec(hash);
  if (s) {
    const study = decodeStudy(s[1]);
    if (study) return { page: "shared", study };
  }
  if (hash === "#/run") return { page: "run" };
  if (hash === "#/results") return { page: "results" };
  return { page: "setup" };
}

interface Loaded {
  schema: Schema;
  /** Null in the browser: no server, no limits. */
  limits: Limits | null;
  cells: Record<string, LibraryCell>;
}

/** With the browser engine everything the form needs ships with the app, so it shows at once. */
const BUNDLED: Loaded = { schema: schemaJson as unknown as Schema, limits: null, cells: library };

export function App() {
  const [hash, setHash] = useState(window.location.hash);
  const [loaded, setLoaded] = useState<Loaded | null>(ENGINE === "browser" ? BUNDLED : null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<FormState | null>(ENGINE === "browser" ? initialForm(BUNDLED.schema) : null);
  const [running, setRunning] = useState<Study | null>(null);
  const [opened, setOpened] = useState<ResultsDoc | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  useEffect(() => {
    if (ENGINE === "browser") {
      browserEngine.start().catch(() => {}); // warm up; failures show in the header
      return;
    }
    Promise.all([api.schema(), api.limits(), api.cells()])
      .then(([schema, limits, cells]) => {
        setLoaded({ schema, limits, cells });
        setForm(initialForm(schema));
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  const r = route(hash);
  const go = (h: string) => {
    window.location.hash = h;
    window.scrollTo(0, 0);
  };

  // A shared study fills in the form, then the address goes back to the form's.
  useEffect(() => {
    if (r.page === "shared" && loaded && form) {
      setForm(formFromStudy(loaded.schema, r.study, form));
      setNotice("Opened a shared study. Check it, then run it.");
      window.history.replaceState(null, "", "#/");
      setHash("#/");
    }
  }, [r.page, loaded, form, r]);

  const edit = (study: ResultsDoc["study"]) => {
    if (loaded && form) setForm(formFromStudy(loaded.schema, study, form));
    go("#/");
  };

  const openResults = async (file: File) => {
    try {
      const doc = JSON.parse(await file.text()) as ResultsDoc;
      if (typeof doc.packtherm_results !== "number" || !Array.isArray(doc.designs))
        throw new Error("not a PackTherm results file");
      setOpened(doc);
      go("#/results");
    } catch (e) {
      setNotice(`Could not open ${file.name}: ${e instanceof Error ? e.message : String(e)}.`);
    }
  };

  return (
    <>
      <Header />
      <main id="main">
        {error && (
          <div className="notice notice--critical" role="alert">
            <p>
              <strong>The app could not load.</strong> {error}
            </p>
          </div>
        )}
        {notice && r.page === "setup" && (
          <div className="notice notice--info" role="status">
            <p>
              {notice}{" "}
              <button type="button" className="link" onClick={() => setNotice(null)}>
                Dismiss
              </button>
            </p>
          </div>
        )}
        {ENGINE === "browser" && r.page === "setup" && <Intro />}
        {!error && (!loaded || !form) && <p className="status">Loading…</p>}
        {loaded && form && (r.page === "setup" || r.page === "shared") && (
          <Setup
            schema={loaded.schema}
            limits={loaded.limits}
            checks={engine}
            cells={loaded.cells}
            form={form}
            setForm={setForm}
            onRun={async (study) => {
              if (ENGINE === "browser") {
                setRunning(study);
                go("#/run");
              } else {
                const s = await api.submit(study);
                go(`#/studies/${s.id}`);
              }
            }}
            onOpenResults={ENGINE === "browser" ? openResults : undefined}
          />
        )}
        {loaded?.limits && form && r.page === "study" && (
          <StudyPage id={r.id} limits={loaded.limits} onEdit={edit} onNew={() => go("#/")} />
        )}
        {r.page === "run" &&
          (running ? (
            <BrowserRun study={running} onEdit={edit} onNew={() => go("#/")} />
          ) : (
            <Gone what="This run is no longer open (the page was reloaded)." onNew={() => go("#/")} />
          ))}
        {r.page === "results" &&
          (opened ? (
            <Results source={{ kind: "file" }} results={opened} onEdit={edit} onNew={() => go("#/")} />
          ) : (
            <Gone what="No results file is open." onNew={() => go("#/")} />
          ))}
      </main>
      <footer className="footer">
        <p>
          PackTherm models cylindrical-cell modules; results are estimates with the labelled assumptions in each results
          file.{" "}
          {ENGINE === "browser" ? (
            "Studies run on your computer: nothing you enter is sent anywhere."
          ) : (
            <a href="/docs">HTTP API</a>
          )}{" "}
          ·{" "}
          <a href="https://github.com/omlettehead22/packtherm" rel="noopener">
            Source on GitHub
          </a>
        </p>
      </footer>
    </>
  );
}

function Gone({ what, onNew }: { what: string; onNew: () => void }) {
  return (
    <section className="card">
      <p>{what}</p>
      <button type="button" className="button button--primary" onClick={onNew}>
        Set up a study
      </button>
    </section>
  );
}

function EngineBadge() {
  const s = useSyncExternalStore(
    (fn) => browserEngine.subscribe(fn),
    () => browserEngine.getState(),
  );
  const text =
    s.phase === "ready"
      ? `Engine ready: PackTherm ${s.version} in your browser`
      : s.phase === "failed"
        ? "The engine could not load: reload the page to try again"
        : "Loading the engine…";
  return (
    <p className={"engine engine--" + s.phase} role="status" title={s.phase === "failed" ? s.message : undefined}>
      <span aria-hidden="true">{s.phase === "ready" ? "● " : s.phase === "failed" ? "✕ " : "○ "}</span>
      {text}
    </p>
  );
}

type Theme = "light" | "dark" | null;

function readTheme(): Theme {
  try {
    const t = localStorage.getItem("packtherm-theme");
    return t === "light" || t === "dark" ? t : null;
  } catch {
    return null;
  }
}

function Header() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    try {
      if (theme) localStorage.setItem("packtherm-theme", theme);
      else localStorage.removeItem("packtherm-theme");
    } catch {
      /* storage can be unavailable; the choice then lasts for this visit */
    }
  }, [theme]);
  const dark = theme === "dark" || (theme === null && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  return (
    <header className="header">
      <a className="skip" href="#main">
        Skip to the content
      </a>
      <a className="brand" href="#/">
        <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" width="28" height="28" />
        <span>
          <strong>PackTherm</strong>
          <span className="brand__sub">Battery thermal design studies</span>
        </span>
      </a>
      <div className="header__end">
        {ENGINE === "browser" && <EngineBadge />}
        <button
          type="button"
          className="button button--quiet"
          aria-pressed={dark}
          onClick={() => setTheme(dark ? "light" : "dark")}
        >
          {dark ? "Light theme" : "Dark theme"}
        </button>
      </div>
    </header>
  );
}
