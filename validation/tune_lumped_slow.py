"""Tune the lumped model's slow branch (Cell.slow_share; v0.6.11), and check it.

A lumped cell's heat is I^2 R with R a DC resistance read over seconds (PackTherm
states its cells' at 10 s, 1.5C, mid charge, 25 degC). The losses that keep
growing over minutes (diffusion) are missed: a lumped model made 22-64 % of its
fitted circuit's heat on a steady discharge. The slow branch adds a first-order
overpotential, resistance slow_share x R0 (own Arrhenius, same SOC factor) and
time constant slow_tau_s, which builds under steady current and fades in rests.

Tuning, per chemistry: the fitted circuits of the PF, 30T and HG2 (NMC/NCA) and
of the A123 (LFP) are run electrically, at a held temperature, over steady
discharges (0.5, 1 and 2C), 2C pulses (10 s on, 20 s off), a measured drive cycle
(the Warwick M50's, scaled to the cell) and a 0.5C charge from 10 %, at 25, 10, 0
and -10 degC (no charging below 0 degC). A lumped model of each (R0 = the
circuit's 10 s DC resistance, Ea 20 kJ/mol, the default SOC factor, as a
datasheet cell gets) is run on the circuit's own current; the cumulative heats
are compared at a quarter, half, three quarters and the end of each run, and
(slow_share, slow_tau_s, slow_Ea) chosen to minimise the mean squared log ratio.

Check, never tuned on: the M50's circuit over the same duties, and the lumped M50
(the datasheet's 30 mOhm) against the measured 1C discharges with a core
thermocouple (validation/data/lg_m50_core).

Usage:  python validation/tune_lumped_slow.py [--json PATH]     (about 20 min)
"""

from __future__ import annotations

import gzip
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from packtherm.cells import CELLS, LUMPED_SLOW, default_soc_factor
from packtherm.ecm import ECMState
from packtherm.fitting.cellfile import dc_resistance

HERE = Path(__file__).parent
R_GAS, T_REF, DT = 8.314462618, 298.15, 2.0
FAMILIES = {"NMC": ("PF", "30T", "HG2"), "LFP": ("A123",)}
TEMPS_C = (25, 10, 0, -10)


def _drive() -> np.ndarray:
    rows = gzip.decompress((HERE / "data" / "lg_m50_drive" / "run_A.csv.gz").read_bytes()).decode().splitlines()[1:]
    return np.array([[float(x) for x in r.split(",")[:2]] for r in rows])


def duties(cap: float, drv: np.ndarray) -> dict:
    sc = cap / 4.85  # the M50 drive cycle, in C-rate
    return {
        "0.5C": (lambda x: 0.5 * cap, 7920.0, 1.0),
        "1C": (lambda x: 1.0 * cap, 3960.0, 1.0),
        "2C": (lambda x: 2.0 * cap, 1980.0, 1.0),
        "pulses": (lambda x: 2.0 * cap if (x % 30) < 10 else 0.0, 10800.0, 1.0),
        "drive": (lambda x: float(np.interp(x, drv[:, 0], drv[:, 1])) * sc, float(drv[-1, 0]), 1.0),
        "charge 0.5C": (lambda x: -0.5 * cap, 4608.0, 0.1),
    }


def circuit_trace(cell, prof, T: float, dur: float, soc0: float) -> np.ndarray:
    """(I, SOC, heat) per step of the fitted circuit at a held temperature."""
    e, cap = cell.ecm, cell.capacity_Ah
    h0 = 1.0 if soc0 > 0.99 else 0.0
    st, soc, t, out = ECMState(h=h0, s=h0), soc0, 0.0, []
    while t < dur:
        I = prof(t)
        I_eff, V = st.apply(e, I, soc - 0.5 * I * DT / 3600 / cap, T, DT)
        sm = soc - 0.5 * I_eff * DT / 3600 / cap
        out.append((I_eff, sm, I_eff * (e.ocv(sm, T) + 0.5 * e.hyst_V(T) - V)))
        soc -= I_eff * DT / 3600 / cap
        t += DT
        if st.cutoff or (I < 0 and abs(I_eff) < 0.02 * cap and t > 600):
            break
    return np.array(out)


def lumped_heat(R0: float, a: np.ndarray, T: float, share: float, tau: float, Ea_s: float, Ea: float = 20e3):
    I, soc = a[:, 0], a[:, 1]
    f = np.array([default_soc_factor(s) for s in soc])
    q = I**2 * R0 * math.exp(Ea / R_GAS * (1 / T - 1 / T_REF)) * f
    if share:
        Rs = share * R0 * math.exp(Ea_s / R_GAS * (1 / T - 1 / T_REF)) * f
        d, v = math.exp(-DT / tau), 0.0
        for i in range(len(I)):
            target = I[i] * Rs[i]
            v_mean = target + (v - target) * (1 - d) * tau / DT
            v = target + (v - target) * d
            q[i] += I[i] * v_mean
    return q


def log_errors(traces: dict, R0: dict, p) -> tuple[np.ndarray, dict]:
    share, log_tau, Ea_s = p
    errs, ends = [], {}
    for (key, duty, Tc), a in traces.items():
        Cc = np.cumsum(a[:, 2])
        Cl = np.cumsum(lumped_heat(R0[key], a, Tc + 273.15, share, math.exp(log_tau), Ea_s))
        n = len(Cc)
        errs += [math.log(Cl[j] / Cc[j]) for j in (n // 4, n // 2, 3 * n // 4, n - 1) if Cc[j] > 0 and Cl[j] > 0]
        ends[f"{key} {duty} {Tc} degC"] = float(Cl[-1] / Cc[-1])
    return np.array(errs), ends


def traces_for(keys, drv) -> dict:
    out = {}
    for key in keys:
        c = CELLS[key]
        for Tc in TEMPS_C:
            for d, (prof, dur, s0) in duties(c.capacity_Ah, drv).items():
                if d.startswith("charge") and Tc < 0:
                    continue
                out[(key, d, Tc)] = circuit_trace(c, prof, Tc + 273.15, dur, s0)
    return out


def m50_measured() -> list[dict]:
    """The lumped M50 (datasheet 30 mOhm) on the measured 1C discharges, with and without the branch."""
    sys.path.insert(0, str(HERE))
    import check_m50_core as core

    from packtherm.cells import params_for_cell
    from packtherm.electrothermal import ElectroThermalLoad
    from packtherm.model import simulate

    h = json.loads((HERE / "m50_core_check.json").read_text())["library (1.2 W/(m K)), measured heat"]["h_W_m2K"]
    names = [m["name"] for m in json.loads((core.DATA / "manifest.json").read_text())["tests"]]
    rows = []
    for n in names:
        test = core.load(n)
        rec = test["rec"]
        t = rec.t - rec.t[0]
        row = {"test": n, "surface_rise_meas_K": float(rec.temperature_C.max() - test["ambient_C"])}
        for label, share in (("no branch", 0.0), ("branch", None)):
            cell = CELLS["M50-LUMPED"] if share is None else replace(CELLS["M50-LUMPED"], slow_share=share)
            P = params_for_cell(cell, pcm_thickness=0.0, case_thickness=0.0)
            P = P.with_(T_initial=float(rec.temperature_C[0]) + 273.15, solver=replace(P.solver, dt=2.0, store_every=10**6))
            load = ElectroThermalLoad(cell, lambda x, t=t, i=rec.current_A: float(np.interp(x, t, i)), soc0=1.0)
            res = simulate(P, duration=float(t[-1]), h=h, T_env=test["ambient_C"] + 273.15, load=load)
            s = np.interp(t, res.t, res.T_surface - 273.15)
            row[f"{label}: surface_rise_K"] = float(s.max() - test["ambient_C"])
            row[f"{label}: surface_rmse_K"] = float(np.sqrt(np.mean((s - rec.temperature_C) ** 2)))
            if test["core"] is not None and np.isfinite(test["core"]).any():
                co = np.interp(t, res.t, res.T_max - 273.15)
                row[f"{label}: core_rmse_K"] = float(np.sqrt(np.nanmean((co - test["core"]) ** 2)))
        rows.append(row)
    return rows


def main() -> dict:
    drv = _drive()
    out: dict = {"families": {}}
    for fam, keys in FAMILIES.items():
        tr = traces_for(keys, drv)
        R0 = {k: dc_resistance(CELLS[k].ecm, capacity_Ah=CELLS[k].capacity_Ah) for k in keys}
        before, ends0 = log_errors(tr, R0, (0.0, 0.0, 0.0))
        best = None
        for s0 in (0.5, 1.0, 1.5):
            for lt0 in (math.log(60), math.log(300), math.log(1200)):
                r = minimize(
                    lambda p, tr=tr, R0=R0: float(np.mean(log_errors(tr, R0, p)[0] ** 2)),
                    [s0, lt0, 30e3],
                    method="Nelder-Mead",
                    options={"maxiter": 300, "xatol": 1e-3, "fatol": 1e-6},
                )
                best = r if best is None or r.fun < best.fun else best
        used = LUMPED_SLOW[fam]
        p_used = (used["slow_share"], math.log(used["slow_tau_s"]), used["slow_Ea_R"])
        after, ends = log_errors(tr, R0, p_used)
        out["families"][fam] = {
            "cells": list(keys),
            "fitted": {"slow_share": best.x[0], "slow_tau_s": math.exp(best.x[1]), "slow_Ea_R": best.x[2]},
            "used": used,
            "lumped_over_circuit_without": {"min": min(ends0.values()), "max": max(ends0.values())},
            "lumped_over_circuit_with": {"min": min(ends.values()), "max": max(ends.values())},
            "rms_log_error": {"without": float(np.sqrt(np.mean(before**2))), "with": float(np.sqrt(np.mean(after**2)))},
            "runs": ends,
        }
        print(f"{fam}: fitted share {best.x[0]:.3f}, tau {math.exp(best.x[1]):.0f} s, Ea {best.x[2] / 1e3:.1f} kJ/mol; "
              f"lumped/circuit {min(ends0.values()):.2f}-{max(ends0.values()):.2f} -> {min(ends.values()):.2f}-{max(ends.values()):.2f}")
    # Never tuned on: the M50's circuit, and the measured M50.
    tr = traces_for(("M50",), drv)
    R0 = {"M50": dc_resistance(CELLS["M50"].ecm, capacity_Ah=CELLS["M50"].capacity_Ah)}
    p = LUMPED_SLOW["NMC"]
    _, ends = log_errors(tr, R0, (p["slow_share"], math.log(p["slow_tau_s"]), p["slow_Ea_R"]))
    out["check_m50_circuit"] = ends
    print(f"M50 circuit (check): lumped/circuit {min(ends.values()):.2f}-{max(ends.values()):.2f}")
    out["check_m50_measured"] = m50_measured()
    for r in out["check_m50_measured"]:
        print(f"  {r['test']}: surface rise {r['no branch: surface_rise_K']:.1f} -> {r['branch: surface_rise_K']:.1f} K "
              f"(measured {r['surface_rise_meas_K']:.1f})")
    return out


if __name__ == "__main__":
    res = main()
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
