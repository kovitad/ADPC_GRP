"""Best-effort Langfuse v4 export of privacy-safe AI telemetry.

Metadata is the default. AI input/output content is exported only for explicitly allow-listed
accounts in non-production stakeholder testing. Emails, secrets, MCP arguments/results and real
session identifiers are never sent. Failures are swallowed: GRP remains the official record.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

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
    login_session_id: str | None = None


@dataclass(frozen=True)
class TraceObservation:
    """One child operation inside a question trace."""

    name: str
    as_type: str
    started_at: datetime
    ended_at: datetime
    outcome: str
    metadata: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    usage_details: dict[str, int] | None = None
    input: Any | None = None
    output: Any | None = None


@dataclass
class QuestionTrace:
    """Collect related AI and MCP operations with content disabled by default."""

    user_id: str
    login_session_id: str
    hub_code: str | None
    channel: str = "web"
    question_kind: str = "new"
    capture_content: bool = False
    input: Any | None = None
    output: Any | None = None
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    outcome: str = "running"
    error_code: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    observations: list[TraceObservation] = field(default_factory=list)

    def add_generation(
        self,
        record: AiCallRecord,
        *,
        instructions: str | None = None,
        prompt: str | None = None,
        answer: str | None = None,
    ) -> None:
        generation_input = None
        if self.capture_content:
            generation_input = {"instructions": instructions, "prompt": prompt}
        self.observations.append(
            TraceObservation(
                name=record.prompt_version,
                as_type="generation",
                started_at=record.started_at,
                ended_at=record.ended_at,
                outcome=record.outcome,
                model=record.model,
                usage_details={
                    "input": record.input_tokens,
                    "output": record.output_tokens,
                    "total": record.input_tokens + record.output_tokens,
                },
                metadata={"prompt_version": record.prompt_version},
                input=generation_input,
                output=answer if self.capture_content else None,
            )
        )

    def add_tool(
        self,
        *,
        name: str,
        started_at: datetime,
        ended_at: datetime,
        outcome: str,
        error_category: str | None = None,
        identifiers: dict[str, str] | None = None,
    ) -> None:
        metadata: dict[str, Any] = {"tool": name}
        if error_category:
            metadata["error_category"] = error_category
        if identifiers:
            metadata.update(identifiers)
        self.observations.append(
            TraceObservation(
                name=f"mcp.{name}",
                as_type="tool",
                started_at=started_at,
                ended_at=ended_at,
                outcome=outcome,
                metadata=metadata,
            )
        )

    def update(self, **metadata: Any) -> None:
        self.metadata.update({key: value for key, value in metadata.items() if value is not None})

    def finish(self, outcome: str, *, error_code: str | None = None) -> None:
        self.outcome = outcome
        self.error_code = error_code
        self.ended_at = datetime.now(UTC)


_question_trace: ContextVar[QuestionTrace | None] = ContextVar("grp_question_trace", default=None)
_export_tasks: set[asyncio.Task[bool]] = set()


def current_question_trace() -> QuestionTrace | None:
    return _question_trace.get()


@contextmanager
def collect_question_trace(trace: QuestionTrace) -> Iterator[QuestionTrace]:
    token = _question_trace.set(trace)
    try:
        yield trace
    finally:
        _question_trace.reset(token)


def langfuse_configured(settings: Settings) -> bool:
    return bool(
        settings.langfuse_host
        and settings.langfuse_public_key
        and settings.langfuse_secret_key_file.is_file()
    )


def langfuse_content_enabled(settings: Settings, email: str) -> bool:
    """Fail closed unless content export has both non-production locks enabled."""

    if settings.grp_env not in {"dev", "evaluation"} or not settings.langfuse_capture_content:
        return False
    allowed = {
        item.strip().lower()
        for item in settings.langfuse_eval_text_accounts.split(",")
        if item.strip()
    }
    return email.strip().lower() in allowed


def person_reference(user_id: str) -> str:
    """Stable pseudonymous reference so Langfuse can group calls without GRP identities."""

    return "grp-" + hashlib.sha256(f"grp-langfuse-v1:{user_id}".encode()).hexdigest()[:24]


def session_reference(login_session_id: str) -> str:
    """Group calls from one login without exporting the real GRP session identifier."""

    digest = hashlib.sha256(f"grp-langfuse-session-v1:{login_session_id}".encode()).hexdigest()
    return "grp-session-" + digest[:24]


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
        "session_id": (
            session_reference(record.login_session_id) if record.login_session_id else None
        ),
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


def _duration_ms(started_at: datetime, ended_at: datetime) -> int:
    return max(0, round((ended_at - started_at).total_seconds() * 1000))


def build_question_trace(trace: QuestionTrace) -> dict[str, Any]:
    """Build one question and its children, retaining content only when explicitly enabled."""

    ended_at = trace.ended_at or datetime.now(UTC)
    metadata = {
        "hub_code": trace.hub_code,
        "channel": trace.channel,
        "question_kind": trace.question_kind,
        "outcome": trace.outcome,
        "error_code": trace.error_code,
        "started_at": trace.started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "duration_ms": _duration_ms(trace.started_at, ended_at),
        **trace.metadata,
    }
    observations = []
    for item in trace.observations:
        child_metadata = {
            "outcome": item.outcome,
            "started_at": item.started_at.isoformat(),
            "ended_at": item.ended_at.isoformat(),
            "duration_ms": _duration_ms(item.started_at, item.ended_at),
            **item.metadata,
        }
        observation: dict[str, Any] = {
            "name": item.name,
            "as_type": item.as_type,
            "level": "DEFAULT" if item.outcome == "completed" else "ERROR",
            "status_message": None if item.outcome == "completed" else item.outcome,
            "metadata": child_metadata,
        }
        if item.model:
            observation["model"] = item.model
        if item.usage_details is not None:
            observation["usage_details"] = item.usage_details
        if item.input is not None:
            observation["input"] = item.input
        if item.output is not None:
            observation["output"] = item.output
        observations.append(observation)
    return {
        "trace_id": trace.trace_id,
        "trace_name": "grp-planning-question",
        "user_id": person_reference(trace.user_id),
        "session_id": session_reference(trace.login_session_id),
        "metadata": metadata,
        "root": {
            "name": "planning-question",
            "as_type": "chain",
            "level": "DEFAULT" if trace.outcome == "completed" else "ERROR",
            "status_message": None if trace.outcome == "completed" else trace.error_code,
            "metadata": metadata,
            **({"input": trace.input} if trace.input is not None else {}),
            **({"output": trace.output} if trace.output is not None else {}),
        },
        "observations": observations,
    }


def _new_langfuse_client(settings: Settings) -> Langfuse:
    return Langfuse(
        public_key=str(settings.langfuse_public_key),
        secret_key=read_secret(settings.langfuse_secret_key_file),
        base_url=str(settings.langfuse_host).rstrip("/"),
        environment=settings.langfuse_environment or settings.grp_env,
    )


def _export_question_trace(
    settings: Settings, trace: QuestionTrace, client: Any | None = None
) -> bool:
    owns_client = client is None
    langfuse = client or _new_langfuse_client(settings)
    document = build_question_trace(trace)
    try:
        trace_id = langfuse.create_trace_id(seed=document["trace_id"])
        with propagate_attributes(
            trace_name=document["trace_name"],
            user_id=document["user_id"],
            session_id=document["session_id"],
            metadata=document["metadata"],
            environment=settings.langfuse_environment or settings.grp_env,
        ):
            root = langfuse.start_observation(
                trace_context={"trace_id": trace_id},
                **document["root"],
            )
            for child_document in document["observations"]:
                child = root.start_observation(**child_document)
                child.end()
            root.end()
        langfuse.flush()
        return True
    finally:
        if owns_client:
            langfuse.shutdown()


async def send_question_trace(
    settings: Settings, trace: QuestionTrace, client: Any | None = None
) -> bool:
    if not langfuse_configured(settings):
        return False
    try:
        return await asyncio.to_thread(_export_question_trace, settings, trace, client)
    except Exception:  # telemetry must never fail an operational GRP response
        logger.warning("Langfuse question export failed", extra={"trace_id": trace.trace_id})
        return False


def schedule_question_trace(settings: Settings, trace: QuestionTrace) -> None:
    """Flush independently while retaining the task until it finishes."""

    task = asyncio.create_task(send_question_trace(settings, trace))
    _export_tasks.add(task)
    task.add_done_callback(_export_tasks.discard)


def _export_ai_call(settings: Settings, record: AiCallRecord, client: Any | None = None) -> bool:
    owns_client = client is None
    langfuse = client or _new_langfuse_client(settings)
    document = build_observation(record)
    try:
        trace_id = langfuse.create_trace_id(seed=record.request_id)
        with propagate_attributes(
            trace_name=document["trace_name"],
            user_id=document["user_id"],
            session_id=document["session_id"],
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
