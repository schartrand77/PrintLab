from __future__ import annotations

import base64
import binascii
import hmac
import os

from fastapi import FastAPI, Request, Response


def get_admin_username() -> str:
    return os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"


def get_admin_password() -> str:
    return os.getenv("ADMIN_PASSWORD", "").strip()


def parse_basic_auth(authorization: str | None) -> tuple[str, str] | None:
    if not authorization:
        return None
    if not authorization.lower().startswith("basic "):
        return None
    token = authorization[6:].strip()
    if not token:
        return None
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    if ":" not in decoded:
        return None
    username, password = decoded.split(":", 1)
    return username, password


def actor_from_request(request: Request) -> str:
    credentials = parse_basic_auth(request.headers.get("authorization"))
    if credentials is not None:
        username, _password = credentials
        if username.strip():
            return username.strip()
    return "dashboard"


def register_admin_auth(app: FastAPI) -> None:
    @app.middleware("http")
    async def admin_auth_middleware(request: Request, call_next):
        admin_password = get_admin_password()
        if not admin_password:
            return await call_next(request)

        credentials = parse_basic_auth(request.headers.get("authorization"))
        if credentials is not None:
            username, password = credentials
            if hmac.compare_digest(username, get_admin_username()) and hmac.compare_digest(password, admin_password):
                return await call_next(request)

        return Response(
            content="Unauthorized",
            status_code=401,
            headers={
                "WWW-Authenticate": 'Basic realm="PrintLab Admin"',
                "Cache-Control": "no-store",
            },
        )
