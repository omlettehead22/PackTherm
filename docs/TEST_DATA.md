# Cell test data

PackTherm reads cell test data so it can fit a cell model to it (v0.6). This page covers reading and checking the data, from v0.6.0. Fitting comes in v0.6.1 to v0.6.3.

```bash
packtherm data hppc_25C.csv --capacity 3.0 --segments --plot hppc_25C.png
```

```python
from packtherm.testdata import load_test_data

rec = load_test_data("hppc_25C.csv", capacity_Ah=3.0)
print(rec.summary())
for part in rec.segments():
    print(part.kind, part.t0, part.duration_s, part.current_A)
```

## What it reads

- **CSV or TSV** (`.csv`, `.tsv`, `.txt`), with any delimiter. Excel files are not read yet; save the sheet as CSV.
- **MATLAB `.mat`** files (version 7 or earlier): top-level vectors, or a structure of them. That covers the `meas` structure of the Kollmeyer datasets (Panasonic NCR18650PF, Samsung INR21700-30T, LG HG2).

A test needs **time, current and voltage**. **Cell temperature**, **ambient (chamber) temperature** and the **tester's charge counter** are read if present. The counter keeps counting while logging pauses, so it fills in what the log leaves out (see Gaps below).

### Columns

Columns are found by name, for the exports of the common testers:

| Role | Names recognised (start of the name, any case) |
|---|---|
| time | `Test Time`, `Test_Time(s)`, `Total Time`, `Time`, `time/s`, `t`, `Elapsed`, `Run Time` |
| current | `Current`, `I`, `I/mA`, `<I>/mA`, `Amps` |
| voltage | `Voltage`, `V`, `Ewe/V`, `Ecell/V`, `U`, `Cell Voltage` |
| temperature | `Battery_Temp`, `Cell Temp`, `Surface Temp`, `Temperature`, `Temp`, `Aux…Temp`, `T_cell` |
| ambient | `Chamber`, `Ambient`, `T_amb`, `Env` |
| charge counter | `Ah`, `Amp-hours`, `Capacity`, `(Q-Qo)` (Biologic), or Arbin's and Maccor's separate `Charge_Capacity` and `Discharge_Capacity` |

If a column isn't found, the error lists the file's columns. Name them: `--time 'secs' --current 'amps_out' --voltage 'cellV'`, or `columns={"time": "secs", ...}` in Python.

### Units

Units are taken from the column name: `(mA)`, `/mA`, `[mV]`, `(ms)`, `(min)`, `(h)`, `(mAh)`, and `K` for temperature. They are also checked against the values. A voltage in the thousands is millivolts, and a current over 1000 is milliamps. Time can be numbers, `h:mm:ss` durations, or dates and times. Every conversion is listed in the summary.

### Sign of the current

PackTherm's convention is **positive current = discharge**. Testers differ: Biologic and the Kollmeyer datasets record discharge as negative. The reader works out the sign from the voltage and flips it if needed, saying why:

1. In a finely logged record (2 s or less between samples), each jump in current moves the voltage at once: down for more discharge. With 20 or more jumps and 90% of them agreeing, that settles it. This is the clearest sign in a drive cycle.
2. Otherwise it checks how the voltage behaves:
   - when current starts from rest, the voltage falls on discharge;
   - when current stops, the voltage recovers after discharge;
   - during a long steady current, the voltage drifts down through a discharge.

   80% of these checks must agree.

If the evidence is unclear (a file with very little current, say), the current is left as it is and the summary says so. `--flip` reverses it.

## Checks

The summary warns about:

- rows dropped for missing time, current or voltage;
- repeated times, and time running backwards (a logger restart): rows not later than an earlier row are dropped;
- **gaps**, meaning steps over 10 times the usual step and at least 60 s. No current is logged across a gap, but the cell is not necessarily resting: some testers pause logging during long steps. The Panasonic pulse tests leave out every discharge between pulse levels. If the file has a charge counter, the charge that moved across each gap is counted, as an `unlogged` part. If it has none, a gap across which the voltage moved by more than 20 mV is flagged, because current probably flowed there that nothing records;
- a charge counter that disagrees with the logged current by more than 10% (it is then used only across gaps, and across steps where the current changes between two samples);
- a coarse time step (over 10 s), too coarse for pulse tests;
- a median voltage that isn't a single cell's (a module or pack?);
- cell temperatures that can't be °C;
- with `--capacity` given, a record that moves more charge in one direction than the cell holds. That usually means charges between its parts are in another file, as with some of the Panasonic dataset's repeated discharges.

## The parts of a test

`segments()` labels each part:

| Kind | What it is |
|---|---|
| `rest` | No current (below 0.5% of the record's largest current, and 5 mA) |
| `pulse` | A steady current lasting at most 60 s, as in HPPC tests |
| `constant` | A longer steady current: a C/20 or 1C discharge, or a step between pulse levels |
| `cc-cv` | A charge whose current tapers at constant voltage at the end |
| `dynamic` | A varying current such as a drive cycle: a stretch of 30 or more current steps with no rest of 5 minutes or more, or one whose current jumps about within a step |
| `unlogged` | A gap in the log across which the tester's charge counter moved: its charge is known, not how it flowed |

Each part has its start and end, mean current, and the charge it moved. `--segments` lists them, with C-rates if the capacity is given. `--plot` draws current, voltage and temperature against time, with the parts shaded.

## The public dataset used for v0.6

- **Panasonic NCR18650PF**: P. Kollmeyer, "Panasonic 18650PF Li-ion Battery Data", Mendeley Data v1 (2018), doi:[10.17632/wykht8y7tg.1](https://doi.org/10.17632/wykht8y7tg.1), CC BY 4.0. It has slow C/20 tests, five-pulse HPPC tests and drive cycles at 25, 10, 0, −10 and −20 °C. Of its 198 files, 191 hold data and 7 a single sample (reported as such). The sign is left unclear, and flagged, in two (`Dis1C_Rp`, coarsely logged repeats of a 1C discharge with their charges in another file). In each of the other 189 it is found from the voltage, and every one of the 131 whose name says what it is (a discharge, drive cycle, pulse test or charge) comes out the right way round.
- **Samsung INR21700-30T** (v0.6.3): P. Kollmeyer and M. Skells, "Samsung INR21700 30T 3Ah Li-ion Battery Data", Mendeley Data v2 (2023), doi:[10.17632/9xyvy2njj3.2](https://doi.org/10.17632/9xyvy2njj3.2), CC BY 4.0. It has HPPC tests, 0.5C to 2C discharges and drive cycles at 40, 25, 10, 0, −10 and −20 °C, and a C/20 test at 25 °C. Its quirks: there is no chamber channel, and the chambers ran off their setpoints; the 0.5C and 2C files begin with the discharge already running (the tester's counter holds what went before); one drive cycle's file logs a block of time twice; and the HPPC files' charge counter disagrees with the logged current by 31–63% over their logged parts at 10 to 40 °C, so the counter is used only across gaps and steps. `validation/prepare_samsung_30t.py` deals with each (see [FITTING.md](FITTING.md#checked-on-a-second-cell-the-samsung-30t)).

## Tests

`tests/test_testdata.py` checks the reader in two ways:

- **Real files**, in every CI run. Six files from the Panasonic set, copied unchanged into `tests/data/panasonic_18650pf/` (1.4 MB; credited in the README there): the 25 °C five-pulse test, the C/20 test, a 1C discharge logged from partway, a CC-CV charge, the first 20 minutes of a UDDS drive cycle, and a single-sample file. Each check is a fact about the file that doesn't depend on the reader:
  - the test's design: pulses at 0.5, 1, 2, 4 and 6C, and the C/20 current;
  - the 2.5 V cut-off that ends three pulses early;
  - the tester's own amp-hour counter, which the reader's charge must match within 1%. The CC-CV charge, logged once a minute, must match within 2%.
- **Synthetic records**, with exactly known answers, for what the real files don't cover: Arbin, Biologic and Neware formats, units in mA, mV and `h:mm:ss`, and deliberately damaged files (missing values, repeated and backwards time, gaps).

With `PACKTHERM_PF_DATA` pointing at a copy of the whole dataset, one more test reads all 198 files.
