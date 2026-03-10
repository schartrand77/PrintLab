from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from app.auth import actor_from_request
from app.runtime import printer_manager, service_or_404, works_service
from app.services import (
    AddPrinterRequest,
    AlertRuleRequest,
    AlertRuleUpdateRequest,
    ChamberLightRequest,
    ControlPresetRequest,
    FanRequest,
    MakerworksQueueJobRequest,
    OrderworksPrintJobRequest,
    PrinterNameRequest,
    QueuePrintJobRequest,
    QueueReorderRequest,
    QueueUpdateRequest,
    SuccessfulGcodeSyncRequest,
    TemperatureRequest,
    UpdatePrinterRequest,
    WorksRequest,
)

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, Any]:
    state = await service_or_404().state()
    return {
        "ok": state["configured"],
        "configured": state["configured"],
        "connected": state["connected"],
        "last_error": state["last_error"],
    }


@router.get("/api/printers")
async def list_printers() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for entry in printer_manager.list_items():
        svc = service_or_404(entry["id"])
        state = await svc.state()
        job = state.get("job") or {}
        queue = state.get("queue") or {}
        health = state.get("health") or {}
        active_alerts = state.get("active_alerts") or []
        items.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "connected": state.get("connected"),
                "configured": state.get("configured"),
                "serial": (state.get("printer") or {}).get("serial"),
                "device_type": (state.get("printer") or {}).get("device_type"),
                "last_error": state.get("last_error"),
                "job": {
                    "state": job.get("state"),
                    "progress_percent": job.get("progress_percent"),
                    "file": job.get("file"),
                    "subtask_name": job.get("subtask_name"),
                    "current_layer": job.get("current_layer"),
                    "total_layers": job.get("total_layers"),
                    "remaining_minutes": job.get("remaining_minutes"),
                    "thumbnail_url": job.get("thumbnail_url"),
                },
                "queue": {
                    "count": queue.get("count", 0),
                    "next_item": queue.get("next_item"),
                },
                "health": {
                    "score": health.get("score"),
                },
                "active_alert_count": len(active_alerts) if isinstance(active_alerts, list) else 0,
                "can_edit": bool(entry.get("is_added")),
                "can_delete": bool(entry.get("is_added")) and entry["id"] != printer_manager.default_id,
                "settings": {
                    "name": entry["name"],
                    "host": (entry.get("config") or {}).get("host", ""),
                    "serial": (entry.get("config") or {}).get("serial", ""),
                    "access_code": (entry.get("config") or {}).get("access_code", ""),
                    "device_type": (entry.get("config") or {}).get("device_type", "unknown"),
                    "local_mqtt": bool((entry.get("config") or {}).get("local_mqtt", True)),
                    "enable_camera": bool((entry.get("config") or {}).get("enable_camera", True)),
                    "disable_ssl_verify": bool((entry.get("config") or {}).get("disable_ssl_verify", False)),
                },
            }
        )
    return {"default_id": printer_manager.default_id, "items": items}


@router.post("/api/printers")
async def add_printer(request: AddPrinterRequest) -> dict[str, Any]:
    try:
        printer = await printer_manager.add(request)
        return {"ok": True, "printer": printer}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/printers/{printer_id}")
async def update_printer(printer_id: str, request: UpdatePrinterRequest) -> dict[str, Any]:
    try:
        printer = await printer_manager.update(printer_id, request)
        return {"ok": True, "printer": printer}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/printers/{printer_id}")
async def delete_printer(printer_id: str) -> dict[str, Any]:
    try:
        return await printer_manager.remove(printer_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/printers/{printer_id}/name")
async def rename_printer(printer_id: str, request: PrinterNameRequest) -> dict[str, Any]:
    try:
        printer = printer_manager.rename(printer_id, request.name)
        return {"ok": True, "printer": printer}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/state")
async def get_state() -> dict[str, Any]:
    return await service_or_404().state()


@router.get("/api/printers/{printer_id}/state")
async def get_state_by_printer(printer_id: str) -> dict[str, Any]:
    return await service_or_404(printer_id).state()


@router.get("/api/works/services")
async def works_services() -> dict[str, Any]:
    return {"items": works_service.list_services()}


@router.get("/api/works/{service_name}/health")
async def works_health(service_name: str, path: str = "/health", printer_id: str | None = None) -> dict[str, Any]:
    try:
        result = await works_service.health(service_name, path=path)
        if service_name.lower() == "stockworks":
            result["printer_filament"] = service_or_404(printer_id).filament_snapshot()
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/printers/{printer_id}/works/{service_name}/health")
async def works_health_by_printer(printer_id: str, service_name: str, path: str = "/health") -> dict[str, Any]:
    service = service_or_404(printer_id)
    try:
        result = await works_service.health(service_name, path=path)
        if service_name.lower() == "stockworks":
            result["printer_filament"] = service.filament_snapshot()
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/works/{service_name}/request")
async def works_request(service_name: str, request: WorksRequest, printer_id: str | None = None) -> dict[str, Any]:
    try:
        result = await works_service.request(service_name, request)
        if service_name.lower() == "stockworks":
            result["printer_filament"] = service_or_404(printer_id).filament_snapshot()
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/printers/{printer_id}/works/{service_name}/request")
async def works_request_by_printer(printer_id: str, service_name: str, request: WorksRequest) -> dict[str, Any]:
    service = service_or_404(printer_id)
    try:
        result = await works_service.request(service_name, request)
        if service_name.lower() == "stockworks":
            result["printer_filament"] = service.filament_snapshot()
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/works/makerworks/library")
async def makerworks_library(
    query: str | None = None,
    page: int = 1,
    page_size: int | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    try:
        return await works_service.makerworks_library(query=query, page=page, page_size=page_size, include_raw=include_raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/printers/{printer_id}/works/makerworks/library")
async def makerworks_library_by_printer(
    printer_id: str,
    query: str | None = None,
    page: int = 1,
    page_size: int | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    service_or_404(printer_id)
    try:
        return await works_service.makerworks_library(query=query, page=page, page_size=page_size, include_raw=include_raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/works/makerworks/library/{model_id}")
async def makerworks_library_item(model_id: str, include_raw: bool = True) -> dict[str, Any]:
    try:
        return await works_service.makerworks_library_item(model_id, include_raw=include_raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/printers/{printer_id}/works/makerworks/library/{model_id}")
async def makerworks_library_item_by_printer(printer_id: str, model_id: str, include_raw: bool = True) -> dict[str, Any]:
    service_or_404(printer_id)
    try:
        return await works_service.makerworks_library_item(model_id, include_raw=include_raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/printers/{printer_id}/works/makerworks/queue-job")
async def makerworks_queue_job_by_printer(
    printer_id: str,
    request: Request,
    payload: MakerworksQueueJobRequest,
) -> dict[str, Any]:
    service = service_or_404(printer_id)
    try:
        if not (await service.state()).get("connected"):
            raise ValueError("Printer is not connected. Choose a connected printer before queueing a MakerWorks model.")
        if service.job_busy():
            raise ValueError("Printer is currently printing. Choose a printer that is not actively printing.")

        detail = await works_service.makerworks_library_item(payload.model_id, include_raw=False)
        item = detail["item"]
        if not item.get("queue_supported"):
            raise ValueError(item.get("printer_handoff_note") or "This MakerWorks model cannot be queued yet.")

        asset = await works_service.download_asset("makerworks", str(item.get("download_url") or ""))
        preferred_base = re.sub(r"[^A-Za-z0-9._-]+", "-", f"makerworks-{item.get('id') or payload.model_id}-{item.get('name') or 'model'}").strip("._-")
        preferred_name = f"{preferred_base[:96]}{Path(str(asset.get('filename') or '')).suffix or '.3mf'}"
        if str(asset.get("filename") or "").lower().endswith(".gcode.3mf"):
            preferred_name = f"{preferred_base[:96]}.gcode.3mf"

        staged = await service.stage_project_bytes(bytes(asset["content"]), preferred_name)
        queue_request = QueuePrintJobRequest(
            file_path=str(staged["file_path"]),
            plate_gcode=payload.plate_gcode,
            use_ams=payload.use_ams,
            ams_mapping=payload.ams_mapping,
            bed_type=payload.bed_type,
            timelapse=payload.timelapse,
            bed_leveling=payload.bed_leveling,
            flow_cali=payload.flow_cali,
            vibration_cali=payload.vibration_cali,
            layer_inspect=payload.layer_inspect,
            start_at=payload.start_at,
        )
        result = await service.queue_print_job(
            queue_request,
            actor=actor_from_request(request),
            metadata={
                "display_name": item.get("name"),
                "source": "makerworks",
                "source_model_id": item.get("id"),
                "source_model_url": item.get("model_url"),
                "source_download_url": item.get("download_url"),
                "source_file_type": item.get("file_type"),
                "staged_file_name": staged.get("file_name"),
            },
        )
        return {"ok": True, "queued": True, "printer_id": printer_id, "source_item": item, **result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/works/orderworks/print-job")
async def orderworks_print_job(request: Request, payload: OrderworksPrintJobRequest, printer_id: str | None = None) -> dict[str, Any]:
    try:
        return await service_or_404(printer_id).start_orderworks_print_job(payload, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/printers/{printer_id}/works/orderworks/print-job")
async def orderworks_print_job_by_printer(printer_id: str, request: Request, payload: OrderworksPrintJobRequest) -> dict[str, Any]:
    try:
        return await service_or_404(printer_id).start_orderworks_print_job(payload, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/queue")
async def queue_snapshot() -> dict[str, Any]:
    return service_or_404().queue_snapshot()


@router.get("/api/printers/{printer_id}/queue")
async def queue_snapshot_by_printer(printer_id: str) -> dict[str, Any]:
    return service_or_404(printer_id).queue_snapshot()


@router.post("/api/queue")
async def queue_print_job(request: Request, payload: QueuePrintJobRequest) -> dict[str, Any]:
    try:
        return await service_or_404().queue_print_job(payload, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/printers/{printer_id}/queue")
async def queue_print_job_by_printer(printer_id: str, request: Request, payload: QueuePrintJobRequest) -> dict[str, Any]:
    try:
        return await service_or_404(printer_id).queue_print_job(payload, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/queue/{item_id}")
async def update_queue(item_id: str, request: Request, payload: QueueUpdateRequest) -> dict[str, Any]:
    try:
        return await service_or_404().update_queue_item(item_id, payload, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/queue/{item_id}/reorder")
async def reorder_queue(item_id: str, request: Request, payload: QueueReorderRequest) -> dict[str, Any]:
    try:
        return await service_or_404().reorder_queue_item(item_id, payload.direction, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/printers/{printer_id}/queue/{item_id}")
async def update_queue_by_printer(printer_id: str, item_id: str, request: Request, payload: QueueUpdateRequest) -> dict[str, Any]:
    try:
        return await service_or_404(printer_id).update_queue_item(item_id, payload, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/printers/{printer_id}/queue/{item_id}/reorder")
async def reorder_queue_by_printer(printer_id: str, item_id: str, request: Request, payload: QueueReorderRequest) -> dict[str, Any]:
    try:
        return await service_or_404(printer_id).reorder_queue_item(item_id, payload.direction, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/queue/{item_id}")
async def remove_queue(item_id: str, request: Request) -> dict[str, Any]:
    try:
        return await service_or_404().remove_queue_item(item_id, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/printers/{printer_id}/queue/{item_id}")
async def remove_queue_by_printer(printer_id: str, item_id: str, request: Request) -> dict[str, Any]:
    try:
        return await service_or_404(printer_id).remove_queue_item(item_id, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/timeline")
async def timeline_snapshot() -> dict[str, Any]:
    return {"items": service_or_404().timeline_snapshot()}


@router.get("/api/printers/{printer_id}/timeline")
async def timeline_snapshot_by_printer(printer_id: str) -> dict[str, Any]:
    return {"items": service_or_404(printer_id).timeline_snapshot()}


@router.get("/api/successful-gcodes")
async def successful_gcodes() -> dict[str, Any]:
    items = service_or_404().successful_gcodes_snapshot()
    return {"items": items, "count": len(items)}


@router.get("/api/printers/{printer_id}/successful-gcodes")
async def successful_gcodes_by_printer(printer_id: str) -> dict[str, Any]:
    items = service_or_404(printer_id).successful_gcodes_snapshot()
    return {"items": items, "count": len(items)}


@router.post("/api/successful-gcodes/{record_id}/sync-makerworks")
async def sync_successful_gcode(record_id: str, payload: SuccessfulGcodeSyncRequest | None = None) -> dict[str, Any]:
    try:
        record = await service_or_404().sync_successful_gcode(record_id, force=bool(payload and payload.force))
        return {"ok": True, "item": record}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/printers/{printer_id}/successful-gcodes/{record_id}/sync-makerworks")
async def sync_successful_gcode_by_printer(
    printer_id: str,
    record_id: str,
    payload: SuccessfulGcodeSyncRequest | None = None,
) -> dict[str, Any]:
    try:
        record = await service_or_404(printer_id).sync_successful_gcode(record_id, force=bool(payload and payload.force))
        return {"ok": True, "item": record}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/control-presets")
async def control_presets() -> dict[str, Any]:
    return {"items": service_or_404().presets_snapshot()}


@router.get("/api/printers/{printer_id}/control-presets")
async def control_presets_by_printer(printer_id: str) -> dict[str, Any]:
    return {"items": service_or_404(printer_id).presets_snapshot()}


@router.post("/api/control-presets")
async def save_control_preset(request: Request, payload: ControlPresetRequest) -> dict[str, Any]:
    try:
        return await service_or_404().save_control_preset(payload, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/printers/{printer_id}/control-presets")
async def save_control_preset_by_printer(printer_id: str, request: Request, payload: ControlPresetRequest) -> dict[str, Any]:
    try:
        return await service_or_404(printer_id).save_control_preset(payload, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/control-presets/{preset_id}")
async def remove_control_preset(preset_id: str, request: Request) -> dict[str, Any]:
    try:
        return await service_or_404().remove_control_preset(preset_id, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/printers/{printer_id}/control-presets/{preset_id}")
async def remove_control_preset_by_printer(printer_id: str, preset_id: str, request: Request) -> dict[str, Any]:
    try:
        return await service_or_404(printer_id).remove_control_preset(preset_id, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/alert-rules")
async def alert_rules() -> dict[str, Any]:
    return {"items": service_or_404().alert_rules_snapshot()}


@router.get("/api/printers/{printer_id}/alert-rules")
async def alert_rules_by_printer(printer_id: str) -> dict[str, Any]:
    return {"items": service_or_404(printer_id).alert_rules_snapshot()}


@router.post("/api/alert-rules")
async def save_alert_rule(request: Request, payload: AlertRuleRequest) -> dict[str, Any]:
    try:
        return await service_or_404().save_alert_rule(payload, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/alert-rules/{rule_id}")
async def update_alert_rule(rule_id: str, request: Request, payload: AlertRuleUpdateRequest) -> dict[str, Any]:
    try:
        return await service_or_404().update_alert_rule(rule_id, payload, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/printers/{printer_id}/alert-rules")
async def save_alert_rule_by_printer(printer_id: str, request: Request, payload: AlertRuleRequest) -> dict[str, Any]:
    try:
        return await service_or_404(printer_id).save_alert_rule(payload, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/printers/{printer_id}/alert-rules/{rule_id}")
async def update_alert_rule_by_printer(printer_id: str, rule_id: str, request: Request, payload: AlertRuleUpdateRequest) -> dict[str, Any]:
    try:
        return await service_or_404(printer_id).update_alert_rule(rule_id, payload, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/alert-rules/{rule_id}")
async def remove_alert_rule(rule_id: str, request: Request) -> dict[str, Any]:
    try:
        return await service_or_404().remove_alert_rule(rule_id, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/printers/{printer_id}/alert-rules/{rule_id}")
async def remove_alert_rule_by_printer(printer_id: str, rule_id: str, request: Request) -> dict[str, Any]:
    try:
        return await service_or_404(printer_id).remove_alert_rule(rule_id, actor=actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/events")
async def event_stream(request: Request) -> StreamingResponse:
    queue = service_or_404().subscribe_events()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"event: printer\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            service_or_404().unsubscribe_events(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/printers/{printer_id}/events")
async def event_stream_by_printer(request: Request, printer_id: str) -> StreamingResponse:
    svc = service_or_404(printer_id)
    queue = svc.subscribe_events()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"event: printer\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            svc.unsubscribe_events(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/sd/models")
async def sd_models(query: str | None = None) -> dict[str, Any]:
    try:
        models = await service_or_404().list_sd_models(query=query)
        return {"items": models, "count": len(models)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/printers/{printer_id}/sd/models")
async def sd_models_by_printer(printer_id: str, query: str | None = None) -> dict[str, Any]:
    try:
        models = await service_or_404(printer_id).list_sd_models(query=query)
        return {"items": models, "count": len(models)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/sd/thumbnail")
async def sd_thumbnail(path: str) -> Response:
    try:
        content, mime = await service_or_404().get_sd_thumbnail(path)
        if not content or not mime:
            raise HTTPException(status_code=404, detail="Thumbnail not found.")
        return Response(content=content, media_type=mime, headers={"Cache-Control": "public, max-age=86400"})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/printers/{printer_id}/sd/thumbnail")
async def sd_thumbnail_by_printer(printer_id: str, path: str) -> Response:
    try:
        content, mime = await service_or_404(printer_id).get_sd_thumbnail(path)
        if not content or not mime:
            raise HTTPException(status_code=404, detail="Thumbnail not found.")
        return Response(content=content, media_type=mime, headers={"Cache-Control": "public, max-age=86400"})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/live/chamber.jpg")
async def chamber_image() -> Response:
    try:
        content, mime = await service_or_404().get_live_frame()
        if not content or not mime:
            return Response(status_code=204)
        return Response(content=content, media_type=mime, headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/live/stream.mjpg")
async def chamber_stream() -> StreamingResponse:
    return await chamber_stream_by_printer(printer_manager.default_id)


@router.get("/api/printers/{printer_id}/live/chamber.jpg")
async def chamber_image_by_printer(printer_id: str) -> Response:
    try:
        content, mime = await service_or_404(printer_id).get_live_frame()
        if not content or not mime:
            return Response(status_code=204)
        return Response(content=content, media_type=mime, headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/printers/{printer_id}/live/stream.mjpg")
async def chamber_stream_by_printer(printer_id: str) -> StreamingResponse:
    service = service_or_404(printer_id)
    boundary = "frame"

    async def frame_generator():
        try:
            for rtsp_url in service._rtsp_urls_to_try():
                proc = None
                try:
                    cmd = [
                        "ffmpeg",
                        "-nostdin",
                        "-loglevel",
                        "error",
                        "-rtsp_transport",
                        "tcp",
                        "-fflags",
                        "nobuffer",
                        "-flags",
                        "low_delay",
                        "-probesize",
                        "32",
                        "-analyzeduration",
                        "0",
                        "-i",
                        rtsp_url,
                        "-an",
                        "-vf",
                        "fps=12",
                        "-f",
                        "image2pipe",
                        "-vcodec",
                        "mjpeg",
                        "-q:v",
                        "6",
                        "pipe:1",
                    ]
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    if proc.stdout is None:
                        raise RuntimeError("ffmpeg did not expose stdout")
                    buffer = bytearray()
                    started = False
                    while True:
                        chunk = await proc.stdout.read(65536)
                        if not chunk:
                            if proc.returncode is not None:
                                break
                            await asyncio.sleep(0.01)
                            continue
                        started = True
                        buffer.extend(chunk)
                        while True:
                            start = buffer.find(b"\xff\xd8")
                            if start < 0:
                                if len(buffer) > 1:
                                    del buffer[:-1]
                                break
                            if start > 0:
                                del buffer[:start]
                            end = buffer.find(b"\xff\xd9", 2)
                            if end < 0:
                                break
                            frame = bytes(buffer[: end + 2])
                            del buffer[: end + 2]
                            header = (
                                f"--{boundary}\r\n"
                                f"Content-Type: image/jpeg\r\n"
                                f"Content-Length: {len(frame)}\r\n\r\n"
                            ).encode("ascii")
                            yield header
                            yield frame
                            yield b"\r\n"
                    if started:
                        return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
                finally:
                    if proc is not None:
                        try:
                            if proc.returncode is None:
                                proc.terminate()
                                await asyncio.wait_for(proc.wait(), timeout=1.2)
                        except Exception:
                            try:
                                proc.kill()
                            except Exception:
                                pass

            while True:
                content, mime = await service.get_live_frame()
                if content and mime:
                    header = (
                        f"--{boundary}\r\n"
                        f"Content-Type: {mime}\r\n"
                        f"Content-Length: {len(content)}\r\n\r\n"
                    ).encode("ascii")
                    yield header
                    yield content
                    yield b"\r\n"
                await asyncio.sleep(0.22)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        frame_generator(),
        media_type=f"multipart/x-mixed-replace; boundary={boundary}",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@router.post("/api/actions/refresh")
async def refresh() -> dict[str, bool]:
    try:
        await service_or_404().refresh()
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/actions/chamber-light")
async def chamber_light(request: Request, payload: ChamberLightRequest) -> dict[str, bool]:
    try:
        await service_or_404().set_chamber_light(payload.on, actor=actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/actions/temperature")
async def temperature(request: Request, payload: TemperatureRequest) -> dict[str, bool]:
    try:
        await service_or_404().set_temperature(payload, actor=actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/actions/fan")
async def fan(request: Request, payload: FanRequest) -> dict[str, bool]:
    try:
        await service_or_404().set_fan(payload, actor=actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/actions/{action}")
async def action(request: Request, action: str) -> dict[str, bool]:
    try:
        ok = await service_or_404().action(action, actor=actor_from_request(request))
        return {"ok": ok}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/printers/{printer_id}/actions/refresh")
async def refresh_by_printer(printer_id: str) -> dict[str, bool]:
    try:
        await service_or_404(printer_id).refresh()
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/printers/{printer_id}/actions/chamber-light")
async def chamber_light_by_printer(printer_id: str, request: Request, payload: ChamberLightRequest) -> dict[str, bool]:
    try:
        await service_or_404(printer_id).set_chamber_light(payload.on, actor=actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/printers/{printer_id}/actions/temperature")
async def temperature_by_printer(printer_id: str, request: Request, payload: TemperatureRequest) -> dict[str, bool]:
    try:
        await service_or_404(printer_id).set_temperature(payload, actor=actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/printers/{printer_id}/actions/fan")
async def fan_by_printer(printer_id: str, request: Request, payload: FanRequest) -> dict[str, bool]:
    try:
        await service_or_404(printer_id).set_fan(payload, actor=actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/printers/{printer_id}/actions/{action}")
async def action_by_printer(printer_id: str, request: Request, action: str) -> dict[str, bool]:
    try:
        ok = await service_or_404(printer_id).action(action, actor=actor_from_request(request))
        return {"ok": ok}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
