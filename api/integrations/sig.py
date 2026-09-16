"""SIG service role: machine login for the read-only evidence endpoint (Section 9.6).

Staging fallback: a long random bearer token checked against a SHA-256 hash file, plus an
optional IP allowlist. Human session cookies and SIG MCP tokens are never accepted here.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from api.dependencies import DatabaseSession
from api.errors import GrpError, not_found
from api.rate_limits import limiter
from api.settings import get_settings
from core.access_models import AuditEvent, AuditResult
from core.db import read_secret

router = APIRouter(prefix="/integrations/sig", tags=["sig"])
EVIDENCE_SCOPE = "assessment:evidence:read"


@dataclass(frozen=True)
class SigServicePrincipal:
    scope: str
    client_ip: str | None


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _unauthorized() -> GrpError:
    return GrpError(401, "NOT_SIGNED_IN", "Please sign in.")


def sig_service(request: Request) -> SigServicePrincipal:
    settings = get_settings()
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or len(token) < 32:
        raise _unauthorized()
    try:
        expected = read_secret(settings.sig_service_token_hash_file)
    except (OSError, RuntimeError) as error:
        raise _unauthorized() from error
    if not hmac.compare_digest(token_hash(token), expected):
        raise _unauthorized()
    client_ip = request.client.host if request.client else None
    if settings.sig_allowed_ips and client_ip not in settings.sig_allowed_ips:
        raise GrpError(403, "ACCESS_NOT_AUTHORIZED", "Access not authorized.")
    limiter.check(
        "sig_evidence_reads_per_minute",
        "sig-service",
        settings.rate_limits["sig_evidence_reads_per_minute"],
        60,
    )
    return SigServicePrincipal(scope=EVIDENCE_SCOPE, client_ip=client_ip)


SigService = Annotated[SigServicePrincipal, Depends(sig_service)]


@router.get(
    "/assessments/{assessment_id}/evidence",
    summary="Read evidence for an Admin-shared assessment (SIG service only)",
    openapi_extra={"x-grp-access": "internal"},
)
def assessment_evidence(
    assessment_id: UUID, service: SigService, session: DatabaseSession
) -> dict[str, object]:
    """Private by default: until Increments 1 and 3 add shared results, every read is 404."""

    session.add(
        AuditEvent(
            actor_kind="sig_service",
            action="sig_evidence_read",
            target_type="assessment",
            target_id=str(assessment_id),
            new_value={"scope": service.scope},
            result=AuditResult.DENIED,
        )
    )
    session.commit()
    raise not_found()
