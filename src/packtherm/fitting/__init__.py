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

# Imported when first used (PEP 562): the cell library reads a fitted cell file through
# ``cellfile`` at import, and need not load the fitting itself (scipy.optimize) for that.
_WHERE = {
    "FittedCellError": "cellfile",
    "fitted_cell_doc": "cellfile",
    "read_fitted_cell": "cellfile",
    "write_fitted_cell": "cellfile",
    "CircuitModel": "circuit",
    "FitResult": "circuit",
    "fit_cell": "circuit",
    "OCVCurve": "ocv",
    "ocv_from_slow_test": "ocv",
    "write_report": "report",
    "track_soc": "soc",
}

__all__ = [  # provided by __getattr__
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


def __getattr__(name: str):
    if name in _WHERE:
        from importlib import import_module

        return getattr(import_module(f".{_WHERE[name]}", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
