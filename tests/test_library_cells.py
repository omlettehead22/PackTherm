"""The cell library's fitted cells: what ships with PackTherm matches the fit that made it."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest
import yaml

from packtherm.cells import CELLS, get_cell
from packtherm.fitting.cellfile import dc_resistance

ROOT = Path(__file__).resolve().parents[1]


def test_samsung_30t_is_its_fitted_cell_file():
    cell, lumped = CELLS["30T"], CELLS["30T-LUMPED"]
    shipped = yaml.safe_load((ROOT / "src" / "packtherm" / "data" / "samsung_30t_fitted.yaml").read_text())
    example = yaml.safe_load((ROOT / "docs" / "examples" / "fitting" / "samsung_30t_fitted.yaml").read_text())
    # The library's copy is the documented fit's, value for value.
    assert shipped["model"] == example["model"] and shipped["open_circuit_voltage"] == example["open_circuit_voltage"]
    assert shipped["usable_in_studies"] is True and shipped["like"] == "30T-LUMPED"
    assert get_cell("30t") is cell and cell.model_label == "circuit (fitted)" and not cell.user_defined
    # Six temperatures, -20 to 40 degC, and the tested range carried for the studies' warnings.
    assert len(cell.ecm.by_T) == 6
    lo, hi = cell.validity["temperature_C"]
    assert lo < -19.0 and hi > 39.0
    # Size, mass and thermal properties are the lumped cell's; its resistance is the fit's.
    for k in ("diameter", "height", "mass", "cp", "k_radial", "form_factor", "max_discharge_C"):
        assert getattr(cell, k) == getattr(lumped, k), k
    r0 = dc_resistance(cell.ecm, capacity_Ah=cell.capacity_Ah)
    assert cell.R0_25C == pytest.approx(r0)
    assert lumped.R0_25C == pytest.approx(r0, rel=0.02)


def test_samsung_30t_resistance_grows_in_the_cold():
    ecm = CELLS["30T"].ecm
    R = [dc_resistance(ecm, T=273.15 + T, capacity_Ah=3.0) for T in (40, 25, 10, 0, -10, -20)]
    assert all(b > a for a, b in pairwise(R))


def test_lg_hg2_is_its_fitted_cell_file():
    cell, lumped = CELLS["HG2"], CELLS["HG2-LUMPED"]
    shipped = yaml.safe_load((ROOT / "src" / "packtherm" / "data" / "lg_hg2_fitted.yaml").read_text())
    example = yaml.safe_load((ROOT / "docs" / "examples" / "fitting" / "lg_hg2_fitted.yaml").read_text())
    assert shipped["model"] == example["model"] and shipped["open_circuit_voltage"] == example["open_circuit_voltage"]
    assert shipped["usable_in_studies"] is True and shipped["like"] == "HG2-LUMPED"
    assert get_cell("hg2") is cell and cell.model_label == "circuit (fitted)" and not cell.user_defined
    assert len(cell.ecm.by_T) == 6
    lo, hi = cell.validity["temperature_C"]
    assert lo < -19.0 and hi > 37.0
    for k in ("diameter", "height", "mass", "cp", "k_radial", "form_factor", "max_discharge_C"):
        assert getattr(cell, k) == getattr(lumped, k), k
    r0 = dc_resistance(cell.ecm, capacity_Ah=cell.capacity_Ah)
    assert cell.R0_25C == pytest.approx(r0)
    assert lumped.R0_25C == pytest.approx(r0, rel=0.02)


def test_a123_is_its_fitted_cell_file():
    # v0.6.6: an LFP cell, fitted blind without pulse tests.
    cell, lumped = CELLS["A123"], CELLS["A123-LUMPED"]
    shipped = yaml.safe_load((ROOT / "src" / "packtherm" / "data" / "a123_26650_fitted.yaml").read_text())
    example = yaml.safe_load((ROOT / "docs" / "examples" / "fitting" / "a123_26650_fitted.yaml").read_text())
    assert shipped["model"] == example["model"] and shipped["open_circuit_voltage"] == example["open_circuit_voltage"]
    assert shipped["usable_in_studies"] is True and shipped["like"] == "A123-LUMPED"
    assert "no pulse test" in shipped["provenance"]["settings"]["kinetics fitted on"]
    assert get_cell("a123") is cell and cell.chemistry == lumped.chemistry == "LFP / graphite"
    assert len(cell.ecm.by_T) == 7 and len(shipped["open_circuit_voltage"]["by_temperature"]) == 6  # and 25 degC
    for k in ("diameter", "height", "mass", "cp", "k_radial", "form_factor", "max_discharge_C"):
        assert getattr(cell, k) == getattr(lumped, k), k
    r0 = dc_resistance(cell.ecm, capacity_Ah=cell.capacity_Ah)
    assert cell.R0_25C == pytest.approx(r0)
    assert lumped.R0_25C == pytest.approx(r0, rel=0.02)
    R = [dc_resistance(cell.ecm, T=273.15 + T, capacity_Ah=cell.capacity_Ah) for T in (45, 25, 5, -15)]
    assert all(b > a for a, b in pairwise(R))
    assert 3.2 < cell.ecm.ocv(0.5) < 3.4  # the LFP plateau


def test_only_the_lfp_cell_has_hysteresis():
    # v0.6.7: the A123's gap between its charge and discharge branches, from its slow charges.
    a123 = CELLS["A123"].ecm
    assert len(a123.hyst) == 7  # 15 degC takes 25 degC's: its slow charge is held out
    assert 0.02 < a123.hyst_V(298.15) < 0.04
    assert not CELLS["30T"].ecm.hyst and not CELLS["HG2"].ecm.hyst
