from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_CONFIG_CACHE: dict[str, Any] | None = None
_CONFIG_CACHE_SOURCE: str | None = None
_CONFIG_CACHE_MTIME_NS: int | None = None


def _candidate_config_paths() -> list[Path]:
    import os

    candidates: list[Path] = []
    explicit = os.getenv("PRINTLAB_CONFIG_PATH") or os.getenv("PRINTLAB_CONFIG_JSON")
    if explicit:
        candidates.append(Path(explicit.strip()))

    data_dir = os.getenv("PRINTLAB_DATA_DIR", "").strip()
    if data_dir:
        candidates.append(Path(data_dir) / "config.json")

    candidates.extend(
        [
            Path("/data/config.json"),
            Path("/config/config.json"),
            Path(__file__).resolve().parents[1] / "data" / "config.json",
        ]
    )
    return candidates


def _load_json_config() -> dict[str, Any]:
    global _CONFIG_CACHE, _CONFIG_CACHE_MTIME_NS, _CONFIG_CACHE_SOURCE

    for path in _candidate_config_paths():
        try:
            resolved = path.expanduser()
            if not resolved.exists():
                continue
            stat = resolved.stat()
            source = str(resolved.resolve())
            if (
                _CONFIG_CACHE is not None
                and _CONFIG_CACHE_SOURCE == source
                and _CONFIG_CACHE_MTIME_NS == stat.st_mtime_ns
            ):
                return _CONFIG_CACHE
            payload = json.loads(resolved.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError(f"Config file {resolved} must contain a JSON object.")
            _CONFIG_CACHE = payload
            _CONFIG_CACHE_SOURCE = source
            _CONFIG_CACHE_MTIME_NS = stat.st_mtime_ns
            return payload
        except OSError as exc:
            raise RuntimeError(f"Failed to read config.json from {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse config.json from {path}: {exc}") from exc

    _CONFIG_CACHE = {}
    _CONFIG_CACHE_SOURCE = None
    _CONFIG_CACHE_MTIME_NS = None
    return {}


def _config_value(name: str) -> Any:
    payload = _load_json_config()
    if not payload:
        return None

    if name in payload:
        return payload[name]
    lowered_name = name.lower()
    if lowered_name in payload:
        return payload[lowered_name]

    if "_" not in lowered_name:
        return None
    section, _, key = lowered_name.partition("_")
    section_payload = payload.get(section)
    if not isinstance(section_payload, dict):
        return None
    if key in section_payload:
        return section_payload[key]
    alt_key = key.replace("_", "-")
    if alt_key in section_payload:
        return section_payload[alt_key]
    return None


def _stringify_config_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return json.dumps(value)


def get_env(name: str, default: str = "") -> str:
    import os

    direct = os.getenv(name)
    if direct is not None:
        return direct.strip()

    file_path = os.getenv(f"{name}_FILE")
    if file_path is None:
        configured = _config_value(name)
        if configured is not None:
            return _stringify_config_value(configured)
        return default

    path = Path(file_path.strip())
    if not path:
        configured = _config_value(name)
        if configured is not None:
            return _stringify_config_value(configured)
        return default
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"Failed to read {name}_FILE from {path}: {exc}") from exc


def get_bool(name: str, default: bool) -> bool:
    raw = get_env(name, "")
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}
