from __future__ import annotations

import asyncio
import base64
import binascii
import copy
import hashlib
import hmac
import io
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4
from zipfile import ZipFile

import requests
from pydantic import BaseModel, Field

from app.config import get_bool, get_env

try:
    from pybambu import BambuClient
    from pybambu.commands import PAUSE, PRINT_PROJECT_FILE_TEMPLATE, RESUME, STOP
    from pybambu.const import FansEnum, TempEnum
except ImportError:  # pragma: no cover - exercised only in test/dev environments without pybambu
    BambuClient = Any  # type: ignore[assignment]
    PAUSE = "pause"
    PRINT_PROJECT_FILE_TEMPLATE = {}
    RESUME = "resume"
    STOP = "stop"

    class FansEnum:
        PART_COOLING = "part_cooling"
        AUXILIARY = "auxiliary"
        CHAMBER = "chamber"
        HEATBREAK = "heatbreak"
        SECONDARY_AUXILIARY = "secondary_auxiliary"

    class TempEnum:
        HEATBED = "heatbed"
        NOZZLE = "nozzle"


LOGGER = logging.getLogger("printlab")
logging.basicConfig(level=get_env("LOG_LEVEL", "INFO").upper())


def data_root() -> Path:
    configured = get_env("PRINTLAB_DATA_DIR", "")
    if configured:
        return Path(configured)
    default = Path("/data")
    if default.exists():
        return default
    return Path(__file__).resolve().parents[1] / "data"


def parse_bool(name: str, default: bool) -> bool:
    return get_bool(name, default)


def build_default_printer_config() -> dict[str, Any]:
    return {
        "name": get_env("PRINTER_NAME", ""),
        "host": get_env("PRINTER_HOST", ""),
        "serial": get_env("PRINTER_SERIAL", ""),
        "access_code": get_env("PRINTER_ACCESS_CODE", ""),
        "device_type": get_env("PRINTER_DEVICE_TYPE", "unknown"),
        "local_mqtt": parse_bool("PRINTER_LOCAL_MQTT", True),
        "enable_camera": parse_bool("PRINTER_ENABLE_CAMERA", True),
        "disable_ssl_verify": parse_bool("PRINTER_DISABLE_SSL_VERIFY", False),
        "user_language": get_env("USER_LANGUAGE", "en"),
        "file_cache_path": get_env("FILE_CACHE_PATH", "/data/cache"),
        "print_cache_count": int(get_env("PRINT_CACHE_COUNT", "1")),
        "timelapse_cache_count": int(get_env("TIMELAPSE_CACHE_COUNT", "0")),
        "usage_hours": float(get_env("USAGE_HOURS", "0")),
        "force_ip": parse_bool("FORCE_IP", False),
        "region": get_env("BAMBU_REGION", ""),
        "email": get_env("BAMBU_EMAIL", ""),
        "username": get_env("BAMBU_USERNAME", ""),
        "auth_token": get_env("BAMBU_AUTH_TOKEN", ""),
    }


def load_printer_definitions() -> list[dict[str, Any]]:
    raw = get_env("PRINTERS_JSON", "")
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


class UpdatePrinterRequest(BaseModel):
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
    body_text: str | None = None
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


class MakerworksQueueJobRequest(BaseModel):
    model_id: str = Field(min_length=1)
    start_at: str | None = Field(default=None, description="UTC ISO timestamp for scheduled start.")
    plate_gcode: str = Field(default="Metadata/plate_1.gcode")
    use_ams: bool = True
    ams_mapping: list[int] | None = None
    bed_type: str = "auto"
    timelapse: bool = False
    bed_leveling: bool = True
    flow_cali: bool = True
    vibration_cali: bool = True
    layer_inspect: bool = True


class MakerworksSubmitJobRequest(BaseModel):
    model_id: str = Field(min_length=1)
    printer_id: str | None = Field(default=None, min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=128)
    source_job_id: str = Field(min_length=1, max_length=128)
    source_order_id: str = Field(min_length=1, max_length=128)
    start_at: str | None = Field(default=None, description="UTC ISO timestamp for scheduled start.")
    plate_gcode: str = Field(default="Metadata/plate_1.gcode")
    use_ams: bool = True
    ams_mapping: list[int] | None = None
    bed_type: str = "auto"
    timelapse: bool = False
    bed_leveling: bool = True
    flow_cali: bool = True
    vibration_cali: bool = True
    layer_inspect: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


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


class SuccessfulGcodeSyncRequest(BaseModel):
    force: bool = False


class WebhookSubscriptionRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    description: str | None = Field(default=None, max_length=200)
    events: list[str] = Field(default_factory=lambda: ["printer.state", "printer.timeline", "audit"])
    secret: str | None = Field(default=None, max_length=256)
    enabled: bool = True


class WebhookSubscriptionUpdateRequest(BaseModel):
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    description: str | None = Field(default=None, max_length=200)
    events: list[str] | None = None
    secret: str | None = Field(default=None, max_length=256)
    enabled: bool | None = None


class WorksService:
    def __init__(self) -> None:
        self._service_env: dict[str, str] = {
            "makerworks": "MAKERWORKS",
            "orderworks": "ORDERWORKS",
            "stockworks": "STOCKWORKS",
        }

    def _default_allowed_paths(self, service: str) -> list[str]:
        prefixes = ["/health"]
        if service == "makerworks":
            path_template = get_env("MAKERWORKS_ATTACH_GCODE_PATH_TEMPLATE", "")
            prefix = self._path_template_prefix(path_template)
            if prefix:
                prefixes.append(prefix)
            callback_template = get_env("MAKERWORKS_JOB_CALLBACK_PATH_TEMPLATE", "")
            callback_prefix = self._path_template_prefix(callback_template)
            if callback_prefix and callback_prefix not in prefixes:
                prefixes.append(callback_prefix)
            library_cfg = self._makerworks_library_config()
            for candidate in (library_cfg["list_path"], library_cfg["detail_path_template"]):
                library_prefix = self._path_template_prefix(candidate)
                if library_prefix and library_prefix not in prefixes:
                    prefixes.append(library_prefix)
        return prefixes

    def _path_template_prefix(self, path_template: str) -> str | None:
        raw = str(path_template or "").strip()
        if not raw:
            return None
        if not raw.startswith("/"):
            raw = f"/{raw}"
        prefix = raw.split("{", 1)[0].rstrip("/")
        return prefix or "/"

    def _parse_csv(self, raw: str) -> list[str]:
        return [item.strip() for item in raw.split(",") if item.strip()]

    def _clean_optional_path(self, raw: str, default: str = "") -> str:
        value = str(raw or default).strip()
        if not value:
            return ""
        if not value.startswith("/"):
            value = f"/{value}"
        return value

    def _env_int(self, name: str, default: int) -> int:
        raw = get_env(name, str(default))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    def _makerworks_library_config(self) -> dict[str, Any]:
        return {
            "list_path": self._clean_optional_path(get_env("MAKERWORKS_LIBRARY_LIST_PATH", "/api/models"), "/api/models"),
            "detail_path_template": self._clean_optional_path(
                get_env("MAKERWORKS_LIBRARY_DETAIL_PATH_TEMPLATE", "/api/models/{model_id}"),
                "/api/models/{model_id}",
            ),
            "search_param": get_env("MAKERWORKS_LIBRARY_SEARCH_PARAM", "q"),
            "page_param": get_env("MAKERWORKS_LIBRARY_PAGE_PARAM", "page"),
            "page_size_param": get_env("MAKERWORKS_LIBRARY_PAGE_SIZE_PARAM", "page_size"),
            "default_page_size": max(1, min(100, self._env_int("MAKERWORKS_LIBRARY_PAGE_SIZE", 24))),
            "items_path": get_env("MAKERWORKS_LIBRARY_ITEMS_PATH", "models|items|data.items|results"),
            "total_path": get_env("MAKERWORKS_LIBRARY_TOTAL_PATH", "total|count|meta.total"),
            "id_path": get_env("MAKERWORKS_LIBRARY_ID_PATH", "id|model_id|slug"),
            "name_path": get_env("MAKERWORKS_LIBRARY_NAME_PATH", "title|name"),
            "summary_path": get_env("MAKERWORKS_LIBRARY_SUMMARY_PATH", "summary|subtitle|excerpt|tagline|material"),
            "description_path": get_env("MAKERWORKS_LIBRARY_DESCRIPTION_PATH", "description|details|content"),
            "thumbnail_path": get_env(
                "MAKERWORKS_LIBRARY_THUMBNAIL_PATH",
                "coverImagePath|thumbnail_url|thumbnail|thumbnail.url|cover.url|image.url|preview_url",
            ),
            "model_url_path": get_env("MAKERWORKS_LIBRARY_MODEL_URL_PATH", "href|url|model_url|links.self|links.web"),
            "download_url_path": get_env(
                "MAKERWORKS_LIBRARY_DOWNLOAD_URL_PATH",
                "filePath|download_url|files.0.download_url|files.0.url|assets.0.download_url|assets.0.url|viewerFilePath",
            ),
            "author_path": get_env(
                "MAKERWORKS_LIBRARY_AUTHOR_PATH",
                "creditName|author.name|author.display_name|author|owner.name|owner.display_name",
            ),
            "tags_path": get_env("MAKERWORKS_LIBRARY_TAGS_PATH", "tags|categories|labels"),
            "files_path": get_env("MAKERWORKS_LIBRARY_FILES_PATH", "files|assets"),
            "created_at_path": get_env("MAKERWORKS_LIBRARY_CREATED_AT_PATH", "created_at|createdAt|published_at"),
            "updated_at_path": get_env("MAKERWORKS_LIBRARY_UPDATED_AT_PATH", "updated_at|updatedAt|modified_at"),
        }

    def _path_tokens(self, path: str) -> list[str]:
        normalized = path.replace("[", ".").replace("]", "")
        return [token for token in normalized.split(".") if token]

    def _extract_path_value(self, payload: Any, path_expr: str) -> Any:
        for raw_path in str(path_expr or "").split("|"):
            path = raw_path.strip()
            if not path or path == ".":
                if payload is not None:
                    return payload
                continue

            current = payload
            valid = True
            for token in self._path_tokens(path):
                if isinstance(current, dict):
                    if token not in current:
                        valid = False
                        break
                    current = current[token]
                elif isinstance(current, list):
                    if not token.isdigit():
                        valid = False
                        break
                    index = int(token)
                    if index < 0 or index >= len(current):
                        valid = False
                        break
                    current = current[index]
                else:
                    valid = False
                    break

            if valid and current is not None:
                return current
        return None

    def _stringify_library_value(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            clean = value.strip()
            return clean or None
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, dict):
            for key in ("name", "title", "display_name", "label", "value"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
        return None

    def _listify_library_value(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            items = [self._stringify_library_value(item) for item in value]
            return [item for item in items if item]
        if isinstance(value, str):
            items = [part.strip() for part in value.split(",")]
            return [item for item in items if item]
        single = self._stringify_library_value(value)
        return [single] if single else []

    def _absolutize_external_url(self, base_url: str, value: str | None) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        return f"{base_url.rstrip('/')}/{raw.lstrip('/')}"

    def _request_error_message(self, response: dict[str, Any], fallback: str) -> str:
        if response.get("ok"):
            return fallback
        status_code = response.get("status_code")
        body = response.get("body")
        snippet: str | None = None
        if isinstance(body, dict):
            for key in ("detail", "error", "message"):
                value = body.get(key)
                if isinstance(value, str) and value.strip():
                    snippet = value.strip()
                    break
        elif isinstance(body, str):
            compact = re.sub(r"\s+", " ", body).strip()
            if compact:
                snippet = compact[:180]
        if snippet:
            return f"{fallback} (status {status_code}): {snippet}"
        return f"{fallback} (status {status_code})"

    def _makerworks_queue_supported(self, download_url: str | None, file_type: str | None) -> bool:
        lowered_url = str(download_url or "").lower()
        lowered_type = str(file_type or "").lower()
        if lowered_url.endswith(".gcode.3mf") or lowered_url.endswith(".3mf") or lowered_url.endswith(".gcode"):
            return True
        return lowered_type in {"3mf", "gcode", "gcode.3mf"}

    def _normalize_makerworks_item(
        self,
        item: Any,
        cfg: dict[str, Any],
        *,
        base_url: str,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise ValueError("MakerWorks library item must be a JSON object.")

        item_id = self._stringify_library_value(self._extract_path_value(item, cfg["id_path"]))
        name = self._stringify_library_value(self._extract_path_value(item, cfg["name_path"])) or "Untitled model"
        summary = self._stringify_library_value(self._extract_path_value(item, cfg["summary_path"]))
        description = self._stringify_library_value(self._extract_path_value(item, cfg["description_path"]))
        thumbnail_url = self._absolutize_external_url(
            base_url,
            self._stringify_library_value(self._extract_path_value(item, cfg["thumbnail_path"])),
        )
        model_url = self._absolutize_external_url(
            base_url,
            self._stringify_library_value(self._extract_path_value(item, cfg["model_url_path"])),
        )
        download_url = self._absolutize_external_url(
            base_url,
            self._stringify_library_value(self._extract_path_value(item, cfg["download_url_path"])),
        )
        author = self._stringify_library_value(self._extract_path_value(item, cfg["author_path"]))
        tags = self._listify_library_value(self._extract_path_value(item, cfg["tags_path"]))
        file_type = self._stringify_library_value(self._extract_path_value(item, "fileType|file_type|assetType"))
        files = self._extract_path_value(item, cfg["files_path"])
        file_count = len(files) if isinstance(files, list) else 0
        has_assets = bool(download_url or file_count)
        queue_supported = self._makerworks_queue_supported(download_url, file_type)

        normalized = {
            "source": "makerworks",
            "id": item_id or name.lower().replace(" ", "-"),
            "name": name,
            "summary": summary,
            "description": description,
            "thumbnail_url": thumbnail_url,
            "model_url": model_url,
            "download_url": download_url,
            "author": author,
            "tags": tags,
            "file_type": file_type,
            "file_count": file_count,
            "created_at": self._stringify_library_value(self._extract_path_value(item, cfg["created_at_path"])),
            "updated_at": self._stringify_library_value(self._extract_path_value(item, cfg["updated_at_path"])),
            "printer_handoff_ready": has_assets,
            "queue_supported": queue_supported,
            "printer_handoff_status": "queue_supported" if queue_supported else "metadata_only",
            "printer_handoff_note": (
                "Model can be staged and queued to an idle printer."
                if queue_supported
                else (
                    "Model assets are available, but this file type is not queueable yet."
                    if has_assets
                    else "Library metadata is available, but no downloadable model asset was found."
                )
            ),
        }
        if include_raw:
            normalized["raw"] = item
        return normalized

    def _service_request_headers(self, cfg: dict[str, Any], extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "*/*"}
        if cfg["api_key"]:
            headers[cfg["auth_header"]] = cfg["api_key"]
        if cfg["bearer_token"]:
            headers["Authorization"] = f"Bearer {cfg['bearer_token']}"
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def download_asset_sync(self, service: str, asset_url: str, timeout_seconds: float = 120.0) -> dict[str, Any]:
        cfg = self._get_config(service)
        url = asset_url.strip()
        if not url:
            raise ValueError("Asset URL is required.")
        if not (url.startswith("http://") or url.startswith("https://")):
            url = self._build_url(cfg["base_url"], url)

        response = requests.get(
            url,
            headers=self._service_request_headers(cfg),
            timeout=timeout_seconds,
            verify=cfg["verify_ssl"],
        )
        if not response.ok:
            error_payload = {
                "ok": response.ok,
                "status_code": response.status_code,
                "body": response.text,
            }
            raise RuntimeError(self._request_error_message(error_payload, f"{service} asset download failed"))
        path = urlsplit(response.url or url).path
        filename = Path(path).name or Path(urlsplit(url).path).name or "asset.bin"
        return {"url": response.url or url, "filename": filename, "content": response.content, "content_type": response.headers.get("content-type")}

    async def download_asset(self, service: str, asset_url: str, timeout_seconds: float = 120.0) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.download_asset_sync(service, asset_url, timeout_seconds))

    def _makerworks_library_items(self, body: Any, cfg: dict[str, Any]) -> list[Any]:
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            extracted = self._extract_path_value(body, cfg["items_path"])
            if isinstance(extracted, list):
                return extracted
        raise ValueError("MakerWorks library response did not contain a list of items.")

    def _makerworks_library_query_params(self, cfg: dict[str, Any], query: str | None, page: int, page_size: int) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if query and cfg["search_param"]:
            params[str(cfg["search_param"])] = query
        if cfg["page_param"]:
            params[str(cfg["page_param"])] = page
        if cfg["page_size_param"]:
            params[str(cfg["page_size_param"])] = page_size
        return params

    def makerworks_library_sync(
        self,
        *,
        query: str | None = None,
        page: int = 1,
        page_size: int | None = None,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        service_cfg = self._get_config("makerworks")
        library_cfg = self._makerworks_library_config()
        page_value = max(1, int(page))
        size_value = page_size if page_size is not None else int(library_cfg["default_page_size"])
        size_value = max(1, min(100, int(size_value)))

        if not library_cfg["list_path"]:
            raise RuntimeError("MakerWorks library is not configured (missing MAKERWORKS_LIBRARY_LIST_PATH).")

        payload = WorksRequest(
            method="GET",
            path=str(library_cfg["list_path"]),
            query=self._makerworks_library_query_params(library_cfg, query, page_value, size_value),
        )
        response = self.request_sync("makerworks", payload)
        if not response.get("ok"):
            raise RuntimeError(self._request_error_message(response, "MakerWorks library request failed"))
        body = response.get("body")
        items = [
            self._normalize_makerworks_item(
                item,
                library_cfg,
                base_url=str(service_cfg["base_url"]),
                include_raw=include_raw,
            )
            for item in self._makerworks_library_items(body, library_cfg)
        ]
        total = self._extract_path_value(body, library_cfg["total_path"]) if isinstance(body, dict) else None
        total_value = int(total) if isinstance(total, (int, float)) else len(items)
        return {
            "service": service_cfg["service"],
            "path": library_cfg["list_path"],
            "configured": service_cfg["configured"],
            "count": len(items),
            "total": total_value,
            "page": page_value,
            "page_size": size_value,
            "items": items,
        }

    async def makerworks_library(
        self,
        *,
        query: str | None = None,
        page: int = 1,
        page_size: int | None = None,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.makerworks_library_sync(
                query=query,
                page=page,
                page_size=page_size,
                include_raw=include_raw,
            ),
        )

    def makerworks_library_item_sync(self, model_id: str, *, include_raw: bool = True) -> dict[str, Any]:
        library_cfg = self._makerworks_library_config()
        template = str(library_cfg["detail_path_template"] or "").strip()
        if not template:
            raise RuntimeError("MakerWorks model detail is not configured (missing MAKERWORKS_LIBRARY_DETAIL_PATH_TEMPLATE).")

        payload = WorksRequest(
            method="GET",
            path=template.format(model_id=quote(str(model_id), safe="")),
        )
        response = self.request_sync("makerworks", payload)
        if not response.get("ok"):
            raise RuntimeError(self._request_error_message(response, "MakerWorks model detail request failed"))
        body = response.get("body")
        if isinstance(body, dict):
            raw_item = self._extract_path_value(body, "item|data|model") or body
        else:
            raw_item = body
        item = self._normalize_makerworks_item(
            raw_item,
            library_cfg,
            base_url=str(self._get_config("makerworks")["base_url"]),
            include_raw=include_raw,
        )
        return {
            "service": "makerworks",
            "path": payload.path,
            "configured": self._get_config("makerworks")["configured"],
            "item": item,
        }

    async def makerworks_library_item(self, model_id: str, *, include_raw: bool = True) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.makerworks_library_item_sync(model_id, include_raw=include_raw),
        )

    def _get_config(self, service: str) -> dict[str, Any]:
        key = self._service_env.get(service.lower())
        if key is None:
            raise ValueError(f"Unknown integration service: {service}")

        base_url = get_env(f"{key}_BASE_URL", "")
        api_key = get_env(f"{key}_API_KEY", "")
        bearer_token = get_env(f"{key}_BEARER_TOKEN", "")
        auth_header = get_env(f"{key}_AUTH_HEADER", "X-API-Key") or "X-API-Key"
        verify_ssl = parse_bool(f"{key}_VERIFY_SSL", True)
        configured_allowed_paths = self._parse_csv(get_env(f"{key}_ALLOWED_PATHS", ""))
        default_allowed_paths = self._default_allowed_paths(service.lower())
        allowed_paths = configured_allowed_paths or list(default_allowed_paths)
        for default_path in default_allowed_paths:
            if default_path not in allowed_paths:
                allowed_paths.append(default_path)
        allowed_methods = [item.upper() for item in self._parse_csv(get_env(f"{key}_ALLOWED_METHODS", ""))]

        return {
            "service": service.lower(),
            "base_url": base_url,
            "api_key": api_key,
            "bearer_token": bearer_token,
            "auth_header": auth_header,
            "verify_ssl": verify_ssl,
            "allowed_paths": allowed_paths,
            "allowed_methods": allowed_methods,
            "configured": bool(base_url),
        }

    def list_services(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for service in self._service_env:
            cfg = self._get_config(service)
            item = {
                "service": cfg["service"],
                "configured": cfg["configured"],
                "base_url": cfg["base_url"],
                "allowed_paths": cfg["allowed_paths"],
                "allowed_methods": cfg["allowed_methods"],
            }
            if service == "makerworks":
                library_cfg = self._makerworks_library_config()
                item["library"] = {
                    "list_path": library_cfg["list_path"],
                    "detail_path_template": library_cfg["detail_path_template"],
                    "default_page_size": library_cfg["default_page_size"],
                }
            items.append(item)
        return items

    def _normalize_path(self, path: str) -> str:
        raw_path = (path or "/").strip()
        if raw_path.startswith("http://") or raw_path.startswith("https://"):
            raise ValueError("Absolute URLs are not allowed in request path.")
        if not raw_path.startswith("/"):
            raw_path = f"/{raw_path}"
        return raw_path

    def _ensure_request_allowed(self, cfg: dict[str, Any], method: str, path: str) -> str:
        normalized_path = self._normalize_path(path)
        allowed_paths = [str(item).strip() for item in cfg.get("allowed_paths", []) if str(item).strip()]
        if not any(normalized_path == prefix or normalized_path.startswith(f"{prefix.rstrip('/')}/") for prefix in allowed_paths):
            raise ValueError(f"Path is not allowed for {cfg['service']}: {normalized_path}")
        allowed_methods = [str(item).upper() for item in cfg.get("allowed_methods", []) if str(item).strip()]
        if allowed_methods and method.upper() not in allowed_methods:
            raise ValueError(f"Method is not allowed for {cfg['service']}: {method.upper()}")
        return normalized_path

    def _build_url(self, base_url: str, path: str) -> str:
        if not base_url:
            raise RuntimeError("Service is not configured (missing BASE_URL).")
        raw_path = self._normalize_path(path)
        return f"{base_url.rstrip('/')}{raw_path}"

    def request_sync(self, service: str, payload: WorksRequest) -> dict[str, Any]:
        cfg = self._get_config(service)
        normalized_path = self._ensure_request_allowed(cfg, payload.method, payload.path)
        url = self._build_url(cfg["base_url"], normalized_path)

        headers: dict[str, str] = {"Accept": "application/json"}
        if cfg["api_key"]:
            headers[cfg["auth_header"]] = cfg["api_key"]
        if cfg["bearer_token"]:
            headers["Authorization"] = f"Bearer {cfg['bearer_token']}"
        if payload.headers:
            headers.update(payload.headers)

        body_text = payload.body_text
        body_json = None if body_text is not None else payload.body

        response = requests.request(
            method=payload.method,
            url=url,
            params=payload.query or None,
            json=body_json,
            data=body_text,
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
        root = data_root()
        self._queue_file = root / f"queue_{printer_id}.json"
        self._timeline_file = root / f"timeline_{printer_id}.json"
        self._audit_file = root / f"audit_{printer_id}.json"
        self._webhooks_file = root / f"webhooks_{printer_id}.json"
        self._presets_file = root / f"control_presets_{printer_id}.json"
        self._alert_rules_file = root / f"alert_rules_{printer_id}.json"
        self._successful_gcodes_file = root / f"successful_gcodes_{printer_id}.json"
        self._submitted_jobs_file = root / f"submitted_jobs_{printer_id}.json"
        self._queue_items: list[dict[str, Any]] = self._load_json_list(self._queue_file)
        self._timeline_entries: list[dict[str, Any]] = self._load_json_list(self._timeline_file)
        self._audit_entries: list[dict[str, Any]] = self._load_json_list(self._audit_file)
        self._webhooks: list[dict[str, Any]] = self._load_json_list(self._webhooks_file)
        self._control_presets: list[dict[str, Any]] = self._load_json_list(self._presets_file)
        self._alert_rules: list[dict[str, Any]] = self._load_json_list(self._alert_rules_file)
        self._successful_gcodes: list[dict[str, Any]] = self._load_json_list(self._successful_gcodes_file)
        self._submitted_jobs: list[dict[str, Any]] = self._load_json_list(self._submitted_jobs_file)
        self._queue_task: asyncio.Task[None] | None = None
        self._job_monitor_task: asyncio.Task[None] | None = None
        self._disconnected_since_utc: str | None = None
        self._last_job_state: str | None = None
        self._active_job_context: dict[str, Any] | None = None
        self._last_completed_job_key: str | None = None

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

    def _save_audit(self) -> None:
        self._save_json_list(self._audit_file, self._audit_entries)

    def _save_webhooks(self) -> None:
        self._save_json_list(self._webhooks_file, self._webhooks)

    def _save_presets(self) -> None:
        self._save_json_list(self._presets_file, self._control_presets)

    def _save_alert_rules(self) -> None:
        self._save_json_list(self._alert_rules_file, self._alert_rules)

    def _save_successful_gcodes(self) -> None:
        self._save_json_list(self._successful_gcodes_file, self._successful_gcodes)

    def _save_submitted_jobs(self) -> None:
        self._save_json_list(self._submitted_jobs_file, self._submitted_jobs)

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
        self._record_audit(event, message, severity=severity, actor=actor, details=details)
        self._broadcast_event(
            event,
            kind="printer.timeline",
            details={"entry": entry, "severity": severity, "message": message},
        )

    def _record_audit(
        self,
        event: str,
        message: str,
        *,
        severity: str = "info",
        actor: str = "system",
        details: dict[str, Any] | None = None,
    ) -> None:
        entry = {
            "id": uuid4().hex,
            "printer_id": self.printer_id,
            "printer_name": self.display_name,
            "event": event,
            "message": message,
            "severity": severity,
            "actor": actor,
            "details": details or {},
            "at": datetime.now(timezone.utc).isoformat(),
        }
        self._audit_entries = [entry, *self._audit_entries[:499]]
        self._save_audit()

    def audit_snapshot(self, limit: int = 100) -> list[dict[str, Any]]:
        return list(self._audit_entries[: max(1, min(limit, 500))])

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

    def job_busy(self) -> bool:
        return self._job_busy()

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

    def successful_gcodes_snapshot(self) -> list[dict[str, Any]]:
        return list(self._successful_gcodes[:200])

    def youtube_connection_status(self) -> dict[str, Any]:
        cfg = self._youtube_upload_config()
        latest_uploaded = next(
            (item for item in self._successful_gcodes if (item.get("youtube") or {}).get("uploaded")),
            None,
        )
        latest_attempt = next(
            (
                item
                for item in self._successful_gcodes
                if (item.get("youtube") or {}).get("last_attempt_at") or (item.get("youtube") or {}).get("uploaded_at")
            ),
            None,
        )
        latest_error = next(
            (item for item in self._successful_gcodes if (item.get("youtube") or {}).get("last_error")),
            None,
        )
        configured = bool(cfg["client_id"] and cfg["client_secret"] and cfg["refresh_token"])
        return {
            "enabled": cfg["enabled"],
            "configured": configured,
            "ready": bool(cfg["enabled"] and configured),
            "privacy_status": cfg["privacy_status"],
            "category_id": cfg["category_id"],
            "uploaded_count": sum(1 for item in self._successful_gcodes if (item.get("youtube") or {}).get("uploaded")),
            "last_uploaded_at": (latest_uploaded or {}).get("youtube", {}).get("uploaded_at"),
            "last_video_url": (latest_uploaded or {}).get("youtube", {}).get("video_url"),
            "last_attempt_at": (latest_attempt or {}).get("youtube", {}).get("last_attempt_at"),
            "last_error": (latest_error or {}).get("youtube", {}).get("last_error"),
        }

    def youtube_videos_snapshot(self, *, page: int = 1, page_size: int = 5) -> dict[str, Any]:
        page_value = max(1, int(page))
        size_value = max(1, min(50, int(page_size)))
        uploaded = [item for item in self._successful_gcodes if (item.get("youtube") or {}).get("uploaded")]
        uploaded.sort(
            key=lambda item: str((item.get("youtube") or {}).get("uploaded_at") or item.get("completed_at") or ""),
            reverse=True,
        )
        total = len(uploaded)
        start = (page_value - 1) * size_value
        end = start + size_value
        items = []
        for record in uploaded[start:end]:
            youtube = record.get("youtube") or {}
            items.append(
                {
                    "record_id": record.get("id"),
                    "printer_id": self.printer_id,
                    "printer_name": self.display_name,
                    "model_id": record.get("model_id"),
                    "model_name": record.get("model_name"),
                    "file_name": record.get("file_name"),
                    "completed_at": record.get("completed_at"),
                    "uploaded_at": youtube.get("uploaded_at"),
                    "video_id": youtube.get("video_id"),
                    "video_url": youtube.get("video_url"),
                    "title": youtube.get("title"),
                    "path": youtube.get("path"),
                    "thumbnail_url": self._job_thumbnail_url(record.get("file_path"), record.get("subtask_name")),
                }
            )
        return {
            "items": items,
            "count": len(items),
            "total": total,
            "page": page_value,
            "page_size": size_value,
            "pages": max(1, (total + size_value - 1) // size_value) if total else 1,
            "connection": self.youtube_connection_status(),
        }

    def submitted_jobs_snapshot(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if not status:
            return list(self._submitted_jobs[:200])
        target = status.strip().lower()
        return [item for item in self._submitted_jobs[:200] if str(item.get("status") or "").lower() == target]

    def submitted_job(self, job_id: str) -> dict[str, Any]:
        for item in self._submitted_jobs:
            if item.get("id") == job_id:
                return item
        raise ValueError(f"Unknown submitted job: {job_id}")

    def find_submitted_job_by_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        target = idempotency_key.strip()
        if not target:
            return None
        for item in self._submitted_jobs:
            if str(item.get("idempotency_key") or "").strip() == target:
                return item
        return None

    def submitted_job_record(self, job_id: str) -> dict[str, Any]:
        return copy.deepcopy(self.submitted_job(job_id))

    def _append_submitted_job_event(
        self,
        job: dict[str, Any],
        *,
        status: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "id": uuid4().hex,
            "status": status,
            "message": message,
            "at": datetime.now(timezone.utc).isoformat(),
            "details": details or {},
        }
        history = job.get("history")
        if not isinstance(history, list):
            history = []
            job["history"] = history
        history.insert(0, event)
        del history[50:]
        job["status"] = status
        job["updated_at"] = event["at"]
        if status not in {"submit_failed", "failed"}:
            job["last_error"] = None

    def create_submitted_job(self, payload: dict[str, Any], *, message: str = "Job accepted by PrintLab.") -> dict[str, Any]:
        job = copy.deepcopy(payload)
        self._append_submitted_job_event(job, status=str(job.get("status") or "accepted"), message=message)
        self._submitted_jobs = [job, *self._submitted_jobs[:499]]
        self._save_submitted_jobs()
        job_id = str(job.get("id") or "").strip()
        if job_id:
            self._schedule_submitted_job_callback(job_id)
        return copy.deepcopy(job)

    def update_submitted_job(
        self,
        job_id: str,
        *,
        status: str,
        message: str,
        details: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job = self.submitted_job(job_id)
        if extra:
            job.update(extra)
        if status in {"submit_failed", "failed"} and details and details.get("error"):
            job["last_error"] = str(details["error"])
        self._append_submitted_job_event(job, status=status, message=message, details=details)
        self._save_submitted_jobs()
        self._schedule_submitted_job_callback(job_id)
        return copy.deepcopy(job)

    def _strip_model_suffix(self, value: str) -> str:
        lowered = value.lower()
        for suffix in (".gcode.3mf", ".3mf", ".gcode"):
            if lowered.endswith(suffix):
                value = value[: -len(suffix)]
                break
        return value

    def _normalize_model_key(self, value: str) -> str:
        normalized = self._strip_model_suffix(value).lower().replace("_", "-").replace(" ", "-")
        normalized = re.sub(r"(?:[-_])plate[-_]?\d+$", "", normalized)
        normalized = re.sub(r"-+", "-", normalized).strip("-")
        return normalized

    def _extract_model_metadata(self, file_path: str, subtask_name: str | None = None) -> dict[str, Any]:
        file_name = Path(file_path or "").name
        base_name = self._strip_model_suffix(file_name)
        normalized_key = self._normalize_model_key(base_name)
        model_id_match = re.match(r"^(\d+)[-_]", base_name)
        plate_match = re.search(r"(?:^|[-_])plate[-_]?(\d+)$", base_name, re.IGNORECASE)
        model_name = re.sub(r"(?:[-_])plate[-_]?\d+$", "", base_name, flags=re.IGNORECASE).strip("-_ ")
        return {
            "file_name": file_name,
            "model_key": normalized_key or self._normalize_model_key(file_name),
            "model_id": model_id_match.group(1) if model_id_match else None,
            "model_name": model_name or (subtask_name or file_name),
            "plate_index": int(plate_match.group(1)) if plate_match else None,
        }

    def _model_summary_for_path(self, path: str) -> dict[str, Any]:
        metadata = self._extract_model_metadata(path)
        matches = [
            item
            for item in self._successful_gcodes
            if item.get("file_path") == path
            or (
                item.get("model_key")
                and metadata.get("model_key")
                and item.get("model_key") == metadata.get("model_key")
            )
        ]
        synced = [item for item in matches if item.get("makerworks", {}).get("attached")]
        latest = matches[0] if matches else None
        return {
            "successful_gcode_count": len(matches),
            "makerworks_attachment_count": len(synced),
            "latest_success_at": latest.get("completed_at") if latest else None,
            "latest_plate_gcode": latest.get("plate_gcode") if latest else None,
            "latest_makerworks_sync_at": latest.get("makerworks", {}).get("attached_at") if latest else None,
        }

    def _job_thumbnail_url(self, file_path: str | None, subtask_name: str | None = None) -> str | None:
        resolved_path = str(file_path or "").strip()
        context = self._active_job_context or {}
        context_path = str(context.get("file_path") or "").strip()
        lowered = resolved_path.lower()
        looks_like_internal_plate_path = (
            lowered.startswith("/data/metadata/")
            or lowered.startswith("data/metadata/")
            or lowered.startswith("/metadata/")
            or lowered.startswith("metadata/")
        )
        if not resolved_path and context_path:
            resolved_path = context_path
        elif looks_like_internal_plate_path and context_path:
            resolved_path = context_path
        elif resolved_path and not resolved_path.startswith("/") and context_path:
            resolved_name = Path(resolved_path).name
            context_name = Path(context_path).name
            if resolved_name == context_name or resolved_name == str(subtask_name or "").strip():
                resolved_path = context_path

        if not resolved_path:
            return None

        quoted = quote(resolved_path, safe="")
        return f"/api/printers/{quote(self.printer_id, safe='')}/sd/thumbnail?path={quoted}"

    def _is_alias_thumbnail_path(self, path: str) -> bool:
        normalized = str(path or "").strip().replace("\\", "/")
        if not normalized:
            return True
        lowered = normalized.lower()
        if lowered.startswith("/data/metadata/") or lowered.startswith("/metadata/"):
            return True
        return not normalized.startswith("/")

    def _plate_index_from_path(self, path: str | None) -> int | None:
        file_name = Path(str(path or "").strip()).name
        match = re.search(r"(?:^|[-_])plate[-_]?(\d+)(?:\.[^.]+)+$", file_name, re.IGNORECASE)
        if not match:
            match = re.search(r"(?:^|[-_])plate[-_]?(\d+)$", self._strip_model_suffix(file_name), re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _preferred_thumbnail_plate_index(self, raw_path: str, resolved_path: str) -> int | None:
        context = self._active_job_context or {}
        for candidate in (
            context.get("plate_index"),
            self._plate_index_from_path(context.get("plate_gcode")),
            self._plate_index_from_path(raw_path),
            self._plate_index_from_path(resolved_path),
        ):
            if isinstance(candidate, int) and candidate > 0:
                return candidate
        return None

    def _job_context_from_request(self, request: OrderworksPrintJobRequest, actor: str) -> dict[str, Any]:
        metadata = self._extract_model_metadata(request.file_path, request.subtask_name)
        return {
            "file_path": request.file_path if request.file_path.startswith("/") else f"/{request.file_path}",
            "plate_gcode": request.plate_gcode,
            "subtask_name": request.subtask_name,
            "use_ams": request.use_ams,
            "ams_mapping": list(request.ams_mapping) if request.ams_mapping else None,
            "actor": actor,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            **metadata,
        }

    def _job_snapshot(self) -> dict[str, Any] | None:
        if self.client is None or not self.client.connected:
            return None
        try:
            job = self.client.get_device().print_job
            file_path = str(getattr(job, "gcode_file", "") or "").strip()
            subtask_name = str(getattr(job, "subtask_name", "") or "").strip() or None
            state = str(getattr(job, "gcode_state", "") or "").upper()
            metadata = self._extract_model_metadata(file_path or subtask_name or "", subtask_name)
            return {
                "state": state,
                "file_path": file_path,
                "subtask_name": subtask_name,
                "progress_percent": getattr(job, "print_percentage", None),
                "remaining_minutes": getattr(job, "remaining_time", None),
                **metadata,
            }
        except Exception:
            return None

    def _build_completion_record(self, snapshot: dict[str, Any], completed_at: str) -> dict[str, Any]:
        context = self._active_job_context or {}
        file_path = str(snapshot.get("file_path") or context.get("file_path") or "").strip()
        metadata = self._extract_model_metadata(file_path, snapshot.get("subtask_name") or context.get("subtask_name"))
        record = {
            "id": uuid4().hex,
            "printer_id": self.printer_id,
            "printer_name": self.display_name,
            "completed_at": completed_at,
            "state": snapshot.get("state") or self._last_job_state,
            "file_path": file_path,
            "file_name": metadata.get("file_name"),
            "model_key": metadata.get("model_key"),
            "model_id": context.get("model_id") or metadata.get("model_id"),
            "model_name": context.get("model_name") or metadata.get("model_name"),
            "plate_index": context.get("plate_index") or metadata.get("plate_index"),
            "plate_gcode": context.get("plate_gcode"),
            "subtask_name": snapshot.get("subtask_name") or context.get("subtask_name"),
            "use_ams": context.get("use_ams"),
            "ams_mapping": context.get("ams_mapping"),
            "progress_percent": snapshot.get("progress_percent"),
            "makerworks": {
                "attached": False,
                "attached_at": None,
                "last_attempt_at": None,
                "last_error": None,
                "status_code": None,
                "path": None,
            },
            "youtube": {
                "uploaded": False,
                "uploaded_at": None,
                "last_attempt_at": None,
                "last_error": None,
                "status_code": None,
                "video_id": None,
                "video_url": None,
                "path": None,
                "title": None,
            },
        }
        return record

    def _completion_key(self, payload: dict[str, Any]) -> str:
        file_path = str(payload.get("file_path") or "").strip().lower()
        subtask_name = str(payload.get("subtask_name") or "").strip().lower()
        completed_at = str(payload.get("completed_at") or "").strip()
        return f"{file_path}|{subtask_name}|{completed_at[:16]}"

    def _makerworks_attach_config(self) -> dict[str, Any]:
        path_template = get_env("MAKERWORKS_ATTACH_GCODE_PATH_TEMPLATE", "")
        return {
            "enabled": parse_bool("MAKERWORKS_ATTACH_GCODE_ENABLED", False),
            "path_template": path_template,
            "method": (get_env("MAKERWORKS_ATTACH_GCODE_METHOD", "POST") or "POST").upper(),
        }

    def _makerworks_job_callback_config(self) -> dict[str, Any]:
        path_template = get_env("MAKERWORKS_JOB_CALLBACK_PATH_TEMPLATE", "")
        return {
            "enabled": parse_bool("MAKERWORKS_JOB_CALLBACK_ENABLED", False),
            "path_template": path_template,
            "method": (get_env("MAKERWORKS_JOB_CALLBACK_METHOD", "POST") or "POST").upper(),
            "webhook_secret": get_env("MAKERWORKS_WEBHOOK_SECRET", ""),
        }

    def _youtube_upload_config(self) -> dict[str, Any]:
        tags_raw = get_env("YOUTUBE_TAGS", "")
        return {
            "enabled": parse_bool("YOUTUBE_UPLOAD_ENABLED", False),
            "client_id": get_env("YOUTUBE_CLIENT_ID", ""),
            "client_secret": get_env("YOUTUBE_CLIENT_SECRET", ""),
            "refresh_token": get_env("YOUTUBE_REFRESH_TOKEN", ""),
            "privacy_status": (get_env("YOUTUBE_PRIVACY_STATUS", "private") or "private").strip().lower(),
            "category_id": (get_env("YOUTUBE_CATEGORY_ID", "28") or "28").strip(),
            "title_template": get_env("YOUTUBE_TITLE_TEMPLATE", "{model_name} - {printer_name}"),
            "description_template": get_env(
                "YOUTUBE_DESCRIPTION_TEMPLATE",
                "Printed on {printer_name}\nModel: {model_name}\nFile: {file_name}\nCompleted: {completed_at}",
            ),
            "tags": [item.strip() for item in tags_raw.split(",") if item.strip()],
            "notify_subscribers": parse_bool("YOUTUBE_NOTIFY_SUBSCRIBERS", False),
            "made_for_kids": parse_bool("YOUTUBE_MADE_FOR_KIDS", False),
            "embeddable": parse_bool("YOUTUBE_EMBEDDABLE", True),
            "license": (get_env("YOUTUBE_LICENSE", "youtube") or "youtube").strip(),
            "public_stats_viewable": parse_bool("YOUTUBE_PUBLIC_STATS_VIEWABLE", True),
            "wait_seconds": max(0, int(get_env("YOUTUBE_TIMELAPSE_WAIT_SECONDS", "180") or "180")),
            "poll_interval_seconds": max(1, int(get_env("YOUTUBE_TIMELAPSE_POLL_INTERVAL_SECONDS", "5") or "5")),
            "timeout_seconds": max(30, int(get_env("YOUTUBE_UPLOAD_TIMEOUT_SECONDS", "900") or "900")),
        }

    def _youtube_template_context(self, record: dict[str, Any]) -> dict[str, str]:
        return {
            "printer_id": str(self.printer_id or ""),
            "printer_name": str(self.display_name or ""),
            "record_id": str(record.get("id") or ""),
            "model_id": str(record.get("model_id") or ""),
            "model_key": str(record.get("model_key") or ""),
            "model_name": str(record.get("model_name") or record.get("file_name") or "Print"),
            "file_path": str(record.get("file_path") or ""),
            "file_name": str(record.get("file_name") or ""),
            "plate_index": str(record.get("plate_index") or ""),
            "subtask_name": str(record.get("subtask_name") or ""),
            "completed_at": str(record.get("completed_at") or ""),
        }

    def _render_template(self, template: str, context: dict[str, str]) -> str:
        class SafeDict(dict[str, str]):
            def __missing__(self, key: str) -> str:
                return ""

        return template.format_map(SafeDict(context)).strip()

    def _timelapse_cache_dir(self) -> Path:
        configured = str(self._configured_settings.get("file_cache_path") or "").strip()
        base = Path(configured) if configured else data_root() / "cache"
        return base / "timelapse"

    def _find_latest_timelapse_file(self, record: dict[str, Any]) -> Path | None:
        cache_dir = self._timelapse_cache_dir()
        if not cache_dir.exists():
            return None

        used_paths = {
            str(item.get("youtube", {}).get("path") or "")
            for item in self._successful_gcodes
            if isinstance(item, dict)
        }
        completed_at = str(record.get("completed_at") or "").strip()
        completed_ts = None
        if completed_at:
            try:
                dt = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                completed_ts = dt.timestamp()
            except ValueError:
                completed_ts = None

        candidates: list[tuple[float, Path]] = []
        for ext in ("*.mp4", "*.avi", "*.mov"):
            for path in cache_dir.glob(ext):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                path_str = str(path.resolve())
                if path_str in used_paths:
                    continue
                if completed_ts is not None and stat.st_mtime < (completed_ts - 3600):
                    continue
                candidates.append((stat.st_mtime, path))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _youtube_access_token(self, cfg: dict[str, Any]) -> str:
        response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "refresh_token": cfg["refresh_token"],
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        token = str(body.get("access_token") or "").strip()
        if not token:
            raise RuntimeError("YouTube OAuth token exchange returned no access_token.")
        return token

    def _youtube_upload_video(self, record: dict[str, Any], video_path: Path, cfg: dict[str, Any]) -> dict[str, Any]:
        if not video_path.exists():
            raise RuntimeError(f"Timelapse file does not exist: {video_path}")

        context = self._youtube_template_context(record)
        title = self._render_template(str(cfg["title_template"]), context) or (record.get("file_name") or "Print")
        description = self._render_template(str(cfg["description_template"]), context)
        mime_type = "video/mp4"
        suffix = video_path.suffix.lower()
        if suffix == ".avi":
            mime_type = "video/x-msvideo"
        elif suffix == ".mov":
            mime_type = "video/quicktime"

        access_token = self._youtube_access_token(cfg)
        metadata = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "categoryId": str(cfg["category_id"]),
                "tags": list(cfg["tags"]),
            },
            "status": {
                "privacyStatus": cfg["privacy_status"],
                "selfDeclaredMadeForKids": bool(cfg["made_for_kids"]),
                "embeddable": bool(cfg["embeddable"]),
                "license": str(cfg["license"]),
                "publicStatsViewable": bool(cfg["public_stats_viewable"]),
            },
        }
        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {access_token}"})
        init_response = session.post(
            "https://www.googleapis.com/upload/youtube/v3/videos",
            params={
                "part": "snippet,status",
                "uploadType": "resumable",
                "notifySubscribers": "true" if cfg["notify_subscribers"] else "false",
            },
            json=metadata,
            headers={
                "X-Upload-Content-Length": str(video_path.stat().st_size),
                "X-Upload-Content-Type": mime_type,
            },
            timeout=30,
        )
        init_response.raise_for_status()
        upload_url = str(init_response.headers.get("Location") or "").strip()
        if not upload_url:
            raise RuntimeError("YouTube resumable upload returned no session URL.")

        with video_path.open("rb") as handle:
            upload_response = session.put(
                upload_url,
                data=handle,
                headers={"Content-Type": mime_type},
                timeout=cfg["timeout_seconds"],
            )
        upload_response.raise_for_status()
        body = upload_response.json()
        video_id = str(body.get("id") or "").strip()
        if not video_id:
            raise RuntimeError("YouTube upload completed without a video id.")
        return {
            "video_id": video_id,
            "video_url": f"https://www.youtube.com/watch?v={video_id}",
            "status_code": upload_response.status_code,
            "title": title,
            "path": str(video_path.resolve()),
        }

    def _submitted_job_callback_payload(self, job: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": job.get("id"),
            "status": job.get("status"),
            "printer_id": self.printer_id,
            "printer_name": self.display_name,
            "queue_item_id": job.get("queue_item_id"),
            "successful_gcode_id": job.get("successful_gcode_id"),
            "idempotency_key": job.get("idempotency_key"),
            "source": "makerworks",
            "source_job_id": job.get("source_job_id"),
            "source_order_id": job.get("source_order_id"),
            "model_id": job.get("model_id"),
            "model_name": job.get("model_name"),
            "model_url": job.get("model_url"),
            "download_url": job.get("download_url"),
            "file_path": job.get("file_path"),
            "file_name": job.get("file_name"),
            "plate_gcode": job.get("plate_gcode"),
            "start_at": job.get("start_at"),
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
            "last_error": job.get("last_error"),
            "metadata": job.get("metadata") or {},
            "history": job.get("history") or [],
            "updated_at": job.get("updated_at"),
            "created_at": job.get("created_at"),
        }

    def _submitted_job_callback_headers(self, body_text: str, *, secret: str) -> dict[str, str]:
        timestamp = datetime.now(timezone.utc).isoformat()
        message = f"{timestamp}.{body_text}".encode("utf-8")
        signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        return {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "X-MakerWorks-Timestamp": timestamp,
            "X-MakerWorks-Signature": f"sha256={signature}",
        }

    async def _sync_submitted_job_to_makerworks(self, job: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        cfg = self._makerworks_job_callback_config()
        if not cfg["enabled"]:
            raise RuntimeError("MakerWorks job callbacks are disabled.")
        if not cfg["path_template"]:
            raise RuntimeError("MAKERWORKS_JOB_CALLBACK_PATH_TEMPLATE is not configured.")
        if not cfg["webhook_secret"]:
            raise RuntimeError("MAKERWORKS_WEBHOOK_SECRET is not configured.")
        if str(job.get("source") or "").lower() != "makerworks":
            raise RuntimeError("Only MakerWorks-origin jobs can be synced back to MakerWorks.")

        callback = job.setdefault("callback", {})
        current_status = str(job.get("status") or "").strip().lower()
        if callback.get("delivered_status") == current_status and not force:
            return job

        path = cfg["path_template"].format(
            job_id=quote(str(job.get("id") or ""), safe=""),
            printer_id=quote(self.printer_id, safe=""),
            model_id=quote(str(job.get("model_id") or ""), safe=""),
            source_job_id=quote(str(job.get("source_job_id") or ""), safe=""),
            source_order_id=quote(str(job.get("source_order_id") or ""), safe=""),
            status=quote(current_status, safe=""),
        )
        callback["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
        callback["path"] = path
        try:
            from app.runtime import works_service

            payload = self._submitted_job_callback_payload(job)
            body_text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
            headers = self._submitted_job_callback_headers(body_text, secret=cfg["webhook_secret"])
            result = await works_service.request(
                "makerworks",
                WorksRequest(method=cfg["method"], path=path, body=payload, body_text=body_text, headers=headers),
            )
            if not result.get("ok"):
                raise RuntimeError(f"MakerWorks returned HTTP {result.get('status_code')}.")
            callback.update(
                {
                    "delivered_status": current_status,
                    "last_delivered_at": datetime.now(timezone.utc).isoformat(),
                    "last_error": None,
                    "status_code": result.get("status_code"),
                }
            )
            self._save_submitted_jobs()
            self._record_timeline(
                "makerworks_job_callback_success",
                f"Synced job status {current_status} for {job.get('file_name') or job.get('model_name') or 'job'} to MakerWorks.",
                actor="system",
                details={"job_id": job.get("id"), "status": current_status, "path": path},
            )
            return job
        except Exception as exc:
            callback.update(
                {
                    "last_error": str(exc),
                }
            )
            self._save_submitted_jobs()
            self._record_timeline(
                "makerworks_job_callback_failed",
                f"Failed syncing job status {current_status} for {job.get('file_name') or job.get('model_name') or 'job'} to MakerWorks.",
                actor="system",
                severity="warning",
                details={"job_id": job.get("id"), "status": current_status, "error": str(exc), "path": path},
            )
            raise

    def _schedule_submitted_job_callback(self, job_id: str, *, force: bool = False) -> None:
        cfg = self._makerworks_job_callback_config()
        if not cfg["enabled"]:
            return
        try:
            job = self.submitted_job(job_id)
        except ValueError:
            return
        if str(job.get("source") or "").lower() != "makerworks":
            return

        async def _runner() -> None:
            try:
                await self._sync_submitted_job_to_makerworks(job, force=force)
            except Exception:
                return

        if self._main_loop and self._main_loop.is_running():
            try:
                running_loop = asyncio.get_running_loop()
                if running_loop is self._main_loop:
                    asyncio.create_task(_runner())
                    return
            except RuntimeError:
                pass
            self._main_loop.call_soon_threadsafe(lambda: asyncio.create_task(_runner()))

    async def _sync_successful_gcode_to_makerworks(self, record: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        cfg = self._makerworks_attach_config()
        if not cfg["enabled"]:
            raise RuntimeError("MakerWorks G-code attachment is disabled.")
        if not cfg["path_template"]:
            raise RuntimeError("MAKERWORKS_ATTACH_GCODE_PATH_TEMPLATE is not configured.")
        if not record.get("model_id"):
            raise RuntimeError("Record has no model_id to attach in MakerWorks.")
        if record.get("makerworks", {}).get("attached") and not force:
            return record

        path = cfg["path_template"].format(
            model_id=quote(str(record.get("model_id")), safe=""),
            printer_id=quote(self.printer_id, safe=""),
            record_id=quote(str(record.get("id")), safe=""),
        )
        payload = {
            "printer_id": self.printer_id,
            "printer_name": self.display_name,
            "record_id": record.get("id"),
            "model_id": record.get("model_id"),
            "model_name": record.get("model_name"),
            "model_key": record.get("model_key"),
            "file_path": record.get("file_path"),
            "file_name": record.get("file_name"),
            "plate_gcode": record.get("plate_gcode"),
            "plate_index": record.get("plate_index"),
            "subtask_name": record.get("subtask_name"),
            "completed_at": record.get("completed_at"),
            "use_ams": record.get("use_ams"),
            "ams_mapping": record.get("ams_mapping"),
        }

        record.setdefault("makerworks", {})
        record["makerworks"]["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
        record["makerworks"]["path"] = path
        try:
            from app.runtime import works_service

            result = await works_service.request(
                "makerworks",
                WorksRequest(method=cfg["method"], path=path, body=payload),
            )
            if not result.get("ok"):
                raise RuntimeError(f"MakerWorks returned HTTP {result.get('status_code')}.")
            record["makerworks"].update(
                {
                    "attached": True,
                    "attached_at": datetime.now(timezone.utc).isoformat(),
                    "last_error": None,
                    "status_code": result.get("status_code"),
                }
            )
            self._save_successful_gcodes()
            self._record_timeline(
                "makerworks_attach_success",
                f"Attached successful G-code for {record.get('file_name') or 'model'} to MakerWorks.",
                actor="system",
                details={"record_id": record.get("id"), "model_id": record.get("model_id"), "path": path},
            )
            return record
        except Exception as exc:
            record["makerworks"].update(
                {
                    "attached": False,
                    "last_error": str(exc),
                }
            )
            self._save_successful_gcodes()
            self._record_timeline(
                "makerworks_attach_failed",
                f"Failed to attach successful G-code for {record.get('file_name') or 'model'} to MakerWorks.",
                actor="system",
                severity="warning",
                details={"record_id": record.get("id"), "model_id": record.get("model_id"), "error": str(exc), "path": path},
            )
            raise

    async def sync_successful_gcode(self, record_id: str, *, force: bool = False) -> dict[str, Any]:
        for record in self._successful_gcodes:
            if record.get("id") == record_id:
                return await self._sync_successful_gcode_to_makerworks(record, force=force)
        raise ValueError(f"Unknown successful G-code record: {record_id}")

    async def _sync_successful_gcode_to_youtube(
        self,
        record: dict[str, Any],
        *,
        force: bool = False,
        video_path: Path | None = None,
    ) -> dict[str, Any]:
        cfg = self._youtube_upload_config()
        if not cfg["enabled"]:
            raise RuntimeError("YouTube uploads are disabled.")
        if not cfg["client_id"] or not cfg["client_secret"] or not cfg["refresh_token"]:
            raise RuntimeError("YouTube upload is not configured with OAuth credentials.")
        if record.get("youtube", {}).get("uploaded") and not force:
            return record

        youtube = record.setdefault("youtube", {})
        youtube["last_attempt_at"] = datetime.now(timezone.utc).isoformat()

        selected_path = video_path
        if selected_path is None:
            deadline = time.monotonic() + int(cfg["wait_seconds"])
            while True:
                selected_path = self._find_latest_timelapse_file(record)
                if selected_path is not None:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("No timelapse video became available before the YouTube upload timeout.")
                await asyncio.sleep(int(cfg["poll_interval_seconds"]))
        youtube["path"] = str(selected_path.resolve())
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None,
                self._youtube_upload_video,
                record,
                selected_path,
                cfg,
            )
            youtube.update(
                {
                    "uploaded": True,
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    "last_error": None,
                    "status_code": result["status_code"],
                    "video_id": result["video_id"],
                    "video_url": result["video_url"],
                    "title": result["title"],
                    "path": result["path"],
                }
            )
            self._save_successful_gcodes()
            self._record_timeline(
                "youtube_upload_success",
                f"Uploaded timelapse for {record.get('file_name') or 'model'} to YouTube.",
                actor="system",
                details={
                    "record_id": record.get("id"),
                    "video_id": result["video_id"],
                    "video_url": result["video_url"],
                    "path": result["path"],
                },
            )
            return record
        except Exception as exc:
            youtube.update(
                {
                    "uploaded": False,
                    "last_error": str(exc),
                }
            )
            self._save_successful_gcodes()
            self._record_timeline(
                "youtube_upload_failed",
                f"Failed to upload timelapse for {record.get('file_name') or 'model'} to YouTube.",
                actor="system",
                severity="warning",
                details={"record_id": record.get("id"), "error": str(exc), "path": youtube.get("path")},
            )
            raise

    def _schedule_youtube_upload(self, record_id: str, *, force: bool = False) -> None:
        cfg = self._youtube_upload_config()
        if not cfg["enabled"]:
            return
        record = next((item for item in self._successful_gcodes if item.get("id") == record_id), None)
        if record is None:
            return

        async def _runner() -> None:
            try:
                await self._sync_successful_gcode_to_youtube(record, force=force)
            except Exception:
                return

        if self._main_loop and self._main_loop.is_running():
            try:
                running_loop = asyncio.get_running_loop()
                if running_loop is self._main_loop:
                    asyncio.create_task(_runner())
                    return
            except RuntimeError:
                pass
            self._main_loop.call_soon_threadsafe(lambda: asyncio.create_task(_runner()))

    async def _record_successful_completion(self, snapshot: dict[str, Any]) -> None:
        completed_at = datetime.now(timezone.utc).isoformat()
        record = self._build_completion_record(snapshot, completed_at)
        completion_key = self._completion_key(record)
        if completion_key == self._last_completed_job_key:
            return
        self._last_completed_job_key = completion_key
        self._successful_gcodes = [record, *self._successful_gcodes[:499]]
        self._save_successful_gcodes()
        self._record_timeline(
            "print_success",
            f"Recorded successful G-code for {record.get('file_name') or 'model'}.",
            actor="system",
            details={"record_id": record.get("id"), "file_path": record.get("file_path"), "model_id": record.get("model_id")},
        )
        if self._makerworks_attach_config()["enabled"]:
            try:
                await self._sync_successful_gcode_to_makerworks(record)
            except Exception:
                pass
        self._schedule_youtube_upload(str(record.get("id") or ""))
        job_id = str((self._active_job_context or {}).get("job_id") or "").strip()
        if job_id:
            self.update_submitted_job(
                job_id,
                status="completed",
                message=f"Print completed for {record.get('file_name') or 'model'}.",
                details={"record_id": record.get("id"), "file_path": record.get("file_path")},
                extra={"completed_at": completed_at, "successful_gcode_id": record.get("id")},
            )

    async def _monitor_print_jobs(self) -> None:
        while True:
            try:
                await asyncio.sleep(10)
                if self.client is None or not self.client.connected:
                    continue
                await self.client.refresh()
                snapshot = self._job_snapshot()
                if snapshot is None:
                    continue
                state = str(snapshot.get("state") or "").upper()
                busy = bool(state) and not any(marker in state for marker in ("IDLE", "FINISH", "COMPLETE", "FAILED", "STOP"))
                previously_busy = bool(self._last_job_state) and not any(
                    marker in str(self._last_job_state or "").upper() for marker in ("IDLE", "FINISH", "COMPLETE", "FAILED", "STOP")
                )
                if busy:
                    context = self._active_job_context or {}
                    self._active_job_context = {
                        **context,
                        **{k: v for k, v in snapshot.items() if v not in (None, "")},
                    }
                elif ("FINISH" in state or "COMPLETE" in state) and previously_busy:
                    await self._record_successful_completion(snapshot)
                    self._active_job_context = None
                elif "FAILED" in state or "STOP" in state or "IDLE" in state:
                    context = self._active_job_context or {}
                    job_id = str(context.get("job_id") or "").strip()
                    if previously_busy and job_id:
                        failure_status = "cancelled" if "STOP" in state else "failed"
                        self.update_submitted_job(
                            job_id,
                            status=failure_status,
                            message=f"Print ended in state {state or 'unknown'} for {snapshot.get('file_name') or 'model'}.",
                            details={"state": state, "file_path": snapshot.get("file_path")},
                            extra={"completed_at": datetime.now(timezone.utc).isoformat()},
                        )
                    self._active_job_context = None
                self._last_job_state = state
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self.last_error = str(exc)
                self._record_timeline("job_monitor_error", f"Job monitor error: {exc}", severity="error", actor="system")

    def presets_snapshot(self) -> list[dict[str, Any]]:
        return list(self._control_presets)

    def alert_rules_snapshot(self) -> list[dict[str, Any]]:
        return list(self._alert_rules)

    def webhooks_snapshot(self) -> list[dict[str, Any]]:
        return list(self._webhooks)

    def save_webhook(self, request: WebhookSubscriptionRequest, actor: str = "dashboard") -> dict[str, Any]:
        url = str(request.url or "").strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            raise ValueError("Webhook URL must start with http:// or https://.")
        item = {
            "id": uuid4().hex,
            "url": url,
            "description": str(request.description or "").strip() or None,
            "events": [str(event).strip() for event in (request.events or []) if str(event).strip()],
            "secret": str(request.secret or "").strip() or None,
            "enabled": bool(request.enabled),
            "last_attempt_at": None,
            "last_delivered_at": None,
            "last_error": None,
            "status_code": None,
        }
        if not item["events"]:
            item["events"] = ["printer.state", "printer.timeline", "audit"]
        self._webhooks = [item, *self._webhooks[:99]]
        self._save_webhooks()
        self._record_timeline("webhook_saved", f"Saved webhook for {url}.", actor=actor, details={"webhook_id": item["id"], "url": url})
        return {"ok": True, "item": item, "items": self.webhooks_snapshot()}

    def update_webhook(self, webhook_id: str, request: WebhookSubscriptionUpdateRequest, actor: str = "dashboard") -> dict[str, Any]:
        for item in self._webhooks:
            if item.get("id") != webhook_id:
                continue
            if request.url is not None:
                url = str(request.url or "").strip()
                if not url.startswith("http://") and not url.startswith("https://"):
                    raise ValueError("Webhook URL must start with http:// or https://.")
                item["url"] = url
            if request.description is not None:
                item["description"] = str(request.description or "").strip() or None
            if request.events is not None:
                events = [str(event).strip() for event in request.events if str(event).strip()]
                item["events"] = events or ["printer.state", "printer.timeline", "audit"]
            if request.secret is not None:
                item["secret"] = str(request.secret or "").strip() or None
            if request.enabled is not None:
                item["enabled"] = bool(request.enabled)
            self._save_webhooks()
            self._record_timeline(
                "webhook_updated",
                f"Updated webhook for {item.get('url')}.",
                actor=actor,
                details={"webhook_id": item.get("id"), "url": item.get("url")},
            )
            return {"ok": True, "item": item, "items": self.webhooks_snapshot()}
        raise ValueError(f"Unknown webhook subscription: {webhook_id}")

    def remove_webhook(self, webhook_id: str, actor: str = "dashboard") -> dict[str, Any]:
        for index, item in enumerate(self._webhooks):
            if item.get("id") != webhook_id:
                continue
            removed = self._webhooks.pop(index)
            self._save_webhooks()
            self._record_timeline(
                "webhook_removed",
                f"Removed webhook for {removed.get('url')}.",
                actor=actor,
                severity="warning",
                details={"webhook_id": removed.get("id"), "url": removed.get("url")},
            )
            return {"ok": True, "removed": removed, "items": self.webhooks_snapshot()}
        raise ValueError(f"Unknown webhook subscription: {webhook_id}")

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
        self._broadcast_event(event, kind="printer.state")

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

    def _event_payload(self, event: str, *, kind: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "kind": kind,
            "event": event,
            "at": self.last_update_utc or datetime.now(timezone.utc).isoformat(),
            "printer_id": self.printer_id,
            "printer_name": self.display_name,
            "connected": bool(self.client and self.client.connected),
            "queue_count": len(self._queue_items),
            "details": details or {},
        }

    def _schedule_webhook_delivery(self, payload: dict[str, Any]) -> None:
        enabled_hooks = [item for item in self._webhooks if item.get("enabled", True)]
        if not enabled_hooks:
            return

        async def _runner() -> None:
            for hook in enabled_hooks:
                events = [str(item).strip() for item in hook.get("events") or [] if str(item).strip()]
                if events and payload.get("kind") not in events:
                    continue
                await asyncio.get_running_loop().run_in_executor(None, self._deliver_webhook_sync, hook, payload)

        if self._main_loop and self._main_loop.is_running():
            try:
                running_loop = asyncio.get_running_loop()
                if running_loop is self._main_loop:
                    asyncio.create_task(_runner())
                    return
            except RuntimeError:
                pass
            self._main_loop.call_soon_threadsafe(lambda: asyncio.create_task(_runner()))

    def _deliver_webhook_sync(self, hook: dict[str, Any], payload: dict[str, Any]) -> None:
        body_text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        headers = {"Content-Type": "application/json"}
        secret = str(hook.get("secret") or "").strip()
        timestamp = datetime.now(timezone.utc).isoformat()
        if secret:
            signature = hmac.new(secret.encode("utf-8"), f"{timestamp}.{body_text}".encode("utf-8"), hashlib.sha256).hexdigest()
            headers["X-PrintLab-Timestamp"] = timestamp
            headers["X-PrintLab-Signature"] = f"sha256={signature}"
        hook["last_attempt_at"] = timestamp
        try:
            response = requests.post(str(hook.get("url") or ""), data=body_text, headers=headers, timeout=8.0)
            hook["status_code"] = response.status_code
            if not response.ok:
                raise RuntimeError(f"Webhook returned HTTP {response.status_code}.")
            hook["last_delivered_at"] = datetime.now(timezone.utc).isoformat()
            hook["last_error"] = None
        except Exception as exc:
            hook["last_error"] = str(exc)
        finally:
            self._save_webhooks()

    def _broadcast_event(self, event: str, *, kind: str = "printer.state", details: dict[str, Any] | None = None) -> None:
        payload = self._event_payload(event, kind=kind, details=details)

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
        self._schedule_webhook_delivery(payload)

    def subscribe_events(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=40)
        self._event_subscribers.add(queue)
        queue.put_nowait(self._event_payload(self.last_event, kind="printer.state"))
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
            if self._job_monitor_task is None or self._job_monitor_task.done():
                self._job_monitor_task = asyncio.create_task(self._monitor_print_jobs())
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
        if self._job_monitor_task is not None:
            self._job_monitor_task.cancel()
            self._job_monitor_task = None
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

    def _resolve_sd_path_sync(self, ftp: Any, raw_path: str) -> str:
        path = str(raw_path or "").strip().replace("\\", "/")
        if not path:
            return path
        if path.startswith("/"):
            lowered = path.lower()
            if not (
                lowered.startswith("/data/metadata/")
                or lowered.startswith("/metadata/")
            ):
                return path

        target_name = Path(path).name.lower()
        current_subtask_name = ""
        try:
            if self.client is not None:
                current_subtask_name = str(getattr(self.client.get_device().print_job, "subtask_name", "") or "").strip()
        except Exception:
            current_subtask_name = ""

        dirs = ["/cache", "/"]
        pattern_time = re.compile(r"^\S+\s+\d+\s+\S+\s+\S+\s+(\d+)\s+(\S+\s+\d+\s+\d+:\d+)\s+(.+)$")
        pattern_year = re.compile(r"^\S+\s+\d+\s+\S+\s+\S+\s+(\d+)\s+(\S+\s+\d+\s+\d+)\s+(.+)$")

        def normalize_model_name(value: str) -> str:
            lowered = value.lower().strip()
            for suffix in (".gcode.3mf", ".3mf", ".gcode"):
                if lowered.endswith(suffix):
                    lowered = lowered[: -len(suffix)]
                    break
            lowered = lowered.replace("_", "-").replace(" ", "-")
            lowered = re.sub(r"-+", "-", lowered).strip("-")
            return lowered

        target_norm = normalize_model_name(target_name)
        subtask_norm = normalize_model_name(current_subtask_name)

        for base in dirs:
            try:
                matches: list[str] = []
                normalized_matches: list[str] = []

                def parse_line(line: str) -> None:
                    match = pattern_time.match(line) or pattern_year.match(line)
                    if not match:
                        return
                    _size_raw, _ts_raw, name = match.groups()
                    candidate = f"{base.rstrip('/')}/{name}" if base != "/" else f"/{name}"
                    lower_name = name.lower()
                    if lower_name == target_name:
                        matches.append(candidate)
                    normalized_name = normalize_model_name(name)
                    if target_norm and normalized_name == target_norm:
                        normalized_matches.append(candidate)
                    elif subtask_norm and normalized_name == subtask_norm:
                        normalized_matches.append(candidate)

                ftp.retrlines(f"LIST {base}", parse_line)
                if matches:
                    return matches[0]
                if normalized_matches:
                    return normalized_matches[0]
            except Exception:
                continue

        return f"/{Path(path).name}"

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
            cache_dir = data_root() / "cache" / "prints"
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
                            return f"{data_root().as_posix()}/cache/prints/{p.name}"

                # 2) Match by numeric ID prefix (e.g. "20906356-...").
                id_match = re.match(r"^(\d+)-", name)
                if id_match:
                    model_id = id_match.group(1)
                    for p in thumb_files:
                        if p.stem.startswith(f"{model_id}-"):
                            return f"{data_root().as_posix()}/cache/prints/{p.name}"

                # 3) Strict normalized stem equality as final safe fallback.
                model_norm = normalize_base(name)
                for p in thumb_files:
                    if normalize_base(p.stem) == model_norm:
                        return f"{data_root().as_posix()}/cache/prints/{p.name}"

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
                    **self._model_summary_for_path(path),
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

        thumb_dir = data_root() / "cache" / "sd_thumbs"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        raw_path = str(path or "").strip()
        raw_key = hashlib.sha1(raw_path.encode("utf-8")).hexdigest() if raw_path else None
        if raw_key and not self._is_alias_thumbnail_path(raw_path):
            for ext, mime in ((".png", "image/png"), (".jpg", "image/jpeg"), (".jpeg", "image/jpeg"), (".webp", "image/webp")):
                p = thumb_dir / f"{raw_key}{ext}"
                if p.exists():
                    return p.read_bytes(), mime

        ftp = self.client.ftp_connection()
        resolved_path = self._resolve_sd_path_sync(ftp, raw_path)
        preferred_plate = self._preferred_thumbnail_plate_index(raw_path, resolved_path)
        resolved_key = hashlib.sha1(resolved_path.encode("utf-8")).hexdigest() if resolved_path else raw_key
        if resolved_key:
            for ext, mime in ((".png", "image/png"), (".jpg", "image/jpeg"), (".jpeg", "image/jpeg"), (".webp", "image/webp")):
                p = thumb_dir / f"{resolved_key}{ext}"
                if p.exists():
                    return p.read_bytes(), mime
        model_name = Path(resolved_path).name
        base_dir = str(Path(resolved_path).parent).replace("\\", "/")
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
                    p = thumb_dir / f"{resolved_key}{ext}"
                    p.write_bytes(content)
                    return content, mime

            # 2) Try extracting from 3mf archive.
            if lower.endswith(".3mf"):
                blob = try_retr(resolved_path)
                if blob:
                    with ZipFile(io.BytesIO(blob)) as zf:
                        candidates = [n for n in zf.namelist() if re.match(r"^Metadata/plate_\d+\.png$", n)]
                        if preferred_plate:
                            preferred_name = f"Metadata/plate_{preferred_plate}.png"
                            if preferred_name in candidates:
                                candidates = [preferred_name]
                        if not candidates and "Metadata/plate_1.png" in zf.namelist():
                            candidates = ["Metadata/plate_1.png"]
                        if candidates:
                            candidates.sort()
                            image = zf.read(candidates[0])
                            p = thumb_dir / f"{resolved_key}.png"
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

    def _project_file_suffix(self, name: str) -> str | None:
        lowered = name.lower()
        for suffix in (".gcode.3mf", ".3mf", ".gcode"):
            if lowered.endswith(suffix):
                return suffix
        return None

    def _safe_project_file_name(self, preferred_name: str) -> str:
        raw = preferred_name.strip()
        suffix = self._project_file_suffix(raw)
        if suffix is None:
            raise ValueError("Only .3mf, .gcode.3mf, and .gcode files can be queued to a printer.")
        stem = raw[: -len(suffix)] if suffix else raw
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("._-") or "makerworks-model"
        stem = stem[:96]
        return f"{stem}{suffix}"

    def _stage_project_bytes_sync(self, content: bytes, preferred_name: str) -> dict[str, Any]:
        if self.client is None:
            raise RuntimeError("Client not initialized.")
        if not content:
            raise ValueError("Project file is empty.")

        remote_name = self._safe_project_file_name(preferred_name)
        remote_path = f"/cache/{remote_name}"
        ftp = self.client.ftp_connection()
        try:
            ftp.storbinary(f"STOR {remote_path}", io.BytesIO(content))
        finally:
            try:
                ftp.quit()
            except Exception:
                pass
        return {"file_name": remote_name, "file_path": remote_path, "size_bytes": len(content)}

    async def stage_project_bytes(self, content: bytes, preferred_name: str) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._stage_project_bytes_sync, content, preferred_name)

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
        self._active_job_context = self._job_context_from_request(request, actor)
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

    async def queue_print_job(
        self,
        request: QueuePrintJobRequest,
        actor: str = "dashboard",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        start_at = self._normalize_schedule(request.start_at)
        item = request.model_dump()
        if metadata:
            item.update(metadata)
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
            if item.get("job_id"):
                self.update_submitted_job(
                    str(item["job_id"]),
                    status="queued",
                    message=f"Queue schedule updated for {Path(str(item.get('file_path') or '')).name or 'model'}.",
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
            if item.get("job_id"):
                self.update_submitted_job(
                    str(item["job_id"]),
                    status="queued",
                    message=f"Queue order updated for {Path(str(item.get('file_path') or '')).name or 'model'}.",
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
            if removed.get("job_id"):
                self.update_submitted_job(
                    str(removed["job_id"]),
                    status="cancelled",
                    message=f"Queue entry removed for {Path(str(removed.get('file_path') or '')).name or 'model'}.",
                    details={"queue_item_id": item_id, "actor": actor},
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
                    if due_item.get("job_id"):
                        if self._active_job_context is None:
                            self._active_job_context = {}
                        self._active_job_context.update(
                            {
                                "job_id": due_item.get("job_id"),
                                "model_id": due_item.get("source_model_id"),
                                "model_name": due_item.get("display_name"),
                                "source_model_url": due_item.get("source_model_url"),
                                "source_download_url": due_item.get("source_download_url"),
                            }
                        )
                        self.update_submitted_job(
                            str(due_item["job_id"]),
                            status="started",
                            message=f"Printer started queued job for {Path(request.file_path).name}.",
                            details={"queue_item_id": due_item.get("id"), "file_path": request.file_path},
                            extra={"started_at": datetime.now(timezone.utc).isoformat()},
                        )
                    self._queue_items = [item for item in self._queue_items if item.get("id") != due_item.get("id")]
                    self._save_queue()
                    self._record_timeline(
                        "queue_submit",
                        f"Queued job started for {Path(request.file_path).name}.",
                        actor="scheduler",
                        details={"queue_item_id": due_item.get("id"), "file_path": request.file_path},
                    )
                else:
                    if due_item.get("job_id"):
                        self.update_submitted_job(
                            str(due_item["job_id"]),
                            status="submit_failed",
                            message=f"Printer rejected queued job for {Path(request.file_path).name}.",
                            details={"queue_item_id": due_item.get("id"), "file_path": request.file_path},
                        )
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

    def system_status_snapshot(self) -> dict[str, Any]:
        latest_callback = next((job.get("callback") for job in self._submitted_jobs if isinstance(job.get("callback"), dict)), {}) or {}
        latest_sync_error = None
        for record in self._successful_gcodes:
            makerworks = record.get("makerworks") or {}
            if makerworks.get("last_error"):
                latest_sync_error = str(makerworks.get("last_error"))
                break
        if latest_sync_error is None and latest_callback.get("last_error"):
            latest_sync_error = str(latest_callback.get("last_error"))
        enabled_webhooks = [item for item in self._webhooks if item.get("enabled", True)]
        latest_webhook = next((item for item in enabled_webhooks if item.get("last_attempt_at") or item.get("last_delivered_at")), None)
        return {
            "mqtt": {
                "configured": self.configured,
                "connected": bool(self.client and self.client.connected),
                "last_event": self.last_event,
                "last_update_utc": self.last_update_utc,
            },
            "callback": {
                "enabled": self._makerworks_job_callback_config()["enabled"],
                "last_delivered_at": latest_callback.get("last_delivered_at"),
                "last_attempt_at": latest_callback.get("last_attempt_at"),
                "last_error": latest_callback.get("last_error"),
                "status_code": latest_callback.get("status_code"),
            },
            "webhooks": {
                "enabled_count": len(enabled_webhooks),
                "last_delivered_at": (latest_webhook or {}).get("last_delivered_at"),
                "last_attempt_at": (latest_webhook or {}).get("last_attempt_at"),
                "last_error": (latest_webhook or {}).get("last_error"),
                "status_code": (latest_webhook or {}).get("status_code"),
            },
            "sync": {
                "last_error": latest_sync_error,
                "submitted_jobs": len(self._submitted_jobs),
                "successful_gcodes": len(self._successful_gcodes),
            },
            "youtube": self.youtube_connection_status(),
            "sse": {
                "subscriber_count": len(self._event_subscribers),
            },
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
                "successful_gcodes": self.successful_gcodes_snapshot()[:8],
                "control_presets": self.presets_snapshot(),
                "alert_rules": self.alert_rules_snapshot(),
                "webhooks": self.webhooks_snapshot(),
                "audit": self.audit_snapshot(limit=8),
                "system_status": self.system_status_snapshot(),
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
                        "thumbnail_url": self._job_thumbnail_url(job.gcode_file, job.subtask_name),
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
        root = data_root()
        self._names_file = root / "printer_names.json"
        self._added_printers_file = root / "printers_added.json"
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
                "is_added": service.printer_id in self._added_printers,
                "config": dict(service._configured_settings),
            }
            for service in self._services.values()
        ]

    def audit_snapshot(self, limit: int = 200, printer_id: str | None = None) -> list[dict[str, Any]]:
        if printer_id:
            return self.get(printer_id).audit_snapshot(limit=limit)
        items: list[dict[str, Any]] = []
        for service in self._services.values():
            items.extend(service.audit_snapshot(limit=limit))
        items.sort(key=lambda item: str(item.get("at") or ""), reverse=True)
        return items[: max(1, min(limit, 500))]

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

    async def update(self, printer_id: str, request: UpdatePrinterRequest) -> dict[str, str]:
        if printer_id not in self._added_printers:
            raise ValueError("Only printers added from this app can be edited.")

        existing = self.get(printer_id)
        config = {
            **build_default_printer_config(),
            "name": request.name.strip(),
            "host": request.host.strip(),
            "serial": request.serial.strip(),
            "access_code": request.access_code.strip(),
            "device_type": request.device_type.strip() or "unknown",
            "local_mqtt": request.local_mqtt,
            "enable_camera": request.enable_camera,
            "disable_ssl_verify": request.disable_ssl_verify,
        }
        entry = {"id": printer_id, "name": request.name.strip(), "config": config}

        await existing.stop()
        replacement = PrinterService(config=config, printer_id=printer_id, display_name=request.name.strip())
        self._services[printer_id] = replacement
        self._added_printers[printer_id] = entry
        self._name_overrides[printer_id] = request.name.strip()
        self._save_added_printers()
        self._save_name_overrides()
        await replacement.start()
        return {"id": replacement.printer_id, "name": replacement.display_name}

    async def remove(self, printer_id: str) -> dict[str, Any]:
        if printer_id not in self._added_printers:
            raise ValueError("Only printers added from this app can be deleted.")
        if len(self._services) <= 1:
            raise ValueError("At least one printer must remain configured.")

        service = self.get(printer_id)
        await service.stop()
        self._services.pop(printer_id, None)
        self._added_printers.pop(printer_id, None)
        self._name_overrides.pop(printer_id, None)
        if self._default_id == printer_id:
            self._default_id = next(iter(self._services), None)
        self._save_added_printers()
        self._save_name_overrides()
        return {"ok": True, "id": printer_id}

    async def start(self) -> None:
        for service in self._services.values():
            await service.start()

    async def stop(self) -> None:
        for service in self._services.values():
            await service.stop()


class MakerworksSubmitError(RuntimeError):
    def __init__(self, message: str, *, job: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.job = copy.deepcopy(job) if job is not None else None


class PrintJobManager:
    def __init__(self, printer_manager: MultiPrinterManager, works_service: WorksService) -> None:
        self._printer_manager = printer_manager
        self._works_service = works_service

    def _find_submitted_job_by_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        target = str(idempotency_key or "").strip()
        if not target:
            return None
        for entry in self._printer_manager.list_items():
            match = self._printer_manager.get(entry["id"]).find_submitted_job_by_idempotency(target)
            if match is not None:
                return copy.deepcopy(match)
        return None

    async def _resolve_printer(self, printer_id: str | None) -> PrinterService:
        if printer_id:
            service = self._printer_manager.get(printer_id)
            state = await service.state()
            if not state.get("connected"):
                raise ValueError(f"Printer {printer_id} is not connected.")
            return service

        candidates: list[tuple[bool, int, str, PrinterService]] = []
        for entry in self._printer_manager.list_items():
            service = self._printer_manager.get(entry["id"])
            state = await service.state()
            if not state.get("connected"):
                continue
            queue = state.get("queue") or {}
            candidates.append((service.job_busy(), int(queue.get("count") or 0), entry["id"], service))

        if not candidates:
            raise ValueError("No connected printers are available.")

        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        return candidates[0][3]

    def _build_preferred_name(self, source_item: dict[str, Any], payload: MakerworksSubmitJobRequest, asset: dict[str, Any]) -> str:
        preferred_base = re.sub(
            r"[^A-Za-z0-9._-]+",
            "-",
            f"makerworks-{source_item.get('id') or payload.model_id}-{source_item.get('name') or 'model'}",
        ).strip("._-")
        preferred_name = f"{preferred_base[:96]}{Path(str(asset.get('filename') or '')).suffix or '.3mf'}"
        if str(asset.get("filename") or "").lower().endswith(".gcode.3mf"):
            preferred_name = f"{preferred_base[:96]}.gcode.3mf"
        return preferred_name

    def _submit_failed_response(
        self,
        *,
        payload: MakerworksSubmitJobRequest,
        message: str,
        printer: PrinterService | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": job_id or uuid4().hex,
            "source": "makerworks",
            "status": "submit_failed",
            "printer_id": printer.printer_id if printer else payload.printer_id,
            "printer_name": printer.display_name if printer else None,
            "queue_item_id": None,
            "idempotency_key": payload.idempotency_key,
            "source_job_id": payload.source_job_id,
            "source_order_id": payload.source_order_id,
            "model_id": payload.model_id,
            "model_name": None,
            "model_url": None,
            "download_url": None,
            "file_type": None,
            "file_path": None,
            "file_name": None,
            "plate_gcode": payload.plate_gcode,
            "start_at": payload.start_at,
            "use_ams": payload.use_ams,
            "ams_mapping": payload.ams_mapping,
            "metadata": payload.metadata or {},
            "last_error": message,
            "created_at": now,
            "updated_at": now,
        }
        if printer is None:
            record["history"] = [{"id": uuid4().hex, "status": "submit_failed", "message": message, "at": now, "details": {}}]
            return record
        return printer.create_submitted_job(record, message=message)

    def _job_response(self, job: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(job)

    async def submit_makerworks_job(self, payload: MakerworksSubmitJobRequest, actor: str = "dashboard") -> dict[str, Any]:
        existing = self._find_submitted_job_by_idempotency(payload.idempotency_key)
        if existing is not None:
            return self._job_response(existing)

        job_id = uuid4().hex
        target_printer: PrinterService | None = None
        try:
            target_printer = await self._resolve_printer(payload.printer_id)
            detail = await self._works_service.makerworks_library_item(payload.model_id, include_raw=False)
            source_item = detail["item"]
            if not source_item.get("queue_supported"):
                raise ValueError(source_item.get("printer_handoff_note") or "This MakerWorks model cannot be queued yet.")

            asset = await self._works_service.download_asset("makerworks", str(source_item.get("download_url") or ""))
            preferred_name = self._build_preferred_name(source_item, payload, asset)
            staged = await target_printer.stage_project_bytes(bytes(asset["content"]), preferred_name)

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

            queue_result = await target_printer.queue_print_job(
                queue_request,
                actor=actor,
                metadata={
                    "job_id": job_id,
                    "display_name": source_item.get("name"),
                    "source": "makerworks",
                    "source_model_id": source_item.get("id"),
                    "source_model_url": source_item.get("model_url"),
                    "source_download_url": source_item.get("download_url"),
                    "source_file_type": source_item.get("file_type"),
                    "staged_file_name": staged.get("file_name"),
                },
            )
            queue_item = queue_result["item"]
            submitted_job = target_printer.create_submitted_job(
                {
                    "id": job_id,
                    "source": "makerworks",
                    "status": "queued",
                    "printer_id": target_printer.printer_id,
                    "printer_name": target_printer.display_name,
                    "queue_item_id": queue_item.get("id"),
                    "idempotency_key": payload.idempotency_key,
                    "source_job_id": payload.source_job_id,
                    "source_order_id": payload.source_order_id,
                    "model_id": source_item.get("id"),
                    "model_name": source_item.get("name"),
                    "model_url": source_item.get("model_url"),
                    "download_url": source_item.get("download_url"),
                    "file_type": source_item.get("file_type"),
                    "file_path": staged.get("file_path"),
                    "file_name": staged.get("file_name"),
                    "plate_gcode": payload.plate_gcode,
                    "start_at": queue_item.get("start_at"),
                    "use_ams": payload.use_ams,
                    "ams_mapping": payload.ams_mapping,
                    "actor": actor,
                    "metadata": payload.metadata or {},
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                message=f"Queued MakerWorks model {source_item.get('name') or payload.model_id}.",
            )
            target_printer._record_timeline(
                "job_accept",
                f"Accepted MakerWorks job for {source_item.get('name') or payload.model_id}.",
                actor=actor,
                details={"job_id": job_id, "queue_item_id": queue_item.get("id"), "model_id": source_item.get("id")},
            )
            return self._job_response(submitted_job)
        except Exception as exc:
            failed_job = self._submit_failed_response(payload=payload, message=str(exc), printer=target_printer, job_id=job_id)
            raise MakerworksSubmitError(str(exc), job=failed_job) from exc

    def list_jobs(self, *, printer_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        if printer_id:
            return self._printer_manager.get(printer_id).submitted_jobs_snapshot(status=status)

        items: list[dict[str, Any]] = []
        for entry in self._printer_manager.list_items():
            items.extend(self._printer_manager.get(entry["id"]).submitted_jobs_snapshot(status=status))
        items.sort(key=lambda item: str(item.get("created_at") or item.get("updated_at") or ""), reverse=True)
        return items

    def get_job(self, job_id: str, *, printer_id: str | None = None) -> dict[str, Any]:
        if printer_id:
            return self._printer_manager.get(printer_id).submitted_job_record(job_id)

        for entry in self._printer_manager.list_items():
            service = self._printer_manager.get(entry["id"])
            try:
                return service.submitted_job_record(job_id)
            except ValueError:
                continue
        raise ValueError(f"Unknown submitted job: {job_id}")

    async def sync_job_to_makerworks(self, job_id: str, *, printer_id: str | None = None, force: bool = False) -> dict[str, Any]:
        if printer_id:
            service = self._printer_manager.get(printer_id)
            job = service.submitted_job(job_id)
            return await service._sync_submitted_job_to_makerworks(job, force=force)

        for entry in self._printer_manager.list_items():
            service = self._printer_manager.get(entry["id"])
            try:
                job = service.submitted_job(job_id)
            except ValueError:
                continue
            return await service._sync_submitted_job_to_makerworks(job, force=force)
        raise ValueError(f"Unknown submitted job: {job_id}")


