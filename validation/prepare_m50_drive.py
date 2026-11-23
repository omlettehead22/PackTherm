"""Prepare the LG M50 drive-profile runs from the Warwick data (v0.6.9).

Data: Gulsoy, Kucuk, Barai, Marco (University of Warwick), "Dataset of internal
temperature during lithium-ion battery ageing", Mendeley Data,
doi:10.17632/bf6fksxpp2.2, CC BY 4.0 (LoadProfileTesting/LoadProfile_dataTable.mat).

Three cells, about 12.4 h each, logged at up to 1 kHz: a C/3 CC-CV charge to
4.2 V, a rest, then drive cycles (up to 7.2 A discharge and 2.5 A regen) with
partial CC-CV top-ups to 4.0 V and rests between, down to about 16 % charge.

The file is MATLAB v7.3 (HDF5), so h5py reads it a column at a time (h5py is
needed only here, not by PackTherm). The table's columns sit in the file's
#refs# group; each run's eight columns are recognised by their values (asserted
below). This keeps, for each run, from one minute before the first drive cycle
(rested after the full charge: state of charge 1) to the end, in 1 s bins (mean
current, last voltage), as gzipped CSVs (t_s, current_A positive on discharge,
voltage_V) with a manifest, to validation/data/lg_m50_drive/.

The file's six temperature channels (10 Hz) carry no clock shared with the
electrical log, so they are not used here.

Usage:  python validation/prepare_m50_drive.py <LoadProfile_dataTable.mat>
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent / "data" / "lg_m50_drive"
CITATION = (
    "M. Gulsoy, K. Kucuk, A. Barai, J. Marco, Dataset of internal temperature during lithium-ion battery "
    "ageing, University of Warwick, Mendeley Data v2, doi:10.17632/bf6fksxpp2.2"
)
# Each run's columns in the file, in table order: current (mA, negative on discharge),
# capacity (mAh), step, cycle, time (s), time again, zeros, voltage (V).
RUNS = {"run_A": "1 5 C G K O S W", "run_B": "Y 3 A E I M Q U", "run_C": "Z 4 B F J N R V"}


def read_run(f, keys: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    k = keys.split()
    col = lambda name: f["#refs#/" + name][0, :]  # noqa: E731
    I_mA, t, V = col(k[0]), col(k[4]), col(k[7])
    assert 7000 < -I_mA.min() < 7500 and 2000 < I_mA.max() < 3000, "not the current in mA"
    assert np.all(np.diff(t) >= 0) and t[-1] > 40000, "not the time"
    assert 3.0 < V.min() and V.max() < 4.25, "not the voltage"
    b = np.floor(t).astype(np.int64)
    starts = np.r_[0, np.flatnonzero(np.diff(b)) + 1]
    ends = np.r_[starts[1:], len(t)]
    I = -np.add.reduceat(I_mA, starts) / (ends - starts) / 1000.0
    return b[starts].astype(float), I, V[ends - 1]


def main(path: str) -> None:
    import h5py

    OUT.mkdir(parents=True, exist_ok=True)
    tests = []
    with h5py.File(path, "r") as f:
        for name, keys in RUNS.items():
            t, I, V = read_run(f, keys)
            first_drive = int(np.flatnonzero((t > 3.0 * 3600) & (I > 0.05))[0])
            s = slice(first_drive - 60, None)
            tt = t[s] - t[s][0]
            lines = ["t_s,current_A,voltage_V"] + [f"{a:.0f},{b:.4f},{c:.4f}" for a, b, c in zip(tt, I[s], V[s])]
            (OUT / f"{name}.csv.gz").write_bytes(gzip.compress(("\n".join(lines) + "\n").encode(), mtime=0))
            tests.append({"name": name, "samples": len(tt), "duration_s": float(tt[-1])})
            print(name, len(tt), "s,", round(tt[-1] / 3600, 2), "h")
    manifest = {
        "citation": CITATION,
        "licence": "CC BY 4.0",
        "cell": "LG INR21700-M50, chamber 25 degC",
        "start": "rested after a C/3 CC-CV charge to 4.2 V: state of charge 1",
        "tests": tests,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
