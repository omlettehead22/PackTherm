"""The web app: its shared files are current, the API serves it, and the study check it relies on."""

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from packtherm.api import Limits, Settings, create_app

ROOT = Path(__file__).resolve().parents[1]
SMALL = {
    "packtherm_study": 1,
    "cell": "M50",
    "mode": "fast",
    "duty": {"type": "constant", "c_rate": 1.5},
    "design_space": {"topologies": ["ribbon"], "fillers": ["none"], "coolant_flows_g_s": [0.05], "chiller_C": []},
}


def _contract():
    spec = importlib.util.spec_from_file_location("export_contract", ROOT / "web" / "scripts" / "export_contract.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.contract()


def test_web_contract_files_are_current():
    """The form is built from these: regenerate with python web/scripts/export_contract.py."""
    for name, text in _contract().items():
        path = ROOT / "web" / "src" / "generated" / name
        assert path.read_text(encoding="utf-8") == text, f"{path} is out of date: run web/scripts/export_contract.py"


def client(tmp_path, web_dir=None, **limits):
    s = Settings(jobs_dir=tmp_path / "jobs", limits=Limits(**limits), web_dir=web_dir)
    return TestClient(create_app(s, start_scheduler=False))


def test_serves_the_built_app(tmp_path):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>PackTherm</title>", encoding="utf-8")
    (web / "assets" / "index-abc.js").write_text("console.log(1)", encoding="utf-8")
    (web / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    c = client(tmp_path, web)
    r = c.get("/")
    assert r.status_code == 200 and "<title>PackTherm</title>" in r.text
    assert r.headers["cache-control"] == "no-cache"
    assert c.get("/assets/index-abc.js").text == "console.log(1)"
    assert c.get("/favicon.svg").headers["content-type"] == "image/svg+xml"
    assert c.get("/health").json()["status"] == "ok"  # the API is unchanged
    assert "/" not in c.get("/openapi.json").json()["paths"]


def test_explains_when_the_app_is_not_built(tmp_path):
    c = client(tmp_path, tmp_path / "missing")
    r = c.get("/")
    assert r.status_code == 200 and "npm run build" in r.text and "/docs" in r.text


def test_study_check(tmp_path):
    c = client(tmp_path, max_designs_fast=3)
    ok = c.post("/studies/check", json=SMALL).json()
    assert ok == {"designs": 1, "mode": "fast", "within_limits": True, "problems": []}
    big = dict(SMALL, design_space={"topologies": ["ribbon"], "fillers": ["none", "RT31"], "coolant_flows_g_s": [0.02, 0.05]})
    over = c.post("/studies/check", json=big).json()
    assert not over["within_limits"] and "more than the 3 allowed in fast mode" in over["problems"][0]
    bad = c.post("/studies/check", json=dict(SMALL, duty={"type": "constant", "c_rate": -1}))
    assert bad.status_code == 422 and any("c_rate" in e for e in bad.json()["errors"])
    assert c.post("/studies/check", content=b"{").status_code == 400
    search = c.post("/studies/check", json=dict(SMALL, search={})).json()  # v0.6.14: command line only
    assert not search["within_limits"] and "command line" in search["problems"][0]
    # Checking queues nothing.
    assert c.get("/health").json()["queued"] == 0


def test_results_carry_chart_labels():
    from packtherm.study import StudySpec, validate

    doc = StudySpec(validate(SMALL)).run(workers=1).to_json()
    assert doc["labels"]["mass_axis"].startswith("Mass added per cell")
    assert set(doc["labels"]["kinds"]) == {"natural", "air", "liquid"}
    json.dumps(doc, allow_nan=False)
