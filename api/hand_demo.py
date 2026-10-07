"""Pilot practice example: how a HAND flood-depth estimate works, on made-up data (Phase B1).

Admins only, like the rest of the Pilot tab. The person chooses the water height themselves;
nothing here uses a forecast, a rating curve, real terrain or an LLM, and nothing is stored or
sent anywhere. The grid is tiny pure-Python arithmetic, so it runs in the request.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from api.errors import validation_failed
from api.permissions import AdminUser
from core.hand_depth import MAX_DEMO_STAGE_M, StageError, practice

router = APIRouter(prefix="/pilot/hand-demo", tags=["pilot"])


@router.get(
    "",
    summary="The synthetic HAND practice grid for a chosen water height",
    openapi_extra={"x-grp-access": "protected"},
)
def hand_practice(
    principal: AdminUser,
    stage_m: float = Query(default=3.0, description="Water height above the channel, metres"),
) -> dict[str, Any]:
    try:
        return practice(stage_m)
    except StageError as exc:
        raise validation_failed(
            f"{exc} Choose a value from 0 to {MAX_DEMO_STAGE_M:g} metres."
        ) from exc
