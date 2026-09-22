"""Approved baseline activation enables real districts without changing source bytes."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.access_models import AppUser, AuditEvent, Base
from core.assessment_models import Boundary, Dataset, DatasetVersion, Method
from core.baseline_activation import activate_mvp1_baseline
from core.boundary_import import PLATFORM_BOUNDARY_DATASET_ID
from core.hazard_import import PLATFORM_HAZARD_DATASET_ID
from core.shelter_import import PLATFORM_SHELTER_DATASET_ID
from core.validation import canonical_sha256


def test_activate_latest_imported_baseline() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    geometry = {
        "type": "Polygon",
        "coordinates": [[[100, 15], [101, 15], [101, 16], [100, 16], [100, 15]]],
    }
    with Session(engine) as session:
        user = AppUser(email="owner@example.test", is_platform_admin=True)
        datasets = [
            Dataset(
                id=PLATFORM_BOUNDARY_DATASET_ID,
                type="boundary",
                owner_kind="platform",
                title="Thailand districts",
                provider="Approved source",
            ),
            Dataset(
                id=PLATFORM_SHELTER_DATASET_ID,
                type="evacuation_centers",
                owner_kind="platform",
                title="Thailand evacuation centres",
                provider="Approved source",
            ),
            Dataset(
                id=PLATFORM_HAZARD_DATASET_ID,
                type="hazard",
                owner_kind="platform",
                title="Thailand RP100",
                provider="Approved source",
            ),
        ]
        session.add_all([user, *datasets])
        session.flush()
        boundary_version = DatasetVersion(
            dataset_id=PLATFORM_BOUNDARY_DATASET_ID,
            sha256="a" * 64,
            is_current=False,
            readiness="technically_valid",
        )
        center_version = DatasetVersion(
            dataset_id=PLATFORM_SHELTER_DATASET_ID,
            sha256="b" * 64,
            is_current=False,
            readiness="technically_valid",
        )
        hazard_version = DatasetVersion(
            dataset_id=PLATFORM_HAZARD_DATASET_ID,
            sha256="c" * 64,
            return_period_years=100,
            is_current=False,
            readiness="waiting_for_method",
        )
        session.add_all([boundary_version, center_version, hazard_version])
        session.flush()
        boundary = Boundary(
            admin_code="TH-TEST",
            admin_level="district",
            name="Approved Test District",
            geom=geometry,
            source="Approved source",
            edition="2026",
            geometry_sha256=canonical_sha256(geometry),
            collection_version_id=boundary_version.id,
            is_supported=False,
        )
        session.add(boundary)
        session.flush()

        result = activate_mvp1_baseline(
            session,
            actor_user_id=user.id,
            actor_email=user.email,
        )
        session.commit()

        assert result["supported_districts"] == 1
        assert boundary.is_supported
        assert all(
            version.is_current and version.readiness == "assessment_ready"
            for version in (boundary_version, center_version, hazard_version)
        )
        method = session.scalar(select(Method).where(Method.status == "approved"))
        assert method is not None and method.approved_by == user.email
        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "mvp1_baseline_activated")
        )
        assert audit.new_value["no_data_policy"] == "unable_to_assess"
