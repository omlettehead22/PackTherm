"""The in-browser engine (packtherm.browser), driven as the web app drives it, gives packtherm run's results."""

import json

import pytest

from packtherm import browser
from packtherm.study import StudySpec, validate

STUDY = {
    "packtherm_study": 1,
    "cell": "M50",
    "mode": "fast",
    "ambient_C": 25,
    "duty": {"type": "constant", "c_rate": 0.8, "rest_h": 1},  # robust picks with the M50's measured resistance (v0.6.9)
    "design_space": {
        "topologies": ["air", "ribbon"],
        "fillers": ["none", "RT31"],
        "air_flows_g_s": [0.3],
        "coolant_flows_g_s": [0.03],
        "chiller_C": [],
    },
}


def drive(doc: dict) -> dict:
    """What the web app's workers do: check, evaluate every design (here in reverse order), finish."""
    text = json.dumps(doc)
    check = json.loads(browser.check_study(text))
    assert check["ok"], check
    rows = [None] * check["designs"]
    for i in reversed(range(check["designs"])):
        rows[i] = browser.evaluate(text, i)
    rechecks, rounds = {}, 0
    while True:
        # As the web app sends them: both as JSON text.
        out = json.loads(browser.finish(text, json.dumps(rows), json.dumps(rechecks), 1.0))
        assert out["ok"], out
        if "results" in out:
            return out["results"], rounds
        rounds += 1
        assert out["need"] and not set(out["need"]) & {int(k) for k in rechecks}
        for i in out["need"]:
            rechecks[str(i)] = browser.evaluate(text, i, worst=True)


def strip(doc):
    return {k: v for k, v in doc.items() if k not in ("created", "elapsed_s")}


@pytest.fixture(scope="module")
def both():
    native = StudySpec(validate(STUDY)).run(workers=1).to_json()
    native = json.loads(json.dumps(native))  # as it arrives over HTTP
    in_browser, rounds = drive(STUDY)
    return native, in_browser, rounds


def test_same_results_as_packtherm_run(both):
    native, in_browser, rounds = both
    assert strip(in_browser) == strip(native)
    assert rounds >= 1  # the worst-case re-check went through the ask-and-answer loop
    assert any(p.get("robust") is not None for p in in_browser["picks"])


def test_results_are_strict_json(both):
    _, in_browser, _ = both
    json.dumps(in_browser, allow_nan=False)


def test_library_and_cell_check_match_the_api():
    from fastapi.testclient import TestClient

    from packtherm.api import Settings, create_app

    api = TestClient(create_app(Settings(), start_scheduler=False))
    assert json.loads(browser.library()) == api.get("/cells").json()
    cell = {"name": "X", "format": "21700", "chemistry": "NMC", "capacity_Ah": 5, "V_nominal": 3.6, "mass_g": 69,
            "DCIR_mOhm": 22}
    mine = json.loads(browser.check_cell(json.dumps(cell)))
    assert mine.pop("ok") and mine == api.post("/cells/check", json=cell).json()
    bad = json.loads(browser.check_cell(json.dumps({**cell, "mass_g": 0.069})))
    assert not bad["ok"] and any("mass_g" in e for e in bad["errors"])


def test_invalid_study_is_reported_not_raised():
    out = json.loads(browser.check_study(json.dumps({**STUDY, "duty": {"type": "constant", "c_rate": -1}})))
    assert not out["ok"] and any("c_rate" in e for e in out["errors"])
    assert browser.version()
