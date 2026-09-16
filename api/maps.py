"""Map layers for the Planning workspace: flood overlay picture, centers, placeholders."""

from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlalchemy import or_, select

from api.dependencies import DatabaseSession
from api.errors import not_found
from api.permissions import SignedInMember
from api.planning_access import planner_membership
from api.settings import get_settings
from core.assessment_models import Dataset, DatasetVersion, Feature
from core.hazard_overlay import legend
from core.storage import LocalStorage

router = APIRouter(prefix="/maps", tags=["maps"])

VULNERABILITY_PLACEHOLDER = {
    "id": "vulnerable-people",
    "title": "Vulnerable people",
    "available": False,
    "message": (
        "Not available yet. The approved vulnerability layer and its meaning arrive in "
        "Increment 6 (dependency DEP-07)."
    ),
}


def _visible_version(session, version_id: UUID, hub_id: UUID) -> tuple[DatasetVersion, Dataset]:
    row = session.execute(
        select(DatasetVersion, Dataset)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(
            DatasetVersion.id == version_id,
            or_(Dataset.hub_id.is_(None), Dataset.hub_id == hub_id),
        )
    ).first()
    if row is None:
        raise not_found()
    return row


@router.get(
    "/layers",
    summary="Layers for the Planning map",
    openapi_extra={"x-grp-access": "protected"},
)
def map_layers(
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
        .order_by(Dataset.type, DatasetVersion.return_period_years)
    ).all()
    flood = [
        {
            "id": f"flood-{version.id}",
            "version_id": str(version.id),
            "title": f"Flood depth RP{version.return_period_years} · {dataset.title}",
            "return_period_years": version.return_period_years,
            "provider": dataset.provider,
            "image_url": f"/api/v1/maps/hazard/{version.id}/overlay.png",
            "bounds": version.meta.get("overlay_bounds"),
            "available": bool(version.meta.get("overlay_key")),
        }
        for version, dataset in rows
        if dataset.type == "hazard"
    ]
    centers = [
        {
            "id": f"centers-{version.id}",
            "version_id": str(version.id),
            "title": dataset.title,
            "owner_kind": dataset.owner_kind,
            "provider": dataset.provider,
            "features_url": f"/api/v1/maps/datasets/{version.id}/features",
        }
        for version, dataset in rows
        if dataset.type == "evacuation_centers"
    ]
    return {
        "flood": flood,
        "flood_legend": legend(),
        "evacuation_centers": centers,
        "vulnerability": VULNERABILITY_PLACEHOLDER,
        "note": "Map pictures are for orientation. Assessment numbers come from the locked result.",
    }


@router.get(
    "/hazard/{version_id}/overlay.png",
    summary="Display-only flood depth picture",
    openapi_extra={"x-grp-access": "protected"},
    response_class=Response,
)
def hazard_overlay(
    version_id: UUID,
    principal: SignedInMember,
    session: DatabaseSession,
    hub_code: str | None = Query(default=None, max_length=64),
) -> Response:
    hub = planner_membership(principal, hub_code)
    version, dataset = _visible_version(session, version_id, hub.hub_id)
    key = version.meta.get("overlay_key")
    storage = LocalStorage(get_settings().storage_root)
    if dataset.type != "hazard" or not key or not storage.exists(str(key)):
        raise not_found()
    return Response(
        storage.read_bytes(str(key)),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get(
    "/datasets/{version_id}/features",
    summary="Evacuation center points for the map",
    openapi_extra={"x-grp-access": "protected"},
)
def dataset_features(
    version_id: UUID,
    principal: SignedInMember,
    session: DatabaseSession,
    hub_code: str | None = Query(default=None, max_length=64),
) -> dict[str, object]:
    hub = planner_membership(principal, hub_code)
    version, dataset = _visible_version(session, version_id, hub.hub_id)
    if dataset.type != "evacuation_centers":
        raise not_found()
    features = session.scalars(
        select(Feature).where(Feature.dataset_version_id == version.id).order_by(Feature.name)
    ).all()
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": str(feature.id),
                "geometry": {"type": "Point", "coordinates": [feature.lon, feature.lat]},
                "properties": {"name": feature.name},
            }
            for feature in features
        ],
    }
