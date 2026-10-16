"""Best-effort Langfuse v4 export of privacy-safe AI call metadata.

Only safe fields leave ADPC: model, prompt version, token counts, timing, outcome,
a hashed person reference and the Hub code. Prompts, answers, emails and secrets are
never sent. Failures are swallowed: the GRP database stays the official record.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from langfuse import Langfuse, propagate_attributes

from api.settings import Settings
from core.db import read_secret

logger = logging.getLogger("grp.langfuse")


@dataclass(frozen=True)
class AiCallRecord:
    request_id: str
    user_id: str
    hub_code: str | None
    channel: str
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    outcome: str
    started_at: datetime
    ended_at: datetime


def langfuse_configured(settings: Settings) -> bool:
    return bool(
        settings.langfuse_host
        and settings.langfuse_public_key
        and settings.langfuse_secret_key_file.is_file()
    )


def person_reference(user_id: str) -> str:
    """Stable pseudonymous reference so Langfuse can group calls without GRP identities."""

    return "grp-" + hashlib.sha256(f"grp-langfuse-v1:{user_id}".encode()).hexdigest()[:24]


def build_observation(record: AiCallRecord) -> dict[str, Any]:
    """Build the metadata-only Langfuse v4 observation without prompts or answers."""

    duration_ms = max(0, round((record.ended_at - record.started_at).total_seconds() * 1000))
    metadata = {
        "hub_code": record.hub_code,
        "channel": record.channel,
        "prompt_version": record.prompt_version,
        "outcome": record.outcome,
        "started_at": record.started_at.isoformat(),
        "ended_at": record.ended_at.isoformat(),
        "duration_ms": duration_ms,
    }
    usage = {
        "input": record.input_tokens,
        "output": record.output_tokens,
        "total": record.input_tokens + record.output_tokens,
    }
    return {
        "trace_name": "grp-ai-call",
        "user_id": person_reference(record.user_id),
        "metadata": metadata,
        "observation": {
            "name": record.prompt_version,
            "as_type": "generation",
            "model": record.model,
            "usage_details": usage,
            "level": "DEFAULT" if record.outcome == "completed" else "ERROR",
            "status_message": None if record.outcome == "completed" else record.outcome,
            "metadata": metadata,
        },
    }


def _export_ai_call(settings: Settings, record: AiCallRecord, client: Any | None = None) -> bool:
    owns_client = client is None
    langfuse = client or Langfuse(
        public_key=str(settings.langfuse_public_key),
        secret_key=read_secret(settings.langfuse_secret_key_file),
        base_url=str(settings.langfuse_host).rstrip("/"),
        environment=settings.langfuse_environment or settings.grp_env,
    )
    document = build_observation(record)
    try:
        trace_id = langfuse.create_trace_id(seed=record.request_id)
        with propagate_attributes(
            trace_name=document["trace_name"],
            user_id=document["user_id"],
            metadata=document["metadata"],
            environment=settings.langfuse_environment or settings.grp_env,
        ):
            observation = langfuse.start_observation(
                trace_context={"trace_id": trace_id},
                **document["observation"],
            )
            observation.end()
        langfuse.flush()
        return True
    finally:
        if owns_client:
            langfuse.shutdown()


async def send_ai_call(
    settings: Settings, record: AiCallRecord, client: Any | None = None
) -> bool:
    """Export through the Langfuse v4 OTel SDK without delaying the request event loop."""

    if not langfuse_configured(settings):
        return False
    try:
        return await asyncio.to_thread(_export_ai_call, settings, record, client)
    except Exception:  # telemetry must never fail an operational GRP response
        logger.warning("Langfuse export failed; the GRP usage record is unaffected")
        return False
