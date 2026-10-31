"""Read-only HTTP API over PostgreSQL, S3 and Orthanc (stage 5; D9, D17).

All data routes live under `/api/v1` and are GET-only. Every run-derived result carries its
provenance (run id, pipeline version, QC status) [Margeta2022]. The same routes are the tools
of the AI assistant (stage 7), which therefore can only read versioned results; its own
`POST /assistant/chat` writes nothing but the conversation log.
"""

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from cochleahub import __version__
from cochleahub.api import API_PREFIX
from cochleahub.api.deps import get_session, get_store
from cochleahub.api.routers import assistant, compare, runs, specimens
from cochleahub.api.schemas import Health
from cochleahub.config import settings
from cochleahub.storage.objects import ObjectStore

app = FastAPI(
    title="CochleaHub API",
    version=__version__,
    description="Read-only access to versioned temporal-bone measurements, QC and validation. "
    "Research use only; not a clinical tool.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)

v1 = APIRouter(prefix=API_PREFIX)


@v1.get("/health", response_model=Health, tags=["health"])
def health():
    """Liveness: the process is up. Does not touch dependencies."""
    return Health(status="ok", pipeline_version=__version__)


@v1.get("/health/ready", response_model=Health, tags=["health"])
def ready(
    session: Annotated[Session, Depends(get_session)],
    store: Annotated[ObjectStore, Depends(get_store)],
):
    """Readiness: database, object store and DICOM archive are reachable."""
    checks = {}
    probes = {
        "database": lambda: session.execute(text("SELECT 1")),
        "object_store": lambda: store.client.head_bucket(Bucket=store.bucket),
        "dicom_archive": lambda: httpx.get(
            f"{settings.orthanc_url}/system", timeout=3
        ).raise_for_status(),
    }
    for name, probe in probes.items():
        try:
            probe()
            checks[name] = "ok"
        except Exception as e:  # noqa: BLE001 - any failure is reported, not raised
            checks[name] = f"{type(e).__name__}: {e}"[:200]
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return Health(status=status, pipeline_version=__version__, checks=checks)


v1.include_router(specimens.router)
v1.include_router(runs.router)
v1.include_router(compare.router)
v1.include_router(assistant.router)
app.include_router(v1)
