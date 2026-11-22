"""Fitting the circuit model (packtherm.fitting, v0.6.1, v0.6.2).

Two kinds of check:

- known answers: tests made by a cell with known values, read back through the
  whole fit. The fit must find those values, and predict a drive cycle it
  never saw.
- real data: the Panasonic NCR18650PF tests in tests/data (CC BY 4.0). There
  is no true answer, so the check is the one a user would make: the fitted
  cell must predict the drive cycle it was not fitted to, and as well as the
  library cell does.

Also: the fitted cell file (contents, hashes); that studies refuse a cell fitted
at one temperature and run one fitted at three, warning beyond its tested range;
the test list; and fits across temperatures, against known laws.
"""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from packtherm.cells import PANASONIC_NCR18650PF as PF
from packtherm.ecm import FULL_SOC, ECMState
from packtherm.fitting import (
    CircuitModel,
    fit_cell,
    fitted_cell_doc,
    read_fitted_cell,
    track_soc,
    write_fitted_cell,
    write_report,
)
from packtherm.fitting.circuit import TestSet, interval_current
from packtherm.fitting.ocv import OCVCurve
from packtherm.testdata import TestRecord, load_test_data

CAP = 3.0
# A cell with three well-separated branches: seconds, tens of seconds, minutes.
TRUE = {
    "R0_25C": 0.022,
    "I0_25C": 2.5,
    "gamma": 1.1,
    "tau_ct": 1.5,
    "Rm_25C": 0.012,
    "tau_m": 30.0,
    "Rd_25C": 0.018,
    "tau_d": 900.0,
    "soc_a": 6.0,
    "soc_b": 0.06,
}
# How close each value must come (noise-free tests made by PackTherm's own model). Each
# part is fitted in a stage of its own with the rest held from the stage before, so a
# small coupling bias remains.
TOLERANCE = {
    "R0_25C": 0.01,
    "I0_25C": 0.1,
    "gamma": 0.1,
    "tau_ct": 0.05,
    "Rm_25C": 0.1,
    "tau_m": 0.12,
    "Rd_25C": 0.05,
    "tau_d": 0.1,
    "soc_a": 0.06,
    "soc_b": 0.03,
}
_OCV = OCVCurve(np.array(PF.ecm.ocv_soc), np.array(PF.ecm.ocv_V), CAP, 2.5, 4.2, 0.0, "library table")
LAWS = {"Ea_R0": 20e3, "Ea_I0": 45e3, "Ea_Rm": 25e3, "Ea_Rd": 30e3, "Ea_soc": 20e3}
TRUE_ECM = CircuitModel().ecm({**TRUE, **LAWS}, _OCV)


def synth(parts, soc0: float = 1.0, name: str = "synthetic", T_C: float = 25.0, ecm=None) -> TestRecord:
    """A test from (duration_s, current_A, dt_s) parts, run through PackTherm's own model (ECMState).

    A discharge stops at its cut-off. The cell is held at T_C. The tester's
    charge counter is recorded too, as real testers do.
    """
    t, I, part = [0.0], [0.0], [-1]
    for j, (dur, cur, dt) in enumerate(parts):
        n = max(1, round(dur / dt))
        t += list(t[-1] + dt * np.arange(1, n + 1))
        I += [float(cur)] * n
        part += [j] * n
    t, I = np.array(t), np.array(I)
    V = np.empty(t.size)
    q = np.zeros(t.size)
    T = T_C + 273.15
    ecm = TRUE_ECM if ecm is None else ecm
    st = ECMState(h=1.0 if soc0 >= FULL_SOC else 0.0)  # hysteresis from full: just charged
    soc = soc0
    V[0] = st.step(ecm, 0.0, soc, T, 0.0)[0]
    stopped = False
    for k in range(1, t.size):
        if part[k] != part[k - 1]:
            stopped = False
        if stopped:
            I[k] = 0.0
        dt = t[k] - t[k - 1]
        soc -= I[k] * dt / 3600 / CAP
        q[k] = q[k - 1] + I[k] * dt / 3600
        V[k], st.eta_ct, st.V_d, st.V_m = st.step(ecm, I[k], soc, T, dt)
        st.h = ecm.hyst_step(st.h, I[k], dt, T)
        if I[k] > 0 and V[k] < ecm.V_min:
            stopped = True  # the tester stops the discharge at its cut-off (from the next sample)
    return TestRecord(t=t, current_A=I, voltage_V=V, temperature_C=np.full(t.size, T_C), counter_Ah=q, source=name)


def slow_test(T_C: float = 25.0) -> TestRecord:
    return synth([(3600, 0, 60), (25 * 3600, 0.15, 60), (3600, 0, 60)], name="slow.csv", T_C=T_C)


def pulse_test(T_C: float = 25.0) -> TestRecord:
    parts = [(3 * 3600, 0, 60)]
    for _ in range(10):  # ten levels, from full down to 10%
        parts += [(10, CAP, 0.5), (60, 0, 0.5), (10, 2 * CAP, 0.5), (90, 0, 0.5)]
        parts += [(360, CAP, 5), (3 * 3600, 0, 60)]  # 10% at 1C, then a rest of 3 tau_d
    return synth(parts, name="pulses.csv", T_C=T_C)


def steps_test(T_C: float = 25.0) -> TestRecord:
    parts = [(3 * 3600, 0, 60)]
    for _ in range(6):
        parts += [(5400, 0.3, 10), (3600, 0, 60)]  # 6 x tau_d: settled by its end
    return synth(parts, name="steps.csv", T_C=T_C)


def discharge_test(T_C: float = 25.0, ecm=None) -> TestRecord:
    return synth([(4000, CAP, 2), (1800, 0, 10)], name="dis1c.csv", T_C=T_C, ecm=ecm)


def drive_test(T_C: float = 25.0) -> TestRecord:
    rng = np.random.default_rng(3)
    parts = [(3 * 3600, 0, 60)] + [(float(rng.integers(5, 40)), float(rng.uniform(-1.5, 4.5)), 0.5) for _ in range(90)]
    return synth(parts, soc0=0.8, name="drive.csv", T_C=T_C)


@pytest.fixture(scope="module")
def synthetic_fit():
    tests = TestSet(pulse_test(), steps_test(), discharges=[discharge_test()])
    return fit_cell(slow_test(), sets=[tests], checks=[drive_test()], check_soc0=[0.8])


def test_simulator_matches_packtherms_ecm():
    # The fit's replay must be the model PackTherm runs: same voltages as ECMState.step.
    rec = drive_test()
    soc, _ = track_soc(rec, _OCV, CAP)
    I = interval_current(rec)
    V = CircuitModel().simulate(TRUE_ECM, rec.t, I, soc, np.full(rec.t.size, 298.15))
    st = ECMState()
    ref = [st.step(TRUE_ECM, 0.0, soc[0], 298.15, 0.0)[0]]
    for k in range(1, rec.t.size):
        v, st.eta_ct, st.V_d, st.V_m = st.step(TRUE_ECM, I[k], soc[k], 298.15, rec.t[k] - rec.t[k - 1])
        ref.append(v)
    assert np.max(np.abs(V - np.array(ref))) < 1e-9


def test_finds_known_values(synthetic_fit):
    fit = synthetic_fit
    got = {p.name: p for p in fit.params}
    assert fit.capacity_Ah == pytest.approx(CAP, rel=0.01)
    # The kinetics trade off against each other (I0, gamma); what a cell is
    # judged by is its resistance, which must be found closely.
    for name, tol in TOLERANCE.items():
        assert got[name].value == pytest.approx(TRUE[name], rel=tol), name
        assert got[name].source == "fitted"
    # About half the true values lie in their 95% ranges. On noise-free tests the
    # misfit left is the small steady bias of fitting in stages, which ranges built
    # from how far the windows disagree cannot show: they are not a guarantee.
    inside = [n for n in TRUE if got[n].ci95 and got[n].ci95[0] <= TRUE[n] <= got[n].ci95[1]]
    assert len(inside) >= 4, inside
    assert all(e["rmse_mV"] < 2 for k, e in fit.errors.items() if "20-95%" in k)


def test_predicts_a_drive_cycle_it_never_saw(synthetic_fit):
    (check,) = synthetic_fit.checks
    assert check["rmse_mV"] < 2


def test_validity_and_sources(synthetic_fit):
    v = synthetic_fit.validity
    assert v["temperature_C"] == [25.0, 25.0]
    assert v["discharge_C"] == pytest.approx([1.0, 2.0], abs=0.01)
    assert v["soc"][0] < 0.2 and v["soc"][1] > 0.95
    sources = {p.name: p.source for p in synthetic_fit.params}
    assert sources["capacity_Ah"] == "data" and sources["V_min"] == "data"
    assert sources["Ea_I0"] == "default"  # one temperature: borrowed, and said so


def test_without_a_steps_test_the_slow_branch_is_marked_not_fitted():
    fit = fit_cell(slow_test(), pulse_test())
    got = {p.name: p for p in fit.params}
    assert got["Rd_25C"].source == "not fitted" and got["tau_d"].source == "not fitted"
    assert any("slow branch" in n for n in fit.notes)


def test_too_few_pulses_is_an_error():
    few = synth([(1800, 0, 30), (10, CAP, 0.5), (40, 0, 0.5)], name="few.csv")
    with pytest.raises(ValueError, match="pulses found"):
        fit_cell(slow_test(), few)


def dyn_test(T_C: float = 25.0, ecm=None) -> TestRecord:
    """Plett's drive-profile test, as the A123 data has: a 1C step, a rest, then profile blocks with 5 min rests."""
    rng = np.random.default_rng(5)
    parts = [(2 * 3600, 0, 60), (720, CAP, 1), (900, 0, 1)]
    for _ in range(9):
        for _ in range(60):
            cur = rng.choice([0.0, rng.uniform(-1.5, 4.5)], p=[0.15, 0.85])
            parts.append((float(rng.integers(3, 40)), float(cur), 1.0))
        parts.append((300, 0, 1))
    return synth(parts, name="dyn.csv", T_C=T_C, ecm=ecm)


def test_without_a_pulse_test_the_kinetics_come_from_the_changes_in_current():
    # v0.6.6: a cell tested as the A123 was, with no pulse test, still gives the known values.
    fit = fit_cell(
        slow_test(), sets=[TestSet(None, discharges=[discharge_test()], cycles=[dyn_test()])],
        checks=[drive_test()], check_soc0=[0.8],
    )  # fmt: skip
    got = {p.name: p.value for p in fit.params}
    for name, value in TRUE.items():
        assert got[name] == pytest.approx(value, rel=0.06), name
    mid = fit.errors["changes in current at 20-95% SOC"]
    assert mid["rmse_mV"] < 0.5 and mid["parts"] > 40
    # The profile charges too (to 0.5C): the tested range says so, over 30 s as a study checks it.
    assert fit.validity["charge_C"] is not None and 0.05 <= fit.validity["charge_C"][1] <= 0.5
    assert fit.validity["discharge_C"][1] <= 1.5
    assert fit.checks[0]["rmse_mV"] < 1


HYST_ECM = replace(TRUE_ECM, hyst=((298.15, 0.04, 20.0),))  # an LFP-like 40 mV gap


def test_hysteresis_comes_from_a_slow_charge_and_the_profiles():
    # v0.6.7: a cell with a 40 mV gap between its branches, crossed in about 1/20 Ah.
    slow = synth([(3600, 0, 60), (25 * 3600, 0.15, 60), (3600, 0, 60)], name="slow.csv", ecm=HYST_ECM)
    charge = synth([(3600, 0, 60), (0.9 * CAP / 0.15 * 3600, -0.15, 60)], soc0=0.0, name="charge.csv", ecm=HYST_ECM)
    t = TestSet(None, discharges=[discharge_test(ecm=HYST_ECM)], cycles=[dyn_test(ecm=HYST_ECM)], slow_charge=charge)
    fit = fit_cell(slow, sets=[t])
    assert fit.ecm.hyst_V(298.15) == pytest.approx(0.04, rel=0.1)
    # The rate is weakly pinned by a slow charge from empty (the curve's steep end is there too).
    assert 10.0 < fit.ecm.hyst_rate(298.15) < 40.0
    assert fit.errors["slow charge at 10-95% SOC"]["rmse_mV"] < 2
    # Without the slow charge there's no hysteresis, and the charge runs about 40 mV low.
    plain = fit_cell(slow, sets=[replace(t, slow_charge=None)])
    assert not plain.ecm.hyst


def test_hysteresis_heats_by_half_the_gap_per_unit_of_charge_each_way():
    from packtherm.ecm import ECMState

    st = ECMState(h=0.0)
    T, dt = 298.15, 1.0
    for current in (2.0, -2.0):
        for _ in range(600):  # long enough to be on the branch
            I, V = st.apply(HYST_ECM, current, 0.5, T, dt)
        mid = HYST_ECM.ocv(0.5, T) + 0.5 * HYST_ECM.hyst_V(T)
        # Heat both ways, half the gap's included: more than the drops alone (I^2 R, under 0.03 W here).
        assert I * (mid - V) > abs(I) * 0.02


def test_load_windows_are_the_sudden_changes_and_do_not_overlap():
    from packtherm.fitting.circuit import LOAD_S, PRE_S, discharge_windows, load_windows

    w, _ = discharge_windows(dyn_test(), 1.0, _OCV, CAP, "cycle")
    wins = load_windows(w, CAP)
    assert all(x.kind == "load" and x.relative for x in wins)
    assert all(a.k1 <= b.k0 for a, b in pairwise(wins))
    assert all(x.t[-1] - x.t[0] <= PRE_S + LOAD_S + 1 for x in wins)
    assert wins[0].soc0 == pytest.approx(1.0, abs=0.01)  # the 1C step from the rested start


def test_with_no_pulse_test_and_no_long_tests_it_says_what_to_give():
    with pytest.raises(ValueError, match="give a pulse test, or discharges or cycles"):
        fit_cell(slow_test(), sets=[TestSet(None, steps_test())])


def test_soc_from_a_start_given_or_from_the_first_voltage():
    rec = drive_test()
    soc, how = track_soc(rec, _OCV, CAP, soc0=0.8)
    assert soc[0] == 0.8 and "as given" in how
    # It has a 3-hour rest at the start, so it anchors there.
    soc, how = track_soc(rec, _OCV, CAP)
    assert soc[0] == pytest.approx(0.8, abs=0.01) and "settled" in how


# -- the cell file and the report -------------------------------------------------------------------


def test_cell_file_round_trip_and_studies_refuse_it(synthetic_fit, tmp_path):
    from packtherm.study import StudyError, validate
    from packtherm.user_cells import CellError, load_cell

    files = {}
    for role in ("slow", "pulses", "steps", "discharges"):
        p = tmp_path / f"{role}.bin"
        p.write_bytes(role.encode())
        files[role] = [p]
    doc = fitted_cell_doc(
        synthetic_fit,
        "Test cell",
        files,
        rated_capacity_Ah=2.9,
        dataset={"citation": "synthetic", "licence": "CC0"},
    )
    path = write_fitted_cell(tmp_path / "cell.yaml", doc)
    back = read_fitted_cell(path)
    assert back["usable_in_studies"] is False and back["status"] == "single-temperature"
    expected = 100 * (synthetic_fit.capacity_Ah / 2.9 - 1)
    assert back["capacity"]["measured_vs_rated"] == f"{expected:+.1f}%"
    assert back["values"]["R0_25C"]["source"] == "fitted" and len(back["values"]["R0_25C"]["range_95"]) == 2
    assert back["values"]["Ea_I0"]["source"] == "default"
    # Provenance: each input's SHA-256 (of the bytes above), the dataset, the version.
    import hashlib

    hashes = {i["role"]: i["sha256"] for i in back["provenance"]["inputs"]}
    assert hashes["slow"] == hashlib.sha256(b"slow").hexdigest()
    assert back["provenance"]["dataset"]["licence"] == "CC0"
    assert back["errors"]["held_out"][0]["rmse_mV"] < 2

    with pytest.raises(CellError, match="one temperature"):
        load_cell(path)
    with pytest.raises(StudyError, match=r"cell: .*one temperature.*3 temperatures or more"):
        validate({"cell": str(path)})

    report = write_report(tmp_path / "cell.html", synthetic_fit, doc)
    html = report.read_text()
    assert "Not usable in studies" in html and "never saw" in html and html.count("data:image/png") >= 4


# -- real data (tests/data/panasonic_18650pf, CC BY 4.0) --------------------------------------------

REAL = Path(__file__).parent / "data" / "panasonic_18650pf"


def real(name: str) -> TestRecord:
    (p,) = REAL.glob(f"*{name}*")  # exactly one: several would make a test read the wrong file
    return load_test_data(p)


def test_real_panasonic_fit_predicts_a_drive_cycle():
    fit = fit_cell(
        real("C20 OCV"),
        real("25degC_5Pulse_HPPC"),
        steps=real("3390_dis5_10p"),
        checks=[real("UDDS")],
        compare_ecm=("library", PF.ecm, PF.capacity_Ah),
    )
    # The C/20 discharge holds 2.995 Ah, by the tester's own counter (rated 2.9 Ah).
    assert fit.capacity_Ah == pytest.approx(2.995, abs=0.005)
    (check,) = fit.checks
    # The UDDS cycle was not fitted to. The fit predicts it to about 5 mV RMS,
    # better than the library cell (about 10 mV), whose values came from the
    # same dataset by a simpler method.
    assert check["rmse_mV"] < 9
    assert check["rmse_mV"] < check["compare_rmse_mV"]
    assert fit.errors["pulses at 20-95% SOC"]["rmse_mV"] < 12
    assert fit.errors["steps at 20-95% SOC"]["rmse_mV"] < 12
    # 25 degC chamber; the cell warms a little in the 6C pulses.
    lo, hi = fit.validity["temperature_C"]
    assert 24 <= lo and hi <= 30
    assert fit.validity["discharge_C"][1] == pytest.approx(6.0, rel=0.05)


# -- the command ------------------------------------------------------------------------------------


def test_fit_command(tmp_path, capsys):
    from packtherm.cli import main

    paths = {}
    for name, rec in (("slow", slow_test()), ("pulses", pulse_test()), ("drive", drive_test())):
        paths[name] = tmp_path / f"{name}.csv"
        pd.DataFrame(
            {
                "Test_Time(s)": rec.t,
                "Current(A)": rec.current_A,
                "Voltage(V)": rec.voltage_V,
                "Temperature (C)_1": rec.temperature_C,
            }
        ).to_csv(paths[name], index=False)
    out = tmp_path / "my_cell.yaml"
    main(
        [
            "fit",
            "--slow",
            str(paths["slow"]),
            "--pulses",
            str(paths["pulses"]),
            "--check",
            str(paths["drive"]),
            "--compare",
            "PF",
            "-o",
            str(out),
        ]
    )
    text = capsys.readouterr().out
    assert "not usable in studies" in text and "held out" in text
    assert out.exists() and out.with_suffix(".html").exists()
    assert read_fitted_cell(out)["name"] == "my_cell"


# -- several temperatures (v0.6.2) ------------------------------------------------------------------

TEMPS = (25.0, 5.0, -15.0)


@pytest.fixture(scope="module")
def three_temperatures():
    """Tests at three temperatures, made by a cell whose values follow known Arrhenius laws."""
    sets = [
        TestSet(pulse_test(T), steps_test(T), T, discharges=[discharge_test(T)] if T == 25.0 else [])
        for T in TEMPS
    ]
    return fit_cell(slow_test(), sets=sets, checks=[drive_test(5.0)], check_soc0=[0.8])


def test_three_temperatures_follow_the_known_laws(three_temperatures):
    fit = three_temperatures
    assert fit.temperatures == sorted(TEMPS)
    assert len(fit.ecm.by_T) == 3
    # Each temperature's own values: what the true laws give there. At -15 degC the 2C pulses
    # hit the cut-off and are cut short, so the cold tests say less: there, each true value
    # must lie in its reported range or within 35%.
    for pt in fit.per_temperature:
        T = pt["cell_C"] + 273.15
        own = {p.name: p for p in pt["params"]}
        true = {"R0_25C": TRUE_ECM.R0(T), "I0_25C": TRUE_ECM.I0(T), "Rm_25C": TRUE_ECM.Rm(T), "Rd_25C": TRUE_ECM.Rd(T)}
        assert own["R0_25C"].value == pytest.approx(true["R0_25C"], rel=0.03), pt["at_C"]
        for name in ("I0_25C", "Rm_25C", "Rd_25C"):
            p = own[name]
            if pt["at_C"] > 0:
                assert p.value == pytest.approx(true[name], rel=0.12), (pt["at_C"], name)
            else:
                inside = p.ci95 is not None and p.ci95[0] <= true[name] <= p.ci95[1]
                assert inside or p.value == pytest.approx(true[name], rel=0.35), (pt["at_C"], name)
        # The table PackTherm runs gives them back at that temperature.
        assert fit.ecm.R0(T) == pytest.approx(own["R0_25C"].value, rel=1e-6)
    # Laws through them: the instant resistance's closely; the others in the right direction.
    laws = {p.name: p for p in fit.params if p.name.startswith("Ea_")}
    assert laws["Ea_R0"].value == pytest.approx(LAWS["Ea_R0"], rel=0.1)
    assert laws["Ea_I0"].value > 10e3 and laws["Ea_Rd"].value > 5e3
    # A drive cycle at 5 degC it never saw.
    assert fit.checks[0]["rmse_mV"] < 3
    assert fit.validity["temperature_C"] == pytest.approx([-15.0, 25.0], abs=0.01)


def test_a_cell_fitted_at_three_temperatures_runs_in_studies(three_temperatures, tmp_path):
    from packtherm.cells import get_cell
    from packtherm.electrothermal import check_fitted_range, constant_current, simulate_cell
    from packtherm.study import StudyError, validate

    files = {"slow": [tmp_path / "slow.bin"]}
    files["slow"][0].write_bytes(b"slow")
    doc = fitted_cell_doc(three_temperatures, "Synthetic three-branch cell", files, like="PF")
    assert doc["usable_in_studies"] is True and doc["status"] == "multi-temperature"
    assert [row["at_C"] for row in doc["by_temperature"]] == list(TEMPS)
    # Which way each temperature's middle-branch time constant was set (v0.6.3).
    assert {row["tau_m_from"] for row in doc["by_temperature"]} <= {"pulses", "long tests"}
    path = write_fitted_cell(tmp_path / "fitted.yaml", doc)

    cell = get_cell(str(path))  # as a study's "cell: fitted.yaml" loads it
    assert cell.name == "Synthetic three-branch cell" and cell.model_label == "circuit (fitted)"
    assert cell.diameter == PF.diameter and cell.mass == PF.mass  # from 'like'
    assert cell.ecm.by_T and cell.capacity_Ah == pytest.approx(three_temperatures.capacity_Ah, rel=1e-4)
    for T in (253.15, 268.15, 288.15, 310.15):  # the file holds exactly what was fitted
        assert cell.ecm.R0(T) == pytest.approx(three_temperatures.ecm.R0(T), rel=1e-5)
        assert cell.ecm.Rm(T) == pytest.approx(three_temperatures.ecm.Rm(T), rel=1e-5)
    # Studies accept it: the only complaints are about the study, not the cell.
    with pytest.raises(StudyError) as e:
        validate({"cell": str(path)})
    assert not any(line.strip().startswith("cell:") for line in str(e.value).splitlines()[1:])

    # Inside its tested range: no warning. At 45 degC, and at 4C: warnings.
    res, load = simulate_cell(cell, constant_current(cell, 1.0), 600, 30.0, 293.15, pcm_thickness=0.0)
    assert check_fitted_range(cell, load, res) == []
    res, load = simulate_cell(cell, constant_current(cell, 4.0), 600, 30.0, 318.15, pcm_thickness=0.0)
    warnings = check_fitted_range(cell, load, res)
    assert any("warmer than its fitted model's warmest test" in w for w in warnings)
    assert any("Discharge 4.00C" in w and "extrapolation" in w for w in warnings)


def test_two_temperatures_are_not_enough_for_studies(three_temperatures, tmp_path):
    from dataclasses import replace

    two = replace(three_temperatures, temperatures=[5.0, 25.0], per_temperature=three_temperatures.per_temperature[:2])
    doc = fitted_cell_doc(two, "Two", {}, like="PF")
    assert doc["usable_in_studies"] is False and "3 or more" in doc["why_not_usable"]


def test_test_list_reports_every_problem(tmp_path):
    from packtherm.fitting.testlist import TestListError, read_test_list

    (tmp_path / "t.yaml").write_text(
        "packtherm_fit: 1\nname: x\nslow: missing.csv\nlike: NOPE\ncolour: red\n"
        "temperatures:\n  - at: 25\n    pulses: p.csv\n  - pulses: q.csv\n"
    )
    with pytest.raises(TestListError) as e:
        read_test_list(tmp_path / "t.yaml")
    msg = str(e.value)
    for bit in ("colour: unknown key", "slow: file not found", "temperatures[0].pulses: file not found",
                "temperatures[1].at: give the temperature", "like: Unknown cell"):  # fmt: skip
        assert bit in msg, bit


def test_a_test_list_needs_pulses_only_without_long_tests(tmp_path):
    from packtherm.fitting.testlist import TestListError, read_test_list

    for f in ("slow.csv", "cycle.csv"):
        (tmp_path / f).write_text("t_s,current_A,voltage_V\n")
    (tmp_path / "t.yaml").write_text(
        "packtherm_fit: 1\nname: x\nslow: slow.csv\ntemperatures:\n  - at: 25\n    cycles: [cycle.csv]\n"
    )
    assert read_test_list(tmp_path / "t.yaml").sets[0]["pulses"] is None
    (tmp_path / "t.yaml").write_text("packtherm_fit: 1\nname: x\nslow: slow.csv\ntemperatures:\n  - at: 25\n")
    with pytest.raises(TestListError, match="pulses: give a file name"):
        read_test_list(tmp_path / "t.yaml")


def test_fit_command_with_a_test_list(tmp_path, capsys):
    from packtherm.cli import main
    from packtherm.user_cells import load_cell

    def csv(rec, name):
        pd.DataFrame(
            {
                "Test_Time(s)": rec.t,
                "Current(A)": rec.current_A,
                "Voltage(V)": rec.voltage_V,
                "Temperature (C)_1": rec.temperature_C,
            }
        ).to_csv(tmp_path / name, index=False)
        return name

    lines = ["packtherm_fit: 1", "name: Listed", "like: PF", f"slow: {csv(slow_test(), 'slow.csv')}", "temperatures:"]
    for T in TEMPS:
        lines += [f"  - at: {T:g}", f"    pulses: {csv(pulse_test(T), f'p{T:g}.csv')}"]
    lines += ["output: listed.yaml"]
    (tmp_path / "tests.yaml").write_text("\n".join(lines) + "\n")
    main(["fit", str(tmp_path / "tests.yaml")])
    out = capsys.readouterr().out
    assert "fitted at -15, 5, 25 degC" in out and "usable in studies" in out
    assert (tmp_path / "listed.html").exists()
    cell = load_cell(tmp_path / "listed.yaml")
    assert len(cell.ecm.by_T) == 3


def test_real_panasonic_three_temperatures(monkeypatch):
    """The real cell at 25, 0 and -20 degC, from its pulse tests: resistances grow in the cold.

    One round of the fit, not three, to keep CI quick: this checks the shape, not the precision
    (docs/FITTING.md has the full fit and its checks).
    """
    from packtherm.fitting import circuit

    monkeypatch.setattr(circuit, "ROUNDS", 1)
    sets = [
        TestSet(real("25degC_5Pulse_HPPC"), None, 25.0),
        TestSet(real("10.44 0degC_5pulse_HPPC"), None, 0.0),
        TestSet(real("n20degC_5Pulse_HPPC"), None, -20.0),
    ]
    fit = fit_cell(real("C20 OCV"), sets=sets)
    rows = sorted(fit.ecm.by_T)  # coldest first
    R0 = [r[1] for r in rows]
    assert R0[0] > R0[1] > R0[2]  # colder: more resistance
    assert R0[2] == pytest.approx(0.025, rel=0.25)  # about 25 mOhm at 25 degC
    laws = {p.name: p.value for p in fit.params if p.name.startswith("Ea_") and p.source == "fitted"}
    assert 5e3 < laws["Ea_R0"] < 40e3 and 10e3 < laws["Ea_I0"] < 90e3
    assert all(e["rmse_mV"] < 60 for k, e in fit.errors.items() if "pulses at 20-95%" in k)


def test_chamber_calibration_in_a_test_list(tmp_path):
    from packtherm.fitting.testlist import TestListError, read_test_list

    for name in ("slow.csv", "p.csv", "check.csv"):
        (tmp_path / name).write_text("t_s,current_A,voltage_V\n0,0,4.1\n")
    base = "packtherm_fit: 1\nname: x\nlike: PF\nslow: slow.csv\ntemperatures:\n  - at: 25\n    pulses: p.csv\n"
    (tmp_path / "ok.yaml").write_text(base + "chamber_calibration: {file: p.csv, ambient_C: 24.5}\n")
    (cal,) = read_test_list(tmp_path / "ok.yaml").chamber_calibration
    assert cal["ambient_C"] == 24.5 and cal["start_soc"] == 1.0
    (tmp_path / "two.yaml").write_text(base + "chamber_calibration: [p.csv, {file: slow.csv, start_soc: 0.5}]\n")
    assert [c["start_soc"] for c in read_test_list(tmp_path / "two.yaml").chamber_calibration] == [1.0, 0.5]
    (tmp_path / "bad.yaml").write_text(
        base + "chamber_h_W_m2K: 30\nchecks: [{file: check.csv}]\n"
        "chamber_calibration: {file: check.csv, colour: red}\n"
    )
    with pytest.raises(TestListError) as e:
        read_test_list(tmp_path / "bad.yaml")
    msg = str(e.value)
    for bit in ("not both", "chamber_calibration.colour: unknown key", "one of the checks"):
        assert bit in msg, bit


def test_rig_calibrated_from_measured_heat():
    """The McMaster rig, from the 30T's 25 degC tests fitted to: h from the 1C discharge, the fixture from Mixed1."""
    import json

    from packtherm.cells import CELLS
    from packtherm.fitting.thermal import ThermalCheck, calibrate_rig
    from packtherm.testdata import load_test_data

    data = Path(__file__).resolve().parents[1] / "validation" / "data" / "samsung_30t"
    manifest = {m["name"]: m for m in json.loads((data / "manifest.json").read_text())}

    def check(name):
        m = manifest[name]
        assert m["role"] == "fit"
        return ThermalCheck(load_test_data(data / m["file"]), m["soc0"], m["ambient_C"])

    one = calibrate_rig([check("25C_1C_discharge_1")], CELLS["30T"])
    assert 20.0 < one["h_W_m2K"] < 120.0 and one["fixture_J_K"] == 0.0 and not one["note"]
    both = calibrate_rig([check("25C_1C_discharge_1"), check("25C_Mixed1")], CELLS["30T"])
    assert 20.0 < both["h_W_m2K"] < 120.0 and not both["note"]
    assert 0.0 < both["fixture_J_K"] < 2.0 * both["cell_J_K"]
    assert both["T_rmse_K"] < 0.6


# -- capacity by temperature (v0.6.5) ---------------------------------------------------------------

# A cell whose open-circuit curve shifts with temperature: at 10 degC it holds 94% of its 25 degC
# charge above the cut-off, at 0 degC 88% (the curve squeezed above a state of charge of 0.06, 0.12).
# Not as cold as the laws' tests (-15 degC): there the synthetic cell's kinetics, 16x slower, are
# the harder part, and this is about the curves.
SHIFT = {25.0: 0.0, 10.0: 0.06, 0.0: 0.12}


def _shifted(lost: float) -> tuple[tuple[float, ...], tuple[float, ...]]:
    soc = np.linspace(lost, 1.0, 101)
    return tuple(soc), tuple(float(TRUE_ECM.ocv((x - lost) / (1.0 - lost))) for x in soc)


SHIFTED_ECM = __import__("dataclasses").replace(
    TRUE_ECM, ocv_by_T=tuple((T + 273.15, *_shifted(lost)) for T, lost in SHIFT.items())
)


@pytest.fixture(scope="module")
def capacity_by_temperature():
    def run(T, parts, name, soc0=1.0):
        return synth(parts, soc0=soc0, name=name, T_C=T, ecm=SHIFTED_ECM)

    slow = [(3600, 0, 60), (25 * 3600, 0.15, 60), (3600, 0, 60)]
    pulses = [(3 * 3600, 0, 60)]
    for _ in range(10):
        pulses += [(10, CAP, 0.5), (60, 0, 0.5), (10, 2 * CAP, 0.5), (90, 0, 0.5), (360, CAP, 5), (3 * 3600, 0, 60)]
    sets = [
        TestSet(
            run(T, pulses, f"pulses_{T:g}.csv"),
            run(T, [(3 * 3600, 0, 60)] + [(5400, 0.3, 10), (3600, 0, 60)] * 6, f"steps_{T:g}.csv"),
            T,
            discharges=[run(T, [(4000, CAP, 2), (1800, 0, 10)], f"dis1c_{T:g}.csv")],
            slow=run(T, slow, f"slow_{T:g}.csv") if T != 25.0 else None,
        )
        for T in SHIFT
    ]
    check = run(0.0, [(4000, CAP, 2), (600, 0, 10)], "dis1c_check.csv")
    return fit_cell(run(25.0, slow, "slow_25.csv"), sets=sets, checks=[check], check_soc0=[1.0])


def test_open_circuit_curves_by_temperature_are_found(capacity_by_temperature):
    fit = capacity_by_temperature
    caps = {round(c.T_K - 273.15): c.capacity_Ah for c in fit.ocv_curves}
    assert set(caps) == {10, 0}
    for T, lost in SHIFT.items():
        if T == 25.0:
            continue
        # The slow test stops at its cut-off a little before the curve's end: its own drop.
        assert caps[round(T)] == pytest.approx((1 - lost) * fit.capacity_Ah, rel=0.02)
        for soc in (0.3, 0.5, 0.7, 0.9):
            true = SHIFTED_ECM.ocv(soc, T + 273.15)
            assert fit.ecm.ocv(soc, T + 273.15) == pytest.approx(true, abs=0.006), (T, soc)
    # Between curves, linear in temperature.
    mid = 0.5 * (fit.ecm.ocv(0.5, 273.15) + fit.ecm.ocv(0.5, 283.15))
    assert fit.ecm.ocv(0.5, 278.15) == pytest.approx(mid, abs=1e-9)


def test_a_cold_discharge_ends_where_the_cell_does(capacity_by_temperature):
    fit = capacity_by_temperature
    check = fit.checks[0]
    assert check["rmse_mV"] < 12
    one_curve = __import__("dataclasses").replace(fit.ecm, ocv_by_T=())
    from packtherm.ecm import ECMState

    def charge_out(ecm):
        st, soc, q = ECMState(), 1.0, 0.0
        while not st.cutoff and q < 2 * CAP:
            I, _ = st.apply(ecm, CAP, soc, 273.15, 2.0)
            soc -= I * 2.0 / 3600 / fit.capacity_Ah
            q += I * 2.0 / 3600
        return q

    truth = charge_out(SHIFTED_ECM)
    assert charge_out(fit.ecm) == pytest.approx(truth, rel=0.02)
    assert charge_out(one_curve) > 1.03 * truth  # one curve runs on: 4% here, more where the cell loses more


def test_curves_by_temperature_round_trip_through_the_cell_file(capacity_by_temperature, tmp_path):
    from packtherm.fitting.cellfile import ecm_from_doc

    doc = fitted_cell_doc(capacity_by_temperature, "shifted", {})
    assert len(doc["open_circuit_voltage"]["by_temperature"]) == 2
    ecm = ecm_from_doc(doc)
    for T in (268.15, 273.15, 278.15, 290.0, 298.15):
        assert ecm.ocv(0.4, T) == pytest.approx(capacity_by_temperature.ecm.ocv(0.4, T), abs=2e-4)
