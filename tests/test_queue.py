from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.services import MakerworksSubmitJobRequest, PrinterService, PrintJobManager


def _service() -> PrinterService:
    return PrinterService(
        config={"host": "127.0.0.1", "serial": "SERIAL", "access_code": "CODE"},
        printer_id="printer-1",
        display_name="Printer 1",
    )


def test_normalize_schedule_converts_to_utc() -> None:
    service = _service()
    assert service._normalize_schedule("2026-03-10T08:00:00-04:00") == "2026-03-10T12:00:00+00:00"


def test_queue_due_item_skips_recent_attempts() -> None:
    service = _service()
    service._queue_items = [
        {
            "id": "a",
            "file_path": "/cache/first.3mf",
            "last_attempt_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "id": "b",
            "file_path": "/cache/second.3mf",
            "start_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        },
    ]

    due_item = service._queue_due_item()
    assert due_item is not None
    assert due_item["id"] == "b"


def test_queue_due_item_waits_for_future_schedule() -> None:
    service = _service()
    service._queue_items = [
        {
            "id": "future",
            "file_path": "/cache/future.3mf",
            "start_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        }
    ]

    assert service._queue_due_item() is None


def test_submitted_job_lifecycle_updates_status() -> None:
    service = _service()
    created = service.create_submitted_job(
        {
            "id": "job-1",
            "status": "queued",
            "file_name": "widget.3mf",
            "file_path": "/cache/widget.3mf",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        message="Queued widget.",
    )

    assert created["status"] == "queued"
    assert created["history"][0]["message"] == "Queued widget."

    updated = service.update_submitted_job(
        "job-1",
        status="completed",
        message="Widget completed.",
        extra={"successful_gcode_id": "record-1"},
    )

    assert updated["status"] == "completed"
    assert updated["successful_gcode_id"] == "record-1"
    assert updated["history"][0]["message"] == "Widget completed."


def test_timeline_entries_are_copied_to_audit_log() -> None:
    service = _service()
    service._record_timeline("queue_add", "Queued widget.", actor="tester", details={"queue_item_id": "q-1"})

    audit = service.audit_snapshot()

    assert audit[0]["event"] == "queue_add"
    assert audit[0]["actor"] == "tester"


class _FakePrinter:
    def __init__(self, printer_id: str, *, connected: bool, busy: bool, queue_count: int) -> None:
        self.printer_id = printer_id
        self.display_name = printer_id.upper()
        self._connected = connected
        self._busy = busy
        self._queue_count = queue_count
        self.created_jobs: list[dict[str, object]] = []

    async def state(self) -> dict[str, object]:
        return {"connected": self._connected, "queue": {"count": self._queue_count}}

    def job_busy(self) -> bool:
        return self._busy

    def find_submitted_job_by_idempotency(self, idempotency_key: str) -> dict[str, object] | None:
        for job in self.created_jobs:
            if job.get("idempotency_key") == idempotency_key:
                return job
        return None

    async def stage_project_bytes(self, content: bytes, preferred_name: str) -> dict[str, object]:
        assert content == b"3mf"
        return {"file_name": preferred_name, "file_path": f"/cache/{preferred_name}"}

    async def queue_print_job(self, _request, actor: str = "dashboard", metadata=None) -> dict[str, object]:
        self._queue_count += 1
        return {
            "item": {
                "id": "queue-1",
                "start_at": None,
                **(metadata or {}),
            },
            "queue": {"count": self._queue_count},
        }

    def create_submitted_job(self, payload: dict[str, object], *, message: str = "Job accepted by PrintLab.") -> dict[str, object]:
        payload = dict(payload)
        payload["history"] = [{"message": message}]
        self.created_jobs.append(payload)
        return payload

    def _record_timeline(self, *_args, **_kwargs) -> None:
        return None


class _FakePrinterManager:
    def __init__(self, printers: list[_FakePrinter]) -> None:
        self._printers = {printer.printer_id: printer for printer in printers}

    def list_items(self) -> list[dict[str, str]]:
        return [{"id": printer_id} for printer_id in self._printers]

    def get(self, printer_id: str):
        return self._printers[printer_id]


class _FakeWorksService:
    async def makerworks_library_item(self, model_id: str, *, include_raw: bool = False) -> dict[str, object]:
        assert include_raw is False
        return {
            "item": {
                "id": model_id,
                "name": "Widget",
                "model_url": "https://makerworks.local/models/widget",
                "download_url": "https://makerworks.local/files/widget.3mf",
                "file_type": "3mf",
                "queue_supported": True,
            }
        }

    async def download_asset(self, service: str, asset_url: str) -> dict[str, object]:
        assert service == "makerworks"
        assert asset_url.endswith("widget.3mf")
        return {"content": b"3mf", "filename": "widget.3mf"}


def test_print_job_manager_auto_selects_idle_connected_printer() -> None:
    busy = _FakePrinter("busy-printer", connected=True, busy=True, queue_count=0)
    idle = _FakePrinter("idle-printer", connected=True, busy=False, queue_count=1)
    offline = _FakePrinter("offline-printer", connected=False, busy=False, queue_count=0)
    manager = PrintJobManager(_FakePrinterManager([busy, idle, offline]), _FakeWorksService())

    result = asyncio.run(
        manager.submit_makerworks_job(
            MakerworksSubmitJobRequest(
                model_id="widget-1",
                idempotency_key="mw-123",
                source_job_id="source-job-1",
                source_order_id="source-order-1",
            ),
            actor="makerworks",
        )
    )

    assert result["printer_id"] == "idle-printer"
    assert idle.created_jobs[0]["idempotency_key"] == "mw-123"


def test_print_job_manager_reuses_existing_idempotent_job_across_printers() -> None:
    first = _FakePrinter("first-printer", connected=True, busy=False, queue_count=0)
    second = _FakePrinter("second-printer", connected=True, busy=False, queue_count=0)
    first.created_jobs.append(
        {
            "id": "job-existing",
            "printer_id": "first-printer",
            "idempotency_key": "mw-123",
            "status": "queued",
        }
    )
    manager = PrintJobManager(_FakePrinterManager([first, second]), _FakeWorksService())

    result = asyncio.run(
        manager.submit_makerworks_job(
            MakerworksSubmitJobRequest(
                model_id="widget-1",
                idempotency_key="mw-123",
                source_job_id="source-job-1",
                source_order_id="source-order-1",
            ),
            actor="makerworks",
        )
    )

    assert result["id"] == "job-existing"
    assert len(second.created_jobs) == 0
