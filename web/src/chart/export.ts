// The trade-off chart as a file, made in the page (the public site has no
// server to draw the PNG). The on-screen SVG is cloned with its styles written
// in, and the title, axis label, legend and pick key, which are HTML on
// screen, are drawn into the file so it stands on its own.

const STYLE_PROPS = [
  "fill",
  "stroke",
  "stroke-width",
  "stroke-dasharray",
  "opacity",
  "font-family",
  "font-size",
  "font-weight",
  "font-variant-numeric",
  "dominant-baseline",
  "text-anchor",
] as const;

export interface LegendItem {
  label: string;
  shape: "circle" | "square" | "hollow" | "line";
  color: string; // a CSS colour or var(--x)
}

export interface ChartFile {
  title: string;
  yLabel: string;
  legend: LegendItem[];
  /** Lines under the chart: the numbered picks. */
  key: string[];
}

const NS = "http://www.w3.org/2000/svg";

function el<K extends keyof SVGElementTagNameMap>(name: K, attrs: Record<string, string | number>, text?: string) {
  const e = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (text !== undefined) e.textContent = text;
  return e;
}

/** A colour that may be var(--x), as the page currently shows it. */
function resolve(color: string, root: Element): string {
  const m = /^var\((--[\w-]+)\)$/.exec(color.trim());
  return m ? getComputedStyle(root).getPropertyValue(m[1]).trim() || color : color;
}

/** Copy the computed styles onto a clone, element by element (both trees have the same shape). */
function inlineStyles(source: Element, target: Element) {
  const cs = getComputedStyle(source);
  const style = STYLE_PROPS.map((p) => `${p}:${cs.getPropertyValue(p)}`).join(";");
  target.setAttribute("style", style);
  for (let i = 0; i < source.children.length; i++) inlineStyles(source.children[i], target.children[i]);
}

/** A standalone SVG document of the chart. */
export function chartSvg(svg: SVGSVGElement, f: ChartFile): string {
  const [, , W, H] = (svg.getAttribute("viewBox") ?? "0 0 720 420").split(/\s+/).map(Number);
  const root = document.documentElement;
  const bg = resolve("var(--surface-1)", root);
  const ink = resolve("var(--text-primary)", root);
  const muted = resolve("var(--text-secondary)", root);
  const font = getComputedStyle(svg).fontFamily || "system-ui, sans-serif";

  const plot = svg.cloneNode(true) as SVGSVGElement;
  inlineStyles(svg, plot);
  // Hover-only parts do not belong in a file.
  plot.querySelectorAll(".hit, .hover-ring").forEach((n) => n.remove());

  // Lay the legend out first (measured text, wrapping rows), then size the header to it.
  const measure = document.createElement("canvas").getContext("2d");
  if (measure) measure.font = `12px ${font}`;
  const textWidth = (s: string) => (measure ? measure.measureText(s).width : s.length * 7.5);
  const placed: { item: LegendItem; x: number; row: number }[] = [];
  let lx = 16;
  let row = 0;
  for (const item of f.legend) {
    const width = 22 + textWidth(item.label) + 18;
    if (lx + width > W - 8 && lx > 16) {
      lx = 16;
      row += 1;
    }
    placed.push({ item, x: lx, row });
    lx += width;
  }
  const legendTop = 46;
  const top = legendTop + row * 18 + 32;
  const lineH = 18;
  const bottom = 16 + f.key.length * lineH;
  const out = el("svg", { xmlns: NS, width: W, height: top + H + bottom, viewBox: `0 0 ${W} ${top + H + bottom}` });
  out.appendChild(el("rect", { x: 0, y: 0, width: W, height: top + H + bottom, fill: bg }));
  const text = (x: number, y: number, s: string, size: number, color: string, weight = 400) =>
    out.appendChild(el("text", { x, y, "font-family": font, "font-size": size, "font-weight": weight, fill: color }, s));
  text(16, 24, f.title, 16, ink, 700);

  for (const { item, x, row: r } of placed) {
    const y = legendTop + r * 18;
    const c = resolve(item.color, root);
    if (item.shape === "circle") out.appendChild(el("circle", { cx: x + 6, cy: y - 4, r: 5, fill: c }));
    else if (item.shape === "square") out.appendChild(el("rect", { x: x + 1, y: y - 9, width: 10, height: 10, rx: 1, fill: c }));
    else if (item.shape === "hollow")
      out.appendChild(el("circle", { cx: x + 6, cy: y - 4, r: 4.3, fill: bg, stroke: c, "stroke-width": 1.4 }));
    else out.appendChild(el("path", { d: `M${x} ${y - 1} H${x + 8} V${y - 7} H${x + 16}`, fill: "none", stroke: c, "stroke-width": 2 }));
    text(x + 22, y, item.label, 12, ink);
  }
  text(16, top - 6, `↑ ${f.yLabel}`, 12, muted);

  const g = el("g", { transform: `translate(0 ${top})` });
  plot.removeAttribute("width");
  plot.removeAttribute("height");
  plot.setAttribute("width", String(W));
  plot.setAttribute("height", String(H));
  g.appendChild(plot);
  out.appendChild(g);
  f.key.forEach((line, i) => text(16, top + H + 14 + i * lineH, line, 12, ink));
  return '<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(out);
}

/** The SVG drawn onto a canvas at `scale`, as a PNG. */
export async function svgToPng(svgText: string, scale = 2): Promise<Blob> {
  const url = URL.createObjectURL(new Blob([svgText], { type: "image/svg+xml" }));
  try {
    const img = new Image();
    await new Promise<void>((ok, fail) => {
      img.onload = () => ok();
      img.onerror = () => fail(new Error("could not draw the chart"));
      img.src = url;
    });
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale);
    canvas.height = Math.round(img.height * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("no canvas");
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0);
    return await new Promise<Blob>((ok, fail) =>
      canvas.toBlob((b) => (b ? ok(b) : fail(new Error("could not make the PNG"))), "image/png"),
    );
  } finally {
    URL.revokeObjectURL(url);
  }
}
