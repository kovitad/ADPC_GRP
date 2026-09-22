"""Versioned Thailand flood-risk recipe mirrored from SIG for MVP 1.

SIG remains the calculator. GRP stores the exact approved recipe it is willing to display so a
change in SIG cannot silently change the meaning of a Planner's map or evidence panel.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from core.access_models import JSON_VALUE, AuditEvent, AuditResult, utc_now
from core.db import Base

RECIPE_KEY = "thailand-flood-risk"
DEFAULT_VERSION = "sig-current-2026-09-22"
DEFAULT_WEIGHTS = {
    "population": 0.40,
    "building_density": 0.35,
    "road_distance": 0.25,
}
MISSING_DATA_POLICY = "unable_to_assess"


class RiskRecipe(Base):
    __tablename__ = "risk_recipe"
    __table_args__ = (
        UniqueConstraint("key", "version", name="uq_risk_recipe_key_version"),
        CheckConstraint("status IN ('approved', 'retired')", name="ck_risk_recipe_status"),
        CheckConstraint(
            "missing_data_policy IN ('unable_to_assess')",
            name="ck_risk_recipe_missing_data_policy",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    weights: Mapped[dict[str, float]] = mapped_column(JSON_VALUE, nullable=False)
    missing_data_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    science_owner: Mapped[str] = mapped_column(String(200), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    change_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


def recipe_payload(recipe: RiskRecipe) -> dict[str, object]:
    return {
        "key": recipe.key,
        "version": recipe.version,
        "weights": dict(recipe.weights),
        "missing_data_policy": recipe.missing_data_policy,
        "science_owner": recipe.science_owner,
        "source_ref": recipe.source_ref,
        "change_reason": recipe.change_reason,
        "status": recipe.status,
        "approved_at": recipe.approved_at.isoformat(),
    }


def active_risk_recipe(session: Session, *, create_default: bool = True) -> RiskRecipe | None:
    recipe = session.scalar(
        select(RiskRecipe).where(
            RiskRecipe.key == RECIPE_KEY,
            RiskRecipe.status == "approved",
            RiskRecipe.is_active,
        )
    )
    if recipe is not None or not create_default:
        return recipe
    # ``create_all`` test databases do not run Alembic's seed insert. The same explicit MVP 1
    # assumption is therefore materialized here on first use; production gets it from 0012.
    recipe = RiskRecipe(
        key=RECIPE_KEY,
        version=DEFAULT_VERSION,
        weights=DEFAULT_WEIGHTS,
        missing_data_policy=MISSING_DATA_POLICY,
        science_owner="SIG Thailand risk method owner",
        source_ref="SIG configurable Thailand flood-risk recipe",
        change_reason="Product Owner instructed MVP 1 to presume the supplied recipe is approved.",
        status="approved",
        is_active=True,
        approved_at=datetime.now(UTC),
    )
    session.add(recipe)
    session.flush()
    return recipe


def approve_risk_recipe(
    session: Session,
    *,
    actor_user_id: UUID,
    version: str,
    weights: dict[str, float],
    science_owner: str,
    source_ref: str,
    change_reason: str,
    now: datetime | None = None,
) -> RiskRecipe:
    required = set(DEFAULT_WEIGHTS)
    if set(weights) != required:
        raise ValueError("Provide population, building density and road distance weights")
    if any(value < 0 or value > 1 for value in weights.values()):
        raise ValueError("Each risk weight must be between 0 and 1")
    if abs(sum(weights.values()) - 1.0) > 1e-6:
        raise ValueError("Risk weights must total 100%")
    if not version.strip() or not science_owner.strip() or not source_ref.strip():
        raise ValueError("Version, science owner and SIG source reference are required")
    if not change_reason.strip():
        raise ValueError("Record why this approved recipe is being activated")

    now = now or datetime.now(UTC)
    previous = session.scalar(
        select(RiskRecipe)
        .where(RiskRecipe.key == RECIPE_KEY, RiskRecipe.is_active)
        .with_for_update()
    )
    if previous is not None and previous.version == version.strip():
        if (
            dict(previous.weights) == weights
            and previous.science_owner == science_owner.strip()
            and previous.source_ref == source_ref.strip()
        ):
            return previous
        raise ValueError("That recipe version already exists with different details")
    if previous is not None:
        previous.is_active = False
        previous.status = "retired"
    existing_version = session.scalar(
        select(RiskRecipe.id).where(
            RiskRecipe.key == RECIPE_KEY,
            RiskRecipe.version == version.strip(),
        )
    )
    if existing_version is not None:
        raise ValueError("That risk-recipe version has already been used")

    recipe = RiskRecipe(
        key=RECIPE_KEY,
        version=version.strip(),
        weights=weights,
        missing_data_policy=MISSING_DATA_POLICY,
        science_owner=science_owner.strip(),
        source_ref=source_ref.strip(),
        change_reason=change_reason.strip(),
        status="approved",
        is_active=True,
        approved_by=actor_user_id,
        approved_at=now,
    )
    session.add(recipe)
    session.flush()
    session.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            actor_kind="person",
            action="risk_recipe_approved",
            target_type="risk_recipe",
            target_id=str(recipe.id),
            old_value=recipe_payload(previous) if previous is not None else None,
            new_value=recipe_payload(recipe),
            result=AuditResult.SUCCESS,
        )
    )
    return recipe
