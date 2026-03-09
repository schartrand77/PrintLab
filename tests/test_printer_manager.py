from __future__ import annotations

import asyncio
import shutil
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services import AddPrinterRequest, MultiPrinterManager, PrinterService, UpdatePrinterRequest


def _base_definition() -> list[dict[str, object]]:
    return [
        {
            "id": "printer-1",
            "name": "Printer 1",
            "config": {
                "name": "Printer 1",
                "host": "192.168.1.10",
                "serial": "BASE123",
                "access_code": "SECRET",
                "device_type": "x1c",
                "local_mqtt": True,
                "enable_camera": True,
                "disable_ssl_verify": False,
            },
        }
    ]


def _data_dir() -> str:
    path = "tests/.tmp/" + uuid4().hex
    shutil.rmtree(path, ignore_errors=True)
    return path


def test_added_printer_can_be_updated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTLAB_DATA_DIR", _data_dir())
    monkeypatch.setattr(PrinterService, "start", AsyncMock())
    monkeypatch.setattr(PrinterService, "stop", AsyncMock())
    manager = MultiPrinterManager(_base_definition())

    async def run() -> None:
        await manager.add(
            AddPrinterRequest(
                id="printer-2",
                name="Added Printer",
                host="192.168.1.11",
                serial="ADD123",
                access_code="CODE1",
            )
        )
        result = await manager.update(
            "printer-2",
            UpdatePrinterRequest(
                name="Updated Printer",
                host="192.168.1.12",
                serial="ADD999",
                access_code="CODE2",
                enable_camera=False,
            ),
        )
        assert result == {"id": "printer-2", "name": "Updated Printer"}

    asyncio.run(run())
    items = {item["id"]: item for item in manager.list_items()}
    assert items["printer-2"]["name"] == "Updated Printer"
    assert items["printer-2"]["is_added"] is True
    assert items["printer-2"]["config"]["host"] == "192.168.1.12"
    assert items["printer-2"]["config"]["serial"] == "ADD999"
    assert items["printer-2"]["config"]["enable_camera"] is False


def test_added_printer_can_be_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTLAB_DATA_DIR", _data_dir())
    monkeypatch.setattr(PrinterService, "start", AsyncMock())
    monkeypatch.setattr(PrinterService, "stop", AsyncMock())
    manager = MultiPrinterManager(_base_definition())

    async def run() -> None:
        await manager.add(
            AddPrinterRequest(
                id="printer-2",
                name="Added Printer",
                host="192.168.1.11",
                serial="ADD123",
                access_code="CODE1",
            )
        )
        result = await manager.remove("printer-2")
        assert result == {"ok": True, "id": "printer-2"}

    asyncio.run(run())
    assert [item["id"] for item in manager.list_items()] == ["printer-1"]


def test_builtin_printer_cannot_be_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTLAB_DATA_DIR", _data_dir())
    monkeypatch.setattr(PrinterService, "start", AsyncMock())
    monkeypatch.setattr(PrinterService, "stop", AsyncMock())
    manager = MultiPrinterManager(_base_definition())

    async def run() -> None:
        with pytest.raises(ValueError, match="Only printers added from this app can be deleted."):
            await manager.remove("printer-1")

    asyncio.run(run())
