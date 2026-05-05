# Prusa Printer Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Prusa printer support without regressing the existing Bambu printer integration, and make Prusa printer cards and detail pages look and behave as close to Bambu printers as the available PrusaLink data allows.

**Architecture:** Introduce a provider boundary between PrintLab's queue/UI/job orchestration and printer-specific protocols. Keep the existing Bambu behavior behind a `BambuPrinterProvider`, add a local `PrusaLinkPrinterProvider`, and make cloud Prusa Connect support a later provider because PrintLab's current control path is direct local printer operation.

**Tech Stack:** FastAPI, Pydantic, pytest, paho-mqtt/pybambu for Bambu, `requests` for PrusaLink HTTP, existing dashboard HTML/JS.

---

## Source Notes

- Existing Bambu coupling lives mostly in `app/services.py`: `PrinterService.start()` constructs `BambuClient`, control methods call `pybambu` enums/commands, SD listing/staging uses `client.get_device().ftp`, and `state()` serializes a pybambu device.
- `MultiPrinterManager` already owns multi-printer creation, add/update/remove, config backup/import, and persisted UI-added printers.
- API routes in `app/routers/api.py` are mostly printer-provider-agnostic because they call `PrinterService` methods.
- Add-printer UI in `app/views.py` currently assumes Bambu fields: host, serial, access code, local MQTT, camera, SSL verify.
- Prusa's official user docs describe sending G-code over the network via PrusaLink/Prusa Connect and using API keys from printer/Connect settings. Start with PrusaLink local HTTP support; defer full Prusa Connect cloud control until there is a documented need.

## Capability Target

Phase 1 PrusaLink support should include:

- Configure a printer with `provider="prusa_link"`, host, API key, optional username/password, optional TLS verify flag, and device type.
- Poll printer status and expose a normalized PrintLab `state()` compatible with the current dashboard.
- Populate the same normalized card/detail fields used by Bambu cards wherever PrusaLink exposes equivalent data: printer name, model/device type, IP address, connection state, job state, progress, remaining time, temperatures, queue count, latest file name, health score, alerts, and file browser entries.
- Upload `.gcode` and `.bgcode` files to printer storage and queue/start them through the existing PrintLab queue.
- Support pause, resume, stop/cancel where PrusaLink exposes those actions.
- List printer files when available from PrusaLink.
- Keep printer cards and the detail page visually aligned with Bambu printers. Do not create separate Prusa-only card templates or a visibly different detail page. Use the existing Bambu layout and render unavailable features as disabled, empty, or "Unavailable" states inside the same sections.
- Degrade unsupported Bambu-only features cleanly: AMS, chamber camera, chamber light, Bambu timelapse download, Bambu MQTT event stream.

Out of scope for Phase 1:

- Prusa Connect cloud account integration.
- Automatic slicing from STL/3MF into Prusa-specific G-code.
- Full Prusa camera integration beyond reporting unavailable unless a configured camera URL exists.
- Reusing Bambu AMS mapping semantics for Prusa printers.
- A Prusa-specific redesign of printer cards or the detail dashboard.

## File Structure

- Create `app/printers/__init__.py`: provider exports and registry helpers.
- Create `app/printers/base.py`: protocol/interface, normalized dataclasses, feature flags, provider errors.
- Create `app/printers/bambu.py`: move pybambu-specific connection, control, file, camera, and serialization behavior out of `PrinterService`.
- Create `app/printers/prusa_link.py`: PrusaLink HTTP client/provider implementation.
- Modify `app/services.py`: keep orchestration, queue, timeline, MakerWorks, YouTube, webhooks; delegate printer-specific operations to `self.provider`.
- Modify `app/models.py` and Pydantic models in `app/services.py`: add provider fields while keeping Bambu defaults backward compatible.
- Modify `app/views.py`: add provider selector and provider-specific field labels/help on `/add-printer`; preserve the existing gallery card DOM/CSS structure for Bambu and Prusa cards.
- Modify `app/dashboard.html`: preserve the existing Bambu detail page layout for Prusa printers; disable unsupported controls based on `state.capabilities` while keeping sections in familiar positions.
- Modify `.env.example` and `README.md`: document Bambu and PrusaLink config.
- Modify `requirements.txt`: no new dependency needed for Phase 1 because `requests` already exists.
- Add `tests/test_printer_providers.py`: provider registry and normalized state contract tests.
- Add `tests/test_prusa_link_provider.py`: mocked HTTP behavior for status, upload, print, and actions.
- Update `tests/test_printer_manager.py`, `tests/test_api_security.py`, and `tests/test_dashboard_ui.py`: provider-aware config and UI expectations.

---

### Task 1: Add Provider Schema And Registry

**Files:**
- Create: `app/printers/__init__.py`
- Create: `app/printers/base.py`
- Test: `tests/test_printer_providers.py`

- [ ] **Step 1: Write failing provider registry tests**

```python
from app.printers import create_printer_provider
from app.printers.base import PrinterCapabilities, PrinterProvider


def test_create_bambu_provider_by_default() -> None:
    provider = create_printer_provider({"host": "192.168.1.10", "serial": "SERIAL", "access_code": "CODE"})
    assert provider.provider_name == "bambu"


def test_create_prusa_link_provider() -> None:
    provider = create_printer_provider({"provider": "prusa_link", "host": "192.168.1.20", "api_key": "KEY"})
    assert provider.provider_name == "prusa_link"


def test_unknown_provider_is_rejected() -> None:
    try:
        create_printer_provider({"provider": "makerbot"})
    except ValueError as exc:
        assert "Unsupported printer provider" in str(exc)
    else:
        raise AssertionError("Expected provider creation to fail")
```

- [ ] **Step 2: Run the failing tests**

Run: `pytest tests/test_printer_providers.py -v`

Expected: FAIL because `app.printers` does not exist.

- [ ] **Step 3: Implement base provider types**

Create `app/printers/base.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class PrinterCapabilities:
    pause: bool = True
    resume: bool = True
    stop: bool = True
    temperature_control: bool = True
    fan_control: bool = True
    chamber_light: bool = False
    camera: bool = False
    file_list: bool = True
    file_upload: bool = True
    timelapse_download: bool = False
    ams: bool = False


@dataclass(frozen=True)
class PrinterFile:
    path: str
    name: str
    size: int | None = None
    modified_at: str | None = None
    thumbnail_url: str | None = None


@dataclass(frozen=True)
class StagedFile:
    file_path: str
    name: str
    size: int


@dataclass
class NormalizedPrinterState:
    connected: bool
    printer: dict[str, Any]
    job: dict[str, Any] = field(default_factory=dict)
    temperatures: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, bool] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


class PrinterProvider(Protocol):
    provider_name: str
    capabilities: PrinterCapabilities

    async def connect(self, on_event: Any) -> None: ...
    async def disconnect(self) -> None: ...
    async def refresh(self) -> None: ...
    def is_connected(self) -> bool: ...
    def normalized_state(self) -> NormalizedPrinterState: ...
    async def action(self, action: str) -> None: ...
    async def set_temperature(self, target: str, value: float) -> None: ...
    async def set_fan(self, target: str, value: int) -> None: ...
    async def set_chamber_light(self, on: bool) -> None: ...
    async def list_files(self, query: str | None = None) -> list[PrinterFile]: ...
    async def upload_file(self, content: bytes, preferred_name: str) -> StagedFile: ...
    async def start_file(self, file_path: str, options: dict[str, Any]) -> None: ...
    async def get_thumbnail(self, path: str) -> tuple[bytes | None, str | None]: ...
    async def get_live_frame(self) -> tuple[bytes | None, str | None]: ...
```

- [ ] **Step 4: Implement provider registry**

Create `app/printers/__init__.py` with a lazy import registry so tests can import it without requiring pybambu:

```python
from __future__ import annotations

from typing import Any

from app.printers.base import PrinterProvider


def create_printer_provider(config: dict[str, Any]) -> PrinterProvider:
    provider = str(config.get("provider") or "bambu").strip().lower()
    if provider in {"bambu", "bambu_lab", "bambulab"}:
        from app.printers.bambu import BambuPrinterProvider

        return BambuPrinterProvider(config)
    if provider in {"prusa", "prusa_link", "prusalink"}:
        from app.printers.prusa_link import PrusaLinkPrinterProvider

        return PrusaLinkPrinterProvider(config)
    raise ValueError(f"Unsupported printer provider: {provider}")
```

- [ ] **Step 5: Add temporary provider stubs**

Create minimal `app/printers/bambu.py` and `app/printers/prusa_link.py` classes with `provider_name`, `capabilities`, constructor, and unimplemented async methods that raise `NotImplementedError`. These stubs make registry tests pass before behavior is moved.

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_printer_providers.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add app/printers tests/test_printer_providers.py
git commit -m "feat: add printer provider registry"
```

---

### Task 2: Preserve Bambu Behavior Behind Provider Boundary

**Files:**
- Modify: `app/printers/bambu.py`
- Modify: `app/services.py`
- Test: `tests/test_queue.py`
- Test: `tests/test_printer_manager.py`

- [ ] **Step 1: Add tests around existing Bambu defaults**

Add assertions that existing configs without `provider` still produce `provider == "bambu"` in `list_items()` and backup exports. Existing tests should remain unchanged except for checking the new provider value.

- [ ] **Step 2: Move pybambu import block**

Move the current pybambu import fallback from `app/services.py` into `app/printers/bambu.py`. Keep the fallback behavior because tests run without pybambu.

- [ ] **Step 3: Implement `BambuPrinterProvider` by extracting current methods**

Move these behaviors from `PrinterService` into provider methods:

- `start()` connection internals: `BambuClient(cfg)`, `connect()`, `refresh()`
- `stop()` disconnect internals
- `action()`
- `set_chamber_light()`
- `set_temperature()`
- `set_fan()`
- SD file resolution/listing/thumbnail/upload
- live frame/camera helpers
- device serialization used by `state()`

Keep queue persistence, timeline, webhooks, YouTube, MakerWorks, and submitted-job logic in `PrinterService`.

- [ ] **Step 4: Delegate from `PrinterService`**

In `PrinterService.__init__`, create `self.provider = create_printer_provider(config)`. Replace direct `self.client` reads with provider calls:

- connected checks use `self.provider.is_connected()`
- `start()` calls `self.provider.connect(self._on_client_event)`
- `stop()` calls `self.provider.disconnect()`
- control methods call provider methods
- file methods call provider methods
- `state()` merges `self.provider.normalized_state()` with queue/timeline/webhook/system data

- [ ] **Step 5: Run Bambu regression tests**

Run: `pytest tests/test_queue.py tests/test_printer_manager.py tests/test_api_security.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add app/services.py app/printers/bambu.py tests/test_queue.py tests/test_printer_manager.py tests/test_api_security.py
git commit -m "refactor: isolate bambu printer provider"
```

---

### Task 3: Implement PrusaLink HTTP Provider

**Files:**
- Modify: `app/printers/prusa_link.py`
- Test: `tests/test_prusa_link_provider.py`

- [ ] **Step 1: Write mocked HTTP tests**

Use monkeypatched `requests.Session.request` or a fake session object to verify:

- `connect()` calls a status/version endpoint and sets connected.
- `normalized_state()` maps status to PrintLab keys: `printer`, `job`, `temperatures`, `errors`, `capabilities`.
- `upload_file()` sends bytes with PrusaLink API authentication and returns a `StagedFile`.
- `start_file()` sends a print command for the uploaded file.
- unsupported actions raise a clear `ValueError`.

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/test_prusa_link_provider.py -v`

Expected: FAIL because the PrusaLink provider is still a stub.

- [ ] **Step 3: Implement configuration parsing**

In `PrusaLinkPrinterProvider.__init__`, support:

- `host`
- `api_key`
- `username`
- `password`
- `use_ssl`, default `False`
- `disable_ssl_verify`
- `device_type`, default `prusa`
- `storage`, default `usb`
- `timeout_seconds`, default `10`

Build `base_url` from `http://{host}` or `https://{host}` and never log secrets.

- [ ] **Step 4: Implement request helper**

Use `requests.Session.request` in `asyncio.to_thread()` wrappers. Send API key using the header expected by PrusaLink/PrusaSlicer-compatible upload flows, and support HTTP basic auth when username/password are configured. Convert HTTP errors to `RuntimeError` with status and sanitized response detail.

- [ ] **Step 5: Implement status mapping**

Poll likely PrusaLink local endpoints in this order, accepting the first successful response:

- `/api/v1/status`
- `/api/printer`
- `/api/job`

Normalize into PrintLab's expected shape:

```python
NormalizedPrinterState(
    connected=True,
    printer={
        "serial": config.get("serial") or "",
        "device_type": config.get("device_type") or "prusa",
        "ip_address": config["host"],
        "provider": "prusa_link",
    },
    job={
        "state": mapped_state,
        "progress": progress_percent,
        "remaining_minutes": remaining_minutes,
        "file_name": file_name,
    },
    temperatures={
        "nozzle_current": nozzle_actual,
        "nozzle_target": nozzle_target,
        "bed_current": bed_actual,
        "bed_target": bed_target,
        "chamber": None,
    },
    errors={"print_error": error_message},
    capabilities=asdict(self.capabilities),
    raw=last_status_payload,
)
```

- [ ] **Step 6: Preserve Bambu-equivalent state keys for UI parity**

Ensure `PrusaLinkPrinterProvider.normalized_state()` always returns the same high-level keys the current Bambu dashboard consumes. Missing data should be `None`, `"-"`, `0`, or an explicit unavailable capability, not omitted.

Required minimum shape:

```python
{
    "printer": {
        "serial": "",
        "device_type": "mk4",
        "ip_address": "192.168.1.120",
        "provider": "prusa_link",
    },
    "job": {
        "state": "IDLE",
        "progress": 0,
        "remaining_minutes": None,
        "file_name": None,
        "thumbnail_url": None,
    },
    "temperatures": {
        "nozzle_current": None,
        "nozzle_target": None,
        "bed_current": None,
        "bed_target": None,
        "chamber": None,
    },
    "errors": {"print_error": None},
    "capabilities": {
        "pause": True,
        "resume": True,
        "stop": True,
        "temperature_control": False,
        "fan_control": False,
        "chamber_light": False,
        "camera": False,
        "file_list": True,
        "file_upload": True,
        "timelapse_download": False,
        "ams": False,
    },
}
```

- [ ] **Step 7: Implement upload and start**

Accept `.gcode` and `.bgcode` for PrusaLink. If a `.3mf` is passed to a Prusa provider, raise `ValueError("PrusaLink requires sliced .gcode or .bgcode files.")`.

Upload to configured storage and remote filename, then start by path. Preserve the existing PrintLab queue item metadata so MakerWorks callbacks still receive `file_path`, `file_name`, and status transitions.

- [ ] **Step 8: Implement controls**

Map PrintLab actions:

- `pause`
- `resume`
- `stop`

Return a clear unsupported-feature error for `chamber_light`, AMS-specific options, and unavailable controls. Implement temperature/fan only if tests confirm endpoint behavior; otherwise set capabilities to `False` and make methods raise `ValueError("Temperature control is not supported for this PrusaLink printer.")`.

- [ ] **Step 9: Run tests**

Run: `pytest tests/test_prusa_link_provider.py tests/test_printer_providers.py -v`

Expected: PASS.

- [ ] **Step 10: Commit**

Run:

```bash
git add app/printers/prusa_link.py tests/test_prusa_link_provider.py
git commit -m "feat: add prusalink printer provider"
```

---

### Task 4: Add Provider-Aware Config And API Serialization

**Files:**
- Modify: `app/services.py`
- Modify: `app/models.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`
- Test: `tests/test_printer_manager.py`
- Test: `tests/test_api_security.py`

- [ ] **Step 1: Add config tests**

Add tests for:

- default provider is `bambu`
- `PRINTER_PROVIDER=prusa_link` appears in default config
- `PRINTERS_JSON` entries can override provider and include `api_key`
- admin list/settings redacts `api_key` and `password`
- config backup exports `has_api_key` but not `api_key`

- [ ] **Step 2: Update config builders**

Add fields to `build_default_printer_config()`:

- `provider`
- `api_key`
- `username`
- `password`
- `use_ssl`
- `storage`

Keep Bambu env names working:

- `PRINTER_ACCESS_CODE` remains the Bambu credential.
- `PRINTER_API_KEY` is the PrusaLink credential.

- [ ] **Step 3: Update request models**

Extend `AddPrinterRequest` and `UpdatePrinterRequest` with provider-aware optional fields. Validation rules:

- Bambu requires `host`, `serial`, and `access_code`.
- PrusaLink requires `host` and `api_key`.
- `serial` is optional for PrusaLink.

- [ ] **Step 4: Update redaction helpers**

Ensure list/settings/backup omit these secrets:

- `access_code`
- `api_key`
- `password`

Expose booleans:

- `has_access_code`
- `has_api_key`
- `has_password`

- [ ] **Step 5: Update `.env.example`**

Document both single-printer examples:

```env
PRINTER_PROVIDER=bambu
PRINTER_HOST=192.168.1.100
PRINTER_SERIAL=YOUR_BAMBU_SERIAL
PRINTER_ACCESS_CODE=YOUR_BAMBU_ACCESS_CODE

# PrusaLink example:
# PRINTER_PROVIDER=prusa_link
# PRINTER_HOST=192.168.1.120
# PRINTER_API_KEY=YOUR_PRUSALINK_API_KEY
# PRINTER_DEVICE_TYPE=mk4
# PRINTER_STORAGE=usb
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_config.py tests/test_printer_manager.py tests/test_api_security.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add app/services.py app/models.py .env.example tests/test_config.py tests/test_printer_manager.py tests/test_api_security.py
git commit -m "feat: add provider-aware printer config"
```

---

### Task 5: Update Queue And MakerWorks Compatibility For Prusa

**Files:**
- Modify: `app/services.py`
- Test: `tests/test_queue.py`
- Test: `tests/test_works.py`

- [ ] **Step 1: Add queue tests for Prusa file rules**

Assert:

- `.gcode` and `.bgcode` queue for PrusaLink.
- `.3mf` and `.gcode.3mf` fail for PrusaLink with a clear sliced-file message.
- Bambu still accepts `.3mf`, `.gcode.3mf`, and `.gcode`.

- [ ] **Step 2: Make file validation provider-aware**

Move suffix validation from `PrinterService._project_file_suffix()` into provider capabilities or provider method. `PrinterService.queue_print_job()` should ask the provider to upload/start and report provider errors unchanged.

- [ ] **Step 3: Make MakerWorks preflight provider-aware**

Update compatibility checks so a model with only `.3mf` asset is not considered directly queueable to PrusaLink. If MakerWorks provides `.gcode` or `.bgcode`, PrusaLink can qualify.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_queue.py tests/test_works.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add app/services.py tests/test_queue.py tests/test_works.py
git commit -m "feat: make queue routing provider aware"
```

---

### Task 6: Update Add-Printer UI And Dashboard Capabilities

**Files:**
- Modify: `app/views.py`
- Modify: `app/dashboard.html`
- Test: `tests/test_dashboard_ui.py`

- [ ] **Step 1: Add UI tests**

Assert rendered add-printer page includes:

- provider selector with Bambu and PrusaLink
- PrusaLink API key field
- provider-specific validation text

Assert gallery and dashboard parity:

```python
def test_prusa_cards_use_existing_printer_card_layout(client) -> None:
    response = client.get("/")
    html = response.text
    assert "printer-card" in html
    assert "device_type" in html
    assert "health" in html.lower()


def test_dashboard_uses_same_sections_for_capability_limited_printers() -> None:
    html = render_printer_dashboard("prusa-1")
    assert "overviewPanel" in html
    assert "systemHealth" in html
    assert "settingsPanel" in html
    assert "capabilities" in html
```

Assert dashboard JS references `capabilities` before enabling Bambu-only controls, but does not branch into a separate Prusa-only page layout.

- [ ] **Step 2: Update add-printer form**

Add a provider selector. For Bambu, show serial/access code/local MQTT/camera fields. For PrusaLink, show API key, optional username/password, storage, and SSL fields.

- [ ] **Step 3: Update submit payload**

Send `provider` and only relevant credential fields. Client validation:

- Bambu: name, host, serial, access code.
- PrusaLink: name, host, API key.

- [ ] **Step 4: Update existing-printer cards**

Keep the same card component used by Bambu printers. Show provider label next to device type only as secondary metadata, using the same typography and spacing as existing card metadata. Preserve the same visual hierarchy:

- printer image/thumbnail area
- printer name
- model/device type
- connected/offline badge
- active job summary
- progress/remaining time when printing
- queue count
- health score
- open-dashboard action

For PrusaLink cards, fill missing Bambu-only values with the same empty-state treatment used elsewhere in PrintLab. Redact PrusaLink credentials when editing unless the admin enters replacements, matching existing access-code behavior.

- [ ] **Step 5: Update dashboard controls**

Read `s.capabilities`. Keep the same dashboard sections and control positions as Bambu. Disable controls that cannot work, and keep their labels consistent:

- chamber light when `capabilities.chamber_light` is false
- fan/temperature controls when unsupported
- camera/live preview when `capabilities.camera` is false
- AMS preset UI when `capabilities.ams` is false
- timelapse/YouTube download actions when `capabilities.timelapse_download` is false

Do not replace the detail page with a separate Prusa dashboard. The detail page should still show Overview, Health, Settings, model library, queue, timeline, webhooks, and job status in the same order as Bambu. Prusa-only differences belong in state values and disabled controls, not in page structure.

- [ ] **Step 6: Add visual parity smoke checks**

After implementation, run the app and compare a Bambu fixture/state and a PrusaLink fixture/state:

1. Open `/` and confirm Bambu and Prusa cards have the same dimensions, grid placement, status badge style, metadata hierarchy, and action placement.
2. Open `/printer/{bambu_id}` and `/printer/{prusa_id}` and confirm the first viewport contains the same major sections in the same order.
3. Confirm unavailable Prusa features do not collapse surrounding layout or create large blank gaps.
4. Confirm a printing PrusaLink state renders progress, remaining time, temperatures, queue, and file name in the same places as a printing Bambu state.

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_dashboard_ui.py -v`

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add app/views.py app/dashboard.html tests/test_dashboard_ui.py
git commit -m "feat: expose prusalink printer setup in ui"
```

---

### Task 7: Documentation And Manual Verification

**Files:**
- Modify: `README.md`
- Optional modify: `compose.yaml` only if new env passthrough is required

- [ ] **Step 1: Update README positioning**

Change the intro from Bambu-only to Bambu plus PrusaLink, while noting Bambu remains fully supported.

- [ ] **Step 2: Document setup**

Add sections:

- Bambu setup
- PrusaLink setup
- Provider capability matrix
- Known PrusaLink limitations

- [ ] **Step 3: Run full verification**

Run:

```bash
ruff check .
pytest -v
```

Expected: PASS.

- [ ] **Step 4: Manual smoke test with a real/simulated PrusaLink printer**

Use an admin session:

1. Add a PrusaLink printer through `/add-printer`.
2. Confirm `/api/printers/{printer_id}/state` returns `provider: prusa_link` and a `capabilities` object.
3. Confirm its gallery card matches the Bambu card layout and only differs in printer data/provider metadata.
4. Confirm its detail dashboard matches the Bambu detail page structure and first-viewport section order.
5. Upload or queue a small known-safe `.bgcode` or `.gcode`.
6. Confirm queue item moves from queued to started or fails with a clear PrusaLink response.
7. Confirm unsupported controls stay in the expected Bambu-equivalent positions and are disabled, unavailable, or empty without breaking layout.

- [ ] **Step 5: Commit**

Run:

```bash
git add README.md compose.yaml
git commit -m "docs: document prusalink printer support"
```

---

## Risks And Decisions

- PrusaLink API behavior varies by printer generation and firmware. Keep the provider small, heavily mocked, and tolerant of missing fields.
- Prusa files should be sliced before PrintLab receives them. Do not pretend `.3mf` uploads are equivalent to Bambu project files.
- Current Bambu timelapse and AMS features do not map cleanly to PrusaLink. Model these as capabilities, not special cases spread across the UI.
- Prusa Connect cloud support should be a separate provider after local PrusaLink works.

## Final Verification Checklist

- [ ] Existing Bambu single-printer `.env` works unchanged.
- [ ] Existing `PRINTERS_JSON` Bambu fleets work unchanged.
- [ ] UI-added Bambu printers can still be edited/removed.
- [ ] UI-added PrusaLink printers persist and redact secrets.
- [ ] Bambu and PrusaLink cards use the same card template, dimensions, metadata hierarchy, and action placement.
- [ ] Bambu and PrusaLink detail pages use the same section order and visual structure.
- [ ] `/api/printers`, `/api/printers/{id}/state`, queue, jobs, webhooks, and system health handle mixed Bambu/Prusa fleets.
- [ ] MakerWorks routing only chooses PrusaLink for sliced `.gcode`/`.bgcode` assets.
- [ ] Full tests pass: `ruff check . && pytest -v`.
