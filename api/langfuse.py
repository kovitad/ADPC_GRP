"""Best-effort Langfuse (hosted) export of AI call metadata (Section 14.1).

Only safe fields leave ADPC: model, prompt version, token counts, timing, outcome,
a hashed person reference and the Hub code. Prompts, answers, emails and secrets are
never sent. Failures are swallowed: the GRP database stays the official record.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

import httpx

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


def build_batch(settings: Settings, record: AiCallRecord) -> dict[str, object]:
    trace_id = record.request_id
    metadata = {
        "hub_code": record.hub_code,
        "channel": record.channel,
        "prompt_version": record.prompt_version,
        "outcome": record.outcome,
    }
    usage = {
        "input": record.input_tokens,
        "output": record.output_tokens,
        "total": record.input_tokens + record.output_tokens,
    }
    return {
        "batch": [
            {
                "id": str(uuid4()),
                "timestamp": record.started_at.isoformat(),
                "type": "trace-create",
                "body": {
                    "id": trace_id,
                    "name": "grp-ai-call",
                    "userId": person_reference(record.user_id),
                    "metadata": metadata,
                    "environment": settings.langfuse_environment or settings.grp_env,
                },
            },
            {
                "id": str(uuid4()),
                "timestamp": record.ended_at.isoformat(),
                "type": "generation-create",
                "body": {
                    "id": f"{trace_id}-generation",
                    "traceId": trace_id,
                    "name": record.prompt_version,
                    "model": record.model,
                    "startTime": record.started_at.isoformat(),
                    "endTime": record.ended_at.isoformat(),
                    "usage": {**usage, "unit": "TOKENS"},
                    "usageDetails": {"input": usage["input"], "output": usage["output"]},
                    "level": "DEFAULT" if record.outcome == "completed" else "ERROR",
                    "metadata": metadata,
                },
            },
        ]
    }


async def send_ai_call(
    settings: Settings, record: AiCallRecord, client: httpx.AsyncClient | None = None
) -> bool:
    if not langfuse_configured(settings):
        return False
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=10.0)
    try:
        response = await http_client.post(
            f"{str(settings.langfuse_host).rstrip('/')}/api/public/ingestion",
            auth=(
                str(settings.langfuse_public_key),
                read_secret(settings.langfuse_secret_key_file),
            ),
            json=build_batch(settings, record),
        )
        response.raise_for_status()
        return True
    except (httpx.HTTPError, OSError, RuntimeError):
        logger.warning("Langfuse export failed; the GRP usage record is unaffected")
        return False
    finally:
        if owns_client:
            await http_client.aclose()
