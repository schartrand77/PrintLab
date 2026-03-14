from __future__ import annotations

import asyncio
import hashlib
import io
from pathlib import Path
from zipfile import ZipFile

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


def test_sd_thumbnail_alias_path_does_not_reuse_stale_alias_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = Path("tests/.tmp/thumb-cache")
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PRINTLAB_DATA_DIR", str(data_dir.resolve()))

    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )

    alias_path = "/data/Metadata/plate_1.gcode"
    resolved_path = "/cache/actual-part.gcode.3mf"
    thumb_dir = data_dir / "cache" / "sd_thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    stale_key = hashlib.sha1(alias_path.encode("utf-8")).hexdigest()
    (thumb_dir / f"{stale_key}.png").write_bytes(b"stale")

    class FakeFtp:
        def retrbinary(self, command: str, callback) -> None:
            if command == "RETR /cache/actual-part.png":
                callback(b"fresh")
                return
            raise AssertionError(f"unexpected RETR command: {command}")

        def quit(self) -> None:
            return None

    class FakeClient:
        def ftp_connection(self) -> FakeFtp:
            return FakeFtp()

    service.client = FakeClient()
    service._resolve_sd_path_sync = lambda ftp, raw_path: resolved_path  # type: ignore[method-assign]

    content, mime = service._get_sd_thumbnail_sync(alias_path)

    assert content == b"fresh"
    assert mime == "image/png"
    resolved_key = hashlib.sha1(resolved_path.encode("utf-8")).hexdigest()
    assert (thumb_dir / f"{resolved_key}.png").read_bytes() == b"fresh"


def test_sd_thumbnail_uses_requested_plate_image_from_3mf(monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = Path("tests/.tmp/thumb-cache-multiplate-direct")
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PRINTLAB_DATA_DIR", str(data_dir.resolve()))

    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )

    archive = io.BytesIO()
    with ZipFile(archive, "w") as zf:
        zf.writestr("Metadata/plate_1.png", b"plate-one")
        zf.writestr("Metadata/plate_2.png", b"plate-two")

    class FakeFtp:
        def retrbinary(self, command: str, callback) -> None:
            if command == "RETR /cache/widget.gcode.3mf":
                callback(archive.getvalue())
                return
            raise AssertionError(f"unexpected RETR command: {command}")

        def quit(self) -> None:
            return None

    class FakeClient:
        def ftp_connection(self) -> FakeFtp:
            return FakeFtp()

    service.client = FakeClient()
    service._resolve_sd_path_sync = lambda ftp, raw_path: "/cache/widget.gcode.3mf"  # type: ignore[method-assign]

    content, mime = service._get_sd_thumbnail_sync("/data/Metadata/plate_2.gcode")

    assert content == b"plate-two"
    assert mime == "image/png"


def test_sd_thumbnail_uses_active_plate_context_for_3mf_thumbnail(monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = Path("tests/.tmp/thumb-cache-multiplate-context")
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PRINTLAB_DATA_DIR", str(data_dir.resolve()))

    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )
    service._active_job_context = {"file_path": "/cache/widget.gcode.3mf", "plate_gcode": "Metadata/plate_2.gcode"}

    archive = io.BytesIO()
    with ZipFile(archive, "w") as zf:
        zf.writestr("Metadata/plate_1.png", b"plate-one")
        zf.writestr("Metadata/plate_2.png", b"plate-two")

    class FakeFtp:
        def retrbinary(self, command: str, callback) -> None:
            if command == "RETR /cache/widget.gcode.3mf":
                callback(archive.getvalue())
                return
            raise AssertionError(f"unexpected RETR command: {command}")

        def quit(self) -> None:
            return None

    class FakeClient:
        def ftp_connection(self) -> FakeFtp:
            return FakeFtp()

    service.client = FakeClient()
    service._resolve_sd_path_sync = lambda ftp, raw_path: "/cache/widget.gcode.3mf"  # type: ignore[method-assign]

    content, mime = service._get_sd_thumbnail_sync("/cache/widget.gcode.3mf")

    assert content == b"plate-two"
    assert mime == "image/png"


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


def test_successful_gcode_can_upload_timelapse_to_youtube(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path = Path("tests/.tmp/youtube-upload")
    cache_dir = tmp_path / "cache" / "timelapse"
    cache_dir.mkdir(parents=True, exist_ok=True)
    video_path = cache_dir / "video_2026-03-13_12-12-18.mp4"
    video_path.write_bytes(b"fake-video")

    monkeypatch.setenv("YOUTUBE_UPLOAD_ENABLED", "true")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "client-id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("YOUTUBE_TITLE_TEMPLATE", "{model_name} on {printer_name}")
    monkeypatch.setenv("YOUTUBE_DESCRIPTION_TEMPLATE", "Completed {completed_at}")

    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE", "file_cache_path": str(tmp_path / "cache")},
        printer_id="printer-1",
        display_name="Printer 1",
    )
    record = {
        "id": "record-1",
        "file_name": "widget.3mf",
        "model_name": "Widget",
        "completed_at": "2026-03-13T12:00:00+00:00",
        "youtube": {
            "uploaded": False,
            "uploaded_at": None,
            "last_attempt_at": None,
            "last_error": None,
            "status_code": None,
            "video_id": None,
            "video_url": None,
            "path": None,
            "title": None,
        },
    }

    class TokenResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"access_token": "access-token"}

    class InitResponse:
        status_code = 200
        headers = {"Location": "https://upload.youtube.test/session"}

        def raise_for_status(self) -> None:
            return None

    class UploadResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"id": "video-123"}

    captured: dict[str, object] = {}

    class FakeSession:
        headers: dict[str, str]

        def __init__(self) -> None:
            self.headers = {}

        def post(self, url: str, *, params=None, json=None, headers=None, timeout=None):
            captured["init_url"] = url
            captured["init_params"] = params
            captured["init_json"] = json
            captured["init_headers"] = headers
            captured["auth_header"] = self.headers.get("Authorization")
            return InitResponse()

        def put(self, url: str, *, data=None, headers=None, timeout=None):
            captured["upload_url"] = url
            captured["upload_headers"] = headers
            captured["upload_bytes"] = data.read()
            return UploadResponse()

    monkeypatch.setattr("app.services.requests.post", lambda *args, **kwargs: TokenResponse())
    monkeypatch.setattr("app.services.requests.Session", FakeSession)

    result = asyncio.run(service._sync_successful_gcode_to_youtube(record, force=True, video_path=video_path))

    assert result["youtube"]["uploaded"] is True
    assert result["youtube"]["video_id"] == "video-123"
    assert result["youtube"]["video_url"] == "https://www.youtube.com/watch?v=video-123"
    assert result["youtube"]["title"] == "Widget on Printer 1"
    assert captured["auth_header"] == "Bearer access-token"
    assert captured["upload_url"] == "https://upload.youtube.test/session"
    assert captured["upload_bytes"] == b"fake-video"


def test_youtube_video_snapshot_is_paginated() -> None:
    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )
    service._successful_gcodes = [
        {
            "id": f"record-{index}",
            "model_name": f"Model {index}",
            "file_name": f"model-{index}.3mf",
            "file_path": f"/cache/model-{index}.3mf",
            "subtask_name": None,
            "completed_at": f"2026-03-14T0{index}:00:00+00:00",
            "youtube": {
                "uploaded": True,
                "uploaded_at": f"2026-03-14T0{index}:10:00+00:00",
                "video_id": f"video-{index}",
                "video_url": f"https://www.youtube.com/watch?v=video-{index}",
                "title": f"Video {index}",
                "path": f"C:/videos/video-{index}.mp4",
            },
        }
        for index in range(1, 8)
    ]

    page_one = service.youtube_videos_snapshot(page=1, page_size=5)
    page_two = service.youtube_videos_snapshot(page=2, page_size=5)

    assert page_one["page"] == 1
    assert page_one["pages"] == 2
    assert page_one["count"] == 5
    assert page_one["items"][0]["video_id"] == "video-7"
    assert page_two["page"] == 2
    assert page_two["count"] == 2
    assert page_two["items"][0]["video_id"] == "video-2"


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

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "submit_failed"
    assert response.json()["error"]["details"]["job"]["status"] == "submit_failed"
