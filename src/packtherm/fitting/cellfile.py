"""The fitted cell file: what a fit found, and everything needed to judge it.

A YAML file with the model's values and, for each, where it came from and how
certain it is; where the model is valid; its errors on the tests it was fitted
to and on tests it never saw; what went in (each file's SHA-256, the dataset's
citation and licence); and the data-quality warnings from reading the tests.

Fitted at one temperature, the file says ``usable_in_studies: false`` and
studies refuse it: a cell whose temperature behaviour is borrowed would make
every thermal result look more certain than it is. Fitted at three
temperatures or more (v0.6.2), it holds the values by temperature and studies
use it, with the size, mass and thermal properties of the cell it names under
``like`` (a library cell or a cell file).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from pathlib import Path
from typing import Any

FORMAT = 1
STATUS_SINGLE = "single-temperature"
STATUS_MULTI = "multi-temperature"
MIN_TEMPERATURES = 3  # a law through two points is not checked by a third
ECM_FIELDS = (
    "R0_25C",
    "Ea_R0",
    "I0_25C",
    "Ea_I0",
    "gamma",
    "tau_ct",
    "Rm_25C",
    "tau_m",
    "Ea_Rm",
    "Rd_25C",
    "tau_d",
    "Ea_Rd",
    "soc_a",
    "soc_b",
    "Ea_soc",
    "V_max",
    "V_min",
    "cv_cutoff_A",
)


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


def _values(params) -> dict[str, dict]:
    values = {}
    for p in params:
        entry: dict[str, Any] = {"value": _r(p.value), "unit": p.unit, "source": p.source, "what": p.what}
        if p.ci95 is not None:
            entry["range_95"] = [_r(p.ci95[0], 4), _r(p.ci95[1], 4)]
        if p.note:
            entry["note"] = p.note
        values[p.name] = entry
    return values


def ecm_doc(ecm) -> dict:
    """What PackTherm runs, in full: every value of the circuit model and its table by temperature."""
    from ..ecm import BY_T_COLUMNS

    out = {k: (None if getattr(ecm, k) is None else _r(getattr(ecm, k), 6)) for k in ECM_FIELDS}
    if ecm.by_T:
        out["by_temperature"] = {
            "columns": list(BY_T_COLUMNS),
            "rows": [[_r(x, 6) for x in row] for row in sorted(ecm.by_T)],
        }
    return out


def ecm_from_doc(doc: dict):
    from ..ecm import BY_T_COLUMNS, ECM

    m = doc["model"]["ecm"]
    ocv = doc["open_circuit_voltage"]
    rows = ()
    if "by_temperature" in m:
        cols = m["by_temperature"]["columns"]
        if list(cols) != list(BY_T_COLUMNS):
            raise FittedCellError(f"model.ecm.by_temperature: columns {cols} are not {list(BY_T_COLUMNS)}")
        rows = tuple(tuple(float(x) for x in r) for r in m["by_temperature"]["rows"])
    return ECM(
        ocv_soc=tuple(float(x) for x in ocv["soc"]),
        ocv_V=tuple(float(x) for x in ocv["V"]),
        **{k: (None if m.get(k) is None else float(m[k])) for k in ECM_FIELDS},
        sources=("fitted by packtherm.fitting",),
        by_T=rows,
    )


def dc_resistance(ecm, T: float = 298.15, soc: float = 0.5, c_rate: float = 1.5, capacity_Ah: float = 1.0) -> float:
    """The 10 s DC resistance at mid charge, 25 degC and 1.5C: how PackTherm's cells state theirs."""
    from ..ecm import ECMState

    I = c_rate * capacity_Ah
    V = ECMState().step(ecm, I, soc, T, 10.0)[0]
    return (ecm.ocv(soc) - V) / I


def fitted_cell_doc(
    fit,
    name: str,
    paths: dict[str, list[str | Path]],
    rated_capacity_Ah: float | None = None,
    dataset: dict | None = None,
    when: _dt.datetime | None = None,
    like: str | None = None,
    thermal_checks: list[dict] | None = None,
) -> dict[str, Any]:
    """The cell file's contents. paths: role -> the files, as given to the fit (for their hashes).

    like: the cell whose size, mass and thermal properties go with these
    electrical values in a study (a library key or a cell file).
    thermal_checks: electro-thermal predictions of held-out tests (``thermal.thermal_checks``).
    """
    from .. import __version__

    when = when or _dt.datetime.now(_dt.timezone.utc)
    values = _values(fit.params)

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
    temps = list(fit.temperatures)
    multi = len(temps) >= 2
    usable = len(temps) >= MIN_TEMPERATURES and like is not None
    if usable:
        status, why = STATUS_MULTI, None
    elif not multi:
        status = STATUS_SINGLE
        why = (
            "fitted at one temperature: its temperature behaviour is the library NCR18650PF's, not this cell's. "
            f"Fit tests at {MIN_TEMPERATURES} temperatures or more to use it in studies."
        )
    else:
        status = STATUS_MULTI
        why = (
            f"fitted at {len(temps)} temperatures; studies need {MIN_TEMPERATURES} or more, so the temperature laws "
            "are checked by at least one temperature they were not drawn through"
            if len(temps) < MIN_TEMPERATURES
            else "no cell named under 'like' for its size, mass and thermal properties"
        )
    doc: dict[str, Any] = {
        "packtherm_fitted_cell": FORMAT,
        "name": name,
        "status": status,
        "usable_in_studies": usable,
    }
    if why:
        doc["why_not_usable"] = why
    if like is not None:
        doc["like"] = like
    doc.update(
        {
            "model": {
                "form": fit.model.form,
                "description": "open-circuit voltage, instant resistance R0, a charge-transfer branch "
                "(I0, gamma, tau_ct), a middle branch (Rm, tau_m), a slow branch (Rd, tau_d) and a rise near empty "
                "(soc_a, soc_b): packtherm.ecm.ECM"
                + (
                    "; values by temperature, interpolated between the fitted temperatures and carried beyond them "
                    "by the fitted laws"
                    if multi
                    else ""
                ),
                "ecm": ecm_doc(fit.ecm),
                "dc_resistance_mOhm": _r(1e3 * dc_resistance(fit.ecm, capacity_Ah=fit.capacity_Ah), 4),
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
                "held_out": [
                    {k: (round(v, 2) if isinstance(v, float) else v) for k, v in c.items()} for c in fit.checks
                ],
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
    )
    if multi:
        doc["by_temperature"] = [
            {
                "at_C": pt["at_C"],
                "cell_C": pt["cell_C"],
                "pulses": pt["pulses"],
                "tau_m_from": pt.get("tau_m_from", "pulses"),
                "values": _values(pt["params"]),
            }
            for pt in fit.per_temperature
        ]
        # The order a reader wants: the per-temperature values right after the summary values.
        keys = list(doc)
        keys.insert(keys.index("values") + 1, keys.pop(keys.index("by_temperature")))
        doc = {k: doc[k] for k in keys}
    if thermal_checks:
        doc["errors"]["held_out_electrothermal"] = [
            {k: v for k, v in c.items() if not k.startswith("_")} for c in thermal_checks
        ]
    return doc


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


def refusal(doc: dict, where: str = "cell.") -> str | None:
    """Why a study cannot use this fitted cell file (one line), or None if it can."""
    if doc.get("packtherm_fitted_cell") != FORMAT:
        return (
            f"{where.rstrip('.')}: fitted cell format {doc.get('packtherm_fitted_cell')!r} is not read by this version"
        )
    if doc.get("status") == STATUS_SINGLE:
        return (
            f"{where.rstrip('.')}: {doc.get('name', 'this cell')!r} was fitted at one temperature (single-temperature); "
            f"studies need its temperature behaviour too: fit tests at {MIN_TEMPERATURES} temperatures or more"
        )
    if not doc.get("usable_in_studies", False):
        return f"{where.rstrip('.')}: {doc.get('name', 'this cell')!r}: {doc.get('why_not_usable', 'not usable in studies')}"
    return None


def cell_from_doc(doc: dict, base: str | Path | None = None):
    """The Cell a study runs: these electrical values with the size, mass and thermal properties of ``like``."""
    from dataclasses import replace

    from ..cells import get_cell

    like_key = str(doc["like"])
    if like_key.lower().endswith((".yaml", ".yml", ".json")) and base is not None and not Path(like_key).is_absolute():
        like_key = str(Path(base) / like_key)
    like = get_cell(like_key)
    ecm = ecm_from_doc(doc)
    cap = float(doc["capacity"]["measured_Ah"])
    r0 = dc_resistance(ecm, capacity_Ah=cap)
    v = doc.get("valid_for") or {}
    return replace(
        like,
        name=str(doc["name"]),
        capacity_Ah=cap,
        R0_25C=r0,
        R0_range=(0.9 * r0, 1.1 * r0),
        ecm=ecm,
        model_label="circuit (fitted)",
        user_defined=True,
        sources=("fitted by packtherm fit", *like.sources),
        validity={
            "temperature_C": v.get("temperature_C"),
            "discharge_C": v.get("discharge_C"),
            "charge_C": v.get("charge_C"),
        },
    )
