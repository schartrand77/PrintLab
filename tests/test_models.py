from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.main import create_app
from app.models import QueuePrintJobRequest, WorksRequest


def test_works_request_rejects_invalid_method() -> None:
    with pytest.raises(ValidationError):
        WorksRequest(method="TRACE", path="/health")


def test_queue_request_accepts_iso_schedule() -> None:
    payload = QueuePrintJobRequest(file_path="/cache/model.3mf", start_at="2026-03-10T12:00:00Z")
    assert payload.start_at == "2026-03-10T12:00:00Z"


def test_openapi_contains_queue_schema() -> None:
    schema = create_app().openapi()
    assert "/api/queue" in schema["paths"]
    assert "QueuePrintJobRequest" in schema["components"]["schemas"]
