"""Admin data-library API exposes and queues only the known platform baseline."""

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import api.data_library as routes
from api.sessions import CurrentPrincipal
from core.access_models import AppUser, AuditEvent, Base
from core.assessment_models import Dataset, DatasetVersion
from core.boundary_import import BOUNDARY_SOURCE_REF, BOUNDARY_STEM, REQUIRED_SUFFIXES
from core.data_library_models import DataImportJob


def _source(root: Path) -> None:
    folder = root / BOUNDARY_SOURCE_REF
    folder.mkdir(parents=True)
    for suffix in REQUIRED_SUFFIXES:
        (folder / f"{BOUNDARY_STEM}{suffix}").write_bytes(suffix.encode())


def _principal(user_id, *, platform=True) -> CurrentPrincipal:
    return CurrentPrincipal(
        user_id=user_id,
        email="admin@example.test",
        display_name="Admin",
        is_platform_admin=platform,
        memberships=(),
        issued_at=0,
        session_id="test",
    )


@pytest.fixture
def api_world(tmp_path: Path, monkeypatch):
    root = tmp_path / "data-in"
    _source(root)
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(
            data_in_root=root,
            grp_env="test",
            shelter_browser_upload_enabled=False,
            shelter_upload_max_bytes=64 * 1024 * 1024,
        ),
    )
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = AppUser(email="admin@example.test", is_platform_admin=True)
        session.add(user)
        session.commit()
        yield session, _principal(user.id)


@pytest.mark.fast
def test_platform_admin_can_queue_boundary_import_and_it_is_audited(api_world) -> None:
    session, principal = api_world

    started = routes.import_boundaries(
        principal=principal,
        session=session,
        idempotency_key="boundary-import-test",
    )

    job = session.get(DataImportJob, UUID(started["import_id"]))
    audit = session.scalar(
        select(AuditEvent).where(AuditEvent.action == "platform_baseline_import_requested")
    )
    assert started["state"] == "queued"
    assert job.source_ref == BOUNDARY_SOURCE_REF
    assert job.hub_id is None
    assert audit.target_id == str(job.id)


@pytest.mark.fast
def test_data_library_reuses_active_import_and_shows_it(api_world) -> None:
    session, principal = api_world
    first = routes.import_boundaries(
        principal=principal,
        session=session,
        idempotency_key="boundary-import-first",
    )
    second = routes.import_boundaries(
        principal=principal,
        session=session,
        idempotency_key="boundary-import-second",
    )

    payload = routes.data_library(principal=principal, session=session)

    assert second == {"import_id": first["import_id"], "state": "queued", "reused": True}
    assert payload["boundary"]["source_available"] is True
    assert payload["boundary"]["active_import_id"] == first["import_id"]
    assert payload["boundary"]["versions"] == []
    assert payload["thailand_bootstrap"]["ready"] is False
    assert payload["thailand_bootstrap"]["categories"]["boundary"]["source_present"] is True


@pytest.mark.fast
def test_import_status_hides_report_until_terminal(api_world) -> None:
    session, principal = api_world
    started = routes.import_boundaries(
        principal=principal,
        session=session,
        idempotency_key="boundary-import-status",
    )

    payload = routes.read_import(UUID(started["import_id"]), principal, session)

    assert payload["state"] == "queued"
    assert payload["progress"] == 0
    assert payload["report"] is None
    assert payload["version"] is None


@pytest.mark.fast
def test_platform_admin_accepts_one_exact_shelter_version(api_world) -> None:
    session, principal = api_world
    dataset = Dataset(
        type="evacuation_centers",
        owner_kind="platform",
        title="Uploaded DDPM shelters",
        provider="ADPC local upload",
    )
    session.add(dataset)
    session.flush()
    old = DatasetVersion(
        dataset_id=dataset.id,
        sha256="a" * 64,
        meta={},
        readiness="assessment_ready",
        is_current=True,
    )
    uploaded = DatasetVersion(
        dataset_id=dataset.id,
        sha256="b" * 64,
        meta={
            "shelter_names_confirmed": False,
            "source_mode": "browser_upload",
            "original_filename": "local-shelters.zip",
        },
        readiness="technically_valid",
        is_current=False,
    )
    session.add_all([old, uploaded])
    session.commit()

    payload = routes.accept_shelter_version(uploaded.id, principal, session)
    session.refresh(old)
    session.refresh(uploaded)

    assert payload["version"]["version_id"] == str(uploaded.id)
    assert payload["version"]["readiness"] == "assessment_ready"
    assert payload["version"]["shelter_names_confirmed"] is False
    assert payload["version"]["source_mode"] == "browser_upload"
    assert payload["version"]["original_filename"] == "local-shelters.zip"
    assert payload["version"]["dataset_title"] == "Uploaded DDPM shelters"
    assert payload["version"]["provider"] == "ADPC local upload"
    assert uploaded.is_current is True
    assert uploaded.accepted_by == principal.user_id
    assert old.is_current is False
    assert session.scalar(
        select(AuditEvent).where(AuditEvent.action == "shelter_version_accepted")
    ) is not None
