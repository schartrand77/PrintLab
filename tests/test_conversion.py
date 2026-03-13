from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import base64

from app.conversion import (
    BatchModelConversionRequest,
    ModelConversionRequest,
    convert_model_batch,
    convert_model_bytes,
    convert_model_upload,
    infer_source_format,
    supported_conversion_formats,
)

trimesh = pytest.importorskip("trimesh")


def test_supported_conversion_formats_include_obj_target() -> None:
    formats = supported_conversion_formats()
    assert "obj" in formats["source_formats"]
    assert any(item["id"] == "obj" and item["recommended"] for item in formats["target_formats"])
    assert any(item["source"] == "3mf" and item["target"] == "stl" for item in formats["common_conversions"])
    assert any(item["id"] == "glb" and item["preserves_materials"] for item in formats["target_details"])
    assert any(item["id"] == "stl" and item["kind"] == "mesh" for item in formats["source_details"])


def test_convert_model_bytes_writes_obj_output_with_uvs(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path = Path("data/test-conversion")
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PRINTLAB_DATA_DIR", str(tmp_path.resolve()))
    mesh = trimesh.creation.box()
    stl_bytes = mesh.export(file_type="stl")

    try:
        result = convert_model_bytes("sample.stl", stl_bytes, "obj")

        assert result["source_format"] == "stl"
        assert result["target_format"] == "obj"
        assert result["uv_generated"] is True
        assert str(result["output_filename"]).endswith(".obj")
        assert str(result["download_url"]).startswith("/data/conversions/")

        saved = tmp_path / Path(str(result["download_url"]).removeprefix("/data/"))
        assert saved.exists()
        content = saved.read_text(encoding="utf-8")
        assert "\nv " in content
        assert "\nvt " in content
        assert any("/" in line and not "//" in line for line in content.splitlines() if line.startswith("f "))
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_convert_model_upload_worker_returns_obj_result(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path = Path("data/test-conversion-worker")
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PRINTLAB_DATA_DIR", str(tmp_path.resolve()))
    mesh = trimesh.creation.box()
    stl_bytes = mesh.export(file_type="stl")

    try:
        result = convert_model_upload(
            ModelConversionRequest(
                filename="worker.stl",
                content_base64=base64.b64encode(stl_bytes).decode("ascii"),
                target_format="obj",
            )
        )
        assert result["target_format"] == "obj"
        assert result["uv_generated"] is True
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_convert_model_bytes_supports_3mf_to_stl(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path = Path("data/test-conversion-3mf")
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PRINTLAB_DATA_DIR", str(tmp_path.resolve()))
    mesh = trimesh.creation.box()
    payload = mesh.export(file_type="3mf")

    try:
        result = convert_model_bytes("part.3mf", payload, "stl")
        assert result["source_format"] == "3mf"
        assert result["target_format"] == "stl"
        assert result["uv_generated"] is False
        assert result["scene_preserved"] is False
        assert result["warnings"]
        saved = tmp_path / Path(str(result["download_url"]).removeprefix("/data/"))
        assert saved.exists()
        assert saved.suffix == ".stl"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_infer_source_format_accepts_gcode_3mf() -> None:
    assert infer_source_format("widget.gcode.3mf") == "3mf"


def test_convert_model_batch_returns_mixed_results(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path = Path("data/test-conversion-batch")
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PRINTLAB_DATA_DIR", str(tmp_path.resolve()))
    mesh = trimesh.creation.box()
    stl_bytes = mesh.export(file_type="stl")

    try:
        result = convert_model_batch(
            BatchModelConversionRequest(
                items=[
                    ModelConversionRequest(
                        filename="ok.stl",
                        content_base64=base64.b64encode(stl_bytes).decode("ascii"),
                        target_format="obj",
                    ),
                    ModelConversionRequest(
                        filename="bad.unknown",
                        content_base64=base64.b64encode(b"bad").decode("ascii"),
                        target_format="obj",
                    ),
                ]
            ),
            use_worker=False,
        )
        assert result["count"] == 2
        assert result["items"][0]["ok"] is True
        assert result["items"][1]["ok"] is False
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
