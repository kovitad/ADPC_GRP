"""Stored flood evidence: every fetch, and every distinct observed state (ADR-0038).

A fetch row is written for success and failure alike, so source health is read from the same
record that holds the raw bytes. An observation row is one observed state of one external
record; a later fetch that repeats the state only refreshes its times and its last fetch.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.access_models import JSON_VALUE, uuid7
from core.db import Base

FETCH_OK = "ok"
FETCH_HTTP_ERROR = "http_error"
FETCH_NETWORK_ERROR = "network_error"
FETCH_FORMAT_ERROR = "format_error"
FETCH_TOO_LARGE = "too_large"


class FloodSourceFetch(Base):
    __tablename__ = "flood_source_fetch"
    __table_args__ = (
        Index("ix_flood_source_fetch_source_time", "pilot_id", "source_id", "retrieved_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    pilot_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    byte_count: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    # Gzipped raw bytes in storage; kept for audit and replay, never served to operators.
    storage_key: Mapped[str | None] = mapped_column(String(400))
    record_count: Mapped[int | None] = mapped_column(Integer)
    new_states: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FloodObservation(Base):
    __tablename__ = "flood_observation"
    __table_args__ = (
        UniqueConstraint(
            "pilot_id", "source_id", "record_key", "state_hash", name="uq_flood_observation_state"
        ),
        Index("ix_flood_observation_last_fetch", "last_fetch_id"),
        Index("ix_flood_observation_source_observed", "pilot_id", "source_id", "observed_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    pilot_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    # SHA-256 of the provider's record ID (which can be a long URL), and the ID itself.
    record_key: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The newest time the provider said this state still held. Freshness is measured from it.
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_fetch_id: Mapped[UUID] = mapped_column(
        ForeignKey("flood_source_fetch.id", ondelete="RESTRICT"), nullable=False
    )
    last_fetch_id: Mapped[UUID] = mapped_column(
        ForeignKey("flood_source_fetch.id", ondelete="RESTRICT"), nullable=False
    )
    geometry: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, nullable=False)
    depth_cm: Mapped[float | None] = mapped_column(Float)
    state: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, nullable=False)
    underlying_sources: Mapped[list[str]] = mapped_column(JSON_VALUE, nullable=False)
    evidence_class: Mapped[str] = mapped_column(String(24), nullable=False)
    provider_judgement: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, nullable=False)
    text_sha256: Mapped[str | None] = mapped_column(String(64))
    rule_version: Mapped[str] = mapped_column(String(48), nullable=False)


class FloodAssetExposure(Base):
    """A facility's exposure and access state against one good roads snapshot (ADR-0040)."""

    __tablename__ = "flood_asset_exposure"
    __table_args__ = (
        UniqueConstraint("fetch_id", "asset_id", name="uq_flood_asset_exposure_fetch_asset"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    pilot_id: Mapped[str] = mapped_column(String(32), nullable=False)
    fetch_id: Mapped[UUID] = mapped_column(
        ForeignKey("flood_source_fetch.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[str] = mapped_column(String(80), nullable=False)
    exposure_state: Mapped[str] = mapped_column(String(32), nullable=False)
    access_state: Mapped[str] = mapped_column(String(32), nullable=False)
    nearest_road_key: Mapped[str | None] = mapped_column(String(16))
    nearest_distance_m: Mapped[int | None] = mapped_column(Integer)
    road_keys: Mapped[list[str]] = mapped_column(JSON_VALUE, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON_VALUE, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(48), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FloodIncident(Base):
    """A group of nearby flooding evidence that keeps its identity across snapshots (ADR-0041)."""

    __tablename__ = "flood_incident"
    __table_args__ = (Index("ix_flood_incident_pilot_status", "pilot_id", "status"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    pilot_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # active: flooding reported now; receding: no current evidence; closed: gone or merged.
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    road_keys: Mapped[list[str]] = mapped_column(JSON_VALUE, nullable=False)
    bbox: Mapped[list[float]] = mapped_column(JSON_VALUE, nullable=False)
    # The latest interpretation: confidence, reasons, evidence keys, facts, facilities, priority.
    summary: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(48), nullable=False)


class FloodIncidentEvent(Base):
    """What changed for an incident between consecutive snapshots."""

    __tablename__ = "flood_incident_event"
    __table_args__ = (Index("ix_flood_incident_event_pilot_at", "pilot_id", "at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    pilot_id: Mapped[str] = mapped_column(String(32), nullable=False)
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("flood_incident.id", ondelete="CASCADE"), nullable=False, index=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, nullable=False)


class FloodIncidentRun(Base):
    """One incident pass over one roads snapshot. Older snapshots are never processed again."""

    __tablename__ = "flood_incident_run"
    __table_args__ = (Index("ix_flood_incident_run_pilot_snapshot", "pilot_id", "snapshot_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    pilot_id: Mapped[str] = mapped_column(String(32), nullable=False)
    fetch_id: Mapped[UUID] = mapped_column(
        ForeignKey("flood_source_fetch.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
