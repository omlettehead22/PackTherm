# Study files

A study file describes a whole module design study in one YAML or JSON document. The command line, Python and (next) the API and web app all run the same document, so they cannot drift apart. `packtherm design --level module` builds the same document from its flags.

```bash
packtherm template --out study.yaml          # a commented file with every default
packtherm run study.yaml --out-dir results/  # results JSON, designs CSV, trade-off chart
```

```python
from packtherm.study import load_study

run = load_study("study.yaml").run()
doc = run.to_json()  # the results document
run.write("results/")  # the same three files as packtherm run
```

The smallest valid study:

```yaml
packtherm_study: 1
cell: M50
duty: {type: constant, c_rate: 1.5}
```

The examples in [`docs/examples/`](examples/) (`m50_roadtrip_35c.yaml`, `m50_discharge_1.5c_25c.yaml`, `m50_wltc3_35c.yaml`) are the studies behind the README, and each sits next to its results.

## Rules

- `packtherm_study` (the format version, currently `1`), `cell` and `duty.type` are required. Everything else is optional; defaults are those of `packtherm design`.
- Problems are reported together before anything runs, each naming its field, for example `design_space.coolant_flows_g_s[1]: must be > 0, got 0`. Rejected:
  - unknown keys and keys a duty type does not use;
  - wrong types (`true` is not a number);
  - NaN and infinity;
  - out-of-range values;
  - unknown cells and fillers.
- YAML is read with a safe loader; JSON is accepted as it is (`.json` files are parsed as JSON).
- `null` means "use the model's own value" where a key allows it (for example `requirements.T_max_C`).

## Top level

| Key | Type | Default | Meaning |
|---|---|---|---|
| `packtherm_study` | integer | required | Format version: `1` |
| `name` | text | none | Optional label, echoed in the results |
| `cell` | text or mapping | required | A library cell from `packtherm cells` (M50, M50-LUMPED, MJ1, PF, case-insensitive), a cell file (`my_cell.yaml`, relative to the study file), or a definition written inline ([below](#user-defined-cells)) |
| `mode` | `normal` / `fast` | `normal` | Numerical resolution ([FAST_MODE.md](FAST_MODE.md)) |
| `ambient_C` | number | 25 | Ambient temperature; also the coolant's radiator inlet |

## User-defined cells

A cylindrical cell described by its datasheet, inline under `cell:` or in its own file. A cell file works wherever a cell name does: `packtherm design my_cell.yaml ...`, `packtherm module my_cell.yaml ...`, and `cell: my_cell.yaml` in a study. A study's results carry the full definition. `packtherm cells my_cell.yaml` checks a file and shows the cell as PackTherm understands it, including its density, energy density, cold resistance rise and thermal properties.

```yaml
name: My 21700 cell
format: 21700
chemistry: NMC
capacity_Ah: 5.0
V_nominal: 3.6
mass_g: 69
DCIR_mOhm: 22
```

[`examples/user_cell_mj1.yaml`](examples/user_cell_mj1.yaml) is the LG MJ1 written this way; it gives exactly the library MJ1's results. [`examples/user_cell_lfp_26650.yaml`](examples/user_cell_lfp_26650.yaml) is an LFP power cell (Lithium Werks / A123 ANR26650M1-B) from its datasheet.

**Model.** The lumped resistance model, as for the library MJ1: heat from current and DC resistance, rising in the cold (Arrhenius) and at low charge, plus entropic heat. Since v0.6.11 it adds the slow losses a DC resistance misses (diffusion): under steady current they build over minutes to +88 % of the DC resistance (NMC and NCA; +160 % for LFP) and fade in rests, as tuned on the library's fitted cells. Without them a lumped model made 22–64 % of the fitted circuits' heat on a steady discharge; with them its heat is within −31 to +19 % of theirs (LFP −42 to +27 %) over steady, pulsed, drive and charge duties from −10 to 25 °C. Give the DC resistance over about 10 s (PackTherm's cells state theirs at 10 s, 1.5C, mid charge, 25 °C). There is no voltage model, so no voltage cut-off and no constant-voltage charge taper: a charge runs at constant current to its target. Results are labelled "user-defined, lumped DCIR" and are less accurate than the validated cells.

| Key | Default | Meaning |
|---|---|---|
| `name` | required | Label |
| `format` | none | `18650` (18.4 × 65.0 mm), `21700` (21.1 × 70.1), `26650` (26.2 × 65.2) or `4680` (46.0 × 80.0); give this or both sizes |
| `diameter_mm`, `height_mm` | from `format` | Can size; override the nominal size with the measured one |
| `chemistry` | `NMC` | `NMC`: NMC/graphite jelly-roll properties and entropic heat (from the LG M50 data). `NCA`: the same jelly-roll properties, no entropic heat (published NCA profiles disagree). `LFP`: heat capacity 1100 J/kg·K, radial conductivity 0.35 W/m·K (about a third of NMC's), axial 31 W/m·K, all measured on whole cylindrical LFP cells, and graphite-dominated entropic heat; literature values, so lower confidence ([below](#lfp-cells)) |
| `capacity_Ah` | required | Rated capacity |
| `V_nominal` | required | Nominal voltage |
| `mass_g` | required | Mass, grams |
| `DCIR_mOhm` | required | **DC** resistance at 25 °C, mid charge, milliohms. Many datasheets give only the 1 kHz AC impedance, which is lower (A123's 26650 datasheet: 8 mΩ AC against 10 mΩ DC); using it under-predicts heat. If that is all you have, raise it, and say so in `source` |
| `DCIR_max_mOhm` | `DCIR_mOhm` | Datasheet maximum; the worst-case re-check uses it plus `options.r_margin` |
| `max_discharge_A`, `max_charge_A` | none | Datasheet current limits, checked against the duty. Without `max_charge_A`, charging is unchecked (a study note says so) and the road trip's rapid charge runs at 1C |
| `T_max_charge_C`, `T_max_discharge_C` | none | Datasheet temperature limits. The default peak limit is the lower of 45 °C and the charging limit (for a duty that charges) or the discharge limit |
| `T_min_charge_C`, `T_min_discharge_C` | none | Datasheet lower limits (v0.6.7). A run that charges, or discharges, at 0.05C or more over 30 s (v0.6.8: not a moment's regen) with any part of the cell colder than these gets a warning (most cells must not be charged below 0 °C) |
| `cp_J_kgK`, `k_radial_W_mK`, `k_axial_W_mK` | jelly roll | Heat capacity and conductivities, if you have measured values |
| `Ea_kJ_mol` | 20 | How fast resistance rises in the cold (20 kJ/mol: about ×2.1 from 25 to 0 °C) |
| `entropic` | true | Entropic heat (NMC and LFP; NCA has none) |
| `source` | none | Where the values come from, echoed in the results |

**Checks.** Values no real cylindrical Li-ion cell has are errors, so a unit slip fails before anything runs. Each error names the likely slip:
- size outside 8–60 × 30–200 mm;
- density outside 1.5–4.0 g/cm³ (mass in kg instead of grams);
- nominal voltage outside 3.3–4.2 V for NMC and NCA, or 2.9–3.45 V for LFP (a cell around 3.2 V labelled NMC, or 3.6 V labelled LFP, is probably the wrong chemistry, and the error says so);
- energy density outside 100–1000 Wh/L (100–600 for LFP; capacity in mAh);
- resistance outside 0.5–500 mΩ (resistance in ohms);
- temperature limits outside 20–90 °C.

Unusual but possible values are warnings, shown by `packtherm cells` and written into the results notes:
- density outside 2.2–3.2 g/cm³ (LFP 1.9–2.7);
- voltage outside 3.4–3.8 V (LFP 3.1–3.35);
- more than 800 Wh/L (LFP 500);
- a current limit above 20C.

### LFP cells

- **Thermal properties** are from measurements on whole cylindrical LFP cells. Heat capacity is the mean of the cylindrical LFP entries in a 2022 meta-analysis (Steinhardt et al., *J. Power Sources* 522, 230829), leaving out two taken at full charge, which were higher. Radial conductivity is the median of those entries (range 0.15–0.51 W/m·K). Axial conductivity is from Drake et al. (*J. Power Sources* 252, 2014) on 26650 and 18650 LFP cells. Measured the same way, NMC cells have a median radial conductivity of about 1.1 W/m·K. PackTherm's calculated NMC value (1.23) sits close to it, so the LFP/NMC difference is the chemistry, not the method.
- **Entropic heat** comes from the graphite electrode, which dominates an LFP/graphite cell's entropy change. It uses the graphite fit behind the NMC profile and the graphite range of an A123 26650 LFP cell (PyBaMM `Prada2013`). It runs from −0.38 mV/K near empty to +0.06 mV/K near full. That is inside the −0.42 to +0.17 mV/K reported for LFP/graphite cells, and heat-absorbing on discharge from about 30 % charge, as measured. It understates the measured mid-charge peak, so mid-charge discharge heat is slightly overstated (the safe side for cooling design) and mid-charge charge heat slightly understated.
- **What it means for design:** radial conduction is poor, so a side ribbon or air leaves LFP cells with two to three times NMC's in-cell spread. A bottom plate draws heat along the axis, where LFP conducts well, so it does comparatively better.

## `duty`

| Key | Used by | Default | Meaning |
|---|---|---|---|
| `type` | all | required | `constant`, `wltc`, `roadtrip` or `segments` |
| `rest_h` | all | 3 | Rest simulated after the event, for recovery |
| `pack_kWh` | all | 60 | Pack size: sets the EV duties' current, and sizes pack-level cooling hardware |
| `c_rate` | constant | 1.0 | Current, in C (> 0) |
| `direction` | constant | `discharge` | `discharge` or `charge` |
| `soc0` | constant, segments | null | Starting SOC (0–1); null: the top of the SOC window for a discharge, the bottom for a charge (segments: 1) |
| `soc_min`, `soc_max` | constant, segments | 0, 1 | Current stops when SOC leaves this window (`soc_min` < `soc_max`) |
| `cycles` | wltc | 3 | WLTC Class 3b cycles back to back |
| `speed_kmh` | roadtrip | 130 | Motorway speed, driven from 90 % to 10 %, then a rapid charge to 80 % |
| `charge_c_rate` | roadtrip | null | Rapid-charge rate; null: the cell's maximum charge rate |
| `pack_V` | wltc, roadtrip | 350 | Pack voltage, for the series count |
| `steps` | segments | required | `[[duration_s, c_rate], ...]`; positive discharges, negative charges, 0 rests |
| `name` | segments | `custom segments` | Label for the duty |

## `requirements`

| Key | Default | Meaning |
|---|---|---|
| `T_max_C` | null | Peak limit for the hottest cell; null: the lower of 45 °C and the cell's datasheet limit |
| `dT_cell_max_C` | 5 | In-cell spread limit (> 0) |
| `recovery_max_min` | null | Ready again (within 1 K of ambient, PCM re-frozen) within this time; null: within the rest window. From v0.6.8 a cell no warmer than 25 °C is also ready if it is above ambient by no more than the event's headroom to its peak limit: in the cold, a little warmth is no harm |
| `cell_to_cell_max_K` | null | Hottest-to-coolest cell limit; null: reported but not limited |
| `capacity_min_pct` | null | Capacity left after `life_years` (% of new) a design must keep; null: reported but not limited (from v0.6.13) |

## `design_space`

Every combination is simulated (ribbons widen to their minimum gap; duplicates are dropped).

| Key | Default | Items |
|---|---|---|
| `topologies` | `[none, air, bottom, ribbon]` | `none` (sealed), `air` (forced air), `bottom` (cold plate), `ribbon` (side ribbon) |
| `air_flows_g_s` | `[0.15, 0.3, 0.6]` | Air per cell, > 0 |
| `coolant_flows_g_s` | `[0.02, 0.05]` | Liquid per cell, > 0 |
| `chiller_C` | `[15]` | Chiller set-points; `[]` for no chiller. Liquid designs always also run on the radiator, and set-points at or above `ambient_C` are skipped |
| `fillers` | `[none, RT31, RT42, RT31-EG]` | `none` or a grade from the PCM library (`-EG`: with expanded graphite) |
| `gaps_mm` | `[2]` | Gap between cans, ≥ 0 |
| `packing` | `hex` | `hex` or `square` |

## `options`

| Key | Default | Meaning |
|---|---|---|
| `edge_cells` | true | Also simulate cells on the module wall |
| `wall_U` | 5 | Module wall heat-transfer coefficient, W/m²K |
| `r_margin` | 0.2 | Worst-case resistance margin above the datasheet maximum, for the re-check of the picks |
| `chiller_cop` | null | Fixed chiller COP; null: from ambient (Carnot fraction) |
| `chiller_runs` | `event` | `event` (then the radiator takes over) or `always` |
| `liquid_loop_kg`, `air_system_kg`, `chiller_kg` | 3, 4, 4 | Pack-level hardware mass |
| `life_years` | 8 | Battery life estimate: capacity left after this many years of the duty once a day (from v0.6.13); 0: no estimate |
| `life_park_C` | null | Where the cell waits between duties; null: `ambient_C` |

### Battery life (from v0.6.13)

Each design gets `capacity_after_pct`: the capacity left after `life_years`, from NREL's BLAST-Lite ageing models (BSD 3-clause, copied into PackTherm). One day is the duty as simulated (state of charge, and the cell's mean temperature: halfway between its hottest and coolest points), then parked at `life_park_C` and the state of charge it ended at for the rest of 24 h; that day repeats every day. The LG M50 and MJ1 have their own models; the other cells use the closest model by chemistry (Panasonic 18650B for NCA, Sony-Murata 26650 for LFP, the M50 for other NMC) and `life_model` says it is a stand-in. Use it to compare designs: a hot-day study makes every day hot, so as an absolute life it is pessimistic.

## `search`

From v0.6.14. Optional: with this section the study searches the design space instead of simulating every combination. It needs the search extra (`pip install "packtherm[search]"`, which installs pymoo) and runs from the command line (`packtherm run`); the web app and the API refuse it for now.

In a search the design space's numeric lists are ranges: any flow between the smallest and largest listed (on a log scale, air and coolant separately), any gap between the smallest and largest (to 0.1 mm), and the chiller either off or at any set-point in its range below ambient (to 0.5 °C). A list with one value fixes it. Cooling types and fillers stay choices. pymoo's NSGA-II for mixed variables looks for the designs that do best on the objectives while meeting every limit in `requirements`; each design is simulated once, however often the search returns to it.

| Key | Default | Meaning |
|---|---|---|
| `evaluations` | 200 | Designs the search may ask for (≥ 10); repeats are not simulated again, so somewhat fewer are simulated |
| `population` | 20 | Designs per generation (≥ 4, at most `evaluations`) |
| `seed` | 1 | Random seed: the same seed gives the same search |
| `mode` | `fast` | Resolution during the search |
| `final_designs` | 12 | How many of the best designs (feasible ones by non-dominated rank, spread from lightest to heaviest) are run again at the study's own `mode` and the cell's resistance, then picked and re-checked at worst-case resistance as a grid study's are. With none feasible, the three nearest misses |
| `objectives` | `[mass, energy]` | What the search minimises: `mass` (mass added), `energy` (fan, pump and chiller energy), `volume` (space taken between and around the cells) and `life` (capacity lost after `life_years`) |
| `worst_case` | true | Judge designs at the worst-case resistance (the datasheet maximum plus `r_margin`) during the search, so that what it finds survives the picks' re-check; false: at the cell's resistance |

A search optimises what it is given and nothing else. Wider gaps, for example, cut air and coolant pressure drop for no added mass but take space: add `volume` to the objectives when the gap is a variable.

`packtherm run` names a search's files `<stem>_search_…`, so they sit beside the grid study's, and also writes `<stem>_search_simulated.csv`: every design the search simulated, in order, at the search's mode and resistance. The results document gains a `search` block (settings, designs simulated, generations, feasible designs found).

## `sensitivity`

From v0.6.15. Optional: with this section the study ranks which uncertain inputs matter most for one design, instead of comparing designs. It needs the sensitivity extra (`pip install "packtherm[sensitivity]"`, which installs SALib and needs numpy 2) and runs from the command line; the web app and the API refuse it for now. A study can have `search` or `sensitivity`, not both.

It uses Morris screening (SALib): each input moves across its range one level at a time along random trajectories, about `trajectories × (inputs + 1)` simulations. For each result it reports `mu_star`, about how much the result changes as the input goes from the low to the high end of its range (the mean absolute elementary effect, in the result's units), and `sigma`, the spread of those effects: large against `mu_star` when the input's effect depends on the others. The results ranked are peak temperature, in-cell spread, cell-to-cell spread, running energy and capacity left.

| Key | Default | Meaning |
|---|---|---|
| `design` | `balanced` | `lightest`, `lowest_energy` or `balanced`: run the grid study first and take that pick. Or a design: `{topology, flow_g_s, chiller_C, filler, gap_mm}` (`chiller_C` null or absent: no chiller; `filler` none by default; `gap_mm` 2 by default) |
| `trajectories` | 10 | Morris trajectories (≥ 2) |
| `levels` | 4 | Levels across each range (even, ≥ 2) |
| `seed` | 1 | Random seed: the same seed gives the same screening |
| `mode` | `fast` | Resolution of the simulations |
| `factors` | null | Inputs to vary; null: every one that applies to the design |
| `ranges` | `{}` | `{input: [low, high]}` replacing an input's default range |

| Input | Default range | What moves |
|---|---|---|
| `ambient` | −5 to +5 K | The study's ambient (and where the car is parked, for battery life) |
| `resistance` | 0 to 1 | The cell's resistance, from its own (0) to the study's worst case (1: the datasheet maximum plus `r_margin`) |
| `cell_heat_capacity` | × 0.9 to 1.1 | The cell's specific heat |
| `cell_conductivity` | × 0.7 to 1.3 | The cell's radial (and axial) thermal conductivity |
| `entropic_heat` | × 0.5 to 1.5 | The reversible heat, dU/dT |
| `tim_conductivity` | × 0.5 to 1.5 | The interface material's conductivity (cold plate and ribbon) |
| `heat_transfer` | × 0.7 to 1.3 | The coolant's h, or the air's |
| `flow` | × 0.8 to 1.2 | The air or coolant flow |
| `chiller_inlet` | −3 to +3 K | The chiller's set-point (chilled designs) |

`packtherm run` names a sensitivity study's files `<stem>_sensitivity_…`: the results document (the design, the inputs and their ranges, the ranking), the ranking CSV, every simulation's inputs and results (`_samples.csv`), and a chart with one panel per result.

## Results document

`packtherm run` writes `<stem>_results.json` next to the designs CSV and the chart (`<stem>` is the name `packtherm design` uses). Format `packtherm_results: 1`, strict JSON (NaN and infinities become `null`):

| Key | Contents |
|---|---|
| `packtherm_results`, `packtherm_version` | Format and software version |
| `created`, `elapsed_s` | When it ran (UTC) and how long it took |
| `study` | The study as run, with every default filled in. It is a valid study file itself: `packtherm run` and the web app re-run it as it is |
| `summary` | Cell, duty, mode, number of designs, feasible, on the trade-off front, the temperature limit, and the text summary |
| `picks` | `lightest`, `lowest_energy`, `balanced` (where they exist), each with every column of its design |
| `notes` | Warnings (each starting `WARNING:`) and notes (`NOTE:`) from the study |
| `labels` | The chart's axis titles and the names of the cooling kinds (from 0.5.5) |
| `assumptions` | Resolution, coolant and air reference points, chiller, wall, resistance margin and pack-level parts |
| `designs` | Every design, one object per row of the designs CSV |

Each design's `fail_reason` lists what it fails, joined by ` · `: `hot` (peak over the limit), `uneven` (in-cell spread over the limit), `slow` (not ready again in time), `spread` (cell-to-cell over the limit), `ages` (less capacity left than `capacity_min_pct`) and `short`, when the cell reached its voltage cut-off and delivered less than 80% of the discharge the duty asks for. A run like that understates the heat, so it fails whatever the cooling, and `rating_warning` says how much was delivered. `rating_warning` also holds datasheet-rating breaches, which are warnings only.
