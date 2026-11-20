"""The open-circuit voltage curve and the capacity, from a slow test.

A slow discharge (C/20 or slower) from full to the cut-off gives both:
its charge is the capacity, and its voltage, plus the small drop its own
current causes, is the open-circuit voltage at each state of charge. The same
method made the library's NCR18650PF curve (``data/ncr18650pf_ocv.csv``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..testdata import Segment, TestRecord

SLOW_MAX_C = 0.1  # a "slow" test is at C/10 or less


@dataclass
class OCVCurve:
    soc: np.ndarray  # 0..1 on a 0.01 grid
    V: np.ndarray  # open-circuit voltage, V
    capacity_Ah: float  # the slow discharge's charge
    V_min: float  # where the slow discharge stopped
    V_top: float  # where it started (after the charge and rest)
    current_A: float  # the slow discharge's current
    method: str
    notes: list[str] = field(default_factory=list)
    # The slow discharge and charge as measured (for the report): SOC, voltage.
    discharge: tuple[np.ndarray, np.ndarray] | None = None
    charge: tuple[np.ndarray, np.ndarray] | None = None
    discharge_span: tuple[int, int] | None = None  # the slow discharge's samples in its record
    R_used_ohm: float = 0.0
    # Curves by temperature (v0.6.5): (T_K, soc, V), on this curve's state of charge; this one among them.
    by_T: tuple = ()
    T_K: float | None = None  # the slow discharge's median cell temperature

    def at(self, soc) -> np.ndarray:
        return np.interp(soc, self.soc, self.V)

    def soc_at(self, V: float, T_K: float | None = None) -> float:
        """The state of charge whose open-circuit voltage is V (at T_K, with curves by temperature)."""
        if not self.by_T or T_K is None:
            return float(np.interp(V, self.V, self.soc))
        from ..ecm import curve_value

        curves = sorted(self.by_T, key=lambda c: c[0])
        lo = min(min(c[1]) for c in curves)
        grid = np.linspace(lo, 1.0, 401)
        Ts = [c[0] for c in curves]

        def v_at(soc):
            if T_K <= Ts[0]:
                return curve_value(curves[0][1], curves[0][2], soc)
            if T_K >= Ts[-1]:
                return curve_value(curves[-1][1], curves[-1][2], soc)
            k = int(np.searchsorted(Ts, T_K)) - 1
            u = (T_K - Ts[k]) / (Ts[k + 1] - Ts[k])
            a = curve_value(curves[k][1], curves[k][2], soc)
            return a + (curve_value(curves[k + 1][1], curves[k + 1][2], soc) - a) * u

        v = np.maximum.accumulate(np.array([v_at(x) for x in grid]))
        return float(np.interp(V, v, grid))

    def as_row(self) -> tuple[float, tuple[float, ...], tuple[float, ...]]:
        return (float(self.T_K if self.T_K is not None else 298.15), tuple(map(float, self.soc)), tuple(map(float, self.V)))



def _grid(soc: np.ndarray, V: np.ndarray, grid: np.ndarray | None = None) -> np.ndarray:
    """Voltage on a SOC grid (0.01 steps from 0 to 1); made to rise with SOC (noise at a step can dip it)."""
    order = np.argsort(soc)
    s, v = soc[order], V[order]
    v = np.maximum.accumulate(v)  # monotonic: an OCV curve rises with charge
    if grid is None:
        grid = np.linspace(0.0, 1.0, 101)
    return np.interp(grid, s, v)


def _slow_parts(rec: TestRecord, discharge: bool) -> list[Segment]:
    cap_guess = max(abs(s.charge_Ah) for s in rec.segments()) if rec.segments() else 0.0
    out = []
    for s in rec.segments():
        if s.kind not in ("constant", "cc-cv"):
            continue
        if (s.current_A > 0) != discharge:
            continue
        if cap_guess and abs(s.current_A) > SLOW_MAX_C * cap_guess * 1.2:
            continue
        out.append(s)
    return out


def ocv_from_slow_test(rec: TestRecord, R_ohm: float = 0.0, factor=None, reference_Ah: float | None = None) -> OCVCurve:
    """The curve and capacity from the slowest full discharge in ``rec`` (and its charge, if it has one).

    The discharge must start full (after a charge and a rest) and run to the
    cut-off: its charge is then the capacity. factor(soc), if given, scales the
    drop with the state of charge (the model's rise near empty). R_ohm is the resistance whose
    drop is added back; the fit sets it from the model's steady resistance.

    reference_Ah: for a slow test at another temperature (v0.6.5), the state of
    charge is the charge left as a share of this capacity (the reference
    curve's), not of the test's own: the curve then ends where the test
    stopped, at a state of charge above 0 if it delivered less.
    """
    parts = _slow_parts(rec, discharge=True)
    if not parts:
        raise ValueError(
            f"{rec.source}: no slow discharge (C/10 or slower, a steady current over hours) to take the "
            "open-circuit voltage and capacity from"
        )
    d = max(parts, key=lambda s: s.charge_Ah)
    t = rec.t[d.start : d.stop]
    q = rec.charge_Ah()[d.start : d.stop]
    q = q - q[0]
    cap = float(q[-1])
    V = rec.voltage_V[d.start : d.stop]
    ref = cap if reference_Ah is None else float(reference_Ah)
    soc = 1.0 - q / ref
    lo = 0.0 if reference_Ah is None else float(round(soc[-1], 4))
    grid = np.linspace(lo, 1.0, 101)
    notes = []
    before = rec.voltage_V[max(d.start - 1, 0)]
    if before < 4.0 and before < np.max(rec.voltage_V) - 0.1:
        notes.append(
            f"the slow discharge starts at {before:.3f} V, not obviously full: the capacity "
            f"({cap:.3f} Ah) and the curve assume it is"
        )
    T = rec.temperature_C[d.start : d.stop] if rec.temperature_C is not None else None
    curve = OCVCurve(
        soc=grid,
        V=_grid(soc, V + d.current_A * R_ohm * (np.vectorize(factor)(soc) if factor else 1.0), grid),
        capacity_Ah=cap,
        V_min=float(V[-1]),
        V_top=float(before),
        current_A=float(d.current_A),
        method=f"slow discharge at {d.current_A:.3g} A over {(t[-1] - t[0]) / 3600:.1f} h"
        + (
            f", plus its own drop ({1e3 * d.current_A * R_ohm:.1f} mV: {d.current_A:.3g} A x {1e3 * R_ohm:.1f} mOhm, "
            "the fitted model's steady resistance"
            + (", rising near empty as the model's does)" if factor else ")")
            if R_ohm
            else ""
        ),
        notes=notes,
        discharge=(soc, V),
        discharge_span=(d.start, d.stop),
        R_used_ohm=R_ohm,
        T_K=float(np.nanmedian(T)) + 273.15 if T is not None and np.isfinite(T).any() else None,
    )
    ch = _slow_parts(rec, discharge=False)
    if ch:
        c = max(ch, key=lambda s: -s.charge_Ah)
        qc = rec.charge_Ah()[c.start : c.stop]
        # The charge starts where the discharge ended (empty) if it follows it.
        soc_c = (qc[0] - qc) / ref + soc[-1]
        curve.charge = (soc_c, rec.voltage_V[c.start : c.stop])
    return curve


def hysteresis_mV(curve: OCVCurve) -> float | None:
    """Half the gap between the slow charge and discharge at 20-80 % SOC, less the drops: a hysteresis estimate."""
    if curve.charge is None or curve.discharge is None:
        return None
    grid = np.linspace(0.2, 0.8, 61)
    sd, vd = curve.discharge
    sc, vc = curve.charge
    if sc.max() < 0.8 or sc.min() > 0.2:
        return None
    o = np.argsort(sc)
    gap = np.interp(grid, sc[o], vc[o]) - np.interp(grid, np.sort(sd), vd[np.argsort(sd)])
    drop = 2 * abs(curve.current_A) * curve.R_used_ohm
    return float(1e3 * (np.median(gap) - drop) / 2)
