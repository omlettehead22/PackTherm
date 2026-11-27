"""The state of charge through a test.

Anchored at a settled rest, where the voltage is the open-circuit voltage and
so gives the state of charge, then carried through the test by the charge
counted (``TestRecord.charge_Ah``, which includes what moved while logging
paused). This works for any tester: it does not rely on how a tester's own
charge counter is zeroed. With open-circuit curves by temperature, the curve at
the cell's temperature there reads it.
"""

from __future__ import annotations

import numpy as np

from ..testdata import TestRecord
from .ocv import OCVCurve

SETTLED_S = 20 * 60  # a rest this long counts as settled


def track_soc(rec: TestRecord, ocv: OCVCurve, capacity_Ah: float, soc0: float | None = None) -> tuple[np.ndarray, str]:
    """SOC at every sample, and how it was anchored (in words).

    soc0: the state of charge at the first sample, if known (a test started
    straight after a full charge, say). Otherwise a rest in the test anchors it.
    """
    q = rec.charge_Ah()
    if soc0 is not None:
        return soc0 - (q - q[0]) / capacity_Ah, f"{soc0:.1%} at the start, as given"
    rests = [s for s in rec.segments() if s.kind == "rest" and s.stop - s.start >= 2]
    if not rests and abs(float(rec.current_A[0])) < 0.05 * capacity_Ah:
        # Starts at (almost) no current but never rests: the first voltage is the best there is.
        soc_0 = ocv.soc_at(float(rec.voltage_V[0]), _T_K(rec, 0))
        how = (
            f"{soc_0:.1%} from the first voltage: the test has no rest, so this is not a settled "
            "open-circuit voltage and may be off by a few percent"
        )
        return soc_0 - (q - q[0]) / capacity_Ah, how
    settled = [s for s in rests if s.duration_s >= SETTLED_S]
    if settled:
        anchor = settled[0]
        how = f"settled {anchor.duration_s / 60:.0f}-minute rest at {anchor.t1 / 3600:.2f} h"
    elif rests:
        anchor = max(rests, key=lambda s: s.duration_s)
        how = (
            f"longest rest ({anchor.duration_s / 60:.1f} min at {anchor.t1 / 3600:.2f} h), not fully settled: "
            "the state of charge may be off by a few percent"
        )
    else:
        raise ValueError(f"{rec.source}: no rest to anchor the state of charge (a settled rest of 20 min is best)")
    k = anchor.stop - 1
    soc_k = ocv.soc_at(float(rec.voltage_V[k]), _T_K(rec, k))
    soc = soc_k - (q - q[k]) / capacity_Ah
    how = f"{soc_k:.1%} from the voltage at the end of the {how}"
    return soc, how


def _T_K(rec: TestRecord, k: int) -> float | None:
    T = rec.temperature_C
    if T is None or not np.isfinite(T[k]):
        return None
    return float(T[k]) + 273.15


def start_soc_from_end(rec, capacity_Ah: float, V_max: float, tolerance_V: float = 0.02) -> float:
    """Where a test that ends full started (v0.6.17): counted back from its end, 1 less the charge it put in.

    For a check whose start is uncertain but whose end is not: a charge run to the voltage limit ends full.
    Near empty a percent of charge is hundreds of millivolts on the open-circuit curve, so a check said to
    start at 0 that really starts at 2 % (the A123's C/30 charge, after a C/30 discharge to the cut-off
    and a rest) is scored hundreds of millivolts off in its first minutes, whatever the model.
    """
    vmax = float(max(rec.voltage_V))
    if vmax < V_max - tolerance_V:
        raise ValueError(
            f"{rec.source}: start_soc 'end' needs a test that charges to the voltage limit ({V_max:.3f} V); "
            f"it reaches {vmax:.3f} V"
        )
    return float(min(max(1.0 + rec.charge_Ah()[-1] / capacity_Ah, 0.0), 1.0))
