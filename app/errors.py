from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import requests
from fastapi import HTTPException


@dataclass
class ApiError(Exception):
    code: str
    message: str
    status_code: int = 400
    details: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload = {"error": {"code": self.code, "message": self.message}}
        if self.details:
            payload["error"]["details"] = self.details
        return payload


def api_error(code: str, message: str, status_code: int = 400, **details: Any) -> ApiError:
    clean_details = {key: value for key, value in details.items() if value is not None}
    return ApiError(code=code, message=message, status_code=status_code, details=clean_details)


def from_http_exception(exc: HTTPException) -> ApiError:
    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("code") or f"http_{exc.status_code}")
        message = str(detail.get("message") or detail.get("detail") or "Request failed.")
        details = {key: value for key, value in detail.items() if key not in {"code", "message", "detail"}}
        return api_error(code, message, exc.status_code, **details)
    if isinstance(detail, str):
        return api_error(f"http_{exc.status_code}", detail, exc.status_code)
    return api_error(f"http_{exc.status_code}", "Request failed.", exc.status_code)


def from_exception(exc: Exception) -> ApiError:
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, HTTPException):
        return from_http_exception(exc)
    if isinstance(exc, PermissionError):
        return api_error("permission_denied", str(exc) or "Permission denied.", 403)
    if isinstance(exc, KeyError):
        return api_error("not_found", str(exc).strip("'") or "Record not found.", 404)
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, requests.Timeout)):
        return api_error("upstream_timeout", str(exc) or "Upstream request timed out.", 504)
    if isinstance(exc, (ConnectionError, requests.ConnectionError)):
        return api_error("upstream_unavailable", str(exc) or "Upstream service unavailable.", 503)
    if isinstance(exc, ValueError):
        return api_error("validation_error", str(exc) or "Invalid request.", 400)
    return api_error("internal_error", str(exc) or "Internal server error.", 500)

