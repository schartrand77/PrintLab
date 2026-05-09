from __future__ import annotations

import asyncio
import json
import shutil
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.auth import actor_from_request, require_role, role_from_request
from app.conversion import (
    BatchModelConversionRequest,
    ModelConversionRequest,
    convert_model_batch,
    convert_model_upload,
    supported_conversion_formats,
)
from app.errors import api_error, from_exception
from app.runtime import job_manager, printer_manager, service_or_404, works_service
from app.services import (
    AddPrinterRequest,
    AlertRuleRequest,
    AlertRuleUpdateRequest,
    CacheCleanupRequest,
    ChamberLightRequest,
    ControlPresetRequest,
    FanRequest,
    MakerworksPreflightRequest,
    MakerworksQueueJobRequest,
    MakerworksSubmitError,
    MakerworksSubmitJobRequest,
    PrinterNameRequest,
    PrintJobRequest,
    QueuePrintJobRequest,
    QueueReorderRequest,
    QueueUpdateRequest,
    SubmittedJobBatchConnectRequest,
    SubmittedJobConnectRequest,
    SubmittedJobQueueRequest,
    SuccessfulGcodeSyncRequest,
    TemperatureRequest,
    TimelapseActionRequest,
    UpdatePrinterRequest,
    WebhookSubscriptionRequest,
    WebhookSubscriptionUpdateRequest,
    WorksRequest,
    data_root,
)

router = APIRouter()


def _require_operator(request: Request) -> None:
    require_role(request, "operator")


def _require_admin(request: Request) -> None:
    require_role(request, "admin")


def _raise_api_error(exc: Exception) -> None:
    raise from_exception(exc) from exc


def _mask_value(value: str, *, keep_start: int = 0, keep_end: int = 4) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    if len(raw) <= keep_start + keep_end:
        return "*" * len(raw)
    hidden = "*" * max(1, len(raw) - keep_start - keep_end)
    return f"{raw[:keep_start]}{hidden}{raw[-keep_end:]}"


def _masked_printer_settings(entry: dict[str, Any]) -> dict[str, Any]:
    config = entry.get("config") or {}
    access_code = str(config.get("access_code") or "")
    return {
        "name": entry["name"],
        "host_masked": _mask_value(str(config.get("host") or ""), keep_end=6),
        "serial_masked": _mask_value(str(config.get("serial") or ""), keep_end=4),
        "access_code_masked": _mask_value(access_code, keep_end=2) if access_code else "",
        "has_access_code": bool(access_code),
        "device_type": config.get("device_type", "unknown"),
        "local_mqtt": bool(config.get("local_mqtt", True)),
        "enable_camera": bool(config.get("enable_camera", True)),
        "disable_ssl_verify": bool(config.get("disable_ssl_verify", False)),
    }


def _full_printer_settings(entry: dict[str, Any]) -> dict[str, Any]:
    config = entry.get("config") or {}
    return {
        "name": entry["name"],
        "host": str(config.get("host") or ""),
        "serial": str(config.get("serial") or ""),
        "access_code": str(config.get("access_code") or ""),
        "device_type": str(config.get("device_type") or "unknown"),
        "local_mqtt": bool(config.get("local_mqtt", True)),
        "enable_camera": bool(config.get("enable_camera", True)),
        "disable_ssl_verify": bool(config.get("disable_ssl_verify", False)),
    }


def _sanitize_state_payload(payload: dict[str, Any], *, is_admin: bool) -> dict[str, Any]:
    state = dict(payload)
    if not is_admin:
        state["webhooks"] = []
    return state


def _storage_health() -> dict[str, Any]:
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(root)
    return {
        "data_root": str(root),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "used_percent": round((usage.used / usage.total) * 100, 1) if usage.total else 0,
    }


def _latest_value(items: list[dict[str, Any]], key: str) -> Any:
    values = [item.get(key) for item in items if item.get(key)]
    return max(values) if values else None


@router.get("/health")
async def health() -> dict[str, Any]:
    state = await service_or_404().state()
    return {
        "ok": state["configured"],
        "configured": state["configured"],
        "connected": state["connected"],
        "last_error": state["last_error"],
    }


@router.get("/api/conversion/formats")
async def conversion_formats() -> dict[str, Any]:
    try:
        return supported_conversion_formats()
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/conversion")
async def convert_model(request: Request, payload: ModelConversionRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        result = convert_model_upload(payload)
        return {"ok": True, **result}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/conversion/batch")
async def convert_model_batch_route(request: Request, payload: BatchModelConversionRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return convert_model_batch(payload)
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/api/printers")
async def list_printers(request: Request) -> dict[str, Any]:
    is_admin = role_from_request(request) == "admin"
    items: list[dict[str, Any]] = []
    for entry in printer_manager.list_items():
        svc = service_or_404(entry["id"])
        state = await svc.state()
        job = state.get("job") or {}
        queue = state.get("queue") or {}
        health = state.get("health") or {}
        active_alerts = state.get("active_alerts") or []
        active_submitted_job = state.get("active_submitted_job")
        items.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "connected": state.get("connected"),
                "configured": state.get("configured"),
                "serial": (state.get("printer") or {}).get("serial") if is_admin else None,
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
                "active_submitted_job": active_submitted_job if isinstance(active_submitted_job, dict) else None,
                "health": {
                    "score": health.get("score"),
                },
                "active_alert_count": len(active_alerts) if isinstance(active_alerts, list) else 0,
                "can_edit": bool(entry.get("is_added")),
                "can_delete": bool(entry.get("is_added")) and entry["id"] != printer_manager.default_id,
                "settings": (_masked_printer_settings(entry) if is_admin else None),
            }
        )
    return {"default_id": printer_manager.default_id, "items": items}


@router.get("/api/printers/{printer_id}/settings")
async def printer_settings(printer_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    for entry in printer_manager.list_items():
        if entry["id"] == printer_id:
            return {"printer_id": printer_id, "settings": _full_printer_settings(entry)}
    raise HTTPException(status_code=404, detail="Printer not found.")


@router.post("/api/printers")
async def add_printer(http_request: Request, request: AddPrinterRequest) -> dict[str, Any]:
    _require_admin(http_request)
    try:
        printer = await printer_manager.add(request)
        return {"ok": True, "printer": printer}
    except Exception as exc:
        _raise_api_error(exc)


@router.patch("/api/printers/{printer_id}")
async def update_printer(printer_id: str, http_request: Request, request: UpdatePrinterRequest) -> dict[str, Any]:
    _require_admin(http_request)
    try:
        printer = await printer_manager.update(printer_id, request)
        return {"ok": True, "printer": printer}
    except Exception as exc:
        _raise_api_error(exc)


@router.delete("/api/printers/{printer_id}")
async def delete_printer(printer_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    try:
        return await printer_manager.remove(printer_id)
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/name")
async def rename_printer(printer_id: str, http_request: Request, request: PrinterNameRequest) -> dict[str, Any]:
    _require_admin(http_request)
    try:
        printer = printer_manager.rename(printer_id, request.name)
        return {"ok": True, "printer": printer}
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/api/state")
async def get_state(request: Request) -> dict[str, Any]:
    return _sanitize_state_payload(await service_or_404().state(), is_admin=role_from_request(request) == "admin")


@router.get("/api/printers/{printer_id}/state")
async def get_state_by_printer(printer_id: str, request: Request) -> dict[str, Any]:
    return _sanitize_state_payload(await service_or_404(printer_id).state(), is_admin=role_from_request(request) == "admin")


@router.get("/api/system/health")
async def system_health(request: Request) -> dict[str, Any]:
    _require_admin(request)
    printer_items: list[dict[str, Any]] = []
    connected_count = 0
    queued_job_count = 0
    youtube_ready_count = 0
    enabled_webhook_count = 0
    webhook_statuses: list[dict[str, Any]] = []
    callback_statuses: list[dict[str, Any]] = []
    sync_statuses: list[dict[str, Any]] = []

    for entry in printer_manager.list_items():
        service = service_or_404(entry["id"])
        snapshot = await service.state()
        queue = snapshot.get("queue") or {}
        system = snapshot.get("system_status") or {}
        youtube = system.get("youtube") or {}
        webhooks_status = system.get("webhooks") or {}
        callback_status = system.get("callback") or {}
        sync_status = system.get("sync") or {}
        connected = bool(snapshot.get("connected"))
        if connected:
            connected_count += 1
        queued_job_count += int(queue.get("count") or 0)
        if youtube.get("ready"):
            youtube_ready_count += 1
        enabled_webhook_count += int(webhooks_status.get("enabled_count") or 0)
        webhook_statuses.append(webhooks_status)
        callback_statuses.append(callback_status)
        sync_statuses.append(sync_status)
        printer_items.append(
            {
                "printer_id": entry["id"],
                "printer_name": entry["name"],
                "configured": bool(snapshot.get("configured")),
                "connected": connected,
                "last_error": snapshot.get("last_error"),
                "last_update_utc": snapshot.get("last_update_utc"),
                "queue": {
                    "count": int(queue.get("count") or 0),
                    "next_item": queue.get("next_item"),
                },
                "health": snapshot.get("health") or {},
                "youtube": youtube,
                "callback": callback_status,
                "webhooks": webhooks_status,
                "sync": sync_status,
            }
        )

    return {
        "summary": {
            "printer_count": len(printer_items),
            "connected_printer_count": connected_count,
            "queued_job_count": queued_job_count,
            "youtube_ready_count": youtube_ready_count,
            "enabled_webhook_count": enabled_webhook_count,
            "audit_count": len(printer_manager.audit_snapshot(limit=500)),
            "last_webhook_delivery_at": _latest_value(webhook_statuses, "last_delivered_at"),
            "last_callback_delivery_at": _latest_value(callback_statuses, "last_delivered_at"),
            "last_sync_error": next((item.get("last_error") for item in sync_statuses if item.get("last_error")), None),
        },
        "storage": _storage_health(),
        "printers": printer_items,
        "services": works_service.list_services(),
    }


@router.get("/api/config/backup")
async def export_config_backup(request: Request) -> dict[str, Any]:
    _require_admin(request)
    return printer_manager.export_config_backup()


@router.post("/api/config/backup/import")
async def import_config_backup(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    _require_admin(request)
    try:
        return printer_manager.import_config_backup(payload, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


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
        _raise_api_error(exc)


@router.get("/api/printers/{printer_id}/works/{service_name}/health")
async def works_health_by_printer(printer_id: str, service_name: str, path: str = "/health") -> dict[str, Any]:
    service = service_or_404(printer_id)
    try:
        result = await works_service.health(service_name, path=path)
        if service_name.lower() == "stockworks":
            result["printer_filament"] = service.filament_snapshot()
        return result
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/works/{service_name}/request")
async def works_request(service_name: str, http_request: Request, request: WorksRequest, printer_id: str | None = None) -> dict[str, Any]:
    _require_operator(http_request)
    try:
        result = await works_service.request(service_name, request)
        if service_name.lower() == "stockworks":
            result["printer_filament"] = service_or_404(printer_id).filament_snapshot()
        return result
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/works/{service_name}/request")
async def works_request_by_printer(printer_id: str, service_name: str, http_request: Request, request: WorksRequest) -> dict[str, Any]:
    _require_operator(http_request)
    service = service_or_404(printer_id)
    try:
        result = await works_service.request(service_name, request)
        if service_name.lower() == "stockworks":
            result["printer_filament"] = service.filament_snapshot()
        return result
    except Exception as exc:
        _raise_api_error(exc)


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
        _raise_api_error(exc)


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
        _raise_api_error(exc)


@router.get("/api/works/makerworks/library/{model_id}")
async def makerworks_library_item(model_id: str, include_raw: bool = True) -> dict[str, Any]:
    try:
        return await works_service.makerworks_library_item(model_id, include_raw=include_raw)
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/api/works/{service}/asset")
async def works_asset(service: str, url: str, timeout_seconds: float = 20.0) -> Response:
    try:
        result = await works_service.download_asset(service, url, timeout_seconds=timeout_seconds)
        content = result.get("content")
        if not content:
            raise HTTPException(status_code=404, detail="Asset not found.")
        media_type = str(result.get("content_type") or "application/octet-stream")
        return Response(content=content, media_type=media_type, headers={"Cache-Control": "public, max-age=3600"})
    except HTTPException:
        raise
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/api/works/{service}/mesh-preview")
async def works_mesh_preview(service: str, url: str, timeout_seconds: float = 30.0) -> Response:
    try:
        content, media_type = await works_service.render_mesh_preview(service, url, timeout_seconds=timeout_seconds)
        return Response(content=content, media_type=media_type, headers={"Cache-Control": "public, max-age=3600"})
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/api/printers/{printer_id}/works/makerworks/library/{model_id}")
async def makerworks_library_item_by_printer(printer_id: str, model_id: str, include_raw: bool = True) -> dict[str, Any]:
    service_or_404(printer_id)
    try:
        return await works_service.makerworks_library_item(model_id, include_raw=include_raw)
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/works/makerworks/queue-job")
async def makerworks_queue_job_by_printer(
    printer_id: str,
    request: Request,
    payload: MakerworksQueueJobRequest,
) -> dict[str, Any]:
    _require_operator(request)
    service = service_or_404(printer_id)
    try:
        if not (await service.state()).get("connected"):
            raise api_error("printer_offline", "Printer is not connected. Choose a connected printer before queueing a MakerWorks model.", 409)
        result = await job_manager.submit_makerworks_job(
            MakerworksSubmitJobRequest(
                model_id=payload.model_id,
                printer_id=printer_id,
                idempotency_key=f"makerworks-printer-queue:{printer_id}:{payload.model_id}:{uuid4().hex}",
                source_job_id=f"makerworks-printer-job:{printer_id}:{payload.model_id}:{uuid4().hex}",
                source_order_id=f"makerworks-printer-order:{payload.model_id}",
                start_at=payload.start_at,
                plate_gcode=payload.plate_gcode,
                use_ams=payload.use_ams,
                ams_mapping=payload.ams_mapping,
                bed_type=payload.bed_type,
                timelapse=payload.timelapse,
                bed_leveling=payload.bed_leveling,
                flow_cali=payload.flow_cali,
                vibration_cali=payload.vibration_cali,
                layer_inspect=payload.layer_inspect,
            ),
            actor=actor_from_request(request),
        )
        return {"ok": True, "queued": True, "printer_id": printer_id, "source_item": result.get("source_item"), **result}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/works/makerworks/preflight")
async def makerworks_preflight(request: Request, payload: MakerworksPreflightRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await job_manager.makerworks_preflight(payload.model_id, printer_id=payload.printer_id)
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/works/makerworks/jobs")
async def makerworks_submit_job(request: Request, payload: MakerworksSubmitJobRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await job_manager.submit_makerworks_job(payload, actor=actor_from_request(request))
    except MakerworksSubmitError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "error": {"code": "submit_failed", "message": str(exc), "details": {"job": exc.job}},
            },
        )
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/api/works/makerworks/jobs/{job_id}")
async def makerworks_get_job(job_id: str) -> dict[str, Any]:
    try:
        return job_manager.get_job(job_id)
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/api/jobs")
async def list_jobs(status: str | None = None) -> dict[str, Any]:
    items = job_manager.list_jobs(status=status)
    return {"items": items, "count": len(items)}


@router.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    try:
        return {"item": job_manager.get_job(job_id)}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/jobs/{job_id}/sync-makerworks")
async def sync_job(job_id: str, request: Request, payload: SuccessfulGcodeSyncRequest | None = None) -> dict[str, Any]:
    _require_operator(request)
    try:
        job = await job_manager.sync_job_to_makerworks(job_id, force=bool(payload and payload.force))
        return {"ok": True, "item": job}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/jobs/{job_id}/queue")
async def queue_submitted_job(job_id: str, request: Request, payload: SubmittedJobQueueRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        item = await job_manager.queue_submitted_job(job_id, printer_id=payload.printer_id, actor=actor_from_request(request), request=payload)
        return {"ok": True, "item": item}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/jobs/{job_id}/connect-current-print")
async def connect_submitted_job_to_current_print(job_id: str, request: Request, payload: SubmittedJobConnectRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        item = await job_manager.connect_submitted_job_to_current_print(job_id, printer_id=payload.printer_id, actor=actor_from_request(request))
        return {"ok": True, "item": item}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/jobs/connect-current-print")
async def connect_submitted_jobs_to_current_print(request: Request, payload: SubmittedJobBatchConnectRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await job_manager.connect_submitted_jobs_to_current_print(
            payload.job_ids,
            printer_id=payload.printer_id,
            actor=actor_from_request(request),
        )
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/api/printers/{printer_id}/jobs")
async def list_jobs_by_printer(printer_id: str, status: str | None = None) -> dict[str, Any]:
    try:
        items = job_manager.list_jobs(printer_id=printer_id, status=status)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/api/printers/{printer_id}/jobs/{job_id}")
async def get_job_by_printer(printer_id: str, job_id: str) -> dict[str, Any]:
    try:
        return {"item": job_manager.get_job(job_id, printer_id=printer_id)}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/jobs/{job_id}/sync-makerworks")
async def sync_job_by_printer(
    printer_id: str,
    job_id: str,
    request: Request,
    payload: SuccessfulGcodeSyncRequest | None = None,
) -> dict[str, Any]:
    _require_operator(request)
    try:
        job = await job_manager.sync_job_to_makerworks(job_id, printer_id=printer_id, force=bool(payload and payload.force))
        return {"ok": True, "item": job}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/print-job")
async def print_job(request: Request, payload: PrintJobRequest, printer_id: str | None = None) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404(printer_id).start_print_job(payload, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/print-job")
async def print_job_by_printer(printer_id: str, request: Request, payload: PrintJobRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404(printer_id).start_print_job(payload, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/api/queue")
async def queue_snapshot() -> dict[str, Any]:
    return service_or_404().queue_snapshot()


@router.get("/api/printers/{printer_id}/queue")
async def queue_snapshot_by_printer(printer_id: str) -> dict[str, Any]:
    return service_or_404(printer_id).queue_snapshot()


@router.post("/api/queue")
async def queue_print_job(request: Request, payload: QueuePrintJobRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404().queue_print_job(payload, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/queue")
async def queue_print_job_by_printer(printer_id: str, request: Request, payload: QueuePrintJobRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404(printer_id).queue_print_job(payload, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.patch("/api/queue/{item_id}")
async def update_queue(item_id: str, request: Request, payload: QueueUpdateRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404().update_queue_item(item_id, payload, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/queue/{item_id}/reorder")
async def reorder_queue(item_id: str, request: Request, payload: QueueReorderRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404().reorder_queue_item(item_id, payload.direction, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.patch("/api/printers/{printer_id}/queue/{item_id}")
async def update_queue_by_printer(printer_id: str, item_id: str, request: Request, payload: QueueUpdateRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404(printer_id).update_queue_item(item_id, payload, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/queue/{item_id}/reorder")
async def reorder_queue_by_printer(printer_id: str, item_id: str, request: Request, payload: QueueReorderRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404(printer_id).reorder_queue_item(item_id, payload.direction, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.delete("/api/queue/{item_id}")
async def remove_queue(item_id: str, request: Request) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404().remove_queue_item(item_id, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.delete("/api/printers/{printer_id}/queue/{item_id}")
async def remove_queue_by_printer(printer_id: str, item_id: str, request: Request) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404(printer_id).remove_queue_item(item_id, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/api/timeline")
async def timeline_snapshot() -> dict[str, Any]:
    return {"items": service_or_404().timeline_snapshot()}


@router.get("/api/printers/{printer_id}/timeline")
async def timeline_snapshot_by_printer(printer_id: str) -> dict[str, Any]:
    return {"items": service_or_404(printer_id).timeline_snapshot()}


@router.get("/api/audit")
async def audit_snapshot(limit: int = 100) -> dict[str, Any]:
    items = printer_manager.audit_snapshot(limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/api/printers/{printer_id}/audit")
async def audit_snapshot_by_printer(printer_id: str, limit: int = 100) -> dict[str, Any]:
    items = printer_manager.audit_snapshot(limit=limit, printer_id=printer_id)
    return {"items": items, "count": len(items)}


@router.get("/api/successful-gcodes")
async def successful_gcodes() -> dict[str, Any]:
    items = service_or_404().successful_gcodes_snapshot()
    return {"items": items, "count": len(items)}


@router.get("/api/printers/{printer_id}/successful-gcodes")
async def successful_gcodes_by_printer(printer_id: str) -> dict[str, Any]:
    items = service_or_404(printer_id).successful_gcodes_snapshot()
    return {"items": items, "count": len(items)}


@router.get("/api/youtube/videos")
async def youtube_videos(page: int = 1, page_size: int = 5) -> dict[str, Any]:
    return service_or_404().youtube_videos_snapshot(page=page, page_size=page_size)


@router.get("/api/printers/{printer_id}/youtube/videos")
async def youtube_videos_by_printer(printer_id: str, page: int = 1, page_size: int = 5) -> dict[str, Any]:
    return service_or_404(printer_id).youtube_videos_snapshot(page=page, page_size=page_size)


@router.post("/api/successful-gcodes/{record_id}/sync-makerworks")
async def sync_successful_gcode(record_id: str, request: Request, payload: SuccessfulGcodeSyncRequest | None = None) -> dict[str, Any]:
    _require_operator(request)
    try:
        record = await service_or_404().sync_successful_gcode(record_id, force=bool(payload and payload.force))
        return {"ok": True, "item": record}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/successful-gcodes/{record_id}/sync-makerworks")
async def sync_successful_gcode_by_printer(
    printer_id: str,
    record_id: str,
    request: Request,
    payload: SuccessfulGcodeSyncRequest | None = None,
) -> dict[str, Any]:
    _require_operator(request)
    try:
        record = await service_or_404(printer_id).sync_successful_gcode(record_id, force=bool(payload and payload.force))
        return {"ok": True, "item": record}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/successful-gcodes/{record_id}/sync-youtube")
async def sync_successful_gcode_to_youtube(
    record_id: str,
    request: Request,
    payload: SuccessfulGcodeSyncRequest | None = None,
) -> dict[str, Any]:
    _require_operator(request)
    try:
        record = await service_or_404().sync_successful_gcode_to_youtube(record_id, force=bool(payload and payload.force))
        return {"ok": True, "item": record}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/successful-gcodes/{record_id}/sync-youtube")
async def sync_successful_gcode_to_youtube_by_printer(
    printer_id: str,
    record_id: str,
    request: Request,
    payload: SuccessfulGcodeSyncRequest | None = None,
) -> dict[str, Any]:
    _require_operator(request)
    try:
        record = await service_or_404(printer_id).sync_successful_gcode_to_youtube(record_id, force=bool(payload and payload.force))
        return {"ok": True, "item": record}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/timelapses/upload-youtube")
async def sync_timelapse_to_youtube(request: Request, payload: TimelapseActionRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        record = await service_or_404().sync_timelapse_to_youtube(payload.path, force=bool(payload.force))
        return {"ok": True, "item": record}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/timelapses/upload-youtube")
async def sync_timelapse_to_youtube_by_printer(printer_id: str, request: Request, payload: TimelapseActionRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        record = await service_or_404(printer_id).sync_timelapse_to_youtube(payload.path, force=bool(payload.force))
        return {"ok": True, "item": record}
    except Exception as exc:
        _raise_api_error(exc)


@router.delete("/api/timelapses")
async def delete_timelapse(request: Request, path: str) -> dict[str, Any]:
    _require_operator(request)
    try:
        result = await service_or_404().delete_timelapse(path)
        return {"ok": True, **result}
    except Exception as exc:
        _raise_api_error(exc)


@router.delete("/api/printers/{printer_id}/timelapses")
async def delete_timelapse_by_printer(printer_id: str, request: Request, path: str) -> dict[str, Any]:
    _require_operator(request)
    try:
        result = await service_or_404(printer_id).delete_timelapse(path)
        return {"ok": True, **result}
    except Exception as exc:
        _raise_api_error(exc)


@router.delete("/api/timelapses/all")
async def delete_all_timelapses(request: Request) -> dict[str, Any]:
    _require_operator(request)
    try:
        result = await service_or_404().delete_all_timelapses()
        return {"ok": True, **result}
    except Exception as exc:
        _raise_api_error(exc)


@router.delete("/api/printers/{printer_id}/timelapses/all")
async def delete_all_timelapses_by_printer(printer_id: str, request: Request) -> dict[str, Any]:
    _require_operator(request)
    try:
        result = await service_or_404(printer_id).delete_all_timelapses()
        return {"ok": True, **result}
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/api/control-presets")
async def control_presets() -> dict[str, Any]:
    return {"items": service_or_404().presets_snapshot()}


@router.get("/api/printers/{printer_id}/control-presets")
async def control_presets_by_printer(printer_id: str) -> dict[str, Any]:
    return {"items": service_or_404(printer_id).presets_snapshot()}


@router.post("/api/control-presets")
async def save_control_preset(request: Request, payload: ControlPresetRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404().save_control_preset(payload, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/control-presets")
async def save_control_preset_by_printer(printer_id: str, request: Request, payload: ControlPresetRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404(printer_id).save_control_preset(payload, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.delete("/api/control-presets/{preset_id}")
async def remove_control_preset(preset_id: str, request: Request) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404().remove_control_preset(preset_id, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.delete("/api/printers/{printer_id}/control-presets/{preset_id}")
async def remove_control_preset_by_printer(printer_id: str, preset_id: str, request: Request) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404(printer_id).remove_control_preset(preset_id, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/api/alert-rules")
async def alert_rules() -> dict[str, Any]:
    return {"items": service_or_404().alert_rules_snapshot()}


@router.get("/api/printers/{printer_id}/alert-rules")
async def alert_rules_by_printer(printer_id: str) -> dict[str, Any]:
    return {"items": service_or_404(printer_id).alert_rules_snapshot()}


@router.post("/api/alert-rules")
async def save_alert_rule(request: Request, payload: AlertRuleRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404().save_alert_rule(payload, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.patch("/api/alert-rules/{rule_id}")
async def update_alert_rule(rule_id: str, request: Request, payload: AlertRuleUpdateRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404().update_alert_rule(rule_id, payload, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/alert-rules")
async def save_alert_rule_by_printer(printer_id: str, request: Request, payload: AlertRuleRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404(printer_id).save_alert_rule(payload, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.patch("/api/printers/{printer_id}/alert-rules/{rule_id}")
async def update_alert_rule_by_printer(printer_id: str, rule_id: str, request: Request, payload: AlertRuleUpdateRequest) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404(printer_id).update_alert_rule(rule_id, payload, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.delete("/api/alert-rules/{rule_id}")
async def remove_alert_rule(rule_id: str, request: Request) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404().remove_alert_rule(rule_id, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.delete("/api/printers/{printer_id}/alert-rules/{rule_id}")
async def remove_alert_rule_by_printer(printer_id: str, rule_id: str, request: Request) -> dict[str, Any]:
    _require_operator(request)
    try:
        return await service_or_404(printer_id).remove_alert_rule(rule_id, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


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


@router.get("/api/system/status")
async def system_status() -> dict[str, Any]:
    printer_items: list[dict[str, Any]] = []
    for entry in printer_manager.list_items():
        service = service_or_404(entry["id"])
        snapshot = await service.state()
        printer_items.append(
            {
                "printer_id": entry["id"],
                "printer_name": entry["name"],
                "connected": snapshot.get("connected"),
                "last_error": snapshot.get("last_error"),
                "system_status": snapshot.get("system_status"),
            }
        )
    return {
        "printers": printer_items,
        "services": works_service.list_services(),
        "audit_count": len(printer_manager.audit_snapshot(limit=500)),
    }


@router.get("/api/webhooks")
async def webhooks(request: Request) -> dict[str, Any]:
    _require_admin(request)
    items: list[dict[str, Any]] = []
    for entry in printer_manager.list_items():
        for hook in service_or_404(entry["id"]).webhooks_snapshot():
            items.append({"printer_id": entry["id"], "printer_name": entry["name"], **hook})
    return {"items": items, "count": len(items)}


@router.get("/api/printers/{printer_id}/webhooks")
async def webhooks_by_printer(printer_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    items = service_or_404(printer_id).webhooks_snapshot()
    return {"items": items, "count": len(items)}


@router.post("/api/printers/{printer_id}/maintenance/timelapse-cleanup")
async def cleanup_timelapse_cache_by_printer(printer_id: str, request: Request, payload: CacheCleanupRequest) -> dict[str, Any]:
    _require_admin(request)
    try:
        return service_or_404(printer_id).cleanup_timelapse_cache(
            max_age_days=payload.max_age_days,
            keep_latest=payload.keep_latest,
            dry_run=payload.dry_run,
            actor=actor_from_request(request),
        )
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/webhooks")
async def save_webhook_by_printer(printer_id: str, request: Request, payload: WebhookSubscriptionRequest) -> dict[str, Any]:
    _require_admin(request)
    try:
        return service_or_404(printer_id).save_webhook(payload, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.patch("/api/printers/{printer_id}/webhooks/{webhook_id}")
async def update_webhook_by_printer(
    printer_id: str,
    webhook_id: str,
    request: Request,
    payload: WebhookSubscriptionUpdateRequest,
) -> dict[str, Any]:
    _require_admin(request)
    try:
        return service_or_404(printer_id).update_webhook(webhook_id, payload, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.delete("/api/printers/{printer_id}/webhooks/{webhook_id}")
async def remove_webhook_by_printer(printer_id: str, webhook_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    try:
        return service_or_404(printer_id).remove_webhook(webhook_id, actor=actor_from_request(request))
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/api/sd/models")
async def sd_models(query: str | None = None) -> JSONResponse:
    try:
        models = await service_or_404().list_sd_models(query=query)
        return JSONResponse(
            {"items": models, "count": len(models)},
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/api/printers/{printer_id}/sd/models")
async def sd_models_by_printer(printer_id: str, query: str | None = None) -> JSONResponse:
    try:
        models = await service_or_404(printer_id).list_sd_models(query=query)
        return JSONResponse(
            {"items": models, "count": len(models)},
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    except Exception as exc:
        _raise_api_error(exc)


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
        _raise_api_error(exc)


@router.get("/api/printers/{printer_id}/sd/thumbnail")
async def sd_thumbnail_by_printer(printer_id: str, path: str) -> Response:
    try:
        content, mime = await service_or_404(printer_id).get_sd_thumbnail(path)
        if not content or not mime:
            raise HTTPException(status_code=404, detail="Thumbnail not found.")
        return Response(
            content=content,
            media_type=mime,
            headers={"Cache-Control": "public, max-age=300"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/api/live/chamber.jpg")
async def chamber_image() -> Response:
    try:
        content, mime = await service_or_404().get_live_frame()
        if not content or not mime:
            return Response(status_code=204)
        return Response(content=content, media_type=mime, headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})
    except Exception as exc:
        _raise_api_error(exc)


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
        _raise_api_error(exc)


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
                        "fps=18",
                        "-f",
                        "image2pipe",
                        "-vcodec",
                        "mjpeg",
                        "-q:v",
                        "4",
                        "pipe:1",
                    ]
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    if proc.stdout is None:
                        raise RuntimeError("ffmpeg did not expose stdout")
                    buffer = bytearray()
                    started = False
                    last_frame_at = asyncio.get_running_loop().time()
                    while True:
                        chunk = await asyncio.wait_for(proc.stdout.read(65536), timeout=5.0)
                        if not chunk:
                            if proc.returncode is not None:
                                break
                            await asyncio.sleep(0.01)
                            if started and (asyncio.get_running_loop().time() - last_frame_at) > 5.0:
                                raise RuntimeError("ffmpeg stream stalled")
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
                            last_frame_at = asyncio.get_running_loop().time()
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
async def refresh(request: Request) -> dict[str, bool]:
    _require_operator(request)
    try:
        await service_or_404().refresh()
        return {"ok": True}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/actions/chamber-light")
async def chamber_light(request: Request, payload: ChamberLightRequest) -> dict[str, bool]:
    _require_operator(request)
    try:
        await service_or_404().set_chamber_light(payload.on, actor=actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/actions/temperature")
async def temperature(request: Request, payload: TemperatureRequest) -> dict[str, bool]:
    _require_operator(request)
    try:
        await service_or_404().set_temperature(payload, actor=actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/actions/fan")
async def fan(request: Request, payload: FanRequest) -> dict[str, bool]:
    _require_operator(request)
    try:
        await service_or_404().set_fan(payload, actor=actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/actions/{action}")
async def action(request: Request, action: str) -> dict[str, bool]:
    _require_operator(request)
    try:
        ok = await service_or_404().action(action, actor=actor_from_request(request))
        return {"ok": ok}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/actions/refresh")
async def refresh_by_printer(printer_id: str, request: Request) -> dict[str, bool]:
    _require_operator(request)
    try:
        await service_or_404(printer_id).refresh()
        return {"ok": True}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/actions/chamber-light")
async def chamber_light_by_printer(printer_id: str, request: Request, payload: ChamberLightRequest) -> dict[str, bool]:
    _require_operator(request)
    try:
        await service_or_404(printer_id).set_chamber_light(payload.on, actor=actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/actions/temperature")
async def temperature_by_printer(printer_id: str, request: Request, payload: TemperatureRequest) -> dict[str, bool]:
    _require_operator(request)
    try:
        await service_or_404(printer_id).set_temperature(payload, actor=actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/actions/fan")
async def fan_by_printer(printer_id: str, request: Request, payload: FanRequest) -> dict[str, bool]:
    _require_operator(request)
    try:
        await service_or_404(printer_id).set_fan(payload, actor=actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/api/printers/{printer_id}/actions/{action}")
async def action_by_printer(printer_id: str, request: Request, action: str) -> dict[str, bool]:
    _require_operator(request)
    try:
        ok = await service_or_404(printer_id).action(action, actor=actor_from_request(request))
        return {"ok": ok}
    except Exception as exc:
        _raise_api_error(exc)
