from __future__ import annotations

import base64

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, auth_router, register_admin_auth, require_role, validate_auth_configuration


def _basic(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _build_app() -> FastAPI:
    app = FastAPI()
    register_admin_auth(app)
    app.include_router(auth_router)

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/mutate")
    async def mutate() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/operator-only")
    async def operator_only(request: Request) -> dict[str, bool]:
        require_role(request, "operator")
        return {"ok": True}

    return app


def test_auth_middleware_allows_requests_when_auth_is_disabled(monkeypatch) -> None:
    monkeypatch.delenv("REQUIRE_AUTH", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    app = _build_app()

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_validate_auth_configuration_rejects_required_auth_without_password(monkeypatch) -> None:
    monkeypatch.setenv("REQUIRE_AUTH", "true")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="REQUIRE_AUTH"):
        validate_auth_configuration()


def test_auth_middleware_rejects_invalid_basic_credentials(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    app = _build_app()

    with TestClient(app) as client:
        response = client.get("/health", headers=_basic("admin", "wrong"))

    assert response.status_code == 401


def test_auth_middleware_accepts_valid_basic_credentials(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    app = _build_app()

    with TestClient(app) as client:
        response = client.get("/health", headers=_basic("admin", "secret"))

    assert response.status_code == 200


def test_login_sets_session_and_session_endpoint_returns_csrf(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    app = _build_app()

    with TestClient(app) as client:
        login = client.post("/auth/login", json={"username": "admin", "password": "secret"})
        session = client.get("/auth/session")

    assert login.status_code == 200
    assert SESSION_COOKIE_NAME in login.cookies
    assert CSRF_COOKIE_NAME in login.cookies
    assert session.status_code == 200
    assert session.json()["authenticated"] is True
    assert session.json()["csrf_token"]
    assert session.json()["username"] == "admin"
    assert session.json()["role"] == "admin"


def test_auth_supports_role_specific_users(monkeypatch) -> None:
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv(
        "AUTH_USERS_JSON",
        '[{"username":"viewer","password":"view","role":"viewer"},{"username":"ops","password":"operate","role":"operator"}]',
    )
    app = _build_app()

    with TestClient(app) as client:
        login = client.post("/auth/login", json={"username": "ops", "password": "operate"})
        session = client.get("/auth/session")

    assert login.status_code == 200
    assert session.status_code == 200
    assert session.json()["role"] == "operator"


def test_viewer_cannot_access_operator_route(monkeypatch) -> None:
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("AUTH_USERS_JSON", '[{"username":"viewer","password":"view","role":"viewer"}]')
    app = _build_app()

    with TestClient(app) as client:
        login = client.post("/auth/login", json={"username": "viewer", "password": "view"})
        csrf = login.cookies.get(CSRF_COOKIE_NAME)
        response = client.post("/operator-only", headers={"X-CSRF-Token": csrf})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"


def test_session_auth_requires_csrf_for_mutations(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    app = _build_app()

    with TestClient(app) as client:
        login = client.post("/auth/login", json={"username": "admin", "password": "secret"})
        csrf = login.cookies.get(CSRF_COOKIE_NAME)
        rejected = client.post("/mutate")
        accepted = client.post("/mutate", headers={"X-CSRF-Token": csrf})

    assert rejected.status_code == 403
    assert accepted.status_code == 200
