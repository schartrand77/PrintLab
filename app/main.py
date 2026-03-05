from __future__ import annotations

import asyncio
import io
import hashlib
import re
import logging
import os
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from zipfile import ZipFile

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pybambu import BambuClient
from pybambu.commands import PAUSE, RESUME, STOP
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

    def _on_client_event(self, event: str) -> None:
        self._mark_event(event)

    async def start(self) -> None:
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

    def _capture_rtsp_snapshot_sync(self) -> tuple[bytes | None, str | None]:
        if self.client is None:
            return None, None

        now = time.time()
        if self._live_cache_bytes and (now - self._live_cache_time) < 1.5:
            return self._live_cache_bytes, self._live_cache_mime

        device = self.client.get_device()
        rtsp_url = device.camera.rtsp_url
        if not rtsp_url or rtsp_url == "disable":
            return None, None

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

        for url in urls_to_try:
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
                }
            except Exception as exc:
                self.last_error = str(exc)
                return base


app = FastAPI(title="PrintLab", version="0.1.0")
service = PrinterService()
dashboard_html = (Path(__file__).with_name("dashboard.html")).read_text(encoding="utf-8")
app.mount("/data", StaticFiles(directory="/data"), name="data")


@app.on_event("startup")
async def startup() -> None:
    await service.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await service.stop()


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return dashboard_html


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
