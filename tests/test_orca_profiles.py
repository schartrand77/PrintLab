from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import create_app


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


def test_plus_printer_profiles_api_lists_existing_printers(monkeypatch, tmp_path: Path) -> None:
    import app.routers.api as api_routes
    from app.orca_profiles import OrcaProfileManager

    fake_printers = FakePrinterManager(
        [{"id": "printer-1", "name": "Shop X1C", "is_added": False, "config": {"device_type": "x1c"}}]
    )
    monkeypatch.setattr(api_routes, "printer_manager", fake_printers)
    monkeypatch.setattr(api_routes, "orca_profile_manager", OrcaProfileManager(root=tmp_path, printer_manager=fake_printers))
    monkeypatch.setattr(api_routes, "works_service", SimpleNamespace(list_services=lambda: []))

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
    monkeypatch.setattr(api_routes, "works_service", SimpleNamespace(list_services=lambda: []))

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
