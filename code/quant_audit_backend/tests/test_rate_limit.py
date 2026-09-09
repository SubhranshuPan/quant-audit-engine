"""The rate limiter, exercised with its own low limit.

Built as a standalone app rather than by reconfiguring the shared one, so these
tests cannot leak a low limit into the rest of the suite.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.rate_limit import RateLimitMiddleware


@pytest.fixture
def app():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limit=3, window_seconds=60, exempt=("/health",))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/costly")
    def costly():
        return {"ok": True}

    return TestClient(app)


def test_requests_under_the_limit_pass(app):
    assert [app.get("/costly").status_code for _ in range(3)] == [200, 200, 200]


def test_the_fourth_request_is_throttled(app):
    for _ in range(3):
        app.get("/costly")

    response = app.get("/costly")

    assert response.status_code == 429
    assert "Rate limit reached" in response.json()["detail"]
    # Retry-After lets a well-behaved client back off instead of hammering.
    assert int(response.headers["Retry-After"]) > 0


def test_health_is_never_throttled(app):
    """A monitoring probe must not be able to lock itself out."""
    for _ in range(10):
        app.get("/costly")

    assert app.get("/health").status_code == 200


def test_clients_are_limited_independently(app):
    for _ in range(4):
        app.get("/costly", headers={"X-Forwarded-For": "10.0.0.1"})

    # A different forwarded address is a different bucket.
    assert app.get("/costly", headers={"X-Forwarded-For": "10.0.0.2"}).status_code == 200
    assert app.get("/costly", headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 429
