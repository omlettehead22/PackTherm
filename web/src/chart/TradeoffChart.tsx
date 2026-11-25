// The trade-off chart: every design on mass added against running energy.
// Same encoding as the PNG (report.py): colour and legend for the cooling kind,
// squares for chilled liquid, filled = meets the limits, hollow = fails, a
// staircase for the trade-off front, numbered rings for the picks.
import { useId, useMemo, useState } from "react";
import type { Design, Pick } from "../types";
import type { LegendItem } from "./export";
import { linear, needsLog, staircase, symlog } from "./scale";

export const KINDS = ["natural", "air", "liquid"] as const;
const KIND_VAR: Record<string, string> = { natural: "var(--series-1)", air: "var(--series-2)", liquid: "var(--series-3)" };
export const PICK_LABEL: Record<string, string> = {
  lightest: "Lightest",
  lowest_energy: "Lowest energy",
  balanced: "Balanced",
};

const W = 720;
const H = 420;
const M = { top: 16, right: 20, bottom: 52, left: 64 };
/** How close the pointer must be to a design to pick it, in chart units (about a finger's width). */
const REACH = 24;

interface Props {
  designs: Design[];
  picks: Pick[];
  kindNames: Record<string, string>;
  xLabel: string;
  yLabel: string;
  active: number | null;
  setActive: (i: number | null) => void;
}

export interface Point {
  i: number;
  d: Design;
  x: number;
  y: number;
}

/** Which designs are picks, numbered as in the key (a design that is two picks gets one number). */
export function pickNumbers(designs: Design[], picks: Pick[]): Map<number, { n: number; names: string[] }> {
  const out = new Map<number, { n: number; names: string[] }>();
  for (const p of picks) {
    const i = designs.findIndex((d) => d.design === p.design);
    if (i < 0) continue;
    const e = out.get(i);
    if (e) e.names.push(PICK_LABEL[p.pick] ?? p.pick);
    else out.set(i, { n: out.size + 1, names: [PICK_LABEL[p.pick] ?? p.pick] });
  }
  return out;
}

/** The design nearest (px, py), within REACH, or null. */
export function nearest(points: Point[], px: number, py: number): number | null {
  let best: Point | null = null;
  let bestD = REACH * REACH;
  for (const p of points) {
    const d = (p.x - px) ** 2 + (p.y - py) ** 2;
    if (d < bestD) {
      best = p;
      bestD = d;
    }
  }
  return best ? best.i : null;
}

export function TradeoffChart({ designs, picks, kindNames, xLabel, yLabel, active, setActive }: Props) {
  const id = useId();
  const [focused, setFocused] = useState(false);

  const pts = useMemo(
    () =>
      designs
        .map((d, i) => ({ i, d }))
        .filter(({ d }) => typeof d.mass_overhead_pct === "number" && typeof d.aux_energy_pct === "number"),
    [designs],
  );
  const xs = pts.map((p) => p.d.mass_overhead_pct as number);
  const ys = pts.map((p) => p.d.aux_energy_pct as number);
  const x = linear(Math.max(...xs, 0) * 1.04, M.left, W - M.right);
  const lin = needsLog(ys);
  const yMax = Math.max(...ys, 0) * 1.04;
  const y = lin === null ? linear(yMax, H - M.bottom, M.top) : symlog(yMax, lin, H - M.bottom, M.top);
  const points: Point[] = pts.map(({ i, d }) => ({
    i,
    d,
    x: x(d.mass_overhead_pct as number),
    y: y(d.aux_energy_pct as number),
  }));
  const byX = [...points].sort((a, b) => a.x - b.x || a.y - b.y);
  const front = staircase(points.filter((p) => p.d.pareto && p.d.feasible).map((p) => [p.x, p.y]));
  const numbered = pickNumbers(designs, picks);
  const activePt = points.find((p) => p.i === active) ?? null;

  const move = (step: number) => {
    if (!byX.length) return;
    const at = byX.findIndex((p) => p.i === active);
    const next = at < 0 ? (step > 0 ? 0 : byX.length - 1) : Math.min(byX.length - 1, Math.max(0, at + step));
    setActive(byX[next].i);
  };
  const pointer = (e: React.MouseEvent<SVGRectElement>) => {
    const svg = e.currentTarget.ownerSVGElement;
    if (!svg) return;
    const box = svg.getBoundingClientRect();
    setActive(nearest(points, ((e.clientX - box.left) / box.width) * W, ((e.clientY - box.top) / box.height) * H));
  };

  return (
    <figure className="chart" aria-labelledby={`${id}-cap`}>
      <figcaption id={`${id}-cap`} className="chart__title">
        Trade-off: lower left is better
      </figcaption>
      <ul className="legend" aria-label="Legend">
        {chartLegend(designs, kindNames).map((item) => (
          <li key={item.label}>
            <LegendMark item={item} />
            {item.label}
          </li>
        ))}
      </ul>
      <p className="chart__ylabel">↑ {yLabel}</p>
      <div className="chart__scroll">
      <div className="chart__plot">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`Scatter chart of ${points.length} designs: ${xLabel} against ${yLabel}. Use the arrow keys to step through the designs; the table below has every value.`}
          tabIndex={0}
          onFocus={() => setFocused(true)}
          onBlur={() => {
            setFocused(false);
            setActive(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowRight" || e.key === "ArrowUp") move(1);
            else if (e.key === "ArrowLeft" || e.key === "ArrowDown") move(-1);
            else if (e.key === "Escape") setActive(null);
            else return;
            e.preventDefault();
          }}
          onMouseLeave={() => setActive(null)}
        >
          {y.ticks.map((t) => (
            <g key={`y${t}`}>
              <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} className="gridline" />
              <text x={M.left - 8} y={y(t)} className="tick" textAnchor="end" dominantBaseline="middle">
                {y.format(t)}
              </text>
            </g>
          ))}
          {x.ticks.map((t) => (
            <g key={`x${t}`}>
              <line x1={x(t)} x2={x(t)} y1={M.top} y2={H - M.bottom} className="gridline" />
              <text x={x(t)} y={H - M.bottom + 18} className="tick" textAnchor="middle">
                {x.format(t)}
              </text>
            </g>
          ))}
          <line x1={M.left} x2={W - M.right} y1={H - M.bottom} y2={H - M.bottom} className="axis" />
          <text x={(M.left + W - M.right) / 2} y={H - 10} className="axis-label" textAnchor="middle">
            {xLabel}
          </text>

          {front.length > 1 && (
            <path d={"M" + front.map(([a, b]) => `${a},${b}`).join(" L")} className="front" fill="none" />
          )}

          {/* failed designs first, so the feasible ones sit on top */}
          {[...points]
            .sort((a, b) => Number(a.d.feasible) - Number(b.d.feasible))
            .map((p) => (
              <Mark key={p.i} p={p} />
            ))}

          {[...numbered.entries()].map(([i, { n }]) => {
            const p = points.find((q) => q.i === i);
            if (!p) return null;
            return (
              <g key={`pick${i}`} className="pick" aria-hidden="true">
                <circle cx={p.x} cy={p.y} r={11} fill="none" />
                <g transform={`translate(${p.x - 15},${p.y - 15})`}>
                  <rect x={-8} y={-8} width={16} height={16} rx={4} />
                  <text textAnchor="middle" dominantBaseline="central">
                    {n}
                  </text>
                </g>
              </g>
            );
          })}

          {activePt && <circle cx={activePt.x} cy={activePt.y} r={9} className="hover-ring" />}

          {/* one hover layer picks the nearest design, so close marks never hide each other */}
          <rect
            x={M.left - 12}
            y={M.top - 12}
            width={W - M.left - M.right + 24}
            height={H - M.top - M.bottom + 24}
            className="hit"
            onMouseMove={pointer}
            onClick={pointer}
          />
        </svg>
        {activePt && <Tooltip p={activePt} kindNames={kindNames} pick={numbered.get(activePt.i)?.names} />}
        {focused && !activePt && <p className="chart__hint">Arrow keys step through the designs.</p>}
      </div>
      </div>
      {numbered.size > 0 && (
        <ol className="pick-key">
          {[...numbered.entries()].map(([i, { n, names }]) => (
            <li key={i} value={n}>
              <strong>{names.join(" / ")}</strong>: {designs[i].design}
            </li>
          ))}
        </ol>
      )}
    </figure>
  );
}

/** The legend: the cooling kinds present, then how marks read. Shared by the page and the chart file. */
export function chartLegend(designs: Design[], kindNames: Record<string, string>): LegendItem[] {
  const items: LegendItem[] = KINDS.filter((k) => designs.some((d) => d.cooling_kind === k)).map((k) => ({
    label: kindNames[k] ?? k,
    shape: "circle",
    color: KIND_VAR[k],
  }));
  if (designs.some((d) => d.chilled)) items.push({ label: "liquid + chiller", shape: "square", color: KIND_VAR.liquid });
  items.push(
    { label: "meets the limits", shape: "circle", color: "var(--text-secondary)" },
    { label: "fails the limits", shape: "hollow", color: "var(--text-secondary)" },
    { label: "trade-off front", shape: "line", color: "var(--text-secondary)" },
  );
  return items;
}

function LegendMark({ item }: { item: LegendItem }) {
  if (item.shape === "line")
    return (
      <svg width="18" height="12" aria-hidden="true">
        <path d="M1 9 H9 V3 H17" fill="none" stroke={item.color} strokeWidth="2" />
      </svg>
    );
  return (
    <svg width="12" height="12" aria-hidden="true">
      {item.shape === "square" ? (
        <rect x="1" y="1" width="10" height="10" rx="1" fill={item.color} />
      ) : item.shape === "hollow" ? (
        <circle cx="6" cy="6" r="4.3" fill="var(--surface-1)" stroke={item.color} strokeWidth="1.4" />
      ) : (
        <circle cx="6" cy="6" r="5" fill={item.color} />
      )}
    </svg>
  );
}

function Mark({ p }: { p: Point }) {
  const color = KIND_VAR[p.d.cooling_kind] ?? "var(--text-secondary)";
  const ok = p.d.feasible;
  const fill = ok ? color : "var(--surface-1)";
  const stroke = ok ? "var(--surface-1)" : color;
  const sw = ok ? 2 : 1.4;
  return p.d.chilled ? (
    <rect x={p.x - 5} y={p.y - 5} width={10} height={10} rx={1.5} fill={fill} stroke={stroke} strokeWidth={sw} />
  ) : (
    <circle cx={p.x} cy={p.y} r={ok ? 5.5 : 4.5} fill={fill} stroke={stroke} strokeWidth={sw} />
  );
}

const f1 = (v: unknown, digits = 1) => (typeof v === "number" ? v.toFixed(digits) : "–");

function Tooltip({ p, kindNames, pick }: { p: Point; kindNames: Record<string, string>; pick?: string[] }) {
  const d = p.d;
  const left = (p.x / W) * 100;
  const top = (p.y / H) * 100;
  return (
    <div
      className={"tooltip" + (left > 60 ? " tooltip--left" : "")}
      style={{ left: `${left}%`, top: `${top}%` }}
      role="status"
    >
      <p className="tooltip__title">{d.design}</p>
      {pick && <p className="tooltip__pick">{pick.join(" / ")}</p>}
      <dl>
        <dt>Cooling</dt>
        <dd>
          {kindNames[d.cooling_kind] ?? d.cooling_kind}
          {d.chilled ? " + chiller" : ""}
        </dd>
        <dt>Peak</dt>
        <dd>{f1(d.T_peak_C)} °C</dd>
        <dt>Mass added</dt>
        <dd>{f1(d.mass_overhead_pct)} %</dd>
        <dt>Energy</dt>
        <dd>{f1(d.aux_energy_pct, 2)} %</dd>
      </dl>
      <p className={d.feasible ? "tooltip__ok" : "tooltip__bad"}>
        {d.feasible ? "✓ Meets the limits" : `✕ Fails: ${failWords(d.fail_reason)}`}
      </p>
    </div>
  );
}

const FAIL_WORDS: Record<string, string> = {
  hot: "too hot",
  uneven: "in-cell spread",
  slow: "slow to recover",
  spread: "cell-to-cell spread",
  short: "cell can't deliver the current",
  ages: "loses too much capacity",
};

export const failWords = (reason: string) =>
  reason
    .split("·")
    .map((r) => r.trim())
    .filter(Boolean)
    .map((r) => FAIL_WORDS[r] ?? r)
    .join(", ");
