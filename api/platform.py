from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from api.dependencies import DatabaseSession
from api.errors import GrpError, not_found, validation_failed
from api.langfuse import langfuse_configured
from api.permissions import PlatformAdmin
from api.settings import get_settings
from core.access_models import AuditEvent, AuditResult
from core.ai_allowance import (
    MAX_TOKEN_LIMIT,
    MIN_TOKEN_LIMIT,
    load_setting,
    people_usage,
    reset_person_usage,
    update_setting,
)
from grp.admin import (
    HubAccessDenied,
    ItemNotFound,
    create_hub_as_actor,
    list_all_hubs,
    set_hub_status,
)

router = APIRouter(prefix="/platform", tags=["platform"])


class AiUsageSettingUpdate(BaseModel):
    token_limit_per_person: int = Field(ge=MIN_TOKEN_LIMIT, le=MAX_TOKEN_LIMIT)
    ai_enabled: bool


class HubCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=200)


class HubStatusUpdate(BaseModel):
    status: Literal["active", "closed"]


def _setting_payload(setting, feature_enabled: bool) -> dict[str, object]:
    return {
        "token_limit_per_person": setting.token_limit_per_person,
        "ai_enabled": setting.ai_enabled,
        "ai_feature_enabled": feature_enabled,
        "changed_by": str(setting.changed_by) if setting.changed_by else None,
        "changed_at": setting.changed_at.isoformat() if setting.changed_at else None,
    }


@router.get(
    "/ai-usage/setting",
    summary="Read the platform AI usage setting",
    openapi_extra={"x-grp-access": "protected"},
)
def read_ai_setting(principal: PlatformAdmin, session: DatabaseSession) -> dict[str, object]:
    del principal
    return _setting_payload(load_setting(session), get_settings().ai_feature_enabled)


@router.put(
    "/ai-usage/setting",
    summary="Set the one token limit and turn AI on or off",
    openapi_extra={"x-grp-access": "protected"},
)
def change_ai_setting(
    update: AiUsageSettingUpdate, principal: PlatformAdmin, session: DatabaseSession
) -> dict[str, object]:
    try:
        setting = update_setting(
            session,
            actor_user_id=principal.user_id,
            token_limit_per_person=update.token_limit_per_person,
            ai_enabled=update.ai_enabled,
        )
        session.commit()
    except ValueError as error:
        session.rollback()
        raise validation_failed(str(error)) from error
    return _setting_payload(setting, get_settings().ai_feature_enabled)


@router.get(
    "/ai-usage/people",
    summary="Per-person AI usage for this month",
    openapi_extra={"x-grp-access": "protected"},
)
def ai_usage_people(principal: PlatformAdmin, session: DatabaseSession) -> dict[str, object]:
    people = people_usage(session, feature_enabled=get_settings().ai_feature_enabled)
    session.add(
        AuditEvent(
            actor_user_id=principal.user_id,
            actor_kind="person",
            action="admin_viewed_usage",
            target_type="ai_allowance",
            target_id="all",
            result=AuditResult.SUCCESS,
        )
    )
    session.commit()
    return {"people": people}


@router.post(
    "/ai-usage/people/{user_id}/reset",
    summary="Reset one person's AI usage for this month (ADR-0003)",
    openapi_extra={"x-grp-access": "protected"},
)
def reset_ai_usage(
    user_id: UUID, principal: PlatformAdmin, session: DatabaseSession
) -> dict[str, object]:
    try:
        previous = reset_person_usage(session, actor_user_id=principal.user_id, user_id=user_id)
        session.commit()
    except LookupError as error:
        session.rollback()
        raise not_found() from error
    return {"changed": True, "tokens_used_before": previous, "message": "AI usage reset"}


@router.get(
    "/hubs",
    summary="List all Hubs",
    openapi_extra={"x-grp-access": "protected"},
)
def platform_hubs(principal: PlatformAdmin, session: DatabaseSession) -> dict[str, object]:
    del principal
    return {"hubs": list_all_hubs(session)}


def _domain_error(error: ValueError) -> GrpError:
    if isinstance(error, ItemNotFound):
        return not_found()
    if isinstance(error, HubAccessDenied):
        return GrpError(403, "ACCESS_NOT_AUTHORIZED", "Access not authorized.")
    return validation_failed(str(error))


@router.post(
    "/hubs",
    summary="Create a Hub",
    openapi_extra={"x-grp-access": "protected"},
)
def create_hub(
    payload: HubCreate, principal: PlatformAdmin, session: DatabaseSession
) -> dict[str, object]:
    try:
        result = create_hub_as_actor(
            session, actor_user_id=principal.user_id, code=payload.code, name=payload.name
        )
        session.commit()
    except ValueError as error:
        session.rollback()
        raise _domain_error(error) from error
    return {"changed": result.changed, "message": result.message}


@router.patch(
    "/hubs/{hub_code}",
    summary="Close or reopen a Hub",
    openapi_extra={"x-grp-access": "protected"},
)
def change_hub_status(
    hub_code: str, payload: HubStatusUpdate, principal: PlatformAdmin, session: DatabaseSession
) -> dict[str, object]:
    try:
        result = set_hub_status(
            session, actor_user_id=principal.user_id, hub_code=hub_code, hub_status=payload.status
        )
        session.commit()
    except ValueError as error:
        session.rollback()
        raise _domain_error(error) from error
    return {"changed": result.changed, "message": result.message}


@router.get(
    "/health",
    summary="System health for the Platform Admin",
    openapi_extra={"x-grp-access": "protected"},
)
def platform_health(principal: PlatformAdmin, session: DatabaseSession) -> dict[str, object]:
    del principal
    settings = get_settings()
    try:
        session.execute(text("SELECT 1"))
        database = "ready"
    except Exception:  # noqa: BLE001 - health must report, never raise
        database = "unavailable"
    return {
        "api": "up",
        "database": database,
        "environment": settings.grp_env,
        "ai_feature_enabled": settings.ai_feature_enabled,
        "ai_provider_key_present": settings.ai_key_file_adpc.is_file(),
        "ai_model": settings.ai_model,
        "langfuse_configured": langfuse_configured(settings),
        "sig_service_login_configured": settings.sig_service_token_hash_file.is_file(),
        "worker": "not monitored until the job queue exists (Increment 1)",
    }
