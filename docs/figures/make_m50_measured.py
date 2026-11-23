"""Draw docs/validation/m50_measured.png: the LG M50 against measured data (v0.6.9).

One of the Warwick 1C discharges with a core thermocouple (VP011, cycle 2, never
fitted on), predicted from its current alone by the library M50 (resistance
scaled to the measured pulses) and by the v0.6.8 derived circuit: the voltage,
and the surface and core temperatures. The chamber's h is check_m50_core.py's.
Run: python docs/figures/make_m50_measured.py
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import matplotlib.pyplot as plt

from packtherm.cells import CELLS

TEXT, TEXT_2, GRID = "#0b0b0b", "#52514e", "#e1e0d9"
MEAS, LIB, OLD = "#0b0b0b", "#2a78d6", "#eb6834"
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9.5,
        "text.color": TEXT,
        "axes.labelcolor": TEXT_2,
        "xtick.color": TEXT_2,
        "ytick.color": TEXT_2,
        "axes.edgecolor": GRID,
    }
)
ROOT = Path(__file__).resolve().parents[2]
TEST = "VP011_cycle2"


def main() -> None:
    spec = importlib.util.spec_from_file_location("check_m50_core", ROOT / "validation" / "check_m50_core.py")
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    res = json.loads((ROOT / "validation" / "m50_core_check.json").read_text())
    h = res["library (1.2 W/(m K)), predicted"]["h_W_m2K"]
    test = core.load(TEST)
    rec = test["rec"]
    t = (rec.t - rec.t[0]) / 60.0
    lib = core.run(test, CELLS["M50"], h, "predicted")
    old = core.run(test, CELLS["M50-DERIVED"], h, "predicted")
    on = rec.current_A > 0.5

    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 3.8), constrained_layout=True)
    a.plot(t[on], rec.voltage_V[on], color=MEAS, lw=2, label="measured")
    a.plot(t[on], lib["V"][on], color=LIB, lw=2, label="library M50 (v0.6.9)")
    a.plot(t[on], old["V"][on], color=OLD, lw=2, ls="--", label="derived circuit (v0.6.8)")
    a.set(xlabel="time (min)", ylabel="voltage (V)", title="1C discharge: voltage")
    b.plot(t, test["core"], color=MEAS, lw=2, label="measured core")
    b.plot(t, rec.temperature_C, color=MEAS, lw=1.2, ls=":", label="measured surface")
    b.plot(t, lib["core"], color=LIB, lw=2, label="library core")
    b.plot(t, lib["surface"], color=LIB, lw=1.2, ls=":", label="library surface")
    b.plot(t, old["core"], color=OLD, lw=2, ls="--", label="v0.6.8 core")
    b.set(xlabel="time (min)", ylabel="temperature (°C)", title="Core and surface, from the current alone")
    for ax in (a, b):
        ax.grid(color=GRID, lw=0.8)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, fontsize=8.5)
    fig.suptitle(f"LG M50 against the Warwick data ({TEST.replace('_cycle', ', cycle ')}; never fitted on)", fontsize=10.5)
    out = ROOT / "docs" / "validation" / "m50_measured.png"
    fig.savefig(out, dpi=150)
    print("wrote", out)


if __name__ == "__main__":
    main()
