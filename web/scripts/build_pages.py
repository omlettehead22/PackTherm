"""Build the public site: the web app with the in-browser engine, and the PackTherm wheel it loads.

    python web/scripts/build_pages.py [--base /packtherm/] [--out web/dist-pages]

The site is static files (GitHub Pages serves it): the app, built with
VITE_ENGINE=browser, and py/<the PackTherm wheel> with py/manifest.json
naming it, and the pure-Python wheels it needs that Pyodide does not ship
(ht and fluids, v0.6.12). Each visitor's browser downloads Python (Pyodide, from its CDN)
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
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
BROWSER_DEPS = ("ht", "fluids")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Relative paths, so the site works wherever it is served (GitHub serves it under the
    # repository's name, /PackTherm/, with its capital letters).
    ap.add_argument("--base", default="./", help="the path the site is served under (default ./: any)")
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
        # Pure-Python dependencies Pyodide does not ship (v0.6.12): the versions installed here.
        deps = []
        for name in BROWSER_DEPS:
            spec = f"{name}=={metadata.version(name)}"
            subprocess.run(
                [sys.executable, "-m", "pip", "download", spec, "--no-deps", "--only-binary=:all:", "-q", "-d", tmp],
                check=True,
            )
            (dep,) = Path(tmp).glob(f"{name}-*.whl")
            shutil.copy(dep, out / "py" / dep.name)
            deps.append(dep.name)
    manifest = {"wheel": wheel.name, "deps": deps}
    (out / "py" / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    # GitHub Pages: serve files as they are (no Jekyll).
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"site in {out} (served under {args.base}); engine package py/{wheel.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
