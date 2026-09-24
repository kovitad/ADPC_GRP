"""Describe delivered source files and report what is wrong or missing (ADR-0006).

Runs only in the worker (AD-03). It reads GIS files to describe them; it never produces a
result, never writes to the source folder, and nothing it returns may be shown to a planner.

Findings are graded so a reader can tell the three apart:
  blocker  the data cannot be loaded, or would be loaded wrongly, until someone decides
  problem  the data is usable but something in it is wrong
  known    already understood and on the backlog; shown so it is not rediscovered as a surprise
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("grp.worker.inspection")

VECTOR_SUFFIXES = (".shp", ".geojson", ".gpkg")
RASTER_SUFFIXES = (".tif", ".tiff")
# A shapefile is several files; these must sit beside the .shp or it cannot be read properly.
SHAPEFILE_SIDECARS = {
    ".shx": "geometry index",
    ".dbf": "attribute table",
    ".prj": "coordinate system",
}
LICENCE_HINTS = (
    "licence",
    "license",
    "readme",
    "metadata",
    "terms",
    "citation",
    "provenance",
    "approval",
)
# Above this, a flood depth is more likely a river or reservoir than flooding (unconfirmed).
DEEP_WATER_M = 10.0
MAX_PREVIEW_POINTS = 500
MAX_EXAMPLES = 200
# Below this share of names in common, the point layer is naming a different admin level.
NAME_AGREEMENT_FLOOR = 0.5
MAX_SAMPLE_VALUES = 4
SAMPLE_TEXT_CHARS = 60
RASTER_STAT_PIXELS = 512
RASTER_EXACT_BLOCK_PIXELS = 1024
# Field names that plausibly name the district a point claims to be in.
DISTRICT_FIELD_HINTS = ("อำเ", "ampho", "district", "amphoe")


@dataclass
class Finding:
    grade: str  # "blocker" | "problem" | "known"
    title: str
    detail: str
    affects: str = ""
    action: str = ""


@dataclass
class LayerReport:
    path: str
    kind: str  # "vector" | "raster"
    readable: bool = True
    crs: str | None = None
    crs_epsg: int | None = None
    feature_count: int | None = None
    geometry_type: str | None = None
    fields: list[dict[str, Any]] = field(default_factory=list)
    width: int | None = None
    height: int | None = None
    pixel_size_m: float | None = None
    dtype: str | None = None
    nodata: float | None = None
    band_count: int | None = None
    value_min: float | None = None
    value_max: float | None = None
    nodata_share: float | None = None
    bounds: list[float] | None = None
    value_stats_scope: str | None = None
    encoding: str | None = None
    encoding_source: str | None = None
    encoding_attempts: list[str] = field(default_factory=list)
    error_category: str | None = None
    note: str | None = None


def _crs_text(crs: Any) -> tuple[str | None, int | None]:
    if not crs:
        return None, None
    if hasattr(crs, "to_string"):
        try:
            return crs.to_string(), crs.to_epsg()
        except Exception:  # noqa: BLE001 - a malformed .prj is a finding, not a crash
            return str(crs), None
    text = str(crs)
    upper = text.upper()
    if "EPSG:" in upper:
        tail = upper.rsplit("EPSG:", 1)[-1].strip().strip('"]\'')
        if tail.isdigit():
            return text, int(tail)
    return text, None


def _looks_truncated(name: str) -> bool:
    """A Thai heading cut to the shapefile's 10-byte field-name limit loses most of itself."""

    thai = [c for c in name if "฀" <= c <= "๿"]
    return bool(thai) and len(name) <= 4


class VectorEncodingError(Exception):
    """All explicit encoding attempts failed; keep only safe diagnostic metadata."""

    def __init__(self, errors: list[Exception], attempts: list[str]) -> None:
        super().__init__(type(errors[-1]).__name__)
        self.errors = errors
        self.original = errors[-1]
        self.attempts = attempts


def _cpg_encoding(path: Path) -> str | None:
    if path.suffix.casefold() != ".shp":
        return None
    cpg = next(
        (
            candidate
            for candidate in path.parent.iterdir()
            if candidate.is_file()
            and candidate.stem.casefold()
            in {path.stem.casefold(), f"{path.stem.casefold()}.dbf"}
            and candidate.suffix.casefold() == ".cpg"
        ),
        None,
    )
    if cpg is None:
        return None
    value = cpg.read_bytes()[:128].decode("ascii", errors="ignore").strip().strip("\ufeff")
    aliases = {"65001": "UTF-8", "874": "CP874", "WINDOWS-874": "CP874"}
    return aliases.get(value.upper(), value) or None


# A byte-preserving read: every byte becomes one code point, so the original bytes can be
# recovered exactly and decoded with the encoding the file declares.
BYTE_PRESERVING_ENCODING = "ISO-8859-1"


def _encoding_candidates(path: Path) -> list[tuple[str, str]]:
    """Declared shapefile encoding first; otherwise explicit, auditable Thai fallbacks."""

    if path.suffix.casefold() != ".shp":
        return [("UTF-8", "format")]
    declared = _cpg_encoding(path)
    # A declared encoding that fails on a few truncated values is recovered rather than abandoned.
    # Guessing a different encoding decodes every row, silently and wrongly: that is how the
    # village delivery came in as mojibake while its .cpg said UTF-8. Recovery is only offered
    # when there is a declared encoding to recover to; without one, guessing is all there is.
    candidates = (
        [(declared, "cpg"), (declared, "cpg-recovered")] if declared else []
    ) + [
        ("UTF-8", "assumed"),
        ("TIS-620", "assumed"),
        ("CP874", "assumed"),
    ]
    unique: list[tuple[str, str]] = []
    seen: set[tuple[str, bool]] = set()
    for encoding, source in candidates:
        key = (encoding.casefold().replace("_", "-"), source == "cpg-recovered")
        if key not in seen:
            unique.append((encoding, source))
            seen.add(key)
    return unique


def _recover_declared_text(result, declared: str) -> int:
    """Re-decode a byte-preserving read with the encoding the file declares.

    Returns the number of values that the declared encoding could not decode. Those keep a
    replacement character rather than failing the whole file, and the caller reports the count.
    """

    replaced = 0
    for column in result[3]:
        if getattr(column, "dtype", None) is None or column.dtype != object:
            continue
        for index, value in enumerate(column):
            if not isinstance(value, str):
                continue
            raw = value.encode(BYTE_PRESERVING_ENCODING, errors="replace")
            try:
                column[index] = raw.decode(declared)
            except UnicodeDecodeError:
                column[index] = raw.decode(declared, errors="replace")
                replaced += 1
    return replaced


def read_vector_explicit(path: Path, *, read_geometry: bool = True):
    from pyogrio.raw import read as read_vector

    errors: list[Exception] = []
    candidates = _encoding_candidates(path)
    for encoding, source in candidates:
        try:
            if source == "cpg-recovered":
                result = read_vector(
                    path, read_geometry=read_geometry, encoding=BYTE_PRESERVING_ENCODING
                )
                _recover_declared_text(result, encoding)
            else:
                result = read_vector(path, read_geometry=read_geometry, encoding=encoding)
            return result, encoding, source, [item[0] for item in candidates[: len(errors) + 1]]
        except Exception as error:  # noqa: BLE001 - try the next declared fallback
            errors.append(error)
    raise VectorEncodingError(errors, [item[0] for item in candidates])


def _read_error_category(error: Exception) -> str:
    errors = error.errors if isinstance(error, VectorEncodingError) else [error]
    text = " ".join(f"{type(item).__name__} {item}" for item in errors).casefold()
    if any(word in text for word in ("truncated", "corrupt", "premature end", "unexpected eof")):
        return "truncated"
    if any(isinstance(item, UnicodeDecodeError) for item in errors) or any(
        word in text for word in ("encoding", "decode", "codec", "invalid byte sequence")
    ):
        return "encoding"
    return "unreadable"


def describe_vector(path: Path, relative: str) -> LayerReport:
    """Field names, fill rate and sample values, plus explicit text encoding."""

    report = LayerReport(path=relative, kind="vector")
    try:
        result, encoding, source, attempts = read_vector_explicit(path, read_geometry=True)
        meta, _, geometries, columns = result
        report.encoding = encoding
        report.encoding_source = source
        report.encoding_attempts = attempts
    except Exception as error:  # noqa: BLE001 - an unreadable file is a finding, not a crash
        report.readable = False
        report.error_category = _read_error_category(error)
        report.encoding_attempts = error.attempts if isinstance(error, VectorEncodingError) else []
        report.note = f"Could not be read: {type(error).__name__}"
        return report

    report.crs, report.crs_epsg = _crs_text(meta.get("crs"))
    report.geometry_type = str(meta.get("geometry_type") or "unknown")
    report.feature_count = 0 if geometries is None else len(geometries)
    for index, name in enumerate(meta["fields"]):
        values = columns[index]
        filled = [v for v in values if v is not None and str(v).strip() not in ("", "nan")]
        report.fields.append(
            {
                "name": str(name),
                "filled": len(filled),
                "empty": len(values) - len(filled),
                "samples": [str(v)[:SAMPLE_TEXT_CHARS] for v in filled[:MAX_SAMPLE_VALUES]],
                # Shapefile field names are cut to 10 bytes, which truncates Thai headings.
                "possibly_truncated": _looks_truncated(str(name)),
            }
        )
    return report


def describe_raster(path: Path, relative: str) -> LayerReport:
    """Size, CRS, resolution and value range, read at reduced resolution so big files stay fast."""

    import numpy as np
    import rasterio

    report = LayerReport(path=relative, kind="raster")
    try:
        with rasterio.open(path) as raster:
            report.crs, report.crs_epsg = _crs_text(raster.crs)
            report.width, report.height = raster.width, raster.height
            report.dtype = str(raster.dtypes[0])
            report.band_count = raster.count
            report.nodata = None if raster.nodata is None else float(raster.nodata)
            report.bounds = [round(value, 6) for value in raster.bounds]
            report.pixel_size_m = _pixel_size_m(raster)
            shape = (
                max(1, min(RASTER_STAT_PIXELS, raster.height)),
                max(1, min(RASTER_STAT_PIXELS, raster.width)),
            )
            values = raster.read(1, out_shape=shape, masked=True)
            total = int(values.size)
            missing = int(np.ma.count_masked(values))
            report.nodata_share = round(missing / total, 4) if total else None
            report.value_min, report.value_max = _full_resolution_min_max(raster)
            report.value_stats_scope = "full_resolution"
    except Exception as error:  # noqa: BLE001 - an unreadable file is a finding, not a crash
        report.readable = False
        report.note = f"Could not be read: {type(error).__name__}"
    return report


def _full_resolution_min_max(raster: Any) -> tuple[float | None, float | None]:
    """Read bounded windows so extrema are exact without loading a whole raster into memory."""

    import numpy as np
    from rasterio.windows import Window

    minimum: float | None = None
    maximum: float | None = None
    for row in range(0, raster.height, RASTER_EXACT_BLOCK_PIXELS):
        for column in range(0, raster.width, RASTER_EXACT_BLOCK_PIXELS):
            window = Window(
                column,
                row,
                min(RASTER_EXACT_BLOCK_PIXELS, raster.width - column),
                min(RASTER_EXACT_BLOCK_PIXELS, raster.height - row),
            )
            values = raster.read(1, window=window, masked=True).compressed()
            finite = values[np.isfinite(values)]
            if not finite.size:
                continue
            block_min = float(finite.min())
            block_max = float(finite.max())
            minimum = block_min if minimum is None else min(minimum, block_min)
            maximum = block_max if maximum is None else max(maximum, block_max)
    return (
        round(minimum, 4) if minimum is not None else None,
        round(maximum, 4) if maximum is not None else None,
    )


def _pixel_size_m(raster: Any) -> float | None:
    """Approximate pixel size in metres, so 90 m and 12.5 m layers can be compared."""

    size = abs(raster.transform.a)
    if raster.crs is not None and raster.crs.is_geographic:
        return round(size * 111_320, 1)
    return round(size, 2)


def _is_known_utm(layer: LayerReport) -> bool:
    """The vulnerability rasters are known to arrive in UTM; that is on the backlog already."""

    return bool(layer.crs_epsg) and 32601 <= layer.crs_epsg <= 32760


def _is_licence_file(name: str) -> bool:
    lowered = Path(name).stem.lower()
    return any(hint in lowered for hint in LICENCE_HINTS)


def _shapefile_findings(layer: LayerReport, suffixes_by_stem: dict[str, set[str]]) -> list[Finding]:
    findings: list[Finding] = []
    stem = Path(layer.path).stem
    present = suffixes_by_stem.get(stem, set())
    for suffix, meaning in SHAPEFILE_SIDECARS.items():
        if suffix not in present:
            findings.append(
                Finding(
                    "blocker",
                    f"{stem}{suffix} is missing",
                    f"A shapefile needs its {meaning} file beside it.",
                    layer.path,
                    "Ask the provider for the complete shapefile set.",
                )
            )
    return findings


def _vector_findings(
    layer: LayerReport,
    suffixes_by_stem: dict[str, set[str]],
    *,
    enforce_wgs84: bool,
) -> list[Finding]:
    findings: list[Finding] = []
    if layer.path.lower().endswith(".shp"):
        findings.extend(_shapefile_findings(layer, suffixes_by_stem))
    if layer.encoding and layer.encoding_source == "assumed":
        findings.append(
            Finding(
                "known",
                f"Text encoding was assumed to be {layer.encoding}",
                "The shapefile has no usable declared encoding, so the inspector tried "
                f"{', '.join(layer.encoding_attempts)} and opened it with {layer.encoding}. "
                "The values are readable, but the provider should confirm that interpretation.",
                layer.path,
                f"Confirm {layer.encoding} with the data team and add a same-name .cpg file.",
            )
        )
    truncated = [f["name"] for f in layer.fields if f["possibly_truncated"]]
    if truncated:
        findings.append(
            Finding(
                "known",
                "Thai column names are cut short",
                "The shapefile format cuts field names to 10 bytes, so "
                + ", ".join(truncated)
                + " lost most of their heading. Each meaning must be confirmed before it is "
                "shown to a planner (DEP-06).",
                layer.path,
                "Confirm the meanings with the provider; backlog A5.",
            )
        )
    empty = [f["name"] for f in layer.fields if f["filled"] == 0]
    if empty:
        findings.append(
            Finding(
                "problem",
                f"{len(empty)} column(s) hold no values at all",
                ", ".join(empty[:12]),
                layer.path,
                "Decide whether they are expected to be empty, or the export dropped them.",
            )
        )
    if enforce_wgs84 and layer.crs_epsg not in (4326, None):
        findings.append(
            Finding(
                "problem",
                f"{layer.path} is not EPSG:4326",
                f"It is {layer.crs}. GRP's method 1.0.0 requires EPSG:4326.",
                layer.path,
                "Reproject at load time.",
            )
        )
    if layer.crs_epsg is None and layer.readable:
        findings.append(
            Finding(
                "blocker",
                f"{layer.path} has no coordinate system",
                "Without a projection file the points cannot be placed on the earth.",
                layer.path,
                "Ask the provider for the .prj, or for the projection in writing.",
            )
        )
    return findings


def _raster_findings(
    layer: LayerReport,
    *,
    enforce_wgs84: bool,
    flood_depth_rules: bool,
) -> list[Finding]:
    findings: list[Finding] = []
    if layer.crs_epsg is None:
        findings.append(
            Finding(
                "blocker",
                f"{layer.path} has no coordinate system",
                "Without a CRS the file cannot be placed on the earth.",
                layer.path,
                "Ask the provider for the projection.",
            )
        )
    elif enforce_wgs84 and layer.crs_epsg != 4326:
        known = _is_known_utm(layer)
        findings.append(
            Finding(
                "known" if known else "problem",
                f"{layer.path} is not EPSG:4326",
                f"It is {layer.crs}. GRP's method 1.0.0 requires EPSG:4326, so this layer must "
                "be reprojected before it can be used.",
                layer.path,
                "Reproject at load time; backlog G1."
                if known
                else "Reproject, or ask the provider for EPSG:4326.",
            )
        )
    if layer.nodata is None and layer.readable:
        findings.append(
            Finding(
                "problem",
                f"{layer.path} declares no 'no data' value",
                "Every pixel therefore counts as measured, which is rarely true.",
                layer.path,
                "Confirm the no-data value with the provider.",
            )
        )
    if flood_depth_rules and layer.nodata_share is not None and layer.nodata_share > 0.5:
        findings.append(
            Finding(
                "blocker",
                f"{layer.path} is mostly empty",
                f"{layer.nodata_share:.0%} of the sampled pixels hold no value. Whether that "
                "means 'not flooded' or 'not modelled' changes the answer a planner reads, and "
                "it has not been decided (DEP-05).",
                layer.path,
                "Ask the Scientific and Data Authority for the no-data rule and the "
                "modelled-area mask.",
            )
        )
    if flood_depth_rules and layer.value_max is not None and layer.value_max > DEEP_WATER_M:
        findings.append(
            Finding(
                "problem",
                f"{layer.path} holds values over {DEEP_WATER_M:.0f}",
                f"The largest sampled value is {layer.value_max}. For a depth layer that is more "
                "likely a river or reservoir than flooding.",
                layer.path,
                "Agree a permanent-water rule: mask it, or flag it.",
            )
        )
    if flood_depth_rules and layer.value_min is not None and layer.value_min < 0:
        findings.append(
            Finding(
                "problem",
                f"{layer.path} holds negative values",
                f"The lowest sampled value is {layer.value_min}. A depth cannot be negative, so "
                "this is probably an unmarked no-data value.",
                layer.path,
                "Confirm the no-data value with the provider.",
            )
        )
    return findings


def find_problems(
    layers: list[LayerReport],
    file_names: list[str],
    *,
    profile: str = "grp_baseline",
) -> list[Finding]:
    """Grade what the layers show under the selected, explicit validation purpose."""

    suffixes_by_stem: dict[str, set[str]] = {}
    for name in file_names:
        suffixes_by_stem.setdefault(Path(name).stem, set()).add(Path(name).suffix.lower())

    findings: list[Finding] = []
    enforce_wgs84 = profile in {"grp_baseline", "flood_depth"}
    for layer in layers:
        if not layer.readable:
            if layer.error_category == "encoding":
                title = f"{layer.path} could not be decoded"
                attempted = ", ".join(layer.encoding_attempts) or "none"
                detail = (
                    "The geometry file was found, but its attribute text did not open with the "
                    f"declared or supported encodings: {attempted}."
                )
                action = (
                    "Ask the provider for the text encoding and a matching .cpg file. For Thai "
                    "shapefiles, confirm whether it is UTF-8, TIS-620 or CP874."
                )
            elif layer.error_category == "truncated":
                title = f"{layer.path} appears incomplete or damaged"
                detail = (
                    "The reader reported a truncated or corrupt dataset, not a text-encoding "
                    "issue."
                )
                action = (
                    "Ask the provider to re-export the complete dataset and verify its checksum "
                    "after transfer."
                )
            else:
                title = f"{layer.path} could not be read"
                detail = layer.note or "The GIS reader rejected this layer."
                action = (
                    "Ask the provider to verify the format and required companion files, then "
                    "re-export it if necessary."
                )
            findings.append(Finding("blocker", title, detail, layer.path, action))
            continue
        if layer.kind == "vector":
            findings.extend(
                _vector_findings(layer, suffixes_by_stem, enforce_wgs84=enforce_wgs84)
            )
        else:
            flood_rules = profile == "flood_depth" or (
                profile == "grp_baseline" and "flood" in layer.path.casefold()
            )
            findings.extend(
                _raster_findings(
                    layer,
                    enforce_wgs84=enforce_wgs84,
                    flood_depth_rules=flood_rules,
                )
            )

    if not any(_is_licence_file(name) for name in file_names):
        findings.append(
            Finding(
                "known",
                "Approval and provenance need registering",
                "The product owner confirms these files were delivered by the Data Science team. "
                "GRP still needs to register that approval with the source, edition, licence, "
                "retrieval date and checksums when the files are loaded.",
                "the whole folder",
                "Create the dataset-version records during ingestion; this is setup work, not a "
                "defect in the delivered files (ADR-0007).",
            )
        )
    return findings


def pick_district_field(field_names: Iterable[str]) -> str | None:
    """Choose the claimed-district field using the shared inspector/import rule."""

    for candidate in field_names:
        if any(hint in candidate.lower() for hint in DISTRICT_FIELD_HINTS):
            return candidate
    return None


def _pick_district_field(layer: LayerReport) -> str | None:
    """The field in a point layer that claims which area each point is in."""

    return pick_district_field(candidate["name"] for candidate in layer.fields)


def _area_names(meta: dict[str, Any], columns: Any) -> list[str]:
    """Area names, preferring a known name field, falling back to blanks."""

    fields = list(meta["fields"])
    for preferred in ("NAME2", "NAME_2", "NAME", "name"):
        if preferred in fields:
            return [str(value or "").strip() for value in columns[fields.index(preferred)]]
    return ["" for _ in (columns[0] if len(columns) else [])]


def choose_area_layer(
    area_paths: list[Path], claimed: list[str]
) -> tuple[Path | None, float]:
    """Pick the boundary layer the point layer is actually naming, and how well it agrees.

    A point layer naming districts must be checked against districts. Checked against
    sub-districts, almost every point would be reported as mismatched, which would be a made-up
    problem. The layer whose names overlap the claimed names most is the one being referred to.
    """

    wanted = {value for value in claimed if value}
    if not wanted:
        return (area_paths[0] if area_paths else None), 0.0
    scored: list[tuple[Path, float, int]] = []
    for path in area_paths:
        try:
            result, _, _, _ = read_vector_explicit(path, read_geometry=False)
            meta, _, _, columns = result
        except Exception:  # noqa: BLE001 - an unreadable layer simply cannot be chosen
            continue
        values = _area_names(meta, columns)
        names = {name for name in values if name}
        scored.append((path, len(wanted & names) / len(wanted), len(values)))
    if not scored:
        return None, 0.0
    # Several levels can name the same districts, because a sub-district layer carries its
    # district name too. Among those that agree, take the coarsest: "areas with no points" then
    # means districts with no shelters, which is the question a planner would ask.
    agreeing = [item for item in scored if item[1] >= NAME_AGREEMENT_FLOOR]
    if agreeing:
        chosen = min(agreeing, key=lambda item: item[2])
        return chosen[0], chosen[1]
    best = max(scored, key=lambda item: item[1])
    return best[0], best[1]


def cross_check_points(
    area_paths: list[Path], point_path: Path, point_layer: LayerReport
) -> tuple[list[Finding], dict[str, Any] | None]:
    """Check each point against the boundary polygons: is it where its attributes say it is?

    This is the check that found a Prachinburi shelter sitting inside Bang Bua Thong. It reports
    three things a loader must handle: points outside every area, points inside an area other
    than the one they name, and areas holding no points at all.
    """

    from shapely import from_wkb
    from shapely.strtree import STRtree

    try:
        point_result, _, _, _ = read_vector_explicit(point_path, read_geometry=True)
        point_meta, _, point_geoms, point_columns = point_result
    except Exception as error:  # noqa: BLE001 - reported, never raised
        logger.warning("Cross-check skipped: %s", type(error).__name__)
        return [], None
    if point_geoms is None:
        return [], None

    claimed_field = _pick_district_field(point_layer)
    claimed: list[str] = []
    if claimed_field is not None:
        index = list(point_meta["fields"]).index(claimed_field)
        claimed = [str(value or "").strip() for value in point_columns[index]]

    area_path, agreement = choose_area_layer(area_paths, claimed)
    if area_path is None:
        return [], None
    try:
        area_result, _, _, _ = read_vector_explicit(area_path, read_geometry=True)
        area_meta, _, area_geoms, area_columns = area_result
    except Exception as error:  # noqa: BLE001 - reported, never raised
        logger.warning("Cross-check skipped: %s", type(error).__name__)
        return [], None
    if area_geoms is None:
        return [], None

    areas = [from_wkb(item) for item in area_geoms]
    names = _area_names(area_meta, area_columns)
    points = [from_wkb(item) for item in point_geoms]
    tree = STRtree(areas)
    # Names were read from a different admin level, so a name comparison would invent problems.
    compare_names = bool(claimed) and agreement >= NAME_AGREEMENT_FLOOR

    outside = 0
    mismatches = 0
    examples: list[dict[str, str]] = []
    matched_areas: set[int] = set()
    preview: list[dict[str, Any]] = []
    for position, point in enumerate(points):
        if point is None or point.is_empty:
            outside += 1
            continue
        holder = None
        for candidate in tree.query(point):
            if areas[candidate].covers(point):
                holder = int(candidate)
                break
        status = "outside"
        if holder is None:
            outside += 1
        else:
            matched_areas.add(holder)
            status = "inside"
            if compare_names and claimed[position]:
                actual = names[holder]
                if actual and claimed[position] not in actual and actual not in claimed[position]:
                    status = "mismatched"
                    mismatches += 1
                    if len(examples) < MAX_EXAMPLES:
                        examples.append({"claims": claimed[position], "sits_in": actual})
        if len(preview) < MAX_PREVIEW_POINTS:
            preview.append({"lon": round(point.x, 6), "lat": round(point.y, 6), "status": status})

    findings = _cross_check_findings(
        total=len(points),
        outside=outside,
        mismatches=mismatches,
        example=examples[0] if examples else None,
        compared_names=compare_names,
        empty_areas=len(areas) - len(matched_areas),
        area_total=len(areas),
    )
    summary = {
        "points": len(points),
        "outside_every_area": outside,
        "mismatched": mismatches,
        "examples": examples[:10],
        "areas": len(areas),
        "areas_without_points": len(areas) - len(matched_areas),
        "claimed_field": claimed_field,
        "chosen_area_path": str(area_path),
        "compared_names": compare_names,
        "name_agreement": round(agreement, 3),
        "preview": preview,
        "preview_truncated": len(points) > len(preview),
    }
    return findings, summary


def _cross_check_findings(
    *,
    total: int,
    outside: int,
    mismatches: int,
    example: dict[str, str] | None,
    compared_names: bool,
    empty_areas: int,
    area_total: int,
) -> list[Finding]:
    findings: list[Finding] = []
    if outside:
        findings.append(
            Finding(
                "problem",
                f"{outside} of {total} points fall outside every area",
                "They belong to no area, so an assessment would silently drop them.",
                "point layer",
                "Report them to the provider; exclude them at load time with a stated count.",
            )
        )
    if mismatches and example is not None:
        findings.append(
            Finding(
                "problem",
                f"{mismatches} of {total} points are not in the area they name",
                f"For example, one says it is in {example['claims']} but its coordinates put it "
                f"in {example['sits_in']}. The coordinates and the attributes disagree, so one "
                "of them is wrong.",
                "point layer",
                "Check these with the provider; the loader must report them, not accept them.",
            )
        )
    if not compared_names:
        findings.append(
            Finding(
                "known",
                "The point layer names no area that can be checked",
                "Nothing in the point layer reliably names an area at the boundary level "
                "supplied, so membership can only be decided by geometry. That is what GRP's "
                "method does anyway.",
                "point layer",
                "Load by point-in-polygon, never by name; backlog A5.",
            )
        )
    if empty_areas and area_total:
        findings.append(
            Finding(
                "problem",
                f"{empty_areas} of {area_total} areas contain no points",
                "A completeness question for the Hub, not a software fault, but a planner must "
                "be told what 'in scope' covered.",
                "both layers",
                "Confirm with the provider whether these areas genuinely have none.",
            )
        )
    return findings


def scan_folder(
    folder: Path,
    root: Path,
    files: list[Any],
    *,
    profile: str = "grp_baseline",
) -> dict[str, Any]:
    """Describe every readable layer using an explicit validation purpose."""

    base = root.resolve()
    layers: list[LayerReport] = []
    paths: dict[str, Path] = {}
    for item in files:
        if item.suffix not in VECTOR_SUFFIXES + RASTER_SUFFIXES:
            continue
        path = (base / item.relative_path).resolve()
        if not path.is_file():
            continue
        paths[item.relative_path] = path
        if item.suffix in VECTOR_SUFFIXES:
            layers.append(describe_vector(path, item.relative_path))
        else:
            layers.append(describe_raster(path, item.relative_path))

    findings = find_problems(
        layers, [item.relative_path for item in files], profile=profile
    )
    if not layers:
        findings.append(
            Finding(
                "blocker",
                "No supported GIS layer was found",
                "This inspector currently opens Shapefile, GeoJSON, GeoPackage and GeoTIFF layers.",
                "the selected folder",
                "Ask the data team for one of the supported formats, or add a validated reader "
                "before relying on this report.",
            )
        )

    cross = None
    area_layers = _polygon_layers(layers)
    points = _largest(layers, "Point")
    if profile in {"grp_baseline", "points_boundaries"} and area_layers and points is not None:
        extra, cross = cross_check_points(
            [paths[layer.path] for layer in area_layers], paths[points.path], points
        )
        findings.extend(extra)
        if cross is not None:
            cross["point_layer"] = points.path
            chosen = cross.pop("chosen_area_path", None)
            cross["area_layer"] = next(
                (layer.path for layer in area_layers if str(paths[layer.path]) == chosen),
                area_layers[0].path,
            )

    order = {"blocker": 0, "problem": 1, "known": 2}
    findings.sort(key=lambda item: (order.get(item.grade, 3), item.title))
    profile_notes = {
        "general": (
            "Generic structural GIS checks only. No GRP-specific CRS, flood-depth or spatial "
            "membership rule was assumed."
        ),
        "grp_baseline": (
            "GRP baseline checks, including EPSG:4326, flood-depth and point-versus-boundary rules."
        ),
        "flood_depth": (
            "GRP flood-depth checks, including exact extrema and sampled no-data coverage."
        ),
        "points_boundaries": (
            "Generic structural checks plus point-versus-boundary membership where both exist."
        ),
    }
    return {
        "folder": folder.resolve().relative_to(base).as_posix() if folder != base else "",
        "profile": profile,
        "profile_note": profile_notes[profile],
        "layers": [asdict(layer) for layer in layers],
        "findings": [asdict(item) for item in findings],
        "cross_check": cross,
        "counts": {
            grade: sum(1 for item in findings if item.grade == grade)
            for grade in ("blocker", "problem", "known")
        },
    }


def _largest(layers: list[LayerReport], geometry: str) -> LayerReport | None:
    """The vector layer of this geometry type holding the most features."""

    candidates = [
        layer
        for layer in layers
        if layer.kind == "vector"
        and layer.readable
        and geometry.lower() in (layer.geometry_type or "").lower()
        and (layer.feature_count or 0) > 0
    ]
    return max(candidates, key=lambda layer: layer.feature_count or 0) if candidates else None


def _polygon_layers(layers: list[LayerReport]) -> list[LayerReport]:
    """Every usable polygon layer, largest first; the cross-check picks among them."""

    found = [
        layer
        for layer in layers
        if layer.kind == "vector"
        and layer.readable
        and "polygon" in (layer.geometry_type or "").lower()
        and (layer.feature_count or 0) > 0
    ]
    return sorted(found, key=lambda layer: layer.feature_count or 0, reverse=True)
