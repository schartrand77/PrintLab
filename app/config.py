from __future__ import annotations

from pathlib import Path


def get_env(name: str, default: str = "") -> str:
    import os

    direct = os.getenv(name)
    if direct is not None:
        return direct.strip()

    file_path = os.getenv(f"{name}_FILE")
    if file_path is None:
        return default

    path = Path(file_path.strip())
    if not path:
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
