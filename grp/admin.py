from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from typing import Never

from sqlalchemy import select
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
)
from core.db import session_scope

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class CommandResult:
    changed: bool
    message: str


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
    normalized_email = normalize_email(email)
    normalized_role = role.strip().lower()
    if normalized_role not in {MembershipRole.PLANNER, MembershipRole.ADMIN}:
        raise ValueError("Role must be planner or admin")
    hub = session.scalar(select(Hub).where(Hub.code == hub_code.strip().lower()))
    if hub is None or hub.status != HubStatus.ACTIVE:
        raise ValueError("Active Hub does not exist")
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
