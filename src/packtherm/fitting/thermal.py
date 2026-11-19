"""Held-out tests predicted as PackTherm runs a cell: voltage and temperature from the current alone.

Each test the fit never saw is run through the electro-thermal model with the
fitted cell (its electrical values, with the size, mass and thermal properties
of the cell it names under ``like``): only the measured current goes in, and
the cell's surface temperature and voltage come out, to compare with the
thermocouple and the voltage logged. A library cell can be run the same way
for comparison.

The rig is not the cell. The chamber's convection (h) is given, or calibrated
on tests that are fitted to (``calibrate_rig``), with the heat from their
measured voltage, so the checks are not tuned to the circuit model. For the
Panasonic dataset h is the 38.7 W/(m2 K) calibrated in ``packtherm.validation``.
With two calibration tests or more, one steady and one dynamic, the heat
capacity the cell's fixture adds (J/K: clips, leads, holder) is calibrated
too: a steady test's rise sets h, a drive cycle's peaks the heat capacity. It
is the rig's, used for the checks only, never stored on the cell.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..testdata import TestRecord
from .circuit import KNEE_SHARE


@dataclass
class ThermalCheck:
    """A held-out test, with what the electro-thermal run needs to know about it."""

    record: TestRecord
    soc0: float = 1.0  # where it starts (a drive cycle straight after a full charge: 1)
    ambient_C: float | None = None  # the chamber; from the file's chamber column if it has one


def _ambient(c: ThermalCheck) -> float:
    if c.ambient_C is not None:
        return float(c.ambient_C)
    a = c.record.ambient_C
    if a is not None and np.isfinite(a).any():
        return float(np.nanmedian(a))
    raise ValueError(f"{c.record.source}: no chamber temperature in the file; give ambient_C")


def run_check(c: ThermalCheck, cell, h: float, dt: float = 2.0) -> dict:
    """One electro-thermal prediction: voltage (down to the knee) and surface temperature against measured."""
    from ..validation import TestRecord as VTest
    from ..validation import run_test

    rec = c.record
    if rec.temperature_C is None or not np.isfinite(rec.temperature_C).any():
        raise ValueError(f"{rec.source}: no cell temperature in the file: the thermal check needs it")
    amb = _ambient(c)
    test = VTest(
        rec.source, "drive_cycle", "check", amb, amb, c.soc0,
        rec.t - rec.t[0], rec.current_A, rec.voltage_V, rec.temperature_C,
    )  # fmt: skip
    r = run_test(test, cell, h=h, mode="predictive", dt=dt)
    s = r["series"]
    knee = cell.ecm.V_min + KNEE_SHARE * (cell.ecm.V_max - cell.ecm.V_min)
    active = np.abs(np.interp(s["t_V"], test.t, test.current_A)) > 0.05
    use = active & (s["V_meas"] > knee)
    dv = (s["V_model"] - s["V_meas"])[use]
    return {
        "file": rec.source,
        "ambient_C": amb,
        "V_rmse_mV": float(1e3 * np.sqrt(np.mean(dv**2))) if dv.size else float("nan"),
        "T_rmse_K": r["T_rmse_K"],
        "peak_error_K": r["peak_error_K"],
        "rise_meas_K": r["rise_meas_K"],
        "_series": s,
    }


def rig_cell(cell, fixture_J_K: float = 0.0):
    """The cell as the rig holds it: the fixture's heat capacity lumped with the cell's."""
    if not fixture_J_K:
        return cell
    from dataclasses import replace

    return replace(cell, cp=cell.cp + fixture_J_K / cell.mass)


def calibrate_rig(cals: list[ThermalCheck], cell, dt: float = 2.0) -> dict:
    """The rig's convection (h), and with two tests or more the fixture's heat capacity, from measured heat.

    The heat is I (OCV - V) with V as measured: the circuit model plays no part
    beyond the open-circuit voltage, so the checks that follow are not tuned to
    it. Use tests that are fitted to, not the checks: a steady one (a constant
    current discharge) for h, and a dynamic one (a drive cycle) for the heat
    capacity. Scored on the RMS of the tests' temperature errors.
    """
    from scipy.optimize import minimize, minimize_scalar

    from ..validation import TestRecord as VTest
    from ..validation import run_test

    tests = []
    for c in cals:
        rec = c.record
        if rec.temperature_C is None or not np.isfinite(rec.temperature_C).any():
            raise ValueError(f"{rec.source}: no cell temperature in the file: calibrating the rig needs it")
        amb = _ambient(c)
        test = VTest(
            rec.source, "calibration", "calibration", amb, amb, c.soc0,
            rec.t - rec.t[0], rec.current_A, rec.voltage_V, rec.temperature_C,
        )  # fmt: skip
        tests.append(test)

    def rms(h: float, fixture: float) -> float:
        c = rig_cell(cell, fixture)
        return float(np.sqrt(np.mean([run_test(t, c, h, "thermal", dt)["T_rmse_K"] ** 2 for t in tests])))

    H_LO, H_HI = 2.0, 200.0
    own = cell.mass * cell.cp  # J/K
    if len(tests) == 1:
        r = minimize_scalar(lambda h: rms(h, 0.0), bounds=(H_LO, H_HI), method="bounded", options={"xatol": 0.05})
        h, fixture = float(r.x), 0.0
    else:
        # log h, and the fixture as a share of the cell's own heat capacity (0 to 3x)
        def f(x):
            return rms(float(np.exp(np.clip(x[0], np.log(H_LO), np.log(H_HI)))), own * float(np.clip(x[1], 0.0, 3.0)))

        r = minimize(f, np.array([np.log(40.0), 0.3]), method="Nelder-Mead", options={"xatol": 2e-3, "fatol": 1e-3})
        h = float(np.exp(np.clip(r.x[0], np.log(H_LO), np.log(H_HI))))
        fixture = own * float(np.clip(r.x[1], 0.0, 3.0))
    notes = []
    if h < 1.25 * H_LO or h > 0.995 * H_HI:
        notes.append(f"h at the edge of {H_LO:g} to {H_HI:g} W/(m2 K): check the tests")
    if len(tests) > 1 and fixture > 2.9 * own:
        notes.append("the fixture's heat capacity at the edge (3x the cell's): check the tests")
    return {
        "files": [t.name for t in tests],
        "h_W_m2K": h,
        "fixture_J_K": fixture,
        "cell_J_K": own,
        "T_rmse_K": rms(h, fixture),
        "note": "; ".join(notes),
    }


def thermal_checks(
    checks: list[ThermalCheck], cell, h: float, compare=None, compare_name: str = "", fixture_J_K: float = 0.0
) -> list[dict]:
    """Every held-out test, with the fitted cell and (optionally) a cell to compare with, in the rig."""
    cell = rig_cell(cell, fixture_J_K)
    compare = None if compare is None else rig_cell(compare, fixture_J_K)
    out = []
    for c in checks:
        row = run_check(c, cell, h)
        if compare is not None:
            other = run_check(c, compare, h)
            row["compare"] = compare_name
            for k in ("V_rmse_mV", "T_rmse_K", "peak_error_K"):
                row[f"compare_{k}"] = other[k]
            row["_compare_series"] = other["_series"]
        out.append(row)
    return out


def summary(rows: list[dict]) -> dict:
    """Medians and the share within 1 K, for the fitted cell and the comparison."""
    if not rows:
        return {}
    out = {
        "tests": len(rows),
        "median_V_rmse_mV": float(np.nanmedian([r["V_rmse_mV"] for r in rows])),
        "median_T_rmse_K": float(np.median([r["T_rmse_K"] for r in rows])),
        "within_1K": float(np.mean([r["T_rmse_K"] < 1.0 for r in rows])),
        "median_abs_peak_error_K": float(np.median([abs(r["peak_error_K"]) for r in rows])),
    }
    if "compare" in rows[0]:
        out["compare"] = rows[0]["compare"]
        out["compare_median_V_rmse_mV"] = float(np.nanmedian([r["compare_V_rmse_mV"] for r in rows]))
        out["compare_median_T_rmse_K"] = float(np.median([r["compare_T_rmse_K"] for r in rows]))
        out["compare_within_1K"] = float(np.mean([r["compare_T_rmse_K"] < 1.0 for r in rows]))
        out["compare_median_abs_peak_error_K"] = float(np.median([abs(r["compare_peak_error_K"]) for r in rows]))
    return out
