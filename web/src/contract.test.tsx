// The results screen against real results files: the committed examples
// (made by packtherm run). Assigning them to Results makes tsc check the shape.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import discharge from "../../docs/examples/module_m50_discharge_1.5c_25c_results.json";
import roadtrip from "../../docs/examples/module_m50_roadtrip_130kmh_35c_results.json";
import wltc from "../../docs/examples/module_m50_wltc3_35c_results.json";
import { pickNumbers } from "./chart/TradeoffChart";
import { Results } from "./components/Results";
import type { Limits, Results as ResultsDoc } from "./types";

const examples: ResultsDoc[] = [roadtrip, discharge, wltc] as ResultsDoc[];
const limits = { keep_h: 24, max_designs_fast: 120, max_designs_normal: 40 } as Limits;

describe("results files", () => {
  it("carry every field the app reads, in every design", () => {
    const used = ["design", "cooling_kind", "chilled", "feasible", "pareto", "fail_reason", "T_peak_C", "dT_cell_C",
      "cell_to_cell_K", "recovery_min", "mass_overhead_pct", "aux_energy_pct", "robust"];
    for (const r of examples) {
      for (const d of [...r.designs, ...r.picks]) for (const k of used) expect(d, `${r.study.name}: ${k}`).toHaveProperty(k);
      expect(r.summary.designs).toBe(r.designs.length);
    }
  });

  it("names every pick after a design in the table", () => {
    for (const r of examples) for (const p of r.picks) expect(r.designs.some((d) => d.design === p.design)).toBe(true);
  });
});

describe("the results screen", () => {
  const show = (r: ResultsDoc) =>
    render(
      <Results
        source={{ kind: "server", id: "abc", finished: 1.7e9, keepH: limits.keep_h }}
        results={r}
        onEdit={() => {}}
        onNew={() => {}}
      />,
    );

  it("shows the summary, one card per picked design, and every design", () => {
    const r = examples[0];
    show(r);
    expect(screen.getByText(r.summary.duty, { exact: false })).toBeTruthy();
    const cards = within(screen.getByRole("region", { name: "Recommended designs" })).getAllByRole("article");
    expect(cards).toHaveLength(new Set(r.picks.map((p) => p.design)).size);
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(r.designs.length + 1);
    expect(pickNumbers(r.designs, r.picks).size).toBe(cards.length);
  });

  it("sorts the table and filters to the feasible designs", async () => {
    const r = examples[0];
    show(r);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Peak/ }));
    const peaks = within(screen.getByRole("table"))
      .getAllByRole("row")
      .slice(1)
      .map((row) => Number(within(row).getAllByRole("cell")[0].textContent));
    expect(peaks).toEqual([...peaks].sort((a, b) => a - b));
    await user.click(screen.getByRole("radio", { name: /Meet the limits/ }));
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(r.summary.feasible + 1);
  });

  it("labels fast-mode and user-defined-cell results", () => {
    const r = structuredClone(examples[1]);
    r.summary.mode = "fast";
    r.summary.cell_model = "user-defined, lumped DCIR";
    show(r);
    expect(screen.getByText("Fast mode")).toBeTruthy();
    expect(screen.getByText(/user-defined, lumped DCIR/)).toBeTruthy();
  });

  it("says so when no design meets the limits", () => {
    const r = structuredClone(examples[2]);
    r.picks = [];
    show(r);
    expect(screen.getByText(/No design meets the limits/)).toBeTruthy();
  });
});
