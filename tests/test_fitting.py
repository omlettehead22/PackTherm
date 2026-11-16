"""Fitting the circuit model (packtherm.fitting, v0.6.1).

Two kinds of check:

- known answers: tests made by a cell with known values, read back through the
  whole fit. The fit must find those values, and predict a drive cycle it
  never saw.
- real data: the Panasonic NCR18650PF tests in tests/data (CC BY 4.0). There
  is no true answer, so the check is the one a user would make: the fitted
  cell must predict the drive cycle it was not fitted to, and as well as the
  library cell does.

Also: the fitted cell file (contents, hashes) and that studies refuse it.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from packtherm.cells import PANASONIC_NCR18650PF as PF
from packtherm.ecm import ECMState
from packtherm.fitting import (
    CircuitModel,
    fit_cell,
    fitted_cell_doc,
    read_fitted_cell,
    track_soc,
    write_fitted_cell,
    write_report,
)
from packtherm.fitting.circuit import interval_current
from packtherm.fitting.ocv import OCVCurve
from packtherm.testdata import TestRecord, load_test_data

CAP = 3.0
TRUE = {
    "R0_25C": 0.022,
    "I0_25C": 2.5,
    "gamma": 1.1,
    "tau_ct": 2.5,
    "Rd_25C": 0.018,
    "tau_d": 150.0,
    "soc_a": 6.0,
    "soc_b": 0.06,
}
# How close each value must come (noise-free tests made by the same model).
TOLERANCE = {
    "R0_25C": 0.01,
    "I0_25C": 0.03,
    "gamma": 0.03,
    "tau_ct": 0.03,
    "Rd_25C": 0.03,
    "tau_d": 0.05,
    "soc_a": 0.05,
    "soc_b": 0.02,
}
_OCV = OCVCurve(np.array(PF.ecm.ocv_soc), np.array(PF.ecm.ocv_V), CAP, 2.5, 4.2, 0.0, "library table")
TRUE_ECM = CircuitModel().ecm(TRUE, _OCV)


def synth(parts, soc0: float = 1.0, name: str = "synthetic") -> TestRecord:
    """A test from (duration_s, current_A, dt_s) parts, made by TRUE_ECM; a discharge stops at its cut-off.

    The tester's charge counter is recorded too, as real testers do.
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
    soc, eta, vd = soc0, 0.0, 0.0
    e = TRUE_ECM
    stopped = False
    for k in range(t.size):
        if k:
            if part[k] != part[k - 1]:
                stopped = False
            if stopped:
                I[k] = 0.0
            dt = t[k] - t[k - 1]
            soc -= I[k] * dt / 3600 / CAP
            q[k] = q[k - 1] + I[k] * dt / 3600
            f = e.soc_factor(soc) if I[k] > 0 else 1.0
            e1, e2 = math.exp(-dt / e.tau_ct), math.exp(-dt / e.tau_d)
            eta = eta * e1 + f * e.eta_ss(I[k], 298.15) * (1 - e1)
            vd = vd * e2 + f * e.Rd(298.15) * I[k] * (1 - e2)
        f = e.soc_factor(soc) if I[k] > 0 else 1.0
        V[k] = e.ocv(soc) - I[k] * f * e.R0(298.15) - eta - vd
        if I[k] > 0 and V[k] < e.V_min:
            stopped = True  # the tester stops the discharge at its cut-off (from the next sample)
    return TestRecord(t=t, current_A=I, voltage_V=V, temperature_C=np.full(t.size, 25.0), counter_Ah=q, source=name)


def slow_test() -> TestRecord:
    return synth([(3600, 0, 60), (25 * 3600, 0.15, 60), (3600, 0, 60)], name="slow.csv")


def pulse_test() -> TestRecord:
    parts = [(1800, 0, 30)]
    for _ in range(10):  # ten levels, from full down to 10%
        parts += [(10, CAP, 0.5), (40, 0, 0.5), (10, 2 * CAP, 0.5), (40, 0, 0.5)]
        parts += [(360, CAP, 5), (1500, 0, 30)]  # 10% at 1C, then a rest
    return synth(parts, name="pulses.csv")


def steps_test() -> TestRecord:
    parts = [(1800, 0, 60)]
    for _ in range(6):
        parts += [(1500, 0.9, 10), (1800, 0, 60)]  # 10 x tau_d: settled by its end
    return synth(parts, name="steps.csv")


def drive_test() -> TestRecord:
    rng = np.random.default_rng(3)
    parts = [(1800, 0, 30)] + [(float(rng.integers(5, 40)), float(rng.uniform(-1.5, 4.5)), 0.5) for _ in range(60)]
    return synth(parts, soc0=0.8, name="drive.csv")


@pytest.fixture(scope="module")
def synthetic_fit():
    return fit_cell(slow_test(), pulse_test(), steps=steps_test(), checks=[drive_test()])


def test_simulator_matches_packtherms_ecm():
    # The fit's replay must be the model PackTherm runs: same voltages as ECMState.step.
    rec = drive_test()
    soc, _ = track_soc(rec, _OCV, CAP)
    I = interval_current(rec)
    V = CircuitModel().simulate(TRUE_ECM, rec.t, I, soc, np.full(rec.t.size, 298.15))
    st = ECMState()
    ref = [st.step(TRUE_ECM, 0.0, soc[0], 298.15, 0.0)[0]]
    for k in range(1, rec.t.size):
        v, st.eta_ct, st.V_d = st.step(TRUE_ECM, I[k], soc[k], 298.15, rec.t[k] - rec.t[k - 1])
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
    # Most true values lie in their 95% ranges. On noise-free tests a small
    # steady bias (here in soc_a, about 3%) can sit outside: the ranges show how
    # far the windows disagree, which is all a fit to real tests can know.
    inside = [n for n in TRUE if got[n].ci95[0] <= TRUE[n] <= got[n].ci95[1]]
    assert len(inside) >= 6, inside
    assert all(e["rmse_mV"] < 1 for k, e in fit.errors.items() if "20-95%" in k)


def test_predicts_a_drive_cycle_it_never_saw(synthetic_fit):
    (check,) = synthetic_fit.checks
    assert check["rmse_mV"] < 1


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


def test_soc_from_a_start_given_or_from_the_first_voltage():
    rec = drive_test()
    soc, how = track_soc(rec, _OCV, CAP, soc0=0.8)
    assert soc[0] == 0.8 and "as given" in how
    # It has a 30-minute rest at the start, so it anchors there.
    soc, how = track_soc(rec, _OCV, CAP)
    assert soc[0] == pytest.approx(0.8, abs=0.01) and "settled" in how


# -- the cell file and the report -------------------------------------------------------------------


def test_cell_file_round_trip_and_studies_refuse_it(synthetic_fit, tmp_path):
    from packtherm.study import StudyError, validate
    from packtherm.user_cells import CellError, load_cell

    files = {}
    for role in ("slow", "pulses", "steps"):
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
    assert back["errors"]["held_out"][0]["rmse_mV"] < 1

    with pytest.raises(CellError, match="one temperature"):
        load_cell(path)
    with pytest.raises(StudyError, match=r"cell: .*one temperature.*v0\.6\.2"):
        validate({"cell": str(path)})

    report = write_report(tmp_path / "cell.html", synthetic_fit, doc)
    html = report.read_text()
    assert "Not usable in studies yet" in html and "never saw" in html and html.count("data:image/png") >= 4


# -- real data (tests/data/panasonic_18650pf, CC BY 4.0) --------------------------------------------

REAL = Path(__file__).parent / "data" / "panasonic_18650pf"


def real(name: str) -> TestRecord:
    return load_test_data(next(REAL.glob(f"*{name}*")))


def test_real_panasonic_fit_predicts_a_drive_cycle():
    fit = fit_cell(
        real("C20 OCV"),
        real("5Pulse_HPPC"),
        steps=real("dis5_10p"),
        checks=[real("UDDS")],
        compare_ecm=("library", PF.ecm, PF.capacity_Ah),
    )
    # The C/20 discharge holds 2.995 Ah, by the tester's own counter (rated 2.9 Ah).
    assert fit.capacity_Ah == pytest.approx(2.995, abs=0.005)
    (check,) = fit.checks
    # The UDDS cycle was not fitted to. The fit predicts it to about 5 mV RMS,
    # better than the library cell (about 10 mV), whose values came from the
    # same dataset by a simpler method.
    assert check["rmse_mV"] < 7
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
    assert "not usable in studies yet" in text and "held out" in text
    assert out.exists() and out.with_suffix(".html").exists()
    assert read_fitted_cell(out)["name"] == "my_cell"
