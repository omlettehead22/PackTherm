import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { browserEngine, ENGINE } from "./engine";
import "./styles.css";

// For diagnostics (the end-to-end check reads the engine's download figures).
if (ENGINE === "browser") (window as unknown as { __packtherm: unknown }).__packtherm = browserEngine;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
