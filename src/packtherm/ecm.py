"""Equivalent-circuit electrical model with temperature-dependent kinetics.

Terminal voltage (current I > 0 on discharge):

    V = OCV(SOC) - I R0(T) - eta_ct - V_m - V_d

* R0(T): ohmic resistance, Arrhenius in temperature.
* eta_ct: charge-transfer overpotential. Its steady-state value follows a
  lumped Butler-Volmer form, eta_ss = A(T) asinh(I / (2 I0(T))) with
  A = gamma 2RT/F, so the apparent resistance falls as current rises and
  climbs steeply in the cold. It relaxes to eta_ss with time constant tau_ct.
* On discharge all three are scaled by a low-SOC factor
  1 + soc_a(T) exp(-SOC/soc_b) (identified from discharge pulses, so not
  applied while charging). soc_a is Arrhenius in temperature when Ea_soc is
  set, which makes the voltage knee arrive earlier in the cold.
* V_m: an optional middle RC branch (R_m, tau_m; off when R_m = 0), between
  the charge transfer's seconds and the slow branch's minutes: tens of seconds.
  Fitted cells use it (v0.6.2); the library cells do not.
* V_d: a slow (diffusion) RC branch with resistance R_d(T) and time
  constant tau_d. With Ea_Rd set, R_d is Arrhenius with its own activation
  energy; otherwise it scales with the small-signal charge-transfer
  resistance.

Values by temperature (``by_T``, from fitting tests at several temperatures,
v0.6.2): rows of R0, I0, gamma, tau_ct, Rd, tau_d, soc_a and soc_b at each
fitted temperature. Between them each is interpolated in 1/T (logarithmically:
an Arrhenius law between neighbours). Beyond the coldest or warmest row, the
resistances and rates follow the laws above (Ea_*) from that row, and the shape
and time constants hold. Without rows, the laws above apply everywhere.

Open-circuit voltage by temperature (``ocv_by_T``, v0.6.5): curves from slow
discharges at several temperatures, each against the same state of charge (the
charge left, as a share of the reference capacity: the 25 degC slow test's). A
cell whose capacity shrinks in the cold reaches its cut-off at a higher state of
charge there, and charge is still conserved as its temperature changes. Between
curves the voltage at a state of charge is interpolated linearly in T; beyond
the coldest or warmest, that curve holds. Without them, the one curve applies
at every temperature.

Hysteresis (``hyst``, v0.6.7; LFP): the open-circuit curve is the discharge's,
and a state h runs from 0 (on the discharge branch) to 1 (on the charge
branch). Charging moves h towards 1 and discharging towards 0, by
dh = (target - h)(1 - exp(-k |I| dt / 3600)): about 1/k Ah of charge in one
direction crosses most of the way. The voltage is raised by G h, G the gap
between the two branches. Rows (T_K, G, k) by temperature, interpolated
linearly in T and held beyond the ends; off when there are none. A fourth
column (v0.6.8), the instant share f: that share of the gap follows the sign of
the last current at once (Plett's instantaneous hysteresis), the rest by h, so
V is raised by G ((1 - f) h + f s), s 1 after a charge and 0 after a discharge.

Irreversible heat is I (OCV - V), so every loss term heats the cell; with
hysteresis, OCV is taken midway between the branches (the curve plus G/2), so
each pass round the loop heats by about G/2 per unit of charge.
Discharge stops at V_min; charging switches from constant current to
constant voltage at V_max and ends when |I| falls below the cut-off.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field, replace

F = 96485.33212
R_GAS = 8.314462618
T_REF = 298.15
FULL_SOC = 0.98  # a run or test starting this full starts just charged: on the charge branch (hysteresis)
BY_T_COLUMNS = ("T_K", "R0", "I0", "gamma", "tau_ct", "Rm", "tau_m", "Rd", "tau_d", "soc_a", "soc_b")
# The excess branch's threshold turns over this current, A (a softplus, so the fit stays smooth).
EXCESS_SOFT_A = 0.01
EXCESS_SEEN_V = 0.02  # V: where the excess branch counts as acting (its tested range, and studies' warning)


@dataclass(frozen=True)
class ECM:
    ocv_soc: tuple[float, ...]
    ocv_V: tuple[float, ...]
    R0_25C: float  # Ohm
    Ea_R0: float  # J/mol
    I0_25C: float  # A, lumped exchange current
    Ea_I0: float  # J/mol
    gamma: float  # multiplier on 2RT/F
    tau_ct: float = 2.0  # s
    Rd_25C: float = 0.0  # Ohm, slow branch
    tau_d: float = 300.0  # s
    V_max: float = 4.2
    V_min: float = 2.5
    cv_cutoff_A: float = 0.05
    # Low-SOC rise of all overpotentials: factor = 1 + soc_a exp(-SOC / soc_b).
    soc_a: float = 0.0
    soc_b: float = 0.08
    Ea_soc: float = 0.0  # J/mol, temperature dependence of soc_a
    Ea_Rd: float | None = None  # J/mol; None = follow the charge-transfer kinetics
    sources: tuple[str, ...] = field(default=())
    # The middle branch: off at Rm_25C = 0.
    Rm_25C: float = 0.0  # Ohm
    tau_m: float = 30.0  # s
    Ea_Rm: float | None = None  # J/mol; None = as the slow branch
    # Values by temperature: rows of BY_T_COLUMNS, any order.
    by_T: tuple[tuple[float, ...], ...] = ()
    # Open-circuit voltage by temperature: (T_K, soc, V) curves, on the reference capacity's state of charge.
    ocv_by_T: tuple[tuple[float, tuple[float, ...], tuple[float, ...]], ...] = ()
    # Hysteresis (v0.6.7): (T_K, G, k) rows: the gap between the charge and discharge branches (V), and how
    # quickly a change of direction crosses it (1/Ah). Off when empty.
    hyst: tuple[tuple[float, ...], ...] = ()
    # Excess polarisation (v0.6.17): transport losses beyond the rate the open-circuit curves were measured
    # at. The curves come from slow tests (C/30), so they already hold whatever a cell loses at that
    # current; above it, a cell can lose much more in the cold near empty (the A123 at -12 degC: about
    # 1 ohm on the current above C/30 at 25 % charge, against tens of milliohms warm). The current
    # smoothed over tau_x, i_f, drives a drop R_x(soc, T) softplus(|i_f| - I_x), on charge and discharge
    # alike: R_x = Rx_cold exp(Ea_x/R (1/T - 1/T_x)) / (1 + exp((soc - soc_x)/w_x)), rising as the charge
    # runs down and levelling off near empty. Off at Rx_cold = 0.
    Rx_cold: float = 0.0  # ohm, at T_x and empty
    Ea_x: float = 0.0  # J/mol
    soc_x: float = 0.2  # where the rise is half way
    w_x: float = 0.05  # how sharply it rises (SOC)
    tau_x: float = 300.0  # s
    I_x: float = 0.0  # A: the open-circuit curves' own current
    T_x: float = 261.15  # K: where Rx_cold is given
    # The largest smoothed current at which the fit's tests saw the branch add EXCESS_SEEN_V or more (A);
    # studies warn beyond it (0: not recorded).
    I_x_tested: float = 0.0

    def __post_init__(self):
        if self.by_T:
            rows = sorted(self.by_T, key=lambda r: -r[0])  # warm to cold: 1/T ascending
            if len(rows) < 2 or any(len(r) != len(BY_T_COLUMNS) for r in rows):
                raise ValueError(f"by_T needs two rows or more of {', '.join(BY_T_COLUMNS)}")
            object.__setattr__(self, "_x", tuple(1.0 / r[0] for r in rows))
            object.__setattr__(self, "_cols", tuple(tuple(r[i] for r in rows) for i in range(len(BY_T_COLUMNS))))
        if self.ocv_by_T:
            curves = sorted(self.ocv_by_T, key=lambda c: c[0])
            if any(len(c[1]) != len(c[2]) or len(c[1]) < 2 for c in curves):
                raise ValueError("ocv_by_T: each curve needs as many voltages as states of charge, two or more")
            object.__setattr__(self, "_ocv_T", tuple(float(c[0]) for c in curves))
            object.__setattr__(self, "_ocv_curves", tuple((tuple(c[1]), tuple(c[2])) for c in curves))

    @property
    def excess(self) -> bool:
        return self.Rx_cold > 0.0

    def Rx(self, soc: float, T: float) -> float:
        """The excess branch's resistance at soc and T (K), ohm."""
        z = min(max((soc - self.soc_x) / self.w_x, -50.0), 50.0)
        return self.Rx_cold * math.exp(self.Ea_x / R_GAS * (1.0 / T - 1.0 / self.T_x)) / (1.0 + math.exp(z))

    def excess_V(self, i_f: float, soc: float, T: float) -> float:
        """The excess drop (V, + on discharge) for the smoothed current i_f (A)."""
        if not self.excess:
            return 0.0
        x = (abs(i_f) - self.I_x) / EXCESS_SOFT_A
        over = EXCESS_SOFT_A * (math.log1p(math.exp(x)) if x < 30.0 else x)
        return math.copysign(self.Rx(soc, T) * over, i_f)

    def excess_step(self, i_f: float, current: float, dt: float) -> float:
        """The smoothed current after dt at current."""
        e = math.exp(-dt / self.tau_x)
        return i_f * e + current * (1.0 - e)

    def _hyst_at(self, i: int, T: float) -> float:
        rows = sorted(self.hyst)
        if T <= rows[0][0]:
            return rows[0][i]
        if T >= rows[-1][0]:
            return rows[-1][i]
        k = bisect_right([r[0] for r in rows], T) - 1
        a, b = rows[k], rows[k + 1]
        return a[i] + (b[i] - a[i]) * (T - a[0]) / (b[0] - a[0])

    def hyst_V(self, T: float) -> float:
        """The gap between the charge and discharge branches at T (K): 0 without hysteresis."""
        return self._hyst_at(1, T) if self.hyst else 0.0

    def hyst_rate(self, T: float) -> float:
        """How quickly a change of direction crosses the gap at T (K), 1/Ah."""
        return self._hyst_at(2, T) if self.hyst else 0.0

    def hyst_share(self, T: float) -> float:
        """The share of the gap that changes branch at once with the current's sign (v0.6.8)."""
        if not self.hyst or len(self.hyst[0]) < 4:
            return 0.0
        return self._hyst_at(3, T)

    def hyst_offset(self, h: float, s: float, T: float) -> float:
        """The voltage the hysteresis adds: G ((1 - f) h + f s)."""
        if not self.hyst:
            return 0.0
        f = self.hyst_share(T)
        return self.hyst_V(T) * ((1.0 - f) * h + f * s)

    def factor(self, soc: float, current: float, T: float = T_REF) -> float:
        """The rise near empty: identified on discharge, so applied on discharge only."""
        return self.soc_factor(soc, T) if current > 0 else 1.0

    @staticmethod
    def hyst_sign(s: float, current: float) -> float:
        """The last direction: 1 after a charge, 0 after a discharge (held at rest)."""
        return 1.0 if current < 0 else (0.0 if current > 0 else s)

    def hyst_step(self, h: float, current: float, dt: float, T: float = T_REF) -> float:
        """The hysteresis state after dt at current (+ = discharge): towards 1 on charge, 0 on discharge."""
        if not self.hyst or current == 0.0:
            return h
        target = 1.0 if current < 0 else 0.0
        return target + (h - target) * math.exp(-self.hyst_rate(T) * abs(current) * dt / 3600.0)

    def _at(self, col: str, T: float, Ea: float | None = None, sign: float = 1.0) -> float:
        """A tabulated value at T: log-interpolated in 1/T; beyond the rows, Ea from the end row (or held)."""
        i = BY_T_COLUMNS.index(col)
        xs, ys = self._x, self._cols[i]
        x = 1.0 / T
        if x <= xs[0] or x >= xs[-1]:
            j = 0 if x <= xs[0] else -1
            y = ys[j]
            if Ea is None or y <= 0:
                return y
            return y * math.exp(sign * Ea / R_GAS * (x - xs[j]))
        k = bisect_right(xs, x) - 1
        u = (x - xs[k]) / (xs[k + 1] - xs[k])
        a, b = ys[k], ys[k + 1]
        if a > 0 and b > 0:
            return a * (b / a) ** u
        return a + (b - a) * u

    def gamma_at(self, T: float) -> float:
        return self._at("gamma", T) if self.by_T else self.gamma

    def tau_ct_at(self, T: float) -> float:
        return self._at("tau_ct", T) if self.by_T else self.tau_ct

    def tau_d_at(self, T: float) -> float:
        return self._at("tau_d", T) if self.by_T else self.tau_d

    def tau_m_at(self, T: float) -> float:
        return self._at("tau_m", T) if self.by_T else self.tau_m

    def Rm(self, T: float) -> float:
        Ea = self.Ea_Rm if self.Ea_Rm is not None else self.Ea_Rd
        if self.by_T:
            return self._at("Rm", T, Ea if Ea is not None else self.Ea_I0)
        if self.Rm_25C == 0.0:
            return 0.0
        if Ea is not None:
            return self.Rm_25C * math.exp(Ea / R_GAS * (1.0 / T - 1.0 / T_REF))
        return self.Rm_25C * self.R_ct_small_signal(T) / self.R_ct_small_signal(T_REF)

    def scaled(self, f: float) -> ECM:
        """Every loss term times f: R0 and Rd times f, I0 divided by f (see cells.with_R0)."""
        rows = tuple((r[0], r[1] * f, r[2] / f, r[3], r[4], r[5] * f, r[6], r[7] * f, *r[8:]) for r in self.by_T)
        return replace(
            self,
            R0_25C=self.R0_25C * f,
            Rd_25C=self.Rd_25C * f,
            Rm_25C=self.Rm_25C * f,
            I0_25C=self.I0_25C / f,
            by_T=rows,
        )

    def soc_factor(self, soc: float, T: float = T_REF) -> float:
        if self.by_T:
            a, b = self._at("soc_a", T, self.Ea_soc), self._at("soc_b", T)
        else:
            a = self.soc_a * math.exp(self.Ea_soc / R_GAS * (1.0 / T - 1.0 / T_REF))
            b = self.soc_b
        return 1.0 + a * math.exp(-max(soc, 0.0) / b)

    def ocv(self, soc: float, T: float | None = None) -> float:
        """OCV at soc (and the cell temperature T, K, if the cell has curves by temperature)."""
        if not self.ocv_by_T or T is None:
            return curve_value(self.ocv_soc, self.ocv_V, soc)
        Ts, cs = self._ocv_T, self._ocv_curves
        if T <= Ts[0]:
            return curve_value(*cs[0], soc)
        if T >= Ts[-1]:
            return curve_value(*cs[-1], soc)
        k = bisect_right(Ts, T) - 1
        u = (T - Ts[k]) / (Ts[k + 1] - Ts[k])
        a, b = curve_value(*cs[k], soc), curve_value(*cs[k + 1], soc)
        return a + (b - a) * u

    def R0(self, T: float) -> float:
        if self.by_T:
            return self._at("R0", T, self.Ea_R0)
        return self.R0_25C * math.exp(self.Ea_R0 / R_GAS * (1.0 / T - 1.0 / T_REF))

    def I0(self, T: float) -> float:
        if self.by_T:
            return self._at("I0", T, self.Ea_I0, -1.0)
        return self.I0_25C * math.exp(-self.Ea_I0 / R_GAS * (1.0 / T - 1.0 / T_REF))

    def A(self, T: float) -> float:
        return self.gamma_at(T) * 2.0 * R_GAS * T / F

    def eta_ss(self, current: float, T: float) -> float:
        return self.A(T) * math.asinh(current / (2.0 * self.I0(T)))

    def R_ct_small_signal(self, T: float) -> float:
        return self.A(T) / (2.0 * self.I0(T))

    def Rd(self, T: float) -> float:
        if self.by_T:
            return self._at("Rd", T, self.Ea_Rd if self.Ea_Rd is not None else self.Ea_I0)
        if self.Ea_Rd is not None:
            return self.Rd_25C * math.exp(self.Ea_Rd / R_GAS * (1.0 / T - 1.0 / T_REF))
        return self.Rd_25C * self.R_ct_small_signal(T) / self.R_ct_small_signal(T_REF)


def curve_value(s: tuple[float, ...], v: tuple[float, ...], soc: float) -> float:
    """A curve's voltage at soc; linear extrapolation (slope of the last 5 %) outside it."""
    if soc > s[-1]:
        k = min(len(s) - 1, max(1, round(0.05 / (s[-1] - s[-2]))))
        return v[-1] + (v[-1] - v[-1 - k]) / (s[-1] - s[-1 - k]) * (soc - s[-1])
    if soc < s[0]:
        k = min(len(s) - 1, max(1, round(0.05 / (s[1] - s[0]))))
        return v[0] + (v[k] - v[0]) / (s[k] - s[0]) * (soc - s[0])
    # Scalar linear interpolation (np.interp on one value is slow in a time loop).
    i = bisect_right(s, soc) - 1
    if i >= len(s) - 1:
        return float(v[-1])
    return v[i] + (v[i + 1] - v[i]) * (soc - s[i]) / (s[i + 1] - s[i])


@dataclass
class ECMState:
    eta_ct: float = 0.0
    V_d: float = 0.0
    V_m: float = 0.0
    h: float = 0.0  # hysteresis: 0 on the discharge branch, 1 on the charge branch
    s: float = 0.0  # the last direction (v0.6.8): 1 after a charge, 0 after a discharge
    i_f: float = 0.0  # the current smoothed for the excess branch (v0.6.17), A
    cutoff: bool = False  # discharge hit V_min
    charge_done: bool = False  # CV phase ended

    def step(self, ecm: ECM, current: float, soc: float, T: float, dt: float) -> tuple[float, float, float, float]:
        """Voltage after a step at ``current`` without committing: (V, eta_ct_new, V_d_new, V_m_new)."""
        e1 = math.exp(-dt / ecm.tau_ct_at(T))
        e2 = math.exp(-dt / ecm.tau_d_at(T))
        # The low-SOC rise was identified on discharge pulses; apply it on discharge only.
        f = ecm.factor(soc, current, T)
        eta = self.eta_ct * e1 + f * ecm.eta_ss(current, T) * (1.0 - e1)
        vd = self.V_d * e2 + f * ecm.Rd(T) * current * (1.0 - e2)
        vm = 0.0
        Rm = ecm.Rm(T)
        if Rm or self.V_m:
            e3 = math.exp(-dt / ecm.tau_m_at(T))
            vm = self.V_m * e3 + f * Rm * current * (1.0 - e3)
        V = ecm.ocv(soc, T) - current * f * ecm.R0(T) - eta - vm - vd
        if ecm.excess:  # v0.6.17
            self._i_f_next = ecm.excess_step(self.i_f, current, dt)
            V -= ecm.excess_V(self._i_f_next, soc, T)
        if ecm.hyst:
            V += ecm.hyst_offset(ecm.hyst_step(self.h, current, dt, T), ecm.hyst_sign(self.s, current), T)
        return V, eta, vd, vm

    def apply(self, ecm: ECM, current: float, soc: float, T: float, dt: float) -> tuple[float, float]:
        """Enforce voltage limits, commit the step and return (current, V).

        Discharge below V_min stops the test (current 0 from then on).
        Charge above V_max switches to constant voltage: the current is
        reduced (by bisection, V is monotonic in I) to hold V_max until it
        falls below the cut-off, which ends the charge.
        """
        if current > 0 and self.cutoff:
            current = 0.0
        if current < 0 and self.charge_done:
            current = 0.0
        V, eta, vd, vm = self.step(ecm, current, soc, T, dt)
        if current > 0 and V < ecm.V_min:
            self.cutoff = True
            current = 0.0
            V, eta, vd, vm = self.step(ecm, 0.0, soc, T, dt)
        elif current < 0 and V > ecm.V_max:
            lo, hi = current, 0.0  # V(lo) > V_max >= V(hi) at rest
            if self.step(ecm, 0.0, soc, T, dt)[0] > ecm.V_max:
                lo = hi = 0.0
            for _ in range(50):
                mid = 0.5 * (lo + hi)
                if self.step(ecm, mid, soc, T, dt)[0] > ecm.V_max:
                    lo = mid
                else:
                    hi = mid
                if hi - lo < 1e-6:
                    break
            current = hi
            if abs(current) < ecm.cv_cutoff_A:
                self.charge_done = True
                current = 0.0
            V, eta, vd, vm = self.step(ecm, current, soc, T, dt)
        self.eta_ct, self.V_d, self.V_m = eta, vd, vm
        if ecm.excess:
            self.i_f = self._i_f_next  # from the last step: the current committed
        self.h = ecm.hyst_step(self.h, current, dt, T)
        self.s = ecm.hyst_sign(self.s, current)
        return current, V
