// Scales for the trade-off chart. The y axis switches to a symmetric log
// scale when the energies span a wide range, as the PNG chart (report.py) does.

export interface Scale {
  (v: number): number;
  ticks: number[];
  format: (v: number) => string;
  log: boolean;
  linthresh?: number;
}

/** Round tick steps (1, 2, 5 × 10^n) covering [0, max]. */
export function niceTicks(max: number, count = 5): number[] {
  if (!(max > 0)) return [0, 1];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const ticks: number[] = [];
  for (let t = 0; t <= max + step * 1e-9; t += step) ticks.push(+t.toPrecision(12));
  if (ticks[ticks.length - 1] < max) ticks.push(+(ticks[ticks.length - 1] + step).toPrecision(12));
  return ticks;
}

export function formatTick(v: number): string {
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 100) return v.toFixed(0);
  if (a >= 1) return String(+v.toPrecision(3));
  return String(+v.toPrecision(2));
}

/** A linear scale from [0, ticks[-1]] onto [r0, r1]. */
export function linear(max: number, r0: number, r1: number): Scale {
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1];
  const f = ((v: number) => r0 + ((r1 - r0) * v) / top) as Scale;
  f.ticks = ticks;
  f.format = formatTick;
  f.log = false;
  return f;
}

/** Does this set of values need the log scale? Same rule as report.py. */
export function needsLog(values: number[]): number | null {
  const pos = values.filter((v) => v > 0);
  if (!pos.length) return null;
  const minPos = Math.min(...pos);
  const max = Math.max(...values);
  if (max <= 20 * Math.max(minPos, 1e-4)) return null;
  return 10 ** Math.floor(Math.log10(Math.max(minPos, 1e-4)));
}

/** matplotlib's symlog (base 10, linscale 1): linear up to linthresh, logarithmic above. */
export function symlogT(v: number, lin: number): number {
  const a = Math.abs(v);
  const t = a <= lin ? a / lin : 1 + Math.log10(a / lin);
  return Math.sign(v) * t;
}

export function symlog(max: number, lin: number, r0: number, r1: number): Scale {
  const ticks = [0];
  for (let t = lin; t < max * 10; t *= 10) {
    ticks.push(+t.toPrecision(12));
    if (t >= max) break;
  }
  const top = symlogT(ticks[ticks.length - 1], lin);
  const f = ((v: number) => r0 + ((r1 - r0) * symlogT(v, lin)) / top) as Scale;
  f.ticks = ticks;
  f.format = formatTick;
  f.log = true;
  f.linthresh = lin;
  return f;
}

/** The trade-off front as a staircase: everything above and right of it is dominated. */
export function staircase(points: [number, number][]): [number, number][] {
  const sorted = [...points].sort((a, b) => a[0] - b[0]);
  const out: [number, number][] = [];
  for (const [x, y] of sorted) {
    if (out.length) out.push([x, out[out.length - 1][1]]);
    out.push([x, y]);
  }
  return out;
}
