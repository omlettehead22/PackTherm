"""Cells from BPX files (v0.6.16).

BPX (Battery Parameter eXchange, https://github.com/FaradayInstitution/BPX) is an
open format for the parameters of physics-based cell models (DFN, SPM). From one,
PackTherm takes what its own models use directly:

* capacity and voltage limits;
* density and specific heat (so mass and heat capacity) and, where the file gives
  one, the lumped thermal conductivity (BPX 1.x has no field for it: PackTherm reads
  it from the "User-defined" block or a 0.x file, else uses the chemistry's value);
* the size, from the volume and external surface area, as a cylinder (only files
  that say they describe a cylindrical cell, or given a diameter and height);
* the open-circuit voltage and reversible heat by state of charge, from each
  electrode's OCP and entropic coefficient between its stoichiometry limits.

It has no resistance a circuit model could use. ``packtherm.bpx_fit`` derives
one by running the file's DFN in PyBaMM through pulse tests; without it, give a
DC resistance and the cell uses the lumped model.

Reading needs the ``bpx`` package: ``pip install "packtherm[bpx]"``.
"""

from __future__ import annotations

import json
import math
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

INSTALL_HINT = "Reading BPX files needs the bpx package, an optional extra: pip install 'packtherm[bpx]'"
SOC_GRID = tuple(round(x, 4) for x in np.linspace(0.0, 1.0, 51))
CONDUCTIVITY_KEY = "Thermal conductivity [W.m-1.K-1]"


class BPXError(ValueError):
    """A BPX file PackTherm cannot turn into a cell; the message says why."""


@dataclass(frozen=True)
class BPXCell:
    """What a BPX file gives PackTherm, in PackTherm's units."""

    path: str
    title: str
    model: str  # the file's model: DFN, SPMe, SPM
    chemistry: str  # NMC, NCA or LFP
    capacity_Ah: float
    V_min: float
    V_max: float
    V_nominal: float  # mean open-circuit voltage over the state of charge
    diameter_mm: float
    height_mm: float
    mass_g: float
    cp_J_kgK: float
    k_W_mK: float | None  # lumped thermal conductivity, if the file gives one
    soc: tuple[float, ...]
    ocv_V: tuple[float, ...]
    dUdT_mV_K: tuple[float, ...]
    notes: tuple[str, ...] = field(default=())

    def cell_spec(self, name: str | None = None, DCIR_mOhm: float | None = None, source: str | None = None) -> dict:
        """A datasheet cell definition (``packtherm.user_cells``) with this file's values."""
        spec = {
            "name": name or self.title,
            "diameter_mm": round(self.diameter_mm, 2),
            "height_mm": round(self.height_mm, 2),
            "chemistry": self.chemistry,
            "capacity_Ah": round(self.capacity_Ah, 4),
            "V_nominal": round(self.V_nominal, 3),
            "mass_g": round(self.mass_g, 2),
            "DCIR_mOhm": None if DCIR_mOhm is None else round(DCIR_mOhm, 3),
            "cp_J_kgK": round(self.cp_J_kgK, 1),
            "entropic_soc": list(self.soc),
            "entropic_mV_K": [round(x, 5) for x in self.dUdT_mV_K],
            "source": source or f"BPX file {Path(self.path).name}: {self.title}",
        }
        if self.k_W_mK is not None:
            spec["k_radial_W_mK"] = round(self.k_W_mK, 4)
        return spec


def _bpx():
    try:
        import bpx
    except ImportError as e:  # pragma: no cover - depends on the install
        raise BPXError(INSTALL_HINT) from e
    return bpx


def _fn(v, what: str):
    """A BPX value (number, expression in x or table) as a function of one argument."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return lambda x, c=float(v): np.full_like(np.asarray(x, float), c)
    if hasattr(v, "x") and hasattr(v, "y"):  # InterpolatedTable
        xs, ys = np.asarray(v.x, float), np.asarray(v.y, float)
        return lambda x: np.interp(x, xs, ys)
    if hasattr(v, "to_python_function"):
        f = v.to_python_function(preamble="from numpy import exp, tanh, cosh, sinh, sqrt, log, pi, abs\n")
        return lambda x: np.asarray(f(np.asarray(x, float)), float) * np.ones_like(np.asarray(x, float))
    raise BPXError(f"{what}: not a number, expression or table")


def _ocp(e, side: str):
    if e.ocp is not None:
        return _fn(e.ocp, f"{side} OCP")
    if e.ocp_delith is not None and e.ocp_lith is not None:  # hysteresis: the mean of the two branches
        a, b = _fn(e.ocp_delith, side), _fn(e.ocp_lith, side)
        return lambda x: 0.5 * (a(x) + b(x))
    raise BPXError(f"{side} electrode: no OCP")


def cylinder(volume_m3: float, area_m2: float) -> tuple[float, float]:
    """Diameter and height [m] of the cylinder with this volume and external area (the taller one)."""
    # A = 2 pi r^2 + 2 V / r  ->  2 pi r^3 - A r + 2 V = 0
    roots = [
        r.real for r in np.roots([2 * math.pi, 0.0, -area_m2, 2 * volume_m3]) if abs(r.imag) < 1e-12 and r.real > 0
    ]
    shapes = sorted(((2 * r, volume_m3 / (math.pi * r * r)) for r in roots), key=lambda s: -s[1] / s[0])
    if not shapes:
        raise BPXError("no cylinder has this volume and external surface area")
    return shapes[0]


def _chemistry(text: str) -> str | None:
    t = text.upper()
    for word, chem in (("LFP", "LFP"), ("LIFEPO", "LFP"), ("NCA", "NCA"), ("NMC", "NMC"), ("NCM", "NMC")):
        if re.search(rf"\b{word}", t):
            return chem
    return None


def read_bpx(
    path: str | Path,
    chemistry: str | None = None,
    diameter_mm: float | None = None,
    height_mm: float | None = None,
) -> BPXCell:
    """The cell a BPX file describes, for PackTherm (raises BPXError)."""
    bpx = _bpx()
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    notes = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            obj = bpx.parse_bpx_file(str(path))
        except (ValueError, TypeError, KeyError) as e:  # pydantic ValidationError is a ValueError
            raise BPXError(f"{path.name}: not a valid BPX file: {e}") from None
    if any("legacy" in str(w.message).lower() for w in caught):
        notes.append("a BPX 0.x file, converted to 1.x by the bpx package")
    p = obj.parameterisation
    ne, pe = p.negative_electrode, p.positive_electrode
    for side, e in (("negative", ne), ("positive", pe)):
        if not hasattr(e, "ocp"):
            raise BPXError(f"{path.name}: the {side} electrode is a blend; PackTherm reads single-material electrodes")
    c = p.cell
    header = raw.get("Header", {})
    text = " ".join(str(header.get(k, "")) for k in ("Title", "Description"))

    if diameter_mm is None or height_mm is None:
        if "cylind" not in text.lower():
            raise BPXError(
                f"{path.name}: the file does not say the cell is cylindrical. PackTherm models cylindrical "
                "cells: give its diameter and height if it is one"
            )
        d, h = cylinder(c.volume, c.external_surface_area)
        diameter_mm, height_mm = 1e3 * d, 1e3 * h
        notes.append(f"size from the volume and external area: {diameter_mm:.1f} x {height_mm:.1f} mm")
    chem = (chemistry or _chemistry(text) or "").upper()
    if chem not in ("NMC", "NCA", "LFP"):
        raise BPXError(f"{path.name}: say which chemistry (NMC, NCA or LFP); the file's title does not")

    # State of charge by stoichiometry: 0 at the negative's minimum and the positive's maximum.
    soc = np.asarray(SOC_GRID)
    x = ne.minimum_stoichiometry + soc * (ne.maximum_stoichiometry - ne.minimum_stoichiometry)
    y = pe.maximum_stoichiometry - soc * (pe.maximum_stoichiometry - pe.minimum_stoichiometry)
    ocv = _ocp(pe, "positive")(y) - _ocp(ne, "negative")(x)
    dn, dp = _fn(ne.dudt, "negative entropic"), _fn(pe.dudt, "positive entropic")
    zero = np.zeros_like(soc)
    dudt = (dp(y) if dp else zero) - (dn(x) if dn else zero)
    if dn is None and dp is None:
        notes.append("no entropic coefficients: no reversible heat")
    elif not np.any(dudt):
        notes.append("the entropic coefficients are zero: no reversible heat")
    if not np.all(np.isfinite(ocv)) or not np.all(np.diff(ocv) > -0.005):
        raise BPXError(f"{path.name}: the open-circuit voltage from the electrodes is not rising with charge")

    cell_raw = raw.get("Parameterisation", {}).get("Cell", {})
    user = raw.get("Parameterisation", {}).get("User-defined", {}) or {}
    k = cell_raw.get(CONDUCTIVITY_KEY, user.get(CONDUCTIVITY_KEY))
    if k is None:
        notes.append("no thermal conductivity in the file: the chemistry's is used")
    return BPXCell(
        path=str(path),
        title=str(header.get("Title", path.stem)),
        model=str(header.get("Model", "")),
        chemistry=chem,
        capacity_Ah=float(c.nominal_cell_capacity),
        V_min=float(c.lower_voltage_cutoff),
        V_max=float(c.upper_voltage_cutoff),
        V_nominal=float(np.trapezoid(ocv, soc)),
        diameter_mm=float(diameter_mm),
        height_mm=float(height_mm),
        mass_g=1e3 * float(c.density) * float(c.volume),
        cp_J_kgK=float(c.specific_heat_capacity),
        k_W_mK=None if k is None else float(k),
        soc=tuple(float(s) for s in soc),
        ocv_V=tuple(float(v) for v in ocv),
        dUdT_mV_K=tuple(1e3 * float(v) for v in dudt),
        notes=tuple(notes),
    )


DERIVED_WARNING = (
    "derived from a physics model (the BPX file in PyBaMM), not measured: for the LG M50 a derivation like this "
    "gave about half the resistance measured on real cells (v0.6.9), so heat from this cell is likely low until "
    "its resistance is checked against pulses on the real cell"
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "bpx_cell"


def write_cell_files(
    cell: BPXCell, out_dir: str | Path, name: str | None = None, DCIR_mOhm: float | None = None, report=None
) -> dict[str, Path]:
    """Write the cell as PackTherm cell files.

    With a fit report (``packtherm.bpx_fit.derive``): ``<name>.yaml`` (size, mass, thermal properties,
    reversible heat, and the circuit's DC resistance) and ``<name>_circuit.yaml`` (the derived circuit, a
    fitted cell file naming the first under ``like``; studies use this one). With only ``DCIR_mOhm``:
    the first, on its own, for the lumped model.
    """
    import datetime as dt
    import hashlib

    import yaml

    from . import __version__
    from .fitting.cellfile import FORMAT, STATUS_MULTI, _plain, dc_resistance, ecm_doc

    if report is None and DCIR_mOhm is None:
        raise BPXError("give a DC resistance, or derive the circuit from the file's model")
    name = name or cell.title
    stem = _slug(name)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if report is not None:
        DCIR_mOhm = 1e3 * dc_resistance(report.ecm, capacity_Ah=cell.capacity_Ah)
    spec = cell.cell_spec(name=name, DCIR_mOhm=DCIR_mOhm)
    paths = {"cell": out / f"{stem}.yaml"}
    head = f"# PackTherm cell from the BPX file {Path(cell.path).name} (packtherm bpx, v{__version__}).\n"
    for n in cell.notes:
        head += f"# Note: {n}.\n"
    if report is None:
        head += "# DCIR_mOhm was given by hand: the lumped resistance model.\n"
    else:
        head += f"# DCIR_mOhm is the derived circuit's ({stem}_circuit.yaml): {DERIVED_WARNING}.\n"
    paths["cell"].write_text(
        head + yaml.safe_dump(_plain(spec), sort_keys=False, allow_unicode=True, width=110), encoding="utf-8"
    )
    if report is None:
        return paths

    st = report.settings
    temps = sorted(st.temperatures_C)
    doc = {
        "packtherm_fitted_cell": FORMAT,
        "name": name,
        "status": STATUS_MULTI,
        "usable_in_studies": len(temps) >= 3,
        **({} if len(temps) >= 3 else {"why_not_usable": "derived at fewer than 3 temperatures"}),
        "like": paths["cell"].name,
        "model": {
            "form": "circuit",
            "description": "open-circuit voltage, instant resistance R0, a charge-transfer branch (I0, gamma, tau_ct), "
            "a slow branch (Rd, tau_d) and a rise near empty (soc_a, soc_b): packtherm.ecm.ECM, derived from the BPX "
            "file's model (packtherm.bpx_fit)",
            "ecm": ecm_doc(report.ecm),
            "dc_resistance_mOhm": round(DCIR_mOhm, 4),
        },
        "capacity": {"measured_Ah": cell.capacity_Ah, "how": "the BPX file's nominal capacity"},
        "open_circuit_voltage": {
            "soc": [round(float(x), 4) for x in report.ecm.ocv_soc],
            "V": [round(float(x), 5) for x in report.ecm.ocv_V],
            "how": "the model's C/25 discharge and charge at 25 degC, averaged",
        },
        "valid_for": {
            "temperature_C": [temps[0], temps[-1]],
            "discharge_C": [0.0, max(st.rates_C)],
            "charge_C": None,
            "soc": [min(st.socs), max(st.socs)],
        },
        "errors": {
            "fitted_on": {
                "pulse_overpotential_median_pct": {f"{k:g}C": round(v, 2) for k, v in report.pulse_error_pct.items()},
                "replay_rmse_mV_above_10pct_soc": {f"{k:g}C": round(v, 2) for k, v in report.replay_rmse_mV.items()},
            },
            "held_out": [],
        },
        "data_warnings": [DERIVED_WARNING, "charging was not in the synthetic tests", *cell.notes],
        "provenance": {
            "packtherm": __version__,
            "fitted_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "derived_from_bpx": {
                "file": Path(cell.path).name,
                "sha256": hashlib.sha256(Path(cell.path).read_bytes()).hexdigest(),
                "title": cell.title,
                "model": st.model,
            },
            "settings": {
                "temperatures_C": list(st.temperatures_C),
                "socs": list(st.socs),
                "rates_C": list(st.rates_C),
                "pulse_s": st.pulse_s,
                "rest_min": st.rest_min,
                "pulses": report.pulses,
            },
        },
    }
    paths["circuit"] = out / f"{stem}_circuit.yaml"
    paths["circuit"].write_text(
        f"# PackTherm cell: a circuit derived from the BPX file {Path(cell.path).name} in PyBaMM (packtherm bpx).\n"
        f"# {DERIVED_WARNING}.\n" + yaml.safe_dump(_plain(doc), sort_keys=False, allow_unicode=True, width=110),
        encoding="utf-8",
    )
    return paths


__all__ = ["DERIVED_WARNING", "INSTALL_HINT", "BPXCell", "BPXError", "cylinder", "read_bpx", "write_cell_files"]
