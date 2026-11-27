"""Excess polarisation (v0.6.17): losses beyond the open-circuit curves' rate, in the cold near empty."""

import math
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from packtherm.cells import A123_26650, LG_M50
from packtherm.ecm import EXCESS_SOFT_A, R_GAS, ECMState
from packtherm.fitting.cellfile import ecm_doc, ecm_from_doc
from packtherm.fitting.circuit import CircuitModel, Trace, _thin
from packtherm.fitting.soc import start_soc_from_end

ON = {"Rx_cold": 3.0, "Ea_x": 95e3, "soc_x": 0.22, "w_x": 0.06, "tau_x": 600.0, "I_x": 0.08, "T_x": 261.15}


def test_off_by_default_and_by_hand():
    e = A123_26650.ecm
    assert not LG_M50.ecm.excess and e.excess  # the shipped A123 has it from v0.6.17
    x = replace(LG_M50.ecm, **ON)
    assert x.excess
    # Empty-ish and at T_x: the full resistance; half way up the rise: half; the law in temperature.
    assert x.Rx(-1.0, 261.15) == pytest.approx(3.0, rel=1e-6)
    assert x.Rx(0.22, 261.15) == pytest.approx(1.5)
    assert x.Rx(0.22, 298.15) == pytest.approx(1.5 * math.exp(95e3 / R_GAS * (1 / 298.15 - 1 / 261.15)))
    # Below the curves' own current it does next to nothing; above, the excess current times R_x; the sign follows.
    R = x.Rx(0.3, 261.15)
    assert abs(x.excess_V(0.04, 0.3, 261.15)) < 1e-3 * R
    assert x.excess_V(0.5, 0.3, 261.15) == pytest.approx(R * (0.5 - 0.08), rel=1e-6)
    assert x.excess_V(-0.5, 0.3, 261.15) == pytest.approx(-R * (0.5 - 0.08), rel=1e-6)
    assert x.excess_V(0.08, 0.3, 261.15) == pytest.approx(R * EXCESS_SOFT_A * math.log(2))


def test_model_step_and_fit_replay_agree():
    x = replace(A123_26650.ecm, **ON)
    t = np.arange(0.0, 3600.0, 5.0)
    I = np.where((t // 600) % 2 == 0, 0.6, 0.0)  # 10 minutes on, 10 off (above the cut-off throughout)
    soc = 0.4 - np.concatenate([[0.0], np.cumsum(I[1:] * np.diff(t))]) / 3600 / A123_26650.capacity_Ah
    T = np.full(t.size, 261.15)
    V_fit = CircuitModel().simulate(x, t, I, soc, T, I)
    st, V_step = ECMState(), [V_fit[0]]
    for k in range(1, t.size):
        st.apply(x, float(I[k]), float(soc[k]), 261.15, float(t[k] - t[k - 1]))
        V_step.append(st.step(x, float(I[k]), float(soc[k]), 261.15, 0.0)[0])
    assert not st.cutoff
    assert np.allclose(V_fit[1:], V_step[1:], atol=1e-6)
    off = CircuitModel().simulate(replace(x, Rx_cold=0.0), t, I, soc, T, I)
    assert (off - V_fit).max() > 0.15  # at 0.6 A, 30-40 % charge, -12 degC: well over 100 mV


def test_thinning_keeps_the_charge():
    t = np.arange(0.0, 1000.0, 1.0)
    I = np.sin(t / 37.0) + 0.3
    tr = Trace(t, I, np.zeros(t.size), np.full(t.size, 298.15), np.zeros(t.size), I)
    th = _thin(tr, 5)
    q = float(np.sum(I[1:] * np.diff(t)))
    assert float(np.sum(th.current[1:] * np.diff(th.t))) == pytest.approx(
        q - float(np.sum(I[th.t.size * 5 - 4 :])), abs=1.0
    )
    assert th.t.size == 200


def test_start_soc_from_the_end():
    q = np.linspace(0.0, -2.53, 100)  # a charge putting 2.53 Ah in (charge_Ah is + on discharge)
    rec = SimpleNamespace(voltage_V=np.linspace(2.4, 3.6, 100), charge_Ah=lambda: q, source="charge")
    assert start_soc_from_end(rec, 2.5777, 3.6) == pytest.approx(1 - 2.53 / 2.5777)
    short = SimpleNamespace(voltage_V=np.linspace(2.4, 3.4, 100), charge_Ah=lambda: q, source="charge")
    with pytest.raises(ValueError, match="voltage limit"):
        start_soc_from_end(short, 2.5777, 3.6)


def test_cell_file_round_trip():
    x = replace(A123_26650.ecm, **ON, I_x_tested=0.25)
    from importlib import resources

    import yaml

    doc = yaml.safe_load((resources.files("packtherm") / "data" / "a123_26650_fitted.yaml").read_text())
    doc["model"]["ecm"] = ecm_doc(x)
    assert set(doc["model"]["ecm"]["excess_polarisation"]) == {
        "Rx_cold_ohm", "at_C", "Ea_x", "soc_x", "w_x", "tau_x_s", "I_x_A", "I_tested_A"
    }  # fmt: skip
    back = ecm_from_doc(doc)
    for k, v in ON.items():
        assert getattr(back, k) == pytest.approx(v, rel=1e-5)
    assert back.I_x_tested == pytest.approx(0.25)
    assert "excess_polarisation" not in ecm_doc(LG_M50.ecm)


def test_studies_warn_beyond_the_tested_current():
    """A sustained 1C in the cold, near empty, runs the branch far beyond the drive profiles' 0.1C."""
    from packtherm.electrothermal import check_fitted_range, constant_current, simulate_cell

    cell = replace(A123_26650, ecm=replace(A123_26650.ecm, **ON, I_x_tested=0.25))
    msgs = {}
    for rate in (0.08, 1.0):
        res, load = simulate_cell(cell, constant_current(cell, rate), 3600 / rate * 0.9, 10.0, 263.15, T_initial=263.15)
        msgs[rate] = [m for m in check_fitted_range(cell, load, res) if "loss branch" in m]
    assert not msgs[0.08]  # 0.2 A: within the tested range
    assert len(msgs[1.0]) == 1 and "its tests reached 0.10C" in msgs[1.0][0]
