# Real test files: Panasonic NCR18650PF

Files from P. Kollmeyer, "Panasonic 18650PF Li-ion Battery Data", Mendeley Data v1 (2018),
doi:[10.17632/wykht8y7tg.1](https://doi.org/10.17632/wykht8y7tg.1), published under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The tests were performed at the
University of Wisconsin-Madison. The cell is a Panasonic NCR18650PF (NCA, 2.9 Ah), tested in a
25 °C chamber.

They are copied unchanged, with their original names. One file is cut: the UDDS drive cycle is
5.3 MB, so `..._first20min.mat` holds only its first 12,001 rows (20 minutes). Its values are not
altered. `tests/test_testdata.py` reads them all in every CI run.

| File | What it is |
|---|---|
| `03-11-17_08.47 25degC_5Pulse_HPPC_Pan18650PF.mat` | Five-pulse HPPC test: 10 s pulses at 0.5, 1, 2, 4 and 6C, with discharges between the levels that the log leaves out |
| `05-08-17_13.26 C20 OCV Test_C20_25dC.mat` | C/20 discharge and charge (0.145 A), for the open-circuit voltage |
| `07-22-17_22.44 4020_Dis1C_1.mat` | 1C discharge, logged from partway through |
| `07-22-17_23.40 4020_Charge2.mat` | CC-CV charge, logged once a minute |
| `03-21-17_00.29 25degC_UDDS_Pan18650PF_first20min.mat` | The first 20 minutes of a UDDS drive cycle |
| `03-09-17_15.12 3349_TS002973.mat` | A single-sample file, as the dataset has several |

As in the original files, discharge current is negative; PackTherm's reader flips it.
