from __future__ import annotations

import argparse
import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests


YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def build_auth_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": YOUTUBE_UPLOAD_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


def exchange_code_for_tokens(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
) -> dict[str, Any]:
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text}
    if not response.ok:
        raise RuntimeError(f"Google token exchange failed (HTTP {response.status_code}): {json.dumps(body)}")
    return body


class OAuthCallbackServer(HTTPServer):
    def __init__(self, server_address: tuple[str, int], request_handler_class: type[BaseHTTPRequestHandler], expected_state: str) -> None:
        super().__init__(server_address, request_handler_class)
        self.expected_state = expected_state
        self.code: str | None = None
        self.error: str | None = None


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self._write_page(404, "Not found.")
            return
        params = parse_qs(parsed.query)
        state = (params.get("state") or [""])[0]
        error = (params.get("error") or [""])[0]
        code = (params.get("code") or [""])[0]

        if state != self.server.expected_state:
            self.server.error = "OAuth state mismatch. Start the flow again."
            self._write_page(400, "OAuth state mismatch. You can close this window.")
            return
        if error:
            self.server.error = error
            self._write_page(400, f"Google returned an error: {error}. You can close this window.")
            return
        if not code:
            self.server.error = "Google callback did not include a code."
            self._write_page(400, "Missing authorization code. You can close this window.")
            return

        self.server.code = code
        self._write_page(200, "Authorization code received. Return to the terminal.")

    def log_message(self, format: str, *args: object) -> None:
        return

    def _write_page(self, status: int, message: str) -> None:
        payload = (
            "<!doctype html><html><head><meta charset='utf-8'><title>YouTube OAuth</title></head>"
            f"<body style='font-family:Segoe UI,sans-serif;padding:24px;'><h1>{message}</h1></body></html>"
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Get a YouTube refresh token for PrintLab.")
    parser.add_argument("--client-id", required=True, help="Google OAuth client id")
    parser.add_argument("--client-secret", required=True, help="Google OAuth client secret")
    parser.add_argument("--host", default="127.0.0.1", help="Local callback host")
    parser.add_argument("--port", type=int, default=8080, help="Local callback port")
    parser.add_argument("--no-browser", action="store_true", help="Print the consent URL without opening a browser")
    args = parser.parse_args()

    state = secrets.token_urlsafe(24)
    redirect_uri = f"http://{args.host}:{args.port}/callback"
    auth_url = build_auth_url(client_id=args.client_id, redirect_uri=redirect_uri, state=state)
    server = OAuthCallbackServer((args.host, args.port), OAuthCallbackHandler, state)
    server.timeout = 1

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print("Open this Google consent URL if the browser does not launch:")
    print(auth_url)
    print()
    print(f"Configured redirect URI: {redirect_uri}")
    print("Waiting for Google OAuth callback...")

    if not args.no_browser:
        webbrowser.open(auth_url)

    deadline = time.monotonic() + 300
    try:
        while time.monotonic() < deadline:
            if server.error:
                raise RuntimeError(server.error)
            if server.code:
                tokens = exchange_code_for_tokens(
                    client_id=args.client_id,
                    client_secret=args.client_secret,
                    redirect_uri=redirect_uri,
                    code=server.code,
                )
                refresh_token = str(tokens.get("refresh_token") or "").strip()
                access_token = str(tokens.get("access_token") or "").strip()
                if not refresh_token:
                    raise RuntimeError(
                        "Google did not return a refresh_token. Revoke the app for this Google account and rerun with prompt=consent."
                    )
                print()
                print("Put this in your .env:")
                print(f"YOUTUBE_REFRESH_TOKEN={refresh_token}")
                print()
                print("Token exchange summary:")
                print(json.dumps({"has_access_token": bool(access_token), "scope": tokens.get("scope"), "token_type": tokens.get("token_type")}, indent=2))
                return 0
            time.sleep(0.2)
        raise RuntimeError("Timed out waiting for Google OAuth callback.")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
