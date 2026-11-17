"""Cell test data: read a tester's export, check it, and label its parts.

The first step towards fitting a cell model to measured data (v0.6). A record
is time, current, voltage and, where logged, cell and ambient temperature, in
PackTherm's units and sign convention: seconds, amps (positive = discharge),
volts, degC.

    from packtherm.testdata import load_test_data
    rec = load_test_data("hppc_25C.csv")
    print(rec.summary())
    for s in rec.segments():
        ...

Files: CSV or TSV (any delimiter pandas can sniff), and MATLAB ``.mat`` files,
including the ``meas`` structure of the Kollmeyer datasets (Panasonic
NCR18650PF, Samsung 30T, LG HG2). Columns are found by name for the common
tester exports (Arbin, Neware, Biologic, Digatron, Maccor) or given
explicitly. Units are read from the column names ("Current(mA)", "I/mA",
"Voltage [mV]", "Time (ms)") and checked against the values. The sign of the
current is judged from the voltage: on discharge the voltage falls when the
current starts.

The parts of a test (`segments`):

- ``rest``: no current
- ``pulse``: a short steady current (at most 60 s), as in HPPC tests
- ``constant``: a longer steady current (a C/20 or 1C discharge, say)
- ``cc-cv``: a constant-current charge that tapers at constant voltage
- ``dynamic``: a varying current, such as a drive cycle (a stretch of many
  short steps with no long rest between them)

Nothing here fits a model: v0.6.1 does that, from these labelled parts. The
reading, checks and labels do not assume the model, so a generic circuit
model with the user's choice of RC branches can be fitted from the same
records later.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# -- column names -----------------------------------------------------------
# Matched against a column name lower-cased with spaces, brackets and units
# kept; the first pattern that matches a column wins, so the specific ones come
# first. A unit in the name ("(mA)", "/mA", "[mV]") is read separately.
COLUMN_PATTERNS: dict[str, tuple[str, ...]] = {
    "time": (
        r"^test[ _]?time",  # Arbin, Maccor "Test Time"
        r"^total[ _]?time",  # Neware "Total Time"
        r"^time\b",  # "Time", "Time (s)", "time/s" (Biologic), Kollmeyer "Time"
        r"^t\b",
        r"^t_s$",  # "t_s": time in seconds
        r"^elapsed",
        r"^runtime|^run[ _]time",
    ),
    "current": (r"^current", r"^i\b", r"^i/", r"^amps?\b", r"<i>"),
    "voltage": (r"^voltage", r"^v\b", r"^ewe", r"^ecell", r"^u\b", r"^volts?\b", r"^cell[ _]?voltage", r"<ewe>"),
    "temperature": (
        r"^battery[ _]?temp",  # Kollmeyer Battery_Temp_degC
        r"^cell[ _]?temp",
        r"^surface[ _]?temp",
        r"^temperature",  # Arbin "Temperature (C)_1"
        r"^temp\b",
        r"^aux.*temp",
        r"^t[ _]?cell",
    ),
    "ambient": (r"^chamber", r"^ambient", r"^t[ _]?amb", r"^env"),
    # The tester's own charge counter: it keeps counting while logging pauses.
    "charge": (r"^ah\b", r"^amp[ _-]?hours?", r"^capacity", r"^\(q-qo\)", r"^q[ _-]?charge", r"^cap\b"),
    "charge_in": (r"^charge[ _]?capacity", r"^chg[ _]?cap"),  # Arbin, Maccor: separate counters
    "charge_out": (r"^discharge[ _]?capacity", r"^dchg[ _]?cap"),
}

_UNIT = re.compile(
    r"[\(\[/]\s*(ms|s|sec|h|hr|min|mah|ah|ma|a|mv|v|degc|°c|c|k|ma\.h)\s*[\)\]]?\s*(?:_\d+)?$", re.IGNORECASE
)

PULSE_MAX_S = 60.0  # a steady current this short is a pulse
SECTION_REST_S = 300.0  # rests this long separate the parts of a test
DYNAMIC_MIN_STEPS = 30  # a stretch of this many current steps without a long rest is a drive cycle


class TestDataError(ValueError):
    """The file cannot be read as a cell test, with what to do about it."""

    __test__ = False  # not a pytest test class


@dataclass(frozen=True)
class Segment:
    kind: str  # rest, pulse, constant, cc-cv, dynamic, unlogged
    start: int  # index of the first sample
    stop: int  # index after the last sample
    t0: float  # s
    t1: float  # s
    current_A: float  # mean current (+ discharge)
    charge_Ah: float  # charge moved (+ discharged)

    @property
    def duration_s(self) -> float:
        return self.t1 - self.t0


@dataclass
class TestRecord:
    """A cell test in PackTherm's units and sign convention (seconds, A with + = discharge, V, degC)."""

    __test__ = False  # not a pytest test class

    t: np.ndarray
    current_A: np.ndarray
    voltage_V: np.ndarray
    temperature_C: np.ndarray | None = None
    ambient_C: np.ndarray | None = None
    # The tester's own count of charge discharged (Ah, + = discharge), if the file has one. It keeps
    # counting when logging pauses, so it fills gaps in the record (see charge_Ah).
    counter_Ah: np.ndarray | None = None
    source: str = ""
    columns: dict[str, str] = field(default_factory=dict)  # role -> column it came from
    conversions: list[str] = field(default_factory=list)  # what was changed on reading, in words
    warnings: list[str] = field(default_factory=list)
    capacity_Ah: float | None = None  # if known: C-rates in the summary

    def __len__(self) -> int:
        return int(self.t.size)

    @property
    def duration_s(self) -> float:
        return float(self.t[-1] - self.t[0]) if self.t.size else 0.0

    def charge_Ah(self) -> np.ndarray:
        """Cumulative charge discharged since the start (Ah), by the trapezium rule."""
        return np.concatenate([[0.0], np.cumsum(interval_charge_Ah(self.t, self.current_A, self.counter_Ah))])

    def segments(self) -> list[Segment]:
        return label_segments(self.t, self.current_A, self.voltage_V, self.counter_Ah)

    def summary(self) -> str:
        segs = self.segments()
        counts: dict[str, int] = {}
        for s in segs:
            counts[s.kind] = counts.get(s.kind, 0) + 1
        dt = np.diff(self.t)
        step = f" (median step {np.median(dt):.3g} s)" if dt.size else ""
        lo, hi = self.current_A.min() + 0.0, self.current_A.max() + 0.0  # + 0.0: no "-0"
        lines = [
            f"{self.source or 'test record'}: {len(self)} samples over {_hms(self.duration_s)}{step}",
            (
                f"current {lo:.3g} to {hi:.3g} A (+ = discharge); "
                f"voltage {self.voltage_V.min():.3f} to {self.voltage_V.max():.3f} V"
            ),
        ]
        if self.temperature_C is not None:
            T = self.temperature_C[np.isfinite(self.temperature_C)]
            if T.size:
                lines.append(f"cell temperature {T.min():.1f} to {T.max():.1f} degC")
        if self.ambient_C is not None:
            A = self.ambient_C[np.isfinite(self.ambient_C)]
            if A.size:
                lines.append(f"ambient {np.median(A):.1f} degC (median)")
        q = self.charge_Ah()
        lines.append(f"charge discharged: {q.max():.3f} Ah at most, {q[-1]:.3f} Ah at the end")
        if self.columns:
            lines.append("columns: " + ", ".join(f"{k} <- {v!r}" for k, v in self.columns.items()))
        lines += [f"converted: {c}" for c in self.conversions]
        lines.append("parts: " + ", ".join(f"{n} {k}" for k, n in counts.items()))
        lines += [f"WARNING: {w}" for w in self.warnings]
        return "\n".join(lines)

    def segment_table(self) -> list[dict]:
        cap = self.capacity_Ah
        rows = []
        for i, s in enumerate(self.segments()):
            row = {
                "n": i + 1,
                "kind": s.kind,
                "start_s": round(s.t0, 3),
                "duration_s": round(s.duration_s, 3),
                "current_A": round(s.current_A, 4),
                "charge_Ah": round(s.charge_Ah, 5),
            }
            if cap:
                row["c_rate"] = round(s.current_A / cap, 3)
            rows.append(row)
        return rows

    def plot(self, path: str | Path, dpi: int = 130) -> Path:
        """Current, voltage and temperature against time, with the labelled parts shaded."""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        hours = self.duration_s > 3 * 3600
        x = (self.t - self.t[0]) / (3600.0 if hours else 60.0)
        n = 3 if self.temperature_C is not None else 2
        fig, ax = plt.subplots(n, 1, sharex=True, figsize=(9, 2.2 * n + 0.6))
        shade = {"pulse": "#2a78d6", "constant": "#1baf7a", "cc-cv": "#1baf7a", "dynamic": "#eb6834"}
        for s in self.segments():
            if s.kind in shade:
                for a in ax:
                    a.axvspan(x[s.start], x[s.stop - 1], color=shade[s.kind], alpha=0.08, lw=0)
        ax[0].plot(x, self.current_A, lw=0.8, color="#0b0b0b")
        ax[0].set_ylabel("Current (A)\n+ discharge")
        ax[1].plot(x, self.voltage_V, lw=0.8, color="#2a78d6")
        ax[1].set_ylabel("Voltage (V)")
        if n == 3:
            ax[2].plot(x, self.temperature_C, lw=0.8, color="#eb6834", label="cell")
            if self.ambient_C is not None:
                ax[2].plot(x, self.ambient_C, lw=0.8, color="#52514e", ls="--", label="ambient")
                ax[2].legend(frameon=False, fontsize=8)
            ax[2].set_ylabel("Temperature (°C)")
        ax[-1].set_xlabel("Time (h)" if hours else "Time (min)")
        for a in ax:
            a.grid(color="#e1e0d9", lw=0.6)
            a.spines[["top", "right"]].set_visible(False)
        ax[0].set_title(
            f"{self.source or 'Test record'}  (shaded: blue pulses, green constant current, orange dynamic)",
            fontsize=9,
            loc="left",
        )
        fig.tight_layout()
        out = Path(path)
        fig.savefig(out, dpi=dpi)
        plt.close(fig)
        return out


def _hms(s: float) -> str:
    h, rem = divmod(round(s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min {sec:02d} s"


def gap_threshold(t: np.ndarray) -> float:
    """A time step longer than this is a gap in the record (10 median steps, and at least 60 s)."""
    return max(10.0 * float(np.median(np.diff(t))), 60.0) if t.size > 1 else math.inf


def interval_charge_Ah(t: np.ndarray, current: np.ndarray, counter: np.ndarray | None = None) -> np.ndarray:
    """Charge discharged over each sample interval (Ah).

    Within the logged record, the trapezium rule. Two kinds of interval it
    cannot see into, and where the tester's charge counter, if the file has
    one, says what moved instead:

    - a gap, where nothing is logged (without a counter, nothing is counted);
    - a step, where the current changes between two samples: when in the
      interval it changed is unknown, and with sparse logging (a sample every
      few minutes in a rest) averaging the two ends can be far off.
    """
    dt = np.diff(t)
    dq = 0.5 * (current[1:] + current[:-1]) * dt / 3600.0
    gap = dt > gap_threshold(t)
    if counter is None:
        dq[gap] = 0.0
        return dq
    dc = np.diff(counter)
    use = gap | _steps(current)
    dq[use] = dc[use]
    return dq


def _steps(current: np.ndarray) -> np.ndarray:
    """Intervals across which the current changes by more than noise."""
    return np.abs(np.diff(current)) > _threshold(current)


UNLOGGED_AH = 1e-3  # a gap across which the counter moved more than this hid some current


# -- labelling ---------------------------------------------------------------


def _threshold(current: np.ndarray) -> float:
    """Below this, current is noise: 0.5 % of the largest current, and at least 5 mA."""
    peak = float(np.max(np.abs(current))) if current.size else 0.0
    return max(0.005, 0.005 * peak)


def label_segments(
    t: np.ndarray, current: np.ndarray, voltage: np.ndarray, counter: np.ndarray | None = None
) -> list[Segment]:
    """Split a record into rests, pulses, constant-current steps, CC-CV charges and dynamic stretches.

    With the tester's charge counter, a gap across which charge moved is an
    ``unlogged`` part of its own: its charge is known, but not how it flowed.
    """
    segs = _label(t, current, voltage, counter)
    if counter is None or t.size < 2:
        return segs
    dt = np.diff(t)
    hidden = np.flatnonzero((dt > gap_threshold(t)) & (np.abs(np.diff(counter)) > UNLOGGED_AH))
    if hidden.size == 0:
        return segs
    dq = interval_charge_Ah(t, current, counter)
    out: list[Segment] = []
    for sg in segs:
        # A segment owns the intervals from each of its samples to the next one.
        inside = [int(g) for g in hidden if sg.start <= g < sg.stop]
        if not inside:
            out.append(sg)
            continue
        a = sg.start
        for g in inside:
            if g + 1 > a:  # the part before the gap: samples a..g, intervals a..g-1
                out.append(
                    Segment(
                        sg.kind,
                        a,
                        g + 1,
                        float(t[a]),
                        float(t[g]),
                        float(np.mean(current[a : g + 1])),
                        float(np.sum(dq[a:g])),
                    )
                )
            out.append(
                Segment(
                    "unlogged", g + 1, g + 1, float(t[g]), float(t[g + 1]), float(dq[g] * 3600.0 / dt[g]), float(dq[g])
                )
            )
            a = g + 1
        if a < sg.stop:  # the part after the last gap keeps the segment's end
            out.append(
                Segment(
                    sg.kind,
                    a,
                    sg.stop,
                    float(t[a]),
                    sg.t1,
                    float(np.mean(current[a : sg.stop])),
                    float(np.sum(dq[a : sg.stop])),
                )
            )
    return out


def _label(t: np.ndarray, current: np.ndarray, voltage: np.ndarray, counter: np.ndarray | None) -> list[Segment]:
    n = t.size
    if n == 0:
        return []
    eps = _threshold(current)
    state = np.where(current > eps, 1, np.where(current < -eps, -1, 0))
    # Runs of the same state.
    edges = np.flatnonzero(np.diff(state)) + 1
    starts = np.concatenate([[0], edges])
    stops = np.concatenate([edges, [n]])
    # Charge per sample interval, assigned to the interval's first sample.
    dq = np.concatenate([interval_charge_Ah(t, current, counter), [0.0]])

    def t_end(stop: int) -> float:
        return float(t[stop]) if stop < n else float(t[-1])

    runs = []
    for a, b in zip(starts, stops):
        runs.append((int(a), int(b), int(state[a])))

    # Sections: stretches between long rests. A section of many runs is dynamic.
    out: list[Segment] = []
    i = 0
    while i < len(runs):
        a, b, s = runs[i]
        if s == 0:
            out.append(_seg("rest", a, b, t, t_end(b), current, dq))
            i += 1
            continue
        # Gather the section: runs until a rest of SECTION_REST_S or longer.
        j = i
        while j < len(runs):
            ra, rb, rs = runs[j]
            if rs == 0 and t_end(rb) - t[ra] >= SECTION_REST_S:
                break
            j += 1
        section = runs[i:j]
        # Trailing short rests belong to the gap, not the section.
        while section and section[-1][2] == 0:
            section.pop()
            j -= 1
        active = [r for r in section if r[2] != 0]
        if len(active) >= DYNAMIC_MIN_STEPS or _varying(section, t, t_end, current):
            out.append(_seg("dynamic", section[0][0], section[-1][1], t, t_end(section[-1][1]), current, dq))
        else:
            for ra, rb, rs in section:
                if rs == 0:
                    out.append(_seg("rest", ra, rb, t, t_end(rb), current, dq))
                else:
                    out.append(
                        _seg(_steady_kind(ra, rb, rs, t, t_end, current, voltage), ra, rb, t, t_end(rb), current, dq)
                    )
        i = j
    return out


def _seg(kind: str, a: int, b: int, t: np.ndarray, t1: float, current: np.ndarray, dq: np.ndarray) -> Segment:
    return Segment(
        kind=kind,
        start=a,
        stop=b,
        t0=float(t[a]),
        t1=t1,
        current_A=float(np.mean(current[a:b])),
        charge_Ah=float(np.sum(dq[a:b])),
    )


def _varying(section, t, t_end, current) -> bool:
    """A section whose current runs vary within themselves (a drive cycle's fine detail)."""
    for a, b, s in section:
        if s == 0 or b - a < 5:
            continue
        x = np.abs(current[a:b])
        core = x[len(x) // 10 : len(x) - len(x) // 10] if len(x) >= 20 else x
        if core.size and np.std(core) > 0.15 * np.mean(core) and t_end(b) - t[a] > PULSE_MAX_S:
            # Not a CC-CV taper: those fall smoothly, a drive cycle jumps about.
            d = np.diff(core)
            if np.mean(np.abs(d)) > 3 * abs(np.mean(d)) + 1e-12:
                return True
    return False


def _steady_kind(a, b, s, t, t_end, current, voltage) -> str:
    dur = t_end(b) - t[a]
    if dur <= PULSE_MAX_S:
        return "pulse"
    if s < 0:  # a charge: does it taper at constant voltage?
        x = np.abs(current[a:b])
        head = np.median(x[: max(3, len(x) // 5)])
        tail = np.median(x[-max(3, len(x) // 10) :])
        v_tail = voltage[a:b][-max(3, len(x) // 10) :]
        if tail < 0.7 * head and np.ptp(v_tail) < 0.02:
            return "cc-cv"
    return "constant"


# -- reading -----------------------------------------------------------------


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).strip().lower())


def _unit_of(name: str) -> str | None:
    n = _norm(name)
    m = _UNIT.search(n)
    if m:
        return m.group(1).lower().replace("°c", "degc")
    # Kollmeyer style: Battery_Temp_degC; "_mA" endings
    for u in ("degc", "ma", "mv", "ms"):
        if n.endswith("_" + u):
            return u
    return None


def find_columns(names: list[str]) -> dict[str, str]:
    """Which column is time, current, voltage, temperature, ambient (those found)."""
    found: dict[str, str] = {}
    used: set[str] = set()
    for role, patterns in COLUMN_PATTERNS.items():
        for pat in patterns:
            hit = next((c for c in names if c not in used and re.search(pat, _norm(c))), None)
            if hit is not None:
                found[role] = hit
                used.add(hit)
                break
    return found


def _scale(role: str, unit: str | None, values: np.ndarray, conversions: list[str], col: str) -> np.ndarray:
    mah = {"mah": 1e-3, "ma.h": 1e-3}
    factor = {
        "time": {"ms": 1e-3, "min": 60.0, "h": 3600.0, "hr": 3600.0},
        "current": {"ma": 1e-3},
        "voltage": {"mv": 1e-3},
        "charge": mah,
        "charge_in": mah,
        "charge_out": mah,
    }
    f = factor.get(role, {}).get(unit or "")
    if f:
        conversions.append(f"{role} from {unit} ({col!r})")
        return values * f
    if role == "temperature" and unit == "k":
        conversions.append(f"{role} from kelvin ({col!r})")
        return values - 273.15
    return values


def _from_columns(
    data: dict[str, np.ndarray],
    names: list[str],
    columns: dict[str, str] | None,
    source: str,
) -> TestRecord:
    cols = find_columns(names)
    if columns:
        for role, col in columns.items():
            if role not in COLUMN_PATTERNS:
                raise TestDataError(f"unknown column role {role!r} (choose from {', '.join(COLUMN_PATTERNS)})")
            if col not in data:
                raise TestDataError(f"{source}: no column {col!r} (columns: {', '.join(map(repr, names))})")
            # A column named for one role is no longer a guess for another.
            cols = {r: c for r, c in cols.items() if c != col}
            cols[role] = col
    missing = [r for r in ("time", "current", "voltage") if r not in cols]
    if missing:
        raise TestDataError(
            f"{source}: could not find the {', '.join(missing)} column{'s' if len(missing) > 1 else ''}. "
            f"Columns: {', '.join(map(repr, names))}. Name them, e.g. --{missing[0]} '<column>'."
        )
    conversions: list[str] = []
    arrays = {}
    for role, col in cols.items():
        v = np.asarray(data[col])
        if v.dtype.kind in "OUS":
            if role == "time":
                v = _time_from_text(v, col, conversions)
            else:
                v = np.asarray(_to_float(v), dtype=float)
        arrays[role] = _scale(role, _unit_of(col), v.astype(float), conversions, col)
    return _clean(arrays, cols, conversions, source)


def _to_float(v):
    out = []
    for x in v:
        try:
            out.append(float(x))
        except (TypeError, ValueError):
            out.append(math.nan)
    return out


def _time_from_text(v: np.ndarray, col: str, conversions: list[str]) -> np.ndarray:
    """Time given as text: numbers, h:mm:ss durations, or dates."""
    import pandas as pd

    s = pd.Series(v).astype(str).str.strip()
    num = pd.to_numeric(s, errors="coerce")
    if num.notna().mean() > 0.99:
        return num.to_numpy(float)
    if s.str.match(r"^\d+:\d{1,2}:\d{1,2}(\.\d+)?$").mean() > 0.99:
        td = pd.to_timedelta(s, errors="coerce")
        conversions.append(f"time from h:mm:ss ({col!r})")
        return td.dt.total_seconds().to_numpy(float)
    dt = pd.to_datetime(s, errors="coerce", format="mixed")
    if dt.notna().mean() > 0.99:
        conversions.append(f"time from dates and times ({col!r})")
        return (dt - dt.iloc[0]).dt.total_seconds().to_numpy(float)
    raise TestDataError(f"cannot read the time column {col!r}: it is neither numbers, durations nor dates")


def _clean(arrays: dict[str, np.ndarray], cols: dict[str, str], conversions: list[str], source: str) -> TestRecord:
    warnings: list[str] = []
    n0 = arrays["time"].size
    ok = np.isfinite(arrays["time"]) & np.isfinite(arrays["current"]) & np.isfinite(arrays["voltage"])
    if (~ok).sum():
        warnings.append(f"{int((~ok).sum())} of {n0} rows dropped: missing time, current or voltage")
    arrays = {k: v[ok] for k, v in arrays.items()}
    t = arrays["time"]
    if t.size < 2:
        raise TestDataError(f"{source}: fewer than two usable rows")
    # Time must increase: keep each row later than every row before it (drops
    # repeated rows, and rows after a logger's clock steps back).
    prev_max = np.maximum.accumulate(np.concatenate([[-np.inf], t[:-1]]))
    keep = t > prev_max
    back = int((np.diff(t) < 0).sum())
    dropped = int((~keep).sum())
    if back:
        warnings.append(
            f"time runs backwards {back} time{'s' if back > 1 else ''}; {dropped} rows not later than an earlier one were dropped"
        )
    elif dropped:
        warnings.append(f"{dropped} rows with a repeated time were dropped")
    arrays = {k: v[keep] for k, v in arrays.items()}
    t = arrays["time"] - arrays["time"][0]
    I = arrays["current"]
    V = arrays["voltage"]

    # Units the names did not give: judge by the values.
    if not any(c.startswith("voltage") for c in conversions) and np.nanmedian(V) > 100:
        V = V * 1e-3
        conversions.append("voltage from mV (values in the thousands)")
    if not any(c.startswith("current") for c in conversions) and np.nanmax(np.abs(I)) > 1000:
        I = I * 1e-3
        conversions.append("current from mA (values over 1000)")
    if not (0.5 < np.nanmedian(V) < 6.0):
        warnings.append(f"median voltage {np.nanmedian(V):.3g} V is not a single cell's: is this a module or pack?")

    sign, evidence = current_sign(t, I, V)
    if sign < 0:
        I = -I
        conversions.append(f"current sign flipped to + = discharge ({evidence})")
    elif sign == 0 and np.max(np.abs(I)) > _threshold(I) and np.max(np.abs(I)) > 0.005:
        warnings.append(f"could not tell the current's sign from the voltage ({evidence}); taken as + = discharge")

    dt = np.diff(t)
    med = float(np.median(dt))
    gaps = np.flatnonzero(dt > gap_threshold(t))
    counter = _counter(arrays, t, I, gaps, warnings)
    if gaps.size:
        worst = float(dt[gaps].max())
        warnings.append(
            f"{gaps.size} gap{'s' if gaps.size > 1 else ''} in the record (longest {_hms(worst)} at "
            f"{_hms(float(t[gaps[np.argmax(dt[gaps])]]))}): no current is logged across them"
        )
        if counter is not None:
            moved = np.abs(np.diff(counter)[gaps])
            hidden = moved > UNLOGGED_AH
            if hidden.any():
                warnings.append(
                    f"the tester's charge counter shows {moved[hidden].sum():.3f} Ah moved during {int(hidden.sum())} of "
                    "those gaps, current the record does not log: it is counted, as unlogged parts"
                )
        else:
            jump = np.abs(V[gaps + 1] - V[gaps])
            moved = jump > 0.02
            if moved.any():
                warnings.append(
                    f"the voltage changed by up to {jump.max() * 1e3:.0f} mV across {int(moved.sum())} of those gaps: "
                    "current probably flowed that the record does not log, and there is no charge counter "
                    "(Ah or capacity column) to count it"
                )
    if med > 10:
        warnings.append(f"median time step {med:.0f} s is coarse for pulse tests (1 s or finer is usual)")

    rec = TestRecord(
        t=t,
        current_A=I,
        voltage_V=V,
        temperature_C=arrays.get("temperature"),
        ambient_C=arrays.get("ambient"),
        counter_Ah=counter,
        source=source,
        columns=dict(cols),
        conversions=conversions,
        warnings=warnings,
    )
    if rec.temperature_C is not None and np.isfinite(rec.temperature_C).any():
        T = rec.temperature_C[np.isfinite(rec.temperature_C)]
        if T.max() > 120 or T.min() < -60:
            warnings.append(
                f"cell temperature {T.min():.0f} to {T.max():.0f}: not degC? (kelvin is converted if the column says K)"
            )
    return rec


def _counter(arrays: dict, t: np.ndarray, I: np.ndarray, gaps: np.ndarray, warnings: list[str]) -> np.ndarray | None:
    """The tester's charge counter as Ah discharged since the start (+ = discharge), or None.

    Testers count either way round, and some keep charge and discharge apart
    (Arbin's Charge_Capacity and Discharge_Capacity): the direction is taken
    from the logged current, over the intervals that are not gaps.
    """
    if "charge" in arrays:
        c = np.asarray(arrays["charge"], float)
    elif "charge_out" in arrays and "charge_in" in arrays:
        c = np.asarray(arrays["charge_out"], float) - np.asarray(arrays["charge_in"], float)
    else:
        return None
    if not np.all(np.isfinite(c)):
        warnings.append("the charge counter has missing values; it is not used")
        return None
    dt = np.diff(t)
    logged = np.ones(dt.size, bool)
    logged[gaps] = False
    logged[_steps(I)] = False  # the current's own charge is unclear across a step; compare where it is clear
    dq = 0.5 * (I[1:] + I[:-1]) * dt / 3600.0
    dc = np.diff(c)
    q_logged, c_logged = float(np.sum(np.abs(dq[logged]))), float(np.sum(np.abs(dc[logged])))
    if q_logged < 1e-6 or c_logged < 1e-6:
        return None  # nothing moved while logged: no way to orient it, and nothing to fill
    if float(np.dot(dc[logged], dq[logged])) < 0:
        c = -c
    ratio = c_logged / q_logged
    if abs(ratio - 1) > 0.1:
        warnings.append(
            f"the charge counter and the logged current disagree by {100 * (ratio - 1):+.0f}% over the logged parts; "
            "the counter is used only across gaps and steps"
        )
    return c - c[0]


def current_sign(t: np.ndarray, current: np.ndarray, voltage: np.ndarray) -> tuple[int, str]:
    """+1 if the data's current is + = discharge, -1 if + = charge, 0 if unclear; with the evidence.

    Three kinds of evidence, each a vote on what positive current does:

    - a step from rest into current: the voltage falls at once on discharge;
    - a step from current to rest: the voltage recovers (rises) after discharge;
    - a long steady current: the voltage drifts down through a discharge.

    The sign agreeing with at least 80 % of the votes wins. First, though, the
    instant response: in a finely logged record (2 s or less between samples),
    every jump in current moves the voltage at once, down for more discharge.
    With 20 or more jumps and 90 % of them agreeing, that decides it; it is the
    clearest sign in a drive cycle, where the cell never settles between steps.
    """
    eps = _threshold(current)
    dI, dV, dt = np.diff(current), np.diff(voltage), np.diff(t)
    jump = (np.abs(dI) > max(0.05, 0.02 * float(np.max(np.abs(current))))) & (dt <= 2.0) & (dV != 0)
    if jump.sum() >= 20:
        same = float(np.mean(np.sign(dI[jump]) == np.sign(dV[jump])))
        if same >= 0.9:  # more current, higher voltage: positive current charges
            return -1, f"voltage rose with the current at {same:.0%} of {int(jump.sum())} jumps"
        if same <= 0.1:
            return 1, f"voltage fell as the current rose at {1 - same:.0%} of {int(jump.sum())} jumps"
    on = np.abs(current) > eps
    n = current.size
    votes: list[float] = []
    kinds = {"start": 0, "end": 0, "drift": 0}

    def at(i: int, dt: float) -> int:
        return int(min(max(np.searchsorted(t, t[i] + dt), 0), n - 1))

    for i in np.flatnonzero(on[1:] & ~on[:-1]) + 1:  # rest -> current
        j = max(at(i, 2.0), i + 1) if i + 1 < n else i
        dv = voltage[j] - voltage[i - 1]
        if abs(dv) >= 1e-4:
            votes.append(-np.sign(dv) * np.sign(current[i]))
            kinds["start"] += 1
    for i in np.flatnonzero(on[:-1] & ~on[1:]) + 1:  # current -> rest, i is the first rest sample
        j = at(i, 2.0)
        dv = voltage[j] - voltage[i - 1]
        if abs(dv) >= 1e-4 and j > i - 1:
            votes.append(np.sign(dv) * np.sign(current[i - 1]))
            kinds["end"] += 1
    # Long steady stretches: the voltage drift over the middle of the stretch.
    state = np.where(current > eps, 1, np.where(current < -eps, -1, 0))
    edges = np.flatnonzero(np.diff(state)) + 1
    for a, b in zip(np.concatenate([[0], edges]), np.concatenate([edges, [n]])):
        if state[a] == 0 or t[b - 1] - t[a] < 300:
            continue
        x = current[a:b]
        if np.std(x) > 0.05 * abs(np.mean(x)):
            continue  # not steady (a CV taper or a drive cycle): no clean drift
        lo, hi = a + (b - a) // 4, a + 3 * (b - a) // 4
        dv = voltage[hi] - voltage[lo]
        if abs(dv) >= 1e-3:
            votes.append(-np.sign(dv) * np.sign(np.mean(x)))
            kinds["drift"] += 1
    if not votes:
        return 0, "no steps from rest, no long steady current"
    v = np.asarray(votes)
    agree = int((v > 0).sum())
    names = {"start": "current starting", "end": "current stopping", "drift": "steady current"}
    what = ", ".join(f"{c} {names[k]}" for k, c in kinds.items() if c)
    if agree >= 0.8 * v.size:
        return 1, f"the voltage agreed at {agree} of {v.size} checks: {what}"
    if agree <= 0.2 * v.size:
        return -1, f"the voltage agreed at {v.size - agree} of {v.size} checks: {what}"
    return 0, f"the voltage agreed one way at only {max(agree, v.size - agree)} of {v.size} checks: {what}"


def read_csv(path: str | Path, columns: dict[str, str] | None = None) -> TestRecord:
    import pandas as pd

    p = Path(path)
    try:
        df = pd.read_csv(p, sep=None, engine="python")
    except (pd.errors.ParserError, UnicodeDecodeError) as e:
        raise TestDataError(f"{p.name}: cannot read as CSV ({e})") from None
    if df.shape[1] < 3:
        raise TestDataError(f"{p.name}: only {df.shape[1]} column(s); a test needs time, current and voltage")
    data = {c: df[c].to_numpy() for c in df.columns}
    return _from_columns(data, [str(c) for c in df.columns], columns, p.name)


def read_mat(path: str | Path, columns: dict[str, str] | None = None) -> TestRecord:
    """A MATLAB file: the Kollmeyer ``meas`` structure, or top-level vectors with recognisable names."""
    import scipy.io as sio

    p = Path(path)
    try:
        raw = sio.loadmat(str(p), squeeze_me=True, struct_as_record=False)
    except (ValueError, NotImplementedError) as e:  # NotImplementedError: v7.3 (HDF5) files
        raise TestDataError(f"{p.name}: cannot read this MATLAB file ({e}); save it with -v7 or as CSV") from None
    data: dict[str, np.ndarray] = {}
    longest = 0
    for k, v in raw.items():
        if k.startswith("__"):
            continue
        if hasattr(v, "_fieldnames"):  # a struct, such as Kollmeyer's meas
            for f in v._fieldnames:
                x = np.atleast_1d(getattr(v, f))
                longest = max(longest, x.size)
                if x.ndim == 1 and x.size > 1:
                    data[f] = x
        else:
            x = np.atleast_1d(v)
            if x.ndim == 1 and x.size > 1:
                data[k] = x
            elif x.ndim == 2 and min(x.shape) == 1:
                data[k] = x.ravel()
    sizes = {v.size for v in data.values()}
    if not data:
        if longest == 1:
            raise TestDataError(f"{p.name}: holds a single sample, not a test")
        raise TestDataError(f"{p.name}: no vectors found in this MATLAB file")
    if len(sizes) > 1:  # keep the vectors of the most common length
        common = max(sizes, key=lambda s: sum(v.size == s for v in data.values()))
        data = {k: v for k, v in data.items() if v.size == common}
    # Kollmeyer's TimeStamp is a date string; its Time is seconds: prefer Time.
    names = sorted(data, key=lambda k: (k != "Time", k))
    return _from_columns(data, names, columns, p.name)


def load_test_data(
    path: str | Path,
    columns: dict[str, str] | None = None,
    capacity_Ah: float | None = None,
) -> TestRecord:
    """Read a cell test from CSV/TSV or a MATLAB file; columns found by name unless given."""
    p = Path(path)
    if not p.is_file():
        raise TestDataError(f"file not found: {p}")
    suffix = p.suffix.lower()
    if suffix in (".gz", ".bz2", ".xz", ".zip") and len(p.suffixes) >= 2:
        suffix = p.suffixes[-2].lower()  # a compressed CSV: read through its compression
    if suffix == ".mat":
        rec = read_mat(p, columns)
    elif suffix in (".csv", ".tsv", ".txt"):
        rec = read_csv(p, columns)
    elif suffix in (".xlsx", ".xls"):
        raise TestDataError(f"{p.name}: Excel files are not read yet; save the sheet as CSV")
    else:
        raise TestDataError(f"{p.name}: unknown file type {suffix!r} (CSV, TSV or .mat, or a compressed CSV)")
    rec.capacity_Ah = capacity_Ah
    if capacity_Ah:
        q = rec.charge_Ah()
        swing = float(q.max() - q.min())
        if swing > 1.1 * capacity_Ah:
            rec.warnings.append(
                f"the record moves {swing:.2f} Ah in one direction, more than the cell's {capacity_Ah:g} Ah: "
                "charges (or discharges) between its parts are probably in another file"
            )
    return rec


__all__ = [
    "Segment",
    "TestDataError",
    "TestRecord",
    "current_sign",
    "find_columns",
    "label_segments",
    "load_test_data",
    "read_csv",
    "read_mat",
]
