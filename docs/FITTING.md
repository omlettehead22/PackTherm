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
    pulses: hppc_25.mat     # required: a pulse (HPPC) test
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
| Pulse test (HPPC) at each temperature, with a rest of 20 min or more somewhere to fix the state of charge | The instant resistance, the charge-transfer branch (seconds) and the middle branch (tens of seconds) |
| Long tests at each temperature: steps with rests, full discharges, drive cycles | The slow branch (minutes) and the rise near empty. **A drive cycle or a full discharge at each temperature matters**: without them the slow branch is fitted on steps alone, and the cold behaviour is poorly known (see the results) |
| Checks | Not fitted to: predicted afterwards, as the honest test of the fit |

**The test rig.** The thermal checks run the cell in a model of the rig: the chamber's convection (h) and, if calibrated, the heat capacity the cell's fixture adds (clips, leads, holder). Give h (`chamber_h_W_m2K`), or calibrate the rig on tests that are fitted to, never the checks (`chamber_calibration`). The heat comes from each test's measured voltage, I · (OCV − V), so the circuit model plays no part beyond the open-circuit voltage. With one test, h alone is fitted. With two or more, a steady one (a constant-current discharge) and a dynamic one (a drive cycle), the fixture's heat capacity is fitted too: a steady test's rise sets h, and a drive cycle's peaks the heat capacity. Both belong to the rig. They are used for the checks only and never stored on the cell.

## The model

The model is the one PackTherm's electro-thermal runs use (`packtherm.ecm.ECM`):

- the open-circuit voltage, from a table over the state of charge;
- an instant (ohmic) resistance `R0`;
- a charge-transfer branch: a Butler–Volmer-shaped overpotential `gamma · 2RT/F · asinh(I / 2I0)`, reached with time constant `tau_ct` (seconds);
- a middle branch: resistance `Rm`, time constant `tau_m` (tens of seconds). New in v0.6.2; off in the library cells;
- a slow branch: resistance `Rd`, time constant `tau_d` (minutes);
- a rise of all of them near empty, `1 + soc_a · exp(−SOC / soc_b)`, on discharge.

**Values by temperature.** A cell fitted at several temperatures holds every value at each one. PackTherm interpolates between them (in 1/T, logarithmically: an Arrhenius law between neighbours). Beyond the coldest and warmest, the resistances and rates follow laws fitted through the temperatures' own values (`Ea_R0`, `Ea_I0`, `Ea_Rm`, `Ea_Rd`, `Ea_soc`), and the shape and time constants hold. Studies warn when a run goes beyond the tested temperatures (by more than 2 K) or rates.

Fitted cell files name the model (`model.form: packtherm-circuit-1`) and hold it in full (`model.ecm`). The fitting code treats a model as an interface (parameters, a simulator, what PackTherm runs), so a generic circuit with a chosen number of branches can share everything else.

## How it fits

1. **Open-circuit voltage and capacity** come from the slow discharge. Its charge to the cut-off is the measured capacity. Its voltage, plus the cell's own drop at that current (the fitted model's steady resistance at the slow test's temperature, rising near empty as the model's does), is the open-circuit curve.
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
| `capacity`, `open_circuit_voltage` | Measured, how, and against the rated capacity if given |
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
| 25 °C | 11 | 16.9 mV | 18.2 mV | 91% | 91% | 0.0 K | −0.8 K |
| 10 °C | 8 | 23.7 mV | **20.9 mV** | 100% | 100% | 0.0 K | −0.7 K |
| 0 °C | 8 | 33.3 mV | **25.6 mV** | 88% | 75% | −0.8 K | −1.5 K |
| −10 °C | 8 | 52.8 mV | **34.4 mV** | 75% | **88%** | −1.1 K | −0.9 K |
| −20 °C | 8 | **69.2 mV** | 91.6 mV | 75% | 50% | −0.9 K | +0.1 K |
| **All** | **43** | **32.7 mV** | **24.4 mV** | **86%** | **81%** | 0.6 K | 0.9 K |

All figures are medians, as `packtherm fit` reports them for the worked example. Voltage is scored down to the knee. Peak error is predicted minus measured peak surface temperature; in the "All" row it's the absolute value.

**Reading it:**

- **Voltage:** from tests alone, the fitted cell predicts voltage better than the hand-tuned model from 10 to −10 °C, and as well at 25 °C. It is worse at −20 °C, where the tests pin the least (below).
- **Against v0.6.2:** setting the middle branch's time constant two ways (above) took the median from 28.2 to 24.4 mV and the share within 1 K from 79% to 81%. The 10, −10 and −20 °C fits now take it from their long tests: −10 °C improved from 54.2 to 34.4 mV, and −20 °C, whose checks warm into the −10 °C row, worsened from 67.4 to 91.6 mV.
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
- each temperature's first 1C discharge and drive cycle Mixed1, from `validation/data/samsung_30t/` (made by `validation/prepare_samsung_30t.py`).

The checks are the other 82 tests, never fitted to. That's 0.5C, 1C and 2C discharges, and the UDDS, HWFET, LA92, US06 and Mixed2 to Mixed8 drive cycles at every temperature. The rig is calibrated on the 25 °C 1C discharge and Mixed1 (both fitted to): h = 63.3 W/(m² K), and the fixture adds 58 J/K to the cell's own 55 J/K.

**The data, prepared with care** (all in the manifest, `validation/data/samsung_30t/manifest.json`):

- **Ambient:** the dataset has no chamber channel, and the chambers ran off their setpoints: the 25 °C one at about 24 °C, and at −10 °C between −13 and −9 °C. A test's ambient is the cell's temperature after the settled rest before it.
- **Start:** the 0.5C and 2C files begin with the discharge already running. At −10 °C, 1.6 Ah of the 2C discharge went before logging began. Each starts from the charge the tester counted before its first sample.
- **Glitches:** one file logs a block of time twice (kept once), and the rest after a cold test can hold the chamber's ramp back to 25 °C (cut).

| Chamber | Tests | Voltage RMS | Within 1 K | Temperature RMS | Peak error |
|---|---|---|---|---|---|
| 40 °C | 13 | 12.6 mV | 100% | 0.44 K | −0.7 K |
| 25 °C | 13 | 17.4 mV | 100% | 0.45 K | +0.1 K |
| 10 °C | 14 | 20.4 mV | 71% | 0.82 K | +0.3 K |
| 0 °C | 14 | 27.8 mV | 64% | 0.88 K | −0.5 K |
| −10 °C | 14 | 51.0 mV | 14% | 1.38 K | −0.6 K |
| −20 °C | 14 | 78.5 mV | 29% | 1.17 K | −0.3 K |
| **All** | **82** | **27.7 mV** | **62%** | 0.79 K | 0.8 K |

Medians, as `packtherm fit` reports them, scored as for the Panasonic. There is no hand-tuned 30T to compare with: the fit is the library's only circuit for it.

**Reading it:**

- **Warm:** from 40 to 0 °C the voltage is within 13–28 mV, and at 40 and 25 °C every test is within 1 K. The drive cycles here are harder than the Panasonic's: US06 and the Mixed cycles reach 36 A (12C), and the cell warms by up to 21 K.
- **Cold:** at −10 °C and below, the drive cycles' temperature RMS runs 0.7–2.5 K. The peaks are close (within 1 K, median), but the cell warms by 10–20 K through the tested temperatures' rows, and the voltage errors double. At −20 °C the fit's own values sit at the edges of their ranges (the middle branch's time constant near its 5 s limit, the slow branch's at its 10 000 s limit). R0 comes out lower at −20 °C than at −10 °C, which is not physical. The file flags both.
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

The figures above are therefore a check of the fitted values, not a blind test of the method. A third cell (the LG HG2, v0.6.4) will be fitted with the method as it stands.

**Fitted values at 25 °C** (the library's `30T`):

| Value | Fitted |
|---|---|
| Capacity (C/20) | 3.03 Ah (rated 3.0 Ah) |
| R0 | 6.3 mΩ (16–20 mΩ at −10 to −20 °C; law 14.0 kJ/mol) |
| Charge-transfer time constant | 1.2 s |
| Middle branch | 9.1 mΩ over 42 s (from the long tests) |
| Slow branch | 8.2 mΩ over 24 min |
| 10 s DC resistance, mid charge, 1.5C | 14.3 mΩ (10.6 at 40 °C, 35.7 at 0 °C, 95 at −20 °C) |

## Known limits

- **The collapse near empty.** The rise near empty is an exponential in the state of charge. The real collapse in the last minutes of a discharge is steeper, so heat there is under-predicted and peaks run cold (above).
- **Cold slow branch.** At 0 °C and below, the slow branch is at the edge of its range on both datasets' tests. On the Panasonic at −20 °C, with no usable steps file, the middle branch is off and the slow branch has taken its place, so the recovery after a pulse is wrong there (the report shows it). On the 30T at −20 °C, R0 comes out below its −10 °C value. Drive cycles at those temperatures are the tests that pin it, and more of them would help.
- **The test rig.** The thermal checks need the rig's convection and, for drive cycles, the heat capacity its fixture adds. Both come from fitted tests, but they are the rig's, and a cell's peaks in a pack depend on the pack's own.
- **One shape across currents.** Pulses from 0.5C to 6C share one non-linear charge-transfer shape; the 1C pulses at mid charge come out about 10% too deep at every temperature.
- **One open-circuit curve**, from the slow discharge at one temperature. It doesn't change with temperature, as in PackTherm's library cells.
- **Hysteresis is not modelled.** The curve follows the discharge, and the report gives the gap to the charge if the slow test has one.
- **Charge.** The near-empty rise applies on discharge only, as in PackTherm's runs.
- **Speed.** With the middle branch fitted two ways, the stages after the first run twice, and a fit takes up to twice as long as in v0.6.2.
