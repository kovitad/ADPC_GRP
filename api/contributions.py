"""Send a Hub's data to Global Risk as a contribution, and follow it until it lands (ADR-0032).

A contribution is outward-facing and, on a deployment that auto-approves, public for every Global
Risk user at once. So the flow is: GRP checks the manifest (preview), the person confirms the
exact manifest, GRP writes a durable row, and only then does a background task call
``contribute_submit`` under the person's own SERVIR sign-in. A timeout is never retried blindly:
GRP looks for the record in ``contribute_status`` first.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import UUID

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.dependencies import DatabaseSession
from api.errors import GrpError, not_found
from api.mcp_client import SigMcpClient, SigMcpError
from api.permissions import SignedInMember
from api.planning_access import planner_membership
from api.sessions import CurrentPrincipal
from api.settings import get_settings, planning_chat_available
from api.sig_connection import sig_access_token
from api.sig_evidence import tool_payload
from api.sig_jobs import app_session
from core.access_models import PLANNING_MEMBER_ROLES, AuditEvent, AuditResult
from core.contribution_models import (
    APPROVED,
    CHECKING,
    DECLINED,
    FAILED,
    OPEN_STATES,
    REJECTED,
    STAGED,
    SUBMITTING,
    WITHDRAWN,
    SigContribution,
)
from core.contribution_rules import NAME_FIELD, check_manifest, check_point_file

logger = logging.getLogger("grp.contributions")
router = APIRouter(prefix="/contributions", tags=["contributions"])

# Global Risk downloads and checks the file before it answers, so a submit can take minutes.
SUBMIT_TIMEOUT_SECONDS = 240.0
# GRP reads a point file itself only to keep contact fields out and record what was sent.
POINT_FILE_MAX_BYTES = 50 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 60.0
FETCH_HOSTS = frozenset(
    {
        "drive.google.com",
        "docs.google.com",
        "drive.usercontent.google.com",
        "raw.githubusercontent.com",
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)
MISSING_FIELD = re.compile(r"missing required field '([a-z_]+)'")
# Global Risk's record status -> GRP state.
RECORD_STATES = {
    "approved": APPROVED,
    "staged": STAGED,
    "pending": STAGED,
    "rejected": REJECTED,
    "withdrawn": WITHDRAWN,
    "failed": FAILED,
    "declined": DECLINED,
}


class ContributionRequest(BaseModel):
    hub_code: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=16)
    manifest: dict[str, Any]
    # True: check and show the exact manifest, send nothing. False: the person has confirmed.
    preview: bool = True


def _available() -> None:
    # The SERVIR token lives only where the planning chat runs (ADR-0004).
    if not planning_chat_available(get_settings()):
        raise not_found()


def _job_state(row: SigContribution) -> str:
    """The top-bar job tracker's vocabulary: a submission has finished once Global Risk answered."""

    if row.state in {SUBMITTING, CHECKING}:
        return "running"
    if row.state in {APPROVED, STAGED}:
        return "succeeded"
    return "failed"


def field_problems(problems: list[str] | None) -> dict[str, str]:
    """Global Risk's "missing required field 'x'" lines, keyed by the form field they belong to."""

    mapped: dict[str, str] = {}
    for problem in problems or []:
        match = MISSING_FIELD.search(problem)
        if match:
            mapped[match.group(1)] = "Global Risk says this is required."
    return mapped


def view(row: SigContribution, principal: CurrentPrincipal) -> dict[str, Any]:
    failed = _job_state(row) == "failed"
    return {
        "id": str(row.id),
        "kind": row.kind,
        "name": row.name,
        "title": row.title,
        "status": row.state,
        "state": _job_state(row),
        "error_code": row.error_code or (row.state.upper() if failed else None),
        "error": row.error_message,
        "contribution_id": row.contribution_id,
        "problems": row.problems or [],
        "field_problems": field_problems(row.problems),
        "response": row.response or {},
        "manifest": row.manifest,
        "file_sha256": row.file_sha256,
        "feature_count": row.feature_count,
        "mine": row.user_id == principal.user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _audit(session, row: SigContribution, action: str, result: AuditResult) -> None:
    session.add(
        AuditEvent(
            actor_user_id=row.user_id,
            actor_kind="person",
            hub_id=row.hub_id,
            action=action,
            target_type="sig_contribution",
            target_id=str(row.id),
            new_value={
                "kind": row.kind,
                "name": row.name,
                "state": row.state,
                "contribution_id": row.contribution_id,
                "file_sha256": row.file_sha256,
            },
            result=result,
        )
    )


def _find_record(value: Any, *, contribution_id: str | None = None) -> dict[str, Any] | None:
    """The contribution record inside a Global Risk reply, wherever the reply nests it."""

    if isinstance(value, dict):
        if "contribution_id" in value and (
            contribution_id is None or value.get("contribution_id") == contribution_id
        ):
            return value
        for child in value.values():
            found = _find_record(child, contribution_id=contribution_id)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_record(child, contribution_id=contribution_id)
            if found is not None:
                return found
    return None


def _safe_response(payload: dict[str, Any], record: dict[str, Any] | None) -> dict[str, Any]:
    """What GRP keeps of a reply: enough to explain the outcome, no server paths."""

    source = record or payload
    preview = source.get("preview") if isinstance(source.get("preview"), dict) else {}
    observed = preview.get("observed") if isinstance(preview.get("observed"), dict) else {}
    kept = {
        "status": source.get("status") or payload.get("status"),
        "decision_note": source.get("decision_note"),
        "reviewer_label": source.get("reviewer_label"),
        "how_to_test": preview.get("how_to_test") or payload.get("how_to_test"),
        "layer": preview.get("layer"),
        "observed": {k: observed[k] for k in ("features", "bbox", "properties") if k in observed},
        "note": payload.get("note"),
    }
    return {key: value for key, value in kept.items() if value not in (None, {}, "")}


def _apply_record(row: SigContribution, record: dict[str, Any], payload: dict[str, Any]) -> None:
    row.contribution_id = str(record.get("contribution_id") or row.contribution_id or "") or None
    status = str(record.get("status") or payload.get("status") or "").lower()
    row.state = RECORD_STATES.get(status, row.state)
    row.response = _safe_response(payload, record)
    if row.state in {APPROVED, STAGED}:
        row.error_code = row.error_message = None


def _apply_submit_reply(row: SigContribution, payload: dict[str, Any]) -> None:
    status = str(payload.get("status") or "").lower()
    if status == "declined":
        row.state = DECLINED
        row.problems = [str(problem) for problem in payload.get("problems") or []]
        row.error_code = "DECLINED_BY_GLOBAL_RISK"
        row.error_message = "Global Risk declined the contribution and named what to fix."
        row.response = _safe_response(payload, None)
        return
    record = _find_record(payload)
    if record is None and status in RECORD_STATES:
        record = payload
    if record is None:
        row.state = FAILED
        row.error_code = "UNEXPECTED_REPLY"
        row.error_message = "Global Risk answered in a way GRP does not recognise."
        row.response = _safe_response(payload, None)
        return
    _apply_record(row, record, payload)
    if row.state not in {APPROVED, STAGED, REJECTED, WITHDRAWN, DECLINED}:
        row.state = STAGED if row.contribution_id else FAILED


async def _fetch_point_file(url: str) -> bytes:
    """Download a point file from an allowed host, following redirects only to allowed hosts."""

    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False) as client:
        for _ in range(6):
            host = (urlparse(url).hostname or "").lower()
            if urlparse(url).scheme != "https" or host not in FETCH_HOSTS:
                raise GrpError(
                    422,
                    "FILE_HOST_NOT_CHECKABLE",
                    "GRP checks point files before sending them, and can read them only from "
                    "Google Drive or GitHub. Share the file there.",
                )
            async with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                if response.status_code != 200:
                    raise GrpError(
                        422,
                        "FILE_NOT_REACHABLE",
                        f"The link answered HTTP {response.status_code}. Check that anyone with "
                        "the link can open it.",
                    )
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > POINT_FILE_MAX_BYTES:
                        raise GrpError(
                            422, "FILE_TOO_LARGE", "The point file is larger than 50 MB."
                        )
                    chunks.append(chunk)
                return b"".join(chunks)
        raise GrpError(422, "FILE_NOT_REACHABLE", "The link redirected too many times.")


async def _reconcile(mcp: SigMcpClient, row: SigContribution) -> bool:
    """After an unanswered submit: is there a record for it on Global Risk?"""

    result = await mcp.call_tool("contribute_status", {})
    payload = tool_payload(result)
    records = payload.get("contributions") if isinstance(payload.get("contributions"), list) else []
    created = row.created_at or datetime.now(UTC)
    if created.tzinfo is None:  # SQLite returns the stored UTC time without its zone
        created = created.replace(tzinfo=UTC)
    since = created - timedelta(minutes=2)
    for record in records:
        if not isinstance(record, dict) or record.get("kind") != row.kind:
            continue
        try:
            created_at = datetime.fromisoformat(str(record.get("created_at") or ""))
        except ValueError:
            continue
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        text = f"{record.get('title', '')} {record.get('preview', '')}"
        if created_at >= since and (row.name in text or row.title in text):
            _apply_record(row, record, payload)
            return True
    return False


async def submit_contribution(row_id: UUID, access_token: str) -> None:
    """The background half: check the file, submit once, and record whatever happened."""

    settings = get_settings()
    with app_session() as session:
        row = session.get(SigContribution, row_id)
        if row is None:
            return
        try:
            if row.kind == "vector":
                body = await _fetch_point_file(str(row.manifest["url"]))
                row.file_sha256 = hashlib.sha256(body).hexdigest()
                checked = check_point_file(body)
                row.feature_count = checked.feature_count or None
                if checked.problem:
                    raise GrpError(422, "FILE_CHECK_FAILED", checked.problem)
            session.commit()
        except GrpError as error:
            row.state, row.error_code, row.error_message = FAILED, error.code, error.message
            _audit(session, row, "sig_contribution_failed", AuditResult.DENIED)
            return
        except httpx.HTTPError:
            row.state, row.error_code = FAILED, "FILE_NOT_REACHABLE"
            row.error_message = "GRP could not download the file to check it. Nothing was sent."
            _audit(session, row, "sig_contribution_failed", AuditResult.DENIED)
            return

        http = httpx.AsyncClient(timeout=SUBMIT_TIMEOUT_SECONDS, follow_redirects=False)
        try:
            async with SigMcpClient(settings.sig_mcp_base_url, access_token, client=http) as mcp:
                try:
                    result = await mcp.call_tool(
                        "contribute_submit", {"kind": row.kind, "manifest": row.manifest}
                    )
                except (SigMcpError, httpx.HTTPError) as error:
                    # It may have arrived. Look before anyone is invited to send it again.
                    logger.warning("contribution %s: submit unanswered: %r", row.id, error)
                    row.state = CHECKING
                    session.commit()
                    if not await _reconcile(mcp, row):
                        row.state, row.error_code = FAILED, "SUBMIT_UNCONFIRMED"
                        row.error_message = (
                            "Global Risk did not answer, and has no record of this contribution. "
                            "It is safe to submit it again."
                        )
                else:
                    _apply_submit_reply(row, tool_payload(result))
        except (SigMcpError, httpx.HTTPError) as error:
            logger.warning("contribution %s: could not reach Global Risk: %r", row.id, error)
            if row.state == CHECKING:
                row.error_code = "SUBMIT_UNCONFIRMED"
                row.error_message = (
                    "Global Risk did not answer and GRP could not check whether it arrived. "
                    "Refresh this contribution before submitting again."
                )
            else:
                row.state, row.error_code = FAILED, "GLOBAL_RISK_UNAVAILABLE"
                row.error_message = "GRP could not reach Global Risk. Nothing was sent."
        finally:
            await http.aclose()
        _audit(
            session,
            row,
            "sig_contribution_result",
            AuditResult.SUCCESS if row.state in {APPROVED, STAGED} else AuditResult.DENIED,
        )


_running: set[asyncio.Task[None]] = set()


def _start(row_id: UUID, access_token: str) -> None:
    async def guarded() -> None:
        try:
            await submit_contribution(row_id, access_token)
        except Exception:  # noqa: BLE001 - a row must never be left "submitting" silently
            logger.exception("contribution %s crashed", row_id)
            with app_session() as session:
                row = session.get(SigContribution, row_id)
                if row is not None and row.state in {SUBMITTING, CHECKING}:
                    row.state, row.error_code = FAILED, "SUBMIT_UNCONFIRMED"
                    row.error_message = (
                        "GRP stopped while sending. Refresh this contribution to see whether it "
                        "reached Global Risk before submitting again."
                    )

    task = asyncio.create_task(guarded())
    _running.add(task)
    task.add_done_callback(_running.discard)


@router.get(
    "",
    summary="Contributions this Hub sent to Global Risk",
    openapi_extra={"x-grp-access": "protected"},
)
def list_contributions(
    principal: SignedInMember, session: DatabaseSession, hub_code: str | None = None
) -> dict[str, Any]:
    _available()
    hub = planner_membership(principal, hub_code)
    rows = session.scalars(
        select(SigContribution)
        .where(SigContribution.hub_id == hub.hub_id)
        .order_by(SigContribution.created_at.desc())
        .limit(100)
    ).all()
    return {"hub_code": hub.hub_code, "contributions": [view(row, principal) for row in rows]}


@router.post(
    "",
    summary="Check a contribution, or send a confirmed one to Global Risk",
    openapi_extra={"x-grp-access": "protected"},
)
async def create_contribution(
    payload: ContributionRequest, principal: SignedInMember, session: DatabaseSession
) -> dict[str, Any]:
    _available()
    hub = planner_membership(principal, payload.hub_code)
    kind = payload.kind.strip().lower()
    checked = check_manifest(kind, payload.manifest)
    if payload.preview or checked.problems:
        return {
            "sent": False,
            "kind": kind,
            "manifest": checked.manifest,
            "problems": checked.problems,
            "notes": checked.notes,
        }
    access_token = await sig_access_token(get_settings(), principal.session_id)
    if not access_token:
        raise GrpError(
            401, "SIG_REAUTH_REQUIRED", "Sign in with SERVIR again to send data to Global Risk."
        )
    manifest = checked.manifest
    row = SigContribution(
        hub_id=hub.hub_id,
        user_id=principal.user_id,
        kind=kind,
        name=str(manifest.get(NAME_FIELD[kind]) or "")[:200],
        title=str(manifest.get("title") or manifest.get("hazard") or "")[:500],
        manifest=manifest,
        state=SUBMITTING,
    )
    session.add(row)
    session.flush()
    _audit(session, row, "sig_contribution_submitted", AuditResult.SUCCESS)
    session.commit()
    session.refresh(row)
    _start(row.id, access_token)
    return {"sent": True, "contribution": view(row, principal)}


def _own_hub_row(
    contribution_id: UUID, principal: CurrentPrincipal, session
) -> SigContribution:
    """A contribution of a Hub the person plans for; anything else is simply not found."""

    row = session.get(SigContribution, contribution_id)
    if row is None or not any(
        m.hub_id == row.hub_id and m.role in PLANNING_MEMBER_ROLES for m in principal.memberships
    ):
        raise not_found()
    return row


@router.get(
    "/{contribution_id}",
    summary="One contribution this Hub sent to Global Risk",
    openapi_extra={"x-grp-access": "protected"},
)
def read_contribution(
    contribution_id: UUID, principal: SignedInMember, session: DatabaseSession
) -> dict[str, Any]:
    _available()
    return view(_own_hub_row(contribution_id, principal, session), principal)


@router.post(
    "/{contribution_id}/refresh",
    summary="Ask Global Risk for the current state of your own contribution",
    openapi_extra={"x-grp-access": "protected"},
)
async def refresh_contribution(
    contribution_id: UUID, principal: SignedInMember, session: DatabaseSession
) -> dict[str, Any]:
    _available()
    row = _own_hub_row(contribution_id, principal, session)
    # contribute_status answers only for the caller's own contributions.
    if row.user_id != principal.user_id:
        raise GrpError(
            403,
            "NOT_YOUR_CONTRIBUTION",
            "Only the person who sent this contribution can check it on Global Risk.",
        )
    unconfirmed = row.state == FAILED and row.error_code == "SUBMIT_UNCONFIRMED"
    if row.state not in OPEN_STATES and not unconfirmed:
        return view(row, principal)
    access_token = await sig_access_token(get_settings(), principal.session_id)
    if not access_token:
        raise GrpError(
            401, "SIG_REAUTH_REQUIRED", "Sign in with SERVIR again to check Global Risk."
        )
    try:
        async with SigMcpClient(get_settings().sig_mcp_base_url, access_token) as mcp:
            if row.contribution_id:
                result = await mcp.call_tool(
                    "contribute_status", {"contribution_id": row.contribution_id}
                )
                payload = tool_payload(result)
                record = _find_record(payload, contribution_id=row.contribution_id)
                if record is not None:
                    _apply_record(row, record, payload)
            elif await _reconcile(mcp, row):
                pass
            elif row.state == CHECKING or row.error_code == "SUBMIT_UNCONFIRMED":
                row.state, row.error_code = FAILED, "SUBMIT_UNCONFIRMED"
                row.error_message = (
                    "Global Risk has no record of this contribution. It is safe to submit it again."
                )
    except (SigMcpError, httpx.HTTPError) as error:
        raise GrpError(
            503, "SIG_UNAVAILABLE", "Global Risk is not available right now."
        ) from error
    session.commit()
    session.refresh(row)
    return view(row, principal)
