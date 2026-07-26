#!/usr/bin/env python3
"""First-use Palmate bootstrap for Claude Code.

Uses browser OAuth PKCE, downloads the authenticated CLI release, verifies its
digest, installs it atomically, and delegates credential persistence to the
newly installed CLI package. Tokens are never printed or passed as arguments.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 18271
CALLBACK_PATH = "/callback"
MAX_JSON_BYTES = 64 * 1024
MAX_CLI_BYTES = 128 * 1024 * 1024


class BootstrapError(Exception):
    pass


def normalized_host(value: str) -> str:
    parsed = urllib.parse.urlsplit(str(value).strip().rstrip("/"))
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise BootstrapError("Palmate host must be an HTTPS origin without credentials or a path")
    return urllib.parse.urlunsplit(("https", parsed.netloc, "", "", ""))


def same_origin(left: str, right: str) -> bool:
    a, b = urllib.parse.urlsplit(left), urllib.parse.urlsplit(right)
    return (a.scheme.lower(), a.hostname, a.port) == (
        b.scheme.lower(),
        b.hostname,
        b.port,
    )


class SameOriginRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not same_origin(request.full_url, newurl):
            raise BootstrapError("Palmate redirected an authenticated request to another origin")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(SameOriginRedirects())


def read_response(response, limit: int) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared:
        try:
            if int(declared) > limit:
                raise BootstrapError("Palmate response exceeds the allowed size")
        except ValueError as exc:
            raise BootstrapError("Palmate returned an invalid Content-Length") from exc
    output = bytearray()
    while chunk := response.read(min(1024 * 1024, limit + 1 - len(output))):
        output.extend(chunk)
        if len(output) > limit:
            raise BootstrapError("Palmate response exceeds the allowed size")
    return bytes(output)


def request_json(
    url: str,
    *,
    token: str | None = None,
    form: dict[str, str] | None = None,
) -> dict:
    headers = {"Accept": "application/json"}
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if form is not None:
        body = urllib.parse.urlencode(form).encode("ascii")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with OPENER.open(request, timeout=30) as response:
            value = json.loads(read_response(response, MAX_JSON_BYTES))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise BootstrapError("Palmate authentication or release request failed") from exc
    if not isinstance(value, dict):
        raise BootstrapError("Palmate returned invalid JSON")
    return value


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    expected_state = ""
    code: str | None = None
    error: str | None = None

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        values = urllib.parse.parse_qs(parsed.query)
        state = values.get("state", [""])[0]
        if (
            parsed.path != CALLBACK_PATH
            or not state
            or not secrets.compare_digest(state, self.expected_state)
        ):
            self.error = "OAuth callback validation failed"
            self.send_response(400)
            self.end_headers()
            return
        if values.get("error"):
            self.error = "Login was not completed"
            self.send_response(400)
            self.end_headers()
            return
        self.code = values.get("code", [None])[0]
        if not self.code:
            self.error = "OAuth callback did not contain a code"
            self.send_response(400)
            self.end_headers()
            return
        body = (
            b"<!doctype html><meta charset=utf-8>"
            b"<title>Palmate login complete</title>"
            b"<h1>Login complete</h1><p>You can close this window.</p>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", "default-src 'none'")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def oauth_login(host: str) -> tuple[str, str]:
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    callback = f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"
    CallbackHandler.expected_state = state
    CallbackHandler.code = None
    CallbackHandler.error = None

    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "redirect_uri": callback,
            "client_id": "palmate-cli",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    authorize_url = f"{host}/api/o/authorize/?{query}"
    try:
        server = http.server.HTTPServer((CALLBACK_HOST, CALLBACK_PORT), CallbackHandler)
    except OSError as exc:
        raise BootstrapError(
            f"Cannot bind OAuth callback port {CALLBACK_PORT}; close the process using it and retry"
        ) from exc
    server.timeout = 180
    print("Opening Palmate login in your browser…", flush=True)
    if not webbrowser.open(authorize_url):
        print(f"Open this URL to continue:\n{authorize_url}", flush=True)
    server.handle_request()
    server.server_close()
    if not CallbackHandler.code:
        raise BootstrapError(CallbackHandler.error or "Timed out waiting for Palmate login")

    tokens = request_json(
        f"{host}/api/o/token/",
        form={
            "grant_type": "authorization_code",
            "code": CallbackHandler.code,
            "redirect_uri": callback,
            "client_id": "palmate-cli",
            "code_verifier": verifier,
        },
    )
    access = str(tokens.get("access_token", ""))
    refresh = str(tokens.get("refresh_token", ""))
    if not access:
        raise BootstrapError("Palmate did not issue an access token")
    return access, refresh


def download_cli(host: str, access_token: str, destination: Path) -> Path:
    metadata = request_json(
        f"{host}/api/palmate-cli/release/",
        token=access_token,
    )
    url = str(metadata.get("download_url", ""))
    expected = str(metadata.get("sha256", "")).lower()
    declared_size = metadata.get("size")
    if (
        not url
        or not same_origin(host, url)
        or urllib.parse.urlsplit(url).scheme != "https"
        or metadata.get("algorithm") != "sha256"
        or len(expected) != 64
        or not isinstance(declared_size, int)
        or declared_size < 1
        or declared_size > MAX_CLI_BYTES
    ):
        raise BootstrapError("Palmate returned invalid CLI release metadata")

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "Authorization": f"Bearer {access_token}",
        },
    )
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    total = 0
    try:
        try:
            response = OPENER.open(request, timeout=60)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise BootstrapError("Authenticated CLI download failed") from exc
        with response, os.fdopen(descriptor, "wb") as output:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_CLI_BYTES:
                    raise BootstrapError("CLI download exceeds the allowed size")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if total != declared_size or digest.hexdigest() != expected:
            raise BootstrapError("Downloaded CLI failed size or checksum verification")
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def persist_with_installed_cli(
    cli: Path,
    host: str,
    access_token: str,
    refresh_token: str,
) -> None:
    sys.path.insert(0, str(cli))
    try:
        from palmate_cli.auth.credentials import save_credentials

        save_credentials(
            host,
            access_token,
            refresh_token,
            auth_mode="oauth",
            client_id="palmate-cli",
            make_default=True,
        )
    except Exception as exc:
        cli.unlink(missing_ok=True)
        raise BootstrapError("CLI installed but secure credential initialization failed") from exc
    finally:
        sys.path.pop(0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install and authenticate Palmate")
    parser.add_argument("--host", required=True, help="HTTPS Palmate origin")
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path.home() / ".local" / "bin" / "palmate",
    )
    args = parser.parse_args()
    try:
        host = normalized_host(args.host)
        access, refresh = oauth_login(host)
        cli = download_cli(host, access, args.destination.expanduser())
        persist_with_installed_cli(cli, host, access, refresh)
    except BootstrapError as exc:
        print(f"Palmate setup failed: {exc}", file=sys.stderr)
        return 1
    print(f"Palmate is installed and authenticated: {cli}")
    if str(cli.parent) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"Add {cli.parent} to PATH, then retry the original Palmate action.")
    else:
        print("Retry the original Palmate action now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
