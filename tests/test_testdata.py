"""Reading cell test data (packtherm.testdata): formats, units, sign, checks and the labelled parts."""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from packtherm.testdata import TestDataError, current_sign, find_columns, label_segments, load_test_data

R0, R1, TAU = 0.03, 0.015, 20.0  # a simple cell for synthetic records
CAP = 3.0  # Ah


def simulate(t: np.ndarray, current: np.ndarray, T_amb: float = 25.0) -> dict[str, np.ndarray]:
    """Voltage and temperature of a simple one-RC cell (+ = discharge)."""
    soc, v1 = 1.0, 0.0
    V = np.empty_like(t)
    T = np.empty_like(t)
    temp = T_amb
    for k in range(t.size):
        dt = t[k] - t[k - 1] if k else 0.0
        soc -= current[k] * dt / 3600 / CAP
        v1 += dt * (R1 * current[k] - v1) / TAU
        temp += dt * (current[k] ** 2 * R0 / 40.0 - (temp - T_amb) / 600.0)
        V[k] = 3.0 + 1.2 * soc - R0 * current[k] - v1
        T[k] = temp
    return {"t": t, "I": current, "V": V, "T": T}


def steps(*parts: tuple[float, float], dt: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """(duration_s, current_A) parts -> sampled time and current."""
    t, I, t0 = [], [], 0.0
    for dur, cur in parts:
        n = round(dur / dt)
        t.append(t0 + dt * np.arange(n))
        I.append(np.full(n, float(cur)))
        t0 += dur
    return np.concatenate(t), np.concatenate(I)


HPPC = (
    (60, 0),
    (10, 6.0),
    (40, 0),
    (10, -4.5),
    (600, 0),
    (1800, 1.5),  # C/2 to the next level
    (3600, 0),
    (10, 6.0),
    (40, 0),
    (10, -4.5),
    (600, 0),
)


def write_csv(path: Path, cols: dict[str, np.ndarray]) -> Path:
    pd.DataFrame(cols).to_csv(path, index=False)
    return path


def test_reads_an_arbin_export_and_labels_an_hppc_test(tmp_path):
    t, I = steps(*HPPC)
    s = simulate(t, I)
    f = write_csv(
        tmp_path / "arbin.csv",
        {
            "Data_Point": np.arange(t.size),
            "Test_Time(s)": s["t"],
            "Current(A)": s["I"],
            "Voltage(V)": s["V"],
            "Temperature (C)_1": s["T"],
        },
    )
    rec = load_test_data(f, capacity_Ah=CAP)
    assert rec.columns == {
        "time": "Test_Time(s)",
        "current": "Current(A)",
        "voltage": "Voltage(V)",
        "temperature": "Temperature (C)_1",
    }
    assert not any("flipped" in c for c in rec.conversions)  # already + = discharge
    kinds = [x.kind for x in rec.segments()]
    assert kinds == ["rest", "pulse", "rest", "pulse", "rest", "constant", "rest", "pulse", "rest", "pulse", "rest"]
    cc = rec.segments()[5]
    assert cc.current_A == pytest.approx(1.5) and cc.charge_Ah == pytest.approx(0.75, rel=0.01)
    assert cc.duration_s == pytest.approx(1800, abs=1)
    assert rec.segment_table()[1]["c_rate"] == pytest.approx(2.0)
    assert rec.warnings == []


def test_biologic_units_and_charge_positive_sign(tmp_path):
    t, I = steps(*HPPC)
    s = simulate(t, I)
    # Biologic: current in mA with charge positive, time/s, Ewe/V.
    f = write_csv(tmp_path / "biologic.csv", {"time/s": s["t"], "<I>/mA": -1e3 * s["I"], "Ewe/V": s["V"]})
    rec = load_test_data(f)
    assert rec.columns["current"] == "<I>/mA" and rec.columns["voltage"] == "Ewe/V"
    assert np.allclose(rec.current_A, s["I"])  # mA -> A, and flipped to + = discharge
    assert any("current from ma" in c for c in rec.conversions)
    assert any("flipped" in c for c in rec.conversions)


def test_neware_durations_and_mv_found_from_the_values(tmp_path):
    t, I = steps((60, 0), (600, 1.0), (300, 0))
    s = simulate(t, I)
    hms = [f"{int(x // 3600)}:{int(x % 3600 // 60):02d}:{x % 60:06.3f}" for x in s["t"]]
    f = write_csv(tmp_path / "neware.csv", {"Total Time": hms, "Current(mA)": 1e3 * s["I"], "Voltage": 1e3 * s["V"]})
    rec = load_test_data(f)
    assert rec.t[-1] == pytest.approx(s["t"][-1])
    assert np.allclose(rec.voltage_V, s["V"]) and np.allclose(rec.current_A, s["I"])
    assert any("h:mm:ss" in c for c in rec.conversions) and any("voltage from mV" in c for c in rec.conversions)


def test_kollmeyer_mat_file(tmp_path):
    import scipy.io as sio

    t, I = steps(*HPPC)
    s = simulate(t, I)
    meas = {
        "TimeStamp": np.array(["3/11/2017 8:47:03 AM"] * t.size, dtype=object),
        "Time": s["t"],
        "Voltage": s["V"],
        "Current": -s["I"],  # Kollmeyer: discharge negative
        "Ah": np.zeros(t.size),
        "Battery_Temp_degC": s["T"],
        "Chamber_Temp_degC": np.full(t.size, 25.0),
    }
    f = tmp_path / "kollmeyer.mat"
    sio.savemat(f, {"meas": meas})
    rec = load_test_data(f)
    assert rec.columns["time"] == "Time" and rec.columns["temperature"] == "Battery_Temp_degC"
    assert rec.columns["ambient"] == "Chamber_Temp_degC"
    assert np.allclose(rec.current_A, s["I"])
    assert "flipped" in rec.conversions[0] and "the voltage agreed at 11 of 11 checks" in rec.conversions[0]


def test_single_sample_mat_file_is_reported(tmp_path):
    import scipy.io as sio

    f = tmp_path / "stub.mat"
    sio.savemat(f, {"meas": {"Time": 0.0, "Voltage": 3.6, "Current": 0.0}})
    with pytest.raises(TestDataError, match="single sample"):
        load_test_data(f)


def test_sign_from_a_record_that_starts_mid_discharge():
    # No step from rest at the start: the voltage's drift during the long
    # steady current, and its recovery at the end, give the sign.
    t, I = steps((3000, -2.9), (600, 0), dt=10.0)
    s = simulate(t, -I)  # simulate the discharge, then record it with discharge negative
    sign, why = current_sign(t, I, s["V"])
    assert sign == -1, why


def test_drive_cycle_is_one_dynamic_part():
    rng = np.random.default_rng(1)
    parts = [(60, 0)] + [(float(rng.integers(2, 15)), float(rng.normal(0.8, 1.5))) for _ in range(300)] + [(600, 0)]
    t, I = steps(*parts)
    s = simulate(t, I)
    kinds = [x.kind for x in label_segments(t, I, s["V"])]
    assert kinds == ["rest", "dynamic", "rest"]
    assert current_sign(t, I, s["V"])[0] == 1


def test_cc_cv_charge():
    t = np.arange(0.0, 7200.0, 1.0)
    I = np.where(t < 3600, -1.5, -1.5 * np.exp(-(t - 3600) / 900))  # CC then a CV taper
    I[t < 60] = 0.0
    V = np.where(t < 3600, 3.6 + 0.6 * t / 3600, 4.2)
    V[t < 60] = 3.6
    kinds = [x.kind for x in label_segments(t, I, V)]
    assert kinds == ["rest", "cc-cv"]


def test_gaps_repeats_backwards_time_and_missing_rows(tmp_path):
    t, I = steps((60, 0), (600, 1.0), (600, 0))
    s = simulate(t, I)
    df = pd.DataFrame({"Time": s["t"], "Current": s["I"], "Voltage": s["V"]})
    df.loc[700:, "Time"] += 7200  # a two-hour gap
    df = pd.concat([df.iloc[:300], df.iloc[[299]], df.iloc[300:]])  # a repeated row
    df.loc[df.index[10], "Voltage"] = np.nan  # a missing value
    rows = df.to_dict("records")
    rows.insert(500, dict(rows[100]))  # the clock steps back
    f = tmp_path / "messy.csv"
    pd.DataFrame(rows).to_csv(f, index=False)
    rec = load_test_data(f)
    w = " | ".join(rec.warnings)
    assert "1 of" in w and "missing" in w
    assert "time runs backwards" in w
    assert "1 gap" in w and "2 h 00 min" in w
    assert np.all(np.diff(rec.t) > 0)
    # Across the gap the cell is taken as resting: no charge is counted there.
    assert rec.charge_Ah()[-1] == pytest.approx(600 / 3600, rel=0.01)


def test_capacity_check_flags_charge_from_another_file(tmp_path):
    t, I = steps((60, 0), (3000, 3.0), (600, 0), (3000, 3.0), (600, 0), dt=5.0)
    s = simulate(t, I)
    f = write_csv(tmp_path / "two_discharges.csv", {"Time": s["t"], "Current": s["I"], "Voltage": s["V"]})
    rec = load_test_data(f, capacity_Ah=CAP)
    assert any("more than the cell's 3 Ah" in w for w in rec.warnings)


def test_columns_named_explicitly_and_errors(tmp_path):
    t, I = steps((60, 0), (600, 1.0), (60, 0))
    s = simulate(t, I)
    f = write_csv(tmp_path / "odd.csv", {"secs": s["t"], "amps_out": s["I"], "cellV": s["V"]})
    with pytest.raises(TestDataError, match=r"could not find the time, current, voltage columns.*'secs'"):
        load_test_data(f)
    rec = load_test_data(f, columns={"time": "secs", "current": "amps_out", "voltage": "cellV"})
    assert rec.columns == {"time": "secs", "current": "amps_out", "voltage": "cellV"}
    with pytest.raises(TestDataError, match="no column 'nope'"):
        load_test_data(f, columns={"time": "nope"})
    with pytest.raises(TestDataError, match="unknown column role"):
        load_test_data(f, columns={"pressure": "secs"})
    with pytest.raises(TestDataError, match="Excel"):
        (tmp_path / "a.xlsx").write_bytes(b"x")
        load_test_data(tmp_path / "a.xlsx")


def test_column_names_of_common_testers():
    assert find_columns(["Test Time (s)", "Current (A)", "Voltage (V)", "Aux_Temperature_1 (C)"]) == {
        "time": "Test Time (s)",
        "current": "Current (A)",
        "voltage": "Voltage (V)",
        "temperature": "Aux_Temperature_1 (C)",
    }
    cols = find_columns(["time/s", "Ewe/V", "<I>/mA", "Ecell/V"])
    assert cols["voltage"] == "Ewe/V" and cols["current"] == "<I>/mA"


def test_cli(tmp_path, capsys):
    from packtherm.cli import main

    t, I = steps(*HPPC)
    s = simulate(t, I)
    f = write_csv(tmp_path / "hppc.csv", {"Time": s["t"], "Current": s["I"], "Voltage": s["V"]})
    main(["data", str(f), "--capacity", "3", "--segments", "--plot", str(tmp_path / "p.png")])
    out = capsys.readouterr().out
    assert "4 pulse" in out and "c_rate" in out and (tmp_path / "p.png").stat().st_size > 10_000
    main(["data", str(f), "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert [x["kind"] for x in doc["segments"]].count("pulse") == 4
    with pytest.raises(SystemExit) as e:
        main(["data", str(tmp_path / "missing.csv")])
    assert e.value.code == 2 and "file not found" in capsys.readouterr().err


PF = os.environ.get("PACKTHERM_PF_DATA")  # the Panasonic NCR18650PF dataset, if present


@pytest.mark.skipif(not PF, reason="set PACKTHERM_PF_DATA to the Panasonic 18650PF dataset folder")
def test_panasonic_dataset():
    root = Path(PF)
    hppc = load_test_data(next(root.rglob("*25degC_5Pulse_HPPC*.mat")), capacity_Ah=2.9)
    assert [s.kind for s in hppc.segments()].count("pulse") == 67
    assert any("flipped" in c for c in hppc.conversions)
    udds = load_test_data(next(root.rglob("*25degC_UDDS_Pan18650PF.mat")))
    assert [s.kind for s in udds.segments()].count("dynamic") == 1
    assert udds.charge_Ah()[-1] > 2.0  # a full discharge, read as positive
