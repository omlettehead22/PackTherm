import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import schema from "./generated/schema.json";

const limits = {
  max_designs_fast: 120, max_designs_normal: 40, max_simulated_h: 24, max_steps: 1000, max_runtime_s: 900,
  max_running: 2, max_queued: 20, rate_per_hour: 10, max_request_kB: 256, keep_h: 24,
};
const cells = {
  M50: { name: "LG INR21700 M50", group: "design", model: "circuit (derived, measured resistance)", format: "21700", capacity_Ah: 5, V_nominal: 3.63, DCIR_25C_mOhm: 30, mass_g: 68 },
  "M50-LUMPED": { name: "LG INR21700 M50 (lumped DCIR)", group: "comparison", model: "lumped DCIR", format: "21700", capacity_Ah: 5, V_nominal: 3.63, DCIR_25C_mOhm: 30, mass_g: 68 },
};

let posted: { url: string; body: unknown }[] = [];

beforeEach(() => {
  posted = [];
  window.location.hash = "";
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      if (init?.method === "POST") posted.push({ url, body });
      const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
      if (url === "/schema") return json(schema);
      if (url === "/limits") return json(limits);
      if (url === "/cells") return json(cells);
      if (url === "/studies/check") return json({ designs: 39, mode: body.mode, within_limits: true, problems: [] });
      if (url === "/cells/check")
        return body.DCIR_mOhm ? json({ cell: body, derived: { name: body.name, model: "user-defined, lumped DCIR", energy_Wh: 8.6 }, warnings: [] })
          : json({ error: "Invalid cell", errors: ["DCIR_mOhm: required"] }, 422);
      if (url === "/studies") return json({ id: "job1", state: "queued", designs: 39, mode: "fast" }, 202);
      return json({ error: "not found" }, 404);
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("the setup screen", () => {
  it("starts in fast mode, checks the study with the server, and submits it", async () => {
    render(<App />);
    await screen.findByText(/39 designs in fast mode \(up to 120 allowed\)/);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Hot motorway road trip" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Run the study" })).toHaveProperty("disabled", false));
    await user.click(screen.getByRole("button", { name: "Run the study" }));
    await waitFor(() => expect(window.location.hash).toBe("#/studies/job1"));
    const sent = posted.find((p) => p.url === "/studies")!.body;
    expect(sent).toEqual({
      packtherm_study: 1, name: "M50 road trip, 35 degC", cell: "M50", mode: "fast", ambient_C: 35,
      duty: { type: "roadtrip" },
    });
  });

  it("lists comparison-only models apart, and says so when one is chosen", async () => {
    render(<App />);
    await screen.findByText(/designs in fast mode/);
    const group = screen.getByRole("group", { name: "For comparison only (not for design)" });
    expect(group.textContent).toContain("M50-LUMPED");
    expect(group.textContent).not.toContain("M50: ");
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Library cell"), "M50-LUMPED");
    expect(await screen.findByText(/For comparison only: an earlier or simpler model/)).toBeTruthy();
  });

  it("shows each duty type's own fields", async () => {
    render(<App />);
    await screen.findByText(/designs in fast mode/);
    const user = userEvent.setup();
    expect(screen.getByLabelText(/^Current/)).toBeTruthy();
    await user.selectOptions(screen.getByLabelText("Duty type"), "wltc");
    expect(screen.queryByLabelText(/^Current/)).toBeNull();
    expect(screen.getByLabelText("WLTC cycles")).toBeTruthy();
    await user.selectOptions(screen.getByLabelText("Duty type"), "segments");
    expect(screen.getByRole("button", { name: "Add a segment" })).toBeTruthy();
  });

  it("checks your own cell as it is typed", async () => {
    render(<App />);
    await screen.findByText(/designs in fast mode/);
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "Your own cell" }));
    await screen.findByText(/Not a valid cell yet/, {}, { timeout: 2000 });
    await user.click(screen.getByRole("button", { name: /ANR26650/ }));
    await screen.findByText(/Valid cell: ANR26650M1-B/, {}, { timeout: 2000 });
  });

  it("shows a field's problem instead of sending a bad value", async () => {
    render(<App />);
    await screen.findByText(/designs in fast mode/);
    const user = userEvent.setup();
    const field = screen.getByLabelText(/^Current/);
    await user.clear(field);
    await user.type(field, "-2");
    expect(screen.getByText("Must be more than 0")).toBeTruthy();
    await act(async () => new Promise((r) => setTimeout(r, 500)));
    const last = posted.filter((p) => p.url === "/studies/check").pop()!.body as { duty: { c_rate?: number } };
    expect(last.duty.c_rate).not.toBe(-2);
  });
});
