from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.access_models import (
    AppUser,
    AuditEvent,
    AuditResult,
    ExternalIdentity,
    Hub,
    HubMembership,
    HubStatus,
    MembershipStatus,
    UserStatus,
    utc_now,
)


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    verified_email: str
    display_name: str | None
    provider_kind: str = "servir_sig"


@dataclass(frozen=True)
class MembershipView:
    hub_id: UUID
    hub_code: str
    hub_name: str
    role: str


@dataclass(frozen=True)
class IdentityLinkResult:
    allowed: bool
    reason: str
    user_id: UUID | None = None
    email: str | None = None
    display_name: str | None = None
    is_platform_admin: bool = False
    memberships: tuple[MembershipView, ...] = ()


def load_active_memberships(session: Session, user_id: UUID) -> tuple[MembershipView, ...]:
    rows = session.execute(
        select(HubMembership, Hub)
        .join(Hub, Hub.id == HubMembership.hub_id)
        .where(
            HubMembership.user_id == user_id,
            HubMembership.status == MembershipStatus.ACTIVE,
            Hub.status == HubStatus.ACTIVE,
        )
        .order_by(Hub.code)
    ).all()
    return tuple(
        MembershipView(
            hub_id=hub.id,
            hub_code=hub.code,
            hub_name=hub.name,
            role=membership.role,
        )
        for membership, hub in rows
    )


def _audit_denial(session: Session, identity: VerifiedIdentity, reason: str) -> None:
    notification = (
        "membership_assignment_required"
        if reason in {"membership_assignment_required", "no_active_membership"}
        else "security_review_required"
    )
    session.add(
        AuditEvent(
            actor_kind="system",
            action="identity_link_denied",
            target_type="verified_login",
            target_id=identity.verified_email.lower(),
            new_value={
                "verified_email": identity.verified_email.lower(),
                "provider_kind": identity.provider_kind,
                "reason": reason,
                "admin_notification": notification,
            },
            result=AuditResult.DENIED,
        )
    )


def link_verified_identity(
    session: Session,
    identity: VerifiedIdentity,
    now: datetime | None = None,
) -> IdentityLinkResult:
    """Link a verified login only after an active GRP access mapping exists."""

    now = now or utc_now()
    normalized_email = identity.verified_email.strip().lower()
    external = session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.issuer == identity.issuer,
            ExternalIdentity.subject == identity.subject,
        )
    )

    if external is not None:
        user = session.get(AppUser, external.user_id)
        if external.disabled_at is not None or user is None or user.status != UserStatus.ACTIVE:
            _audit_denial(session, identity, "identity_or_user_disabled")
            return IdentityLinkResult(allowed=False, reason="access_not_authorized")
    else:
        user = session.scalar(select(AppUser).where(AppUser.email == normalized_email))
        if user is None:
            _audit_denial(session, identity, "membership_assignment_required")
            return IdentityLinkResult(allowed=False, reason="membership_assignment_required")
        if user.status != UserStatus.ACTIVE:
            _audit_denial(session, identity, "user_disabled")
            return IdentityLinkResult(allowed=False, reason="access_not_authorized")

    memberships = load_active_memberships(session, user.id)
    if not memberships and not user.is_platform_admin:
        _audit_denial(session, identity, "no_active_membership")
        return IdentityLinkResult(allowed=False, reason="membership_assignment_required")

    if external is None:
        external = ExternalIdentity(
            user_id=user.id,
            issuer=identity.issuer,
            subject=identity.subject,
            provider_kind=identity.provider_kind,
            verified_email=normalized_email,
            linked_at=now,
            last_sign_in_at=now,
            safe_metadata={},
        )
        try:
            with session.begin_nested():
                session.add(external)
                session.flush()
        except IntegrityError:
            external = session.scalar(
                select(ExternalIdentity).where(
                    ExternalIdentity.issuer == identity.issuer,
                    ExternalIdentity.subject == identity.subject,
                )
            )
            if external is None or external.user_id != user.id:
                _audit_denial(session, identity, "identity_link_conflict")
                return IdentityLinkResult(allowed=False, reason="access_not_authorized")
        session.add(
            AuditEvent(
                actor_user_id=user.id,
                actor_kind="person",
                action="identity_linked",
                target_type="external_identity",
                target_id=str(external.id),
                new_value={"provider_kind": identity.provider_kind},
                result=AuditResult.SUCCESS,
            )
        )

    external.last_sign_in_at = now
    user.last_sign_in_at = now
    if identity.display_name and not user.display_name:
        user.display_name = identity.display_name
    session.add(
        AuditEvent(
            actor_user_id=user.id,
            actor_kind="person",
            action="sign_in_success",
            target_type="app_user",
            target_id=str(user.id),
            result=AuditResult.SUCCESS,
        )
    )
    return IdentityLinkResult(
        allowed=True,
        reason="allowed",
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_platform_admin=user.is_platform_admin,
        memberships=memberships,
    )
