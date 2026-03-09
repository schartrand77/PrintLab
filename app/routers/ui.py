from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from app.views import render_add_printer_html, render_gallery_html, render_printer_dashboard, static_dir

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard_root() -> str:
    return render_gallery_html()


@router.get("/printer/{printer_id}", response_class=HTMLResponse)
async def printer_dashboard(printer_id: str) -> str:
    return render_printer_dashboard(printer_id)


@router.get("/add-printer", response_class=HTMLResponse)
async def add_printer_page() -> str:
    return render_add_printer_html()


@router.get("/manifest.webmanifest")
async def manifest() -> FileResponse:
    return FileResponse(static_dir / "manifest.webmanifest", media_type="application/manifest+json")


@router.get("/sw.js")
async def service_worker() -> FileResponse:
    return FileResponse(static_dir / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/favicon.ico")
async def favicon() -> FileResponse:
    return FileResponse(static_dir / "icons" / "icon-192.png", media_type="image/png")
