from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import get_bool, get_env

SESSION_COOKIE_NAME = "printlab_session"
CSRF_COOKIE_NAME = "printlab_csrf"
CSRF_HEADER_NAME = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class AuthConfig:
    enabled: bool
    require_auth: bool
    username: str
    password: str
    session_secret: str
    session_ttl_seconds: int
    cookie_secure: bool
    cookie_domain: str | None


def _auth_config() -> AuthConfig:
    username = get_env("ADMIN_USERNAME", "admin") or "admin"
    password = get_env("ADMIN_PASSWORD", "")
    require_auth = get_bool("REQUIRE_AUTH", False)
    enabled = bool(password)
    session_secret = get_env("SESSION_SECRET", "") or hashlib.sha256(f"{username}:{password}".encode("utf-8")).hexdigest()
    ttl_raw = get_env("SESSION_TTL_SECONDS", "1800") or "1800"
    try:
        ttl_seconds = max(300, min(86400, int(ttl_raw)))
    except ValueError:
        ttl_seconds = 1800
    cookie_domain = get_env("SESSION_COOKIE_DOMAIN", "") or None
    return AuthConfig(
        enabled=enabled,
        require_auth=require_auth,
        username=username,
        password=password,
        session_secret=session_secret,
        session_ttl_seconds=ttl_seconds,
        cookie_secure=get_bool("SESSION_COOKIE_SECURE", False),
        cookie_domain=cookie_domain,
    )


def validate_auth_configuration() -> None:
    config = _auth_config()
    if config.require_auth and (not config.username.strip() or not config.password.strip()):
        raise RuntimeError("REQUIRE_AUTH is enabled but ADMIN_USERNAME or ADMIN_PASSWORD is not configured.")


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


def _session_signer(secret_value: str, payload: bytes) -> str:
    return hmac.new(secret_value.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _encode_session(username: str, csrf_token: str, expires_at: int, *, secret_value: str) -> str:
    payload = json.dumps({"u": username, "csrf": csrf_token, "exp": expires_at}, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload).decode("ascii")
    signature = _session_signer(secret_value, payload)
    return f"{payload_b64}.{signature}"


def _decode_session(raw_value: str | None, *, secret_value: str) -> dict[str, object] | None:
    if not raw_value or "." not in raw_value:
        return None
    payload_b64, signature = raw_value.split(".", 1)
    try:
        payload = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
    except (ValueError, binascii.Error):
        return None
    expected = _session_signer(secret_value, payload)
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        if int(data.get("exp", 0)) <= int(time.time()):
            return None
    except (TypeError, ValueError):
        return None
    return data


def _valid_basic_credentials(request: Request, config: AuthConfig) -> str | None:
    credentials = parse_basic_auth(request.headers.get("authorization"))
    if credentials is None:
        return None
    username, password = credentials
    if hmac.compare_digest(username, config.username) and hmac.compare_digest(password, config.password):
        return username
    return None


def _valid_session(request: Request, config: AuthConfig) -> tuple[str, dict[str, object]] | None:
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    session = _decode_session(raw, secret_value=config.session_secret)
    if session is None:
        return None
    username = str(session.get("u") or "").strip()
    if not username:
        return None
    return username, session


def actor_from_request(request: Request) -> str:
    actor = getattr(request.state, "auth_user", None)
    if isinstance(actor, str) and actor.strip():
        return actor.strip()
    credentials = parse_basic_auth(request.headers.get("authorization"))
    if credentials is not None:
        username, _password = credentials
        if username.strip():
            return username.strip()
    return "dashboard"


def _is_makerworks_boundary_request(path: str) -> bool:
    return path == "/api/works/makerworks/jobs" or path.startswith("/api/works/makerworks/jobs/")


def _valid_makerworks_boundary_auth(request: Request) -> str | None:
    bearer_token = get_env("MAKERWORKS_SUBMIT_BEARER_TOKEN", "")
    api_key = get_env("MAKERWORKS_SUBMIT_API_KEY", "")
    auth_header = get_env("MAKERWORKS_SUBMIT_AUTH_HEADER", "X-API-Key") or "X-API-Key"

    authorization = request.headers.get("authorization", "")
    if bearer_token and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token and hmac.compare_digest(token, bearer_token):
            return "makerworks"

    if api_key:
        supplied = request.headers.get(auth_header, "").strip()
        if supplied and hmac.compare_digest(supplied, api_key):
            return "makerworks"

    return None


def _clear_auth_cookies(response: Response, config: AuthConfig) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", domain=config.cookie_domain)
    response.delete_cookie(CSRF_COOKIE_NAME, path="/", domain=config.cookie_domain)


def _set_auth_cookies(response: Response, *, username: str, config: AuthConfig) -> dict[str, object]:
    csrf_token = secrets.token_urlsafe(24)
    expires_at = int(time.time()) + config.session_ttl_seconds
    session_value = _encode_session(username, csrf_token, expires_at, secret_value=config.session_secret)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_value,
        max_age=config.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=config.cookie_secure,
        path="/",
        domain=config.cookie_domain,
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        max_age=config.session_ttl_seconds,
        httponly=False,
        samesite="lax",
        secure=config.cookie_secure,
        path="/",
        domain=config.cookie_domain,
    )
    return {"csrf_token": csrf_token, "expires_at": expires_at}


def _login_html(next_path: str) -> str:
    safe_next = json.dumps(next_path)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PrintLab Login</title>
  <style>
    :root {{
      --bg: linear-gradient(160deg, #eef4fb 0%, #d7e6f7 100%);
      --panel: rgba(255,255,255,.94);
      --text: #183149;
      --muted: #5f768e;
      --accent: #1f4f7b;
      --border: #c8d9eb;
      --shadow: 0 28px 70px rgba(24,49,73,.18);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: var(--bg); color: var(--text); font-family: "Segoe UI", sans-serif; }}
    .panel {{ width: min(420px, calc(100vw - 32px)); background: var(--panel); border: 1px solid var(--border); border-radius: 20px; padding: 28px; box-shadow: var(--shadow); }}
    h1 {{ margin: 0 0 8px; }}
    p {{ margin: 0 0 18px; color: var(--muted); }}
    label {{ display: block; margin: 0 0 6px; font-size: 13px; font-weight: 600; }}
    input {{ width: 100%; margin: 0 0 14px; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--border); font-size: 15px; }}
    button {{ width: 100%; border: 0; border-radius: 12px; padding: 12px 14px; background: var(--accent); color: #fff; font-size: 15px; font-weight: 700; cursor: pointer; }}
    #status {{ min-height: 20px; margin-top: 12px; color: #9d2d2d; font-size: 13px; }}
  </style>
</head>
<body>
  <form class="panel" id="loginForm">
    <h1>PrintLab</h1>
    <p>Sign in to access the dashboard and API.</p>
    <label for="username">Username</label>
    <input id="username" name="username" autocomplete="username" required>
    <label for="password">Password</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required>
    <button type="submit">Sign In</button>
    <div id="status" role="alert"></div>
  </form>
  <script>
    const nextPath = {safe_next};
    document.getElementById("loginForm").addEventListener("submit", async (event) => {{
      event.preventDefault();
      const status = document.getElementById("status");
      status.textContent = "";
      const username = document.getElementById("username").value.trim();
      const password = document.getElementById("password").value;
      try {{
        const response = await fetch("/auth/login", {{
          method: "POST",
          headers: {{ "content-type": "application/json" }},
          body: JSON.stringify({{ username, password }})
        }});
        const payload = await response.json().catch(() => ({{}}));
        if (!response.ok) {{
          throw new Error(payload.detail || `HTTP ${{response.status}}`);
        }}
        window.location.assign(nextPath || "/");
      }} catch (error) {{
        status.textContent = String(error?.message || error);
      }}
    }});
  </script>
</body>
</html>"""


auth_router = APIRouter(include_in_schema=False)


@auth_router.get("/login", response_class=HTMLResponse)
async def login_page(next: str = "/") -> str:
    return _login_html(next if next.startswith("/") else "/")


@auth_router.post("/auth/login")
async def login_endpoint(request: Request) -> JSONResponse:
    config = _auth_config()
    if not config.enabled:
        return JSONResponse(status_code=400, content={"detail": "Authentication is not configured."})
    payload = await request.json()
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not (hmac.compare_digest(username, config.username) and hmac.compare_digest(password, config.password)):
        response = JSONResponse(status_code=401, content={"detail": "Invalid credentials."})
        _clear_auth_cookies(response, config)
        return response
    response = JSONResponse(content={"ok": True, "username": username, "ttl_seconds": config.session_ttl_seconds})
    _set_auth_cookies(response, username=username, config=config)
    return response


@auth_router.post("/auth/logout")
async def logout_endpoint() -> JSONResponse:
    config = _auth_config()
    response = JSONResponse(content={"ok": True})
    _clear_auth_cookies(response, config)
    return response


@auth_router.get("/auth/session")
async def session_endpoint(request: Request) -> JSONResponse:
    config = _auth_config()
    session_match = _valid_session(request, config)
    if not config.enabled:
        return JSONResponse(content={"auth_enabled": False, "authenticated": True, "username": None, "csrf_token": None})
    if session_match is None:
        return JSONResponse(content={"auth_enabled": True, "authenticated": False, "username": None, "csrf_token": None}, status_code=401)
    username, session = session_match
    return JSONResponse(
        content={
            "auth_enabled": True,
            "authenticated": True,
            "username": username,
            "csrf_token": session.get("csrf"),
            "expires_at": session.get("exp"),
            "ttl_seconds": config.session_ttl_seconds,
        }
    )


def register_admin_auth(app: FastAPI) -> None:
    @app.middleware("http")
    async def admin_auth_middleware(request: Request, call_next):
        config = _auth_config()
        request.state.auth_user = None
        request.state.auth_scheme = None

        if not config.enabled and not config.require_auth:
            return await call_next(request)

        path = request.url.path
        if path in {"/login", "/auth/login", "/auth/session"}:
            return await call_next(request)

        if _is_makerworks_boundary_request(path):
            makerworks_user = _valid_makerworks_boundary_auth(request)
            if makerworks_user is not None:
                request.state.auth_user = makerworks_user
                request.state.auth_scheme = "makerworks"
                return await call_next(request)

        basic_user = _valid_basic_credentials(request, config) if config.enabled else None
        if basic_user is not None:
            request.state.auth_user = basic_user
            request.state.auth_scheme = "basic"
            return await call_next(request)

        session_match = _valid_session(request, config) if config.enabled else None
        if session_match is not None:
            session_user, session_payload = session_match
            if request.method.upper() not in SAFE_METHODS:
                csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME, "")
                csrf_header = request.headers.get(CSRF_HEADER_NAME, "")
                csrf_session = str(session_payload.get("csrf") or "")
                if not csrf_cookie or not csrf_header or not csrf_session:
                    return JSONResponse(status_code=403, content={"detail": "CSRF token required."})
                if not (hmac.compare_digest(csrf_cookie, csrf_header) and hmac.compare_digest(csrf_cookie, csrf_session)):
                    return JSONResponse(status_code=403, content={"detail": "CSRF token mismatch."})
            request.state.auth_user = session_user
            request.state.auth_scheme = "session"
            return await call_next(request)

        wants_html = request.method.upper() == "GET" and "text/html" in request.headers.get("accept", "").lower()
        if wants_html:
            target = quote(request.url.path or "/", safe="/")
            if request.url.query:
                target = f"{target}%3F{quote(request.url.query, safe='=&')}"
            return RedirectResponse(url=f"/login?next={target}", status_code=303)

        return Response(
            content="Unauthorized",
            status_code=401,
            headers={
                "WWW-Authenticate": 'Basic realm="PrintLab Admin"',
                "Cache-Control": "no-store",
            },
        )
