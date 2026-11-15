"""The PackTherm HTTP API (FastAPI). Start it with ``packtherm serve``.

A study is submitted as JSON (the study-file format), queued, and run in its
own process; the client checks its status, then fetches the results. One
server process holds the queue, so run a single instance (no extra uvicorn
workers). Interactive documentation is served at /docs; docs/API.md has examples.
"""

from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from .jobs import JobManager, QueueFull
from .settings import Settings

# The web app's built files (``npm run build`` in web/ writes them here).
WEB_DIR = Path(__file__).resolve().parent.parent / "web_static"

NO_WEB_APP = """<!doctype html><html lang="en"><meta charset="utf-8"><title>PackTherm API</title>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 3rem auto; line-height: 1.5">
<h1>PackTherm API</h1>
<p>The web app is not built in this installation. Build it with <code>npm ci && npm run build</code>
in the repository's <code>web/</code> folder, or use the API directly: see <a href="/docs">/docs</a>.</p>
</body></html>"""


def _error(status: int, message: str, errors: list[str] | None = None, **extra) -> JSONResponse:
    body = {"error": message}
    if errors:
        body["errors"] = errors
    body.update(extra)
    return JSONResponse(body, status_code=status)


class RateLimiter:
    """Accepted studies per client per hour (a sliding window, in memory)."""

    def __init__(self, per_hour: int):
        self.per_hour = per_hour
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def retry_after(self, client: str, now: float | None = None) -> float | None:
        """Seconds until this client may submit again, or None if it may now."""
        now = time.time() if now is None else now
        q = self.hits[client]
        while q and now - q[0] >= 3600:
            q.popleft()
        return None if len(q) < self.per_hour else 3600 - (now - q[0])

    def record(self, client: str, now: float | None = None) -> None:
        self.hits[client].append(time.time() if now is None else now)


def create_app(settings: Settings | None = None, start_scheduler: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    manager = JobManager(settings)
    limiter = RateLimiter(settings.limits.rate_per_hour)
    lim = settings.limits

    @asynccontextmanager
    async def lifespan(_app):
        if start_scheduler:
            manager.start()
        yield
        manager.stop()

    app = FastAPI(
        title="PackTherm API",
        version=__version__,
        description="Battery thermal management design studies for cylindrical-cell packs. "
        "Submit a study (the study-file format, as JSON), check its status, then fetch the results.",
        lifespan=lifespan,
    )
    app.state.manager = manager
    app.state.limiter = limiter
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-API-Key"],
    )

    @app.middleware("http")
    async def limit_body(request: Request, call_next):
        size = request.headers.get("content-length")
        if size is not None and size.isdigit() and int(size) > lim.max_request_kB * 1024:
            return _error(413, f"request larger than {lim.max_request_kB} kB")
        return await call_next(request)

    def has_key(request: Request) -> bool:
        key = request.headers.get("x-api-key", "")
        return bool(key) and any(secrets.compare_digest(key, k) for k in settings.api_keys)

    def client_id(request: Request) -> str:
        if settings.trust_proxy and request.headers.get("x-forwarded-for"):
            return request.headers["x-forwarded-for"].split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def body_json(request: Request):
        raw = await request.body()
        if len(raw) > lim.max_request_kB * 1024:
            raise ValueError(f"request larger than {lim.max_request_kB} kB")
        import json

        try:
            return json.loads(raw or b"null")
        except ValueError as e:
            raise ValueError(f"not valid JSON: {e}") from None

    # -- information ------------------------------------------------------------
    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__, "running": manager.running(), "queued": len(manager.queue)}

    @app.get("/limits")
    def limits():
        """The limits for requests without an API key."""
        return {k: getattr(lim, k) for k in lim.__dataclass_fields__}

    @app.get("/schema")
    def schema():
        """The study format as data: types, defaults and allowed values of every key."""
        from ..study import schema as study_schema

        return study_schema()

    @app.get("/template", response_class=PlainTextResponse)
    def template():
        """The commented study template (YAML), as ``packtherm template`` prints it."""
        from ..study import TEMPLATE

        return TEMPLATE

    @app.get("/cells")
    def cells():
        from ..cells import library_summary

        return library_summary()

    @app.post("/cells/check")
    async def check_cell(request: Request):
        """Check a user-defined cell; returns it as PackTherm understands it, with any warnings."""
        from ..user_cells import CellError, cell_summary, validate_cell

        try:
            doc = await body_json(request)
            spec, warnings = validate_cell(doc, "")
        except CellError as e:
            return _error(422, str(e).splitlines()[0].rstrip(":"), [x.strip() for x in str(e).splitlines()[1:]])
        except ValueError as e:
            return _error(400, str(e))
        return {"cell": spec, "derived": cell_summary(spec), "warnings": warnings}

    # -- studies ----------------------------------------------------------------
    def examine(doc, unlimited: bool):
        """Validate a study and check it against the limits.

        Returns (spec, study, designs, error response or None, over-limit problems).
        """
        from ..study import StudyError, StudySpec, validate

        if (
            isinstance(doc, dict)
            and isinstance(doc.get("cell"), str)
            and doc["cell"].lower().endswith((".yaml", ".yml", ".json"))
        ):
            return (
                None,
                None,
                0,
                _error(422, "Invalid study", ["cell: a file name cannot be used here; give the definition inline"]),
                [],
            )
        try:
            spec = validate(doc)
        except StudyError as e:
            return (
                None,
                None,
                0,
                _error(422, "Invalid study", [x.strip() for x in str(e).splitlines()[1:]] or [str(e)]),
                [],
            )
        study = StudySpec(spec).build()
        n = len(study.designs())
        problems = []
        if not unlimited:
            cap = lim.max_designs_fast if study.mode == "fast" else lim.max_designs_normal
            if n > cap:
                problems.append(f"design_space: {n} designs, more than the {cap} allowed in {study.mode} mode")
            hours = (study.duty.event_duration() + study.duty.rest_after_s) / 3600
            if hours > lim.max_simulated_h:
                problems.append(f"duty: {hours:.1f} h simulated (event and rest), more than {lim.max_simulated_h:g} h")
            steps = spec["duty"].get("steps") or []
            if len(steps) > lim.max_steps:
                problems.append(f"duty.steps: {len(steps)} segments, more than {lim.max_steps}")
        return spec, study, n, None, problems

    @app.post("/studies/check")
    async def check_study(request: Request):
        """Validate a study without running it: the number of designs, and any limits it is over."""
        try:
            doc = await body_json(request)
        except ValueError as e:
            return _error(400, str(e))
        _spec, study, n, err, problems = examine(doc, has_key(request))
        if err:
            return err
        return {"designs": n, "mode": study.mode, "within_limits": not problems, "problems": problems}

    @app.post("/studies", status_code=202)
    async def submit(request: Request):
        """Queue a study. Returns its id and where to check on it."""
        try:
            doc = await body_json(request)
        except ValueError as e:
            return _error(400, str(e))
        unlimited = has_key(request)
        spec, study, n, err, problems = examine(doc, unlimited)
        if err:
            return err
        if problems:
            return _error(422, "Study over the limits (GET /limits)", problems)
        if not unlimited:
            client = client_id(request)
            wait = limiter.retry_after(client)
            if wait is not None:
                return JSONResponse(
                    {"error": f"rate limit: {lim.rate_per_hour} studies per hour", "retry_after_s": round(wait)},
                    status_code=429,
                    headers={"Retry-After": str(int(wait) + 1)},
                )
        try:
            job = manager.submit(spec, unlimited)
        except QueueFull:
            return _error(503, f"the queue is full ({lim.max_queued} studies waiting); try again shortly")
        if not unlimited:
            limiter.record(client_id(request))
        return {
            "id": job.id,
            "state": job.state,
            "designs": n,
            "mode": study.mode,
            "status_url": f"/studies/{job.id}",
            "results_url": f"/studies/{job.id}/results",
        }

    def find(jid: str):
        job = manager.get(jid)
        return job, (None if job else _error(404, f"no study {jid!r} (results are kept {lim.keep_h:g} h)"))

    @app.get("/studies/{jid}")
    def status(jid: str):
        job, err = find(jid)
        if err:
            return err
        doc = job.status()
        if job.state == "queued":
            doc["queue_position"] = manager.position(jid)
        return doc

    def output(jid: str, kind: str, media: str):
        job, err = find(jid)
        if err:
            return err
        if job.state != "done":
            return _error(409, f"the study is {job.state}, not done", state=job.state)
        files = job.status()["files"] or {}
        return FileResponse(job.dir / files[kind], media_type=media, filename=files[kind])

    @app.get("/studies/{jid}/results")
    def results(jid: str):
        """The results document (the same JSON ``packtherm run`` writes)."""
        return output(jid, "json", "application/json")

    @app.get("/studies/{jid}/designs.csv")
    def designs_csv(jid: str):
        return output(jid, "csv", "text/csv")

    @app.get("/studies/{jid}/chart.png")
    def chart(jid: str):
        return output(jid, "chart", "image/png")

    @app.delete("/studies/{jid}")
    def cancel(jid: str):
        """Cancel a queued or running study, or delete a finished one and its results."""
        _, err = find(jid)
        if err:
            return err
        return {"id": jid, "result": manager.cancel_or_delete(jid)}

    # -- the web app --------------------------------------------------------------
    web_dir = settings.web_dir if settings.web_dir is not None else WEB_DIR
    index = web_dir / "index.html"
    if (web_dir / "assets").is_dir():
        # Hashed file names, so they can be cached for good.
        app.mount("/assets", StaticFiles(directory=web_dir / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def web_app():
        if index.is_file():
            return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})
        return HTMLResponse(NO_WEB_APP)

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        icon = web_dir / "favicon.svg"
        return FileResponse(icon, media_type="image/svg+xml") if icon.is_file() else _error(404, "no icon")

    return app
