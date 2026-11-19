"""Build the processed test set for the Samsung INR21700-30T from its public dataset.

Usage:
    python validation/prepare_samsung_30t.py "/path/to/Samsung INR21700 30T 3Ah Li-ion Battery Data"

Source: P. Kollmeyer and M. Skells, "Samsung INR21700 30T 3Ah Li-ion Battery
Data", Mendeley Data v2 (2023), doi:10.17632/9xyvy2njj3.2, licensed CC BY 4.0.
The tests were performed at McMaster University by Dr. Phillip Kollmeyer. The
raw dataset (~460 MB) is not stored here. This script copies the pulse tests
and the 25 degC C/20 test unchanged to tests/data/samsung_30t/, and writes the
discharges and drive cycles, resampled to 1 s bin means, as gzipped CSVs with a
manifest to validation/data/samsung_30t/.

Selection, at each of 40, 25, 10, 0, -10 and -20 degC
-----------------------------------------------------
* role "fit" (fitted to): the first 1C discharge and drive cycle Mixed1.
* The constant-current files hold sequences (the 2C file at 10 to 40 degC
  starts with a 1C discharge and a charge, and some end in rests of days):
  each is cut to its named discharge, from 60 s before it to 30 min after.
* role "validation" (never fitted to): the second 1C discharge, the 0.5C and
  2C discharges, UDDS, HWFET, LA92, US06, and Mixed2 to Mixed8.

Each test follows a full charge (the dataset's README: 1C to 4.2 V, 10 mA cut
off, at a cell temperature of 25 degC) and a soak while the cell settles to the
chamber, trimmed here to 60 s before the first current.

Ambient. The dataset has no chamber channel, and the chambers ran off their
setpoints (the 25 degC one at about 24 degC; at -10 degC from -13 to -9 degC).
A cell settled after 15 minutes or more at rest is at the chamber's temperature,
so the ambient is the cell temperature over the last minute of the rest before
each test (in its own file, or at the end of the file before it). Every test
here has one; one without would fall back to the setpoint, noted in the manifest.

Start. The 0.5C and 2C files (and some drive cycles' files) begin with the
discharge already running: logging started after it. The tester's charge
counter (``Ah``) holds what moved before the first sample; where it is negative
(discharged) the start is 1 - that / the C/20 capacity. Where it is positive
(three 0.5C files, the counter not reset from the step before), the time
between the files at the logged current is used instead (the file names' start
minute: about 1%). The manifest records which.

End. The rest logged after a test can hold the chamber's ramp to 25 degC for
the next charge: it is cut where the cell starts moving away from the ambient.

Time. Some files log a block twice (the time steps back by up to 35 min, then
repeats): only samples later than every one before are kept.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import re
import shutil
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import scipy.io as sio

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "validation" / "data" / "samsung_30t"
RAW = REPO / "tests" / "data" / "samsung_30t"
SETPOINTS = (40, 25, 10, 0, -10, -20)
CITATION = (
    "P. Kollmeyer and M. Skells, Samsung INR21700 30T 3Ah Li-ion Battery Data, Mendeley Data v2 (2023), "
    "doi:10.17632/9xyvy2njj3.2"
)


def load(path: Path) -> dict[str, np.ndarray]:
    m = sio.loadmat(str(path), squeeze_me=True, struct_as_record=False)["meas"]
    keys = ("Time", "Voltage", "Current", "Ah", "Battery_Temp_degC")
    d = {k: np.atleast_1d(getattr(m, k)).astype(float) for k in keys}
    ok = np.all([np.isfinite(v) for v in d.values()], axis=0)
    d = {k: v[ok] for k, v in d.items()}
    t = d["Time"]
    keep = np.concatenate([[True], t[1:] > np.maximum.accumulate(t)[:-1]])  # a repeated block is dropped
    return {k: v[keep] for k, v in d.items()}


def started(path: Path) -> dt.datetime:
    # The lab's local time; only differences between files are used.
    return dt.datetime.strptime(path.name[:14], "%m-%d-%y_%H.%M").replace(tzinfo=dt.UTC)


# At rest this long the cell is at the chamber's temperature: about 1.5 of its time constants (about
# 7 min) after a charge in the same chamber (the 25 degC tests, within 1-2 K), and the colder
# chambers' soaks run 28 min or more.
SETTLED_S = 600.0


def rest_before(t: np.ndarray, current: np.ndarray, i: int) -> float:
    """How long the cell was at rest before sample i (and any lead-in of up to 2 min before it)."""
    j = i
    while j > 0 and abs(current[j - 1]) >= 0.05 and t[i] - t[j - 1] <= 120.0:
        j -= 1
    k = j
    while k > 0 and abs(current[k - 1]) < 0.05:
        k -= 1
    return float(t[j] - t[k])


def last_minute_T(t: np.ndarray, T: np.ndarray, i: int) -> float:
    m = (t >= t[i] - 60.0) & (t <= t[i])
    return float(np.median(T[m]))


def c20_capacity(path: Path) -> float:
    d = load(path)
    return float(-np.min(d["Ah"]))


def bin_means(t: np.ndarray, y: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Exact means of the piecewise-linear signal y(t) over [edges[i], edges[i+1]]."""
    cum = np.concatenate([[0.0], np.cumsum(0.5 * (y[1:] + y[:-1]) * np.diff(t))])
    c = np.interp(edges, t, cum)
    return np.diff(c) / np.diff(edges)


def trim_soak(d: dict, lead_s: float = 60.0) -> dict:
    """Drop a pre-test soak: start ``lead_s`` before the first current if that is > 10 min in."""
    active = np.flatnonzero(np.abs(d["Current"]) > 0.05)
    if active.size and d["Time"][active[0]] - d["Time"][0] > 600.0:
        start = np.searchsorted(d["Time"], d["Time"][active[0]] - lead_s)
        d = {k: v[start:] for k, v in d.items()}
    return d


def cut_discharge(r: dict, current_A: float, lead_s: float = 60.0, tail_s: float = 1800.0) -> dict:
    """The discharge at this current alone: from ``lead_s`` before it to ``tail_s`` into the rest after it.

    The constant-current files hold sequences (a 1C discharge, a charge, then
    the 2C discharge, then rests of up to days): the test is the named step.
    """
    on = r["current_A"] > 0.8 * current_A
    edges = np.flatnonzero(np.diff(np.concatenate([[0], on.astype(int), [0]])))
    runs = [(a, b) for a, b in zip(edges[::2], edges[1::2]) if b - a >= 60]
    if not runs:
        raise ValueError(f"no discharge at {current_A} A")
    a, b = runs[0]
    t = r["t"]
    stop = min(b + 1, t.size)  # the bin the step ends in holds part of it
    while stop < t.size and abs(r["current_A"][stop]) < 0.05 and t[stop] - t[b] < tail_s:
        stop += 1
    i0 = int(np.searchsorted(t, t[a] - lead_s))
    out = {k: v[i0:stop] for k, v in r.items()}
    out["t"] = out["t"] - out["t"][0]
    return out, a


def start_state(path, raw, r, a, prev, setpoint, cap) -> dict:
    """The test's ambient and starting charge: see the module's notes."""
    t, I, T = r["t"], r["current_A"], r["T_cell_C"]
    out = {}
    rest = rest_before(t, I, a)
    running_at_start = a == 0 and abs(I[0]) > 0.5  # a drive cycle's file starts at rest or a trickle
    if rest >= SETTLED_S:
        j = a
        while j > 0 and abs(I[j - 1]) >= 0.05 and t[a] - t[j - 1] <= 120.0:
            j -= 1
        out["ambient_C"] = round(last_minute_T(t, T, j), 2)
        out["ambient_from"] = "cell temperature after a settled rest in the file"
    elif a <= 120 and prev is not None:
        pr = resample(load(prev))
        end = pr["t"].size - 1
        gap = (started(path) - started(prev)).total_seconds() - pr["t"][-1]
        if rest + max(gap, 0.0) + rest_before(pr["t"], pr["current_A"], end) >= SETTLED_S:
            out["ambient_C"] = round(last_minute_T(pr["t"], pr["T_cell_C"], end), 2)
            out["ambient_from"] = "cell temperature after a settled rest at the end of the file before"
    if "ambient_C" not in out:
        out["ambient_C"] = float(setpoint)
        out["ambient_from"] = "setpoint: no settled rest before the test"
    soc0 = 1.0
    out["soc0_from"] = "full: charged to 4.2 V before it"
    if running_at_start:
        ah0 = float(raw["Ah"][0])
        if abs(ah0) < 1e-4:
            pass  # the counter starts at zero with the first sample: logging began with the step
        elif ah0 < 0.0:
            soc0 = 1.0 + ah0 / cap
            out["soc0_from"] = f"full less the tester's counter before the first sample ({-ah0:.3f} Ah)"
        else:
            gap = (started(path) - started(prev)).total_seconds() - float(resample(load(prev))["t"][-1])
            moved = max(gap, 0.0) * float(I[0]) / 3600.0
            soc0 = 1.0 - moved / cap
            out["soc0_from"] = f"full less {moved:.3f} Ah: {gap / 60:.1f} min between the files at {I[0]:.2f} A"
    out["soc0"] = round(soc0, 4)
    return out


def cut_tail(r: dict, ambient_C: float, margin_K: float = 0.5) -> tuple[dict, float]:
    """End the rest after a test where the cell starts moving away from the chamber's temperature again.

    After a test the chamber is taken to 25 degC for the next charge, and the
    rest logged after a cold test can hold that ramp (at -20 degC, 40 K of it).
    Cut where the cell's distance from the ambient grows by margin_K past its
    smallest since its peak after the last current.
    """
    I, T = r["current_A"], r["T_cell_C"]
    on = np.flatnonzero(np.abs(I) > 0.05)
    if not on.size:
        return r, 0.0
    e = int(on[-1])
    # The case keeps warming for a minute or two after the current stops: start from its peak.
    first = np.abs(T[e : e + 300] - ambient_C)
    e += int(np.argmax(first))
    dist = np.abs(T[e:] - ambient_C)
    grows = np.flatnonzero(dist > np.minimum.accumulate(dist) + margin_K)
    if not grows.size:
        return r, 0.0
    stop = e + int(grows[0])
    cut = float(r["t"][-1] - r["t"][stop - 1])
    return {k: v[:stop] for k, v in r.items()}, cut


def resample(d: dict, dt: float = 1.0) -> dict[str, np.ndarray]:
    t = d["Time"] - d["Time"][0]
    edges = np.arange(0.0, t[-1] + 1e-9, dt)
    mids = 0.5 * (edges[1:] + edges[:-1])
    return {
        "t": edges[:-1],
        "current_A": -bin_means(t, d["Current"], edges),  # dataset: discharge < 0; packtherm: discharge > 0
        "voltage_V": bin_means(t, d["Voltage"], edges),
        "T_cell_C": np.interp(mids, t, d["Battery_Temp_degC"]),
    }


def write(name: str, r: dict, meta: dict, manifest: list) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.csv.gz"
    with gzip.open(path, "wt", compresslevel=9) as f:
        f.write("t_s,current_A,voltage_V,T_cell_C\n")
        for row in zip(r["t"], r["current_A"], r["voltage_V"], r["T_cell_C"]):
            f.write(f"{row[0]:.0f},{row[1]:.4f},{row[2]:.4f},{row[3]:.2f}\n")
    manifest.append({"name": name, "file": path.name, **meta})
    print(
        f"{name:<24} {r['t'][-1] / 60:6.1f} min  {meta['role']:<10} T0 {r['T_cell_C'][0]:6.2f}  "
        f"ambient {meta['ambient_C']:6.2f}  soc0 {meta['soc0']:.4f}"
    )


def main(root: str) -> None:
    root = Path(root)
    manifest: list[dict] = []
    RAW.mkdir(parents=True, exist_ok=True)
    c20 = next((root / "25degC").glob("*_C20DisCh_*.mat"))
    cap = c20_capacity(c20)
    print(f"C/20 capacity at 25 degC: {cap:.4f} Ah")
    for setpoint in SETPOINTS:
        folder = root / f"{setpoint}degC"
        files = sorted(folder.glob("*.mat"), key=started)
        before = {}  # each file: the one logged before it (its rest at the end, and when it ended)
        for prev, p in pairwise(files):
            before[p] = prev
        hppc = next(p for p in files if "_HPPC_" in p.name)
        shutil.copy2(hppc, RAW / hppc.name)
        if setpoint == 25:
            c20 = next(p for p in files if "_C20DisCh_" in p.name)
            shutil.copy2(c20, RAW / c20.name)
        caps = [p for p in files if "_Cap_1C_" in p.name]
        tests = []
        for i, p in enumerate(caps):
            tests.append((p, f"1C_discharge_{i + 1}", "cc_discharge", "fit" if i == 0 else "validation"))
        for tag, name in (("Dis_0p5C", "0p5C_discharge"), ("Dis_2C", "2C_discharge")):
            tests += [(p, name, "cc_discharge", "validation") for p in files if f"_{tag}_" in p.name]
        rates = {"1C_discharge_1": 3.0, "1C_discharge_2": 3.0, "0p5C_discharge": 1.5, "2C_discharge": 6.0}
        for p in files:
            m = re.search(r"_(UDDS|HWFET|LA92|US06|Mixed\d)_", p.name)
            if m:
                cycle = m.group(1)
                tests.append((p, cycle, "drive_cycle", "fit" if cycle == "Mixed1" else "validation"))
        for path, label, kind, role in tests:
            raw = load(path)
            name = f"{setpoint}C_{label}".replace("-", "m")
            r = resample(raw)
            a = int(np.argmax(np.abs(r["current_A"]) > 0.05))
            if kind == "cc_discharge":
                r_cut, a = cut_discharge(r, 0.9 * rates[label])
            meta = {"setpoint_C": setpoint, "role": role, "kind": kind, "source": path.name}
            meta.update(start_state(path, raw, r, a, before.get(path), setpoint, cap))
            if kind == "cc_discharge":
                r = r_cut
            else:
                r = resample(trim_soak(raw))
            r, cut = cut_tail(r, meta["ambient_C"])
            if cut:
                meta["tail_cut_s"] = round(cut)
            write(name, r, meta, manifest)

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    licence = (
        f"Processed from {CITATION}, licensed **CC BY 4.0**. The tests were performed at McMaster University "
        "by Dr. Phillip Kollmeyer.\n\n"
    )
    (OUT / "README.md").write_text(
        "# Samsung INR21700-30T test set\n\n"
        + licence
        + "Changes from the original: tests selected (role `fit`: fitted to; `validation`: never fitted to), "
        "non-finite and duplicate-time samples removed, a cooling soak before each test trimmed to 60 s, "
        "resampled to exact 1 s bin means (current sign flipped so discharge is positive), battery case "
        "temperature interpolated at bin centres, samples of a block logged twice dropped. The dataset has no "
        "chamber channel: the ambient is the cell temperature at the end of the settled rest before each test, "
        "and a test whose file starts with the discharge running starts below full by the charge the tester "
        "counted before it (see `ambient_from` and `soc0_from` in the manifest); the rest after a test is cut "
        "where the chamber's ramp for the next charge begins (`tail_cut_s`). "
        "Generated by `validation/prepare_samsung_30t.py`.\n"
    )
    (RAW / "README.md").write_text(
        "# Samsung INR21700-30T test files\n\n"
        + licence
        + "Unchanged copies of the pulse (HPPC) test at each of 40, 25, 10, 0, -10 and -20 degC, and the C/20 "
        "discharge and charge at 25 degC: what `packtherm fit` fits the 30T on, with the drive cycles and "
        "discharges in `validation/data/samsung_30t/`. Copied by `validation/prepare_samsung_30t.py`.\n"
    )
    print(f"{len(manifest)} tests written to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
