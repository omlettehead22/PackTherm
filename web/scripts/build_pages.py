"""Build the public site: the web app with the in-browser engine, and the PackTherm wheel it loads.

    python web/scripts/build_pages.py [--base /packtherm/] [--out web/dist-pages]

The site is static files (GitHub Pages serves it): the app, built with
VITE_ENGINE=browser, and py/<the PackTherm wheel> with py/manifest.json
naming it. Each visitor's browser downloads Python (Pyodide, from its CDN)
and runs PackTherm itself.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="/packtherm/", help="the path the site is served under (default /packtherm/)")
    ap.add_argument("--out", type=Path, default=WEB / "dist-pages")
    args = ap.parse_args()
    out = args.out.resolve()

    env = {**os.environ, "VITE_ENGINE": "browser"}
    npx = "npx.cmd" if os.name == "nt" else "npx"
    subprocess.run([npx, "tsc", "--noEmit"], cwd=WEB, check=True)
    subprocess.run([npx, "vite", "build", "--base", args.base, "--outDir", str(out)], cwd=WEB, env=env, check=True)

    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "-q", "-w", tmp],
            check=True,
        )
        shutil.rmtree(ROOT / "build", ignore_errors=True)  # setuptools' scratch folder from the wheel build
        (wheel,) = Path(tmp).glob("packtherm-*.whl")
        (out / "py").mkdir(exist_ok=True)
        shutil.copy(wheel, out / "py" / wheel.name)
    (out / "py" / "manifest.json").write_text(json.dumps({"wheel": wheel.name}) + "\n", encoding="utf-8")
    # GitHub Pages: serve files as they are (no Jekyll).
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"site in {out} (served under {args.base}); engine package py/{wheel.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
