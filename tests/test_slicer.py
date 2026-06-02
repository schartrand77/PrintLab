from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_orca_adapter_prefers_configured_binary_and_reports_ready(tmp_path) -> None:
    from app.slicer import OrcaSlicerAdapter

    configured = tmp_path / "OrcaSlicer.exe"
    configured.write_text("", encoding="utf-8")

    adapter = OrcaSlicerAdapter(binary=str(configured))

    status = adapter.engine_status()

    assert status["engine"] == "orca"
    assert status["ready"] is True
    assert status["binary"] == str(configured)
    assert status["resolved_binary"] == str(configured)
    assert status["source"] == "configured"


def test_orca_adapter_reports_runtime_probe_failure(tmp_path) -> None:
    from app.slicer import OrcaSlicerAdapter

    configured = tmp_path / "orca-slicer"
    configured.write_text("", encoding="utf-8")

    def probe_runner(command: list[str]):
        assert command == [str(configured), "--help"]
        return SimpleNamespace(returncode=139, stdout="", stderr="Segmentation fault")

    status = OrcaSlicerAdapter(binary=str(configured), probe_runner=probe_runner).engine_status()

    assert status["ready"] is True
    assert status["runtime_ready"] is False
    assert status["probe_return_code"] == 139
    assert "Segmentation fault" in status["probe_error"]


def test_orca_adapter_reports_runtime_probe_success(tmp_path) -> None:
    from app.slicer import OrcaSlicerAdapter

    configured = tmp_path / "orca-slicer"
    configured.write_text("", encoding="utf-8")

    status = OrcaSlicerAdapter(
        binary=str(configured),
        probe_runner=lambda _command: SimpleNamespace(returncode=0, stdout="Usage: orca-slicer", stderr=""),
    ).engine_status()

    assert status["runtime_ready"] is True
    assert status["probe_return_code"] == 0


def test_orca_adapter_discovers_binary_from_common_install_paths(tmp_path) -> None:
    from app.slicer import OrcaSlicerAdapter

    discovered = tmp_path / "OrcaSlicer" / "OrcaSlicer.exe"
    discovered.parent.mkdir()
    discovered.write_text("", encoding="utf-8")

    adapter = OrcaSlicerAdapter(
        binary=None,
        env_getter=lambda _name, default="": default,
        path_finder=lambda _name: None,
        common_paths=[discovered],
    )

    assert adapter.binary == str(discovered)
    assert adapter.engine_status()["source"] == "common_path"


def test_orca_adapter_prefers_orca_slicer_command_on_path() -> None:
    from app.slicer import OrcaSlicerAdapter

    def path_finder(name: str) -> str | None:
        return "C:/Tools/orca-slicer.exe" if name == "orca-slicer" else None

    adapter = OrcaSlicerAdapter(binary=None, env_getter=lambda _name, default="": default, path_finder=path_finder, common_paths=[])

    assert adapter.binary == "C:/Tools/orca-slicer.exe"
    assert adapter.engine_status()["source"] == "path"


def test_slicer_capabilities_include_engine_readiness(tmp_path) -> None:
    from app.slicer import OrcaSlicerAdapter, SlicerService

    binary = tmp_path / "orca-cli"
    binary.write_text("", encoding="utf-8")
    service = SlicerService(root=tmp_path, adapter=OrcaSlicerAdapter(binary=str(binary)))

    capabilities = service.capabilities()

    assert capabilities["engine_status"]["ready"] is True
    assert capabilities["engine_status"]["resolved_binary"] == str(binary)
    assert "ORCASLICER_BINARY" in capabilities["engine_status"]["env_vars"]


def test_orca_adapter_maps_common_settings_and_outputs() -> None:
    from app.slicer import OrcaSlicerAdapter

    adapter = OrcaSlicerAdapter(binary="orca-cli")

    command = adapter.build_command(
        model_path="/models/widget.3mf",
        output_path="/gcode/widget.gcode.3mf",
        settings={
            "layer_height": 0.2,
            "infill": 15,
            "supports": True,
            "wall_count": 3,
            "infill_pattern": "gyroid",
            "unknown_raw_flag": "ignored",
        },
        outputs=["gcode_3mf", "slicedata"],
    )

    assert command[0] == "orca-cli"
    assert "--slice" in command
    assert command[command.index("--slice") + 1] == "0"
    assert "--export-3mf" in command
    assert command[command.index("--export-3mf") + 1] == "widget.gcode.3mf"
    assert "--outputdir" in command
    assert command[command.index("--outputdir") + 1].replace("\\", "/").endswith("/gcode")
    assert command[-1] == "/models/widget.3mf"
    assert "--layer-height" in command
    assert "--infill" in command
    assert "--supports" in command
    assert "true" in command
    assert "--wall-count" in command
    assert "--infill-pattern" in command
    assert "--output-format" not in command
    assert "gcode_3mf,slicedata" not in command
    assert "--unknown-raw-flag" not in command


def test_orca_adapter_expands_profile_and_material_presets_with_explicit_overrides() -> None:
    from app.slicer import OrcaSlicerAdapter

    adapter = OrcaSlicerAdapter(binary="orca-cli")

    command = adapter.build_command(
        model_path="/models/widget.3mf",
        output_path="/gcode/widget.gcode.3mf",
        settings={"profile": "draft", "material": "PLA", "layer_height": 0.2, "infill": 15},
        outputs=["gcode_3mf"],
    )

    assert command[command.index("--layer-height") + 1] == "0.2"
    assert command[command.index("--infill") + 1] == "15"
    assert command[command.index("--print-speed") + 1] == "140"
    assert command[command.index("--nozzle-temperature") + 1] == "220"
    assert command[command.index("--bed-temperature") + 1] == "60"
    assert "--profile" not in command
    assert "--material" not in command


def test_slicer_service_writes_manifest_and_artifact(tmp_path) -> None:
    from app.slicer import OrcaSlicerAdapter, SlicerService

    calls: list[list[str]] = []

    def runner(command: list[str]):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="sliced ok", stderr="")

    service = SlicerService(root=tmp_path, adapter=OrcaSlicerAdapter(binary="orca-cli", runner=runner))
    job = service.create_from_routing_job(
        {
            "id": "route-1",
            "source": "makerworks",
            "model_id": "model-1",
            "model_name": "Widget",
            "file_path": "/cache/widget.3mf",
            "download_url": "https://makerworks.local/widget.3mf",
            "plate_gcode": "Metadata/plate_1.gcode",
            "metadata": {"priority": "rush"},
        },
        settings={"layer_height": 0.2, "infill": 20},
        outputs=["gcode_3mf"],
    )

    sliced = service.slice_job(job["id"])

    assert calls
    assert sliced["status"] == "complete"
    assert sliced["source_job_id"] == "route-1"
    assert sliced["model_name"] == "Widget"
    assert sliced["settings"]["infill"] == 20
    assert [artifact["kind"] for artifact in sliced["artifacts"]] == ["command_manifest", "gcode_3mf"]
    assert sliced["artifacts"][0]["path"].endswith("command_manifest.json")
    assert sliced["artifacts"][1]["path"].endswith("output.gcode.3mf")
    assert "orca-cli" in sliced["command_manifest"]["command"]


def test_slicer_service_preserves_artifact_written_by_orca(tmp_path) -> None:
    from app.slicer import OrcaSlicerAdapter, SlicerService

    def runner(command: list[str]):
        output_path = f"{command[command.index('--outputdir') + 1]}/{command[command.index('--export-3mf') + 1]}"
        with open(output_path, "wb") as output_file:
            output_file.write(b"real-orca-gcode-3mf")
        return SimpleNamespace(returncode=0, stdout="orca finished", stderr="")

    service = SlicerService(root=tmp_path, adapter=OrcaSlicerAdapter(binary="orca-cli", runner=runner))
    job = service.create_from_routing_job({"id": "route-1", "file_path": "/cache/widget.3mf"})

    sliced = service.slice_job(job["id"])

    artifact_path = sliced["artifacts"][1]["path"]
    with open(artifact_path, "rb") as artifact_file:
        assert artifact_file.read() == b"real-orca-gcode-3mf"
    assert sliced["artifacts"][1]["size_bytes"] == len(b"real-orca-gcode-3mf")


def test_slicer_service_downloads_remote_model_before_invoking_orca(tmp_path) -> None:
    from app.slicer import OrcaSlicerAdapter, SlicerService

    calls: dict[str, object] = {}

    def downloader(url: str) -> dict[str, object]:
        calls["url"] = url
        return {"content": b"remote-3mf", "filename": "widget.3mf"}

    def runner(command: list[str]):
        model_path = command[-1]
        calls["model_path"] = model_path
        with open(model_path, "rb") as model_file:
            calls["model_bytes"] = model_file.read()
        return SimpleNamespace(returncode=0, stdout="sliced ok", stderr="")

    service = SlicerService(root=tmp_path, adapter=OrcaSlicerAdapter(binary="orca-cli", runner=runner), downloader=downloader)
    job = service.create_from_routing_job({"id": "route-1", "download_url": "https://makerworks.local/files/widget.3mf"})

    sliced = service.slice_job(job["id"])

    assert calls["url"] == "https://makerworks.local/files/widget.3mf"
    assert calls["model_bytes"] == b"remote-3mf"
    assert str(calls["model_path"]).endswith("input-widget.3mf")
    assert sliced["model_path"] == calls["model_path"]
    assert sliced["artifacts"][0]["kind"] == "input_model"
    assert sliced["artifacts"][1]["kind"] == "command_manifest"
    assert sliced["artifacts"][2]["kind"] == "gcode_3mf"


def test_slicer_service_returns_structured_missing_binary_failure(tmp_path) -> None:
    from app.slicer import OrcaSlicerAdapter, SlicerService

    def runner(_command: list[str]):
        raise FileNotFoundError("orcaslicer")

    service = SlicerService(root=tmp_path, adapter=OrcaSlicerAdapter(runner=runner))
    job = service.create_from_routing_job({"id": "route-1", "file_path": "/cache/widget.3mf"})

    sliced = service.slice_job(job["id"])

    assert sliced["status"] == "failed"
    assert sliced["error_code"] == "slicer_binary_missing"
    assert "orcaslicer" in sliced["error_message"]
    assert sliced["artifacts"][0]["kind"] == "command_manifest"


def test_slice_routing_job_api_uses_printlab_job_context(monkeypatch, tmp_path) -> None:
    import app.routers.api as api_routes
    from app.slicer import OrcaSlicerAdapter, SlicerService

    def runner(_command: list[str]):
        return SimpleNamespace(returncode=0, stdout="sliced ok", stderr="")

    monkeypatch.setattr(
        api_routes,
        "job_manager",
        SimpleNamespace(
            get_job=lambda job_id: {
                "id": job_id,
                "source": "makerworks",
                "model_id": "model-1",
                "model_name": "Widget",
                "file_path": "/cache/widget.3mf",
                "printer_id": "printer-1",
            }
        ),
    )
    monkeypatch.setattr(
        api_routes,
        "slicer_service",
        SlicerService(root=tmp_path, adapter=OrcaSlicerAdapter(binary="orca-cli", runner=runner)),
    )

    response = TestClient(create_app()).post(
        "/api/slicer/routing-jobs/route-1/slice",
        json={"settings": {"layer_height": 0.2, "infill": 15}, "outputs": ["gcode_3mf"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["item"]["status"] == "complete"
    assert body["item"]["source_job_id"] == "route-1"
    assert body["item"]["printer_id"] == "printer-1"
    assert body["item"]["artifacts"][1]["kind"] == "gcode_3mf"


def test_save_slicer_job_api_attaches_artifacts_to_routing_job(monkeypatch, tmp_path) -> None:
    import app.routers.api as api_routes
    from app.slicer import OrcaSlicerAdapter, SlicerService

    def runner(_command: list[str]):
        return SimpleNamespace(returncode=0, stdout="sliced ok", stderr="")

    attached: dict[str, object] = {}

    class FakeJobManager:
        def get_job(self, job_id: str) -> dict[str, object]:
            return {"id": job_id, "file_path": "/cache/widget.3mf", "model_name": "Widget"}

        def attach_slicer_job(self, slicer_job: dict[str, object]) -> dict[str, object]:
            attached.update(slicer_job)
            return {
                "id": slicer_job["source_job_id"],
                "slicer_job_id": slicer_job["id"],
                "slicer_status": slicer_job["status"],
                "slicer_artifacts": slicer_job["artifacts"],
            }

    service = SlicerService(root=tmp_path, adapter=OrcaSlicerAdapter(binary="orca-cli", runner=runner))
    slicer_job = service.create_from_routing_job({"id": "route-1", "file_path": "/cache/widget.3mf"})
    slicer_job = service.slice_job(slicer_job["id"])
    monkeypatch.setattr(api_routes, "job_manager", FakeJobManager())
    monkeypatch.setattr(api_routes, "slicer_service", service)

    response = TestClient(create_app()).post(f"/api/slicer/jobs/{slicer_job['id']}/save-routing")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["item"]["id"] == "route-1"
    assert body["item"]["slicer_job_id"] == slicer_job["id"]
    assert attached["source_job_id"] == "route-1"


def test_download_slicer_artifact_api_returns_recorded_output(monkeypatch, tmp_path) -> None:
    import app.routers.api as api_routes
    from app.slicer import OrcaSlicerAdapter, SlicerService

    def runner(command: list[str]):
        output_dir = command[command.index("--outputdir") + 1]
        output_name = command[command.index("--export-3mf") + 1]
        output_path = tmp_path / output_dir / output_name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"real-orca-gcode-3mf")
        return SimpleNamespace(returncode=0, stdout="sliced ok", stderr="")

    service = SlicerService(root=tmp_path, adapter=OrcaSlicerAdapter(binary="orca-cli", runner=runner))
    slicer_job = service.create_from_routing_job({"id": "route-1", "file_path": "/cache/widget.3mf"})
    slicer_job = service.slice_job(slicer_job["id"])
    monkeypatch.setattr(api_routes, "slicer_service", service)

    response = TestClient(create_app()).get(f"/api/slicer/jobs/{slicer_job['id']}/artifacts/gcode_3mf/download")

    assert response.status_code == 200
    assert response.content == b"real-orca-gcode-3mf"
    assert "output.gcode.3mf" in response.headers["content-disposition"]


def test_save_slicer_job_api_rejects_completed_job_without_output_artifact(monkeypatch, tmp_path) -> None:
    import app.routers.api as api_routes

    class FakeSlicerService:
        def get_job(self, job_id: str) -> dict[str, object]:
            return {
                "id": job_id,
                "source_job_id": "route-1",
                "status": "complete",
                "artifacts": [{"kind": "command_manifest", "path": str(tmp_path / "command_manifest.json")}],
            }

    class FakeJobManager:
        def attach_slicer_job(self, slicer_job: dict[str, object]) -> dict[str, object]:
            raise AssertionError("job should not be attached without a sliced output artifact")

    monkeypatch.setattr(api_routes, "job_manager", FakeJobManager())
    monkeypatch.setattr(api_routes, "slicer_service", FakeSlicerService())

    response = TestClient(create_app()).post("/api/slicer/jobs/slicer-job-1/save-routing")

    assert response.status_code == 400
    assert "output artifact" in response.text


def test_real_orca_binary_smoke_slices_sample_model(tmp_path) -> None:
    from app.slicer import OrcaSlicerAdapter, SlicerService

    binary = os.environ.get("ORCASLICER_BINARY") or os.environ.get("ORCA_SLICER_BINARY")
    if not binary:
        pytest.skip("Set ORCASLICER_BINARY or ORCA_SLICER_BINARY to run the real Orca smoke test.")
    binary_path = Path(binary)
    if not binary_path.exists():
        pytest.skip(f"Configured Orca binary does not exist: {binary_path}")

    sample = tmp_path / "sample.stl"
    sample.write_text(
        "\n".join(
            [
                "solid printlab",
                "facet normal 0 0 1",
                "  outer loop",
                "    vertex 0 0 0",
                "    vertex 20 0 0",
                "    vertex 0 20 0",
                "  endloop",
                "endfacet",
                "facet normal 0 0 1",
                "  outer loop",
                "    vertex 20 0 0",
                "    vertex 20 20 0",
                "    vertex 0 20 0",
                "  endloop",
                "endfacet",
                "endsolid printlab",
                "",
            ]
        ),
        encoding="utf-8",
    )

    service = SlicerService(root=tmp_path / "printlab-data", adapter=OrcaSlicerAdapter(binary=str(binary_path)))
    job = service.create_from_routing_job({"id": "orca-smoke", "file_path": str(sample), "model_name": "Smoke STL"})

    sliced = service.slice_job(job["id"])

    assert sliced["status"] == "complete", sliced.get("stderr") or sliced.get("error_message")
    output_artifact = next(item for item in sliced["artifacts"] if item["kind"] == "gcode_3mf")
    assert output_artifact["size_bytes"] > 0
