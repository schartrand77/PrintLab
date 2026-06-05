# PrintLab Plus Printer Orca Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse existing PrintLab printers in PrintLab Plus and ask for Orca slicer profile data only when a printer has no confirmed Orca binding.

**Architecture:** Keep `MultiPrinterManager` as the printer connection source of truth. Add a small JSON-backed Orca profile binding service keyed by `printer_id`, expose Plus-specific API endpoints, and make printer-targeted slicer requests require a confirmed binding before invoking Orca. The slicer command manifest records the resolved machine, process, filament, nozzle, and AMS context.

**Tech Stack:** FastAPI, Pydantic, server-rendered HTML/JavaScript in `app/views.py`, pytest, Ruff, JSON persistence under `PRINTLAB_DATA_DIR`.

---

## File Structure

- Create `app/orca_profiles.py`: JSON-backed Orca profile binding store, device-type preset mapping, validation, and printer-list projection for PrintLab Plus.
- Modify `app/runtime.py`: instantiate `orca_profile_manager` beside the existing printer and job managers.
- Modify `app/routers/api.py`: add Plus printer/profile endpoints and pass the profile manager into `SlicerService`.
- Modify `app/slicer.py`: add optional `printer_id` to slice requests, add Orca profile validation, and include resolved profile data in slicer jobs and manifests.
- Modify `app/views.py`: add a compact slicer-profile prompt inside `/slicer` so operators can complete missing Orca setup from the slicer workflow.
- Add `tests/test_orca_profiles.py`: binding store and auto-discovery tests.
- Modify `tests/test_slicer.py`: setup-required and confirmed-profile slicer behavior.
- Modify `tests/test_models.py`: rendered `/slicer` profile prompt and JavaScript hooks.

---

## Task 1: Add Orca Profile Binding Store

**Files:**
- Create: `app/orca_profiles.py`
- Test: `tests/test_orca_profiles.py`

- [x] **Step 1: Write failing tests for auto-discovered pending profiles**

Create `tests/test_orca_profiles.py`:

```python
from __future__ import annotations

from pathlib import Path


class FakePrinterManager:
    def __init__(self, items: list[dict[str, object]]) -> None:
        self._items = items

    def list_items(self) -> list[dict[str, object]]:
        return self._items


def test_env_backed_printer_appears_as_pending_orca_profile(tmp_path: Path) -> None:
    from app.orca_profiles import OrcaProfileManager

    printers = FakePrinterManager(
        [
            {
                "id": "printer-1",
                "name": "Shop X1C",
                "is_added": False,
                "config": {"device_type": "x1c", "serial": "SERIAL123"},
            }
        ]
    )
    manager = OrcaProfileManager(root=tmp_path, printer_manager=printers)

    items = manager.list_plus_printers()

    assert items == [
        {
            "id": "printer-1",
            "name": "Shop X1C",
            "device_type": "x1c",
            "is_added": False,
            "orca_profile": {
                "printer_id": "printer-1",
                "orca_machine_preset": "Bambu Lab X1 Carbon 0.4 nozzle",
                "nozzle_diameter": 0.4,
                "ams_enabled": True,
                "filament_presets": [],
                "process_preset": "",
                "profile_confirmed_at": None,
                "profile_source": "device_type",
                "updated_at": None,
                "status": "needs_slicer_profile",
            },
        }
    ]


def test_in_app_added_printer_appears_as_pending_orca_profile(tmp_path: Path) -> None:
    from app.orca_profiles import OrcaProfileManager

    printers = FakePrinterManager(
        [
            {
                "id": "printer-2",
                "name": "Added P1S",
                "is_added": True,
                "config": {"device_type": "p1s", "serial": "SERIAL456"},
            }
        ]
    )
    manager = OrcaProfileManager(root=tmp_path, printer_manager=printers)

    item = manager.list_plus_printers()[0]

    assert item["id"] == "printer-2"
    assert item["is_added"] is True
    assert item["orca_profile"]["orca_machine_preset"] == "Bambu Lab P1S 0.4 nozzle"
    assert item["orca_profile"]["status"] == "needs_slicer_profile"


def test_confirmed_profile_persists_and_is_resolved(tmp_path: Path) -> None:
    from app.orca_profiles import OrcaProfileManager, OrcaProfileUpdateRequest

    printers = FakePrinterManager([{"id": "printer-1", "name": "Shop X1C", "config": {"device_type": "x1c"}}])
    manager = OrcaProfileManager(root=tmp_path, printer_manager=printers)

    profile = manager.update_profile(
        "printer-1",
        OrcaProfileUpdateRequest(
            orca_machine_preset="Bambu Lab X1 Carbon 0.4 nozzle",
            nozzle_diameter=0.4,
            ams_enabled=True,
            filament_presets=["Bambu PLA Basic @BBL X1C"],
            process_preset="0.20mm Standard @BBL X1C",
        ),
    )
    reloaded = OrcaProfileManager(root=tmp_path, printer_manager=printers)

    assert profile["status"] == "ready"
    assert profile["profile_source"] == "user"
    assert profile["profile_confirmed_at"]
    assert reloaded.require_confirmed_profile("printer-1")["process_preset"] == "0.20mm Standard @BBL X1C"


def test_removed_printer_binding_is_not_listed_as_active(tmp_path: Path) -> None:
    from app.orca_profiles import OrcaProfileManager, OrcaProfileUpdateRequest

    printers = FakePrinterManager([{"id": "printer-1", "name": "Shop X1C", "config": {"device_type": "x1c"}}])
    manager = OrcaProfileManager(root=tmp_path, printer_manager=printers)
    manager.update_profile(
        "printer-1",
        OrcaProfileUpdateRequest(
            orca_machine_preset="Bambu Lab X1 Carbon 0.4 nozzle",
            nozzle_diameter=0.4,
            ams_enabled=False,
            filament_presets=["Generic PLA"],
            process_preset="0.20mm Standard",
        ),
    )

    empty_manager = OrcaProfileManager(root=tmp_path, printer_manager=FakePrinterManager([]))

    assert empty_manager.list_plus_printers() == []
    assert empty_manager.profile_for("printer-1")["status"] == "stale_printer"
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_orca_profiles.py -q --basetemp C:\tmp\pytest-printlab-plus-profiles
```

Expected: fails with `ModuleNotFoundError: No module named 'app.orca_profiles'`.

- [x] **Step 3: Implement `app/orca_profiles.py`**

Create `app/orca_profiles.py`:

```python
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
```

- [x] **Step 4: Run profile tests**

Run:

```powershell
python -m pytest tests/test_orca_profiles.py -q --basetemp C:\tmp\pytest-printlab-plus-profiles
```

Expected: all tests pass.

- [x] **Step 5: Commit Task 1**

Run:

```powershell
git add app/orca_profiles.py tests/test_orca_profiles.py
git commit -m "add orca printer profile store"
```

Expected: commit succeeds with only these two files staged.

---

## Task 2: Expose PrintLab Plus Printer Profile API

**Files:**
- Modify: `app/runtime.py`
- Modify: `app/routers/api.py`
- Test: `tests/test_orca_profiles.py`

- [x] **Step 1: Add failing API tests**

Append to `tests/test_orca_profiles.py`:

```python
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import create_app


def test_plus_printer_profiles_api_lists_existing_printers(monkeypatch, tmp_path: Path) -> None:
    import app.routers.api as api_routes
    from app.orca_profiles import OrcaProfileManager

    fake_printers = FakePrinterManager(
        [{"id": "printer-1", "name": "Shop X1C", "is_added": False, "config": {"device_type": "x1c"}}]
    )
    monkeypatch.setattr(api_routes, "printer_manager", fake_printers)
    monkeypatch.setattr(api_routes, "orca_profile_manager", OrcaProfileManager(root=tmp_path, printer_manager=fake_printers))

    response = TestClient(create_app()).get("/api/plus/printers")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == "printer-1"
    assert body["items"][0]["orca_profile"]["status"] == "needs_slicer_profile"


def test_plus_printer_profile_api_confirms_profile(monkeypatch, tmp_path: Path) -> None:
    import app.routers.api as api_routes
    from app.orca_profiles import OrcaProfileManager

    fake_printers = FakePrinterManager([{"id": "printer-1", "name": "Shop X1C", "config": {"device_type": "x1c"}}])
    manager = OrcaProfileManager(root=tmp_path, printer_manager=fake_printers)
    monkeypatch.setattr(api_routes, "printer_manager", fake_printers)
    monkeypatch.setattr(api_routes, "orca_profile_manager", manager)

    response = TestClient(create_app()).patch(
        "/api/plus/printers/printer-1/orca-profile",
        json={
            "orca_machine_preset": "Bambu Lab X1 Carbon 0.4 nozzle",
            "nozzle_diameter": 0.4,
            "ams_enabled": True,
            "filament_presets": ["Bambu PLA Basic @BBL X1C"],
            "process_preset": "0.20mm Standard @BBL X1C",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["item"]["status"] == "ready"
    assert manager.require_confirmed_profile("printer-1")["filament_presets"] == ["Bambu PLA Basic @BBL X1C"]
```

- [x] **Step 2: Run API tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_orca_profiles.py::test_plus_printer_profiles_api_lists_existing_printers tests/test_orca_profiles.py::test_plus_printer_profile_api_confirms_profile -q --basetemp C:\tmp\pytest-printlab-plus-api
```

Expected: fails with missing `orca_profile_manager` or `404 Not Found`.

- [x] **Step 3: Instantiate the profile manager in runtime**

Modify `app/runtime.py`:

```python
from app.orca_profiles import OrcaProfileManager
from app.services import MultiPrinterManager, PrinterService, PrintJobManager, WorksService, data_root, load_printer_definitions

printer_manager = MultiPrinterManager(load_printer_definitions())
works_service = WorksService()
job_manager = PrintJobManager(printer_manager, works_service)
orca_profile_manager = OrcaProfileManager(root=data_root(), printer_manager=printer_manager)
```

- [x] **Step 4: Wire the API router imports and slicer service**

Modify the imports and global services near the top of `app/routers/api.py`:

```python
from app.orca_profiles import OrcaProfileUpdateRequest
from app.runtime import job_manager, orca_profile_manager, printer_manager, service_or_404, works_service
from app.slicer import SlicerService, SlicerSliceRequest

router = APIRouter()
slicer_service = SlicerService(root=data_root(), orca_profiles=orca_profile_manager)
```

- [x] **Step 5: Add Plus printer/profile endpoints**

Add these routes after `list_printers()` in `app/routers/api.py`:

```python
@router.get("/api/plus/printers")
async def list_plus_printers() -> dict[str, Any]:
    items = orca_profile_manager.list_plus_printers()
    return {"items": items, "count": len(items)}


@router.get("/api/plus/printers/{printer_id}/orca-profile")
async def plus_printer_orca_profile(printer_id: str) -> dict[str, Any]:
    try:
        return {"item": orca_profile_manager.profile_for(printer_id)}
    except Exception as exc:
        _raise_api_error(exc)


@router.patch("/api/plus/printers/{printer_id}/orca-profile")
async def update_plus_printer_orca_profile(
    printer_id: str,
    request: Request,
    payload: OrcaProfileUpdateRequest,
) -> dict[str, Any]:
    _require_operator(request)
    try:
        return {"ok": True, "item": orca_profile_manager.update_profile(printer_id, payload)}
    except Exception as exc:
        _raise_api_error(exc)
```

- [x] **Step 6: Run API tests**

Run:

```powershell
python -m pytest tests/test_orca_profiles.py -q --basetemp C:\tmp\pytest-printlab-plus-api
```

Expected: all profile and API tests pass.

- [x] **Step 7: Commit Task 2**

Run:

```powershell
git add app/runtime.py app/routers/api.py tests/test_orca_profiles.py
git commit -m "add printlab plus profile api"
```

Expected: commit succeeds with only these three files staged.

---

## Task 3: Require Confirmed Orca Profile For Printer-Targeted Slicing

**Files:**
- Modify: `app/slicer.py`
- Modify: `app/routers/api.py`
- Test: `tests/test_slicer.py`

- [x] **Step 1: Add failing slicer tests**

Append to `tests/test_slicer.py`:

```python
def test_slicer_service_rejects_printer_target_without_confirmed_orca_profile(tmp_path) -> None:
    from app.errors import ApiError
    from app.slicer import OrcaSlicerAdapter, SlicerService

    class FakeProfiles:
        def require_confirmed_profile(self, printer_id: str) -> dict[str, object]:
            raise ApiError(
                code="orca_profile_required",
                message="Printer needs an Orca slicer profile before slicing.",
                status_code=409,
                details={"printer_id": printer_id},
            )

    service = SlicerService(root=tmp_path, adapter=OrcaSlicerAdapter(binary="orca-cli"), orca_profiles=FakeProfiles())

    with pytest.raises(ApiError) as excinfo:
        service.create_from_routing_job({"id": "route-1", "file_path": "/cache/widget.3mf", "printer_id": "printer-1"})

    assert excinfo.value.code == "orca_profile_required"
    assert excinfo.value.status_code == 409


def test_slicer_service_manifest_includes_confirmed_orca_profile(tmp_path) -> None:
    from app.slicer import OrcaSlicerAdapter, SlicerService

    class FakeProfiles:
        def require_confirmed_profile(self, printer_id: str) -> dict[str, object]:
            return {
                "printer_id": printer_id,
                "orca_machine_preset": "Bambu Lab X1 Carbon 0.4 nozzle",
                "nozzle_diameter": 0.4,
                "ams_enabled": True,
                "filament_presets": ["Bambu PLA Basic @BBL X1C"],
                "process_preset": "0.20mm Standard @BBL X1C",
                "status": "ready",
            }

    def runner(_command: list[str]):
        return SimpleNamespace(returncode=0, stdout="sliced ok", stderr="")

    service = SlicerService(
        root=tmp_path,
        adapter=OrcaSlicerAdapter(binary="orca-cli", runner=runner),
        orca_profiles=FakeProfiles(),
    )
    job = service.create_from_routing_job(
        {"id": "route-1", "file_path": "/cache/widget.3mf", "printer_id": "printer-1"},
        settings={"layer_height": 0.2},
    )

    sliced = service.slice_job(job["id"])

    assert sliced["printer_id"] == "printer-1"
    assert sliced["orca_profile"]["process_preset"] == "0.20mm Standard @BBL X1C"
    assert sliced["command_manifest"]["orca_profile"]["filament_presets"] == ["Bambu PLA Basic @BBL X1C"]
```

- [x] **Step 2: Run slicer tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_slicer.py::test_slicer_service_rejects_printer_target_without_confirmed_orca_profile tests/test_slicer.py::test_slicer_service_manifest_includes_confirmed_orca_profile -q --basetemp C:\tmp\pytest-printlab-plus-slicer
```

Expected: fails because `SlicerService.__init__()` has no `orca_profiles` argument.

- [x] **Step 3: Extend `SlicerSliceRequest` and `SlicerService`**

Modify `app/slicer.py`:

```python
class SlicerSliceRequest(BaseModel):
    printer_id: str | None = Field(default=None, min_length=1, max_length=64)
    settings: dict[str, Any] = Field(default_factory=dict)
    outputs: list[str] = Field(default_factory=lambda: ["gcode_3mf"])
```

Change the service constructor:

```python
def __init__(
    self,
    *,
    root: Path,
    adapter: OrcaSlicerAdapter | None = None,
    downloader: Downloader | None = None,
    orca_profiles: Any | None = None,
) -> None:
    self.root = Path(root)
    self.jobs_root = self.root / "slicer" / "jobs"
    self.adapter = adapter or OrcaSlicerAdapter()
    self.downloader = downloader or self._download_url
    self.orca_profiles = orca_profiles
```

At the start of `create_from_routing_job()`, after `model_path` validation:

```python
printer_id = str((settings or {}).get("printer_id") or routing_job.get("printer_id") or "").strip()
orca_profile = None
if printer_id and self.orca_profiles is not None:
    orca_profile = self.orca_profiles.require_confirmed_profile(printer_id)
```

In the job dictionary, set:

```python
"printer_id": printer_id or routing_job.get("printer_id"),
"orca_profile": orca_profile,
```

In `_write_manifest()`, add:

```python
"printer_id": job.get("printer_id"),
"orca_profile": job.get("orca_profile"),
```

- [x] **Step 4: Pass request-selected printer id in the API**

Modify `slice_routing_job()` in `app/routers/api.py`:

```python
routing_job = dict(job_manager.get_job(job_id))
if payload.printer_id:
    routing_job["printer_id"] = payload.printer_id
slicer_job = slicer_service.create_from_routing_job(
    routing_job,
    settings=payload.settings,
    outputs=payload.outputs,
)
```

- [x] **Step 5: Add API setup-required test**

Append to `tests/test_slicer.py`:

```python
def test_slice_routing_job_api_returns_setup_required_for_missing_orca_profile(monkeypatch, tmp_path) -> None:
    import app.routers.api as api_routes
    from app.errors import ApiError
    from app.slicer import OrcaSlicerAdapter, SlicerService

    class FakeProfiles:
        def require_confirmed_profile(self, printer_id: str) -> dict[str, object]:
            raise ApiError(
                code="orca_profile_required",
                message="Printer needs an Orca slicer profile before slicing.",
                status_code=409,
                details={"printer_id": printer_id},
            )

    monkeypatch.setattr(
        api_routes,
        "job_manager",
        SimpleNamespace(get_job=lambda job_id: {"id": job_id, "file_path": "/cache/widget.3mf"}),
    )
    monkeypatch.setattr(
        api_routes,
        "slicer_service",
        SlicerService(root=tmp_path, adapter=OrcaSlicerAdapter(binary="orca-cli"), orca_profiles=FakeProfiles()),
    )

    response = TestClient(create_app()).post(
        "/api/slicer/routing-jobs/route-1/slice",
        json={"printer_id": "printer-1", "settings": {"layer_height": 0.2}, "outputs": ["gcode_3mf"]},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "orca_profile_required"
    assert response.json()["error"]["details"]["printer_id"] == "printer-1"
```

- [x] **Step 6: Run focused slicer tests**

Run:

```powershell
python -m pytest tests/test_slicer.py -q --basetemp C:\tmp\pytest-printlab-plus-slicer
```

Expected: all slicer tests pass.

- [x] **Step 7: Commit Task 3**

Run:

```powershell
git add app/slicer.py app/routers/api.py tests/test_slicer.py
git commit -m "require orca profile before printer slicing"
```

Expected: commit succeeds with only these three files staged.

---

## Task 4: Add Slicer Onboarding Prompt In The UI

**Files:**
- Modify: `app/views.py`
- Test: `tests/test_models.py`

- [x] **Step 1: Add failing render assertions**

Modify `tests/test_models.py::test_render_slicer_page_contains_printlab_workspace` to include:

```python
assert "orcaProfilePanel" in html
assert "/api/plus/printers" in html
assert "saveOrcaProfile" in html
assert "orcaMachinePresetInput" in html
assert "filamentPresetsInput" in html
assert "processPresetInput" in html
```

- [x] **Step 2: Run the render test to verify it fails**

Run:

```powershell
python -m pytest tests/test_models.py::test_render_slicer_page_contains_printlab_workspace -q --basetemp C:\tmp\pytest-printlab-plus-ui
```

Expected: fails on the first missing `orcaProfilePanel` assertion.

- [x] **Step 3: Add profile panel markup to `render_slicer_html()`**

In `app/views.py`, inside the `/slicer` workspace controls near the existing profile/material controls, add:

```html
<section id="orcaProfilePanel" class="panel muted">
  <h2>Printer Slicer Profile</h2>
  <p id="orcaProfileStatus">Select a printer to check Orca setup.</p>
  <label for="orcaPrinterSelect">Printer</label>
  <select id="orcaPrinterSelect" onchange="selectOrcaPrinter(this.value)"></select>
  <label for="orcaMachinePresetInput">Machine preset</label>
  <input id="orcaMachinePresetInput" type="text" autocomplete="off">
  <label for="nozzleDiameterInput">Nozzle diameter</label>
  <input id="nozzleDiameterInput" type="number" min="0.1" max="2" step="0.05" value="0.4">
  <label>
    <input id="amsEnabledInput" type="checkbox">
    AMS enabled
  </label>
  <label for="filamentPresetsInput">Filament presets</label>
  <input id="filamentPresetsInput" type="text" autocomplete="off" placeholder="Bambu PLA Basic @BBL X1C">
  <label for="processPresetInput">Process preset</label>
  <input id="processPresetInput" type="text" autocomplete="off" placeholder="0.20mm Standard @BBL X1C">
  <button class="btn secondary" type="button" onclick="saveOrcaProfile()">Save Slicer Profile</button>
</section>
```

- [x] **Step 4: Add profile panel JavaScript**

In the `/slicer` script block in `app/views.py`, add these functions:

```javascript
let plusPrinters = [];
let selectedPlusPrinter = null;

async function loadPlusPrinters() {
  const response = await fetch('/api/plus/printers');
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  plusPrinters = data.items || [];
  const select = document.getElementById('orcaPrinterSelect');
  if (!select) return;
  select.innerHTML = plusPrinters.map((printer) => `<option value="${escapeHtml(printer.id)}">${escapeHtml(printer.name)}</option>`).join('');
  if (plusPrinters[0]) selectOrcaPrinter(plusPrinters[0].id);
}

function selectOrcaPrinter(printerId) {
  selectedPlusPrinter = plusPrinters.find((printer) => printer.id === printerId) || null;
  const profile = selectedPlusPrinter?.orca_profile || {};
  document.getElementById('orcaMachinePresetInput').value = profile.orca_machine_preset || '';
  document.getElementById('nozzleDiameterInput').value = profile.nozzle_diameter || 0.4;
  document.getElementById('amsEnabledInput').checked = !!profile.ams_enabled;
  document.getElementById('filamentPresetsInput').value = (profile.filament_presets || []).join(', ');
  document.getElementById('processPresetInput').value = profile.process_preset || '';
  const status = profile.status === 'ready' ? 'Ready for Orca slicing.' : 'Needs slicer profile before printer-targeted slicing.';
  document.getElementById('orcaProfileStatus').textContent = status;
}

async function saveOrcaProfile() {
  if (!selectedPlusPrinter?.id) return;
  const payload = {
    orca_machine_preset: document.getElementById('orcaMachinePresetInput').value.trim(),
    nozzle_diameter: Number(document.getElementById('nozzleDiameterInput').value || 0.4),
    ams_enabled: document.getElementById('amsEnabledInput').checked,
    filament_presets: document.getElementById('filamentPresetsInput').value.split(',').map((item) => item.trim()).filter(Boolean),
    process_preset: document.getElementById('processPresetInput').value.trim(),
  };
  const response = await fetch(`/api/plus/printers/${encodeURIComponent(selectedPlusPrinter.id)}/orca-profile`, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  selectedPlusPrinter.orca_profile = data.item;
  selectOrcaPrinter(selectedPlusPrinter.id);
}
```

In the existing page initialization path, call:

```javascript
loadPlusPrinters().catch((error) => appendLog(`Printer profile load failed: ${error.message}`));
```

- [x] **Step 5: Include selected printer in slice payload**

In the existing slice request payload in `app/views.py`, add:

```javascript
printer_id: selectedPlusPrinter?.id || null,
```

- [x] **Step 6: Run focused UI tests**

Run:

```powershell
python -m pytest tests/test_models.py::test_render_slicer_page_contains_printlab_workspace -q --basetemp C:\tmp\pytest-printlab-plus-ui
```

Expected: test passes.

- [x] **Step 7: Commit Task 4**

Run:

```powershell
git add app/views.py tests/test_models.py
git commit -m "add orca profile prompt to slicer"
```

Expected: commit succeeds with only these two files staged.

---

## Task 5: Final Verification

**Files:**
- All files touched by Tasks 1-4.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
python -m pytest tests/test_orca_profiles.py tests/test_slicer.py tests/test_models.py -q --basetemp C:\tmp\pytest-printlab-plus-focused
```

Expected: all focused tests pass.

- [ ] **Step 2: Run Ruff on touched app/test files**

Run:

```powershell
python -m ruff check app/orca_profiles.py app/runtime.py app/routers/api.py app/slicer.py app/views.py tests/test_orca_profiles.py tests/test_slicer.py tests/test_models.py
```

Expected: `All checks passed!`

- [ ] **Step 3: Run the full test suite**

Run:

```powershell
python -m pytest -q --basetemp C:\tmp\pytest-printlab-plus-full
```

Expected: full suite passes, with any real Orca binary smoke test skipped unless `ORCASLICER_BINARY` or `ORCA_SLICER_BINARY` is configured.

- [ ] **Step 4: Inspect final diff**

Run:

```powershell
git status --short --branch
git diff --stat
```

Expected: branch is `dev`; uncommitted changes include only intentional work from this plan plus the pre-existing Orca/Docker edits if they were not committed separately.

---

## Self-Review

- Spec coverage: the plan covers auto-discovery from existing printers, pending profile state, user-confirmed bindings, API onboarding, slicer setup-required behavior, manifest profile context, stale removed-printer handling, and UI prompt entry points.
- Placeholder scan: no plan steps defer decisions or leave implementation details unspecified.
- Type consistency: the profile API uses `OrcaProfileUpdateRequest`; slicer code refers to `orca_profiles.require_confirmed_profile(printer_id)`; saved profile keys match the spec and tests.
