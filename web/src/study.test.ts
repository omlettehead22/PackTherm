import { describe, expect, it } from "vitest";
import cells from "./generated/cells.json";
import presets from "./generated/presets.json";
import schema from "./generated/schema.json";
import { fileStem, formFromStudy, initialForm, ownCellDoc, studyFromForm, toYaml } from "./study";
import type { Json, Schema } from "./types";

const s = schema as unknown as Schema;

describe("study documents", () => {
  it("writes only what differs from the defaults", () => {
    expect(studyFromForm(initialForm(s), s)).toEqual({
      packtherm_study: 1,
      cell: "M50",
      mode: "fast",
      duty: { type: "constant" },
    });
  });

  it("reproduces every preset, with the mode the app chose", () => {
    for (const p of presets) {
      const f = formFromStudy(s, p.study as unknown as Record<string, Json>, initialForm(s));
      const out = studyFromForm(f, s);
      // The same study: the preset's values, less any it states that equal their defaults.
      const duty = Object.fromEntries(
        Object.entries(p.study.duty).filter(([k, v]) => k === "type" || v !== s.duty.keys[k].default),
      );
      const top = Object.fromEntries(
        Object.entries(p.study).filter(([k, v]) => !(k in s.top) || k === "cell" || k === "packtherm_study" || v !== s.top[k].default),
      );
      expect(out).toEqual({ ...top, duty, mode: "fast" });
    }
  });

  it("keeps only the keys the duty type uses", () => {
    const f = initialForm(s);
    f.duty = { ...f.duty, type: "wltc", c_rate: 3, cycles: 2 };
    expect(studyFromForm(f, s).duty).toEqual({ type: "wltc", cycles: 2 });
  });

  it("reads a results file's full study back into the same study", () => {
    const f = initialForm(s);
    f.design_space = { ...f.design_space, topologies: ["ribbon"], gaps_mm: [1, 2] };
    f.requirements = { ...f.requirements, T_max_C: 40 };
    const study = studyFromForm(f, s);
    expect(studyFromForm(formFromStudy(s, study as unknown as Record<string, Json>), s)).toEqual(study);
  });

  it("writes a user-defined cell inline, without empty keys", () => {
    const f = initialForm(s);
    f.cellSource = "own";
    f.ownCell = { ...f.ownCell, ...(cells[1].cell as Record<string, Json>) };
    expect(studyFromForm(f, s).cell).toEqual(cells[1].cell);
    expect(ownCellDoc({ ...f.ownCell, source: null }, s)).not.toHaveProperty("source");
  });
});

describe("YAML", () => {
  it("writes a study file packtherm run reads", () => {
    const study = {
      packtherm_study: 1 as const,
      name: "Test: a study",
      cell: { name: "My cell", format: "21700", capacity_Ah: 5, entropic: false },
      mode: "fast" as const,
      duty: { type: "segments", steps: [[600, 1.5], [300, -0.5]] },
      design_space: { topologies: ["air", "ribbon"], chiller_C: [] },
      requirements: { T_max_C: null },
    };
    expect(toYaml(study, "a comment")).toBe(
      [
        "# a comment",
        "packtherm_study: 1",
        'name: "Test: a study"',
        "cell:",
        "  name: My cell",
        '  format: "21700"',
        "  capacity_Ah: 5",
        "  entropic: false",
        "mode: fast",
        "duty:",
        "  type: segments",
        "  steps:",
        "    - [600, 1.5]",
        "    - [300, -0.5]",
        "design_space:",
        "  topologies: [air, ribbon]",
        "  chiller_C: []",
        "requirements:",
        "  T_max_C: null",
        "",
      ].join("\n"),
    );
  });

  it("quotes strings YAML would read as something else", () => {
    expect(toYaml({ a: "yes", b: "null", c: "1.5", d: "M50", e: "x #y" })).toBe(
      'a: "yes"\nb: "null"\nc: "1.5"\nd: M50\ne: "x #y"\n',
    );
  });

  it("names files from the study name", () => {
    expect(fileStem({ name: "M50 road trip, 35 degC" })).toBe("m50_road_trip_35_degc");
    expect(fileStem({})).toBe("study");
  });
});
