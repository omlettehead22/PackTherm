"""Fitting a cell model to test data (v0.6).

The steps that do not depend on the model come first and are shared:

- ``ocv``: the open-circuit voltage curve and the capacity, from a slow test;
- ``soc``: the state of charge through any test, from a settled rest and the
  charge counted (``packtherm.testdata``).

Then a model fits its parameters to the pulses and slow steps. v0.6.1 has one:
``circuit``, the circuit model PackTherm's ECM cells run (``packtherm.ecm.ECM``).
A model is a small interface (``CellModel`` in ``circuit``): simulate a test,
list its parameters, and turn fitted values into something PackTherm can run.
A generic circuit model, with the user's choice of RC branches, can be added
alongside it and use the same steps, report and cell file.

``fit_cell`` runs it all; ``write_fitted_cell`` saves the result with where it
is valid, how certain each value is, the errors, and the source files'
fingerprints (``cellfile``); ``write_report`` makes the HTML report.
"""

from .cellfile import FittedCellError, fitted_cell_doc, read_fitted_cell, write_fitted_cell
from .circuit import CircuitModel, FitResult, fit_cell
from .ocv import OCVCurve, ocv_from_slow_test
from .report import write_report
from .soc import track_soc

__all__ = [
    "CircuitModel",
    "FitResult",
    "FittedCellError",
    "OCVCurve",
    "fit_cell",
    "fitted_cell_doc",
    "ocv_from_slow_test",
    "read_fitted_cell",
    "track_soc",
    "write_fitted_cell",
    "write_report",
]
