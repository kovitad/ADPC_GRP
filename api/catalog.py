from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import and_, or_, select

from api.dependencies import DatabaseSession
from api.errors import not_found
from api.permissions import SignedInMember
from api.planning_access import planner_membership
from core.assessment_models import Boundary, Dataset, DatasetVersion, Method
from core.data_library_models import AreaPopulationSummary
from core.facility_types import TYPE_LABELS
from core.local_evidence import facility_type_counts

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get(
    "/boundaries",
    summary="Supported areas",
    openapi_extra={"x-grp-access": "protected"},
)
def boundaries(
    principal: SignedInMember,
    session: DatabaseSession,
    hub_code: str | None = Query(default=None, max_length=64),
    level: str = Query(default="district", pattern="^(district|subdistrict)$"),
    parent_admin_code: str | None = Query(default=None, max_length=64),
) -> dict[str, object]:
    planner_membership(principal, hub_code)
    statement = select(Boundary).where(Boundary.is_supported, Boundary.admin_level == level)
    if level == "subdistrict" and parent_admin_code:
        statement = statement.where(Boundary.admin_code.like(f"{parent_admin_code[:4]}%"))
    rows = session.scalars(statement.order_by(Boundary.name)).all()
    return {
        "boundaries": [
            {
                "id": str(row.id),
                "name": row.name,
                "name_th": row.name_th,
                "admin_code": row.admin_code,
                "admin_level": row.admin_level,
                "province_name": row.province_name,
                "province_name_th": row.province_name_th,
                "country_name": row.country_name,
                "source": row.source,
                "edition": row.edition,
                "synthetic": "synthetic" in row.source.casefold(),
                "geometry": row.geom,
            }
            for row in rows
        ]
    }


@router.get(
    "/datasets",
    summary="Current platform and Hub datasets, shown separately",
    openapi_extra={"x-grp-access": "protected"},
)
def datasets(
    principal: SignedInMember,
    session: DatabaseSession,
    hub_code: str | None = Query(default=None, max_length=64),
) -> dict[str, object]:
    hub = planner_membership(principal, hub_code)
    rows = session.execute(
        select(DatasetVersion, Dataset)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(
            or_(Dataset.hub_id.is_(None), Dataset.hub_id == hub.hub_id),
            or_(
                DatasetVersion.is_current,
                and_(
                    Dataset.type == "evacuation_centers",
                    DatasetVersion.readiness == "assessment_ready",
                ),
            ),
        )
        .order_by(Dataset.type, DatasetVersion.is_current.desc(), DatasetVersion.created_at.desc())
    ).all()
    return {
        "datasets": [
            {
                "version_id": str(version.id),
                "type": dataset.type,
                "owner_kind": dataset.owner_kind,
                "title": dataset.title,
                "title_th": version.meta.get("title_th")
                or (
                    "ศูนย์พักพิงและศูนย์อพยพของ ปภ."
                    if dataset.type == "evacuation_centers"
                    and dataset.provider.casefold() != "grp synthetic test data"
                    else None
                ),
                "provider": dataset.provider,
                "synthetic": dataset.provider.casefold() == "grp synthetic test data",
                "return_period_years": version.return_period_years,
                "edition": version.meta.get("edition"),
                "sha256": version.sha256,
                "readiness": version.readiness,
                "feature_count": version.meta.get("feature_count"),
                "is_current": version.is_current,
                "created_at": version.created_at.isoformat(),
            }
            for version, dataset in rows
        ]
    }


@router.get(
    "/methods",
    summary="Methods that may run",
    openapi_extra={"x-grp-access": "protected"},
)
def methods(
    principal: SignedInMember,
    session: DatabaseSession,
    hub_code: str | None = Query(default=None, max_length=64),
) -> dict[str, object]:
    planner_membership(principal, hub_code)
    rows = session.scalars(select(Method).where(Method.status != "retired")).all()
    if rows is None:
        raise not_found()
    return {
        "methods": [
            {
                "key": row.key,
                "version": row.version,
                "status": row.status,
                "reason_codes": row.reason_codes,
            }
            for row in rows
        ]
    }


@router.get(
    "/areas/{boundary_id}/profile",
    summary="Population and village counts for one supported area",
    openapi_extra={"x-grp-access": "protected"},
)
def area_profile(
    boundary_id: UUID,
    principal: SignedInMember,
    session: DatabaseSession,
    hub_code: str | None = Query(default=None, max_length=64),
) -> dict[str, object]:
    """Read the counts the village import computed for this area.

    Registered village population, not a vulnerability measure: the delivery carries no count of
    children, older people or people with disabilities. See ADR-0027 and
    docs/vulnerable-people-data-proof.md. The numbers come from one indexed row per area, written
    at import time, so this does no GIS work.
    """

    planner_membership(principal, hub_code)
    boundary = session.get(Boundary, boundary_id)
    if boundary is None or not boundary.is_supported:
        raise not_found()
    version = session.scalar(
        select(DatasetVersion)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(Dataset.type == "village_locations", DatasetVersion.is_current)
        .order_by(DatasetVersion.created_at.desc())
    )
    summary = (
        session.scalar(
            select(AreaPopulationSummary).where(
                AreaPopulationSummary.dataset_version_id == version.id,
                AreaPopulationSummary.admin_code == boundary.admin_code,
                AreaPopulationSummary.admin_level == boundary.admin_level,
            )
        )
        if version is not None
        else None
    )
    centers_version = session.scalar(
        select(DatasetVersion)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(Dataset.type == "evacuation_centers", DatasetVersion.is_current)
        .order_by(DatasetVersion.created_at.desc())
    )
    facilities = (
        facility_type_counts(session, centers_version.id, boundary.id)
        if centers_version is not None
        else {}
    )
    area = {
        "id": str(boundary.id),
        "name": boundary.name,
        "name_th": boundary.name_th,
        "admin_code": boundary.admin_code,
        "admin_level": boundary.admin_level,
        "province_name": boundary.province_name,
        "province_name_th": boundary.province_name_th,
        "country_name": boundary.country_name,
    }
    evacuation_centers = {
        "total": sum(facilities.values()),
        "by_type": [
            {"key": key, "label": TYPE_LABELS.get(key, key), "count": count}
            for key, count in sorted(facilities.items(), key=lambda item: (-item[1], item[0]))
        ],
        "caveat": "Type is read from the delivered Thai name (ADR-0028). Centre capacity, "
        "building condition and route safety are not assessed.",
    }
    if summary is None:
        # Fail closed: say there is no population record rather than imply zero people.
        return {
            "area": area,
            "population": None,
            "source": None,
            "evacuation_centers": evacuation_centers,
        }
    return {
        "area": area,
        "evacuation_centers": evacuation_centers,
        "population": {
            "village_count": summary.village_count,
            "counted_village_count": summary.counted_village_count,
            "excluded_village_count": summary.excluded_village_count,
            "male": summary.male,
            "female": summary.female,
            "total_population": summary.total_population,
            "households": summary.households,
        },
        "source": {
            "version_id": str(version.id),
            "label": "Registered village population",
            "label_th": "ประชากรตามทะเบียนหมู่บ้าน",
            "edition": boundary.edition,
            "caveat": "Source columns are not yet confirmed by the data owner (ADR-0027). "
            "This is not a count of vulnerable people.",
        },
    }
