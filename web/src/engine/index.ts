// The engine the app runs studies on: the PackTherm server (packtherm serve),
// or PackTherm itself running in the page (the public site, with no server).
import { api } from "../api";
import type { CellCheck, Study, StudyCheck } from "../types";
import { browserEngine } from "./browser";
import { ENGINE } from "./config";

export interface Checks {
  kind: "server" | "browser";
  checkCell: (cell: unknown) => Promise<CellCheck>;
  checkStudy: (study: Study) => Promise<StudyCheck>;
}

export const serverChecks: Checks = { kind: "server", checkCell: api.checkCell, checkStudy: api.checkStudy };

export const engine: Checks =
  ENGINE === "browser"
    ? {
        kind: "browser",
        checkCell: (c) => browserEngine.checkCell(c),
        checkStudy: (s) => browserEngine.checkStudy(s),
      }
    : serverChecks;

export { browserEngine, ENGINE };
