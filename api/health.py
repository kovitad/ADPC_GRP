from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.settings import get_settings

router = APIRouter(tags=["health"])


@router.get(
    "/healthz",
    summary="Liveness check",
    openapi_extra={"x-grp-access": "public"},
)
def healthz() -> dict[str, str]:
    """Return a detail-free public liveness response."""

    return {"status": "ok"}


@router.get(
    "/readyz",
    summary="Internal readiness check",
    openapi_extra={"x-grp-access": "internal"},
)
def readyz() -> JSONResponse:
    """Report whether required local configuration files are available."""

    settings = get_settings()
    required_files = {"database_url": settings.database_url_file}
    checks = {name: Path(path).is_file() for name, path in required_files.items()}
    ready = all(checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )
