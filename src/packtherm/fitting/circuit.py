"""Fitting PackTherm's circuit model (``packtherm.ecm.ECM``) to test data at one temperature.

The model: the open-circuit voltage, an instant resistance R0, a charge-transfer
branch (exchange current I0, shape gamma, time constant tau_ct), a slow
diffusion branch (Rd, tau_d), and a rise of all of them near empty
(1 + soc_a exp(-SOC/soc_b)). See ``packtherm.ecm``.

What fits what:

- the slow test: the open-circuit voltage and the capacity (``ocv``);
- the pulses: R0, I0, gamma and tau_ct, from how the voltage jumps and settles
  through each pulse and the rest after it; the near-empty rise from the
  pulses at low charge;
- a test with long steps and rests (optional): Rd and tau_d, from the slow
  recovery in the rests.

The fit is through time: each pulse window and the slow test are replayed
through the same model PackTherm runs, and the parameters fit the voltage
there, not one point per pulse. The temperature behaviour is not fitted (one
temperature): it is the library NCR18650PF's, labelled as such, until v0.6.2.

A model is a ``CellModel``: parameters with bounds, a simulator, and a way to
build what PackTherm runs. A generic circuit model can be another.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from itertools import pairwise

import numpy as np
from scipy.optimize import least_squares

from ..ecm import ECM
from ..testdata import TestRecord
from .ocv import OCVCurve, hysteresis_mV, ocv_from_slow_test
from .soc import track_soc

T_REF = 298.15
# The temperature behaviour used until v0.6.2 fits it: the library NCR18650PF's.
DEFAULT_TEMPERATURE_LAWS = {"Ea_R0": 0.0, "Ea_I0": 45.2e3, "Ea_Rm": 26.8e3, "Ea_Rd": 26.8e3, "Ea_soc": 20.7e3}
MID_SOC = (0.2, 0.95)  # the kinetics fit on these pulses; the near-empty rise then on all
PRE_S, POST_S = 5.0, 40.0  # each pulse window: this long before, and after the pulse
ROUNDS = 3
MIN_STEP_S = 5 * 60  # a steady step this long has settled by its end
SETTLED_REST_S = 10 * 60  # a rest this long leaves the cell settled enough to replay a pulse from
# With no pulse test (v0.6.6), the kinetics are fitted on the long tests' sudden changes in current
# (STEP_C or more, in C, from one sample to the next: a start of load after a rest, or a step within a
# drive cycle), each from PRE_S before it to LOAD_S after.
STEP_C = 0.5
LOAD_S = 60.0
MIN_PULSES = 5


@dataclass(frozen=True)
class Param:
    name: str
    unit: str
    lo: float
    hi: float
    start: float
    what: str  # in words, for the cell file and report
    scale: float = 1.0  # fitted in these units (an energy in kJ/mol), so finite differences are a sensible size


class CellModel:
    """The interface a fitted model gives: its parameters, a simulator, and what PackTherm runs."""

    form: str = ""
    params: tuple[Param, ...] = ()

    def ecm(self, values: dict[str, float], ocv: OCVCurve) -> ECM:  # pragma: no cover - interface
        raise NotImplementedError

    def simulate(
        self, ecm: ECM, t, current, soc, T_K, current_now=None, steady_start=False
    ) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError


class CircuitModel(CellModel):
    """PackTherm's circuit model, as ``packtherm.ecm.ECM`` runs it."""

    form = "packtherm-circuit-1"
    params = (
        Param("R0_25C", "Ohm", 1e-4, 0.5, 0.03, "instant (ohmic) resistance"),
        Param("I0_25C", "A", 0.05, 500.0, 5.0, "exchange current of the charge-transfer branch"),
        Param("gamma", "-", 0.1, 30.0, 2.0, "shape of the charge-transfer branch (multiplies 2RT/F)"),
        Param("tau_ct", "s", 0.1, 10.0, 2.0, "time constant of the charge-transfer branch (seconds)"),
        Param("Rm_25C", "Ohm", 1e-5, 0.5, 0.01, "resistance of the middle branch"),
        # Up to the slow branch's floor (v0.6.5; was 300 s): above it the two overlap, and on the LG HG2 at 10
        # and 0 degC the middle branch took the slow branch's place (235-300 s, with no slow branch left).
        Param("tau_m", "s", 5.0, 120.0, 30.0, "time constant of the middle branch (tens of seconds)"),
        Param("Rd_25C", "Ohm", 1e-4, 0.5, 0.02, "resistance of the slow (diffusion) branch"),
        Param("tau_d", "s", 120.0, 10000.0, 600.0, "time constant of the slow branch (minutes)"),
        Param("soc_a", "-", 0.0, 50.0, 1.0, "size of the rise near empty"),
        Param("soc_b", "-", 0.01, 0.5, 0.08, "how far up from empty the rise reaches (SOC)"),
    )
    # The temperature laws (Arrhenius, about 25 degC): fitted only from tests at several temperatures.
    temperature_params = (
        Param("Ea_R0", "J/mol", -20e3, 120e3, 0.0, "how the instant resistance grows in the cold", 1e3),
        Param("Ea_I0", "J/mol", -20e3, 150e3, 45e3, "how the charge-transfer branch's exchange current falls in the cold", 1e3),
        Param("Ea_Rm", "J/mol", -20e3, 150e3, 27e3, "how the middle branch's resistance grows in the cold", 1e3),
        Param("Ea_Rd", "J/mol", -20e3, 150e3, 27e3, "how the slow branch's resistance grows in the cold", 1e3),
        Param("Ea_soc", "J/mol", -40e3, 120e3, 20e3, "how the rise near empty grows in the cold", 1e3),
    )

    def param(self, name: str) -> Param:
        return next(q for q in (*self.params, *self.temperature_params) if q.name == name)

    def ecm(
        self, values: dict[str, float], ocv: OCVCurve, V_max: float = 4.2, cv_cutoff_A: float = 0.05, by_T=()
    ) -> ECM:
        return ECM(
            ocv_soc=tuple(float(x) for x in ocv.soc),
            ocv_V=tuple(float(x) for x in ocv.V),
            R0_25C=values["R0_25C"],
            Ea_R0=values.get("Ea_R0", DEFAULT_TEMPERATURE_LAWS["Ea_R0"]),
            I0_25C=values["I0_25C"],
            Ea_I0=values.get("Ea_I0", DEFAULT_TEMPERATURE_LAWS["Ea_I0"]),
            gamma=values["gamma"],
            tau_ct=values["tau_ct"],
            Rd_25C=values["Rd_25C"],
            tau_d=values["tau_d"],
            V_max=V_max,
            V_min=ocv.V_min,
            cv_cutoff_A=cv_cutoff_A,
            soc_a=values["soc_a"],
            soc_b=values["soc_b"],
            Ea_soc=values.get("Ea_soc", DEFAULT_TEMPERATURE_LAWS["Ea_soc"]),
            Ea_Rd=values.get("Ea_Rd", DEFAULT_TEMPERATURE_LAWS["Ea_Rd"]),
            Rm_25C=values.get("Rm_25C", 0.0),
            tau_m=values.get("tau_m", 30.0),
            Ea_Rm=values.get("Ea_Rm", DEFAULT_TEMPERATURE_LAWS["Ea_Rm"]),
            sources=("fitted by packtherm.fitting",),
            by_T=tuple(by_T),
            ocv_by_T=tuple(ocv.by_T),
        )

    def simulate(self, ecm: ECM, t, current, soc, T_K, current_now=None, steady_start=False) -> np.ndarray:
        """Replay a test: the voltage at each sample.

        It starts settled (no polarisation), or with steady_start in the
        steady state for the first sample's current: a step that was already
        running when logging resumed after a gap.

        current: the mean current over each interval, ending at each sample
        (it moves the slow states). current_now: the current logged at each
        sample (the instant drop there); the mean if not given. These are the
        equations of ``ECMState.step``, with the two currents kept apart: in a
        record sampled every few minutes a step can fall anywhere inside an
        interval.
        """
        now = current if current_now is None else current_now
        out = np.empty(t.size)
        R0, Rd, Rm = ecm.R0, ecm.Rd, ecm.Rm
        eta = vd = vm = 0.0
        if steady_start:
            I0, T0 = float(now[0]), float(T_K[0])
            f0 = ecm.soc_factor(float(soc[0]), T0) if I0 > 0 else 1.0
            eta, vd, vm = f0 * ecm.eta_ss(I0, T0), f0 * Rd(T0) * I0, f0 * Rm(T0) * I0
        for k in range(t.size):
            Tk = float(T_K[k])
            if k:
                Im = float(current[k])
                dt = float(t[k] - t[k - 1])
                e1, e2 = math.exp(-dt / ecm.tau_ct_at(Tk)), math.exp(-dt / ecm.tau_d_at(Tk))
                f = ecm.soc_factor(float(soc[k]), Tk) if Im > 0 else 1.0
                eta = eta * e1 + f * ecm.eta_ss(Im, Tk) * (1.0 - e1)
                vd = vd * e2 + f * Rd(Tk) * Im * (1.0 - e2)
                e3 = math.exp(-dt / ecm.tau_m_at(Tk))
                vm = vm * e3 + f * Rm(Tk) * Im * (1.0 - e3)
            In = float(now[k])
            fn = ecm.soc_factor(float(soc[k]), Tk) if In > 0 else 1.0
            out[k] = ecm.ocv(float(soc[k]), Tk) - In * fn * R0(Tk) - eta - vm - vd
        return out


def interval_current(rec: TestRecord) -> np.ndarray:
    """The mean current over each interval, ending at each sample; 0 before the first.

    From the charge counted (``TestRecord.charge_Ah``): across gaps, and steps
    between two samples, the tester's charge counter says what moved.
    """
    dt = np.diff(rec.t)
    return np.concatenate([[0.0], np.diff(rec.charge_Ah()) * 3600.0 / np.where(dt > 0, dt, 1.0)])


def temperature_K(rec: TestRecord) -> np.ndarray:
    for x in (rec.temperature_C, rec.ambient_C):
        if x is not None and np.isfinite(x).all():
            return x + 273.15
    return np.full(rec.t.size, T_REF)


@dataclass
class Trace:
    """A stretch of a test the fit replays, from a known start."""

    t: np.ndarray
    current: np.ndarray  # mean over each interval, ending at each sample
    soc: np.ndarray
    T_K: np.ndarray
    V: np.ndarray
    now: np.ndarray  # the current logged at each sample
    steady_start: bool = False  # starts in the steady state for its first current, not settled

    def simulate(self, model: CellModel, ecm: ECM) -> np.ndarray:
        return model.simulate(ecm, self.t, self.current, self.soc, self.T_K, self.now, self.steady_start)


@dataclass
class Window:
    """A part of a trace the fit is scored on: a pulse with the rest after it, or the rest after a step.

    Short windows are scored on the voltage's change from their first sample,
    so an error in the open-circuit voltage's level does not count, only its
    slope; long tests on the voltage itself.
    """

    kind: str  # pulse or step
    trace: Trace
    k0: int  # the window's samples in its trace
    k1: int
    c_rate: float
    soc0: float
    # Scored on the change from its first sample (pulses, rests after steps: short, so an error in the
    # open-circuit voltage's level should not count), or on the voltage itself (long tests: over hours,
    # one sample's error carried through every other would dominate).
    relative: bool = True
    end: int | None = None  # a long test's last sample, past the knee (k1 stops at the knee)

    def to_end(self) -> Window:
        """The whole of a long test, through the knee: what the rise near empty is fitted on."""
        return replace(self, k1=self.end) if self.end is not None else self

    @property
    def t(self) -> np.ndarray:
        return self.trace.t[self.k0 : self.k1]

    @property
    def V(self) -> np.ndarray:
        return self.trace.V[self.k0 : self.k1]

    def model_V(self, Vm_trace: np.ndarray) -> np.ndarray:
        return Vm_trace[self.k0 : self.k1]

    def simulate(self, model: CellModel, ecm: ECM) -> np.ndarray:
        return self.model_V(self.trace.simulate(model, ecm))


def _trace(rec: TestRecord, I, soc, T, a: int, b: int, steady: bool = False) -> Trace:
    sl = slice(a, b)
    return Trace(rec.t[sl], I[sl], soc[sl], T[sl], rec.voltage_V[sl], rec.current_A[sl], steady)


def pulse_windows(rec: TestRecord, soc: np.ndarray, capacity: float) -> list[Window]:
    """Each pulse, from PRE_S before it to POST_S into the rest after it.

    A pulse can follow the one before by under a minute, while that one's
    slow recovery is still under way. So each is replayed from the end of the
    last long rest before it (SETTLED_REST_S), through any pulses between, and
    pulses that share that start share one replay.
    """
    I = interval_current(rec)
    T = temperature_K(rec)
    segs = rec.segments()
    spans = []
    for i, s in enumerate(segs):
        if s.kind != "pulse" or s.stop - s.start < 3:
            continue
        a = int(np.searchsorted(rec.t, s.t0 - PRE_S))
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        end_t = s.t1 + (min(POST_S, nxt.duration_s) if nxt is not None and nxt.kind == "rest" else 0.0)
        b = int(np.searchsorted(rec.t, end_t, side="right"))
        if b - a < 5:
            continue
        start = a
        for prev in reversed(segs[:i]):
            if prev.kind == "rest" and prev.duration_s >= SETTLED_REST_S:
                start = min(prev.stop - 1, a)
                break
            if prev.kind == "unlogged":
                break  # nothing to replay through: start at the window, as if settled
        spans.append((start, a, b, s))
    ends: dict[int, int] = {}
    for start, _, b, _ in spans:
        ends[start] = max(ends.get(start, 0), b)
    traces = {start: _trace(rec, I, soc, T, start, end) for start, end in ends.items()}
    return [
        Window("pulse", traces[start], a - start, b - start, s.current_A / capacity, float(soc[s.start]))
        for start, a, b, s in spans
    ]


def step_windows(rec: TestRecord, soc: np.ndarray, capacity: float) -> list[Window]:
    """The recovery in the rest after each steady step: it fits the slow branch.

    Each window runs from the step's last sample under load through the rest
    after it, and starts in the steady state for the step's current. How the
    step itself started is often unknown (logging can resume part-way into
    it, after a gap), but a step of several minutes has settled into its
    steady state by its end, whatever its start.
    """
    I = interval_current(rec)
    T = temperature_K(rec)
    segs = rec.segments()
    out = []
    for s, nxt in pairwise(segs):
        if s.kind != "constant" or nxt.kind != "rest" or nxt.duration_s < 5 * 60 or abs(s.current_A) < 1e-3:
            continue
        if s.duration_s < MIN_STEP_S:
            continue
        a = s.stop - 1
        if nxt.stop - a < 3:
            continue
        tr = _trace(rec, I, soc, T, a, nxt.stop, steady=True)
        out.append(Window("step", tr, 0, tr.t.size, s.current_A / capacity, float(soc[s.start])))
    return out


@dataclass
class ParamResult:
    name: str
    unit: str
    value: float
    source: str  # fitted, data, default, not fitted
    what: str
    ci95: tuple[float, float] | None = None
    rel_sd: float | None = None
    note: str = ""


@dataclass
class FitResult:
    """Everything a fit produced: values, how certain, errors, where it is valid, and what it came from."""

    model: CellModel
    ocv: OCVCurve
    ecm: ECM
    params: list[ParamResult]
    capacity_Ah: float
    errors: dict[str, dict]  # name -> {"rmse_mV", "max_mV", "samples"}
    checks: list[dict]  # held-out tests: file, rmse/max for the fit and any library model
    validity: dict
    correlated: list[tuple[str, str, float]]
    notes: list[str]
    records: dict[str, list[TestRecord]]  # role -> records
    soc_anchors: dict[str, str]
    settings: dict = field(default_factory=dict)
    plot_data: dict = field(default_factory=dict)
    temperatures: list = field(default_factory=list)  # the sets' temperatures, with several
    ocv_curves: list = field(default_factory=list)  # the other slow tests' curves (v0.6.5), on ocv's state of charge
    per_temperature: list = field(default_factory=list)  # each temperature's own fit, against the laws


def _vec_to_values(model: CellModel, x: np.ndarray, names: list[str], fixed: dict[str, float]) -> dict[str, float]:
    v = dict(fixed)
    for n, xi in zip(names, x):
        p = model.param(n)
        v[n] = float(np.exp(xi)) if p.lo > 0 else float(xi) * p.scale
    return v


def _x0(model: CellModel, names: list[str], values: dict[str, float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x, lo, hi = [], [], []
    for n in names:
        p = model.param(n)
        if p.lo > 0:  # positive: fit its logarithm
            x.append(math.log(min(max(values[n], p.lo * 1.0001), p.hi * 0.9999)))
            lo.append(math.log(p.lo))
            hi.append(math.log(p.hi))
        else:
            x.append(min(max(values[n], p.lo), p.hi) / p.scale)
            lo.append(p.lo / p.scale)
            hi.append(p.hi / p.scale)
    return np.array(x), np.array(lo), np.array(hi)


def _weight(w: Window) -> float:
    """Each window counts equally, however densely it was logged.

    A pulse logged every 0.1 s has hundreds of samples; the rest after a step,
    logged every few minutes, a handful. Weighted by sample, the pulses decide
    everything and the slow branch fits their tens of seconds, not the minutes
    a rest (and a drive cycle's heat) shows.
    """
    return 1.0 / math.sqrt(max(w.k1 - w.k0 - 1, 1))


def _residuals(model, ocv, values, windows: list[Window], V_max, weighted: bool = True) -> np.ndarray:
    """Model minus measured change in voltage through each window, from its first sample (weighted for the fit)."""
    return _residuals_ecm(model, model.ecm(values, ocv, V_max), windows, weighted)


def _residuals_ecm(model, ecm: ECM, windows: list[Window], weighted: bool = False) -> np.ndarray:
    sims: dict[int, np.ndarray] = {}
    parts = []
    for w in windows:
        key = id(w.trace)
        if key not in sims:
            sims[key] = w.trace.simulate(model, ecm)
        Vm, V = w.model_V(sims[key]), w.V
        r = ((Vm - Vm[0]) - (V - V[0]))[1:] if w.relative else (Vm - V)[1:]
        parts.append(r * _weight(w) if weighted else r)
    return np.concatenate(parts) if parts else np.zeros(0)


def _fit(model, ocv, values, names, windows, V_max):
    fixed = {k: v for k, v in values.items() if k not in names}
    x0, lo, hi = _x0(model, names, values)

    def f(x):
        return _residuals(model, ocv, _vec_to_values(model, x, names, fixed), windows, V_max)

    res = least_squares(f, x0, bounds=(lo, hi), x_scale="jac", diff_step=1e-4, max_nfev=200)
    return _vec_to_values(model, res.x, names, fixed), res


def _rms_mV(r: np.ndarray) -> tuple[float, float]:
    return float(1e3 * np.sqrt(np.mean(r**2))), float(1e3 * np.max(np.abs(r)))


@dataclass
class TestSet:
    """The tests at one temperature: a pulse test or long tests (or both), and optionally steps with rests."""

    __test__ = False  # not a pytest class

    # The pulse test (HPPC). Optional from v0.6.6: without one, the kinetics are fitted on the start of
    # load after each quiet spell in the discharges and cycles (load_windows).
    pulses: TestRecord | None
    steps: TestRecord | None = None
    at_C: float | None = None  # the chamber's setpoint, as a label; the fit uses the measured cell temperature
    # Full discharges at a working rate (1C, say), each starting rested at a known state of charge
    # (full, straight after a charge and a rest): the slow branch and the rise near empty over minutes.
    discharges: list[TestRecord] = field(default_factory=list)
    # Drive cycles (or any dynamic test) to fit on, each starting rested at a known state of charge.
    cycles: list[TestRecord] = field(default_factory=list)
    discharge_soc0: float = 1.0  # where the discharges and cycles start (full, straight after a charge)
    # A slow discharge at this temperature (v0.6.5), starting full: its open-circuit curve, on the
    # reference capacity's state of charge (the top-level slow test's), for when capacity moves with T.
    slow: TestRecord | None = None

    def label(self) -> str:
        return f"{self.at_C:g} degC" if self.at_C is not None else ""


@dataclass
class _SetFit:
    """One temperature's own fit, and its windows."""

    test: TestSet
    wins: list[Window]
    step_wins: list[Window]
    values: dict[str, float]
    names: list[str]
    res: object
    T_C: float  # the median measured cell temperature in its windows
    stages: dict = field(default_factory=dict)  # the slow branch's and the rise's stages: names, result, windows

    @property
    def slow(self):
        return self.stages.get("slow")


BASE_NAMES = ["R0_25C", "I0_25C", "gamma", "tau_ct", "Rm_25C", "tau_m", "soc_a", "soc_b"]
SLOW_NAMES = ["Rd_25C", "tau_d"]


def _scored(wins: list[Window], step_wins: list[Window]) -> list[Window]:
    """What the final fit is scored on: every pulse and every long test (steps, discharges)."""
    return list(wins) + list(step_wins)


def _long_for_slow(step_wins: list[Window]) -> list[Window]:
    """What the slow branch is fitted on: discharges, and steps at 20-95% SOC (all steps if none are)."""
    mid = [w for w in step_wins if w.kind in ("discharge", "cycle") or MID_SOC[0] <= w.soc0 <= MID_SOC[1]]
    return mid or list(step_wins)


LONG_DT_S = 1.0  # long tests logged faster than this are thinned to it for the fit
# Long tests are scored down to the knee: 40% of the way up from the cut-off to full (3.18 V on a
# 2.5-4.2 V cell). Below it the voltage collapses within minutes; a few minutes of large errors there
# would decide the whole fit (the rise near empty comes from the pulses and steps instead).
KNEE_SHARE = 0.4


def discharge_windows(
    rec: TestRecord, soc0: float, ocv: OCVCurve, cap: float, kind: str = "discharge"
) -> tuple[Window, str]:
    """A whole long test (a discharge, a drive cycle, and any rest after it), replayed from a rested start.

    A test logged every 0.1 s for hours is thinned to about LONG_DT_S: every
    n-th sample, with the mean current over each interval from the charge
    counted between them, so no charge is lost.
    """
    soc, how = track_soc(rec, ocv, cap, soc0=soc0)
    I = interval_current(rec)
    T = temperature_K(rec)
    dt = float(np.median(np.diff(rec.t))) if len(rec) > 1 else LONG_DT_S
    n = max(1, int(LONG_DT_S / max(dt, 1e-9)))
    if n > 1:
        keep = np.arange(0, len(rec), n)
        t = rec.t[keep]
        q = rec.charge_Ah()[keep]
        dtk = np.diff(t)
        Im = np.concatenate([[0.0], np.diff(q) * 3600.0 / np.where(dtk > 0, dtk, 1.0)])
        tr = Trace(t, Im, soc[keep], T[keep], rec.voltage_V[keep], rec.current_A[keep])
    else:
        tr = _trace(rec, I, soc, T, 0, len(rec))
    rate = float(np.max(np.abs(rec.current_A))) / cap
    knee = ocv.V_min + KNEE_SHARE * (ocv.V_top - ocv.V_min)
    below = np.flatnonzero(tr.V < knee)
    k1 = int(below[0]) if below.size else tr.t.size
    return Window(kind, tr, 0, max(k1, 2), rate, soc0, relative=False, end=tr.t.size), how


def load_windows(long_w: Window, capacity: float) -> list[Window]:
    """The long test's sudden changes in current: the kinetics, with no pulse test.

    Each runs from PRE_S before the change to LOAD_S after it, whatever the
    test does then (a rest, a step, a drive cycle's varying current), and is
    scored on the change from its first sample, as a pulse is. It is a part
    of the long test's own replay, which runs from the test's rested start,
    so it needs no settled rest before it: what is still relaxing from the
    load before is in the replay. The windows don't overlap: a change inside
    one window starts none of its own.
    """
    tr = long_w.trace
    n = min(tr.t.size, long_w.end or tr.t.size)
    jumps = np.flatnonzero(np.abs(np.diff(tr.now[:n])) >= STEP_C * capacity) + 1
    out: list[Window] = []
    last = 0
    for k in jumps:
        if tr.t[k] - PRE_S < tr.t[last] and out:
            continue
        a = max(int(np.searchsorted(tr.t, tr.t[k] - PRE_S)), last)
        b = min(int(np.searchsorted(tr.t, tr.t[k] + LOAD_S, side="right")), n)
        if b - a < 5:
            continue
        rate = float(np.max(np.abs(tr.now[k:b]))) / capacity
        out.append(Window("load", tr, a, b, rate, float(tr.soc[k])))
        last = b
    return out


def _windows(test: TestSet, ocv: OCVCurve, cap: float, anchors: dict[str, str]) -> tuple[list[Window], list[Window]]:
    tag = f" at {test.label()}" if test.at_C is not None else ""
    wins: list[Window] = []
    if test.pulses is not None:
        soc_p, anchors["pulses" + tag] = track_soc(test.pulses, ocv, cap)
        wins = pulse_windows(test.pulses, soc_p, cap)
        if len(wins) < MIN_PULSES:
            raise ValueError(f"{test.pulses.source}: only {len(wins)} pulses found; a pulse test needs at least 5")
    elif not (test.discharges or test.cycles):
        raise ValueError(f"tests{tag}: give a pulse test, or discharges or cycles to fit the kinetics on")
    step_wins: list[Window] = []
    if test.steps is not None:
        soc_s, anchors["steps" + tag] = track_soc(test.steps, ocv, cap)
        step_wins = step_windows(test.steps, soc_s, cap)
        if len(step_wins) < 2:
            raise ValueError(
                f"{test.steps.source}: {len(step_wins)} steady steps followed by a rest of 5 min or more; needs 2"
            )
    for kind, recs in (("discharge", test.discharges), ("cycle", test.cycles)):
        for i, rec in enumerate(recs):
            w, anchors[f"{kind} {i + 1}{tag}"] = discharge_windows(rec, test.discharge_soc0, ocv, cap, kind)
            step_wins.append(w)  # the long tests: they fit the slow branch together
    if test.pulses is None:
        wins = [lw for w in step_wins if w.kind in ("discharge", "cycle") for lw in load_windows(w, cap)]
        if len(wins) < MIN_PULSES:
            raise ValueError(
                f"tests{tag}: no pulse test, and only {len(wins)} sudden changes in current ({STEP_C:g}C or more) "
                f"in the discharges and cycles; the kinetics need at least {MIN_PULSES}"
            )
    return wins, step_wins


def _fit_one(model, ocv, values, wins, step_wins, V_max):
    """The staged fit at one temperature, each part of the model on the tests that show it.

    1. The kinetics (R0, the charge-transfer branch I0, gamma, tau_ct, and the
       middle branch Rm, tau_m) on pulses at 20-95% SOC.
    2. The slow branch (Rd, tau_d) on the long tests only: steps, discharges
       and drive cycles (down to the knee). Fitted with the pulses, both
       branches go to the pulses' seconds and tens of seconds, and the minutes
       a drive cycle's heat builds over are lost: predicted cycles ran cold.
    3. The rise near empty (soc_a, soc_b) on the pulses and the long tests
       run to their end: the knee at the end of a discharge is that rise.
    4. The kinetics again, on all the pulses, with the rest held (with no
       pulse test, on the long tests' changes in current at 20-95% SOC, as
       in step 1). Not on the long tests as a whole: there the middle branch's resistance can take over the slow
       branch's part, and the two drift apart round after round (on tests made
       by a known cell, the slow branch's time constant ran to 10x).

    The middle branch's time constant (tau_m) is fitted both ways when there
    are long tests: with the kinetics, on the pulses (as above), and with the
    slow branch, on the long tests (stage 2; held in stage 4). Pulses can leave
    it loose: the Samsung 30T's at 25 degC fit as well (10 mV) with it at 30 s
    as at 290 s, where a middle branch four times too strong held its 1C
    discharge 50-60 mV low. The way that fits the discharges and drive cycles
    better is kept (the steps, if there are none), as long as the pulses at
    20-95% SOC still fit within PULSE_SLACK of the other way. Not the steps
    when there are discharges or cycles: on the Panasonic at 0 degC, the
    steps' rests favoured the long tests' tau_m while its drive cycle fitted
    on went from 31 to 56 mV.

    Returns the values, the names fitted in the last stage and its result, and
    the stages for the slow branch and the rise (names, result, windows), for
    their ranges; stages["middle"] says which way tau_m was set.
    """
    values = dict(values)
    mid = [w for w in wins if MID_SOC[0] <= w.soc0 <= MID_SOC[1]]
    # Stage 4 on every pulse, but on the long tests' changes in current at 20-95% SOC only: a test run
    # to empty has as many below 20% as above, and their slope there would set the kinetics.
    last = mid if any(w.kind == "load" for w in wins) else list(wins)
    kin = ["R0_25C", "I0_25C", "gamma", "tau_ct", "Rm_25C", "tau_m"]
    values, _ = _fit(model, ocv, values, kin, mid, V_max)
    if not step_wins:
        rise_w = list(wins)
        values, r = _fit(model, ocv, values, ["soc_a", "soc_b"], rise_w, V_max)
        values, res = _fit(model, ocv, values, kin, last, V_max)
        return values, kin, res, {"rise": (["soc_a", "soc_b"], r, rise_w), "middle": "pulses"}

    long_w = _long_for_slow(step_wins)
    rise_w = list(wins) + [w.to_end() for w in step_wins]
    # Judged on what a study runs: the discharges and drive cycles (the steps if there are none).
    judge = [w for w in long_w if w.kind in ("discharge", "cycle")] or long_w
    ways = {}
    for way in ("pulses", "long tests"):
        own = ["tau_m"] if way == "long tests" else []
        slow, k = [*SLOW_NAMES, *own], [n for n in kin if n not in own]
        v, r_slow = _fit(model, ocv, dict(values), slow, long_w, V_max)
        v, r_rise = _fit(model, ocv, v, ["soc_a", "soc_b"], rise_w, V_max)
        v, res = _fit(model, ocv, v, k, last, V_max)
        stages = {"slow": (slow, r_slow, long_w), "rise": (["soc_a", "soc_b"], r_rise, rise_w), "middle": way}
        score = (_rms(_residuals(model, ocv, v, judge, V_max)), _rms(_residuals(model, ocv, v, mid, V_max)))
        ways[way] = (v, k, res, stages, score)
    a, b = ways["pulses"], ways["long tests"]
    better_long = b[4][0] < a[4][0]
    pulses_hold = b[4][1] <= (1.0 + PULSE_SLACK) * a[4][1]
    return (b if better_long and pulses_hold else a)[:4]


PULSE_SLACK = 0.1  # the pulses may fit up to 10% worse for the long tests to set tau_m


def _rms(r: np.ndarray) -> float:
    return float(np.sqrt(np.mean(r**2))) if r.size else 0.0


def _steady_R(ecm: ECM, T: float, I: float, have_steps: bool) -> float:
    """The model's steady resistance at a slow test's current: its drop, added back to give the curve."""
    return ecm.R0(T) + ecm.eta_ss(I, T) / I + ecm.Rm(T) + (ecm.Rd(T) if have_steps else 0.0)


def _curves_by_T(ocv: OCVCurve, sets: list[TestSet], ecm0: ECM | None, have_steps: bool) -> list[OCVCurve]:
    """Each set's slow test as an open-circuit curve on the reference's state of charge; set on ocv.by_T."""
    out = []
    for t in sets:
        c = ocv_from_slow_test(t.slow, reference_Ah=ocv.capacity_Ah)
        if c.T_K is None:
            raise ValueError(f"{t.slow.source}: no cell temperature, so its curve can't be placed by temperature")
        if ecm0 is not None:
            T = c.T_K
            c = ocv_from_slow_test(
                t.slow,
                _steady_R(ecm0, T, c.current_A, have_steps),
                factor=lambda soc, e=ecm0, T=T: e.soc_factor(soc, T),
                reference_Ah=ocv.capacity_Ah,
            )
        out.append(c)
    ocv.by_T = (ocv.as_row(), *(c.as_row() for c in out)) if out else ()
    return out


def _median_T_C(wins: list[Window]) -> float:
    return float(np.median(np.concatenate([w.trace.T_K[w.k0 : w.k1] for w in wins]))) - 273.15


ARRHENIUS = {  # value -> (its law, sign: +1 grows in the cold, -1 falls)
    "R0_25C": ("Ea_R0", 1.0),
    "I0_25C": ("Ea_I0", -1.0),
    "Rm_25C": ("Ea_Rm", 1.0),
    "Rd_25C": ("Ea_Rd", 1.0),
    "soc_a": ("Ea_soc", 1.0),
}
R_GAS = 8.314462618


def _row(f: _SetFit) -> tuple[float, ...]:
    """One temperature's own values as a row of the table (see ecm.BY_T_COLUMNS)."""
    v = f.values
    return (
        f.T_C + 273.15,
        v["R0_25C"],
        v["I0_25C"],
        v["gamma"],
        v["tau_ct"],
        v["Rm_25C"],
        v["tau_m"],
        v["Rd_25C"],
        v["tau_d"],
        v["soc_a"],
        v["soc_b"],
    )


def _laws_through(fits: list[_SetFit], model) -> list[ParamResult]:
    """Arrhenius laws through each temperature's own values (log value against 1/T), with 95% ranges.

    They carry the table beyond the coldest and warmest temperatures fitted,
    and show how far a single law would describe the cell. The slow branch's
    law uses only the temperatures with long tests.
    """
    from scipy import stats

    out = []
    for name, (law, sign) in ARRHENIUS.items():
        use = [f for f in fits if f.slow is not None] if name == "Rd_25C" else fits
        # A value at the edge of its range was not determined by its tests: it does not set a law.
        vp = model.param(name)
        use = [f for f in use if not _at_edge(f.values[name], vp)]
        prm = model.param(law)
        if len(use) < 2:
            continue
        x = np.array([(1.0 / (f.T_C + 273.15) - 1.0 / T_REF) / R_GAS for f in use])
        y = np.log([max(f.values[name], 1e-6) for f in use])
        slope, icpt = np.polyfit(x, y, 1)
        Ea = float(np.clip(sign * slope, prm.lo, prm.hi))
        ci, note = None, ""
        if len(use) > 2:
            resid = y - (slope * x + icpt)
            se = math.sqrt(float(np.sum(resid**2)) / (len(use) - 2) / float(np.sum((x - x.mean()) ** 2)))
            q = float(stats.t.ppf(0.975, len(use) - 2))
            ci = (Ea - q * se, Ea + q * se)
            # How far the temperatures' own values sit off the line (a factor, at worst).
            off = float(np.exp(np.max(np.abs(resid))))
            if off > 1.25:
                note = f"the temperatures' own values sit up to {off:.2g}x off this law: the table follows them"
        else:
            note = "a law through two temperatures: not checked by a third"
        what = prm.what + " (through the temperatures' own values; used beyond the coldest and warmest)"
        out.append(ParamResult(law, "J/mol", Ea, "fitted", what, ci, None, note))
    return out


def _at_edge(v: float, p: Param) -> bool:
    return abs(v - p.lo) <= 1e-3 * max(abs(p.lo), 1e-9) or abs(v - p.hi) <= 1e-3 * abs(p.hi)


def _laws_only(model, values, ocv, V_max) -> ECM:
    return model.ecm(values, ocv, V_max)


def fit_cell(
    slow: TestRecord,
    pulses: TestRecord | None = None,
    steps: TestRecord | None = None,
    checks: list[TestRecord] | None = None,
    compare_ecm: tuple[str, ECM, float] | None = None,
    V_max: float | None = None,
    sets: list[TestSet] | None = None,
    check_soc0: list[float | None] | None = None,
) -> FitResult:
    """Fit the circuit model, at one temperature or several.

    slow: a slow full discharge (C/20) from full to the cut-off: the open-circuit voltage and capacity.
    pulses, steps: the tests at one temperature (see TestSet); or sets: the tests at several.
      A pulse (HPPC) test fits R0, the charge-transfer branch and the near-empty rise;
      steps with rests after them fit the slow branch (Rd, tau_d).
    checks: tests the fit does not see, predicted afterwards (a drive cycle, say); check_soc0, where each
      starts, if known (otherwise a rest in it, or its first voltage, anchors it).
    compare_ecm: (name, ECM, capacity) of a model to predict the checks with too, such as a library cell's.

    With tests at several temperatures, each is first fitted on its own (its
    values at its temperature), straight lines through those (log value
    against 1/T) start the temperature laws, and a joint fit over every test,
    each replayed at its measured cell temperature, gives the model. With one,
    the temperature laws are the library NCR18650PF's, and the fitted cell
    file says so.
    """
    if sets is None:
        if pulses is None:
            raise ValueError("give the pulse test (pulses) or the tests by temperature (sets)")
        sets = [TestSet(pulses, steps)]
    elif pulses is not None or steps is not None:
        raise ValueError("give either pulses and steps, or sets, not both")
    multi = len(sets) > 1
    if multi and any(t.at_C is None for t in sets):
        raise ValueError("with tests at several temperatures, give each set its temperature (at_C)")
    long_at = [t.steps is not None or bool(t.discharges) or bool(t.cycles) for t in sets]
    have_steps = any(long_at)  # long tests (steps or discharges): the slow branch is fitted

    model = CircuitModel()
    notes: list[str] = []
    ocv = ocv_from_slow_test(slow)
    cap = ocv.capacity_Ah
    notes += ocv.notes
    others = [t for t in sets if t.slow is not None and t.slow is not slow and t.slow.source != slow.source]
    if others and ocv.T_K is None:
        raise ValueError(f"{slow.source}: no cell temperature, so its curve can't be placed among those by temperature")
    curves = _curves_by_T(ocv, others, None, False)
    records = [slow, *(r for t in sets for r in (t.pulses, t.steps, *t.discharges, *t.cycles) if r is not None)]
    if V_max is None:
        V_max = round(float(max(np.max(r.voltage_V) for r in records)), 2)
        V_max = min(max(V_max, 3.4), 4.5)
    T_slow = T_REF
    if slow.temperature_C is not None and ocv.discharge_span is not None:
        a, b = ocv.discharge_span
        Ts = slow.temperature_C[a:b]
        if np.isfinite(Ts).any():
            T_slow = float(np.nanmedian(Ts)) + 273.15

    start = {p.name: p.start for p in model.params}
    if multi:  # each temperature's own values: no law inside one set
        start.update({p.name: 0.0 for p in model.temperature_params})
    anchors: dict[str, str] = {}
    fits: list[_SetFit] = []
    values = dict(start)
    laws: list[ParamResult] = []
    rows: tuple = ()
    starts: dict[int, dict[str, float]] = {}
    # In rounds: the open-circuit voltage needs the model's steady resistance (for the slow
    # test's own drop), the state of charge in each test needs the curve, and each stage of
    # the fit holds the others' values from the round before. Three rounds bring tests made
    # by a known cell to within a few percent (two left the slow branch 17% off).
    for _ in range(ROUNDS):
        fits = []
        for t in sets:
            wins, step_wins = _windows(t, ocv, cap, anchors)
            v, nm, res, stages = _fit_one(model, ocv, starts.get(id(t), start), wins, step_wins, V_max)
            fits.append(_SetFit(t, wins, step_wins, v, nm, res, _median_T_C(wins), stages))
            starts[id(t)] = v
        if multi:
            # Each temperature's own values become a row; laws through them go beyond the coldest and warmest.
            laws = _laws_through(fits, model)
            values = {**min(fits, key=lambda f: abs(f.T_C - 25.0)).values, **{p.name: p.value for p in laws}}
            rows = tuple(_row(f) for f in fits)
            ecm0 = model.ecm(values, ocv, V_max, by_T=rows)
            values.update({n: _law_value(ecm0, n, T_REF) for n in BASE_NAMES + SLOW_NAMES})  # the 25 degC values
        else:
            values = fits[0].values
            ecm0 = model.ecm(values, ocv, V_max)
        I_s = ocv.current_A
        R_ss = (
            ecm0.R0(T_slow)
            + ecm0.eta_ss(I_s, T_slow) / I_s
            + ecm0.Rm(T_slow)
            + (ecm0.Rd(T_slow) if have_steps else 0.0)
        )
        ocv = ocv_from_slow_test(slow, R_ss, factor=lambda soc, e=ecm0, T=T_slow: e.soc_factor(soc, T))
        curves = _curves_by_T(ocv, others, ecm0, have_steps)

    ecm = model.ecm(values, ocv, V_max, by_T=rows)
    correlated: list[tuple[str, str, float]] = []
    if multi:
        params = list(laws)
    else:
        f = fits[0]
        sizes = [w.k1 - w.k0 - 1 for w in f.wins]  # the kinetics stage: the pulses
        params, correlated = _uncertainty(model, f.names, f.values, f.res, sizes)
        params += _stage_params(model, f.values, f.stages.get("rise"))
        params += _slow_params(model, f.values, f.slow)
    params.append(ParamResult("capacity_Ah", "Ah", cap, "data", "capacity: the slow discharge's charge"))
    params.append(ParamResult("V_min", "V", ocv.V_min, "data", "discharge cut-off: where the slow discharge stopped"))
    params.append(ParamResult("V_max", "V", V_max, "data", "charge limit: the highest voltage in the tests"))
    for k, v in DEFAULT_TEMPERATURE_LAWS.items():
        if multi and any(p.name == k for p in laws):
            continue
        what = f"temperature behaviour ({k}): the library NCR18650PF's, not fitted"
        note = (
            "give long tests (steps, discharges or cycles) at two temperatures or more to fit it"
            if multi
            else "fitted from tests at several temperatures (see docs/FITTING.md)"
        )
        params.append(ParamResult(k, "J/mol", v, "default", what, note=note))

    # Errors on what the fit saw, with the model as fitted (with several temperatures: the table).
    errors: dict[str, dict] = {}
    per_temperature = []
    for f in fits:
        tag = f", {f.test.label()}" if multi else ""
        steps_only = [w for w in f.step_wins if w.kind == "step"]
        kin = "pulses" if f.test.pulses is not None else "changes in current"
        for label, ws in (
            (f"{kin} at 20-95% SOC", [w for w in f.wins if MID_SOC[0] <= w.soc0 <= MID_SOC[1]]),
            (f"{kin} below 20% SOC", [w for w in f.wins if w.soc0 < MID_SOC[0]]),
            ("steps at 20-95% SOC", [w for w in steps_only if MID_SOC[0] <= w.soc0 <= MID_SOC[1]]),
            ("steps below 20% SOC", [w for w in steps_only if w.soc0 < MID_SOC[0]]),
            ("discharges", [w for w in f.step_wins if w.kind == "discharge"]),
            ("drive cycles fitted on", [w for w in f.step_wins if w.kind == "cycle"]),
        ):
            if not ws:
                continue
            r = _residuals_ecm(model, ecm, ws)
            rms, mx = _rms_mV(r)
            errors[label + tag] = {"rmse_mV": rms, "max_mV": mx, "samples": int(r.size), "parts": len(ws)}
        if multi:
            sizes = [w.k1 - w.k0 - 1 for w in f.wins]  # the kinetics stage: the pulses
            own_params, own_corr = _uncertainty(model, f.names, f.values, f.res, sizes)
            own_params += _stage_params(model, f.values, f.stages.get("rise"))
            own_params += _slow_params(model, f.values, f.slow)
            correlated += [(a, b, c) for a, b, c in own_corr if (a, b) not in {(x, y) for x, y, _ in correlated}]
            per_temperature.append(
                {
                    "at_C": f.test.at_C,
                    "cell_C": round(f.T_C, 1),
                    "pulses": len(f.wins),
                    "params": own_params,
                    "tau_m_from": f.stages.get("middle", "pulses"),
                    "slow_capacity_Ah": next(
                        (c.capacity_Ah for c, t in zip(curves, others) if t is f.test),
                        cap if f.test.slow is not None else None,
                    ),
                    "law": {n: _law_value(_laws_only(model, values, ocv, V_max), n, f.T_C + 273.15) for n in ARRHENIUS},
                }
            )

    check_out, plot_checks = _checks(model, ecm, ocv, cap, checks or [], compare_ecm, check_soc0)

    wins_all = [w for f in fits for w in f.wins]
    steps_all = [w for f in fits for w in f.step_wins]
    validity = _validity(slow, ocv, wins_all, steps_all, multi)
    h = hysteresis_mV(ocv)
    if h is not None:
        notes.append(
            f"the slow charge and discharge differ by about {2 * h:.0f} mV beyond their drops (hysteresis): "
            "the curve follows the discharge, as the library's does"
        )
    if not have_steps:
        notes.append("no test with long steps and rests: the slow branch (Rd, tau_d) is not fitted")
    from_long = [f for f in fits if f.stages.get("middle") == "long tests"]
    if from_long:
        at = ", ".join(f"{f.T_C:.0f}" for f in from_long)
        notes.append(
            f"the middle branch's time constant (tau_m) set by the long tests at {at} degC, where they fit "
            "better that way and the pulses still fit (elsewhere by the pulses)"
        )
    for rec in (*records, *(checks or [])):
        for w in rec.warnings:
            notes.append(f"{rec.source}: {w}")

    sims: dict[int, np.ndarray] = {}  # one replay per trace: windows from the long tests share theirs

    def sim(w: Window) -> np.ndarray:
        if id(w.trace) not in sims:
            sims[id(w.trace)] = w.trace.simulate(model, ecm)
        return w.model_V(sims[id(w.trace)])

    plot_data = {
        "ocv": ocv,
        "pulses": [(w, sim(w)) for w in fits[0].wins] if not multi else [],
        "steps": [(w, sim(w)) for w in fits[0].step_wins] if not multi else [],
        "pulses_by_T": {f.test.label(): [(w, sim(w)) for w in f.wins] for f in fits} if multi else {},
        "checks": plot_checks,
    }
    temps = sorted({f.test.at_C for f in fits if f.test.at_C is not None})
    return FitResult(
        ocv_curves=curves,
        model=model,
        ocv=ocv,
        ecm=ecm,
        params=params,
        capacity_Ah=cap,
        errors=errors,
        checks=check_out,
        validity=validity,
        correlated=correlated,
        notes=notes,
        records={
            "slow": [slow, *(t.slow for t in others)],
            "pulses": [t.pulses for t in sets if t.pulses is not None],
            "steps": [t.steps for t in sets if t.steps is not None],
            "checks": list(checks or []),
        },
        soc_anchors=anchors,
        settings={
            "pulse window": f"{PRE_S:g} s before each pulse to {POST_S:g} s after",
            "kinetics fitted on": f"pulses at {MID_SOC[0]:.0%}-{MID_SOC[1]:.0%} SOC, then the near-empty rise on all"
            + (
                f"; with no pulse test (at {', '.join(t.label() or 'its temperature' for t in sets if t.pulses is None)}), "
                f"on the discharges' and cycles' changes in current of {STEP_C:g}C or more from one sample to the "
                f"next, each from {PRE_S:g} s before to {LOAD_S:g} s after, at {MID_SOC[0]:.0%}-{MID_SOC[1]:.0%} SOC"
                if any(t.pulses is None for t in sets)
                else ""
            ),
            "temperature behaviour": (
                "Arrhenius laws fitted jointly over tests at "
                + ", ".join(f"{x:g}" for x in temps)
                + " degC, each replayed at its measured cell temperature; the time constants, gamma and soc_b "
                "do not change with temperature, as in PackTherm's model"
                if multi
                else "the library NCR18650PF's (not fitted at one temperature)"
            ),
            "uncertainty": (
                "95% ranges counting each pulse and step as one piece of evidence (cluster-robust): they show how "
                "far the tests disagree, not a guarantee; a value the tests barely touch is flagged"
            ),
        },
        plot_data=plot_data,
        temperatures=temps,
        per_temperature=per_temperature,
    )


def _stage_params(model, values, stage) -> list[ParamResult]:
    """Values fitted in a stage of their own, with ranges from it."""
    if stage is None:
        return []
    nms, res, wins = stage
    out, _ = _uncertainty(model, nms, values, res, [w.k1 - w.k0 - 1 for w in wins])
    return out


def _slow_params(model, values, stage) -> list[ParamResult]:
    """The slow branch's values, with ranges from its own stage (fitted on long tests), or marked not fitted."""
    if stage is None:
        out = []
        for nme in SLOW_NAMES:
            prm = model.param(nme)
            out.append(
                ParamResult(nme, prm.unit, values[nme], "not fitted", prm.what, note="a starting value: give a steps test")
            )
        return out
    nms, res, wins = stage
    out, _ = _uncertainty(model, nms, values, res, [w.k1 - w.k0 - 1 for w in wins])
    for p in out:
        p.what += " (fitted on the long tests: steps and discharges)"
    return out


def _law_value(ecm: ECM, name: str, T: float) -> float:
    """A value as the fitted laws give it at temperature T (what each temperature's own fit is compared with)."""
    return {
        "R0_25C": lambda: ecm.R0(T),
        "I0_25C": lambda: ecm.I0(T),
        "Rd_25C": lambda: ecm.Rd(T),
        "Rm_25C": lambda: ecm.Rm(T),
        "tau_m": lambda: ecm.tau_m_at(T),
        "soc_a": lambda: ecm.soc_factor(0.0, T) - 1.0,
        "gamma": lambda: ecm.gamma_at(T),
        "tau_ct": lambda: ecm.tau_ct_at(T),
        "tau_d": lambda: ecm.tau_d_at(T),
        "soc_b": lambda: ecm.soc_b,
    }[name]()


def _checks(model, ecm, ocv, cap, checks, compare_ecm, soc0s=None):
    """Tests the fit never saw: replayed with their measured cell temperature, voltage against measured."""
    check_out, plot_checks = [], []
    soc0s = list(soc0s or []) + [None] * len(checks)
    for rec, soc0 in zip(checks, soc0s):
        row = {"file": rec.source}
        soc_c, how = track_soc(rec, ocv, cap, soc0=soc0)
        I = interval_current(rec)
        T = temperature_K(rec)
        Vm = model.simulate(ecm, rec.t, I, soc_c, T, rec.current_A)
        # Down to the knee near empty, as the fit scores its long tests; the whole record beside it.
        knee = ocv.V_min + KNEE_SHARE * (ocv.V_top - ocv.V_min)
        use = (rec.voltage_V > knee)[1:]
        r_all = (Vm - rec.voltage_V)[1:]
        r = r_all[use] if use.any() else r_all
        row["rmse_mV"], row["max_mV"] = _rms_mV(r)
        row["rmse_whole_mV"] = _rms_mV(r_all)[0]
        row["cell_C"] = round(float(np.median(T)) - 273.15, 1)
        row["soc_start"] = float(soc_c[0])
        row["anchored"] = how
        plot = {"file": rec.source, "t": rec.t, "V": rec.voltage_V, "fit": Vm}
        if compare_ecm is not None:
            name, lib, lib_cap = compare_ecm
            lib_curve = OCVCurve(np.array(lib.ocv_soc), np.array(lib.ocv_V), lib_cap, lib.V_min, 0, 0, "library")
            soc_l, _ = track_soc(rec, lib_curve, lib_cap, soc0=soc0)
            Vl = model.simulate(lib, rec.t, I, soc_l, T, rec.current_A)
            rl_all = (Vl - rec.voltage_V)[1:]
            rl = rl_all[use] if use.any() else rl_all
            row["compare"] = name
            row["compare_rmse_mV"], row["compare_max_mV"] = _rms_mV(rl)
            plot["compare"], plot["compare_name"] = Vl, name
        check_out.append(row)
        plot_checks.append(plot)
    return check_out, plot_checks


def _uncertainty(
    model, names, values, res, sizes: list[int]
) -> tuple[list[ParamResult], list[tuple[str, str, float]]]:
    """95% ranges and correlations, counting each window (a pulse, a step) as one piece of evidence.

    The usual ranges from a least-squares fit assume every sample's error is
    independent noise. Here they are not: what is left after a fit like this
    is mostly the model's own misfit, the same shape through a whole pulse.
    Treated as independent, ten thousand samples would claim a precision the
    tests cannot give (on noise-free test data, every true value fell outside
    those ranges). So the covariance is the cluster-robust ("sandwich") one,
    with each window a cluster: the spread is how far the windows disagree.
    """
    J = res.jac
    p = J.shape[1]
    r = res.fun
    try:
        B = np.linalg.pinv(J.T @ J)
        M = np.zeros((p, p))
        a = 0
        for m in sizes:
            g = J[a : a + m].T @ r[a : a + m]
            M += np.outer(g, g)
            a += m
        G = len(sizes)
        cov = B @ M @ B * (G / max(G - p, 1))
    except np.linalg.LinAlgError:  # pragma: no cover
        cov = np.full((p, p), np.nan)
    sd = np.sqrt(np.clip(np.diag(cov), 0, None))
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = cov / np.outer(sd, sd)
    out = []
    for i, nme in enumerate(names):
        prm = model.param(nme)
        v = values[nme]
        if not np.isfinite(sd[i]) or (prm.lo > 0 and sd[i] > 5):  # a range of more than e^10: the tests do not pin it
            ci, rel = None, None
        elif prm.lo > 0:  # fitted in logs: a multiplicative range
            ci = (v * math.exp(-1.96 * sd[i]), v * math.exp(1.96 * sd[i]))
            rel = float(sd[i])
        else:
            sd_i = sd[i] * prm.scale
            ci = (v - 1.96 * sd_i, v + 1.96 * sd_i)
            rel = float(sd_i / abs(v)) if v else None
        ci = None if ci is None else (float(ci[0]), float(ci[1]))
        note = ""
        if ci is None:
            note = "not determined by these tests: no usable range"
        elif rel is not None and rel > 0.5:
            note = "poorly determined by these tests"
        at_bound = abs(v - prm.lo) <= 1e-3 * max(abs(prm.lo), 1e-12) or abs(v - prm.hi) <= 1e-3 * abs(prm.hi)
        if at_bound:
            note = "at the edge of its allowed range: not determined by these tests"
        out.append(ParamResult(nme, prm.unit, v, "fitted", prm.what, ci, rel, note))
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if np.isfinite(corr[i, j]) and abs(corr[i, j]) > 0.95:
                pairs.append((names[i], names[j], float(corr[i, j])))
    return out, pairs


def _validity(slow: TestRecord, ocv: OCVCurve, wins: list[Window], step_wins: list[Window], multi: bool = False) -> dict:
    """What the fit saw: the cell temperatures in the parts it used, the state of charge and rates of its pulses."""
    temps = [w.trace.T_K[w.k0 : w.k1] - 273.15 for w in (*wins, *step_wins)]
    if slow.temperature_C is not None and ocv.discharge_span is not None:
        a, b = ocv.discharge_span
        temps.append(slow.temperature_C[a:b])
    T = np.concatenate(temps) if temps else np.zeros(0)
    T = T[np.isfinite(T)]
    dis = [w.c_rate for w in wins if w.kind != "load" and w.c_rate > 0]
    chg = [-w.c_rate for w in wins if w.kind != "load" and w.c_rate < 0]
    # A change in current (no pulse test) can hold both: its peak each way, where it has one of 0.05C or more,
    # over 30 s as a study's check of the range takes it (electrothermal.check_fitted_range).
    for w in wins:
        if w.kind == "load":
            i = w.trace.now[w.k0 : w.k1] / ocv.capacity_Ah
            n = max(1, min(i.size, round(30.0 / float(np.median(np.diff(w.t))))))
            i = np.convolve(i, np.ones(n) / n, mode="valid")
            dis += [float(i.max())] if i.max() >= 0.05 else []
            chg += [float(-i.min())] if i.min() <= -0.05 else []
    return {
        "temperature_C": [round(float(T.min()), 1), round(float(T.max()), 1)] if T.size else None,
        "soc": [round(float(min(w.soc0 for w in wins)), 3), round(float(max(w.soc0 for w in wins)), 3)],
        "discharge_C": [round(float(min(dis)), 2), round(float(max(dis)), 2)] if dis else None,
        "charge_C": [round(float(min(chg)), 2), round(float(max(chg)), 2)] if chg else None,
        "pulse_s": round(float(np.median([w.t[-1] - w.t[0] for w in wins])), 1),
        "note": (
            "the tests covered these; outside them the model is extrapolating"
            + (
                " (beyond the coldest and warmest, by the fitted laws)."
                if multi
                else ". One temperature only: the temperature behaviour is not fitted."
            )
        ),
    }


def replace_ocv(ecm: ECM, ocv: OCVCurve) -> ECM:  # used by tests
    return replace(ecm, ocv_soc=tuple(ocv.soc), ocv_V=tuple(ocv.V))
