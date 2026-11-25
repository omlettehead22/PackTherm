"""Battery degradation models copied from NREL's BLAST-Lite (v0.6.13).

Source: https://github.com/NREL/BLAST-Lite (commit 991591726c07, November 2026), BSD 3-clause
licence, Copyright (c) 2023 Alliance for Energy Innovation, LLC: see LICENSE and NOTICE here.
Copied rather than installed because the package pins Python <= 3.13 and numpy < 2 and pulls
in weather-data packages PackTherm does not need. Changes: imports made relative; the base
model's matplotlib import and a commented-out test block at its end removed; np.trapz (gone from numpy 2.4) replaced by np.trapezoid where numpy has it; only
rescale_soc kept from utils/functions.py; four of its cell models kept.
"""
