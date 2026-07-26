#!/usr/bin/env python3
"""Port-free first-use Palmate bootstrap.

Uses OAuth device authorization, downloads the authenticated CLI release,
verifies its digest, installs it atomically, and delegates credential storage
to the installed CLI. Durable tokens are never displayed or passed as args.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import secrets
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

CLIENT_ID = "palmate-cli-device"
DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
MAX_JSON_BYTES = 64 * 1024
MAX_CLI_BYTES = 128 * 1024 * 1024
SIGNATURE_ALGORITHM = "rsa-pkcs1v15-sha256"
SIGNING_KEY_ID = "00046399fc0ed330"
SIGNING_PUBLIC_EXPONENT = 65537
SIGNING_PUBLIC_MODULUS = int(
    "aa7e785c94aff298eaac355e5fe3d3e8e375c7c32d78ca391549f9c8a901434"
    "a3342fad7746aec3d3db615afcfbbb07aea88d05c1cebbbe42f388326378545bb"
    "97c515f5c7408d5e60395b202688019c2fae62bb00e5d64e66bcc84ebf114251"
    "e4f5746b5aff69e6c2db038d9ac00f874f5fcf18f938aa3fa04c09c326e426b"
    "6b4619b724f4832adb873dcc44e002829c121e3cbabbcc2dc39fedae0183bc2d"
    "ae10d93bc4deaeb441d6dd7d3e1ee2340754a6de50901d906ca48fa728e67241"
    "83ec45aa8a74221e3930c6382c11b020fed0e954d06965cf7c628d7d1ff04a64"
    "e1081762cf808ce46eed77f68b6a8d0de1dfad7b4c1a77a1c610ea4376e7b0c"
    "e56590694996acb9a0568b62eb5f452301a105cda14d6ae7c19e1d3e47a9892"
    "2844516a1e2eee9942175df50952c6ad9c12a2a79513e50cb91bd92fa7d08da"
    "989d2972627d2e976c7dd7e6924c863bd7ee1290678b7d376e32a33815c59575"
    "7a3bd43f864589fe4d349ac8315289df3f21e11b077ec716c7ae9f0e29edeaed"
    "6caf",
    16,
)
SHA256_DIGEST_INFO_PREFIX = bytes.fromhex(
    "3031300d060960864801650304020105000420"
)


class BootstrapError(Exception):
    pass


def verify_release_signature(digest_hex: str, signature_b64: str) -> bool:
    """Verify the release using the public key pinned in this plugin."""
    try:
        digest = bytes.fromhex(digest_hex)
        signature = base64.b64decode(signature_b64, validate=True)
    except (ValueError, binascii.Error):
        return False
    key_size = (SIGNING_PUBLIC_MODULUS.bit_length() + 7) // 8
    if len(digest) != hashlib.sha256().digest_size or len(signature) != key_size:
        return False
    signature_value = int.from_bytes(signature, "big")
    if signature_value >= SIGNING_PUBLIC_MODULUS:
        return False
    encoded = pow(
        signature_value,
        SIGNING_PUBLIC_EXPONENT,
        SIGNING_PUBLIC_MODULUS,
    ).to_bytes(key_size, "big")
    digest_info = SHA256_DIGEST_INFO_PREFIX + digest
    padding_size = key_size - len(digest_info) - 3
    expected = b"\x00\x01" + (b"\xff" * padding_size) + b"\x00" + digest_info
    return padding_size >= 8 and secrets.compare_digest(encoded, expected)


def marker_path() -> Path:
    configured = os.environ.get("PALMATE_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".palmate"
    return root / "plugin-bootstrap.json"


def setup_complete(host: str) -> bool:
    try:
        value = json.loads(marker_path().read_text(encoding="utf-8"))
        cli = Path(value["cli"]).expanduser()
        return value.get("host") == host and cli.is_file() and os.access(cli, os.X_OK)
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return False


def save_marker(host: str, cli: Path) -> None:
    path = marker_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".plugin-bootstrap.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump({"host": host, "cli": str(cli)}, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


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
    response_status, value = request_json_result(url, token=token, form=form)
    if response_status >= 400:
        raise BootstrapError("Palmate authentication or release request failed")
    return value


def request_json_result(
    url: str,
    *,
    token: str | None = None,
    form: dict[str, str] | None = None,
) -> tuple[int, dict]:
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
            response_status = response.status
    except urllib.error.HTTPError as exc:
        try:
            value = json.loads(read_response(exc, MAX_JSON_BYTES))
        except (OSError, json.JSONDecodeError) as parse_exc:
            raise BootstrapError("Palmate returned an invalid error response") from parse_exc
        response_status = exc.code
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise BootstrapError("Palmate authentication or release request failed") from exc
    if not isinstance(value, dict):
        raise BootstrapError("Palmate returned invalid JSON")
    return response_status, value


def oauth_login(host: str) -> tuple[str, str]:
    authorization = request_json(
        f"{host}/api/palmate-cli/device/authorize/",
        form={"client_id": CLIENT_ID, "scope": "read write"},
    )
    device_code = str(authorization.get("device_code", ""))
    user_code = str(authorization.get("user_code", ""))
    verification_url = str(authorization.get("verification_uri", ""))
    complete_url = str(
        authorization.get("verification_uri_complete", verification_url)
    )
    expires_in = authorization.get("expires_in")
    interval = authorization.get("interval", 5)
    if (
        len(device_code) < 24
        or not 4 <= len(user_code) <= 16
        or not isinstance(expires_in, int)
        or not 30 <= expires_in <= 1800
        or not isinstance(interval, int)
        or not 1 <= interval <= 30
        or not same_origin(host, verification_url)
        or not same_origin(host, complete_url)
    ):
        raise BootstrapError("Palmate returned invalid device authorization metadata")

    print("Opening Palmate login in your browser.", flush=True)
    print(f"One-time code: {user_code}", flush=True)
    print("The browser receives no CLI credential; approve only this code.", flush=True)
    if not webbrowser.open(complete_url):
        print(f"Open this URL to continue:\n{complete_url}", flush=True)

    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)
        response_status, tokens = request_json_result(
            f"{host}/api/palmate-cli/device/token/",
            form={
                "grant_type": DEVICE_GRANT_TYPE,
                "device_code": device_code,
                "client_id": CLIENT_ID,
            },
        )
        error = str(tokens.get("error", ""))
        if response_status == 200:
            access = str(tokens.get("access_token", ""))
            refresh = str(tokens.get("refresh_token", ""))
            if not access or not refresh:
                raise BootstrapError("Palmate did not issue renewable credentials")
            return access, refresh
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval = min(interval + 5, 30)
            continue
        if error == "access_denied":
            raise BootstrapError("Palmate login was denied")
        if error == "expired_token":
            raise BootstrapError("Palmate login code expired; run setup again")
        raise BootstrapError("Palmate device authentication failed")
    raise BootstrapError("Palmate login code expired; run setup again")


def download_cli(host: str, access_token: str, destination: Path) -> Path:
    metadata = request_json(
        f"{host}/api/palmate-cli/release/",
        token=access_token,
    )
    url = str(metadata.get("download_url", ""))
    expected = str(metadata.get("sha256", "")).lower()
    declared_size = metadata.get("size")
    signature = str(metadata.get("signature", ""))
    if (
        not url
        or not same_origin(host, url)
        or urllib.parse.urlsplit(url).scheme != "https"
        or metadata.get("algorithm") != "sha256"
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
        or not isinstance(declared_size, int)
        or declared_size < 1
        or declared_size > MAX_CLI_BYTES
        or metadata.get("signature_algorithm") != SIGNATURE_ALGORITHM
        or metadata.get("signing_key_id") != SIGNING_KEY_ID
        or not signature
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
        if (
            total != declared_size
            or digest.hexdigest() != expected
            or not verify_release_signature(expected, signature)
        ):
            raise BootstrapError(
                "Downloaded CLI failed size, checksum, or signature verification"
            )
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
            client_id=CLIENT_ID,
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Exit successfully only when plugin bootstrap already completed.",
    )
    mode.add_argument(
        "--update",
        action="store_true",
        help="Re-authenticate and replace the installed CLI with the signed server release.",
    )
    args = parser.parse_args()
    try:
        host = normalized_host(args.host)
        if args.check:
            return 0 if setup_complete(host) else 1
        access, refresh = oauth_login(host)
        cli = download_cli(host, access, args.destination.expanduser())
        persist_with_installed_cli(cli, host, access, refresh)
        save_marker(host, cli)
    except BootstrapError as exc:
        print(f"Palmate setup failed: {exc}", file=sys.stderr)
        return 1
    action = "updated" if args.update else "installed"
    print(f"Palmate is {action} and authenticated: {cli}")
    if str(cli.parent) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"Add {cli.parent} to PATH, then retry the original Palmate action.")
    else:
        print("Retry the original Palmate action now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
