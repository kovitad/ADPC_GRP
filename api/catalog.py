from fastapi import APIRouter, Query
from sqlalchemy import or_, select

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
                "synthetic": "synthetic" in row.source,
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
            DatasetVersion.is_current,
            or_(Dataset.hub_id.is_(None), Dataset.hub_id == hub.hub_id),
        )
        .order_by(Dataset.type, Dataset.title)
    ).all()
    return {
        "datasets": [
            {
                "version_id": str(version.id),
                "type": dataset.type,
                "owner_kind": dataset.owner_kind,
                "title": dataset.title,
                "provider": dataset.provider,
                "return_period_years": version.return_period_years,
                "edition": version.meta.get("edition"),
                "sha256": version.sha256,
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
