import math
from dataclasses import replace

import numpy as np
import pytest

from packtherm.cells import LG_M50, LG_M50_LUMPED, PANASONIC_NCR18650PF
from packtherm.ecm import ECM, ECMState
from packtherm.electrothermal import ElectroThermalLoad, MeasuredHeatLoad, constant_current, simulate_cell

PF = PANASONIC_NCR18650PF
ECM_PF = PF.ecm
T25 = 298.15


def flat_ecm(**kw):
    base = {
        "ocv_soc": (0.0, 1.0),
        "ocv_V": (3.0, 4.2),
        "R0_25C": 0.02,
        "Ea_R0": 0.0,
        "I0_25C": 1e6,  # charge transfer negligible
        "Ea_I0": 0.0,
        "gamma": 1.0,
        "Rd_25C": 0.0,
    }
    base.update(kw)
    return ECM(**base)


def test_ohmic_only_voltage_and_heat():
    ecm = flat_ecm()
    st = ECMState()
    current, V = st.apply(ecm, 2.0, 0.5, T25, 1.0)
    assert current == 2.0
    assert V == pytest.approx(3.6 - 2.0 * 0.02, abs=1e-6)


def test_butler_volmer_is_odd_and_sublinear():
    a, b = ECM_PF.eta_ss(2.0, 263.15), ECM_PF.eta_ss(-2.0, 263.15)
    assert a == pytest.approx(-b)
    # Apparent charge-transfer resistance falls with current.
    assert ECM_PF.eta_ss(6.0, 263.15) / 6.0 < ECM_PF.eta_ss(1.0, 263.15) / 1.0


def test_kinetics_slow_down_in_the_cold():
    assert ECM_PF.eta_ss(2.9, 253.15) > 5 * ECM_PF.eta_ss(2.9, T25)
    assert ECM_PF.Rd(253.15) > ECM_PF.Rd(T25)


def test_rc_branch_relaxes():
    ecm = flat_ecm(Rd_25C=0.01, tau_d=100.0)
    st = ECMState()
    for _ in range(1000):
        st.apply(ecm, 1.0, 0.5, T25, 1.0)
    assert st.V_d == pytest.approx(0.01, rel=1e-3)  # steady state R I
    for _ in range(1000):
        st.apply(ecm, 0.0, 0.5, T25, 1.0)
    assert abs(st.V_d) < 1e-6


def test_discharge_cutoff_latches():
    ecm = flat_ecm(V_min=3.5)
    st = ECMState()
    current, _ = st.apply(ecm, 5.0, 0.3, T25, 1.0)  # OCV 3.36 < V_min
    assert current == 0.0 and st.cutoff
    current, _ = st.apply(ecm, 5.0, 0.9, T25, 1.0)
    assert current == 0.0


def test_cv_phase_holds_vmax_and_tapers():
    load = ElectroThermalLoad(PF, constant_current(PF, 1.0, "charge"), soc0=0.05)
    for k in range(3 * 3600):
        load.power(float(k), 1.0, T25)
        if load.ecm_state.charge_done:
            break
    a = load.arrays()
    assert np.nanmax(a["V"]) <= PF.ecm.V_max + 1e-4
    cv = a["V"] > PF.ecm.V_max - 1e-3
    assert cv.any()
    i_cv = -a["current_A"][cv]
    assert i_cv[0] > 1.0 and i_cv[-1] < 0.1  # tapers from ~1C towards the cut-off
    assert np.all(np.diff(i_cv) <= 1e-3)  # monotonic taper (to 1 mA: thermal feedback)
    assert load.soc > 0.95


def test_heat_is_current_times_overpotential():
    load = ElectroThermalLoad(PF, constant_current(PF, 1.0), soc0=0.8, entropic=False)
    q = load.power(0.0, 1.0, T25)
    a = load.arrays()
    soc_mid = 0.8 - 0.5 * a["current_A"][0] / (3600 * PF.capacity_Ah)
    assert q == pytest.approx(a["current_A"][0] * (PF.ecm.ocv(soc_mid) - a["V"][0]), rel=1e-9)


def test_legacy_cells_unchanged():
    """Cells without an ECM keep the lumped I^2 R path (no voltage)."""
    assert LG_M50_LUMPED.ecm is None
    _, load = simulate_cell(LG_M50_LUMPED, constant_current(LG_M50_LUMPED, 1.0), 60.0, h=30.0, T_env=T25)
    assert np.isnan(load.arrays()["V"]).all()


def test_m50_circuit_and_worst_case_scaling():
    """The M50 now has a derived circuit; worst-case scaling stresses every loss term."""
    from packtherm.cells import with_R0

    assert LG_M50.ecm is not None
    _, load = simulate_cell(LG_M50, constant_current(LG_M50, 1.0), 600.0, h=30.0, T_env=T25)
    V = load.arrays()["V"]
    assert np.isfinite(V[1:]).all() and 3.3 < V[-1] < 4.2
    worst = with_R0(LG_M50, LG_M50.R0_25C * 1.44)
    assert worst.ecm.R0_25C == pytest.approx(1.44 * LG_M50.ecm.R0_25C)
    assert worst.ecm.Rd_25C == pytest.approx(1.44 * LG_M50.ecm.Rd_25C)
    assert worst.ecm.I0_25C == pytest.approx(LG_M50.ecm.I0_25C / 1.44)
    r1, _ = simulate_cell(LG_M50, constant_current(LG_M50, 1.0), 1200.0, h=30.0, T_env=T25)
    r2, _ = simulate_cell(worst, constant_current(worst, 1.0), 1200.0, h=30.0, T_env=T25)
    assert r2.E_generated > 1.3 * r1.E_generated


def test_measured_heat_load():
    t = np.arange(0.0, 101.0)
    current = np.full_like(t, 2.0)
    V = np.full_like(t, 3.5)
    load = MeasuredHeatLoad(t, current, V, lambda s: 3.6, capacity_Ah=3.0)
    assert load.power(10.0, 1.0, T25) == pytest.approx(2.0 * 0.1)
    assert load._soc[-1] == pytest.approx(1 - 200 / 3600 / 3.0)


def test_pf_cell_runs_through_design_path():
    res, load = simulate_cell(PF, constant_current(PF, 1.0), 4000.0, h=40.0, T_env=T25, pcm_thickness=0.0)
    a = load.arrays()
    # Discharge ends at the 2.5 V cut-off before the SOC window is exhausted.
    assert np.nanmin(a["V"][a["current_A"] > 0]) >= PF.ecm.V_min - 1e-6
    assert load.ecm_state.cutoff
    assert 0.0 < load.soc < 0.15
    assert math.isfinite(res.T_max.max())


def test_ecm_is_frozen_and_replaceable():
    e2 = replace(ECM_PF, Rd_25C=0.05)
    assert e2.Rd(T25) == pytest.approx(0.05)


def test_cold_temperature_laws():
    import math
    from dataclasses import replace

    from packtherm.cells import PANASONIC_NCR18650PF

    e = PANASONIC_NCR18650PF.ecm
    T25, Tm10 = 298.15, 263.15
    R = 8.314462618
    # Low-SOC rise grows in the cold with its own activation energy; unchanged at 25 degC.
    assert e.soc_factor(0.05, T25) == pytest.approx(1 + e.soc_a * math.exp(-0.05 / e.soc_b))
    ratio = (e.soc_factor(0.05, Tm10) - 1) / (e.soc_factor(0.05, T25) - 1)
    assert ratio == pytest.approx(math.exp(e.Ea_soc / R * (1 / Tm10 - 1 / T25)))
    # Slow branch: own Arrhenius law, gentler than following the charge-transfer kinetics.
    assert e.Rd(Tm10) / e.Rd(T25) == pytest.approx(math.exp(e.Ea_Rd / R * (1 / Tm10 - 1 / T25)))
    coupled = replace(e, Ea_Rd=None)
    assert coupled.Rd(Tm10) > e.Rd(Tm10)
    # Charging ignores the low-SOC factor.
    from packtherm.ecm import ECMState

    V_chg, *_ = ECMState().step(e, -1.0, 0.05, Tm10, 1.0)
    V_flat, *_ = ECMState().step(replace(e, soc_a=0.0), -1.0, 0.05, Tm10, 1.0)
    assert V_chg == pytest.approx(V_flat)


# -- values by temperature, and the middle branch (v0.6.2) ------------------------------------------


def test_a_table_built_from_laws_gives_the_laws_back():
    # Between the rows: log-interpolation in 1/T is an Arrhenius law between neighbours.
    # Beyond them: the laws from the end row. So a table of a law is that law, everywhere.
    from packtherm.cells import PANASONIC_NCR18650PF as PF

    e = PF.ecm
    rows = tuple(
        (T, e.R0(T), e.I0(T), e.gamma, e.tau_ct, 0.0, 30.0, e.Rd(T), e.tau_d, e.soc_factor(0, T) - 1, e.soc_b)
        for T in (253.15, 273.15, 298.15)
    )
    t = replace(e, by_T=rows)
    for T in (238.15, 263.15, 283.15, 318.15):
        assert t.R0(T) == pytest.approx(e.R0(T), rel=1e-12)
        assert t.I0(T) == pytest.approx(e.I0(T), rel=1e-12)
        assert t.Rd(T) == pytest.approx(e.Rd(T), rel=1e-12)
        assert t.soc_factor(0.05, T) == pytest.approx(e.soc_factor(0.05, T), rel=1e-12)


def test_a_table_holds_shape_and_time_constants_beyond_its_rows():
    from packtherm.cells import PANASONIC_NCR18650PF as PF

    rows = (
        (263.15, 0.05, 0.5, 2.0, 3.0, 0.02, 40.0, 0.03, 600.0, 20.0, 0.05),
        (298.15, 0.02, 3.0, 1.0, 1.0, 0.01, 20.0, 0.02, 900.0, 8.0, 0.06),
    )
    t = replace(PF.ecm, by_T=rows)
    assert t.gamma_at(250.0) == 2.0 and t.gamma_at(320.0) == 1.0
    assert t.tau_ct_at(250.0) == 3.0 and t.tau_d_at(320.0) == 900.0
    mid = 1 / (0.5 / 263.15 + 0.5 / 298.15)  # halfway in 1/T: the geometric mean
    assert t.tau_m_at(mid) == pytest.approx((40.0 * 20.0) ** 0.5)
    with pytest.raises(ValueError, match="two rows"):
        replace(PF.ecm, by_T=rows[:1])


def test_the_middle_branch_is_off_unless_set():
    from packtherm.cells import PANASONIC_NCR18650PF as PF

    e = PF.ecm
    assert e.Rm(298.15) == 0.0
    a = ECMState().step(e, 3.0, 0.5, 298.15, 30.0)
    b = ECMState().step(replace(e, Rm_25C=0.01, tau_m=30.0), 3.0, 0.5, 298.15, 30.0)
    f = e.soc_factor(0.5)  # it takes the rise near empty too, like the other branches
    assert a[3] == 0.0 and b[3] == pytest.approx(f * 0.01 * 3.0 * (1 - math.exp(-1)), rel=1e-9)
    assert b[0] == pytest.approx(a[0] - b[3], abs=1e-12)  # it adds its drop, nothing else


def test_scaling_a_tabulated_cell_scales_every_loss():
    from packtherm.cells import PANASONIC_NCR18650PF as PF

    rows = (
        (263.15, 0.05, 0.5, 2.0, 3.0, 0.02, 40.0, 0.03, 600.0, 20.0, 0.05),
        (298.15, 0.02, 3.0, 1.0, 1.0, 0.01, 20.0, 0.02, 900.0, 8.0, 0.06),
    )
    t = replace(PF.ecm, by_T=rows)
    s = t.scaled(1.5)
    for T in (255.0, 280.0, 300.0):
        assert s.R0(T) == pytest.approx(1.5 * t.R0(T)) and s.Rd(T) == pytest.approx(1.5 * t.Rd(T))
        assert s.Rm(T) == pytest.approx(1.5 * t.Rm(T)) and s.I0(T) == pytest.approx(t.I0(T) / 1.5)
