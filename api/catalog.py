from fastapi import APIRouter, Query
from sqlalchemy import and_, or_, select

from api.dependencies import DatabaseSession
from api.errors import not_found
from api.permissions import SignedInMember
from api.planning_access import planner_membership
from core.assessment_models import Boundary, Dataset, DatasetVersion, Method

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
) -> dict[str, object]:
    planner_membership(principal, hub_code)
    rows = session.scalars(
        select(Boundary).where(Boundary.is_supported).order_by(Boundary.name)
    ).all()
    return {
        "boundaries": [
            {
                "id": str(row.id),
                "name": row.name,
                "admin_code": row.admin_code,
                "admin_level": row.admin_level,
                "province_name": row.province_name,
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
                "provider": dataset.provider,
                "synthetic": dataset.provider.casefold() == "grp synthetic test data",
                "return_period_years": version.return_period_years,
                "edition": version.meta.get("edition"),
                "sha256": version.sha256,
                "readiness": version.readiness,
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
