from __future__ import annotations

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
