"""Prepare the LG M50 core-temperature tests (v0.6.9).

Data: Gulsoy, Kucuk, Barai, Marco (University of Warwick), "Dataset of internal
temperature during lithium-ion battery ageing", Mendeley Data,
doi:10.17632/bf6fksxpp2.2, CC BY 4.0. LG INR21700-M50 (5 Ah) cells cycled at
25 degC: a C/3 CC-CV charge to 4.2 V, then a 1C (5 A) discharge to 2.5 V and a
60 s rest. Three cells (VP010-VP012) carry a thermocouple in their core as well
as on their surface; three (VP016-VP018) only on the surface.

Usage:  python validation/prepare_m50_core.py <ShortTermAgeing_100cycles/100cycles_dataTable.mat>

Reading the file needs mat-io (pip install mat-io: it reads MATLAB tables) and
about 6 GB of memory; PackTherm itself does not. Writes, for cycles 2 and 3 of
each instrumented cell and cycle 2 of one plain cell, the last 10 min of the
charge, the 1C discharge, its rest and the first hour of the next charge (the
cooling), as gzipped CSVs (t_s, current_A positive on discharge, voltage_V,
T_cell_C on the surface, T_core_C) with a manifest, to
validation/data/lg_m50_core/.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent / "data" / "lg_m50_core"
CITATION = (
    "M. Gulsoy, K. Kucuk, A. Barai, J. Marco, Dataset of internal temperature during lithium-ion battery "
    "ageing, University of Warwick, Mendeley Data v2, doi:10.17632/bf6fksxpp2.2"
)
CHARGE, DISCHARGE = 4, 5  # the tester's step numbers
BEFORE_S = 600.0  # of the charge before the discharge: settled at the chamber's temperature
AFTER_S = 3600.0  # of the next charge: the cooling
# (cell, the first part of the file with its current and core temperature logged, cycles, core thermocouple)
CELLS = [("VP010", 1, (2, 3), True), ("VP011", 0, (2, 3), True), ("VP012", 0, (2, 3), True), ("VP016", 0, (2,), False)]


def _segments(v) -> list[np.ndarray]:
    if not isinstance(v, np.ndarray):
        return []
    return [np.asarray(x, dtype=float).ravel() for x in v.ravel()]


def _write(name: str, cols: dict[str, np.ndarray]) -> None:
    lines = ["t_s,current_A,voltage_V,T_cell_C,T_core_C"]
    for t, i, v, ts, tc in zip(*cols.values()):
        core = f"{tc:.2f}" if np.isfinite(tc) else ""
        lines.append(f"{t:.1f},{i:.4f},{v:.4f},{ts:.2f},{core}")
    text = "\n".join(lines) + "\n"
    path = OUT / f"{name}.csv.gz"
    if not (path.exists() and gzip.decompress(path.read_bytes()).decode() == text):
        path.write_bytes(gzip.compress(text.encode(), compresslevel=9, mtime=0))


def main(src: str) -> None:
    from matio import load_from_mat  # pip install mat-io

    table = next(v for k, v in load_from_mat(src).items() if not k.startswith("__"))
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for cell, seg, cycles, cored in CELLS:
        row = table[table["Cell Name"] == cell].iloc[0]
        col = {c: _segments(row[c])[seg] for c in ("Prog Time", "Current [A] ", "Voltage [V]", "Surf Temp [C]", "Step ", "Cycle No")}
        core = _segments(row["Core Temp [C]"])
        Tc = core[seg] if cored else np.full(col["Prog Time"].size, np.nan)
        t = col["Prog Time"] / 1000.0  # ms
        step, cyc = col["Step "], col["Cycle No"]
        for c in cycles:
            dis = np.flatnonzero((cyc == c) & (step == DISCHARGE))
            nxt = np.flatnonzero((cyc == c + 1) & (step == CHARGE))
            t0, t1 = t[dis[0]] - BEFORE_S, t[nxt[0]] + AFTER_S
            m = (t >= t0) & (t <= t1)
            name = f"{cell}_cycle{c}"
            _write(
                name,
                {
                    "t": t[m] - t[m][0],
                    "I": -col["Current [A] "][m],  # the tester's: discharge negative
                    "V": col["Voltage [V]"][m],
                    "Ts": col["Surf Temp [C]"][m],
                    "Tc": Tc[m],
                },
            )
            ambient = float(np.median(col["Surf Temp [C]"][m][: int(BEFORE_S // 2)]))
            manifest.append(
                {
                    "name": name,
                    "file": f"{name}.csv.gz",
                    "cell": cell,
                    "cycle": c,
                    "core_thermocouple": cored,
                    "ambient_C": round(ambient, 2),
                    "ambient_from": "the surface over the first 5 min (the end of a 3 h charge at C/3: settled)",
                    "soc0": 1.0,
                    "soc0_from": "full: the end of a CC-CV charge to 4.2 V",
                    "samples": int(m.sum()),
                }
            )
            print(f"{name}: {m.sum()} samples, ambient {ambient:.2f} degC")
    doc = {"citation": CITATION, "licence": "CC BY 4.0", "tests": manifest}
    (OUT / "manifest.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
