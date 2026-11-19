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
chamber_h_W_m2K: 38.7       # optional: the test chamber's convection, for the thermal check
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
| `errors` | RMS and worst error on each kind of test fitted at each temperature, and on each check, in two forms: <br>• voltage, replayed at the check's measured temperature; <br>• with `like` and `chamber_h_W_m2K` given, run as a study runs the cell (`held_out_electrothermal`): voltage and surface temperature from the current alone, beside the comparison cell's |
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
| 25 °C | 11 | 16.9 mV | 18.0 mV | 91% | 91% | 0.0 K | −0.8 K |
| 10 °C | 8 | 23.7 mV | 23.9 mV | 100% | 100% | 0.0 K | −0.8 K |
| 0 °C | 8 | 33.3 mV | **26.5 mV** | 88% | 75% | −0.8 K | −1.6 K |
| −10 °C | 8 | 52.8 mV | 54.2 mV | 75% | 75% | −1.1 K | −1.2 K |
| −20 °C | 8 | 69.2 mV | 67.4 mV | 75% | 50% | −0.9 K | −0.1 K |
| **All** | **43** | **32.7 mV** | **28.2 mV** | **86%** | **79%** | 0.6 K | 1.0 K |

All figures are medians, as `packtherm fit` reports them for the worked example. Voltage is scored down to the knee. Peak error is predicted minus measured peak surface temperature; in the "All" row it's the absolute value.

**Reading it:**

- **Voltage:** from tests alone, the fitted cell predicts voltage as well as the hand-tuned model, and better at 0 °C.
- **Peaks:** it runs colder at its temperature peak, by about 0.8 K at 25 and 10 °C. Through the first 90% of a drive cycle, its heat is closer than the library's to the heat implied by the measured voltage. The shortfall comes in the last minutes near empty, where the voltage collapses faster than the near-empty rise (an exponential) can follow.
- **Cold:** at −10 °C and below, the slow branch sits at the edge of its allowed range. The cold long tests don't pin it down, and the file flags it.

**A caveat on how blind this is.** The fitted values never see the 43 checks. But while building v0.6.2, variants of the method were compared on these same tests, so the method itself was not chosen blind. A second dataset (the Samsung 30T, v0.6.3) will check it independently.

**Fitted values at 25 °C:**

| Value | Fitted |
|---|---|
| R0 | 23.4 mΩ (93 mΩ at −20 °C; law 18.7 kJ/mol) |
| Charge-transfer time constant | 1.1 s |
| Middle branch | 18.5 mΩ over 33 s |
| Slow branch | 26.1 mΩ over 29 min |
| 10 s DC resistance, mid charge, 1.5C | 40.6 mΩ (the library model: 40.6 mΩ) |

## Known limits

- **The collapse near empty.** The rise near empty is an exponential in the state of charge. The real collapse in the last minutes of a discharge is steeper, so heat there is under-predicted and peaks run cold (above).
- **Cold slow branch.** At 0 °C and below, the slow branch is at the edge of its range on this dataset's tests; at −20 °C, with no usable steps file, the middle branch is off and the slow branch has taken its place, so the recovery after a pulse is wrong there (the report shows it). Drive cycles at those temperatures are the tests that pin it, and more of them would help.
- **One shape across currents.** Pulses from 0.5C to 6C share one non-linear charge-transfer shape; the 1C pulses at mid charge come out about 10% too deep at every temperature.
- **One open-circuit curve**, from the slow discharge at one temperature. It doesn't change with temperature, as in PackTherm's library cells.
- **Hysteresis is not modelled.** The curve follows the discharge, and the report gives the gap to the charge if the slow test has one.
- **Charge.** The near-empty rise applies on discharge only, as in PackTherm's runs.
- **Speed.** A five-temperature fit with drive cycles takes about five minutes.
