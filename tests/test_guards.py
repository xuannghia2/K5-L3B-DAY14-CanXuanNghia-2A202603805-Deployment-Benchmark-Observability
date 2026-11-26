"""Integration checks use an isolated real Redis database, not an in-memory substitute."""
import concurrent.futures
import importlib
import json
import os
import sys
from pathlib import Path

import pytest
import redis
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "06-lab-complete"))
os.environ.setdefault("AGENT_API_KEY", "integration-only-generated-at-runtime")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "5")
from app import main
from app import rate_limiter, cost_guard
from app.redis_client import r

@pytest.fixture
def state_store():
    if not os.getenv("REDIS_URL"):
        pytest.skip("Set REDIS_URL to an isolated Redis test database")
    r.ping()
    # Remove only keys created by this test suite, never flush a shared server.
    keys = [*r.scan_iter("agent:rate:*"), *cost_guard.budget_keys()]
    assert r.connection_pool.connection_kwargs["db"] == 15, "Use Redis database 15 for tests"
    if keys:
        r.delete(*keys)
    yield r
    keys = [*r.scan_iter("agent:rate:*"), *cost_guard.budget_keys()]
    if keys:
        r.delete(*keys)

def test_atomic_limit_across_threads_and_reload(state_store):
    def attempt(_):
        try:
            rate_limiter.check_rate_limit("concurrent-test-key")
            return 200
        except HTTPException as exc:
            assert exc.headers["Retry-After"]
            return exc.status_code
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(attempt, range(30)))
    assert codes.count(200) == 5
    assert codes.count(429) == 25
    importlib.reload(rate_limiter)
    with pytest.raises(HTTPException) as exc:
        rate_limiter.check_rate_limit("concurrent-test-key")
    assert exc.value.status_code == 429

def test_budget_persists_and_blocks_at_boundary(state_store):
    day, month = cost_guard.budget_keys()
    value = cost_guard.record_cost(1000, 1000)
    assert value == pytest.approx(.00075)
    assert float(r.get(day)) == pytest.approx(value)
    r.set(day, str(main.settings.daily_budget_usd), ex=60)
    with pytest.raises(HTTPException) as exc:
        cost_guard.check_budget()
    assert exc.value.status_code == 402
    r.set(day, "0", ex=60)
    r.set(month, str(main.settings.monthly_budget_usd), ex=60)
    with pytest.raises(HTTPException) as exc:
        cost_guard.check_budget()
    assert exc.value.status_code == 402

def test_auth_and_invalid_input():
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
        for headers in ({}, {"X-API-Key":"wrong"}):
            assert client.post("/ask", json={"question":"hello"}, headers=headers).status_code == 401
        headers = {"X-API-Key":main.settings.agent_api_key}
        for question in ("", "   ", "x" * 2001):
            assert client.post("/ask", json={"question":question}, headers=headers).status_code == 422

def test_redis_failure_is_503_and_health_stays_live(monkeypatch):
    def unavailable(*args, **kwargs):
        raise redis.ConnectionError("private connection details")
    monkeypatch.setattr(r, "ping", unavailable)
    monkeypatch.setattr(r, "eval", unavailable)
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        resp = client.post("/ask", json={"question":"hello"},
                           headers={"X-API-Key":main.settings.agent_api_key})
        assert resp.status_code == 503
        assert "private connection details" not in resp.text

