from fastapi import APIRouter, Query
from sqlalchemy import select

from api.dependencies import DatabaseSession
from api.errors import access_not_authorized, not_found
from api.permissions import SignedInMember
from core.access_models import AppUser, AuditEvent, Hub

router = APIRouter(tags=["audit"])


@router.get(
    "/admin/audit-events",
    summary="Read the security log (own Hub for Hub Admins, all for Platform Admins)",
    openapi_extra={"x-grp-access": "protected"},
)
def audit_events(
    principal: SignedInMember,
    session: DatabaseSession,
    hub_code: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, object]:
    admin_hubs = {m.hub_code: m.hub_id for m in principal.memberships if m.role == "admin"}
    query = select(AuditEvent, AppUser.email).outerjoin(
        AppUser, AppUser.id == AuditEvent.actor_user_id
    )
    if hub_code:
        code = hub_code.strip().lower()
        if principal.is_platform_admin:
            hub = session.scalar(select(Hub).where(Hub.code == code))
            if hub is None:
                raise not_found()
            query = query.where(AuditEvent.hub_id == hub.id)
        elif code in admin_hubs:
            query = query.where(AuditEvent.hub_id == admin_hubs[code])
        else:
            raise not_found()
    elif not principal.is_platform_admin:
        if not admin_hubs:
            raise access_not_authorized()
        query = query.where(AuditEvent.hub_id.in_(list(admin_hubs.values())))
    rows = session.execute(query.order_by(AuditEvent.occurred_at.desc()).limit(limit)).all()
    return {
        "events": [
            {
                "occurred_at": event.occurred_at.isoformat(),
                "actor": email or event.actor_kind,
                "action": event.action,
                "target_type": event.target_type,
                "result": event.result,
                "old_value": event.old_value,
                "new_value": event.new_value,
                "support_ref": event.support_ref,
            }
            for event, email in rows
        ]
    }
