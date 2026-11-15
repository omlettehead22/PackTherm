import { useEffect, useState } from "react";
import { api, ApiError } from "./api";
import { Setup } from "./components/Setup";
import { StudyPage } from "./components/StudyPage";
import { formFromStudy, initialForm, type FormState } from "./study";
import type { LibraryCell, Limits, Schema } from "./types";

/** "#/studies/<id>" shows a study; anything else, the setup screen. */
export function route(hash: string): { page: "setup" } | { page: "study"; id: string } {
  const m = /^#\/studies\/([A-Za-z0-9_-]+)$/.exec(hash);
  return m ? { page: "study", id: m[1] } : { page: "setup" };
}

interface Loaded {
  schema: Schema;
  limits: Limits;
  cells: Record<string, LibraryCell>;
}

export function App() {
  const [hash, setHash] = useState(window.location.hash);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<FormState | null>(null);

  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  useEffect(() => {
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
        {!error && (!loaded || !form) && <p className="status">Loading…</p>}
        {loaded && form && r.page === "setup" && (
          <Setup
            schema={loaded.schema}
            limits={loaded.limits}
            cells={loaded.cells}
            form={form}
            setForm={setForm}
            onSubmitted={(id) => go(`#/studies/${id}`)}
          />
        )}
        {loaded && form && r.page === "study" && (
          <StudyPage
            id={r.id}
            limits={loaded.limits}
            onEdit={(study) => {
              setForm(formFromStudy(loaded.schema, study, form));
              go("#/");
            }}
            onNew={() => go("#/")}
          />
        )}
      </main>
      <footer className="footer">
        <p>
          PackTherm models cylindrical-cell modules; results are estimates with the labelled assumptions in each results
          file. <a href="/docs">HTTP API</a> ·{" "}
          <a href="https://github.com/omlettehead22/packtherm" rel="noopener">
            Source on GitHub
          </a>
        </p>
      </footer>
    </>
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
        <img src="/favicon.svg" alt="" width="28" height="28" />
        <span>
          <strong>PackTherm</strong>
          <span className="brand__sub">Battery thermal design studies</span>
        </span>
      </a>
      <button
        type="button"
        className="button button--quiet"
        aria-pressed={dark}
        onClick={() => setTheme(dark ? "light" : "dark")}
      >
        {dark ? "Light theme" : "Dark theme"}
      </button>
    </header>
  );
}
