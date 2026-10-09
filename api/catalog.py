import json
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, literal_column, or_, select

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
    include_geometry: bool = Query(default=False),
    geometry_detail: str = Query(default="full", pattern="^(full|overview)$"),
) -> dict[str, object]:
    """List the supported areas at one level.

    ``include_geometry=false`` omits the polygons. A picker only needs names, and sending 928
    district outlines to build a dropdown made the assessment page slow to load (backlog U2).
    ``province_code`` narrows by the leading digits of the Thai administrative code, so a planner
    can choose a province first instead of scrolling every district in the country.
    """

    planner_membership(principal, hub_code)
    columns = (
        Boundary.id,
        Boundary.name,
        Boundary.name_th,
        Boundary.admin_code,
        Boundary.admin_level,
        Boundary.province_name,
        Boundary.province_name_th,
        Boundary.country_name,
        Boundary.source,
        Boundary.edition,
    )
    overview_geometry = include_geometry and geometry_detail == "overview"
    if overview_geometry and session.get_bind().dialect.name == "postgresql":
        # A nationwide picker needs only an orientation outline. Selecting/clicking an area uses
        # the full indexed geometry through the narrowed or point endpoint. Never deserialize all
        # 928 detailed source polygons in the API process on the 1 GB pilot host.
        geometry_column = func.ST_AsGeoJSON(
            func.ST_SimplifyPreserveTopology(literal_column("boundary.geom_postgis"), 0.01)
        ).label("geometry")
    else:
        geometry_column = Boundary.geom.label("geometry")
    selected_columns = (*columns, geometry_column) if include_geometry else columns
    statement = select(*selected_columns).where(
        Boundary.is_supported, Boundary.admin_level == level
    )
    if level == "subdistrict" and parent_admin_code:
        statement = statement.where(Boundary.admin_code.like(f"{parent_admin_code[:4]}%"))
    if province_code:
        statement = statement.where(Boundary.admin_code.like(f"{province_code[:2]}%"))
    rows = session.execute(statement.order_by(Boundary.name)).all()
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
                **(
                    {
                        "geometry": (
                            json.loads(row.geometry)
                            if overview_geometry and isinstance(row.geometry, str)
                            else row.geometry
                        )
                    }
                    if include_geometry
                    else {}
                ),
            }
            for row in rows
        ]
    }


# ---------- areas by name or by point: district and sub-district together ----------
AREA_LEVELS = ("district", "subdistrict")
# Words people type around a name: "เขตจตุจักร", "แขวงลาดยาว", "Chatuchak District", "Tambon ...".
AREA_WORDS = ("subdistrict", "sub-district", "district", "khwaeng", "khet", "tambon", "amphoe",
              "แขวง", "เขต", "ตำบล", "อำเภอ", "ต.", "อ.")


def _area_view(row: Boundary, parent: Boundary | None = None, geometry: bool = False) -> dict:
    view = {
        "id": str(row.id),
        "name": row.name,
        "name_th": row.name_th,
        "admin_code": row.admin_code,
        "admin_level": row.admin_level,
        "province_name": row.province_name,
        "province_name_th": row.province_name_th,
        "country_name": row.country_name,
        "synthetic": "synthetic" in row.source.casefold(),
    }
    if row.admin_level == "subdistrict":
        view["district"] = None if parent is None else {
            "id": str(parent.id), "name": parent.name, "name_th": parent.name_th,
            "admin_code": parent.admin_code,
        }
    if geometry:
        view["geometry"] = row.geom
    return view


def _parents(session, rows: list[Boundary]) -> dict[str, Boundary]:
    codes = {row.admin_code[:4] for row in rows if row.admin_level == "subdistrict"}
    if not codes:
        return {}
    districts = session.scalars(select(Boundary).where(
        Boundary.is_supported, Boundary.admin_level == "district", Boundary.admin_code.in_(codes)))
    return {row.admin_code: row for row in districts}


def _search_term(q: str) -> str:
    term = " ".join(q.split()).casefold()
    for word in AREA_WORDS:
        term = term.replace(word, " ")
    return " ".join(term.split())


@router.get(
    "/areas/search",
    summary="Districts and sub-districts by Thai or English name",
    openapi_extra={"x-grp-access": "protected"},
)
def search_areas(
    principal: SignedInMember,
    session: DatabaseSession,
    q: str = Query(min_length=2, max_length=80),
    hub_code: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=12, ge=1, le=30),
) -> dict[str, object]:
    """Every supported district and sub-district whose name contains the words typed.

    Exact names come first, then names that start with the words, then the rest; districts come
    before sub-districts of the same rank. Sub-districts say which district they are in.
    """

    planner_membership(principal, hub_code)
    term = _search_term(q)
    if len(term) < 2:
        return {"areas": []}
    squeezed = term.replace(" ", "")
    rows = session.scalars(
        select(Boundary).where(
            Boundary.is_supported,
            Boundary.admin_level.in_(AREA_LEVELS),
            or_(
                func.lower(Boundary.name).contains(term),
                func.lower(func.coalesce(Boundary.name_th, "")).contains(term),
                func.replace(func.lower(Boundary.name), " ", "").contains(squeezed),
            ),
        ).limit(300)
    ).all()

    def rank(row: Boundary) -> tuple:
        names = [row.name.casefold(), (row.name_th or "").casefold()]
        flat = [name.replace(" ", "") for name in names]
        exact = term in names or squeezed in flat
        prefix = (any(name.startswith(term) for name in names)
                  or any(f.startswith(squeezed) for f in flat))
        return (0 if exact else 1 if prefix else 2, AREA_LEVELS.index(row.admin_level), row.name)

    rows = sorted(rows, key=rank)[:limit]
    parents = _parents(session, rows)
    return {"areas": [_area_view(row, parents.get(row.admin_code[:4])) for row in rows]}


@router.get(
    "/areas/at",
    summary="The district and sub-district that contain a point",
    openapi_extra={"x-grp-access": "protected"},
)
def area_at(
    principal: SignedInMember,
    session: DatabaseSession,
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    hub_code: str | None = Query(default=None, max_length=64),
) -> dict[str, object]:
    """One click on the map selects the sub-district under it and its district together.

    PostGIS answers with its spatial index; a database without it (the tests' SQLite) is read
    with Shapely. Either both are found, one of them, or neither: never a guess.
    """

    planner_membership(principal, hub_code)
    base = select(Boundary).where(Boundary.is_supported, Boundary.admin_level.in_(AREA_LEVELS))
    if session.get_bind().dialect.name == "postgresql":
        point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
        # geom_postgis is maintained by the migrations and indexed; the model keeps GeoJSON.
        covers = func.ST_Covers(literal_column("boundary.geom_postgis"), point)
        rows = session.scalars(base.where(covers)).all()
    else:
        from shapely.geometry import Point, shape

        here = Point(lon, lat)
        rows = [row for row in session.scalars(base).all()
                if row.geom and shape(row.geom).covers(here)]
    # A real area wins over the synthetic test district if both cover the point.
    rows.sort(key=lambda row: "synthetic" in row.source.casefold())
    district = next((row for row in rows if row.admin_level == "district"), None)
    subdistrict = next((row for row in rows if row.admin_level == "subdistrict"
                        and (district is None or row.admin_code.startswith(district.admin_code))),
                       None)
    if district is None and subdistrict is not None:
        district = _parents(session, [subdistrict]).get(subdistrict.admin_code[:4])
    return {
        "district": None if district is None else _area_view(district, geometry=True),
        "subdistrict": (None if subdistrict is None
                        else _area_view(subdistrict, district, geometry=True)),
    }


# Thailand's five statistical regions (National Statistical Office), read from the first two
# digits of the official province code: Central includes the East (20-27) and West (70-77).
REGIONS = (
    ("bangkok", "Bangkok", "กรุงเทพมหานคร"),
    ("central", "Central", "ภาคกลาง"),
    ("north", "North", "ภาคเหนือ"),
    ("northeast", "Northeast", "ภาคตะวันออกเฉียงเหนือ"),
    ("south", "South", "ภาคใต้"),
)


def province_region(code: str) -> int:
    """Index into REGIONS for a two-digit Thai province code; unknown codes sort last."""

    try:
        number = int(code)
    except (TypeError, ValueError):
        return len(REGIONS)
    if number == 10:
        return 0
    if 11 <= number <= 27 or 70 <= number <= 77:
        return 1
    if 50 <= number <= 67:
        return 2
    if 30 <= number <= 49:
        return 3
    if 80 <= number <= 96:
        return 4
    return len(REGIONS)


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
    # Grouped by region, Bangkok first, then A-Z within each region: an alphabetical list of 77
    # names scattered neighbouring provinces across the whole list.
    ordered = sorted(rows, key=lambda row: (province_region(row[0]), row[1]))
    return {
        "regions": [{"key": key, "name": name, "name_th": name_th}
                    for key, name, name_th in REGIONS],
        "provinces": [
            {
                "code": code,
                "name": name,
                "name_th": name_th,
                "district_count": int(districts),
                "region": REGIONS[province_region(code)][0]
                if province_region(code) < len(REGIONS) else "other",
            }
            for code, name, name_th, districts in ordered
        ],
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
    if boundary.admin_level == "subdistrict":
        parent = session.scalar(
            select(Boundary).where(
                Boundary.is_supported,
                Boundary.admin_level == "district",
                Boundary.admin_code == boundary.admin_code[:4],
            )
        )
        if parent is not None:
            area["district_name"] = parent.name
            area["district_name_th"] = parent.name_th
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
