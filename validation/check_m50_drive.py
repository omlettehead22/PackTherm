"""The LG M50 on measured drive cycles (v0.6.9).

Three cells' 8 h of drive cycles with regen, CC-CV top-ups and rests
(validation/data/lg_m50_drive, prepared by prepare_m50_drive.py from the Warwick
data, CC BY 4.0), never fitted on. The circuit is run on the measured current
from full (the tester's own voltage limits are in the record, so the model's are
lifted) at the chamber's 25 degC: the cells rise only a few kelvin here. The
voltage error is reported while current flows, and at the end of each long rest
(where the circuit's only error is its open-circuit curve and state of charge).

The library M50 (its resistance scaled to the measured pulses) and the v0.6.8
derived circuit (M50-DERIVED) are compared.

Usage:  python validation/check_m50_drive.py      (--json PATH writes the results)
"""

from __future__ import annotations

import gzip
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

from packtherm.cells import CELLS
from packtherm.ecm import ECMState

DATA = Path(__file__).parent / "data" / "lg_m50_drive"
T_K = 298.15
CAPACITY_AH = 4.85  # the fresh cells' measured capacity is 4.7-4.9 Ah (C/10 to 2.5 V: 4.80-4.99)
REST_S = 600


def load(name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows = gzip.decompress((DATA / f"{name}.csv.gz").read_bytes()).decode().splitlines()[1:]
    a = np.array([[float(x) for x in r.split(",")] for r in rows])
    return a[:, 0], a[:, 1], a[:, 2]


def predict(key: str, t: np.ndarray, I: np.ndarray) -> np.ndarray:
    ecm = replace(CELLS[key].ecm, V_min=-1e9, V_max=1e9)
    st, soc = ECMState(), 1.0
    V = np.empty_like(I)
    V[0] = ecm.ocv(soc, T_K)
    for i in range(1, len(t)):
        dt = float(t[i] - t[i - 1])
        soc -= I[i] * dt / 3600.0 / CAPACITY_AH
        V[i] = st.apply(ecm, float(I[i]), soc, T_K, dt)[1]
    return V


def score(t: np.ndarray, I: np.ndarray, V: np.ndarray, Vm: np.ndarray) -> dict:
    e = 1e3 * (Vm - V)
    on = np.abs(I) > 0.05
    rest = np.abs(I) < 0.01
    ends = [i for i in np.flatnonzero(rest[:-1] & ~rest[1:]) if i > REST_S and rest[i - REST_S : i].all()]
    return {
        "rms_mV_under_current": float(np.sqrt(np.mean(e[on] ** 2))),
        "p95_mV_under_current": float(np.percentile(np.abs(e[on]), 95)),
        "bias_mV_under_current": float(np.mean(e[on])),
        "rest_end_errors_mV": [round(float(e[i]), 1) for i in ends],
    }


def main() -> dict:
    names = [m["name"] for m in json.loads((DATA / "manifest.json").read_text())["tests"]]
    out: dict = {}
    for key in ("M50", "M50-DERIVED"):
        out[key] = {}
        for n in names:
            t, I, V = load(n)
            out[key][n] = score(t, I, V, predict(key, t, I))
            r = out[key][n]
            print(
                f"{key:12s} {n}: {r['rms_mV_under_current']:.1f} mV RMS under current "
                f"(95 % within {r['p95_mV_under_current']:.0f}, mean {r['bias_mV_under_current']:+.1f}); "
                f"at the end of long rests {r['rest_end_errors_mV']} mV"
            )
    return out


if __name__ == "__main__":
    res = main()
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
