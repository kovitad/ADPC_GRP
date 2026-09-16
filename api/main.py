from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api import access, admin, ai, assessments, audit, auth, catalog, health, uploads
from api.integrations import sig
from api.settings import get_settings

settings = get_settings()

app = FastAPI(
    title="SERVIR Global Risk Platform API",
    version="0.1.0",
    docs_url="/docs" if settings.grp_env == "dev" else None,
    redoc_url=None,
)

for module in (health, auth, access, admin, catalog, uploads, assessments, ai, audit, sig):
    app.include_router(module.router, prefix="/api/v1")

if settings.grp_env == "dev":
    app.mount(
        "/",
        StaticFiles(directory=Path(__file__).resolve().parents[1] / "web", html=True),
        name="development-web",
    )
