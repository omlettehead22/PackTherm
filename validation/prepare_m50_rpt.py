"""Prepare the LG M50 pulse tests from the Warwick characterisation runs (v0.6.9).

Data: Gulsoy, Kucuk, Barai, Marco (University of Warwick), "Dataset of internal
temperature during lithium-ion battery ageing", Mendeley Data,
doi:10.17632/bf6fksxpp2.2, CC BY 4.0 (ShortTermAgeing_100cycles/ShortTerm_RPT_dataTable.mat).

The file holds 33 reference performance tests (RPTs) of 25 h each: six cells at
25 degC, tested five or six times as they aged. Each RPT: a C/3 charge, a 1C
discharge, a C/10 discharge, a C/3 charge to full, then at about 100, 80, 50
and 20 % state of charge a 2C (10 A) discharge pulse of 30 s and a C/2 (2.5 A)
pulse, with C/3 charges between and C/3 discharges to the next level.

This script keeps each cell's FIRST RPT (the fresh cell), from the end of the
full charge (state of charge 1) to an hour after the last 2C pulse, as gzipped CSVs
(t_s, current_A positive on discharge, voltage_V) with a manifest, to
validation/data/lg_m50_rpt/.

The file stores MATLAB table objects. mat-io reads them but needs more memory
than a 7 GB machine has for this 241 MB file, so the table's numbers are taken
straight from the MAT v5 elements of its workspace (scipy reads that as bytes):
33 arrays a column, in column order. The columns are recognised by their values
(asserted below). The cell names are not in that part of the file, so the files
are numbered by their place in it (rpt_00 ... rpt_27: the first RPT of each cell).

Usage:  python validation/prepare_m50_rpt.py <ShortTerm_RPT_dataTable.mat>   (about 2 GB of memory)
"""

from __future__ import annotations

import gzip
import json
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent / "data" / "lg_m50_rpt"
CITATION = (
    "M. Gulsoy, K. Kucuk, A. Barai, J. Marco, Dataset of internal temperature during lithium-ion battery "
    "ageing, University of Warwick, Mendeley Data v2, doi:10.17632/bf6fksxpp2.2"
)
N_TESTS = 33
FIRST_RPTS = (0, 5, 10, 15, 21, 27)  # each cell's first RPT (the capacity falls test by test after each)
AFTER_S = 3600.0  # after the last 2C pulse: its 2.5 A pulse and the rest after it

_NUM = {1: "i1", 2: "u1", 3: "i2", 4: "u2", 5: "i4", 6: "u4", 7: "f4", 9: "f8", 12: "i8", 13: "u8"}
_CONTAINERS = {1, 2, 3, 17}  # cell, struct, object, opaque
_NUMERIC = set(range(6, 16))


def _tag(buf, p):
    t, n = struct.unpack_from("<II", buf, p)
    if t >> 16:  # small data element
        return t & 0xFFFF, t >> 16, p + 4, p + 8
    return t, n, p + 8, p + 8 + (n + 7) // 8 * 8


def _walk(buf, p, end, depth, out):
    while p + 8 <= end:
        t, n, d, nxt = _tag(buf, p)
        if t == 15:  # compressed
            sub = zlib.decompress(bytes(buf[d : d + n]))
            _walk(memoryview(sub), 0, len(sub), depth, out)
        elif t == 14 and n:  # matrix
            _matrix(buf, d, d + n, depth, out)
        p = nxt


def _matrix(buf, p, end, depth, out):
    t, n, d, p = _tag(buf, p)  # array flags
    cls = buf[d] if n else 0
    t, n, d, p = _tag(buf, p)  # dims
    dims = np.frombuffer(buf, "<i4", n // 4, d)
    t, n, d, p = _tag(buf, p)  # name
    if cls in _CONTAINERS:
        _walk(buf, p, end, depth + 1, out)
    elif cls in _NUMERIC and np.prod(dims) >= 1000:
        t, n, d, _ = _tag(buf, p)
        if t in _NUM:
            dt = np.dtype("<" + _NUM[t])
            out.append((depth, np.frombuffer(buf, dt, n // dt.itemsize, d).astype(float)))


def columns(path: Path) -> dict[str, list[np.ndarray]]:
    """The table's numeric columns, 33 tests each: time, voltage, current (A, positive on discharge)."""
    from scipy.io import loadmat

    ws = loadmat(path, squeeze_me=False)["__function_workspace__"].ravel()
    buf = memoryview(np.ascontiguousarray(ws))
    out: list[tuple[int, np.ndarray]] = []
    _walk(buf, 8, len(buf), 0, out)  # past the workspace's 8-byte header
    arrs = [a for d, a in out if d == 6]
    col = [arrs[i * N_TESTS : (i + 1) * N_TESTS] for i in range(8)]
    # step, cycle, step time, programme time, (zeros), voltage V, current mA (negative on discharge), capacity mAh
    t, V, I_mA = col[3], col[5], col[6]
    assert all(len(a) == len(b) == len(c) for a, b, c in zip(t, V, I_mA))
    assert all(2.3 < v.min() and v.max() < 4.3 for v in V), "column 5 is not the voltage"
    assert all(9000 < -i.min() < 11000 for i in I_mA), "column 6 is not the current in mA"
    assert all(np.all(np.diff(x) >= 0) for x in t), "column 3 is not the programme time"
    return {"t": t, "V": V, "I": [-i / 1000.0 for i in I_mA]}


def pulse_section(t: np.ndarray, V: np.ndarray, I: np.ndarray) -> slice:
    """From the end of the full charge before the first 2C pulse to an hour after the last."""
    big = np.flatnonzero(I > 9.0)
    first = big[0]
    charging = np.flatnonzero(I < -0.03)
    full = charging[charging < first][-1] + 1
    last = big[-1]
    end = int(np.searchsorted(t, t[last] + AFTER_S))
    return slice(full, end)


def main(path: str) -> None:
    cols = columns(Path(path))
    OUT.mkdir(parents=True, exist_ok=True)
    tests = []
    for k in FIRST_RPTS:
        t, V, I = cols["t"][k], cols["V"][k], cols["I"][k]
        s = pulse_section(t, V, I)
        tt = t[s] - t[s][0]
        name = f"rpt_{k:02d}"
        lines = ["t_s,current_A,voltage_V"] + [f"{a:.2f},{b:.4f},{c:.4f}" for a, b, c in zip(tt, I[s], V[s])]
        (OUT / f"{name}.csv.gz").write_bytes(gzip.compress(("\n".join(lines) + "\n").encode(), mtime=0))
        tests.append({"name": name, "place_in_file": k, "samples": len(tt), "duration_s": round(float(tt[-1]), 1)})
        print(name, len(tt), "samples,", round(tt[-1] / 3600, 2), "h")
    manifest = {
        "citation": CITATION,
        "licence": "CC BY 4.0",
        "cell": "LG INR21700-M50, fresh (each cell's first RPT), chamber 25 degC",
        "start": "rested after a C/3 CC-CV charge to full: state of charge 1",
        "tests": tests,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
