"""The LG M50 against measured data (Warwick, Gulsoy et al., CC BY 4.0; v0.6.9).

Regression gates on docs/VALIDATION.md's M50 section: the library circuit's
resistance scale is the one its pulses give, and the 1C discharges with a core
thermocouple (never fitted on) stay as close as reported.
"""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from packtherm.cells import CELLS, LG_M50_ECM_DERIVED, M50_R_SCALE

VALIDATION = Path(__file__).parent.parent / "validation"
pytestmark = pytest.mark.skipif(
    not all((VALIDATION / "data" / d).exists() for d in ("lg_m50_rpt", "lg_m50_core", "lg_m50_drive")),
    reason="M50 data not present",
)
H = 43.8  # check_m50_core.py's calibration on VP010 cycle 2


def _script(name):
    spec = importlib.util.spec_from_file_location(name, VALIDATION / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pulses():
    m = _script("fit_m50_scale")
    rows = [p for t in ("rpt_00", "rpt_15") for p in m.pulses(*m.load(t))]
    return m, rows


def test_the_pulses_are_found(pulses):
    _, rows = pulses
    assert len(rows) == 16  # 10 A and 2.5 A at four levels, two cells
    assert sorted({r["I"] for r in rows}) == [2.5, 10.0]
    socs = sorted({round(r["soc"], 1) for r in rows})
    assert socs[0] == pytest.approx(0.2, abs=0.1) and socs[-1] == pytest.approx(1.0, abs=0.05)


def test_the_library_circuit_has_the_measured_resistance(pulses):
    m, rows = pulses
    upper = [r for r in rows if r["I"] > 9 and r["soc"] >= m.FIT_ABOVE_SOC]
    meas = np.array([r["drops_V"] for r in upper])
    derived = np.array([m.model_drops(LG_M50_ECM_DERIVED, r["I"], r["soc"]) for r in upper])
    library = np.array([m.model_drops(CELLS["M50"].ecm, r["I"], r["soc"]) for r in upper])
    assert (meas / derived).mean() == pytest.approx(M50_R_SCALE, rel=0.05)
    assert 1e3 * np.sqrt(np.mean((meas - library) ** 2)) < 25.0
    assert 1e3 * np.sqrt(np.mean((meas - derived) ** 2)) > 120.0  # what v0.6.8 had


@pytest.fixture(scope="module")
def core():
    return _script("check_m50_core")


def test_a_1c_discharge_is_predicted_from_the_current_alone(core):
    test = core.load("VP011_cycle2")
    r = core.scores(test, core.run(test, CELLS["M50"], H, "predicted"))
    assert r["V_rmse_mV"] < 35.0
    assert abs(r["surface_rise_model_K"] - r["surface_rise_meas_K"]) < 1.0
    assert r["core_rmse_K"] < 1.6


def test_the_core_runs_a_few_kelvin_above_the_surface(core):
    test = core.load("VP010_cycle2")
    r = core.scores(test, core.run(test, CELLS["M50"], H, "measured heat"))
    assert r["core_rmse_K"] < 1.0
    assert 1.0 < r["core_minus_surface_model_K"] < 4.0
    assert 1.0 < r["core_minus_surface_meas_K"] < 4.0


def test_drive_cycles_it_never_saw():
    """8 h of drive cycles with regen and top-ups: within 40 mV RMS (the derived circuit: 44 mV)."""
    m = _script("check_m50_drive")
    t, I, V = m.load("run_A")
    lib = m.score(t, I, V, m.predict("M50", t, I))
    old = m.score(t, I, V, m.predict("M50-DERIVED", t, I))
    assert lib["rms_mV_under_current"] < 40.0 < old["rms_mV_under_current"]
    # Most of what is left is the open-circuit curve: the circuit sits 15-35 mV low at rest.
    assert all(-40.0 < e < -10.0 for e in lib["rest_end_errors_mV"])


def test_the_lumped_slow_branch_is_the_tuned_one():
    """cells.LUMPED_SLOW holds tune_lumped_slow.py's result, rounded (v0.6.11)."""
    import json

    from packtherm.cells import LUMPED_SLOW

    res = json.loads((VALIDATION / "lumped_slow.json").read_text())["families"]
    for fam, used in LUMPED_SLOW.items():
        fitted = res[fam]["fitted"]
        assert used["slow_share"] == pytest.approx(fitted["slow_share"], rel=0.02)
        assert used["slow_tau_s"] == pytest.approx(fitted["slow_tau_s"], rel=0.02)
        assert used["slow_Ea_R"] == pytest.approx(fitted["slow_Ea_R"], rel=0.02)
        assert res[fam]["lumped_over_circuit_with"]["min"] > 0.55
        assert res[fam]["lumped_over_circuit_with"]["max"] < 1.3


def test_the_lumped_m50_on_a_measured_discharge(core):
    """The datasheet's 30 mOhm with the slow branch, never tuned on the M50: within 1 K of the
    measured surface rise on VP012 (was 2.2 K short), and the core within 1 K RMS."""
    from dataclasses import replace

    from packtherm.cells import params_for_cell
    from packtherm.electrothermal import ElectroThermalLoad
    from packtherm.model import simulate

    test = core.load("VP012_cycle2")
    rec = test["rec"]
    t = rec.t - rec.t[0]
    cell = CELLS["M50-LUMPED"]
    P = params_for_cell(cell, pcm_thickness=0.0, case_thickness=0.0)
    P = P.with_(T_initial=float(rec.temperature_C[0]) + 273.15, solver=replace(P.solver, dt=2.0, store_every=10**6))
    load = ElectroThermalLoad(cell, lambda x: float(np.interp(x, t, rec.current_A)), soc0=1.0)
    res = simulate(P, duration=float(t[-1]), h=H, T_env=test["ambient_C"] + 273.15, load=load)
    rise = float(np.interp(t, res.t, res.T_surface - 273.15).max() - test["ambient_C"])
    assert abs(rise - (rec.temperature_C.max() - test["ambient_C"])) < 1.0
    core_T = np.interp(t, res.t, res.T_max - 273.15)
    assert float(np.sqrt(np.nanmean((core_T - test["core"]) ** 2))) < 1.0
