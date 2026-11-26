# History

How PackTherm grew from an MSc thesis model to a module design tool. Results on this page are **snapshots from the version named**: the model has changed since, so re-running the commands today gives different numbers. Current results are in the [README](../README.md); every change is in [CHANGELOG.md](../CHANGELOG.md).

## Versions

| Version | Scope |
|---|---|
| **v0.1** | Python port of the MATLAB thesis solver, parity tests, CI |
| **v0.2** | Electro-thermal heat generation, cell library (M50 21700, MJ1 18650), enthalpy-Newton solver, datasheet limit checks |
| **v0.3** | Design advisor: cooling × PCM sweep, feasibility (peak, ΔT, recovery), Pareto front, three picks, worst-case-resistance re-check, trade-off chart |
| **v0.3.1** | Continuous h with fan-law power, chiller, PCM grade library, WLTC and road-trip EV duties, iterative robustness, 2.6× faster solver |
| **v0.3.2** | Validation against measured temperatures (48 blind tests, 25 to −20 °C); equivalent-circuit electrical model with Butler–Volmer kinetics, voltage cut-off and CC-CV charging; validated Panasonic NCR18650PF cell |
| **v0.4** | Module level: packed unit cell (hex/square), air / PCM / composite-PCM filler, forced air, bottom plate, side ribbon, coolant rise with inlet/outlet cells, pump and fan power from flow |
| **v0.4.1** | Design advisor on the module model: flow, topology, filler and gap as design variables with physical pump/fan energy |
| **v0.4.2** | Rename to PackTherm, new model picture, housekeeping |
| **v0.4.3** | Cooling hardware mass from sourced geometry; ribbon gap and height coverage |
| **v0.4.4** | Chiller accounting: ambient-dependent COP, heat leak, chiller during the event only |
| **v0.4.5** | Whole-loop pump power and radiator fan energy |
| **v0.4.6** | Edge cells on the module wall, in the model and the advisor |
| **v0.4.7** | Coolant thermal mass in the channel |
| **v0.4.8** | 2D (radius × height) bottom-plate model |
| **v0.4.9** | Side ribbon on a strip of the can (radius × angle model) |
| **v0.4.10** | Cold-weather cell model: temperature laws for the low-SOC rise and slow branch (88 % of blind tests within 1 K) |
| **v0.4.11** | LG M50 equivalent circuit derived from a physics model (PyBaMM + ORegan2022); worst-case checks scale every loss term |
| **v0.4.12** | Audit: crash and message fixes, air cooling depends on the gap, rebuilt README, 2D field and validation figures |
| **v0.4.13** | Physics audit: laminar coolant channels and cross-flow air laws, in-cell spread measured on the cooled face, datasheet limits checked per phase and as currents, CLI input checks |
| **v0.5.0** | Fast and normal modes: fast is about 5× quicker with the same verdicts on the example studies; exact region volumes on every mesh |
| **v0.5.1** | Study files (YAML or JSON): `packtherm run`, `packtherm template`, results JSON; README numbers checked in CI |
| **v0.5.2** | User-defined cylindrical NMC/NCA cells from datasheet values, with unit-slip checks |
| **v0.5.3** | HTTP API (queue, progress, results, limits, API keys), Docker image; example studies re-run in CI |
| **v0.5.4** | LFP user-defined cells: measured thermal properties and graphite-dominated entropic heat; chemistry-specific checks |
| **v0.5.5** | Web app (React + TypeScript): study set-up form built from the study format, live checks, progress, interactive trade-off chart and design table, downloads and shareable result links |
| **v0.5.6** | Public site on GitHub Pages: PackTherm runs in the visitor's browser (Pyodide, parallel workers), checked against `packtherm run` in CI; release wheels with the web app |
| **v0.5.7** | Fixes from a full audit: a duty the cell cannot deliver (voltage cut-off) now fails instead of looking cool; chart downloads on the public site; results files re-run as study files; `--version` |
| **v0.6.0** | Cell test data: CSV and `.mat` reading, column, unit and sign detection, checks, and the test's parts labelled (`packtherm data`) |
| **v0.6.1** | Fitting the circuit model at one temperature (`packtherm fit`): fitted cell file with sources, 95% ranges, validity, errors and input hashes, and an HTML report; checked on known answers and on the Panasonic NCR18650PF |
| **v0.6.2** | Fitting across temperatures from a test list: values by temperature, a third circuit branch, drive cycles as fitting tests; fitted cells usable in studies, with warnings beyond their tested range; checked on 43 Panasonic tests the fit never saw |
| **v0.6.3** | The Samsung INR21700-30T fitted at six temperatures (−20 to 40 °C) and added to the library (`30T`); 82 tests it never saw: 27.7 mV median voltage error, 62% within 1 K. The middle branch's time constant set by the long tests where they fit better; the test rig (convection and fixture) calibrated on fitted tests. The Panasonic refitted: 24.4 mV, 81% within 1 K |
| **v0.6.4** | The LG INR18650-HG2 fitted blind with v0.6.3's method, run once, and added to the library (`HG2`); 74 tests it never saw: 59.7 mV median voltage error (22.0 mV at 25 °C), 89% within 1 K. It exposed one capacity for every temperature as the fitted cells' main limit. One data-preparation script for the McMaster datasets |
| **v0.6.5** | Open-circuit curves by temperature from slow tests at each, on one state of charge; the middle branch capped below the slow branch (120 s). The HG2's checks from 59.7 to 36.6 mV (93% within 1 K), the 30T's to 26.5 mV; the Panasonic 26.4 mV |
| **v0.6.6** | Fitting without a pulse test: the kinetics from the long tests' sudden changes in current. The 30T and HG2 refitted without their pulses: 29.4 and 35.4 mV on the same checks. The A123 ANR26650M1B (LFP) fitted blind at −15 to 45 °C and added to the library (`A123`): 4–7 mV on its profiles from 5 to 45 °C, 8.2 mV on a 4C-peak profile at 25 °C it never saw, about 100 mV at −12 °C; a C/30 charge 35–50 mV above the model (hysteresis) |
| **v0.6.7** | LFP hysteresis (a state between the charge and discharge branches, fitted from slow charges): the A123's held-out C/30 charge from 41.2 to 8.2 mV at 10–95%, its discharge profiles 1–4 mV worse. Datasheet temperature limits for the 30T, HG2 and A123, with warnings for charging (or discharging) below them; a warning below a fitted cell's tested state of charge; the tested C-rates of a fit without pulses fixed (the A123 had recorded no charge). Two attempts at the cold, neither shipped |
| **v0.6.8** | Fixes. The fit had ended long tests at the first dip below their knee, so cold drive cycles were fitted on seconds (the 30T's and HG2's −20 °C Mixed1 on 15 s): fixed, with the slow branch fitted down to 30% at least: the 30T to 25.7 mV, the HG2 unchanged at 36.6 mV (39.0 without the 30%). Hysteresis in two parts: the A123's warm profiles back to 4–7 mV, its held-out charge 8.1 mV. The HG2's hysteresis estimate's sign; notes where the tests don't pin the branch split; recovery in the cold; the cold-charge warning held over 30 s; the HG2's capacity noted. Not shipped: charge lost with rate (no gain), the rise near empty on charge (no gain) |
| **v0.6.9** | The LG M50 against the Warwick data, with a core thermocouple. Its derived circuit had half the real resistance (2C pulses: 130–200 mV against 270–400 mV); scaled ×2.04 on the pulses, 1C discharges it never saw come out at 18–40 mV (was 114–146) and the core within 0.7–1.4 K (was 2.2–3.2). Drive cycles 44 → 35 mV. A tenth of the radial conductivity ruled out (core 14–16 K above the surface against 2–3.5 K measured). Lumped models found to make about half the heat; the lumped and earlier cell versions listed apart, for comparison only. The design examples run hotter; the 1.5C discharge has no feasible design |
| **v0.6.10** | Patch after a check of every library cell: the PF and MJ1 got their lower temperature limits (no cold-charging warning before); a dip of hundredths of a kelvin below a limit is no longer reported |
| **v0.6.11** | The lumped model's slow losses, tuned by chemistry on the fitted cells: datasheet cells and the MJ1 make their circuits' heat within −31 to +19 % (was 22–64 % on a steady discharge); the M50's datasheet resistance gives 8.0–8.4 K on its measured 1C tests against 8–10.4 K (was 5.5–5.9) |
| **v0.6.12** | Coolant heat transfer and pressure drop from the channel shape (ht, fluids) and 50/50 glycol properties: plate about 650 W/m²K per can base and ribbon about 1,950 per bonded strip (both an assumed 1,500 before); channel pressure drop under 1 kPa (an assumed 20 kPa before). Road trip 24 of 39 feasible |
| **v0.6.14** | Design search with pymoo's NSGA-II (optional extra): flows, gap and chiller set-point as ranges, judged at worst-case resistance. Road trip: air at 0.43 % running energy against the grid's 1.91 %, with a wider gap |
| **v0.6.15** | Which inputs matter most: Morris screening (SALib, optional extra) of nine inputs around one design. Road trip's balanced ribbon: ambient about 9 K on the peak, interface and coolant heat transfer under 0.2 K |
| **v0.6.15.1** | Fix: cell-to-cell spread at the same moment, not the difference of peaks at different times; chilled road-trip designs from about 0 to up to 16.5 K, no verdicts changed |
| **v0.6.16** | Cells from BPX files (optional extras): size, mass, OCV and reversible heat from the file, a circuit derived in PyBaMM. LG M50 from Chen2020: 26.7 mΩ against 33.7 measured |
| **v0.6.13** | Battery life from NREL's BLAST-Lite ageing models: capacity left after 8 years of the duty once a day, parked at the ambient between; road trip at 35 °C 46–52 % sealed, 55–57 % for the cooled designs that pass |

## v0.3.1: single-cell design advisor

The first advisor treated each cell on its own, with a uniform h around it. It is still available as `packtherm design ... --level cell`.

```bash
packtherm design M50 --level cell --duty roadtrip --t-env 35 --out-dir results/
packtherm design M50 --level cell --duty wltc --cycles 3 --t-env 35
packtherm design M50 --level cell --c-rate 1.5
```

![Trade-off chart, LG M50 road trip at 35 °C (v0.3.1)](history/examples/m50_roadtrip_130kmh_35c_tradeoff.png)

```
LG INR21700 M50, 130 km/h 90%→10%, then 0.7C charge to 80% (96s35p), ambient 35 degC
Limits: T_peak <= 45 degC, in-cell dT <= 5 degC, ready again within 180 min
135 designs, 65 feasible, 1 on the trade-off front
Lightest       air h=10, no PCM: T_peak 40.5 degC, +32.7% mass, aux 0.04% of energy, recovery 39 min
Not picked     natural, no PCM: +19.3% mass, aux 0.00%, but fails (hot) at worst-case R0 = 43 mOhm (peak 46.6 degC)
Not picked     natural, RT42 2 mm: +35.7% mass, aux 0.00%, but fails (slow) at worst-case R0 = 43 mOhm (peak 41.4 degC)
```

**Design space**
- **Cooling:** natural convection; forced air at h = 10–60 W/m²K; liquid at h = 100–600, at ambient (radiator) or chilled to 15 °C. Fan and pump power followed a fan law P ∝ h^3.75 anchored to the thesis mid levels; chiller electricity = heat removed ÷ COP (3.0).
- **PCM:** none, or RT28HC, RT31, OM35 or RT42 at 2 or 4 mm, as a sleeve in a 1 mm aluminium tube.
- **Duties:** the WLTC Class 3b trace through a C-segment EV road-load model (146 Wh/km, 61 kWh 96s35p pack of M50 cells), and a road trip at 130 km/h from 90 % to 10 % then a rapid charge to 80 %.

**Findings at the time**
- On the 35 °C road trip, mild forced air (h = 10) was enough (peak 40.5 °C). A PCM that melts at or below ambient never re-solidifies without a chiller, so the melt point has to sit above the hottest ambient. This still holds in the module model.
- At 1.5C and 25 °C ([chart](history/examples/m50_discharge_1.5c_25c_tradeoff.png)), low-h liquid was the lowest-energy option.
- Chilled coolant at high h failed on in-cell spread: pulling a 25 °C cell down to 15 °C quickly created a gradient above 5 °C.
- WLTC at 35 °C ([chart](history/examples/m50_wltc3_35c_tradeoff.png)): a 60 kWh pack sees mild C-rates (mean 0.11C, peak 0.9C), so thermal design is driven by rapid charging and motorway driving, not urban cycles. This also still holds.

**Why it was replaced:** a uniform h around an isolated cell made natural and liquid cooling optimistic (an uncooled interior cell in a pack runs far hotter than one in free air), and the per-cell PCM sleeve added about 19 % of cell mass on its own. v0.4 moved to a packed module unit cell, and v0.4.1 moved the advisor onto it.

## v0.2: electro-thermal cells

- **Heat from real cells:** Q = I²R(SOC, T) − I·T·dU/dT(SOC), with coulomb-counted SOC and temperature feeding back into resistance every step.
- **Cell library** with every value sourced (`src/packtherm/cells.py`): LG M50 21700 (5 Ah, NMC811/graphite-SiOx, Chen 2020 and O'Regan 2022) and LG MJ1 18650. Jelly-roll heat capacity and radial conductivity are computed from O'Regan's measured layer properties.
- **Duty cycles:** constant C-rate, piecewise segments, or a CSV of current against time; charge windows such as 10→80 % respected.
- **Faster, exactly conservative solver:** Newton iteration on the enthalpy residual replaced the thesis Picard scheme, converging in about 2 iterations per step, about 3× faster, with the energy balance closed to round-off. The thesis scheme is kept as `SolverSettings(scheme="thesis")`.

**First design finding: PCM can make things worse.** LG M50 at 2.5C discharge, peak cell temperature (single cell, uniform h):

| Cooling | No PCM | 3 mm PCM |
|---|---|---|
| Air, h = 10 W/m²K | 65.2 °C | **53.4 °C** (PCM buffers the heat) |
| Air, h = 60 | **44.4 °C** | 46.4 °C |
| Liquid, h = 300 | **35.2 °C** | 43.5 °C (paraffin insulates the cell from the coolant) |

## v0.1: Python port of the thesis model

The thesis model was a 1D radial line from the cell centre (18650, r = 9 mm) through 3 mm of RT31-type paraffin to a 1 mm Al 6061 casing, solved with cell-centred finite volumes, harmonic-mean face conductivities, backward Euler, and an apparent-heat-capacity PCM iterated with under-relaxed Picard steps. Verification was an independent enthalpy balance (< 0.1 % error) plus mesh and time-step convergence studies.

The Python port reproduces the MATLAB results to about 1e-11 on every summary metric for the four thesis scenarios, and the mesh and time-step studies. The MATLAB code is kept in [`matlab/`](../matlab/) as the reference. `packtherm thesis` re-runs the scenarios with the v0.2 Newton solver: the same temperatures, with the energy balance closed to round-off instead of the errors below (`SolverSettings(scheme="thesis")` gives those).

| Scenario | Peak T (°C) | In-cell ΔT (°C) | Mean PCM liquid fraction | Fan/pump energy (Wh) | Energy-balance error |
|---|---|---|---|---|---|
| drive, air, mid (h=30) | 31.67 | 1.39 | 0.02 | 3.3 | 0.013 % |
| drive, liquid, low (h=100) | 31.09 | 1.43 | 0.005 | 1.7 | 0.0007 % |
| fast charge, air, high (h=60) | 36.81 | 2.07 | 0.32 | 40 | 0.003 % |
| fast charge, liquid, mid (h=300) | 33.56 | 2.09 | 0.07 | 40 | 0.001 % |

With liquid cooling the PCM barely melted (about 7 % used), so it added mass for little benefit; with weaker air cooling it did real work.

**Thesis figures** (from the MATLAB code):

| | |
|---|---|
| ![Model domain](history/figures/figure_3_1_model_domain.png) | ![Temperature histories](history/figures/figure_4_1_temperature_histories.png) |
| ![Mesh convergence](history/figures/figure_3_4_mesh_convergence.png) | ![Energy balance](history/figures/figure_4_6_energy_balance.png) |

All ten are in [`docs/history/figures/`](history/figures/).
