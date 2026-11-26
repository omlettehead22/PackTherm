"""Command line interface.

packtherm thesis                      # the four MSc thesis scenarios
packtherm cell M50 --mode discharge --c-rate 1.5 --cooling air --level high --pcm-mm 3 --pcm-grade RT42
packtherm cells                       # list the cell library
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import pandas as pd

from .cells import CELLS, get_cell
from .electrothermal import check_fitted_range, check_limits, constant_current, simulate_cell
from .materials import PCM_LIBRARY
from .metrics import summarise_result, summary_table
from .params import DEFAULT_AUX_POWER, DEFAULT_H, KELVIN, default_params
from .scenarios import run_scenario, thesis_scenarios


def _number(kind, lo, lo_open, hi=None):
    """argparse type: a number with bounds, so bad input fails with a usage message."""

    def parse(text):
        try:
            x = kind(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
        if (x <= lo) if lo_open else (x < lo):
            raise argparse.ArgumentTypeError(f"must be {'>' if lo_open else '>='} {lo:g}, got {text}")
        if hi is not None and x > hi:
            raise argparse.ArgumentTypeError(f"must be <= {hi:g}, got {text}")
        return x

    return parse


POS = _number(float, 0.0, True)  # > 0
NONNEG = _number(float, 0.0, False)  # >= 0
FRACTION = _number(float, 0.0, False, 1.0)  # 0-1
CONTACT = _number(float, 0.0, True, 1.0)  # (0, 1]
POS_INT = _number(int, 0, True)


def _thesis(args) -> None:
    P = default_params()
    pairs = []
    for sc in thesis_scenarios(P):
        t0 = time.perf_counter()
        res = run_scenario(P, sc)
        print(f"{sc.name:<20} T_peak={res.T_max.max() - KELVIN:6.2f} degC  ({time.perf_counter() - t0:.1f}s)")
        pairs.append((sc, res))
    df = summary_table(pairs)
    cols = ["Scenario", "T_peak_C", "MaxCellDifference_C", "PCM_utilisation", "E_aux_Wh", "BalanceError_pct"]
    with pd.option_context("display.width", 120, "display.precision", 4):
        print(df[cols].to_string(index=False))
    if args.out:
        df.to_csv(args.out, index=False)
        print(f"Wrote {args.out}")


def _cell_file(path: str) -> None:
    """Show a user-defined cell as PackTherm understands it."""
    from .user_cells import ENTROPIC, cell_from_spec, read_cell_file, validate_cell

    spec, warnings = validate_cell(read_cell_file(path))
    c = cell_from_spec(spec)
    rows = [
        ("name", c.name),
        ("model", c.model_label),
        (
            "format",
            f"{spec['format']} ({c.diameter * 1e3:g} x {c.height * 1e3:g} mm)" if spec["format"] else c.form_factor,
        ),
        (
            "chemistry",
            c.chemistry + ("" if spec["entropic"] and spec["chemistry"] in ENTROPIC else ", no entropic heat"),
        ),
        ("capacity", f"{c.capacity_Ah:g} Ah at {c.V_nominal:g} V ({c.capacity_Ah * c.V_nominal:.1f} Wh)"),
        (
            "energy density",
            (
                f"{c.capacity_Ah * c.V_nominal / (c.volume * 1e3):.0f} Wh/L, "
                f"{c.capacity_Ah * c.V_nominal / c.mass:.0f} Wh/kg"
            ),
        ),
        ("mass, density", f"{c.mass * 1e3:g} g, {c.density / 1e3:.2f} g/cm3"),
        ("DCIR at 25 degC", f"{c.R0_25C * 1e3:g} mOhm (worst case uses {c.R0_range[1] * 1e3:g} mOhm + margin)"),
        (
            "cold rise",
            (
                f"x{math.exp(c.Ea_R / 8.314462618 * (1 / 273.15 - 1 / 298.15)):.2f} at 0 degC "
                f"(activation energy {c.Ea_R / 1e3:g} kJ/mol)"
            ),
        ),
        ("thermal", f"cp {c.cp:.0f} J/kgK, k radial {c.k_radial:.2f}, axial {c.k_axial:.1f} W/mK"),
        (
            "limits",
            ", ".join(
                x
                for x in (
                    f"discharge {c.max_discharge_C * c.capacity_Ah:g} A ({c.max_discharge_C:.2f}C)"
                    if c.max_discharge_C
                    else "",
                    f"charge {c.max_charge_C * c.capacity_Ah:g} A ({c.max_charge_C:.2f}C)" if c.max_charge_C else "",
                    f"charge <= {c.T_max_charge_C:g} degC" if c.T_max_charge_C is not None else "",
                    f"discharge <= {c.T_max_discharge_C:g} degC" if c.T_max_discharge_C is not None else "",
                    f"charge >= {c.T_min_charge_C:g} degC" if c.T_min_charge_C is not None else "",
                    f"discharge >= {c.T_min_discharge_C:g} degC" if c.T_min_discharge_C is not None else "",
                )
                if x
            )
            or "none given (no datasheet checks)",
        ),
    ]
    w = max(len(k) for k, _ in rows)
    for k, v in rows:
        print(f"{k:<{w}}  {v}")
    for x in warnings:
        print(f"WARNING: {x}")
    print("Lumped resistance from datasheet values, no voltage model: less accurate than the validated cells.")


def _serve(args) -> None:
    import os

    try:
        import uvicorn

        from .api import create_app
    except ImportError as e:
        raise ValueError(
            f"the API needs its extra dependencies: pip install 'packtherm[api]' ({e.name} missing)"
        ) from None
    port = args.port or int(os.environ.get("PORT", "8000"))
    # One process: the job queue lives in it (each study runs in its own worker process).
    uvicorn.run(create_app(), host=args.host, port=port, workers=1)


def _data(args) -> None:
    import json

    from .testdata import TestDataError, load_test_data

    columns = {r: getattr(args, r) for r in ("time", "current", "voltage", "temperature", "ambient") if getattr(args, r)}
    try:
        rec = load_test_data(args.file, columns=columns or None, capacity_Ah=args.capacity)
    except TestDataError as e:
        raise ValueError(str(e)) from None
    if args.flip:
        rec.current_A = -rec.current_A
        rec.conversions.append("current sign flipped (--flip)")
    if args.json:
        print(
            json.dumps(
                {
                    "source": rec.source,
                    "samples": len(rec),
                    "duration_s": rec.duration_s,
                    "columns": rec.columns,
                    "converted": rec.conversions,
                    "warnings": rec.warnings,
                    "segments": rec.segment_table(),
                },
                indent=1,
            )
        )
        return
    print(rec.summary())
    if args.segments:
        rows = rec.segment_table()
        print()
        keys = list(rows[0]) if rows else []
        print("  ".join(f"{k:>11}" for k in keys))
        for r in rows:
            print("  ".join(f"{r[k]!s:>11}" for k in keys))
    if args.plot:
        print(f"Wrote {rec.plot(args.plot)}")


def _fit_cell(args) -> None:
    from pathlib import Path

    from .fitting import fit_cell, fitted_cell_doc, write_fitted_cell, write_report
    from .testdata import TestDataError, load_test_data

    def read(path):
        try:
            return load_test_data(path)
        except TestDataError as e:
            raise ValueError(str(e)) from None

    thermal: list[dict] = []
    if args.tests:
        from .fitting.testlist import read_test_list, run_test_list

        single = ("slow", "pulses", "steps", "check", "compare", "rated_capacity", "citation", "licence")
        given = [f"--{k.replace('_', '-')}" for k in single if getattr(args, k)]
        if given:
            raise ValueError(f"{', '.join(given)}: give these in the test list, not with it")
        tl = read_test_list(args.tests)
        print(f"Fitting {tl.name} from {tl.path}")
        fit, doc, thermal = run_test_list(tl)
        name = tl.name
        out_path = Path(args.output) if args.output else (tl.output or tl.path.with_name(tl.path.stem + "_cell.yaml"))
        report = Path(args.report) if args.report else (tl.report or out_path.with_suffix(".html"))
    else:
        if not (args.slow and args.pulses):
            raise ValueError("give a test list (packtherm fit tests.yaml), or --slow and --pulses")
        slow, pulses = read(args.slow), read(args.pulses)
        steps = read(args.steps) if args.steps else None
        checks = [read(f) for f in args.check or []]
        compare = None
        if args.compare:
            from .cells import get_cell

            lib = get_cell(args.compare)
            if lib.ecm is None:
                raise ValueError(f"--compare {args.compare}: that cell has no circuit model to compare with")
            compare = (f"library {lib.name}", lib.ecm, lib.capacity_Ah)
        fit = fit_cell(slow, pulses, steps=steps, checks=checks, compare_ecm=compare)
        out_path = Path(args.output or "fitted_cell.yaml")
        name = args.name or out_path.stem
        dataset = {k: v for k, v in (("citation", args.citation), ("licence", args.licence)) if v}
        paths = {"slow": [args.slow], "pulses": [args.pulses]}
        if args.steps:
            paths["steps"] = [args.steps]
        if args.check:
            paths["checks"] = list(args.check)
        doc = fitted_cell_doc(fit, name, paths, rated_capacity_Ah=args.rated_capacity, dataset=dataset or None)
        report = Path(args.report) if args.report else out_path.with_suffix(".html")
    if args.name:
        doc["name"] = name = args.name
    out = write_fitted_cell(out_path, doc)
    write_report(report, fit, doc, thermal)

    T = doc["valid_for"]["temperature_C"]
    where = f" ({T[0]:g} to {T[1]:g} degC)" if T else ""
    temps = fit.temperatures
    how = f"fitted at {', '.join(f'{x:g}' for x in temps)} degC" if len(temps) > 1 else "fitted at one temperature"
    use = "usable in studies" if doc["usable_in_studies"] else "not usable in studies: " + doc.get("why_not_usable", "")
    print(f"{name}: {how}{where}; {use}")
    cap = doc["capacity"]
    print(f"  capacity {fit.capacity_Ah:.4g} Ah" + (f" (rated {cap['rated_Ah']:g} Ah)" if "rated_Ah" in cap else ""))
    if fit.per_temperature:
        names = ("R0_25C", "I0_25C", "Rm_25C", "Rd_25C", "tau_d")
        print("  by temperature:  " + "  ".join(f"{n.replace('_25C', ''):>9}" for n in names))
        for pt in fit.per_temperature:
            v = {p.name: p.value for p in pt["params"]}
            print(f"    {pt['at_C']:>5g} degC     " + "  ".join(f"{v[n]:>9.4g}" for n in names))
    for p in fit.params:
        if p.source not in ("fitted", "not fitted"):
            continue
        rng = f"  95% {p.ci95[0]:.4g} to {p.ci95[1]:.4g}" if p.ci95 else ""
        flag = f"  [{p.note}]" if p.note else ""
        print(f"  {p.name:<8} {p.value:>10.4g} {p.unit:<5}{rng}{flag}")
    for k, e in fit.errors.items():
        print(f"  error, {k}: {e['rmse_mV']:.1f} mV RMS, {e['max_mV']:.0f} mV worst")
    for c in fit.checks:
        line = f"  held out, {c['file']}: {c['rmse_mV']:.1f} mV RMS"
        if "compare" in c:
            line += f" (the {c['compare']}: {c['compare_rmse_mV']:.1f} mV)"
        print(line)
    if thermal:
        from .fitting.thermal import summary

        sm = summary(thermal)
        line = (
            f"  held out, voltage and temperature from the current alone ({sm['tests']} tests): "
            f"{sm['median_V_rmse_mV']:.1f} mV, {100 * sm['within_1K']:.0f}% within 1 K"
        )
        if "compare" in sm:
            line += (
                f" (the {sm['compare']}: {sm['compare_median_V_rmse_mV']:.1f} mV, "
                f"{100 * sm['compare_within_1K']:.0f}% within 1 K)"
            )
        print(line)
    for a, b, r in fit.correlated:
        print(f"  {a} and {b} trade off (correlation {r:+.2f}): the tests pin a combination")
    print(f"Wrote {out} and {report}")


def _cells(args) -> None:
    if args.file:
        _cell_file(args.file)
        return
    from .cells import COMPARISON

    rows = [
        {
            "key": k,
            "name": c.name,
            "Ah": round(c.capacity_Ah, 2),
            "model": c.model_label,
            "DCIR_25C_mOhm": c.R0_25C * 1e3,
            "mass_g": c.mass * 1e3,
            "max_chg_C": round(c.max_charge_C, 2) if c.max_charge_C else None,
            "max_dis_C": round(c.max_discharge_C, 2) if c.max_discharge_C else None,
        }
        for k, c in CELLS.items()
    ]
    table = pd.DataFrame(rows)
    print("Cells to design with:")
    print(table[~table.key.isin(COMPARISON)].to_string(index=False))
    print("\nFor comparison only (an earlier or simpler model of a cell above; lumped models have no voltage limits):")
    print(table[table.key.isin(COMPARISON)].to_string(index=False))
    print(
        "DCIR_25C is the lumped reference; it sets the worst-case re-check. Circuit cells compute "
        "losses from their own R0, charge transfer and slow branch."
    )


def _cell(args) -> None:
    cell = get_cell(args.cell)
    h = args.h if args.h is not None else DEFAULT_H[args.cooling][args.level]
    T_env = args.t_env + KELVIN
    soc0 = args.soc0 if args.soc0 is not None else (1.0 if args.mode == "discharge" else 0.1)
    limits = (args.soc_min, args.soc_max)
    duration = args.duration or 3600 * (abs(limits[1] - limits[0]) / args.c_rate) * 1.05
    from .materials import get_pcm, melt_midpoint_C
    from .params import Params

    pcm = get_pcm(args.pcm_grade)
    res, load = simulate_cell(
        cell,
        constant_current(cell, args.c_rate, args.mode),
        duration,
        h,
        T_env,
        pcm_thickness=args.pcm_mm * 1e-3,
        case_thickness=args.case_mm * 1e-3,
        soc0=soc0,
        soc_limits=limits,
        base=Params(pcm=pcm),
    )
    m = summarise_result(res, aux_power_W=DEFAULT_AUX_POWER.get(args.cooling, {}).get(args.level, 0.0))
    a = load.arrays()
    pcm_text = (
        f"{args.pcm_grade} {args.pcm_mm:g} mm (melts ~{melt_midpoint_C(pcm):.0f} degC)" if args.pcm_mm > 0 else "none"
    )
    print(f"{cell.name}: {args.mode} at {args.c_rate}C, {args.cooling} h={h:g} W/m2K, PCM {pcm_text}")
    print(f"  SOC {soc0:.2f} -> {load.soc:.2f} in {duration / 60:.1f} min")
    print(f"  Peak cell temperature   {m['T_peak_C']:.2f} degC (at {m['TimeToPeak_s'] / 60:.1f} min)")
    print(f"  Max in-cell difference  {m['MaxCellDifference_C']:.2f} degC")
    print(
        f"  Heat generated          {res.E_generated / 1e3:.2f} kJ (reversible {a['Q_rev_W'].sum() / max(a['Q_irr_W'].sum(), 1e-12):+.0%} of irreversible)"
    )
    print(f"  PCM peak liquid frac    {m['PCM_fraction_peak']:.2f}")
    print(f"  Energy balance error    {res.balance_error_pct:.1e} %")
    for w in check_limits(cell, load, res) + check_fitted_range(cell, load, res):
        print(f"  WARNING: {w}")


def _design(args) -> None:
    import re

    from .design import DutyCycle, Requirements
    from .ev import Pack, Vehicle, road_trip_duty, wltc_duty
    from .report import plot_tradeoff

    cell = get_cell(args.cell)
    rest = args.rest_h * 3600
    if args.duty == "constant":
        duty = DutyCycle.constant(
            args.c_rate, args.mode, soc0=args.soc0, soc_limits=(args.soc_min, args.soc_max), rest_after_s=rest
        )
        stem = f"{args.cell.lower()}_{args.mode}_{args.c_rate:g}C"
    else:
        pack = Pack.for_energy(cell, args.pack_kwh, args.pack_v)
        vehicle = Vehicle()
        if args.duty == "wltc":
            duty = wltc_duty(cell, pack, vehicle, cycles=args.cycles, rest_after_s=rest)
            stem = f"{args.cell.lower()}_wltc{args.cycles}"
        else:
            duty = road_trip_duty(
                cell, pack, vehicle, speed_kmh=args.speed, charge_c_rate=args.charge_c, rest_after_s=rest
            )
            stem = f"{args.cell.lower()}_roadtrip_{args.speed:g}kmh"
    stem += f"_{args.t_env:g}C"
    req = Requirements(
        T_max_C=args.t_max, dT_cell_max_C=args.dt_max, T_env_C=args.t_env, recovery_max_min=args.recovery_max_min
    )
    if args.level == "module":
        from .study import StudySpec, validate

        spec = StudySpec(validate(_study_doc(args)))
        study = spec.build()
        cells = "interior and edge cells at inlet and outlet" if study.edge_cells else "inlet and outlet cell"
        n = len(study.designs())
        print(f"Simulating {n} module design{'s' if n != 1 else ''} ({cells}, {study.mode} mode)...")
        t0 = time.perf_counter()
        run = spec.run(workers=args.workers)
        print(run.result.summary())
        print(f"({time.perf_counter() - t0:.0f}s)")
        if args.out_dir:
            paths = run.write(args.out_dir)
            print("Wrote " + ", ".join(str(p) for p in paths.values()))
        return
    else:
        result = _cell_study(args, cell, duty, req)
        t0 = result.t0
    print(result.summary())
    print(f"({time.perf_counter() - t0:.0f}s)")
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^a-z0-9_.]+", "_", stem.lower())
        result.table.to_csv(args.out_dir / f"{stem}_designs.csv", index=False)
        plot_tradeoff(result, args.out_dir / f"{stem}_tradeoff.png")
        print(f"Wrote {stem}_designs.csv and {stem}_tradeoff.png to {args.out_dir}")


def _cell_study(args, cell, duty, req):
    from .design import DesignStudy, cooling_options, run_study, thesis_cooling_options

    hw = {"air": args.air_kg_per_kwh, "liquid": args.liquid_kg_per_kwh}
    if args.thesis_levels:
        options = thesis_cooling_options(hw)
    else:
        options = cooling_options(
            air_h=tuple(args.air_h),
            liquid_h=tuple(args.liquid_h),
            chiller_setpoints_C=tuple(sp for sp in args.chiller_c if sp < args.t_env),
            hardware_kg_per_kWh=hw,
        )
    study = DesignStudy(
        cell,
        duty,
        req,
        cooling_options=tuple(options),
        pcm_grades=tuple(args.pcm_grades),
        pcm_thicknesses_mm=tuple(x for x in args.pcm_mm if x > 0),
        case_thickness_mm=args.case_mm,
        cells_in_pack=args.cells_in_pack,
        chiller_cop=args.cop if args.cop is not None else 3.0,
        resistance_margin=args.r_margin,
    )
    n = len(options) * len(study.pcm_choices())
    print(f"Simulating {n} single-cell design{'s' if n != 1 else ''}...")
    t0 = time.perf_counter()
    result = run_study(study, workers=args.workers)
    result.t0 = t0
    return result


def _study_doc(args) -> dict:
    """The study document (packtherm.study) that ``design --level module`` flags describe."""
    duty = {"type": args.duty, "rest_h": args.rest_h, "pack_kWh": args.pack_kwh}
    if args.duty == "constant":
        duty.update(c_rate=args.c_rate, direction=args.mode, soc0=args.soc0, soc_min=args.soc_min, soc_max=args.soc_max)
    elif args.duty == "wltc":
        duty.update(cycles=args.cycles, pack_V=args.pack_v)
    else:
        duty.update(speed_kmh=args.speed, charge_c_rate=args.charge_c, pack_V=args.pack_v)
    return {
        "packtherm_study": 1,
        "cell": args.cell,
        "mode": "fast" if args.fast else "normal",
        "ambient_C": args.t_env,
        "duty": duty,
        "requirements": {
            "T_max_C": args.t_max,
            "dT_cell_max_C": args.dt_max,
            "recovery_max_min": args.recovery_max_min,
            "cell_to_cell_max_K": args.cell_to_cell_max,
        },
        "design_space": {
            "topologies": list(args.topologies),
            "air_flows_g_s": list(args.air_flows),
            "coolant_flows_g_s": list(args.coolant_flows),
            "chiller_C": list(args.chiller_c),
            "fillers": list(args.fillers),
            "gaps_mm": list(args.gaps),
            "packing": args.packing,
        },
        "options": {
            "edge_cells": not args.no_edge_cells,
            "wall_U": args.wall_u,
            "r_margin": args.r_margin,
            "chiller_cop": args.cop,
            "chiller_runs": args.chiller_runs,
            "liquid_loop_kg": args.liquid_loop_kg,
            "air_system_kg": args.air_system_kg,
            "chiller_kg": args.chiller_kg,
        },
    }


def _run(args) -> None:
    from .study import load_study

    spec = load_study(args.study)
    study = spec.build()
    label = f" ({spec.spec['name']})" if spec.spec.get("name") else ""
    if spec.is_sensitivity:
        se = spec.spec["sensitivity"]
        what = f"the grid's {se['design']} pick" if isinstance(se["design"], str) else "the named design"
        print(f"{args.study}{label}: which inputs matter most for {what}, {se['mode']} mode...")
    elif spec.is_search:
        se = spec.spec["search"]
        print(
            f"{args.study}{label}: searching up to {se['evaluations']} module designs in {se['mode']} mode, "
            f"the best run again in {study.mode} mode..."
        )
    else:
        n = len(study.designs())
        print(f"{args.study}{label}: {n} module design{'s' if n != 1 else ''}, {study.mode} mode...")
    run = spec.run(workers=args.workers)
    print(run.result.summary())
    print(f"({run.elapsed_s:.0f}s)")
    out = args.out_dir or Path(args.study).parent
    paths = run.write(out)
    print("Wrote " + ", ".join(str(p) for p in paths.values()))


def _template(args) -> None:
    from .study import TEMPLATE

    if args.out:
        Path(args.out).write_text(TEMPLATE, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(TEMPLATE, end="")


def _build_duty(args, cell):
    from .design import DutyCycle
    from .ev import Pack, Vehicle, road_trip_duty, wltc_duty

    rest = getattr(args, "rest_h", 0.0) * 3600
    if args.duty == "constant":
        return DutyCycle.constant(
            args.c_rate, args.mode, soc0=args.soc0, soc_limits=(args.soc_min, args.soc_max), rest_after_s=rest
        )
    pack = Pack.for_energy(cell, args.pack_kwh, args.pack_v)
    if args.duty == "wltc":
        return wltc_duty(cell, pack, Vehicle(), cycles=args.cycles, rest_after_s=rest)
    return road_trip_duty(cell, pack, Vehicle(), speed_kmh=args.speed, charge_c_rate=args.charge_c, rest_after_s=rest)


def _fit(layout, filler, cooling, note=True):
    """A module, with the gap widened if a side ribbon needs more room."""
    from dataclasses import replace

    from .module import Module, SideRibbon

    if isinstance(cooling, SideRibbon) and layout.gap_mm < cooling.min_gap_mm:
        if note:
            print(f"Note: gap widened to {cooling.min_gap_mm:g} mm to fit the side ribbon and its bonds.")
        layout = replace(layout, gap_mm=cooling.min_gap_mm)
    return Module(layout, filler, cooling)


def _bpx(args) -> None:
    from .bpx import BPXError, read_bpx, write_cell_files

    try:
        cell = read_bpx(args.file, chemistry=args.chemistry, diameter_mm=args.diameter_mm, height_mm=args.height_mm)
    except BPXError as e:
        raise SystemExit(f"Error: {e}") from None
    print(
        f"{cell.title}: {cell.chemistry}, {cell.capacity_Ah:g} Ah, {cell.diameter_mm:.1f} x {cell.height_mm:.1f} mm, "
        f"{cell.mass_g:.1f} g, {cell.V_min:g}-{cell.V_max:g} V"
    )
    for n in cell.notes:
        print(f"Note: {n}.")
    report = None
    if args.dcir_mohm is None:
        from .bpx_fit import FULL, QUICK, derive

        settings = QUICK if args.quick else FULL
        print(f"Deriving the circuit: the file's {settings.model} through pulse tests at "
              f"{', '.join(f'{t:g}' for t in settings.temperatures_C)} degC in PyBaMM...")
        try:
            report = derive(cell, settings, progress=lambda i, n: print(f"  temperature {i} of {n} done", flush=True))
        except RuntimeError as e:
            raise SystemExit(f"Error: {e} (or give --dcir-mohm)") from None
        errs = ", ".join(f"{k:g} degC {v:.1f} mV" for k, v in report.replay_rmse_mV.items())
        print(f"  {report.pulses} pulses, replayed through the circuit: {errs} ({report.seconds:.0f} s)")
    paths = write_cell_files(cell, args.out, name=args.name, DCIR_mOhm=args.dcir_mohm, report=report)
    use = paths.get("circuit", paths["cell"])
    print("Wrote " + ", ".join(str(p) for p in paths.values()))
    print(f"Use it in a study as  cell: {use}")
    if report is not None:
        from .bpx import DERIVED_WARNING

        print(f"Note: {DERIVED_WARNING}.")


def _module(args) -> None:
    import pandas as pd

    from .module import AirFlow, BottomPlate, Coolant, Interface, Layout, Module, SideRibbon, compare_modules

    cell = get_cell(args.cell)
    duty = _build_duty(args, cell)
    coolant = Coolant(flow_g_s_per_cell=args.flow, inlet_C=args.inlet_c)
    tim = Interface(args.tim_mm, args.tim_k)
    layout = Layout(args.packing, args.gap)

    def cooling_for(kind):
        return {
            "none": None,
            "air": AirFlow(flow_g_s_per_cell=args.air_flow),
            "bottom": BottomPlate(coolant=coolant, tim=tim),
            "ribbon": SideRibbon(coolant=coolant, tim=tim, contact_fraction=args.contact),
        }[kind]

    if args.compare:
        modules = [Module(layout, None, None), Module(layout, None, AirFlow(flow_g_s_per_cell=args.air_flow))]
        for kind in ("bottom", "ribbon"):
            for filler in (None, *args.fillers):
                modules.append(_fit(layout, filler, cooling_for(kind), note=False))  # the header says so
    else:
        filler = None if args.filler in (None, "air", "none") else args.filler
        modules = [_fit(layout, filler, cooling_for(args.cooling))]
    gaps = sorted({m.layout.gap_mm for m in modules})
    gap_text = " / ".join(f"{g:g}" for g in gaps) + " mm gap" + (" (ribbons widened to fit)" if len(gaps) > 1 else "")
    where = "edge cells (on the module wall)" if args.edge else "interior cells"
    mode = ", fast mode" if args.fast else ""
    print(f"{cell.name}, {duty.name}, ambient {args.t_env:g} degC, {layout.packing} packing, {gap_text}, {where}{mode}")
    rows = compare_modules(cell, modules, duty, args.t_env, edge=args.edge, mode="fast" if args.fast else "normal")
    df = pd.DataFrame(rows)
    cols = [
        "cooling",
        "filler",
        "gap_mm",
        "T_peak_inlet_C",
        "T_peak_outlet_C",
        "cell_to_cell_K",
        "dT_cell_outlet_K",
        "coolant_rise_max_K",
        "pump_mW_per_cell",
        "filler_mass_pct",
    ]
    with pd.option_context("display.width", 160):
        print(df[cols].round(2).to_string(index=False))
    if args.out:
        df.to_csv(args.out, index=False)
        print(f"Wrote {args.out}")


def parser() -> argparse.ArgumentParser:
    """The packtherm command-line parser."""
    from . import __version__

    ap = argparse.ArgumentParser(prog="packtherm", description="Battery thermal management design toolkit.")
    ap.add_argument("--version", action="version", version=f"packtherm {__version__}")
    sub = ap.add_subparsers(dest="cmd")

    t = sub.add_parser("thesis", help="Run the four MSc thesis scenarios.")
    t.add_argument("--out", type=Path, help="Write summary CSV here.")
    t.set_defaults(func=_thesis)

    sv = sub.add_parser("serve", help="Run the HTTP API (needs: pip install packtherm[api]).")
    sv.add_argument("--host", default="127.0.0.1", help="address to listen on (0.0.0.0 for all)")
    sv.add_argument("--port", type=POS_INT, default=None, help="port (default: $PORT, or 8000)")
    sv.set_defaults(func=_serve)

    c = sub.add_parser("cells", help="List the cell library, or show a user-defined cell file.")
    c.add_argument("file", nargs="?", help="a cell file (.yaml or .json) to check and show")
    c.set_defaults(func=_cells)

    t = sub.add_parser(
        "data",
        help="Read cell test data (CSV or .mat), check it and list its parts.",
        description=(
            "Read a cell test (CSV/TSV or MATLAB .mat), convert it to seconds, amps (+ = discharge), volts and degC, "
            "check it, and label its parts: rests, pulses, constant-current steps, CC-CV charges and drive cycles. "
            "Columns are found by name; name them if they are not. See docs/TEST_DATA.md."
        ),
    )
    t.add_argument("file", help="the test file (.csv, .tsv, .txt or .mat)")
    for role in ("time", "current", "voltage", "temperature", "ambient"):
        t.add_argument(f"--{role}", metavar="COLUMN", help=f"the {role} column, if not found by name")
    t.add_argument("--capacity", type=POS, metavar="AH", help="the cell's capacity: C-rates, and a charge check")
    t.add_argument(
        "--flip", action="store_true", help="flip the current's sign after reading (if the check got it wrong)"
    )
    t.add_argument("--segments", action="store_true", help="list every part of the test")
    t.add_argument("--plot", metavar="PNG", help="plot current, voltage and temperature to this file")
    t.add_argument("--json", action="store_true", help="print the summary and parts as JSON")
    t.set_defaults(func=_data)

    ft = sub.add_parser(
        "fit",
        help="Fit PackTherm's circuit model to cell tests.",
        description=(
            "Fit the circuit model to cell tests: a test list (YAML) with tests at several temperatures, or, at "
            "one temperature, --slow and --pulses. Writes a fitted cell file with each value's source and 95%% "
            "range, where it is valid, its errors and what went in, and an HTML report. Fitted at three "
            "temperatures or more, with a cell named under 'like', studies can use it. See docs/FITTING.md."
        ),
    )
    ft.add_argument("tests", nargs="?", metavar="TESTS", help="a test list (.yaml): the tests by temperature")
    ft.add_argument("--slow", metavar="FILE", help="one temperature: a slow full discharge (C/20 or slower), from full")
    ft.add_argument("--pulses", metavar="FILE", help="one temperature: a pulse test (HPPC) with rests between pulses")
    ft.add_argument("--steps", metavar="FILE", help="a test with steady steps followed by rests of 5 min or more")
    ft.add_argument("--check", action="append", metavar="FILE", help="a test to predict, not fitted to (repeatable)")
    ft.add_argument("--compare", metavar="CELL", help="a library cell to predict the --check tests with too, e.g. PF")
    ft.add_argument("-o", "--output", help="the fitted cell file (default: the test list's, or fitted_cell.yaml)")
    ft.add_argument("--report", metavar="HTML", help="the report (default: the cell file's name, .html)")
    ft.add_argument("--name", help="the cell's name (default: the output file's name)")
    ft.add_argument("--rated-capacity", type=POS, metavar="AH", help="the datasheet capacity, to compare with")
    ft.add_argument("--citation", help="where the data comes from, for the file's provenance")
    ft.add_argument("--licence", help="the data's licence, for the file's provenance")
    ft.set_defaults(func=_fit_cell)

    bx = sub.add_parser(
        "bpx",
        help="Make PackTherm cell files from a BPX file (needs packtherm[bpx]; deriving the circuit, packtherm[bpx-fit]).",
    )
    bx.add_argument("file", help="the BPX file (.json)")
    bx.add_argument("--out", default=".", help="folder for the cell files")
    bx.add_argument("--name", help="the cell's name (default: the file's title)")
    bx.add_argument("--chemistry", choices=["NMC", "NCA", "LFP"], help="if the file's title does not say")
    bx.add_argument("--diameter-mm", type=float, help="the can's diameter, instead of from the volume and area")
    bx.add_argument("--height-mm", type=float, help="the can's height, with --diameter-mm")
    bx.add_argument(
        "--dcir-mohm",
        type=float,
        help="a DC resistance from a datasheet: skip deriving the circuit (no PyBaMM) and use the lumped model",
    )
    bx.add_argument("--quick", action="store_true", help="fewer pulse tests (3 temperatures): about a tenth of the time")
    bx.set_defaults(func=_bpx)

    e = sub.add_parser("cell", help="Electro-thermal run of one cell at constant C-rate.")
    e.add_argument("cell", help=f"Cell key ({', '.join(CELLS)}) or a cell file (.yaml or .json)")
    e.add_argument("--mode", choices=["charge", "discharge"], default="discharge")
    e.add_argument("--c-rate", type=POS, default=1.0)
    e.add_argument("--cooling", choices=["air", "liquid", "none"], default="air")
    e.add_argument("--level", choices=["low", "mid", "high"], default="mid")
    e.add_argument("--h", type=NONNEG, help="Override convective coefficient [W/m2K].")
    e.add_argument("--pcm-mm", type=NONNEG, default=3.0)
    e.add_argument("--pcm-grade", default="RT31", help=f"PCM grade: {', '.join(PCM_LIBRARY)}")
    e.add_argument("--case-mm", type=NONNEG, default=1.0)
    e.add_argument("--t-env", type=float, default=25.0, help="Ambient/coolant [degC].")
    e.add_argument("--soc0", type=FRACTION)
    e.add_argument("--soc-min", type=FRACTION, default=0.0)
    e.add_argument("--soc-max", type=FRACTION, default=1.0)
    e.add_argument("--duration", type=POS, help="Seconds (default: time to cross the SOC window +5%%).")
    e.set_defaults(func=_cell)

    d = sub.add_parser("design", help="Sweep module cooling designs and chart the trade-off.")
    d.add_argument("cell", help=f"Cell key ({', '.join(CELLS)}) or a cell file (.yaml or .json)")
    d.add_argument(
        "--level",
        choices=["module", "cell"],
        default="module",
        help="module (default): cell inside a packed module; cell: the v0.3 isolated-cell advisor.",
    )
    g = d.add_argument_group("duty")
    g.add_argument("--duty", choices=["constant", "wltc", "roadtrip"], default="constant")
    g.add_argument("--mode", choices=["charge", "discharge"], default="discharge", help="constant duty")
    g.add_argument("--c-rate", type=POS, default=1.0, help="constant duty")
    g.add_argument("--soc0", type=FRACTION, help="constant duty")
    g.add_argument("--soc-min", type=FRACTION, default=0.0, help="constant duty")
    g.add_argument("--soc-max", type=FRACTION, default=1.0, help="constant duty")
    g.add_argument("--cycles", type=POS_INT, default=3, help="wltc: back-to-back cycles")
    g.add_argument("--speed", type=POS, default=130.0, help="roadtrip: motorway speed [km/h]")
    g.add_argument("--charge-c", type=POS, help="roadtrip: charge C-rate (default: cell maximum)")
    g.add_argument("--pack-kwh", type=POS, default=60.0, help="EV duties: pack energy")
    g.add_argument("--pack-v", type=POS, default=350.0, help="EV duties: nominal pack voltage")
    g.add_argument("--rest-h", type=NONNEG, default=3.0, help="Rest simulated after the event [h].")
    r = d.add_argument_group("requirements")
    r.add_argument("--t-env", type=float, default=25.0, help="Ambient [degC].")
    r.add_argument("--t-max", type=float, help="Peak limit [degC] (default min(45, datasheet)).")
    r.add_argument("--dt-max", type=POS, default=5.0, help="In-cell spread limit [degC].")
    r.add_argument("--recovery-max-min", type=NONNEG, help="Must be ready again within this many minutes.")
    r.add_argument(
        "--cell-to-cell-max", type=POS, help="module: hottest-to-coolest cell peak limit, edge cells included [K]."
    )
    m = d.add_argument_group("module design space (--level module)")
    m.add_argument("--topologies", nargs="+", default=["none", "air", "bottom", "ribbon"])
    m.add_argument("--air-flows", type=POS, nargs="+", default=[0.15, 0.3, 0.6], help="Air per cell [g/s].")
    m.add_argument("--coolant-flows", type=POS, nargs="+", default=[0.02, 0.05], help="Coolant per cell [g/s].")
    m.add_argument(
        "--fillers", nargs="*", default=["none", "RT31", "RT42", "RT31-EG"], help=f"none or {', '.join(PCM_LIBRARY)}"
    )
    m.add_argument("--gaps", type=NONNEG, nargs="+", default=[2.0], help="Can-to-can gaps [mm].")
    m.add_argument("--packing", choices=["hex", "square"], default="hex")
    m.add_argument("--no-edge-cells", action="store_true", help="Skip the cells on the module wall.")
    m.add_argument("--wall-u", type=NONNEG, default=5.0, help="Module wall to ambient, for edge cells [W/m2K].")
    v = d.add_argument_group("single-cell design space (--level cell)")
    v.add_argument("--air-h", type=NONNEG, nargs="+", default=[10, 15, 22, 33, 45, 60])
    v.add_argument("--liquid-h", type=POS, nargs="+", default=[100, 180, 330, 600])
    d.add_argument(
        "--chiller-c", type=float, nargs="*", default=[15.0], help="Chiller setpoints [degC]; none to disable."
    )
    v.add_argument("--thesis-levels", action="store_true", help="Use the discrete thesis cooling levels instead.")
    v.add_argument("--pcm-grades", nargs="*", default=["RT28HC", "RT31", "OM35", "RT42"])
    v.add_argument("--pcm-mm", type=NONNEG, nargs="+", default=[2, 4], help="PCM thicknesses (no PCM always included).")
    v.add_argument("--case-mm", type=NONNEG, default=1.0)
    a = d.add_argument_group("assumptions")
    a.add_argument(
        "--cells-in-pack", type=POS_INT, default=100, help="--level cell only: cells sharing the anchor fan/pump power."
    )
    a.add_argument("--air-kg-per-kwh", type=NONNEG, default=0.5, help="--level cell only.")
    a.add_argument("--liquid-kg-per-kwh", type=NONNEG, default=1.0, help="--level cell only.")
    a.add_argument("--liquid-loop-kg", type=NONNEG, default=3.0, help="module: pump, manifolds, hoses per pack.")
    a.add_argument("--air-system-kg", type=NONNEG, default=4.0, help="module: fan, plenum, ducts per pack.")
    a.add_argument("--chiller-kg", type=NONNEG, default=4.0, help="module: chiller, valve, lines per pack.")
    a.add_argument("--cop", type=POS, help="Fixed chiller COP (module default: from set-point and ambient; cell: 3).")
    a.add_argument(
        "--chiller-runs",
        choices=["event", "always"],
        default="event",
        help="module: chiller on during the event only (then radiator), or throughout.",
    )
    a.add_argument("--r-margin", type=NONNEG, default=0.2, help="Worst-case resistance margin over the published max.")
    d.add_argument("--workers", type=POS_INT)
    d.add_argument(
        "--fast",
        action="store_true",
        help="fast mode (--level module): coarser time step and grids, about 10x quicker, "
        "peaks within about 0.1 K of normal mode (see docs/FAST_MODE.md)",
    )
    d.add_argument("--out-dir", type=Path)
    d.set_defaults(func=_design)

    mo = sub.add_parser("module", help="Simulate a cell inside a packed module (inlet and outlet cell).")
    mo.add_argument("cell", help=f"Cell key ({', '.join(CELLS)}) or a cell file (.yaml or .json)")
    mo.add_argument("--compare", action="store_true", help="Compare all cooling topologies x fillers.")
    mo.add_argument("--fast", action="store_true", help="fast mode: coarser step and grids (see docs/FAST_MODE.md)")
    mo.add_argument("--cooling", choices=["none", "air", "bottom", "ribbon"], default="ribbon")
    mo.add_argument(
        "--filler", default=None, help=f"Gap filler: air (default) or a PCM grade: {', '.join(PCM_LIBRARY)}"
    )
    mo.add_argument("--fillers", nargs="*", default=["RT31", "RT31-EG", "RT42-EG"], help="Fillers for --compare.")
    mo.add_argument("--packing", choices=["hex", "square"], default="hex")
    mo.add_argument("--gap", type=NONNEG, default=2.0, help="Can-to-can gap [mm].")
    mo.add_argument("--flow", type=POS, default=0.05, help="Coolant flow per cell [g/s].")
    mo.add_argument("--inlet-c", type=float, help="Coolant inlet [degC] (default ambient; lower = chiller).")
    mo.add_argument("--contact", type=CONTACT, default=0.25, help="Ribbon contact fraction of the circumference.")
    mo.add_argument("--tim-mm", type=POS, default=0.5)
    mo.add_argument("--tim-k", type=POS, default=2.0)
    mo.add_argument("--air-flow", type=POS, default=0.3, help="Air flow per cell for --cooling air [g/s].")
    mo.add_argument("--duty", choices=["constant", "wltc", "roadtrip"], default="constant")
    mo.add_argument("--mode", choices=["charge", "discharge"], default="discharge")
    mo.add_argument("--c-rate", type=POS, default=1.0)
    mo.add_argument("--soc0", type=FRACTION)
    mo.add_argument("--soc-min", type=FRACTION, default=0.0)
    mo.add_argument("--soc-max", type=FRACTION, default=1.0)
    mo.add_argument("--cycles", type=POS_INT, default=3)
    mo.add_argument("--speed", type=POS, default=130.0)
    mo.add_argument("--charge-c", type=POS)
    mo.add_argument("--pack-kwh", type=POS, default=60.0)
    mo.add_argument("--pack-v", type=POS, default=350.0)
    mo.add_argument("--t-env", type=float, default=25.0)
    mo.add_argument("--edge", action="store_true", help="Run the cells on the module wall (edge cells).")
    mo.add_argument("--out", type=Path, help="Write results CSV here.")
    mo.set_defaults(func=_module)

    rn = sub.add_parser("run", help="Run a study file (YAML or JSON; see packtherm template).")
    rn.add_argument("study", type=Path, help="study file (.yaml, .yml or .json)")
    rn.add_argument("--out-dir", type=Path, help="where to write results (default: next to the study file)")
    rn.add_argument("--workers", type=POS_INT)
    rn.set_defaults(func=_run)
    tp = sub.add_parser("template", help="Print a commented study file to start from.")
    tp.add_argument("--out", type=Path, help="write it to this file instead")
    tp.set_defaults(func=_template)
    return ap


def main(argv: list[str] | None = None) -> None:
    ap = parser()
    args = ap.parse_args(argv)
    if args.cmd is None:
        args = ap.parse_args(["thesis", *(argv or [])])
    try:
        args.func(args)
    except BrokenPipeError:
        # Output piped into something that stopped reading (| head): not an error.
        import os
        import sys

        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
    except (KeyError, ValueError, OSError) as e:  # unknown name, invalid combination or study, missing file
        if isinstance(e, FileNotFoundError) and e.filename:
            msg = f"file not found: {e.filename}"
        elif isinstance(e, OSError):
            msg = f"cannot read {e.filename}: {e.strerror}" if e.filename and e.strerror else str(e)
        else:
            msg = e.args[0] if e.args else str(e)
        ap.exit(2, f"packtherm {args.cmd}: error: {msg}\n")


if __name__ == "__main__":
    main()
