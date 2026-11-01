"""A worker can produce a real map-grid result without receiving an MCP credential."""

import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.access_models import AppUser, Base, Hub
from core.coastal_zoning.jobs import claim_next_run, new_run_steps
from core.coastal_zoning.models import (
    CoastalZoningArtifact,
    CoastalZoningRun,
    CoastalZoningStep,
    ZoningRunState,
)
from core.coastal_zoning.pipeline import process_coastal_zoning_run
from core.storage import LocalStorage
from core.validation import sha256_file


def _palette(value: float, *, legend=None):
    return {
        "grid": {
            "w": 4,
            "h": 4,
            "bounds": [40.0, -2.04, 40.04, -2.0],
            "crs": "EPSG:4326",
            "encoding": "palette",
            "palette": [value],
            "cells": "0" * 16,
        },
        "legend": legend or {},
        "title": "Synthetic governed contract",
        "source": "test",
        "licence": "test-only",
        "vintage": "test",
        "validation": "contract-test",
    }


def test_worker_builds_result_from_immutable_pack_without_token(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    storage = LocalStorage(tmp_path / "storage")
    with Session(engine) as session:
        hub = Hub(code="adpc", name="ADPC")
        user = AppUser(email="coastal@example.test", is_platform_admin=False)
        session.add_all([hub, user])
        session.flush()
        run = CoastalZoningRun(
            hub_id=hub.id,
            owner_id=user.id,
            idempotency_key="pipeline-test",
            request_sha256="a" * 64,
            site_name="Governed coast",
            country="KE",
            aoi_geojson={"type": "Feature", "geometry": {}},
            aoi_source="drawn",
            aoi_sha256="b" * 64,
            profile="no_hazard",
            scale="local",
            params=[],
            status=ZoningRunState.QUEUED,
            versions={"rules": "test"},
            trace_id="trace-coastal-pipeline",
            support_ref="GRP-PIPELINE-TEST",
        )
        session.add(run)
        session.flush()
        session.add_all(new_run_steps(run.id))
        evidence = {
            "status": "ok",
            "pack_id": "pack-test",
            "gaps": ["Population is intentionally unavailable in this fixture."],
            "_coastal_zoning": {
                "profile_id": "lamu",
                "zoning_profile": "no_hazard",
                "geometry": {"type": "Polygon", "coordinates": []},
                "bbox": [40.0, -2.04, 40.04, -2.0],
                "area_km2": 10,
            },
            "layers": {
                "landcover_ke_gmw_v3_2class_ke_coast_1996": _palette(0),
                "landcover_ke_gmw_v3_2class_ke_coast_2020": _palette(1),
                "measure_ke_lamu_copdem30_elevation": {
                    "grid": {
                        "w": 4,
                        "h": 4,
                        "bounds": [40.0, -2.04, 40.04, -2.0],
                        "crs": "EPSG:4326",
                        "encoding": "values",
                        "cells": [10] * 16,
                    }
                },
                "landcover_ke_gwl_fcs30d_ke_coast_2022": _palette(0),
                "landcover_ke_worldcover_lamu_2021": _palette(30),
                "population_ke_lamu_worldpop_2020": {
                    "grid": {
                        "w": 4,
                        "h": 4,
                        "bounds": [40.0, -2.04, 40.04, -2.0],
                        "crs": "EPSG:4326",
                        "encoding": "values",
                        "cells": [None] * 16,
                    }
                },
            },
        }
        source = tmp_path / "coverage.json"
        source.write_text(
            json.dumps(
                {
                    "owner_id": str(user.id),
                    "hub_id": str(hub.id),
                    "geometry_sha256": "b" * 64,
                    "evidence": evidence,
                }
            ),
            encoding="utf-8",
        )
        key = "coastal-zoning/coverage/test.json"
        digest = storage.put(key, source)
        session.add(
            CoastalZoningArtifact(
                run_id=run.id,
                kind="coverage_pack",
                storage_key=key,
                media_type="application/json",
                bytes=source.stat().st_size,
                sha256=digest,
            )
        )
        session.commit()

        assert claim_next_run(session, lease_minutes=15) == run.id
        assert process_coastal_zoning_run(session, storage, run.id) == "succeeded"

        session.expire_all()
        assert session.get(CoastalZoningRun, run.id).status == ZoningRunState.SUCCEEDED
        steps = session.scalars(
            select(CoastalZoningStep).where(CoastalZoningStep.run_id == run.id)
        ).all()
        assert len(steps) == 10
        assert {step.status for step in steps} == {"completed", "skipped"}
        result_artifact = session.scalar(
            select(CoastalZoningArtifact).where(
                CoastalZoningArtifact.run_id == run.id,
                CoastalZoningArtifact.kind == "result_json",
            )
        )
        assert result_artifact is not None
        assert storage.sha256(result_artifact.storage_key) == result_artifact.sha256
        result = json.loads(storage.read_bytes(result_artifact.storage_key))
        assert result["evidence"]["pack_id"] == "pack-test"
        assert result["evidence"]["receipt_status"] == "unverified"
        assert result["limits"][1].startswith("Missing evidence remains unknown")
        assert sha256_file(source) == digest
