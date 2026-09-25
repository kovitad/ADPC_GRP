from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, or_, select

from api.dependencies import DatabaseSession
from api.errors import not_found
from api.permissions import SignedInMember
from api.planning_access import planner_membership
from core.assessment_models import Boundary, Dataset, DatasetVersion, Method
from core.data_library_models import AreaFloodExposure, AreaPopulationSummary
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
    province_code: str | None = Query(default=None, max_length=8),
    include_geometry: bool = Query(default=True),
) -> dict[str, object]:
    """List the supported areas at one level.

    ``include_geometry=false`` omits the polygons. A picker only needs names, and sending 928
    district outlines to build a dropdown made the assessment page slow to load (backlog U2).
    ``province_code`` narrows by the leading digits of the Thai administrative code, so a planner
    can choose a province first instead of scrolling every district in the country.
    """

    planner_membership(principal, hub_code)
    statement = select(Boundary).where(Boundary.is_supported, Boundary.admin_level == level)
    if level == "subdistrict" and parent_admin_code:
        statement = statement.where(Boundary.admin_code.like(f"{parent_admin_code[:4]}%"))
    if province_code:
        statement = statement.where(Boundary.admin_code.like(f"{province_code[:2]}%"))
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
                **({"geometry": row.geom} if include_geometry else {}),
            }
            for row in rows
        ]
    }


@router.get(
    "/provinces",
    summary="Provinces that contain a supported area",
    openapi_extra={"x-grp-access": "protected"},
)
def provinces(
    principal: SignedInMember,
    session: DatabaseSession,
    hub_code: str | None = Query(default=None, max_length=64),
) -> dict[str, object]:
    """Provinces derived from the supported districts, never from the province boundaries.

    The province rows in ``boundary`` are not supported areas and must not become selectable: a
    province is not something an assessment runs on. Deriving the list from supported districts
    also guarantees every province offered contains at least one district a planner can pick.
    """

    planner_membership(principal, hub_code)
    # Group by the province name and take the code as an aggregate. Every district in a province
    # shares the same two leading digits, so min() is exact, and it avoids grouping by a substr
    # expression: SQLAlchemy binds its arguments separately in SELECT and GROUP BY, which SQLite
    # accepts and PostgreSQL rejects as a different expression.
    rows = session.execute(
        select(
            func.min(func.substr(Boundary.admin_code, 1, 2)).label("code"),
            Boundary.province_name,
            func.min(Boundary.province_name_th).label("name_th"),
            func.count(Boundary.id).label("districts"),
        )
        .where(
            Boundary.is_supported,
            Boundary.admin_level == "district",
            Boundary.province_name.is_not(None),
        )
        .group_by(Boundary.province_name)
        .order_by(Boundary.province_name)
    ).all()
    return {
        "provinces": [
            {
                "code": code,
                "name": name,
                "name_th": name_th,
                "district_count": int(districts),
            }
            for code, name, name_th, districts in rows
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
    hazard_version = session.scalar(
        select(DatasetVersion)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(Dataset.type == "hazard", DatasetVersion.is_current)
        .order_by(DatasetVersion.created_at.desc())
    )
    exposure_row = (
        session.scalar(
            select(AreaFloodExposure).where(
                AreaFloodExposure.hazard_version_id == hazard_version.id,
                AreaFloodExposure.village_version_id == version.id,
                AreaFloodExposure.admin_code == boundary.admin_code,
                AreaFloodExposure.admin_level == boundary.admin_level,
            )
        )
        if hazard_version is not None and version is not None
        else None
    )
    # None means the exposure job has not run for this pair of versions, which is not zero exposed.
    flood_exposure = (
        None
        if exposure_row is None
        else {
            "return_period_years": exposure_row.return_period_years,
            "villages_in_zone": exposure_row.villages_in_zone,
            "people_in_zone": exposure_row.people_in_zone,
            "households_in_zone": exposure_row.households_in_zone,
            "no_data_village_count": exposure_row.no_data_village_count,
            "villages_in_zone_without_population": (
                exposure_row.villages_in_zone_without_population
            ),
            "depth_bands": exposure_row.depth_bands,
            "caveat": "A village is a point, so this counts villages whose recorded location "
            "falls inside the modelled extent. The flood layer records a depth only where the "
            "model produced flooding, so the remaining villages are dry, outside the modelled "
            "area or outside its coverage, and must not be read as confirmed safe.",
        }
    )
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
            "flood_exposure": flood_exposure,
        }
    return {
        "area": area,
        "evacuation_centers": evacuation_centers,
        "flood_exposure": flood_exposure,
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
