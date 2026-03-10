from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import register_admin_auth
from app.main import create_app
from app.routers.api import router as api_router
from app.services import MakerworksSubmitError, PrinterService, WorksService


def test_build_url_rejects_absolute_urls() -> None:
    service = WorksService()
    with pytest.raises(ValueError):
        service._build_url("https://makerworks.local", "https://evil.example/path")


def test_build_url_normalizes_missing_leading_slash() -> None:
    service = WorksService()
    url = service._build_url("https://makerworks.local/", "v1/orders")
    assert url == "https://makerworks.local/v1/orders"


def test_request_allowlist_rejects_unlisted_path(monkeypatch) -> None:
    monkeypatch.setenv("MAKERWORKS_BASE_URL", "https://makerworks.local")
    monkeypatch.setenv("MAKERWORKS_ALLOWED_PATHS", "/health,/v1/orders")
    service = WorksService()

    with pytest.raises(ValueError, match="Path is not allowed"):
        service._ensure_request_allowed(service._get_config("makerworks"), "GET", "/v1/admin")


def test_request_allowlist_rejects_unlisted_method(monkeypatch) -> None:
    monkeypatch.setenv("MAKERWORKS_BASE_URL", "https://makerworks.local")
    monkeypatch.setenv("MAKERWORKS_ALLOWED_PATHS", "/v1/orders")
    monkeypatch.setenv("MAKERWORKS_ALLOWED_METHODS", "GET")
    service = WorksService()

    with pytest.raises(ValueError, match="Method is not allowed"):
        service._ensure_request_allowed(service._get_config("makerworks"), "POST", "/v1/orders")


def test_makerworks_library_paths_are_kept_when_env_allowlist_is_legacy(monkeypatch) -> None:
    monkeypatch.setenv("MAKERWORKS_BASE_URL", "https://makerworks.local")
    monkeypatch.setenv("MAKERWORKS_ALLOWED_PATHS", "/health")
    service = WorksService()

    cfg = service._get_config("makerworks")

    assert "/health" in cfg["allowed_paths"]
    assert "/api/models" in cfg["allowed_paths"]


def test_makerworks_job_callback_path_is_kept_when_env_allowlist_is_legacy(monkeypatch) -> None:
    monkeypatch.setenv("MAKERWORKS_BASE_URL", "https://makerworks.local")
    monkeypatch.setenv("MAKERWORKS_ALLOWED_PATHS", "/health")
    monkeypatch.setenv("MAKERWORKS_JOB_CALLBACK_PATH_TEMPLATE", "/api/printlab/jobs/{job_id}")
    service = WorksService()

    cfg = service._get_config("makerworks")

    assert "/api/printlab/jobs" in cfg["allowed_paths"]


def test_secret_file_is_used_for_service_api_key(monkeypatch) -> None:
    secret_file = Path("data/test-makerworks-api-key.txt")
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text("from-file\n", encoding="utf-8")
    try:
        monkeypatch.delenv("MAKERWORKS_API_KEY", raising=False)
        monkeypatch.setenv("MAKERWORKS_API_KEY_FILE", str(secret_file.resolve()))

        service = WorksService()

        assert service._get_config("makerworks")["api_key"] == "from-file"
    finally:
        secret_file.unlink(missing_ok=True)


def test_makerworks_library_normalizes_common_payload(monkeypatch) -> None:
    monkeypatch.setenv("MAKERWORKS_BASE_URL", "https://makerworks.local")

    class FakeResponse:
        ok = True
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict[str, object]:
            return {
                "models": [
                    {
                        "id": 42,
                        "title": "Desk Organizer",
                        "material": "PLA",
                        "coverImagePath": "/thumbs/42.png",
                        "filePath": "/files/42.3mf",
                        "href": "/models/42",
                        "creditName": "PrintLab",
                        "tags": ["storage", "desk"],
                        "updated_at": "2026-03-09T12:00:00Z",
                    }
                ],
                "total": 1,
            }

        @property
        def text(self) -> str:
            return ""

    monkeypatch.setattr("app.services.requests.request", lambda **kwargs: FakeResponse())
    service = WorksService()

    result = service.makerworks_library_sync(query="desk")

    assert result["count"] == 1
    assert result["total"] == 1
    assert result["items"][0]["id"] == "42"
    assert result["items"][0]["name"] == "Desk Organizer"
    assert result["items"][0]["summary"] == "PLA"
    assert result["items"][0]["author"] == "PrintLab"
    assert result["items"][0]["thumbnail_url"] == "https://makerworks.local/thumbs/42.png"
    assert result["items"][0]["download_url"] == "https://makerworks.local/files/42.3mf"
    assert result["items"][0]["model_url"] == "https://makerworks.local/models/42"
    assert result["items"][0]["printer_handoff_ready"] is True


def test_makerworks_library_item_normalizes_detail_payload(monkeypatch) -> None:
    monkeypatch.setenv("MAKERWORKS_BASE_URL", "https://makerworks.local")

    class FakeResponse:
        ok = True
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict[str, object]:
            return {
                "model": {
                    "id": "widget-1",
                    "title": "Widget",
                    "description": "Test model",
                    "filePath": "/files/widget-1.3mf",
                }
            }

        @property
        def text(self) -> str:
            return ""

    monkeypatch.setattr("app.services.requests.request", lambda **kwargs: FakeResponse())
    service = WorksService()

    result = service.makerworks_library_item_sync("widget-1")

    assert result["item"]["id"] == "widget-1"
    assert result["item"]["name"] == "Widget"
    assert result["item"]["printer_handoff_ready"] is True
    assert result["item"]["download_url"] == "https://makerworks.local/files/widget-1.3mf"
    assert result["item"]["raw"]["title"] == "Widget"


def test_makerworks_library_surfaces_upstream_http_errors(monkeypatch) -> None:
    monkeypatch.setenv("MAKERWORKS_BASE_URL", "https://makerworks.local")

    class FakeResponse:
        ok = False
        status_code = 404
        headers = {"content-type": "text/html; charset=utf-8"}

        @property
        def text(self) -> str:
            return "<html><body>Not found</body></html>"

    monkeypatch.setattr("app.services.requests.request", lambda **kwargs: FakeResponse())
    service = WorksService()

    with pytest.raises(RuntimeError, match="MakerWorks library request failed"):
        service.makerworks_library_sync()


def test_resolve_sd_path_from_filename_only() -> None:
    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )

    class FakeFtp:
        def retrlines(self, command: str, callback) -> None:
            if command == "LIST /":
                callback("-rw-r--r-- 1 user group 123 Mar 09 10:00 figurine_plate_2.gcode.3mf")

    resolved = service._resolve_sd_path_sync(FakeFtp(), "figurine_plate_2.gcode.3mf")
    assert resolved == "/figurine_plate_2.gcode.3mf"


def test_job_thumbnail_url_uses_active_context_for_internal_plate_path() -> None:
    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )
    service._active_job_context = {"file_path": "/cache/figurine_plate_2.gcode.3mf"}

    url = service._job_thumbnail_url("/data/Metadata/plate_1.gcode", "figurine_plate_2.gcode.3mf")

    assert url == "/api/printers/printer-1/sd/thumbnail?path=%2Fcache%2Ffigurine_plate_2.gcode.3mf"


def test_resolve_sd_path_from_internal_plate_path_uses_current_subtask_name() -> None:
    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )

    class FakePrintJob:
        subtask_name = "CubeStack_desk_lamp_(no_glue,_no_supports)"

    class FakeDevice:
        print_job = FakePrintJob()

    class FakeClient:
        def get_device(self):
            return FakeDevice()

    class FakeFtp:
        def retrlines(self, command: str, callback) -> None:
            if command == "LIST /cache":
                callback("-rw-r--r-- 1 user group 123 Mar 09 10:00 CubeStack_desk_lamp_(no_glue,_no_supports).gcode.3mf")

    service.client = FakeClient()

    resolved = service._resolve_sd_path_sync(FakeFtp(), "/data/Metadata/plate_1.gcode")
    assert resolved == "/cache/CubeStack_desk_lamp_(no_glue,_no_supports).gcode.3mf"


def test_openapi_contains_makerworks_library_paths() -> None:
    schema = create_app().openapi()
    assert "/api/works/makerworks/library" in schema["paths"]
    assert "/api/printers/{printer_id}/works/makerworks/library" in schema["paths"]


def test_submitted_job_sync_posts_status_to_makerworks(monkeypatch) -> None:
    monkeypatch.setenv("MAKERWORKS_JOB_CALLBACK_ENABLED", "true")
    monkeypatch.setenv("MAKERWORKS_JOB_CALLBACK_METHOD", "POST")
    monkeypatch.setenv("MAKERWORKS_JOB_CALLBACK_PATH_TEMPLATE", "/api/printlab/jobs/{job_id}")
    monkeypatch.setenv("MAKERWORKS_WEBHOOK_SECRET", "shared-secret")

    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )
    service._submitted_jobs = [
        {
            "id": "job-1",
            "source": "makerworks",
            "status": "queued",
            "model_id": "widget-1",
            "file_name": "widget.3mf",
            "created_at": "2026-03-10T12:00:00+00:00",
            "updated_at": "2026-03-10T12:00:00+00:00",
            "history": [],
        }
    ]

    class FakeWorksService:
        async def request(self, service_name: str, payload) -> dict[str, object]:
            assert service_name == "makerworks"
            assert payload.path == "/api/printlab/jobs/job-1"
            assert payload.body_text is not None
            assert payload.body["status"] == "queued"
            assert payload.body["printer_id"] == "printer-1"
            assert payload.body["source"] == "makerworks"
            assert payload.headers["Authorization"] == "Bearer shared-secret"
            assert payload.headers["X-MakerWorks-Timestamp"]
            assert payload.headers["X-MakerWorks-Signature"].startswith("sha256=")
            return {"ok": True, "status_code": 202}

    monkeypatch.setattr("app.runtime.works_service", FakeWorksService())

    job = asyncio.run(service._sync_submitted_job_to_makerworks(service._submitted_jobs[0], force=True))

    assert job["callback"]["delivered_status"] == "queued"
    assert job["callback"]["status_code"] == 202


def _makerworks_api_app() -> FastAPI:
    app = FastAPI()
    register_admin_auth(app)
    app.include_router(api_router)
    return app


def test_makerworks_submit_route_accepts_configured_api_key_auth(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("MAKERWORKS_SUBMIT_API_KEY", "submit-secret")

    captured: dict[str, object] = {}

    class FakeJobManager:
        async def submit_makerworks_job(self, payload, actor: str = "dashboard") -> dict[str, object]:
            captured["actor"] = actor
            captured["payload"] = payload
            return {
                "id": "job-1",
                "status": "queued",
                "printer_id": "printer-1",
                "printer_name": "Printer 1",
                "queue_item_id": "queue-1",
                "idempotency_key": payload.idempotency_key,
                "source_job_id": payload.source_job_id,
                "source_order_id": payload.source_order_id,
                "model_id": payload.model_id,
                "model_name": "Widget",
                "file_path": "/cache/widget.3mf",
                "file_name": "widget.3mf",
                "created_at": "2026-03-10T12:00:00+00:00",
                "updated_at": "2026-03-10T12:00:00+00:00",
                "history": [],
            }

    monkeypatch.setattr("app.routers.api.job_manager", FakeJobManager())

    with TestClient(_makerworks_api_app()) as client:
        response = client.post(
            "/api/works/makerworks/jobs",
            headers={"X-API-Key": "submit-secret"},
            json={
                "model_id": "widget-1",
                "printer_id": "printer-1",
                "idempotency_key": "mw-123",
                "source_job_id": "source-job-1",
                "source_order_id": "source-order-1",
                "metadata": {"priority": "rush"},
            },
        )

    assert response.status_code == 200
    assert response.json()["id"] == "job-1"
    assert captured["actor"] == "makerworks"


def test_makerworks_get_job_route_accepts_bearer_auth(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("MAKERWORKS_SUBMIT_BEARER_TOKEN", "submit-bearer")

    class FakeJobManager:
        def get_job(self, job_id: str, *, printer_id: str | None = None) -> dict[str, object]:
            assert printer_id is None
            return {"id": job_id, "status": "queued", "history": []}

    monkeypatch.setattr("app.routers.api.job_manager", FakeJobManager())

    with TestClient(_makerworks_api_app()) as client:
        response = client.get(
            "/api/works/makerworks/jobs/job-1",
            headers={"Authorization": "Bearer submit-bearer"},
        )

    assert response.status_code == 200
    assert response.json()["id"] == "job-1"


def test_makerworks_submit_route_returns_clear_submit_failure_payload(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("MAKERWORKS_SUBMIT_API_KEY", "submit-secret")

    class FakeJobManager:
        async def submit_makerworks_job(self, _payload, actor: str = "dashboard") -> dict[str, object]:
            raise MakerworksSubmitError("Printer is not connected.", job={"id": "job-1", "status": "submit_failed"})

    monkeypatch.setattr("app.routers.api.job_manager", FakeJobManager())

    with TestClient(_makerworks_api_app()) as client:
        response = client.post(
            "/api/works/makerworks/jobs",
            headers={"X-API-Key": "submit-secret"},
            json={
                "model_id": "widget-1",
                "printer_id": "printer-1",
                "idempotency_key": "mw-123",
                "source_job_id": "source-job-1",
                "source_order_id": "source-order-1",
            },
        )

    assert response.status_code == 400
    assert response.json()["error"] == "submit_failed"
    assert response.json()["job"]["status"] == "submit_failed"
