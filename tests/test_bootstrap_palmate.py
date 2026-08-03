from __future__ import annotations

import importlib.util
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
