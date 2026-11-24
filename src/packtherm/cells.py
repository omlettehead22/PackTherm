"""Cell library: geometry, electrical and thermal parameters of real cells.

Every number carries a source. Where a value is an engineering assumption
rather than a measurement it is marked ``ASSUMPTION`` and is exposed as a
field so it can be overridden or swept.

Sources
-------
[ORegan2022]  K. O'Regan, F. Brosa Planella, W.D. Widanage, E. Kendrick,
              "Thermal-electrochemical parameters of a high energy lithium-ion
              cylindrical battery", Electrochimica Acta 425 (2022) 140700.
              Layer thermal properties and electrode entropic coefficients of
              the LG M50 (NMC811 / graphite-SiOx), as implemented in PyBaMM's
              ``ORegan2022`` parameter set.
[Chen2020]    C.-H. Chen et al., "Development of experimental techniques for
              parameterization of multi-scale lithium-ion battery models",
              J. Electrochem. Soc. 167 (2020) 080534. LG M50 electrode design.
[BD-M50]      batterydesign.net, "LG INR 21700 M50" (datasheet summary):
              5.0 Ah, 3.63 V, <=21.10 x 70.15 mm, 68 g, DCIR 30 +/- 6 mOhm
              (30 s, 0.5C), max charge 0.7C at 25-50 degC, max continuous
              discharge 1.5C at 5-60 degC.
[Gulsoy-M50]  M. Gulsoy, K. Kucuk, A. Barai, J. Marco (University of Warwick),
              "Dataset of internal temperature during lithium-ion battery
              ageing", Mendeley Data v2, doi:10.17632/bf6fksxpp2.2, CC BY 4.0.
              LG INR21700-M50 cells at 25 degC: 2C pulses of fresh cells and
              1C discharges with a core thermocouple (v0.6.9).
[M50-DS]      LG Chem, "Product specification, rechargeable lithium ion battery,
              model INR21700 M50 18.2Wh" (2017, tentative): charge 0-45 degC
              (0.3C at 0-25 degC), discharge -20-55 degC; DCIR 30 +/- 6 mOhm
              (0.5C for 30 s at 50 % SOC, 25 degC).
[BD-MJ1]      batterydesign.net, "LG INR 18650 MJ1": NMC811 / graphite-Si,
              3.5 Ah, 46.8 g measured, DCIR 33 mOhm (summary) and 60 mOhm
              (Heenan et al., J. Electrochem. Soc. 167 (2020)), -20 to 60 degC.
[MJ1-DS]      LG Chem INR18650 MJ1 product specification: 3.635 V nominal,
              10 A max continuous discharge, 3.4 A (1C of the 3.4 Ah minimum)
              max charge, charge 0-45 degC, discharge -20-60 degC,
              approx. 18.3 x 65.1 mm.
[Kollmeyer2018] P. Kollmeyer, "Panasonic 18650PF Li-ion Battery Data", Mendeley
              Data v1 (2018), doi:10.17632/wykht8y7tg.1, CC BY 4.0.
[Kollmeyer2023] P. Kollmeyer and M. Skells, "Samsung INR21700 30T 3Ah Li-ion
              Battery Data", Mendeley Data v2 (2023), doi:10.17632/9xyvy2njj3.2,
              CC BY 4.0. Tests at McMaster University at -20 to 40 degC.
[30T-TI]      "Technical Information and Experimental Test Results for Samsung
              IN21700-30T" (McMaster, April 2020, in [Kollmeyer2023]): Li-ion,
              3.6 V, 3.0 Ah, 166 Wh/kg, charge 1.5 A (4 A fast) to 4.2 V,
              discharge to 2.5 V, 35 A max continuous.
[30T-DS]      Samsung SDI, "Specification of Product INR21700-30T" v2.0:
              operating (surface) temperature, charge 0 to 50 degC, discharge
              -20 to 80 degC.
[Kollmeyer2020] P. Kollmeyer, M. Naguib and M. Skells, "LG 18650HG2 Li-ion
              Battery Data", Mendeley Data v2 (2020), doi:10.17632/b5mj79w5w9.2,
              CC BY 4.0. Tests at McMaster University at -20 to 40 degC.
[HG2-TI]      "Technical Information and Experimental Test Results for LG
              18650HG2" (McMaster, January 2020, in [Kollmeyer2020]):
              Li[NiMnCo]O2 / graphite + SiO, 3.6 V, 3.0 Ah, 240 Wh/kg, 18.3 x
              65.0 mm, charge 1.5 A (4 A fast) to 4.2 V, discharge to 2.0 V,
              20 A max continuous.
[HG2-DS]      LG Chem, "Product Specification INR18650HG2" (BCY-PS-HG2):
              operating (cell surface) temperature, charge 0 to 50 degC,
              discharge -20 to 75 degC.
[Souza2021]   M. Kawakita de Souza, "A123 26650 m1b LFP Cell Data", University
              of Colorado Colorado Springs, Mendeley Data v1,
              doi:10.17632/p8kf893yv3.1, CC BY 4.0. Plett-format OCV and
              drive-profile tests at -25 to 45 degC.
[A123-DS]     A123 Systems ANR26650M1-B datasheet (MD100113): LiFePO4 /
              graphite, 26 x 65 mm, 76 g, 2.5 Ah nominal (2.4 min), 3.3 V,
              charge 1C (fast 4C) to 3.6 V CC-CV, operating -30 to 55 degC; and
              Lithium Werks (A123's successor), "ANR26650m1B Power Cell": 50 A
              (20C) max continuous discharge, 120 A 10 s pulse, discharge to 2.0 V;
              charging 0 to 60 degC (under 250 mA below 0 degC for some uses).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace

import numpy as np

from .ecm import ECM
from .params import KELVIN, Geometry, Material, Params

R_GAS = 8.314462618  # J/(mol K)
T_REF = 25.0 + KELVIN


# ---------------------------------------------------------------------------
# NMC811 / graphite-Si jelly-roll properties from [ORegan2022]
# ---------------------------------------------------------------------------


def nmc811_jellyroll_properties(T: float = T_REF) -> tuple[float, float, float]:
    """Stack-averaged (rho, cp, k_radial) of an NMC811/graphite-SiOx jelly roll.

    Builds one repeat unit of the wound stack (Cu foil | 2x anode | 2x
    separator | 2x cathode | Al foil) with LG M50 layer thicknesses [Chen2020]
    and wet-layer properties [ORegan2022]. Heat capacity is thickness-weighted;
    radial conductivity is the series (through-plane) combination, which is
    the relevant direction for a radial model.
    """
    rho_e, cp_e = 1280.0, 229.0  # electrolyte

    def wet(rho_dry, cp_dry, eps):
        rho = rho_dry + rho_e * eps
        return rho, (rho_dry * cp_dry + rho_e * cp_e * eps) / rho

    neg = wet(1740.0, 4.932e-4 * T**3 - 0.491 * T**2 + 169.4 * T - 1.897e4, 0.25)
    pos = wet(3270.0, -8.414e-4 * T**3 + 0.7892 * T**2 - 241.3 * T + 2.508e4, 0.335)
    sep = wet(946.0, 1.494e-3 * T**3 - 1.444 * T**2 + 475.5 * T - 5.13e4, 0.47)
    cu = (8933.0, 1.445e-6 * T**3 - 1.946e-3 * T**2 + 0.9633 * T + 236.0)
    al = (2702.0, 4.503e-6 * T**3 - 6.256e-3 * T**2 + 3.281 * T + 355.7)
    k = {
        "cu": -5.409e-7 * T**3 + 7.054e-4 * T**2 - 0.3727 * T + 463.6,
        "neg": -2.61e-4 * T**2 + 0.1726 * T - 24.49,
        "sep": 0.3344,
        "pos": 2.063e-5 * T**2 - 0.01127 * T + 2.331,
        "al": 237.0,
    }
    layers = {  # (thickness [m], (rho, cp))
        "cu": (12e-6, cu),
        "neg": (2 * 85.2e-6, neg),
        "sep": (2 * 12e-6, sep),
        "pos": (2 * 75.6e-6, pos),
        "al": (16e-6, al),
    }
    L = sum(th for th, _ in layers.values())
    rho = sum(th * p[0] for th, p in layers.values()) / L
    rho_cp = sum(th * p[0] * p[1] for th, p in layers.values()) / L
    k_radial = L / sum(th / k[name] for name, (th, _) in layers.items())
    return rho, rho_cp / rho, k_radial


def nmc811_jellyroll_k_axial(T: float = T_REF) -> float:
    """In-plane (axial) conductivity of the same repeat unit: layers in parallel [W/(m K)].

    The copper and aluminium foils dominate. This is the ideal value along the
    winding; how well the roll's ends couple to the can is a separate
    resistance (see ``packtherm.module.BottomPlate.R_end``).
    """
    k = {
        "cu": -5.409e-7 * T**3 + 7.054e-4 * T**2 - 0.3727 * T + 463.6,
        "neg": -2.61e-4 * T**2 + 0.1726 * T - 24.49,
        "sep": 0.3344,
        "pos": 2.063e-5 * T**2 - 0.01127 * T + 2.331,
        "al": 237.0,
    }
    th = {"cu": 12e-6, "neg": 2 * 85.2e-6, "sep": 2 * 12e-6, "pos": 2 * 75.6e-6, "al": 16e-6}
    return sum(th[n] * k[n] for n in th) / sum(th.values())


def nmc811_graphite_dUdT(soc: float) -> float:
    """Full-cell entropic coefficient dU/dT [V/K] versus state of charge.

    dU/dT = dU_pos/dT(y) - dU_neg/dT(x), electrode fits from [ORegan2022].
    Stoichiometry windows are derived from the LG M50 PyBaMM ``ORegan2022``
    set: 100 % SOC is its initial state (x = 28866/29583 = 0.976,
    y = 13975/51765 = 0.270), and 5 Ah spans dx = 0.961, dy = 0.698.
    """
    soc = min(max(soc, 0.0), 1.0)
    x = 0.976 - 0.961 * (1.0 - soc)
    y = 0.270 + 0.698 * (1.0 - soc)
    dU_neg = (-0.1112 * x + 0.02914 + 0.3561 * math.exp(-((x - 0.08309) ** 2) / 0.004616)) / 1000.0
    dU_pos = (
        0.04006 * math.exp(-((y - 0.2828) ** 2) / 0.0009855) - 0.06656 * math.exp(-((y - 0.8032) ** 2) / 0.02179)
    ) / 1000.0
    return dU_pos - dU_neg


# LFP/graphite cylindrical cells (v0.5.4), from measurements on whole cells.
# [Steinhardt2022] M. Steinhardt et al., "Meta-analysis of experimental results for heat capacity and
#   thermal conductivity in lithium-ion batteries: A critical review", J. Power Sources 522 (2022) 230829.
# [Drake2014] S.J. Drake et al., "Measurement of anisotropic thermophysical properties of cylindrical
#   Li-ion cells", J. Power Sources 252 (2014) 298-304 (26650 and 18650 LFP).
# Heat capacity: mean of the cylindrical LFP entries in [Steinhardt2022] Table 6 without the two taken at
#   100 % SOC ([Drake2014]: 1605, 1720): about 1100 J/kg K (range 998-1720).
# Radial: median of the cylindrical LFP entries in [Steinhardt2022] Table 9: 0.35 W/m K (range 0.15-0.51;
#   the paper's all-format LFP median is 0.40). About a third of NMC's, measured the same way (median 1.1),
#   so the difference is the chemistry, not the method.
# Axial: [Drake2014] 32 and 30.4 W/m K.
LFP_CP = 1100.0
LFP_K_RADIAL = 0.35
LFP_K_AXIAL = 31.0


def lfp_graphite_dUdT(soc: float) -> float:
    """Full-cell entropic coefficient dU/dT [V/K] of an LFP/graphite cell versus SOC.

    The full cell's entropy change comes from the graphite electrode; LiFePO4
    reacts in two phases on a flat plateau and contributes little (measured on
    a commercial LFP/graphite cell split into its electrodes: J. Power Sources
    2014, doi:10.1016/j.jpowsour.2013.07.035). So dU/dT = -dU_neg/dT(x), with
    the graphite fit of [ORegan2022] and the graphite window of an A123 26650
    LFP cell (PyBaMM ``Prada2013``: x = 0.0176 empty to 0.8100 full).

    Result: -0.38 to +0.06 mV/K, inside the -0.42 to +0.17 mV/K reported for
    LFP/graphite cells near 25 degC; heat-absorbing on discharge from about
    30 % SOC, as measured. It understates the measured mid-SOC peak (fit
    without the graphite staging step, as published), so mid-SOC discharge
    heat is slightly overstated and mid-SOC charge heat slightly understated.
    """
    soc = min(max(soc, 0.0), 1.0)
    x = 0.0176 + 0.7924 * soc
    dU_neg = (-0.1112 * x + 0.02914 + 0.3561 * math.exp(-((x - 0.08309) ** 2) / 0.004616)) / 1000.0
    return -dU_neg


def default_soc_factor(soc: float) -> float:
    """ASSUMPTION: resistance multiplier vs SOC.

    Flat over the usable window, rising to ~1.6x at 0 % SOC. This mirrors the
    generic shape of HPPC resistance maps for NMC/graphite cells; replace it
    with a measured map when one is available.
    """
    return 1.0 + 0.6 * math.exp(-max(soc, 0.0) / 0.08)


# ---------------------------------------------------------------------------
# Cell definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Cell:
    name: str
    form_factor: str
    chemistry: str
    capacity_Ah: float
    V_nominal: float
    diameter: float  # m
    height: float  # m
    mass: float  # kg
    R0_25C: float  # Ohm, lumped DC resistance used for irreversible heat
    R0_range: tuple[float, float]  # Ohm, published spread, for sensitivity sweeps
    cp: float  # J/(kg K), jelly-roll average
    k_radial: float  # W/(m K)
    dUdT: Callable[[float], float] = field(repr=False, default=nmc811_graphite_dUdT)
    # ASSUMPTION: Arrhenius activation energy of the lumped resistance. 20 kJ/mol
    # roughly doubles R between 25 degC and 0 degC, typical of NMC/graphite DCIR.
    Ea_R: float = 20e3  # J/mol
    soc_factor: Callable[[float], float] = field(repr=False, default=default_soc_factor)
    max_charge_C: float | None = None
    max_discharge_C: float | None = None
    T_max_charge_C: float | None = None  # degC, datasheet upper limit while charging
    T_max_discharge_C: float | None = None
    # degC, datasheet lower limits (v0.6.7): most cells must not be charged below 0 degC (lithium plating).
    T_min_charge_C: float | None = None
    T_min_discharge_C: float | None = None
    sources: tuple[str, ...] = ()
    # Axial (along the winding) conductivity; defaults to the NMC811 jelly-roll value.
    k_axial: float = field(default_factory=lambda: nmc811_jellyroll_k_axial())
    # Optional equivalent-circuit model. When set, heat is I (OCV - V) from the
    # ECM (with voltage limits and CC-CV charging) instead of I^2 R0.
    ecm: ECM | None = None
    # How the electrical side is modelled, as shown to users (cells table, results).
    model_label: str = "lumped DCIR"
    user_defined: bool = False
    # A fitted cell's tested range: cell temperature (degC), discharge and charge C-rates. Studies warn beyond it.
    validity: dict | None = None
    # v0.6.11: the lumped model's slow losses (diffusion), which a DC resistance read over
    # seconds misses: a first-order overpotential with resistance slow_share x R0_25C (with its
    # own Arrhenius and the same SOC factor) and time constant slow_tau_s. Under steady current
    # it adds slow_share x R0 to the heat; it fades in rests. 0: none (circuit cells don't use it).
    slow_share: float = 0.0
    slow_tau_s: float = 440.0
    slow_Ea_R: float = 26e3  # J/mol

    @property
    def radius(self) -> float:
        return self.diameter / 2

    @property
    def volume(self) -> float:
        return math.pi * self.radius**2 * self.height

    @property
    def density(self) -> float:
        """Bulk density from measured mass and can volume [kg/m^3]."""
        return self.mass / self.volume

    @property
    def material(self) -> Material:
        return Material(rho=self.density, cp=self.cp, k=self.k_radial)

    def resistance(self, soc: float, T: float) -> float:
        """Lumped resistance [Ohm] at state of charge and temperature [K]."""
        arrhenius = math.exp(self.Ea_R / R_GAS * (1.0 / T - 1.0 / T_REF))
        return self.R0_25C * arrhenius * self.soc_factor(soc)

    def slow_resistance(self, soc: float, T: float) -> float:
        """The lumped model's slow-branch resistance [Ohm] (v0.6.11; 0 when it has none)."""
        if not self.slow_share:
            return 0.0
        arrhenius = math.exp(self.slow_Ea_R / R_GAS * (1.0 / T - 1.0 / T_REF))
        return self.slow_share * self.R0_25C * arrhenius * self.soc_factor(soc)

    def current(self, c_rate: float) -> float:
        return c_rate * self.capacity_Ah

    @staticmethod
    def from_datasheet(**values) -> Cell:
        """A user-defined cell from datasheet values (see ``packtherm.user_cells``)."""
        from .user_cells import from_datasheet

        return from_datasheet(**values)


_RHO_JR, _CP_JR, _K_JR = nmc811_jellyroll_properties()

# v0.6.11: the lumped model's slow branch (Cell.slow_share), by chemistry. A DC resistance
# read over seconds left a lumped cell making 22-64 % of its fitted circuit's heat. Tuned
# (validation/tune_lumped_slow.py) so lumped models of the PF, 30T and HG2 (NMC/NCA) and of
# the A123 (LFP), from their 10 s DC resistance, make the heat of their fitted circuits over
# steady discharges (0.5-2C), 2C pulses, a measured drive cycle and a 0.5C charge at 25 to
# -10 degC: lumped/circuit heat 0.69-1.19 (NMC/NCA; was 0.33-1.05) and 0.58-1.27 (LFP, whose
# resistance depends on current more than a lumped model can follow; was 0.16-0.68).
# Checked on the M50, never tuned on: its circuit 0.98-1.42 (most above 1.15 on 2C pulses),
# and the measured 1C discharges, surface rise 8.0-8.4 K against 8-10.4 K (was 5.5-5.9).
LUMPED_SLOW: dict[str, dict[str, float]] = {
    "NMC": {"slow_share": 0.88, "slow_tau_s": 440.0, "slow_Ea_R": 26e3},
    "LFP": {"slow_share": 1.6, "slow_tau_s": 250.0, "slow_Ea_R": 36e3},
}


def _load_ocv_table(name: str) -> tuple[tuple[float, ...], tuple[float, ...]]:
    from importlib import resources

    text = resources.files("packtherm").joinpath(f"data/{name}").read_text()
    rows = [line.split(",") for line in text.splitlines() if line and not line.startswith(("#", "soc"))]
    soc, ocv = zip(*((float(a), float(b)) for a, b in rows))
    return soc, ocv


_M50_SOC, _M50_OCV = _load_ocv_table("lgm50_oregan2022_ocv.csv")

# v0.4.11: equivalent circuit for the M50 DERIVED from a physics model, not from
# cell tests: PyBaMM's DFN with the ORegan2022 parameter set (measured on the LG
# M50T, with temperature dependence) was run through synthetic HPPC tests at
# 25, 10, 0 and -10 degC (10 s pulses at 0.2-3C, C/3 steps with 1 h rests), and
# the same circuit as the NCR18650PF fitted to them (validation/derive_m50_ecm.py).
# Pulse overpotential within 3.6-4.7 % median; irreversible heat within 0.94-1.13x
# of the DFN on 0.5-1.4C discharges and a pulsed profile at 0-25 degC (the lumped
# model it replaces: 0.92-1.42x). The knee comes late in the cold: cut-off up to
# 0.75 Ah after the DFN at 0 degC 1.4C. Measured M50 data would replace this.
LG_M50_ECM_DERIVED = ECM(
    ocv_soc=_M50_SOC,
    ocv_V=_M50_OCV,
    R0_25C=0.0131,
    Ea_R0=11.4e3,
    I0_25C=4.93,
    Ea_I0=38.9e3,
    gamma=1.335,
    tau_ct=13.5,
    Rd_25C=0.0069,
    tau_d=147.0,
    Ea_Rd=38.0e3,
    V_max=4.2,
    V_min=2.5,
    cv_cutoff_A=0.05,
    soc_a=2.52,
    soc_b=0.0795,
    Ea_soc=0.0,
    sources=("ORegan2022", "PyBaMM"),
)

# v0.6.9: measured M50 data. The derived circuit has about half the cell's real
# resistance: on the 2C pulses of six fresh cells at 25 degC [Gulsoy-M50] it
# drops 130-200 mV where the cells drop 270-400 mV. One scale on every loss term,
# fitted on those pulses alone (validation/fit_m50_scale.py), takes the pulse
# error from 168 to 19 mV RMS; on the 1C discharges of the core-temperature tests
# (never fitted on) the voltage error falls from 114-146 to 18-40 mV and the heat,
# about 60 % of the measured before, comes right (validation/check_m50_core.py).
# Checked at 25 degC only: the temperature dependence is still the DFN's.
M50_R_SCALE = 2.04
LG_M50_ECM = LG_M50_ECM_DERIVED.scaled(M50_R_SCALE)

LG_M50 = Cell(
    name="LG INR21700 M50",
    form_factor="21700",
    chemistry="NMC811 / graphite-SiOx",
    capacity_Ah=5.0,
    V_nominal=3.63,
    diameter=21.10e-3,
    height=70.15e-3,
    mass=0.068,
    R0_25C=0.030,
    R0_range=(0.024, 0.036),
    cp=_CP_JR,
    k_radial=_K_JR,
    max_charge_C=0.7,
    max_discharge_C=1.5,
    T_max_charge_C=50.0,
    T_max_discharge_C=60.0,
    # v0.6.9: the lower limits (no charging below 0 degC, discharge down to -20 degC),
    # as in [M50-DS] and [BD-M50] (0.3C from 0 degC); without them studies gave no cold warnings.
    T_min_charge_C=0.0,
    T_min_discharge_C=-20.0,
    sources=("BD-M50", "M50-DS", "ORegan2022", "Chen2020", "Gulsoy-M50"),
    ecm=LG_M50_ECM,
    model_label="circuit (derived, measured resistance)",
)

# The v0.4.11-v0.6.8 M50: the derived circuit as the DFN gave it, for comparison.
LG_M50_DERIVED = replace(
    LG_M50, name="LG INR21700 M50 (derived circuit, v0.6.8)", ecm=LG_M50_ECM_DERIVED, model_label="circuit (derived)"
)

# The v0.4.10 lumped-resistance M50 (I^2 R with an Arrhenius DCIR), for comparison.
LG_M50_LUMPED = replace(
    LG_M50, name="LG INR21700 M50 (lumped DCIR)", ecm=None, model_label="lumped DCIR", **LUMPED_SLOW["NMC"]
)

LG_MJ1 = Cell(
    name="LG INR18650 MJ1",
    form_factor="18650",
    chemistry="NMC811 / graphite-Si",
    capacity_Ah=3.5,
    V_nominal=3.635,
    diameter=18.3e-3,
    height=65.1e-3,
    mass=0.0468,
    # Conservative choice: the measured 60 mOhm (Heenan 2020) rather than the
    # 33 mOhm summary value; both bound R0_range.
    R0_25C=0.060,
    R0_range=(0.033, 0.060),
    # Same chemistry family as the M50; jelly-roll properties reused (ASSUMPTION).
    cp=_CP_JR,
    k_radial=_K_JR,
    max_charge_C=3.4 / 3.5,  # 3.4 A
    max_discharge_C=10.0 / 3.5,  # 10 A
    T_max_charge_C=45.0,
    T_max_discharge_C=60.0,
    T_min_charge_C=0.0,  # [MJ1-DS] (v0.6.10: missing before, so cold studies gave no warning)
    T_min_discharge_C=-20.0,
    sources=("BD-MJ1", "MJ1-DS", "ORegan2022"),
    **LUMPED_SLOW["NMC"],
)

CELLS: dict[str, Cell] = {"M50": LG_M50, "M50-DERIVED": LG_M50_DERIVED, "M50-LUMPED": LG_M50_LUMPED, "MJ1": LG_MJ1}


def with_R0(cell: Cell, R0: float) -> Cell:
    """The cell with its resistance scaled to R0 (lumped DCIR reference).

    For an equivalent-circuit cell every loss term scales by R0 / R0_25C: the
    ohmic and slow-branch resistances, and the charge-transfer term through
    I0 (its small-signal resistance is inversely proportional to I0).
    """
    f = R0 / cell.R0_25C
    if cell.ecm is None:
        return replace(cell, R0_25C=R0)
    return replace(cell, R0_25C=R0, ecm=cell.ecm.scaled(f))


def get_cell(key: str) -> Cell:
    """A library cell by key, or a user-defined cell from a .yaml/.yml/.json file."""
    if key.lower().endswith((".yaml", ".yml", ".json")):
        from .user_cells import load_cell

        return load_cell(key)
    try:
        return CELLS[key.upper()]
    except KeyError:
        raise KeyError(
            f"Unknown cell '{key}'. Available: {', '.join(CELLS)}, or a cell file (.yaml or .json)"
        ) from None


def params_for_cell(
    cell: Cell,
    pcm_thickness: float = 3e-3,
    case_thickness: float = 1e-3,
    base: Params | None = None,
    dr_target: float = 1e-4,
    exact_volumes: bool = False,
) -> Params:
    """Model parameters for ``cell`` wrapped in PCM and a casing.

    pcm_thickness may be 0 (no PCM). The radial mesh keeps a ~0.1 mm spacing,
    which the thesis mesh study showed is converged to < 0.001 degC.
    """
    base = base or Params()
    r_cell = cell.radius
    r_pcm = r_cell + pcm_thickness
    r_case = r_pcm + case_thickness
    n = max(3, int(np.ceil(r_case / dr_target)))
    geom = Geometry(
        r_cell=r_cell, r_pcm=r_pcm, r_case=r_case, length=cell.height, n_cells=n, exact_volumes=exact_volumes
    )
    return base.with_(geometry=geom, cell=cell.material)


# ---------------------------------------------------------------------------
# Panasonic NCR18650PF: identified from the Kollmeyer test dataset
# ---------------------------------------------------------------------------


def _zero_dUdT(soc: float) -> float:
    return 0.0


_PF_SOC, _PF_OCV = _load_ocv_table("ncr18650pf_ocv.csv")

# Electrical model identified from the dataset's own characterisation tests
# (see validation/identify_panasonic.py):
#   OCV: 25 degC C/20 discharge/charge.
#   R0, I0, Ea_I0, gamma: 10 s overpotential of every HPPC pulse at 20-95 % SOC
#       at 25, 10, 0, -10, -20 degC (median error 5-11 % per temperature).
#   soc_a, soc_b: low-SOC rise of the same pulse overpotentials (all temperatures).
#   tau_ct: median fitted pulse time constant at 25 degC.
#   Rd, tau_d: slow branch fitted to the voltage of the 25 degC 1C calibration
#       discharge (the only test used for calibration).
NCR18650PF_ECM = ECM(
    ocv_soc=_PF_SOC,
    ocv_V=_PF_OCV,
    R0_25C=0.0260,
    Ea_R0=0.0,
    I0_25C=15.61,
    Ea_I0=45.2e3,
    gamma=8.69,
    tau_ct=4.0,
    Rd_25C=0.0284,  # calibrated on the 25 degC 1C discharge #1 voltage (v0.4.10 re-fit)
    tau_d=405.0,
    V_max=4.2,
    V_min=2.5,
    cv_cutoff_A=0.05,
    soc_a=10.18,
    soc_b=0.0801,
    # v0.4.10: temperature laws from the 0.9 A discharge-and-rest steps between
    # the HPPC pulse sets at 25, 10, 0 and -10 degC (identification data, not
    # in the validation set): the low-SOC rise grows in the cold (20.7 kJ/mol)
    # and the slow branch follows its own, gentler Arrhenius law (26.8 kJ/mol)
    # instead of the charge-transfer kinetics (45 kJ/mol). Rd_25C and tau_d
    # re-calibrated on the same single test with these laws.
    Ea_Rd=26.8e3,
    Ea_soc=20.7e3,
    sources=("Kollmeyer2018",),
)

PANASONIC_NCR18650PF = Cell(
    name="Panasonic NCR18650PF",
    form_factor="18650",
    chemistry="NCA / graphite",
    capacity_Ah=2.99491,  # C/20 at 25 degC, this dataset's cell
    V_nominal=3.6,
    diameter=18.5e-3,  # with tube (datasheet max); the thermocouple sits on the tube
    height=65.3e-3,
    mass=0.047,  # datasheet: 47.0 g max without tube, 48.0 g max with tube
    R0_25C=0.046,  # 10 s DC resistance at 1-2C, mid SOC, from the HPPC data
    R0_range=(0.043, 0.052),
    # ASSUMPTION: NMC811-family jelly-roll properties reused for NCA/graphite.
    cp=_CP_JR,
    k_radial=_K_JR,
    # ASSUMPTION: entropic heat neglected (no NCA dU/dT data in this dataset).
    dUdT=_zero_dUdT,
    # Datasheet limits are currents; C-rates here are against this cell's
    # measured capacity, which is what the model uses to turn C-rate into amps.
    max_charge_C=1.375 / 2.99491,  # datasheet standard charge 1375 mA
    max_discharge_C=10.0 / 2.99491,  # 10 A
    T_max_charge_C=45.0,
    T_max_discharge_C=60.0,
    # Panasonic's NCR18650PF sheet: charge 0 to +45 degC, discharge -20 to +60 degC (some later
    # copies give charge from +10 degC). v0.6.10: missing before, so cold studies gave no warning.
    T_min_charge_C=0.0,
    T_min_discharge_C=-20.0,
    sources=("Kollmeyer2018", "NCR18650PF datasheet"),
    ecm=NCR18650PF_ECM,
    model_label="circuit (measured)",
)

CELLS["PF"] = PANASONIC_NCR18650PF


# ---------------------------------------------------------------------------
# Samsung INR21700 30T: geometry and limits; its circuit is fitted (v0.6.3)
# ---------------------------------------------------------------------------

# The lumped-resistance 30T: the base a fitted circuit is laid on (its "like" cell),
# and the comparison for it. Its R0_25C is the fitted circuit's 10 s DC resistance.
SAMSUNG_30T_LUMPED = Cell(
    name="Samsung INR21700 30T (lumped DCIR)",
    form_factor="21700",
    chemistry="Li-ion (cathode not stated by the source)",
    capacity_Ah=3.0,
    V_nominal=3.6,
    # Maximum size with tube from the dataset's drawing; the thermocouple sits on the tube.
    diameter=21.22e-3,
    height=70.30e-3,
    # Derived: 3.6 V x 3.0 Ah at 166 Wh/kg [30T-TI] is 65 g; no mass is stated.
    mass=0.065,
    # The fitted circuit's 10 s DC resistance at mid charge, 1.5C and 25 degC (30T below); it rises
    # 2.5x by 0 degC, close to the default Arrhenius law's 20 kJ/mol (21-25 kJ/mol between 40 and 0 degC).
    R0_25C=0.0143,
    R0_range=(0.0129, 0.0157),
    # ASSUMPTION: NMC811-family jelly-roll properties (the source names no cathode).
    cp=_CP_JR,
    k_radial=_K_JR,
    # ASSUMPTION: entropic heat neglected, as for the NCR18650PF.
    dUdT=_zero_dUdT,
    max_charge_C=4.0 / 3.0,  # 4 A fast charge
    max_discharge_C=35.0 / 3.0,  # 35 A continuous
    T_max_charge_C=50.0,  # [30T-DS], surface
    T_max_discharge_C=80.0,
    T_min_charge_C=0.0,
    T_min_discharge_C=-20.0,
    sources=("Kollmeyer2023", "30T-TI", "30T-DS"),
    **LUMPED_SLOW["NMC"],
)

CELLS["30T-LUMPED"] = SAMSUNG_30T_LUMPED


def _packaged_fitted_cell(file: str, name: str, sources: tuple[str, ...]) -> Cell:
    """A library cell from a fitted cell file shipped with PackTherm (made by ``packtherm fit``)."""
    from importlib import resources

    import yaml

    from .fitting.cellfile import cell_from_doc

    doc = yaml.safe_load(resources.files("packtherm").joinpath(f"data/{file}").read_text())
    cell = cell_from_doc(doc)
    return replace(cell, name=name, model_label="circuit (fitted)", user_defined=False, sources=sources)


# v0.6.3: the 30T's circuit fitted by `packtherm fit` at -20 to 40 degC, from the tests in
# [Kollmeyer2023] (docs/examples/fitting/samsung_30t_tests.yaml; the report beside it).
SAMSUNG_30T = _packaged_fitted_cell("samsung_30t_fitted.yaml", "Samsung INR21700 30T", ("Kollmeyer2023", "30T-TI", "30T-DS"))
CELLS["30T"] = SAMSUNG_30T


# ---------------------------------------------------------------------------
# LG INR18650-HG2: geometry and limits; its circuit is fitted (v0.6.4)
# ---------------------------------------------------------------------------

# The lumped-resistance HG2: the base a fitted circuit is laid on (its "like" cell),
# and the comparison for it. Its R0_25C is the fitted circuit's 10 s DC resistance.
LG_HG2_LUMPED = Cell(
    name="LG INR18650-HG2 (lumped DCIR)",
    form_factor="18650",
    chemistry="NMC / graphite + SiO",
    capacity_Ah=3.0,
    V_nominal=3.6,
    diameter=18.3e-3,
    height=65.0e-3,
    # Derived: 3.6 V x 3.0 Ah at 240 Wh/kg [HG2-TI] is 45 g; no mass is stated.
    mass=0.045,
    # The fitted circuit's 10 s DC resistance at mid charge, 1.5C and 25 degC (HG2 below); it
    # rises 2x by 0 degC, close to the default Arrhenius law's 20 kJ/mol.
    R0_25C=0.0283,
    R0_range=(0.0255, 0.0311),
    # ASSUMPTION: NMC811-family jelly-roll properties, as for the other library cells.
    cp=_CP_JR,
    k_radial=_K_JR,
    # ASSUMPTION: entropic heat neglected, as for the NCR18650PF and the 30T.
    dUdT=_zero_dUdT,
    max_charge_C=4.0 / 3.0,  # 4 A fast charge
    max_discharge_C=20.0 / 3.0,  # 20 A continuous
    T_max_charge_C=50.0,  # [HG2-DS], cell surface
    T_max_discharge_C=75.0,
    T_min_charge_C=0.0,
    T_min_discharge_C=-20.0,
    sources=("Kollmeyer2020", "HG2-TI", "HG2-DS"),
    **LUMPED_SLOW["NMC"],
)

CELLS["HG2-LUMPED"] = LG_HG2_LUMPED

# v0.6.4: the HG2's circuit fitted by `packtherm fit` at -20 to 40 degC, from the tests in
# [Kollmeyer2020] (docs/examples/fitting/lg_hg2_tests.yaml; the report beside it), with the
# method of v0.6.3 unchanged.
# Its capacity is the dataset's C/20 at 25 degC to its 2.8 V cut-off, 2.78 Ah: below the rated 3.0 Ah
# (to 2.0 V), so a pack sized on it has about 8% more cells than the rating needs (v0.6.8 note).
LG_HG2 = _packaged_fitted_cell("lg_hg2_fitted.yaml", "LG INR18650-HG2", ("Kollmeyer2020", "HG2-TI", "HG2-DS"))
CELLS["HG2"] = LG_HG2


# ---------------------------------------------------------------------------
# A123 ANR26650M1B (LFP): geometry and limits; its circuit is fitted (v0.6.6)
# ---------------------------------------------------------------------------

# The lumped-resistance A123: the base a fitted circuit is laid on (its "like" cell). Its
# R0_25C is the fitted circuit's 10 s DC resistance.
A123_26650_LUMPED = Cell(
    name="A123 ANR26650M1B (lumped DCIR)",
    form_factor="26650",
    chemistry="LFP / graphite",
    capacity_Ah=2.5,
    V_nominal=3.3,
    diameter=26.0e-3,
    height=65.0e-3,
    mass=0.076,
    # The fitted circuit's 10 s DC resistance at mid charge, 1.5C and 25 degC (A123 below; 16.9 mOhm
    # in v0.6.6, 14.4 in v0.6.7); it rises 2.2x by 5 degC and 8x by -15 degC.
    R0_25C=0.0134,
    R0_range=(0.0121, 0.0147),
    # Whole-cell LFP values, as for user-defined LFP cells (v0.5.4).
    cp=LFP_CP,
    k_radial=LFP_K_RADIAL,
    k_axial=LFP_K_AXIAL,
    dUdT=lfp_graphite_dUdT,
    max_charge_C=4.0,  # 4C fast charge
    max_discharge_C=20.0,  # 50 A continuous
    # [A123-DS]: operating -30 to 55 degC; charging from 0 degC (Lithium Werks: up to 60, held at 55 here).
    T_max_charge_C=55.0,
    T_max_discharge_C=55.0,
    T_min_charge_C=0.0,
    T_min_discharge_C=-30.0,
    sources=("Souza2021", "A123-DS"),
    **LUMPED_SLOW["LFP"],
)

CELLS["A123-LUMPED"] = A123_26650_LUMPED

# v0.6.6: the A123's circuit fitted blind by `packtherm fit` at -15 to 45 degC, from the tests in
# [Souza2021] (docs/examples/fitting/a123_26650_tests.yaml; the report beside it). There are no pulse
# tests: the kinetics come from the drive profiles' changes in current. v0.6.7: refitted with LFP's
# hysteresis, from its slow charges. Good at 5-45 degC; much less so in the cold (docs/FITTING.md).
A123_26650 = _packaged_fitted_cell("a123_26650_fitted.yaml", "A123 ANR26650M1B", ("Souza2021", "A123-DS"))
CELLS["A123"] = A123_26650


# Kept to compare against, not to design with (v0.6.9): the M50's circuit before its
# resistance was measured, and the lumped-resistance versions of the circuit cells.
# A lumped cell's heat is within about -30 to +20 % of its circuit's since v0.6.11 (22-64 % on a
# steady discharge before), but it has no voltage limits: no cut-off, no constant-voltage taper.
COMPARISON = frozenset({"M50-DERIVED", "M50-LUMPED", "30T-LUMPED", "HG2-LUMPED", "A123-LUMPED"})


def library_summary() -> dict[str, dict]:
    """The cell library in brief, as the API's GET /cells and the web app show it."""
    return {
        k: {
            "name": c.name,
            "group": "comparison" if k in COMPARISON else "design",
            "model": c.model_label,
            "format": c.form_factor,
            "capacity_Ah": c.capacity_Ah,
            "V_nominal": c.V_nominal,
            "DCIR_25C_mOhm": c.R0_25C * 1e3,
            "mass_g": c.mass * 1e3,
        }
        for k, c in CELLS.items()
    }
