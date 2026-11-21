"""The test list: which tests a fit uses, by temperature, in one YAML file (``packtherm fit tests.yaml``).

```yaml
packtherm_fit: 1
name: Panasonic NCR18650PF (fitted)
like: PF                    # size, mass and thermal properties: a library cell or a cell file
rated_capacity_Ah: 2.9      # optional, to compare with the measured capacity
dataset:                    # optional, kept in the fitted cell file
  citation: Kollmeyer (2018), doi:10.17632/wykht8y7tg.1
  licence: CC BY 4.0
slow: c20.mat               # a slow full discharge: the open-circuit voltage and the capacity
temperatures:               # one entry per test temperature (three or more for studies)
  - at: 25                  # the chamber setpoint (a label: the fit uses the measured cell temperature)
    pulses: hppc_25.mat     # a pulse (HPPC) test; optional with discharges or cycles (the kinetics
                            # then come from the start of load after each rest of a minute or more)
    steps: steps_25.mat     # optional: steady steps with rests after them
    discharges: [dis1c.mat] # optional: full discharges at a working rate
    cycles: [cycle1.csv.gz] # optional: drive cycles to fit on
    start_soc: 1.0          # where the discharges and cycles start (default 1: full)
    slow: c20_0C.mat        # optional: a slow full discharge here too, starting full: the open-circuit
                            # voltage at this temperature, for a cell whose capacity moves with it
checks:                     # optional: tests the fit never sees, predicted afterwards
  - file: udds_25.csv.gz
    start_soc: 1.0
    ambient_C: 25           # if the file has no chamber column (for the thermal check)
compare: PF                 # optional: a library cell to predict the checks with too
chamber_h_W_m2K: 38.7       # optional: the test chamber's convection, for the thermal check; or instead
chamber_calibration:        # calibrate the rig on tests fitted to (heat from their measured voltage): one
  - {file: dis1c.mat, start_soc: 1.0, ambient_C: 25}   # sets h; a drive cycle too sets the heat capacity
  - {file: cycle1.mat, start_soc: 1.0, ambient_C: 25}  # the cell's fixture adds (both for the checks only)
output: pf_fitted.yaml      # optional: where to write the fitted cell file
```

Paths are relative to the test list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FORMAT = 1
TOP_KEYS = {
    "packtherm_fit", "name", "like", "rated_capacity_Ah", "dataset", "slow", "temperatures", "checks",
    "compare", "chamber_h_W_m2K", "chamber_calibration", "output", "report",
}  # fmt: skip
SET_KEYS = {"at", "pulses", "steps", "discharges", "cycles", "start_soc", "slow"}
CHECK_KEYS = {"file", "start_soc", "ambient_C"}


class TestListError(ValueError):
    __test__ = False


@dataclass
class TestList:
    __test__ = False

    path: Path
    name: str
    slow: Path
    sets: list[dict]
    like: str | None = None
    rated_capacity_Ah: float | None = None
    dataset: dict | None = None
    checks: list[dict] = field(default_factory=list)
    compare: str | None = None
    chamber_h: float | None = None
    chamber_calibration: list[dict] | None = None
    output: Path | None = None
    report: Path | None = None

    def files(self) -> dict[str, list[Path]]:
        """Every file, by role: for the fitted cell file's provenance."""
        out: dict[str, list[Path]] = {"slow": [self.slow]}
        for s in self.sets:
            for role in ("pulses", "steps"):
                if s.get(role):
                    out.setdefault(role, []).append(s[role])
            if s.get("slow") and s["slow"] != self.slow:
                out["slow"].append(s["slow"])
            for role in ("discharges", "cycles"):
                out.setdefault(role, []).extend(s.get(role, []))
        if self.checks:
            out["checks"] = [c["file"] for c in self.checks]
        return {k: v for k, v in out.items() if v}


def read_test_list(path: str | Path) -> TestList:
    """Read and check a test list; every problem is reported at once."""
    import yaml

    path = Path(path)
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TestListError(f"{path}: not found") from None
    except yaml.YAMLError as e:
        raise TestListError(f"{path}: not valid YAML: {e}") from None
    if not isinstance(doc, dict):
        raise TestListError(f"{path}: a test list is a mapping of keys to values")
    base = path.parent
    errors: list[str] = []

    def file(v: Any, where: str) -> Path | None:
        if not isinstance(v, str) or not v:
            errors.append(f"{where}: give a file name")
            return None
        p = Path(v) if Path(v).is_absolute() else base / v
        if not p.is_file():
            errors.append(f"{where}: file not found: {p}")
            return None
        return p

    def files(v: Any, where: str) -> list[Path]:
        if v is None:
            return []
        v = [v] if isinstance(v, str) else v
        if not isinstance(v, list):
            errors.append(f"{where}: give a file or a list of files")
            return []
        return [p for i, x in enumerate(v) if (p := file(x, f"{where}[{i}]")) is not None]

    def number(v: Any, where: str, lo: float | None = None, hi: float | None = None) -> float | None:
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            errors.append(f"{where}: a number, got {v!r}")
            return None
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            errors.append(f"{where}: {v} is outside {lo} to {hi}")
            return None
        return float(v)

    for k in sorted(set(doc) - TOP_KEYS):
        errors.append(f"{k}: unknown key (known: {', '.join(sorted(TOP_KEYS))})")
    if doc.get("packtherm_fit") != FORMAT:
        errors.append(f"packtherm_fit: this version reads format {FORMAT}, got {doc.get('packtherm_fit')!r}")
    slow = file(doc.get("slow"), "slow")
    raw_sets = doc.get("temperatures")
    sets: list[dict] = []
    if not isinstance(raw_sets, list) or not raw_sets:
        errors.append("temperatures: give a list, one entry per test temperature")
        raw_sets = []
    for i, s in enumerate(raw_sets):
        w = f"temperatures[{i}]"
        if not isinstance(s, dict):
            errors.append(f"{w}: a mapping (at, pulses, ...)")
            continue
        for k in sorted(set(s) - SET_KEYS):
            errors.append(f"{w}.{k}: unknown key (known: {', '.join(sorted(SET_KEYS))})")
        at = number(s.get("at"), f"{w}.at", -60, 80)
        if s.get("at") is None and len(raw_sets) > 1:
            errors.append(f"{w}.at: give the temperature (degC)")
        sets.append(
            {
                "at": at,
                # Optional when there are discharges or cycles (v0.6.6): the kinetics then come from them.
                "pulses": file(s.get("pulses"), f"{w}.pulses")
                if s.get("pulses") or not (s.get("discharges") or s.get("cycles"))
                else None,
                "steps": file(s["steps"], f"{w}.steps") if s.get("steps") else None,
                "discharges": files(s.get("discharges"), f"{w}.discharges"),
                "cycles": files(s.get("cycles"), f"{w}.cycles"),
                "start_soc": number(s.get("start_soc", 1.0), f"{w}.start_soc", 0, 1),
                "slow": file(s["slow"], f"{w}.slow") if s.get("slow") else None,
            }
        )
    ats = [s["at"] for s in sets if s["at"] is not None]
    if len(ats) != len(set(ats)):
        errors.append("temperatures: each temperature once")
    checks = []
    for i, c in enumerate(doc.get("checks") or []):
        w = f"checks[{i}]"
        if isinstance(c, str):
            c = {"file": c}
        if not isinstance(c, dict):
            errors.append(f"{w}: a file, or a mapping (file, start_soc, ambient_C)")
            continue
        for k in sorted(set(c) - CHECK_KEYS):
            errors.append(f"{w}.{k}: unknown key (known: {', '.join(sorted(CHECK_KEYS))})")
        checks.append(
            {
                "file": file(c.get("file"), f"{w}.file"),
                "start_soc": number(c.get("start_soc"), f"{w}.start_soc", 0, 1),
                "ambient_C": number(c.get("ambient_C"), f"{w}.ambient_C", -60, 80),
            }
        )
    like = doc.get("like")
    if like is not None:
        from ..cells import get_cell

        key = like if not str(like).lower().endswith((".yaml", ".yml", ".json")) else str(base / like)
        try:
            get_cell(str(key))
            like = str(key)
        except (KeyError, ValueError, FileNotFoundError) as e:
            errors.append(f"like: {e.args[0] if e.args else e}")
    compare = doc.get("compare")
    if compare is not None:
        from ..cells import get_cell

        try:
            if get_cell(str(compare)).ecm is None:
                errors.append(f"compare: {compare} has no circuit model to compare with")
        except KeyError as e:
            errors.append(f"compare: {e.args[0]}")
    h = number(doc.get("chamber_h_W_m2K"), "chamber_h_W_m2K", 1, 1000)
    cal = None
    raw_cal = doc.get("chamber_calibration")
    if raw_cal is not None:
        if h is not None:
            errors.append("chamber_calibration: give it or chamber_h_W_m2K, not both")
        items = raw_cal if isinstance(raw_cal, list) else [raw_cal]
        cal = []
        for i, item in enumerate(items):
            at = f"chamber_calibration[{i}]" if isinstance(raw_cal, list) else "chamber_calibration"
            if isinstance(item, str):
                item = {"file": item}
            if not isinstance(item, dict):
                errors.append(f"{at}: a file, or a mapping (file, start_soc, ambient_C)")
                continue
            for k in sorted(set(item) - CHECK_KEYS):
                errors.append(f"{at}.{k}: unknown key (known: {', '.join(sorted(CHECK_KEYS))})")
            one = {
                "file": file(item.get("file"), f"{at}.file"),
                "start_soc": number(item.get("start_soc", 1.0), f"{at}.start_soc", 0, 1),
                "ambient_C": number(item.get("ambient_C"), f"{at}.ambient_C", -60, 80),
            }
            if one["file"] is not None and any(c.get("file") == one["file"] for c in checks):
                errors.append(f"{at}: that test is one of the checks; calibrate on tests fitted to")
            cal.append(one)
    name = doc.get("name")
    if not isinstance(name, str) or not name:
        errors.append("name: give the cell a name")
    if errors:
        raise TestListError(f"{path}:\n  " + "\n  ".join(errors))
    out = doc.get("output")
    rep = doc.get("report")
    return TestList(
        path=path,
        name=name,
        slow=slow,
        sets=sets,
        like=like,
        rated_capacity_Ah=number(doc.get("rated_capacity_Ah"), "rated_capacity_Ah", 0.01, 1000),
        dataset=doc.get("dataset"),
        checks=checks,
        compare=None if compare is None else str(compare),
        chamber_h=h,
        chamber_calibration=cal,
        output=None if out is None else base / out,
        report=None if rep is None else base / rep,
    )


def run_test_list(tl: TestList, progress=print):
    """Fit as the test list says: returns (fit, cell file doc, thermal check rows)."""
    from ..cells import get_cell
    from ..testdata import load_test_data
    from .cellfile import cell_from_doc, fitted_cell_doc
    from .circuit import TestSet, fit_cell
    from .thermal import ThermalCheck, thermal_checks

    def read(p):
        progress(f"  reading {p.name}")
        return load_test_data(p)

    sets = [
        TestSet(
            read(s["pulses"]) if s["pulses"] else None,
            read(s["steps"]) if s["steps"] else None,
            s["at"],
            discharges=[read(p) for p in s["discharges"]],
            cycles=[read(p) for p in s["cycles"]],
            discharge_soc0=s["start_soc"],
            slow=read(s["slow"]) if s.get("slow") and s["slow"] != tl.slow else None,
        )
        for s in tl.sets
    ]
    checks = [(read(c["file"]), c) for c in tl.checks]
    compare = get_cell(tl.compare) if tl.compare else None
    progress(f"  fitting at {', '.join(f'{s.at_C:g}' for s in sets if s.at_C is not None) or 'one temperature'} degC")
    fit = fit_cell(
        read(tl.slow),
        sets=sets,
        checks=[r for r, _ in checks],
        check_soc0=[c["start_soc"] for _, c in checks],
        compare_ecm=(f"library {compare.name}", compare.ecm, compare.capacity_Ah) if compare else None,
    )
    kw = {"rated_capacity_Ah": tl.rated_capacity_Ah, "dataset": tl.dataset, "like": tl.like}
    doc = fitted_cell_doc(fit, tl.name, tl.files(), **kw)
    thermal: list[dict] = []
    h = tl.chamber_h
    cal = None
    if checks and tl.like and tl.chamber_calibration:
        from .thermal import calibrate_rig

        names = ", ".join(c["file"].name for c in tl.chamber_calibration)
        progress(f"  calibrating the test rig on {names}")
        cal = calibrate_rig(
            [ThermalCheck(read(c["file"]), c["start_soc"], c["ambient_C"]) for c in tl.chamber_calibration],
            cell_from_doc(doc),
        )
        h = cal["h_W_m2K"]
    if checks and tl.like and h:
        progress("  predicting the checks' voltage and temperature from their current")
        cell = cell_from_doc(doc)
        tc = [ThermalCheck(r, c["start_soc"] if c["start_soc"] is not None else 1.0, c["ambient_C"]) for r, c in checks]
        fixture = cal["fixture_J_K"] if cal else 0.0
        thermal = thermal_checks(tc, cell, h, compare, f"library {compare.name}" if compare else "", fixture)
        doc = fitted_cell_doc(fit, tl.name, tl.files(), thermal_checks=thermal, **kw)
        if cal:
            rig = (
                f"{h:.1f} W/(m2 K)"
                + (f", fixture {cal['fixture_J_K']:.0f} J/K (the cell: {cal['cell_J_K']:.0f} J/K)" if fixture else "")
                + f", calibrated on {', '.join(cal['files'])} with the heat from their measured voltage"
                + f" ({cal['T_rmse_K']:.2f} K RMS there){'; ' + cal['note'] if cal['note'] else ''}"
            )
        else:
            rig = f"{h:.1f} W/(m2 K), as given"
        doc["provenance"]["settings"]["test rig"] = rig
    return fit, doc, thermal
