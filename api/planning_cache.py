"""Short-lived, login-session-bound cache for expensive SIG planning answers.

The cache is process memory only. A new login evicts prior entries for that person, logout deletes
that session's entries, and entries expire before a publish token can become stale.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

MAX_CACHE_ENTRIES = 500
CACHE_TTL_SECONDS = 10 * 60


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
