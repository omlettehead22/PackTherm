# Known issues and improvement backlog

Open items as of v0.6.9, ranked within each group by how much they could change a design recommendation. What has been fixed, and when, is in the [resolved log](#resolved-log) at the end and in [CHANGELOG.md](../CHANGELOG.md).

## Cell model
1. **LG M50: resistance measured at 25 °C only.** The circuit is derived from PyBaMM's DFN (ORegan2022); since v0.6.9 its loss terms are scaled ×2.04 to measured 2C pulses of six fresh cells (Warwick, CC BY 4.0), and it predicts their 1C discharges to 18–40 mV and the core to 0.7–1.4 K ([VALIDATION.md](VALIDATION.md#lg-m50-measured-v069)). Not checked: its temperature dependence (still the DFN's; the data is all at 25 °C), its cold voltage knee (late against the DFN at 0 °C), and near empty, where the scaled circuit drops about 55 mV too much on a 2C pulse. In the checks the heat arrives earlier in the discharge than the cell's, and the cell cools more slowly afterwards than the model (entropic heat near empty, or the holder's heat capacity). The drive profile with the core measured (one 2.4 GB file) is not read yet.
2. **Lumped-resistance cells.** The LG MJ1 and every user-defined cell (v0.5.2) use a lumped DC resistance with assumed temperature and SOC shapes and no voltage model; `packtherm cells` shows which model each cell uses. User-defined cells are NMC, NCA or LFP; NCA has no entropic heat, and LFP's thermal and entropic values are literature data (its entropic fit understates the measured mid-charge peak, and the coefficient's temperature dependence near full and empty is not modelled). A full circuit fitted from a user's own tests at three temperatures or more (v0.6.2, `packtherm fit`) replaces this in studies.
3. **Cold drive-cycle heat is 7–10 % low** on the validated PF cell: the slow-branch temperature law, fitted at 0.3C, is slightly too gentle at drive-cycle currents (worst peak −3.5 K at −20 °C).
4. **NCA entropic heat is neglected** (no dU/dT data in the dataset; published NCA profiles disagree on the sign). The PF charge is under-predicted by 1.1–1.4 K.
5. **Core temperature: checked on one cell.** On the LG M50 (v0.6.9) the core runs 2–3.5 K above the surface at the end of a 1C discharge; the model, with the assumed radial conductivity (1.2 W/(m K)), has 1.7–2 K, and a tenth of it (0.12, which the Samsung 30T and LG HG2 fits allowed) gives 14–16 K, ruled out. The effective value is nearer 0.6–1 W/(m K): the library value may be somewhat high, so cores could run about 1 K hotter at 1C than PackTherm predicts. On the 30T and HG2 the low fitted values stood in for something the model lacks (the fixture's heat capacity, which the fit ships, or the case thermocouple's lag). Faster transients and other cells are not checked.
6. **Fitted cells run about 1 K cold at their temperature peaks** on the Panasonic drive cycles (median, 0 to 25 °C), against about 0 K for the hand-tuned library cell. The shortfall is in the last minutes near empty: the voltage collapses faster than the rise near empty (an exponential in the state of charge) can follow. Below 0 °C the fitted slow branch sits at the edge of its range on both fitted cells: the cold long tests do not pin it down. At −20 °C the 30T's R0 comes out below its −10 °C value, and its checks there are 78.5 mV (median) against 13–28 mV from 40 to 0 °C. A different shape for the rise near empty, more cold drive cycles, and a generic circuit with a chosen number of branches would each help ([FITTING.md](FITTING.md#known-limits)).

7. **Capacity that falls with rate, not only with temperature.** The A123 (LFP, v0.6.6) shows it more strongly in the cold: at −12 °C its drive profiles collapse to 2.3 V with 12% left by the −15 °C C/30 curve, and the model runs 180–270 mV high below 25% (its checks there are about 100 mV). Its rise near empty sits at its limit (`soc_b` 0.5) at four temperatures, so the rise's shape is part of it. v0.6.8 found the fit had been ending cold drive cycles at their first dip below the knee (seconds in), fixed (the slow branch now fitted down to 30%, below which the A123's cold checks show the cell still running out first); a third attempt, charge lost with rate as a surface state of charge, fitted to zero on the 30T and HG2 and didn't ship. Charging from empty on the A123 is the open-circuit curve below about 7% (the rise near empty on charge didn't help). Two attempts in v0.6.7 didn't ship: a "surface" state of charge (the slow branch's held charge taken off) gained about 5% at −12 °C; fitting the rise on the long tests alone brought the −12 °C checks to 70 and 54 mV but sent the −5 and 5 °C values to their bounds. LFP hysteresis is modelled from v0.6.7; charging from empty still runs about 200 mV low over its first 10% on the A123, and with hysteresis its branch values are less physical (its rate at its 100 per Ah bound). Since v0.6.5 a fitted cell has an open-circuit curve at each temperature with a slow test, and its middle branch stays below the slow branch's range (120 s). The LG HG2's checks went from 59.7 to 36.6 mV median. What is left: at 40 °C the HG2 delivers 2.50 Ah at 1C against 2.69 Ah at C/20, more than its fitted losses explain, and its 1C discharge there runs up to 180 mV high near the end. At 10 and 0 °C the middle branch sits at its 120 s cap with no slow branch, so the split between them is not pinned (the voltage is). And at −10 and −20 °C the checks are still 60–70 mV.

## Module model
8. **Roll-end-to-can resistance** (5e-4 m²K/W) dominates bottom-plate cooling and is the least certain value. A teardown or a bottom-cooling test would pin it down.
9. **Reference flows and pressure drops are typical values, not a specific pack:** coolant 0.05 g/s per cell, h_ref 1500 W/m²K, module Δp 20 kPa plus loop 30 kPa, pump efficiency 0.3; air 0.3 g/s, h 30 W/m²K and Δp 200 Pa at a 2 mm gap. Only the scaling away from these points is physics (since v0.4.13: laminar coolant channels, cross-flow over the cans for air). The air correlation is used below its usual pitch range (pitch/diameter 1.1 against ≥ 1.25), and the ribbon's h_ref is not tied to its port geometry.
10. **2D slices, not a 3D field.** The plate is solved in radius × height and the ribbon in radius × angle, separately. The ribbon displaces filler near the strip, but the angle model fills the full annulus.
11. **Coolant holdup is one lump per cell**, not a transport delay, so a sharp inlet step arrives smeared rather than delayed.
12. **Edge cells use an assumed wall** (U = 5 W/m²K over 1/3 of the share). With air gaps the wall is applied at the can, which slightly overstates the edge path. The chiller's heat leak and the edge wall are separate estimates of the same physics, and the leak is charged to the chiller but does not warm the cells.
13. **Not modelled:** tab heating, top-side (tab/busbar) cooling, cell holders and module structure (not charged to any option).

## Energy and hardware assumptions
14. **Chiller:** the Carnot share (0.42) and the 9 h pack time constant are single-source assumptions; idle losses and the condenser fan are not modelled.
15. **Radiator fan at 3 % of rejected heat** is an assumption; ram air at speed would make it smaller.
16. **Pack-level parts** (liquid loop 3 kg, air system 4 kg, chiller 4 kg) are assumptions.

## Advisor and product
17. **Ageing as a third objective.** Temperature drives calendar and cycle ageing. Scoring designs on predicted capacity fade would show what "hotter but lighter" costs in battery life. Probably the highest-value product feature.
18. **Cost objective (£/pack):** PCM £/kg, cooling hardware, chiller.
19. **Cold climate:** pre-heating energy and cold-start limits, not just cooling.
20. **Speed.** Fast mode (v0.5.0) runs the road-trip study in about 40 s on two cores, against about 3 minutes in normal mode. Not yet done: adaptive time steps (long steady cruise and rest periods would allow much longer steps), stopping a simulation once the cell has recovered, and compiled inner loops (Numba). A design is four cell simulations in a Python time loop, so more cores help directly.
21. **Search instead of grid** once the design variables multiply (NSGA-II or Bayesian optimisation).
22. **Uncertainty:** Monte Carlo over the assumptions instead of a single worst case.
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
