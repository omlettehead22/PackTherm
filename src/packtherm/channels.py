"""Coolant channels: heat transfer and pressure drop from their shape and flow (v0.6.12).

Up to v0.6.11 the liquid coolant's convective coefficient was an assumed
1500 W/(m^2 K) at a reference flow for every cold plate and ribbon, scaled by
an assumed flow exponent, and the channels' pressure drop an assumed 20 kPa.
Here both come from the channel geometry, the flow and the coolant's
properties at its temperature:

* Properties: 50/50 ethylene glycol-water (CoolProp's MEG[0.5], tabulated in
  data/meg50_properties.csv). Its viscosity rises sevenfold from 25 to -20 degC.
* Heat transfer (ht, Caleb Bell, MIT): laminar flow in a rectangular passage,
  fully developed (Shah and London, uniform wall flux, by aspect ratio) with
  the thermal-entry rise of Hausen's mean Nusselt number scaled onto it;
  turbulent flow by Gnielinski; between Re 2300 and 3000 a linear blend.
* Friction (fluids, Caleb Bell, MIT): laminar rectangular passages by Shah and
  London's f Re(aspect ratio); turbulent by fluids' smooth-pipe friction factor.
* Fins: the passage walls and ribs carry heat from the face that touches the
  cell; their efficiency (tanh(mL)/mL, aluminium) is taken into the wetted area.

What a cell sees is h per contact area: the wall coefficient times the
effective wetted area over the area through which the cell is cooled.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

LAMINAR_RE, TURBULENT_RE = 2300.0, 3000.0
K_ALUMINIUM = 160.0  # W/(m K): 3003-type brazing alloy (pure aluminium ~ 237)
_DATA = Path(__file__).parent / "data" / "meg50_properties.csv"


@lru_cache(maxsize=1)
def _table() -> np.ndarray:
    with _DATA.open(encoding="utf-8") as f:
        rows = [r for r in csv.reader(line for line in f if not line.startswith("#"))]
    return np.array([[float(x) for x in r] for r in rows[1:]])


@dataclass(frozen=True)
class Fluid:
    rho: float  # kg/m^3
    cp: float  # J/(kg K)
    k: float  # W/(m K)
    mu: float  # Pa s

    @property
    def Pr(self) -> float:
        return self.mu * self.cp / self.k


def glycol50(T_C: float) -> Fluid:
    """50/50 ethylene glycol-water at T_C (clamped to -30..100 degC); viscosity interpolated in log."""
    a = _table()
    T = float(np.clip(T_C, a[0, 0], a[-1, 0]))
    rho, cp, k = (float(np.interp(T, a[:, 0], a[:, i])) for i in (1, 2, 3))
    mu = float(np.exp(np.interp(T, a[:, 0], np.log(a[:, 4]))))
    return Fluid(rho, cp, k, mu)


def _shah_london_fRe(alpha: float) -> float:
    """Laminar f_Darcy Re in a rectangular duct of aspect ratio alpha <= 1 (Shah and London 1978)."""
    a = alpha
    return 96.0 * (1 - 1.3553 * a + 1.9467 * a**2 - 1.7012 * a**3 + 0.9564 * a**4 - 0.2537 * a**5)


@dataclass(frozen=True)
class Passage:
    """One rectangular flow passage of a channel, and how many run side by side."""

    width_m: float
    height_m: float
    count: float  # passages in parallel carrying the channel's flow (may be fractional per cell row)
    length_m: float  # along the flow

    @property
    def area(self) -> float:
        return self.width_m * self.height_m

    @property
    def perimeter(self) -> float:
        return 2.0 * (self.width_m + self.height_m)

    @property
    def Dh(self) -> float:
        return 4.0 * self.area / self.perimeter

    @property
    def aspect(self) -> float:
        return min(self.width_m, self.height_m) / max(self.width_m, self.height_m)


@dataclass(frozen=True)
class ChannelFlow:
    Re: float
    Pr: float
    Nu: float
    h_wall: float  # W/(m^2 K), on the wetted wall
    f_darcy: float
    dp_Pa: float  # along the channel
    velocity_m_s: float
    regime: str


def channel_flow(p: Passage, mdot_kg_s: float, fluid: Fluid) -> ChannelFlow:
    """Heat transfer and pressure drop for ``mdot`` shared by ``p.count`` passages."""
    import fluids
    import ht

    v = mdot_kg_s / (fluid.rho * p.area * p.count)
    Re = fluid.rho * v * p.Dh / fluid.mu
    Pr = fluid.Pr

    def laminar():
        Nu_fd = ht.Nu_laminar_rectangular_Shan_London(p.aspect)
        entry = ht.laminar_entry_thermal_Hausen(Re=Re, Pr=Pr, L=p.length_m, Di=p.Dh) / 3.66
        return Nu_fd * entry, _shah_london_fRe(p.aspect) / Re

    def turbulent():
        f = fluids.friction_factor(Re=max(Re, TURBULENT_RE), eD=0.0)
        return ht.conv_internal.turbulent_Gnielinski(Re=max(Re, TURBULENT_RE), Pr=Pr, fd=f), f

    if Re <= LAMINAR_RE:
        Nu, f = laminar()
        regime = "laminar"
    elif Re >= TURBULENT_RE:
        Nu, f = turbulent()
        regime = "turbulent"
    else:
        w = (Re - LAMINAR_RE) / (TURBULENT_RE - LAMINAR_RE)
        (Nl, fl), (Nt, ft) = laminar(), turbulent()
        Nu, f = (1 - w) * Nl + w * Nt, (1 - w) * fl + w * ft
        regime = "transitional"
    h = Nu * fluid.k / p.Dh
    dp = f * p.length_m / p.Dh * 0.5 * fluid.rho * v * v
    return ChannelFlow(Re, Pr, Nu, h, f, dp, v, regime)


def fin_efficiency(h: float, thickness_m: float, length_m: float, k: float = K_ALUMINIUM) -> float:
    """Straight fin with an adiabatic tip: tanh(mL)/(mL)."""
    if length_m <= 0:
        return 1.0
    mL = math.sqrt(2.0 * h / (k * thickness_m)) * length_m
    return math.tanh(mL) / mL if mL > 1e-9 else 1.0
