from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.auth import require_role
from app.views import (
    render_add_printer_html,
    render_conversion_html,
    render_gallery_html,
    render_makerworks_routing_html,
    render_makerworks_search_html,
    render_printer_dashboard,
    static_dir,
)

router = APIRouter()
public_dir = Path(__file__).resolve().parents[2] / "public"


@router.get("/", response_class=HTMLResponse)
async def dashboard_root() -> str:
    return render_gallery_html()


@router.get("/printer/{printer_id}", response_class=HTMLResponse)
async def printer_dashboard(printer_id: str) -> str:
    return render_printer_dashboard(printer_id)


@router.get("/add-printer", response_class=HTMLResponse)
async def add_printer_page(request: Request) -> str:
    require_role(request, "admin")
    return render_add_printer_html()


@router.get("/makerworks", response_class=HTMLResponse)
async def makerworks_page() -> str:
    return render_makerworks_search_html()


@router.get("/makerworks-routing", response_class=HTMLResponse)
async def makerworks_routing_page() -> str:
    return render_makerworks_routing_html()


@router.get("/conversion", response_class=HTMLResponse)
async def conversion_page() -> str:
    return render_conversion_html()


@router.get("/manifest.webmanifest")
async def manifest() -> FileResponse:
    return FileResponse(
        static_dir / "manifest.webmanifest",
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/sw.js")
async def service_worker() -> FileResponse:
    return FileResponse(static_dir / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/favicon.ico")
async def favicon() -> FileResponse:
    return FileResponse(public_dir / "printlab.png", media_type="image/png")


@router.get("/printlab.png")
async def printlab_icon() -> FileResponse:
    return FileResponse(public_dir / "printlab.png", media_type="image/png")


@router.get("/apple-touch-icon.png")
async def apple_touch_icon() -> FileResponse:
    return FileResponse(static_dir / "icons" / "apple-touch-icon.png", media_type="image/png")
