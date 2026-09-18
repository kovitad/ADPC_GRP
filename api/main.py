from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from api import (
    access,
    admin,
    ai,
    assessments,
    audit,
    auth,
    catalog,
    data_inspector,
    health,
    maps,
    planning,
    platform,
    uploads,
)
from api.errors import register_error_handlers
from api.integrations import sig
from api.settings import get_settings

settings = get_settings()

app = FastAPI(
    title="SERVIR Global Risk Platform API",
    version="0.1.0",
    docs_url="/docs" if settings.grp_env == "dev" else None,
    redoc_url=None,
)
register_error_handlers(app)

for module in (
    health, auth, access, admin, platform, planning, maps, catalog,
    uploads, assessments, ai, audit, sig, data_inspector,
):
    app.include_router(module.router, prefix="/api/v1")


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
def admin_login() -> RedirectResponse:
    return RedirectResponse(url="/admin-login.html", status_code=303)

if settings.grp_env == "dev":

    @app.middleware("http")
    async def no_stale_web_files(request, call_next):
        """Local development: always revalidate pages and scripts so edits show at once."""

        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount(
        "/",
        StaticFiles(directory=Path(__file__).resolve().parents[1] / "web", html=True),
        name="development-web",
    )
