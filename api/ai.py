from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from api.ai_gateway import run_ai_call
from api.dependencies import DatabaseSession
from api.langfuse import send_ai_call
from api.permissions import PlatformAdmin, SignedInMember
from api.rate_limits import limiter
from api.settings import get_settings
from core.ai_allowance import usage_view

router = APIRouter(tags=["ai"])

TEST_PROMPT_VERSION = "platform-test-v1"
TEST_INSTRUCTIONS = (
    "You are a connectivity check for the GRP AI gateway. Reply in one short sentence. "
    "Do not invent facts about floods, places or people."
)


class AiTestCall(BaseModel):
    message: str = Field(
        default="Confirm that the GRP AI gateway is working.", min_length=1, max_length=300
    )


def usage_payload(view) -> dict[str, object]:
    return {
        "tokens_used": view.tokens_used,
        "tokens_remaining": view.tokens_remaining,
        "token_limit": view.token_limit,
        "reset_at": view.reset_at.isoformat(),
        "status": view.status,
    }


@router.get(
    "/me/ai-usage",
    summary="Read my AI allowance for this month",
    openapi_extra={"x-grp-access": "protected"},
)
def my_ai_usage(principal: SignedInMember, session: DatabaseSession) -> dict[str, object]:
    settings = get_settings()
    view = usage_view(session, principal.user_id, feature_enabled=settings.ai_feature_enabled)
    return usage_payload(view)


@router.post(
    "/ai/test-call",
    summary="Make one small AI call through the gateway to test usage and limits",
    openapi_extra={"x-grp-access": "protected"},
)
async def ai_test_call(
    payload: AiTestCall,
    principal: PlatformAdmin,
    session: DatabaseSession,
    background: BackgroundTasks,
) -> dict[str, object]:
    """Platform Admin connectivity check; the tokens count against the admin's own allowance."""

    settings = get_settings()
    limiter.check(
        "ai_requests_per_person_per_hour",
        str(principal.user_id),
        settings.rate_limits["ai_requests_per_person_per_hour"],
        3600,
    )
    hub = principal.memberships[0] if principal.memberships else None
    answer = await run_ai_call(
        session,
        settings,
        user_id=principal.user_id,
        hub_id=hub.hub_id if hub else None,
        hub_code=hub.hub_code if hub else None,
        instructions=TEST_INSTRUCTIONS,
        prompt=payload.message,
        prompt_version=TEST_PROMPT_VERSION,
        export=lambda record: background.add_task(send_ai_call, settings, record),
    )
    view = usage_view(session, principal.user_id, feature_enabled=settings.ai_feature_enabled)
    return {
        "answer": answer.text,
        "label": "AI test reply. Not a GRP result.",
        "model": answer.model,
        "input_tokens": answer.input_tokens,
        "output_tokens": answer.output_tokens,
        "usage": usage_payload(view),
    }
