# Changelog

## 0.6.15.1

Fix: the cell-to-cell spread is now the largest difference between the hottest and coolest cells at the same moment. Up to v0.6.15 it was the hottest cell's peak minus the coolest cell's peak, and those can come at different times (found while testing v0.6.15, BACKLOG item 11a).

- **What was wrong:** with a chiller, every cell starts at the ambient and is cooled from there, so the inlet cell's peak is its starting temperature, and often so is the outlet cell's. On the 35 °C road trip the chilled ribbon designs were reported at about 0 K, while during the chiller's pull-down the inlet and outlet cells are up to 16.5 K apart. Without a chiller the error was smaller but in the same direction: the inlet cell peaks early and cools while the outlet cell keeps warming.
- **Now:** at each time step, the hottest of the outlet cells (interior and edge) minus the coolest of the inlet cells, over the time all of them were simulated (`module_design.cell_to_cell_spread`); `packtherm module --compare` likewise. The new value is at least the old one (to within 0.01 K, from interpolating between time steps).
- **Example studies re-run.** No verdicts or picks changed; none of them limits the cell-to-cell spread.
  - Road trip and 3 × WLTC at 35 °C: chilled designs from about 0 to 4–17 K (up 11 K on average); unchilled within 0.1 K.
  - 1.5C discharge at 25 °C: chilled designs up by 2–7 K, unchilled by 1–5 K.
  - The search and sensitivity examples: the same designs and picks; in the sensitivity ranking the cell-to-cell spread's order is unchanged (`mu_star` within 0.07 K).
  - The module comparison (`docs/examples/m50_module_1.5c_25c.csv`, README table): forced air 4.9 → 6.1 K, bottom plate 6.8 → 9.0 K, side ribbon 13.0 → 16.4 K; with RT31 in the ribbon's gaps 10.8 → 13.6 K.
- **Fast mode:** its largest cell-to-cell difference from normal mode is now 0.77 K (1.5C discharge), was 0.56; FAST_MODE.md and the example re-run test's tolerance (1.0 K) updated.
- **Tests:** the spread by hand (an outlet warming while the inlet is cooled: 20 K at the same moment where the peaks differ by 10), and a chilled design's spread clearly above the difference of its peaks.

## 0.6.15

Which inputs matter most: a study can rank the uncertain inputs around one design by how much each moves its results, with Morris screening from SALib (an optional extra: `pip install "packtherm[sensitivity]"`).

- **New: `packtherm/sensitivity.py`** and a study-file `sensitivity:` section. The design is a pick of the grid study (`balanced` by default; the grid runs first) or named. Nine inputs, each over a default range you can change: ambient (±5 K), cell resistance (its own to the worst case), cell heat capacity (×0.9–1.1), cell conductivity (×0.7–1.3), reversible heat (×0.5–1.5), interface conductivity (×0.5–1.5), air or coolant heat transfer (×0.7–1.3), flow (×0.8–1.2) and chiller set-point (±3 K); only those that apply to the design are varied.
- **Results:** for peak temperature, in-cell spread, cell-to-cell spread, running energy and capacity left, each input's `mu_star` (about how much the result changes across the input's range) and `sigma` (whether that depends on the other inputs). Files: results JSON, ranking CSV, every simulation's inputs and results, and a chart with one panel per result.
- **New: `Coolant.h_scale`**, a multiplier on the coolant h (default 1: results unchanged).
- **Example** (`docs/examples/m50_roadtrip_35c_sensitivity.yaml`): the road trip's balanced design, a ribbon at 0.05 g/s, at 35 °C. 90 simulations in about 2 minutes on two cores; 82 of them pass (8 run hot at the top of the ambient range).
  - Peak temperature: ambient about 9 K across its ±5 K, cell resistance 1.5 K, flow 1.2 K; the interface material and the coolant heat transfer under 0.2 K each. Without a chiller the heat ends up in the 35 °C air, so that sets the peak rather than the path to the coolant.
  - In-cell spread: the cell's own conductivity (0.55 K), then its resistance.
  - Capacity left: the ambient, about 9 percentage points; nothing else moves it by more than 0.1.
- **Where it runs:** the command line and Python. The web app and the API refuse a study with a `sensitivity` section for now. SALib needs numpy 2; the core still runs on numpy 1.24.
- **Found while testing:** the cell-to-cell spread compares the outlet and inlet cells' peaks, which can come at different times, and understates it for chilled designs (BACKLOG item 11a, to fix in a patch).
- **Tests:** which inputs apply to which design, each input moving what it names (and the scaled dU/dT surviving worker processes), a small screening ranking ambient first for an air design, a grid pick as the design, the study-file section, the API and browser refusing it, and the stored example ranking matching its samples.

## 0.6.14

Design search: instead of simulating every combination, a study can search the design space with pymoo's NSGA-II (an optional extra: `pip install "packtherm[search]"`).

- **New: `packtherm/search.py`** and a study-file `search:` section. The design space's numeric lists become ranges: air and coolant flows on a log scale between the smallest and largest listed, the gap (to 0.1 mm) and the chiller (off, or a set-point to 0.5 °C below ambient). Cooling types and fillers stay choices. pymoo's `MixedVariableGA` with rank-and-crowding survival (NSGA-II for mixed variables) minimises the objectives (`mass` and `energy` by default; `volume` and `life` can be added) with one constraint per limit (peak, in-cell spread, recovery, cell-to-cell, delivery, capacity), each positive by how far it is missed and agreeing with `fail_reason`.
- **Judged at worst-case resistance.** A first version searched at the cell's resistance: on a test study 11 of its 12 best designs then failed the picks' re-check. The search now simulates at the worst-case resistance (`worst_case: true`), then runs its best designs (`final_designs`, 12) again in the study's mode at the cell's resistance and makes the picks and re-check as a grid study does.
- **Settings:** `evaluations` (200), `population` (20), `seed` (1: the same seed gives the same search), `mode` (`fast` during the search), `final_designs`, `objectives`, `worst_case`. A design the search returns to is not simulated again.
- **Output:** a search writes `<stem>_search_…` files beside a grid study's, plus `<stem>_search_simulated.csv` with every design it simulated; the results document gains a `search` block, and a note says how it ran.
- **Example** (`docs/examples/m50_roadtrip_35c_search.yaml`, 35 °C road trip): 172 designs simulated in about 6 minutes on two cores, all 12 re-run designs feasible, and the 3 on the trade-off front still pass at worst-case resistance.
  - Lightest: air at 0.246 g/s with a 3.5 mm gap, 0.43 % running energy, where the grid's best air design (0.3 g/s, 2 mm) needs 1.91 %. The wider gap lowers the pressure drop for no added mass, but the module is about 50 % larger by volume instead of 32 %: add `volume` to the objectives when the gap is free.
  - Balanced: a ribbon at 0.032 g/s, 0.10 % (the grid's 0.05 g/s ribbon: 0.14 %).
  - Lowest energy: a ribbon at 0.028 g/s with RT42, 0.10 %. The grid's 0.02 g/s ribbon with RT42 needs 0.09 %: the search missed that corner.
- **Where it runs:** the command line and Python. The web app's in-browser engine and the API refuse a study with a `search` section for now (pymoo's moocore is compiled and has no browser build, and a search is hundreds of simulations).
- **Tests:** variables to designs by hand, constraints against `fail_reason`, the ranking of the best designs, a small search end to end (its picks robust, the search at worst case and the final rows at the cell's resistance), the study-file section, and the API and browser refusing it. The `dev` extra includes pymoo, so CI runs them.

## 0.6.13

Battery life: each module design reports the capacity left after some years of its duty, from NREL's BLAST-Lite ageing models.

- **New: `packtherm/life.py`.** One day is the duty as simulated (the cell's state of charge, and its temperature halfway between its hottest and coolest points), then parked for the rest of 24 h at `life_park_C` (default: the study's ambient) and the state of charge it ended at. BLAST-Lite's calendar and cycle ageing models run that day for `life_years` (default 8).
- **Models:** the LG M50 and MJ1 have their own (NMC811 / graphite-Si). The others use the closest model by chemistry and say so in `life_model`: the Panasonic 18650B for NCA (the NCR18650PF), the Sony-Murata 3 Ah 26650 for LFP (the A123), and the M50's for other NMC cells (30T, HG2, user cells).
- **BLAST-Lite is copied in** (`packtherm/_vendor/blast`, BSD 3-clause, licence and notice kept; upstream commit 991591726c07), rather than a dependency: its package pins Python ≤ 3.13 and numpy < 2 and pulls in weather-data packages. Only the models and the rainflow counter are copied. Changes: relative imports, no plotting, and a stand-in for `np.trapz` (removed in numpy 2.4, which breaks upstream too). A test checks the copy gives upstream's capacity on a test day to 1e-12 for all four models.
- **Study files:**
  - `options.life_years` (0: no estimate) and `options.life_park_C`;
  - `requirements.capacity_min_pct`: designs keeping less fail with `ages`; null (default) reports only.
- **Results:** `capacity_after_pct`, `life_years` and `life_model` on every design; the CLI summary gives each pick's capacity; the web app has a "Capacity left" column and shows it on the pick cards.
- **Example studies re-run** (verdicts unchanged). Road trip at 35 °C: 46–52 % left after 8 years sealed, 55–57 % for every cooled design that passes. 3 × WLTC at 35 °C: 69–70 %. 1.5C discharge at 25 °C: 62–71 %. Between passing designs life hardly differs: most of each day is parked at the ambient.
- **Limits** (BACKLOG item 17): every day is the study's day (a hot-day study ages the cell as if every day were hot), so compare designs with it rather than read it as the car's life; ageing does not raise the resistance during the study.

## 0.6.12

The liquid coolant's heat transfer and pressure drop come from the channels' shape, the flow and the coolant's properties, using two new dependencies: ht and fluids (Caleb Bell, MIT, pure Python).

- **Changed: coolant h per channel shape** (`packtherm/channels.py`). Up to v0.6.11 every cold plate and ribbon got an assumed 1500 W/(m² K) at 0.05 g/s per cell, scaled by an assumed flow exponent. Now:
  - laminar rectangular passages, fully developed (Shah and London, by aspect ratio) with Hausen's thermal-entry rise;
  - Gnielinski when turbulent, blended between Re 2300 and 3000;
  - fin efficiency for the walls and ribs;
  - the result is taken per area through which the cell is cooled.
- **What it gives:**
  - Bottom plate (10 × 4 mm channels under half the footprint): about 570–720 W/(m² K) per can base, depending on flow and coolant temperature. Its in-cell spread falls (8.2 K at 1.5C, was 9.1) and its cells run 0.3–4 K warmer.
  - Side ribbon (21 ports of 1.7 × 2.15 mm): about 1,890–1,980 per bonded strip, so ribbon designs barely change.
  - The channels are laminar (Re about 1–50).
- **Changed: the module channels' pressure drop** comes from Shah and London's laminar friction (and fluids' turbulent friction). For a path of 20 cells it is under 1 kPa, rising sevenfold from 25 to −20 °C with the glycol's viscosity. Up to v0.6.11 it was an assumed 20 kPa. The rest of the loop (hoses, manifolds, chiller, radiator) is still an assumed 30 kPa at 0.05 g/s per cell, so pump power fell from 7.9 to 4.7 mW per cell at that flow.
- **Coolant properties:** 50/50 ethylene glycol by mass, tabulated from CoolProp's MEG[0.5] (`data/meg50_properties.csv`, written by `validation/coolant_properties.py`; CoolProp is needed only for that). Heat capacity 3338 J/(kg K) at 25 °C (was 3500), so the coolant warms about 5 % more.
- **New assumptions:**
  - `Coolant.cells_per_channel`: 20 cells in series along one coolant path;
  - `PlateGeometry.channel_width_mm`: 10 mm;
  - `Coolant.h_override` replaces the computed h.
  - Removed: `h_ref`, `h_flow_exponent` and `dp_ref_Pa` on the coolant.
- **Design results:**
  - **Road trip:** 24 of 39 feasible (was 23). The lightest cold plate (0.02 g/s) now runs over the limit (45.4 °C), while the 0.05 g/s chilled plates now pass. Lowest energy pick: a ribbon with RT42 at 0.02 g/s (0.09 %); balanced pick: a ribbon at 0.05 g/s (0.14 %).
  - **3 × WLTC:** within 1.2 K of ambient.
  - The 1.5C discharge still has no feasible design.
- **Browser engine:** the site serves ht and fluids' wheels beside PackTherm's (`py/manifest.json` lists them).
- **Tests:** a square duct's Re, f Re and Nu by hand; h hardly changing with flow (laminar); pressure drop proportional to flow and rising with viscosity in the cold.

## 0.6.11

The lumped model's slow losses: datasheet cells and the MJ1 make about the right heat.

- **Changed: lumped cells add slow losses.** A DC resistance read over seconds misses the losses that keep building over minutes (diffusion): on a steady discharge a lumped model made 22–64 % of the fitted circuit's heat. The lumped model now carries a slow branch, a first-order overpotential that under steady current builds to +88 % of the DC resistance with a 7-minute time constant (NMC and NCA; LFP: +160 %, 4 minutes) and fades in rests. It has its own temperature dependence (26 kJ/mol; LFP 36).
- **How it was set:** tuned so lumped models of the PF, 30T and HG2 (NMC/NCA) and of the A123 (LFP), from their 10 s DC resistance, make the heat of their fitted circuits over steady discharges (0.5–2C), 2C pulses, a measured drive cycle and a 0.5C charge at 25 to −10 °C (`validation/tune_lumped_slow.py`). Lumped heat over circuit heat moved from 0.33–1.05 to 0.69–1.19 (NMC/NCA) and from 0.16–0.68 to 0.58–1.27 (LFP).
- **Checked, never tuned on:**
  - The M50's circuit: 0.98–1.42 (above 1.15 only on 2C pulses).
  - The M50's measured 1C discharges, with the datasheet's 30 mΩ: surface rise 8.0–8.4 K against 8–10.4 K measured (was 5.5–5.9); surface RMS 0.8–1.1 K (was 1.0–2.1); core 0.9–1.7 K (was 2.0–3.0).
- **Who it changes:** user-defined datasheet cells (by their chemistry), the MJ1 and the lumped comparison versions. Circuit cells (the M50, PF, 30T, HG2, A123 and fitted cell files) are unchanged, and so are the example studies. A datasheet cell's summary (`packtherm cells my_cell.yaml`, the web app) shows the slow losses.
- **Tests:** hand calculations for the branch (energy held at a constant current; its decay in a rest).

## 0.6.10

A small patch from a check of every library cell after v0.6.9 (discharges at 0.2–2C from −20 to 40 °C, charges at 0.3–0.7C from 0 to 40 °C, and fast studies of every duty type at −10, 0, 25 and 40 °C: no errors, results as expected).

- **Fixed: the Panasonic NCR18650PF and LG MJ1 had no lower temperature limits,** so a study charging them in the cold gave no warning. Both now warn below 0 °C on charge and −20 °C on discharge (Panasonic's PF sheet; the MJ1 specification the library already cites). Some later copies of the PF sheet give charging from +10 °C.
- **Fixed: a cell charging at exactly its lower limit was reported as below it** ("Charging at −0.0 degC, below the 0 degC limit"; the A123 at a 0 °C ambient dips a few hundredths of a kelvin). Dips under 0.05 K are no longer reported.
- **Tests:** every library cell with a circuit or a datasheet carries its lower limits.

## 0.6.9

The LG M50 against measured data, with a thermocouple inside the cell (Warwick, Gulsoy et al., Mendeley bf6fksxpp2 v2, CC BY 4.0).

- **Changed: the library M50's resistance, ×2.04.** Its circuit, derived from a physics model in v0.4.11, had half the real cell's resistance: on the 2C pulses of six fresh cells it dropped 130–200 mV where they dropped 270–400 mV (its open-circuit voltage was within 10–50 mV). One scale on every loss term, fitted on the 2C pulses at 30 % charge and above, takes them from 167 to 18 mV RMS; the C/2 pulses (not fitted) from 39 to 13 mV. Near empty it now drops too much (55 mV). The v0.6.8 circuit is `M50-DERIVED`.
- **The core-temperature check.** Seven 1C discharges with the core measured, never fitted on, predicted from the current alone: voltage 18–40 mV (was 114–146), surface 0.8–0.9 K (was 1.1–2.2), core 0.7–1.4 K (was 2.2–3.2). The heat had been about 60 % of the real cell's. The core runs 2–3.5 K above the surface at the end, the model's 1.7–2 K; a tenth of the radial conductivity (0.12 W/(m K), BACKLOG item 5) gives 14–16 K and is ruled out. Checked at 25 °C only: the temperature dependence is still the physics model's.
- **Design results move.** With twice the heat the M50 studies run hotter: on the road trip an uncooled pack reaches 70 °C (was 55), the lightest feasible design is air at 0.3 g/s per cell (1.9 % of the energy moved; 0.15 g/s now fails the worst-case check), and liquid cooling costs about 0.1 % (was 0.05). Still 23 of 39 feasible. The 1.5C full discharge at 25 °C, the M50's rated current, now has no feasible design (was the hard example); 3 × WLTC keeps every cooled design within 1.1 K of ambient. All three examples, the comparison CSVs and the field figure are re-run.
- **Reading the data:** `validation/prepare_m50_core.py` (mat-io, only for preparing) and `validation/prepare_m50_rpt.py`, which takes a MATLAB table's numbers straight from the file's elements (mat-io needs more than 7 GB for the 241 MB characterisation file). `validation/fit_m50_scale.py`, `validation/check_m50_core.py`, `docs/figures/make_m50_measured.py`.
- **Drive cycles, never fitted on:** three cells' 8 h of drive cycles with regen, top-ups and rests (`validation/prepare_m50_drive.py`, h5py, only for preparing; `validation/check_m50_drive.py`): 34–36 mV RMS while current flows (the derived circuit: 44 mV). Most of what is left is the open-circuit curve, 15–35 mV low at rest. The file's temperatures have no clock shared with its current and are not used.
- **The M50's cold limits** (no charging below 0 °C, discharge to −20 °C, from LG's specification): a study charging it in the cold gave no warning before.
- **Lumped models make too little heat:** 22–64 % of the fitted circuit's on a constant discharge (the M50's datasheet 30 mΩ: about half its measured heat). The library's lumped versions and the v0.6.8 M50 are now listed apart, for comparison only (`packtherm cells`, the API's `group`, the web app's cell list, which says so when one is chosen). User-defined datasheet cells and the MJ1 still use the lumped model: BACKLOG item 2, next.
- **Checked across the M50's range:** discharges at 0.2–2C from −20 to 40 °C, charges at 0.3–0.7C from 0 to 40 °C, and fast studies of every duty type at −10, 0, 25 and 40 °C ran without errors; it delivers 93–98 % of 5 Ah (the cells measured 4.7–4.9 Ah at 1C). Its cold behaviour is still the physics model's, not measured.
- **Not read:** the long-term ageing files (22 GB).
- **Tests:** the pulses, the scale, a 1C discharge predicted, the core above the surface (`tests/test_m50_measured.py`). Five tests that used the M50 as a convenient cell now use a duty it can deliver at its measured resistance (a 2C module study to 1.5C, the browser check to 0.8C, the reversible-heat check at 70 % charge, where a 1C charge no longer meets the voltage limit at once).

## 0.6.8

A patch of fixes for the known issues after v0.6.7.

- **Fixed: cold drive cycles were cut short in the fit.** A long test's fitted part ended at the first sample below its knee; in the cold a drive cycle's peaks dip below it within seconds, so the 30T's and HG2's −20 °C Mixed1 were fitted on 15 s (the 30T's 180 mV without pulses in v0.6.6), and the HG2's 0 and −10 °C cycles on a fifth of their charge. The knee is now where the voltage stays below it under load for a minute, or where the charge counted reaches it, and the slow branch is fitted down to 30% state of charge at least. 30T checks 26.5 → 25.7 mV (68% within 1 K); HG2 36.6 → 36.6 mV (−10 °C 4.5 mV better, −20 °C 6.8 mV worse). Without the 30% (a first try) the HG2 went to 39.0 mV: its 25 °C middle branch was set by the low charge the model handles worst. The 30% was chosen with the checks in view.
- **Hysteresis in two parts.** A share of the gap follows the current's sign at once (Plett), chosen per temperature on the drive cycles. The A123's profiles at 5–45 °C are 3.9–7.2 mV (v0.6.7: 4.1–8.1), its 4C-peak check 11.6 mV (11.9), its held-out charge 8.1 mV (8.2). Its −5 and −15 °C profiles fitted on are 7.4 and 29.6 mV (22.3, 44.6), but its −12 °C checks are 102 and 91 mV (98, 88): below 30% the cell still runs out first.
- **Fixed: the HG2's hysteresis estimate had the wrong sign** (−12 mV; now 14 mV): a slow charge counting more charge in than out is stretched onto the discharge's range.
- **New: a note where the tests don't pin the split between the branches** (two or more branch values at their range's edge): the A123 at five temperatures, the HG2 at 9 and 0 °C.
- **Studies:** a module a little warm in a cool ambient is ready again (no warmer than 25 °C and within the event's headroom to its peak limit), so a sealed module at −10 °C no longer fails on recovery; the low-temperature warnings need 0.05C held over 30 s, not a moment's regen. The library notes the HG2's 2.78 Ah (8% more cells than its 3.0 Ah rating).
- **Tried and not shipped:** charge lost with rate (a surface state of charge; fitted to zero on the 30T and HG2, no gain), the rise near empty on charge (no gain on the A123's charge from empty, whose error is the open-circuit curve below about 7%).
- **Not done: the core-temperature check** against the LG M50 with an embedded thermocouple; its 2.3 GB archive is still to be unpacked (v0.6.9).
- **Tests:** the knee against a dip; hysteresis share on a known cell; recovery in the cold; regen blips.

## 0.6.7

LFP hysteresis, datasheet temperature limits, and the fixes from the audit after v0.6.6: the eighth v0.6 mini update.

- **New: hysteresis** (LFP). The circuit can carry a state between its charge and discharge branches: charging moves it onto the charge branch, discharging off it, crossing most of the gap in 1/k Ah. The gap G and rate k are fitted at each temperature from a `slow_charge` (a slow charge from empty) in the test list, and written to the cell file. Heat counts the loop (half the gap per unit of charge). A cell with no slow charges has none: the 30T and HG2 refit to 26.5 and 36.6 mV on their checks, as before.
- **The A123 refitted with hysteresis**, from its C/30 charges at six temperatures; the 15 °C one is held out.
  - Held-out charge (10–95%): 8.2 mV, was 41.2 mV. The gap is 28 mV at 25 °C, 51 mV at −12 °C.
  - Discharge profiles fitted on: 4.1–8.1 mV at 5 to 45 °C (was 4.2–6.6); the 4C-peak check 11.9 mV (was 8.2); the −12 °C checks 98 and 88 mV (were 104 and 93).
  - Its branch values are less physical than before, and the rate sits at its 100 per Ah bound; its 10 s DC resistance at 25 °C is 14.4 mΩ (was 16.9; `A123-LUMPED` follows).
  - Charging from empty still runs about 200 mV low over its first 10%.
- **The cold is not fixed.** Two attempts, neither shipped (FITTING.md); BACKLOG item 7 has them.
- **New: datasheet temperature limits** for the 30T (charge 0 to 50 °C, discharge −20 to 80 °C), HG2 (0 to 50, −20 to 75) and A123 (0 to 55, −30 to 55), and new `T_min_charge_C` / `T_min_discharge_C` for any cell (user cell files too). A study warns when the cell charges, or discharges, with any part colder than them: below 0 °C, charging can plate lithium. A drive cycle's regen counts: an A123 module on WLTC at −10 °C now warns.
- **New: a warning below a fitted cell's tested state of charge.** The tested range now runs down to where the long tests end, not only the pulses.
- **Fixed (v0.6.6):** a fit without pulse tests recorded no charge rate and an instantaneous discharge peak; it now records each window's 30 s mean peak each way. The A123 is tested to 0.97C discharge and 0.41C charge. Studies of it with regen no longer warn that its charge wasn't tested.
- **Fixed:** wording for fits without pulses (`kinetics_from`, `tau_m_from`); rests logged once a minute are no longer reported as gaps; the "coarse for pulse tests" warning only where there are pulses.
- **Data:** the A123's C/30 charges at every temperature (`validation/prepare_a123.py`).
- **Tests:** hysteresis from a slow charge on a known cell; its heat; the lower temperature limits and the library's; the state-of-charge warning; slow-logged rests.

## 0.6.6

An LFP cell, and fitting without a pulse test: the seventh v0.6 mini update.

- **New: fitting without a pulse test.** A test list's `pulses` is now optional where a temperature has discharges or drive cycles. The kinetics then come from their sudden changes in current (0.5C or more from one sample to the next), each from 5 s before to 60 s after, scored on the change from its first sample as a pulse is. They're parts of the long test's own replay from its rested start, so they need no settled rest before them. Stages 1 and 4 use those at 20–95% state of charge. The file and report say when a fit had no pulse test.
- **Proven before the LFP fit:**
  - on a known cell tested as the A123 was (no pulses): every value within 6%;
  - on the 30T and the HG2 with their pulse and step tests taken out: checks 29.4 mV (with pulses 26.5) and 35.4 mV (36.6), 77% and 96% within 1 K. The branch values differ a lot either way; the library's 30T and HG2 keep their pulse fits.
- **New cell: the A123 ANR26650M1B** (LFP / graphite, 26650, 2.5 Ah), fitted blind once at −15 to 45 °C from the open UCCS dataset (Kawakita de Souza, CC BY 4.0) and added to the library as `A123`, with `A123-LUMPED` for its size and thermal properties (LFP values; entropic heat from v0.5.4's LFP profile).
  - Fitted on: 4–7 mV RMS on its drive profiles from 5 to 45 °C; 21.8 mV at −5 °C, 48.4 mV at −15 °C.
  - Checks, never fitted to: a 25 °C profile at four times the current, 8.2 mV; two −12 °C profiles, 104 and 93 mV; a 25 °C C/30 charge, 59.7 mV. Median 76.5 mV, 75% within 1 K.
  - What it exposed (v0.6.7): in the cold the cell runs out well before the model (180–270 mV high below 25%), and its early losses are over-predicted by about 120 mV; on charge the model is 35–50 mV low, LFP's hysteresis.
  - The rig can't be calibrated on these tests (rises under 1 K at 25 °C): h ran to its limit, which the file flags.
- **Data:** `validation/prepare_a123.py` reads the dataset's Excel exports (its .mat files have no temperature) into `validation/data/a123_26650/` (19 files, 4.4 MB) with a manifest. −25 °C is left out: its drive profile logged no cell temperature.
- **Tests:** the known cell without pulses; the windows (no overlaps, from the long test's replay); a test list without pulses; the A123 in the library.
- **Docs:** FITTING.md (fitting without pulses, the 30T and HG2 without them, the A123 blind, limits), README, HISTORY, BACKLOG (item 7), TEST_DATA.

## 0.6.5

Capacity by temperature, the sixth v0.6 mini update: the two faults the LG HG2's blind check found, fixed.

- **New: open-circuit curves by temperature.** A test list can give a slow (C/20) discharge at each temperature (`temperatures[].slow`), each starting full. Each becomes an open-circuit curve against the same state of charge: the charge left, as a share of the 25 °C capacity. A cell that delivers less in the cold reaches its cut-off sooner there, and charge is still conserved as it warms or cools. Between curves the voltage is interpolated linearly in temperature; beyond them, the end curve holds. Rests are read through the curve at the cell's temperature.
  - The model (`ECM.ocv(soc, T)`), the studies, the measured-heat check, the fitted cell file (`open_circuit_voltage.by_temperature`) and the report's chart all follow.
  - Cells and files without them run as before.
- **Fixed: the middle branch could take the slow branch's place.** Its time constant is now capped at 120 s, the slow branch's floor (was 300 s). On the HG2 at 10 and 0 °C it had run to 235–300 s with no slow branch left, holding 1C discharges 90–150 mV low.
- **Results** (median voltage error on the checks, never fitted to):

  | Cell | v0.6.4 | v0.6.5 | Within 1 K |
  |---|---|---|---|
  | LG HG2 | 59.7 mV | 36.6 mV | 93% (was 89%) |
  | Samsung 30T | 27.7 mV | 26.5 mV | 66% (was 62%) |
  | Panasonic PF | 24.4 mV | 26.4 mV | 81% (unchanged) |

  - **HG2:** the curves by temperature alone gave 59.7 → 55.9 mV; the cap gave the rest. v0.6.4 had named the capacity as the main cause, but it was the smaller part.
  - **30T:** its R0 now rises from −10 to −20 °C, as it should.
  - **Panasonic:** it has a slow test at 25 °C only. The cap costs it a little at 0 and −10 °C, where its middle branch had been at 138 and 121 s.
- **Left open (BACKLOG item 7):**
  - at 40 °C the HG2 delivers 2.50 Ah at 1C against 2.69 at C/20, which the model doesn't follow (up to 180 mV high near the end);
  - at 10 and 0 °C its middle branch sits at the cap with no slow branch;
  - −10 and −20 °C are still 60–70 mV.
- **None of the three cells is a blind check now.** The next cell (an LFP, v0.6.6) will be.
- **Data:** the C/20 test at every temperature for the 30T and the HG2, unchanged, in `tests/data/` (10 files, 0.7 MB). `validation/prepare_mcmaster.py` copies them.
- **Tests:** a known cell whose curve shifts with temperature. The fit finds each curve within 6 mV, and a 0 °C discharge ends within 2% of where the cell's does (one curve runs 4% on). Plus the curves through the cell file.
- **Docs:** FITTING.md (the model, the HG2 follow-up, three cells side by side), README, HISTORY, BACKLOG (item 7 rewritten).

## 0.6.4

The LG INR18650-HG2, the fifth v0.6 mini update: a third cell, fitted blind with the method of v0.6.3 unchanged, and added to the library.

- **New: the LG HG2 in the library** (`HG2`). It is a 3 Ah NMC / graphite + SiO 18650, fitted at 40, 25, 10, 0, −10 and −20 °C from the McMaster tests (Kollmeyer, Naguib and Skells, Mendeley Data v2, 2020, CC BY 4.0). The fitted cell file ships with PackTherm. `HG2-LUMPED` carries its size and limits (from the lab's technical sheet), a mass derived from its stated 240 Wh/kg, and the fitted 10 s DC resistance (28.3 mΩ at 25 °C) as a lumped resistance.
- **Blind results.** The fit was run once and reported as it came out. On 74 tests it never saw, from current alone: **59.7 mV** median voltage error and **89% within 1 K**. At 25 °C it is 22.0 mV, in line with the Panasonic (18.2) and the 30T (17.4). Elsewhere it is 43–70 mV. See [docs/FITTING.md](docs/FITTING.md#a-third-cell-fitted-blind-the-lg-hg2).
- **What it exposed: one capacity for every temperature.** The fitted cell takes its capacity and open-circuit curve from the 25 °C C/20 test (2.78 Ah). The HG2's C/20 capacity is 2.69 Ah at 40 °C and 2.50 at −20 °C, so the state of charge drifts through a discharge, and even the fitted discharges reach 140 mV at 40, 10 and 0 °C. The middle branch also drifted to the slow branch's time scale at 10 and 0 °C. Both go to v0.6.5 (BACKLOG item 7, new). The method was not changed here.
- **The rig, again.** The HG2 warms by at most 8 K in these tests, which leaves the rig loosely pinned: h = 130 W/(m² K), and the fixture at its limit. A radial conductivity of 0.06 W/(m K) fits the checks better (44.5 mV, 95% within 1 K), but it is below any jelly roll's. It is standing in for something the model lacks, most likely the thermocouple's lag. Reported only; the fixture ships (BACKLOG item 5).
- **One data-preparation script for both McMaster datasets** (`validation/prepare_mcmaster.py 30t|hg2`, replacing `prepare_samsung_30t.py`). It rebuilds the 30T's 94 tests byte for byte. For the HG2 it also:
  - picks the first 1C discharge as the one before the UDDS cycle (the 10 °C tests ran out of order);
  - reads a start time missing its `_`;
  - replaces a lone temperature reading more than 5 K from both neighbours;
  - leaves out runs that discharged under a quarter of the capacity, listed in `excluded.json`: five 40 °C drive cycles run at room temperature and stopped at 0.2 Ah, and an empty 25 °C HWFET.

  Gzipped CSVs are now written without a timestamp, and left alone when unchanged.
- **Data:** the HG2's pulse tests at six temperatures and its 25 °C C/20 test, unchanged, in `tests/data/lg_hg2/` (3.8 MB). Its 86 discharges and drive cycles, processed, in `validation/data/lg_hg2/` (3.8 MB). Both CC BY 4.0, credited in their READMEs.
- **Tests:** the library HG2 against its documented fit; the data preparation's rules (start times, folder names, tails) and both manifests.
- **Docs:** FITTING.md (the HG2, and three cells side by side), README, HISTORY, BACKLOG (item 7 new, item 5 updated, later items renumbered), TEST_DATA.

## 0.6.3

The Samsung INR21700-30T, the fourth v0.6 mini update: a second cell fitted with `packtherm fit` and added to the library, and what it showed about the method.

- **New: the Samsung 30T in the library** (`30T`). It is a 3 Ah high-power 21700, fitted at 40, 25, 10, 0, −10 and −20 °C from the McMaster tests (Kollmeyer and Skells, Mendeley Data v2, 2023, CC BY 4.0). The fitted cell file ships with PackTherm. `30T-LUMPED` carries its size, the mass derived from its stated 166 Wh/kg, and its limits, with the fitted 10 s DC resistance (14.3 mΩ at 25 °C) as a lumped resistance. The cathode isn't stated by the source, so its thermal properties and zero entropic heat are assumptions.
- **Results.** On 82 tests it never saw, from current alone: 27.7 mV median voltage error and 62% within 1 K. From 40 to 0 °C the error is 13–28 mV, and every test at 25 and 40 °C is within 1 K. The cold is weaker: 51 and 79 mV at −10 and −20 °C, where values sit at their limits. See [docs/FITTING.md](docs/FITTING.md#checked-on-a-second-cell-the-samsung-30t).
- **Fixed: the middle branch's time constant was left loose by the pulses.** The 30T's 25 °C pulses fit as well with it at 30 s as at 290 s, and at 290 s its 1C discharge ran 50–60 mV low. Where there are long tests, the fit now runs both ways: once with the time constant from the pulses, once from the long tests. It keeps the one that fits the discharges and drive cycles better, provided the pulses still fit within 10%. Only fitted tests decide. Each temperature's choice is in the file (`by_temperature[].tau_m_from`). A fit takes up to twice as long.
- **The Panasonic refitted** with it: 24.4 mV median on its 43 checks (was 28.2) and 81% within 1 K (was 79%). −10 °C improved from 54 to 34 mV, and −20 °C worsened from 67 to 92 mV.
- **New: the test rig, calibrated.** A test list can calibrate the rig for the thermal checks on tests that are fitted to (`chamber_calibration`), with the heat from their measured voltage. One test sets the chamber's convection. A drive cycle as well sets the heat capacity the cell's fixture adds. Both are the rig's, used for the checks only, and recorded in the file's provenance.
- **Open question: the fixture, or the cell's conduction.** On the 30T the fixture explains the drive cycles' peaks about as well as a radial conductivity of 0.12 W/(m K) instead of the assumed 1.2, and one case thermocouple can't tell them apart (BACKLOG item 5).
- **The 30T's data, prepared with care** (`validation/prepare_samsung_30t.py`):
  - the ambient is the cell temperature after the settled rest before each test, since the chambers ran off their setpoints;
  - the tests whose files begin mid-discharge start from the charge the tester counted;
  - a block logged twice is kept once, and a chamber's ramp after a test is cut.
- **Faster import:** `packtherm.fitting` loads its parts when first used, so the cell library can read a fitted cell file without loading the fit.
- **How blind this is.** The 30T was the promised independent check of the method. The middle-branch fault showed in its fitted tests, and the fix decides on fitted tests. But the alternatives, and the rig's form, were compared on both cells' checks before choosing. The LG HG2 (v0.6.4) will be fitted with the method as it stands.
- **Data:** the 30T's pulse tests at six temperatures and its 25 °C C/20 discharge, unchanged, in `tests/data/samsung_30t/` (4.1 MB). Its 94 discharges and drive cycles, processed, in `validation/data/samsung_30t/` (2.2 MB). Both CC BY 4.0, credited in their READMEs.
- **Tests:** the library 30T against its documented fit, its resistance growing in the cold, the rig calibrated on the 30T's fitted tests, and test lists with calibration tests.
- **Docs:** FITTING.md (the two ways, the rig, the 30T's results and how independent they are), README, HISTORY, BACKLOG (items 5 and 6), TEST_DATA.

## 0.6.2

Fitting across temperatures, the third v0.6 mini update. Fitted cells can now be used in studies.

- **New: test lists.** `packtherm fit tests.yaml` takes a cell's tests by temperature: pulse tests, steps, full discharges and drive cycles, plus checks the fit never sees. Paths are relative to the list; every problem in a list is reported at once. Compressed CSVs (`.csv.gz`) are read too.
- **New: values by temperature.** Each temperature is fitted on its own, and PackTherm's circuit model now holds a table of values by temperature (`ECM.by_T`): interpolated in 1/T between the fitted temperatures, and carried beyond the coldest and warmest by Arrhenius laws fitted through them. Existing cells are unchanged.
- **New: a third branch.** A middle RC branch (tens of seconds) sits between the charge transfer (seconds) and the slow branch (minutes). With two, the fit had to choose, and predicted drive cycles ran cold. Off in the library cells.
- **New: fitted cells in studies.** A file fitted at three temperatures or more, naming a cell for its size, mass and thermal properties (`like: PF`), loads as `cell: my_cell.yaml` in a study, the API and the CLI. Runs that go beyond the tested temperatures (by more than 2 K) or C-rates get a warning in the results.
- **New: checks as a study runs the cell.** With `like` and the chamber's convection given, each check is run electro-thermally from its measured current alone, and its voltage and surface temperature are compared with what was measured, beside a library cell's (`errors.held_out_electrothermal`, and a chart in the report).
- **The fit, reworked from what the checks showed:**
  - the slow branch is fitted on long tests only (steps, discharges, drive cycles): fitted with the pulses, it went to tens of seconds, and drive cycles ran cold;
  - long tests are scored on their voltage down to the knee near empty, not relative to their first sample, which carried one sample's error through hours;
  - the rise near empty is fitted on pulses and long tests run to their end;
  - three rounds, not two.
- **Fixed, found by the known-answer tests:** the rise near empty was set to zero while the slow branch was fitted, so the slow branch made up for it. On tests made by a known cell, the slow branch's time constant ran to 10x its true value. It now comes back within 10%.
- **Results.** The Panasonic NCR18650PF fitted at five temperatures (−20 to 25 °C), from files in the repository, predicts 43 tests it never saw, from their current alone: 28.2 mV median voltage error against 32.7 mV for the hand-tuned library cell, and 79% within 1 K against 86%. Its temperature peaks run about 1 K cold, in the last minutes near empty (BACKLOG item 6). See [docs/FITTING.md](docs/FITTING.md); the worked example is in `docs/examples/fitting/`.
- **Tests:** known answers at one and three temperatures (values following known laws), the temperature table and middle branch, fitted cells in studies and their range warnings, test lists, and a real three-temperature fit. Six more Panasonic files in `tests/data` (the 10, 0, −10 and −20 °C pulse tests and their steps, unchanged, CC BY 4.0).
- **Docs:** FITTING.md rewritten for test lists, the table and the results; BACKLOG item 6 rewritten (the cold peaks); README and HISTORY.

## 0.6.1

Fitting a cell model at one temperature, the second v0.6 mini update.

- **New: `packtherm fit` and `packtherm.fitting`.** The command fits PackTherm's circuit model (`packtherm.ecm.ECM`) to a slow discharge, a pulse test and, optionally, steady steps with rests, all at one temperature.
  - **Through time:** each pulse, and each rest after a step, is replayed through the same simulation PackTherm runs (a test checks they agree to 1e-9 V) and fitted on how the voltage changes. Pulses that follow each other within a minute are replayed from the last long rest before them, so the slow recovery from one pulse is not mistaken for the next one's response.
  - **The open-circuit voltage and capacity** come from the slow discharge, with the cell's own drop added back from the fitted model. **The state of charge** is anchored at a settled rest and carried by the charge counted.
  - **Held-out tests** (`--check`) are predicted afterwards, never fitted to, alongside a library cell (`--compare`).
  - The fitting code treats a model as an interface, so a generic circuit with a chosen number of branches can be added later and share the rest.
- **New: the fitted cell file** (YAML) and **an HTML report** beside it:
  - each value with its source (`fitted`, `data`, `default` or `not fitted`), a 95% range and flags;
  - pairs of values that trade off;
  - where the model is valid (cell temperature, state of charge and C-rates the tests covered);
  - its errors on each kind of part fitted and on each held-out test;
  - measured against rated capacity;
  - every data warning;
  - provenance: each input's SHA-256, the dataset's citation and licence, the PackTherm version, the date and the settings.
- **Studies refuse a fitted cell file for now.** Fitted at one temperature, its temperature behaviour is borrowed from the library NCR18650PF, which would make thermal results look more certain than they are. Every route into a study (study files, `get_cell`, the API, the web app's engine) gives the same message; v0.6.2 fits that behaviour from tests at several temperatures.
- **Honest ranges.** The usual least-squares ranges treat every sample as independent. On noise-free test data with known answers, every true value fell outside them, because what is left after a fit like this is the model's misfit, shared across a whole pulse. The ranges now count each pulse and step as one piece of evidence (cluster-robust), and 7 of 8 true values lie inside them.
- **Checked against known answers**: tests made by a cell with known values come back within 1–5% (`R0` within 0.1%), and a drive cycle the fit never saw is predicted to 0.2 mV RMS.
- **Checked on real data in every CI run.** The Panasonic NCR18650PF at 25 °C (Kollmeyer, CC BY 4.0) gives:
  - 2.995 Ah measured (rated 2.9 Ah);
  - a UDDS drive cycle the fit never saw predicted to 5.3 mV RMS, against 10.1 mV for the library cell;
  - pulses at 20–95% state of charge to 8.9 mV, and rests after steps to 7.6 mV.
  - One more file from the dataset is in `tests/data` (16 KB, unchanged): the steps and rests that complete the pulse test.
- **Fixed: charge across a step that falls between two samples.** Where logging is sparse (every 5 min in a rest), averaging the current at the two ends counted charge that never moved: 0.036 Ah at every step of the Panasonic steps file, and a false "counter disagrees by 20%" warning. Where the current changes between two samples, the tester's charge counter is used.
- **Docs:** [docs/FITTING.md](docs/FITTING.md): the tests it needs, the method, the file, the results and the known limits. The model's two branches cannot follow every time scale a cell responds on. This is now a backlog item, and the case for the planned generic circuit.

## 0.6.0

Cell test data, the first v0.6 mini update. v0.6 fits a cell model to measured test data; this step reads and checks the data.

- **New: `packtherm.testdata` and `packtherm data <file>`.** It reads a cell test from CSV/TSV, or from MATLAB `.mat` files (top-level vectors or a structure, including the Kollmeyer datasets' `meas`), and converts it to seconds, amps with + = discharge, volts and °C.
  - **Columns** are found by name for the common tester exports (Arbin, Neware, Biologic, Digatron, Maccor), or named with `--time`, `--current`, `--voltage`, `--temperature` and `--ambient`.
  - **Units** are read from the column names (`mA`, `mV`, `ms`, `min`, `h`, `K`) and checked against the values. Time may be numbers, `h:mm:ss` durations, or dates and times.
  - **The current's sign** is worked out from the voltage. In a finely logged record, from the instant response to every jump in current; otherwise from how the voltage behaves when current starts and stops, and during long steady currents. It is flipped if needed, and the evidence is shown (`--flip` overrides it).
  - **The tester's charge counter** (`Ah`, `Capacity`, `(Q-Qo)`, or Arbin's charge and discharge capacities) is read too. Testers can pause logging during long steps, and the counter keeps counting: the charge that moved across a gap is counted, as an `unlogged` part. Without a counter, a gap across which the voltage moved is flagged.
  - **Checks:** missing rows, repeated times, time running backwards, gaps, a counter that disagrees with the logged current, a coarse time step, a voltage that isn't a single cell's, implausible temperatures, and, with `--capacity`, more charge moved than the cell holds.
  - **The parts of a test** are labelled: rests, pulses (60 s or less), constant-current steps, CC-CV charges, dynamic stretches such as drive cycles, and unlogged gaps. `--segments` lists them, `--plot` draws the test with the parts shaded, and `--json` prints the lot.
- **Checked on the Panasonic NCR18650PF dataset** (Kollmeyer, CC BY 4.0): of its 198 files, 191 hold data and 7 a single sample. The sign is found from the voltage in 189, and all 131 whose names say what they are come out the right way round. The other two are flagged as unclear.
- **Tested on real files in every CI run.** Six files from that dataset, copied unchanged (1.4 MB, credited), are checked against facts that don't depend on the reader: the pulse test's design (0.5 to 6C), the 2.5 V cut-off that ends three pulses early, and the tester's own amp-hour counter, which the reader's charge matches within 1%. That check found a real fault: the pulse test leaves out every discharge between pulse levels (logging pauses during them), so the charge read 1.34 Ah against the tester's 2.77 Ah, until the counter was used. Synthetic records with known answers still cover other formats and damaged files.
- **Docs:** [docs/TEST_DATA.md](docs/TEST_DATA.md). The roadmap lists v0.6.1–v0.6.3 (fitting), then a generic circuit model, fitting in the web app, and a 3D view.

## 0.5.7

Fixes from a full audit (every test, the command line, the API's edge cases, the docs' links and the web app's files), the eighth v0.5 mini update.

- **Fixed: a duty the cell cannot deliver no longer passes as a cool design.** A cell with a voltage model (M50, PF) stops at its voltage cut-off, so a current it cannot sustain is cut short, at the extreme to nothing. The M50 at 30C delivered no current, showed a 25 °C peak, and was reported feasible with no warning; at 20C it reached 176 °C. Now each design checks how much of the requested discharge the cell delivered during the event. Below 80% it fails with reason `short` and a warning giving the share. Normal duties deliver 87–100% (the shortfall is the taper near empty). This applies to module studies and the single-cell design study.
- **Fixed: warnings in results files carry their `WARNING:` prefix**, so the web app shows them as warnings, and a design with two warnings lists them separately.
- **Fixed: a first visit to the public site downloaded 56 MB, not 28.** Each extra worker downloaded SciPy's 14 MB package again, because the browser's own cache did not keep a file that large; CI now reports each worker's downloads, which showed it. The engine's files are now kept in the page's Cache Storage, shared by every worker and by later visits, so the extra workers download nothing. Measured in CI: 28.3 MB in all, and the first run starts sooner.
- **New: chart downloads on the public site.** The trade-off chart downloads as SVG or PNG, made in the page, with its title, axis label, legend and pick key drawn in. The server still gives its PNG.
- **New: `packtherm --version`.** Piping output into a command that stops reading (`| head`) no longer ends with an error.
- **Example results regenerated** in normal mode with 0.5.7. Every design's numbers are unchanged; the files now carry the chart labels and the cell model.
- **Docs:** the results format lists every fail reason, and says the `study` block re-runs as a study file.

## 0.5.6

The public site, the seventh v0.5 mini update: PackTherm runs in the visitor's browser, published free on GitHub Pages.

- **New: an in-browser engine.** The public site ([omlettehead22.github.io/PackTherm](https://omlettehead22.github.io/PackTherm/)) runs PackTherm itself in the page, with Pyodide (Python compiled to WebAssembly). It needs no server, so it costs nothing to host, has no queue or design limits, and nothing a visitor enters leaves their computer.
  - Designs run in parallel Web Workers: one per core, leaving one for the page, at most four.
  - Measured in CI (headless Chromium, 4 cores): the engine is ready about 6 s into a first visit, after a 28 MB download; the hot road-trip example (39 designs, fast mode) took 41–101 s on 3 workers across CI runs (shared machines vary).
  - **Same results as `packtherm run`**: CI runs a study in the browser and compares the results file with a native run. All text and verdicts match; numbers agree to 1e-11 (the browser's NumPy is a different build).
- **New: `packtherm.browser`**, the Python side of the engine: a study in steps (check, evaluate each design, assemble the results with any worst-case re-checks), with values crossing between workers as exact JSON text. A test drives it as the workers do and gets `packtherm run`'s results exactly. `run_module_study` and the engine share the final step (`module_study_result`).
- **Sharing without a server:** a link carries the study and fills in the form for whoever opens it; a downloaded results file opens in the app. Results JSON and the designs CSV download from the page.
- **Release wheels:** a version tag builds the wheel with the web app inside and attaches it to a GitHub release, so `pip install` of its URL gives `packtherm serve` with the app and needs no Node.
- **Fixed: a results file's `study` block is a valid study again.** It lists every duty key, with null or the default for those the duty doesn't use, and validation rejected them, so the results screen's "Study file (YAML)" (new in 0.5.5) gave a file `packtherm run` refused. Keys left at their defaults are now accepted; a test checks every example study validates to itself.
- PackTherm no longer imports process pools until it uses them (Pyodide has no processes).
- CI gains a `browser-engine` job; a Pages workflow publishes the site from `main` after CI passes.

## 0.5.5

The web app, the sixth v0.5 mini update: set up a study in the browser, watch it run, explore the results.

- **New: a web app**, served by `packtherm serve` at `/` and included in the Docker image. Built with React and TypeScript (Vite), in `web/`; Node is needed only to build it.
  - **Set up:** start from the README's example studies or a blank form. Choose a library cell or enter your own (NMC, NCA, LFP), with the server checking it as you type: what PackTherm derives from it, warnings, and errors by field. The duty's own fields follow its type, including an editor for custom segments. Limits, the designs to compare, and advanced options (collapsed) complete the form.
  - **Fast mode by default**, with normal mode one click away. The app shows how many designs the study will run and stops a study over the public limits before it is sent, with the reason.
  - **Running:** progress through the designs and the worst-case re-check, time remaining, queue position, and cancel. The page can be closed: the link keeps working.
  - **Results:** a card for each pick (one card where a design is two picks), the interactive trade-off chart (hover or arrow keys for a design's numbers), a sortable table of every design with why each failed, the notes, and labels for fast mode and user-defined cells.
  - **Downloads:** results JSON, designs CSV, the PNG chart, and the study as a YAML file to re-run with `packtherm run`. A link to the results works for 24 hours.
  - Light and dark themes (following the system, with a switch), keyboard use, and phone widths.
- **The form is built from the study format** (`packtherm.study.schema()`), so it cannot drift from what the API accepts. Tests fail if the shared files are out of date or a key has no label.
- **New: `POST /studies/check`** validates a study without queuing it: how many designs it would run, and any limits it is over. `POST /studies` uses the same checks.
- **Results files carry chart labels** (`labels`: axis titles and cooling-kind names), so the app's chart matches the PNG. The format version is unchanged; older files work without them.
- **New setting `PACKTHERM_WEB_DIR`**, to serve a web app built elsewhere. Without a built app, `/` explains how to build it.
- **CI** gains a web job (type-check, 26 tests, build), and the Docker job checks that the image serves the app.

## 0.5.4

LFP cells, the fifth v0.5 mini update: user-defined cylindrical cells can now be LFP/graphite.

- **New: `chemistry: LFP`.**
  - Thermal properties measured on whole cylindrical LFP cells: heat capacity 1100 J/kg·K (mean of a 2022 meta-analysis' cylindrical LFP entries, leaving out two at full charge), radial conductivity 0.35 W/m·K (median; range 0.15–0.51), axial 31 W/m·K (Drake 2014).
  - LFP's radial conduction is about a third of NMC's measured the same way. PackTherm's calculated NMC value (1.23) is close to the measured NMC median (about 1.1), so the difference is the chemistry, not the method.
  - Sources are in `cells.py` and `docs/STUDY_FILES.md`.
- **New: LFP entropic heat** (`cells.lfp_graphite_dUdT`). It comes from the graphite electrode, which dominates an LFP/graphite cell's entropy change: the published O'Regan 2022 graphite fit, over an A123 26650 LFP cell's graphite range (PyBaMM `Prada2013`).
  - It runs from −0.38 to +0.06 mV/K, inside the −0.42 to +0.17 mV/K reported, and absorbs heat on discharge from about 30 % charge, as measured. Tests check both.
  - It understates the measured mid-charge peak: slightly more heat than real in mid-charge discharge (the safe side), slightly less in mid-charge charge.
- **Checked:** PyBaMM's own O'Regan 2022 graphite and NMC entropic functions match PackTherm's exactly (PyBaMM zeroes the same staging term), so the existing NMC entropic heat is confirmed.
- **Chemistry-specific plausibility checks.**
  - Nominal voltage errors outside 2.9–3.45 V for LFP and 3.3–4.2 V for NMC/NCA (was 2.5–4.2). The error suggests the likely mix-up: a 3.2 V cell labelled NMC, or a 3.6 V cell labelled LFP.
  - LFP energy density is capped at 600 Wh/L, and LFP has its own usual density and voltage bands.
- **New example:** `docs/examples/user_cell_lfp_26650.yaml`, an LFP power cell (Lithium Werks / A123 ANR26650M1-B) from its current datasheet; it passes with no warnings.
- **New guidance: DC resistance, not AC impedance.** Many datasheets give only the 1 kHz AC impedance, which is lower than the DC resistance PackTherm needs (A123: 8 mΩ AC against 10 mΩ DC). The docs and the example say so.
- **Physics check** (normal mode, same cell labelled LFP and NMC, entropic heat off, 4C):
  - Side ribbon and air: LFP's in-cell spread is 2–2.8× NMC's (3.2 against 1.6 K; 2.0 against 0.7 K).
  - Bottom plate: LFP comes out lower (1.3 against 1.8 K), since a plate draws heat along the axis, where LFP conducts better, and LFP's higher heat capacity damps its peaks.
- API tests use `httpx2` (the HTTP client the test client now expects), which clears a deprecation warning.

## 0.5.3

The HTTP API, the fourth v0.5 mini update: run studies over HTTP, for programs and for the web app to come.

- **New: `packtherm.api`** (FastAPI). Install with `pip install "packtherm[api]"`, start with `packtherm serve` or the new Docker image.
  - `POST /studies` queues a study (the study-file format, as JSON) and returns its id.
  - `GET /studies/{id}` gives state, progress (designs done out of total, then the worst-case re-check), time remaining and queue position.
  - `GET /studies/{id}/results`, `/designs.csv` and `/chart.png` fetch the outputs. `DELETE` cancels a study or deletes its results.
  - Also `GET /cells`, `POST /cells/check`, `GET /schema`, `/template`, `/limits` and `/health`, with interactive docs at `/docs`.
  - Details in `docs/API.md`.
- **Same results:** a study through the API gives exactly the results `packtherm run` writes for it (test).
- **Jobs.**
  - Each study runs in its own process, so a time limit or a cancel stops it cleanly and a crash can't affect another.
  - There's no database: each job is a folder, deleted 24 hours after it finishes.
  - A restart fails unfinished studies and keeps finished ones.
- **Limits** for a public server, all settable by environment variables: designs per study (120 fast, 40 normal), simulated time (24 h), duty segments, run time (15 min), 10 studies per visitor per hour, request size (256 kB), 2 running and 20 queued. **API keys** (`PACKTHERM_API_KEYS`, `X-API-Key` header) skip the per-study limits, the time limit and the rate limit.
- **New: `GET /schema`**, the study format as data: types, defaults, choices and bounds, taken from the same rules that validate studies. The web app will build its forms from it. (`packtherm.study.schema()`; the validation rules now carry their bounds.)
- **New: progress reporting.** `run_module_study(progress=...)` and `StudySpec.run(progress=...)`.
- **New: example studies re-run in CI** (`tests/test_examples_rerun.py`). The three examples run in fast mode and must match their committed results: the same verdicts and picks, peaks and spreads within 0.3 K, recovery within 3 min, energy within 2 %. A model change that moves a result now fails CI until the examples are regenerated. About 1½ minutes.
- **CI:** a new job builds the Docker image, starts it and runs a study through the API.
- `packtherm serve`; `Dockerfile` (non-root, health check); `api` extra (FastAPI, Uvicorn).

## 0.5.2

User-defined cells, the third v0.5 mini update: describe your own cylindrical cell from its datasheet and run every study on it.

- **New: user-defined cells** (`packtherm.user_cells`).
  - A definition gives name, format (18650, 21700, 26650, 4680) or diameter and height, chemistry (NMC or NCA), capacity, nominal voltage, mass and DC resistance. Optional: datasheet maximum resistance (for the worst case), current and temperature limits, and overrides for heat capacity, conductivities and the cold resistance rise.
  - It can be written inline in a study (`cell:` as a mapping) or as its own file. A cell file works wherever a cell name does: `packtherm design my_cell.yaml`, `packtherm module my_cell.yaml`, `cell: my_cell.yaml` in a study (relative to the study; inlined so the results carry the full cell). In Python: `Cell.from_datasheet(...)` or `load_cell(path)`.
  - `packtherm cells my_cell.yaml` checks a file and shows the cell as PackTherm understands it: density, energy density, cold resistance rise, thermal properties and limits.
- **Model:** the lumped resistance model of the library MJ1, with no voltage model (no cut-off, no constant-voltage taper). NMC uses the NMC/graphite jelly-roll properties and entropic heat behind the LG M50. NCA uses the same jelly-roll properties and no entropic heat, as for the validated Panasonic NCA cell. Results are labelled "user-defined, lumped DCIR" in the cells table, the results JSON (`summary.cell_model`) and a study note.
- **Unit-slip checks.** Values no real cylindrical Li-ion cell has are errors, each naming the likely slip: mass in kg, resistance in ohms, capacity in mAh, sizes, voltage, temperature limits. Unusual values are warnings, written into the results notes.
- **Proof:** `docs/examples/user_cell_mj1.yaml`, the LG MJ1 from its datasheet values, gives byte-identical results to the library MJ1. A test checks every value the model uses and a design's full result. Conversions shift the decimal point (`65.1 mm` gives exactly `65.1e-3 m`) so this holds exactly.
- **New note:** a duty that charges a cell with no datasheet charge limit gets a study note saying the charge rate is unchecked. The road trip's rapid charge falls back to 1C without a limit, which was easy to miss.
- `Cell.model_label` and `Cell.user_defined`; the `packtherm cells` model column now comes from the cell.
- Docs: README "your own cell" section; `docs/STUDY_FILES.md` documents every cell key (enforced by a test); BACKLOG.

## 0.5.1

Study files, the second v0.5 mini update: one document describes a whole module study, so the command line, Python and (next) the API and web app run the same thing.

- **New: study files** (`packtherm.study`), format 1, in YAML or JSON.
  - A document holds the cell, normal or fast mode, ambient, duty (constant, wltc, roadtrip or segments), requirements, design space and options. Every key except `packtherm_study`, `cell` and `duty.type` is optional; defaults are those of `packtherm design`.
  - `packtherm run study.yaml [--out-dir]` writes `<stem>_results.json`, the designs CSV and the trade-off chart.
  - `packtherm template [--out]` prints a commented file with every default.
  - Python: `load_study(path)`, `StudySpec.build()` (the `ModuleStudy`), `StudySpec.run()`, `StudyRun.to_json()` and `.write()`.
- **Validation before anything runs.** Unknown keys, wrong types, out-of-range values, unknown cells or fillers, and duty keys a duty type doesn't use are all reported together, each naming its field (for example `design_space.coolant_flows_g_s[1]: must be > 0, got -0.05`). Bad YAML or JSON and missing files give a one-line CLI error.
- **New: results JSON** (format 1). It holds:
  - the study as run (with defaults), PackTherm version, time and run time;
  - a summary (designs, feasible, on the front, temperature limit), the picks and notes;
  - the main assumptions (resolution, reference flows and pressure drops, efficiencies, chiller, wall, resistance margin, pack parts);
  - every design.

  NaN and infinities are written as null, so the file is strict JSON. It will be the API's response format.
- **New: segments duties** in study files: `steps: [[duration_s, c_rate], ...]` (negative C-rate charges), for a custom duty without a CSV.
- **Changed:** `packtherm design --level module` builds a study document from its flags and runs it. The CLI and study files can't diverge, and it now also writes the results JSON. Output files are otherwise unchanged, and so are the results: the road-trip study through a study file reproduces the v0.5.0 CSV exactly.
- **New: README numbers checked in CI** (`tests/test_docs.py`): the current version against the roadmap and CHANGELOG, the road-trip picks and claims, the WLTC claims, the module comparison table and the validation figures, all against the committed example results. A model change that moves a quoted number now fails CI until the README is updated.
- Example study files for the three example studies (`docs/examples/*.yaml`), with their results JSON. Tests check that each file is exactly what its `packtherm design` command runs.
- README: study-file quick start; fast mode under "What the model covers"; study time corrected to 2–3½ minutes.
- New dependency: PyYAML (≥ 6.0).
- `packtherm.cli.parser()` returns the argument parser.
- `docs/STUDY_FILES.md`: every key of the study and results formats; a test checks that every key the format accepts is documented there. A test also checks the README's M50 heat claims against `validation/m50_vs_dfn.csv`.

## 0.5.0

Fast and normal modes, the first v0.5 mini update.

- **New: fast mode.** `packtherm design ... --fast`, `packtherm module ... --fast`, `ModuleStudy(mode="fast")` and `compare_modules(mode="fast")`.
  - Settings: 5 s thermal step, 0.3 mm radial spacing, 12 plate layers, 8 ribbon slices.
  - Speed: 5.0–5.5× quicker on the three example studies (road trip 196 s → 38 s on two cores).
  - Accuracy over all 117 designs: hottest cell within 0.12 K, in-cell spread within 0.19 K, recovery within 2 min, energy within 0.6 %. No design changes verdict and the picks are the same.
  - Details in `docs/FAST_MODE.md`. Normal mode stays the default.
- **New: electrical substeps.** `ElectroThermalLoad(max_substep=...)` runs the cell model in steps of at most that length inside a longer thermal step, and logs one averaged entry per thermal step. A drive cycle's second-by-second current is followed whatever the thermal step. It takes a single step when the current is constant across the step. The log gains `I_abs_A` (mean absolute current), and studies now use it for energy throughput, so drive and regen within one step don't cancel.
- **Changed: exact region volumes in module simulations.** A uniform radial mesh puts each node wholly in the cell or the filler, so the filler's volume (and heat capacity and latent heat) was only right to half a node. Each region now gets its exact volume (`Geometry.exact_volumes`; the module model's default). Effect in normal mode: peaks move by at most 0.09 K (sealed RT42 at 1.5C), with no verdict changes. The thesis model and its parity tests are unchanged.
- **Faster electrical model:** scalar OCV interpolation without `np.interp` (identical results), which helps both modes.
- `Resolution` and `RESOLUTIONS` (in `packtherm.module`) hold the settings for each mode.
- Examples regenerated in normal mode; README quick start, roadmap and BACKLOG updated.

## 0.4.13

A physics and minor-bug audit: every model file read against its physics, numerical convergence checked, and every CLI option tried with bad input.

- **Changed: coolant flow laws.** The module's coolant channels are laminar (Reynolds number about 3–550 for any plausible number of cells per channel; ribbon ports under 2 mm, plate channels 4 mm high). Up to v0.4.12 they used turbulent laws (h ∝ flow^0.8, Δp ∝ flow²).
  - h now depends only weakly on flow. Ribbon ports are fully developed within a few cells, so their h doesn't depend on flow. Plate channels are still developing (Lévêque): h ∝ flow^1/3. The exponent is set by `Coolant.h_flow_exponent`; the default comes from the cooling layout.
  - Pressure drop across the module channels ∝ flow (Hagen–Poiseuille); the rest of the loop (hoses, Re ≈ 4,000) stays ∝ flow².
  - Results at the 0.05 g/s reference flow are unchanged.
- **Changed: air flow laws.** The air crosses the array of cans, so it is cross-flow over a bank of cylinders (Re ≈ 1,200–5,000 on the can diameter). h ∝ v^0.6 (Žukauskas, staggered banks) and Δp ∝ v^1.8, with v ∝ flow / gap. This replaces h ∝ flow^0.8 / gap and Δp ∝ flow² / gap³ (v0.4.12). Results at 0.3 g/s and a 2 mm gap are unchanged.
- **Fixed: in-cell spread of plate designs was about 0.4 K low.** The coolest point was taken at the centre of the bottom layer, half a layer above the cooled face, so the spread depended on the grid: 5.35 / 5.75 / 5.95 K at 8 / 16 / 32 layers for the M50 at 1.5C. It is now taken on the roll's base face (and on the cooled can face for ribbons) and gives 6.14 K at every grid. The 2D model now matches the exact solution within 1 % (test tightened from 3 %).
- **Fixed: datasheet temperature warnings** compared the whole run's peak with the charging limit. A hot discharge followed by a cooler charge was reported as a charging breach. Each limit is now judged on the peak while that kind of current flows. The design studies' own limits were not affected.
- **Fixed: datasheet current limits.**
  - The Panasonic NCR18650PF's 10 A discharge and 1,375 mA charge limits were written as C-rates against the 2.9 Ah rating, but the model converts with this cell's measured 2.995 Ah, so they allowed 10.3 A and 1.50 A. They are now exact currents.
  - The LG MJ1 had no charge limits; it now has the product specification's 3.4 A and 45 °C.
- **Fixed: CLI input.**
  - Every numeric option is checked when parsed (flows, C-rates, cycles and margins > 0; SOC 0–1; ribbon contact (0, 1]). For example, `--c-rate 0` crashed and `--cycles 0` or `--r-margin -2` ran a full study.
  - Unknown cells, fillers and topologies, and invalid combinations, give a one-line error instead of a traceback.
- **Fixed, smaller:**
  - `compare_modules` measured the coolant rise from its first-step temperature rather than the inlet. That understated it whenever the coolant warmed in the first step, as chilled coolant does (4.4 K reported against 8.4 K for a 15 °C inlet at 1C).
  - "1 module designs" now reads "1 module design".
  - The PF road-trip name showed "0.459098C".
  - The forced-air error message used API wording.
  - The Coolant docstring said 13 L/min for a 4,400-cell pack; the example pack is 3,360 cells at 9.5 L/min.
  - The module advisor's docstring still described scoring on the outlet cell with an axial estimate.
  - `compare_modules` was missing from `packtherm.module.__all__`.
- **Checked, no change:**
  - Energy balance closes to 1e-11 in every layout.
  - A 2 s step is within 0.07 K of 0.5 s.
  - Ribbon angle grid converged (12 vs 24 slices: 0.01 K).
  - RT42 data-sheet values; M50 stoichiometry windows (the parameter set's initial state, a 4.2 V full charge; PyBaMM's own calculation assumes 4.4 V); chiller COP law; road-load power at 130 km/h (0.45C).
- **Effect on the examples.** M50 road trip at 35 °C: same three picks (air 39.5 °C, plate 40.4 °C, ribbon 39.2 °C); 23 of 39 designs feasible (was 24). A chilled plate at 0.05 g/s now fails on in-cell spread (5.3 K), as does a 0.05 g/s plate with RT42 at 1.5C (5.1 K).
- Docs: the README roadmap lists every version from v0.1. The README module table shows the corrected spreads (plate 6.1 K) and the flow finding (tripling the flow buys 0.8–1.0 K for 20× the pump power). BACKLOG is updated.

## 0.4.12

An audit of every documented command, message and claim, plus the documentation rebuilt around the module tool.

- **Fixed: crash on gaps below the ribbon minimum.** `packtherm design M50 ... --gaps 1.5 2 3` (the README example) failed with "Index contains duplicate entries": every gap under 3.5 mm widens to 3.5 mm for a ribbon, so the same design appeared several times. `ModuleStudy.designs()` now keeps one of each.
- **Fixed: air cooling did not depend on the gap.** Forced air now scales with the gap at fixed mass flow: h ∝ 2 mm / gap and pressure drop ∝ (2 mm / gap)³ (laminar channel, fixed Nusselt number; `AirFlow.gap_ref_mm`). A module sets the gap on its air flow. Results at the 2 mm default are unchanged.
- **Fixed: messages.**
  - A study with feasible designs that all fail the worst-case re-check said there was no feasible design; it now says "No robust design", lists each with its nominal and worst-case peak, and suggests what to change.
  - The chilled pull-down note appeared whenever a chilled bottom plate was in the sweep; it now appears only when one fails on uneven cooling.
  - `packtherm module --compare` printed the gap-widened note once per ribbon design, and its header showed the requested gap; the header now shows the gaps actually used, and the output has a `gap_mm` column.
- **Fixed: trade-off chart labels.** Pick labels could overlap each other and the legend when picks sat close together, and a long footnote ran off the edge. Picks are now numbered badges with a key under the plot, the legend sits below the axes, and the footnote wraps.
- **CLI:**
  - `packtherm design`: `--no-edge-cells` and `--wall-u`; progress line says which cells are simulated; clearer help for `--cell-to-cell-max` and `--cells-in-pack`.
  - `packtherm module --edge` runs the edge cells.
  - `packtherm cells` shows each cell's model (measured circuit, derived circuit or lumped DCIR); `R0_mOhm` renamed `DCIR_25C_mOhm`, with a note on what it is used for; capacity rounded.
- **Package:** the top-level docstring, `module.py` docstring and `pyproject.toml` description describe the module tool; project URLs added; `LG_M50_LUMPED`, `with_R0`, `PackHardware`, `hardware_mass_per_cell`, `Chiller`, `PlateGeometry`, `RibbonGeometry`, `Wall`, `compare_modules`, `ModuleDesign`, `ModuleStudy`, `run_module_study`, `DutyCycle` and `Requirements` exported.
- **Docs:**
  - README rebuilt around the module tool: design result first, then the 2D fields, then validation. Thesis-era results, figures and the version table moved to `docs/HISTORY.md` (`docs/history/`).
  - New figures: model picture with edge cells and the 2D slices; 2D temperature fields (`make_fields.py`); cold-weather validation before and after v0.4.10 (`make_validation_compare.py`); M50 circuit against the physics model (`validation/check_m50_ecm.py`, `make_m50_check.py`).
  - VALIDATION.md: 48 blind tests plus one calibration test (was "49 blind"); thermal median 0.60 K; new LG M50 section.
  - BACKLOG.md restructured into open items and a resolved log; stale items removed (pump efficiency, uniform ribbon contact, speed, licence).
  - Example studies regenerated.
- **Effect:** same picks; no result at the default 2 mm gap changes.

## 0.4.11
- **LG M50 equivalent circuit** (`cells.LG_M50_ECM`, now on `LG_M50`): derived, not measured. PyBaMM's DFN with the ORegan2022 parameter set (measured on the LG M50T, with temperature dependence) was run through synthetic HPPC tests at 25, 10, 0 and −10 °C, and the PF cell's circuit fitted to them (`validation/derive_m50_ecm.py`). OCV table `data/lgm50_oregan2022_ocv.csv`.
  - Pulse overpotential within 3.6–4.7 % (median) at every temperature; replay within 21–23 mV above 10 % SOC.
  - Irreversible heat within 0.94–1.13× of the DFN on 0.5–1.4C discharges and a pulsed profile at 0–25 °C; the lumped model it replaces was 0.92–1.42× (over-predicting pulsed loads by 24–42 %).
  - The M50 now stops at its voltage cut-off. The knee comes late in the cold (up to 0.75 Ah after the DFN at 0 °C 1.4C); the lumped model had no cut-off.
  - `LG_M50_LUMPED` (CLI key `M50-LUMPED`) keeps the previous model.
- **Fixed:** the worst-case resistance re-check only scaled the lumped R0, so for equivalent-circuit cells (the PF, now the M50) it did nothing. `cells.with_R0` now scales R0, the slow branch and the charge-transfer term together.
- **Effect:** same picks; M50 road-trip peaks 0.5–0.9 K lower.

## 0.4.10
- **Cold-weather cell model** (Panasonic NCR18650PF): two temperature laws identified from the 0.9 A discharge-and-rest steps between the HPPC pulse sets at 25, 10, 0 and −10 °C (identification data, not in the validation set; `identify_panasonic.cold_laws`):
  - the low-SOC rise grows in the cold (`ECM.Ea_soc`, 20.7 kJ/mol), so the voltage knee arrives earlier: the cold capacity loss;
  - the slow branch follows its own Arrhenius law (`ECM.Ea_Rd`, 26.8 kJ/mol) instead of the charge-transfer kinetics (45 kJ/mol), which made it about twice too large at 0 to −10 °C.
  - R_d and τ_d re-calibrated on the same single test with these laws (28.4 mΩ, 405 s).
- **Blind validation (48 tests), predictive mode:** within 1 K 79 % → 88 %; −20 °C median 1.28 → 0.73 K; cold voltage error 177/84/40 → 70/53/34 mV at −20/−10/0 °C; overall median 0.63 → 0.65 K. In the cold the model now under-predicts heat by 7–10 % (worst −3.5 K) where it used to over-predict (worst +3.4 K). Thermal mode unchanged.
- **Not changed:** NCA entropic heat. Published NCA/graphite profiles disagree on the sign over the SOC range that matters, so no curve is applied (see docs/VALIDATION.md).
- The four combinations of the two laws were compared on the blind tests before choosing; only the M50/MJ1-independent PF electrical model changes.

## 0.4.9
- **Side ribbon on a strip of the can** (`model2d.simulate_rtheta`, `model2d.Strip`): ribbons are now solved on a radius × angle grid (12 slices over half the circumference, by symmetry). The ribbon cools the can over its contact share; heat reaches it round the circumference along the spiral winding (in-plane conductivity, as along the height) and through the steel can (0.25 mm, 50 W/m·K, assumption). `simulate_module(..., n_theta=0)` keeps the radial model with the contact spread evenly.
- The 2D bottom-plate and ribbon grids share one solver core (`model2d._run`), which reports heat and sink flows per whole cell when the grid covers a symmetric part.
- **Checked:** a full wrap matches the radial model within 0.02 K; 12 and 24 slices agree within 0.05 K; quasi-steady heat into the coolant matches generation; energy balance < 1e-6 %.
- **Effect:** ribbon peaks rise 0.1–1.0 K and the in-cell spread 0.5–1.6 K (the far side of the can runs warm). All ribbon designs that passed still pass. At 1.5C the lowest-energy pick moves to the 0.05 g/s ribbon (the 0.02 g/s RT42 design no longer survives worst-case resistance). Road-trip study: about 3 minutes.

## 0.4.8
- **2D bottom-plate model** (`packtherm.model2d`): bottom plates are now solved on an axisymmetric radius × height grid (16 layers by default) with the winding's axial conductivity, the roll-end resistance, interface and coolant film at the base, an adiabatic top and, for edge cells, the module wall. Same enthalpy–Newton scheme as the radial model; the sparse factorisation is reused until a PCM node changes phase band, which makes it about 15× faster than refactorising every iteration. `simulate_module(..., nz=0)` keeps the v0.4.7 radial model with its quasi-steady axial estimate.
- **Checked** against the exact steady solution for a base-cooled cell (top and top-to-base spread within 1 % and 3 % at 8 and 16 layers), with PCM filler and with the edge wall; energy balance closes to 1e-6 %.
- **Effect:** at 1.5C the bottom-plate peaks fall 0.1–0.45 K and the in-cell spread 0.15–0.7 K (the estimate was conservative, as intended). New finding: a chiller pulling a hot-soaked pack down through its base opens top-to-bottom gradients of up to 6 K while it does so, so three chilled bottom-plate designs now fail the 5 K in-cell limit on the 35 °C road trip. Studies with bottom plates take about twice as long.

## 0.4.7
- **Coolant thermal mass:** the coolant held in each cell's share of the channel (`module.coolant_holdup_kg`, from the v0.4.3 plate and ribbon geometry, about 1 g per M50 cell) stores heat. Energy balance M·cp·dTc/dt = (ṁ·cp/frac)(T_in − Tc) + ΣG(T − Tc), solved implicitly each step, so the outlet coolant lags heat input by about M/ṁ (about 20 s at the reference flow). `simulate_module(..., coolant_mass=False)` restores the steady balance. The hardware mass model now uses the same holdup function.
- **Effect:** peaks on the long M50 duties move by under 0.1 K and recovery by about a minute; the term matters for short pulses and start-up.

## 0.4.6
- **Edge cells** (`simulate_module(..., edge=True)`, `module.Wall`): a cell on the module wall exchanges heat with ambient through a third of its share (it has 4 neighbours instead of 6), at U = 5 W/m²K (assumption). `Wall(fraction=0.5)` for corner cells.
- **Advisor** (`ModuleStudy.edge_cells`, on by default): edge cells at both ends of the channel are simulated; feasibility uses the hottest of interior and edge cells, and the cell-to-cell spread is hottest minus coolest. New columns `T_peak_interior_C`, `T_peak_edge_outlet_C`, `T_peak_edge_inlet_C`, `hottest_cell`.
- **Effect (M50, 35 °C road trip):** cooled modules' edge cells run 0.1–0.8 K cooler than interior cells; a sealed module's edge cells run 8 K cooler; in chilled designs the edge cells are the hottest, by hundredths of a degree. Same picks. Studies take about 60 % longer (two more cells per design).

## 0.4.5
- **Whole-loop pump power.** `Coolant.dp_loop_ref_Pa` (30 kPa) adds the rest of the loop (hoses, manifolds, chiller, radiator) to the module channels (20 kPa); 50 kPa in total matches the 0.5–0.6 bar small electric coolant pumps are rated for at 20–25 L/min. Pump efficiency 0.5 → 0.3, from the same datasheets (Pierburg CWA50, Rheinmetall CWA 50). Pump power per cell 1.9 → 7.9 mW (about 26 W for a 60 kWh M50 pack).
- **Radiator fan energy** (`ModuleResult.radiator_fan_energy_Wh`): 3 % of the heat the coolant carries to the radiator, whenever the chiller is not running (assumption).
- **Effect:** liquid cooling costs about 0.05 % of the energy moved on the 35 °C road trip (was about 0.001 %), still about 5× less than the lightest air design. The bottom plate and the ribbon now tie on energy, so the lowest-energy pick moves to the bottom plate; the ribbon stays the balanced pick.

## 0.4.4
- **Chiller accounting** (`packtherm.module.Chiller`):
  - COP falls with ambient: a share (0.42) of the Carnot COP between an evaporator 5 K below the set-point and a condenser 15 K above ambient. About 3.0 at 35 °C with a 15 °C set-point (the old fixed value), 2.4 at 45 °C, 4.0 at 25 °C. `--cop` still fixes it.
  - Heat leaking into a chilled pack from a hot day is charged to the chiller: cell heat capacity / 9 h pack time constant × (ambient − set-point).
  - The chiller runs during the event, then the loop hands back to the radiator (`Coolant.chiller_until_s`, `--chiller-runs event|always`). Before, the chiller held the set-point forever in the simulation and its energy was cut off at an immediate "ready" time.
- **Effect:** chilled designs cost 1.2–2.1 % of the energy moved on the 35 °C road trip (was 1.1–2.0 %). Same picks.

## 0.4.3
- **Cooling hardware mass from geometry** (`packtherm.hardware`), replacing the flat kg per kWh in the module advisor:
  - cold plate: base and channel sheets over the cell's footprint, coolant in the channels, gap filler under the cell (`PlateGeometry`);
  - side ribbon: the cell's share of an extruded multi-port tube (walls and ribs), coolant inside, bond to the can (`RibbonGeometry`);
  - pack-level parts per cell: liquid loop, air system, chiller (`PackHardware`, with `--pack-kwh`, `--liquid-loop-kg`, `--air-system-kg`, `--chiller-kg`);
  - defaults sourced from supplier data (AMAG, Boyd, XD Thermal, Dow, Bostik); the rest labelled as assumptions;
  - mass breakdown columns in the design CSV (`mass_hw_aluminium_g`, `_coolant_g`, `_interface_g`, `_pack_share_g`).
- **Changed:** liquid hardware drops from 1.0 to about 0.3 kg/kWh and air from 0.5 to 0.07. M50 road trip at 35 °C: forced air +1.8 % mass (was +13 %), side ribbon +7.2 % (was +27 %). Same picks.
- **Changed:** the side ribbon covers 75 % of the can height, and its contact conductance is scaled to match (it assumed full height).
- **Changed:** the ribbon's minimum gap is the tube plus two bond lines (3.5 mm by default, was a flat 1.5 mm). The advisor and `packtherm module` widen the gap to fit, and the tube's volume is taken out of the filler.
- `Interface.rho` (gap-filler density). Heatmap rows carry the gap when it varies, so filler columns stay aligned. Pick labels sit closer to their point.

## 0.4.2
- **Renamed to PackTherm.** GitHub repo `EV_BTMS` → `PackTherm` (old links redirect), Python package `btms` → `packtherm` (`import packtherm`), command `btms` → `packtherm`. Entries below keep the old names.
- **New model picture** (`docs/figures/model_overview.svg`, drawn by `make_model_diagram.py`): the module, one cell's share solved in 1D, and the design loop. Replaces the thesis cell–PCM–casing figure in the README.
- **Fixed:** v0.4.1 never reached `main` (PR #8 merged into the v0.4 branch after it had been merged); brought across in #9.
- **Fixed:** `matlab/main_simulation.m` called `plot_additional_results.m`, which was never committed. It now calls `generate_thesis_figures.m`, the routine that replaced it.
- **Fixed:** trade-off chart pick labels could cross the front line. Labels now sit below-left of each pick, where the front's staircase never runs.

## 0.4.1
- **Design advisor on the module model** (`btms.module_design`, now the default for `btms design`):
  - design variables: topology (sealed / forced air / bottom plate / side ribbon), flow per cell, chiller inlet, gap filler, gap;
  - scored on the coolant-outlet cell; the inlet cell gives the cell-to-cell spread, with an optional limit (`--cell-to-cell-max`, fail reason `spread`);
  - fan and pump energy from flow and pressure drop, chiller energy from the heat taken by sub-ambient coolant ÷ COP;
  - mass = filler + cooling hardware; gap volume reported as `volume_overhead_pct`;
  - the v0.3 single-cell advisor stays available as `btms design --level cell`.
- **Fixed:** the advisor used the thesis pump anchor (about 400 mW per cell for liquid), about 200× the pump power computed from flow and pressure drop (1.9 mW).
- **Fixed:** forced-air h was fixed while flow changed fan power and air rise. h now follows flow (h ∝ flow^0.8); `AirFlow.with_h()` finds the flow for a target h. `btms module --h` is replaced by `--air-flow`.
- **Fixed:** chiller energy was missing from the module model (`ModuleResult.chiller_energy_Wh`).
- **Fixed:** a side ribbon could be placed in a gap too small for it; it now needs at least 1.5 mm (`SideRibbon.min_gap_mm`).
- **Changed:** the bottom-plate axial estimate uses the smaller of generated heat and heat reaching the coolant, rather than generated heat alone. Still an upper bound; bottom-plate in-cell ΔT at 1.5C drops from 9.3 K to 6.4 K.
- Front, robustness and picks are factored into `design.select_front`, shared by both advisors. Trade-off chart: n/a cells for invalid combinations, adaptive log threshold, labels kept inside the axes.

## 0.4.0
- **Module-level model** (`btms.module`, `btms module`):
  - one cell in a packed hex or square array, as an equivalent annulus with an adiabatic outer edge;
  - gap filler: air, PCM or composite PCM;
  - cooling: forced air, bottom cold plate (axial conduction, roll-end resistance, thermal interface), side ribbon (contact fraction), or none;
  - coolant and air warm along the channel, solved in balance with the absorbed heat (stable at any contact-to-flow ratio); inlet and outlet cells are both reported;
  - flow sets h, the coolant rise and pump/fan power.
- **Solver:** distributed sinks with a state-dependent sink temperature (`model.Sink`). The heat taken by each sink and its temperature are returned.
- **Composite PCM grades** (`<grade>-EG`, Yu et al. 2023): k = 3.85 W/m·K, latent heat × 0.86.
- `Cell.k_axial`: in-plane conductivity of the winding (25 W/m·K for NMC811 layers).
- **`btms cell --pcm-grade`** to choose the PCM for single runs.
- Tests: analytic bottom-plate steady state (within 3 %), coolant heat balance, adiabatic interior cell, air-flow equivalence with the bare-cell model, stability at extreme contact-to-flow ratios.

## 0.3.2
- **Validation** (`btms.validation`, `validation/`, `docs/VALIDATION.md`) against 49 tests of the Panasonic NCR18650PF (Kollmeyer 2018, CC BY 4.0) at 25 to −20 °C. Thermal mode: 0.59 K median RMSE. Fully predictive: 0.62 K. Regression gates are in `tests/test_validation.py`.
- **Equivalent-circuit electrical model** (`btms.ecm`):
  - OCV table, ohmic R0, Butler–Volmer charge-transfer overpotential with Arrhenius I₀(T), a slow diffusion RC branch, and a low-SOC factor on discharge;
  - heat = I·(OCV − V);
  - discharge stops at V_min; charging switches to CV at V_max and ends at the current cut-off.
- **New cell** `PF` (Panasonic NCR18650PF), identified from the dataset's own C/20 and HPPC tests (`validation/identify_panasonic.py`).
- `MeasuredHeatLoad` for thermal-only validation from logged current and voltage.
- `SimulationResult.T_surface`: outer-surface temperature at every step.
- Cells without an ECM (M50, MJ1) keep the lumped I²R path unchanged.

## 0.3.1
- **Passenger-EV duties** (`btms.ev`): WLTC Class 3b trace (UN GTR 15), road-load vehicle model, pack sizing, a 3× WLTC duty, and a motorway-then-rapid-charge road trip.
- **Continuous cooling:** h sweeps with fan-law power (P ∝ h^3.75), anchored to the thesis levels. The thesis levels are still available via `thesis_cooling_options()` / `--thesis-levels`.
- **Chiller:** a coolant setpoint below ambient as a design option, with chiller energy = heat removed ÷ COP.
- **PCM library** (`btms.materials`): RT28HC, RT31, OM35, RT42, with grade as a design variable alongside thickness.
- **Robustness:** worst-case resistance = published max × (1 + 20 % margin). Front designs that fail are marked fragile and the front is rebuilt without them.
- **Fixed:** fan/pump energy now covers event + recovery (it previously covered the event only).
- **Fixed:** design studies report datasheet C-rate breaches, judged on a 30 s rolling mean.
- Solver 2.6× faster (direct LAPACK tridiagonal solve, precomputed enthalpy masks). Optional `store_every` cuts memory for long runs.
- Separate initial and sink temperatures in `simulate_cell`.
- New `docs/BACKLOG.md`: known limitations and the improvement plan.

## 0.3.0
- Design advisor (`btms.design`): sweeps cooling option × PCM thickness for one cell and duty cycle.
- Feasibility checks peak temperature, in-cell ΔT and recovery (ready for the next event), with a reason recorded for each failure.
- Costs are mass overhead (PCM + sleeve + cooling hardware, % of cell mass) and fan/pump energy (% of throughput).
- Pareto front plus three picks (lightest, lowest energy, balanced). Front designs are re-checked at worst-case cell resistance.
- Trade-off chart (`btms.report.plot_tradeoff`): scatter of mass vs energy, and a grid of peak temperatures with failure reasons.
- `btms design` CLI writes a CSV and PNG. Studies run in parallel.
- Duties stop drawing current at the end of the event, so the rest period is a true rest.
- matplotlib added as a dependency.

## 0.2.0
- Electro-thermal load: Q = I²R(SOC,T) − I·T·dU/dT, coulomb-counted SOC, SOC windows.
- Cell library: LG M50 (21700) and LG MJ1 (18650) with cited parameters; jelly-roll cp and k from O'Regan 2022 layer data.
- Current profiles: constant C-rate, piecewise segments (optionally repeating), CSV import.
- Datasheet limit warnings (`check_limits`).
- Solver: Newton on the enthalpy residual is now the default (`SolverSettings.scheme="enthalpy"`). It converges on every step, about 3× faster, with machine-precision energy balance. The thesis scheme is still available and parity-tested.
- CLI subcommands: `btms thesis`, `btms cells`, `btms cell`.
- `metrics.summarise_result` works for any run, not just thesis scenarios.

## 0.1.0
- Python port of the MATLAB thesis model with bit-for-bit parity tests, README and CI.
