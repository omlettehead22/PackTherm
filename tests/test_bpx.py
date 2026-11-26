"""Cells from BPX files (v0.6.16).

The test file is the LG M50 written from PyBaMM's Chen2020 parameter set
(tests/data/lg_m50_chen2020_bpx.json, its header says how).
"""

import json
import math
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("bpx")

from packtherm.bpx import BPXError, cylinder, read_bpx, write_cell_files
from packtherm.cells import LG_M50
from packtherm.user_cells import CellError, from_datasheet, load_cell

FILE = Path(__file__).parent / "data" / "lg_m50_chen2020_bpx.json"


def test_cylinder_from_volume_and_area():
    for d, h in ((0.0185, 0.065), (0.0211, 0.0701), (0.046, 0.08)):
        V, A = math.pi * d * d / 4 * h, math.pi * d * d / 2 + math.pi * d * h
        assert cylinder(V, A) == pytest.approx((d, h), rel=1e-9)
    with pytest.raises(BPXError):
        cylinder(1e-4, 1e-4)  # less area than any cylinder of that volume


def test_the_m50_file():
    b = read_bpx(FILE)
    assert b.chemistry == "NMC" and b.capacity_Ah == 5.0 and (b.V_min, b.V_max) == (2.5, 4.2)
    assert b.diameter_mm == pytest.approx(1e3 * LG_M50.diameter, abs=0.01)
    assert b.height_mm == pytest.approx(1e3 * LG_M50.height, abs=0.05)
    assert b.mass_g == pytest.approx(1e3 * LG_M50.mass, rel=1e-3)
    assert b.k_W_mK == pytest.approx(LG_M50.k_radial, rel=1e-3)  # from the User-defined block
    assert b.ocv_V[0] == pytest.approx(2.5, abs=0.01) and b.ocv_V[-1] == pytest.approx(4.19, abs=0.01)
    assert np.all(np.diff(b.ocv_V) > 0) and 3.6 < b.V_nominal < 3.75
    assert not any(b.dUdT_mV_K) and any("entropic coefficients are zero" in n for n in b.notes)
    # The open-circuit voltage at half charge, by hand from the file's two OCPs.
    P = json.loads(FILE.read_text())["Parameterisation"]
    ne, pe = P["Negative electrode"], P["Positive electrode"]
    x = ne["Minimum stoichiometry"] + 0.5 * (ne["Maximum stoichiometry"] - ne["Minimum stoichiometry"])
    y = pe["Maximum stoichiometry"] - 0.5 * (pe["Maximum stoichiometry"] - pe["Minimum stoichiometry"])
    ev = {"exp": math.exp, "tanh": math.tanh}
    U = eval(pe["OCP [V]"], ev, {"x": y}) - eval(ne["OCP [V]"], ev, {"x": x})
    assert b.ocv_V[b.soc.index(0.5)] == pytest.approx(U, abs=1e-9)


def _variant(tmp_path, edit) -> Path:
    doc = json.loads(FILE.read_text())
    edit(doc)
    p = tmp_path / "variant.json"
    p.write_text(json.dumps(doc))
    return p


def test_reversible_heat_from_the_electrodes(tmp_path):
    def edit(d):
        d["Parameterisation"]["Negative electrode"]["Entropic change coefficient [V.K-1]"] = 1e-4
        d["Parameterisation"]["Positive electrode"]["Entropic change coefficient [V.K-1]"] = {
            "x": [0, 1],
            "y": [-2e-4, 2e-4],
        }

    b = read_bpx(_variant(tmp_path, edit))
    pe = json.loads(FILE.read_text())["Parameterisation"]["Positive electrode"]
    for s in (0.0, 0.5, 1.0):
        y = pe["Maximum stoichiometry"] - s * (pe["Maximum stoichiometry"] - pe["Minimum stoichiometry"])
        dp = -2e-4 + 4e-4 * y
        assert b.dUdT_mV_K[b.soc.index(s)] == pytest.approx(1e3 * (dp - 1e-4), abs=1e-9)


def test_what_it_refuses(tmp_path):
    def not_cylindrical(d):
        d["Header"]["Title"] = "An NMC cell"
        d["Header"]["Description"] = ""

    p = _variant(tmp_path, not_cylindrical)
    with pytest.raises(BPXError, match="cylindrical"):
        read_bpx(p)
    assert read_bpx(p, diameter_mm=21.0, height_mm=70.0).diameter_mm == 21.0  # given the size, it reads

    def no_chemistry(d):
        d["Header"]["Title"] = "A cylindrical cell"

    with pytest.raises(BPXError, match="chemistry"):
        read_bpx(_variant(tmp_path, no_chemistry))
    assert read_bpx(_variant(tmp_path, no_chemistry), chemistry="NMC").chemistry == "NMC"
    bad = tmp_path / "bad.json"
    bad.write_text('{"Header": {"BPX": "1.0.0", "Title": "x", "Model": "DFN"}}')
    with pytest.raises(BPXError, match="not a valid BPX file"):
        read_bpx(bad)


def test_cell_file_with_a_datasheet_resistance(tmp_path):
    b = read_bpx(FILE)
    paths = write_cell_files(b, tmp_path, name="M50 from BPX", DCIR_mOhm=30.0)
    assert set(paths) == {"cell"}
    c = load_cell(paths["cell"])
    assert c.R0_25C == pytest.approx(0.030) and c.capacity_Ah == 5.0 and c.model_label == "user-defined, lumped DCIR"
    assert c.dUdT(0.5) == 0.0  # the file's (zero) reversible heat, not the chemistry's
    with pytest.raises(BPXError):
        write_cell_files(b, tmp_path)  # neither a resistance nor a derived circuit


def test_dUdT_table_in_a_datasheet_cell():
    base = {"name": "t", "format": "21700", "capacity_Ah": 5, "V_nominal": 3.65, "mass_g": 68, "DCIR_mOhm": 25}
    c = from_datasheet(**base, entropic_soc=[0, 0.5, 1], entropic_mV_K=[0.1, -0.2, 0.0])
    assert c.dUdT(0.25) == pytest.approx(-0.05e-3) and c.dUdT(2.0) == pytest.approx(0.0)
    for bad, word in (
        ({"entropic_soc": [0, 1]}, "both or neither"),
        ({"entropic_soc": [0, 1], "entropic_mV_K": [0.1]}, "as many values"),
        ({"entropic_soc": [0.5, 0.2], "entropic_mV_K": [0.1, 0.1]}, "rising"),
        ({"entropic_soc": [0, 1], "entropic_mV_K": [100, 0]}, "units"),
    ):
        with pytest.raises(CellError, match=word):
            from_datasheet(**base, **bad)


def test_deriving_the_circuit(tmp_path):
    pytest.importorskip("pybamm")
    from packtherm.bpx_fit import FitSettings, derive
    from packtherm.design import DutyCycle, Requirements
    from packtherm.fitting.cellfile import dc_resistance
    from packtherm.module_design import ModuleDesign, ModuleStudy, evaluate_module_design
    from packtherm.user_cells import read_cell_file, validate_cell

    b = read_bpx(FILE)
    fast = FitSettings(temperatures_C=(25.0, 5.0, -10.0), socs=(0.8, 0.5, 0.3), rates_C=(1.0, 2.0), rest_min=10.0)
    rep = derive(b, fast)
    assert rep.pulses == 3 * 3 * 2
    assert max(rep.pulse_error_pct.values()) < 5.0 and max(rep.replay_rmse_mV.values()) < 15.0
    # Chen2020's M50: about 27 mOhm at 25 degC (the measured cells about 34, the O'Regan derivation 17).
    assert 20e-3 < dc_resistance(rep.ecm, capacity_Ah=5.0) < 35e-3
    assert dc_resistance(rep.ecm, T=263.15, capacity_Ah=5.0) > dc_resistance(rep.ecm, capacity_Ah=5.0)
    paths = write_cell_files(b, tmp_path, name="M50 from BPX", report=rep)
    doc = read_cell_file(paths["circuit"])
    assert doc["like"] == paths["cell"].name and doc["usable_in_studies"]
    assert "not measured" in doc["data_warnings"][0]
    spec, _ = validate_cell(doc)
    from packtherm.user_cells import cell_from_spec

    cell = cell_from_spec(spec, tmp_path)
    assert cell.ecm is not None and cell.model_label == "circuit (fitted)"
    duty = DutyCycle.constant(1.0, "discharge", soc0=1.0, soc_limits=(0.5, 1.0), rest_after_s=600)
    s = ModuleStudy(cell, duty, Requirements(T_env_C=25.0), mode="fast", dt=8.0)
    row = evaluate_module_design(s, ModuleDesign("ribbon", 0.05))
    assert 25.0 < row["T_peak_C"] < 40.0
