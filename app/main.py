from __future__ import annotations

import asyncio
import copy
import io
import hashlib
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


def parse_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class FanRequest(BaseModel):
    fan: str = Field(pattern="^(part_cooling|auxiliary|chamber|heatbreak|secondary_auxiliary)$")
    percent: int = Field(ge=0, le=100)


class TemperatureRequest(BaseModel):
    target: str = Field(pattern="^(heatbed|nozzle)$")
    value: int = Field(ge=0, le=320)


class ChamberLightRequest(BaseModel):
    on: bool


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
    def __init__(self) -> None:
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

    def _config(self) -> dict[str, Any]:
        host = os.getenv("PRINTER_HOST", "").strip()
        serial = os.getenv("PRINTER_SERIAL", "").strip()
        access_code = os.getenv("PRINTER_ACCESS_CODE", "").strip()

        if not host or not serial or not access_code:
            raise ValueError("PRINTER_HOST, PRINTER_SERIAL, and PRINTER_ACCESS_CODE are required.")

        return {
            "host": host,
            "serial": serial,
            "access_code": access_code,
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

    def _mark_event(self, event: str) -> None:
        self.last_event = event
        self.last_update_utc = datetime.now(timezone.utc).isoformat()
        self._broadcast_event(event)

    def _on_client_event(self, event: str) -> None:
        self._mark_event(event)

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
            LOGGER.info("Connected to printer %s", cfg["serial"])
        except Exception as exc:
            self.last_error = str(exc)
            LOGGER.exception("Failed to connect to printer")

    async def stop(self) -> None:
        if self.client is not None:
            self.client.disconnect()
            self._mark_event("disconnected")

    async def action(self, action: str) -> bool:
        if self.client is None:
            raise RuntimeError("Client not initialized.")

        if action == "pause":
            return self.client.publish(PAUSE)
        if action == "resume":
            return self.client.publish(RESUME)
        if action == "stop":
            return self.client.publish(STOP)
        raise ValueError(f"Unknown action: {action}")

    async def set_chamber_light(self, on: bool) -> None:
        if self.client is None:
            raise RuntimeError("Client not initialized.")
        device = self.client.get_device()
        if on:
            device.lights.TurnChamberLightOn()
        else:
            device.lights.TurnChamberLightOff()
        self._mark_event("event_light_update")

    async def set_temperature(self, request: TemperatureRequest) -> None:
        if self.client is None:
            raise RuntimeError("Client not initialized.")
        target = TempEnum.HEATBED if request.target == "heatbed" else TempEnum.NOZZLE
        self.client.get_device().temperature.set_target_temp(target, request.value)
        self._mark_event("event_temperature_update")

    async def set_fan(self, request: FanRequest) -> None:
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
            slots = ams.get("slots", [])
            loaded = next((slot for slot in slots if slot.get("active")), None)
            loaded_filament = None
            if loaded:
                loaded_filament = {
                    "slot_index": loaded.get("index"),
                    "type": loaded.get("type"),
                    "color_hex": loaded.get("color_hex"),
                    "remaining_percent": loaded.get("remain_percent"),
                }
            remaining = [
                {
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

    async def start_orderworks_print_job(self, request: OrderworksPrintJobRequest) -> dict[str, Any]:
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
        return {
            "ok": bool(ok),
            "submitted": bool(ok),
            "file_path": ftp_path,
            "plate_gcode": request.plate_gcode,
            "use_ams": request.use_ams,
            "ams_mapping": command_print.get("ams_mapping"),
            "subtask_name": command_print.get("subtask_name"),
        }

    def _serialize_ams(self, device: Any) -> dict[str, Any]:
        ams = getattr(device, "ams", None)
        ams_data = getattr(ams, "data", None)
        if not isinstance(ams_data, dict) or not ams_data:
            return {
                "present": False,
                "ams_index": None,
                "active_ams_index": None,
                "active_tray_index": None,
                "humidity_pct": None,
                "temperature_c": None,
                "slots": [],
            }

        active_ams_index = getattr(ams, "active_ams_index", None)
        active_tray_index = getattr(ams, "active_tray_index", None)

        if active_ams_index in ams_data:
            selected_ams_index = active_ams_index
        else:
            selected_ams_index = sorted(ams_data.keys())[0]

        selected = ams_data[selected_ams_index]
        trays = list(getattr(selected, "tray", []) or [])
        slots: list[dict[str, Any]] = []
        for tray_idx in range(4):
            tray = trays[tray_idx] if tray_idx < len(trays) else None
            is_empty = bool(getattr(tray, "empty", True)) if tray is not None else True
            tray_type = (getattr(tray, "type", "") or "").strip() if tray is not None else ""
            slots.append(
                {
                    "index": tray_idx,
                    "active": bool(getattr(tray, "active", False)) if tray is not None else False,
                    "empty": is_empty,
                    "type": tray_type if tray_type else ("Empty" if is_empty else "-"),
                    "name": (getattr(tray, "name", "") or "").strip() if tray is not None else "",
                    "color_hex": self._normalize_ams_color(getattr(tray, "color", None)) if tray is not None else "#2f343c",
                    "remain_percent": getattr(tray, "remain", None) if tray is not None else None,
                }
            )

        humidity = getattr(selected, "humidity", None)
        temperature = getattr(selected, "temperature", None)
        return {
            "present": True,
            "ams_index": selected_ams_index,
            "active_ams_index": active_ams_index,
            "active_tray_index": active_tray_index,
            "humidity_pct": humidity if isinstance(humidity, (int, float)) and humidity >= 0 else None,
            "temperature_c": temperature if isinstance(temperature, (int, float)) and temperature >= 0 else None,
            "slots": slots,
        }

    async def state(self) -> dict[str, Any]:
        async with self._lock:
            base = {
                "configured": self.configured,
                "connected": bool(self.client and self.client.connected),
                "last_event": self.last_event,
                "last_update_utc": self.last_update_utc,
                "last_error": self.last_error,
            }

            if self.client is None:
                return base

            try:
                device = self.client.get_device()
                info = device.info
                job = device.print_job
                temp = device.temperature
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
                }
            except Exception as exc:
                self.last_error = str(exc)
                return base


app = FastAPI(title="PrintLab", version="0.1.0")
service = PrinterService()
works_service = WorksService()
dashboard_html = (Path(__file__).with_name("dashboard.html")).read_text(encoding="utf-8")
static_dir = Path(__file__).with_name("static")
app.mount("/data", StaticFiles(directory="/data"), name="data")
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.on_event("startup")
async def startup() -> None:
    await service.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await service.stop()


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return dashboard_html


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


@app.get("/health")
async def health() -> dict[str, Any]:
    state = await service.state()
    return {
        "ok": state["configured"],
        "configured": state["configured"],
        "connected": state["connected"],
        "last_error": state["last_error"],
    }


@app.get("/api/state")
async def get_state() -> dict[str, Any]:
    return await service.state()


@app.get("/api/works/services")
async def works_services() -> dict[str, Any]:
    return {"items": works_service.list_services()}


@app.get("/api/works/{service_name}/health")
async def works_health(service_name: str, path: str = "/health") -> dict[str, Any]:
    try:
        result = await works_service.health(service_name, path=path)
        if service_name.lower() == "stockworks":
            result["printer_filament"] = service.filament_snapshot()
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/works/{service_name}/request")
async def works_request(service_name: str, request: WorksRequest) -> dict[str, Any]:
    try:
        result = await works_service.request(service_name, request)
        if service_name.lower() == "stockworks":
            result["printer_filament"] = service.filament_snapshot()
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/works/orderworks/print-job")
async def orderworks_print_job(request: OrderworksPrintJobRequest) -> dict[str, Any]:
    try:
        return await service.start_orderworks_print_job(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/events")
async def event_stream(request: Request) -> StreamingResponse:
    queue = service.subscribe_events()

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
            service.unsubscribe_events(queue)

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
        models = await service.list_sd_models(query=query)
        return {"items": models, "count": len(models)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sd/thumbnail")
async def sd_thumbnail(path: str) -> Response:
    try:
        content, mime = await service.get_sd_thumbnail(path)
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
        content, mime = await service.get_live_frame()
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
        await service.refresh()
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/actions/{action}")
async def action(action: str) -> dict[str, bool]:
    try:
        ok = await service.action(action)
        return {"ok": ok}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/actions/chamber-light")
async def chamber_light(request: ChamberLightRequest) -> dict[str, bool]:
    try:
        await service.set_chamber_light(request.on)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/actions/temperature")
async def temperature(request: TemperatureRequest) -> dict[str, bool]:
    try:
        await service.set_temperature(request)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/actions/fan")
async def fan(request: FanRequest) -> dict[str, bool]:
    try:
        await service.set_fan(request)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
