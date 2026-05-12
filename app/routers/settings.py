from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.settings import merge_settings_payload, read_settings_file, redact_settings, runtime_config_path, write_settings_file

router = APIRouter()


def require_admin(request: Request) -> None:
    role = str(getattr(request.state, "auth_role", "") or "")
    permissions = set(getattr(request.state, "auth_permissions", []) or [])
    if role != "admin" and "auth:manage" not in permissions:
        raise HTTPException(status_code=403, detail="Admin access required.")


@router.get("/api/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    require_admin(request)
    return {"settings": redact_settings(read_settings_file())}


@router.patch("/api/settings")
async def patch_settings(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    require_admin(request)
    path = runtime_config_path()
    current = read_settings_file(path)
    merged = merge_settings_payload(current, payload)
    write_settings_file(path, merged)
    return {"ok": True, "settings": redact_settings(merged)}
