"""Write the files the web app shares with the Python package.

    python web/scripts/export_contract.py

src/generated/schema.json   the study format (packtherm.study.schema()), which
                            the setup form is built from
src/generated/presets.json  the example studies in docs/examples, offered as presets
src/generated/cells.json    the example cell files in docs/examples, offered as
                            starting points for your own cell

tests/test_web.py fails if these are out of date, so the app cannot drift from
the study format.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "src" / "generated"
PRESETS = [  # (file, label), in the order the app shows them
    ("m50_roadtrip_35c.yaml", "Hot motorway road trip"),
    ("m50_discharge_1.5c_25c.yaml", "1.5C discharge"),
    ("m50_wltc3_35c.yaml", "WLTC city driving"),
]
CELLS = [
    ("user_cell_mj1.yaml", "LG MJ1 (NMC 18650)"),
    ("user_cell_lfp_26650.yaml", "ANR26650M1-B (LFP 26650)"),
]


def contract() -> dict[str, str]:
    """File name -> its text."""
    import yaml

    from packtherm.study import schema

    presets = []
    for name, label in PRESETS:
        doc = yaml.safe_load((ROOT / "docs" / "examples" / name).read_text(encoding="utf-8"))
        presets.append({"label": label, "file": name, "study": doc})
    cells = []
    for name, label in CELLS:
        doc = yaml.safe_load((ROOT / "docs" / "examples" / name).read_text(encoding="utf-8"))
        cells.append({"label": label, "file": name, "cell": doc})
    dump = lambda d: json.dumps(d, indent=1, ensure_ascii=False) + "\n"  # noqa: E731
    return {"schema.json": dump(schema()), "presets.json": dump(presets), "cells.json": dump(cells)}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in contract().items():
        (OUT / name).write_text(text, encoding="utf-8")
        print(f"wrote {OUT / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
