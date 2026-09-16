from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from core.access_models import (
    AppUser,
    AuditEvent,
    Base,
    ExternalIdentity,
    HubMembership,
    uuid7,
)
from core.identity import VerifiedIdentity, link_verified_identity
from grp.admin import (
    assign_member,
    bootstrap_platform_admin,
    ensure_hub,
    list_access_requests,
)


def test_uuid7_generator_sets_version_and_variant() -> None:
    value = uuid7()

    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_unknown_verified_identity_creates_only_a_pending_audit_event() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    identity = VerifiedIdentity(
        issuer="https://identity.example.test",
        subject="unknown-subject",
        verified_email="Expert@Example.test",
        display_name="Example Expert",
    )

    with Session(engine) as session:
        result = link_verified_identity(session, identity, request_intent="register")
        session.commit()

        assert not result.allowed
        assert result.reason == "membership_assignment_required"
        assert session.scalar(select(func.count()).select_from(AppUser)) == 0
        assert session.scalar(select(func.count()).select_from(ExternalIdentity)) == 0
        event = session.scalar(select(AuditEvent))
        assert event is not None
        assert event.action == "identity_link_denied"
        assert event.new_value["verified_email"] == "expert@example.test"
        assert event.new_value["request_intent"] == "register"
        assert list_access_requests(session) == ["expert@example.test"]


def test_admin_mapping_allows_retry_and_links_identity_once() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    identity = VerifiedIdentity(
        issuer="https://identity.example.test",
        subject="expert-subject",
        verified_email="expert@example.test",
        display_name="Example Expert",
    )

    with Session(engine) as session:
        assert bootstrap_platform_admin(session, "owner@example.test").changed
        assert ensure_hub(
            session,
            actor_email="owner@example.test",
            code="adpc",
            name="ADPC Hub",
        ).changed
        assert assign_member(
            session,
            actor_email="owner@example.test",
            email="expert@example.test",
            hub_code="adpc",
            role="planner",
        ).changed
        session.commit()

        first = link_verified_identity(session, identity)
        second = link_verified_identity(session, identity)
        session.commit()

        assert first.allowed and second.allowed
        assert first.display_name == "Example Expert"
        assert [(item.hub_code, item.role) for item in first.memberships] == [("adpc", "planner")]
        assert session.scalar(select(func.count()).select_from(ExternalIdentity)) == 1
        assert session.scalar(select(func.count()).select_from(HubMembership)) == 1
        assert list_access_requests(session) == []


def test_membership_assignment_is_idempotent() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        bootstrap_platform_admin(session, "owner@example.test")
        ensure_hub(
            session,
            actor_email="owner@example.test",
            code="adpc",
            name="ADPC Hub",
        )
        first = assign_member(
            session,
            actor_email="owner@example.test",
            email="expert@example.test",
            hub_code="adpc",
            role="planner",
        )
        second = assign_member(
            session,
            actor_email="owner@example.test",
            email="expert@example.test",
            hub_code="adpc",
            role="planner",
        )

        assert first.changed
        assert not second.changed
        assert session.scalar(select(func.count()).select_from(HubMembership)) == 1


def test_preauthorized_user_without_hub_stays_in_pending_queue() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    identity = VerifiedIdentity(
        issuer="https://identity.example.test",
        subject="unmapped-subject",
        verified_email="unmapped@example.test",
        display_name=None,
    )

    with Session(engine) as session:
        session.add(AppUser(email="unmapped@example.test"))
        session.flush()
        result = link_verified_identity(session, identity)
        session.commit()

        assert not result.allowed
        assert list_access_requests(session) == ["unmapped@example.test"]


def _linked_planner(session: Session) -> VerifiedIdentity:
    bootstrap_platform_admin(session, "owner@example.test")
    ensure_hub(session, actor_email="owner@example.test", code="adpc", name="ADPC Hub")
    assign_member(
        session,
        actor_email="owner@example.test",
        email="planner@example.test",
        hub_code="adpc",
        role="planner",
    )
    identity = VerifiedIdentity(
        issuer="https://identity.example.test",
        subject="planner-subject",
        verified_email="planner@example.test",
        display_name="Planner",
    )
    assert link_verified_identity(session, identity).allowed
    session.commit()
    return identity


def test_same_login_reaches_same_person_after_email_change() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        identity = _linked_planner(session)
        renamed = VerifiedIdentity(
            issuer=identity.issuer,
            subject=identity.subject,
            verified_email="new-address@example.test",
            display_name="Renamed",
        )

        result = link_verified_identity(session, renamed)

        assert result.allowed
        assert result.email == "planner@example.test"
        assert session.scalar(select(func.count()).select_from(ExternalIdentity)) == 1


def test_second_login_with_same_email_is_not_merged() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        identity = _linked_planner(session)
        other_login = VerifiedIdentity(
            issuer=identity.issuer,
            subject="different-subject",
            verified_email="planner@example.test",
            display_name="Someone else",
        )

        result = link_verified_identity(session, other_login)
        session.commit()

        assert not result.allowed
        assert session.scalar(select(func.count()).select_from(ExternalIdentity)) == 1
        assert session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "identity_link_denied")
        ) == 1


def test_disabled_user_is_denied_at_sign_in() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        identity = _linked_planner(session)
        user = session.scalar(select(AppUser).where(AppUser.email == "planner@example.test"))
        user.status = "disabled"
        session.commit()

        assert not link_verified_identity(session, identity).allowed


def test_verified_email_differing_from_admin_entry_is_denied() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _linked_planner(session)
        near_miss = VerifiedIdentity(
            issuer="https://identity.example.test",
            subject="near-miss-subject",
            verified_email="planner@example.test.evil",
            display_name=None,
        )

        assert not link_verified_identity(session, near_miss).allowed
        assert session.scalar(select(func.count()).select_from(AppUser)) == 2
