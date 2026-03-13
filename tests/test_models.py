from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import app.views as views
from app.main import create_app
from app.models import MakerworksSubmitJobRequest, QueuePrintJobRequest, WorksRequest
from app.views import (
    render_add_printer_html,
    render_conversion_html,
    render_gallery_html,
    render_makerworks_routing_html,
    render_makerworks_search_html,
    render_printer_dashboard,
)


def test_works_request_rejects_invalid_method() -> None:
    with pytest.raises(ValidationError):
        WorksRequest(method="TRACE", path="/health")


def test_queue_request_accepts_iso_schedule() -> None:
    payload = QueuePrintJobRequest(file_path="/cache/model.3mf", start_at="2026-03-10T12:00:00Z")
    assert payload.start_at == "2026-03-10T12:00:00Z"


def test_makerworks_submit_job_request_accepts_metadata() -> None:
    payload = MakerworksSubmitJobRequest(
        model_id="widget-1",
        idempotency_key="mw-1",
        source_job_id="source-job-1",
        source_order_id="source-order-1",
        metadata={"priority": "rush"},
    )
    assert payload.metadata == {"priority": "rush"}


def test_openapi_contains_queue_schema() -> None:
    schema = create_app().openapi()
    assert "/api/queue" in schema["paths"]
    assert "/api/conversion" in schema["paths"]
    assert "/api/conversion/batch" in schema["paths"]
    assert "/api/conversion/formats" in schema["paths"]
    assert "/api/works/makerworks/jobs" in schema["paths"]
    assert "/api/works/makerworks/jobs/{job_id}" in schema["paths"]
    assert "/api/jobs" in schema["paths"]
    assert "/api/jobs/{job_id}/sync-makerworks" in schema["paths"]
    assert "QueuePrintJobRequest" in schema["components"]["schemas"]


def test_sidebar_pages_include_makerworks_navigation() -> None:
    assert 'href="/conversion"' in render_gallery_html()
    assert 'href="/makerworks"' in render_gallery_html()
    assert 'href="/makerworks-routing"' in render_gallery_html()
    assert 'href="/conversion"' in render_add_printer_html()
    assert 'href="/makerworks"' in render_add_printer_html()
    assert 'href="/conversion"' in render_makerworks_search_html()
    assert 'href="/makerworks-routing"' in render_makerworks_search_html()


def test_printer_dashboard_contains_sidebar_navigation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(views, "service_or_404", lambda _printer_id: SimpleNamespace(display_name="X1C-001"))
    html = render_printer_dashboard("printer-1")
    assert 'id="sidebar"' in html
    assert 'id="sidebarBackdrop"' in html
    assert 'aria-label="Open menu"' in html
    assert 'href="/conversion"' in html
    assert 'href="/makerworks"' in html
    assert 'href="/makerworks-routing"' in html


def test_render_conversion_page_contains_converter_controls() -> None:
    html = render_conversion_html()
    assert 'href="/conversion"' in html
    assert 'id="fileInput"' in html
    assert 'id="targetFormat"' in html
    assert 'id="sourceFormat"' in html
    assert 'id="resultUv"' in html
    assert 'id="batchResultCard"' in html
    assert 'id="batchResultList"' in html
    assert 'id="targetQuickPicks"' in html
    assert 'id="formatCapabilities"' in html
    assert 'id="formatWarnings"' in html
    assert 'id="commonConversionList"' in html
    assert 'multiple' in html
    assert '>OBJ - Recommended<' in html
    assert '>STL<' in html
    assert '>Auto detect<' in html
    assert ".gcode.3mf" in html
    assert "/api/conversion/formats" in html
    assert "/api/conversion/batch" in html
    assert "/api/conversion" in html
    assert "OBJ recommended" in html
    assert "UVs are generated automatically when needed" in html
    assert "3MF to STL" in html
    assert "Scene preservation" in html


def test_render_makerworks_search_page_contains_search_only_controls() -> None:
    html = render_makerworks_search_html()
    assert 'id="makerworksSearch"' in html
    assert 'id="makerworksPageInfo"' in html
    assert "Add To Routing Board" in html
    assert "/makerworks-routing" in html
    assert "changeMakerworksPage" in html
    assert "/api/works/makerworks/library" in html
    assert 'id="routingList"' in html


def test_render_makerworks_routing_page_contains_board_layout() -> None:
    html = render_makerworks_routing_html()
    assert 'id="routingBoard"' in html
    assert 'id="sidebar"' in html
    assert 'id="sidebarBackdrop"' in html
    assert 'onclick="openSidebar()"' in html
    assert 'href="/makerworks-routing"' in html
    assert 'id="leftStack"' in html
    assert 'id="rightStack"' in html
    assert 'id="boardSvg"' in html
    assert "Selected left, then connect right." not in html
    assert "Select left, then connect right." not in html
    assert "/api/works/makerworks/jobs" in html
    assert "/api/jobs?status=queued" in html
    assert "/api/queue/" in html
    assert "wire-live" in html
    assert "@keyframes wireFlow" in html
    assert "moveChosenModel" in html
    assert "startWireDrag" in html
    assert "updateWireDrag" in html
    assert "deleteQueuedJob" in html
    assert "data-printer-id" in html
    assert "Models In Queue" in html
    assert "Printers" in html
    assert "drag-handle right" in html
    assert "drag-cord" in html
    assert "drag-knob" in html
    assert "node routeable" in html
    assert "collapse-toggle" in html
    assert "toggleCardCollapse" in html
    assert "load-confirmation" in html
    assert "Model Loaded" in html
    assert "printerGlowClass" in html
    assert "printer-open" in html
    assert "printer-running" in html
    assert ">Up<" in html
    assert ">Down<" in html
    assert ">Delete<" in html
    assert "Disconnect Printer" in html
    assert "Delete Queue" in html
    assert "Send to slicer" in html
    assert "Import revision" in html
    assert "sendQueuedJobToSlicer" in html
    assert "importQueuedRevision" in html
    assert "queued-routing-row" in html
    assert "queued-meta-row" in html
    assert "bambustudioopen://open?file=" in html


def test_render_makerworks_routing_page_can_target_orcaslicer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLICER_TARGET", "orca_slicer")
    html = views.render_makerworks_routing_html()
    assert 'const slicerTarget = "orca_slicer";' in html
    assert "orcaslicer://open?file=" in html
