# From BLAST-Lite blast/utils/functions.py (rescale_soc only).
import numpy as np


def rescale_soc(soc: np.ndarray, rescaling_factor: float) -> np.ndarray:
    # Rescale an soc vector by scaling dSOC by the rescaling factor.
    # Cast inputs to ensure consistent numeric behavior
    soc = np.asarray(soc, dtype=float)
    rescaling_factor = float(rescaling_factor)
    dSOC = np.diff(soc, prepend=soc[0])
    dSOC = dSOC * rescaling_factor
    soc = np.cumsum(dSOC) + soc[0]
    if np.max(soc) > 1 or np.min(soc) < 0:
        # print('Warning: rescaled SOC is outside of the range [0, 1], modified SOC will not directly reflect inputs.')
        soc = np.maximum(0, np.minimum(1, soc)) 
    return soc
