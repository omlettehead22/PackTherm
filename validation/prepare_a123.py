"""Prepare the A123 ANR26650M1B (LFP) tests for PackTherm's fit (v0.6.6).

Data: Kawakita de Souza, "A123 26650 m1b LFP Cell Data" (University of
Colorado Colorado Springs), Mendeley Data v1, doi:10.17632/p8kf893yv3.1,
CC BY 4.0. Tests in Plett's format: OCV scripts (S1: a C/30 discharge at the
test temperature from full, charged at 25 degC; S3: a C/30 charge at it) and
DYN scripts (S1: a 1C step to about 80%, a 15 min rest, then blocks of a
drive profile with 5 min rests between, at the test temperature, from full).

Usage:  python validation/prepare_a123.py <the dataset's folder>

Reads the Arbin .xlsx exports (they carry the cell temperature; the .mat
files don't) and writes gzipped CSVs (t_s, current_A positive on discharge,
voltage_V, T_cell_C, Ah: the tester's net charge discharged) with a
manifest to validation/data/a123_26650/. The slow tests (OCV) are thinned to
one sample in 10 s, keeping the tester's charge counter at each, so no charge
is lost; the rest are kept at the tester's 1 s.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent / "data" / "a123_26650"
CITATION = (
    "M. Kawakita de Souza, A123 26650 m1b LFP Cell Data, University of Colorado Colorado Springs, "
    "Mendeley Data v1, doi:10.17632/p8kf893yv3.1"
)
# Setpoints in the file names: N15 is -15 degC, P05 is 5 degC.
TEMPS = {"N15": -15, "N05": -5, "P05": 5, "P15": 15, "P25": 25, "P35": 35, "P45": 45}
SLOW_DT_S = 10.0
SETTLED_S = 600.0  # the cell temperature over the last this long of the first rest: the test's ambient

# (name, file, role, kind): the fitted tests (one slow discharge and one drive profile per temperature)
# and the checks (every other profile, and the C/30 charge at 25 degC for hysteresis).
FILES: list[tuple[str, str, str, str]] = []
for code in TEMPS:
    FILES.append((f"{code}_C30_discharge", f"OCVdata/A002_OCV_{code}_S1.xlsx", "fit", "slow"))
# -25 degC is left out: its drive profile logged no cell temperature at all (nor the first part of its
# slow discharge), and a test with none is replayed at 25 degC, by the fit and by its checks alike.
FIT_DYN = {"N15": "20", "N05": "15", "P05": "10", "P15": "10", "P25": "20", "P35": "05", "P45": "10"}
CHECK_DYN = [("N15", "05"), ("N15", "15"), ("P25", "50")]
for code, n in FIT_DYN.items():
    FILES.append((f"{code}_DYN{n}", f"DYNdata/A002_DYN/A002_DYN_{n}_{code}_S1.xlsx", "fit", "dynamic"))
for code, n in CHECK_DYN:
    FILES.append((f"{code}_DYN{n}", f"DYNdata/A002_DYN/A002_DYN_{n}_{code}_S1.xlsx", "validation", "dynamic"))
FILES.append(("P25_C30_charge", "OCVdata/A002_OCV_P25_S3.xlsx", "hysteresis", "slow_charge"))


def read_arbin(path: Path) -> dict[str, np.ndarray]:
    """Every channel sheet of an Arbin export, in order: time, current (discharge positive), voltage, temperature."""
    import pandas as pd

    book = pd.ExcelFile(path)
    sheets = [s for s in book.sheet_names if s.startswith("Channel")]
    d = pd.concat([book.parse(s) for s in sheets], ignore_index=True)
    temps = [c for c in d.columns if c.startswith("Aux_Temperature")]
    T = d[temps[0]].to_numpy(float) if temps else np.full(len(d), np.nan)
    counter = (d["Discharge_Capacity(Ah)"] - d["Charge_Capacity(Ah)"]).to_numpy(float)
    return {
        "t": d["Test_Time(s)"].to_numpy(float),
        "I": -d["Current(A)"].to_numpy(float),  # Arbin: discharge negative
        "V": d["Voltage(V)"].to_numpy(float),
        "T": T,
        "q": counter - counter[0],
    }


def thin(r: dict[str, np.ndarray], dt: float) -> dict[str, np.ndarray]:
    """One sample per dt, keeping each step's first and last sample (current changes are not smeared)."""
    edges = np.flatnonzero(np.abs(np.diff(r["I"])) > 1e-3)
    keep = np.zeros(r["t"].size, bool)
    keep[0] = keep[-1] = True
    keep[edges] = keep[edges + 1] = True
    slot = np.floor((r["t"] - r["t"][0]) / dt)
    keep[np.flatnonzero(np.diff(slot)) + 1] = True
    return {k: v[keep] for k, v in r.items()}


def ambient(r: dict[str, np.ndarray]) -> float | None:
    """The cell temperature at the end of the first rest (the soak before the test starts)."""
    loaded = np.flatnonzero(np.abs(r["I"]) > 1e-3)
    if not loaded.size or not np.isfinite(r["T"]).any():
        return None
    k = loaded[0]
    m = (r["t"] >= r["t"][k] - SETTLED_S) & (np.arange(r["t"].size) < k) & np.isfinite(r["T"])
    return round(float(np.median(r["T"][m])), 2) if m.any() else None


def write(name: str, r: dict[str, np.ndarray]) -> None:
    lines = ["t_s,current_A,voltage_V,T_cell_C,Ah"]
    t0 = r["t"][0]
    for t, i, v, T, q in zip(r["t"] - t0, r["I"], r["V"], r["T"], r["q"]):
        Ts = f"{T:.2f}" if np.isfinite(T) else ""
        lines.append(f"{t:.2f},{i:.4f},{v:.4f},{Ts},{q:.5f}")
    text = "\n".join(lines) + "\n"
    path = OUT / f"{name}.csv.gz"
    # Left as it is when its content is unchanged (gzip stores a time); written with none otherwise.
    if not (path.exists() and gzip.decompress(path.read_bytes()).decode() == text):
        path.write_bytes(gzip.compress(text.encode(), compresslevel=9, mtime=0))


def main(root: str) -> None:
    base = Path(root)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, rel, role, kind in FILES:
        r = read_arbin(base / rel)
        code = name.split("_")[0]
        amb = ambient(r)
        how = f"cell temperature over the last {SETTLED_S:g} s of the soak before the test"
        if kind.startswith("slow"):
            r = thin(r, SLOW_DT_S)
        write(name, r)
        manifest.append(
            {
                "name": name,
                "file": f"{name}.csv.gz",
                "setpoint_C": TEMPS[code],
                "role": role,
                "kind": kind,
                "source": rel,
                "ambient_C": amb,
                "ambient_from": how,
                "soc0": 0.0 if kind == "slow_charge" else 1.0,
                "soc0_from": "empty: discharged to 2.0 V before it"
                if kind == "slow_charge"
                else "full: charged at 25 degC (Plett's script) before the soak",
                "samples": int(r["t"].size),
            }
        )
        print(f"{name}: {r['t'].size} samples, ambient {amb} degC, {r['q'][-1]:+.3f} Ah")
    doc = {"citation": CITATION, "licence": "CC BY 4.0", "tests": manifest}
    (OUT / "manifest.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
