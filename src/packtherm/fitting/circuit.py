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
DEFAULT_TEMPERATURE_LAWS = {"Ea_R0": 0.0, "Ea_I0": 45.2e3, "Ea_Rd": 26.8e3, "Ea_soc": 20.7e3}
MID_SOC = (0.2, 0.95)  # the kinetics fit on these pulses; the near-empty rise then on all
PRE_S, POST_S = 5.0, 40.0  # each pulse window: this long before, and after the pulse
MIN_STEP_S = 5 * 60  # a steady step this long has settled by its end
SETTLED_REST_S = 10 * 60  # a rest this long leaves the cell settled enough to replay a pulse from


@dataclass(frozen=True)
class Param:
    name: str
    unit: str
    lo: float
    hi: float
    start: float
    what: str  # in words, for the cell file and report


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
        Param("tau_ct", "s", 0.2, 60.0, 3.0, "time constant of the charge-transfer branch"),
        Param("Rd_25C", "Ohm", 1e-4, 0.5, 0.02, "resistance of the slow (diffusion) branch"),
        Param("tau_d", "s", 30.0, 5000.0, 400.0, "time constant of the slow branch"),
        Param("soc_a", "-", 0.0, 50.0, 1.0, "size of the rise near empty"),
        Param("soc_b", "-", 0.01, 0.5, 0.08, "how far up from empty the rise reaches (SOC)"),
    )

    def ecm(self, values: dict[str, float], ocv: OCVCurve, V_max: float = 4.2, cv_cutoff_A: float = 0.05) -> ECM:
        return ECM(
            ocv_soc=tuple(float(x) for x in ocv.soc),
            ocv_V=tuple(float(x) for x in ocv.V),
            R0_25C=values["R0_25C"],
            Ea_R0=DEFAULT_TEMPERATURE_LAWS["Ea_R0"],
            I0_25C=values["I0_25C"],
            Ea_I0=DEFAULT_TEMPERATURE_LAWS["Ea_I0"],
            gamma=values["gamma"],
            tau_ct=values["tau_ct"],
            Rd_25C=values["Rd_25C"],
            tau_d=values["tau_d"],
            V_max=V_max,
            V_min=ocv.V_min,
            cv_cutoff_A=cv_cutoff_A,
            soc_a=values["soc_a"],
            soc_b=values["soc_b"],
            Ea_soc=DEFAULT_TEMPERATURE_LAWS["Ea_soc"],
            Ea_Rd=DEFAULT_TEMPERATURE_LAWS["Ea_Rd"],
            sources=("fitted by packtherm.fitting",),
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
        R0, Rd = ecm.R0, ecm.Rd
        eta = vd = 0.0
        if steady_start:
            I0, T0 = float(now[0]), float(T_K[0])
            f0 = ecm.soc_factor(float(soc[0]), T0) if I0 > 0 else 1.0
            eta, vd = f0 * ecm.eta_ss(I0, T0), f0 * Rd(T0) * I0
        for k in range(t.size):
            Tk = float(T_K[k])
            if k:
                Im = float(current[k])
                dt = float(t[k] - t[k - 1])
                e1, e2 = math.exp(-dt / ecm.tau_ct), math.exp(-dt / ecm.tau_d)
                f = ecm.soc_factor(float(soc[k]), Tk) if Im > 0 else 1.0
                eta = eta * e1 + f * ecm.eta_ss(Im, Tk) * (1.0 - e1)
                vd = vd * e2 + f * Rd(Tk) * Im * (1.0 - e2)
            In = float(now[k])
            fn = ecm.soc_factor(float(soc[k]), Tk) if In > 0 else 1.0
            out[k] = ecm.ocv(float(soc[k])) - In * fn * R0(Tk) - eta - vd
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

    It is scored on the voltage's change from its first sample, so an error in
    the open-circuit voltage's level does not count, only its slope.
    """

    kind: str  # pulse or step
    trace: Trace
    k0: int  # the window's samples in its trace
    k1: int
    c_rate: float
    soc0: float

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


def _vec_to_values(model: CellModel, x: np.ndarray, names: list[str], fixed: dict[str, float]) -> dict[str, float]:
    v = dict(fixed)
    for n, xi in zip(names, x):
        p = next(q for q in model.params if q.name == n)
        v[n] = float(np.exp(xi)) if p.lo > 0 else float(xi)
    return v


def _x0(model: CellModel, names: list[str], values: dict[str, float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x, lo, hi = [], [], []
    for n in names:
        p = next(q for q in model.params if q.name == n)
        if p.lo > 0:  # positive: fit its logarithm
            x.append(math.log(min(max(values[n], p.lo * 1.0001), p.hi * 0.9999)))
            lo.append(math.log(p.lo))
            hi.append(math.log(p.hi))
        else:
            x.append(min(max(values[n], p.lo), p.hi))
            lo.append(p.lo)
            hi.append(p.hi)
    return np.array(x), np.array(lo), np.array(hi)


def _residuals(model, ocv, values, windows: list[Window], V_max) -> np.ndarray:
    """Model minus measured change in voltage through each window, from its first sample."""
    ecm = model.ecm(values, ocv, V_max)
    sims: dict[int, np.ndarray] = {}
    parts = []
    for w in windows:
        key = id(w.trace)
        if key not in sims:
            sims[key] = w.trace.simulate(model, ecm)
        Vm, V = w.model_V(sims[key]), w.V
        parts.append(((Vm - Vm[0]) - (V - V[0]))[1:])
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


def fit_cell(
    slow: TestRecord,
    pulses: TestRecord,
    steps: TestRecord | None = None,
    checks: list[TestRecord] | None = None,
    compare_ecm: tuple[str, ECM, float] | None = None,
    V_max: float | None = None,
) -> FitResult:
    """Fit the circuit model at one temperature.

    slow: a slow full discharge (C/20) from full to the cut-off: the open-circuit voltage and capacity.
    pulses: a pulse (HPPC) test: R0, the charge-transfer branch, the near-empty rise.
    steps: optional, a test with long steady steps and rests: the slow branch (Rd, tau_d).
    checks: tests the fit does not see, predicted afterwards (a drive cycle, say).
    compare_ecm: (name, ECM, capacity) of a model to predict the checks with too, such as a library cell's.
    """
    model = CircuitModel()
    notes: list[str] = []
    ocv = ocv_from_slow_test(slow)
    cap = ocv.capacity_Ah
    notes += ocv.notes
    if V_max is None:
        V_max = round(float(max(np.max(r.voltage_V) for r in (slow, pulses, *(c for c in [steps] if c)))), 2)
        V_max = min(max(V_max, 3.4), 4.5)

    values = {p.name: p.start for p in model.params}
    # The fit is iterated twice: the open-circuit voltage needs the model's
    # steady resistance (for the slow test's own drop), and the state of charge
    # in each test needs the curve.
    anchors: dict[str, str] = {}
    for _ in range(2):
        soc_p, anchors["pulses"] = track_soc(pulses, ocv, cap)
        wins = pulse_windows(pulses, soc_p, cap)
        if len(wins) < 5:
            raise ValueError(f"{pulses.source}: only {len(wins)} pulses found; a pulse test needs at least 5")
        mid = [w for w in wins if MID_SOC[0] <= w.soc0 <= MID_SOC[1]]
        values["soc_a"] = 0.0
        values, _ = _fit(model, ocv, values, ["R0_25C", "I0_25C", "gamma", "tau_ct"], mid, V_max)
        step_wins: list[Window] = []
        if steps is not None:
            soc_s, anchors["steps"] = track_soc(steps, ocv, cap)
            step_wins = step_windows(steps, soc_s, cap)
            if len(step_wins) < 2:
                raise ValueError(
                    f"{steps.source}: {len(step_wins)} steady steps followed by a rest of 5 min or more; needs 2"
                )
            step_mid = [w for w in step_wins if MID_SOC[0] <= w.soc0 <= MID_SOC[1]]
            values, _ = _fit(model, ocv, values, ["Rd_25C", "tau_d"], step_mid or step_wins, V_max)
        values["soc_a"] = 1.0
        values, _ = _fit(model, ocv, values, ["soc_a", "soc_b"], wins, V_max)
        ecm0 = model.ecm(values, ocv, V_max)
        # Steady resistance at the slow test's current: what its voltage sits below the curve by.
        I_s = ocv.current_A
        R_ss = ecm0.R0(T_REF) + ecm0.eta_ss(I_s, T_REF) / I_s + (ecm0.Rd(T_REF) if steps is not None else 0.0)
        ocv = ocv_from_slow_test(slow, R_ss, factor=lambda soc, e=ecm0: e.soc_factor(soc))

    # Final: all fitted values together, for their uncertainties and correlations.
    names = ["R0_25C", "I0_25C", "gamma", "tau_ct", "soc_a", "soc_b"] + (["Rd_25C", "tau_d"] if steps else [])
    all_wins = list(wins) + [w for w in step_wins if w.soc0 >= MID_SOC[0]]
    values, res = _fit(model, ocv, values, names, all_wins, V_max)
    ecm = model.ecm(values, ocv, V_max)

    params, correlated = _uncertainty(model, names, values, res, steps is not None, [w.k1 - w.k0 - 1 for w in all_wins])
    params.append(ParamResult("capacity_Ah", "Ah", cap, "data", "capacity: the slow discharge's charge"))
    params.append(ParamResult("V_min", "V", ocv.V_min, "data", "discharge cut-off: where the slow discharge stopped"))
    params.append(ParamResult("V_max", "V", V_max, "data", "charge limit: the highest voltage in the tests"))
    for k, v in DEFAULT_TEMPERATURE_LAWS.items():
        params.append(
            ParamResult(
                k,
                "J/mol",
                v,
                "default",
                f"temperature behaviour ({k}): the library NCR18650PF's, not fitted",
                note="fitted from tests at several temperatures in v0.6.2",
            )
        )

    # Errors on what the fit saw.
    errors = {}
    for label, ws in (
        ("pulses at 20-95% SOC", [w for w in wins if MID_SOC[0] <= w.soc0 <= MID_SOC[1]]),
        ("pulses below 20% SOC", [w for w in wins if w.soc0 < MID_SOC[0]]),
        ("steps at 20-95% SOC", [w for w in step_wins if MID_SOC[0] <= w.soc0 <= MID_SOC[1]]),
        ("steps below 20% SOC", [w for w in step_wins if w.soc0 < MID_SOC[0]]),
    ):
        if ws:
            r = _residuals(model, ocv, values, ws, V_max)
            rms, mx = _rms_mV(r)
            errors[label] = {"rmse_mV": rms, "max_mV": mx, "samples": int(r.size), "parts": len(ws)}

    # Held-out tests.
    check_out = []
    plot_checks = []
    for rec in checks or []:
        row = {"file": rec.source}
        soc_c, how = track_soc(rec, ocv, cap)
        I = interval_current(rec)
        T = temperature_K(rec)
        Vm = model.simulate(ecm, rec.t, I, soc_c, T, rec.current_A)
        r = (Vm - rec.voltage_V)[1:]
        row["rmse_mV"], row["max_mV"] = _rms_mV(r)
        row["soc_start"] = float(soc_c[0])
        row["anchored"] = how
        plot = {"file": rec.source, "t": rec.t, "V": rec.voltage_V, "fit": Vm}
        if compare_ecm is not None:
            name, lib, lib_cap = compare_ecm
            lib_curve = OCVCurve(np.array(lib.ocv_soc), np.array(lib.ocv_V), lib_cap, lib.V_min, 0, 0, "library")
            soc_l, _ = track_soc(rec, lib_curve, lib_cap)
            Vl = model.simulate(lib, rec.t, I, soc_l, T, rec.current_A)
            rl = (Vl - rec.voltage_V)[1:]
            row["compare"] = name
            row["compare_rmse_mV"], row["compare_max_mV"] = _rms_mV(rl)
            plot["compare"], plot["compare_name"] = Vl, name
        check_out.append(row)
        plot_checks.append(plot)

    validity = _validity(slow, ocv, wins, step_wins)
    h = hysteresis_mV(ocv)
    if h is not None:
        notes.append(
            f"the slow charge and discharge differ by about {2 * h:.0f} mV beyond their drops (hysteresis): "
            "the curve follows the discharge, as the library's does"
        )
    if steps is None:
        notes.append("no test with long steps and rests: the slow branch (Rd, tau_d) is not fitted")
    for rec in (slow, pulses, *([steps] if steps else []), *(checks or [])):
        for w in rec.warnings:
            notes.append(f"{rec.source}: {w}")

    plot_data = {
        "ocv": ocv,
        "pulses": [(w, w.simulate(model, ecm)) for w in wins],
        "steps": [(w, w.simulate(model, ecm)) for w in step_wins],
        "checks": plot_checks,
    }
    return FitResult(
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
        records={"slow": [slow], "pulses": [pulses], "steps": [steps] if steps else [], "checks": list(checks or [])},
        soc_anchors=anchors,
        settings={
            "pulse window": f"{PRE_S:g} s before each pulse to {POST_S:g} s after",
            "kinetics fitted on": f"pulses at {MID_SOC[0]:.0%}-{MID_SOC[1]:.0%} SOC, then the near-empty rise on all",
            "temperature behaviour": "the library NCR18650PF's (not fitted at one temperature)",
            "uncertainty": (
                "95% ranges counting each pulse and step as one piece of evidence (cluster-robust): they show how "
                "far the tests disagree, not a guarantee; a value the tests barely touch is flagged"
            ),
        },
        plot_data=plot_data,
    )


def _uncertainty(
    model, names, values, res, have_steps, sizes: list[int]
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
        prm = next(q for q in model.params if q.name == nme)
        v = values[nme]
        if not np.isfinite(sd[i]) or sd[i] > 5:  # a range of more than e^10: the tests do not pin it
            ci, rel = None, None
        elif prm.lo > 0:  # fitted in logs: a multiplicative range
            ci = (v * math.exp(-1.96 * sd[i]), v * math.exp(1.96 * sd[i]))
            rel = float(sd[i])
        else:
            ci = (v - 1.96 * sd[i], v + 1.96 * sd[i])
            rel = float(sd[i] / abs(v)) if v else None
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
    if not have_steps:
        for nme in ("Rd_25C", "tau_d"):
            prm = next(q for q in model.params if q.name == nme)
            out.append(
                ParamResult(
                    nme, prm.unit, values[nme], "not fitted", prm.what, note="a starting value: give a steps test"
                )
            )
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if np.isfinite(corr[i, j]) and abs(corr[i, j]) > 0.95:
                pairs.append((names[i], names[j], float(corr[i, j])))
    return out, pairs


def _validity(slow: TestRecord, ocv: OCVCurve, wins: list[Window], step_wins: list[Window]) -> dict:
    """What the fit saw: the cell temperatures in the parts it used, the state of charge and rates of its pulses."""
    temps = [w.trace.T_K[w.k0 : w.k1] - 273.15 for w in (*wins, *step_wins)]
    if slow.temperature_C is not None and ocv.discharge_span is not None:
        a, b = ocv.discharge_span
        temps.append(slow.temperature_C[a:b])
    T = np.concatenate(temps) if temps else np.zeros(0)
    T = T[np.isfinite(T)]
    dis = [w.c_rate for w in wins if w.c_rate > 0]
    chg = [-w.c_rate for w in wins if w.c_rate < 0]
    return {
        "temperature_C": [round(float(T.min()), 1), round(float(T.max()), 1)] if T.size else None,
        "soc": [round(float(min(w.soc0 for w in wins)), 3), round(float(max(w.soc0 for w in wins)), 3)],
        "discharge_C": [round(float(min(dis)), 2), round(float(max(dis)), 2)] if dis else None,
        "charge_C": [round(float(min(chg)), 2), round(float(max(chg)), 2)] if chg else None,
        "pulse_s": round(float(np.median([w.t[-1] - w.t[0] for w in wins])), 1),
        "note": (
            "the tests covered these; outside them the model is extrapolating. One temperature only: "
            "the temperature behaviour is not fitted."
        ),
    }


def replace_ocv(ecm: ECM, ocv: OCVCurve) -> ECM:  # used by tests
    return replace(ecm, ocv_soc=tuple(ocv.soc), ocv_V=tuple(ocv.V))
