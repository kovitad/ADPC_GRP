"""Deterministic worker execution from immutable delegated-MCP evidence.

The API writes the read-only evidence pack before queueing. This module has no network client and
cannot receive a user's token. Grid outputs are explicitly labelled map-grid estimates because the
MCP display grids may be downsampled from the full-resolution summaries.
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
from scipy import ndimage
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.coastal_zoning.jobs import (
    acknowledge_cancellation,
    complete_run,
    complete_step,
    fail_step,
    start_step,
)
from core.coastal_zoning.models import (
    CoastalZoningArtifact,
    CoastalZoningRun,
    CoastalZoningStep,
    CoastalZoningZone,
    ZoningStepState,
)
from core.coastal_zoning.rules import make_zones_winwin
from core.storage import LocalStorage

_GRID_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ZONE_LABELS = {
    0: "Outside selected area",
    1: "Protect existing mangrove",
    2: "Restore mangrove loss",
    3: "Plant or reconnect",
    5: "No-build constraint",
    6: "Settlement",
    7: "Inland alternative",
    8: "Conditional review",
    9: "Not assessed",
    10: "Water",
    11: "Mangrove reserve",
    12: "Standard coastal candidate",
    13: "Raised coastal candidate",
}
_CANDIDATES = {
    2: ("restoration", "R", "Restoration"),
    3: ("restoration", "P", "Planting / reconnection"),
    7: ("inland", "A", "Inland alternative"),
    12: ("coastal", "C", "Coastal candidate"),
    13: ("coastal", "H", "Raised coastal candidate"),
}


class CoastalPipelineError(RuntimeError):
    """A safe deterministic pipeline failure."""


def process_coastal_zoning_run(session: Session, storage: LocalStorage, run_id: UUID) -> str:
    """Execute P1-P10 using only immutable artifacts and deterministic calculations."""

    current = "P1_resolve"
    try:
        run = session.get(CoastalZoningRun, run_id)
        if run is None:
            raise CoastalPipelineError("The run no longer exists.")
        if run.cancellation_requested:
            acknowledge_cancellation(session, run_id)
            return "cancelled"

        evidence = _read_evidence(session, storage, run_id)
        meta = evidence.get("_coastal_zoning")
        if not isinstance(meta, dict) or not isinstance(evidence.get("layers"), dict):
            raise CoastalPipelineError("The immutable coverage pack is incomplete.")
        _step(session, run_id, current, "Area and coverage pins verified.", meta)

        current = "P2_inventory"
        layers: dict[str, dict[str, Any]] = evidence["layers"]
        inventory = {
            name: {
                "title": layer.get("title"),
                "source": layer.get("source"),
                "licence": layer.get("licence"),
                "vintage": layer.get("vintage"),
                "validation": layer.get("validation"),
                "downsampled": layer.get("downsampled"),
            }
            for name, layer in layers.items()
            if isinstance(layer, dict)
        }
        _step(session, run_id, current, f"Inventoried {len(inventory)} governed layers.", inventory)

        current = "P3_pull_tiles"
        _step(
            session,
            run_id,
            current,
            "Reused the immutable delegated-user evidence pack; no token entered the worker.",
            {"pack_id": evidence.get("pack_id"), "layers": sorted(inventory)},
        )

        current = "P4_mosaic"
        arrays, grid = _inputs(evidence)
        _step(
            session,
            run_id,
            current,
            f"Prepared {len(arrays)} rule inputs on a {grid['w']} × {grid['h']} cell grid.",
            {"grid": grid, "map_grid_estimate": True},
        )

        current = "P5_zone"
        params = _params(run.params)
        zones, _distances = make_zones_winwin(
            valid=arrays["valid"],
            sea=arrays["sea"],
            mang_now=arrays["mang_now"],
            mang_old=arrays["mang_old"],
            dem=arrays["dem"],
            not_assessed=arrays["not_assessed"],
            wetland=arrays.get("wetland"),
            built=arrays.get("built"),
            open_land=arrays.get("open_land"),
            pop=arrays.get("pop"),
            flood=arrays.get("flood"),
            fire=arrays.get("fire"),
            cell_m=(grid["cell_y_m"], grid["cell_x_m"]),
            **params,
        )
        counts = {str(code): int((zones == code).sum()) for code in np.unique(zones)}
        _step(
            session,
            run_id,
            current,
            "Applied the pinned Mangrove 360 zoning rules.",
            {"cells": counts},
        )

        current = "P6_pick_zones"
        candidates = list(
            session.scalars(
                select(CoastalZoningZone).where(CoastalZoningZone.run_id == run_id)
            ).all()
        )
        if not candidates:
            candidates = _candidate_records(run_id, zones, grid)
            session.add_all(candidates)
        _step(
            session,
            run_id,
            current,
            f"Selected {len(candidates)} connected map-grid candidate areas.",
            {"candidate_ids": [candidate.zone_id for candidate in candidates]},
        )

        # Zone-level governed briefs require delegated MCP calls. They cannot run in this worker.
        # Keep these checkpoints explicit and do not mint or imply receipts.
        _skip(session, run_id, "P7_evidence", "No zone-level receipt requested in map-grid MVP.")
        _skip(session, run_id, "P8_brief_gate", "No AI brief or groundedness verdict was produced.")

        current = "P9_rank"
        _skip(
            session,
            run_id,
            current,
            "Candidates without receipts remain unranked; mapped area is shown for context only.",
        )

        current = "P10_package"
        result = _result_document(run, evidence, zones, grid, candidates, counts)
        artifact = session.scalar(
            select(CoastalZoningArtifact).where(
                CoastalZoningArtifact.run_id == run_id,
                CoastalZoningArtifact.kind == "result_json",
            )
        )
        if artifact is None:
            artifact = _store_result(storage, run_id, result)
            session.add(artifact)
        _step(
            session,
            run_id,
            current,
            "Packaged the interactive map-grid result.",
            {"sha256": artifact.sha256, "bytes": artifact.bytes},
        )
        session.commit()
        complete_run(session, run_id)
        return "succeeded"
    except Exception as error:
        session.rollback()
        run = session.get(CoastalZoningRun, run_id)
        if run is not None and run.status == "running":
            step = session.scalar(
                select(CoastalZoningStep).where(
                    CoastalZoningStep.run_id == run_id,
                    CoastalZoningStep.step_key == current,
                )
            )
            if step is not None and step.status != ZoningStepState.RUNNING:
                start_step(session, run_id, current)
            fail_step(
                session,
                run_id,
                current,
                code="COASTAL_PIPELINE_FAILED",
                summary=str(error)[:500] or "Coastal zoning failed.",
            )
        return "failed"


def _read_evidence(session: Session, storage: LocalStorage, run_id: UUID) -> dict[str, Any]:
    artifact = session.scalar(
        select(CoastalZoningArtifact).where(
            CoastalZoningArtifact.run_id == run_id,
            CoastalZoningArtifact.kind == "coverage_pack",
        )
    )
    if artifact is None or storage.sha256(artifact.storage_key) != artifact.sha256:
        raise CoastalPipelineError("Check live evidence coverage before running this assessment.")
    document = json.loads(storage.read_bytes(artifact.storage_key))
    evidence = document.get("evidence")
    if not isinstance(evidence, dict):
        raise CoastalPipelineError("The immutable coverage pack is invalid.")
    return evidence


def _step(
    session: Session,
    run_id: UUID,
    key: str,
    summary: str,
    detail: dict[str, object],
) -> None:
    existing = session.scalar(
        select(CoastalZoningStep).where(
            CoastalZoningStep.run_id == run_id, CoastalZoningStep.step_key == key
        )
    )
    if existing is not None and existing.status in {
        ZoningStepState.COMPLETED,
        ZoningStepState.SKIPPED,
    }:
        return
    start_step(session, run_id, key)
    complete_step(session, run_id, key, summary=summary, detail=detail)
    session.commit()


def _skip(session: Session, run_id: UUID, key: str, summary: str) -> None:
    existing = session.scalar(
        select(CoastalZoningStep).where(
            CoastalZoningStep.run_id == run_id, CoastalZoningStep.step_key == key
        )
    )
    if existing is not None and existing.status in {
        ZoningStepState.COMPLETED,
        ZoningStepState.SKIPPED,
    }:
        return
    step = start_step(session, run_id, key)
    step.status = ZoningStepState.SKIPPED
    step.summary = summary
    step.finished_at = step.started_at
    step.duration_ms = 0
    session.commit()


def _decode(layer: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    grid = layer.get("grid")
    if not isinstance(grid, dict):
        raise CoastalPipelineError("An evidence layer has no display grid.")
    width, height = grid.get("w"), grid.get("h")
    bounds = grid.get("bounds")
    if not isinstance(width, int) or not isinstance(height, int) or not isinstance(bounds, list):
        raise CoastalPipelineError("An evidence layer has an invalid grid.")
    cells = grid.get("cells")
    if grid.get("encoding") == "values" and isinstance(cells, list):
        values = [np.nan if value is None else float(value) for value in cells]
    elif grid.get("encoding") == "palette" and isinstance(cells, str):
        palette = grid.get("palette")
        if not isinstance(palette, list):
            raise CoastalPipelineError("An evidence palette is invalid.")
        values = []
        for character in cells:
            if character == ".":
                values.append(np.nan)
                continue
            index = _GRID_ALPHABET.find(character)
            if index < 0 or index >= len(palette):
                raise CoastalPipelineError("An evidence grid contains an unknown palette code.")
            values.append(float(palette[index]))
    else:
        raise CoastalPipelineError("An evidence grid uses an unsupported encoding.")
    if len(values) != width * height:
        raise CoastalPipelineError("An evidence grid has the wrong number of cells.")
    return np.asarray(values, dtype=float).reshape((height, width)), grid


def _resample(source: np.ndarray, source_grid: dict[str, Any], target_grid: dict[str, Any]):
    sw, ss, se, sn = map(float, source_grid["bounds"])
    tw, ts, te, tn = map(float, target_grid["bounds"])
    height, width = int(target_grid["h"]), int(target_grid["w"])
    xs = tw + (np.arange(width) + 0.5) * (te - tw) / width
    ys = tn - (np.arange(height) + 0.5) * (tn - ts) / height
    cols = np.floor((xs - sw) / (se - sw) * source.shape[1]).astype(int)
    rows = np.floor((sn - ys) / (sn - ss) * source.shape[0]).astype(int)
    output = np.full((height, width), np.nan)
    valid_cols = (cols >= 0) & (cols < source.shape[1])
    valid_rows = (rows >= 0) & (rows < source.shape[0])
    for row_out, row_in in enumerate(rows):
        if not valid_rows[row_out]:
            continue
        output[row_out, valid_cols] = source[row_in, cols[valid_cols]]
    return output


def _inputs(evidence: dict[str, Any]):
    layers: dict[str, dict[str, Any]] = evidence["layers"]
    profile = evidence["_coastal_zoning"].get("profile_id")
    if profile == "lamu":
        names = {
            "mang_old": "landcover_ke_gmw_v3_2class_ke_coast_1996",
            "mang_now": "landcover_ke_gmw_v3_2class_ke_coast_2020",
            "dem": "measure_ke_lamu_copdem30_elevation",
            "wetland_classes": "landcover_ke_gwl_fcs30d_ke_coast_2022",
            "land": "landcover_ke_worldcover_lamu_2021",
            "pop": "population_ke_lamu_worldpop_2020",
        }
    elif profile == "south_sumatra":
        names = {
            "mang_old": "landcover_mangrove_indonesia_2017",
            "mang_now": "landcover_mangrove_indonesia_2024",
            "dem": "measure_south_sumatra_dem",
            "land": "landcover_south_sumatra_landforms_2026",
            "pop": "population_south_sumatra_worldpop_2020",
            "flood": "hazard_flood",
            "fire": "hazard_fire",
        }
    else:
        raise CoastalPipelineError("This evidence profile is not supported.")
    current, target_grid = _decode(layers[names["mang_now"]])
    decoded: dict[str, np.ndarray] = {"mang_now": current}
    for role, name in names.items():
        if role == "mang_now":
            continue
        values, grid = _decode(layers[name])
        decoded[role] = _resample(values, grid, target_grid)
    valid = ~np.isnan(current)
    result: dict[str, np.ndarray] = {
        "valid": valid,
        "mang_now": valid & (current == 1),
        "mang_old": valid & (decoded["mang_old"] == 1),
        "dem": decoded["dem"],
        "not_assessed": valid & np.isnan(decoded["dem"]),
        "pop": decoded.get("pop"),
        "flood": decoded.get("flood"),
        "fire": decoded.get("fire"),
    }
    if profile == "lamu":
        wetland = decoded["wetland_classes"]
        land = decoded["land"]
        result.update(
            sea=valid & np.isin(wetland, [180]),
            wetland=valid & np.isin(wetland, [182, 183, 184, 185, 186, 187]),
            built=valid & (land == 50),
            open_land=valid & np.isin(land, [30, 40, 60]),
        )
    else:
        # The South Sumatra profile's supplied golden uses its explicit sea mask. The live pack
        # currently has no governed water grid, so edge-connected low DEM is a declared proxy.
        low = valid & np.isfinite(decoded["dem"]) & (decoded["dem"] <= 0)
        result.update(
            sea=_edge_connected(low),
            wetland=None,
            built=None,
            open_land=None,
        )
    west, south, east, north = map(float, target_grid["bounds"])
    latitude = (south + north) / 2
    grid = {
        "w": int(target_grid["w"]),
        "h": int(target_grid["h"]),
        "bounds": [west, south, east, north],
        "crs": "EPSG:4326",
        "cell_x_m": (east - west)
        / int(target_grid["w"])
        * 111_320
        * math.cos(math.radians(latitude)),
        "cell_y_m": (north - south) / int(target_grid["h"]) * 110_574,
    }
    return result, grid


def _edge_connected(mask: np.ndarray) -> np.ndarray:
    labels, _count = ndimage.label(mask)
    edges = np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
    return mask & np.isin(labels, edges[edges > 0])


def _params(records: list[dict[str, object]]) -> dict[str, object]:
    allowed = {
        "reserve_m",
        "mangrove_buffer_m",
        "coast_band_m",
        "coast_min_dem",
        "inland_max_mangrove_m",
        "plant_within_m",
        "min_dem",
        "settle_pop",
    }
    return {
        str(record["name"]): record["value"]
        for record in records
        if record.get("name") in allowed and isinstance(record.get("value"), (int, float))
    }


def _candidate_records(run_id: UUID, zones: np.ndarray, grid: dict[str, Any]):
    records: list[CoastalZoningZone] = []
    cell_km2 = grid["cell_x_m"] * grid["cell_y_m"] / 1_000_000
    for code, (kind, prefix, label) in _CANDIDATES.items():
        components, count = ndimage.label(zones == code)
        ranked = sorted(
            ((index, int((components == index).sum())) for index in range(1, count + 1)),
            key=lambda item: item[1],
            reverse=True,
        )[:6]
        for rank, (component, cells) in enumerate(ranked, start=1):
            mask = components == component
            records.append(
                CoastalZoningZone(
                    run_id=run_id,
                    zone_id=f"{prefix}{rank}",
                    kind=kind,
                    display_name=f"{label} {rank}",
                    rank=None,
                    score=None,
                    area_km2=round(cells * cell_km2, 4),
                    geometry=_cell_multipolygon(mask, grid),
                    facts={
                        "basis": "MCP map-grid estimate",
                        "zone_code": code,
                        "cells": cells,
                        "receipt_status": "unverified",
                    },
                    note="A place to look, not a place you may build.",
                )
            )
    return records


def _cell_multipolygon(mask: np.ndarray, grid: dict[str, Any]):
    west, south, east, north = grid["bounds"]
    width, height = grid["w"], grid["h"]
    dx, dy = (east - west) / width, (north - south) / height
    polygons = []
    for row, col in zip(*np.where(mask), strict=True):
        left, right = west + col * dx, west + (col + 1) * dx
        top, bottom = north - row * dy, north - (row + 1) * dy
        polygons.append(
            [[[left, bottom], [right, bottom], [right, top], [left, top], [left, bottom]]]
        )
    return {"type": "MultiPolygon", "coordinates": polygons}


def _result_document(run, evidence, zones, grid, candidates, counts):
    return {
        "run_id": str(run.id),
        "site_name": run.site_name,
        "country": run.country,
        "status": "succeeded",
        "evidence": {
            "pack_id": evidence.get("pack_id"),
            "gaps": evidence.get("gaps", []),
            "receipt_status": "unverified",
            "map_grid_estimate": True,
        },
        "grid": {**grid, "codes": zones.tolist()},
        "zone_legend": {str(code): label for code, label in _ZONE_LABELS.items()},
        "cell_counts": counts,
        "candidates": [
            {
                "zone_id": candidate.zone_id,
                "kind": candidate.kind,
                "name": candidate.display_name,
                "rank": candidate.rank,
                "area_km2": candidate.area_km2,
                "geometry": candidate.geometry,
                "facts": candidate.facts,
                "note": candidate.note,
                "receipt_id": None,
            }
            for candidate in candidates
        ],
        "limits": [
            "Map-grid estimate from governed live layers; no zone-level receipt was minted.",
            "Missing evidence remains unknown and is never converted to zero or low risk.",
            "A place to look, not a place you may build.",
        ],
    }


def _store_result(storage: LocalStorage, run_id: UUID, result: dict[str, Any]):
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    key = f"coastal-zoning/runs/{run_id}/result.json"
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
    try:
        digest = storage.put(key, temporary)
    finally:
        temporary.unlink(missing_ok=True)
    return CoastalZoningArtifact(
        run_id=run_id,
        kind="result_json",
        storage_key=key,
        media_type="application/json",
        bytes=len(encoded),
        sha256=digest,
    )
