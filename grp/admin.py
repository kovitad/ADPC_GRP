from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from typing import Never
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.access_models import (
    AppUser,
    AuditEvent,
    AuditResult,
    Hub,
    HubMembership,
    HubStatus,
    MembershipRole,
    MembershipStatus,
    UserStatus,
    utc_now,
)
from core.db import session_scope

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class CommandResult:
    changed: bool
    message: str


class LastAdminRequired(ValueError):
    """Raised when a change would leave a Hub without an active Admin."""


class HubAccessDenied(ValueError):
    """Raised when a member of the Hub lacks the Admin role for the requested action."""


class ItemNotFound(ValueError):
    """Raised for unknown Hubs or members, and for Hubs the actor does not belong to."""


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 320 or not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("A valid work email is required")
    return email


def require_platform_admin(session: Session, email: str) -> AppUser:
    actor = session.scalar(select(AppUser).where(AppUser.email == normalize_email(email)))
    if actor is None or actor.status != UserStatus.ACTIVE or not actor.is_platform_admin:
        raise ValueError("The named actor is not an active Platform Admin")
    return actor


def _active_actor(session: Session, actor_user_id: UUID) -> AppUser:
    actor = session.get(AppUser, actor_user_id)
    if actor is None or actor.status != UserStatus.ACTIVE:
        raise ValueError("The named actor is not an active GRP user")
    return actor


def _active_hub(session: Session, hub_code: str) -> Hub:
    hub = session.scalar(select(Hub).where(Hub.code == hub_code.strip().lower()))
    if hub is None or hub.status != HubStatus.ACTIVE:
        raise ItemNotFound("Active Hub does not exist")
    return hub


def require_hub_manager(session: Session, actor_user_id: UUID, hub: Hub) -> AppUser:
    actor = _active_actor(session, actor_user_id)
    if actor.is_platform_admin:
        return actor
    membership = session.scalar(
        select(HubMembership).where(
            HubMembership.hub_id == hub.id,
            HubMembership.user_id == actor.id,
            HubMembership.role == MembershipRole.ADMIN,
            HubMembership.status == MembershipStatus.ACTIVE,
        )
    )
    if membership is None:
        belongs = session.scalar(
            select(HubMembership.id).where(
                HubMembership.hub_id == hub.id,
                HubMembership.user_id == actor.id,
                HubMembership.status == MembershipStatus.ACTIVE,
            )
        )
        # Other-Hub requests look exactly like unknown Hubs (Section 13.1).
        if belongs is None:
            raise ItemNotFound("Active Hub does not exist")
        raise HubAccessDenied("Hub Admin access required")
    return actor


def list_admin_hubs(session: Session, *, actor_user_id: UUID) -> list[dict[str, str]]:
    actor = _active_actor(session, actor_user_id)
    query = select(Hub).where(Hub.status == HubStatus.ACTIVE)
    if not actor.is_platform_admin:
        query = (
            query.join(HubMembership, HubMembership.hub_id == Hub.id)
            .where(
                HubMembership.user_id == actor.id,
                HubMembership.role == MembershipRole.ADMIN,
                HubMembership.status == MembershipStatus.ACTIVE,
            )
        )
    hubs = session.scalars(query.order_by(Hub.code)).all()
    return [{"id": str(hub.id), "code": hub.code, "name": hub.name} for hub in hubs]


def bootstrap_platform_admin(session: Session, email: str) -> CommandResult:
    normalized = normalize_email(email)
    user = session.scalar(select(AppUser).where(AppUser.email == normalized))
    if user is not None:
        if user.status != UserStatus.ACTIVE:
            raise ValueError("A disabled account cannot be bootstrapped")
        if user.is_platform_admin:
            return CommandResult(False, "Platform Admin already exists; no change")

    if user is None:
        user = AppUser(email=normalized, status=UserStatus.ACTIVE, is_platform_admin=True)
        session.add(user)
        session.flush()
    else:
        user.is_platform_admin = True

    session.add(
        AuditEvent(
            actor_kind="system",
            action="platform_admin_bootstrapped",
            target_type="app_user",
            target_id=str(user.id),
            new_value={"email": normalized, "is_platform_admin": True},
            result=AuditResult.SUCCESS,
            support_ref="grp.admin bootstrap-platform-admin",
        )
    )
    return CommandResult(True, "Platform Admin provisioned")


def ensure_hub(session: Session, *, actor_email: str, code: str, name: str) -> CommandResult:
    actor = require_platform_admin(session, actor_email)
    normalized_code = code.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", normalized_code):
        raise ValueError("Hub code must contain 2-64 lowercase letters, digits, '_' or '-'")
    if not name.strip():
        raise ValueError("Hub name is required")
    hub = session.scalar(select(Hub).where(Hub.code == normalized_code))
    if hub is not None:
        if hub.status == HubStatus.ACTIVE and hub.name == name.strip():
            return CommandResult(False, "Hub already exists; no change")
        raise ValueError("Hub code already exists with a different name or status")
    hub = Hub(code=normalized_code, name=name.strip())
    session.add(hub)
    session.flush()
    session.add(
        AuditEvent(
            actor_user_id=actor.id,
            actor_kind="person",
            hub_id=hub.id,
            action="hub_created",
            target_type="hub",
            target_id=str(hub.id),
            new_value={"code": normalized_code, "name": name.strip()},
            result=AuditResult.SUCCESS,
            support_ref="grp.admin ensure-hub",
        )
    )
    return CommandResult(True, "Hub provisioned")


def assign_member(
    session: Session,
    *,
    actor_email: str,
    email: str,
    hub_code: str,
    role: str,
) -> CommandResult:
    actor = require_platform_admin(session, actor_email)
    return assign_member_as_actor(
        session,
        actor_user_id=actor.id,
        email=email,
        hub_code=hub_code,
        role=role,
    )


def assign_member_as_actor(
    session: Session,
    *,
    actor_user_id: UUID,
    email: str,
    hub_code: str,
    role: str,
) -> CommandResult:
    normalized_email = normalize_email(email)
    normalized_role = role.strip().lower()
    if normalized_role not in {MembershipRole.PLANNER, MembershipRole.ADMIN}:
        raise ValueError("Role must be planner or admin")
    hub = _active_hub(session, hub_code)
    actor = require_hub_manager(session, actor_user_id, hub)
    user = session.scalar(select(AppUser).where(AppUser.email == normalized_email))
    if user is None:
        user = AppUser(email=normalized_email, status=UserStatus.ACTIVE)
        session.add(user)
        session.flush()
    elif user.status != UserStatus.ACTIVE:
        raise ValueError("A disabled account cannot receive membership")
    membership = session.scalar(
        select(HubMembership).where(
            HubMembership.hub_id == hub.id,
            HubMembership.user_id == user.id,
        )
    )
    if membership is not None:
        if membership.role == normalized_role and membership.status == MembershipStatus.ACTIVE:
            return CommandResult(False, "Membership already exists; no change")
        raise ValueError("Role or status changes are not supported by the first-assignment flow")

    membership = HubMembership(
        hub_id=hub.id,
        user_id=user.id,
        role=normalized_role,
        status=MembershipStatus.ACTIVE,
        changed_by=actor.id,
    )
    session.add(membership)
    session.flush()
    session.add(
        AuditEvent(
            actor_user_id=actor.id,
            actor_kind="person",
            hub_id=hub.id,
            action="member_added",
            target_type="hub_membership",
            target_id=str(membership.id),
            new_value={"email": normalized_email, "role": normalized_role},
            result=AuditResult.SUCCESS,
            support_ref="grp.admin assign-member",
        )
    )
    return CommandResult(True, "Membership assigned")


def list_hub_members(
    session: Session, *, actor_user_id: UUID, hub_code: str
) -> list[dict[str, object]]:
    hub = _active_hub(session, hub_code)
    require_hub_manager(session, actor_user_id, hub)
    rows = session.execute(
        select(HubMembership, AppUser)
        .join(AppUser, AppUser.id == HubMembership.user_id)
        .where(HubMembership.hub_id == hub.id)
        .order_by(AppUser.email)
    ).all()
    return [
        {
            "id": str(membership.id),
            "user_id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "role": membership.role,
            "status": membership.status,
            "is_platform_admin": user.is_platform_admin,
        }
        for membership, user in rows
    ]


def update_hub_member(
    session: Session,
    *,
    actor_user_id: UUID,
    hub_code: str,
    member_id: UUID,
    role: str | None = None,
    membership_status: str | None = None,
) -> CommandResult:
    hub = session.scalar(
        select(Hub).where(Hub.code == hub_code.strip().lower()).with_for_update()
    )
    if hub is None or hub.status != HubStatus.ACTIVE:
        raise ItemNotFound("Active Hub does not exist")
    actor = require_hub_manager(session, actor_user_id, hub)
    membership = session.scalar(
        select(HubMembership).where(
            HubMembership.id == member_id,
            HubMembership.hub_id == hub.id,
        )
    )
    if membership is None:
        raise ItemNotFound("Hub membership does not exist")
    new_role = role.strip().lower() if role is not None else membership.role
    new_status = (
        membership_status.strip().lower()
        if membership_status is not None
        else membership.status
    )
    if new_role not in {MembershipRole.PLANNER, MembershipRole.ADMIN}:
        raise ValueError("Role must be planner or admin")
    if new_status not in {MembershipStatus.ACTIVE, MembershipStatus.DISABLED}:
        raise ValueError("Status must be active or disabled")
    if membership.role == new_role and membership.status == new_status:
        return CommandResult(False, "Membership already has those settings; no change")

    removes_active_admin = (
        membership.role == MembershipRole.ADMIN
        and membership.status == MembershipStatus.ACTIVE
        and (new_role != MembershipRole.ADMIN or new_status != MembershipStatus.ACTIVE)
    )
    if removes_active_admin:
        other_admins = session.scalar(
            select(func.count())
            .select_from(HubMembership)
            .where(
                HubMembership.hub_id == hub.id,
                HubMembership.id != membership.id,
                HubMembership.role == MembershipRole.ADMIN,
                HubMembership.status == MembershipStatus.ACTIVE,
            )
        )
        if not other_admins:
            raise LastAdminRequired("A Hub must keep at least one active Admin")

    old_value = {"role": membership.role, "status": membership.status}
    membership.role = new_role
    membership.status = new_status
    membership.changed_by = actor.id
    member_user = session.get(AppUser, membership.user_id)
    if member_user is not None:
        # The person gets a new session after any role or access change (Section 9.1).
        member_user.sessions_valid_after = utc_now()
    action = "role_changed" if old_value["role"] != new_role else "access_status_changed"
    session.add(
        AuditEvent(
            actor_user_id=actor.id,
            actor_kind="person",
            hub_id=hub.id,
            action=action,
            target_type="hub_membership",
            target_id=str(membership.id),
            old_value=old_value,
            new_value={"role": new_role, "status": new_status},
            result=AuditResult.SUCCESS,
            support_ref="admin membership update",
        )
    )
    return CommandResult(True, "Membership updated")


def membership_access_message(
    session: Session, *, actor_user_id: UUID, hub_code: str, member_id: UUID
) -> str:
    hub = _active_hub(session, hub_code)
    require_hub_manager(session, actor_user_id, hub)
    row = session.execute(
        select(HubMembership, AppUser)
        .join(AppUser, AppUser.id == HubMembership.user_id)
        .where(HubMembership.id == member_id, HubMembership.hub_id == hub.id)
    ).first()
    if row is None:
        raise ItemNotFound("Hub membership does not exist")
    membership, _user = row
    return (
        f"You now have access to GRP ({hub.name}, {membership.role}). "
        "Open the GRP address and sign in with your SERVIR account."
    )


def list_access_requests(session: Session) -> list[str]:
    events = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.action == "identity_link_denied")
        .order_by(AuditEvent.occurred_at.desc())
    ).all()
    pending: list[str] = []
    seen: set[str] = set()
    for event in events:
        value = event.new_value or {}
        email = str(value.get("verified_email", "")).lower()
        reason = str(value.get("reason", ""))
        if (
            not email
            or email in seen
            or reason not in {"membership_assignment_required", "no_active_membership"}
        ):
            continue
        seen.add(email)
        user = session.scalar(select(AppUser).where(AppUser.email == email))
        if user is None:
            pending.append(email)
            continue
        if user.status != UserStatus.ACTIVE or user.is_platform_admin:
            continue
        membership = session.scalar(
            select(HubMembership.id)
            .join(Hub, Hub.id == HubMembership.hub_id)
            .where(
                HubMembership.user_id == user.id,
                HubMembership.status == MembershipStatus.ACTIVE,
                Hub.status == HubStatus.ACTIVE,
            )
            .limit(1)
        )
        if membership is None:
            pending.append(email)
    return pending


def fail(message: str) -> Never:
    raise SystemExit(f"ERROR: {message}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GRP server-side access administration")
    commands = parser.add_subparsers(dest="command", required=True)

    bootstrap = commands.add_parser("bootstrap-platform-admin")
    bootstrap.add_argument("--email", required=True)

    hub = commands.add_parser("ensure-hub")
    hub.add_argument("--actor-email", required=True)
    hub.add_argument("--code", required=True)
    hub.add_argument("--name", required=True)

    member = commands.add_parser("assign-member")
    member.add_argument("--actor-email", required=True)
    member.add_argument("--email", required=True)
    member.add_argument("--hub-code", required=True)
    member.add_argument("--role", choices=["planner", "admin"], required=True)

    commands.add_parser("list-access-requests")
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    try:
        with session_scope() as session:
            if arguments.command == "bootstrap-platform-admin":
                result = bootstrap_platform_admin(session, arguments.email)
            elif arguments.command == "ensure-hub":
                result = ensure_hub(
                    session,
                    actor_email=arguments.actor_email,
                    code=arguments.code,
                    name=arguments.name,
                )
            elif arguments.command == "assign-member":
                result = assign_member(
                    session,
                    actor_email=arguments.actor_email,
                    email=arguments.email,
                    hub_code=arguments.hub_code,
                    role=arguments.role,
                )
            else:
                requests = list_access_requests(session)
                print("\n".join(requests) if requests else "No pending access requests")
                return
    except ValueError as error:
        fail(str(error))
    print(result.message)


if __name__ == "__main__":
    main()
