"""Held-out tests predicted as PackTherm runs a cell: voltage and temperature from the current alone.

Each test the fit never saw is run through the electro-thermal model with the
fitted cell (its electrical values, with the size, mass and thermal properties
of the cell it names under ``like``): only the measured current goes in, and
the cell's surface temperature and voltage come out, to compare with the
thermocouple and the voltage logged. A library cell can be run the same way
for comparison.

The test chamber's convection (h) is a property of the rig, not the cell: it
is given, not fitted. For the Panasonic dataset it is the 38.7 W/(m2 K)
calibrated in ``packtherm.validation`` from the measured heat alone.
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


def thermal_checks(checks: list[ThermalCheck], cell, h: float, compare=None, compare_name: str = "") -> list[dict]:
    """Every held-out test, with the fitted cell and (optionally) a cell to compare with."""
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
