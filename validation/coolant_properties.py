"""Write src/packtherm/data/meg50_properties.csv: 50/50 ethylene glycol-water properties (v0.6.12).

CoolProp (MIT licence, coolprop.org) is used here only, to tabulate its incompressible
"MEG[0.5]" fluid (Melinder 2010: 50 % ethylene glycol by mass) from -30 to 100 degC at 2 bar;
PackTherm reads the table and does not need CoolProp.

Usage:  pip install CoolProp && python validation/coolant_properties.py
"""

from pathlib import Path

import CoolProp.CoolProp as CP

OUT = Path(__file__).resolve().parents[1] / "src" / "packtherm" / "data" / "meg50_properties.csv"


def main() -> None:
    version = CP.get_global_param_string("version")
    rows = [
        f"# 50/50 (by mass) ethylene glycol-water: CoolProp {version}, INCOMP::MEG[0.5] (Melinder 2010), 2 bar.",
        "# Written by validation/coolant_properties.py (v0.6.12). Columns: T_C, rho_kg_m3, cp_J_kgK, k_W_mK, mu_Pa_s",
        "T_C,rho_kg_m3,cp_J_kgK,k_W_mK,mu_Pa_s",
    ]
    for T in range(-30, 101, 5):
        v = [CP.PropsSI(p, "T", T + 273.15, "P", 2e5, "INCOMP::MEG[0.5]") for p in ("D", "C", "L", "V")]
        rows.append(f"{T},{v[0]:.2f},{v[1]:.1f},{v[2]:.4f},{v[3]:.6g}")
    OUT.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
