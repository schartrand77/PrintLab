from __future__ import annotations

import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import register_admin_auth


def _basic(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def test_auth_middleware_allows_requests_when_password_is_unset(monkeypatch) -> None:
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    app = FastAPI()
    register_admin_auth(app)

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_auth_middleware_rejects_invalid_credentials(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    app = FastAPI()
    register_admin_auth(app)

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/health", headers=_basic("admin", "wrong"))

    assert response.status_code == 401


def test_auth_middleware_accepts_valid_credentials(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    app = FastAPI()
    register_admin_auth(app)

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/health", headers=_basic("admin", "secret"))

    assert response.status_code == 200
