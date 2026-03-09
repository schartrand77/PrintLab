from __future__ import annotations

from fastapi import HTTPException

from app.services import MultiPrinterManager, PrinterService, WorksService, load_printer_definitions

printer_manager = MultiPrinterManager(load_printer_definitions())
works_service = WorksService()


def service_or_404(printer_id: str | None = None) -> PrinterService:
    try:
        return printer_manager.get(printer_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def start_runtime() -> None:
    await printer_manager.start()


async def stop_runtime() -> None:
    await printer_manager.stop()
