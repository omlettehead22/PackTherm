"""The fitted cell file: what a fit found, and everything needed to judge it.

A YAML file with the model's values and, for each, where it came from and how
certain it is; where the model is valid; its errors on the tests it was fitted
to and on tests it never saw; what went in (each file's SHA-256, the dataset's
citation and licence); and the data-quality warnings from reading the tests.

v0.6.1 fits one temperature, so the file says ``usable_in_studies: false`` and
studies refuse it: a cell whose temperature behaviour is borrowed would make
every thermal result look more certain than it is. v0.6.2 fits that behaviour
from tests at several temperatures, and those files are usable.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from pathlib import Path
from typing import Any

FORMAT = 1
STATUS_SINGLE = "single-temperature"


class FittedCellError(ValueError):
    pass


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _r(x: float, sig: int = 5) -> float:
    return float(f"{x:.{sig}g}")


def fitted_cell_doc(
    fit,
    name: str,
    paths: dict[str, list[str | Path]],
    rated_capacity_Ah: float | None = None,
    dataset: dict | None = None,
    when: _dt.datetime | None = None,
) -> dict[str, Any]:
    """The cell file's contents. paths: role -> the files, as given to the fit (for their hashes)."""
    from .. import __version__

    when = when or _dt.datetime.now(_dt.timezone.utc)
    values = {}
    for p in fit.params:
        entry: dict[str, Any] = {"value": _r(p.value), "unit": p.unit, "source": p.source, "what": p.what}
        if p.ci95 is not None:
            entry["range_95"] = [_r(p.ci95[0], 4), _r(p.ci95[1], 4)]
        if p.note:
            entry["note"] = p.note
        values[p.name] = entry

    cap = {"measured_Ah": _r(fit.capacity_Ah), "how": fit.ocv.method}
    if rated_capacity_Ah:
        cap["rated_Ah"] = rated_capacity_Ah
        cap["measured_vs_rated"] = f"{100 * (fit.capacity_Ah / rated_capacity_Ah - 1):+.1f}%"

    inputs = []
    for role, files in paths.items():
        recs = fit.records.get(role, [])
        for i, f in enumerate(files):
            rec = recs[i] if i < len(recs) else None
            item = {"role": role, "file": Path(f).name, "sha256": sha256(f)}
            if rec is not None:
                item["samples"] = len(rec)
                item["duration_h"] = _r(rec.duration_s / 3600, 4)
                if rec.conversions:
                    item["conversions"] = list(rec.conversions)
            inputs.append(item)

    warnings = [n for n in fit.notes]
    return {
        "packtherm_fitted_cell": FORMAT,
        "name": name,
        "status": STATUS_SINGLE,
        "usable_in_studies": False,
        "why_not_usable": (
            "fitted at one temperature: its temperature behaviour is the library NCR18650PF's, not this cell's. "
            "PackTherm v0.6.2 fits that from tests at several temperatures."
        ),
        "model": {
            "form": fit.model.form,
            "description": "open-circuit voltage, instant resistance R0, a charge-transfer branch "
            "(I0, gamma, tau_ct), a slow branch (Rd, tau_d) and a rise near empty (soc_a, soc_b): "
            "packtherm.ecm.ECM",
        },
        "values": values,
        "capacity": cap,
        "open_circuit_voltage": {
            "soc": [_r(x, 4) for x in fit.ocv.soc],
            "V": [_r(x, 5) for x in fit.ocv.V],
            "how": fit.ocv.method,
        },
        "valid_for": fit.validity,
        "identifiability": {
            "correlated_pairs": [
                {
                    "values": [a, b],
                    "correlation": round(c, 3),
                    "meaning": "these trade off: the tests pin a combination",
                }
                for a, b, c in fit.correlated
            ],
            "about_the_ranges": fit.settings.get("uncertainty", ""),
        },
        "errors": {
            "fitted_on": {
                k: {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()}
                for k, v in fit.errors.items()
            },
            "held_out": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in c.items()} for c in fit.checks],
        },
        "state_of_charge_anchors": fit.soc_anchors,
        "data_warnings": warnings,
        "provenance": {
            "packtherm": __version__,
            "fitted_at": when.replace(microsecond=0).isoformat(),
            "settings": fit.settings,
            "inputs": inputs,
            **({"dataset": dataset} if dataset else {}),
        },
    }


def _plain(x):
    """numpy numbers and arrays as plain Python, for YAML."""
    import numpy as np

    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if isinstance(x, np.ndarray):
        return [_plain(v) for v in x.tolist()]
    if isinstance(x, np.generic):
        return x.item()
    return x


def write_fitted_cell(path: str | Path, doc: dict) -> Path:
    import yaml

    doc = _plain(doc)
    path = Path(path)
    header = (
        "# A PackTherm fitted cell (packtherm fit). Fitted at one temperature: studies refuse it until\n"
        "# PackTherm v0.6.2, which fits the temperature behaviour. See the report beside it.\n"
    )
    path.write_text(header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    return path


def read_fitted_cell(path: str | Path) -> dict:
    import yaml

    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or "packtherm_fitted_cell" not in doc:
        raise FittedCellError(f"{path}: not a PackTherm fitted cell file")
    if doc["packtherm_fitted_cell"] != FORMAT:
        raise FittedCellError(
            f"{path}: fitted cell format {doc['packtherm_fitted_cell']!r}; this version reads {FORMAT}"
        )
    return doc


def refusal(doc: dict, where: str = "cell.") -> str:
    """Why a study cannot use this fitted cell file (one line)."""
    status = doc.get("status", "?")
    if status == STATUS_SINGLE or not doc.get("usable_in_studies", False):
        return (
            f"{where.rstrip('.')}: {doc.get('name', 'this cell')!r} was fitted at one temperature ({status}); "
            "studies need its temperature behaviour too, which PackTherm fits from v0.6.2"
        )
    return f"{where.rstrip('.')}: fitted cell format {doc.get('packtherm_fitted_cell')!r} is not read by this version"
