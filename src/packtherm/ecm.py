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

Irreversible heat is I (OCV - V), so every loss term heats the cell.
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
BY_T_COLUMNS = ("T_K", "R0", "I0", "gamma", "tau_ct", "Rm", "tau_m", "Rd", "tau_d", "soc_a", "soc_b")


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

    def __post_init__(self):
        if self.by_T:
            rows = sorted(self.by_T, key=lambda r: -r[0])  # warm to cold: 1/T ascending
            if len(rows) < 2 or any(len(r) != len(BY_T_COLUMNS) for r in rows):
                raise ValueError(f"by_T needs two rows or more of {', '.join(BY_T_COLUMNS)}")
            object.__setattr__(self, "_x", tuple(1.0 / r[0] for r in rows))
            object.__setattr__(self, "_cols", tuple(tuple(r[i] for r in rows) for i in range(len(BY_T_COLUMNS))))

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

    def ocv(self, soc: float) -> float:
        """OCV from the table; linear extrapolation (slope of the last 5 %) outside it."""
        s, v = self.ocv_soc, self.ocv_V
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


@dataclass
class ECMState:
    eta_ct: float = 0.0
    V_d: float = 0.0
    V_m: float = 0.0
    cutoff: bool = False  # discharge hit V_min
    charge_done: bool = False  # CV phase ended

    def step(self, ecm: ECM, current: float, soc: float, T: float, dt: float) -> tuple[float, float, float, float]:
        """Voltage after a step at ``current`` without committing: (V, eta_ct_new, V_d_new, V_m_new)."""
        e1 = math.exp(-dt / ecm.tau_ct_at(T))
        e2 = math.exp(-dt / ecm.tau_d_at(T))
        # The low-SOC rise was identified on discharge pulses; apply it on discharge only.
        f = ecm.soc_factor(soc, T) if current > 0 else 1.0
        eta = self.eta_ct * e1 + f * ecm.eta_ss(current, T) * (1.0 - e1)
        vd = self.V_d * e2 + f * ecm.Rd(T) * current * (1.0 - e2)
        vm = 0.0
        Rm = ecm.Rm(T)
        if Rm or self.V_m:
            e3 = math.exp(-dt / ecm.tau_m_at(T))
            vm = self.V_m * e3 + f * Rm * current * (1.0 - e3)
        V = ecm.ocv(soc) - current * f * ecm.R0(T) - eta - vm - vd
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
        return current, V
