from __future__ import annotations

import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

_SUPPORT_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_support_ref() -> str:
    """Return a short, non-secret reference people can quote to support (Appendix D)."""

    part = "".join(secrets.choice(_SUPPORT_ALPHABET) for _ in range(6))
    return f"GRP-{part[:4]}-{part[4:]}"


class GrpError(Exception):
    """A typed, detail-free API error rendered in the Appendix D format."""

    def __init__(
        self, status_code: int, code: str, message: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}


def not_signed_in() -> GrpError:
    return GrpError(401, "NOT_SIGNED_IN", "Please sign in.")


def access_not_authorized() -> GrpError:
    return GrpError(403, "ACCESS_NOT_AUTHORIZED", "Access not authorized.")


def not_found() -> GrpError:
    return GrpError(404, "NOT_FOUND", "We could not find this item.")


def validation_failed(details: str) -> GrpError:
    return GrpError(422, "VALIDATION_FAILED", f"Some inputs are not valid. {details}".strip())


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(GrpError)
    async def _render(_: Request, error: GrpError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            headers=error.headers,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "support_ref": new_support_ref(),
                }
            },
        )
