from __future__ import annotations

import asyncio
import base64
import binascii
import copy
import io
import hashlib
import hmac
import json
import re
import logging
import os
import requests
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4
from zipfile import ZipFile

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pybambu import BambuClient
from pybambu.commands import PAUSE, PRINT_PROJECT_FILE_TEMPLATE, RESUME, STOP
from pybambu.const import FansEnum, TempEnum


LOGGER = logging.getLogger("printlab")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
if ADMIN_PASSWORD:
    LOGGER.info("Admin password protection enabled.")
else:
    LOGGER.warning("Admin password protection is disabled (ADMIN_PASSWORD not set).")


def parse_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_default_printer_config() -> dict[str, Any]:
    return {
        "name": os.getenv("PRINTER_NAME", "").strip(),
        "host": os.getenv("PRINTER_HOST", "").strip(),
        "serial": os.getenv("PRINTER_SERIAL", "").strip(),
        "access_code": os.getenv("PRINTER_ACCESS_CODE", "").strip(),
        "device_type": os.getenv("PRINTER_DEVICE_TYPE", "unknown"),
        "local_mqtt": parse_bool("PRINTER_LOCAL_MQTT", True),
        "enable_camera": parse_bool("PRINTER_ENABLE_CAMERA", True),
        "disable_ssl_verify": parse_bool("PRINTER_DISABLE_SSL_VERIFY", False),
        "user_language": os.getenv("USER_LANGUAGE", "en"),
        "file_cache_path": os.getenv("FILE_CACHE_PATH", "/data/cache"),
        "print_cache_count": int(os.getenv("PRINT_CACHE_COUNT", "1")),
        "timelapse_cache_count": int(os.getenv("TIMELAPSE_CACHE_COUNT", "0")),
        "usage_hours": float(os.getenv("USAGE_HOURS", "0")),
        "force_ip": parse_bool("FORCE_IP", False),
        "region": os.getenv("BAMBU_REGION", ""),
        "email": os.getenv("BAMBU_EMAIL", ""),
        "username": os.getenv("BAMBU_USERNAME", ""),
        "auth_token": os.getenv("BAMBU_AUTH_TOKEN", ""),
    }


def load_printer_definitions() -> list[dict[str, Any]]:
    raw = os.getenv("PRINTERS_JSON", "").strip()
    default_cfg = build_default_printer_config()
    if not raw:
        return [{"id": "printer-1", "name": default_cfg.get("name") or default_cfg.get("serial") or "Printer 1", "config": default_cfg}]

    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("PRINTERS_JSON must be a JSON array.")
        items: list[dict[str, Any]] = []
        for i, entry in enumerate(data, start=1):
            if not isinstance(entry, dict):
                continue
            merged = {**default_cfg, **entry}
            printer_id = str(entry.get("id") or f"printer-{i}").strip()
            if not printer_id:
                printer_id = f"printer-{i}"
            display_name = str(entry.get("name") or merged.get("name") or merged.get("serial") or f"Printer {i}")
            items.append({"id": printer_id, "name": display_name, "config": merged})
        if items:
            return items
    except Exception as exc:
        LOGGER.warning("Invalid PRINTERS_JSON, falling back to single printer config: %s", exc)

    return [{"id": "printer-1", "name": default_cfg.get("name") or default_cfg.get("serial") or "Printer 1", "config": default_cfg}]


class FanRequest(BaseModel):
    fan: str = Field(pattern="^(part_cooling|auxiliary|chamber|heatbreak|secondary_auxiliary)$")
    percent: int = Field(ge=0, le=100)


class TemperatureRequest(BaseModel):
    target: str = Field(pattern="^(heatbed|nozzle)$")
    value: int = Field(ge=0, le=320)


class ChamberLightRequest(BaseModel):
    on: bool


class PrinterNameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class AddPrinterRequest(BaseModel):
    id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=64)
    host: str = Field(min_length=1, max_length=255)
    serial: str = Field(min_length=1, max_length=128)
    access_code: str = Field(min_length=1, max_length=128)
    device_type: str = Field(default="unknown", max_length=64)
    local_mqtt: bool = True
    enable_camera: bool = True
    disable_ssl_verify: bool = False


class WorksRequest(BaseModel):
    method: str = Field(pattern="^(GET|POST|PUT|PATCH|DELETE)$")
    path: str = Field(default="/")
    query: dict[str, Any] | None = None
    body: Any = None
    headers: dict[str, str] | None = None
    timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)


class OrderworksPrintJobRequest(BaseModel):
    file_path: str = Field(min_length=1, description="Path to .3mf/.gcode.3mf on printer SD card, e.g. /cache/model.3mf")
    plate_gcode: str = Field(default="Metadata/plate_1.gcode")
    subtask_name: str | None = None
    use_ams: bool = True
    ams_mapping: list[int] | None = None
    bed_type: str = "auto"
    timelapse: bool = False
    bed_leveling: bool = True
    flow_cali: bool = True
    vibration_cali: bool = True
    layer_inspect: bool = True


class QueuePrintJobRequest(OrderworksPrintJobRequest):
    start_at: str | None = Field(default=None, description="UTC ISO timestamp for scheduled start.")


class QueueUpdateRequest(BaseModel):
    start_at: str | None = Field(default=None, description="UTC ISO timestamp for scheduled start.")


class ControlPresetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    nozzle_target: int | None = Field(default=None, ge=0, le=320)
    bed_target: int | None = Field(default=None, ge=0, le=130)
    part_cooling: int | None = Field(default=None, ge=0, le=100)
    auxiliary: int | None = Field(default=None, ge=0, le=100)
    chamber: int | None = Field(default=None, ge=0, le=100)


class AlertRuleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    type: str = Field(pattern="^(disconnect_duration|chamber_temp_above|print_error|queue_backlog)$")
    enabled: bool = True
    threshold: float | None = Field(default=None, ge=0)
    severity: str = Field(default="warning", pattern="^(info|warning|error)$")
    notify: bool = True


class AlertRuleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    type: str | None = Field(default=None, pattern="^(disconnect_duration|chamber_temp_above|print_error|queue_backlog)$")
    enabled: bool | None = None
    threshold: float | None = Field(default=None, ge=0)
    severity: str | None = Field(default=None, pattern="^(info|warning|error)$")
    notify: bool | None = None


class QueueReorderRequest(BaseModel):
    direction: str = Field(pattern="^(up|down)$")


class WorksService:
    def __init__(self) -> None:
        self._service_env: dict[str, str] = {
            "makerworks": "MAKERWORKS",
            "orderworks": "ORDERWORKS",
            "stockworks": "STOCKWORKS",
        }

    def _get_config(self, service: str) -> dict[str, Any]:
        key = self._service_env.get(service.lower())
        if key is None:
            raise ValueError(f"Unknown integration service: {service}")

        base_url = os.getenv(f"{key}_BASE_URL", "").strip()
        api_key = os.getenv(f"{key}_API_KEY", "").strip()
        bearer_token = os.getenv(f"{key}_BEARER_TOKEN", "").strip()
        auth_header = os.getenv(f"{key}_AUTH_HEADER", "X-API-Key").strip() or "X-API-Key"
        verify_ssl = parse_bool(f"{key}_VERIFY_SSL", True)

        return {
            "service": service.lower(),
            "base_url": base_url,
            "api_key": api_key,
            "bearer_token": bearer_token,
            "auth_header": auth_header,
            "verify_ssl": verify_ssl,
            "configured": bool(base_url),
        }

    def list_services(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for service in self._service_env:
            cfg = self._get_config(service)
            items.append(
                {
                    "service": cfg["service"],
                    "configured": cfg["configured"],
                    "base_url": cfg["base_url"],
                }
            )
        return items

    def _build_url(self, base_url: str, path: str) -> str:
        if not base_url:
            raise RuntimeError("Service is not configured (missing BASE_URL).")
        raw_path = (path or "/").strip()
        if raw_path.startswith("http://") or raw_path.startswith("https://"):
            raise ValueError("Absolute URLs are not allowed in request path.")
        if not raw_path.startswith("/"):
            raw_path = f"/{raw_path}"
        return f"{base_url.rstrip('/')}{raw_path}"

    def request_sync(self, service: str, payload: WorksRequest) -> dict[str, Any]:
        cfg = self._get_config(service)
        url = self._build_url(cfg["base_url"], payload.path)

        headers: dict[str, str] = {"Accept": "application/json"}
        if cfg["api_key"]:
            headers[cfg["auth_header"]] = cfg["api_key"]
        if cfg["bearer_token"]:
            headers["Authorization"] = f"Bearer {cfg['bearer_token']}"
        if payload.headers:
            headers.update(payload.headers)

        response = requests.request(
            method=payload.method,
            url=url,
            params=payload.query or None,
            json=payload.body,
            headers=headers,
            timeout=payload.timeout_seconds,
            verify=cfg["verify_ssl"],
        )

        content_type = response.headers.get("content-type", "")
        parsed_body: Any
        if "application/json" in content_type.lower():
            try:
                parsed_body = response.json()
            except Exception:
                parsed_body = response.text
        else:
            parsed_body = response.text

        return {
            "service": cfg["service"],
            "url": url,
            "ok": response.ok,
            "status_code": response.status_code,
            "content_type": content_type,
            "headers": {
                "content-type": response.headers.get("content-type"),
                "location": response.headers.get("location"),
            },
            "body": parsed_body,
        }

    async def request(self, service: str, payload: WorksRequest) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.request_sync, service, payload)

    async def health(self, service: str, path: str = "/health", timeout_seconds: float = 8.0) -> dict[str, Any]:
        payload = WorksRequest(method="GET", path=path, timeout_seconds=timeout_seconds)
        return await self.request(service, payload)


class PrinterService:
    def __init__(self, config: dict[str, Any], printer_id: str, display_name: str | None = None) -> None:
        self.printer_id = printer_id
        self.display_name = display_name or printer_id
        self._configured_settings = config
        self.client: BambuClient | None = None
        self.last_event = "init"
        self.last_error: str | None = None
        self.last_update_utc: str | None = None
        self.configured = False
        self._lock = asyncio.Lock()
        self._live_cache_bytes: bytes | None = None
        self._live_cache_mime: str | None = None
        self._live_cache_time: float = 0.0
        self._event_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._queue_file = Path(f"/data/queue_{printer_id}.json")
        self._timeline_file = Path(f"/data/timeline_{printer_id}.json")
        self._presets_file = Path(f"/data/control_presets_{printer_id}.json")
        self._alert_rules_file = Path(f"/data/alert_rules_{printer_id}.json")
        self._queue_items: list[dict[str, Any]] = self._load_json_list(self._queue_file)
        self._timeline_entries: list[dict[str, Any]] = self._load_json_list(self._timeline_file)
        self._control_presets: list[dict[str, Any]] = self._load_json_list(self._presets_file)
        self._alert_rules: list[dict[str, Any]] = self._load_json_list(self._alert_rules_file)
        self._queue_task: asyncio.Task[None] | None = None
        self._disconnected_since_utc: str | None = None

    def _load_json_list(self, path: Path) -> list[dict[str, Any]]:
        try:
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    return [item for item in payload if isinstance(item, dict)]
        except Exception as exc:
            LOGGER.warning("Failed to load %s: %s", path.name, exc)
        return []

    def _save_json_list(self, path: Path, payload: list[dict[str, Any]]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            LOGGER.warning("Failed to save %s: %s", path.name, exc)

    def _save_queue(self) -> None:
        self._save_json_list(self._queue_file, self._queue_items)

    def _save_timeline(self) -> None:
        self._save_json_list(self._timeline_file, self._timeline_entries)

    def _save_presets(self) -> None:
        self._save_json_list(self._presets_file, self._control_presets)

    def _save_alert_rules(self) -> None:
        self._save_json_list(self._alert_rules_file, self._alert_rules)

    def _timeline_entry(
        self,
        event: str,
        message: str,
        *,
        severity: str = "info",
        actor: str = "system",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": uuid4().hex,
            "event": event,
            "message": message,
            "severity": severity,
            "actor": actor,
            "details": details or {},
            "at": datetime.now(timezone.utc).isoformat(),
        }

    def _record_timeline(
        self,
        event: str,
        message: str,
        *,
        severity: str = "info",
        actor: str = "system",
        details: dict[str, Any] | None = None,
    ) -> None:
        entry = self._timeline_entry(event, message, severity=severity, actor=actor, details=details)
        self._timeline_entries = [entry, *self._timeline_entries[:199]]
        self._save_timeline()

    def _normalize_schedule(self, start_at: str | None) -> str | None:
        raw = (start_at or "").strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("start_at must be a valid ISO timestamp.") from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()

    def _job_busy(self) -> bool:
        if self.client is None or not self.client.connected:
            return False
        try:
            state = str(self.client.get_device().print_job.gcode_state or "").upper()
        except Exception:
            return False
        if not state:
            return False
        idle_markers = ("IDLE", "FINISH", "COMPLETE", "FAILED", "STOP")
        return not any(marker in state for marker in idle_markers)

    def _queue_due_item(self) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        for item in self._queue_items:
            last_attempt_raw = item.get("last_attempt_at")
            if last_attempt_raw:
                try:
                    last_attempt = datetime.fromisoformat(str(last_attempt_raw).replace("Z", "+00:00"))
                    if last_attempt.tzinfo is None:
                        last_attempt = last_attempt.replace(tzinfo=timezone.utc)
                    if last_attempt.astimezone(timezone.utc) > now - timedelta(seconds=60):
                        continue
                except ValueError:
                    pass
            start_at_raw = item.get("start_at")
            if not start_at_raw:
                return item
            try:
                start_at = datetime.fromisoformat(str(start_at_raw).replace("Z", "+00:00"))
            except ValueError:
                return item
            if start_at.tzinfo is None:
                start_at = start_at.replace(tzinfo=timezone.utc)
            if start_at.astimezone(timezone.utc) <= now:
                return item
        return None

    def queue_snapshot(self) -> dict[str, Any]:
        next_item = self._queue_items[0] if self._queue_items else None
        return {
            "count": len(self._queue_items),
            "next_item": next_item,
            "items": list(self._queue_items),
        }

    def timeline_snapshot(self) -> list[dict[str, Any]]:
        return list(self._timeline_entries[:50])

    def presets_snapshot(self) -> list[dict[str, Any]]:
        return list(self._control_presets)

    def alert_rules_snapshot(self) -> list[dict[str, Any]]:
        return list(self._alert_rules)

    def _ensure_default_alert_rules(self) -> None:
        if self._alert_rules:
            return
        self._alert_rules = [
            {"id": uuid4().hex, "name": "Disconnected > 2 min", "type": "disconnect_duration", "enabled": True, "threshold": 2, "severity": "warning", "notify": True},
            {"id": uuid4().hex, "name": "Chamber temp > 50C", "type": "chamber_temp_above", "enabled": False, "threshold": 50, "severity": "warning", "notify": False},
            {"id": uuid4().hex, "name": "Print error detected", "type": "print_error", "enabled": True, "threshold": None, "severity": "error", "notify": True},
        ]
        self._save_alert_rules()

    def _evaluate_alert_rules(
        self,
        *,
        connected: bool,
        chamber_temp: float | None,
        print_error: Any,
        queue_count: int,
    ) -> list[dict[str, Any]]:
        self._ensure_default_alert_rules()
        alerts: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        disconnected_minutes = None
        if self._disconnected_since_utc:
            try:
                disconnected_since = datetime.fromisoformat(self._disconnected_since_utc.replace("Z", "+00:00"))
                if disconnected_since.tzinfo is None:
                    disconnected_since = disconnected_since.replace(tzinfo=timezone.utc)
                disconnected_minutes = max(0.0, (now - disconnected_since.astimezone(timezone.utc)).total_seconds() / 60.0)
            except ValueError:
                disconnected_minutes = None

        for rule in self._alert_rules:
            rule.setdefault("severity", "warning")
            rule.setdefault("notify", True)
            if not rule.get("enabled", True):
                continue
            rule_type = str(rule.get("type") or "")
            threshold = rule.get("threshold")
            severity = str(rule.get("severity") or "warning")
            notify = bool(rule.get("notify", True))
            if rule_type == "disconnect_duration":
                threshold_minutes = float(threshold or 0)
                if not connected and disconnected_minutes is not None and disconnected_minutes >= threshold_minutes:
                    alerts.append({
                        "rule_id": rule.get("id"),
                        "rule_name": rule.get("name"),
                        "type": rule_type,
                        "severity": severity,
                        "notify": notify,
                        "message": f"Printer disconnected for {int(disconnected_minutes)} min.",
                    })
            elif rule_type == "chamber_temp_above":
                threshold_temp = float(threshold or 0)
                if chamber_temp is not None and chamber_temp > threshold_temp:
                    alerts.append({
                        "rule_id": rule.get("id"),
                        "rule_name": rule.get("name"),
                        "type": rule_type,
                        "severity": severity,
                        "notify": notify,
                        "message": f"Chamber temperature is {round(chamber_temp)}C.",
                    })
            elif rule_type == "print_error":
                if print_error:
                    alerts.append({
                        "rule_id": rule.get("id"),
                        "rule_name": rule.get("name"),
                        "type": rule_type,
                        "severity": severity,
                        "notify": notify,
                        "message": "Printer reported a print error.",
                    })
            elif rule_type == "queue_backlog":
                threshold_count = int(float(threshold or 0))
                if queue_count > threshold_count:
                    alerts.append({
                        "rule_id": rule.get("id"),
                        "rule_name": rule.get("name"),
                        "type": rule_type,
                        "severity": severity,
                        "notify": notify,
                        "message": f"Queue backlog is {queue_count} jobs.",
                    })
        return alerts

    def _config(self) -> dict[str, Any]:
        cfg = dict(self._configured_settings)
        host = str(cfg.get("host", "")).strip()
        serial = str(cfg.get("serial", "")).strip()
        access_code = str(cfg.get("access_code", "")).strip()
        if not host or not serial or not access_code:
            raise ValueError("PRINTER_HOST, PRINTER_SERIAL, and PRINTER_ACCESS_CODE are required.")
        return cfg

    def _mark_event(self, event: str) -> None:
        self.last_event = event
        self.last_update_utc = datetime.now(timezone.utc).isoformat()
        self._broadcast_event(event)

    def _on_client_event(self, event: str) -> None:
        self._mark_event(event)
        event_name = str(event or "")
        lower = event_name.lower()
        severity = "error" if "error" in lower else ("warning" if "disconnect" in lower else "info")
        if "disconnect" in lower and self._disconnected_since_utc is None:
            self._disconnected_since_utc = datetime.now(timezone.utc).isoformat()
        elif "connect" in lower:
            self._disconnected_since_utc = None
        self._record_timeline(event_name or "printer_event", f"Printer event: {event_name or 'unknown'}", severity=severity)

    def _broadcast_event(self, event: str) -> None:
        payload = {"event": event, "at": self.last_update_utc}

        def _send() -> None:
            for queue in list(self._event_subscribers):
                try:
                    if queue.full():
                        queue.get_nowait()
                    queue.put_nowait(payload)
                except Exception:
                    self._event_subscribers.discard(queue)

        if self._main_loop and self._main_loop.is_running():
            try:
                running_loop = asyncio.get_running_loop()
                if running_loop is self._main_loop:
                    _send()
                    return
            except RuntimeError:
                pass
            self._main_loop.call_soon_threadsafe(_send)
            return
        _send()

    def subscribe_events(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=40)
        self._event_subscribers.add(queue)
        queue.put_nowait({"event": self.last_event, "at": self.last_update_utc})
        return queue

    def unsubscribe_events(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._event_subscribers.discard(queue)

    async def start(self) -> None:
        self._main_loop = asyncio.get_running_loop()
        try:
            cfg = self._config()
            self.configured = True
        except Exception as exc:
            self.configured = False
            self.last_error = str(exc)
            LOGGER.error("Configuration error: %s", exc)
            return

        try:
            self.client = BambuClient(cfg)
            await self.client.connect(self._on_client_event)
            await self.client.refresh()
            self._mark_event("connected")
            self.last_error = None
            self._disconnected_since_utc = None
            self._record_timeline("connected", "Printer connected.", actor="system")
            if self._queue_task is None or self._queue_task.done():
                self._queue_task = asyncio.create_task(self._queue_worker())
            LOGGER.info("Connected to printer %s", cfg["serial"])
        except Exception as exc:
            self.last_error = str(exc)
            if self._disconnected_since_utc is None:
                self._disconnected_since_utc = datetime.now(timezone.utc).isoformat()
            self._record_timeline("connect_failed", f"Failed to connect: {exc}", severity="error", actor="system")
            LOGGER.exception("Failed to connect to printer")

    async def stop(self) -> None:
        if self._queue_task is not None:
            self._queue_task.cancel()
            self._queue_task = None
        if self.client is not None:
            self.client.disconnect()
            self._mark_event("disconnected")
            if self._disconnected_since_utc is None:
                self._disconnected_since_utc = datetime.now(timezone.utc).isoformat()
            self._record_timeline("disconnected", "Printer disconnected.", severity="warning", actor="system")

    async def action(self, action: str, actor: str = "dashboard") -> bool:
        if self.client is None:
            raise RuntimeError("Client not initialized.")

        if action == "pause":
            ok = self.client.publish(PAUSE)
            self._record_timeline("pause", "Pause requested.", actor=actor, severity="warning")
            return ok
        if action == "resume":
            ok = self.client.publish(RESUME)
            self._record_timeline("resume", "Resume requested.", actor=actor)
            return ok
        if action == "stop":
            ok = self.client.publish(STOP)
            self._record_timeline("stop", "Stop requested.", actor=actor, severity="warning")
            return ok
        raise ValueError(f"Unknown action: {action}")

    async def set_chamber_light(self, on: bool, actor: str = "dashboard") -> None:
        if self.client is None:
            raise RuntimeError("Client not initialized.")
        device = self.client.get_device()
        if on:
            device.lights.TurnChamberLightOn()
        else:
            device.lights.TurnChamberLightOff()
        self._mark_event("event_light_update")
        self._record_timeline("chamber_light", f"Chamber light turned {'on' if on else 'off'}.", actor=actor)

    async def set_temperature(self, request: TemperatureRequest, actor: str = "dashboard") -> None:
        if self.client is None:
            raise RuntimeError("Client not initialized.")
        target = TempEnum.HEATBED if request.target == "heatbed" else TempEnum.NOZZLE
        self.client.get_device().temperature.set_target_temp(target, request.value)
        self._mark_event("event_temperature_update")
        self._record_timeline("temperature", f"Set {request.target} target to {request.value}C.", actor=actor)

    async def set_fan(self, request: FanRequest, actor: str = "dashboard") -> None:
        if self.client is None:
            raise RuntimeError("Client not initialized.")
        fan_map = {
            "part_cooling": FansEnum.PART_COOLING,
            "auxiliary": FansEnum.AUXILIARY,
            "chamber": FansEnum.CHAMBER,
            "heatbreak": FansEnum.HEATBREAK,
            "secondary_auxiliary": FansEnum.SECONDARY_AUXILIARY,
        }
        self.client.get_device().fans.set_fan_speed(fan_map[request.fan], request.percent)
        self._mark_event("event_fan_update")
        self._record_timeline("fan", f"Set {request.fan} fan to {request.percent}%.", actor=actor)

    async def refresh(self) -> None:
        if self.client is None:
            raise RuntimeError("Client not initialized.")
        await self.client.refresh()
        self._mark_event("refresh_requested")

    def _list_sd_models_sync(self, query: str | None = None) -> list[dict[str, Any]]:
        if self.client is None:
            raise RuntimeError("Client not initialized.")

        ftp = self.client.ftp_connection()
        entries: list[dict[str, Any]] = []
        dirs = ["/cache", "/"]
        seen: set[str] = set()

        pattern_time = re.compile(r"^\S+\s+\d+\s+\S+\s+\S+\s+(\d+)\s+(\S+\s+\d+\s+\d+:\d+)\s+(.+)$")
        pattern_year = re.compile(r"^\S+\s+\d+\s+\S+\s+\S+\s+(\d+)\s+(\S+\s+\d+\s+\d+)\s+(.+)$")

        def thumbnail_url_for_path(path: str, name: str) -> str | None:
            cache_dir = Path("/data/cache/prints")
            if cache_dir.exists():
                def normalize_base(value: str) -> str:
                    lowered = value.lower()
                    for suffix in (".gcode.3mf", ".3mf", ".gcode"):
                        if lowered.endswith(suffix):
                            lowered = lowered[: -len(suffix)]
                            break
                    lowered = lowered.replace("_", "-").replace(" ", "-")
                    lowered = re.sub(r"-+", "-", lowered).strip("-")
                    return lowered

                candidates: list[str] = []
                lower = name.lower()
                if lower.endswith(".gcode.3mf"):
                    candidates.append(name[:-10])
                elif lower.endswith(".3mf"):
                    candidates.append(name[:-4])
                elif lower.endswith(".gcode"):
                    candidates.append(name[:-6])
                candidates.append(name)

                exts = [".png", ".jpg", ".jpeg", ".webp"]
                thumb_files: list[Path] = []
                for ext in exts:
                    thumb_files.extend(cache_dir.glob(f"*{ext}"))

                # 1) Exact stem match first.
                for stem in candidates:
                    for ext in exts:
                        p = cache_dir / f"{stem}{ext}"
                        if p.exists():
                            return f"/data/cache/prints/{p.name}"

                # 2) Match by numeric ID prefix (e.g. "20906356-...").
                id_match = re.match(r"^(\d+)-", name)
                if id_match:
                    model_id = id_match.group(1)
                    for p in thumb_files:
                        if p.stem.startswith(f"{model_id}-"):
                            return f"/data/cache/prints/{p.name}"

                # 3) Strict normalized stem equality as final safe fallback.
                model_norm = normalize_base(name)
                for p in thumb_files:
                    if normalize_base(p.stem) == model_norm:
                        return f"/data/cache/prints/{p.name}"

            # Dynamic route can fetch from SD and cache thumbnail if local cache misses.
            return f"/api/sd/thumbnail?path={quote(path, safe='')}"

        def parse_line(base: str, line: str) -> None:
            match = pattern_time.match(line) or pattern_year.match(line)
            if not match:
                return

            size_raw, ts_raw, name = match.groups()
            lower = name.lower()
            if not (lower.endswith(".3mf") or lower.endswith(".gcode") or lower.endswith(".gcode.3mf")):
                return

            path = f"{base.rstrip('/')}/{name}" if base != "/" else f"/{name}"
            if path in seen:
                return
            seen.add(path)

            if query and query.lower() not in name.lower():
                return

            timestamp = None
            try:
                if ":" in ts_raw:
                    # FTP LIST without year: infer year relative to now to avoid future-dated entries.
                    dt = datetime.strptime(ts_raw, "%b %d %H:%M").replace(tzinfo=timezone.utc)
                    now_utc = datetime.now().astimezone(timezone.utc)
                    dt = dt.replace(year=now_utc.year)
                    delta = dt - now_utc
                    six_months = timedelta(days=190)
                    if delta > six_months:
                        dt = dt.replace(year=now_utc.year - 1)
                    elif delta < -six_months:
                        dt = dt.replace(year=now_utc.year + 1)
                else:
                    dt = datetime.strptime(ts_raw, "%b %d %Y").replace(tzinfo=timezone.utc)
                timestamp = dt.isoformat()
            except Exception:
                timestamp = None

            entries.append(
                {
                    "name": name,
                    "path": path,
                    "size_bytes": int(size_raw),
                    "modified": timestamp,
                    "thumbnail_url": thumbnail_url_for_path(path, name),
                }
            )

        try:
            for d in dirs:
                try:
                    ftp.retrlines(f"LIST {d}", lambda line: parse_line(d, line))
                except Exception:
                    continue
        finally:
            try:
                ftp.quit()
            except Exception:
                pass

        entries.sort(key=lambda x: ((x.get("modified") or ""), x["name"]), reverse=True)
        return entries[:200]

    async def list_sd_models(self, query: str | None = None) -> list[dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._list_sd_models_sync, query)

    def _get_sd_thumbnail_sync(self, path: str) -> tuple[bytes | None, str | None]:
        if self.client is None:
            raise RuntimeError("Client not initialized.")

        thumb_dir = Path("/data/cache/sd_thumbs")
        thumb_dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha1(path.encode("utf-8")).hexdigest()
        for ext, mime in ((".png", "image/png"), (".jpg", "image/jpeg"), (".jpeg", "image/jpeg"), (".webp", "image/webp")):
            p = thumb_dir / f"{key}{ext}"
            if p.exists():
                return p.read_bytes(), mime

        ftp = self.client.ftp_connection()
        model_name = Path(path).name
        base_dir = str(Path(path).parent).replace("\\", "/")
        if base_dir == ".":
            base_dir = "/"

        lower = model_name.lower()
        base_name = model_name
        for suffix in (".gcode.3mf", ".3mf", ".gcode"):
            if lower.endswith(suffix):
                base_name = model_name[: -len(suffix)]
                break

        def try_retr(remote_path: str) -> bytes | None:
            data = bytearray()
            try:
                ftp.retrbinary(f"RETR {remote_path}", data.extend)
                return bytes(data)
            except Exception:
                return None

        try:
            # 1) Try sidecar image files on SD.
            for ext, mime in ((".png", "image/png"), (".jpg", "image/jpeg"), (".jpeg", "image/jpeg"), (".webp", "image/webp")):
                sidecar = f"{base_dir.rstrip('/')}/{base_name}{ext}" if base_dir != "/" else f"/{base_name}{ext}"
                content = try_retr(sidecar)
                if content:
                    p = thumb_dir / f"{key}{ext}"
                    p.write_bytes(content)
                    return content, mime

            # 2) Try extracting from 3mf archive.
            if lower.endswith(".3mf"):
                blob = try_retr(path)
                if blob:
                    with ZipFile(io.BytesIO(blob)) as zf:
                        candidates = [n for n in zf.namelist() if re.match(r"^Metadata/plate_\\d+\\.png$", n)]
                        if not candidates and "Metadata/plate_1.png" in zf.namelist():
                            candidates = ["Metadata/plate_1.png"]
                        if candidates:
                            candidates.sort()
                            image = zf.read(candidates[0])
                            p = thumb_dir / f"{key}.png"
                            p.write_bytes(image)
                            return image, "image/png"
        finally:
            try:
                ftp.quit()
            except Exception:
                pass

        return None, None

    async def get_sd_thumbnail(self, path: str) -> tuple[bytes | None, str | None]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_sd_thumbnail_sync, path)

    def _rtsp_urls_to_try(self) -> list[str]:
        if self.client is None:
            return []
        device = self.client.get_device()
        rtsp_url = device.camera.rtsp_url
        if not rtsp_url or rtsp_url == "disable":
            return []

        urls_to_try = [rtsp_url]
        try:
            parsed = urlsplit(rtsp_url)
            if parsed.hostname and not parsed.username:
                access_code = getattr(self.client, "_access_code", "")
                if access_code:
                    netloc = f"bblp:{access_code}@{parsed.hostname}"
                    if parsed.port:
                        netloc += f":{parsed.port}"
                    with_creds = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
                    urls_to_try.append(with_creds)
        except Exception:
            pass

        seen: set[str] = set()
        unique: list[str] = []
        for url in urls_to_try:
            if url not in seen:
                seen.add(url)
                unique.append(url)
        return unique

    def _capture_rtsp_snapshot_sync(self) -> tuple[bytes | None, str | None]:
        if self.client is None:
            return None, None

        now = time.time()
        if self._live_cache_bytes and (now - self._live_cache_time) < 1.5:
            return self._live_cache_bytes, self._live_cache_mime

        for url in self._rtsp_urls_to_try():
            try:
                cmd = [
                    "ffmpeg",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-rtsp_transport",
                    "tcp",
                    "-i",
                    url,
                    "-frames:v",
                    "1",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "mjpeg",
                    "pipe:1",
                ]
                proc = subprocess.run(cmd, capture_output=True, timeout=4, check=False)
                if proc.returncode == 0 and proc.stdout:
                    self._live_cache_bytes = proc.stdout
                    self._live_cache_mime = "image/jpeg"
                    self._live_cache_time = now
                    return proc.stdout, "image/jpeg"
            except Exception:
                continue

        return None, None

    def _get_live_frame_sync(self) -> tuple[bytes | None, str | None]:
        if self.client is None:
            return None, None

        try:
            image = self.client.get_device().chamber_image.get_image()
            if image:
                return bytes(image), "image/jpeg"
        except Exception:
            pass

        return self._capture_rtsp_snapshot_sync()

    async def get_live_frame(self) -> tuple[bytes | None, str | None]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_live_frame_sync)

    @staticmethod
    def _normalize_ams_color(color: Any) -> str:
        if not isinstance(color, str):
            return "#3a414b"
        hex_color = color.strip().lstrip("#").upper()
        if len(hex_color) >= 6 and all(ch in "0123456789ABCDEF" for ch in hex_color[:6]):
            rgb = hex_color[:6]
            if rgb == "000000":
                return "#2f343c"
            return f"#{rgb}"
        return "#3a414b"

    def filament_snapshot(self) -> dict[str, Any]:
        if self.client is None:
            return {"loaded_filament": None, "remaining_filament": []}
        try:
            device = self.client.get_device()
            ams = self._serialize_ams(device)
            slots = ams.get("all_slots", []) or ams.get("slots", [])
            loaded = next((slot for slot in slots if slot.get("active")), None)
            loaded_filament = None
            if loaded:
                loaded_filament = {
                    "ams_index": loaded.get("ams_index"),
                    "slot_index": loaded.get("index"),
                    "type": loaded.get("type"),
                    "color_hex": loaded.get("color_hex"),
                    "remaining_percent": loaded.get("remain_percent"),
                }
            remaining = [
                {
                    "ams_index": slot.get("ams_index"),
                    "slot_index": slot.get("index"),
                    "type": slot.get("type"),
                    "color_hex": slot.get("color_hex"),
                    "remaining_percent": slot.get("remain_percent"),
                    "active": bool(slot.get("active")),
                    "empty": bool(slot.get("empty")),
                }
                for slot in slots
            ]
            return {"loaded_filament": loaded_filament, "remaining_filament": remaining}
        except Exception:
            return {"loaded_filament": None, "remaining_filament": []}

    async def start_orderworks_print_job(self, request: OrderworksPrintJobRequest, actor: str = "dashboard") -> dict[str, Any]:
        if self.client is None:
            raise RuntimeError("Client not initialized.")

        raw_path = request.file_path.strip()
        if not raw_path:
            raise ValueError("file_path is required.")
        if raw_path.startswith("ftp://"):
            ftp_url = raw_path
            ftp_path = raw_path[6:]
        else:
            ftp_path = raw_path if raw_path.startswith("/") else f"/{raw_path}"
            ftp_url = f"ftp://{ftp_path}"

        command = copy.deepcopy(PRINT_PROJECT_FILE_TEMPLATE)
        command_print = command["print"]
        command_print["param"] = request.plate_gcode
        command_print["url"] = ftp_url
        command_print["bed_type"] = request.bed_type
        command_print["timelapse"] = request.timelapse
        command_print["bed_leveling"] = request.bed_leveling
        command_print["flow_cali"] = request.flow_cali
        command_print["vibration_cali"] = request.vibration_cali
        command_print["layer_inspect"] = request.layer_inspect
        command_print["use_ams"] = request.use_ams
        if request.ams_mapping:
            command_print["ams_mapping"] = request.ams_mapping
        if request.subtask_name:
            command_print["subtask_name"] = request.subtask_name
        else:
            command_print["subtask_name"] = Path(ftp_path).name

        ok = self.client.publish(command)
        self._mark_event("event_orderworks_print_submit")
        self._record_timeline(
            "print_submit",
            f"Submitted print job for {Path(ftp_path).name}.",
            actor=actor,
            details={
                "file_path": ftp_path,
                "subtask_name": command_print.get("subtask_name"),
                "ams_mapping": command_print.get("ams_mapping"),
            },
        )
        return {
            "ok": bool(ok),
            "submitted": bool(ok),
            "file_path": ftp_path,
            "plate_gcode": request.plate_gcode,
            "use_ams": request.use_ams,
            "ams_mapping": command_print.get("ams_mapping"),
            "subtask_name": command_print.get("subtask_name"),
        }

    async def queue_print_job(self, request: QueuePrintJobRequest, actor: str = "dashboard") -> dict[str, Any]:
        start_at = self._normalize_schedule(request.start_at)
        item = request.model_dump()
        item["id"] = uuid4().hex
        item["start_at"] = start_at
        item["created_at"] = datetime.now(timezone.utc).isoformat()
        item["actor"] = actor
        self._queue_items.append(item)
        self._save_queue()
        schedule_label = start_at or "now"
        self._record_timeline(
            "queue_add",
            f"Queued {Path(request.file_path).name} for {schedule_label}.",
            actor=actor,
            details={"queue_item_id": item["id"], "file_path": request.file_path, "start_at": start_at},
        )
        return {"ok": True, "queued": True, "item": item, "queue": self.queue_snapshot()}

    async def update_queue_item(self, item_id: str, request: QueueUpdateRequest, actor: str = "dashboard") -> dict[str, Any]:
        start_at = self._normalize_schedule(request.start_at)
        for item in self._queue_items:
            if item.get("id") != item_id:
                continue
            item["start_at"] = start_at
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
            item["updated_by"] = actor
            self._save_queue()
            self._record_timeline(
                "queue_update",
                f"Updated queue item for {Path(str(item.get('file_path') or '')).name or 'model'}.",
                actor=actor,
                details={"queue_item_id": item_id, "start_at": start_at},
            )
            return {"ok": True, "item": item, "queue": self.queue_snapshot()}
        raise ValueError(f"Unknown queue item: {item_id}")

    async def reorder_queue_item(self, item_id: str, direction: str, actor: str = "dashboard") -> dict[str, Any]:
        for index, item in enumerate(self._queue_items):
            if item.get("id") != item_id:
                continue
            if direction == "up" and index > 0:
                self._queue_items[index - 1], self._queue_items[index] = self._queue_items[index], self._queue_items[index - 1]
            elif direction == "down" and index < len(self._queue_items) - 1:
                self._queue_items[index + 1], self._queue_items[index] = self._queue_items[index], self._queue_items[index + 1]
            else:
                return {"ok": True, "queue": self.queue_snapshot()}
            self._save_queue()
            self._record_timeline(
                "queue_reorder",
                f"Moved queued job for {Path(str(item.get('file_path') or '')).name or 'model'} {direction}.",
                actor=actor,
                details={"queue_item_id": item_id, "direction": direction},
            )
            return {"ok": True, "queue": self.queue_snapshot()}
        raise ValueError(f"Unknown queue item: {item_id}")

    async def remove_queue_item(self, item_id: str, actor: str = "dashboard") -> dict[str, Any]:
        for index, item in enumerate(self._queue_items):
            if item.get("id") != item_id:
                continue
            removed = self._queue_items.pop(index)
            self._save_queue()
            self._record_timeline(
                "queue_remove",
                f"Removed queued job for {Path(str(removed.get('file_path') or '')).name or 'model'}.",
                actor=actor,
                severity="warning",
                details={"queue_item_id": item_id},
            )
            return {"ok": True, "removed": removed, "queue": self.queue_snapshot()}
        raise ValueError(f"Unknown queue item: {item_id}")

    async def save_control_preset(self, request: ControlPresetRequest, actor: str = "dashboard") -> dict[str, Any]:
        preset = request.model_dump()
        preset["id"] = uuid4().hex
        preset["created_at"] = datetime.now(timezone.utc).isoformat()
        preset["actor"] = actor
        self._control_presets.append(preset)
        self._save_presets()
        self._record_timeline("preset_save", f"Saved control preset {request.name}.", actor=actor)
        return {"ok": True, "item": preset, "items": self.presets_snapshot()}

    async def remove_control_preset(self, preset_id: str, actor: str = "dashboard") -> dict[str, Any]:
        for index, preset in enumerate(self._control_presets):
            if preset.get("id") != preset_id:
                continue
            removed = self._control_presets.pop(index)
            self._save_presets()
            self._record_timeline("preset_remove", f"Removed control preset {removed.get('name') or 'preset'}.", actor=actor, severity="warning")
            return {"ok": True, "removed": removed, "items": self.presets_snapshot()}
        raise ValueError(f"Unknown preset: {preset_id}")

    async def save_alert_rule(self, request: AlertRuleRequest, actor: str = "dashboard") -> dict[str, Any]:
        rule = request.model_dump()
        rule["id"] = uuid4().hex
        rule["created_at"] = datetime.now(timezone.utc).isoformat()
        rule["actor"] = actor
        self._alert_rules.append(rule)
        self._save_alert_rules()
        self._record_timeline("alert_rule_save", f"Saved alert rule {request.name}.", actor=actor)
        return {"ok": True, "item": rule, "items": self.alert_rules_snapshot()}

    async def update_alert_rule(self, rule_id: str, request: AlertRuleUpdateRequest, actor: str = "dashboard") -> dict[str, Any]:
        for rule in self._alert_rules:
            if rule.get("id") != rule_id:
                continue
            updates = request.model_dump(exclude_unset=True)
            for key, value in updates.items():
                rule[key] = value
            rule["updated_at"] = datetime.now(timezone.utc).isoformat()
            rule["updated_by"] = actor
            self._save_alert_rules()
            self._record_timeline(
                "alert_rule_update",
                f"Updated alert rule {rule.get('name') or 'rule'}.",
                actor=actor,
                details={"rule_id": rule_id},
            )
            return {"ok": True, "item": rule, "items": self.alert_rules_snapshot()}
        raise ValueError(f"Unknown alert rule: {rule_id}")

    async def remove_alert_rule(self, rule_id: str, actor: str = "dashboard") -> dict[str, Any]:
        for index, rule in enumerate(self._alert_rules):
            if rule.get("id") != rule_id:
                continue
            removed = self._alert_rules.pop(index)
            self._save_alert_rules()
            self._record_timeline("alert_rule_remove", f"Removed alert rule {removed.get('name') or 'rule'}.", actor=actor, severity="warning")
            return {"ok": True, "removed": removed, "items": self.alert_rules_snapshot()}
        raise ValueError(f"Unknown alert rule: {rule_id}")

    async def _queue_worker(self) -> None:
        while True:
            try:
                await asyncio.sleep(5)
                if self.client is None or not self.client.connected:
                    continue
                if self._job_busy():
                    continue
                due_item = self._queue_due_item()
                if due_item is None:
                    continue

                due_item["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
                self._save_queue()
                request = OrderworksPrintJobRequest(**{k: v for k, v in due_item.items() if k in OrderworksPrintJobRequest.model_fields})
                result = await self.start_orderworks_print_job(request, actor=f"queue:{due_item.get('actor') or 'system'}")
                if result.get("submitted"):
                    self._queue_items = [item for item in self._queue_items if item.get("id") != due_item.get("id")]
                    self._save_queue()
                    self._record_timeline(
                        "queue_submit",
                        f"Queued job started for {Path(request.file_path).name}.",
                        actor="scheduler",
                        details={"queue_item_id": due_item.get("id"), "file_path": request.file_path},
                    )
                else:
                    self._record_timeline(
                        "queue_submit_failed",
                        f"Queued job failed to submit for {Path(request.file_path).name}.",
                        actor="scheduler",
                        severity="error",
                        details={"queue_item_id": due_item.get("id"), "file_path": request.file_path},
                    )
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self.last_error = str(exc)
                self._record_timeline("queue_worker_error", f"Queue worker error: {exc}", severity="error", actor="system")

    def _serialize_ams(self, device: Any) -> dict[str, Any]:
        ams = getattr(device, "ams", None)
        ams_data = getattr(ams, "data", None)
        if not isinstance(ams_data, dict) or not ams_data:
            return {
                "present": False,
                "total_ams_count": 0,
                "ams_index": None,
                "active_ams_index": None,
                "active_tray_index": None,
                "humidity_pct": None,
                "temperature_c": None,
                "all_slots": [],
                "ams_units": [],
                "slots": [],
            }

        active_ams_index = getattr(ams, "active_ams_index", None)
        active_tray_index = getattr(ams, "active_tray_index", None)
        def _sort_key(value: Any) -> tuple[int, Any]:
            try:
                return (0, int(value))
            except Exception:
                return (1, str(value))

        all_slots: list[dict[str, Any]] = []
        ams_units: list[dict[str, Any]] = []
        for ams_index in sorted(ams_data.keys(), key=_sort_key):
            unit = ams_data[ams_index]
            trays = list(getattr(unit, "tray", []) or [])
            slot_count = max(4, len(trays))
            unit_slots: list[dict[str, Any]] = []
            for tray_idx in range(slot_count):
                tray = trays[tray_idx] if tray_idx < len(trays) else None
                is_empty = bool(getattr(tray, "empty", True)) if tray is not None else True
                tray_type = (getattr(tray, "type", "") or "").strip() if tray is not None else ""
                slot = {
                    "ams_index": ams_index,
                    "index": tray_idx,
                    "active": (
                        bool(getattr(tray, "active", False))
                        if tray is not None
                        else (ams_index == active_ams_index and tray_idx == active_tray_index)
                    ),
                    "empty": is_empty,
                    "type": tray_type if tray_type else ("Empty" if is_empty else "-"),
                    "name": (getattr(tray, "name", "") or "").strip() if tray is not None else "",
                    "color_hex": self._normalize_ams_color(getattr(tray, "color", None)) if tray is not None else "#2f343c",
                    "remain_percent": getattr(tray, "remain", None) if tray is not None else None,
                }
                unit_slots.append(slot)
                all_slots.append(slot)

            humidity = getattr(unit, "humidity", None)
            temperature = getattr(unit, "temperature", None)
            ams_units.append(
                {
                    "ams_index": ams_index,
                    "humidity_pct": humidity if isinstance(humidity, (int, float)) and humidity >= 0 else None,
                    "temperature_c": temperature if isinstance(temperature, (int, float)) and temperature >= 0 else None,
                    "slots": unit_slots,
                }
            )

        selected = next((item for item in ams_units if item.get("ams_index") == active_ams_index), ams_units[0])
        return {
            "present": True,
            "total_ams_count": len(ams_units),
            "ams_index": selected.get("ams_index"),
            "active_ams_index": active_ams_index,
            "active_tray_index": active_tray_index,
            "humidity_pct": selected.get("humidity_pct"),
            "temperature_c": selected.get("temperature_c"),
            "all_slots": all_slots,
            "ams_units": ams_units,
            "slots": selected.get("slots", []),
        }

    async def state(self) -> dict[str, Any]:
        async with self._lock:
            queue = self.queue_snapshot()
            self._ensure_default_alert_rules()
            base = {
                "configured": self.configured,
                "connected": bool(self.client and self.client.connected),
                "last_event": self.last_event,
                "last_update_utc": self.last_update_utc,
                "last_error": self.last_error,
                "queue": queue,
                "timeline": self.timeline_snapshot()[:8],
                "control_presets": self.presets_snapshot(),
                "alert_rules": self.alert_rules_snapshot(),
                "active_alerts": [],
            }

            if self.client is None:
                return base

            try:
                device = self.client.get_device()
                info = device.info
                job = device.print_job
                temp = device.temperature
                alerts = self._evaluate_alert_rules(
                    connected=base["connected"],
                    chamber_temp=temp.chamber_temp,
                    print_error=device.print_error.error,
                    queue_count=queue["count"],
                )
                return {
                    **base,
                    "printer": {
                        "serial": info.serial,
                        "device_type": info.device_type,
                        "online": info.online,
                        "ip_address": info.ip_address,
                        "sw_ver": info.sw_ver,
                        "hw_ver": info.hw_ver,
                        "wifi_signal": info.wifi_signal,
                    },
                    "job": {
                        "state": job.gcode_state,
                        "progress_percent": job.print_percentage,
                        "file": job.gcode_file,
                        "subtask_name": job.subtask_name,
                        "print_type": job.print_type,
                        "current_layer": job.current_layer,
                        "total_layers": job.total_layers,
                        "remaining_minutes": job.remaining_time,
                    },
                    "temperatures": {
                        "bed_current": temp.bed_temp,
                        "bed_target": temp.target_bed_temp,
                        "chamber": temp.chamber_temp,
                        "nozzle_current": temp.active_nozzle_temperature,
                        "nozzle_target": temp.active_nozzle_target_temperature,
                    },
                    "lights": {
                        "chamber": device.lights.chamber_light,
                        "heatbed": device.lights.heatbed_light,
                    },
                    "errors": {
                        "print_error": device.print_error.error,
                        "hms": device.hms.errors,
                    },
                    "ams": self._serialize_ams(device),
                    "active_alerts": alerts,
                    "health": {
                        "score": max(
                            0,
                            min(
                                100,
                                100
                                - (0 if base["connected"] else 45)
                                - (25 if device.print_error.error else 0)
                                - min(queue["count"], 5) * 4
                                - (12 if self.last_error else 0),
                            ),
                        ),
                        "queue_backlog": queue["count"],
                    },
                }
            except Exception as exc:
                self.last_error = str(exc)
                return base


class MultiPrinterManager:
    def __init__(self, definitions: list[dict[str, Any]]) -> None:
        self._services: dict[str, PrinterService] = {}
        self._default_id: str | None = None
        self._names_file = Path("/data/printer_names.json")
        self._added_printers_file = Path("/data/printers_added.json")
        self._added_printers = self._load_added_printers()
        self._name_overrides = self._load_name_overrides()
        for entry in definitions:
            self._register_service(entry)
        for entry in self._added_printers.values():
            self._register_service(entry, allow_existing=True)

        if self._default_id is None:
            raise RuntimeError("No printers configured.")

    @property
    def default_id(self) -> str:
        assert self._default_id is not None
        return self._default_id

    def get(self, printer_id: str | None = None) -> PrinterService:
        resolved = printer_id or self.default_id
        service = self._services.get(resolved)
        if service is None:
            raise KeyError(f"Unknown printer: {resolved}")
        return service

    def list_items(self) -> list[dict[str, Any]]:
        return [
            {
                "id": service.printer_id,
                "name": service.display_name,
            }
            for service in self._services.values()
        ]

    def _load_name_overrides(self) -> dict[str, str]:
        try:
            if self._names_file.exists():
                data = json.loads(self._names_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
        except Exception as exc:
            LOGGER.warning("Failed to load printer names file: %s", exc)
        return {}

    def _save_name_overrides(self) -> None:
        try:
            self._names_file.parent.mkdir(parents=True, exist_ok=True)
            self._names_file.write_text(json.dumps(self._name_overrides, indent=2), encoding="utf-8")
        except Exception as exc:
            LOGGER.warning("Failed to save printer names file: %s", exc)

    def _load_added_printers(self) -> dict[str, dict[str, Any]]:
        try:
            if self._added_printers_file.exists():
                data = json.loads(self._added_printers_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    items: dict[str, dict[str, Any]] = {}
                    for raw in data:
                        if not isinstance(raw, dict):
                            continue
                        printer_id = str(raw.get("id", "")).strip()
                        name = str(raw.get("name", "")).strip()
                        config = raw.get("config")
                        if not printer_id or not name or not isinstance(config, dict):
                            continue
                        items[printer_id] = {"id": printer_id, "name": name, "config": dict(config)}
                    return items
        except Exception as exc:
            LOGGER.warning("Failed to load added printers file: %s", exc)
        return {}

    def _save_added_printers(self) -> None:
        try:
            self._added_printers_file.parent.mkdir(parents=True, exist_ok=True)
            self._added_printers_file.write_text(json.dumps(list(self._added_printers.values()), indent=2), encoding="utf-8")
        except Exception as exc:
            LOGGER.warning("Failed to save added printers file: %s", exc)

    def _register_service(self, entry: dict[str, Any], allow_existing: bool = False) -> None:
        printer_id = str(entry.get("id", "")).strip()
        if not printer_id:
            return
        if printer_id in self._services:
            if allow_existing:
                return
            raise ValueError(f"Printer id already exists: {printer_id}")

        config = dict(entry.get("config") or {})
        name = str(entry.get("name") or printer_id)
        self._services[printer_id] = PrinterService(config=config, printer_id=printer_id, display_name=name)
        saved_name = self._name_overrides.get(printer_id, "").strip()
        if saved_name:
            self._services[printer_id].display_name = saved_name
        if self._default_id is None:
            self._default_id = printer_id

    def rename(self, printer_id: str, new_name: str) -> dict[str, str]:
        service = self.get(printer_id)
        clean = new_name.strip()
        if not clean:
            raise ValueError("Printer name cannot be empty.")
        service.display_name = clean
        self._name_overrides[printer_id] = clean
        self._save_name_overrides()
        return {"id": service.printer_id, "name": service.display_name}

    async def add(self, request: AddPrinterRequest) -> dict[str, str]:
        requested_id = (request.id or "").strip()
        if not requested_id:
            base = re.sub(r"[^a-z0-9]+", "-", request.name.strip().lower()).strip("-") or "printer"
            requested_id = base
            suffix = 2
            while requested_id in self._services:
                requested_id = f"{base}-{suffix}"
                suffix += 1

        if requested_id in self._services:
            raise ValueError(f"Printer id already exists: {requested_id}")

        default_cfg = build_default_printer_config()
        config = {
            **default_cfg,
            "name": request.name.strip(),
            "host": request.host.strip(),
            "serial": request.serial.strip(),
            "access_code": request.access_code.strip(),
            "device_type": request.device_type.strip() or "unknown",
            "local_mqtt": request.local_mqtt,
            "enable_camera": request.enable_camera,
            "disable_ssl_verify": request.disable_ssl_verify,
        }
        entry = {"id": requested_id, "name": request.name.strip(), "config": config}
        self._register_service(entry)
        self._added_printers[requested_id] = entry
        self._save_added_printers()

        service = self.get(requested_id)
        await service.start()
        return {"id": service.printer_id, "name": service.display_name}

    async def start(self) -> None:
        for service in self._services.values():
            await service.start()

    async def stop(self) -> None:
        for service in self._services.values():
            await service.stop()


app = FastAPI(title="PrintLab", version="0.1.0")
printer_manager = MultiPrinterManager(load_printer_definitions())
works_service = WorksService()
dashboard_html_template = (Path(__file__).with_name("dashboard.html")).read_text(encoding="utf-8")
static_dir = Path(__file__).with_name("static")
app.mount("/data", StaticFiles(directory="/data"), name="data")
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def _parse_basic_auth(authorization: str | None) -> tuple[str, str] | None:
    if not authorization:
        return None
    if not authorization.lower().startswith("basic "):
        return None
    token = authorization[6:].strip()
    if not token:
        return None
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    if ":" not in decoded:
        return None
    username, password = decoded.split(":", 1)
    return username, password


def _actor_from_request(request: Request) -> str:
    credentials = _parse_basic_auth(request.headers.get("authorization"))
    if credentials is not None:
        username, _password = credentials
        if username.strip():
            return username.strip()
    return "dashboard"


@app.middleware("http")
async def admin_auth_middleware(request: Request, call_next):
    if not ADMIN_PASSWORD:
        return await call_next(request)

    credentials = _parse_basic_auth(request.headers.get("authorization"))
    if credentials is not None:
        username, password = credentials
        if hmac.compare_digest(username, ADMIN_USERNAME) and hmac.compare_digest(password, ADMIN_PASSWORD):
            return await call_next(request)

    return Response(
        content="Unauthorized",
        status_code=401,
        headers={
            "WWW-Authenticate": 'Basic realm="PrintLab Admin"',
            "Cache-Control": "no-store",
        },
    )


def _service_or_404(printer_id: str | None = None) -> PrinterService:
    try:
        return printer_manager.get(printer_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _render_gallery_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#cfe2f7">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="PrintLab">
  <link rel="icon" type="image/png" href="/static/icons/icon-192.png">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
  <title>PrintLab - Printers</title>
  <style>
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif; background:#e6f0fb; color:#213245; }
    .wrap { max-width:1100px; margin:26px auto; padding:0 16px 40px; }
    h1 { margin:0 0 6px; font-size:28px; }
    .top-row { display:flex; align-items:flex-start; justify-content:space-between; margin-bottom:14px; gap:10px; }
    .title-block { display:flex; flex-direction:column; align-items:flex-start; gap:8px; }
    .helper { color:#5d738a; font-size:13px; }
    .top-actions { display:flex; align-items:center; gap:8px; }
    .install-btn {
      border: 1px solid rgba(255,255,255,.74);
      background: rgba(255,255,255,.62);
      color: #2a4f73;
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
    }
    .install-btn[hidden] { display:none !important; }
    .status { min-height:20px; margin:0 0 14px; font-size:13px; color:#3a5977; }
    .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:16px; }
    .card { position:relative; background:rgba(255,255,255,.66); border:1px solid rgba(255,255,255,.75); border-radius:16px; padding:14px; box-shadow:0 10px 30px rgba(42,90,138,.16); backdrop-filter:blur(12px); }
    .card-link { text-decoration:none; color:inherit; display:block; }
    .card:hover { transform:translateY(-2px); transition:all .14s ease; }
    .name-row { margin-top:8px; display:flex; align-items:center; gap:8px; }
    .name { margin:0; font-size:17px; font-weight:700; }
    .meta { margin-top:6px; font-size:13px; color:#5d738a; }
    .badge { display:inline-block; margin-top:8px; padding:4px 8px; border-radius:999px; font-size:12px; border:1px solid rgba(128,165,198,.3); }
    .ok { background:#e5f7ee; color:#2f8b56; }
    .bad { background:#fdeceb; color:#a0413b; }
    .printer-art { width:100%; height:150px; object-fit:contain; background:rgba(255,255,255,.72); border-radius:12px; display:block; }
    .card-actions { position:absolute; top:12px; right:12px; }
    .menu-btn {
      border:1px solid rgba(193,214,236,.9); background:rgba(255,255,255,.92); color:#2f4f6d; cursor:pointer;
      width:34px; height:34px; border-radius:999px; font-size:18px; line-height:1; box-shadow:0 6px 16px rgba(36,69,99,.12);
    }
    .card-menu {
      position:absolute; top:42px; right:0; min-width:132px; display:none; background:#fff;
      border:1px solid #d4e1ef; border-radius:12px; padding:6px; box-shadow:0 16px 34px rgba(22,54,86,.18);
    }
    .card-menu.open { display:block; }
    .menu-item {
      width:100%; border:0; background:transparent; color:#2a4b68; text-align:left; cursor:pointer;
      border-radius:8px; padding:8px 10px; font-size:13px; font-weight:600;
    }
    .menu-item:hover { background:#eef5fc; }
    .dialog-backdrop {
      position:fixed; inset:0; background:rgba(18,34,52,.36); display:none; align-items:center; justify-content:center; z-index:60; padding:16px;
    }
    .dialog-backdrop.open { display:flex; }
    .dialog {
      width:min(420px, 100%); background:#fff; border:1px solid #d4e1ef; border-radius:16px; padding:16px;
      box-shadow:0 24px 46px rgba(22,54,86,.24);
    }
    .dialog h3 { margin:0 0 10px; font-size:19px; }
    .dialog p { margin:0 0 12px; color:#58718b; font-size:13px; }
    .hamburger {
      border:0; border-radius:10px; background:#1f4f7b; color:#fff; cursor:pointer;
      width:42px; height:34px; display:grid; place-items:center; box-shadow:0 8px 22px rgba(22,54,86,.34);
    }
    .hamburger-lines { width:16px; height:12px; position:relative; }
    .hamburger-lines::before, .hamburger-lines::after, .hamburger-lines span {
      content:""; position:absolute; left:0; right:0; height:2px; background:#fff; border-radius:2px;
    }
    .hamburger-lines::before { top:0; }
    .hamburger-lines span { top:5px; }
    .hamburger-lines::after { top:10px; }
    .hamburger-label { font-size:11px; color:#1f4f7b; margin-left:6px; }
    .hamburger-row { display:flex; align-items:center; }
    .hamburger-wrap { display:flex; align-items:center; }
    .hamburger:hover { filter:brightness(1.05); }
    .sidebar-close {
      border:0; background:transparent; color:#365877; cursor:pointer; font-size:20px; line-height:1; padding:2px 4px;
    }
    .sidebar {
      position:fixed; z-index:35; top:0; left:0; height:100vh; width:320px; max-width:85vw;
      background:linear-gradient(180deg, #f4f8fc 0%, #eaf2fb 100%);
      border-right:1px solid #cfe0f3; box-shadow:18px 0 30px rgba(21,50,80,.18);
      transform:translateX(-101%); transition:transform .18s ease; padding:18px 14px 16px; overflow:auto;
    }
    .sidebar.open { transform:translateX(0); }
    .sidebar-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
    .sidebar h2 { margin:0; font-size:20px; }
    .sidebar-tabs { display:flex; gap:8px; margin:0 0 12px; }
    .sidebar-tab {
      border:1px solid #bdd2e8; background:#edf4fb; color:#375a79; border-radius:999px; padding:6px 10px; cursor:pointer; font-size:12px;
    }
    .sidebar-tab.active { background:#1f4f7b; border-color:#1f4f7b; color:#fff; }
    .tab-panel { display:none; }
    .tab-panel.active { display:block; }
    .field { margin-bottom:9px; }
    .field label { display:block; font-size:12px; color:#496986; margin-bottom:3px; }
    .field input { width:100%; box-sizing:border-box; border:1px solid #c4d9ee; border-radius:10px; padding:8px 9px; font-size:14px; background:#fff; }
    .check { display:flex; align-items:center; gap:8px; margin:7px 0; font-size:13px; color:#2f4f6d; }
    .actions { display:flex; gap:8px; margin-top:12px; }
    .btn { border:0; border-radius:10px; padding:9px 12px; cursor:pointer; font-weight:600; }
    .btn-primary { background:#1f4f7b; color:#fff; }
    .btn-light { background:#dbe9f7; color:#244563; }
    .sidebar-note { color:#5f7892; font-size:12px; margin-top:8px; }
    @media (max-width: 760px) {
      .sidebar { width:100%; max-width:100%; }
      .top-row { flex-direction:column; align-items:flex-start; }
    }
  </style>
</head>
<body>
  <aside id="sidebar" class="sidebar">
    <div class="sidebar-head">
      <h2>Printer Tools</h2>
      <button id="closeSidebar" class="sidebar-close" type="button" aria-label="Close sidebar">x</button>
    </div>
    <div class="sidebar-tabs">
      <button class="sidebar-tab active" type="button" data-tab="add-printer">Add Printer</button>
    </div>
    <div class="tab-panel active" data-panel="add-printer">
      <form id="addPrinterForm">
      <div class="field">
        <label for="printerName">Name</label>
        <input id="printerName" name="name" required maxlength="64" placeholder="X1C-002">
      </div>
      <div class="field">
        <label for="printerId">ID (optional)</label>
        <input id="printerId" name="id" maxlength="64" pattern="[A-Za-z0-9_-]+" placeholder="x1c-002">
      </div>
      <div class="field">
        <label for="printerHost">Host / IP</label>
        <input id="printerHost" name="host" required maxlength="255" placeholder="192.168.1.67">
      </div>
      <div class="field">
        <label for="printerSerial">Serial</label>
        <input id="printerSerial" name="serial" required maxlength="128">
      </div>
      <div class="field">
        <label for="printerAccessCode">Access Code</label>
        <input id="printerAccessCode" name="access_code" required maxlength="128">
      </div>
      <div class="field">
        <label for="deviceType">Device Type</label>
        <input id="deviceType" name="device_type" maxlength="64" value="unknown">
      </div>
      <label class="check"><input type="checkbox" name="local_mqtt" checked> Local MQTT</label>
      <label class="check"><input type="checkbox" name="enable_camera" checked> Enable camera</label>
      <label class="check"><input type="checkbox" name="disable_ssl_verify"> Disable SSL verify</label>
      <div class="actions">
        <button class="btn btn-primary" type="submit">Save</button>
        <button class="btn btn-light" type="button" id="collapseSidebar">Collapse</button>
      </div>
      <div class="sidebar-note">Saved printers persist in <code>/data/printers_added.json</code>.</div>
      </form>
    </div>
  </aside>
  <div class="wrap">
    <div class="top-row">
      <div class="title-block">
        <h1>Printers</h1>
        <div class="hamburger-row">
          <button id="sidebarToggle" class="hamburger" type="button" aria-label="Open sidebar">
            <span class="hamburger-lines"><span></span></span>
          </button>
          <span class="hamburger-label">Menu</span>
        </div>
      </div>
      <div class="top-actions">
        <button id="installBtn" class="install-btn" type="button" hidden>Install App</button>
        <div class="helper">Use the sidebar to add printers without editing .env</div>
      </div>
    </div>
    <div id="status" class="status"></div>
    <div id="cards" class="grid"></div>
  </div>
  <div id="renameDialog" class="dialog-backdrop" aria-hidden="true">
    <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="renameTitle">
      <h3 id="renameTitle">Rename Printer</h3>
      <p>Update the label shown on the printer gallery and dashboard.</p>
      <div class="field">
        <label for="renameInput">Printer Name</label>
        <input id="renameInput" maxlength="64" autocomplete="off">
      </div>
      <div class="actions">
        <button class="btn btn-primary" type="button" id="renameSaveBtn">Save</button>
        <button class="btn btn-light" type="button" id="renameCancelBtn">Cancel</button>
      </div>
    </div>
  </div>
  <script>
    const sidebar = document.getElementById('sidebar');
    const sidebarToggle = document.getElementById('sidebarToggle');
    const closeSidebar = document.getElementById('closeSidebar');
    const collapseSidebar = document.getElementById('collapseSidebar');
    const addPrinterForm = document.getElementById('addPrinterForm');
    const renameDialog = document.getElementById('renameDialog');
    const renameInput = document.getElementById('renameInput');
    const renameSaveBtn = document.getElementById('renameSaveBtn');
    const renameCancelBtn = document.getElementById('renameCancelBtn');
    const tabs = Array.from(document.querySelectorAll('.sidebar-tab'));
    const panels = Array.from(document.querySelectorAll('.tab-panel'));
    const statusEl = document.getElementById('status');
    let deferredInstallPrompt = null;
    let renameTarget = null;

    function setStatus(message, isError = false) {
      statusEl.textContent = message || '';
      statusEl.style.color = isError ? '#a0413b' : '#3a5977';
    }

    function closeSidebarPanel() {
      sidebar.classList.remove('open');
    }

    function openRenameDialog(printerId, currentName) {
      renameTarget = printerId;
      renameInput.value = currentName || '';
      renameDialog.classList.add('open');
      renameDialog.setAttribute('aria-hidden', 'false');
      window.setTimeout(() => renameInput.focus(), 0);
    }

    function closeRenameDialog() {
      renameDialog.classList.remove('open');
      renameDialog.setAttribute('aria-hidden', 'true');
      renameTarget = null;
    }

    sidebarToggle.addEventListener('click', () => {
      if (sidebar.classList.contains('open')) closeSidebarPanel();
      else sidebar.classList.add('open');
    });
    closeSidebar.addEventListener('click', closeSidebarPanel);
    collapseSidebar.addEventListener('click', closeSidebarPanel);
    renameCancelBtn.addEventListener('click', closeRenameDialog);
    renameDialog.addEventListener('click', (event) => {
      if (event.target === renameDialog) closeRenameDialog();
    });
    renameSaveBtn.addEventListener('click', async () => {
      if (!renameTarget) return;
      const next = renameInput.value.trim();
      if (!next) return;
      const res = await fetch(`/api/printers/${encodeURIComponent(renameTarget)}/name`, {
        method: 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify({name: next})
      });
      if (res.ok) {
        setStatus(`Renamed printer: ${next}`);
        closeRenameDialog();
        loadPrinters();
      } else {
        const txt = await res.text();
        setStatus(`Rename failed: ${txt}`, true);
      }
    });
    document.addEventListener('click', (event) => {
      if (!(event.target instanceof Element)) return;
      if (event.target.closest('.card-actions')) return;
      document.querySelectorAll('.card-menu.open').forEach((menu) => menu.classList.remove('open'));
    });

    tabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        const tabId = tab.getAttribute('data-tab');
        tabs.forEach((t) => t.classList.toggle('active', t === tab));
        panels.forEach((panel) => {
          panel.classList.toggle('active', panel.getAttribute('data-panel') === tabId);
        });
      });
    });

    async function initPwa() {
      if (!("serviceWorker" in navigator)) return;
      try {
        await navigator.serviceWorker.register("/sw.js");
      } catch (_e) {}
      setupInstallPrompt();
    }

    function setupInstallPrompt() {
      const installBtn = document.getElementById("installBtn");
      if (!installBtn) return;

      window.addEventListener("beforeinstallprompt", (event) => {
        event.preventDefault();
        deferredInstallPrompt = event;
        installBtn.hidden = false;
        installBtn.textContent = "Install App";
      });

      installBtn.addEventListener("click", async () => {
        if (deferredInstallPrompt) {
          deferredInstallPrompt.prompt();
          await deferredInstallPrompt.userChoice.catch(() => null);
          deferredInstallPrompt = null;
          installBtn.hidden = true;
          return;
        }
        if (isIosStandaloneCandidate()) {
          installBtn.textContent = "Use Share > Add to Home Screen";
          installBtn.hidden = false;
        }
      });

      if (isIosStandaloneCandidate()) {
        installBtn.hidden = false;
        installBtn.textContent = "Add to Home Screen";
      }

      window.addEventListener("appinstalled", () => {
        installBtn.hidden = true;
        deferredInstallPrompt = null;
      });
    }

    function isIosStandaloneCandidate() {
      const ua = window.navigator.userAgent.toLowerCase();
      const isIos = /iphone|ipad|ipod/.test(ua);
      const inStandalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
      return isIos && !inStandalone;
    }

    addPrinterForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const fd = new FormData(addPrinterForm);
      const payload = {
        name: String(fd.get('name') || '').trim(),
        host: String(fd.get('host') || '').trim(),
        serial: String(fd.get('serial') || '').trim(),
        access_code: String(fd.get('access_code') || '').trim(),
        device_type: String(fd.get('device_type') || '').trim() || 'unknown',
        local_mqtt: Boolean(fd.get('local_mqtt')),
        enable_camera: Boolean(fd.get('enable_camera')),
        disable_ssl_verify: Boolean(fd.get('disable_ssl_verify'))
      };
      const idValue = String(fd.get('id') || '').trim();
      if (idValue) payload.id = idValue;

      try {
        const res = await fetch('/api/printers', {
          method: 'POST',
          headers: {'content-type': 'application/json'},
          body: JSON.stringify(payload)
        });
        if (!res.ok) {
          const errorBody = await res.json().catch(() => ({}));
          throw new Error(errorBody.detail || `HTTP ${res.status}`);
        }
        setStatus(`Added printer: ${payload.name}`);
        addPrinterForm.reset();
        document.getElementById('deviceType').value = 'unknown';
        document.querySelector('input[name="local_mqtt"]').checked = true;
        document.querySelector('input[name="enable_camera"]').checked = true;
        closeSidebarPanel();
        loadPrinters();
      } catch (err) {
        setStatus(`Add printer failed: ${String(err)}`, true);
      }
    });

    function printerSvg() {
      return '<img class="printer-art" src="/static/printers/x1c.jpg" alt="Bambu Lab X1 Carbon">';
    }

    async function loadPrinters() {
      const cards = document.getElementById('cards');
      try {
        const r = await fetch('/api/printers');
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const s = await r.json();
        const items = s.items || [];
        if (!items.length) {
          cards.innerHTML = '<div class="card"><div class="name">No printers configured</div><div class="meta">Use Add Printer to create one.</div></div>';
          return;
        }
        cards.innerHTML = items.map(p => {
          const ok = p.connected ? 'ok' : 'bad';
          const label = p.connected ? 'Connected' : 'Disconnected';
          return `<article class="card">
            <div class="card-actions">
              <button type="button" class="menu-btn" data-menu-id="${p.id}" aria-label="Open printer actions">...</button>
              <div class="card-menu" data-menu-panel="${p.id}">
                <button type="button" class="menu-item menu-open" data-id="${p.id}">Open</button>
                <button type="button" class="menu-item menu-rename" data-id="${p.id}" data-name="${(p.name || p.id).replace(/"/g, '&quot;')}">Rename</button>
              </div>
            </div>
            <a class="card-link" href="/printer/${encodeURIComponent(p.id)}">
              ${printerSvg()}
              <div class="name-row">
                <div class="name">${p.name || p.id}</div>
              </div>
              <div class="meta">Serial: ${p.serial || '-'}</div>
              <span class="badge ${ok}">${label}</span>
            </a>
          </article>`;
        }).join('');

        document.querySelectorAll('.menu-btn').forEach((btn) => {
          btn.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            const targetId = btn.getAttribute('data-menu-id');
            document.querySelectorAll('.card-menu.open').forEach((menu) => {
              if (menu.getAttribute('data-menu-panel') !== targetId) menu.classList.remove('open');
            });
            const panel = document.querySelector(`.card-menu[data-menu-panel="${targetId}"]`);
            if (panel) panel.classList.toggle('open');
          });
        });

        document.querySelectorAll('.menu-open').forEach((btn) => {
          btn.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            const id = btn.getAttribute('data-id');
            if (id) window.location.href = `/printer/${encodeURIComponent(id)}`;
          });
        });

        document.querySelectorAll('.menu-rename').forEach((btn) => {
          btn.addEventListener('click', async (event) => {
            event.preventDefault();
            event.stopPropagation();
            const id = btn.getAttribute('data-id');
            const current = btn.getAttribute('data-name') || '';
            document.querySelectorAll('.card-menu.open').forEach((menu) => menu.classList.remove('open'));
            openRenameDialog(id, current);
          });
        });
      } catch (err) {
        cards.innerHTML = `<div class="card"><div class="name">Failed to load printers</div><div class="meta">${String(err)}</div></div>`;
      }
    }

    initPwa();
    loadPrinters();
  </script>
</body>
</html>"""

def _render_printer_dashboard(printer_id: str) -> str:
    service = _service_or_404(printer_id)
    injected = (
        "<script>"
        f"window.PRINTER_ID={json.dumps(printer_id)};"
        f"window.PRINTER_NAME={json.dumps(service.display_name)};"
        "</script>"
    )
    return dashboard_html_template.replace("<script>", f"{injected}<script>", 1)


@app.on_event("startup")
async def startup() -> None:
    await printer_manager.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await printer_manager.stop()


@app.get("/", response_class=HTMLResponse)
async def dashboard_root() -> str:
    return _render_gallery_html()


@app.get("/printer/{printer_id}", response_class=HTMLResponse)
async def printer_dashboard(printer_id: str) -> str:
    return _render_printer_dashboard(printer_id)


@app.get("/manifest.webmanifest")
async def manifest() -> FileResponse:
    return FileResponse(
        static_dir / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


@app.get("/sw.js")
async def service_worker() -> FileResponse:
    return FileResponse(
        static_dir / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/favicon.ico")
async def favicon() -> FileResponse:
    return FileResponse(static_dir / "icons" / "icon-192.png", media_type="image/png")


@app.get("/health")
async def health() -> dict[str, Any]:
    state = await _service_or_404().state()
    return {
        "ok": state["configured"],
        "configured": state["configured"],
        "connected": state["connected"],
        "last_error": state["last_error"],
    }


@app.get("/api/printers")
async def list_printers() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for entry in printer_manager.list_items():
        svc = _service_or_404(entry["id"])
        state = await svc.state()
        items.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "connected": state.get("connected"),
                "configured": state.get("configured"),
                "serial": (state.get("printer") or {}).get("serial"),
                "device_type": (state.get("printer") or {}).get("device_type"),
                "last_error": state.get("last_error"),
            }
        )
    return {"default_id": printer_manager.default_id, "items": items}


@app.post("/api/printers")
async def add_printer(request: AddPrinterRequest) -> dict[str, Any]:
    try:
        printer = await printer_manager.add(request)
        return {"ok": True, "printer": printer}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/printers/{printer_id}/name")
async def rename_printer(printer_id: str, request: PrinterNameRequest) -> dict[str, Any]:
    try:
        printer = printer_manager.rename(printer_id, request.name)
        return {"ok": True, "printer": printer}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/state")
async def get_state() -> dict[str, Any]:
    return await _service_or_404().state()


@app.get("/api/printers/{printer_id}/state")
async def get_state_by_printer(printer_id: str) -> dict[str, Any]:
    return await _service_or_404(printer_id).state()


@app.get("/api/works/services")
async def works_services() -> dict[str, Any]:
    return {"items": works_service.list_services()}


@app.get("/api/works/{service_name}/health")
async def works_health(service_name: str, path: str = "/health", printer_id: str | None = None) -> dict[str, Any]:
    try:
        result = await works_service.health(service_name, path=path)
        if service_name.lower() == "stockworks":
            result["printer_filament"] = _service_or_404(printer_id).filament_snapshot()
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/works/{service_name}/request")
async def works_request(service_name: str, request: WorksRequest, printer_id: str | None = None) -> dict[str, Any]:
    try:
        result = await works_service.request(service_name, request)
        if service_name.lower() == "stockworks":
            result["printer_filament"] = _service_or_404(printer_id).filament_snapshot()
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/works/orderworks/print-job")
async def orderworks_print_job(request: Request, payload: OrderworksPrintJobRequest, printer_id: str | None = None) -> dict[str, Any]:
    try:
        return await _service_or_404(printer_id).start_orderworks_print_job(payload, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/queue")
async def queue_snapshot() -> dict[str, Any]:
    return _service_or_404().queue_snapshot()


@app.get("/api/printers/{printer_id}/queue")
async def queue_snapshot_by_printer(printer_id: str) -> dict[str, Any]:
    return _service_or_404(printer_id).queue_snapshot()


@app.post("/api/queue")
async def queue_print_job(request: Request, payload: QueuePrintJobRequest) -> dict[str, Any]:
    try:
        return await _service_or_404().queue_print_job(payload, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/printers/{printer_id}/queue")
async def queue_print_job_by_printer(printer_id: str, request: Request, payload: QueuePrintJobRequest) -> dict[str, Any]:
    try:
        return await _service_or_404(printer_id).queue_print_job(payload, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/queue/{item_id}")
async def update_queue(item_id: str, request: Request, payload: QueueUpdateRequest) -> dict[str, Any]:
    try:
        return await _service_or_404().update_queue_item(item_id, payload, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/queue/{item_id}/reorder")
async def reorder_queue(item_id: str, request: Request, payload: QueueReorderRequest) -> dict[str, Any]:
    try:
        return await _service_or_404().reorder_queue_item(item_id, payload.direction, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/printers/{printer_id}/queue/{item_id}")
async def update_queue_by_printer(printer_id: str, item_id: str, request: Request, payload: QueueUpdateRequest) -> dict[str, Any]:
    try:
        return await _service_or_404(printer_id).update_queue_item(item_id, payload, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/printers/{printer_id}/queue/{item_id}/reorder")
async def reorder_queue_by_printer(printer_id: str, item_id: str, request: Request, payload: QueueReorderRequest) -> dict[str, Any]:
    try:
        return await _service_or_404(printer_id).reorder_queue_item(item_id, payload.direction, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/queue/{item_id}")
async def remove_queue(item_id: str, request: Request) -> dict[str, Any]:
    try:
        return await _service_or_404().remove_queue_item(item_id, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/printers/{printer_id}/queue/{item_id}")
async def remove_queue_by_printer(printer_id: str, item_id: str, request: Request) -> dict[str, Any]:
    try:
        return await _service_or_404(printer_id).remove_queue_item(item_id, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/timeline")
async def timeline_snapshot() -> dict[str, Any]:
    return {"items": _service_or_404().timeline_snapshot()}


@app.get("/api/printers/{printer_id}/timeline")
async def timeline_snapshot_by_printer(printer_id: str) -> dict[str, Any]:
    return {"items": _service_or_404(printer_id).timeline_snapshot()}


@app.get("/api/control-presets")
async def control_presets() -> dict[str, Any]:
    return {"items": _service_or_404().presets_snapshot()}


@app.get("/api/printers/{printer_id}/control-presets")
async def control_presets_by_printer(printer_id: str) -> dict[str, Any]:
    return {"items": _service_or_404(printer_id).presets_snapshot()}


@app.post("/api/control-presets")
async def save_control_preset(request: Request, payload: ControlPresetRequest) -> dict[str, Any]:
    try:
        return await _service_or_404().save_control_preset(payload, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/printers/{printer_id}/control-presets")
async def save_control_preset_by_printer(printer_id: str, request: Request, payload: ControlPresetRequest) -> dict[str, Any]:
    try:
        return await _service_or_404(printer_id).save_control_preset(payload, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/control-presets/{preset_id}")
async def remove_control_preset(preset_id: str, request: Request) -> dict[str, Any]:
    try:
        return await _service_or_404().remove_control_preset(preset_id, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/printers/{printer_id}/control-presets/{preset_id}")
async def remove_control_preset_by_printer(printer_id: str, preset_id: str, request: Request) -> dict[str, Any]:
    try:
        return await _service_or_404(printer_id).remove_control_preset(preset_id, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/alert-rules")
async def alert_rules() -> dict[str, Any]:
    return {"items": _service_or_404().alert_rules_snapshot()}


@app.get("/api/printers/{printer_id}/alert-rules")
async def alert_rules_by_printer(printer_id: str) -> dict[str, Any]:
    return {"items": _service_or_404(printer_id).alert_rules_snapshot()}


@app.post("/api/alert-rules")
async def save_alert_rule(request: Request, payload: AlertRuleRequest) -> dict[str, Any]:
    try:
        return await _service_or_404().save_alert_rule(payload, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/alert-rules/{rule_id}")
async def update_alert_rule(rule_id: str, request: Request, payload: AlertRuleUpdateRequest) -> dict[str, Any]:
    try:
        return await _service_or_404().update_alert_rule(rule_id, payload, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/printers/{printer_id}/alert-rules")
async def save_alert_rule_by_printer(printer_id: str, request: Request, payload: AlertRuleRequest) -> dict[str, Any]:
    try:
        return await _service_or_404(printer_id).save_alert_rule(payload, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/printers/{printer_id}/alert-rules/{rule_id}")
async def update_alert_rule_by_printer(printer_id: str, rule_id: str, request: Request, payload: AlertRuleUpdateRequest) -> dict[str, Any]:
    try:
        return await _service_or_404(printer_id).update_alert_rule(rule_id, payload, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/alert-rules/{rule_id}")
async def remove_alert_rule(rule_id: str, request: Request) -> dict[str, Any]:
    try:
        return await _service_or_404().remove_alert_rule(rule_id, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/printers/{printer_id}/alert-rules/{rule_id}")
async def remove_alert_rule_by_printer(printer_id: str, rule_id: str, request: Request) -> dict[str, Any]:
    try:
        return await _service_or_404(printer_id).remove_alert_rule(rule_id, actor=_actor_from_request(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/events")
async def event_stream(request: Request) -> StreamingResponse:
    queue = _service_or_404().subscribe_events()

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
            _service_or_404().unsubscribe_events(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/printers/{printer_id}/events")
async def event_stream_by_printer(request: Request, printer_id: str) -> StreamingResponse:
    svc = _service_or_404(printer_id)
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


@app.get("/api/sd/models")
async def sd_models(query: str | None = None) -> dict[str, Any]:
    try:
        models = await _service_or_404().list_sd_models(query=query)
        return {"items": models, "count": len(models)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/printers/{printer_id}/sd/models")
async def sd_models_by_printer(printer_id: str, query: str | None = None) -> dict[str, Any]:
    try:
        models = await _service_or_404(printer_id).list_sd_models(query=query)
        return {"items": models, "count": len(models)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sd/thumbnail")
async def sd_thumbnail(path: str) -> Response:
    try:
        content, mime = await _service_or_404().get_sd_thumbnail(path)
        if not content or not mime:
            raise HTTPException(status_code=404, detail="Thumbnail not found.")
        return Response(
            content=content,
            media_type=mime,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/printers/{printer_id}/sd/thumbnail")
async def sd_thumbnail_by_printer(printer_id: str, path: str) -> Response:
    try:
        content, mime = await _service_or_404(printer_id).get_sd_thumbnail(path)
        if not content or not mime:
            raise HTTPException(status_code=404, detail="Thumbnail not found.")
        return Response(
            content=content,
            media_type=mime,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/live/chamber.jpg")
async def chamber_image() -> Response:
    try:
        content, mime = await _service_or_404().get_live_frame()
        if not content or not mime:
            return Response(status_code=204)
        return Response(
            content=content,
            media_type=mime,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/live/stream.mjpg")
async def chamber_stream() -> StreamingResponse:
    return await chamber_stream_by_printer(printer_manager.default_id)


@app.get("/api/printers/{printer_id}/live/chamber.jpg")
async def chamber_image_by_printer(printer_id: str) -> Response:
    try:
        content, mime = await _service_or_404(printer_id).get_live_frame()
        if not content or not mime:
            return Response(status_code=204)
        return Response(
            content=content,
            media_type=mime,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/printers/{printer_id}/live/stream.mjpg")
async def chamber_stream_by_printer(printer_id: str) -> StreamingResponse:
    service = _service_or_404(printer_id)
    boundary = "frame"

    async def frame_generator():
        try:
            # Primary path: one continuous ffmpeg process for smooth RTSP->MJPEG streaming.
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

            # Fallback path: snapshot stream if RTSP/ffmpeg streaming is unavailable.
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


@app.post("/api/actions/refresh")
async def refresh() -> dict[str, bool]:
    try:
        await _service_or_404().refresh()
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/actions/chamber-light")
async def chamber_light(request: Request, payload: ChamberLightRequest) -> dict[str, bool]:
    try:
        await _service_or_404().set_chamber_light(payload.on, actor=_actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/actions/temperature")
async def temperature(request: Request, payload: TemperatureRequest) -> dict[str, bool]:
    try:
        await _service_or_404().set_temperature(payload, actor=_actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/actions/fan")
async def fan(request: Request, payload: FanRequest) -> dict[str, bool]:
    try:
        await _service_or_404().set_fan(payload, actor=_actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/actions/{action}")
async def action(request: Request, action: str) -> dict[str, bool]:
    try:
        ok = await _service_or_404().action(action, actor=_actor_from_request(request))
        return {"ok": ok}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/printers/{printer_id}/actions/refresh")
async def refresh_by_printer(printer_id: str) -> dict[str, bool]:
    try:
        await _service_or_404(printer_id).refresh()
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/printers/{printer_id}/actions/chamber-light")
async def chamber_light_by_printer(printer_id: str, request: Request, payload: ChamberLightRequest) -> dict[str, bool]:
    try:
        await _service_or_404(printer_id).set_chamber_light(payload.on, actor=_actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/printers/{printer_id}/actions/temperature")
async def temperature_by_printer(printer_id: str, request: Request, payload: TemperatureRequest) -> dict[str, bool]:
    try:
        await _service_or_404(printer_id).set_temperature(payload, actor=_actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/printers/{printer_id}/actions/fan")
async def fan_by_printer(printer_id: str, request: Request, payload: FanRequest) -> dict[str, bool]:
    try:
        await _service_or_404(printer_id).set_fan(payload, actor=_actor_from_request(request))
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/printers/{printer_id}/actions/{action}")
async def action_by_printer(printer_id: str, request: Request, action: str) -> dict[str, bool]:
    try:
        ok = await _service_or_404(printer_id).action(action, actor=_actor_from_request(request))
        return {"ok": ok}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
