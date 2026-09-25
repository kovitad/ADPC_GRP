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


# A SIG pack is the expensive artefact: assemble_pack was measured at 149 s of a 200 s answer,
# while the brief that reads it costs about 40 s. Two questions about the same district therefore
# do not need two packs. Cached per login session and place so a follow-up reuses the evidence and
# only re-runs the cheap step, which is what makes "where could people move?" fast after the first
# lookup instead of another full SIG round trip.
#
# Deliberately shorter-lived than the answer cache: a pack underpins a publishable receipt, so a
# planner must not be able to publish a brief built on evidence that is quietly minutes old.
PACK_CACHE_TTL_SECONDS = 5 * 60


class SigPackCache:
    """Keep one assembled SIG pack per login session and place, in process memory only."""

    def __init__(self) -> None:
        self._packs: dict[tuple[str, str, str, str], CachedPlanningAnswer] = {}
        self._lock = Lock()

    @staticmethod
    def _key(
        user_id: str, session_id: str, hub_id: str, place: str
    ) -> tuple[str, str, str, str]:
        # Keyed on the place, not on the question: the pack describes an area, and the question only
        # decides what is said about it.
        return (user_id, session_id, hub_id, " ".join(place.casefold().split()))

    def _evict_expired(self, now: datetime) -> None:
        for key in [key for key, item in self._packs.items() if item.expires_at <= now]:
            del self._packs[key]

    def put(
        self, *, user_id: str, session_id: str, hub_id: str, place: str, pack: dict[str, Any]
    ) -> None:
        now = datetime.now(UTC)
        key = self._key(user_id, session_id, hub_id, place)
        item = CachedPlanningAnswer(
            value=deepcopy(pack),
            created_at=now,
            expires_at=now + timedelta(seconds=PACK_CACHE_TTL_SECONDS),
        )
        with self._lock:
            self._evict_expired(now)
            if len(self._packs) >= MAX_CACHE_ENTRIES and key not in self._packs:
                oldest = min(self._packs, key=lambda candidate: self._packs[candidate].created_at)
                del self._packs[oldest]
            self._packs[key] = item

    def get(
        self, *, user_id: str, session_id: str, hub_id: str, place: str
    ) -> tuple[dict[str, Any], datetime] | None:
        now = datetime.now(UTC)
        key = self._key(user_id, session_id, hub_id, place)
        with self._lock:
            self._evict_expired(now)
            item = self._packs.get(key)
            if item is None:
                return None
            return deepcopy(item.value), item.created_at

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            for key in [key for key in self._packs if key[1] == session_id]:
                del self._packs[key]

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            for key in [key for key in self._packs if key[0] == user_id]:
                del self._packs[key]

    def clear(self) -> None:
        with self._lock:
            self._packs.clear()


sig_pack_cache = SigPackCache()
