"""Check the in-browser engine's results file against `packtherm run` of the same study.

    python web/e2e/compare.py <browser_results.json>

The study is re-run natively from the file's own `study` block. Numbers must
agree to 1e-9 (relative); everything else exactly. The browser runs a
different build of Python and NumPy (WebAssembly), so last-digit differences
are allowed; nothing else is.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

SKIP = {"created", "elapsed_s"}


def diff(a, b, path="", out=None, worst=None):
    out = [] if out is None else out
    worst = worst if worst is not None else [0.0, ""]
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if not path and k in SKIP:
                continue
            if k not in a or k not in b:
                out.append(f"{path}.{k}: only in {'native' if k in a else 'browser'}")
            else:
                diff(a[k], b[k], f"{path}.{k}", out, worst)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: {len(a)} items native, {len(b)} in the browser")
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{i}]", out, worst)
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        rel = abs(a - b) / max(abs(a), abs(b), 1e-12)
        if rel > worst[0]:
            worst[:] = [rel, path]
        if not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12):
            out.append(f"{path}: native {a!r}, browser {b!r}")
    elif a != b:
        out.append(f"{path}: native {a!r}, browser {b!r}")
    return out, worst


def main() -> int:
    from packtherm.study import StudySpec, validate

    browser = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    native = json.loads(json.dumps(StudySpec(validate(browser["study"])).run(workers=1).to_json()))
    problems, worst = diff(native, browser)
    print(f"{len(browser['designs'])} designs; largest relative difference {worst[0]:.2e} at {worst[1] or '-'}")
    for p in problems[:40]:
        print("  " + p)
    if problems:
        print(f"{len(problems)} differences")
        return 1
    print("The in-browser results match packtherm run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
