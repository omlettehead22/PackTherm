"""The LG M50 against its own core thermocouple (v0.6.9).

The library's M50 is run on the Warwick 1C discharges (validation/data/lg_m50_core,
prepared by prepare_m50_core.py) and its core and surface temperatures are set
against the thermocouples in and on the cell. The chamber's convection h is
calibrated on one test's surface alone (VP010, cycle 2); everything else is a
check. Two ways of making the heat:

- "measured heat": I (OCV - V) with V as measured, so only the cell's thermal
  model is tested (its conductivity, heat capacity and the chamber's h);
- "predicted": the cell's circuit makes the voltage and the heat from the
  current alone, as in a study.

And two radial conductivities for the jelly roll: the library's (1.2 W/(m K))
and the tenth of it the 30T and HG2 fits allowed (BACKLOG item 5). The v0.6.8
circuit (M50-DERIVED, before its resistance was scaled to the measured pulses,
fit_m50_scale.py) is run in "predicted" mode too, for comparison.

Usage:  python validation/check_m50_core.py   (prints a table; --json writes the results)
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

from packtherm.cells import CELLS, params_for_cell
from packtherm.electrothermal import ElectroThermalLoad, MeasuredHeatLoad
from packtherm.model import simulate
from packtherm.testdata import load_test_data

DATA = Path(__file__).parent / "data" / "lg_m50_core"
KELVIN = 273.15
CALIBRATION = "VP010_cycle2"
K_RADIAL = {"library (1.2 W/(m K))": None, "a tenth (0.12 W/(m K))": 0.1}


def load(name: str) -> dict:
    """A prepared test: the record PackTherm reads, and the core thermocouple read beside it."""
    import gzip

    rec = load_test_data(DATA / f"{name}.csv.gz")
    rows = [r.split(",") for r in gzip.decompress((DATA / f"{name}.csv.gz").read_bytes()).decode().splitlines()[1:]]
    t_file = np.array([float(r[0]) for r in rows])
    core_file = np.array([float(r[4]) if r[4] else np.nan for r in rows])
    core = np.interp(rec.t, t_file, core_file)  # on the reader's clock (it drops repeated samples)
    meta = next(m for m in json.loads((DATA / "manifest.json").read_text())["tests"] if m["name"] == name)
    return {"name": name, "rec": rec, "core": core, **meta}


def run(test: dict, cell, h: float, mode: str, dt: float = 2.0) -> dict:
    """Simulate one test; the model's surface and core (its hottest node) on the test's clock."""
    rec = test["rec"]
    t = rec.t - rec.t[0]
    P = params_for_cell(cell, pcm_thickness=0.0, case_thickness=0.0)
    P = P.with_(T_initial=float(rec.temperature_C[0]) + KELVIN, solver=replace(P.solver, dt=dt, store_every=10_000))
    if mode == "measured heat":
        load_ = MeasuredHeatLoad(t, rec.current_A, rec.voltage_V, cell.ecm.ocv, cell.capacity_Ah, soc0=1.0, dUdT=cell.dUdT)
    else:
        c = replace(cell, ecm=replace(cell.ecm, V_min=-1e9, V_max=1e9))  # the tester's limits are in the record
        load_ = ElectroThermalLoad(c, lambda x: float(np.interp(x, t, rec.current_A)), soc0=1.0)
    res = simulate(P, duration=float(t[-1]), h=h, T_env=test["ambient_C"] + KELVIN, load=load_)
    out = {
        "t": t,
        "surface": np.interp(t, res.t, res.T_surface - KELVIN),
        "core": np.interp(t, res.t, res.T_max - KELVIN),
    }
    if mode == "predicted":
        a = load_.arrays()
        out["V"] = np.interp(t, a["t"], a["V"])
    return out


def scores(test: dict, sim: dict) -> dict:
    rec = test["rec"]
    Ts, Tc = rec.temperature_C, test["core"]
    on = rec.current_A > 0.5  # the discharge
    end = int(np.flatnonzero(on)[-1])
    row = {
        "test": test["name"],
        "surface_rmse_K": float(np.sqrt(np.mean((sim["surface"] - Ts) ** 2))),
        "surface_rise_meas_K": float(Ts.max() - test["ambient_C"]),
        "surface_rise_model_K": float(sim["surface"].max() - test["ambient_C"]),
        "core_minus_surface_model_K": float(sim["core"][end] - sim["surface"][end]),
    }
    if np.isfinite(Tc).any():
        row |= {
            "core_rmse_K": float(np.sqrt(np.nanmean((sim["core"] - Tc) ** 2))),
            "core_rise_meas_K": float(np.nanmax(Tc) - test["ambient_C"]),
            "core_rise_model_K": float(sim["core"].max() - test["ambient_C"]),
            "core_minus_surface_meas_K": float(Tc[end] - Ts[end]),
        }
    if "V" in sim:
        row["V_rmse_mV"] = float(1e3 * np.sqrt(np.mean((sim["V"][on] - rec.voltage_V[on]) ** 2)))
    return row


def calibrate(test: dict, cell, mode: str) -> float:
    """The chamber's h on the surface alone."""
    from scipy.optimize import minimize_scalar

    def cost(log_h: float) -> float:
        s = run(test, cell, float(np.exp(log_h)), mode, dt=5.0)
        return float(np.mean((s["surface"] - test["rec"].temperature_C) ** 2))

    r = minimize_scalar(cost, bounds=(np.log(3.0), np.log(100.0)), method="bounded", options={"xatol": 0.01})
    return float(np.exp(r.x))


def main() -> dict:
    names = [m["name"] for m in json.loads((DATA / "manifest.json").read_text())["tests"]]
    tests = {n: load(n) for n in names}
    base = CELLS["M50"]
    configs = [(label, base if share is None else replace(base, k_radial=base.k_radial * share), mode)
               for label, share in K_RADIAL.items() for mode in ("measured heat", "predicted")]
    configs.append(("v0.6.8 derived circuit, library k", CELLS["M50-DERIVED"], "predicted"))
    results = {}
    for label, cell, mode in configs:
        if True:
            h = calibrate(tests[CALIBRATION], cell, "measured heat")
            rows = [scores(tests[n], run(tests[n], cell, h, mode)) | {"role": "calibration" if n == CALIBRATION else "check"} for n in names]
            results[f"{label}, {mode}"] = {"h_W_m2K": h, "k_radial": cell.k_radial, "rows": rows}
            print(f"\n== {label}, heat {mode}: h {h:.1f} W/(m2 K) (on {CALIBRATION}'s surface)")
            for r in rows:
                core = (
                    f"core {r['core_rmse_K']:.2f} K, core-surface {r['core_minus_surface_meas_K']:.2f} meas / "
                    f"{r['core_minus_surface_model_K']:.2f} model"
                    if "core_rmse_K" in r
                    else f"(no core), core-surface model {r['core_minus_surface_model_K']:.2f}"
                )
                V = f", V {r['V_rmse_mV']:.1f} mV" if "V_rmse_mV" in r else ""
                print(
                    f"  {r['test']:14s} surface {r['surface_rmse_K']:.2f} K (rise {r['surface_rise_meas_K']:.1f} meas, "
                    f"{r['surface_rise_model_K']:.1f} model), {core}{V}"
                )
    return results


if __name__ == "__main__":
    res = main()
    if "--json" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--json") + 1])
        out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
