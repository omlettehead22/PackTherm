"""Which inputs matter most (v0.6.15): Morris screening with SALib around one design."""

import json
import pickle

import numpy as np
import pytest

from packtherm.cells import LG_M50
from packtherm.design import DutyCycle, Requirements
from packtherm.module import BottomPlate, Layout
from packtherm.module_design import ModuleDesign, ModuleStudy
from packtherm.sensitivity import FACTORS, ScaledDUdT, applicable, design_from_spec, perturbed
from packtherm.study import StudyError, StudySpec, file_stem, validate

DUTY = DutyCycle.constant(1.0, "discharge", soc0=1.0, soc_limits=(0.6, 1.0), rest_after_s=1800)


def study(**kw):
    return ModuleStudy(LG_M50, DUTY, Requirements(T_env_C=30.0), mode="fast", dt=8.0, **kw)


def test_inputs_that_apply_to_each_design():
    assert "flow" not in applicable(ModuleDesign("none")) and "tim_conductivity" not in applicable(ModuleDesign("none"))
    air = applicable(ModuleDesign("air", 0.3))
    assert "flow" in air and "heat_transfer" in air and "tim_conductivity" not in air
    assert "chiller_inlet" not in applicable(ModuleDesign("ribbon", 0.05))
    assert "chiller_inlet" in applicable(ModuleDesign("bottom", 0.05, 20.0))
    assert set(applicable(ModuleDesign("bottom", 0.05, 20.0))) == set(FACTORS)


def test_each_input_moves_what_it_names():
    s, d = study(), ModuleDesign("bottom", 0.05, 20.0, "RT31", 2.0)
    x = {
        "ambient": 3.0,
        "resistance": 0.5,
        "cell_heat_capacity": 1.1,
        "cell_conductivity": 0.7,
        "entropic_heat": 1.5,
        "tim_conductivity": 0.5,
        "heat_transfer": 1.3,
        "flow": 0.8,
        "chiller_inlet": -2.0,
    }
    st, dd, R0 = perturbed(s, d, x)
    assert st.requirements.T_env_C == 33.0
    assert R0 == pytest.approx(0.5 * (LG_M50.R0_25C + s.R0_worst))
    assert st.cell.cp == pytest.approx(1.1 * LG_M50.cp) and st.cell.k_radial == pytest.approx(0.7 * LG_M50.k_radial)
    assert st.cell.dUdT(0.5) == pytest.approx(1.5 * LG_M50.dUdT(0.5))
    assert st.tim.k == pytest.approx(0.5 * s.tim.k)
    assert st.air.h_ref == pytest.approx(1.3 * s.air.h_ref)
    assert dd.flow_g_s == pytest.approx(0.04) and dd.inlet_C == 18.0 and dd.filler == "RT31"
    # Coolant h scales through the new multiplier; the default changes nothing.
    base = BottomPlate(coolant=s.coolant).h_contact(LG_M50, Layout(), 25.0)
    assert BottomPlate(coolant=st.coolant).h_contact(LG_M50, Layout(), 25.0) == pytest.approx(1.3 * base)
    # Nothing moved: the same study, design and resistance.
    assert perturbed(s, d, {}) == (s, d, None)
    # Worker processes need the scaled dU/dT to pickle.
    assert pickle.loads(pickle.dumps(ScaledDUdT(LG_M50.dUdT, 2.0)))(0.5) == pytest.approx(2 * LG_M50.dUdT(0.5))


def test_design_from_the_study_file():
    assert design_from_spec({"topology": "ribbon", "flow_g_s": 0.05, "filler": "none", "gap_mm": 3.5}) == ModuleDesign(
        "ribbon", 0.05, None, None, 3.5
    )
    assert design_from_spec({"topology": "none", "flow_g_s": 1.0, "filler": "RT42"}) == ModuleDesign(
        "none", 0.0, None, "RT42", 2.0
    )


def test_a_small_screening_ranks_the_inputs():
    pytest.importorskip("SALib")
    from packtherm.sensitivity import SensitivitySettings, run_sensitivity

    settings = SensitivitySettings(
        design={"topology": "air", "flow_g_s": 0.3}, trajectories=2, factors=("ambient", "flow", "cell_heat_capacity")
    )
    r = run_sensitivity(study(), settings, workers=1)
    assert len(r.samples) == 2 * (3 + 1) and r.factors == ["ambient", "flow", "cell_heat_capacity"]
    peak = r.ranking[r.ranking.output == "T_peak_C"].set_index("factor")
    # Air at ambient: the ambient moves the peak by about its own range (10 K); heat capacity by little.
    assert 5.0 < peak.mu_star["ambient"] < 12.0
    assert peak.mu_star["cell_heat_capacity"] < peak.mu_star["ambient"] / 5
    assert peak["rank"]["ambient"] == 1
    assert "ambient temperature" in r.summary()
    # Air designs run fans: running energy reacts to flow.
    energy = r.ranking[r.ranking.output == "aux_energy_pct"].set_index("factor")
    assert energy["rank"]["flow"] == 1


def test_sensitivity_section_in_study_files():
    base = {"packtherm_study": 1, "cell": "M50", "duty": {"type": "constant", "c_rate": 1.0}}
    spec = validate({**base, "sensitivity": {}})
    assert spec["sensitivity"] == {
        "design": "balanced",
        "trajectories": 10,
        "levels": 4,
        "seed": 1,
        "mode": "fast",
        "factors": None,
        "ranges": {},
    }
    assert validate(spec) == spec and file_stem(spec) == file_stem(validate(base)) + "_sensitivity"
    named = validate(
        {
            **base,
            "sensitivity": {
                "design": {"topology": "bottom", "flow_g_s": 0.05, "chiller_C": 20},
                "ranges": {"ambient": [-2, 8]},
            },
        }
    )
    st = StudySpec(named).sensitivity_settings()
    assert st.ranges == {"ambient": (-2, 8)} and st.factors is None
    bad = {
        "design": {"topology": "air", "flow_g_s": 0, "chiller_C": 20, "filler": "wax", "colour": 1},
        "levels": 3,
        "factors": ["ambient", "humidity"],
        "ranges": {"flow": [1.2, 0.8]},
    }
    with pytest.raises(StudyError) as e:
        validate({**base, "sensitivity": bad})
    for word in (
        "sensitivity.design.flow_g_s",
        "sensitivity.design.chiller_C",
        "sensitivity.design.filler",
        "sensitivity.design.colour",
        "sensitivity.levels",
        "sensitivity.factors[1]",
        "sensitivity.ranges.flow",
    ):
        assert word in str(e.value)
    with pytest.raises(StudyError, match="not both"):
        validate({**base, "sensitivity": {}, "search": {}})
    with pytest.raises(StudyError, match="sensitivity.design"):
        validate({**base, "sensitivity": {"design": "coolest"}})


def test_sensitivity_is_refused_where_it_cannot_run():
    from packtherm import browser

    doc = {"packtherm_study": 1, "cell": "M50", "duty": {"type": "constant", "c_rate": 1.0}, "sensitivity": {}}
    out = json.loads(browser.check_study(json.dumps(doc)))
    assert not out["ok"] and "command line" in out["error"]


def test_example_results_are_consistent():
    """The example's stored ranking matches its samples (no re-run: that takes minutes)."""
    pytest.importorskip("SALib")
    from pathlib import Path

    import pandas as pd
    from SALib.analyze import morris

    ex = Path(__file__).resolve().parents[1] / "docs" / "examples"
    doc = json.loads((ex / "module_m50_roadtrip_130kmh_35c_sensitivity_results.json").read_text())
    samples = pd.read_csv(ex / "module_m50_roadtrip_130kmh_35c_sensitivity_samples.csv")
    names = [i["name"] for i in doc["inputs"]]
    problem = {"num_vars": len(names), "names": names, "bounds": [[i["low"], i["high"]] for i in doc["inputs"]]}
    Si = morris.analyze(problem, samples[names].to_numpy(), samples["T_peak_C"].to_numpy(), num_levels=4, seed=1)
    stored = {r["factor"]: r["mu_star"] for r in doc["ranking"] if r["output"] == "T_peak_C"}
    assert np.allclose([stored[n] for n in names], Si["mu_star"])
    assert validate(doc["study"]) == doc["study"]


def test_the_design_can_be_a_grid_pick():
    pytest.importorskip("SALib")
    from packtherm.sensitivity import SensitivitySettings, run_sensitivity

    s = study(topologies=("air",), air_flows_g_s=(0.3,), fillers=(None,), gaps_mm=(2.0,))
    r = run_sensitivity(s, SensitivitySettings(design="balanced", trajectories=2, factors=("ambient", "flow")), workers=1)
    assert r.grid is not None and len(r.grid.table) == 1
    assert r.design == ModuleDesign("air", 0.3, None, None, 2.0) and "(balanced)" in r.design_label
