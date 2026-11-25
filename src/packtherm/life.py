"""Battery life from a design's temperatures (v0.6.13).

Capacity left after some years, from NREL's BLAST-Lite degradation models
(copied into packtherm._vendor.blast, BSD 3-clause): calendar ageing by
temperature and state of charge, cycle ageing by charge throughput,
temperature and C-rate, each fitted to published ageing tests of a real cell.

How a design's life is estimated: the study's duty is one day's use. The day is
the duty and its rest as simulated (the cell's state of charge, and its mean
temperature: halfway between its hottest and coolest points), then the cell is
parked for the rest of 24 h at ``park_T_C`` (by default the study's ambient)
and the state of charge it ended at. That day repeats for ``years``.

It compares designs: a cooler cell during and after the duty ages less. As an
absolute life it is pessimistic for a hot-day study (every day of the year is
that day) and leaves out what BLAST-Lite leaves out (see each model's notes).

Cells and models: the LG M50 and MJ1 have their own models. The others use the
model of the closest cell BLAST-Lite has, a stand-in, and say so: the Panasonic
NCR18650PF and NCA datasheet cells the Panasonic 18650B (NCA, same maker); the
A123 and LFP datasheet cells the Sony-Murata 3 Ah LFP 26650; the Samsung 30T,
LG HG2 and other NMC cells the LG M50 (NMC811 / graphite-Si).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .cells import Cell

DAY_S = 86400.0
SAMPLE_S = 60.0


@dataclass(frozen=True)
class LifeModel:
    module: str
    cls: str
    cell: str  # the cell BLAST-Lite's model was fitted to
    stand_in: bool


M50 = LifeModel("nmc811_grSi_LGM50_5Ah_2021", "Nmc811_GrSi_LGM50_5Ah_Battery", "LG M50 (NMC811 / graphite-Si)", False)
MJ1 = LifeModel("nmc811_grSi_LGMJ1_4Ah_2020", "Nmc811_GrSi_LGMJ1_4Ah_Battery", "LG MJ1 (NMC811 / graphite-Si)", False)
NCA = LifeModel("nca_gr_Panasonic3Ah_2018", "Nca_Gr_Panasonic3Ah_Battery", "Panasonic 18650B (NCA / graphite)", True)
LFP = LifeModel("lfp_gr_SonyMurata3Ah_2018", "Lfp_Gr_SonyMurata3Ah_Battery", "Sony-Murata 3 Ah 26650 (LFP / graphite)", True)


def life_model(cell: Cell) -> LifeModel:
    """The BLAST-Lite model for a cell: its own where there is one, else the closest by chemistry."""
    name, chem = cell.name.upper(), cell.chemistry.upper()
    if "M50" in name:
        return M50
    if "MJ1" in name:
        return MJ1
    if "LFP" in chem:
        return LFP
    if "NCA" in chem:
        return NCA
    return LifeModel(M50.module, M50.cls, M50.cell, True)


def _battery(m: LifeModel):
    import importlib

    mod = importlib.import_module(f"packtherm._vendor.blast.models.{m.module}")
    return getattr(mod, m.cls)()


@dataclass(frozen=True)
class LifeResult:
    capacity_pct: float  # capacity left after ``years``, % of new
    years: float
    model: LifeModel
    day_T_mean_C: float  # time-mean cell temperature over the day
    day_efc: float  # equivalent full cycles a day

    @property
    def note(self) -> str:
        stand = " (a stand-in: no model for this cell)" if self.model.stand_in else ""
        return f"BLAST-Lite model of the {self.model.cell}{stand}"


def one_day(t_s, soc, T_C, park_T_C: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The duty as simulated, then parked for the rest of the day (or of the duty, if longer)."""
    t = np.asarray(t_s, float) - float(t_s[0])
    soc, T_C = np.asarray(soc, float), np.asarray(T_C, float)
    grid = np.arange(0.0, t[-1] + 1e-9, SAMPLE_S)
    s, T = np.interp(grid, t, soc), np.interp(grid, t, T_C)
    period = max(DAY_S, math.ceil((grid[-1] + SAMPLE_S) / DAY_S) * DAY_S)
    park = np.arange(grid[-1] + SAMPLE_S, period + 1e-9, SAMPLE_S)
    return (
        np.concatenate([grid, park]),
        np.clip(np.concatenate([s, np.full(park.size, s[-1])]), 0.0, 1.0),
        np.concatenate([T, np.full(park.size, park_T_C)]),
    )


def capacity_after(cell: Cell, t_s, soc, T_C, park_T_C: float, years: float = 8.0) -> LifeResult:
    """Capacity left after ``years`` of this duty once a period (a day, or the duty if longer)."""
    t, s, T = one_day(t_s, soc, T_C, park_T_C)
    m = life_model(cell)
    b = _battery(m)
    b.simulate_battery_life({"Time_s": t, "SOC": s, "Temperature_C": T}, threshold_time=years)
    efc = float(np.sum(np.abs(np.diff(s))) / 2.0) * DAY_S / t[-1]
    T_mean = float(np.sum(0.5 * (T[1:] + T[:-1]) * np.diff(t)) / (t[-1] - t[0]))
    return LifeResult(100.0 * float(b.outputs["q"][-1]), years, m, T_mean, efc)
