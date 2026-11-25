"""Search for module designs instead of simulating a grid (v0.6.14).

A grid study simulates every combination of the design space's lists. A search
treats them as ranges: flows, the gap and the chiller set-point take any value
between the smallest and largest listed (flows on a log scale), while the
cooling type and the filler stay choices. pymoo's NSGA-II for mixed variables
(``MixedVariableGA`` with rank-and-crowding survival) looks for designs that add
the least mass and use the least running energy (the objectives can add the
volume taken and the capacity lost) while meeting the study's limits, which are its constraints.
It judges each design at the worst-case resistance the picks are re-checked
at, so what it finds survives that re-check (``worst_case``).

The search runs at ``search.mode`` (fast by default). The best designs it
found, up to ``final_designs`` of them by non-dominated rank, are then run
again at the study's own mode and go through the usual picks and worst-case
re-check, so the results read like a grid study's.

pymoo is an optional extra: ``pip install packtherm[search]``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .design import _map, pareto_mask
from .module import SideRibbon
from .module_design import (
    KIND,
    ModuleDesign,
    ModuleStudy,
    ModuleStudyResult,
    _eval_args,
    module_study_result,
    recheck_args,
)

INSTALL_HINT = "Search needs pymoo, an optional extra: pip install 'packtherm[search]'"


@dataclass(frozen=True)
class SearchSettings:
    evaluations: int = 200  # designs the search may simulate (repeats are not simulated again)
    population: int = 20
    seed: int = 1
    mode: str = "fast"  # resolution during the search; the final designs run at the study's mode
    final_designs: int = 12  # how many of the best are run again for the picks
    # What the search minimises: mass and energy (the grid's trade-off) by default; "volume"
    # (space taken between and around the cells) and "life" (capacity lost after life_years) too.
    objectives: tuple[str, ...] = ("mass", "energy")
    # Judge designs at worst-case resistance during the search (when the study re-checks its picks
    # there), so the designs it finds survive the re-check. Nominal resistance otherwise.
    worst_case: bool = True


def _sig(x: float, digits: int = 3) -> float:
    return float(f"{x:.{digits}g}")


class Space:
    """The study's design space as search variables, and back to designs."""

    def __init__(self, study: ModuleStudy):
        self.study = study
        T_env = study.requirements.T_env_C
        self.topologies = tuple(study.topologies)
        self.fillers = tuple(study.fillers) or (None,)
        self.air = (min(study.air_flows_g_s), max(study.air_flows_g_s))
        self.coolant = (min(study.coolant_flows_g_s), max(study.coolant_flows_g_s))
        self.gaps = (min(study.gaps_mm), max(study.gaps_mm))
        usable = [c for c in study.chiller_inlets_C if c < T_env]
        self.chiller = (min(usable), max(usable)) if usable else None
        self.ribbon_gap = SideRibbon(tim=study.tim, tube=study.ribbon).min_gap_mm

    def variables(self) -> dict:
        from pymoo.core.variable import Binary, Choice, Real

        v = {
            "topology": Choice(options=list(self.topologies)),
            "filler": Choice(options=[f or "none" for f in self.fillers]),
            "flow": Real(bounds=(0.0, 1.0)),  # position in the topology's flow range, log scale
        }
        if self.gaps[1] > self.gaps[0]:
            v["gap"] = Real(bounds=self.gaps)
        if self.chiller is not None and any(KIND[t] == "liquid" for t in self.topologies):
            v["chilled"] = Binary()
            if self.chiller[1] > self.chiller[0]:
                v["chiller"] = Real(bounds=self.chiller)
        return v

    def design(self, x: dict) -> ModuleDesign:
        """A canonical design: values rounded, and parts a topology doesn't use dropped."""
        topo = str(x["topology"])
        filler = None if str(x["filler"]) == "none" else str(x["filler"])
        gap = round(float(x["gap"]), 1) if "gap" in x else self.gaps[0]
        if topo == "ribbon":
            gap = max(gap, self.ribbon_gap)
        if topo == "none":
            return ModuleDesign("none", 0.0, None, filler, gap)
        lo, hi = self.air if topo == "air" else self.coolant
        flow = _sig(lo * (hi / lo) ** float(x["flow"]))
        if topo == "air":
            return ModuleDesign("air", flow, None, None, gap)  # air needs open gaps
        inlet = None
        if self.chiller is not None and bool(x.get("chilled", False)):
            inlet = round(2 * float(x["chiller"])) / 2 if "chiller" in x else self.chiller[0]
        return ModuleDesign(topo, flow, inlet, filler, gap)


OBJECTIVES = {  # name -> the row's column, as a cost (lower is better)
    "mass": lambda r: r["mass_overhead_pct"],
    "energy": lambda r: r["aux_energy_pct"],
    "volume": lambda r: r["volume_overhead_pct"],
    "life": lambda r: 100.0 - r["capacity_after_pct"],
}


def objectives(row: dict, names: tuple[str, ...]) -> list[float]:
    f = [OBJECTIVES[n](row) for n in names]
    return [float(v) if np.isfinite(v) else 1e6 for v in f]


def constraints(row: dict, study: ModuleStudy) -> list[float]:
    """One per limit, <= 0 when met; positive by how far a failed limit is missed.

    They agree with the row's fail_reason: a limit counts as failed exactly when
    its word is there.
    """
    fails = set(row["fail_reason"].split(" · ")) - {""}
    req = study.requirements

    def g(word: str, margin: float) -> float:
        margin = margin if np.isfinite(margin) else 1.0
        return max(margin, 1e-6) if word in fails else min(margin, 0.0)

    cap_min = study.capacity_min_pct
    return [
        g("hot", (row["T_peak_C"] - row["T_limit_C"]) / 5.0),
        g("uneven", (row["dT_cell_C"] - req.dT_cell_max_C) / 5.0),
        g("slow", 1.0),
        g("spread", (row["cell_to_cell_K"] - row["cell_to_cell_limit_K"]) / 5.0),
        g("short", 1.0),
        g("ages", (cap_min - row["capacity_after_pct"]) / 10.0 if cap_min is not None else 0.0),
    ]


@dataclass
class SearchLog:
    settings: SearchSettings
    history: pd.DataFrame  # every design the search simulated, in order, at the search's mode
    evaluations: int  # designs pymoo asked for (repeats included)
    generations: int
    worst_case: bool  # the search judged designs at worst-case resistance


def best_designs(rows: list[dict], n: int, names: tuple[str, ...]) -> list[int]:
    """Up to n rows: feasible ones by non-dominated rank, else the closest to feasible."""
    feas = [i for i, r in enumerate(rows) if r["feasible"]]
    if not feas:
        # How far each misses, summed over limits; the three nearest are run again.
        miss = [sum(max(0.0, v) for v in r["_G"]) for r in rows]
        return sorted(range(len(rows)), key=lambda i: miss[i])[: min(3, n)]
    F = np.array([objectives(rows[i], names) for i in feas])
    left, out = list(range(len(feas))), []
    while left and len(out) < n:
        sub = F[left]
        front = _pareto(sub)
        layer = [left[k] for k in np.flatnonzero(front)]
        layer.sort(key=lambda k: F[k, 0])
        room = n - len(out)
        if len(layer) > room:  # spread the picks along the layer, lightest to heaviest
            layer = [layer[int(j)] for j in np.round(np.linspace(0, len(layer) - 1, room))]
        out += [feas[k] for k in layer]
        left = [k for j, k in enumerate(left) if not front[j]]
    return out


def _pareto(F: np.ndarray) -> np.ndarray:
    if F.shape[1] == 1:
        return F[:, 0] == F[:, 0].min()
    if F.shape[1] == 2:
        return pareto_mask(F[:, 0], F[:, 1])
    keep = np.ones(len(F), bool)
    for i in range(len(F)):
        dominated = np.all(F <= F[i], axis=1) & np.any(F < F[i], axis=1)
        keep[i] = not dominated.any()
    return keep


def run_module_search(
    study: ModuleStudy, settings: SearchSettings | None = None, workers: int | None = None, progress=None
) -> ModuleStudyResult:
    """Search the design space, then run the best designs again at the study's mode for the picks.

    progress(stage, done, total) is called with stage "search", then "designs"
    for the final runs and "re-check" for the worst-case ones.
    """
    settings = settings or SearchSettings()
    try:
        from pymoo.core.mixed import MixedVariableGA
        from pymoo.core.problem import ElementwiseProblem
        from pymoo.operators.survival.rank_and_crowding import RankAndCrowding
        from pymoo.optimize import minimize
    except ImportError as e:  # pragma: no cover - depends on the install
        raise RuntimeError(INSTALL_HINT) from e

    space = Space(study)
    s_study = replace(study, mode=settings.mode, dt=None) if settings.mode != study.mode else study
    worst = settings.worst_case and study.R0_worst > study.cell.R0_25C

    def args(d: ModuleDesign) -> tuple:
        return (s_study, d, study.R0_worst, True) if worst else (s_study, d)

    cache: dict[ModuleDesign, dict] = {}
    order: list[ModuleDesign] = []
    asked = [0]

    def simulate(designs: list[ModuleDesign]) -> None:
        todo = list(dict.fromkeys(d for d in designs if d not in cache))
        if not todo:
            return
        rows = _map(_eval_args, [args(d) for d in todo], workers)
        for d, r in zip(todo, rows):
            r["_G"] = constraints(r, study)
            cache[d] = r
            order.append(d)
        if progress:
            progress("search", min(len(order), settings.evaluations), settings.evaluations)

    def runner(f, X):
        asked[0] += len(X)
        simulate([space.design(x) for x in X])
        return [f(x) for x in X]

    names = tuple(settings.objectives)
    if "life" in names and study.life_years <= 0:
        raise ValueError("search objective 'life' needs options.life_years above 0")

    class Problem(ElementwiseProblem):
        def __init__(self):
            super().__init__(vars=space.variables(), n_obj=len(names), n_ieq_constr=6, elementwise_runner=runner)

        def _evaluate(self, x, out, *args, **kwargs):
            r = cache[space.design(x)]
            out["F"] = objectives(r, names)
            out["G"] = r["_G"]

    algo = MixedVariableGA(pop_size=settings.population, survival=RankAndCrowding())
    res = minimize(Problem(), algo, ("n_evals", settings.evaluations), seed=settings.seed, verbose=False)

    searched = [cache[d] for d in order]
    history = pd.DataFrame([{k: v for k, v in r.items() if k != "_G"} for r in searched])
    history.insert(0, "simulated", np.arange(1, len(history) + 1))
    idx = best_designs(searched, settings.final_designs, names)
    final = [order[i] for i in idx]

    def report(stage):
        return (lambda done, total: progress(stage, done, total)) if progress else None

    if s_study is study and not worst:
        rows = [{k: v for k, v in searched[i].items() if k != "_G"} for i in idx]
    else:  # at the study's mode and nominal resistance, like a grid study's rows
        rows = _map(_eval_args, [(study, d) for d in final], workers, report("designs"))

    def recheck(ix):
        return _map(_eval_args, [recheck_args(study, final[i]) for i in ix], workers, report("re-check"))

    result = module_study_result(study, rows, recheck)
    result.search = SearchLog(settings, history, asked[0], int(getattr(res.algorithm, "n_gen", 0) or 0), worst)
    return result


def search_note(log: SearchLog, study: ModuleStudy) -> str:
    s = log.settings
    at = f" at worst-case R0 = {study.R0_worst * 1e3:.0f} mOhm" if log.worst_case else ""
    return (
        f"NOTE: searched with NSGA-II (pymoo): {len(log.history)} designs simulated in {s.mode} mode{at} over "
        f"{log.generations} generations (seed {s.seed}), minimising {', '.join(s.objectives)}; the best {len_text(s.final_designs)} run again in "
        f"{study.mode} mode at the cell's resistance and re-checked as a grid study's picks are. Flows, gap and chiller set-point are taken "
        "anywhere between the smallest and largest listed. A search can miss designs; a different seed or a "
        "larger budget is the check."
    )


def len_text(n: int) -> str:
    return f"{n} or fewer" if n > 1 else "one"


__all__ = ["INSTALL_HINT", "SearchLog", "SearchSettings", "Space", "run_module_search", "search_note"]
