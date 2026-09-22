"""Expensive SIG answers are cached only inside one login session."""

import pytest

from api.planning_cache import PlanningAnswerCache


def _put(cache: PlanningAnswerCache, user: str, session: str) -> None:
    cache.put(
        user_id=user,
        session_id=session,
        hub_id="hub-1",
        message="same question",
        place=None,
        value={"mode": "sig_evidence", "evidence": {"pack_id": "pack-1"}},
    )


def _get(cache: PlanningAnswerCache, user: str, session: str):
    return cache.get(
        user_id=user,
        session_id=session,
        hub_id="hub-1",
        message="same question",
        place=None,
    )


@pytest.mark.fast
def test_cache_is_session_bound_and_returns_a_copy() -> None:
    cache = PlanningAnswerCache()
    _put(cache, "user-a", "login-a")

    found = _get(cache, "user-a", "login-a")

    assert found is not None and found["cached"] is True
    found["evidence"]["pack_id"] = "changed"
    assert _get(cache, "user-a", "login-a")["evidence"]["pack_id"] == "pack-1"
    assert _get(cache, "user-a", "login-b") is None
    assert _get(cache, "user-b", "login-a") is None


@pytest.mark.fast
def test_logout_eviction_removes_only_that_session() -> None:
    cache = PlanningAnswerCache()
    _put(cache, "user-a", "login-a")
    _put(cache, "user-b", "login-b")

    cache.delete_session("login-a")

    assert _get(cache, "user-a", "login-a") is None
    assert _get(cache, "user-b", "login-b") is not None


@pytest.mark.fast
def test_new_login_evicts_all_prior_answers_for_that_user() -> None:
    cache = PlanningAnswerCache()
    _put(cache, "user-a", "old-login")
    _put(cache, "user-b", "other-login")

    cache.delete_user("user-a")

    assert _get(cache, "user-a", "old-login") is None
    assert _get(cache, "user-b", "other-login") is not None
