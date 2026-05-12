from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.routers.api as api_routes


def test_makerworks_library_cards_use_proxied_thumbnails() -> None:
    html = Path("app/dashboard.html").read_text(encoding="utf-8")
    makerworks_section = html.split("async function loadMakerworksModels()", 1)[1].split("async function", 1)[0]

    assert "item.thumbnail_proxy_url || item.thumbnail_url || placeholderThumb" in makerworks_section


def test_sd_model_browser_uses_uncached_fetches() -> None:
    html = Path("app/dashboard.html").read_text(encoding="utf-8")
    sd_section = html.split("async function loadSdModels()", 1)[1].split("async function", 1)[0]

    assert 'cache: "no-store"' in sd_section


def test_live_feed_does_not_force_reconnect_after_successful_image_load() -> None:
    html = Path("app/dashboard.html").read_text(encoding="utf-8")
    live_section = html.split("function startLiveFeed()", 1)[1].split("function stopLiveFeed()", 1)[0]

    assert 'setLiveBadge("LIVE", "ok")' in live_section
    assert 'setLiveBadge("RECONNECTING", "err")' not in live_section
    assert "connectStream();" not in live_section.split("img.onerror", 1)[0]


def test_sd_models_api_disables_response_caching(monkeypatch) -> None:
    class FakeService:
        async def list_sd_models(self, query: str | None = None):
            return [{"name": "current.3mf", "path": "/cache/current.3mf"}]

    monkeypatch.setattr(api_routes, "service_or_404", lambda printer_id=None: FakeService())
    app = FastAPI()
    app.include_router(api_routes.router)
    client = TestClient(app)

    response = client.get("/api/printers/printer-1/sd/models")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.json()["items"] == [{"name": "current.3mf", "path": "/cache/current.3mf"}]


def test_routing_board_connections_redraw_on_lane_scroll() -> None:
    html = Path("app/views.py").read_text(encoding="utf-8")
    routing_section = html.split("def render_makerworks_routing_html()", 1)[1]

    assert "function scheduleDrawConnections()" in routing_section
    assert "document.querySelectorAll('#routingBoard .lane-frame').forEach((lane)" in routing_section
    assert "lane.addEventListener('scroll', scheduleDrawConnections" in routing_section
    assert "window.addEventListener('resize', scheduleDrawConnections)" in routing_section


def test_dashboard_exposes_youtube_runtime_upload_setting() -> None:
    html = Path("app/dashboard.html").read_text(encoding="utf-8")

    assert "settingsYoutubeUploadEnabled" in html
    assert "upload_enabled: value(\"settingsYoutubeUploadEnabled\")" in html
