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

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import get_bool, get_env

SESSION_COOKIE_NAME = "printlab_session"
CSRF_COOKIE_NAME = "printlab_csrf"
CSRF_HEADER_NAME = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}
ROLE_PERMISSIONS = {
    "viewer": ["dashboard:read", "printer:read", "queue:read", "audit:read"],
    "operator": ["dashboard:read", "printer:read", "queue:read", "audit:read", "printer:operate", "queue:write", "job:write"],
    "admin": [
        "dashboard:read",
        "printer:read",
        "queue:read",
        "audit:read",
        "printer:operate",
        "queue:write",
        "job:write",
        "printer:manage",
        "integration:manage",
        "auth:manage",
    ],
}


@dataclass(frozen=True)
class AuthUser:
    username: str
    email: str | None
    password_hash: str
    role: str


@dataclass(frozen=True)
class AuthConfig:
    enabled: bool
    require_auth: bool
    users: tuple[AuthUser, ...]
    session_secret: str
    session_ttl_seconds: int
    cookie_secure: bool
    cookie_domain: str | None


def normalize_role(role: str | None, default: str = "viewer") -> str:
    normalized = str(role or default).strip().lower()
    return normalized if normalized in ROLE_RANK else default


def permissions_for_role(role: str | None) -> list[str]:
    normalized = normalize_role(role)
    return list(ROLE_PERMISSIONS.get(normalized, ROLE_PERMISSIONS["viewer"]))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
    derived_b64 = base64.urlsafe_b64encode(derived).decode("ascii")
    return f"scrypt$16384$8$1${salt_b64}${derived_b64}"


def _parse_password_hash(password_hash: str) -> tuple[int, int, int, bytes, bytes]:
    try:
        algorithm, n_raw, r_raw, p_raw, salt_b64, derived_b64 = password_hash.split("$", 5)
        if algorithm != "scrypt":
            raise ValueError("Unsupported password hash algorithm.")
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        derived = base64.urlsafe_b64decode(derived_b64.encode("ascii"))
        return int(n_raw), int(r_raw), int(p_raw), salt, derived
    except (ValueError, binascii.Error) as exc:
        raise RuntimeError("Invalid password hash format.") from exc


def verify_password(password: str, password_hash: str) -> bool:
    n_value, r_value, p_value, salt, expected = _parse_password_hash(password_hash)
    actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n_value, r=r_value, p=p_value, dklen=len(expected))
    return hmac.compare_digest(actual, expected)


def _load_auth_users() -> tuple[AuthUser, ...]:
    allow_legacy_plaintext = get_bool("ALLOW_LEGACY_PLAINTEXT_PASSWORDS", False)
    raw = get_env("AUTH_USERS_JSON", "")
    users: list[AuthUser] = []
    if raw:
        try:
            payload = json.loads(raw)
            if not isinstance(payload, list):
                raise ValueError("AUTH_USERS_JSON must be a JSON array.")
            for entry in payload:
                if not isinstance(entry, dict):
                    continue
                username = str(entry.get("username") or "").strip()
                email = str(entry.get("email") or "").strip().lower() or None
                password_hash = str(entry.get("password_hash") or "").strip()
                password = str(entry.get("password") or "")
                if password_hash:
                    _parse_password_hash(password_hash)
                elif password:
                    if not allow_legacy_plaintext:
                        raise RuntimeError("AUTH_USERS_JSON entries must use password_hash instead of password.")
                    password_hash = hash_password(password)
                if not username or not password_hash:
                    continue
                users.append(
                    AuthUser(
                        username=username,
                        email=email,
                        password_hash=password_hash,
                        role=normalize_role(entry.get("role"), "viewer"),
                    )
                )
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid AUTH_USERS_JSON: {exc}") from exc

    for role_name, default_username, password_env in (
        ("admin", "admin", "ADMIN_PASSWORD"),
        ("operator", "operator", "OPERATOR_PASSWORD"),
        ("viewer", "viewer", "VIEWER_PASSWORD"),
    ):
        password_hash = str(get_env(f"{role_name.upper()}_PASSWORD_HASH", "") or "").strip()
        password = get_env(password_env, "")
        if password_hash:
            _parse_password_hash(password_hash)
        elif password:
            if not allow_legacy_plaintext:
                raise RuntimeError(f"{role_name.upper()}_PASSWORD is no longer supported; configure {role_name.upper()}_PASSWORD_HASH.")
            password_hash = hash_password(password)
        if not password_hash:
            continue
        username = get_env(f"{role_name.upper()}_USERNAME", default_username) or default_username
        email = get_env(f"{role_name.upper()}_EMAIL", "") or None
        users.append(AuthUser(username=username.strip(), email=(email.strip().lower() if email else None), password_hash=password_hash, role=role_name))

    deduped: dict[str, AuthUser] = {}
    for user in users:
        deduped[user.username] = user
    return tuple(deduped.values())


def _auth_config() -> AuthConfig:
    require_auth = get_bool("REQUIRE_AUTH", False)
    users = _load_auth_users()
    enabled = bool(users)
    session_secret = str(get_env("SESSION_SECRET", "") or "").strip()
    ttl_raw = get_env("SESSION_TTL_SECONDS", "1800") or "1800"
    try:
        ttl_seconds = max(300, min(86400, int(ttl_raw)))
    except ValueError:
        ttl_seconds = 1800
    cookie_domain = get_env("SESSION_COOKIE_DOMAIN", "") or None
    return AuthConfig(
        enabled=enabled,
        require_auth=require_auth,
        users=users,
        session_secret=session_secret,
        session_ttl_seconds=ttl_seconds,
        cookie_secure=get_bool("SESSION_COOKIE_SECURE", False),
        cookie_domain=cookie_domain,
    )


def validate_auth_configuration() -> None:
    config = _auth_config()
    if config.require_auth and not config.users:
        raise RuntimeError("REQUIRE_AUTH is enabled but no auth users are configured.")
    if config.enabled and not config.session_secret:
        raise RuntimeError("SESSION_SECRET must be set when authentication is enabled.")


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


def _encode_session(username: str, role: str, csrf_token: str, expires_at: int, *, secret_value: str) -> str:
    payload = json.dumps({"u": username, "r": role, "csrf": csrf_token, "exp": expires_at}, separators=(",", ":")).encode("utf-8")
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


def _user_matches_identifier(user: AuthUser, identifier: str) -> bool:
    target = identifier.strip()
    if not target:
        return False
    if hmac.compare_digest(user.username, target):
        return True
    if user.email and hmac.compare_digest(user.email, target.lower()):
        return True
    return False


def _find_user(config: AuthConfig, username: str) -> AuthUser | None:
    target = username.strip()
    if not target:
        return None
    for user in config.users:
        if _user_matches_identifier(user, target):
            return user
    return None


def _find_user_by_credentials(request_username: str, request_password: str, config: AuthConfig) -> AuthUser | None:
    for user in config.users:
        if _user_matches_identifier(user, request_username) and verify_password(request_password, user.password_hash):
            return user
    return None


def _valid_basic_credentials(request: Request, config: AuthConfig) -> AuthUser | None:
    credentials = parse_basic_auth(request.headers.get("authorization"))
    if credentials is None:
        return None
    username, password = credentials
    return _find_user_by_credentials(username, password, config)


def _valid_session(request: Request, config: AuthConfig) -> tuple[AuthUser, dict[str, object]] | None:
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    session = _decode_session(raw, secret_value=config.session_secret)
    if session is None:
        return None
    username = str(session.get("u") or "").strip()
    role = normalize_role(str(session.get("r") or "viewer"))
    user = _find_user(config, username)
    if user is None or user.role != role:
        return None
    return user, session


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


def role_from_request(request: Request) -> str:
    role = getattr(request.state, "auth_role", None)
    if isinstance(role, str) and role.strip():
        return normalize_role(role)
    config = _auth_config()
    if not config.enabled and not config.require_auth:
        return "admin"
    return "viewer"


def require_role(request: Request, minimum_role: str) -> str:
    current = role_from_request(request)
    required = normalize_role(minimum_role)
    if ROLE_RANK.get(current, 0) < ROLE_RANK.get(required, 0):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "permission_denied",
                "message": f"{required.title()} role required.",
                "required_role": required,
                "role": current,
            },
        )
    return current


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


def _set_auth_cookies(response: Response, *, username: str, role: str, config: AuthConfig) -> dict[str, object]:
    csrf_token = secrets.token_urlsafe(24)
    expires_at = int(time.time()) + config.session_ttl_seconds
    session_value = _encode_session(username, role, csrf_token, expires_at, secret_value=config.session_secret)
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
    return {"csrf_token": csrf_token, "expires_at": expires_at, "role": role}


def _login_html(next_path: str) -> str:
    safe_next = json.dumps(next_path)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="application-name" content="PrintLab">
  <meta name="theme-color" content="#1f2026">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="PrintLab">
  <link rel="icon" type="image/png" sizes="192x192" href="/icon-192.png">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="apple-touch-icon" sizes="152x152" href="/apple-touch-icon-152x152.png">
  <link rel="apple-touch-icon" sizes="167x167" href="/apple-touch-icon-167x167.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon-180x180.png">
  <title>PrintLab Login</title>
  <style>
    :root {{
      --bg: linear-gradient(160deg, #1f2026 0%, #1a1b20 100%);
      --panel: rgba(255,255,255,.94);
      --panel-text: #2b2d33;
      --text: #f3f5f7;
      --muted: #9aa0aa;
      --accent: #20c465;
      --border: #c8d9eb;
      --shadow: 0 28px 70px rgba(24,49,73,.18);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: var(--bg); color: var(--text); font-family: "Segoe UI", sans-serif; }}
    .panel {{ width: min(420px, calc(100vw - 32px)); background: var(--panel); color: var(--panel-text); border: 1px solid var(--border); border-radius: 20px; padding: 28px; box-shadow: var(--shadow); }}
    h1 {{ margin: 0 0 8px; }}
    p {{ margin: 0 0 18px; color: var(--muted); }}
    label {{ display: block; margin: 0 0 6px; font-size: 13px; font-weight: 600; }}
    input {{ width: 100%; margin: 0 0 14px; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--border); font-size: 15px; }}
    button {{ width: 100%; border: 0; border-radius: 12px; padding: 12px 14px; background: var(--accent); color: #2b2d33; font-size: 15px; font-weight: 700; cursor: pointer; }}
    #status {{ min-height: 20px; margin-top: 12px; color: #9d2d2d; font-size: 13px; }}
  </style>
</head>
<body>
  <form class="panel" id="loginForm">
    <h1>PrintLab</h1>
    <p>Sign in to access the dashboard and API.</p>
    <label for="username">Username or email</label>
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
    user = _find_user_by_credentials(username, password, config)
    if user is None:
        response = JSONResponse(status_code=401, content={"detail": "Invalid credentials."})
        _clear_auth_cookies(response, config)
        return response
    response = JSONResponse(
        content={
            "ok": True,
            "username": user.username,
            "role": user.role,
            "permissions": permissions_for_role(user.role),
            "ttl_seconds": config.session_ttl_seconds,
        }
    )
    _set_auth_cookies(response, username=user.username, role=user.role, config=config)
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
        return JSONResponse(
            content={
                "auth_enabled": False,
                "authenticated": True,
                "username": None,
                "role": "admin",
                "permissions": permissions_for_role("admin"),
                "csrf_token": None,
            }
        )
    if session_match is None:
        return JSONResponse(
            content={"auth_enabled": True, "authenticated": False, "username": None, "role": None, "permissions": [], "csrf_token": None},
            status_code=401,
        )
    user, session = session_match
    return JSONResponse(
        content={
            "auth_enabled": True,
            "authenticated": True,
            "username": user.username,
            "role": user.role,
            "permissions": permissions_for_role(user.role),
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
        request.state.auth_role = None
        request.state.auth_permissions = []
        request.state.auth_scheme = None

        if not config.enabled and not config.require_auth:
            request.state.auth_role = "admin"
            request.state.auth_permissions = permissions_for_role("admin")
            return await call_next(request)

        path = request.url.path
        if path in {"/login", "/auth/login", "/auth/session", "/manifest.webmanifest", "/sw.js", "/favicon.ico", "/printlab.png", "/apple-touch-icon.png", "/apple-touch-icon-152x152.png", "/apple-touch-icon-167x167.png", "/apple-touch-icon-180x180.png", "/icon-192.png", "/icon-512.png"}:
            return await call_next(request)

        if _is_makerworks_boundary_request(path):
            makerworks_user = _valid_makerworks_boundary_auth(request)
            if makerworks_user is not None:
                request.state.auth_user = makerworks_user
                request.state.auth_role = "operator"
                request.state.auth_permissions = permissions_for_role("operator")
                request.state.auth_scheme = "makerworks"
                return await call_next(request)

        basic_user = _valid_basic_credentials(request, config) if config.enabled else None
        if basic_user is not None:
            request.state.auth_user = basic_user.username
            request.state.auth_role = basic_user.role
            request.state.auth_permissions = permissions_for_role(basic_user.role)
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
            request.state.auth_user = session_user.username
            request.state.auth_role = session_user.role
            request.state.auth_permissions = permissions_for_role(session_user.role)
            request.state.auth_scheme = "session"
            return await call_next(request)

        accept_header = request.headers.get("accept", "").lower()
        sec_fetch_dest = request.headers.get("sec-fetch-dest", "").lower()
        sec_fetch_mode = request.headers.get("sec-fetch-mode", "").lower()
        wants_html = request.method.upper() == "GET" and "text/html" in accept_header
        is_browser_request = bool(sec_fetch_dest or sec_fetch_mode or request.headers.get("origin"))
        if wants_html:
            target = quote(request.url.path or "/", safe="/")
            if request.url.query:
                target = f"{target}%3F{quote(request.url.query, safe='=&')}"
            return RedirectResponse(url=f"/login?next={target}", status_code=303)

        if is_browser_request:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required.", "login_url": f"/login?next={quote(request.url.path or '/', safe='/')}"},
                headers={"Cache-Control": "no-store"},
            )

        return Response(
            content="Unauthorized",
            status_code=401,
            headers={
                "WWW-Authenticate": 'Basic realm="PrintLab Admin"',
                "Cache-Control": "no-store",
            },
        )
