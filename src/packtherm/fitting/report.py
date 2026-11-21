"""The fit report: one self-contained HTML page beside the fitted cell file.

What it shows, in the order someone checking a fit asks:

1. what the cell file can be used for (one temperature: not in studies yet);
2. the prediction of tests the fit never saw, against the library cell's;
3. the fitted values, each with where it came from, a 95% range and flags;
4. where the model is valid, and the errors on what it was fitted to;
5. the open-circuit voltage, and pulses and steps, measured against the model;
6. the data-quality warnings, and what went in (file hashes, dataset, settings).

The charts are PNGs inside the page, so the page can be sent on its own.
Colours: the categorical slots of PackTherm's trade-off chart (measured in
ink, the fit blue, the library cell orange).
"""

from __future__ import annotations

import base64
import html
import io
from pathlib import Path

import numpy as np

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e1e0d9"
FIT = "#2a78d6"
OTHER = "#eb6834"

CSS = f"""
body {{ font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color: {TEXT}; background: {SURFACE};
  max-width: 980px; margin: 2rem auto; padding: 0 1.2rem; }}
h1 {{ font-size: 1.6rem; margin-bottom: .2rem; }} h2 {{ font-size: 1.15rem; margin-top: 2.2rem;
  border-bottom: 1px solid {GRID}; padding-bottom: .3rem; }}
.sub {{ color: {TEXT_2}; margin-top: 0; }}
.banner {{ border: 1px solid #e9b949; background: #fff8e6; padding: .7rem 1rem; border-radius: 6px; }}
.banner.ok {{ border-color: #8fbf8f; background: #f1f8f1; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; margin: .6rem 0; }}
th, td {{ text-align: left; padding: .35rem .5rem; border-bottom: 1px solid {GRID}; vertical-align: top; }}
th {{ color: {TEXT_2}; font-weight: 600; }} td.n {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
.tag {{ display: inline-block; padding: 0 .4rem; border-radius: 4px; font-size: 12px; border: 1px solid {GRID}; }}
.flag {{ color: #a3460f; }}
img {{ max-width: 100%; }} ul {{ padding-left: 1.2rem; }} code {{ font-size: 12.5px; }}
.kpi {{ display: flex; gap: 1rem; flex-wrap: wrap; }} .kpi div {{ border: 1px solid {GRID}; border-radius: 6px;
  padding: .6rem .9rem; min-width: 12rem; }} .kpi b {{ font-size: 1.4rem; display: block; }}
"""


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=90, facecolor=SURFACE)
    import matplotlib.pyplot as plt

    plt.close(fig)
    return '<img alt="" src="data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode() + '">'


def _axes(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(color=GRID, lw=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(TEXT_2)
    ax.tick_params(colors=TEXT_2, labelsize=8)


def _plots(fit) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = {}
    pd = fit.plot_data

    seen_T: set = set()
    for c, row in zip(pd.get("checks", []), fit.checks):
        T_key = round(row.get("cell_C", 0.0) / 10)  # one chart per 10 K, and five at most, is enough to judge
        if T_key in seen_T or len(seen_T) >= 5:
            continue
        seen_T.add(T_key)
        fig, ax = plt.subplots(2, 1, sharex=True, figsize=(9, 4.6), height_ratios=(3, 1.3), facecolor=SURFACE)
        x = (c["t"] - c["t"][0]) / 60
        ax[0].plot(x, c["V"], lw=1.0, color=TEXT, label="measured")
        ax[0].plot(x, c["fit"], lw=1.0, color=FIT, label="this fit")
        ax[1].plot(x, 1e3 * (c["fit"] - c["V"]), lw=0.8, color=FIT, label="this fit")
        if "compare" in c:
            ax[0].plot(x, c["compare"], lw=1.0, color=OTHER, label=c["compare_name"])
            ax[1].plot(x, 1e3 * (c["compare"] - c["V"]), lw=0.8, color=OTHER, label=c["compare_name"])
        ax[0].set_ylabel("Voltage (V)", fontsize=9)
        ax[1].set_ylabel("Error (mV)", fontsize=9)
        ax[1].axhline(0, color=TEXT_2, lw=0.6)
        ax[1].set_xlabel("Time (min)", fontsize=9)
        ax[0].legend(frameon=False, fontsize=8, ncol=3, loc="lower right", bbox_to_anchor=(1.0, 1.0))
        ax[0].set_title(c["file"], fontsize=9, loc="left", color=TEXT_2)
        for a in ax:
            _axes(a)
        fig.tight_layout()
        out.setdefault("checks", []).append(_png(fig))

    ocv = pd["ocv"]
    fig, ax = plt.subplots(figsize=(9, 3.4), facecolor=SURFACE)
    others = sorted(getattr(fit, "ocv_curves", None) or [], key=lambda c: c.T_K)
    ref_T = f" at {ocv.T_K - 273.15:.0f} °C" if others and ocv.T_K is not None else ""
    ax.plot(100 * ocv.soc, ocv.V, lw=1.6, color=FIT, label=f"open-circuit voltage (fitted){ref_T}")
    # The other temperatures' curves (v0.6.5): one hue, darker colder, on the same state of charge.
    for i, c in enumerate(others):
        shade = plt.get_cmap("Blues")(0.9 - 0.5 * i / max(len(others) - 1, 1))
        ax.plot(100 * c.soc, c.V, lw=1.0, color=shade, label=f"{c.T_K - 273.15:.0f} °C ({c.capacity_Ah:.2f} Ah)")
    if ocv.discharge is not None:
        ax.plot(100 * ocv.discharge[0], ocv.discharge[1], lw=0.9, color=TEXT, label="slow discharge, measured")
    if ocv.charge is not None:
        ax.plot(100 * ocv.charge[0], ocv.charge[1], lw=0.9, color=TEXT_2, ls="--", label="slow charge, measured")
    ax.set_xlabel("State of charge (%)", fontsize=9)
    ax.set_ylabel("Voltage (V)", fontsize=9)
    ax.legend(frameon=False, fontsize=8, loc="lower right", ncol=2 if others else 1)
    _axes(ax)
    fig.tight_layout()
    out["ocv"] = _png(fig)

    for key, title in (("pulses", "Pulses"), ("steps", "Steps and rests")):
        items = pd.get(key) or []
        if not items:
            continue
        # Six spread across the state of charge, from full to empty.
        order = sorted(range(len(items)), key=lambda i: -items[i][0].soc0)
        pick = [order[round(k)] for k in np.linspace(0, len(order) - 1, min(6, len(order)))]
        fig, axs = plt.subplots(2, 3, figsize=(9, 4.8), facecolor=SURFACE)
        for a, i in zip(axs.flat, pick):
            w, Vm = items[i]
            x = w.t - w.t[0]
            if key == "steps":
                x = x / 60
            a.plot(x, 1e3 * (w.V - w.V[0]), lw=1.0, color=TEXT, label="measured")
            a.plot(x, 1e3 * (Vm - Vm[0]), lw=1.0, color=FIT, label="this fit")
            a.set_title(f"{w.soc0:.0%} SOC, {w.c_rate:.2g}C", fontsize=8.5, loc="left", color=TEXT_2)
            _axes(a)
        for a in axs.flat[len(pick) :]:
            a.axis("off")
        axs[0, 0].legend(frameon=False, fontsize=7.5)
        axs[0, 0].set_ylabel("Voltage change (mV)", fontsize=8.5)
        axs[1, 0].set_ylabel("Voltage change (mV)", fontsize=8.5)
        for a in axs[1]:
            a.set_xlabel("Time (min)" if key == "steps" else "Time (s)", fontsize=8.5)
        fig.suptitle(title, fontsize=9.5, x=0.01, ha="left", color=TEXT_2)
        fig.tight_layout()
        out[key] = _png(fig)

    by_T = pd.get("pulses_by_T") or {}
    if by_T:  # one pulse near mid charge at each temperature, at about 1C
        labels = list(by_T)
        cols = min(3, len(labels))
        rows = -(-len(labels) // cols)
        fig, axs = plt.subplots(rows, cols, figsize=(9, 2.6 * rows), facecolor=SURFACE, squeeze=False)
        for a, lab in zip(axs.flat, labels):
            items = by_T[lab]
            w, Vm = min(items, key=lambda it: abs(it[0].soc0 - 0.5) + 0.2 * abs(it[0].c_rate - 1.0))
            x = w.t - w.t[0]
            a.plot(x, 1e3 * (w.V - w.V[0]), lw=1.0, color=TEXT, label="measured")
            a.plot(x, 1e3 * (Vm - Vm[0]), lw=1.0, color=FIT, label="this fit")
            a.set_title(f"{lab}: {w.soc0:.0%} SOC, {w.c_rate:.2g}C", fontsize=8.5, loc="left", color=TEXT_2)
            a.set_xlabel("Time (s)", fontsize=8)
            _axes(a)
        for a in axs.flat[len(labels) :]:
            a.axis("off")
        axs[0, 0].legend(frameon=False, fontsize=7.5)
        axs[0, 0].set_ylabel("Voltage change (mV)", fontsize=8.5)
        fig.tight_layout()
        out["pulses_by_T"] = _png(fig)

    if fit.per_temperature:  # each value against temperature: the temperatures' own fits, and the laws beyond
        show = [
            ("R0_25C", "R0 (mOhm)", 1e3),
            ("I0_25C", "I0 (A)", 1.0),
            ("Rm_25C", "Rm (mOhm)", 1e3),
            ("Rd_25C", "Rd (mOhm)", 1e3),
            ("tau_d", "tau_d (s)", 1.0),
            ("soc_a", "soc_a", 1.0),
        ]
        fig, axs = plt.subplots(2, 3, figsize=(9, 5.0), facecolor=SURFACE)
        Ts = [pt["cell_C"] for pt in fit.per_temperature]
        grid = np.linspace(min(Ts) - 8, max(Ts) + 8, 60)
        for a, (name, label, k) in zip(axs.flat, show):
            ys, lo, hi = [], [], []
            for pt in fit.per_temperature:
                p = next(q for q in pt["params"] if q.name == name)
                ys.append(k * p.value)
                lo.append(k * (p.value - p.ci95[0]) if p.ci95 else 0.0)
                hi.append(k * (p.ci95[1] - p.value) if p.ci95 else 0.0)
            a.errorbar(Ts, ys, yerr=[lo, hi], fmt="o", ms=5, color=TEXT, ecolor=TEXT_2, lw=1, capsize=2,
                       label="each temperature's own fit")  # fmt: skip
            from ..fitting.circuit import _law_value

            a.plot(grid, [k * _law_value(fit.ecm, name, g + 273.15) for g in grid], lw=1.4, color=FIT,
                   label="as PackTherm runs it")  # fmt: skip
            a.set_yscale("log")
            a.set_title(label, fontsize=8.5, loc="left", color=TEXT_2)
            a.set_xlabel("Cell temperature (°C)", fontsize=8)
            _axes(a)
        axs[0, 0].legend(frameon=False, fontsize=7)
        fig.tight_layout()
        out["by_T"] = _png(fig)
    return out


def _thermal_plot(rows: list[dict]) -> str:
    """Surface temperature, measured against predicted, for one held-out test per chamber temperature."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pick: dict = {}
    for r in rows:
        pick.setdefault(round(r["ambient_C"]), r)
    pick = dict(sorted(pick.items(), reverse=True))
    cols = min(3, len(pick))
    nrows = -(-len(pick) // cols)
    fig, axs = plt.subplots(nrows, cols, figsize=(9, 2.7 * nrows), facecolor=SURFACE, squeeze=False)
    for a, r in zip(axs.flat, pick.values()):
        s = r["_series"]
        x = s["t"] / 60
        a.plot(x, s["T_meas"], lw=1.2, color=TEXT, label="measured")
        a.plot(x, s["T_model"], lw=1.2, color=FIT, label="this fit")
        if "_compare_series" in r:
            c = r["_compare_series"]
            a.plot(c["t"] / 60, c["T_model"], lw=1.0, color=OTHER, label=r["compare"])
        a.set_title(f"{r['file']}", fontsize=8, loc="left", color=TEXT_2)
        a.set_xlabel("Time (min)", fontsize=8)
        _axes(a)
    for a in axs.flat[len(pick) :]:
        a.axis("off")
    axs[0, 0].set_ylabel("Surface temperature (°C)", fontsize=8.5)
    axs[0, 0].legend(frameon=False, fontsize=7)
    fig.tight_layout()
    return _png(fig)


def _e(x) -> str:
    return html.escape(str(x))


def _num(x: float) -> str:
    return f"{x:.4g}"


def report_html(fit, doc: dict, thermal: list[dict] | None = None) -> str:
    plots = _plots(fit)
    if doc["usable_in_studies"]:
        like = doc.get("like", "")
        banner = (
            f"<p class='banner ok'><b>Usable in studies</b>, with the size, mass and thermal properties of "
            f"<code>{_e(like)}</code>. Studies warn when a run goes beyond the temperatures and rates tested "
            "(below).</p>"
        )
    else:
        banner = f"<p class='banner'><b>Not usable in studies.</b> {_e(doc.get('why_not_usable', ''))}</p>"
    v = doc["valid_for"]
    parts = [
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>PackTherm fit: {_e(doc['name'])}</title><style>{CSS}</style></head><body>",
        f"<h1>{_e(doc['name'])}</h1>",
        (
            f"<p class='sub'>PackTherm {_e(doc['provenance']['packtherm'])} fit, "
            f"{_e(doc['provenance']['fitted_at'])}. Model: {_e(doc['model']['form'])}.</p>"
        ),
        banner,
    ]

    # 2. Held-out tests.
    parts.append("<h2>Prediction of tests the fit never saw</h2>")
    if fit.checks:
        parts.append("<div class='kpi'>")
        for c in fit.checks:
            parts.append(f"<div>This fit<b>{c['rmse_mV']:.1f} mV</b>RMS error, {c['max_mV']:.0f} mV at worst</div>")
            if "compare" in c:
                parts.append(
                    f"<div>{_e(c['compare'])}<b>{c['compare_rmse_mV']:.1f} mV</b>"
                    f"RMS error, {c['compare_max_mV']:.0f} mV at worst</div>"
                )
        parts.append("</div>")
        for c in fit.checks:
            parts.append(f"<p class='sub'>{_e(c['file'])}: state of charge at the start {_e(c['anchored'])}.</p>")
        parts += plots.get("checks", [])
    else:
        parts.append("<p>No held-out test was given (<code>--check</code>): the fit is judged only on what it saw.</p>")
    if fit.checks:
        parts.append(
            "<p class='sub'>Above: voltage, replayed with each test's measured cell temperature. Below, when the "
            "test list gives a cell (<code>like</code>) and the chamber's convection: voltage and surface "
            "temperature predicted from the measured current alone, as a study runs the cell.</p>"
        )
    if thermal:
        from .thermal import summary

        sm = summary(thermal)
        parts.append("<h2>Voltage and temperature from the current alone</h2><div class='kpi'>")
        parts.append(
            f"<div>This fit<b>{100 * sm['within_1K']:.0f}% within 1 K</b>median {sm['median_T_rmse_K']:.2f} K RMS; "
            f"{sm['median_V_rmse_mV']:.1f} mV</div>"
        )
        if "compare" in sm:
            parts.append(
                f"<div>{_e(sm['compare'])}<b>{100 * sm['compare_within_1K']:.0f}% within 1 K</b>median "
                f"{sm['compare_median_T_rmse_K']:.2f} K RMS; {sm['compare_median_V_rmse_mV']:.1f} mV</div>"
            )
        parts.append("</div>")
        head = "<tr><th>Test</th><th>Chamber</th><th>Voltage RMS</th><th>Temperature RMS</th><th>Peak error</th>"
        cmp = "compare" in thermal[0]
        if cmp:
            head += "<th>Library: voltage</th><th>temperature</th><th>peak</th>"
        parts.append(f"<table>{head}</tr>")
        for r in thermal:
            row = (
                f"<tr><td>{_e(r['file'])}</td><td class='n'>{r['ambient_C']:g} °C</td>"
                f"<td class='n'>{r['V_rmse_mV']:.1f} mV</td><td class='n'>{r['T_rmse_K']:.2f} K</td>"
                f"<td class='n'>{r['peak_error_K']:+.2f} K</td>"
            )
            if cmp:
                row += (
                    f"<td class='n'>{r['compare_V_rmse_mV']:.1f} mV</td><td class='n'>{r['compare_T_rmse_K']:.2f} K</td>"
                    f"<td class='n'>{r['compare_peak_error_K']:+.2f} K</td>"
                )
            parts.append(row + "</tr>")
        parts.append(
            "</table><p class='sub'>Voltage is scored down to the knee near empty (40% of the way up from the "
            "cut-off), where the last minutes' collapse would dominate. Peak error: predicted minus measured "
            "peak surface temperature.</p>"
        )
        parts.append(_thermal_plot(thermal))

    # 3. Values.
    parts.append(
        "<h2>Values</h2><table><tr><th>Value</th><th>Fitted</th><th>95% range</th><th>Source</th><th>What</th></tr>"
    )
    for name, e in doc["values"].items():
        rng = "" if "range_95" not in e else f"{_num(e['range_95'][0])} to {_num(e['range_95'][1])}"
        note = f"<br><span class='flag'>{_e(e['note'])}</span>" if e.get("note") else ""
        parts.append(
            f"<tr><td><code>{_e(name)}</code></td><td class='n'>{_num(e['value'])} {_e(e['unit'])}</td>"
            f"<td class='n'>{rng}</td><td><span class='tag'>{_e(e['source'])}</span></td><td>{_e(e['what'])}{note}</td></tr>"
        )
    parts.append("</table>")
    cap = doc["capacity"]
    rated = f", rated {cap['rated_Ah']} Ah ({cap['measured_vs_rated']})" if "rated_Ah" in cap else ""
    parts.append(f"<p>Capacity measured {cap['measured_Ah']:.4g} Ah{rated}.</p>")
    ident = doc["identifiability"]
    if ident["correlated_pairs"]:
        pairs = "; ".join(
            f"<code>{_e(p['values'][0])}</code> and <code>{_e(p['values'][1])}</code> ({p['correlation']:+.2f})"
            for p in ident["correlated_pairs"]
        )
        parts.append(f"<p class='flag'>These trade off against each other (the tests pin a combination): {pairs}.</p>")
    parts.append(f"<p class='sub'>{_e(ident['about_the_ranges'])}.</p>")
    if doc.get("by_temperature"):
        names = ["R0_25C", "I0_25C", "gamma", "tau_ct", "Rm_25C", "tau_m", "Rd_25C", "tau_d", "soc_a", "soc_b"]
        parts.append(
            "<h2>Values by temperature</h2><p class='sub'>Each temperature fitted on its own. PackTherm "
            "interpolates between them (in 1/T), and beyond the coldest and warmest follows the laws above. "
            "<span class='flag'>Flagged</span>: at the edge of its allowed range, or poorly determined.</p><table><tr>"
            "<th>Chamber</th><th>Cell</th>"
            + "".join(f"<th><code>{n.replace('_25C', '')}</code></th>" for n in names)
            + "</tr>"
        )
        for row in doc["by_temperature"]:
            cells = []
            for n in names:
                e = row["values"].get(n)
                if e is None:
                    cells.append("<td></td>")
                    continue
                cls = " flag" if e.get("note") else ""
                cells.append(f"<td class='n{cls}' title='{_e(e.get('note', ''))}'>{_num(e['value'])}</td>")
            parts.append(
                f"<tr><td class='n'>{row['at_C']:g} °C</td><td class='n'>{row['cell_C']:g} °C</td>"
                + "".join(cells)
                + "</tr>"
            )
        parts.append("</table>")
        if "by_T" in plots:
            parts.append(plots["by_T"])

    # 4. Validity and errors.
    parts.append("<h2>Where it is valid</h2><table>")
    rows = [
        ("Cell temperature", v.get("temperature_C"), "°C"),
        ("State of charge (pulses)", v.get("soc") and [100 * v["soc"][0], 100 * v["soc"][1]], "%"),
        ("Discharge rate", v.get("discharge_C"), "C"),
        ("Charge rate", v.get("charge_C"), "C"),
    ]
    for label, rng, unit in rows:
        txt = "not tested" if not rng else f"{rng[0]:.3g} to {rng[1]:.3g} {unit}"
        parts.append(f"<tr><th>{label}</th><td>{txt}</td></tr>")
    parts.append(f"</table><p class='sub'>{_e(v['note'])}</p>")
    parts.append(
        "<h2>Errors on what it was fitted to</h2><table><tr><th>Part</th><th>RMS</th><th>Worst</th><th>Parts</th></tr>"
    )
    for k, e in fit.errors.items():
        parts.append(
            f"<tr><td>{_e(k)}</td><td class='n'>{e['rmse_mV']:.1f} mV</td>"
            f"<td class='n'>{e['max_mV']:.0f} mV</td><td class='n'>{e['parts']}</td></tr>"
        )
    parts.append(
        "</table><p class='sub'>The model has three branches besides the instant drop: seconds (charge transfer), "
        "tens of seconds and minutes. The worst errors sit in the first tenth of a second after a step and in the "
        "collapse near empty. Below 20% state of charge the open-circuit voltage is steep, so small errors in the "
        "state of charge show up as larger voltage errors. Long tests are scored down to the knee.</p>"
    )

    # 5. Charts.
    parts.append("<h2>Open-circuit voltage</h2>")
    by_T = getattr(fit, "ocv_curves", None) or []
    extra = (
        f" At the other temperatures, from their own slow discharges, on the same state of charge "
        f"(the charge left, as a share of {fit.capacity_Ah:.3f} Ah): a cell that delivers less there reaches "
        "its cut-off at a higher state of charge. Between them the voltage is interpolated in temperature."
        if by_T
        else ""
    )
    parts.append(f"<p class='sub'>{_e(fit.ocv.method)}.{_e(extra)}</p>{plots['ocv']}")
    if "pulses" in plots:
        what = "Pulses" if fit.records.get("pulses") else "Changes in current (no pulse test)"
        parts.append(f"<h2>{what}, measured against the model</h2>{plots['pulses']}")
    if "pulses_by_T" in plots:
        what = "A pulse" if fit.records.get("pulses") else "A change in current"
        parts.append(f"<h2>{what} at each temperature, measured against the model</h2>{plots['pulses_by_T']}")
    if "steps" in plots:
        parts.append(f"<h2>Steps and rests, measured against the model</h2>{plots['steps']}")

    # 6. Warnings and provenance.
    parts.append("<h2>Data warnings</h2>")
    parts.append(
        "<ul>" + "".join(f"<li>{_e(w)}</li>" for w in doc["data_warnings"]) + "</ul>"
        if doc["data_warnings"]
        else "<p>None.</p>"
    )
    prov = doc["provenance"]
    parts.append("<h2>What went in</h2><table><tr><th>Role</th><th>File</th><th>SHA-256</th></tr>")
    for i in prov["inputs"]:
        parts.append(
            f"<tr><td>{_e(i['role'])}</td><td>{_e(i['file'])}</td><td><code>{_e(i['sha256'])}</code></td></tr>"
        )
    parts.append("</table>")
    if "dataset" in prov:
        parts.append("<p>" + "<br>".join(f"<b>{_e(k)}:</b> {_e(val)}" for k, val in prov["dataset"].items()) + "</p>")
    parts.append(
        "<table>"
        + "".join(f"<tr><th>{_e(k)}</th><td>{_e(val)}</td></tr>" for k, val in prov["settings"].items())
        + "</table>"
    )
    parts.append("</body></html>")
    return "\n".join(parts)


def write_report(path: str | Path, fit, doc: dict, thermal: list[dict] | None = None) -> Path:
    path = Path(path)
    path.write_text(report_html(fit, doc, thermal), encoding="utf-8")
    return path
