from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FanRequest(BaseModel):
    fan: str = Field(pattern="^(part_cooling|auxiliary|chamber|heatbreak|secondary_auxiliary)$")
    percent: int = Field(ge=0, le=100)


class TemperatureRequest(BaseModel):
    target: str = Field(pattern="^(heatbed|nozzle)$")
    value: int = Field(ge=0, le=320)


class ChamberLightRequest(BaseModel):
    on: bool


class PrinterNameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class AddPrinterRequest(BaseModel):
    id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=64)
    host: str = Field(min_length=1, max_length=255)
    serial: str = Field(min_length=1, max_length=128)
    access_code: str = Field(min_length=1, max_length=128)
    device_type: str = Field(default="unknown", max_length=64)
    local_mqtt: bool = True
    enable_camera: bool = True
    disable_ssl_verify: bool = False


class WorksRequest(BaseModel):
    method: str = Field(pattern="^(GET|POST|PUT|PATCH|DELETE)$")
    path: str = Field(default="/")
    query: dict[str, Any] | None = None
    body: Any = None
    body_text: str | None = None
    headers: dict[str, str] | None = None
    timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)


class OrderworksPrintJobRequest(BaseModel):
    file_path: str = Field(min_length=1, description="Path to .3mf/.gcode.3mf on printer SD card, e.g. /cache/model.3mf")
    plate_gcode: str = Field(default="Metadata/plate_1.gcode")
    subtask_name: str | None = None
    use_ams: bool = True
    ams_mapping: list[int] | None = None
    bed_type: str = "auto"
    timelapse: bool = False
    bed_leveling: bool = True
    flow_cali: bool = True
    vibration_cali: bool = True
    layer_inspect: bool = True


class QueuePrintJobRequest(OrderworksPrintJobRequest):
    start_at: str | None = Field(default=None, description="UTC ISO timestamp for scheduled start.")


class MakerworksQueueJobRequest(BaseModel):
    model_id: str = Field(min_length=1)
    start_at: str | None = Field(default=None, description="UTC ISO timestamp for scheduled start.")
    plate_gcode: str = Field(default="Metadata/plate_1.gcode")
    use_ams: bool = True
    ams_mapping: list[int] | None = None
    bed_type: str = "auto"
    timelapse: bool = False
    bed_leveling: bool = True
    flow_cali: bool = True
    vibration_cali: bool = True
    layer_inspect: bool = True


class MakerworksSubmitJobRequest(BaseModel):
    model_id: str = Field(min_length=1)
    printer_id: str | None = Field(default=None, min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=128)
    source_job_id: str = Field(min_length=1, max_length=128)
    source_order_id: str = Field(min_length=1, max_length=128)
    start_at: str | None = Field(default=None, description="UTC ISO timestamp for scheduled start.")
    plate_gcode: str = Field(default="Metadata/plate_1.gcode")
    use_ams: bool = True
    ams_mapping: list[int] | None = None
    bed_type: str = "auto"
    timelapse: bool = False
    bed_leveling: bool = True
    flow_cali: bool = True
    vibration_cali: bool = True
    layer_inspect: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueueUpdateRequest(BaseModel):
    start_at: str | None = Field(default=None, description="UTC ISO timestamp for scheduled start.")


class ControlPresetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    nozzle_target: int | None = Field(default=None, ge=0, le=320)
    bed_target: int | None = Field(default=None, ge=0, le=130)
    part_cooling: int | None = Field(default=None, ge=0, le=100)
    auxiliary: int | None = Field(default=None, ge=0, le=100)
    chamber: int | None = Field(default=None, ge=0, le=100)


class AlertRuleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    type: str = Field(pattern="^(disconnect_duration|chamber_temp_above|print_error|queue_backlog)$")
    enabled: bool = True
    threshold: float | None = Field(default=None, ge=0)
    severity: str = Field(default="warning", pattern="^(info|warning|error)$")
    notify: bool = True


class AlertRuleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    type: str | None = Field(default=None, pattern="^(disconnect_duration|chamber_temp_above|print_error|queue_backlog)$")
    enabled: bool | None = None
    threshold: float | None = Field(default=None, ge=0)
    severity: str | None = Field(default=None, pattern="^(info|warning|error)$")
    notify: bool | None = None


class QueueReorderRequest(BaseModel):
    direction: str = Field(pattern="^(up|down)$")


class SuccessfulGcodeSyncRequest(BaseModel):
    force: bool = False
