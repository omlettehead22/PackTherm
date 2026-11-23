"""The LG M50's resistance from measured pulses (v0.6.9).

The library's M50 circuit was derived from a physics model (v0.4.11,
derive_m50_ecm.py). Here it is set against the 2C (10 A, 30 s) pulses of six
fresh M50 cells at 25 degC (validation/data/lg_m50_rpt, prepared by
prepare_m50_rpt.py from the Warwick dataset, CC BY 4.0).

For each pulse the voltage drop from the rested voltage just before it is read at
0.1, 1, 10 and 29 s, and the derived circuit is run through the same pulse from
rest at the same state of charge (from the charge counted from full). One scale
on every loss term (ECM.scaled) is fitted, by least squares, on the 10 A pulses
at 30 % state of charge and above. The pulses at about 20 % and the 2.5 A
pulses are checks: the fit never sees them.

Usage:  python validation/fit_m50_scale.py        (prints the scale and the errors; --json writes them)
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import numpy as np

from packtherm.cells import LG_M50_ECM_DERIVED, M50_R_SCALE
from packtherm.ecm import ECM, ECMState

DATA = Path(__file__).parent / "data" / "lg_m50_rpt"
T_K = 298.15
TIMES = (0.1, 1.0, 10.0, 29.0)
CAPACITY_AH = 4.85  # the fresh cells' C/10-to-2.5 V capacity is 4.80-4.99 Ah; this only places the pulses
FIT_ABOVE_SOC = 0.3


def load(name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows = gzip.decompress((DATA / f"{name}.csv.gz").read_bytes()).decode().splitlines()[1:]
    a = np.array([[float(x) for x in r.split(",")] for r in rows])
    return a[:, 0], a[:, 1], a[:, 2]


def pulses(t: np.ndarray, I: np.ndarray, V: np.ndarray) -> list[dict]:
    """Every discharge pulse: its current, state of charge and measured drops at TIMES."""
    ah = np.concatenate([[0.0], np.cumsum(0.5 * (I[1:] + I[:-1]) * np.diff(t))]) / 3600.0
    on = I > 2.0
    starts = np.flatnonzero(on[1:] & ~on[:-1]) + 1
    out = []
    for s in starts:
        end = s + int(np.argmax(~on[s:]))
        if not 25.0 <= t[end] - t[s] <= 35.0:
            continue  # the C/3 steps between pulses are longer
        V0 = V[s - 1]
        drops = [V0 - V[min(int(np.searchsorted(t, t[s] + x)), end - 1)] for x in TIMES]
        out.append({"I": round(float(np.median(I[s:end])), 1), "soc": 1.0 - ah[s] / CAPACITY_AH, "drops_V": drops})
    return out


def model_drops(ecm: ECM, I: float, soc: float, dt: float = 0.05) -> list[float]:
    st, t, V0, out = ECMState(), 0.0, ecm.ocv(soc, T_K), []
    for x in TIMES:
        while t < x - 1e-9:
            V = st.apply(ecm, I, soc, T_K, dt)[1]
            t += dt
        out.append(V0 - V)
    return out


def main() -> dict:
    names = [m["name"] for m in json.loads((DATA / "manifest.json").read_text())["tests"]]
    rows = []
    for n in names:
        for p in pulses(*load(n)):
            p["model_V"] = model_drops(LG_M50_ECM_DERIVED, p["I"], p["soc"])
            rows.append(p | {"test": n})
    fit = [r for r in rows if r["I"] > 9 and r["soc"] >= FIT_ABOVE_SOC]
    m = np.array([r["drops_V"] for r in fit])
    b = np.array([r["model_V"] for r in fit])
    f = float((m * b).sum() / (b * b).sum())

    def err(sel: list[dict], ecm: ECM) -> float:
        meas = np.array([r["drops_V"] for r in sel])
        mod = np.array([model_drops(ecm, r["I"], r["soc"]) for r in sel])
        return float(1e3 * np.sqrt(np.mean((meas - mod) ** 2)))

    scaled = LG_M50_ECM_DERIVED.scaled(M50_R_SCALE)
    groups = {
        "fitted: 10 A, 30 % and above": fit,
        "check: 10 A, about 20 %": [r for r in rows if r["I"] > 9 and r["soc"] < FIT_ABOVE_SOC],
        "check: 2.5 A, all": [r for r in rows if r["I"] < 9],
    }
    res = {"scale_fitted": f, "scale_used": M50_R_SCALE, "pulses": len(rows), "groups": {}}
    print(f"scale fitted {f:.3f} (library uses {M50_R_SCALE}); {len(rows)} pulses in {len(names)} cells")
    for g, sel in groups.items():
        before, after = err(sel, LG_M50_ECM_DERIVED), err(sel, scaled)
        ratio = float(np.mean([np.mean(np.divide(r["drops_V"], r["model_V"])) for r in sel]))
        res["groups"][g] = {"n": len(sel), "rms_mV_derived": before, "rms_mV_scaled": after, "measured_over_derived": ratio}
        print(f"  {g:32s} n={len(sel):2d}  RMS {before:6.1f} mV derived, {after:5.1f} mV scaled  (measured/derived {ratio:.2f})")
    return res


if __name__ == "__main__":
    out = main()
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
