"""Login-session-bound cache for repeating an identical planning question instantly.

The cache is process memory only, because an answer carries a publish token bound to this login. A
new login evicts prior entries for that person and logout deletes that session's entries. The
evidence behind an answer is kept durably, per person rather than per login, in
``api.planning_memory`` (ADR-0029), so after a restart or a new login the same question only
re-runs the brief, never SIG.

An entry lives as long as its evidence may be reused. Once the evidence is older than the publish
window, the cached answer is still returned but without its publish token.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

from api.planning_memory import PACK_REUSE_SECONDS, publishable_age

MAX_CACHE_ENTRIES = 500
CACHE_TTL_SECONDS = PACK_REUSE_SECONDS


@dataclass(frozen=True)
class CachedPlanningAnswer:
    value: dict[str, Any]
    created_at: datetime
    expires_at: datetime


class PlanningAnswerCache:
    def __init__(self) -> None:
        self._answers: dict[tuple[str, str, str, str, str], CachedPlanningAnswer] = {}
        self._lock = Lock()

    @staticmethod
    def _key(
        user_id: str, session_id: str, hub_id: str, message: str, place: str | None
    ) -> tuple[str, str, str, str, str]:
        return (
            user_id,
            session_id,
            hub_id,
            " ".join(message.casefold().split()),
            " ".join((place or "").casefold().split()),
        )

    def put(
        self,
        *,
        user_id: str,
        session_id: str,
        hub_id: str,
        message: str,
        place: str | None,
        value: dict[str, Any],
    ) -> None:
        now = datetime.now(UTC)
        item = CachedPlanningAnswer(
            value=deepcopy(value),
            created_at=now,
            expires_at=now + timedelta(seconds=CACHE_TTL_SECONDS),
        )
        key = self._key(user_id, session_id, hub_id, message, place)
        with self._lock:
            self._evict_expired(now)
            if len(self._answers) >= MAX_CACHE_ENTRIES and key not in self._answers:
                oldest = min(
                    self._answers,
                    key=lambda candidate: self._answers[candidate].created_at,
                )
                del self._answers[oldest]
            self._answers[key] = item

    def get(
        self,
        *,
        user_id: str,
        session_id: str,
        hub_id: str,
        message: str,
        place: str | None,
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        key = self._key(user_id, session_id, hub_id, message, place)
        with self._lock:
            self._evict_expired(now)
            item = self._answers.get(key)
            if item is None:
                return None
            answer = deepcopy(item.value)
        answer["cached"] = True
        answer["cached_at"] = item.created_at.isoformat()
        assembled = answer.get("evidence_assembled_at")
        if assembled:
            assembled_at = datetime.fromisoformat(str(assembled))
            answer["evidence_age_seconds"] = round((now - assembled_at).total_seconds())
            if answer.get("publish_token") and not publishable_age(assembled_at, now):
                answer["publish_token"] = None
                answer["publish_needs_fresh_evidence"] = True
        return answer

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            for key in [key for key in self._answers if key[1] == session_id]:
                del self._answers[key]

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            for key in [key for key in self._answers if key[0] == user_id]:
                del self._answers[key]

    def clear(self) -> None:
        with self._lock:
            self._answers.clear()

    def _evict_expired(self, now: datetime) -> None:
        for key in [key for key, item in self._answers.items() if item.expires_at <= now]:
            del self._answers[key]


planning_answer_cache = PlanningAnswerCache()
