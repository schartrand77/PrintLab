# PrintLab

Standalone Docker app for Bambu printers that uses `pybambu` from
[`greghesp/ha-bambulab`](https://github.com/greghesp/ha-bambulab).

This is **not** Home Assistant. It runs as a direct web/API service.

## What it provides

- Direct MQTT connection to your printer (LAN mode / local MQTT by default).
- Multi-printer gallery dashboard at `http://localhost:8080`.
- Printer detail dashboard at `http://localhost:8080/printer/{printer_id}`.
- Required auth by default in container images, with signed cookie sessions for the web UI.
- REST API for status and control actions.
- Pause / resume / stop, refresh state, chamber light control, fan and temperature control.

## Quick start

1. Copy `.env.example` to `.env` and fill in either:
   - single-printer `PRINTER_HOST` / `PRINTER_SERIAL` / `PRINTER_ACCESS_CODE`
   - or `PRINTERS_JSON` with multiple printers
2. Set admin credentials:
   - `REQUIRE_AUTH=true` is the image default and startup fails if credentials are missing
   - `ADMIN_USERNAME` (default: `admin`)
   - `ADMIN_PASSWORD`
   - optional `SESSION_SECRET` to override the cookie signing secret
3. If using single-printer mode, fill in:
   - `PRINTER_HOST`
   - `PRINTER_SERIAL`
   - `PRINTER_ACCESS_CODE`
4. Build and run:

```bash
docker compose up -d --build
```

3. Open:

```text
http://localhost:8080
```

## API endpoints

Interactive API docs are published at:

- `GET /docs`
- `GET /redoc`
- `GET /openapi.json`
- `GET /openapi.json/export` to persist the current schema to `data/openapi.json`
- `GET /login`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/session`

- `GET /health`
- `GET /api/printers`
- `POST /api/printers`
  with:
  `{"name":"X1C-002","host":"192.168.1.67","serial":"SERIAL","access_code":"CODE","id":"x1c-002"}`
- `GET /api/state`
- `GET /api/printers/{printer_id}/state`
- `POST /api/actions/pause`
- `POST /api/actions/resume`
- `POST /api/actions/stop`
- `POST /api/actions/refresh`
- `POST /api/actions/chamber-light` with `{"on": true|false}`
- `POST /api/actions/fan` with `{"fan":"part_cooling|auxiliary|chamber|heatbreak|secondary_auxiliary","percent":0-100}`
- `POST /api/actions/temperature` with `{"target":"heatbed|nozzle","value":0-320}`
- `POST /api/printers/{printer_id}/actions/...` (printer-scoped equivalents for all action endpoints)
- `GET /api/works/services`
- `GET /api/works/{makerworks|orderworks|stockworks}/health?path=/health`
- `GET /api/works/makerworks/library`
- `GET /api/works/makerworks/library/{model_id}`
- `POST /api/works/makerworks/jobs`
  with:
  `{"model_id":"widget-1","printer_id":"printer-1","idempotency_key":"mw-job-123","source_job_id":"makerworks-123","metadata":{"priority":"rush"}}`
- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/sync-makerworks`
- `GET /api/printers/{printer_id}/jobs`
- `GET /api/printers/{printer_id}/jobs/{job_id}`
- `POST /api/printers/{printer_id}/jobs/{job_id}/sync-makerworks`
- `POST /api/works/{makerworks|orderworks|stockworks}/request`
  with:
  `{"method":"GET|POST|PUT|PATCH|DELETE","path":"/v1/resource","query":{},"body":{},"headers":{},"timeout_seconds":20}`
- `POST /api/works/orderworks/print-job`
  with:
  `{"file_path":"/cache/model.3mf","plate_gcode":"Metadata/plate_1.gcode","use_ams":true,"ams_mapping":[0]}`
  (optional query: `?printer_id={printer_id}`)
- `GET /api/printers/{printer_id}/works/...`
  printer-scoped equivalents for `health`, `request`, MakerWorks library browsing, and `orderworks/print-job`
- `GET /api/successful-gcodes`
- `GET /api/printers/{printer_id}/successful-gcodes`
- `POST /api/successful-gcodes/{record_id}/sync-makerworks`
- `POST /api/printers/{printer_id}/successful-gcodes/{record_id}/sync-makerworks`

## Works integration config

Configure each external system in `.env`:

- `MAKERWORKS_BASE_URL`, `MAKERWORKS_API_KEY`, `MAKERWORKS_BEARER_TOKEN`, `MAKERWORKS_AUTH_HEADER`, `MAKERWORKS_VERIFY_SSL`, `MAKERWORKS_ALLOWED_PATHS`, `MAKERWORKS_ALLOWED_METHODS`
- Optional MakerWorks job callbacks:
  `MAKERWORKS_JOB_CALLBACK_ENABLED`, `MAKERWORKS_JOB_CALLBACK_METHOD`, `MAKERWORKS_JOB_CALLBACK_PATH_TEMPLATE`
- MakerWorks library normalization:
  `MAKERWORKS_LIBRARY_LIST_PATH`, `MAKERWORKS_LIBRARY_DETAIL_PATH_TEMPLATE`, `MAKERWORKS_LIBRARY_SEARCH_PARAM`, `MAKERWORKS_LIBRARY_PAGE_PARAM`, `MAKERWORKS_LIBRARY_PAGE_SIZE_PARAM`, `MAKERWORKS_LIBRARY_PAGE_SIZE`, `MAKERWORKS_LIBRARY_ITEMS_PATH`, `MAKERWORKS_LIBRARY_TOTAL_PATH`, `MAKERWORKS_LIBRARY_ID_PATH`, `MAKERWORKS_LIBRARY_NAME_PATH`, `MAKERWORKS_LIBRARY_SUMMARY_PATH`, `MAKERWORKS_LIBRARY_DESCRIPTION_PATH`, `MAKERWORKS_LIBRARY_THUMBNAIL_PATH`, `MAKERWORKS_LIBRARY_MODEL_URL_PATH`, `MAKERWORKS_LIBRARY_DOWNLOAD_URL_PATH`, `MAKERWORKS_LIBRARY_AUTHOR_PATH`, `MAKERWORKS_LIBRARY_TAGS_PATH`, `MAKERWORKS_LIBRARY_FILES_PATH`, `MAKERWORKS_LIBRARY_CREATED_AT_PATH`, `MAKERWORKS_LIBRARY_UPDATED_AT_PATH`
- `ORDERWORKS_BASE_URL`, `ORDERWORKS_API_KEY`, `ORDERWORKS_BEARER_TOKEN`, `ORDERWORKS_AUTH_HEADER`, `ORDERWORKS_VERIFY_SSL`, `ORDERWORKS_ALLOWED_PATHS`, `ORDERWORKS_ALLOWED_METHODS`
- `STOCKWORKS_BASE_URL`, `STOCKWORKS_API_KEY`, `STOCKWORKS_BEARER_TOKEN`, `STOCKWORKS_AUTH_HEADER`, `STOCKWORKS_VERIFY_SSL`, `STOCKWORKS_ALLOWED_PATHS`, `STOCKWORKS_ALLOWED_METHODS`

Auth behavior:
- Browser UI auth uses `POST /auth/login`, an HttpOnly signed session cookie, a non-HttpOnly CSRF cookie, and `X-CSRF-Token` on mutating requests.
- Basic Auth still works for API clients.
- If `*_API_KEY` is set, it is sent as `*_AUTH_HEADER` (default `X-API-Key`).
- If `*_BEARER_TOKEN` is set, it is sent as `Authorization: Bearer ...`.
- `*_ALLOWED_PATHS` is a comma-separated prefix allowlist. Requests outside the list are rejected.
- `*_ALLOWED_METHODS` is optional. If set, only those methods are proxied.
- All env vars also support Docker-style file-based secrets via `*_FILE`.

MakerWorks library notes:
- The dashboard now has a `MakerWorks` tab inside the model library modal.
- Responses are normalized into a stable shape (`id`, `name`, `summary`, `thumbnail_url`, `model_url`, `download_url`, `author`, `tags`, `printer_handoff_ready`) so the UI does not need to match your upstream schema exactly.
- This pass is read-only for external models: it surfaces whether downloadable assets exist, and leaves the actual printer handoff as the next step.

MakerWorks job intake:
- `POST /api/works/makerworks/jobs` is the new PrintLab-native submission path for MakerWorks.
- PrintLab stages the asset to printer storage, creates a queue entry, and persists a submitted-job ledger in `/data/submitted_jobs_{printer_id}.json`.
- Use `idempotency_key` when MakerWorks may retry the same submission; PrintLab will return the existing job record instead of queueing a duplicate.
- Job status currently advances through `queued`, `started`, `completed`, `failed`, `cancelled`, and `submit_failed`.
- If `MAKERWORKS_JOB_CALLBACK_ENABLED=true`, each new status is pushed back to MakerWorks once using `MAKERWORKS_JOB_CALLBACK_PATH_TEMPLATE`.

MakerWorks callback contract:
- Recommended callback path template: `/api/printlab/jobs/{job_id}` or `/api/printlab/jobs/{job_id}/status`.
- Default method: `POST`.
- Template variables available in `MAKERWORKS_JOB_CALLBACK_PATH_TEMPLATE`:
  `{job_id}`, `{printer_id}`, `{model_id}`, `{source_job_id}`, `{source_order_id}`, `{status}`.
- Callback payload shape:
  `{"job_id":"...","status":"queued|started|completed|failed|cancelled|submit_failed","printer_id":"...","printer_name":"...","queue_item_id":"...","successful_gcode_id":"...","idempotency_key":"...","source":"makerworks","source_job_id":"...","source_order_id":"...","model_id":"...","model_name":"...","model_url":"...","download_url":"...","file_path":"...","file_name":"...","plate_gcode":"...","start_at":"...","started_at":"...","completed_at":"...","last_error":"...","metadata":{},"history":[],"updated_at":"...","created_at":"..."}`

Successful G-code tracking:
- Every completed print that reaches `FINISH` or `COMPLETE` is persisted to `/data/successful_gcodes_{printer_id}.json`.
- SD-card model listings are enriched with successful G-code counts and latest MakerWorks sync status.
- Optional automatic MakerWorks attachment can be enabled with:
  - `MAKERWORKS_ATTACH_GCODE_ENABLED=true`
  - `MAKERWORKS_ATTACH_GCODE_METHOD=POST`
  - `MAKERWORKS_ATTACH_GCODE_PATH_TEMPLATE=/models/{model_id}/gcodes`
- The attachment payload includes printer, model, file, plate, AMS, and completion metadata. `model_id` is inferred from a leading numeric filename prefix such as `20906356-widget_plate_1.3mf`.

Stockworks enrichment:
- Responses from `GET /api/works/stockworks/health` and `POST /api/works/stockworks/request`
  include `printer_filament` with:
  - `loaded_filament` (active AMS slot/type/color/remaining_percent)
  - `remaining_filament` (all visible AMS slots + remaining percentages)

## Quality and SDK workflow

- Install dev tooling with `pip install -r requirements.txt -r requirements-dev.txt`
- Run `ruff check app tests scripts`
- Run `mypy`
- Run `pytest`
- Export the schema with `python scripts/export_openapi.py`
- Optionally generate a typed client with `pwsh scripts/generate_client.ps1`

## Notes

- Image build pulls `pybambu` from `ha-bambulab` at build time.
- The UI is intentionally minimal; use the API for automation and advanced control.
- Printers added from the UI/API are persisted to `/data/printers_added.json`.
