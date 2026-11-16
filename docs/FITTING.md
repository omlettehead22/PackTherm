# Fitting a cell model to test data

`packtherm fit` fits PackTherm's circuit model to tests of one cell at one temperature, and writes:

- a **fitted cell file** (YAML): the values, where each came from, how certain it is, where the model is valid, its errors, and what went in;
- an **HTML report** beside it: the same, with charts, on one page you can send.

**v0.6.1 fits one temperature.** A cell's resistances change several-fold between 0 and 40 °C, and that behaviour needs tests at several temperatures. Until v0.6.2 fits it, the file says `usable_in_studies: false` and studies refuse it with a message saying why. A study run with borrowed temperature behaviour would give thermal results that look more certain than they are.

The tests are read as in [TEST_DATA.md](TEST_DATA.md) (CSV or `.mat`, any common tester export).

## The tests it needs

| Option | Test | What it gives |
|---|---|---|
| `--slow` (required) | A slow full discharge, C/10 or slower (C/20 is usual), from full to the cut-off | The open-circuit voltage curve and the capacity |
| `--pulses` (required) | A pulse test (HPPC): short pulses with rests between, at several states of charge, with a rest of 20 min or more somewhere to fix the state of charge | The instant resistance, the charge-transfer branch, and the rise near empty |
| `--steps` (optional) | Steady steps of 5 min or more, each followed by a rest of 5 min or more | The slow branch. Without it, the slow branch keeps a starting value and the file says so |
| `--check` (optional, repeatable) | Anything else, typically a drive cycle | Not fitted to: predicted afterwards, as the honest test of the fit |
| `--compare CELL` | A library cell, e.g. `PF` | Predicts the `--check` tests too, for comparison |

```
packtherm fit --slow c20.mat --pulses hppc.mat --steps steps.mat --check udds.mat --compare PF \
  --name "Panasonic NCR18650PF (fitted, 25 degC)" --rated-capacity 2.9 \
  --citation "Kollmeyer (2018), doi:10.17632/wykht8y7tg.1" --licence "CC BY 4.0" -o pf_25C.yaml
```

## The model

The model is the one PackTherm's electro-thermal runs use (`packtherm.ecm.ECM`):

- the open-circuit voltage, from a table over the state of charge;
- an instant (ohmic) resistance `R0`;
- a charge-transfer branch: a Butler–Volmer-shaped overpotential `gamma · 2RT/F · asinh(I / 2I0)`, reached with time constant `tau_ct`;
- a slow (diffusion) branch: resistance `Rd`, time constant `tau_d`;
- a rise of all of them near empty, `1 + soc_a · exp(−SOC / soc_b)`, on discharge.

Fitted cell files name the model (`model.form: packtherm-circuit-1`). The fitting code treats a model as an interface (parameters, a simulator, what PackTherm runs), so a generic circuit with the user's choice of RC branches can be added later and share everything else.

## How it fits

1. **Open-circuit voltage and capacity** come from the slow discharge. Its charge to the cut-off is the measured capacity. Its voltage, plus the cell's own drop at that current (the fitted model's steady resistance, rising near empty as the model's does), is the open-circuit curve. The fit runs twice, so the drop comes from the fitted model.
2. **State of charge** through each test is anchored at a settled rest (20 min or more), where the voltage is the open-circuit voltage, and carried by the charge counted. That includes charge moved while logging paused, and charge across steps between two samples, both from the tester's own counter. A test with no rest that starts at almost no current is anchored at its first voltage, with a warning.
3. **The fit is through time.** Each pulse (5 s before it to 40 s after) and each rest after a step is replayed through the model and scored on how its voltage changes. That is the same simulation PackTherm runs (a test checks they agree to 1e-9 V), with two details real tests need:
   - pulses often follow each other within a minute, while the last one's slow recovery is still under way, so each is replayed from the end of the last long rest before it, through the pulses between;
   - where a step falls between two samples, the slow states move with the interval's mean current (from the counter), and the instant drop uses the current logged at the sample.
4. **In stages, then together:** the kinetics on pulses at 20–95% state of charge, then the slow branch on the steps, then the rise near empty on all pulses, then everything at once.

## What the file holds

| Key | What |
|---|---|
| `status`, `usable_in_studies`, `why_not_usable` | `single-temperature`, `false`, and why |
| `values` | Every value with its `unit`, its `source` (`fitted`, `data`, `default` or `not fitted`), what it is, its 95% range and any flag |
| `capacity` | Measured, how, and against the rated capacity if given |
| `open_circuit_voltage` | The curve, and how it was made |
| `valid_for` | What the tests covered: the cell temperature in the parts fitted, the state of charge and C-rates of the pulses |
| `identifiability` | Pairs of values that trade off (correlation beyond ±0.95): the tests pin a combination, not each |
| `errors` | RMS and worst error on each kind of part fitted (above and below 20% state of charge), and on each `--check` test, with the comparison cell's |
| `data_warnings` | Everything reading the tests flagged |
| `provenance` | PackTherm version, date, settings, and each input's role, name, SHA-256, length and conversions; the dataset's citation and licence |

**The 95% ranges** count each pulse and each step as one piece of evidence (a cluster-robust estimate). The usual least-squares ranges assume every sample's error is independent. Here what's left is mostly the model's own misfit, the same shape through a whole pulse, so those ranges claim far too much: on noise-free test data, every true value fell outside them. The ranges used show how far the parts of the test disagree. On noise-free data from a known cell, 7 of 8 true values lie inside them; the eighth (`soc_a`) is 3% off, a small steady bias that ranges of this kind cannot show. A value the tests barely touch is flagged.

## Checked against known answers and real data

**Known answers** (`tests/test_fitting.py`): tests made by a cell with known values (an HPPC-style pulse test, a C/20 discharge, steps and rests) are fitted. Every value comes back within 1–5%: `R0` within 0.1%, `tau_d` within 2%. A drive cycle the fit never saw is predicted to 0.2 mV RMS.

**Real data**, the Panasonic NCR18650PF at 25 °C (Kollmeyer, CC BY 4.0; the files are in `tests/data/panasonic_18650pf/`, and CI runs this fit):

| | |
|---|---|
| Capacity | 2.995 Ah measured (rated 2.9 Ah, +3.3%) |
| UDDS drive cycle, not fitted to (first 20 min) | **5.3 mV RMS** (59 mV worst); the library cell: 10.1 mV (66 mV) |
| Pulses at 20–95% state of charge | 8.9 mV RMS |
| Rests after steps, 20–95% | 7.6 mV RMS |
| Below 20% state of charge | 27 mV (pulses), 42 mV (steps) |
| R0 | 26.3 mΩ (95%: 24.3 to 28.5) |
| Charge-transfer and slow branches | tau_ct 1.8 s; Rd 21.7 mΩ, tau_d 42 s (34 to 52) |

The fitted cell file and its report are in [docs/examples/fitting/](examples/fitting/) ([report](examples/fitting/ncr18650pf_25C.html)); the command that made them is above, with the files in `tests/data/panasonic_18650pf/`.

The library PF cell was identified from the same dataset by a simpler method (the 10 s overpotential of each pulse), so its 10.1 mV is a fair comparison.

## Known limits

- **Two branches, three time scales.** The model has two branches besides the instant drop; a real cell responds on more. The worst pulse errors sit in the first tenth of a second after a step (faster than either branch), and slow creep over minutes in long pulses and rests is missed. On the Panasonic cell this shows as wide ranges on `I0` and `gamma` (about 2×), which trade off. A generic model with more branches is planned.
- **Near empty** the open-circuit voltage is steep, so small errors in the state of charge become larger voltage errors (27–42 mV RMS below 20%).
- **Hysteresis.** The curve follows the discharge, as the library's does. If the slow test includes a charge, the report gives the gap between them (about 94 mV on the Panasonic cell, beyond their drops).
- **Charge pulses.** The near-empty rise applies on discharge only, as in PackTherm's runs. Charge pulses are fitted with the same kinetics.
- **One temperature**, as above: v0.6.2.
