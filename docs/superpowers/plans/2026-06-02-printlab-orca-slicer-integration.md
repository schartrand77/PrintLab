# PrintLab Orca Slicer Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PrintLab own the slicer workflow while using OrcaSlicer as the installed slicing engine, so MakerWorks routing jobs can be opened in `/slicer`, sliced, saved back to routing, and routed to a printer using the sliced artifact.

**Architecture:** Keep PrintLab as the web UI, routing, job state, and artifact owner. Treat OrcaSlicer as an external engine binary invoked through a small adapter in `app/slicer.py`, with job manifests and artifacts persisted under the PrintLab data root. Route-only MakerWorks jobs stay on the routing board until the operator opens them in PrintLab Slicer, slices them, saves the output artifact back, then routes the saved artifact to the selected printer.

**Tech Stack:** FastAPI, server-rendered HTML/JavaScript in `app/views.py`, Pydantic request models, pytest, Ruff, `requests`, installed OrcaSlicer executable.

---

## Status Summary

- ~~Create development branch for slicer work.~~
- ~~Add full-page `/slicer` PrintLab workspace.~~
- ~~Rename routing-board action from "Send to slicer" to "Open Slicer".~~
- ~~Add OrcaSlicer adapter with allowlisted settings and output formats.~~
- ~~Add slicer API endpoints for capabilities, slice, job lookup, artifact lookup, and save-back.~~
- ~~Add Orca binary discovery from `ORCASLICER_BINARY`, `ORCA_SLICER_BINARY`, PATH, and common install paths.~~
- ~~Show Orca engine readiness in the `/slicer` workspace.~~
- ~~Preserve real Orca output artifacts instead of overwriting them with stdout.~~
- ~~Reject save-back when a completed slicer job has no output artifact.~~
- ~~Route saved slicer artifacts to printer queues instead of re-downloading original MakerWorks assets.~~
- ~~Materialize remote `download_url` models into local slicer job storage before invoking Orca.~~
- ~~Confirm the exact OrcaSlicer CLI arguments from the `schartrand77/OrcaSlicer-MakerWorks` source and adjust `OrcaSlicerAdapter.build_command()`.~~ Built binary smoke testing is still pending because no local `orca-slicer` executable was found on PATH or common Windows install paths on 2026-06-02.
- ~~Add profile/material preset mapping instead of sending only generic raw settings.~~
- ~~Add slicer job progress/status refresh in the `/slicer` UI.~~
- ~~Add artifact download/view API for generated `.gcode.3mf`, manifest, and input model files.~~
- ~~Add `/slicer` artifact download links for generated outputs, manifests, and staged input models.~~
- ~~Add a repeatable Docker Desktop dev override for a `printlab-dev` container on port `8290`.~~
- ~~Confirm FULU publishes Linux/Ubuntu OrcaSlicer builds and add optional Docker LinuxDir ingestion for Unraid/Docker deployments.~~ FULU `v1.0.0` Linux binaries currently fail headless Docker CLI smoke tests with signal 11.
- ~~Add Orca runtime launch probing so a found-but-crashing binary disables slicing and reports the probe failure in `/slicer`.~~
- ~~Install Orca GTK/WebKit/GStreamer/OpenGL Docker runtime packages only when `ORCA_LINUXDIR_URL` is set, keeping normal PrintLab images leaner.~~
- [ ] Add production smoke test with a real built `schartrand77/OrcaSlicer-MakerWorks` installation and a sample 3MF/STL.
- [ ] Commit and push the completed integration branch.

---

## File Structure

- Modify `app/slicer.py`: Orca engine adapter, model materialization, slicing job persistence, command manifest writing, artifact recording, engine status.
- Modify `app/routers/api.py`: slicer API routes and routing save-back validation.
- Modify `app/routers/ui.py`: `/slicer` route.
- Modify `app/views.py`: `/slicer` workspace and MakerWorks routing-board actions.
- Modify `app/services.py`: save slicer artifacts onto routing jobs and route those artifacts to printer queues.
- Modify `app/dashboard.html`: sidebar navigation link to Slicer.
- Modify `.env.example`: Orca binary configuration.
- Modify `README.md`: slicer configuration notes.
- Modify `tests/test_slicer.py`: adapter, service, API, artifact, and remote input tests.
- Modify `tests/test_models.py`: rendered UI route/action assertions.
- Modify `tests/test_queue.py`: sliced artifact routing behavior.

---

## Completed Tasks

### Task 1: Full-Page Slicer Workspace

**Files:**
- Modify: `app/routers/ui.py`
- Modify: `app/views.py`
- Modify: `app/dashboard.html`
- Modify: `tests/test_models.py`

- [x] ~~Add `/slicer` route in `app/routers/ui.py`.~~
- [x] ~~Add `render_slicer_html()` in `app/views.py`.~~
- [x] ~~Add Slicer sidebar links across PrintLab pages.~~
- [x] ~~Add workspace controls for job context, profile, material, layer height, infill, slice, save-back, and output log.~~
- [x] ~~Add rendered-page tests for `/slicer`.~~

### Task 2: Routing Board Integration

**Files:**
- Modify: `app/views.py`
- Modify: `tests/test_models.py`

- [x] ~~Replace "Send to slicer" with "Open Slicer".~~
- [x] ~~Open `/slicer?job_id=...` from MakerWorks routing jobs.~~
- [x] ~~Keep a compatibility wrapper `sendQueuedJobToSlicer()` for existing call sites.~~
- [x] ~~Add "Route To Printer" for jobs with saved slicer output artifacts.~~
- [x] ~~Post routed sliced jobs to `/api/jobs/{job_id}/queue`.~~

### Task 3: Orca Adapter And Slicer Service

**Files:**
- Create/Modify: `app/slicer.py`
- Modify: `tests/test_slicer.py`

- [x] ~~Add `SlicerSliceRequest`.~~
- [x] ~~Add `OrcaSlicerAdapter` with allowlisted settings and output formats.~~
- [x] ~~Add Orca binary discovery from config/env, PATH, common install paths, and fallback command name.~~
- [x] ~~Add `SlicerService` for job creation, persistence, slicing, manifests, artifacts, and capabilities.~~
- [x] ~~Preserve real engine-written output artifacts.~~
- [x] ~~Create fallback output only when Orca returns success but no output file exists.~~
- [x] ~~Materialize remote model URLs into local slicer job storage before invoking Orca.~~

### Task 4: Slicer API

**Files:**
- Modify: `app/routers/api.py`
- Modify: `tests/test_slicer.py`

- [x] ~~Add `GET /api/slicer/capabilities`.~~
- [x] ~~Add `POST /api/slicer/routing-jobs/{job_id}/slice`.~~
- [x] ~~Add `GET /api/slicer/jobs/{job_id}`.~~
- [x] ~~Add `GET /api/slicer/jobs/{job_id}/artifacts`.~~
- [x] ~~Add `POST /api/slicer/jobs/{job_id}/save-routing`.~~
- [x] ~~Require an output artifact before save-back to routing.~~

### Task 5: Routing Save-Back And Queue Handoff

**Files:**
- Modify: `app/services.py`
- Modify: `tests/test_queue.py`
- Modify: `tests/test_slicer.py`

- [x] ~~Add `PrintJobManager.attach_slicer_job()`.~~
- [x] ~~Save `slicer_job_id`, `slicer_status`, `slicer_artifacts`, and `slicer_settings` on routing jobs.~~
- [x] ~~Keep `sliced` jobs visible on the routing board.~~
- [x] ~~Allow route-only jobs with saved slicer output artifacts to be queued.~~
- [x] ~~Stage saved slicer artifact bytes directly instead of downloading original MakerWorks assets.~~

### Task 6: Configuration And Documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [x] ~~Document `ORCASLICER_BINARY`.~~
- [x] ~~Document `ORCA_SLICER_BINARY` legacy alias.~~
- [x] ~~Explain that PrintLab auto-detects Orca from PATH and common install paths when no binary is configured.~~

---

## Remaining Tasks

### Task 7: Validate Real Orca CLI Invocation

**Files:**
- Modify: `app/slicer.py`
- Modify: `tests/test_slicer.py`
- Optional Modify: `.env.example`
- Optional Modify: `README.md`

- [x] ~~**Step 1: Locate the OrcaSlicer-MakerWorks fork**~~

Found fork:

```text
https://github.com/schartrand77/OrcaSlicer-MakerWorks
```

Source inspected through a shallow sparse clone at:

```text
C:\tmp\OrcaSlicer-MakerWorks-inspect
```

Relevant source files:

```text
src/OrcaSlicer.cpp
src/libslic3r/PrintConfig.cpp
src/CMakeLists.txt
build_release_vs2022.bat
```

- [x] ~~**Step 2: Confirm source CLI shape**~~

Source-confirmed command shape:

```powershell
orca-slicer --outputdir <job-output-dir> --slice 0 --export-3mf <output-file-name> [settings...] <input-model-file>
```

Source notes:

- `src/OrcaSlicer.cpp` help text: `Usage: orca-slicer [ OPTIONS ] [ file.3mf/file.stl ... ]`.
- `src/libslic3r/PrintConfig.cpp` defines `slice` as an int CLI action where `0` means all plates.
- `src/libslic3r/PrintConfig.cpp` defines `export_3mf` with CLI params `filename.3mf`.
- `src/libslic3r/PrintConfig.cpp` defines `outputdir` as the output directory.
- `src/CMakeLists.txt` and packaging config use `orca-slicer` / `orca-slicer.exe` as the installed command name.

- [ ] **Step 3: Locate or build the installed executable**

Run on the target PrintLab host:

```powershell
Get-Command orca-slicer -ErrorAction SilentlyContinue
Get-Command orcaslicer -ErrorAction SilentlyContinue
Get-ChildItem "C:\Program Files","$env:LOCALAPPDATA\Programs" -Recurse -Filter orca-slicer.exe -ErrorAction SilentlyContinue | Select-Object -First 5 -ExpandProperty FullName
```

Expected: one executable path, or a decision to install OrcaSlicer before continuing.

- [ ] **Step 4: Capture built Orca CLI help**

Run:

```powershell
& "C:\path\to\orca-slicer.exe" --help
```

Expected: help text matches the source-confirmed command shape.

- [x] ~~**Step 5: Write/update adapter command test**~~

In `tests/test_slicer.py`, update `test_orca_adapter_maps_common_settings_and_outputs()` so the expected command exactly matches the observed Orca CLI syntax.

- [x] ~~**Step 6: Run the focused failing/passing test**~~

Run:

```powershell
python -m pytest tests/test_slicer.py::test_orca_adapter_maps_common_settings_and_outputs -q --basetemp C:\tmp\pytest-printlab-slicer
```

Expected: fail before adapter changes if the current syntax is wrong, pass after the adapter is corrected.

- [x] ~~**Step 7: Run full slicer tests**~~

Run:

```powershell
python -m pytest tests/test_slicer.py -q --basetemp C:\tmp\pytest-printlab-slicer
```

Expected: all slicer tests pass.

### Task 8: Add Profile And Material Presets

**Files:**
- Modify: `app/slicer.py`
- Modify: `app/views.py`
- Modify: `tests/test_slicer.py`
- Modify: `tests/test_models.py`

- [x] ~~**Step 1: Add failing preset expansion test**~~

Add a test in `tests/test_slicer.py` that submits settings like:

```python
settings={"profile": "draft", "material": "PLA", "layer_height": 0.2, "infill": 15}
```

Expected behavior:

```python
assert command contains draft speed/layer defaults
assert command contains PLA nozzle/bed defaults
assert explicit layer_height and infill override preset defaults
```

- [x] ~~**Step 2: Implement preset expansion**~~

Add a small preset map in `app/slicer.py`:

```python
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
```

Merge order: profile defaults, material defaults, explicit user settings.

- [x] ~~**Step 3: Update UI tests**~~

In `tests/test_models.py`, assert the slicer page still renders `profileSelect`, `materialSelect`, and sends those fields in `currentSettings()`.

- [x] ~~**Step 4: Run focused tests**~~

Run:

```powershell
python -m pytest tests/test_slicer.py tests/test_models.py -q --basetemp C:\tmp\pytest-printlab-slicer
```

Expected: all focused tests pass.

### Task 9: Add Slicer Job Status Refresh

**Files:**
- Modify: `app/views.py`
- Modify: `tests/test_models.py`

- [x] ~~**Step 1: Add rendered UI expectations**~~

In `tests/test_models.py`, add assertions for:

```python
assert "refreshSlicerJob" in html
assert "/api/slicer/jobs/" in html
assert "activeSlicerJob" in html
```

- [x] ~~**Step 2: Implement refresh helper**~~

In `/slicer` JavaScript, add:

```javascript
async function refreshSlicerJob() {
  if (!activeSlicerJob?.id) return;
  const response = await fetch(`/api/slicer/jobs/${encodeURIComponent(activeSlicerJob.id)}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data?.detail || data?.error?.message || `HTTP ${response.status}`);
  renderSlicerJob(data.item || data);
}
```

- [x] ~~**Step 3: Add refresh affordance**~~

Add a small secondary button near the output panel:

```html
<button id="refreshSlicerJobBtn" class="btn secondary" type="button" onclick="refreshSlicerJob()" disabled>Refresh Slice</button>
```

Enable it after `renderSlicerJob()`.

- [x] ~~**Step 4: Run focused UI tests**~~

Run:

```powershell
python -m pytest tests/test_models.py::test_render_slicer_page_contains_printlab_workspace -q --basetemp C:\tmp\pytest-printlab-slicer
```

Expected: pass.

### Task 10: Add Artifact Download API

**Files:**
- Modify: `app/routers/api.py`
- Modify: `app/slicer.py`
- Modify: `tests/test_slicer.py`

- [x] ~~**Step 1: Add failing artifact download test**~~

In `tests/test_slicer.py`, create a slicer job with an output artifact and request:

```python
GET /api/slicer/jobs/{job_id}/artifacts/gcode_3mf/download
```

Expected:

```python
assert response.status_code == 200
assert response.content == b"real-orca-gcode-3mf"
assert response.headers["content-disposition"] contains "output.gcode.3mf"
```

- [x] ~~**Step 2: Add `SlicerService.artifact_path(job_id, kind)`**~~

Implementation rule: only return paths already recorded in the job's artifact list and still under the slicer job store.

- [x] ~~**Step 3: Add FastAPI route**~~

Add:

```python
@router.get("/api/slicer/jobs/{job_id}/artifacts/{kind}/download")
async def download_slicer_artifact(job_id: str, kind: str) -> FileResponse:
    path = slicer_service.artifact_path(job_id, kind)
    return FileResponse(path, filename=path.name)
```

- [x] ~~**Step 4: Run focused tests**~~

Run:

```powershell
python -m pytest tests/test_slicer.py -q --basetemp C:\tmp\pytest-printlab-slicer
```

Expected: pass.

### Task 11: Real Orca Smoke Test

**Files:**
- Optional Modify: `README.md`
- Optional Modify: `tests/test_slicer.py`

**2026-06-02 status:** FULU publishes Linux/Ubuntu builds. Release `v1.0.0` includes LinuxDir, AppImage, and `.deb` assets for Ubuntu 22.04 and 24.04. The LinuxDir archive contains `bin/orca-slicer`; PrintLab Docker images can optionally ingest it with `ORCA_LINUXDIR_URL`, extract it to `/opt/orca`, and expose `/usr/local/bin/orca-slicer` for existing PATH discovery. The Docker launcher sets `LD_LIBRARY_PATH=/opt/orca/bin` so bundled LinuxDir libraries are preferred.

Docker binary smoke evidence:

- Ubuntu 24.04 LinuxDir installs and `ldd` resolves after adding GTK/WebKit/GStreamer/OpenGL runtime libraries, but `orca-slicer --help`, `--info`, `--export-stl`, and `--slice 0 --export-3mf` exit with `139` in headless Docker.
- Ubuntu 22.04 LinuxDir also exits with `139` on `--info`.
- Ubuntu 24.04 `.deb` installs `orca-slicer-bmcu`, but the packaged binary also exits with `139` on `--info` after using its bundled library path.
- `xvfb-run` does not clear the crash.
- `gdb` shows the crash in `Slic3r::CLI::run(int, char**)`, not in PrintLab command construction.

An optional pytest harness exists at `tests/test_slicer.py::test_real_orca_binary_smoke_slices_sample_model`; it skips until one of the Orca binary env vars points to an existing executable. Do not mark the real Orca smoke task complete until an Orca build passes a real slice in the target Docker/Unraid image.

- [ ] **Step 1: Configure Orca binary locally**

Set in `.env` or shell:

```powershell
$env:ORCASLICER_BINARY="C:\path\to\OrcaSlicer.exe"
```

- [ ] **Step 2: Start PrintLab**

Run:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

- [ ] **Step 3: Verify capabilities**

Run:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8010/api/slicer/capabilities
```

Expected: `engine_status.ready` is `true`.

- [ ] **Step 4: Slice a known sample model**

Open `/makerworks-routing`, choose a routing job, click `Open Slicer`, click `Slice`, then `Save To Routing`.

Expected:

- Orca command completes.
- Output artifact is non-empty.
- Routing job shows a saved slicer artifact.
- `Route To Printer` appears after connecting the job to a printer.

- [ ] **Step 5: Capture evidence**

Record:

- Orca binary path.
- Slicer job id.
- Output artifact path.
- Any stdout/stderr from Orca.
- Screenshot path if using browser verification.

### Task 12: Final Verification And Commit

**Files:**
- All touched files.

- [x] ~~**Step 1: Run Ruff**~~

Run:

```powershell
python -m ruff check app tests
```

Expected: `All checks passed!`

- [x] ~~**Step 2: Run full tests**~~

Run:

```powershell
python -m pytest -q --basetemp C:\tmp\pytest-printlab-slicer
```

Expected: all tests pass.

- [x] ~~**Step 3: Confirm branch and diff**~~

Run:

```powershell
git status --short --branch
git diff --stat
```

Expected: branch is `dev`; diff contains only slicer integration files and this plan.

- [ ] **Step 4: Commit**

Run:

```powershell
git add app/slicer.py app/routers/api.py app/routers/ui.py app/services.py app/views.py app/dashboard.html tests/test_slicer.py tests/test_models.py tests/test_queue.py .env.example README.md docs/superpowers/plans/2026-06-02-printlab-orca-slicer-integration.md
git commit -m "slicer integration"
```

Expected: commit created on `dev`.

---

## Verification Commands Used So Far

- ~~`python -m pytest tests/test_slicer.py -q --basetemp C:\tmp\pytest-printlab-slicer`~~
- ~~`python -m pytest tests/test_slicer.py tests/test_models.py tests/test_queue.py -q --basetemp C:\tmp\pytest-printlab-slicer`~~
- ~~`python -m pytest -q --basetemp C:\tmp\pytest-printlab-slicer`~~
- ~~`python -m ruff check app tests`~~
- ~~Live smoke checks against `/slicer`, `/makerworks-routing`, and `/api/slicer/capabilities` on `127.0.0.1:8010`.~~

---

## Current Notes

- PrintLab is intentionally using Orca as an installed slicing engine, not vendoring Orca source into this repo.
- Real Orca CLI syntax still needs confirmation against the installed OrcaSlicer binary on the target machine.
- The current adapter command shape is tested, but may need adjustment once real Orca CLI help is captured.
- The saved output artifact is the source of truth for routing to a printer after slicing.
