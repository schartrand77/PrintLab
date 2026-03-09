from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.auth import auth_router, register_admin_auth, validate_auth_configuration
from app.routers.api import router as api_router
from app.routers.ui import router as ui_router
from app.runtime import start_runtime, stop_runtime
from app.services import data_root
from app.views import static_dir


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await start_runtime()
    try:
        yield
    finally:
        await stop_runtime()


def create_app() -> FastAPI:
    validate_auth_configuration()
    app = FastAPI(
        title="PrintLab",
        version="0.1.0",
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        swagger_ui_parameters={"displayRequestDuration": True, "defaultModelsExpandDepth": -1},
        lifespan=lifespan,
    )

    register_admin_auth(app)
    app.mount("/data", StaticFiles(directory=str(data_root())), name="data")
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(auth_router)
    app.include_router(ui_router)
    app.include_router(api_router)

    @app.get("/openapi.json/export", include_in_schema=False)
    async def export_openapi() -> dict[str, object]:
        spec = app.openapi()
        output = data_root() / "openapi.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        return {"ok": True, "path": str(output)}

    return app


app = create_app()
