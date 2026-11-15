import { describe, expect, it } from "vitest";
import { linear, needsLog, niceTicks, staircase, symlog, symlogT } from "./scale";

describe("chart scales", () => {
  it("picks round ticks that cover the data", () => {
    expect(niceTicks(23)).toEqual([0, 5, 10, 15, 20, 25]);
    expect(niceTicks(1.6)).toEqual([0, 0.5, 1, 1.5, 2]);
    expect(niceTicks(0)).toEqual([0, 1]);
    const x = linear(23, 0, 100);
    expect(x(25)).toBe(100);
  });

  it("switches to a log scale on the same rule as the PNG chart", () => {
    expect(needsLog([0, 0.15, 1.5])).toBeNull(); // 10x range: linear
    expect(needsLog([0, 0.05, 2.0])).toBe(0.01); // 40x: log above 0.01
    expect(needsLog([0, 0])).toBeNull();
  });

  it("matches matplotlib's symlog: linear to the threshold, then a decade per unit", () => {
    expect(symlogT(0.005, 0.01)).toBeCloseTo(0.5);
    expect(symlogT(0.01, 0.01)).toBeCloseTo(1);
    expect(symlogT(1, 0.01)).toBeCloseTo(3);
    const y = symlog(2, 0.01, 300, 0);
    expect(y.ticks).toEqual([0, 0.01, 0.1, 1, 10]);
    expect(y(0)).toBe(300);
    expect(y(10)).toBeCloseTo(0);
  });

  it("draws the front as a staircase", () => {
    expect(staircase([[3, 1], [1, 5], [2, 2]])).toEqual([[1, 5], [2, 5], [2, 2], [3, 2], [3, 1]]);
  });
});
