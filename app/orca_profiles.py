from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.errors import api_error


class PrinterRegistry(Protocol):
    def list_items(self) -> list[dict[str, Any]]:
        ...


class OrcaProfileUpdateRequest(BaseModel):
    orca_machine_preset: str = Field(min_length=1, max_length=160)
    nozzle_diameter: float = Field(ge=0.1, le=2.0)
    ams_enabled: bool = False
    filament_presets: list[str] = Field(min_length=1, max_length=16)
    process_preset: str = Field(min_length=1, max_length=160)


class OrcaProfileManager:
    device_type_machine_presets = {
        "x1c": "Bambu Lab X1 Carbon 0.4 nozzle",
        "x1": "Bambu Lab X1 0.4 nozzle",
        "x1e": "Bambu Lab X1E 0.4 nozzle",
        "p1s": "Bambu Lab P1S 0.4 nozzle",
        "p1p": "Bambu Lab P1P 0.4 nozzle",
        "a1": "Bambu Lab A1 0.4 nozzle",
        "a1 mini": "Bambu Lab A1 mini 0.4 nozzle",
        "a1mini": "Bambu Lab A1 mini 0.4 nozzle",
        "h2d": "Bambu Lab H2D 0.4 nozzle",
        "h2s": "Bambu Lab H2S 0.4 nozzle",
    }

    def __init__(self, *, root: Path, printer_manager: PrinterRegistry) -> None:
        self.root = Path(root)
        self.printer_manager = printer_manager
        self.path = self.root / "printlab-plus" / "orca-profiles.json"

    def list_plus_printers(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for printer in self._active_printers():
            printer_id = str(printer["id"])
            config = printer.get("config") if isinstance(printer.get("config"), dict) else {}
            device_type = str(config.get("device_type") or "unknown")
            items.append(
                {
                    "id": printer_id,
                    "name": str(printer.get("name") or printer_id),
                    "device_type": device_type,
                    "is_added": bool(printer.get("is_added")),
                    "orca_profile": self.profile_for(printer_id),
                }
            )
        return items

    def profile_for(self, printer_id: str) -> dict[str, Any]:
        printer_id = str(printer_id).strip()
        stored = self._load().get(printer_id)
        if isinstance(stored, dict):
            profile = self._normalize_profile(printer_id, stored)
            if not self._printer_exists(printer_id):
                profile["status"] = "stale_printer"
            return profile

        profile = self._default_profile(printer_id)
        if not self._printer_exists(printer_id):
            profile["status"] = "stale_printer"
        return profile

    def require_confirmed_profile(self, printer_id: str) -> dict[str, Any]:
        profile = self.profile_for(printer_id)
        if profile.get("status") != "ready":
            raise api_error(
                "orca_profile_required",
                "Printer needs an Orca slicer profile before slicing.",
                409,
                printer_id=printer_id,
                profile=profile,
            )
        return profile

    def update_profile(self, printer_id: str, request: OrcaProfileUpdateRequest) -> dict[str, Any]:
        printer_id = str(printer_id).strip()
        if not self._printer_exists(printer_id):
            raise api_error("printer_not_found", f"Unknown printer: {printer_id}", 404)
        now = _utc_now()
        profile = {
            "printer_id": printer_id,
            "orca_machine_preset": request.orca_machine_preset,
            "nozzle_diameter": request.nozzle_diameter,
            "ams_enabled": request.ams_enabled,
            "filament_presets": list(request.filament_presets),
            "process_preset": request.process_preset,
            "profile_confirmed_at": now,
            "profile_source": "user",
            "updated_at": now,
            "status": "ready",
        }
        data = self._load()
        data[printer_id] = profile
        self._save(data)
        return profile

    def _default_profile(self, printer_id: str) -> dict[str, Any]:
        printer = self._printer_by_id(printer_id) or {}
        config = printer.get("config") if isinstance(printer.get("config"), dict) else {}
        device_type = str(config.get("device_type") or "").strip().lower()
        machine_preset = self.device_type_machine_presets.get(device_type, "")
        return {
            "printer_id": printer_id,
            "orca_machine_preset": machine_preset,
            "nozzle_diameter": 0.4 if machine_preset else None,
            "ams_enabled": self._default_ams_enabled(device_type),
            "filament_presets": [],
            "process_preset": "",
            "profile_confirmed_at": None,
            "profile_source": "device_type" if machine_preset else "none",
            "updated_at": None,
            "status": "needs_slicer_profile",
        }

    def _normalize_profile(self, printer_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        normalized = self._default_profile(printer_id)
        normalized.update({key: profile.get(key) for key in normalized if key in profile})
        ready = bool(
            normalized.get("profile_confirmed_at")
            and normalized.get("orca_machine_preset")
            and normalized.get("nozzle_diameter")
            and normalized.get("filament_presets")
            and normalized.get("process_preset")
        )
        normalized["status"] = "ready" if ready else "needs_slicer_profile"
        return normalized

    def _active_printers(self) -> list[dict[str, Any]]:
        return [item for item in self.printer_manager.list_items() if isinstance(item, dict) and str(item.get("id") or "").strip()]

    def _printer_by_id(self, printer_id: str) -> dict[str, Any] | None:
        for printer in self._active_printers():
            if str(printer.get("id") or "") == printer_id:
                return printer
        return None

    def _printer_exists(self, printer_id: str) -> bool:
        return self._printer_by_id(printer_id) is not None

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        profiles = payload.get("profiles", payload)
        if not isinstance(profiles, dict):
            return {}
        return {str(key): value for key, value in profiles.items() if isinstance(value, dict)}

    def _save(self, profiles: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"profiles": profiles}, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _default_ams_enabled(device_type: str) -> bool:
        return device_type not in {"a1 mini", "a1mini"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
