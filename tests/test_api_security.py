from __future__ import annotations

import base64
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import auth_router, hash_password, register_admin_auth
from app.routers.api import router as api_router


def _basic(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


class _FakeService:
    async def state(self) -> dict[str, object]:
        return {
            "configured": True,
            "connected": True,
            "last_error": None,
            "job": {},
            "queue": {"count": 0, "next_item": None},
            "health": {"score": 98},
            "active_alerts": [],
            "printer": {"serial": "SERIAL1234", "device_type": "x1c"},
            "webhooks": [{"id": "hook-1", "url": "https://example.com/hook", "has_secret": True}],
        }

    def webhooks_snapshot(self) -> list[dict[str, object]]:
        return [{"id": "hook-1", "url": "https://example.com/hook", "has_secret": True}]


class _FakePrinterManager:
    default_id = "printer-1"

    def list_items(self) -> list[dict[str, object]]:
        return [
            {
                "id": "printer-1",
                "name": "Printer 1",
                "is_added": True,
                "config": {
                    "host": "192.168.1.10",
                    "serial": "SERIAL1234",
                    "access_code": "ACCESS99",
                    "device_type": "x1c",
                    "local_mqtt": True,
                    "enable_camera": True,
                    "disable_ssl_verify": False,
                },
            }
        ]

    def audit_snapshot(self, limit: int = 500) -> list[dict[str, object]]:
        return []


def _build_app(monkeypatch) -> FastAPI:
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password("secret"))
    monkeypatch.setenv(
        "AUTH_USERS_JSON",
        f'[{{"username":"viewer","password_hash":"{hash_password("view")}","role":"viewer"}}]',
    )

    app = FastAPI()
    register_admin_auth(app)
    app.include_router(auth_router)
    app.include_router(api_router)

    fake_manager = _FakePrinterManager()
    fake_service = _FakeService()
    monkeypatch.setattr("app.routers.api.printer_manager", fake_manager)
    monkeypatch.setattr("app.routers.api.service_or_404", lambda printer_id=None: fake_service)
    monkeypatch.setattr("app.routers.api.works_service", SimpleNamespace(list_services=lambda: []))
    return app


def test_printer_list_hides_sensitive_settings_from_non_admin(monkeypatch) -> None:
    app = _build_app(monkeypatch)

    with TestClient(app) as client:
        response = client.get("/api/printers", headers=_basic("viewer", "view"))

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["serial"] is None
    assert item["settings"] is None


def test_printer_list_masks_settings_for_admin_and_full_settings_are_admin_only(monkeypatch) -> None:
    app = _build_app(monkeypatch)

    with TestClient(app) as client:
        list_response = client.get("/api/printers", headers=_basic("admin", "secret"))
        settings_response = client.get("/api/printers/printer-1/settings", headers=_basic("admin", "secret"))

    assert list_response.status_code == 200
    item = list_response.json()["items"][0]
    assert item["serial"] == "SERIAL1234"
    assert "access_code" not in item["settings"]
    assert item["settings"]["has_access_code"] is True
    assert settings_response.status_code == 200
    assert settings_response.json()["settings"]["access_code"] == "ACCESS99"


def test_webhook_reads_are_admin_only_and_secrets_are_redacted(monkeypatch) -> None:
    app = _build_app(monkeypatch)

    with TestClient(app) as client:
        viewer_response = client.get("/api/printers/printer-1/webhooks", headers=_basic("viewer", "view"))
        admin_response = client.get("/api/printers/printer-1/webhooks", headers=_basic("admin", "secret"))

    assert viewer_response.status_code == 403
    assert admin_response.status_code == 200
    hook = admin_response.json()["items"][0]
    assert "secret" not in hook
    assert hook["has_secret"] is True


def test_state_route_omits_webhook_details_for_non_admin(monkeypatch) -> None:
    app = _build_app(monkeypatch)

    with TestClient(app) as client:
        viewer_response = client.get("/api/state", headers=_basic("viewer", "view"))
        admin_response = client.get("/api/state", headers=_basic("admin", "secret"))

    assert viewer_response.status_code == 200
    assert viewer_response.json()["webhooks"] == []
    assert admin_response.status_code == 200
    assert admin_response.json()["webhooks"][0]["has_secret"] is True
