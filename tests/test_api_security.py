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
            "system_status": {
                "mqtt": {"connected": True, "last_update_utc": "2026-04-28T12:00:00+00:00"},
                "callback": {"last_delivered_at": "2026-04-28T12:01:00+00:00", "last_error": None},
                "webhooks": {
                    "enabled_count": 1,
                    "last_delivered_at": "2026-04-28T12:02:00+00:00",
                    "last_error": None,
                    "status_code": 200,
                },
                "sync": {"last_error": None, "submitted_jobs": 2, "successful_gcodes": 3},
                "youtube": {"ready": True, "configured": True, "enabled": True, "last_error": None},
            },
        }

    def webhooks_snapshot(self) -> list[dict[str, object]]:
        return [{"id": "hook-1", "url": "https://example.com/hook", "has_secret": True}]

    def cleanup_timelapse_cache(self, *, max_age_days: int, keep_latest: int, dry_run: bool, actor: str) -> dict[str, object]:
        return {
            "ok": True,
            "dry_run": dry_run,
            "max_age_days": max_age_days,
            "keep_latest": keep_latest,
            "delete_count": 2,
            "reclaimed_bytes": 1024,
            "actor": actor,
            "items": [],
            "errors": [],
        }


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

    def export_config_backup(self) -> dict[str, object]:
        return {"version": 1, "secrets_included": False, "printers": [{"id": "printer-1", "name": "Printer 1", "has_access_code": True}]}

    def import_config_backup(self, payload: dict[str, object], *, actor: str = "dashboard") -> dict[str, object]:
        return {"ok": True, "updated_count": len(payload.get("printers", [])), "skipped": [], "actor": actor}


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


def test_system_health_is_admin_only_and_summarizes_operations(monkeypatch) -> None:
    app = _build_app(monkeypatch)

    with TestClient(app) as client:
        viewer_response = client.get("/api/system/health", headers=_basic("viewer", "view"))
        admin_response = client.get("/api/system/health", headers=_basic("admin", "secret"))

    assert viewer_response.status_code == 403
    assert admin_response.status_code == 200
    payload = admin_response.json()
    assert payload["summary"]["printer_count"] == 1
    assert payload["summary"]["connected_printer_count"] == 1
    assert payload["summary"]["queued_job_count"] == 0
    assert payload["summary"]["youtube_ready_count"] == 1
    assert payload["storage"]["data_root"]
    assert payload["printers"][0]["webhooks"]["enabled_count"] == 1


def test_timelapse_cleanup_is_admin_only(monkeypatch) -> None:
    app = _build_app(monkeypatch)

    body = {"max_age_days": 14, "keep_latest": 2, "dry_run": True}
    with TestClient(app) as client:
        viewer_response = client.post("/api/printers/printer-1/maintenance/timelapse-cleanup", headers=_basic("viewer", "view"), json=body)
        admin_response = client.post("/api/printers/printer-1/maintenance/timelapse-cleanup", headers=_basic("admin", "secret"), json=body)

    assert viewer_response.status_code == 403
    assert admin_response.status_code == 200
    assert admin_response.json()["dry_run"] is True
    assert admin_response.json()["delete_count"] == 2


def test_config_backup_export_and_import_are_admin_only(monkeypatch) -> None:
    app = _build_app(monkeypatch)

    with TestClient(app) as client:
        viewer_export = client.get("/api/config/backup", headers=_basic("viewer", "view"))
        admin_export = client.get("/api/config/backup", headers=_basic("admin", "secret"))
        viewer_import = client.post("/api/config/backup/import", headers=_basic("viewer", "view"), json={"printers": []})
        admin_import = client.post("/api/config/backup/import", headers=_basic("admin", "secret"), json={"printers": [{"id": "printer-1"}]})

    assert viewer_export.status_code == 403
    assert admin_export.status_code == 200
    assert admin_export.json()["secrets_included"] is False
    assert "access_code" not in admin_export.json()["printers"][0]
    assert viewer_import.status_code == 403
    assert admin_import.status_code == 200
    assert admin_import.json()["updated_count"] == 1
