"""Thailand bootstrap inventories exact bytes and safely reuses worker imports."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.access_models import AppUser, Base, Hub
from core.data_import_jobs import requeue_failed_import
from core.data_library_models import DataImportJob
from core.models import AssessmentState
from core.thailand_bootstrap import (
    discover_supported_sources,
    prepare_source,
    queue_prepared_source,
    require_bootstrap_context,
)


def _delivery(root: Path) -> None:
    shapes = (
        ("administrative_boundary/nation_boundary", "Thailand_Boundaries"),
        ("administrative_boundary/province_boundary", "Thailand_Province_Boundaries.dbf"),
        ("administrative_boundary/district_boundary", "Thailand_District_Boundaries"),
        (
            "administrative_boundary/sub-district_boundary",
            "Thailand_SubDistrict_Boundaries.dbf",
        ),
        ("administrative_boundary/village", "village"),
        ("evacuation_centers/shelters", "ddpm_shelters"),
        (
            "evacuation_centers/volunteer_center",
            "ddpm_civil_defense_volunteer_center",
        ),
        (
            "evacuation_centers/earlywarning_resources",
            "ddpm_earlywarning_resources",
        ),
    )
    for source_ref, stem in shapes:
        folder = root / source_ref
        folder.mkdir(parents=True)
        for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            (folder / f"{stem}{suffix}").write_bytes(f"{source_ref}:{suffix}".encode())
    hazard = root / "floods/flood_depth_rp100"
    hazard.mkdir(parents=True)
    for index in range(6):
        (hazard / f"tile-{index}.tif").write_bytes(f"tile-{index}".encode())
    vulnerability = root / "vulnerable_people"
    vulnerability.mkdir(parents=True)
    for filename in (
        "childSensitivity_01.tif",
        "elderlySensitivity_01.tif",
        "disability_total.tif",
    ):
        (vulnerability / filename).write_bytes(filename.encode())


def test_discovery_and_fingerprint_are_stable(tmp_path: Path) -> None:
    _delivery(tmp_path)
    sources = discover_supported_sources(tmp_path)

    assert [item.category for item in sources] == [
        "boundary",
        "evacuation_centers",
        "volunteer_centers",
        "early_warning_resources",
        "village_locations",
        "hazard",
        "vulnerability_child",
        "vulnerability_elderly",
        "vulnerability_disability",
    ]
    first = prepare_source(tmp_path, sources[0])
    second = prepare_source(tmp_path, sources[0])
    assert first.fingerprint == second.fingerprint
    assert first.manifest["source_sha256"] == first.fingerprint
    assert len(first.manifest["files"]) == 20


def test_same_source_is_reused_across_admins_and_failed_attempt_can_resume(
    tmp_path: Path,
) -> None:
    _delivery(tmp_path)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        first_admin = AppUser(email="first@example.test", is_platform_admin=True)
        second_admin = AppUser(email="second@example.test", is_platform_admin=True)
        hub = Hub(code="adpc", name="ADPC Hub")
        session.add_all([first_admin, second_admin, hub])
        session.commit()
        prepared = prepare_source(tmp_path, discover_supported_sources(tmp_path)[0])

        first = queue_prepared_source(session, actor_user_id=first_admin.id, prepared=prepared)
        job = session.get(DataImportJob, first.import_id)
        job.state = AssessmentState.FAILED
        job.error_code = "TRANSIENT"
        job.report = {"message": "worker stopped"}
        session.commit()

        reused = queue_prepared_source(session, actor_user_id=second_admin.id, prepared=prepared)
        assert reused.import_id == first.import_id
        assert reused.reused is True
        assert requeue_failed_import(session, reused.import_id) is True
        session.refresh(job)
        assert job.state == AssessmentState.QUEUED
        assert job.error_code is None
        assert (
            require_bootstrap_context(session, actor_email="FIRST@example.test", hub_code="ADPC").id
            == first_admin.id
        )
