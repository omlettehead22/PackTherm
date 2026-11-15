// Where the in-browser engine comes from. The Pyodide version is pinned: CI
// checks the in-browser results against packtherm run with this exact version.
export const PYODIDE_VERSION = "314.0.8";
export const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

/** "server": the app talks to packtherm serve. "browser": PackTherm runs in the page (the public site). */
export const ENGINE: "server" | "browser" = import.meta.env.VITE_ENGINE === "browser" ? "browser" : "server";

/** The PackTherm wheel the browser engine loads, written next to the app by the Pages build. */
export const WHEEL_MANIFEST = `${import.meta.env.BASE_URL}py/manifest.json`;
