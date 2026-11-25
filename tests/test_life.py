"""Battery life (v0.6.13): BLAST-Lite models copied in, and the day a design's duty makes."""

import numpy as np
import pytest

from packtherm import cells
from packtherm.design import DutyCycle, Requirements
from packtherm.life import DAY_S, LFP, M50, MJ1, NCA, _battery, capacity_after, life_model, one_day
from packtherm.module_design import ModuleDesign, ModuleStudy, evaluate_module_design


def test_each_cell_gets_its_model():
    assert life_model(cells.LG_M50) == M50 and life_model(cells.LG_M50_LUMPED) == M50
    assert life_model(cells.LG_MJ1) == MJ1
    assert life_model(cells.PANASONIC_NCR18650PF) == NCA
    assert life_model(cells.A123_26650) == LFP
    for c in (cells.SAMSUNG_30T, cells.LG_HG2):  # no model of their own: the M50's, marked as a stand-in
        m = life_model(c)
        assert m.stand_in and m.module == M50.module
    assert not M50.stand_in and not MJ1.stand_in and NCA.stand_in and LFP.stand_in


# Upstream BLAST-Lite (commit 991591726c07, numpy's trapezoid patched in) on this day profile
# gives these capacities after 8 years, to the last digit. The copy must too.
UPSTREAM_8Y = {M50: 0.6081661916070493, MJ1: 0.4065569552429506, NCA: 0.7918100694712343, LFP: 0.858999186618395}


@pytest.mark.parametrize("model", list(UPSTREAM_8Y), ids=lambda m: m.module)
def test_copied_models_match_upstream(model):
    day = np.arange(0, DAY_S + 1, 60.0)
    soc = np.where(day < 3600, 0.9 - 0.7 * day / 3600, np.where(day < 3 * 3600, 0.2 + 0.6 * (day - 3600) / 7200, 0.8))
    T = 25 + 10 * np.exp(-(((day - 3600) / 3000) ** 2))
    b = _battery(model)
    b.simulate_battery_life({"Time_s": day, "SOC": soc, "Temperature_C": T}, threshold_time=8)
    assert b.outputs["q"][-1] == pytest.approx(UPSTREAM_8Y[model], rel=1e-12)


def test_one_day_pads_with_parking():
    t, s, T = one_day([100.0, 1300.0, 3700.0], [1.0, 0.7, 0.5], [30.0, 40.0, 35.0], park_T_C=20.0)
    assert t[0] == 0.0 and t[-1] == DAY_S and np.allclose(np.diff(t), 60.0)
    assert s[0] == 1.0 and T[0] == 30.0
    parked = t > 3600.0
    assert np.all(s[parked] == 0.5) and np.all(T[parked] == 20.0)
    # A duty longer than a day becomes a two-day period, not a cut one.
    t2, _, _ = one_day([0.0, 1.5 * DAY_S], [1.0, 0.5], [25.0, 25.0], park_T_C=25.0)
    assert t2[-1] == 2 * DAY_S


def test_capacity_after_by_hand():
    """Resting at 25 degC and half charge: calendar ageing only, the model's own number."""
    t, soc, T = [0.0, 3600.0], [0.5, 0.5], [25.0, 25.0]
    r = capacity_after(cells.LG_M50, t, soc, T, park_T_C=25.0, years=8.0)
    b = _battery(M50)
    day = np.arange(0, DAY_S + 1, 60.0)
    b.simulate_battery_life({"Time_s": day, "SOC": np.full(day.size, 0.5), "Temperature_C": np.full(day.size, 25.0)}, threshold_time=8)
    assert r.capacity_pct == pytest.approx(100 * b.outputs["q"][-1], rel=1e-9)
    assert r.day_efc == 0.0 and r.day_T_mean_C == pytest.approx(25.0)
    assert 60.0 < r.capacity_pct < 100.0
    assert "stand-in" not in r.note and "LG M50" in r.note


def test_hotter_and_harder_ages_more():
    t = np.linspace(0, 3600, 61)
    soc = 1.0 - 0.5 * t / 3600
    base = capacity_after(cells.LG_M50, t, soc, np.full(t.size, 30.0), park_T_C=25.0).capacity_pct
    hot = capacity_after(cells.LG_M50, t, soc, np.full(t.size, 45.0), park_T_C=25.0).capacity_pct
    warm_park = capacity_after(cells.LG_M50, t, soc, np.full(t.size, 30.0), park_T_C=35.0).capacity_pct
    longer = capacity_after(cells.LG_M50, t, soc, np.full(t.size, 30.0), park_T_C=25.0, years=12.0).capacity_pct
    assert hot < base and warm_park < base and longer < base
    stand = capacity_after(cells.SAMSUNG_30T, t, soc, np.full(t.size, 30.0), park_T_C=25.0)
    assert "stand-in" in stand.note


DUTY = DutyCycle.constant(1.5, "discharge", soc0=1.0, soc_limits=(0.5, 1.0), rest_after_s=3600)


def study(**kw):
    base = {"topologies": ("none", "ribbon"), "coolant_flows_g_s": (0.05,), "fillers": (None,), "dt": 4.0}
    base.update(kw)
    return ModuleStudy(cells.LG_M50, DUTY, Requirements(T_env_C=25.0), **base)


def test_study_reports_capacity_and_can_fail_on_it():
    sealed = evaluate_module_design(study(), ModuleDesign("none", 0.0))
    cooled = evaluate_module_design(study(), ModuleDesign("ribbon", 0.05))
    assert 0.0 < sealed["capacity_after_pct"] < 100.0 and sealed["life_years"] == 8.0
    assert cooled["capacity_after_pct"] >= sealed["capacity_after_pct"]
    assert "LG M50" in cooled["life_model"]
    strict = evaluate_module_design(study(capacity_min_pct=99.0), ModuleDesign("ribbon", 0.05))
    assert "ages" in strict["fail_reason"] and not strict["feasible"]
    assert "ages" not in cooled["fail_reason"]
    off = evaluate_module_design(study(life_years=0.0), ModuleDesign("ribbon", 0.05))
    assert np.isnan(off["capacity_after_pct"]) and off["life_model"] == ""
    warm = evaluate_module_design(study(life_park_C=40.0), ModuleDesign("ribbon", 0.05))
    assert warm["capacity_after_pct"] < cooled["capacity_after_pct"]
