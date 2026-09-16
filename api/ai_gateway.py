"""The only module allowed to call an AI provider (Section 7.5, Section 10.4)."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.errors import GrpError
from api.langfuse import AiCallRecord
from api.settings import Settings
from core.ai_allowance import AiBlocked, next_reset, reserve, settle
from core.db import read_secret

logger = logging.getLogger("grp.ai")
BLOCKED_MESSAGES = {
    "AI_OFF": (403, "AI features are turned off. Maps, analysis and downloads still work."),
    "AI_LIMIT_REACHED": (
        429,
        "You have used your AI allowance for this month. It resets on {reset_date}. "
        "Maps, analysis and downloads still work.",
    ),
    "AI_USAGE_UNAVAILABLE": (
        503,
        "AI is not available right now. Maps, analysis and downloads still work.",
    ),
}
AI_LABEL = "AI explanation. Numbers come from the assessment result."


@dataclass(frozen=True)
class AiAnswer:
    text: str
    label: str
    model: str
    input_tokens: int
    output_tokens: int
    record: AiCallRecord


class ProviderError(RuntimeError):
    def __init__(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        super().__init__("AI provider call failed")
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def blocked(code: str, now: datetime | None = None) -> GrpError:
    status, message = BLOCKED_MESSAGES[code]
    reset_date = next_reset(now or datetime.now(UTC)).strftime("%d %B %Y")
    return GrpError(status, code, message.format(reset_date=reset_date))


def estimate_input_tokens(*parts: str) -> int:
    """Conservative estimate (about 3 characters per token) used only for the reservation."""

    return max(1, math.ceil(sum(len(part) for part in parts) / 3))


def _provider_key(settings: Settings, hub_code: str | None) -> str:
    # MVP 1 has one Hub key file (AI_KEY_FILE_ADPC). Other Hubs get their own file later.
    del hub_code
    return read_secret(settings.ai_key_file_adpc)


def _output_text(document: dict) -> str:
    parts: list[str] = []
    for item in document.get("output", []):
        if isinstance(item, dict) and item.get("type") == "message":
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("type") == "output_text":
                    parts.append(str(content.get("text", "")))
    return "\n".join(part.strip() for part in parts if part.strip())


async def call_openai(
    settings: Settings,
    *,
    instructions: str,
    prompt: str,
    hub_code: str | None,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, str, int, int]:
    model = settings.ai_model
    if not model:
        raise ProviderError()
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=settings.ai_timeout_seconds)
    try:
        response = await http_client.post(
            settings.ai_base_url or "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {_provider_key(settings, hub_code)}"},
            json={
                "model": model,
                "instructions": instructions,
                "input": prompt,
                "max_output_tokens": settings.ai_max_output_tokens,
                "store": False,
            },
        )
        document = response.json() if response.content else {}
        usage = document.get("usage", {}) if isinstance(document, dict) else {}
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        if response.status_code >= 400:
            raise ProviderError(input_tokens, output_tokens)
        text = _output_text(document)
        if not text:
            raise ProviderError(input_tokens, output_tokens)
        return text, str(document.get("model", model)), input_tokens, output_tokens
    except (httpx.HTTPError, ValueError, TypeError, OSError, RuntimeError) as error:
        if isinstance(error, ProviderError):
            raise
        raise ProviderError() from error
    finally:
        if owns_client:
            await http_client.aclose()


async def run_ai_call(
    session: Session,
    settings: Settings,
    *,
    user_id: UUID,
    hub_id: UUID | None,
    hub_code: str | None,
    instructions: str,
    prompt: str,
    prompt_version: str,
    channel: str = "web",
    provider_call=None,
    export: Callable[[AiCallRecord], None] | None = None,
) -> AiAnswer:
    """Reserve, call, settle. Every path leaves the allowance consistent (AI-09, AI-12)."""

    request_id = str(uuid4())
    started = datetime.now(UTC)
    estimate = estimate_input_tokens(instructions, prompt) + settings.ai_max_output_tokens
    try:
        month = reserve(
            session,
            user_id,
            request_id=request_id,
            estimate=estimate,
            feature_enabled=settings.ai_feature_enabled,
            now=started,
        )
        session.commit()
    except AiBlocked as error:
        session.rollback()
        raise blocked(error.code) from error
    except SQLAlchemyError as error:
        session.rollback()
        raise blocked("AI_USAGE_UNAVAILABLE") from error

    text = ""
    model = settings.ai_model or "unknown"
    input_tokens = output_tokens = 0
    outcome = "completed"
    try:
        call = provider_call or call_openai
        text, model, input_tokens, output_tokens = await call(
            settings, instructions=instructions, prompt=prompt, hub_code=hub_code
        )
    except ProviderError as error:
        outcome = "provider_error"
        input_tokens, output_tokens = error.input_tokens, error.output_tokens

    try:
        settle(
            session,
            user_id,
            month=month,
            request_id=request_id,
            hub_id=hub_id,
            channel=channel,
            provider=settings.ai_provider or "openai",
            model=model,
            prompt_version=prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            outcome=outcome,
        )
        session.commit()
    except SQLAlchemyError as error:
        session.rollback()
        logger.error("AI usage could not be recorded", extra={"request_id": request_id})
        raise blocked("AI_USAGE_UNAVAILABLE") from error

    record = AiCallRecord(
        request_id=request_id,
        user_id=str(user_id),
        hub_code=hub_code,
        channel=channel,
        model=model,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        outcome=outcome,
        started_at=started,
        ended_at=datetime.now(UTC),
    )
    if export is not None:
        export(record)
    if outcome != "completed":
        raise blocked("AI_USAGE_UNAVAILABLE")
    return AiAnswer(text, AI_LABEL, model, input_tokens, output_tokens, record)
