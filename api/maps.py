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
from core.assessment_models import Boundary, Dataset, DatasetVersion, Feature
from core.hazard_overlay import legend
from core.storage import LocalStorage

router = APIRouter(prefix="/maps", tags=["maps"])

MAP_RETURN_PERIODS = (20, 50, 100)

POINT_DATASET_TYPES = {
    "evacuation_centers",
    "volunteer_centers",
    "early_warning_resources",
    "village_locations",
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
    version, dataset = row
    assessment_ready_centers = (
        dataset.type in POINT_DATASET_TYPES and version.readiness == "assessment_ready"
    )
    if not (
        version.is_current or version.meta.get("map_preview") is True or assessment_ready_centers
    ):
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
        row
        for row in rows
        if row[0].is_current
        or row[0].meta.get("map_preview") is True
        or (row[1].type == "evacuation_centers" and row[0].readiness == "assessment_ready")
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
            "synthetic": dataset.provider.casefold() == "grp synthetic test data",
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
    scenario_candidates = [layer for layer in flood if not layer["synthetic"]] or flood
    for layer in scenario_candidates:
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
            "title_th": version.meta.get("title_th")
            or (
                "ศูนย์พักพิงและศูนย์อพยพของ ปภ."
                if dataset.provider.casefold() != "grp synthetic test data"
                else None
            ),
            "owner_kind": dataset.owner_kind,
            "provider": dataset.provider,
            "synthetic": dataset.provider.casefold() == "grp synthetic test data",
            "features_url": f"/api/v1/maps/datasets/{version.id}/features",
            "preview_only": version.meta.get("map_preview") is True and not version.is_current,
            "readiness": version.readiness,
            "is_current": version.is_current,
            "source_mode": version.meta.get("source_mode"),
            "original_filename": version.meta.get("original_filename"),
            "shelter_names_confirmed": version.meta.get("shelter_names_confirmed"),
            "feature_count": version.meta.get("feature_count"),
            "created_at": version.created_at.isoformat(),
        }
        for version, dataset in rows
        if dataset.type == "evacuation_centers"
    ]
    supporting_points = [
        {
            "id": f"{dataset.type}-{version.id}",
            "version_id": str(version.id),
            "role": dataset.type,
            "title": dataset.title,
            "title_th": version.meta.get("title_th"),
            "provider": dataset.provider,
            "features_url": f"/api/v1/maps/datasets/{version.id}/features",
            "feature_count": version.meta.get("feature_count"),
            "available": version.is_current,
        }
        for version, dataset in rows
        if dataset.type in POINT_DATASET_TYPES - {"evacuation_centers"} and version.is_current
    ]
    vulnerability = [
        {
            "id": f"vulnerability-{version.id}",
            "version_id": str(version.id),
            "indicator_key": version.meta.get("indicator_key"),
            "title": dataset.title,
            "title_th": version.meta.get("title_th"),
            "provider": dataset.provider,
            "image_url": f"/api/v1/maps/vulnerability/{version.id}/overlay.png",
            "bounds": version.meta.get("overlay_bounds"),
            "available": bool(version.meta.get("overlay_key")) and version.is_current,
            "display_only": True,
            "meaning": version.meta.get("meaning"),
            "display_range": version.meta.get("display_range"),
        }
        for version, dataset in rows
        if dataset.type == "vulnerability" and version.is_current
    ]
    return {
        "flood": flood,
        "flood_scenarios": flood_scenarios,
        "flood_legend": legend(),
        "evacuation_centers": centers,
        "supporting_points": supporting_points,
        "vulnerability": vulnerability,
        "note": "Available source layers are displayed directly; an assessment is optional.",
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
    "/vulnerability/{version_id}/overlay.png",
    summary="Display-only vulnerability indicator picture",
    openapi_extra={"x-grp-access": "protected"},
    response_class=Response,
)
def vulnerability_overlay(
    version_id: UUID,
    principal: SignedInMember,
    session: DatabaseSession,
    hub_code: str | None = Query(default=None, max_length=64),
) -> Response:
    hub = planner_membership(principal, hub_code)
    version, dataset = _visible_version(session, version_id, hub.hub_id)
    key = version.meta.get("overlay_key")
    storage = LocalStorage(get_settings().storage_root)
    if dataset.type != "vulnerability" or not key or not storage.exists(str(key)):
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
    boundary_id: UUID | None = Query(default=None),  # noqa: B008
) -> dict[str, object]:
    hub = planner_membership(principal, hub_code)
    version, dataset = _visible_version(session, version_id, hub.hub_id)
    if dataset.type not in POINT_DATASET_TYPES:
        raise not_found()
    query = select(Feature).where(Feature.dataset_version_id == version.id)
    boundary = None
    if boundary_id is not None:
        boundary = session.get(Boundary, boundary_id)
        if boundary is None or not boundary.is_supported:
            raise not_found()
        # Imported source points and the current boundary catalogue can have different
        # version-specific UUIDs. Match the stable administrative code as well as the
        # UUID so a catalogue refresh does not disconnect otherwise valid points.
        if boundary.admin_level == "district":
            query = query.where(
                or_(
                    Feature.boundary_id == boundary.id,
                    Feature.attributes["admin_code"].as_string() == boundary.admin_code,
                )
            )
    features = session.scalars(query.order_by(Feature.name, Feature.id)).all()
    if boundary is not None and boundary.admin_level == "subdistrict":
        from shapely.geometry import Point, shape

        polygon = shape(boundary.geom)
        features = [
            feature
            for feature in features
            if feature.attributes.get("subdistrict_code") == boundary.admin_code
            or polygon.covers(Point(feature.lon, feature.lat))
        ]
    return {
        "type": "FeatureCollection",
        "total": len(features),
        "boundary": None
        if boundary is None
        else {
            "id": str(boundary.id),
            "admin_code": boundary.admin_code,
            "name": boundary.name,
        },
        "source": {
            "version_id": str(version.id),
            "title": dataset.title,
            "provider": dataset.provider,
        },
        "features": [
            {
                "type": "Feature",
                "id": str(feature.id),
                "geometry": {"type": "Point", "coordinates": [feature.lon, feature.lat]},
                "properties": {
                    "feature_id": str(feature.id),
                    "name": feature.name,
                    "status": "not_assessed",
                    # Source facts a planner needs beside the label. Capacity is absent for
                    # part of the delivery and is shown as unknown rather than as zero.
                    "capacity": feature.attributes.get("capacity"),
                    "supporting_unit": feature.attributes.get("supporting_unit") or None,
                    "subdistrict": feature.attributes.get("subdistrict") or None,
                    "village": feature.attributes.get("village") or None,
                    "source_title": dataset.title,
                    "source_provider": dataset.provider,
                    "role": dataset.type,
                    "attributes": feature.attributes,
                },
            }
            for feature in features
        ],
    }
