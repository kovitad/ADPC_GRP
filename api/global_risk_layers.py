"""The Global Risk layer names GRP knows, in one place (ADR-0032, ADR-0033, ADR-0034).

A layer name is the key to a dataset on Global Risk: answers count and cite by it, a removal is by
it, and a contribution never overwrites an existing one. Three things read this module:

- the district summary, to say which rows are GRP's own data counted back;
- the Planning layer picker, to offer only names GRP can vouch for;
- the Share data page, to stop a name being sent twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.contribution_models import (
    APPROVED,
    CHECKING,
    FAILED,
    STAGED,
    SUBMITTING,
    SigContribution,
)
from core.planning_memory_models import PlanningChatMessage

# Global Risk's own OpenStreetMap asset layers, as its risk pack counts them (28 Sep 2026).
STANDARD_LAYERS = {
    "schools": "Schools",
    "hospitals": "Hospitals",
    "buildings": "Buildings",
    "roads": "Roads",
}
# Names a planner reads for Global Risk items GRP has seen but does not offer by default.
OTHER_LABELS = {"health_facilities": "Health facilities"}

# GRP's own datasets as ADPC contributes them to Global Risk, matched by exact layer name.
# Contributions made from Claude Desktop never reach `sig_contribution`, so this list is what
# stops GRP's data counted back to it from reading as a Global Risk addition.
GRP_ORIGIN_LAYERS = {
    "evacuation_centres_th_test": "Evacuation centres, test upload",
    "evacuation_centres_ddpm": "Evacuation centres",
    "early_warning_towers_ddpm": "Early-warning towers",
    "civil_defence_volunteer_centres_ddpm": "Civil-defence volunteer centres",
    "villages_th_register": "Villages",
    "population_th_village_register": "People, village register grid",
}

# A name is taken while Global Risk has, or may have, a contribution under it.
TAKEN_STATES = frozenset({SUBMITTING, CHECKING, STAGED, APPROVED})
# Kinds whose name is a layer or dataset that is never overwritten. Weights are left out on
# purpose: submitting weights again for the same hazard is Global Risk's documented way to adjust
# them. Documents are archived by title and may share one.
NAMESPACES = {"vector": "layer", "raster": "layer", "table": "dataset"}
# Evidence older than this may describe a layer Global Risk has since removed.
SEEN_WINDOW = timedelta(days=30)
# At most this many layers can be chosen for one Planning question.
MAX_CHOSEN = 12


def label(name: str) -> str:
    """The planner's name for a layer. An unknown layer keeps its own name, made readable."""

    return (
        STANDARD_LAYERS.get(name)
        or OTHER_LABELS.get(name)
        or GRP_ORIGIN_LAYERS.get(name)
        or name.replace("_", " ").capitalize()
    )


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def seen_in_evidence(
    session: Session,
    *,
    hub_id: UUID | None = None,
    user_id: UUID | None = None,
    now: datetime | None = None,
) -> dict[str, datetime]:
    """Layer names Global Risk counted in recent stored evidence, with when each was last seen.

    A counted layer exists on Global Risk, whoever sent it and however: this is how GRP learns of
    a layer submitted from Claude Desktop. Only the newest evidence for each place counts, so once
    Global Risk removes a layer, gathering evidence again for a place it was seen in clears it.
    """

    since = (now or datetime.now(UTC)) - SEEN_WINDOW
    query = (
        select(PlanningChatMessage.payload, PlanningChatMessage.created_at)
        .where(PlanningChatMessage.kind == "evidence", PlanningChatMessage.created_at >= since)
        .order_by(PlanningChatMessage.created_at.desc())
        .limit(500)
    )
    if hub_id is not None:
        query = query.where(PlanningChatMessage.hub_id == hub_id)
    if user_id is not None:
        query = query.where(PlanningChatMessage.user_id == user_id)
    seen: dict[str, datetime] = {}
    places: set[str] = set()
    for payload, created_at in session.execute(query):
        evidence = (payload or {}).get("evidence") or {}
        place = str((evidence.get("area") or {}).get("requested") or evidence.get("place") or "")
        if place:
            if place.casefold() in places:
                continue  # an older pack for a place already read
            places.add(place.casefold())
        counts = (evidence.get("stats") or {}).get("counts") or {}
        for name in counts:
            if isinstance(name, str) and name not in seen:
                seen[name] = _as_utc(created_at)
    return seen


def _blocks(row: SigContribution) -> bool:
    # A submit that timed out unconfirmed may have landed, so it holds the name until checked.
    return row.state in TAKEN_STATES or (
        row.state == FAILED and row.error_code == "SUBMIT_UNCONFIRMED"
    )


def taken_name(session: Session, kind: str, name: str, hub_id: UUID) -> dict[str, Any] | None:
    """Why `name` cannot be contributed again, or None when it is free.

    Names are global on Global Risk, so every Hub's contributions count. Details of another Hub's
    contribution are not shown; only that GRP already sent the name.
    """

    namespace = NAMESPACES.get(kind)
    if namespace is None or not name:
        return None
    kinds = [k for k, space in NAMESPACES.items() if space == namespace]
    rows = session.scalars(
        select(SigContribution)
        .where(SigContribution.name == name, SigContribution.kind.in_(kinds))
        .order_by(SigContribution.created_at.desc())
    ).all()
    for row in rows:
        if not _blocks(row):
            continue
        if row.hub_id != hub_id:
            return {"name": name, "source": "another_hub", "state": None,
                    "contribution_id": None, "submitted_at": None}
        return {
            "name": name,
            "source": "this_hub",
            "state": row.state,
            "contribution_id": row.contribution_id,
            "submitted_at": _as_utc(row.created_at).isoformat() if row.created_at else None,
            "row_id": str(row.id),
        }
    if namespace == "layer":
        seen = seen_in_evidence(session).get(name)
        if seen is not None:
            return {"name": name, "source": "global_risk_evidence", "state": None,
                    "contribution_id": None, "seen_at": seen.isoformat()}
    return None


def hub_contributed_layers(session: Session, hub_id: UUID) -> dict[str, str]:
    """This Hub's layers on Global Risk (approved or staged), name -> state."""

    rows = session.scalars(
        select(SigContribution)
        .where(
            SigContribution.hub_id == hub_id,
            SigContribution.kind.in_(["vector", "raster"]),
            SigContribution.state.in_([APPROVED, STAGED]),
            SigContribution.name != "",
        )
        .order_by(SigContribution.created_at.desc())
    ).all()
    found: dict[str, str] = {}
    for row in rows:
        # A hazard layer is Global Risk's water, not something counted in it.
        if row.kind == "raster" and not row.name.startswith("population_"):
            continue
        found.setdefault(row.name, row.state)
    return found


def catalog(session: Session, *, hub_id: UUID, user_id: UUID) -> list[dict[str, Any]]:
    """The layers a planner may choose for a Global Risk question, in the order to show them."""

    contributed = hub_contributed_layers(session, hub_id)
    seen = seen_in_evidence(session, hub_id=hub_id, user_id=user_id)
    items: list[dict[str, Any]] = []

    def add(name: str, group: str, note: str) -> None:
        if any(item["name"] == name for item in items):
            return
        items.append({
            "name": name,
            "label": label(name),
            "group": group,
            "grp_origin": name in GRP_ORIGIN_LAYERS or name in contributed,
            "note": note,
        })

    for name in STANDARD_LAYERS:
        add(name, "global_risk", "Global Risk, from OpenStreetMap")
    for name, state in contributed.items():
        add(name, "contributed", "Sent from this Hub" + (", staged for review" if state == STAGED
                                                        else ""))
    for name, when in sorted(seen.items(), key=lambda item: item[0]):
        add(name, "contributed" if name not in OTHER_LABELS else "global_risk",
            f"Counted in your Global Risk evidence on {when:%d %b %Y}")
    return items
