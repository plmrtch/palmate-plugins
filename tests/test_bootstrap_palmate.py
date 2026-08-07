from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
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

    def tearDown(self):
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


if __name__ == "__main__":
    unittest.main()
