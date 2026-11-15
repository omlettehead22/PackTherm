import { describe, expect, it } from "vitest";
import { route } from "./App";
import { designsCsv } from "./components/download";
import { decodeStudy, encodeStudy } from "./share";

describe("links and files", () => {
  it("carries a study in a link, including non-ASCII text", () => {
    const study = { packtherm_study: 1, name: "M50 at 35 °C, 1.5C", cell: "M50", duty: { type: "constant", c_rate: 1.5 } };
    const enc = encodeStudy(study);
    expect(enc).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(decodeStudy(enc)).toEqual(study);
    expect(decodeStudy("not-base64!")).toBeNull();
    expect(route(`#/study/${enc}`)).toEqual({ page: "shared", study });
  });

  it("routes each page", () => {
    expect(route("#/studies/abc_DEF-123")).toEqual({ page: "study", id: "abc_DEF-123" });
    expect(route("#/run")).toEqual({ page: "run" });
    expect(route("#/results")).toEqual({ page: "results" });
    expect(route("")).toEqual({ page: "setup" });
    expect(route("#/study/%%%")).toEqual({ page: "setup" });
  });

  it("writes the designs table as CSV", () => {
    const csv = designsCsv([
      { design: "air 0.3 g/s, RT31", T_peak_C: 41.25, feasible: true, fail_reason: "" },
      { design: 'say "hi"', T_peak_C: null, feasible: false, fail_reason: "hot · slow" },
    ]);
    expect(csv).toBe(
      'design,T_peak_C,feasible,fail_reason\n"air 0.3 g/s, RT31",41.25,true,\n"say ""hi""",,false,hot · slow\n',
    );
  });
});
