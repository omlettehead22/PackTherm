# Fitting a cell model to test data

`packtherm fit` fits PackTherm's circuit model to tests of a cell, and writes:

- a **fitted cell file** (YAML): the values, where each came from, how certain it is, where the model is valid, its errors, and what went in;
- an **HTML report** beside it: the same, with charts, on one page you can send.

**Fitted at three temperatures or more, with a cell named for its size, mass and thermal properties, the file can be used in studies** (`cell: my_cell.yaml`). Fitted at one temperature, studies refuse it: a cell's losses change several-fold between −20 and 25 °C, and borrowing that behaviour would make every thermal result look more certain than it is.

The tests are read as in [TEST_DATA.md](TEST_DATA.md) (CSV, compressed CSV or `.mat`, any common tester export).

## The test list

A test list (YAML) names the tests by temperature. Paths are relative to it.

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
    pulses: hppc_25.mat     # a pulse (HPPC) test; optional with discharges or cycles (v0.6.6)
    steps: steps_25.mat     # optional: steady steps with rests after them
    discharges: [dis1c.mat] # optional: full discharges at a working rate
    cycles: [cycle1.csv.gz] # optional: drive cycles to fit on
    start_soc: 1.0          # where the discharges and cycles start (default 1: full)
  - at: 0
    pulses: hppc_0.mat
    cycles: [cycle1_0C.csv.gz]
checks:                     # optional: tests the fit never sees, predicted afterwards
  - {file: udds_25.csv.gz, start_soc: 1.0, ambient_C: 25}
compare: PF                 # optional: a library cell to predict the checks with too
chamber_h_W_m2K: 38.7       # optional: the test chamber's convection, for the thermal check; or instead
chamber_calibration:        # calibrate the rig on tests that are fitted to (heat from their measured voltage)
  - {file: dis1c.mat, start_soc: 1.0, ambient_C: 25}      # a steady test: the convection
  - {file: cycle1.csv.gz, start_soc: 1.0, ambient_C: 25}  # a drive cycle: the fixture's heat capacity
output: pf_fitted.yaml      # optional: where to write the fitted cell file
```

```
packtherm fit tests.yaml
```

At one temperature, flags do the same without a list: `packtherm fit --slow c20.mat --pulses hppc.mat --steps steps.mat --check udds.mat --compare PF`.

| Test | What it gives |
|---|---|
| Slow discharge (C/10 or slower, from full to the cut-off), at one temperature | The open-circuit voltage and the capacity |
| Pulse test (HPPC) at each temperature, with a rest of 20 min or more somewhere to fix the state of charge | The instant resistance, the charge-transfer branch (seconds) and the middle branch (tens of seconds). Optional where there are discharges or drive cycles (v0.6.6): the kinetics then come from their sudden changes in current (below) |
| Long tests at each temperature: steps with rests, full discharges, drive cycles | The slow branch (minutes) and the rise near empty. **A drive cycle or a full discharge at each temperature matters**: without them the slow branch is fitted on steps alone, and the cold behaviour is poorly known (see the results) |
| Checks | Not fitted to: predicted afterwards, as the honest test of the fit |

**The test rig.** The thermal checks run the cell in a model of the rig: the chamber's convection (h) and, if calibrated, the heat capacity the cell's fixture adds (clips, leads, holder). Give h (`chamber_h_W_m2K`), or calibrate the rig on tests that are fitted to, never the checks (`chamber_calibration`). The heat comes from each test's measured voltage, I · (OCV − V), so the circuit model plays no part beyond the open-circuit voltage. With one test, h alone is fitted. With two or more, a steady one (a constant-current discharge) and a dynamic one (a drive cycle), the fixture's heat capacity is fitted too: a steady test's rise sets h, and a drive cycle's peaks the heat capacity. Both belong to the rig. They are used for the checks only and never stored on the cell.

## The model

The model is the one PackTherm's electro-thermal runs use (`packtherm.ecm.ECM`):

- the open-circuit voltage, from a table over the state of charge, and with slow tests at several temperatures, one table at each (v0.6.5);
- an instant (ohmic) resistance `R0`;
- a charge-transfer branch: a Butler–Volmer-shaped overpotential `gamma · 2RT/F · asinh(I / 2I0)`, reached with time constant `tau_ct` (seconds);
- a middle branch: resistance `Rm`, time constant `tau_m` (5 to 120 s, below the slow branch's range since v0.6.5). New in v0.6.2; off in the library cells;
- a slow branch: resistance `Rd`, time constant `tau_d` (minutes);
- a rise of all of them near empty, `1 + soc_a · exp(−SOC / soc_b)`, on discharge.

**Values by temperature.** A cell fitted at several temperatures holds every value at each one. PackTherm interpolates between them (in 1/T, logarithmically: an Arrhenius law between neighbours). Beyond the coldest and warmest, the resistances and rates follow laws fitted through the temperatures' own values (`Ea_R0`, `Ea_I0`, `Ea_Rm`, `Ea_Rd`, `Ea_soc`), and the shape and time constants hold. Studies warn when a run goes beyond the tested temperatures (by more than 2 K) or rates.

**The open-circuit voltage by temperature (v0.6.5).** A cell can deliver less charge in the cold, or the heat: the LG HG2 gives 2.78 Ah at C/20 at 25 °C, 2.69 Ah at 40 °C and 2.49 Ah at −20 °C. Give a slow discharge at each temperature (`temperatures[].slow`), each starting full. Each becomes an open-circuit curve, all against the same state of charge: the charge left, as a share of the reference capacity (the top-level `slow` test's). A curve whose test delivered less ends at a state of charge above 0, so the cell there reaches its cut-off sooner. Charge is still conserved as the cell warms or cools. Between curves, the voltage at a state of charge is interpolated linearly in temperature; beyond the coldest and warmest, those curves hold. A rest's voltage is read through the curve at the cell's temperature there, too. Without slow tests at other temperatures, one curve serves them all, as before.

Fitted cell files name the model (`model.form: packtherm-circuit-1`) and hold it in full (`model.ecm`). The fitting code treats a model as an interface (parameters, a simulator, what PackTherm runs), so a generic circuit with a chosen number of branches can share everything else.

## How it fits

1. **Open-circuit voltage and capacity** come from the slow discharge. Its charge to the cut-off is the measured capacity. Its voltage, plus the cell's own drop at that current (the fitted model's steady resistance at the slow test's temperature, rising near empty as the model's does), is the open-circuit curve. The slow discharges at other temperatures, if given, are read the same way, each with the drop at its own temperature, onto the reference capacity's state of charge.
2. **State of charge** through each test is anchored at a settled rest (20 min or more), where the voltage is the open-circuit voltage, or given (`start_soc`). It's carried by the charge counted, including charge moved while logging paused and across steps between two samples, both from the tester's own counter.
3. **Through time.** Each pulse (5 s before it to 40 s after), each rest after a step, and each long test is replayed through the same simulation PackTherm runs (a test checks they agree to 1e-9 V) and scored on its voltage.
   - Pulses and rests are scored on the change from their first sample; long tests on the voltage itself, down to the knee near empty (40% of the way up from the cut-off: 3.18 V here).
   - Pulses that follow each other within a minute are replayed from the last long rest before them.
   - Long tests logged every 0.1 s are thinned to 1 s, with each interval's mean current from the charge counted.
4. **In stages, at each temperature**, each part of the model on the tests that show it:
   1. the kinetics (R0, the charge-transfer and middle branches) on pulses at 20–95% state of charge;
   2. the slow branch on the long tests only. Fitted with the pulses, both slower branches go to the pulses' seconds and tens of seconds, and the minutes a drive cycle's heat builds over are lost: predicted drive cycles ran cold;
   3. the rise near empty on the pulses and the long tests run to their end;
   4. the kinetics again, on all the pulses.

   **No pulse test (v0.6.6).** Plenty of datasets have none: the A123's has slow discharges and drive profiles only. Then the kinetics come from the long tests themselves. Each sudden change in current (0.5C or more from one sample to the next: a load after a rest, a step inside a drive cycle) gives a window from 5 s before it to 60 s after, scored on the change from its first sample, as a pulse is. Windows don't overlap. They're parts of the long test's own replay, which runs from its rested start, so they need no settled rest before them: whatever is still relaxing from the load before is in the replay. Stages 1 and 4 use those at 20–95% state of charge (a test run to empty has as many below 20% as above, and the slope of the open-circuit curve there would set the kinetics). Without a pulse test, the file says so (`provenance.settings`), and its errors are under "changes in current".

   **The middle branch's time constant, two ways (v0.6.3).** Pulses can leave it loose. The Samsung 30T's 25 °C pulses fit just as well (10 mV) with it at 30 s as at 290 s. At 290 s, a middle branch four times too strong held its 1C discharge 50–60 mV low. So where there are long tests, the stages run twice. Once `tau_m` comes from the pulses, as above. Once it comes from the long tests, fitted in stage 2 with the slow branch and held in stage 4. The way that fits the temperature's discharges and drive cycles better is kept, as long as its pulses at 20–95% fit within 10% of the other way's. Only the fitted tests decide, never the checks. Each temperature's choice is in the file (`by_temperature[].tau_m_from`). The fit takes about twice as long.

   Three rounds: each stage holds the others' values from the round before, and the open-circuit curve and state of charge are updated between rounds.
5. **Across temperatures**, each temperature's own values become a row of the table, and straight lines through them (log value against 1/T) give the laws beyond.

## What the file holds

| Key | What |
|---|---|
| `status`, `usable_in_studies`, `why_not_usable` | `single-temperature` or `multi-temperature`; whether studies can use it, and if not, why |
| `like` | The cell whose size, mass and thermal properties go with these values |
| `model` | The form, the model in full (`ecm`: every value and the table by temperature), and its 10 s DC resistance at mid charge |
| `values` | With several temperatures, the laws (`Ea_*`) with their 95% ranges; with one, every value. Each with its `unit`, `source` (`fitted`, `data`, `default` or `not fitted`), what it is, and any flag |
| `by_temperature` | Each temperature's own values, with 95% ranges and flags |
| `capacity`, `open_circuit_voltage` | Measured, how, and against the rated capacity if given. With curves by temperature, the reference's cell temperature (`cell_C`) and each other curve with its temperature and capacity (`by_temperature`) |
| `valid_for` | What the tests covered: cell temperature, state of charge and C-rates |
| `identifiability` | Pairs of values that trade off (correlation beyond ±0.95) |
| `errors` | RMS and worst error on each kind of test fitted at each temperature, and on each check, in two forms: <br>• voltage, replayed at the check's measured temperature; <br>• with `like` and the rig given or calibrated, run as a study runs the cell (`held_out_electrothermal`): voltage and surface temperature from the current alone, beside the comparison cell's. The rig, and what it was calibrated on, is in `provenance.settings` |
| `data_warnings`, `provenance` | Everything reading the tests flagged; PackTherm version, date, settings, each input's SHA-256, the dataset's citation and licence |

**The 95% ranges** count each pulse, rest and long test as one piece of evidence (a cluster-robust estimate).

- **Why not the usual ranges:** what's left after a fit like this is mostly the model's own misfit, the same shape through a whole pulse. The usual least-squares ranges treat every sample as independent, and claim far too much.
- **What these show:** how far the parts of the tests disagree. They are not a guarantee: on tests made by a known cell, about half the true values lie inside them. The rest are off by a steady few percent that comes from fitting in stages.
- **Flags:** a value at the edge of its allowed range, or poorly determined, is flagged. A value at its edge does not set a law.

## Checked against known answers

`tests/test_fitting.py` makes tests with a cell whose values are known, run through PackTherm's own model, and fits them:

- **At one temperature** (pulses, steps, a 1C discharge):
  - every value comes back within 8%, and R0 within 1%;
  - a drive cycle the fit never saw is predicted to 1.1 mV RMS.
- **At three temperatures** (25, 5 and −15 °C, values following known Arrhenius laws):
  - R0 comes back within 3% at each temperature;
  - the other resistances come back within 12% at 25 and 5 °C;
  - the instant resistance's law comes back within 10%;
  - at −15 °C the 2C pulses hit the cut-off and are cut short, so the cold tests say less. There, each value is within its reported range or within 35%.

## Checked on real data: the Panasonic NCR18650PF

The worked example, [docs/examples/fitting/ncr18650pf_tests.yaml](examples/fitting/ncr18650pf_tests.yaml), fits the Panasonic NCR18650PF (Kollmeyer, CC BY 4.0) at 25, 10, 0, −10 and −20 °C from files in this repository:

- each temperature's pulse test and steps (not at −20 °C: that file is incomplete), in `tests/data/panasonic_18650pf/`;
- each temperature's drive cycle 1, and the 25 °C 1C discharge #1, from `validation/data/panasonic_18650pf/`.

The checks are every other test in the validation set: 43 tests, never fitted to. That's 41 drive cycles, the second 1C discharge and a charge. The fitted cell file and report are beside it ([report](examples/fitting/ncr18650pf_fitted.html)).

Each check is run as a study runs the cell: only the measured current goes in, and voltage and surface temperature come out. The library PF cell, tuned by hand on this dataset over several releases, is run the same way.

| Chamber | Tests | Voltage RMS, library | Voltage RMS, fitted | Within 1 K, library | Within 1 K, fitted | Peak error, library | Peak error, fitted |
|---|---|---|---|---|---|---|---|
| 25 °C | 11 | 16.9 mV | 18.1 mV | 91% | 91% | 0.0 K | −0.8 K |
| 10 °C | 8 | 23.7 mV | **20.9 mV** | 100% | 100% | 0.0 K | −0.7 K |
| 0 °C | 8 | 33.3 mV | **26.9 mV** | 88% | 75% | −0.8 K | −1.6 K |
| −10 °C | 8 | 52.8 mV | **35.9 mV** | 75% | 75% | −1.1 K | −1.0 K |
| −20 °C | 8 | **69.2 mV** | 87.3 mV | 75% | 62% | −0.9 K | +0.1 K |
| **All** | **43** | **32.7 mV** | **26.4 mV** | **86%** | **81%** | 0.6 K | 1.0 K |

All figures are medians, as `packtherm fit` reports them for the worked example. Voltage is scored down to the knee. Peak error is predicted minus measured peak surface temperature; in the "All" row it's the absolute value.

**Reading it:**

- **Voltage:** from tests alone, the fitted cell predicts voltage better than the hand-tuned model from 10 to −10 °C, and as well at 25 °C. It is worse at −20 °C, where the tests pin the least (below).
- **Against v0.6.2:** setting the middle branch's time constant two ways (v0.6.3) took the median from 28.2 to 24.4 mV and the share within 1 K from 79% to 81%.
- **Against v0.6.4:** capping the middle branch at 120 s (v0.6.5) costs the Panasonic a little, 24.4 to 26.4 mV, at 0 and −10 °C, where its time constant had been 138 and 121 s. −20 °C improved from 91.6 to 87.3 mV. The Panasonic has a slow test at 25 °C only, so it keeps one open-circuit curve.
- **Peaks:** it runs colder at its temperature peak, by about 0.8 K at 25 and 10 °C. Through the first 90% of a drive cycle, its heat is closer than the library's to the heat implied by the measured voltage. The shortfall comes in the last minutes near empty, where the voltage collapses faster than the near-empty rise (an exponential) can follow.
- **Cold:** at −10 °C and below, the slow branch sits at the edge of its allowed range. The cold long tests don't pin it down, and the file flags it.

**A caveat on how blind this is.** The fitted values never see the 43 checks. But variants of the method were compared on these same tests while building v0.6.2 and v0.6.3, so the method itself was not chosen blind. The Samsung 30T (below) is the second check, and only partly independent (see there).

**Fitted values at 25 °C:**

| Value | Fitted |
|---|---|
| R0 | 23.4 mΩ (93 mΩ at −20 °C; law 19.0 kJ/mol) |
| Charge-transfer time constant | 1.1 s |
| Middle branch | 18.5 mΩ over 33 s (from the pulses) |
| Slow branch | 26.0 mΩ over 29 min |
| 10 s DC resistance, mid charge, 1.5C | 40.5 mΩ (the library model: 40.6 mΩ) |

## Checked on a second cell: the Samsung 30T

[docs/examples/fitting/samsung_30t_tests.yaml](examples/fitting/samsung_30t_tests.yaml) fits the Samsung INR21700-30T, a 3 Ah high-power 21700 (Kollmeyer and Skells, McMaster University, CC BY 4.0), at 40, 25, 10, 0, −10 and −20 °C. Its tests ship in this repository:

- each temperature's pulse test (four pulses from 1C to 12C, and the discharge steps between levels), and the 25 °C C/20 discharge, in `tests/data/samsung_30t/` (unchanged);
- each temperature's first 1C discharge and drive cycle Mixed1, from `validation/data/samsung_30t/` (made by `validation/prepare_mcmaster.py 30t`).

The checks are the other 82 tests, never fitted to. That's 0.5C, 1C and 2C discharges, and the UDDS, HWFET, LA92, US06 and Mixed2 to Mixed8 drive cycles at every temperature. The rig is calibrated on the 25 °C 1C discharge and Mixed1 (both fitted to): h = 63.3 W/(m² K), and the fixture adds 58 J/K to the cell's own 55 J/K.

**The data, prepared with care** (all in the manifest, `validation/data/samsung_30t/manifest.json`):

- **Ambient:** the dataset has no chamber channel, and the chambers ran off their setpoints: the 25 °C one at about 24 °C, and at −10 °C between −13 and −9 °C. A test's ambient is the cell's temperature after the settled rest before it.
- **Start:** the 0.5C and 2C files begin with the discharge already running. At −10 °C, 1.6 Ah of the 2C discharge went before logging began. Each starts from the charge the tester counted before its first sample.
- **Glitches:** one file logs a block of time twice (kept once), and the rest after a cold test can hold the chamber's ramp back to 25 °C (cut).

| Chamber | Tests | Voltage RMS | Within 1 K | Temperature RMS | Peak error |
|---|---|---|---|---|---|
| 40 °C | 13 | 10.3 mV | 100% | 0.46 K | −0.8 K |
| 25 °C | 13 | 16.6 mV | 100% | 0.44 K | 0.0 K |
| 10 °C | 14 | 19.2 mV | 86% | 0.77 K | +0.3 K |
| 0 °C | 14 | 27.3 mV | 71% | 0.91 K | −0.5 K |
| −10 °C | 14 | 50.0 mV | 14% | 1.38 K | −0.6 K |
| −20 °C | 14 | 79.8 mV | 29% | 1.39 K | +0.2 K |
| **All** | **82** | **26.5 mV** | **66%** | 0.75 K | 0.7 K |

Since v0.6.5 the 30T is fitted with its slow test at each temperature too (it delivers 2.74 Ah at −20 °C, against 3.03 at 25 °C). Against v0.6.4: 27.7 to 26.5 mV, and 62% to 66% within 1 K.

Medians, as `packtherm fit` reports them, scored as for the Panasonic. There is no hand-tuned 30T to compare with: the fit is the library's only circuit for it.

**Reading it:**

- **Warm:** from 40 to 0 °C the voltage is within 10–28 mV, and at 40 and 25 °C every test is within 1 K. The drive cycles here are harder than the Panasonic's: US06 and the Mixed cycles reach 36 A (12C), and the cell warms by up to 21 K.
- **Cold:** at −10 °C and below, the drive cycles' temperature RMS runs 0.7–2.5 K. The peaks are close (within 1 K, median), but the cell warms by 10–20 K through the tested temperatures' rows, and the voltage errors double. At 0 °C and below the slow branch's time constant sits at its 10 000 s limit, and the file flags it. (In v0.6.4, R0 came out lower at −20 °C than at −10 °C; with the cold open-circuit curves it now rises, 20 to 32 mΩ.)
- **The rig, or the cell's own conduction:** with h alone, calibrated on the 1C discharge, the drive cycles ran 2–5 K hot at their peaks, even with the heat from the measured voltage. A steady test's rise does not depend on how heat is stored or spread, but a drive cycle's peaks do. Two explanations fit about equally well, each with h calibrated on the same two fitted tests:

  | Rig and cell | Voltage RMS | Within 1 K | Peak error |
  |---|---|---|---|
  | h alone | 24.8 mV | 39% | 2.0 K |
  | h, and the fixture's heat capacity (shipped) | 27.7 mV | 62% | 0.8 K |
  | h, and the cell's radial conductivity (0.12 W/(m K), not the assumed 1.2) | 26.0 mV | 63% | 0.8 K |

  These tests can't tell the two apart: they have one thermocouple, on the case. A thermocouple in the core would decide (BACKLOG item 5). The fit ships the fixture explanation because it belongs to the rig and leaves the cell as assumed. The library 30T keeps the assumed jelly-roll values (an NMC811 jelly roll's; the source names no chemistry). If the low conductivity is right, a 30T's core runs hotter than PackTherm predicts in fast transients. The voltage is a little better with the cell warmer in the model (h alone), which leans that way.

**How independent this is.** The 30T was the second, independent check of the method promised in v0.6.2. It found a fault, and the fault was fixed with it in view:

- **The middle branch's time constant:** at 25 °C the fitted tests themselves showed it (101 mV on the 1C discharge fitted to). The fix decides on fitted tests only. But the alternatives were compared on both cells' checks before choosing.
- **The rig's fixture:** this was found on the checks, and is calibrated on a fitted test. Which explanation to ship (above) was also decided with the checks in view.

The figures above are therefore a check of the fitted values, not a blind test of the method. The LG HG2 (below) is the blind one.

**Fitted values at 25 °C** (the library's `30T`):

| Value | Fitted |
|---|---|
| Capacity (C/20) | 3.03 Ah (rated 3.0 Ah) |
| R0 | 6.2 mΩ (20 and 32 mΩ at −10 and −20 °C; law 19.8 kJ/mol) |
| Charge-transfer time constant | 1.2 s |
| Middle branch | 8.8 mΩ over 40 s (from the long tests) |
| Slow branch | 8.1 mΩ over 22 min |
| 10 s DC resistance, mid charge, 1.5C | 14.3 mΩ (10.6 at 40 °C, 35.7 at 0 °C, 95 at −20 °C) |

## A third cell, fitted blind: the LG HG2

[docs/examples/fitting/lg_hg2_tests.yaml](examples/fitting/lg_hg2_tests.yaml) fits the LG INR18650-HG2, a 3 Ah NMC / graphite + SiO 18650 (Kollmeyer, Naguib and Skells, McMaster University, CC BY 4.0). It's from the same rig as the 30T, with the same plan of tests, and was fitted with the v0.6.3 method unchanged. The fit was run once, and its results are reported as they came out; nothing below changed the method or the cell. The data prepared by `validation/prepare_mcmaster.py hg2` follows the 30T's rules. Six runs are left out: five 40 °C drive cycles that ran at room temperature and stopped after 0.2 Ah, and an empty 25 °C HWFET file.

The fit is on each temperature's pulse test, first 1C discharge and Mixed1, and the 25 °C C/20 discharge. The checks are the other 74 tests. The rig was calibrated on the 25 °C 1C discharge and Mixed1: h = 130 W/(m² K), with the fixture at the edge of its range (3× the cell's own heat capacity, which the file flags).

| Chamber | Tests | Voltage RMS | Within 1 K | Temperature RMS | Peak error |
|---|---|---|---|---|---|
| 40 °C | 8 | 43.5 mV | 88% | 0.22 K | −0.1 K |
| 25 °C | 13 | 22.0 mV | 92% | 0.18 K | −0.2 K |
| 10 °C | 13 | 60.6 mV | 77% | 0.29 K | +0.2 K |
| 0 °C | 12 | 64.4 mV | 92% | 0.35 K | −0.1 K |
| −10 °C | 14 | 61.2 mV | 93% | 0.38 K | −0.5 K |
| −20 °C | 14 | 69.5 mV | 93% | 0.37 K | −0.1 K |
| **All** | **74** | **59.7 mV** | **89%** | 0.32 K | 0.3 K |

**Reading it:**

- **Temperature is easy here; voltage is not.** The HG2 warms by at most 8 K in these tests (the 30T: 21 K), so most tests come within 1 K. The voltage is the weakest of the three cells away from 25 °C: 43–70 mV.
- **What v0.6.4 took for the main cause: the capacity changes with temperature, and the model has one** (v0.6.5 found it the smaller part: below). The fit takes its capacity and open-circuit curve from the 25 °C C/20 test (2.78 Ah to 2.8 V). The dataset's C/20 tests at the other temperatures give less: 2.69 Ah at 40 °C, 2.65 at 10 °C, 2.60 at 0 °C, 2.56 at −10 °C and 2.50 at −20 °C. The model keeps the 25 °C capacity, so its state of charge drifts from the cell's through a discharge. At 40 °C the 1C discharge reaches 2.8 V after 2.50 Ah, against 2.72 Ah at 25 °C. The model, holding charge the cell doesn't have, is 180 mV high by the end. Even the discharges fitted on are 140 mV RMS at 40, 10 and 0 °C. The rise near empty and the slow branch take what they can, and end at their limits: no slow branch at 10 and 0 °C (Rd at its floor), and the middle branch's time constant at 235–300 s there. The 30T's capacity moves less with temperature, so the 30T didn't show it. This dataset has a C/20 test at every temperature, which a capacity by temperature could be fitted from (BACKLOG item 7).
- **The rig is ill-posed on this cell.** A 3 K rise on the calibrating discharge leaves h and the fixture loosely pinned: h came out at 130 W/(m² K), and the fixture at its limit. The alternatives, on the same two fitted tests:

  | Rig and cell | Voltage RMS | Within 1 K | Peak error |
  |---|---|---|---|
  | h alone | 57.8 mV | 85% | 1.3 K |
  | h, and the fixture's heat capacity (shipped) | 59.7 mV | 89% | 0.3 K |
  | h, and the cell's radial conductivity (0.06 W/(m K)) | 44.5 mV | 95% | 0.4 K |

  The radial conductivity explains the checks best here too, as on the 30T (0.12 W/(m K)). But 0.06 W/(m K) is below any jelly roll's, so it is standing in for something else: most likely the case thermocouple's lag under its tube, which neither calibration models. The voltage gains because a hotter core lowers the resistance, which offsets the capacity error above. The fit ships the fixture, as the method says.

### Fixed with it in view (v0.6.5)

v0.6.5 added the two fixes the blind check pointed to, and refitted the HG2. It is no longer a blind check.

| Chamber | Tests | v0.6.4 (blind) | Curves by temperature | And the middle branch capped at 120 s | Within 1 K, then |
|---|---|---|---|---|---|
| 40 °C | 8 | 43.5 mV | 38.5 mV | 37.6 mV | 88% |
| 25 °C | 13 | 22.0 mV | 21.9 mV | 22.1 mV | 92% |
| 10 °C | 13 | 60.6 mV | 55.7 mV | **20.5 mV** | 85% |
| 0 °C | 12 | 64.4 mV | 60.2 mV | **27.7 mV** | 100% |
| −10 °C | 14 | 61.2 mV | 57.7 mV | 61.0 mV | 100% |
| −20 °C | 14 | 69.5 mV | 69.1 mV | 69.0 mV | 93% |
| **All** | **74** | **59.7 mV** | 55.9 mV | **36.6 mV** | **93%** |

- **The open-circuit curves by temperature** (each temperature's slow test) helped a little: 59.7 to 55.9 mV. v0.6.4 overstated their part.
- **Most of the error was the middle branch.** At 10 and 0 °C it had taken the slow branch's place: a time constant of 235–300 s, with no slow branch left. That held the 1C discharges 90–150 mV low for most of their length. With its time constant capped at 120 s, the slow branch's floor, those temperatures came to 20.5 and 27.7 mV. The middle branch still sits at the cap there, with the slow branch at its floor (the file flags both), so the split between the two is not pinned. But the voltage is.
- **What is left:**
  - **40 °C:** the 1C discharge runs high through its second half, by up to 180 mV. At 40 °C the cell delivers 2.69 Ah at C/20 but 2.50 Ah at 1C (at 25 °C: 2.78 and 2.72). The model's losses at 1C don't take that much more charge, so the model holds charge the cell can't deliver. A loss of capacity with rate, strongest at 40 °C, is outside the model.
  - **−10 and −20 °C:** about 60–70 mV, unchanged.

**Fitted values at 25 °C** (the library's `HG2`, v0.6.5):

| Value | Fitted |
|---|---|
| Capacity (C/20 to 2.8 V) | 2.78 Ah (rated 3.0 Ah, to 2.0 V) |
| R0 | 19.3 mΩ (67 mΩ at −20 °C; law 16.4 kJ/mol) |
| Charge-transfer time constant | 7.7 s (its limit is 10 s) |
| Middle branch | 26.7 mΩ over 97 s (from the long tests) |
| Slow branch | 22.3 mΩ over 10 000 s (its limit) |
| 10 s DC resistance, mid charge, 1.5C | 28.5 mΩ (23.0 at 40 °C, 55.2 at 0 °C, 166 at −20 °C) |

## Without the pulse tests (v0.6.6)

Before the A123, which has no pulse tests, the 30T and the HG2 were fitted again with theirs taken out: each temperature's first 1C discharge and Mixed1 only (and the slow tests), with the kinetics from their changes in current. The checks are the same tests as before, never fitted to. The test lists are the shipped ones less their `pulses` and `steps` lines.

| Chamber | 30T, with pulses | 30T, without | HG2, with pulses | HG2, without |
|---|---|---|---|---|
| 40 °C | 10.3 mV | 9.5 mV | 37.6 mV | 55.1 mV |
| 25 °C | 16.6 mV | 12.3 mV | 22.1 mV | 10.7 mV |
| 10 °C | 19.2 mV | 24.3 mV | 20.5 mV | 13.8 mV |
| 0 °C | 27.3 mV | 33.7 mV | 27.7 mV | 26.0 mV |
| −10 °C | 50.0 mV | 43.0 mV | 61.0 mV | 51.4 mV |
| −20 °C | 79.8 mV | 73.8 mV | 69.0 mV | 78.6 mV |
| **All (median)** | **26.5 mV** | **29.4 mV** | **36.6 mV** | **35.4 mV** |
| Within 1 K | 66% | 77% | 93% | 96% |

- **The checks come out about as well either way:** 26.5 against 29.4 mV on the 30T, 36.6 against 35.4 mV on the HG2. Better at some temperatures, worse at others (the HG2 at 40 °C by 18 mV).
- **The values behind them differ a lot.** At 25 °C, without pulses, the 30T's middle branch is 45% smaller and its slow branch's time constant 214 s against 1321 s; the HG2's charge-transfer time constant is 1.7 s against 7.8 s. The voltage a drive cycle sees is pinned either way; how the loss splits between the branches is not. A pulse test is still the better way to measure the branches one by one, and the library's 30T and HG2 keep theirs.
- **The 30T's −20 °C Mixed1, fitted on, runs 180 mV RMS without pulses** (94 mV with). Its checks at −20 °C still came out better (73.8 against 79.8 mV). Why that one fitted test does so badly isn't known yet.

## A fourth cell, fitted blind: the A123 26650 (LFP)

[docs/examples/fitting/a123_26650_tests.yaml](examples/fitting/a123_26650_tests.yaml) fits the A123 ANR26650M1B, a 2.5 Ah LFP / graphite 26650 (Kawakita de Souza, University of Colorado Colorado Springs, CC BY 4.0; tests in Plett's format). It's the first LFP cell, with its flat plateau and its hysteresis, and the first dataset with no pulse tests. The method is v0.6.5's plus the changes in current above, which were proven on known answers and on the 30T and HG2 before this fit was run. The fit was run once and its results are reported as they came out ([report](examples/fitting/a123_26650_fitted.html)).

`validation/prepare_a123.py` reads the tester's Excel exports (the .mat files carry no temperature). Each temperature has a C/30 discharge from full (its open-circuit curve; the 25 °C one sets the capacity) and a drive profile: a 1C step to about 80%, a 15 min rest, then 30 min blocks of the profile with 5 min rests, down to about 15%. One profile per temperature is fitted on. The checks are three more profiles (two at −15 °C and the 25 °C one scaled to 10 A peaks, 4C) and the 25 °C C/30 charge. −25 °C is left out: its profile logged no cell temperature. The chamber reads 2–3 K warm below 0 °C, and each test runs at its measured temperature.

**Fitted on**, voltage RMS over each temperature's profile: 4.9 mV at 25 °C, 4.2 at 35, 5.3 at 45, 5.4 at 15, 6.6 at 5, but 21.8 at −5 and 48.4 at −15 °C.

**The checks**, never fitted to, predicted from their current alone:

| Test | Cell | Voltage RMS | Temperature RMS | Measured rise |
|---|---|---|---|---|
| Profile scaled to 4C peaks | 26 °C | 8.2 mV | 0.10 K | 0.2 K |
| Profile, script 05 | −12 °C | 104.3 mV | 0.10 K | 1.0 K |
| Profile, script 15 | −12 °C | 93.4 mV | 0.71 K | 15.5 K |
| C/30 charge, empty to full | 25 °C | 59.7 mV | 1.39 K | 2.1 K |
| **Median** | | **76.5 mV** | | 75% within 1 K |

**Reading it:**

- **From 5 to 45 °C it is the best fit of the four cells.** The fitted profiles are 4–7 mV, and the 25 °C profile at four times the current, which it never saw, is 8.2 mV. The flat plateau did not upset the state of charge: every test starts full (as given), and the charge is counted from there.
- **The cold is where it fails.** At −12 °C both checks are about 100 mV, and the profile fitted on is 48 mV. Through the run the error changes sign. In the first 20% the model's voltage under load is about 120 mV too low, so its loss there is too big. Below 25% it is 180–270 mV too high, under load and at rest alike: the cell is running out well before the model does. The C/30 discharge at −15 °C gave 2.49 Ah (25 °C: 2.58), and the model has that curve, so by its count 0.31 Ah is left at the end of the profiles (2.18 Ah out). But the cell is already collapsing: down to 2.29–2.33 V under load, against 3.12 V at 25 °C after the same charge. So it's charge lost with rate in the cold, as on the HG2 at 40 °C, plus a near-empty rise the model can't make steep enough (`soc_b` is at its limit at 35, 45, 15 and 5 °C, and the cold law for the rise came out negative).
- **Hysteresis, measured:** on the C/30 charge the model runs 35–50 mV below the cell all the way (more at low charge). The model follows the discharge curve, so on charge it sits low by about the gap between the two. LFP's gap is large and flat; this is its size here.
- **The test rig can't be calibrated on these tests.** The 25 °C profile warms the cell by under 1 K, so h ran to the 200 W/(m² K) limit (the file flags it). The temperature checks still come within 1 K in three of four, because the rises are small, except at −12 °C on script 15, which warmed by 15.5 K and came within 0.71 K.
- **Branches at their limits**, flagged in the file: the slow branch's time constant at its 10 000 s ceiling at most temperatures and its resistance at its floor at 35 and 45 °C. As on the 30T and the HG2 without pulses, the voltage is pinned better than the split between the branches.

**Fitted values at 25 °C** (the library's `A123`, v0.6.6):

| Value | Fitted |
|---|---|
| Capacity (C/30 to 2.0 V) | 2.58 Ah (rated 2.5 Ah) |
| R0 | 8.4 mΩ (49 mΩ at −15 °C; law 23 kJ/mol). The datasheet: 6 mΩ at 1 kHz |
| Charge-transfer time constant | 1.8 s |
| Middle branch | 17.5 mΩ over 27 s |
| Slow branch | 11.8 mΩ over 10 000 s (its limit) |
| 10 s DC resistance, mid charge, 1.5C | 16.9 mΩ (13.4 at 45 °C, 33.8 at 5 °C, 114 at −15 °C) |

## The cells side by side

The checks are the tests never fitted to, predicted from their current alone, as a study runs the cell. The figures are medians.

| Cell | Temperatures | Checks | Voltage RMS, v0.6.4 | Voltage RMS, v0.6.5 | Within 1 K, v0.6.5 | How blind |
|---|---|---|---|---|---|---|
| Panasonic NCR18650PF | −20 to 25 °C | 43 | 24.4 mV | 26.4 mV | 81% | method compared on these checks (v0.6.2 to v0.6.5) |
| Samsung INR21700-30T | −20 to 40 °C | 82 | 27.7 mV | 26.5 mV | 66% | method fixed with these checks in view (v0.6.3, v0.6.5) |
| LG INR18650-HG2 | −20 to 40 °C | 74 | 59.7 mV (blind) | 36.6 mV | 93% | blind in v0.6.4; fixed with it in view (v0.6.5) |
| A123 ANR26650M1B (LFP) | −15 to 45 °C | 4 | – | 76.5 mV (v0.6.6, blind) | 75% | blind in v0.6.6; no pulse tests |

At 25 °C the four agree: 18.1, 16.6, 22.1 and 8.2 mV. The blind check of v0.6.4 found a middle branch that could take the slow branch's place, and a capacity that moves with temperature; both are now in the method. The A123 is v0.6.6's blind check, and its four checks are few: two of them are in the cold, where it fails, and one is a charge, which shows the hysteresis. Its median says less than the others'.

## Known limits

- **The collapse near empty.** The rise near empty is an exponential in the state of charge. The real collapse in the last minutes of a discharge is steeper, so heat there is under-predicted and peaks run cold (above).
- **Cold slow branch.** At 0 °C and below, the slow branch is at the edge of its range on both datasets' tests. On the Panasonic at −20 °C, with no usable steps file, the middle branch is off and the slow branch has taken its place, so the recovery after a pulse is wrong there (the report shows it). On the 30T at −20 °C, R0 comes out below its −10 °C value. Drive cycles at those temperatures are the tests that pin it, and more of them would help.
- **Capacity by temperature, but not by rate.** Slow tests at several temperatures give an open-circuit curve at each (v0.6.5). But a cell that delivers much less at 1C than at C/20 beyond what its losses explain (the HG2 at 40 °C: 2.50 against 2.69 Ah) runs out before the model does (BACKLOG item 7).
- **The middle and slow branches can still trade.** With the middle branch capped at 120 s, the HG2 at 10 and 0 °C keeps it at the cap with no slow branch. The voltage fits, but how the loss splits between the two is not pinned.
- **The test rig.** The thermal checks need the rig's convection and, for drive cycles, the heat capacity its fixture adds. Both come from fitted tests, but they are the rig's, and a cell's peaks in a pack depend on the pack's own.
- **One shape across currents.** Pulses from 0.5C to 6C share one non-linear charge-transfer shape; the 1C pulses at mid charge come out about 10% too deep at every temperature.
- **One open-circuit curve without slow tests at other temperatures**, as for the Panasonic and PackTherm's hand-made library cells.
- **Hysteresis is not modelled.** The curve follows the discharge, and the report gives the gap to the charge if the slow test has one. On the A123 (LFP) a C/30 charge runs 35–50 mV above the model.
- **LFP in the cold.** At −12 °C the A123 runs out well before the model (180–270 mV high below 25%), and its loss in the first part of a profile is over-predicted by about 120 mV. Charge lost with rate in the cold, and a near-empty rise too gentle for LFP's, are outside the model.
- **Without a pulse test**, the kinetics come from the long tests' changes in current (v0.6.6). The voltage comes out as well; how it splits between the branches does not.
- **Charge.** The near-empty rise applies on discharge only, as in PackTherm's runs.
- **Speed.** With the middle branch fitted two ways, the stages after the first run twice, and a fit takes up to twice as long as in v0.6.2.
