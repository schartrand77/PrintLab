from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

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
    def __init__(
        self,
        printer_id: str,
        *,
        connected: bool,
        busy: bool,
        queue_count: int,
        current_job: dict[str, object] | None = None,
        device_type: str = "x1c",
        loaded_filament: dict[str, object] | None = None,
        temperatures: dict[str, object] | None = None,
    ) -> None:
        self.printer_id = printer_id
        self.display_name = printer_id.upper()
        self._connected = connected
        self._busy = busy
        self._queue_count = queue_count
        self._current_job = current_job
        self._device_type = device_type
        self._loaded_filament = loaded_filament
        self._temperatures = temperatures or {}
        self.created_jobs: list[dict[str, object]] = []
        self.connected_contexts: list[dict[str, object]] = []

    async def state(self) -> dict[str, object]:
        return {
            "connected": self._connected,
            "queue": {"count": self._queue_count},
            "printer": {"device_type": self._device_type},
            "job": self._current_job or {"state": "RUNNING" if self._busy else "IDLE", "remaining_minutes": 45 if self._busy else 0},
            "health": {"score": 90 if self._connected else 0},
            "temperatures": self._temperatures,
        }

    def job_busy(self) -> bool:
        return self._busy

    def filament_snapshot(self) -> dict[str, object]:
        loaded = self._loaded_filament
        return {
            "loaded_filament": loaded,
            "remaining_filament": [loaded] if loaded else [],
        }

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

    def submitted_job_record(self, job_id: str) -> dict[str, object]:
        for job in self.created_jobs:
            if job.get("id") == job_id:
                return dict(job)
        raise ValueError(f"Unknown submitted job: {job_id}")

    def submitted_jobs_snapshot(self, *, status: str | None = None) -> list[dict[str, object]]:
        if status == "routing":
            return [dict(job) for job in self.created_jobs if str(job.get("status") or "").lower() in {"queued", "started"}]
        if status:
            return [dict(job) for job in self.created_jobs if str(job.get("status") or "").lower() == status]
        return [dict(job) for job in self.created_jobs]

    def update_submitted_job(self, job_id: str, *, status: str, message: str, details=None, extra=None) -> dict[str, object]:
        for job in self.created_jobs:
            if job.get("id") == job_id:
                job.update(extra or {})
                job["status"] = status
                job["history"] = [{"message": message, "details": details or {}}, *list(job.get("history") or [])]
                return dict(job)
        raise ValueError(f"Unknown submitted job: {job_id}")

    def _record_timeline(self, *_args, **_kwargs) -> None:
        return None

    def attach_submitted_job_to_current_print(self, job: dict[str, object], current_print: dict[str, object], *, actor: str) -> None:
        self.connected_contexts.append({"job": dict(job), "current_print": dict(current_print), "actor": actor})


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
                "materials": [],
                "colors": [],
                "printer_profiles": [],
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


def test_print_job_manager_route_only_submission_waits_for_routing() -> None:
    printer = _FakePrinter("printer-1", connected=True, busy=False, queue_count=0)
    manager = PrintJobManager(_FakePrinterManager([printer]), _FakeWorksService())

    result = asyncio.run(
        manager.submit_makerworks_job(
            MakerworksSubmitJobRequest(
                model_id="widget-1",
                idempotency_key="mw-route-only",
                source_job_id="source-job-1",
                source_order_id="source-order-1",
                route_only=True,
            ),
            actor="makerworks",
        )
    )

    assert result["status"] == "queued"
    assert result["printer_id"] is None
    assert result["queue_item_id"] is None
    assert result["file_path"] is None
    assert result["routing_hold"] is True
    assert printer._queue_count == 0


def test_print_job_manager_route_only_accepts_non_queueable_assets_for_routing() -> None:
    printer = _FakePrinter("printer-1", connected=True, busy=False, queue_count=0)

    class _StlWorksService(_FakeWorksService):
        async def makerworks_library_item(self, model_id: str, *, include_raw: bool = False) -> dict[str, object]:
            result = await super().makerworks_library_item(model_id, include_raw=include_raw)
            result["item"]["download_url"] = "https://makerworks.local/files/widget.stl"
            result["item"]["file_type"] = "stl"
            result["item"]["queue_supported"] = False
            result["item"]["printer_handoff_ready"] = True
            result["item"]["printer_handoff_note"] = "Model assets are available, but this file type is not queueable yet."
            return result

    manager = PrintJobManager(_FakePrinterManager([printer]), _StlWorksService())

    result = asyncio.run(
        manager.submit_makerworks_job(
            MakerworksSubmitJobRequest(
                model_id="widget-1",
                idempotency_key="mw-route-only-stl",
                source_job_id="source-job-1",
                source_order_id="source-order-1",
                route_only=True,
            ),
            actor="makerworks",
        )
    )

    assert result["status"] == "queued"
    assert result["routing_hold"] is True
    assert result["download_url"] == "https://makerworks.local/files/widget.stl"
    assert result["preflight"]["selected_printer_id"] is None
    assert printer._queue_count == 0


def test_print_job_manager_rejects_queueing_route_only_submission_after_assignment() -> None:
    printer = _FakePrinter("printer-1", connected=True, busy=False, queue_count=0)
    manager = PrintJobManager(_FakePrinterManager([printer]), _FakeWorksService())
    held = asyncio.run(
        manager.submit_makerworks_job(
            MakerworksSubmitJobRequest(
                model_id="widget-1",
                idempotency_key="mw-route-only",
                source_job_id="source-job-1",
                source_order_id="source-order-1",
                route_only=True,
            ),
            actor="makerworks",
        )
    )

    with pytest.raises(ValueError, match="manually sliced and connected"):
        asyncio.run(manager.queue_submitted_job(str(held["id"]), printer_id="printer-1", actor="operator"))

    assert printer._queue_count == 0


def test_print_job_manager_connects_route_only_submission_to_current_busy_print_without_queueing() -> None:
    printer = _FakePrinter(
        "printer-1",
        connected=True,
        busy=True,
        queue_count=0,
        current_job={
            "state": "RUNNING",
            "file": "/cache/already-sliced.gcode.3mf",
            "subtask_name": "already-sliced.gcode.3mf",
            "progress_percent": 32,
            "remaining_minutes": 61,
        },
    )
    manager = PrintJobManager(_FakePrinterManager([printer]), _FakeWorksService())
    held = asyncio.run(
        manager.submit_makerworks_job(
            MakerworksSubmitJobRequest(
                model_id="widget-1",
                idempotency_key="mw-route-only",
                source_job_id="source-job-1",
                source_order_id="source-order-1",
                route_only=True,
            ),
            actor="makerworks",
        )
    )

    result = asyncio.run(manager.connect_submitted_job_to_current_print(str(held["id"]), printer_id="printer-1", actor="operator"))

    assert result["status"] == "started"
    assert result["printer_id"] == "printer-1"
    assert result["queue_item_id"] is None
    assert result["file_path"] == "/cache/already-sliced.gcode.3mf"
    assert result["file_name"] == "already-sliced.gcode.3mf"
    assert result["routing_hold"] is False
    assert result["connected_current_print"]["state"] == "RUNNING"
    assert printer.connected_contexts[0]["job"]["id"] == held["id"]
    assert printer.connected_contexts[0]["current_print"]["remaining_minutes"] == 61
    assert printer._queue_count == 0


def test_print_job_manager_connects_multiple_route_only_submissions_to_same_current_print() -> None:
    printer = _FakePrinter(
        "printer-1",
        connected=True,
        busy=True,
        queue_count=0,
        current_job={
            "state": "RUNNING",
            "file": "/cache/turtle-eggs.gcode.3mf",
            "subtask_name": "turtle-eggs.gcode.3mf",
            "progress_percent": 12,
            "remaining_minutes": 182,
        },
    )
    manager = PrintJobManager(_FakePrinterManager([printer]), _FakeWorksService())
    first = asyncio.run(
        manager.submit_makerworks_job(
            MakerworksSubmitJobRequest(
                model_id="egg-1",
                idempotency_key="mw-route-only-1",
                source_job_id="source-job-1",
                source_order_id="source-order-1",
                route_only=True,
            ),
            actor="makerworks",
        )
    )
    second = asyncio.run(
        manager.submit_makerworks_job(
            MakerworksSubmitJobRequest(
                model_id="egg-2",
                idempotency_key="mw-route-only-2",
                source_job_id="source-job-1",
                source_order_id="source-order-1",
                route_only=True,
            ),
            actor="makerworks",
        )
    )

    result = asyncio.run(
        manager.connect_submitted_jobs_to_current_print(
            [str(first["id"]), str(second["id"])],
            printer_id="printer-1",
            actor="operator",
        )
    )

    assert result["count"] == 2
    assert [item["status"] for item in result["items"]] == ["started", "started"]
    assert [item["printer_id"] for item in result["items"]] == ["printer-1", "printer-1"]
    assert [item["file_name"] for item in result["items"]] == ["turtle-eggs.gcode.3mf", "turtle-eggs.gcode.3mf"]
    assert len(printer.connected_contexts) == 2
    assert printer.connected_contexts[0]["current_print"]["remaining_minutes"] == 182
    assert printer.connected_contexts[1]["current_print"]["remaining_minutes"] == 182
    assert printer._queue_count == 0


def test_print_job_manager_routing_status_includes_connected_active_jobs_until_terminal() -> None:
    printer = _FakePrinter(
        "printer-1",
        connected=True,
        busy=True,
        queue_count=0,
        current_job={
            "state": "RUNNING",
            "file": "/cache/already-sliced.gcode.3mf",
            "subtask_name": "already-sliced.gcode.3mf",
            "remaining_minutes": 61,
        },
    )
    manager = PrintJobManager(_FakePrinterManager([printer]), _FakeWorksService())
    held = asyncio.run(
        manager.submit_makerworks_job(
            MakerworksSubmitJobRequest(
                model_id="widget-1",
                idempotency_key="mw-route-only",
                source_job_id="source-job-1",
                source_order_id="source-order-1",
                route_only=True,
            ),
            actor="makerworks",
        )
    )

    asyncio.run(manager.connect_submitted_job_to_current_print(str(held["id"]), printer_id="printer-1", actor="operator"))

    routing_items = manager.list_jobs(status="routing")
    assert [item["id"] for item in routing_items] == [held["id"]]

    printer.update_submitted_job(str(held["id"]), status="completed", message="Done.")

    assert manager.list_jobs(status="routing") == []


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


def test_print_job_manager_uses_order_material_override_for_preflight() -> None:
    printer = _FakePrinter(
        "printer-1",
        connected=True,
        busy=False,
        queue_count=0,
        loaded_filament={"type": "PETG", "name": "PETG Charcoal", "color_name": "Charcoal", "color_hex": "#000000"},
    )

    class _PlaLibraryWorks(_FakeWorksService):
        async def makerworks_library_item(self, model_id: str, *, include_raw: bool = False) -> dict[str, object]:
            result = await super().makerworks_library_item(model_id, include_raw=include_raw)
            result["item"]["materials"] = ["PLA"]
            return result

    manager = PrintJobManager(_FakePrinterManager([printer]), _PlaLibraryWorks())

    result = asyncio.run(
        manager.submit_makerworks_job(
            MakerworksSubmitJobRequest(
                model_id="widget-1",
                printer_id="printer-1",
                idempotency_key="mw-123",
                source_job_id="source-job-1",
                source_order_id="source-order-1",
                metadata={"material": "PETG"},
            ),
            actor="makerworks",
        )
    )

    assert result["status"] == "queued"
    assert result["preflight"]["selected_printer_id"] == "printer-1"


def test_print_job_manager_uses_order_storage_path_for_asset_download() -> None:
    printer = _FakePrinter(
        "printer-1",
        connected=True,
        busy=False,
        queue_count=0,
        loaded_filament={"type": "PETG", "name": "PETG Black", "color_name": "Black", "color_hex": "#000000"},
    )

    class _StoragePathWorks(_FakeWorksService):
        async def download_asset(self, service: str, asset_url: str) -> dict[str, object]:
            assert service == "makerworks"
            assert asset_url == "/files/orders/model.3mf"
            return {"content": b"3mf", "filename": "model.3mf"}

    manager = PrintJobManager(_FakePrinterManager([printer]), _StoragePathWorks())

    result = asyncio.run(
        manager.submit_makerworks_job(
            MakerworksSubmitJobRequest(
                model_id="widget-1",
                printer_id="printer-1",
                idempotency_key="mw-storage-path",
                source_job_id="source-job-1",
                source_order_id="source-order-1",
                metadata={
                    "material": "PETG",
                    "colors": ["Black #000000"],
                    "storage_path": "/orders/model.3mf",
                },
            ),
            actor="makerworks",
        )
    )

    assert result["status"] == "queued"


def test_print_job_manager_preflight_warns_when_loaded_filament_is_low() -> None:
    printer = _FakePrinter(
        "printer-1",
        connected=True,
        busy=False,
        queue_count=0,
        loaded_filament={"type": "PLA", "name": "PLA White", "color_name": "White", "color_hex": "#ffffff", "remaining_percent": 4},
    )

    class _FilamentWorks(_FakeWorksService):
        async def makerworks_library_item(self, model_id: str, *, include_raw: bool = False) -> dict[str, object]:
            result = await super().makerworks_library_item(model_id, include_raw=include_raw)
            result["item"]["materials"] = ["PLA"]
            result["item"]["colors"] = ["White"]
            return result

    manager = PrintJobManager(_FakePrinterManager([printer]), _FilamentWorks())

    preflight = asyncio.run(manager.makerworks_preflight("widget-1"))

    assert preflight["candidates"][0]["filament"]["remaining_percent"] == 4
    assert "low" in preflight["candidates"][0]["filament"]["remaining_message"].lower()


def test_print_job_manager_preflight_blocks_hot_printer_guardrail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUEUE_MAX_CHAMBER_TEMP_C", "45")
    printer = _FakePrinter(
        "printer-1",
        connected=True,
        busy=False,
        queue_count=0,
        loaded_filament={"type": "PLA", "name": "PLA White", "color_name": "White", "color_hex": "#ffffff", "remaining_percent": 80},
        temperatures={"chamber": 52},
    )

    class _FilamentWorks(_FakeWorksService):
        async def makerworks_library_item(self, model_id: str, *, include_raw: bool = False) -> dict[str, object]:
            result = await super().makerworks_library_item(model_id, include_raw=include_raw)
            result["item"]["materials"] = ["PLA"]
            result["item"]["colors"] = ["White"]
            return result

    manager = PrintJobManager(_FakePrinterManager([printer]), _FilamentWorks())

    preflight = asyncio.run(manager.makerworks_preflight("widget-1"))

    assert preflight["qualified_printer_count"] == 0
    assert preflight["candidates"][0]["safety"]["ok"] is False
    assert "chamber" in preflight["candidates"][0]["safety"]["messages"][0].lower()


def test_print_job_manager_routes_when_filament_telemetry_is_unavailable() -> None:
    printer = _FakePrinter(
        "printer-1",
        connected=True,
        busy=False,
        queue_count=0,
        loaded_filament=None,
    )

    class _MaterialWorks(_FakeWorksService):
        async def makerworks_library_item(self, model_id: str, *, include_raw: bool = False) -> dict[str, object]:
            result = await super().makerworks_library_item(model_id, include_raw=include_raw)
            result["item"]["materials"] = ["PETG"]
            return result

    manager = PrintJobManager(_FakePrinterManager([printer]), _MaterialWorks())

    result = asyncio.run(
        manager.submit_makerworks_job(
            MakerworksSubmitJobRequest(
                model_id="widget-1",
                printer_id="printer-1",
                idempotency_key="mw-telemetry",
                source_job_id="source-job-1",
                source_order_id="source-order-1",
            ),
            actor="makerworks",
        )
    )

    assert result["status"] == "queued"
    assert result["preflight"]["selected_printer_id"] == "printer-1"


def test_print_job_manager_preflight_requires_approval_when_multiple_printers_qualify() -> None:
    first = _FakePrinter(
        "first-printer",
        connected=True,
        busy=False,
        queue_count=0,
        loaded_filament={"type": "PLA", "name": "PLA White", "color_name": "White", "color_hex": "#ffffff"},
    )
    second = _FakePrinter(
        "second-printer",
        connected=True,
        busy=False,
        queue_count=0,
        loaded_filament={"type": "PLA", "name": "PLA White", "color_name": "White", "color_hex": "#ffffff"},
    )

    class _FilamentWorks(_FakeWorksService):
        async def makerworks_library_item(self, model_id: str, *, include_raw: bool = False) -> dict[str, object]:
            result = await super().makerworks_library_item(model_id, include_raw=include_raw)
            result["item"]["materials"] = ["PLA"]
            result["item"]["colors"] = ["White"]
            return result

    manager = PrintJobManager(_FakePrinterManager([first, second]), _FilamentWorks())

    preflight = asyncio.run(manager.makerworks_preflight("widget-1"))

    assert preflight["approval_required"] is True
    assert preflight["qualified_printer_count"] == 2
    assert preflight["selected_printer_id"] is None
