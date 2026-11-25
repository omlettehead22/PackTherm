"""Design search (v0.6.14): pymoo's NSGA-II over the design space as ranges."""

import json

import numpy as np
import pytest

from packtherm.cells import LG_M50
from packtherm.design import DutyCycle, Requirements
from packtherm.module_design import ModuleDesign, ModuleStudy
from packtherm.study import StudyError, StudySpec, file_stem, validate

pytest.importorskip("pymoo")

from packtherm.search import SearchSettings, Space, best_designs, constraints, run_module_search

DUTY = DutyCycle.constant(1.0, "discharge", soc0=1.0, soc_limits=(0.6, 1.0), rest_after_s=1800)


def study(**kw):
    base = {
        "topologies": ("none", "air", "ribbon"),
        "air_flows_g_s": (0.1, 0.4),
        "coolant_flows_g_s": (0.01, 0.08),
        "chiller_inlets_C": (15.0, 25.0),
        "fillers": (None, "RT31"),
        "gaps_mm": (1.0, 4.0),
        "mode": "fast",
        "dt": 8.0,
    }
    base.update(kw)
    return ModuleStudy(LG_M50, DUTY, Requirements(T_env_C=30.0), **base)


def test_variables_become_canonical_designs():
    sp = Space(study())
    assert set(sp.variables()) == {"topology", "filler", "flow", "gap", "chilled", "chiller"}
    x = {"topology": "air", "filler": "RT31", "flow": 0.0, "gap": 2.04, "chilled": True, "chiller": 18.2}
    assert sp.design(x) == ModuleDesign("air", 0.1, None, None, 2.0)  # air: open gaps, no chiller
    assert sp.design({**x, "flow": 1.0}).flow_g_s == 0.4
    assert sp.design({**x, "flow": 0.5}).flow_g_s == pytest.approx(0.2)  # log scale: the geometric middle
    none = sp.design({**x, "topology": "none"})
    assert none == ModuleDesign("none", 0.0, None, "RT31", 2.0)
    rib = sp.design({**x, "topology": "ribbon", "flow": 0.0})
    assert rib.flow_g_s == 0.01 and rib.inlet_C == 18.0 and rib.filler == "RT31"
    assert rib.gap_mm == sp.ribbon_gap  # widened to fit the ribbon
    assert sp.design({**x, "topology": "ribbon", "chilled": False}).inlet_C is None
    # A single listed value is fixed, not a variable; set-points at or above ambient are dropped.
    fixed = Space(study(gaps_mm=(2.0,), chiller_inlets_C=(15.0, 35.0)))
    assert "gap" not in fixed.variables() and "chiller" not in fixed.variables()
    assert fixed.chiller == (15.0, 15.0)


def _row(**kw):
    r = {
        "T_peak_C": 40.0,
        "T_limit_C": 45.0,
        "dT_cell_C": 2.0,
        "cell_to_cell_K": 1.0,
        "cell_to_cell_limit_K": np.inf,
        "capacity_after_pct": 70.0,
        "fail_reason": "",
        "feasible": True,
        "mass_overhead_pct": 5.0,
        "aux_energy_pct": 0.5,
        "volume_overhead_pct": 30.0,
    }
    r.update(kw)
    return r


def test_constraints_agree_with_the_fail_reason():
    s = study()
    assert all(g <= 0 for g in constraints(_row(), s))
    hot = constraints(_row(T_peak_C=47.0, fail_reason="hot", feasible=False), s)
    assert hot[0] == pytest.approx(0.4) and all(g <= 0 for g in hot[1:])
    slow = constraints(_row(fail_reason="slow · short", feasible=False), s)
    assert slow[2] == 1.0 and slow[4] == 1.0
    aged = constraints(_row(capacity_after_pct=60.0, fail_reason="ages", feasible=False), study(capacity_min_pct=65.0))
    assert aged[5] == pytest.approx(0.5)


def test_best_designs_go_by_rank_then_spread():
    rows = [
        _row(mass_overhead_pct=1, aux_energy_pct=3),
        _row(mass_overhead_pct=2, aux_energy_pct=2),
        _row(mass_overhead_pct=3, aux_energy_pct=1),
        _row(mass_overhead_pct=3, aux_energy_pct=3),  # dominated
        _row(mass_overhead_pct=0, aux_energy_pct=0, feasible=False, fail_reason="hot", T_peak_C=50.0),
    ]
    assert best_designs(rows, 3, ("mass", "energy")) == [0, 1, 2]
    assert best_designs(rows, 2, ("mass", "energy")) == [0, 2]  # the ends of the front
    assert best_designs(rows, 4, ("mass", "energy"))[-1] == 3
    assert best_designs(rows, 4, ("mass",))[0] == 0
    # A third objective: the dominated row is now the smallest, so it joins the front.
    rows[3]["volume_overhead_pct"] = 10.0
    assert 3 in best_designs(rows, 4, ("mass", "energy", "volume"))[:4]
    assert set(best_designs(rows, 3, ("mass", "energy", "volume"))) <= {0, 1, 2, 3}
    for r in rows:
        r["feasible"] = False
        r["_G"] = constraints({**r, "fail_reason": "hot", "T_peak_C": 45.0 + r["mass_overhead_pct"]}, study())
    assert best_designs(rows, 12, ("mass", "energy"))[0] == 4  # none feasible: the nearest misses


def test_a_small_search_runs_and_its_picks_survive_the_recheck():
    s = study()
    r = run_module_search(s, SearchSettings(evaluations=16, population=8, final_designs=4), workers=1)
    log = r.search
    assert log.worst_case and 0 < len(log.history) <= 16 and log.generations >= 2
    assert set(r.table.design) <= set(log.history.design)
    assert 1 <= len(r.table) <= 4
    assert np.allclose(r.table.R0_mOhm, s.cell.R0_25C * 1e3)  # the final rows at the cell's resistance
    assert np.allclose(log.history.R0_mOhm, s.R0_worst * 1e3)  # the search at worst case
    if r.picks:
        assert all(p.robust for p in r.picks.values())
    assert any("NSGA-II" in n for n in r.notes())


def test_search_section_in_study_files(tmp_path):
    base = {"packtherm_study": 1, "cell": "M50", "duty": {"type": "constant", "c_rate": 1.0}}
    grid = validate(base)
    assert "search" not in grid and not StudySpec(grid).is_search
    spec = validate({**base, "search": {"evaluations": 50}})
    assert spec["search"] == {
        "evaluations": 50,
        "population": 20,
        "seed": 1,
        "mode": "fast",
        "final_designs": 12,
        "objectives": ["mass", "energy"],
        "worst_case": True,
    }
    assert validate(spec) == spec
    assert file_stem(spec) == file_stem(grid) + "_search"
    assert StudySpec(spec).search_settings().objectives == ("mass", "energy")
    bad = {"evaluations": 5, "population": 30, "objectives": ["mass", "speed", "mass"], "colour": 1}
    with pytest.raises(StudyError) as e:
        validate({**base, "search": bad})
    for word in ("search.evaluations", "search.objectives[1]", "each objective once", "search.colour"):
        assert word in str(e.value)


def test_search_is_refused_where_it_cannot_run():
    from packtherm import browser

    doc = {"packtherm_study": 1, "cell": "M50", "duty": {"type": "constant", "c_rate": 1.0}, "search": {}}
    out = json.loads(browser.check_study(json.dumps(doc)))
    assert not out["ok"] and "command line" in out["error"]
