"""A circuit model from a BPX file's physics model (v0.6.16).

The file's DFN (or SPMe/SPM) runs in PyBaMM: a C/25 discharge and charge at
25 degC for the open-circuit voltage as the model sees it, then synthetic pulse
tests at several temperatures: from each state of charge, pulses of 10 s at several
C-rates with rests between. The same circuit as PackTherm's validated cells
(``packtherm.ecm.ECM``) is fitted to them, as ``validation/derive_m50_ecm.py``
did for the LG M50 in v0.4.11:

1. the 10 s overpotential of every pulse: R0 and the Butler-Volmer branch
   (I0, gamma), each with an Arrhenius temperature law;
2. the rise near empty (soc_a, soc_b, with temperature);
3. the slow branch and the charge-transfer time constant, by replaying the
   whole test record through the circuit.

Not measured data. For the LG M50 a derivation like this gave about half the
resistance measured on real cells (v0.6.9), so a derived cell's heat is a lower
bound until it is checked against pulses on the real cell.

Needs PyBaMM: ``pip install "packtherm[bpx-fit]"``.
"""

from __future__ import annotations

import math
import os
import time
import warnings
from dataclasses import dataclass, field, replace

import numpy as np

from .ecm import ECM, ECMState

R_GAS, F, T25 = 8.314462618, 96485.33212, 298.15
INSTALL_HINT = "Deriving a circuit from a BPX file needs PyBaMM, an optional extra: pip install 'packtherm[bpx-fit]'"


@dataclass(frozen=True)
class FitSettings:
    temperatures_C: tuple[float, ...] = (25.0, 10.0, 0.0, -10.0)
    socs: tuple[float, ...] = (0.95, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.15, 0.1, 0.05)
    rates_C: tuple[float, ...] = (0.2, 0.5, 1.0, 2.0, 3.0)
    pulse_s: float = 10.0
    rest_min: float = 60.0  # after each move to a new state of charge
    model: str = "DFN"


QUICK = FitSettings(
    temperatures_C=(25.0, 5.0, -10.0), socs=(0.9, 0.7, 0.5, 0.3, 0.15), rates_C=(0.5, 1.0, 2.0), rest_min=20.0
)


@dataclass
class FitReport:
    ecm: ECM
    settings: FitSettings
    pulses: int
    pulse_error_pct: dict[float, float]  # median |error| of the 10 s overpotential, by temperature
    replay_rmse_mV: dict[float, float]  # the whole record through the circuit, above 10 % state of charge
    seconds: float
    notes: list[str] = field(default_factory=list)


def overpotential(p, Tk, current):
    lnR0, Ea0, lnI0, EaI, gamma = p
    R0 = np.exp(lnR0) * np.exp(Ea0 / R_GAS * (1 / Tk - 1 / T25))
    I0 = np.exp(lnI0) * np.exp(-EaI / R_GAS * (1 / Tk - 1 / T25))
    return current * R0 + gamma * 2 * R_GAS * Tk / F * np.arcsinh(current / (2 * I0))


def synthetic_tests(path, capacity_Ah: float, V_min: float, settings: FitSettings, progress=None) -> dict:
    """Run the file's physics model through the pulse tests; records by temperature."""
    # PyBaMM's usage telemetry is opt-in; PackTherm keeps it off whatever the user's PyBaMM config says.
    os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
    try:
        import pybamm
    except ImportError as e:  # pragma: no cover - depends on the install
        raise RuntimeError(INSTALL_HINT) from e
    pybamm.telemetry.disable()
    pybamm.set_logging_level("ERROR")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        base = pybamm.ParameterValues.create_from_bpx(str(path))
    model_cls = {"DFN": pybamm.lithium_ion.DFN, "SPMe": pybamm.lithium_ion.SPMe, "SPM": pybamm.lithium_ion.SPM}
    make = model_cls.get(settings.model, pybamm.lithium_ion.DFN)
    rate_C3 = 1 / 3
    out = {}
    # The open-circuit voltage as the model sees it: C/25 down and back up at the reference temperature,
    # on the same state of charge as the pulse tests (1 - Q / nominal capacity from full).
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p25 = base.copy()
        p25.update({"Ambient temperature [K]": T25, "Initial temperature [K]": T25})
        V_max = p25["Upper voltage cut-off [V]"]
        down = pybamm.Simulation(
            make(),
            parameter_values=p25,
            experiment=pybamm.Experiment([f"Discharge at C/25 until {V_min} V"], period="60 seconds"),
        ).solve(initial_soc=1.0)
        up = pybamm.Simulation(
            make(),
            parameter_values=p25,
            experiment=pybamm.Experiment(["Rest for 1 hour", f"Charge at C/25 until {V_max} V"], period="60 seconds"),
        ).solve(initial_soc=0.0)
    out["ocv"] = {
        "Qd": down["Discharge capacity [A.h]"].entries,
        "Vd": down["Voltage [V]"].entries,
        "Qc": up["Discharge capacity [A.h]"].entries,
        "Vc": up["Voltage [V]"].entries,
    }
    for i, Tc in enumerate(settings.temperatures_C):
        p = base.copy()
        p.update({"Ambient temperature [K]": Tc + 273.15, "Initial temperature [K]": Tc + 273.15})
        steps, prev = [], 1.0
        for s in settings.socs:
            minutes = (prev - s) * 60 / rate_C3
            steps += [
                f"Discharge at C/3 for {minutes:.2f} minutes or until {V_min} V",
                f"Rest for {settings.rest_min:g} minutes",
            ]
            for r in settings.rates_C:
                steps += [
                    f"Discharge at {r}C for {settings.pulse_s:g} seconds or until {V_min} V",
                    "Rest for 2 minutes",
                ]
            prev = s
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sim = pybamm.Simulation(make(), parameter_values=p, experiment=pybamm.Experiment(steps, period="1 second"))
            sol = sim.solve(initial_soc=1.0)
        out[Tc] = {
            k: sol[name].entries
            for k, name in (
                ("t", "Time [s]"),
                ("I", "Current [A]"),
                ("V", "Voltage [V]"),
                ("Q", "Discharge capacity [A.h]"),
            )
        }
        if progress:
            progress(i + 1, len(settings.temperatures_C))
    return out


def pulse_points(records: dict, capacity_Ah: float, pulse_s: float) -> np.ndarray:
    """(T_K, soc, current, overpotential at the pulse's end) for every complete pulse."""
    pts = []
    for Tc, d in records.items():
        if Tc == "ocv":
            continue
        t, I, V, Q = d["t"], d["I"], d["V"], d["Q"]
        on = I > 0.01 * capacity_Ah
        edges = np.flatnonzero(np.diff(on.astype(int))) + 1
        if on[0]:
            edges = np.r_[0, edges]
        for s, k in zip(edges[::2], edges[1::2]):
            if s == 0 or not (0.9 * pulse_s < t[k - 1] - t[s - 1] < 1.1 * pulse_s):
                continue
            end = s + np.searchsorted(t[s:k] - t[s - 1], pulse_s) - 1
            pts.append((Tc + 273.15, 1 - Q[s - 1] / capacity_Ah, I[s:k].mean(), V[s - 1] - V[end]))
    return np.array(pts)


def model_ocv(records: dict, capacity_Ah: float, n: int = 81) -> tuple[np.ndarray, np.ndarray]:
    """The model's open-circuit voltage: the mean of its C/25 discharge and charge, on 1 - Q / capacity."""
    o = records["ocv"]
    sd = 1 - o["Qd"] / capacity_Ah
    sc = sd[-1] - o["Qc"] / capacity_Ah  # the charge starts from the discharged state
    grid = np.linspace(max(sd.min(), sc.min()) + 0.002, min(sd.max(), sc.max()), n)
    Vd = np.interp(grid, sd[::-1], o["Vd"][::-1])
    Vc = np.interp(grid, np.sort(sc), o["Vc"][np.argsort(sc)])
    return grid, 0.5 * (Vd + Vc)


def fit_ecm(
    records: dict, capacity_Ah: float, V_min: float, V_max: float, settings: FitSettings, sources=()
) -> FitReport:
    """Fit the circuit to the synthetic tests (see the module's steps)."""
    from scipy.optimize import least_squares

    t0 = time.perf_counter()
    records = dict(records)
    soc_grid, ocv_V = model_ocv(records, capacity_Ah)
    records.pop("ocv")
    pts = pulse_points(records, capacity_Ah, settings.pulse_s)
    if len(pts) < 10:
        raise ValueError(f"only {len(pts)} complete pulses in the synthetic tests: too few to fit")
    Tk, soc, cur, eta = pts.T
    mid = (soc > 0.2) & (soc < 0.95)
    f1 = least_squares(
        lambda p: (overpotential(p, Tk[mid], cur[mid]) - eta[mid]) / np.maximum(eta[mid], 0.005),
        [np.log(0.02), 20e3, np.log(5.0), 40e3, 1.0],
        bounds=([np.log(1e-4), 0, np.log(1e-3), 0, 0.1], [np.log(0.5), 1e5, np.log(500), 1.5e5, 10]),
    )
    lnR0, Ea0, lnI0, EaI, gamma = f1.x
    pred = overpotential(f1.x, Tk, cur)
    err = {
        float(Tc): float(100 * np.median(np.abs(pred[sel] / eta[sel] - 1)))
        for Tc in records
        if (sel := mid & (np.abs(Tk - 273.15 - Tc) < 0.5)).any()
    }

    def rsoc(q):
        a25, b, Ea = q
        a = a25 * np.exp(Ea / R_GAS * (1 / Tk - 1 / T25))
        return ((1 + a * np.exp(-soc / b)) * pred - eta) / np.maximum(eta, 0.005)

    a25, b, Easoc = least_squares(rsoc, [1.0, 0.05, 20e3], bounds=([0, 0.005, 0], [50, 0.5, 1e5])).x
    base = ECM(
        ocv_soc=tuple(soc_grid),
        ocv_V=tuple(ocv_V),
        R0_25C=math.exp(lnR0),
        Ea_R0=Ea0,
        I0_25C=math.exp(lnI0),
        Ea_I0=EaI,
        gamma=gamma,
        tau_ct=4.0,
        Rd_25C=0.01,
        tau_d=300.0,
        V_max=V_max,
        V_min=V_min,
        cv_cutoff_A=0.01 * capacity_Ah,
        soc_a=a25,
        soc_b=b,
        Ea_soc=Easoc,
        Ea_Rd=20e3,
        sources=tuple(sources),
    )

    def replay(ecm, d, Tc, step=5):
        t, I, V, Q = d["t"][::step], d["I"][::step], d["V"][::step], d["Q"][::step]
        st, out = ECMState(), np.empty_like(V)
        out[0] = V[0]
        for k in range(1, len(t)):
            Vk, eta_, vd, _ = st.step(ecm, I[k], 1 - Q[k] / capacity_Ah, Tc + 273.15, t[k] - t[k - 1])
            st.eta_ct, st.V_d = eta_, vd
            out[k] = Vk
        return out, V, 1 - Q / capacity_Ah

    def resid(p):
        Rd, ltau, EaRd, ltct = p
        ecm = replace(base, Rd_25C=Rd, tau_d=math.exp(ltau), Ea_Rd=EaRd, tau_ct=math.exp(ltct))
        r = []
        for Tc, d in records.items():
            m, V, s = replay(ecm, d, Tc)
            r.append((m - V)[s > 0.1])
        return np.concatenate(r)

    x0 = [0.01, math.log(300), 20e3, math.log(4)]
    fs = least_squares(
        resid,
        x0,
        bounds=([1e-4, math.log(10), 0, math.log(0.3)], [0.2, math.log(1e4), 1e5, math.log(60)]),
        diff_step=1e-3,
    )
    Rd, ltau, EaRd, ltct = fs.x
    ecm = replace(base, Rd_25C=Rd, tau_d=math.exp(ltau), Ea_Rd=EaRd, tau_ct=math.exp(ltct))
    rmse = {}
    for Tc, d in records.items():
        m, V, s = replay(ecm, d, Tc)
        rmse[float(Tc)] = float(1e3 * np.sqrt(np.mean((m - V)[s > 0.1] ** 2)))
    return FitReport(ecm, settings, len(pts), err, rmse, time.perf_counter() - t0)


FULL = FitSettings()


def derive(bpx_cell, settings: FitSettings = FULL, progress=None) -> FitReport:
    """Run the BPX file's model through pulse tests and fit the circuit (minutes)."""
    t0 = time.perf_counter()
    rec = synthetic_tests(bpx_cell.path, bpx_cell.capacity_Ah, bpx_cell.V_min, settings, progress)
    rep = fit_ecm(
        rec,
        bpx_cell.capacity_Ah,
        bpx_cell.V_min,
        bpx_cell.V_max,
        settings,
        sources=(f"BPX: {bpx_cell.title}", f"PyBaMM {settings.model}"),
    )
    rep.seconds = time.perf_counter() - t0
    return rep


__all__ = [
    "FULL",
    "INSTALL_HINT",
    "QUICK",
    "FitReport",
    "FitSettings",
    "derive",
    "fit_ecm",
    "model_ocv",
    "pulse_points",
    "synthetic_tests",
]
