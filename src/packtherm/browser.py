"""PackTherm in the browser: the web app's engine when there is no server.

The web app runs this module under Pyodide (Python compiled to WebAssembly),
in several Web Workers at once. Every function takes and returns JSON text, so
the JavaScript side passes strings and never has to understand the numbers.

A study runs in steps that JavaScript schedules across the workers:

1. ``check_study(doc)``: validate it and count its designs.
2. ``evaluate(doc, i)`` for each design, in any worker, in any order.
3. ``finish(doc, rows, rechecks, elapsed_s)`` with every design's row. It
   either returns the results document, or asks for designs to be re-checked
   at worst-case resistance (``{"need": [i, ...]}``); JavaScript runs
   ``evaluate(doc, i, worst=True)`` for those and calls ``finish`` again with
   the re-checks added. The answer is the same as run_module_study's, since
   both end in module_study_result.

Rows cross between workers as JSON text written by Python's json module,
which round-trips floats exactly (NaN included), so the results document is
identical to the one ``packtherm run`` writes for the same study.
"""

from __future__ import annotations

import json
import math

_built: dict[str, tuple] = {}  # study JSON -> (spec, study, designs); one study at a time per worker


def _plain(x):
    """numpy scalars to Python ones, for json.dumps."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        raise TypeError(type(x)) from None
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return float(x)
    raise TypeError(f"not JSON serialisable: {type(x).__name__}")


def _dump(obj) -> str:
    return json.dumps(obj, default=_plain)


def _error(message: str, errors: list[str] | None = None) -> str:
    return _dump({"ok": False, "error": message, "errors": errors or []})


def _clean(obj):
    """NaN and infinity to None, as the API sends them (JSON has no NaN)."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def _build(doc_json: str):
    if doc_json not in _built:
        from .study import StudySpec, validate

        spec = StudySpec(validate(json.loads(doc_json)))
        study = spec.build()
        _built.clear()
        _built[doc_json] = (spec, study, study.designs())
    return _built[doc_json]


def version() -> str:
    from . import __version__

    return __version__


def library() -> str:
    """The cell library, as GET /cells gives it."""
    from .cells import library_summary

    return _dump(library_summary())


def check_cell(cell_json: str) -> str:
    """A user-defined cell checked, as POST /cells/check gives it."""
    from .user_cells import CellError, cell_summary, validate_cell

    try:
        spec, warnings = validate_cell(json.loads(cell_json), "")
    except CellError as e:
        lines = str(e).splitlines()
        return _error(lines[0].rstrip(":"), [x.strip() for x in lines[1:]])
    except ValueError as e:
        return _error(str(e))
    return _dump({"ok": True, "cell": spec, "derived": _clean(cell_summary(spec)), "warnings": warnings})


def check_study(doc_json: str) -> str:
    """A study validated and its designs counted, as POST /studies/check gives it (no limits here)."""
    from .study import StudyError

    try:
        _spec, study, designs = _build(doc_json)
        if _spec.is_search or _spec.is_sensitivity:
            what = "Search" if _spec.is_search else "Sensitivity"
            return _error(f"{what} runs from the command line (packtherm run), not in the browser yet.")
    except StudyError as e:
        lines = str(e).splitlines()
        return _error("Invalid study", [x.strip() for x in lines[1:]] or [str(e)])
    except (ValueError, TypeError) as e:
        return _error(str(e))
    return _dump({"ok": True, "designs": len(designs), "mode": study.mode, "within_limits": True, "problems": []})


def evaluate(doc_json: str, i: int, worst: bool = False) -> str:
    """One design's row: at nominal resistance, or re-checked at worst case."""
    from .module_design import _eval_args, recheck_args

    _spec, study, designs = _build(doc_json)
    args = recheck_args(study, designs[i]) if worst else (study, designs[i])
    return _dump(_eval_args(args))


class _NeedRecheck(Exception):
    def __init__(self, idx):
        self.idx = [int(i) for i in idx]


def finish(doc_json: str, rows_json, rechecks_json, elapsed_s: float) -> str:
    """The results document, or {"need": [...]} for designs to re-check first.

    rows_json: every design's row (JSON text), in design order.
    rechecks_json: re-checked rows so far, keyed by design index (as text or number).
    Either may also arrive as one JSON text (the web app sends them that way).
    """
    if isinstance(rows_json, str):
        rows_json = json.loads(rows_json)
    if isinstance(rechecks_json, str):
        rechecks_json = json.loads(rechecks_json)
    from .module_design import module_study_result
    from .study import StudyRun

    spec, study, designs = _build(doc_json)
    if len(rows_json) != len(designs):
        return _error(f"expected {len(designs)} designs, got {len(rows_json)}")
    rows = [json.loads(r) for r in rows_json]
    done = {int(k): json.loads(v) for k, v in dict(rechecks_json).items()}

    def recheck(idx):
        missing = [i for i in idx if int(i) not in done]
        if missing:
            raise _NeedRecheck(missing)
        return [done[int(i)] for i in idx]

    try:
        result = module_study_result(study, rows, recheck)
    except _NeedRecheck as e:
        return _dump({"ok": True, "need": e.idx})
    doc = StudyRun(spec, study, result, float(elapsed_s)).to_json()
    return json.dumps({"ok": True, "results": doc}, allow_nan=False, default=_plain)


__all__ = ["check_cell", "check_study", "evaluate", "finish", "library", "version"]
