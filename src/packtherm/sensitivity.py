"""Which inputs matter most for one design (v0.6.15).

Morris screening (SALib): each uncertain input moves across its range one at a
time along random trajectories, and its elementary effects on each result are
averaged. ``mu_star`` (the mean absolute effect, in the result's own units: about
how much the result changes as the input goes from the low to the high end of
its range) ranks the inputs; ``sigma`` (the spread of the effects) is large when an input's
effect depends on the others (interaction or a curve). About
``trajectories x (inputs + 1)`` simulations.

The design is either named in the study file or one of a grid study's picks
(``balanced`` by default), in which case the grid is run first.

SALib is an optional extra: ``pip install packtherm[sensitivity]``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from .design import _map
from .module_design import KIND, ModuleDesign, ModuleStudy, evaluate_module_design

INSTALL_HINT = "Sensitivity needs SALib, an optional extra: pip install 'packtherm[sensitivity]'"

# name: (label, unit of the range, default range, kind) ; kind "add" shifts, "scale" multiplies,
# "share" goes from the cell's resistance (0) to the study's worst case (1).
FACTORS: dict[str, tuple[str, str, tuple[float, float], str]] = {
    "ambient": ("Ambient temperature", "K", (-5.0, 5.0), "add"),
    "resistance": ("Cell resistance (nominal to worst case)", "share", (0.0, 1.0), "share"),
    "cell_heat_capacity": ("Cell heat capacity", "x", (0.9, 1.1), "scale"),
    "cell_conductivity": ("Cell thermal conductivity", "x", (0.7, 1.3), "scale"),
    "entropic_heat": ("Reversible heat (dU/dT)", "x", (0.5, 1.5), "scale"),
    "tim_conductivity": ("Interface (TIM) conductivity", "x", (0.5, 1.5), "scale"),
    "heat_transfer": ("Air or coolant heat transfer", "x", (0.7, 1.3), "scale"),
    "flow": ("Air or coolant flow", "x", (0.8, 1.2), "scale"),
    "chiller_inlet": ("Chiller inlet temperature", "K", (-3.0, 3.0), "add"),
}

OUTPUTS = {
    "T_peak_C": "Peak temperature (degC)",
    "dT_cell_C": "In-cell spread (K)",
    "cell_to_cell_K": "Cell-to-cell spread (K)",
    "aux_energy_pct": "Running energy (% of energy moved)",
    "capacity_after_pct": "Capacity left (%)",
}


@dataclass(frozen=True)
class SensitivitySettings:
    design: str | dict = "balanced"  # a pick of the grid study, or {topology, flow_g_s, ...}
    trajectories: int = 10
    levels: int = 4
    seed: int = 1
    mode: str = "fast"
    factors: tuple[str, ...] | None = None  # None: every input that applies to the design
    ranges: dict = field(default_factory=dict)  # name -> (low, high), replacing the default


class ScaledDUdT:
    """dU/dT times a factor; a class, not a lambda, so worker processes can take it."""

    def __init__(self, f, scale: float):
        self.f, self.scale = f, scale

    def __call__(self, soc: float) -> float:
        return self.scale * self.f(soc)


def applicable(design: ModuleDesign) -> list[str]:
    """The inputs that can change this design's results."""
    kind = KIND[design.topology]
    out = ["ambient", "resistance", "cell_heat_capacity", "cell_conductivity", "entropic_heat"]
    if design.topology in ("bottom", "ribbon"):
        out.append("tim_conductivity")
    if kind in ("air", "liquid"):
        out += ["heat_transfer", "flow"]
    if kind == "liquid" and design.inlet_C is not None:
        out.append("chiller_inlet")
    return out


def perturbed(study: ModuleStudy, design: ModuleDesign, x: dict[str, float]) -> tuple:
    """The study, design and resistance with the inputs moved by x (each in its range's units)."""
    cell = study.cell
    cell_kw = {}
    if "cell_heat_capacity" in x:
        cell_kw["cp"] = cell.cp * x["cell_heat_capacity"]
    if "cell_conductivity" in x:
        cell_kw["k_radial"] = cell.k_radial * x["cell_conductivity"]
        if cell.k_axial is not None:
            cell_kw["k_axial"] = cell.k_axial * x["cell_conductivity"]
    if "entropic_heat" in x:
        cell_kw["dUdT"] = ScaledDUdT(cell.dUdT, x["entropic_heat"])
    st = replace(study, cell=replace(cell, **cell_kw)) if cell_kw else study
    if "ambient" in x:
        st = replace(st, requirements=replace(st.requirements, T_env_C=st.requirements.T_env_C + x["ambient"]))
    if "tim_conductivity" in x:
        st = replace(st, tim=replace(st.tim, k=st.tim.k * x["tim_conductivity"]))
    if "heat_transfer" in x:
        f = x["heat_transfer"]
        st = replace(
            st, coolant=replace(st.coolant, h_scale=st.coolant.h_scale * f), air=replace(st.air, h_ref=st.air.h_ref * f)
        )
    d = design
    if "flow" in x and d.flow_g_s > 0:
        d = replace(d, flow_g_s=d.flow_g_s * x["flow"])
    if "chiller_inlet" in x and d.inlet_C is not None:
        d = replace(d, inlet_C=d.inlet_C + x["chiller_inlet"])
    R0 = None
    if "resistance" in x:
        R0 = cell.R0_25C + x["resistance"] * (study.R0_worst - cell.R0_25C)
    return st, d, R0


def _eval(args):
    study, design, x = args
    st, d, R0 = perturbed(study, design, x)
    return evaluate_module_design(st, d, R0=R0, inlet=True)


def design_from_row(row) -> ModuleDesign:
    filler = row["filler"]
    if not isinstance(filler, str) or filler in ("", "none"):
        filler = None
    inlet = float(row["inlet_C"]) if bool(row.get("chilled", False)) else None
    return ModuleDesign(str(row["topology"]), float(row["flow_g_s_per_cell"]), inlet, filler, float(row["gap_mm"]))


def design_from_spec(d: dict) -> ModuleDesign:
    filler = d.get("filler")
    return ModuleDesign(
        d["topology"],
        float(d.get("flow_g_s", 0.0) or 0.0) if d["topology"] != "none" else 0.0,
        d.get("chiller_C"),
        None if filler in (None, "none") else filler,
        float(d.get("gap_mm", 2.0)),
    )


@dataclass
class SensitivityResult:
    study: ModuleStudy
    settings: SensitivitySettings
    design: ModuleDesign
    design_label: str
    factors: list[str]
    bounds: list[tuple[float, float]]
    samples: pd.DataFrame  # every simulation: the inputs and the results
    ranking: pd.DataFrame  # output, factor, mu_star, mu_star_conf, sigma, rank
    grid: object = None  # the grid study's result when the design was one of its picks

    def summary(self) -> str:
        head = (
            f"Sensitivity of {self.design_label} ({len(self.samples)} simulations, Morris, "
            f"{self.settings.trajectories} trajectories, {self.settings.mode} mode)"
        )
        lines = [head]
        for out, label in OUTPUTS.items():
            sub = self.ranking[self.ranking.output == out]
            if sub.empty or not np.isfinite(sub.mu_star).any():
                continue
            top = sub.sort_values("mu_star", ascending=False).head(3)
            parts = [f"{FACTORS[r.factor][0].lower()} {r.mu_star:.2g}" for r in top.itertuples()]
            lines.append(f"{label}: " + ", ".join(parts))
        return "\n".join(lines)


def run_sensitivity(
    study: ModuleStudy, settings: SensitivitySettings | None = None, workers: int | None = None, progress=None
) -> SensitivityResult:
    settings = settings or SensitivitySettings()
    try:
        from SALib.analyze import morris as morris_analyze
        from SALib.sample import morris as morris_sample
    except ImportError as e:  # pragma: no cover - depends on the install
        raise RuntimeError(INSTALL_HINT) from e

    grid = None
    if isinstance(settings.design, str):
        from .module_design import run_module_study

        def report(stage, done, total):  # the grid's designs, then its re-check
            if progress:
                progress(f"grid {stage}", done, total)

        grid = run_module_study(study, workers=workers, progress=report)
        if settings.design not in grid.picks:
            raise ValueError(f"the grid study has no {settings.design!r} pick (no feasible design?)")
        row = grid.picks[settings.design]
        design, label = design_from_row(row), f"{row['design']} ({settings.design})"
    else:
        design = design_from_spec(settings.design)
        label = _label(design)

    names = list(settings.factors) if settings.factors else applicable(design)
    names = [n for n in names if n in applicable(design)]
    if len(names) < 2:
        raise ValueError("sensitivity needs at least two inputs that apply to the design")
    bounds = [tuple(settings.ranges.get(n, FACTORS[n][2])) for n in names]
    problem = {"num_vars": len(names), "names": names, "bounds": [list(b) for b in bounds]}
    X = morris_sample.sample(problem, settings.trajectories, num_levels=settings.levels, seed=settings.seed)

    s_study = replace(study, mode=settings.mode, dt=None) if settings.mode != study.mode else study
    xs = [dict(zip(names, map(float, row))) for row in X]

    def report_s(done, total):
        if progress:
            progress("sensitivity", done, total)

    rows = _map(_eval, [(s_study, design, x) for x in xs], workers, report_s)

    samples = pd.DataFrame(X, columns=names)
    for out in OUTPUTS:
        samples[out] = [r.get(out, np.nan) for r in rows]
    samples["feasible"] = [r["feasible"] for r in rows]
    samples["fail_reason"] = [r["fail_reason"] for r in rows]

    ranking = []
    for out in OUTPUTS:
        Y = samples[out].to_numpy(float)
        if not np.all(np.isfinite(Y)):
            continue  # e.g. no life estimate, or no inlet cell
        Si = morris_analyze.analyze(problem, X, Y, num_levels=settings.levels, seed=settings.seed)
        for i, n in enumerate(names):
            ranking.append(
                {
                    "output": out,
                    "factor": n,
                    "mu_star": float(Si["mu_star"][i]),
                    "mu_star_conf": float(Si["mu_star_conf"][i]),
                    "sigma": float(Si["sigma"][i]),
                }
            )
    ranking = pd.DataFrame(ranking)
    if not ranking.empty:
        ranking["rank"] = ranking.groupby("output").mu_star.rank(ascending=False, method="min").astype(int)
    return SensitivityResult(study, settings, design, label, names, bounds, samples, ranking, grid)


def _label(d: ModuleDesign) -> str:
    parts = [d.topology]
    if d.topology != "none":
        parts.append(f"{d.flow_g_s:g} g/s")
    if d.inlet_C is not None:
        parts.append(f"chiller {d.inlet_C:g} degC")
    parts.append(f"{d.gap_mm:g} mm gap")
    parts.append(d.filler or "no filler")
    return ", ".join(parts)


def plot(result: SensitivityResult, path) -> None:
    """One panel per result: each input's mean absolute effect (mu*), largest at the top."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    outs = [o for o in OUTPUTS if o in set(result.ranking.output)]
    fig, axes = plt.subplots(len(outs), 1, figsize=(7, 1.0 + 0.32 * len(result.factors) * len(outs)), squeeze=False)
    for ax, out in zip(axes[:, 0], outs):
        sub = result.ranking[result.ranking.output == out].sort_values("mu_star")
        y = np.arange(len(sub))
        ax.barh(y, sub.mu_star, xerr=sub.mu_star_conf, color="#2a6f97", ecolor="#7a8794", height=0.6)
        ax.set_yticks(y, [FACTORS[f][0] for f in sub.factor], fontsize=8)
        ax.set_title(OUTPUTS[out], fontsize=9, loc="left")
        ax.tick_params(axis="x", labelsize=8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.grid(axis="x", color="#e5e5e5", linewidth=0.6)
        ax.set_axisbelow(True)
    axes[-1, 0].set_xlabel("Change in the result across the input's range (Morris mu*, mean absolute effect)", fontsize=8)
    fig.suptitle(f"Which inputs matter most: {result.design_label}", fontsize=10, x=0.02, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


__all__ = ["FACTORS", "INSTALL_HINT", "OUTPUTS", "SensitivityResult", "SensitivitySettings", "run_sensitivity"]
