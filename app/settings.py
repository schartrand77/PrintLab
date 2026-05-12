from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ALLOWED_SETTINGS: dict[str, set[str]] = {
    "makerworks": {
        "base_url",
        "api_key",
        "bearer_token",
        "admin_username",
        "admin_password",
        "allowed_paths",
        "allowed_methods",
        "job_callback_enabled",
        "job_callback_path_template",
        "submit_api_key",
    },
    "stockworks": {
        "base_url",
        "api_key",
        "bearer_token",
        "auth_header",
        "allowed_paths",
        "allowed_methods",
    },
    "youtube": {
        "upload_enabled",
        "client_id",
        "client_secret",
        "refresh_token",
        "privacy_status",
        "category_id",
        "title_template",
        "description_template",
        "tags",
        "made_for_kids",
    },
    "printer": {
        "conversion_max_upload_mb",
        "slicer_target",
        "slicer_protocol_template",
    },
}

SECRET_KEYS = {
    "api_key",
    "bearer_token",
    "admin_password",
    "client_secret",
    "refresh_token",
    "submit_api_key",
}


def runtime_config_path() -> Path:
    explicit = (os.getenv("PRINTLAB_RUNTIME_SETTINGS_PATH") or os.getenv("PRINTLAB_CONFIG_PATH") or "").strip()
    if explicit:
        return Path(explicit)
    data_dir = (os.getenv("PRINTLAB_DATA_DIR") or "").strip()
    if data_dir:
        return Path(data_dir) / "config.json"
    return Path("/data/config.json")


def mask_secret(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if len(raw) < 8:
        return "configured"
    return f"{raw[:6]}********{raw[-4:]}"


def merge_settings_payload(current: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(current or {}))
    for section, values in payload.items():
        if section not in ALLOWED_SETTINGS:
            raise ValueError(f"Unknown settings section: {section}")
        if not isinstance(values, dict):
            raise ValueError(f"Settings section {section} must be an object.")
        target = merged.setdefault(section, {})
        if not isinstance(target, dict):
            target = {}
            merged[section] = target
        for key, value in values.items():
            if key not in ALLOWED_SETTINGS[section]:
                raise ValueError(f"Unknown settings key: {section}.{key}")
            if value == "":
                continue
            target[key] = "" if value is None else value
    return merged


def redact_settings(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = json.loads(json.dumps(payload or {}))
    for values in redacted.values():
        if not isinstance(values, dict):
            continue
        for key, value in list(values.items()):
            if key in SECRET_KEYS:
                values[key] = {"configured": bool(value), "masked": mask_secret(str(value or ""))}
            elif not isinstance(value, dict):
                values[key] = {"configured": bool(value), "value": value}
    return redacted


def read_settings_file(path: Path | None = None) -> dict[str, Any]:
    resolved = path or runtime_config_path()
    if not resolved.exists():
        return {}
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Runtime settings file must contain a JSON object.")
    return payload


def write_settings_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
