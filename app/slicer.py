from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlparse
from uuid import uuid4

import requests
from pydantic import BaseModel, Field

from app.config import get_env

Runner = Callable[[list[str]], Any]
EnvGetter = Callable[[str, str], str]
PathFinder = Callable[[str], str | None]
Downloader = Callable[[str], dict[str, Any]]


class SlicerSliceRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    outputs: list[str] = Field(default_factory=lambda: ["gcode_3mf"])


class OrcaSlicerAdapter:
    allowed_settings = {
        "layer_height",
        "line_width",
        "infill",
        "infill_pattern",
        "supports",
        "support_type",
        "overhang_threshold",
        "brim",
        "skirt_loops",
        "wall_count",
        "top_shell_layers",
        "bottom_shell_layers",
        "quality",
        "seam_position",
        "ironing",
        "print_speed",
        "first_layer_speed",
        "nozzle_temperature",
        "bed_temperature",
    }
    allowed_outputs = {"gcode", "gcode_3mf", "project_3mf", "slicedata"}
    output_extensions = {
        "gcode": ".gcode",
        "gcode_3mf": ".gcode.3mf",
        "project_3mf": ".3mf",
        "slicedata": ".slicedata",
    }
    profile_presets = {
        "draft": {"layer_height": 0.28, "print_speed": 140},
        "standard": {"layer_height": 0.2, "print_speed": 100},
        "high_quality": {"layer_height": 0.12, "print_speed": 70},
    }
    material_presets = {
        "PLA": {"nozzle_temperature": 220, "bed_temperature": 60},
        "PETG": {"nozzle_temperature": 245, "bed_temperature": 80},
        "ABS": {"nozzle_temperature": 255, "bed_temperature": 100},
    }

    env_vars = ("ORCASLICER_BINARY", "ORCA_SLICER_BINARY")

    def __init__(
        self,
        *,
        binary: str | None = None,
        runner: Runner | None = None,
        env_getter: EnvGetter | None = None,
        path_finder: PathFinder | None = None,
        common_paths: Iterable[Path | str] | None = None,
    ) -> None:
        self._env_getter = env_getter or get_env
        self._path_finder = path_finder or shutil.which
        discovery = self._discover_binary(binary=binary, common_paths=common_paths)
        self.binary = discovery["binary"]
        self._binary_source = discovery["source"]
        self._resolved_binary = discovery["resolved_binary"]
        self.runner = runner or (lambda command: subprocess.run(command, capture_output=True, text=True, check=False))

    def engine_status(self) -> dict[str, Any]:
        resolved = self._resolve_binary(self.binary)
        return {
            "engine": "orca",
            "ready": bool(resolved),
            "binary": self.binary,
            "resolved_binary": resolved or "",
            "source": self._binary_source,
            "env_vars": list(self.env_vars),
        }

    def validate_settings(self, settings: dict[str, Any] | None) -> dict[str, Any]:
        if not settings:
            return {}
        expanded: dict[str, Any] = {}
        profile = str(settings.get("profile") or "").strip().lower()
        if profile in self.profile_presets:
            expanded.update(self.profile_presets[profile])
        material = str(settings.get("material") or "").strip().upper()
        if material in self.material_presets:
            expanded.update(self.material_presets[material])
        expanded.update({key: value for key, value in settings.items() if key in self.allowed_settings})
        return expanded

    def validate_outputs(self, outputs: list[str] | None) -> list[str]:
        requested = outputs or ["gcode_3mf"]
        cleaned = [str(item).strip().lower() for item in requested if str(item).strip().lower() in self.allowed_outputs]
        return cleaned or ["gcode_3mf"]

    def build_command(self, *, model_path: str, output_path: str, settings: dict[str, Any] | None, outputs: list[str] | None) -> list[str]:
        validated_settings = self.validate_settings(settings)
        validated_outputs = self.validate_outputs(outputs)
        output = Path(output_path)
        command = [self.binary, "--outputdir", str(output.parent)]
        if any(item in {"gcode", "gcode_3mf", "slicedata"} for item in validated_outputs):
            command.extend(["--slice", "0"])
        if "gcode_3mf" in validated_outputs or "project_3mf" in validated_outputs:
            command.extend(["--export-3mf", output.name])
        if "slicedata" in validated_outputs:
            command.extend(["--export-slicedata", f"{output.stem}.slicedata"])
        for key, value in validated_settings.items():
            command.extend([f"--{key.replace('_', '-')}", self._format_value(value)])
        command.append(model_path)
        return command

    def slice(self, *, model_path: str, output_path: str, settings: dict[str, Any] | None, outputs: list[str] | None) -> dict[str, Any]:
        command = self.build_command(model_path=model_path, output_path=output_path, settings=settings, outputs=outputs)
        result = self.runner(command)
        return {
            "command": command,
            "return_code": int(getattr(result, "returncode", 0)),
            "stdout": str(getattr(result, "stdout", "") or ""),
            "stderr": str(getattr(result, "stderr", "") or ""),
        }

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _discover_binary(self, *, binary: str | None, common_paths: Iterable[Path | str] | None) -> dict[str, str]:
        configured = str(binary or "").strip()
        if configured:
            return {
                "binary": configured,
                "source": "configured",
                "resolved_binary": self._resolve_binary(configured) or "",
            }

        for env_var in self.env_vars:
            configured = str(self._env_getter(env_var, "") or "").strip()
            if configured:
                return {
                    "binary": configured,
                    "source": "configured",
                    "resolved_binary": self._resolve_binary(configured) or "",
                }

        found = self._path_finder("orca-slicer") or self._path_finder("orca-slicer.exe") or self._path_finder("orcaslicer") or self._path_finder("OrcaSlicer")
        if found:
            return {"binary": found, "source": "path", "resolved_binary": found}

        for candidate in common_paths if common_paths is not None else self._default_common_paths():
            candidate_path = Path(candidate).expanduser()
            if candidate_path.exists():
                resolved = str(candidate_path.resolve())
                return {"binary": resolved, "source": "common_path", "resolved_binary": resolved}

        return {"binary": "orca-slicer", "source": "fallback", "resolved_binary": ""}

    def _resolve_binary(self, binary: str) -> str | None:
        value = str(binary or "").strip()
        if not value:
            return None
        path = Path(value).expanduser()
        if path.exists():
            return str(path.resolve())
        return self._path_finder(value)

    @staticmethod
    def _default_common_paths() -> list[Path]:
        candidates = [
            Path.home() / "AppData" / "Local" / "Programs" / "OrcaSlicer" / "orca-slicer.exe",
            Path.home() / "AppData" / "Local" / "Programs" / "OrcaSlicer" / "OrcaSlicer.exe",
            Path.home() / "AppData" / "Local" / "OrcaSlicer" / "orca-slicer.exe",
            Path.home() / "AppData" / "Local" / "OrcaSlicer" / "OrcaSlicer.exe",
        ]
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env_name)
            if base:
                candidates.append(Path(base) / "OrcaSlicer" / "orca-slicer.exe")
                candidates.append(Path(base) / "OrcaSlicer" / "OrcaSlicer.exe")
        candidates.extend(
            [
                Path("/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"),
                Path("/usr/local/bin/orcaslicer"),
                Path("/opt/OrcaSlicer/orcaslicer"),
            ]
        )
        return candidates


class SlicerService:
    def __init__(self, *, root: Path, adapter: OrcaSlicerAdapter | None = None, downloader: Downloader | None = None) -> None:
        self.root = Path(root)
        self.jobs_root = self.root / "slicer" / "jobs"
        self.adapter = adapter or OrcaSlicerAdapter()
        self.downloader = downloader or self._download_url

    def capabilities(self) -> dict[str, Any]:
        return {
            "service": "printlab-slicer",
            "engine": "orca",
            "input_formats": ["3mf", "stl", "obj"],
            "output_formats": sorted(self.adapter.allowed_outputs),
            "settings": sorted(self.adapter.allowed_settings),
            "engine_status": self.adapter.engine_status(),
        }

    def create_from_routing_job(
        self,
        routing_job: dict[str, Any],
        *,
        settings: dict[str, Any] | None = None,
        outputs: list[str] | None = None,
    ) -> dict[str, Any]:
        model_path = str(routing_job.get("file_path") or routing_job.get("model_path") or routing_job.get("download_url") or "").strip()
        if not model_path:
            raise ValueError("Routing job does not have a model path or download URL.")

        now = _utc_now()
        job_id = uuid4().hex
        job = {
            "id": job_id,
            "source": "printlab",
            "source_job_id": str(routing_job.get("id") or ""),
            "source_order_id": routing_job.get("source_order_id"),
            "status": "created",
            "model_id": routing_job.get("model_id"),
            "model_name": routing_job.get("model_name") or routing_job.get("file_name"),
            "model_path": model_path,
            "download_url": routing_job.get("download_url"),
            "printer_id": routing_job.get("printer_id"),
            "plate_gcode": routing_job.get("plate_gcode") or "Metadata/plate_1.gcode",
            "settings": self.adapter.validate_settings(settings or {}),
            "outputs": self.adapter.validate_outputs(outputs),
            "artifacts": [],
            "command_manifest": None,
            "stdout": "",
            "stderr": "",
            "error_code": None,
            "error_message": None,
            "metadata": dict(routing_job.get("metadata") or {}),
            "created_at": now,
            "updated_at": now,
        }
        self._save_job(job)
        return job

    def get_job(self, job_id: str) -> dict[str, Any]:
        path = self._job_path(job_id)
        if not path.exists():
            raise ValueError(f"Unknown slicer job: {job_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_artifacts(self, job_id: str) -> list[dict[str, Any]]:
        return list(self.get_job(job_id).get("artifacts") or [])

    def artifact_path(self, job_id: str, kind: str) -> Path:
        job_dir = self._job_dir(job_id).resolve()
        for artifact in self.list_artifacts(job_id):
            if not isinstance(artifact, dict) or str(artifact.get("kind") or "") != kind:
                continue
            path = Path(str(artifact.get("path") or "")).resolve()
            if job_dir not in path.parents and path != job_dir:
                raise ValueError("Slicer artifact path resolved outside this slicer job.")
            if not path.exists() or not path.is_file():
                raise ValueError(f"Slicer artifact is missing: {kind}")
            return path
        raise ValueError(f"Unknown slicer artifact: {kind}")

    def slice_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        outputs = self.adapter.validate_outputs(job.get("outputs"))
        primary_output = outputs[0]
        output_path = job_dir / f"output{self.adapter.output_extensions.get(primary_output, '.gcode.3mf')}"
        job["status"] = "slicing"
        job["updated_at"] = _utc_now()
        self._save_job(job)

        try:
            model_path = self._materialize_model(job, job_dir)
            result = self.adapter.slice(
                model_path=model_path,
                output_path=str(output_path),
                settings=job.get("settings") or {},
                outputs=outputs,
            )
            job["stdout"] = result["stdout"]
            job["stderr"] = result["stderr"]
            job["command_manifest"] = self._write_manifest(job, result)
            if result["return_code"] == 0:
                if not output_path.exists():
                    output_path.write_text(result["stdout"] or "Generated by PrintLab Slicer.\n", encoding="utf-8")
                job["status"] = "complete"
                job["error_code"] = None
                job["error_message"] = None
                job["artifacts"] = self._input_model_artifacts(job, job_dir) + [
                    self._artifact("command_manifest", self._manifest_path(job_id)),
                    self._artifact(primary_output, output_path),
                ]
            else:
                job["status"] = "failed"
                job["error_code"] = "slicer_process_failed"
                job["error_message"] = "OrcaSlicer returned a non-zero exit code."
                job["artifacts"] = [self._artifact("command_manifest", self._manifest_path(job_id))]
        except FileNotFoundError as exc:
            command = self.adapter.build_command(
                model_path=str(job.get("model_path") or ""),
                output_path=str(output_path),
                settings=job.get("settings") or {},
                outputs=outputs,
            )
            result = {"command": command, "return_code": 127, "stdout": "", "stderr": str(exc)}
            job["command_manifest"] = self._write_manifest(job, result)
            job["status"] = "failed"
            job["error_code"] = "slicer_binary_missing"
            job["error_message"] = str(exc) or "OrcaSlicer binary was not found."
            job["stdout"] = ""
            job["stderr"] = str(exc)
            job["artifacts"] = [self._artifact("command_manifest", self._manifest_path(job_id))]

        job["updated_at"] = _utc_now()
        self._save_job(job)
        return job

    def _materialize_model(self, job: dict[str, Any], job_dir: Path) -> str:
        model_path = str(job.get("model_path") or "").strip()
        if not self._is_remote_url(model_path):
            return model_path
        downloaded = self.downloader(model_path)
        content = downloaded.get("content")
        if not isinstance(content, bytes):
            raise ValueError("Downloaded slicer model content must be bytes.")
        filename = self._safe_input_filename(str(downloaded.get("filename") or self._filename_from_url(model_path) or "model.3mf"))
        path = job_dir / filename
        path.write_bytes(content)
        job["model_path"] = str(path)
        job["download_url"] = model_path
        return str(path)

    def _input_model_artifacts(self, job: dict[str, Any], job_dir: Path) -> list[dict[str, Any]]:
        model_path = Path(str(job.get("model_path") or ""))
        if not model_path.exists():
            return []
        try:
            resolved = model_path.resolve()
            if job_dir.resolve() not in resolved.parents and resolved != job_dir.resolve():
                return []
        except OSError:
            return []
        return [self._artifact("input_model", model_path)]

    def _write_manifest(self, job: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        manifest = {
            "job_id": job["id"],
            "source_job_id": job.get("source_job_id"),
            "engine": "orca",
            "command": result["command"],
            "return_code": result["return_code"],
            "model_path": job.get("model_path"),
            "outputs": job.get("outputs") or [],
            "settings": job.get("settings") or {},
            "created_at": _utc_now(),
        }
        path = self._manifest_path(str(job["id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        return manifest

    def _artifact(self, kind: str, path: Path) -> dict[str, Any]:
        resolved = path.resolve()
        root = self.jobs_root.resolve()
        if root not in resolved.parents and resolved != root:
            raise ValueError("Slicer artifact path resolved outside the slicer job store.")
        return {
            "id": f"{kind}:{path.stem}",
            "kind": kind,
            "path": str(path),
            "size_bytes": path.stat().st_size if path.exists() else 0,
        }

    def _job_dir(self, job_id: str) -> Path:
        safe = "".join(char for char in str(job_id) if char.isalnum() or char in {"-", "_"})[:80]
        if not safe:
            raise ValueError("Invalid slicer job id.")
        return self.jobs_root / safe

    def _job_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "job.json"

    def _manifest_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "command_manifest.json"

    def _save_job(self, job: dict[str, Any]) -> None:
        path = self._job_path(str(job["id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _is_remote_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _filename_from_url(value: str) -> str:
        name = Path(unquote(urlparse(value).path)).name
        return name or "model.3mf"

    @staticmethod
    def _safe_input_filename(value: str) -> str:
        raw = Path(value).name.strip() or "model.3mf"
        safe = "".join(char for char in raw if char.isalnum() or char in {".", "-", "_"})[:96]
        if not safe:
            safe = "model.3mf"
        return f"input-{safe}"

    @staticmethod
    def _download_url(url: str) -> dict[str, Any]:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        return {"content": response.content, "filename": SlicerService._filename_from_url(url)}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
