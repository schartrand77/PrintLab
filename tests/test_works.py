from __future__ import annotations

from pathlib import Path

import pytest

from app.services import PrinterService, WorksService


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
