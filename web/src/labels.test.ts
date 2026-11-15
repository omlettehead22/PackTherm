import { describe, expect, it } from "vitest";
import schema from "./generated/schema.json";
import { CHOICE_LABELS, LABELS, TOPOLOGY_LABELS } from "./labels";
import type { KeyRule, Schema } from "./types";

const s = schema as unknown as Schema;
const sections: [string, Record<string, KeyRule>][] = [
  ["top", s.top],
  ["duty", s.duty.keys],
  ["requirements", s.requirements],
  ["design_space", s.design_space],
  ["options", s.options],
  ["cell", s.cell.keys],
];

describe("the form covers the study format", () => {
  it("has a label for every key in the schema", () => {
    const missing = sections.flatMap(([sec, keys]) => Object.keys(keys).map((k) => `${sec}.${k}`)).filter((k) => !LABELS[k]);
    expect(missing).toEqual([]);
  });

  it("has no labels for keys the schema no longer has", () => {
    const known = new Set(sections.flatMap(([sec, keys]) => Object.keys(keys).map((k) => `${sec}.${k}`)));
    expect(Object.keys(LABELS).filter((k) => !known.has(k))).toEqual([]);
  });

  it("has words for every choice shown in a menu", () => {
    const choices = sections.flatMap(([, keys]) =>
      Object.entries(keys)
        .filter(([k, r]) => r.choices && k !== "format")
        .flatMap(([, r]) => r.choices!.map(String)),
    );
    expect(choices.filter((c) => !CHOICE_LABELS[c])).toEqual([]);
    expect(Object.keys(TOPOLOGY_LABELS)).toEqual(s.design_space.topologies.items!.choices);
  });

  it("has an explanation for every key that may be left empty", () => {
    const nullable = sections
      .flatMap(([sec, keys]) => Object.entries(keys).map(([k, r]) => [`${sec}.${k}`, r] as const))
      .filter(([, r]) => r.type.includes("null") && r.type.includes("number"))
      .map(([k]) => k);
    expect(nullable.filter((k) => !LABELS[k].empty)).toEqual([]);
  });
});
