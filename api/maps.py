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

MAP_RETURN_PERIODS = (20, 50, 100)

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
    version, _ = row
    if not (version.is_current or version.meta.get("map_preview") is True):
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
        .where(or_(Dataset.hub_id.is_(None), Dataset.hub_id == hub.hub_id))
        .order_by(Dataset.type, DatasetVersion.return_period_years)
    ).all()
    # Technically validated baseline imports may be drawn for orientation before scientific
    # activation. They stay non-current, so catalog/assessment input selection cannot use them.
    rows = [
        row for row in rows if row[0].is_current or row[0].meta.get("map_preview") is True
    ]
    rows.sort(
        key=lambda row: (row[0].meta.get("map_preview") is True, row[0].created_at),
        reverse=True,
    )
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
            "preview_only": version.meta.get("map_preview") is True and not version.is_current,
            "readiness": version.readiness,
            "palette": version.meta.get("palette"),
        }
        for version, dataset in rows
        if dataset.type == "hazard"
    ]
    scenario_layers: dict[int, dict[str, object]] = {}
    for layer in flood:
        years = layer["return_period_years"]
        if years in MAP_RETURN_PERIODS and years not in scenario_layers:
            scenario_layers[int(years)] = layer
    flood_scenarios = [
        {
            "return_period_years": years,
            "label": f"RP{years}",
            "available": years in scenario_layers and bool(scenario_layers[years]["available"]),
            "layer_id": scenario_layers[years]["id"] if years in scenario_layers else None,
            "message": None
            if years in scenario_layers and scenario_layers[years]["available"]
            else "Not imported into the managed data library yet.",
        }
        for years in MAP_RETURN_PERIODS
    ]
    centers = [
        {
            "id": f"centers-{version.id}",
            "version_id": str(version.id),
            "title": dataset.title,
            "owner_kind": dataset.owner_kind,
            "provider": dataset.provider,
            "features_url": f"/api/v1/maps/datasets/{version.id}/features",
            "preview_only": version.meta.get("map_preview") is True and not version.is_current,
            "readiness": version.readiness,
        }
        for version, dataset in rows
        if dataset.type == "evacuation_centers"
    ]
    return {
        "flood": flood,
        "flood_scenarios": flood_scenarios,
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
        select(Feature).where(Feature.dataset_version_id == version.id).order_by(Feature.id)
    ).all()
    names_confirmed = version.meta.get("shelter_names_confirmed") is True
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": str(feature.id),
                "geometry": {"type": "Point", "coordinates": [feature.lon, feature.lat]},
                "properties": {
                    "name": feature.name
                    if names_confirmed or feature.attributes.get("synthetic") is True
                    else f"Evacuation centre {position}"
                },
            }
            for position, feature in enumerate(features, start=1)
        ],
    }
