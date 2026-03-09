from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import PrinterService


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
