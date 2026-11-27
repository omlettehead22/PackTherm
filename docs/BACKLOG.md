# Known issues and improvement backlog

Open items as of v0.6.9, ranked within each group by how much they could change a design recommendation. What has been fixed, and when, is in the [resolved log](#resolved-log) at the end and in [CHANGELOG.md](../CHANGELOG.md).

## Cell model
1. **LG M50: resistance measured at 25 °C only.** The circuit is derived from PyBaMM's DFN (ORegan2022); since v0.6.9 its loss terms are scaled ×2.04 to measured 2C pulses of six fresh cells (Warwick, CC BY 4.0), and it predicts their 1C discharges to 18–40 mV and the core to 0.7–1.4 K ([VALIDATION.md](VALIDATION.md#lg-m50-measured-v069)). Not checked: its temperature dependence (still the DFN's; the data is all at 25 °C), its cold voltage knee (late against the DFN at 0 °C), and near empty, where the scaled circuit drops about 55 mV too much on a 2C pulse. In the checks the heat arrives earlier in the discharge than the cell's, and the cell cools more slowly afterwards than the model (entropic heat near empty, or the holder's heat capacity). On three cells' drive cycles (v0.6.9) it is within 34–36 mV, most of it the open-circuit curve (15–35 mV low at rest): the curve is the M50T's published table, not this cell's. The drive file's temperatures have no clock shared with its current, so they are not used.
2. **Lumped-resistance cells.** Since v0.6.11 the lumped model adds slow losses by chemistry (+88 % of the DC resistance under steady current for NMC/NCA, +160 % for LFP, building over 4–7 minutes), tuned on the fitted cells: its heat is within −31 to +19 % of their circuits' over steady, pulsed, drive and charge duties from −10 to 25 °C (LFP −42 to +27 %: its resistance depends on current more than a lumped model follows), where it was 22–64 % on a steady discharge. On the M50's measured 1C discharges (never tuned on) the datasheet 30 mΩ gives 8.0–8.4 K against 8–10.4 K. Left: the spread of ±20–30 %, LFP tuned on one cell, and no voltage limits. The LG MJ1 and every user-defined cell (v0.5.2) use a lumped DC resistance with assumed temperature and SOC shapes and no voltage model; `packtherm cells` shows which model each cell uses. User-defined cells are NMC, NCA or LFP; NCA has no entropic heat, and LFP's thermal and entropic values are literature data (its entropic fit understates the measured mid-charge peak, and the coefficient's temperature dependence near full and empty is not modelled). A full circuit fitted from a user's own tests at three temperatures or more (v0.6.2, `packtherm fit`) replaces this in studies.
3. **Cold drive-cycle heat is 7–10 % low** on the validated PF cell: the slow-branch temperature law, fitted at 0.3C, is slightly too gentle at drive-cycle currents (worst peak −3.5 K at −20 °C).
4. **NCA entropic heat is neglected** (no dU/dT data in the dataset; published NCA profiles disagree on the sign). The PF charge is under-predicted by 1.1–1.4 K.
5. **Core temperature: checked on one cell.** On the LG M50 (v0.6.9) the core runs 2–3.5 K above the surface at the end of a 1C discharge; the model, with the assumed radial conductivity (1.2 W/(m K)), has 1.7–2 K, and a tenth of it (0.12, which the Samsung 30T and LG HG2 fits allowed) gives 14–16 K, ruled out. The effective value is nearer 0.6–1 W/(m K): the library value may be somewhat high, so cores could run about 1 K hotter at 1C than PackTherm predicts. On the 30T and HG2 the low fitted values stood in for something the model lacks (the fixture's heat capacity, which the fit ships, or the case thermocouple's lag). Faster transients and other cells are not checked.
6. **Fitted cells run about 1 K cold at their temperature peaks** on the Panasonic drive cycles (median, 0 to 25 °C), against about 0 K for the hand-tuned library cell. The shortfall is in the last minutes near empty: the voltage collapses faster than the rise near empty (an exponential in the state of charge) can follow. Below 0 °C the fitted slow branch sits at the edge of its range on both fitted cells: the cold long tests do not pin it down. At −20 °C the 30T's R0 comes out below its −10 °C value, and its checks there are 78.5 mV (median) against 13–28 mV from 40 to 0 °C. A different shape for the rise near empty, more cold drive cycles, and a generic circuit with a chosen number of branches would each help ([FITTING.md](FITTING.md#known-limits)).

7. **Capacity that falls with rate, not only with temperature.** Fixed on the A123 in v0.6.17 by an excess-polarisation branch, losses beyond the slow tests' current that grow steeply in the cold and at low charge ([FITTING.md](FITTING.md#the-cold-and-charging-from-empty-v0617)). Its −12 °C checks went from 96 and 84 to 36 and 24 mV, and its charge from empty from 96 to 14 mV (mostly a check that started 2 % off). Solid diffusion, two particle groups and a linear branch were tried first and didn't ship. What is left: the branch is fitted on drive profiles averaging about 0.1C at low charge, and beyond that it is linear in the current, unchecked (studies warn). A cold test run to empty at a sustained 0.5–1C, with real self-heating, would check it and show what it does to the heat. It is fitted on one LFP cell only: the HG2 and 30T (off for both) still have −10 and −20 °C checks of 50–76 mV, and the HG2 at 40 °C delivers 2.50 Ah at 1C against 2.69 Ah at C/20, more than its fitted losses explain (180 mV high near the end). Trying the branch on them is next. At 10 and 0 °C the HG2's middle branch sits at its 120 s cap with no slow branch, so the split between them is not pinned (the voltage is).

## Module model
8. **Roll-end-to-can resistance** (5e-4 m²K/W) dominates bottom-plate cooling and is the least certain value. A teardown or a bottom-cooling test would pin it down.
9. **Reference flows and pressure drops:** since v0.6.12 the coolant's h and the module channels' pressure drop come from the channel shape, flow and glycol properties (ht, fluids), with assumed shapes (plate channels 10 × 4 mm under half the footprint; 21 ribbon ports of 1.7 × 2.15 mm) and 20 cells per coolant path. Still assumed: 0.05 g/s per cell as the flow reference for the rest of the loop (30 kPa), pump efficiency 0.3; air 0.3 g/s, h 30 W/m²K and Δp 200 Pa at a 2 mm gap (the air correlation is used below its usual pitch range, pitch/diameter 1.1 against ≥ 1.25). No measured cold plate checks the coolant side yet.
10. **2D slices, not a 3D field.** The plate is solved in radius × height and the ribbon in radius × angle, separately. The ribbon displaces filler near the strip, but the angle model fills the full annulus.
11. **Coolant holdup is one lump per cell**, not a transport delay, so a sharp inlet step arrives smeared rather than delayed.
11a. **Fixed in v0.6.15.1: cell-to-cell spread compared peaks at different times** (found in v0.6.15). `cell_to_cell_K` is the outlet cell's peak minus the inlet cell's. With a chiller, the inlet cell's peak is its starting temperature (the ambient), since it only cools from there, while the outlet cell peaks near the end, so the spread is understated. A 1.5C discharge at 30 °C with a ribbon chilled to 20 °C (fast mode): 8.2 K reported, 11.5 K at the end of the discharge, when the two cells are furthest apart. Now the largest difference at the same moment.
12. **Edge cells use an assumed wall** (U = 5 W/m²K over 1/3 of the share). With air gaps the wall is applied at the can, which slightly overstates the edge path. The chiller's heat leak and the edge wall are separate estimates of the same physics, and the leak is charged to the chiller but does not warm the cells.
13. **Not modelled:** tab heating, top-side (tab/busbar) cooling, cell holders and module structure (not charged to any option).

## Energy and hardware assumptions
14. **Chiller:** the Carnot share (0.42) and the 9 h pack time constant are single-source assumptions; idle losses and the condenser fan are not modelled.
15. **Radiator fan at 3 % of rejected heat** is an assumption; ram air at speed would make it smaller.
16. **Pack-level parts** (liquid loop 3 kg, air system 4 kg, chiller 4 kg) are assumptions.

## Advisor and product
17. **Ageing.** Since v0.6.13 every design reports the capacity left after `life_years` (NREL's BLAST-Lite models, copied in) and can be limited on it. Left: the cell's temperature for ageing is the mean of its hottest and coolest points (not a volume average); the day repeats the hot-day study every day (no climate year); BLAST-Lite has models for the M50 and MJ1 only among the library cells, so the 30T, HG2, PF, A123 and user cells use a stand-in by chemistry; and ageing does not feed back into the resistance during the study. Not yet an objective on the trade-off chart.
18. **Cost objective (£/pack):** PCM £/kg, cooling hardware, chiller.
19. **Cold climate:** pre-heating energy and cold-start limits, not just cooling.
20. **Speed.** Fast mode (v0.5.0) runs the road-trip study in about 40 s on two cores, against about 3 minutes in normal mode. Not yet done: adaptive time steps (long steady cruise and rest periods would allow much longer steps), stopping a simulation once the cell has recovered, and compiled inner loops (Numba). A design is four cell simulations in a Python time loop, so more cores help directly.
21. **Search instead of grid.** Since v0.6.14 a study can search (pymoo's NSGA-II for mixed variables) with flows, gap and chiller set-point as ranges. Left: the search runs in fast mode, so a design near a limit can rank differently in normal mode (the best are re-run in normal mode, but one the search ranked out is not); the web app and the API don't offer it yet; geometry (channel shape, ribbon ports, cell pitch beyond the gap) is not a variable; and a budget of a few hundred designs is minutes on two cores, so Bayesian optimisation would suit larger spaces.
22. **Uncertainty.** Since v0.6.15 a study can rank which inputs matter most for one design (Morris screening with SALib, nine inputs). Left: Sobol indices (shares of the variance, about ten times the simulations), Monte Carlo over the assumptions for a spread of each result rather than a single worst case, more inputs (pack-level parts, chiller and radiator efficiencies, PCM properties), and the web app and API.
23. **Assumption registry.** Since v0.5.1 a results JSON carries the main assumptions (reference flows and pressure drops, efficiencies, chiller, wall, pack parts, resolution). Not yet: the cell-model and material values, and the CSV on its own carries none.

## Engineering
24. **API at scale.** One server process holds the job queue in memory, results are files kept 24 h, and the rate limit is per process. Several servers, or results that survive longer, would need a shared queue and store (e.g. Redis and object storage). Fine for one public instance.
25. Publish to PyPI, add versioned docs.
26. **Licence: on hold.** No licence for now (all rights reserved by default), which keeps the option of going proprietary. Needed before publishing to PyPI.

## Resolved log

| Version | Resolved |
|---|---|
| v0.3.1 | Fan/pump energy now counted through recovery; datasheet C-rate check in studies; robustness margin when nominal R is already the maximum; no fragile pick when every front design fails the re-check; bounded memory; sink temperature independent of the start temperature (chiller possible) |
| v0.3.2 | Validation on the NCR18650PF: equivalent circuit with Butler–Volmer kinetics and a slow branch, CC-CV taper, OCV from the discharge branch, low-SOC rise (discharge only), charge past SOC 1 handled by CV |
| v0.4 | Isolated-cell assumption replaced by a packed module unit cell; PCM and composite PCM fill the gaps instead of a per-cell sleeve |
| v0.4.1 | Advisor moved onto the module model; pump and fan power from flow and pressure drop |
| v0.4.3 | Cooling hardware mass from sourced geometry instead of flat kg/kWh |
| v0.4.4 | Chiller COP falls with ambient; heat leak charged; chiller hands back to the radiator |
| v0.4.5 | Whole-loop pump power; radiator fan charged |
| v0.4.6 | Edge cells on the module wall |
| v0.4.7 | Coolant thermal mass in the channel |
| v0.4.8 | 2D radius × height bottom-plate model |
| v0.4.9 | Ribbon cools a strip of the can (radius × angle model) instead of a uniform contact |
| v0.4.10 | Cold-weather temperature laws for the low-SOC rise and slow branch (88 % of blind tests within 1 K) |
| v0.4.11 | LG M50 circuit derived from the DFN; worst-case re-check scales every loss term |
| v0.4.12 | Audit: duplicate-design crash, contradictory messages, CLI header and flags, air cooling now depends on the gap |
| v0.4.13 | Physics audit: laminar coolant and cross-flow air laws, in-cell spread on the cooled face, per-phase datasheet temperature checks, datasheet limits as currents, MJ1 charge limits, CLI input checks |
| v0.5.0 | Fast mode (about 5×); exact region volumes on every mesh; faster electrical model |
| v0.5.1 | Study files and results JSON; README numbers checked against the examples in CI |
| v0.5.2 | User-defined cylindrical cells (NMC/NCA) from datasheet values |
| v0.5.3 | HTTP API; example studies re-run in CI |
| v0.5.4 | LFP user-defined cells |
| v0.5.5 | Web app |
| v0.5.6 | Public site with the in-browser engine; release wheels |
| v0.5.7 | Fixes from a full audit |
| v0.6.0 | Cell test data reading |
| v0.6.1 | Circuit fitting at one temperature; the charge counter used across steps between samples |
| v0.6.2 | Fitting across temperatures, a third branch, fitted cells in studies; two branches no longer the limit (item 6 rewritten) |
| v0.6.3 | The Samsung 30T fitted and in the library; the middle branch's time constant no longer left loose by the pulses; the test rig calibrated for the thermal checks (items 5 and 6 updated) |
| v0.6.4 | The LG HG2 fitted blind and in the library; one data-preparation script for the McMaster datasets (item 7 added: capacity by temperature; item 5 updated) |
| v0.6.5 | Open-circuit curves by temperature from slow tests at each; the middle branch capped at 120 s, below the slow branch (item 7 rewritten) |
| v0.6.9 | LG M50 against measured data: resistance scaled to measured pulses, the core checked against a thermocouple inside the cell (item 1 narrowed, item 5 checked on one cell) |
| v0.6.10 | Lower temperature limits for the PF and MJ1; no warning for a dip of hundredths of a kelvin below a limit |
| v0.6.11 | The lumped model's slow losses (item 2): datasheet cells and the MJ1 make their fitted circuits' heat within −31 to +19 % (was 22–64 %) |
| v0.6.12 | Coolant h and channel pressure drop from the channel shape (item 9) |
| v0.6.17 | The cold fixed on the A123 with an excess-polarisation branch; charge checks started from their full end (item 7 rewritten) |
