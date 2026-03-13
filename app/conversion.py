from __future__ import annotations

import base64
import binascii
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from app.services import data_root

try:
    import trimesh
except ImportError:  # pragma: no cover - depends on local environment
    trimesh = None  # type: ignore[assignment]

try:
    import xatlas  # noqa: F401
except ImportError:  # pragma: no cover - depends on local environment
    xatlas = None  # type: ignore[assignment]

try:
    import fast_simplification  # noqa: F401
except ImportError:  # pragma: no cover - depends on local environment
    fast_simplification = None  # type: ignore[assignment]


_SOURCE_CANDIDATES = ("3mf", "dae", "dxf", "glb", "gltf", "obj", "off", "ply", "stl", "xaml", "xyz")
_TARGET_FORMATS = ("obj", "stl", "ply", "off", "glb", "3mf", "dae")
_TARGET_LABELS = {
    "obj": "OBJ",
    "stl": "STL",
    "ply": "PLY",
    "off": "OFF",
    "glb": "GLB",
    "3mf": "3MF",
    "dae": "DAE",
}
_MIME_TYPES = {
    "obj": "text/plain; charset=utf-8",
    "stl": "model/stl",
    "ply": "application/octet-stream",
    "off": "text/plain; charset=utf-8",
    "glb": "model/gltf-binary",
    "3mf": "model/3mf",
    "dae": "model/vnd.collada+xml",
}
_UV_SIMPLIFY_THRESHOLD = 40000
_UV_SIMPLIFY_TARGET = 20000
_WORKER_TIMEOUT_SECONDS = 90
_SCENE_PRESERVING_TARGETS = {"glb", "dae"}
_SCENE_LIKE_SOURCES = {"glb", "gltf", "dae", "3mf", "xaml"}
_GEOMETRY_ONLY_TARGETS = {"obj", "stl", "ply", "off", "3mf"}


class ModelConversionRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)
    target_format: str = Field(min_length=2, max_length=16)
    source_format: str | None = Field(default=None, min_length=2, max_length=16)


class BatchModelConversionRequest(BaseModel):
    items: list[ModelConversionRequest] = Field(min_length=1, max_length=25)


def _require_engine() -> None:
    if trimesh is None:
        raise RuntimeError("Model conversion is unavailable because trimesh is not installed.")


def _normalize_format(value: str | None) -> str:
    cleaned = str(value or "").strip().lower().lstrip(".")
    if cleaned == "stl_ascii":
        return "stl"
    return cleaned


def _available_source_formats() -> list[str]:
    _require_engine()
    available = {str(item).lower() for item in trimesh.available_formats()}
    return [item for item in _SOURCE_CANDIDATES if item in available]


def _available_target_formats() -> list[str]:
    _require_engine()
    try:
        from trimesh.exchange.export import _mesh_exporters
    except Exception as exc:  # pragma: no cover - internal trimesh import failure is environment-specific
        raise RuntimeError("Model conversion exporters are unavailable.") from exc

    available = {str(item).lower() for item in _mesh_exporters.keys()}
    return [item for item in _TARGET_FORMATS if item in available]


def supported_conversion_formats() -> dict[str, object]:
    source_formats = _available_source_formats()
    target_formats = _available_target_formats()
    source_details = [
        {
            "id": item,
            "label": _TARGET_LABELS.get(item, item.upper()),
            "kind": "scene" if item in _SCENE_LIKE_SOURCES else "mesh",
            "notes": (
                "Can include scene hierarchy, materials, or textures."
                if item in _SCENE_LIKE_SOURCES
                else "Geometry-focused mesh input."
            ),
        }
        for item in source_formats
    ]
    target_details = [
        {
            "id": item,
            "label": _TARGET_LABELS.get(item, item.upper()),
            "recommended": item == "obj",
            "description": "Recommended OBJ mesh export." if item == "obj" else "Mesh export format.",
            "preserves_scene": item in _SCENE_PRESERVING_TARGETS,
            "preserves_materials": item in _SCENE_PRESERVING_TARGETS,
            "preserves_textures": item in _SCENE_PRESERVING_TARGETS,
            "generates_uvs": item == "obj",
            "warnings": (
                ["Materials and textures are flattened or discarded for this target."]
                if item in _GEOMETRY_ONLY_TARGETS
                else []
            ),
        }
        for item in target_formats
    ]
    return {
        "source_formats": source_formats,
        "source_details": source_details,
        "target_formats": target_details,
        "target_details": target_details,
        "recommended_target": "obj" if "obj" in target_formats else (target_formats[0] if target_formats else None),
        "common_conversions": [
            {"source": "stl", "target": "obj", "label": "STL to OBJ", "note": "Generates UVs automatically for OBJ export when needed."},
            {"source": "3mf", "target": "stl", "label": "3MF to STL", "note": "Useful for slicer and print workflows."},
            {"source": "stl", "target": "3mf", "label": "STL to 3MF", "note": "Preserves a packaged mesh container."},
            {"source": "obj", "target": "stl", "label": "OBJ to STL", "note": "Useful for printer-facing mesh export."},
            {"source": "glb", "target": "obj", "label": "GLB to OBJ", "note": "Converts textured scene meshes into OBJ geometry."},
            {"source": "ply", "target": "obj", "label": "PLY to OBJ", "note": "Good for scan and mesh cleanup workflows."},
        ],
    }


def infer_source_format(filename: str, source_format: str | None = None) -> str:
    source_formats = set(_available_source_formats())
    requested = _normalize_format(source_format)
    if requested:
        if requested not in source_formats:
            raise ValueError(f"Unsupported source format: {requested}")
        return requested

    lowered_name = str(filename or "").lower()
    if lowered_name.endswith(".gcode.3mf") and "3mf" in source_formats:
        return "3mf"

    suffix = Path(lowered_name).suffix.lower().lstrip(".")
    if suffix in source_formats:
        return suffix
    raise ValueError("Could not determine the source format from the file name.")


def _safe_stem(filename: str) -> str:
    stem = Path(filename).stem or "model"
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("._-")
    return cleaned[:80] or "model"


def _decode_base64(content_base64: str) -> bytes:
    try:
        return base64.b64decode(content_base64.encode("ascii"), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Uploaded file content is not valid base64.") from exc


def _export_payload_to_bytes(payload: object) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    if isinstance(payload, dict):
        return json.dumps(payload, indent=2).encode("utf-8")
    raise ValueError("Converted model exporter returned an unsupported payload.")


def _has_uvs(mesh: object) -> bool:
    visual = getattr(mesh, "visual", None)
    uv = getattr(visual, "uv", None)
    try:
        return uv is not None and len(uv) > 0
    except Exception:
        return False


def _mesh_from_loaded(loaded: object) -> object:
    if isinstance(loaded, trimesh.Trimesh):
        return loaded
    if isinstance(loaded, trimesh.Scene):
        if not loaded.geometry:
            raise ValueError("Source scene does not contain any mesh geometry.")
        combined = loaded.to_mesh()
        if combined is None or combined.is_empty:
            raise ValueError("Failed to combine scene geometry into a mesh.")
        return combined
    raise ValueError("Unsupported model type returned by the loader.")


def _loaded_kind(loaded: object) -> str:
    if isinstance(loaded, trimesh.Scene):
        return "scene"
    if isinstance(loaded, trimesh.Trimesh):
        return "mesh"
    return "unknown"


def _result_warnings(*, source_format: str, target_format: str, source_kind: str, scene_preserved: bool) -> list[str]:
    warnings: list[str] = []
    if source_kind == "scene" and not scene_preserved:
        warnings.append("Scene hierarchy was flattened into mesh geometry for this export.")
    if target_format in _GEOMETRY_ONLY_TARGETS and source_format in _SCENE_LIKE_SOURCES:
        warnings.append("Materials and textures were not preserved for this target format.")
    if target_format == "obj":
        warnings.append("OBJ export is written for geometry compatibility; embedded textures are not included.")
    return warnings


def _ensure_obj_uvs(mesh: object) -> tuple[object, bool]:
    if _has_uvs(mesh):
        return mesh, False
    if xatlas is None:
        raise RuntimeError("OBJ export requires UV generation, but xatlas is not installed.")
    try:
        return mesh.unwrap(), True
    except Exception as exc:
        raise RuntimeError("Failed to generate UVs for OBJ export.") from exc


def _simplify_for_uvs(mesh: object) -> tuple[object, bool]:
    face_count = len(getattr(mesh, "faces", []))
    if face_count <= _UV_SIMPLIFY_THRESHOLD:
        return mesh, False
    if fast_simplification is None:
        return mesh, False
    try:
        simplified = mesh.simplify_quadric_decimation(face_count=_UV_SIMPLIFY_TARGET)
        if simplified is None or simplified.is_empty:
            return mesh, False
        return simplified, True
    except Exception:
        return mesh, False


def convert_model_bytes(filename: str, content: bytes, target_format: str, source_format: str | None = None) -> dict[str, object]:
    _require_engine()
    if not content:
        raise ValueError("Uploaded file is empty.")
    if len(content) > 40 * 1024 * 1024:
        raise ValueError("Uploaded file exceeds the 40 MB limit.")

    resolved_source = infer_source_format(filename, source_format)
    resolved_target = _normalize_format(target_format)
    allowed_targets = set(_available_target_formats())
    if resolved_target not in allowed_targets:
        raise ValueError(f"Unsupported target format: {resolved_target}")

    loaded = trimesh.load(io.BytesIO(content), file_type=resolved_source, force="scene")
    if loaded is None:
        raise ValueError("Failed to parse the source model.")
    source_kind = _loaded_kind(loaded)

    uv_generated = False
    simplified_for_uv = False
    scene_preserved = False
    export_source = loaded
    if resolved_target == "obj":
        export_source = _mesh_from_loaded(export_source)
        export_source, simplified_for_uv = _simplify_for_uvs(export_source)
        export_source, uv_generated = _ensure_obj_uvs(export_source)
    elif resolved_target in _SCENE_PRESERVING_TARGETS and source_kind == "scene":
        scene_preserved = True
    else:
        export_source = _mesh_from_loaded(export_source)

    export_payload = export_source.export(file_type=resolved_target)
    output_bytes = _export_payload_to_bytes(export_payload)
    if not output_bytes:
        raise ValueError("Converted model output was empty.")

    output_name = f"{_safe_stem(filename)}.{resolved_target}"
    relative_path = Path("conversions") / f"{uuid4().hex}-{output_name}"
    absolute_path = data_root() / relative_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_bytes(output_bytes)

    return {
        "source_format": resolved_source,
        "target_format": resolved_target,
        "output_filename": output_name,
        "output_size": len(output_bytes),
        "download_url": f"/data/{relative_path.as_posix()}",
        "mime_type": _MIME_TYPES.get(resolved_target, "application/octet-stream"),
        "uv_generated": uv_generated,
        "simplified_for_uv": simplified_for_uv,
        "source_kind": source_kind,
        "scene_preserved": scene_preserved,
        "materials_preserved": scene_preserved and resolved_target in _SCENE_PRESERVING_TARGETS,
        "textures_preserved": scene_preserved and resolved_target in _SCENE_PRESERVING_TARGETS,
        "warnings": _result_warnings(
            source_format=resolved_source,
            target_format=resolved_target,
            source_kind=source_kind,
            scene_preserved=scene_preserved,
        ),
    }


def _worker_paths(filename: str) -> tuple[Path, Path]:
    safe_name = f"{uuid4().hex}-{Path(filename).name or 'upload.bin'}"
    work_dir = data_root() / "conversions" / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir / safe_name, work_dir / f"{safe_name}.json"


def _run_conversion_worker(payload: ModelConversionRequest, content: bytes) -> dict[str, object]:
    input_path, output_path = _worker_paths(payload.filename)
    try:
        input_path.write_bytes(content)
        command = [
            sys.executable,
            "-m",
            "app.conversion_worker",
            str(input_path),
            str(output_path),
            payload.filename,
            payload.target_format,
            payload.source_format or "",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=_WORKER_TIMEOUT_SECONDS, check=False)
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Conversion worker failed.").strip()
            raise RuntimeError(message)
        if not output_path.exists():
            raise RuntimeError("Conversion worker did not produce an output manifest.")
        return json.loads(output_path.read_text(encoding="utf-8"))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Conversion timed out. This model is too complex for the current OBJ UV-generation pipeline.") from exc
    finally:
        try:
            input_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            output_path.unlink(missing_ok=True)
        except Exception:
            pass


def convert_model_upload(payload: ModelConversionRequest, *, use_worker: bool = True) -> dict[str, object]:
    content = _decode_base64(payload.content_base64)
    if use_worker:
        return _run_conversion_worker(payload, content)
    return convert_model_bytes(
        filename=payload.filename,
        content=content,
        target_format=payload.target_format,
        source_format=payload.source_format,
    )


def convert_model_batch(payload: BatchModelConversionRequest, *, use_worker: bool = True) -> dict[str, object]:
    items: list[dict[str, object]] = []
    for entry in payload.items:
        try:
            result = convert_model_upload(entry, use_worker=use_worker)
            items.append({"ok": True, "filename": entry.filename, **result})
        except Exception as exc:
            items.append({"ok": False, "filename": entry.filename, "error": str(exc)})
    return {"items": items, "count": len(items)}
