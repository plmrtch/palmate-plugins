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
import re
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
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
SESSION_ENVIRONMENT_KEYS = (
    "CODEX_THREAD_ID",
    "CLAUDE_CODE_REMOTE_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_SESSION_ID",
)
MAX_RECORDED_SESSION_CHECKS = 32


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


def load_marker() -> dict:
    try:
        value = json.loads(marker_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, TypeError, json.JSONDecodeError):
        return {}


def installed_cli_path(host: str) -> Path | None:
    value = load_marker()
    try:
        cli = Path(value["cli"]).expanduser()
    except (KeyError, TypeError):
        return None
    if value.get("host") != host or not cli.is_file() or not os.access(cli, os.X_OK):
        return None
    return cli


def setup_complete(host: str) -> bool:
    return installed_cli_path(host) is not None


def save_marker(host: str, cli: Path) -> None:
    path = marker_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    value = load_marker()
    value.update({"host": host, "cli": str(cli)})
    descriptor, temporary_name = tempfile.mkstemp(prefix=".plugin-bootstrap.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def current_agent_session(explicit: str | None = None) -> str | None:
    """Return a stable, non-secret coding-agent session identity when exposed."""
    if explicit and explicit.strip():
        return f"explicit:{explicit.strip()}"
    for key in SESSION_ENVIRONMENT_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return f"{key}:{value}"
    return None


def session_check_key(host: str, session: str) -> str:
    return hashlib.sha256(f"{host}\0{session}".encode("utf-8")).hexdigest()


def session_was_checked(host: str, session: str | None) -> bool:
    if not session:
        return False
    checks = load_marker().get("version_checks")
    return isinstance(checks, dict) and session_check_key(host, session) in checks


def record_session_check(
    host: str,
    cli: Path,
    session: str | None,
    version: str,
) -> None:
    """Record only a hash of the host/session pair and keep the marker bounded."""
    save_marker(host, cli)
    if not session:
        return
    path = marker_path()
    value = load_marker()
    checks = value.get("version_checks")
    if not isinstance(checks, dict):
        checks = {}
    checks[session_check_key(host, session)] = {
        "checked_at": int(time.time()),
        "version": version,
    }
    if len(checks) > MAX_RECORDED_SESSION_CHECKS:
        oldest = sorted(
            checks,
            key=lambda key: int((checks.get(key) or {}).get("checked_at", 0)),
        )[: len(checks) - MAX_RECORDED_SESSION_CHECKS]
        for key in oldest:
            checks.pop(key, None)
    value["version_checks"] = checks
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".plugin-bootstrap.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True)
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


def parse_semver(value: str) -> tuple[tuple[int, int, int], tuple[str, ...] | None]:
    match = SEMVER_PATTERN.fullmatch(str(value).strip())
    if not match:
        raise BootstrapError("Palmate returned an invalid CLI semantic version")
    prerelease = tuple(match.group(4).split(".")) if match.group(4) else None
    if prerelease and any(
        identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0")
        for identifier in prerelease
    ):
        raise BootstrapError("Palmate returned an invalid CLI semantic version")
    return tuple(int(match.group(index)) for index in (1, 2, 3)), prerelease


def compare_semver(left: str, right: str) -> int:
    """Compare two strict SemVer values, ignoring build metadata."""
    left_core, left_pre = parse_semver(left)
    right_core, right_pre = parse_semver(right)
    if left_core != right_core:
        return -1 if left_core < right_core else 1
    if left_pre == right_pre:
        return 0
    if left_pre is None:
        return 1
    if right_pre is None:
        return -1
    for left_part, right_part in zip(left_pre, right_pre):
        if left_part == right_part:
            continue
        left_numeric = left_part.isdigit()
        right_numeric = right_part.isdigit()
        if left_numeric and right_numeric:
            return -1 if int(left_part) < int(right_part) else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_part < right_part else 1
    return -1 if len(left_pre) < len(right_pre) else 1


def installed_cli_identity(
    cli: Path,
    host: str,
    *,
    refresh: bool = False,
) -> tuple[str, str]:
    """Ask the installed CLI's credential authority for its version and token."""
    sys.path.insert(0, str(cli))
    try:
        from palmate_cli._version import CLI_VERSION
        from palmate_cli.auth.credentials import load_credentials

        credentials = load_credentials(host) or {}
        token = str(credentials.get("access_token", ""))
        if refresh and token:
            from palmate_cli.http.auth import refresh_access_token

            refreshed = refresh_access_token(
                base_url=host,
                current_token=token,
                user_agent=f"palmate/{CLI_VERSION}",
            )
            if refreshed:
                token = str(refreshed[0])
        if not token:
            raise BootstrapError("installed Palmate CLI is not authenticated")
        return str(CLI_VERSION), token
    except BootstrapError:
        raise
    except Exception as exc:
        raise BootstrapError(
            "installed Palmate CLI credential authority is unavailable"
        ) from exc
    finally:
        sys.path.pop(0)


def installed_release_metadata(host: str, cli: Path) -> tuple[str, str, dict]:
    installed_version, token = installed_cli_identity(cli, host)
    status, metadata = request_json_result(
        f"{host}/api/palmate-cli/release/",
        token=token,
    )
    if status == 401:
        installed_version, token = installed_cli_identity(cli, host, refresh=True)
        status, metadata = request_json_result(
            f"{host}/api/palmate-cli/release/",
            token=token,
        )
    if status >= 400:
        raise BootstrapError("Palmate CLI release version check failed")
    return installed_version, token, metadata


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


def download_cli(
    host: str,
    access_token: str,
    destination: Path,
    *,
    metadata: dict | None = None,
) -> Path:
    metadata = metadata or request_json(
        f"{host}/api/palmate-cli/release/", token=access_token
    )
    url = str(metadata.get("download_url", ""))
    remote_version = str(metadata.get("version", ""))
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
    parse_semver(remote_version)

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


def check_for_session_update(
    host: str,
    cli: Path,
    *,
    session: str | None = None,
) -> str:
    """Check once per exposed agent session and install only a newer release."""
    session = current_agent_session(session)
    if session_was_checked(host, session):
        return "already_checked"

    installed_version = "unknown"
    try:
        installed_version, token, metadata = installed_release_metadata(host, cli)
        remote_version = str(metadata.get("version", ""))
        comparison = compare_semver(installed_version, remote_version)
        if comparison < 0:
            previous_version = installed_version
            download_cli(host, token, cli, metadata=metadata)
            installed_version = remote_version
            print(
                f"Palmate CLI updated from {previous_version} "
                f"to {remote_version} for this coding-agent session.",
                flush=True,
            )
            result = "updated"
        else:
            result = "current"
    except (BootstrapError, OSError) as exc:
        print(
            f"Palmate CLI version check skipped; using the installed binary: {exc}",
            file=sys.stderr,
            flush=True,
        )
        result = "skipped"
    try:
        record_session_check(host, cli, session, installed_version)
    except OSError as exc:
        print(
            f"Palmate CLI session marker could not be saved: {exc}",
            file=sys.stderr,
            flush=True,
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Install and authenticate Palmate")
    parser.add_argument("--host", required=True, help="HTTPS Palmate origin")
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path.home() / ".local" / "bin" / "palmate",
    )
    parser.add_argument(
        "--session-id",
        help="Optional stable coding-agent session ID; the raw value is never stored.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Verify setup and check once per coding-agent session for a newer CLI.",
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
            cli = installed_cli_path(host)
            if cli is None:
                return 1
            check_for_session_update(host, cli, session=args.session_id)
            return 0
        access, refresh = oauth_login(host)
        cli = download_cli(host, access, args.destination.expanduser())
        persist_with_installed_cli(cli, host, access, refresh)
        save_marker(host, cli)
        try:
            version, _ = installed_cli_identity(cli, host)
        except BootstrapError:
            version = "unknown"
        record_session_check(
            host,
            cli,
            current_agent_session(args.session_id),
            version,
        )
    except (BootstrapError, OSError) as exc:
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
