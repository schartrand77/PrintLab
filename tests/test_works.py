from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import hash_password, register_admin_auth
from app.errors import ApiError
from app.main import create_app
from app.routers.api import router as api_router
from app.services import MakerworksSubmitError, PrinterService, WorksRequest, WorksService


def test_build_url_rejects_absolute_urls() -> None:
    service = WorksService()
    with pytest.raises(ValueError):
        service._build_url("https://makerworks.local", "https://evil.example/path")


def test_build_url_normalizes_missing_leading_slash() -> None:
    service = WorksService()
    url = service._build_url("https://makerworks.local/", "v1/orders")
    assert url == "https://makerworks.local/v1/orders"


def test_service_config_normalizes_base_url_missing_scheme(monkeypatch) -> None:
    monkeypatch.setenv("MAKERWORKS_BASE_URL", "192.168.1.170:3777")
    service = WorksService()

    cfg = service._get_config("makerworks")

    assert cfg["base_url"] == "http://192.168.1.170:3777"


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
    assert result["items"][0]["thumbnail_proxy_url"] == "/api/works/makerworks/asset?url=https%3A%2F%2Fmakerworks.local%2Fthumbs%2F42.png"
    assert result["items"][0]["download_url"] == "https://makerworks.local/files/42.3mf"
    assert result["items"][0]["model_url"] == "https://makerworks.local/models/42"
    assert result["items"][0]["printer_handoff_ready"] is True


def test_makerworks_library_thumbnail_path_keeps_fallback_fields_when_env_is_legacy(monkeypatch) -> None:
    monkeypatch.setenv("MAKERWORKS_BASE_URL", "https://makerworks.local")
    monkeypatch.setenv("MAKERWORKS_LIBRARY_THUMBNAIL_PATH", "coverImagePath")

    class FakeResponse:
        ok = True
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict[str, object]:
            return {
                "models": [
                    {
                        "id": 99,
                        "title": "Image URL Model",
                        "imageUrl": "/thumbs/99.png",
                    }
                ],
                "total": 1,
            }

        @property
        def text(self) -> str:
            return ""

    monkeypatch.setattr("app.services.requests.request", lambda **kwargs: FakeResponse())
    service = WorksService()

    result = service.makerworks_library_sync()

    assert result["items"][0]["thumbnail_url"] == "https://makerworks.local/thumbs/99.png"


def test_makerworks_library_derives_preview_mesh_when_thumbnail_is_missing(monkeypatch) -> None:
    monkeypatch.setenv("MAKERWORKS_BASE_URL", "https://makerworks.local")

    class FakeResponse:
        ok = True
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict[str, object]:
            return {
                "models": [
                    {
                        "id": "preview-1",
                        "title": "Preview Model",
                        "filePath": "/models/preview-1.3mf",
                    }
                ],
                "total": 1,
            }

        @property
        def text(self) -> str:
            return ""

    monkeypatch.setattr("app.services.requests.request", lambda **kwargs: FakeResponse())
    service = WorksService()

    result = service.makerworks_library_sync()

    assert result["items"][0]["thumbnail_url"] is None
    assert result["items"][0]["preview_mesh_url"] == "https://makerworks.local/models/preview-1-preview.stl"
    assert result["items"][0]["thumbnail_proxy_url"] == "/api/works/makerworks/mesh-preview?url=https%3A%2F%2Fmakerworks.local%2Fmodels%2Fpreview-1-preview.stl"


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
    assert result["item"]["thumbnail_proxy_url"] == "/api/works/makerworks/mesh-preview?url=https%3A%2F%2Fmakerworks.local%2Ffiles%2Fwidget-1-preview.stl"
    assert result["item"]["raw"]["title"] == "Widget"


def test_works_asset_endpoint_proxies_service_download(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(create_app())

    async def fake_download_asset(service: str, asset_url: str, timeout_seconds: float = 120.0) -> dict[str, object]:
        assert service == "makerworks"
        assert asset_url == "https://makerworks.local/thumbs/42.png"
        assert timeout_seconds == 20.0
        return {
            "url": asset_url,
            "filename": "42.png",
            "content": b"png-bytes",
            "content_type": "image/png",
        }

    monkeypatch.setattr("app.routers.api.works_service.download_asset", fake_download_asset)

    response = client.get("/api/works/makerworks/asset", params={"url": "https://makerworks.local/thumbs/42.png"})

    assert response.status_code == 200
    assert response.content == b"png-bytes"
    assert response.headers["content-type"].startswith("image/png")


def test_works_mesh_preview_endpoint_renders_service_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(create_app())

    async def fake_render_mesh_preview(service: str, asset_url: str, timeout_seconds: float = 30.0) -> tuple[bytes, str]:
        assert service == "makerworks"
        assert asset_url == "https://makerworks.local/models/preview-1-preview.stl"
        assert timeout_seconds == 30.0
        return (b"png-preview", "image/png")

    monkeypatch.setattr("app.routers.api.works_service.render_mesh_preview", fake_render_mesh_preview)

    response = client.get("/api/works/makerworks/mesh-preview", params={"url": "https://makerworks.local/models/preview-1-preview.stl"})

    assert response.status_code == 200
    assert response.content == b"png-preview"
    assert response.headers["content-type"].startswith("image/png")


def test_download_asset_supports_admin_session_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAKERWORKS_BASE_URL", "https://makerworks.local")
    monkeypatch.setenv("MAKERWORKS_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("MAKERWORKS_ADMIN_PASSWORD", "secret")

    events: list[tuple[str, str, object]] = []

    class FakeResponse:
        def __init__(self, *, text: str = "", content: bytes = b"", status_code: int = 200, headers: dict[str, str] | None = None) -> None:
            self.text = text
            self.content = content
            self.status_code = status_code
            self.headers = headers or {"content-type": "application/octet-stream"}
            self.ok = status_code < 400
            self.url = "https://makerworks.local/thumbs/42.png"

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

    class FakeSession:
        def get(self, url: str, *, headers: dict[str, str], timeout: float, verify: bool) -> FakeResponse:
            events.append(("GET", url, headers))
            if url.endswith("/login"):
                return FakeResponse(
                    text='<meta name="csrf-token" content="csrf-123" />',
                    headers={"content-type": "text/html"},
                )
            return FakeResponse(content=b"image-bytes", headers={"content-type": "image/png"})

        def post(self, url: str, *, data: dict[str, str], headers: dict[str, str], timeout: float, verify: bool) -> FakeResponse:
            events.append(("POST", url, data))
            return FakeResponse()

    monkeypatch.setattr("app.services.requests.Session", lambda: FakeSession())

    service = WorksService()
    result = service.download_asset_sync("makerworks", "https://makerworks.local/thumbs/42.png")

    assert result["content"] == b"image-bytes"
    assert result["content_type"] == "image/png"
    assert events[0][0:2] == ("GET", "https://makerworks.local/login")
    assert events[1] == ("POST", "https://makerworks.local/login", {"username": "admin", "password": "secret", "csrf_token": "csrf-123"})
    assert events[2][0:2] == ("GET", "https://makerworks.local/thumbs/42.png")


def test_download_asset_surfaces_login_requirement_without_service_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAKERWORKS_BASE_URL", "https://makerworks.local")

    class FakeResponse:
        ok = True
        status_code = 200
        text = "<html>login</html>"
        content = b"<html>login</html>"
        url = "https://makerworks.local/login?next=%2Fthumbs%2F42.png"
        headers = {"content-type": "text/html; charset=utf-8"}

    monkeypatch.setattr("app.services.requests.get", lambda *args, **kwargs: FakeResponse())

    service = WorksService()
    with pytest.raises(RuntimeError, match="MAKERWORKS_ADMIN_USERNAME"):
        service.download_asset_sync("makerworks", "https://makerworks.local/thumbs/42.png")


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

    with pytest.raises(ApiError) as exc_info:
        service.makerworks_library_sync()

    assert exc_info.value.code == "upstream_rejected"
    assert exc_info.value.status_code == 502
    assert exc_info.value.details["upstream_status_code"] == 404
    assert "MakerWorks library request failed" in exc_info.value.message


def test_makerworks_library_retries_without_pagination_after_400(monkeypatch) -> None:
    monkeypatch.setenv("MAKERWORKS_BASE_URL", "https://makerworks.local")

    calls: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, ok: bool, status_code: int, body: dict[str, object] | str) -> None:
            self.ok = ok
            self.status_code = status_code
            self._body = body
            self.headers = {"content-type": "application/json"}

        def json(self) -> dict[str, object] | str:
            return self._body

        @property
        def text(self) -> str:
            return self._body if isinstance(self._body, str) else ""

    def fake_request(**kwargs):
        calls.append({"url": kwargs.get("url"), "params": dict(kwargs.get("params") or {})})
        params = dict(kwargs.get("params") or {})
        if "page" in params or "page_size" in params:
            return FakeResponse(False, 400, {"message": "unexpected query params"})
        return FakeResponse(
            True,
            200,
            {
                "models": [
                    {
                        "id": 7,
                        "title": "Fallback Model",
                    }
                ],
                "total": 1,
            },
        )

    monkeypatch.setattr("app.services.requests.request", fake_request)
    service = WorksService()

    result = service.makerworks_library_sync(query="desk")

    assert result["count"] == 1
    assert result["items"][0]["id"] == "7"
    assert calls == [
        {
            "url": "https://makerworks.local/api/models",
            "params": {"q": "desk", "page": 1, "page_size": 24},
        },
        {
            "url": "https://makerworks.local/api/models",
            "params": {"q": "desk"},
        },
    ]


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


def test_job_thumbnail_url_skips_internal_system_gcode_path() -> None:
    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )

    url = service._job_thumbnail_url("/usr/etc/print/auto_cali_for_user_param.gcode", None)

    assert url is None


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
        ok = True
        status_code = 200

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
            captured["upload_bytes"] = data
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
    assert captured["upload_headers"]["Content-Length"] == str(len(b"fake-video"))
    assert captured["upload_headers"]["Content-Range"] == f"bytes 0-{len(b'fake-video') - 1}/{len(b'fake-video')}"


def test_youtube_upload_uses_consistent_file_size_for_resumable_session(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path = Path("tests/.tmp/youtube-upload-stable-size")
    cache_dir = tmp_path / "cache" / "timelapse"
    cache_dir.mkdir(parents=True, exist_ok=True)
    video_path = cache_dir / "video_2026-03-13_12-12-18.mp4"
    payload = b"fake-video"
    video_path.write_bytes(payload)

    monkeypatch.setenv("YOUTUBE_UPLOAD_ENABLED", "true")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "client-id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "refresh-token")

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
        "youtube": {"uploaded": False},
    }

    class TokenResponse:
        ok = True
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"access_token": "access-token"}

    class InitResponse:
        status_code = 200
        headers = {"Location": "https://upload.youtube.test/session"}

    class UploadResponse:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"id": "video-123"}

    captured: dict[str, object] = {}
    original_stat = Path.stat
    stat_calls = {"target": 0}

    def fake_stat(self: Path):
        result = original_stat(self)
        if self == video_path:
            stat_calls["target"] += 1
            if stat_calls["target"] == 2:
                return SimpleNamespace(st_size=result.st_size + 1024, st_mtime=result.st_mtime, st_mtime_ns=result.st_mtime_ns)
        return result

    class FakeSession:
        headers: dict[str, str]

        def __init__(self) -> None:
            self.headers = {}

        def post(self, url: str, *, params=None, json=None, headers=None, timeout=None):
            captured["init_headers"] = headers
            return InitResponse()

        def put(self, url: str, *, data=None, headers=None, timeout=None):
            captured["upload_headers"] = headers
            captured["upload_bytes"] = data
            return UploadResponse()

    monkeypatch.setattr("app.services.requests.post", lambda *args, **kwargs: TokenResponse())
    monkeypatch.setattr("app.services.requests.Session", FakeSession)
    monkeypatch.setattr(Path, "stat", fake_stat, raising=False)

    asyncio.run(service._sync_successful_gcode_to_youtube(record, force=True, video_path=video_path))

    assert captured["init_headers"]["X-Upload-Content-Length"] == str(len(payload))
    assert captured["upload_headers"]["Content-Range"] == f"bytes 0-{len(payload) - 1}/{len(payload)}"
    assert captured["upload_bytes"] == payload


def test_successful_gcode_can_download_sd_timelapse_before_youtube_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path = Path("tests/.tmp/youtube-upload-from-ftp")
    cache_dir = tmp_path / "cache" / "timelapse"
    cache_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("YOUTUBE_UPLOAD_ENABLED", "true")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "client-id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "refresh-token")

    service = PrinterService(
        config={
            "host": "127.0.0.1",
            "serial": "SERIAL",
            "access_code": "CODE",
            "file_cache_path": str(tmp_path / "cache"),
            "timelapse_cache_count": 1,
        },
        printer_id="printer-1",
        display_name="Printer 1",
    )
    record = {
        "id": "record-ftp-1",
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

    class FakeFtp:
        def retrlines(self, command: str, callback) -> None:
            assert command == "LIST /timelapse"
            callback("-rw-r--r-- 1 user group 10 Mar 13 12:12 video_2026-03-13_12-12-18.mp4")

        def retrbinary(self, command: str, callback) -> None:
            assert command == "RETR /timelapse/video_2026-03-13_12-12-18.mp4"
            callback(b"fake-video-from-ftp")

        def quit(self) -> None:
            return None

    service.client = SimpleNamespace(ftp_connection=lambda: FakeFtp(), connected=True)

    class TokenResponse:
        ok = True
        status_code = 200

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
            return {"id": "video-ftp-123"}

    captured: dict[str, object] = {}

    class FakeSession:
        headers: dict[str, str]

        def __init__(self) -> None:
            self.headers = {}

        def post(self, url: str, *, params=None, json=None, headers=None, timeout=None):
            captured["init_url"] = url
            return InitResponse()

        def put(self, url: str, *, data=None, headers=None, timeout=None):
            captured["upload_bytes"] = data
            return UploadResponse()

    monkeypatch.setattr("app.services.requests.post", lambda *args, **kwargs: TokenResponse())
    monkeypatch.setattr("app.services.requests.Session", FakeSession)

    result = asyncio.run(service._sync_successful_gcode_to_youtube(record, force=True))

    assert result["youtube"]["uploaded"] is True
    assert result["youtube"]["video_id"] == "video-ftp-123"
    assert captured["upload_bytes"] == b"fake-video-from-ftp"
    assert Path(str(result["youtube"]["path"])).exists()


def test_download_latest_timelapse_from_printer_ignores_stale_remote_video() -> None:
    tmp_path = Path("tests/.tmp/youtube-stale-remote")
    cache_dir = tmp_path / "cache" / "timelapse"
    cache_dir.mkdir(parents=True, exist_ok=True)

    service = PrinterService(
        config={
            "host": "127.0.0.1",
            "serial": "SERIAL",
            "access_code": "CODE",
            "file_cache_path": str(tmp_path / "cache"),
            "timelapse_cache_count": 1,
        },
        printer_id="printer-1",
        display_name="Printer 1",
    )
    record = {
        "id": "record-ftp-1",
        "file_name": "widget.3mf",
        "model_name": "Widget",
        "completed_at": "2026-04-02T23:50:05+00:00",
        "youtube": {"uploaded": False},
    }

    class FakeFtp:
        def retrlines(self, command: str, callback) -> None:
            assert command == "LIST /timelapse"
            callback("-rw-r--r-- 1 user group 10 Apr 01 14:30 video_2026-04-01_14-30-24.mp4")

        def quit(self) -> None:
            return None

    service.client = SimpleNamespace(ftp_connection=lambda: FakeFtp(), connected=True)

    result = service._download_latest_timelapse_from_printer_sync(record)

    assert result is None


def test_wait_for_stable_timelapse_file_accepts_aged_file(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path = Path("tests/.tmp/youtube-stable-file")
    cache_dir = tmp_path / "cache" / "timelapse"
    cache_dir.mkdir(parents=True, exist_ok=True)
    video_path = cache_dir / "stable.mp4"
    video_path.write_bytes(b"stable-video")

    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE", "file_cache_path": str(tmp_path / "cache")},
        printer_id="printer-1",
        display_name="Printer 1",
    )

    original_stat = video_path.stat()
    old_mtime = original_stat.st_mtime - 30
    video_path.touch()
    os.utime(video_path, (old_mtime, old_mtime))

    result = asyncio.run(
        service._wait_for_stable_timelapse_file(
            video_path,
            cfg={"stable_seconds": 10, "poll_interval_seconds": 1, "wait_seconds": 10},
        )
    )

    assert result == video_path


def test_youtube_upload_stages_local_timelapse_before_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path = Path("tests/.tmp/youtube-staging-local")
    cache_dir = tmp_path / "cache" / "timelapse"
    stage_dir = tmp_path / "stage"
    cache_dir.mkdir(parents=True, exist_ok=True)
    video_path = cache_dir / "video_2026-03-13_12-12-18.mp4"
    payload = b"fake-video"
    video_path.write_bytes(payload)

    monkeypatch.setenv("YOUTUBE_UPLOAD_ENABLED", "true")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "client-id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("YOUTUBE_UPLOAD_STAGING_DIR", str(stage_dir))

    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE", "file_cache_path": str(tmp_path / "cache")},
        printer_id="printer-1",
        display_name="Printer 1",
    )
    record = {
        "id": "record-stage-1",
        "file_name": "widget.3mf",
        "model_name": "Widget",
        "completed_at": "2026-03-13T12:00:00+00:00",
        "youtube": {"uploaded": False},
    }

    captured: dict[str, object] = {}

    def fake_upload(_record: dict[str, object], staged_path: Path, _cfg: dict[str, object]) -> dict[str, object]:
        captured["upload_path"] = staged_path
        captured["upload_bytes"] = staged_path.read_bytes()
        captured["upload_exists_during_call"] = staged_path.exists()
        return {
            "video_id": "video-stage-123",
            "video_url": "https://www.youtube.com/watch?v=video-stage-123",
            "status_code": 200,
            "title": "Widget",
            "path": str(staged_path),
        }

    monkeypatch.setattr(service, "_youtube_upload_video", fake_upload)

    result = asyncio.run(service._sync_successful_gcode_to_youtube(record, force=True, video_path=video_path))

    upload_path = captured["upload_path"]
    assert isinstance(upload_path, Path)
    assert upload_path.parent == stage_dir
    assert upload_path != video_path
    assert captured["upload_bytes"] == payload
    assert captured["upload_exists_during_call"] is True
    assert not upload_path.exists()
    assert result["youtube"]["uploaded"] is True
    assert result["youtube"]["path"] == str(video_path.resolve())


def test_youtube_upload_stages_ftp_timelapse_before_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path = Path("tests/.tmp/youtube-staging-ftp")
    cache_dir = tmp_path / "cache" / "timelapse"
    stage_dir = tmp_path / "stage"
    cache_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("YOUTUBE_UPLOAD_ENABLED", "true")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "client-id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("YOUTUBE_UPLOAD_STAGING_DIR", str(stage_dir))

    service = PrinterService(
        config={
            "host": "127.0.0.1",
            "serial": "SERIAL",
            "access_code": "CODE",
            "file_cache_path": str(tmp_path / "cache"),
            "timelapse_cache_count": 1,
        },
        printer_id="printer-1",
        display_name="Printer 1",
    )
    record = {
        "id": "record-stage-ftp-1",
        "file_name": "widget.3mf",
        "model_name": "Widget",
        "completed_at": "2026-03-13T12:00:00+00:00",
        "youtube": {"uploaded": False},
    }

    class FakeFtp:
        def retrlines(self, command: str, callback) -> None:
            assert command == "LIST /timelapse"
            callback("-rw-r--r-- 1 user group 19 Mar 13 12:12 video_2026-03-13_12-12-18.mp4")

        def retrbinary(self, command: str, callback) -> None:
            assert command == "RETR /timelapse/video_2026-03-13_12-12-18.mp4"
            callback(b"fake-video-from-ftp")

        def quit(self) -> None:
            return None

    service.client = SimpleNamespace(ftp_connection=lambda: FakeFtp(), connected=True)
    captured: dict[str, object] = {}

    def fake_upload(_record: dict[str, object], staged_path: Path, _cfg: dict[str, object]) -> dict[str, object]:
        captured["upload_path"] = staged_path
        captured["upload_bytes"] = staged_path.read_bytes()
        return {
            "video_id": "video-stage-ftp-123",
            "video_url": "https://www.youtube.com/watch?v=video-stage-ftp-123",
            "status_code": 200,
            "title": "Widget",
            "path": str(staged_path),
        }

    monkeypatch.setattr(service, "_youtube_upload_video", fake_upload)

    result = asyncio.run(service._sync_successful_gcode_to_youtube(record, force=True))

    upload_path = captured["upload_path"]
    assert isinstance(upload_path, Path)
    assert upload_path.parent == stage_dir
    assert captured["upload_bytes"] == b"fake-video-from-ftp"
    assert not upload_path.exists()
    assert result["youtube"]["uploaded"] is True
    assert Path(str(result["youtube"]["path"])).parent == cache_dir.resolve()


def test_start_reschedules_pending_youtube_uploads(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path = Path("tests/.tmp/youtube-pending-recovery")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    record_id = "pending-record"
    successful_gcodes_path = tmp_path / "successful_gcodes_printer-1.json"
    successful_gcodes_path.write_text(
        json.dumps(
            [
                {
                    "id": record_id,
                    "file_name": "widget.3mf",
                    "completed_at": "2026-03-13T12:00:00+00:00",
                    "youtube": {
                        "uploaded": False,
                        "uploaded_at": None,
                        "last_attempt_at": "2026-03-13T12:01:00+00:00",
                        "last_error": None,
                        "path": "/data/cache/timelapse/widget.mp4",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PRINTLAB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("YOUTUBE_UPLOAD_ENABLED", "true")

    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE", "file_cache_path": str(cache_dir)},
        printer_id="printer-1",
        display_name="Printer 1",
    )

    scheduled: list[str] = []

    def fake_schedule(target_record_id: str, *, force: bool = False) -> None:
        assert force is False
        scheduled.append(target_record_id)

    class FakeClient:
        connected = True

        async def connect(self, _callback) -> None:
            return None

        async def refresh(self) -> None:
            return None

    monkeypatch.setattr(service, "_schedule_youtube_upload", fake_schedule)
    monkeypatch.setattr("app.services.BambuClient", lambda cfg: FakeClient())

    asyncio.run(service.start())

    assert scheduled == [record_id]


def test_youtube_auto_upload_retries_when_timelapse_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUTUBE_UPLOAD_ENABLED", "true")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "client-id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("YOUTUBE_TIMELAPSE_WAIT_SECONDS", "1")
    monkeypatch.setenv("YOUTUBE_TIMELAPSE_POLL_INTERVAL_SECONDS", "1")

    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )
    record = {
        "id": "record-retry-1",
        "file_name": "widget.3mf",
        "model_name": "Widget",
        "completed_at": "2026-03-13T12:00:00+00:00",
        "youtube": {"uploaded": False},
    }

    scheduled: list[tuple[str, int]] = []

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(service, "_find_latest_timelapse_file", lambda _record: None)
    monkeypatch.setattr(service, "_download_latest_timelapse_from_printer_sync", lambda _record: None)
    monkeypatch.setattr("app.services.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(service, "_save_successful_gcodes", lambda: None)
    monkeypatch.setattr(service, "_schedule_youtube_retry", lambda record_id, delay_seconds: scheduled.append((record_id, delay_seconds)))

    result = asyncio.run(service._sync_successful_gcode_to_youtube(record, force=False))

    assert result is record
    assert record["youtube"]["uploaded"] is False
    assert record["youtube"]["last_error"] is None
    assert record["youtube"]["progress_stage"] == "waiting"
    assert record["youtube"]["progress_label"] == "Waiting for timelapse"
    assert scheduled == [("record-retry-1", 60)]


def test_successful_gcode_surfaces_youtube_api_message_without_upload_url(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path = Path("tests/.tmp/youtube-upload-failure")
    cache_dir = tmp_path / "cache" / "timelapse"
    cache_dir.mkdir(parents=True, exist_ok=True)
    video_path = cache_dir / "video_2026-03-13_12-12-18.mp4"
    video_path.write_bytes(b"fake-video")

    monkeypatch.setenv("YOUTUBE_UPLOAD_ENABLED", "true")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "client-id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "refresh-token")

    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE", "file_cache_path": str(tmp_path / "cache")},
        printer_id="printer-1",
        display_name="Printer 1",
    )
    record = {
        "id": "record-youtube-failure",
        "file_name": "widget.3mf",
        "model_name": "Widget",
        "completed_at": "2026-03-13T12:00:00+00:00",
        "youtube": {"uploaded": False},
    }

    class TokenResponse:
        ok = True
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"access_token": "access-token"}

    class InitResponse:
        ok = False
        status_code = 400
        headers: dict[str, str] = {}
        text = '{"error":{"message":"Request contains an invalid argument."}}'

        def json(self) -> dict[str, object]:
            return {"error": {"message": "Request contains an invalid argument."}}

    class FakeSession:
        headers: dict[str, str]

        def __init__(self) -> None:
            self.headers = {}

        def post(self, url: str, *, params=None, json=None, headers=None, timeout=None):
            return InitResponse()

    monkeypatch.setattr("app.services.requests.post", lambda *args, **kwargs: TokenResponse())
    monkeypatch.setattr("app.services.requests.Session", FakeSession)

    with pytest.raises(RuntimeError, match="Request contains an invalid argument"):
        asyncio.run(service._sync_successful_gcode_to_youtube(record, force=True, video_path=video_path))

    error_text = str(record["youtube"]["last_error"])
    assert "invalid argument" in error_text.lower()
    assert "googleapis.com/upload" not in error_text


def test_youtube_token_exchange_surfaces_oauth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )

    class TokenResponse:
        ok = False
        status_code = 400
        text = '{"error":"invalid_grant","error_description":"Bad Request"}'

        def json(self) -> dict[str, object]:
            return {"error": "invalid_grant", "error_description": "Bad Request"}

    monkeypatch.setattr("app.services.requests.post", lambda *args, **kwargs: TokenResponse())

    with pytest.raises(RuntimeError, match="invalid_grant"):
        service._youtube_access_token(
            {
                "client_id": "client-id",
                "client_secret": "client-secret",
                "refresh_token": "refresh-token",
            }
        )


def test_youtube_video_snapshot_is_paginated() -> None:
    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )
    service._list_timelapse_inventory = lambda: []
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
    assert page_one["items"][0]["thumbnail_url"] == "/api/printers/printer-1/sd/thumbnail?path=%2Fcache%2Fmodel-7.3mf"
    assert page_two["page"] == 2
    assert page_two["count"] == 2
    assert page_two["items"][0]["video_id"] == "video-2"


def test_youtube_video_snapshot_does_not_fall_back_to_active_job_thumbnail() -> None:
    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )
    service._active_job_context = {"file_path": "/cache/current-print.3mf", "plate_gcode": "/cache/current-print.gcode.3mf"}
    service._successful_gcodes = [
        {
            "id": "record-1",
            "model_name": "Historic Model",
            "file_name": "historic.3mf",
            "file_path": "",
            "plate_gcode": "",
            "subtask_name": None,
            "completed_at": "2026-03-14T01:00:00+00:00",
            "youtube": {
                "uploaded": False,
                "last_attempt_at": "2026-03-14T01:10:00+00:00",
                "progress_percent": 5,
                "progress_label": "Waiting for timelapse",
                "progress_stage": "waiting",
            },
        }
    ]

    snapshot = service.youtube_videos_snapshot(page=1, page_size=5)

    assert snapshot["items"][0]["thumbnail_url"] is None


def test_youtube_video_snapshot_does_not_match_stale_timelapse_to_new_print() -> None:
    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )
    service._successful_gcodes = [
        {
            "id": "record-1",
            "model_name": "plate_1",
            "file_name": "plate_1.gcode",
            "file_path": "/data/Metadata/plate_1.gcode",
            "completed_at": "2026-04-02T23:50:05+00:00",
            "plate_index": 1,
            "model_key": "plate-1",
            "youtube": {
                "uploaded": False,
                "last_attempt_at": "2026-04-02T23:50:10+00:00",
                "progress_percent": 5,
                "progress_label": "Waiting for timelapse",
                "progress_stage": "waiting",
            },
        }
    ]
    service._list_timelapse_inventory = lambda: [
        {
            "name": "video_2026-04-01_14-30-24.mp4",
            "path": "/timelapse/video_2026-04-01_14-30-24.mp4",
            "size": 123,
            "mtime": service._parse_iso_timestamp("2026-04-01T19:31:00+00:00").timestamp(),
            "thumbnail_url": None,
        }
    ]

    snapshot = service.youtube_videos_snapshot(page=1, page_size=5)

    assert snapshot["items"][0]["file_name"] == "plate_1.gcode"
    assert snapshot["items"][0]["path"] is None


def test_youtube_video_snapshot_matches_same_day_timelapse_started_hours_before_completion() -> None:
    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )
    service._successful_gcodes = [
        {
            "id": "record-1",
            "model_name": "plate_1",
            "file_name": "plate_1.gcode",
            "file_path": "/data/Metadata/plate_1.gcode",
            "completed_at": "2026-04-02T23:50:05+00:00",
            "plate_index": 1,
            "model_key": "plate-1",
            "youtube": {
                "uploaded": False,
                "last_attempt_at": "2026-04-06T10:49:37+00:00",
                "progress_percent": 5,
                "progress_label": "Waiting for timelapse",
                "progress_stage": "waiting",
            },
        }
    ]
    service._list_timelapse_inventory = lambda: [
        {
            "name": "video_2026-04-02_14-30-24.mp4",
            "path": "/timelapse/video_2026-04-02_14-30-24.mp4",
            "size": 123,
            "mtime": service._parse_iso_timestamp("2026-04-02T19:31:00+00:00").timestamp(),
            "thumbnail_url": None,
        }
    ]

    snapshot = service.youtube_videos_snapshot(page=1, page_size=5)

    assert snapshot["count"] == 1
    assert snapshot["items"][0]["record_id"] == "record-1"
    assert snapshot["items"][0]["path"] == "/timelapse/video_2026-04-02_14-30-24.mp4"


def test_list_timelapse_inventory_does_not_expose_mp4_thumbnail_endpoint() -> None:
    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )

    class FakeFtp:
        def retrlines(self, command: str, callback) -> None:
            assert command == "LIST /timelapse"
            callback("-rw-r--r-- 1 user group 10 Apr 02 14:30 video_2026-04-02_14-30-24.mp4")

        def quit(self) -> None:
            return None

    service.client = SimpleNamespace(ftp_connection=lambda: FakeFtp(), connected=True)

    items = service._list_timelapse_inventory()

    assert items[0]["path"] == "/timelapse/video_2026-04-02_14-30-24.mp4"
    assert items[0]["thumbnail_url"] is None


def test_ensure_timelapse_record_does_not_store_remote_mp4_thumbnail() -> None:
    tmp_path = Path("tests/.tmp/youtube-record-thumb")
    cache_dir = tmp_path / "cache" / "timelapse"
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_path = cache_dir / "video_2026-04-02_14-30-24.mp4"
    local_path.write_bytes(b"video")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("PRINTLAB_DATA_DIR", str(tmp_path))
    try:
        service = PrinterService(
            config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE", "file_cache_path": str(tmp_path / "cache")},
            printer_id="printer-1",
            display_name="Printer 1",
        )

        record = service._ensure_timelapse_record("/timelapse/video_2026-04-02_14-30-24.mp4", local_path)

        assert record["thumbnail_url"] is None
    finally:
        monkeypatch.undo()


def test_filament_snapshot_includes_loaded_filament_name() -> None:
    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )

    loaded_tray = SimpleNamespace(
        empty=False,
        type="PLA",
        name="Bambu PLA Basic Jade White",
        color="FFFFFFFF",
        remain=73,
        active=True,
    )
    unit = SimpleNamespace(tray=[loaded_tray], humidity=18, temperature=24)
    device = SimpleNamespace(
        ams=SimpleNamespace(
            data={0: unit},
            active_ams_index=0,
            active_tray_index=0,
        )
    )
    service.client = SimpleNamespace(get_device=lambda: device)

    snapshot = service.filament_snapshot()

    assert snapshot["loaded_filament"]["name"] == "Bambu PLA Basic Jade White"
    assert snapshot["remaining_filament"][0]["name"] == "Bambu PLA Basic Jade White"
    assert snapshot["loaded_filament"]["type"] == "PLA"


def test_filament_snapshot_derives_color_name_from_hex() -> None:
    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )

    loaded_tray = SimpleNamespace(
        empty=False,
        type="PLA",
        name="",
        color="FF0000FF",
        remain=40,
        active=True,
    )
    unit = SimpleNamespace(tray=[loaded_tray], humidity=18, temperature=24)
    device = SimpleNamespace(
        ams=SimpleNamespace(
            data={0: unit},
            active_ams_index=0,
            active_tray_index=0,
        )
    )
    service.client = SimpleNamespace(get_device=lambda: device)

    snapshot = service.filament_snapshot()

    assert snapshot["loaded_filament"]["color_name"] == "Red"
    assert snapshot["remaining_filament"][0]["color_name"] == "Red"


def test_filament_snapshot_prefers_stockworks_color_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCKWORKS_BASE_URL", "https://stockworks.local")
    monkeypatch.setenv("STOCKWORKS_ALLOWED_PATHS", "/api/filaments")
    monkeypatch.setenv("STOCKWORKS_FILAMENT_LIST_PATH", "/api/filaments")

    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict[str, str]]:
            return [{"hex": "#FF0000", "name": "Bambu Scarlet"}]

    def fake_get(url: str, *, headers: dict[str, str], timeout: float, verify: bool) -> FakeResponse:
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        captured["verify"] = verify
        return FakeResponse()

    monkeypatch.setattr("app.services.requests.get", fake_get)

    service = PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )

    loaded_tray = SimpleNamespace(
        empty=False,
        type="PLA",
        name="",
        color="FF0000FF",
        remain=40,
        active=True,
    )
    unit = SimpleNamespace(tray=[loaded_tray], humidity=18, temperature=24)
    device = SimpleNamespace(
        ams=SimpleNamespace(
            data={0: unit},
            active_ams_index=0,
            active_tray_index=0,
        )
    )
    service.client = SimpleNamespace(get_device=lambda: device)

    snapshot = service.filament_snapshot()

    assert captured["url"] == "https://stockworks.local/api/filaments"
    assert snapshot["loaded_filament"]["color_name"] == "Bambu Scarlet"
    assert snapshot["remaining_filament"][0]["color_name"] == "Bambu Scarlet"


def test_works_request_supports_admin_session_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCKWORKS_BASE_URL", "https://stockworks.local")
    monkeypatch.setenv("STOCKWORKS_ALLOWED_PATHS", "/printlab/filaments")
    monkeypatch.setenv("STOCKWORKS_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("STOCKWORKS_ADMIN_PASSWORD", "secret")

    events: list[tuple[str, str, object]] = []

    class FakeResponse:
        def __init__(self, *, text: str = "", json_body: object = None, status_code: int = 200, headers: dict[str, str] | None = None) -> None:
            self.text = text
            self._json_body = json_body
            self.status_code = status_code
            self.headers = headers or {"content-type": "application/json"}
            self.ok = status_code < 400

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

        def json(self) -> object:
            return self._json_body

    class FakeSession:
        def get(self, url: str, *, headers: dict[str, str], timeout: float, verify: bool) -> FakeResponse:
            events.append(("GET", url, headers))
            if url.endswith("/login"):
                return FakeResponse(
                    text='<meta name="csrf-token" content="csrf-123" />',
                    headers={"content-type": "text/html"},
                )
            return FakeResponse(json_body=[{"hex": "#FF0000", "name": "Bambu Scarlet"}])

        def post(self, url: str, *, data: dict[str, str], headers: dict[str, str], timeout: float, verify: bool) -> FakeResponse:
            events.append(("POST", url, data))
            return FakeResponse(json_body={"ok": True})

        def request(
            self,
            *,
            method: str,
            url: str,
            params: dict[str, object] | None,
            json: object,
            data: object,
            headers: dict[str, str],
            timeout: float,
            verify: bool,
        ) -> FakeResponse:
            events.append((method, url, headers))
            return FakeResponse(json_body=[{"hex": "#FF0000", "name": "Bambu Scarlet"}])

    monkeypatch.setattr("app.services.requests.Session", lambda: FakeSession())

    service = WorksService()
    result = service.request_sync("stockworks", WorksRequest(method="GET", path="/printlab/filaments"))

    assert result["ok"] is True
    assert events[0][0:2] == ("GET", "https://stockworks.local/login")
    assert events[1] == ("POST", "https://stockworks.local/login", {"username": "admin", "password": "secret", "csrf_token": "csrf-123"})
    assert events[2][0:2] == ("GET", "https://stockworks.local/printlab/filaments")


def _makerworks_api_app() -> FastAPI:
    app = FastAPI()
    register_admin_auth(app)
    app.include_router(api_router)
    return app


def _set_admin_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password("secret"))
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")


def test_makerworks_submit_route_accepts_configured_api_key_auth(monkeypatch) -> None:
    _set_admin_auth(monkeypatch)
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
    _set_admin_auth(monkeypatch)
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
    _set_admin_auth(monkeypatch)
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
