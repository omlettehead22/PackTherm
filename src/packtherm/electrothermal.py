"""Electro-thermal coupling: current profiles -> cell heat generation.

Heat generation follows Bernardi et al. (1985) in its common lumped form,
with current I positive on discharge:

    Q = I^2 R(SOC, T)  -  I T dU/dT(SOC)
        irreversible       reversible (entropic)

State of charge is coulomb-counted: dSOC/dt = -I / (3600 * capacity_Ah).
Temperature feeds back through R(SOC, T) every time step.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .cells import Cell

CurrentProfile = Callable[[float], float]  # t [s] -> I [A], + = discharge


def constant_current(cell: Cell, c_rate: float, mode: str = "discharge") -> CurrentProfile:
    """Constant C-rate charge or discharge."""
    if mode not in ("charge", "discharge"):
        raise ValueError("mode must be 'charge' or 'discharge'")
    sign = 1.0 if mode == "discharge" else -1.0
    current = sign * cell.current(c_rate)
    return lambda t: current


def segments(cell: Cell, steps: Sequence[tuple[float, float]], repeat: bool = False) -> CurrentProfile:
    """Piecewise-constant profile from (duration_s, c_rate) pairs.

    c_rate > 0 discharges, < 0 charges, 0 rests. With ``repeat`` the sequence
    loops (e.g. a drive cycle); otherwise current is 0 after the last step.
    """
    durations = np.array([d for d, _ in steps], dtype=float)
    if np.any(durations <= 0):
        raise ValueError("Segment durations must be positive.")
    ends = np.cumsum(durations)
    currents = np.array([cell.current(c) for _, c in steps])
    period = ends[-1]

    def profile(t: float) -> float:
        if repeat:
            t = t % period
        elif t >= period:
            return 0.0
        return float(currents[np.searchsorted(ends, t, side="right")])

    return profile


def from_csv(path: str | Path, time_col: str = "time_s", current_col: str = "current_A") -> CurrentProfile:
    """Linearly interpolated current profile from a CSV with time and current columns."""
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    t = np.array([float(r[time_col]) for r in rows])
    current = np.array([float(r[current_col]) for r in rows])
    if np.any(np.diff(t) <= 0):
        raise ValueError("Time column must be strictly increasing.")
    return lambda x: float(np.interp(x, t, current, left=current[0], right=0.0))


@dataclass
class ElectroThermalLoad:
    """Stateful :class:`packtherm.model.Load` driven by a current profile.

    soc_limits : current is cut (set to 0) once SOC leaves this window,
                 e.g. a charge to 80 % stops at 0.8.
    entropic   : include the reversible heat term.
    max_substep: longest electrical step [s]. A longer thermal step is split
                 into equal electrical substeps at the step's start temperature,
                 so a drive cycle's current is followed at this resolution
                 whatever the thermal step; the log keeps one averaged entry per
                 thermal step. None: one electrical step per thermal step.
    """

    cell: Cell
    profile: CurrentProfile
    soc0: float = 1.0
    soc_limits: tuple[float, float] = (0.0, 1.0)
    entropic: bool = True
    max_substep: float | None = None
    soc: float = field(init=False)
    log: dict[str, list[float]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        from .ecm import ECMState

        lo, hi = self.soc_limits
        if not (0.0 <= lo < hi <= 1.0) or not (lo <= self.soc0 <= hi):
            raise ValueError("Require 0 <= soc_min < soc_max <= 1 and soc0 inside the window.")
        self.soc = self.soc0
        self.ecm_state = ECMState() if self.cell.ecm is not None else None
        self.log = {
            k: [] for k in ("t", "current_A", "soc", "R_ohm", "Q_irr_W", "Q_rev_W", "V", "I_abs_A", "I_req_A")
        }

    def power(self, t: float, dt: float, T_cell: float) -> float:
        h = self.max_substep
        if h is None or dt <= h * (1.0 + 1e-9):
            return self._power_one(t, dt, T_cell)
        n = math.ceil(dt / h - 1e-9)
        starts = [t + i * dt / n for i in range(n)]
        requested = [float(self.profile(x)) for x in starts]
        if max(requested) == min(requested):
            # Constant current over the step (a constant or piecewise duty): one
            # electrical step, as the electrical model is accurate at this step.
            return self._power_one(t, dt, T_cell)
        mark = len(self.log["t"])
        q = sum(self._power_one(x, dt / n, T_cell) for x in starts) / n
        sub = {k: v[mark:] for k, v in self.log.items()}
        for v in self.log.values():
            del v[mark:]

        def mean(xs):
            xs = [x for x in xs if not math.isnan(x)]
            return sum(xs) / len(xs) if xs else math.nan

        merged = {
            "t": t,
            "current_A": sum(sub["current_A"]) / n,  # charge-preserving
            "soc": sub["soc"][-1],
            "R_ohm": mean(sub["R_ohm"]),
            "Q_irr_W": sum(sub["Q_irr_W"]) / n,
            "Q_rev_W": sum(sub["Q_rev_W"]) / n,
            "V": mean(sub["V"]),
            # Drive and regen within one step cancel in the mean current, not here.
            "I_abs_A": sum(sub["I_abs_A"]) / n,
            "I_req_A": sum(sub["I_req_A"]) / n,  # what the duty asked for
        }
        for k in self.log:
            self.log[k].append(merged[k])
        return q

    def _power_one(self, t: float, dt: float, T_cell: float) -> float:
        current = float(self.profile(t))
        self._requested = current
        if self.ecm_state is not None:
            return self._power_ecm(t, dt, T_cell, current)
        lo, hi = self.soc_limits
        # Stop at the SOC window edge; a partial final step uses only the
        # charge that fits in the window.
        dsoc = -current * dt / (3600.0 * self.cell.capacity_Ah)
        if current > 0 and self.soc + dsoc < lo:
            current *= (self.soc - lo) / -dsoc if dsoc else 0.0
        elif current < 0 and self.soc + dsoc > hi:
            current *= (hi - self.soc) / dsoc if dsoc else 0.0
        soc_mid = self.soc - 0.5 * current * dt / (3600.0 * self.cell.capacity_Ah)
        R = self.cell.resistance(soc_mid, T_cell)
        q_irr = current**2 * R
        q_rev = -current * T_cell * self.cell.dUdT(soc_mid) if self.entropic else 0.0
        self.soc = min(max(self.soc - current * dt / (3600.0 * self.cell.capacity_Ah), lo), hi)
        for k, v in zip(self.log, (t, current, self.soc, R, q_irr, q_rev, np.nan, abs(current), self._requested)):
            self.log[k].append(v)
        return q_irr + q_rev

    def _power_ecm(self, t: float, dt: float, T_cell: float, current: float) -> float:
        """Equivalent-circuit path: voltage limits, CC-CV charging, heat = I (OCV - V)."""
        ecm = self.cell.ecm
        cap_As = 3600.0 * self.cell.capacity_Ah
        lo, hi = self.soc_limits
        # A window edge at 0 or 1 is left to the voltage limits (cut-off, CV),
        # as a real charger or tester would; inner edges are enforced.
        if (current > 0 and lo > 0.0 and self.soc <= lo) or (current < 0 and hi < 1.0 and self.soc >= hi):
            current = 0.0
        soc_mid = self.soc - 0.5 * current * dt / cap_As
        current, V = self.ecm_state.apply(ecm, current, soc_mid, T_cell, dt)
        soc_mid = self.soc - 0.5 * current * dt / cap_As
        q_irr = current * (ecm.ocv(soc_mid, T_cell) - V)
        q_rev = -current * T_cell * self.cell.dUdT(soc_mid) if self.entropic else 0.0
        self.soc = self.soc - current * dt / cap_As
        if lo > 0.0:
            self.soc = max(self.soc, lo)
        if hi < 1.0:
            self.soc = min(self.soc, hi)
        R_app = (ecm.ocv(soc_mid, T_cell) - V) / current if current else np.nan
        for k, v in zip(self.log, (t, current, self.soc, R_app, q_irr, q_rev, V, abs(current), self._requested)):
            self.log[k].append(v)
        return q_irr + q_rev

    def arrays(self) -> dict[str, np.ndarray]:
        return {k: np.asarray(v) for k, v in self.log.items()}


@dataclass
class MeasuredHeatLoad:
    """Heat from a measured test record, for validating the thermal model alone.

    Q = I (OCV(SOC, T) - V_measured) + reversible heat, with I > 0 on discharge.
    This removes any electrical-model error, so a temperature mismatch is the
    thermal model's.
    """

    t: np.ndarray
    current_A: np.ndarray  # + discharge
    voltage_V: np.ndarray
    ocv: Callable  # (soc, T_K) -> V, as ECM.ocv; or (soc) -> V, one curve for every temperature
    capacity_Ah: float
    soc0: float = 1.0
    dUdT: Callable[[float], float] | None = None
    substeps: int = 5

    def __post_init__(self) -> None:
        t = np.asarray(self.t, float)
        charge = np.concatenate([[0.0], np.cumsum(0.5 * (self.current_A[1:] + self.current_A[:-1]) * np.diff(t))])
        self._soc = self.soc0 - charge / (3600.0 * self.capacity_Ah)
        import inspect

        try:
            two = len(inspect.signature(self.ocv).parameters) >= 2
        except (TypeError, ValueError):
            two = False
        f = self.ocv if two else (lambda soc, T, g=self.ocv: g(soc))
        self._ocv = np.vectorize(f, excluded={1})

    def power(self, t: float, dt: float, T_cell: float) -> float:
        tt = np.linspace(t, t + dt, self.substeps + 1)
        tt = 0.5 * (tt[1:] + tt[:-1])
        current = np.interp(tt, self.t, self.current_A)
        V = np.interp(tt, self.t, self.voltage_V)
        soc = np.interp(tt, self.t, self._soc)
        q = current * (self._ocv(soc, T_cell) - V)
        if self.dUdT is not None:
            q = q - current * T_cell * np.array([self.dUdT(x) for x in soc])
        return float(q.mean())


def simulate_cell(
    cell: Cell,
    profile: CurrentProfile,
    duration: float,
    h: float,
    T_env: float,
    *,
    pcm_thickness: float = 3e-3,
    case_thickness: float = 1e-3,
    soc0: float = 1.0,
    soc_limits: tuple[float, float] = (0.0, 1.0),
    entropic: bool = True,
    T_initial: float | None = None,
    base=None,
):
    """Run an electro-thermal event for one cell in its PCM sleeve and casing.

    Returns (SimulationResult, ElectroThermalLoad); the load holds the SOC,
    current, resistance and heat logs.
    """
    from .cells import params_for_cell
    from .model import simulate

    P = params_for_cell(cell, pcm_thickness, case_thickness, base=base)
    if T_initial is not None:
        P = P.with_(T_initial=T_initial)
    load = ElectroThermalLoad(cell, profile, soc0=soc0, soc_limits=soc_limits, entropic=entropic)
    res = simulate(P, duration=duration, h=h, T_env=T_env, load=load)
    return res, load


# Below this share of the requested discharge, the cell cannot carry out the duty:
# normal runs deliver 87-100 % (tapering near empty at the voltage cut-off).
MIN_DELIVERED = 0.8


def delivered_share(load: ElectroThermalLoad, until_s: float) -> float:
    """The share of the requested discharge charge the cell delivered before ``until_s``.

    1.0 when nothing was asked (or all of it was delivered). An equivalent-circuit
    cell stops at its voltage cut-off, so a current it cannot sustain is cut
    short, sometimes to nothing: its run then shows little heat, which must not
    pass as a well-cooled design.
    """
    a = load.arrays()
    t = a["t"]
    if t.size == 0:
        return 1.0
    step = np.diff(t, append=t[-1] + (float(np.median(np.diff(t))) if t.size > 1 else 1.0))
    during = t < until_s - 1e-9
    asked = float(np.clip(a["I_req_A"][during], 0.0, None) @ step[during])
    got = float(np.clip(a["current_A"][during], 0.0, None) @ step[during])
    return got / asked if asked > 0 else 1.0


def shortfall_warning(share: float) -> str:
    return (
        f"The cell reached its voltage cut-off and delivered only {100 * share:.0f}% of the discharge the duty asks for, "
        "so this result understates the heat: the cell cannot carry out this duty."
    )


RANGE_MARGIN_K = 2.0  # a fitted cell's tested temperatures, give or take this, count as tested


def check_fitted_range(cell: Cell, load: ElectroThermalLoad, res, window_s: float = 30.0) -> list[str]:
    """For a fitted cell: where a run goes beyond what its tests covered (empty list = within them).

    Inside the tested temperatures the model interpolates between fitted
    values; beyond them it follows the fitted laws, which the tests did not
    check there. Higher C-rates than tested are extrapolation too.
    """
    from .params import KELVIN

    v = cell.validity
    if not v:
        return []
    a = load.arrays()
    current = a["current_A"]
    if current.size == 0:
        return []
    out = []
    T = np.asarray(res.T_max) - KELVIN
    T_lo = float(T.min())
    rng = v.get("temperature_C")
    if rng:
        if T_lo < rng[0] - RANGE_MARGIN_K:
            out.append(
                f"The cell starts at {T_lo:.0f} degC, colder than its fitted model's coldest test ({rng[0]:.0f} degC): "
                "the result rests on its fitted temperature laws, not on tests."
            )
        if float(T.max()) > rng[1] + RANGE_MARGIN_K:
            out.append(
                f"The cell reaches {float(T.max()):.0f} degC, warmer than its fitted model's warmest test "
                f"({rng[1]:.0f} degC): the result rests on its fitted temperature laws, not on tests."
            )
    dt = float(np.median(np.diff(a["t"]))) if current.size > 1 else 1.0
    n = max(1, min(current.size, round(window_s / dt)))
    rolling = np.convolve(current, np.ones(n) / n, mode="valid")
    for label, c, key in (
        ("Discharge", max(rolling.max(), 0.0) / cell.capacity_Ah, "discharge_C"),
        ("Charge", max(-rolling.min(), 0.0) / cell.capacity_Ah, "charge_C"),
    ):
        tested = v.get(key)
        if c > 0.05 and (tested is None or c > 1.1 * tested[1]):
            what = "was not tested" if tested is None else f"was tested up to {tested[1]:.2g}C"
            out.append(f"{label} {c:.2f}C: the fitted model's {label.lower()} {what}; this is extrapolation.")
    return out


def check_limits(cell: Cell, load: ElectroThermalLoad, res, window_s: float = 30.0) -> list[str]:
    """Datasheet-limit warnings for a finished run (empty list = within limits).

    C-rates are judged on a rolling ``window_s`` mean, so short drive-cycle
    peaks are not reported as breaches of a *continuous* rating.
    """
    from .params import KELVIN

    a = load.arrays()
    warnings: list[str] = []
    current = a["current_A"]
    if current.size == 0:
        return warnings
    dt = float(np.median(np.diff(a["t"]))) if current.size > 1 else 1.0
    n = max(1, min(current.size, round(window_s / dt)))
    rolling = np.convolve(current, np.ones(n) / n, mode="valid")
    c_dis = max(rolling.max(), 0.0) / cell.capacity_Ah
    c_chg = max(-rolling.min(), 0.0) / cell.capacity_Ah
    # Judge each temperature limit on the peak while that kind of current flows:
    # a hot discharge followed by a cooler charge is not a charging breach.
    # T_max holds the start state then the state after each logged step.
    T_after = np.asarray(res.T_max)[-current.size :] - KELVIN
    charging = bool((current < 0).any())
    discharging = bool((current > 0).any())
    T_peak_chg = float(T_after[current < 0].max()) if charging else -np.inf
    T_peak_dis = float(T_after[current > 0].max()) if discharging else -np.inf
    if cell.max_discharge_C is not None and c_dis > cell.max_discharge_C + 1e-9:
        warnings.append(f"Discharge {c_dis:.2f}C exceeds the {cell.max_discharge_C:.2f}C continuous rating.")
    if cell.max_charge_C is not None and c_chg > cell.max_charge_C + 1e-9:
        warnings.append(f"Charge {c_chg:.2f}C exceeds the {cell.max_charge_C:.2f}C rating.")
    if cell.T_max_charge_C is not None and T_peak_chg > cell.T_max_charge_C:
        warnings.append(f"Peak {T_peak_chg:.1f} degC while charging exceeds the {cell.T_max_charge_C:.0f} degC limit.")
    if cell.T_max_discharge_C is not None and T_peak_dis > cell.T_max_discharge_C:
        warnings.append(
            f"Peak {T_peak_dis:.1f} degC while discharging exceeds the {cell.T_max_discharge_C:.0f} degC limit."
        )
    return warnings
