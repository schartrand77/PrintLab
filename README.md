# PrintLab

Standalone Docker app for Bambu printers that uses `pybambu` from
[`greghesp/ha-bambulab`](https://github.com/greghesp/ha-bambulab).

This is **not** Home Assistant. It runs as a direct web/API service.

## What it provides

- Direct MQTT connection to your printer (LAN mode / local MQTT by default).
- Simple web dashboard at `http://localhost:8080`.
- REST API for status and control actions.
- Pause / resume / stop, refresh state, chamber light control, fan and temperature control.

## Quick start

1. Copy `.env.example` to `.env` and fill in:
   - `PRINTER_HOST`
   - `PRINTER_SERIAL`
   - `PRINTER_ACCESS_CODE`
2. Build and run:

```bash
docker compose up -d --build
```

3. Open:

```text
http://localhost:8080
```

## API endpoints

- `GET /health`
- `GET /api/state`
- `POST /api/actions/pause`
- `POST /api/actions/resume`
- `POST /api/actions/stop`
- `POST /api/actions/refresh`
- `POST /api/actions/chamber-light` with `{"on": true|false}`
- `POST /api/actions/fan` with `{"fan":"part_cooling|auxiliary|chamber|heatbreak|secondary_auxiliary","percent":0-100}`
- `POST /api/actions/temperature` with `{"target":"heatbed|nozzle","value":0-320}`

## Notes

- Image build pulls `pybambu` from `ha-bambulab` at build time.
- The UI is intentionally minimal; use the API for automation and advanced control.
