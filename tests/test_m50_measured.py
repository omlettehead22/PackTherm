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
    not (VALIDATION / "data" / "lg_m50_rpt").exists() or not (VALIDATION / "data" / "lg_m50_core").exists(),
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
