from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.main import create_app
from app.models import MakerworksSubmitJobRequest, QueuePrintJobRequest, WorksRequest
from app.views import render_add_printer_html, render_gallery_html, render_makerworks_html


def test_works_request_rejects_invalid_method() -> None:
    with pytest.raises(ValidationError):
        WorksRequest(method="TRACE", path="/health")


def test_queue_request_accepts_iso_schedule() -> None:
    payload = QueuePrintJobRequest(file_path="/cache/model.3mf", start_at="2026-03-10T12:00:00Z")
    assert payload.start_at == "2026-03-10T12:00:00Z"


def test_makerworks_submit_job_request_accepts_metadata() -> None:
    payload = MakerworksSubmitJobRequest(model_id="widget-1", metadata={"priority": "rush"})
    assert payload.metadata == {"priority": "rush"}


def test_openapi_contains_queue_schema() -> None:
    schema = create_app().openapi()
    assert "/api/queue" in schema["paths"]
    assert "/api/works/makerworks/jobs" in schema["paths"]
    assert "/api/jobs" in schema["paths"]
    assert "/api/jobs/{job_id}/sync-makerworks" in schema["paths"]
    assert "QueuePrintJobRequest" in schema["components"]["schemas"]


def test_sidebar_pages_include_makerworks_navigation() -> None:
    assert 'href="/makerworks"' in render_gallery_html()
    assert 'href="/makerworks"' in render_add_printer_html()


def test_render_makerworks_page_contains_queue_controls() -> None:
    html = render_makerworks_html()
    assert 'id="destinationPrinter"' in html
    assert 'id="queueList"' in html
    assert 'id="jobList"' in html
    assert 'id="makerworksPageInfo"' in html
    assert "Queue To Idle Printer" in html
    assert "changeMakerworksPage" in html
    assert "/api/works/makerworks/library" in html
    assert "/api/works/makerworks/jobs" in html
    assert "/api/jobs/" in html
