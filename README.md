# PrintLab

Standalone Docker app for Bambu printers that uses `pybambu` from
[`greghesp/ha-bambulab`](https://github.com/greghesp/ha-bambulab).

This is **not** Home Assistant. It runs as a direct web/API service.

## What it provides

- Direct MQTT connection to your printer (LAN mode / local MQTT by default).
- Multi-printer gallery dashboard at `http://localhost:8080`.
- Printer detail dashboard at `http://localhost:8080/printer/{printer_id}`.
- REST API for status and control actions.
- Pause / resume / stop, refresh state, chamber light control, fan and temperature control.

## Quick start

1. Copy `.env.example` to `.env` and fill in either:
   - single-printer `PRINTER_HOST` / `PRINTER_SERIAL` / `PRINTER_ACCESS_CODE`
   - or `PRINTERS_JSON` with multiple printers
2. If using single-printer mode, fill in:
   - `PRINTER_HOST`
   - `PRINTER_SERIAL`
   - `PRINTER_ACCESS_CODE`
3. Build and run:

```bash
docker compose up -d --build
```

3. Open:

```text
http://localhost:8080
```

## API endpoints

- `GET /health`
- `GET /api/printers`
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
- `POST /api/works/{makerworks|orderworks|stockworks}/request`
  with:
  `{"method":"GET|POST|PUT|PATCH|DELETE","path":"/v1/resource","query":{},"body":{},"headers":{},"timeout_seconds":20}`
- `POST /api/works/orderworks/print-job`
  with:
  `{"file_path":"/cache/model.3mf","plate_gcode":"Metadata/plate_1.gcode","use_ams":true,"ams_mapping":[0]}`
  (optional query: `?printer_id={printer_id}`)

## Works integration config

Configure each external system in `.env`:

- `MAKERWORKS_BASE_URL`, `MAKERWORKS_API_KEY`, `MAKERWORKS_BEARER_TOKEN`, `MAKERWORKS_AUTH_HEADER`, `MAKERWORKS_VERIFY_SSL`
- `ORDERWORKS_BASE_URL`, `ORDERWORKS_API_KEY`, `ORDERWORKS_BEARER_TOKEN`, `ORDERWORKS_AUTH_HEADER`, `ORDERWORKS_VERIFY_SSL`
- `STOCKWORKS_BASE_URL`, `STOCKWORKS_API_KEY`, `STOCKWORKS_BEARER_TOKEN`, `STOCKWORKS_AUTH_HEADER`, `STOCKWORKS_VERIFY_SSL`

Auth behavior:
- If `*_API_KEY` is set, it is sent as `*_AUTH_HEADER` (default `X-API-Key`).
- If `*_BEARER_TOKEN` is set, it is sent as `Authorization: Bearer ...`.

Stockworks enrichment:
- Responses from `GET /api/works/stockworks/health` and `POST /api/works/stockworks/request`
  include `printer_filament` with:
  - `loaded_filament` (active AMS slot/type/color/remaining_percent)
  - `remaining_filament` (all visible AMS slots + remaining percentages)

## Notes

- Image build pulls `pybambu` from `ha-bambulab` at build time.
- The UI is intentionally minimal; use the API for automation and advanced control.
