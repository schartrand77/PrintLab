from __future__ import annotations

from types import SimpleNamespace

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

    assert command[:4] == ["orca-cli", "slice", "--input", "/models/widget.3mf"]
    assert "--layer-height" in command
    assert "--infill" in command
    assert "--supports" in command
    assert "true" in command
    assert "--wall-count" in command
    assert "--infill-pattern" in command
    assert "--output-format" in command
    assert "gcode_3mf,slicedata" in command
    assert "--unknown-raw-flag" not in command


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
        output_path = command[command.index("--output") + 1]
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
