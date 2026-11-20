"""The McMaster data preparation's rules, on small made-up records (the raw datasets are not stored here)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_mcmaster", ROOT / "validation" / "prepare_mcmaster.py")
P = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = P  # its dataclass looks itself up there
spec.loader.exec_module(P)


def test_start_times_read_with_or_without_the_underscore():
    a = P.started(Path("12-24-18_02.18 607_Dis_2C_n20degC_LGHG2.mat"))
    b = P.started(Path("12-24-1822.25 610_Charge5.mat"))
    assert (b - a).total_seconds() == (22 * 60 + 25 - (2 * 60 + 18)) * 60


def test_folders_spell_negative_temperatures_their_own_way():
    root = Path("/data")
    assert P.DATASETS["30t"].folder(root, -10) == root / "-10degC"
    assert P.DATASETS["hg2"].folder(root, -20) == root / "n20degC"
    assert P.DATASETS["hg2"].folder(root, 25) == root / "25degC"


def test_a_tail_is_cut_where_the_chamber_ramps():
    t = np.arange(0.0, 3000.0)
    I = np.where(t < 1000, 3.0, 0.0)
    T = np.where(t < 1000, -20 + t / 100, -10 - 10 * (1 - np.exp(-(t - 1000) / 200)))
    T = np.where(t > 2000, T + (t - 2000) / 50, T)  # the chamber warming for the next charge
    r = {"t": t, "current_A": I, "voltage_V": np.full_like(t, 3.6), "T_cell_C": T}
    out, cut = P.cut_tail(r, -20.0)
    assert 2000 <= out["t"][-1] <= 2100 and cut > 800


def test_manifests_are_whole():
    for slug, n in (("samsung_30t", 94), ("lg_hg2", 86)):
        data = ROOT / "validation" / "data" / slug
        manifest = json.loads((data / "manifest.json").read_text())
        assert len(manifest) == n
        for m in manifest:
            assert (data / m["file"]).exists() and 0.4 < m["soc0"] <= 1.0
            assert m["role"] in ("fit", "validation")
        fits = sorted(m["name"] for m in manifest if m["role"] == "fit")
        assert len(fits) == 12 and all(f.endswith(("_1C_discharge_1", "_Mixed1")) for f in fits)
    excluded = json.loads((ROOT / "validation" / "data" / "lg_hg2" / "excluded.json").read_text())
    assert sorted(e["name"] for e in excluded) == ["25C_HWFET"] + [f"40C_Mixed{i}" for i in range(4, 9)]
