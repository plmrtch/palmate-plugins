from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
CODEX_SKILL = ROOT / "codex" / "skills" / "palmate-setup"
CLAUDE_SKILL = ROOT / "claude-code" / "skills" / "palmate-setup"
CODEX_BOOTSTRAP = CODEX_SKILL / "scripts" / "bootstrap_palmate.py"
CLAUDE_BOOTSTRAP = CLAUDE_SKILL / "scripts" / "bootstrap_palmate.py"
SIGNED_COMPLETE_CLI = (
    "dzIFp9DPMXknK87j1r05bLWEGO11m9uOtBw/KwpudivI1SP+82L6ol8FYgA2hj+hu"
    "VejnxCY+1cIBdkU6yCwvPsaRRwB8+277IlImkLoorvMPpRw0WpQoPgT3TVyaRX34G"
    "O4xJVhX9ReeyQO4Z9auB2jHN/Ih/3euVHf14biAAzH7kAxVRraKdWet2qtGezSmTT"
    "/p1jcPyzYF2kMtRQRaRqOqUmR+TmTKQxmDwBOsJkk91yewCG1Bj4NuGIT69fXI0G"
    "Y0Xxe3joTvB5NkizLzJVFHr/94stW4ZlzQAqOethBJ4XhmN6twC8AlNPsV5B2NPgJ"
    "EZFOa8d8vVZqxiH3jcXUdpGjg1t+Ak21aA/m0r0rF3CopoMQztbVjfzkagND4zCxT"
    "CZCIlEqrgAmU47KLbOPLJrSufCFYoI+m8JyeDj1Yn8dYrqzy7Bz0NeE/4Wk8ds7Zi"
    "Ilb5gRjql76R+USIxxmmWk4N9FoxRZQxsAwos4wPOB9RG2ELOeA8yub7zz"
)


def load_bootstrap():
    spec = importlib.util.spec_from_file_location("bootstrap_palmate", CODEX_BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


bootstrap = load_bootstrap()


class SemanticVersionTests(unittest.TestCase):
    def test_remote_stable_release_is_newer_than_prerelease(self):
        self.assertLess(bootstrap.compare_semver("1.2.3-rc.1", "1.2.3"), 0)

    def test_numeric_prerelease_identifiers_follow_semver_order(self):
        self.assertLess(bootstrap.compare_semver("1.2.3-rc.2", "1.2.3-rc.10"), 0)

    def test_build_metadata_does_not_change_precedence(self):
        self.assertEqual(
            bootstrap.compare_semver("1.2.3+local", "1.2.3+remote"),
            0,
        )

    def test_invalid_semantic_version_fails_closed(self):
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.compare_semver("1.2", "1.2.3")


class SignatureVerificationTests(unittest.TestCase):
    def test_pinned_key_accepts_known_release_signature(self):
        digest = hashlib.sha256(b"complete-cli").hexdigest()
        self.assertTrue(bootstrap.verify_release_signature(digest, SIGNED_COMPLETE_CLI))

    def test_pinned_key_rejects_signature_for_different_digest(self):
        digest = hashlib.sha256(b"tampered-cli").hexdigest()
        self.assertFalse(bootstrap.verify_release_signature(digest, SIGNED_COMPLETE_CLI))


class BootstrapMarkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="palmate-marker-test-")
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(
            os.environ, {"PALMATE_HOME": str(self.root / "state")}, clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def executable(self, name):
        path = self.root / "bin" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"cli")
        path.chmod(0o700)
        return path

    def test_marker_preserves_independent_cli_per_host(self):
        first = self.executable("first")
        second = self.executable("second")
        bootstrap.save_marker("https://first.example", first)
        bootstrap.save_marker("https://second.example", second)

        self.assertEqual(
            bootstrap.installed_cli_path("https://first.example"), first,
        )
        self.assertEqual(
            bootstrap.installed_cli_path("https://second.example"), second,
        )
        marker = json.loads(bootstrap.marker_path().read_text(encoding="utf-8"))
        self.assertEqual(marker["version"], 2)
        self.assertEqual(set(marker["hosts"]), {
            "https://first.example", "https://second.example",
        })

    def test_marker_keeps_the_last_install_readable_by_legacy_bootstraps(self):
        first = self.executable("first")
        second = self.executable("second")
        bootstrap.save_marker("https://first.example", first)
        bootstrap.save_marker("https://second.example", second)

        marker = json.loads(bootstrap.marker_path().read_text(encoding="utf-8"))
        # 0.5.x reads only this pair; 0.6+ reads `hosts`.
        self.assertEqual(
            (marker["host"], marker["cli"]), ("https://second.example", str(second)),
        )
        self.assertEqual(marker["hosts"], {
            "https://first.example": {"cli": str(first)},
            "https://second.example": {"cli": str(second)},
        })
        self.assertEqual(
            bootstrap.installed_cli_path("https://first.example"), first,
        )

    def test_legacy_single_host_marker_migrates_without_loss(self):
        first = self.executable("first")
        second = self.executable("second")
        path = bootstrap.marker_path()
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "host": "https://first.example", "cli": str(first),
        }), encoding="utf-8")

        bootstrap.save_marker("https://second.example", second)

        self.assertEqual(
            bootstrap.installed_cli_path("https://first.example"), first,
        )
        self.assertEqual(
            bootstrap.installed_cli_path("https://second.example"), second,
        )

    def test_missing_check_has_actionable_human_and_json_output(self):
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            result = bootstrap.main([
                "--host", "https://missing.example", "--check",
            ])
        self.assertEqual(result, 1)
        self.assertIn("not installed for this host", stderr.getvalue())

        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            result = bootstrap.main([
                "--host", "https://missing.example", "--check", "--json",
            ])
        self.assertEqual(result, 1)
        self.assertEqual(
            json.loads(stdout.getvalue())["code"], "setup_missing",
        )

    def test_corrupt_marker_fails_as_actionable_missing_setup(self):
        path = bootstrap.marker_path()
        path.parent.mkdir(parents=True)
        path.write_text("{not-json", encoding="utf-8")
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            result = bootstrap.main([
                "--host", "https://missing.example", "--check", "--json",
            ])
        self.assertEqual(result, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["code"], "setup_missing")
        self.assertNotIn("not-json", stdout.getvalue())


class SessionUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="palmate-plugin-test-")
        self.root = Path(self.temporary.name)
        self.cli = self.root / "bin" / "palmate"
        self.cli.parent.mkdir(parents=True)
        self.cli.write_bytes(b"known-good-cli")
        self.cli.chmod(0o700)
        self.host = "https://api.palmate.ai"
        self.environment = patch.dict(
            os.environ,
            {
                "PALMATE_HOME": str(self.root / "state"),
                "CODEX_THREAD_ID": "thread-secret-value",
                "CLAUDE_CODE_REMOTE_SESSION_ID": "",
                "CLAUDE_CODE_SESSION_ID": "",
                "CLAUDE_SESSION_ID": "",
            },
        )
        self.environment.start()
        bootstrap.save_marker(self.host, self.cli)

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    @staticmethod
    def metadata(version: str) -> dict:
        return {"version": version}

    def test_newer_remote_release_is_downloaded_only_once_in_session(self):
        with (
            patch.object(
                bootstrap,
                "installed_release_metadata",
                return_value=("1.2.3", "opaque-token", self.metadata("1.3.0")),
            ) as metadata,
            patch.object(bootstrap, "download_cli", return_value=self.cli) as download,
        ):
            first = bootstrap.check_for_session_update(self.host, self.cli)
            second = bootstrap.check_for_session_update(self.host, self.cli)

        self.assertEqual(first, "updated")
        self.assertEqual(second, "already_checked")
        metadata.assert_called_once_with(self.host, self.cli)
        download.assert_called_once()
        marker_text = bootstrap.marker_path().read_text(encoding="utf-8")
        self.assertNotIn("thread-secret-value", marker_text)
        self.assertEqual(len(json.loads(marker_text)["version_checks"]), 1)

    def test_equal_or_older_remote_release_does_not_replace_binary(self):
        for remote in ("1.2.3", "1.2.2"):
            with self.subTest(remote=remote):
                marker = bootstrap.load_marker()
                marker.pop("version_checks", None)
                bootstrap.marker_path().write_text(json.dumps(marker), encoding="utf-8")
                with (
                    patch.object(
                        bootstrap,
                        "installed_release_metadata",
                        return_value=("1.2.3", "opaque-token", self.metadata(remote)),
                    ),
                    patch.object(bootstrap, "download_cli") as download,
                ):
                    result = bootstrap.check_for_session_update(self.host, self.cli)
                self.assertEqual(result, "current")
                download.assert_not_called()

    def test_failed_check_keeps_known_good_binary_and_is_not_retried(self):
        with patch.object(
            bootstrap,
            "installed_release_metadata",
            side_effect=bootstrap.BootstrapError("release unavailable"),
        ) as metadata:
            first = bootstrap.check_for_session_update(self.host, self.cli)
            second = bootstrap.check_for_session_update(self.host, self.cli)

        self.assertEqual(first, "skipped")
        self.assertEqual(second, "already_checked")
        self.assertEqual(self.cli.read_bytes(), b"known-good-cli")
        metadata.assert_called_once_with(self.host, self.cli)

    def test_new_agent_session_performs_a_fresh_check(self):
        with (
            patch.object(
                bootstrap,
                "installed_release_metadata",
                return_value=("1.2.3", "opaque-token", self.metadata("1.2.3")),
            ) as metadata,
            patch.object(bootstrap, "download_cli"),
        ):
            bootstrap.check_for_session_update(self.host, self.cli)
            with patch.dict(os.environ, {"CODEX_THREAD_ID": "next-thread"}):
                result = bootstrap.check_for_session_update(self.host, self.cli)

        self.assertEqual(result, "current")
        self.assertEqual(metadata.call_count, 2)

    def test_claude_remote_session_is_checked_only_once(self):
        with (
            patch.dict(
                os.environ,
                {
                    "CODEX_THREAD_ID": "",
                    "CLAUDE_CODE_REMOTE_SESSION_ID": "remote-session-secret",
                },
            ),
            patch.object(
                bootstrap,
                "installed_release_metadata",
                return_value=("1.2.3", "opaque-token", self.metadata("1.2.3")),
            ) as metadata,
        ):
            first = bootstrap.check_for_session_update(self.host, self.cli)
            second = bootstrap.check_for_session_update(self.host, self.cli)

        self.assertEqual(first, "current")
        self.assertEqual(second, "already_checked")
        metadata.assert_called_once_with(self.host, self.cli)
        self.assertNotIn(
            "remote-session-secret",
            bootstrap.marker_path().read_text(encoding="utf-8"),
        )

    def test_release_metadata_retries_once_with_refreshed_credentials(self):
        with (
            patch.object(
                bootstrap,
                "installed_cli_identity",
                side_effect=[("1.2.3", "expired"), ("1.2.3", "refreshed")],
            ) as identity,
            patch.object(
                bootstrap,
                "request_json_result",
                side_effect=[(401, {}), (200, self.metadata("1.2.4"))],
            ) as request,
        ):
            result = bootstrap.installed_release_metadata(self.host, self.cli)

        self.assertEqual(result, ("1.2.3", "refreshed", self.metadata("1.2.4")))
        self.assertEqual(identity.call_count, 2)
        identity.assert_any_call(self.cli, self.host)
        identity.assert_any_call(self.cli, self.host, refresh=True)
        self.assertEqual(request.call_count, 2)


class BinaryReplacementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="palmate-download-test-")
        self.destination = Path(self.temporary.name) / "bin" / "palmate"
        self.destination.parent.mkdir(parents=True)
        self.destination.write_bytes(b"known-good-cli")
        self.destination.chmod(0o700)
        self.host = "https://api.palmate.ai"
        self.payload = b"new-signed-palmate-cli"
        self.posix = patch.object(bootstrap, "WINDOWS", False)
        self.posix.start()

    def tearDown(self):
        self.posix.stop()
        self.temporary.cleanup()

    def metadata(self, *, digest: str | None = None) -> dict:
        return {
            "download_url": f"{self.host}/api/palmate-cli/download/",
            "version": "1.3.0",
            "sha256": digest or hashlib.sha256(self.payload).hexdigest(),
            "size": len(self.payload),
            "algorithm": "sha256",
            "signature": "test-signature",
            "signature_algorithm": bootstrap.SIGNATURE_ALGORITHM,
            "signing_key_id": bootstrap.SIGNING_KEY_ID,
        }

    def test_verified_download_atomically_replaces_binary(self):
        with (
            patch.object(
                bootstrap.OPENER,
                "open",
                return_value=io.BytesIO(self.payload),
            ) as opened,
            patch.object(bootstrap, "verify_release_signature", return_value=True),
        ):
            result = bootstrap.download_cli(
                self.host,
                "opaque-token",
                self.destination,
                metadata=self.metadata(),
            )

        self.assertEqual(result, self.destination)
        self.assertEqual(self.destination.read_bytes(), self.payload)
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o700)
        request = opened.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer opaque-token")

    def test_checksum_failure_preserves_known_good_binary(self):
        with (
            patch.object(
                bootstrap.OPENER,
                "open",
                return_value=io.BytesIO(self.payload),
            ),
            patch.object(bootstrap, "verify_release_signature", return_value=True),
        ):
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.download_cli(
                    self.host,
                    "opaque-token",
                    self.destination,
                    metadata=self.metadata(digest="0" * 64),
                )

        self.assertEqual(self.destination.read_bytes(), b"known-good-cli")
        self.assertEqual(list(self.destination.parent.glob(".palmate.*")), [])


class WindowsLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="palmate-windows-test-")
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.artifact = self.bin / "palmate.pyz"
        self.host = "https://api.palmate.ai"
        self.payload = b"new-signed-palmate-cli"
        self.environment = patch.dict(
            os.environ,
            {
                "PALMATE_HOME": str(self.root / "state"),
                "CODEX_THREAD_ID": "windows-thread",
                "CLAUDE_CODE_REMOTE_SESSION_ID": "",
                "CLAUDE_CODE_SESSION_ID": "",
                "CLAUDE_SESSION_ID": "",
            },
        )
        self.environment.start()
        self.windows = patch.object(bootstrap, "WINDOWS", True)
        self.windows.start()

    def tearDown(self):
        self.windows.stop()
        self.environment.stop()
        self.temporary.cleanup()

    def metadata(self, version: str = "1.3.0") -> dict:
        return {
            "download_url": f"{self.host}/api/palmate-cli/download/",
            "version": version,
            "sha256": hashlib.sha256(self.payload).hexdigest(),
            "size": len(self.payload),
            "algorithm": "sha256",
            "signature": "test-signature",
            "signature_algorithm": bootstrap.SIGNATURE_ALGORITHM,
            "signing_key_id": bootstrap.SIGNING_KEY_ID,
        }

    def install(self) -> int:
        with (
            patch.object(bootstrap, "oauth_login", return_value=("access", "refresh")),
            patch.object(bootstrap, "request_json", return_value=self.metadata()),
            patch.object(
                bootstrap.OPENER, "open", return_value=io.BytesIO(self.payload),
            ),
            patch.object(bootstrap, "verify_release_signature", return_value=True),
            patch.object(bootstrap, "persist_with_installed_cli"),
            patch.object(
                bootstrap, "installed_cli_identity", return_value=("1.3.0", "access"),
            ),
            patch("sys.stdout", io.StringIO()),
        ):
            return bootstrap.main(
                ["--host", self.host, "--destination", str(self.bin / "palmate")],
            )

    def check(self, remote_version: str):
        stdout = io.StringIO()
        with (
            patch.object(
                bootstrap,
                "installed_release_metadata",
                return_value=("1.2.3", "opaque-token", self.metadata(remote_version)),
            ),
            patch.object(
                bootstrap.OPENER, "open", return_value=io.BytesIO(self.payload),
            ) as opened,
            patch.object(bootstrap, "verify_release_signature", return_value=True),
            patch("sys.stdout", stdout),
        ):
            code = bootstrap.main(["--host", self.host, "--check", "--json"])
        return code, json.loads(stdout.getvalue()), opened

    def test_fresh_install_writes_the_zipapp_and_both_launchers(self):
        self.assertEqual(self.install(), 0)

        self.assertEqual(self.artifact.read_bytes(), self.payload)
        self.assertEqual(bootstrap.installed_cli_path(self.host), self.artifact)
        sh = (self.bin / "palmate").read_text(encoding="utf-8")
        cmd = (self.bin / "palmate.cmd").read_bytes().decode("ascii")
        self.assertTrue(sh.startswith("#!/bin/sh\n"))
        self.assertIn(f"PYTHON='{Path(sys.executable).as_posix()}'", sh)
        self.assertIn(f"CLI='{self.artifact.as_posix()}'", sh)
        self.assertIn('set "PALMATE_CLI=%~dp0palmate.pyz"', cmd)
        self.assertNotIn("\n", cmd.replace("\r\n", ""))
        for launcher in (sh, cmd):
            self.assertIn("PYTHONUTF8=1", launcher)
            self.assertIn("PYTHONIOENCODING=utf-8", launcher)
            self.assertIn("py -3", launcher)

    def test_check_migrates_an_old_install_without_downloading(self):
        old = self.bin / "palmate"
        old.write_bytes(b"known-good-cli")
        old.chmod(0o700)
        bootstrap.save_marker(self.host, old)
        # The session was already checked, so the update check returns early.
        bootstrap.record_session_check(
            self.host, old, bootstrap.current_agent_session(), "1.2.3",
        )

        code, payload, opened = self.check("1.3.0")

        self.assertEqual((code, payload["update_check"]), (0, "already_checked"))
        opened.assert_not_called()
        self.assertEqual(self.artifact.read_bytes(), b"known-good-cli")
        self.assertTrue(old.read_bytes().startswith(b"#!/bin/sh\n"))
        self.assertTrue((self.bin / "palmate.cmd").is_file())
        self.assertEqual(payload["cli"], str(self.artifact))
        self.assertEqual(bootstrap.installed_cli_path(self.host), self.artifact)
        code, payload, _ = self.check("1.3.0")
        self.assertEqual((code, payload["cli"]), (0, str(self.artifact)))

    def test_check_that_updates_keeps_the_zipapp_in_the_marker(self):
        self.artifact.write_bytes(b"known-good-cli")
        self.artifact.chmod(0o700)
        bootstrap.save_marker(self.host, self.artifact)

        code, payload, opened = self.check("1.3.0")

        self.assertEqual((code, payload["update_check"]), (0, "updated"))
        opened.assert_called_once()
        self.assertEqual(self.artifact.read_bytes(), self.payload)
        self.assertEqual(bootstrap.installed_cli_path(self.host), self.artifact)
        self.assertTrue((self.bin / "palmate").is_file())

    def test_posix_paths_are_unchanged_and_no_launchers_are_written(self):
        with patch.object(bootstrap, "WINDOWS", False):
            self.assertEqual(self.install(), 0)

        cli = self.bin / "palmate"
        self.assertEqual(cli.read_bytes(), self.payload)
        self.assertEqual(bootstrap.installed_cli_path(self.host), cli)
        self.assertFalse(self.artifact.exists())
        self.assertFalse((self.bin / "palmate.cmd").exists())


class ResumableDeviceLoginTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="palmate-login-test-")
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(
            os.environ, {"PALMATE_HOME": str(self.root / "state")}, clear=False,
        )
        self.environment.start()
        self.host = "https://api.palmate.ai"
        self.destination = self.root / "bin" / "palmate"
        self.authorization = {
            "device_code": "d" * 32,
            "user_code": "ABCD-EFGH",
            "verification_uri": f"{self.host}/device",
            "verification_uri_complete": f"{self.host}/device?user_code=ABCD-EFGH",
            "expires_in": 600,
            "interval": 5,
        }

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def start(self, *, now=1000):
        with patch.object(bootstrap, "request_json", return_value=self.authorization):
            return bootstrap.start_device_login(
                self.host, self.destination, open_browser=False, now=now,
            )

    def test_start_persists_before_exit_and_reuses_the_live_code(self):
        with patch.object(
            bootstrap, "request_json", return_value=self.authorization,
        ) as request:
            first = bootstrap.start_device_login(
                self.host, self.destination, open_browser=False, now=1000,
            )
            second = bootstrap.start_device_login(
                self.host, self.destination, open_browser=False, now=1001,
            )

        self.assertEqual(first["status"], "pending")
        self.assertTrue(second["reused"])
        request.assert_called_once()
        path = bootstrap.login_state_path()
        stored = json.loads(path.read_text(encoding="utf-8"))["logins"][self.host]
        self.assertEqual(stored["device_code"], "d" * 32)
        self.assertNotIn("device_code", first)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_status_returns_without_polling_before_interval(self):
        self.start()
        with patch.object(bootstrap, "request_json_result") as request:
            value = bootstrap.device_login_status(self.host, now=1001)
        self.assertEqual(value["status"], "pending")
        self.assertEqual(value["next_poll_in"], 4)
        request.assert_not_called()

    def test_network_failure_keeps_the_grant_resumable(self):
        self.start()
        with patch.object(
            bootstrap,
            "request_json_result",
            side_effect=bootstrap.BootstrapError("network unavailable"),
        ):
            value = bootstrap.device_login_status(self.host, now=1005)
        self.assertEqual(value["status"], "pending")
        self.assertIn("network unavailable", value["last_error"])
        stored = json.loads(
            bootstrap.login_state_path().read_text(encoding="utf-8")
        )["logins"][self.host]
        self.assertEqual(stored["device_code"], "d" * 32)

    def test_approval_installs_and_scrubs_all_temporary_secrets(self):
        self.start()
        self.destination.parent.mkdir(parents=True)
        self.destination.write_bytes(b"cli")
        self.destination.chmod(0o700)
        with (
            patch.object(
                bootstrap,
                "request_json_result",
                return_value=(200, {"access_token": "access", "refresh_token": "refresh"}),
            ),
            patch.object(bootstrap, "download_cli", return_value=self.destination),
            patch.object(bootstrap, "persist_with_installed_cli"),
            patch.object(bootstrap, "save_marker"),
            patch.object(bootstrap, "installed_cli_identity", return_value=("0.5.1", "access")),
            patch.object(bootstrap, "record_session_check"),
        ):
            value = bootstrap.device_login_status(self.host, now=1005)

        self.assertEqual(value["status"], "approved")
        state_text = bootstrap.login_state_path().read_text(encoding="utf-8")
        stored = json.loads(state_text)["logins"][self.host]
        self.assertNotIn("device_code", stored)
        self.assertNotIn("access_token", stored)
        self.assertNotIn("refresh_token", stored)
        self.assertNotIn("access", state_text)
        self.assertNotIn("refresh", state_text)

    def test_download_failure_can_be_retried_without_reapproval(self):
        self.start()
        with (
            patch.object(
                bootstrap,
                "request_json_result",
                return_value=(200, {"access_token": "access", "refresh_token": "refresh"}),
            ) as request,
            patch.object(
                bootstrap, "download_cli",
                side_effect=bootstrap.BootstrapError("download disconnected"),
            ),
        ):
            first = bootstrap.device_login_status(self.host, now=1005)

        self.assertEqual(first["status"], "pending")
        self.assertEqual(first["phase"], "installing")
        stored = json.loads(
            bootstrap.login_state_path().read_text(encoding="utf-8")
        )["logins"][self.host]
        self.assertEqual(stored["status"], "authorized")
        self.assertEqual(stored["access_token"], "access")
        request.assert_called_once()

    def test_install_failure_becomes_terminal_after_bounded_attempts(self):
        self.start()
        with (
            patch.object(
                bootstrap,
                "request_json_result",
                return_value=(200, {"access_token": "access", "refresh_token": "refresh"}),
            ),
            patch.object(
                bootstrap, "download_cli",
                side_effect=bootstrap.BootstrapError("release unavailable"),
            ),
        ):
            values = [
                bootstrap.device_login_status(self.host, now=1005 + index)
                for index in range(bootstrap.MAX_INSTALL_ATTEMPTS)
            ]

        self.assertEqual(values[-1]["status"], "error")
        self.assertIn("failed after 3 attempts", values[-1]["last_error"])
        state_text = bootstrap.login_state_path().read_text(encoding="utf-8")
        stored = json.loads(state_text)["logins"][self.host]
        self.assertNotIn("access_token", stored)
        self.assertNotIn("refresh_token", stored)
        self.assertNotIn("access", state_text)
        self.assertNotIn("refresh", state_text)


class AdapterParityTests(unittest.TestCase):
    def test_each_setup_skill_is_self_contained(self):
        for skill, legacy_script in (
            (CODEX_SKILL, ROOT / "codex" / "scripts" / "bootstrap_palmate.py"),
            (
                CLAUDE_SKILL,
                ROOT / "claude-code" / "scripts" / "bootstrap_palmate.py",
            ),
        ):
            with self.subTest(skill=skill):
                self.assertTrue((skill / "scripts" / "bootstrap_palmate.py").is_file())
                self.assertIn(
                    "scripts/bootstrap_palmate.py",
                    (skill / "SKILL.md").read_text(encoding="utf-8"),
                )
                self.assertFalse(legacy_script.exists())

    def test_codex_and_claude_bootstraps_are_identical(self):
        self.assertEqual(CODEX_BOOTSTRAP.read_bytes(), CLAUDE_BOOTSTRAP.read_bytes())


def load_variant(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeJSONResponse(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(json.dumps(payload).encode())
        self.status = status
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


# Spec 124 / backend 058 P0 (contracts.md C9): the version gate answers 426 to
# `palmate-cli/<v>` below CLI_MIN_VERSION. The bootstrap must identify itself
# so the device page can show it, but never as a CLI the gate would refuse.
CLI_GATE = r"^palmate-cli/(\d+)\.(\d+)\.(\d+)"
WORKFLOW_TEST_LINE = (
    "`palmate test start` waits until the bot is ready; `palmate test chat "
    "SESSION \"text\"` sends and waits for the whole turn; `palmate scenarios "
    "run` defaults to concurrency 2, do not raise it; on `cli_upgrade_required` "
    "run the palmate-setup update and retry; on `test_paused` stop and report it."
)


class BootstrapUserAgentTests(unittest.TestCase):
    def test_both_bootstraps_send_the_bootstrap_user_agent(self):
        for path in (CODEX_BOOTSTRAP, CLAUDE_BOOTSTRAP):
            variant = path.relative_to(ROOT).parts[0]
            with self.subTest(variant=variant):
                module = load_variant(
                    path, "bootstrap_" + variant.replace("-", "_"),
                )
                with patch.object(
                    module.OPENER, "open",
                    return_value=FakeJSONResponse({"device_code": "x"}),
                ) as opener_open:
                    module.request_json_result(
                        "https://palmate.test/api/palmate-cli/device/authorize/",
                        form={"client_id": module.CLIENT_ID},
                    )
                request = opener_open.call_args.args[0]
                self.assertEqual(
                    request.get_header("User-agent"),
                    f"palmate-cli-bootstrap/{module.BOOTSTRAP_VERSION}",
                )
                self.assertEqual(module.BOOTSTRAP_VERSION, "0.6.1")

    def test_bootstrap_user_agent_never_matches_the_cli_gate(self):
        module = load_variant(CODEX_BOOTSTRAP, "bootstrap_gate_probe")
        user_agent = f"palmate-cli-bootstrap/{module.BOOTSTRAP_VERSION}"
        self.assertIsNone(re.match(CLI_GATE, user_agent))
        # The probe itself is sound: a CLI user agent does match.
        self.assertIsNotNone(re.match(CLI_GATE, "palmate-cli/0.7.2"))


class PluginReleaseTests(unittest.TestCase):
    def test_both_variants_stay_identical(self):
        self.assertEqual(CODEX_BOOTSTRAP.read_bytes(), CLAUDE_BOOTSTRAP.read_bytes())
        for variant in ("codex", "claude-code"):
            with self.subTest(variant=variant):
                skill = ROOT / variant / "skills" / "palmate-workflow" / "SKILL.md"
                text = " ".join(skill.read_text(encoding="utf-8").split())
                self.assertIn(WORKFLOW_TEST_LINE, text)

    def test_plugin_versions_are_0_6_1(self):
        claude = json.loads(
            (ROOT / "claude-code" / ".claude-plugin" / "plugin.json").read_text(),
        )
        marketplace = json.loads(
            (ROOT / ".claude-plugin" / "marketplace.json").read_text(),
        )
        codex = json.loads(
            (ROOT / "codex" / ".codex-plugin" / "plugin.json").read_text(),
        )
        self.assertEqual(claude["version"], "0.6.1")
        self.assertEqual(
            [plugin["version"] for plugin in marketplace["plugins"]], ["0.6.1"],
        )
        self.assertRegex(codex["version"], r"^0\.6\.1\+codex\.\d{14}$")
        self.assertEqual(bootstrap.BOOTSTRAP_VERSION, "0.6.1")


if __name__ == "__main__":
    unittest.main()
