from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

import installer


ROOT = Path(__file__).resolve().parents[1]


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, "")


class InstallContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.channel = dict(installer.load_channel(ROOT / "channels/rc.json", "rc"))

    def _tar(self, path: Path, members: list[tuple[str, bytes, str]]) -> None:
        with tarfile.open(path, "w") as archive:
            for name, payload, kind in members:
                info = tarfile.TarInfo(name)
                if kind == "file":
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
                elif kind == "dir":
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                elif kind == "symlink":
                    info.type = tarfile.SYMTYPE
                    info.linkname = "../../outside"
                    archive.addfile(info)

    def _rc24_channel(self) -> dict[str, object]:
        value = dict(self.channel)
        value.update({
            "version": "1.0.0-rc.24",
            "tag": "v1.0.0-rc.24",
            "commit": "a" * 40,
            "workbench_runtime_commit": "b" * 40,
            "installation_lock_sha256": "c" * 64,
        })
        return value

    def test_macos_entrypoint_discovers_homebrew_python_without_shell_mutation(self) -> None:
        script = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("/opt/homebrew/bin/python3", script)
        self.assertIn("/usr/local/bin/python3", script)
        self.assertIn("AMBIGUOUS_HOMEBREW_PYTHON", script)
        self.assertIn("shell profiles are unchanged", script)
        self.assertNotIn("--break-system-packages", script)
        for shell_file in (".zshrc", ".zprofile", ".bashrc", ".bash_profile", ".profile"):
            self.assertNotIn(shell_file, script)

    def test_safe_extract_accepts_regular_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "fixture.tar"
            destination = root / "output"
            destination.mkdir()
            self._tar(archive, [("aven-bootstrap", b"ok", "file"), ("lib/module.py", b"pass\n", "file")])
            installer.safe_extract(archive, destination)
            self.assertEqual((destination / "aven-bootstrap").read_bytes(), b"ok")
            self.assertEqual((destination / "lib/module.py").read_bytes(), b"pass\n")

    def test_safe_extract_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "fixture.tar"
            destination = root / "output"
            destination.mkdir()
            self._tar(archive, [("../outside", b"bad", "file")])
            with self.assertRaises(installer.InstallerError) as caught:
                installer.safe_extract(archive, destination)
            self.assertEqual(caught.exception.code, "ARCHIVE_UNSAFE")
            self.assertFalse((root / "outside").exists())

    def test_safe_extract_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "fixture.tar"
            destination = root / "output"
            destination.mkdir()
            self._tar(archive, [("escape", b"", "symlink")])
            with self.assertRaises(installer.InstallerError):
                installer.safe_extract(archive, destination)

    def test_safe_extract_rejects_case_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "fixture.tar"
            destination = root / "output"
            destination.mkdir()
            self._tar(archive, [("File", b"one", "file"), ("file", b"two", "file")])
            with self.assertRaises(installer.InstallerError):
                installer.safe_extract(archive, destination)

    def test_release_resolution_requires_exact_tag_and_assets(self) -> None:
        release = {
            "tag_name": self.channel["tag"],
            "draft": False,
            "prerelease": True,
            "assets": [
                {"name": self.channel["asset"], "size": self.channel["asset_size"], "digest": "sha256:" + self.channel["sha256"]},
                {"name": self.channel["checksum_asset"], "size": 110},
                {"name": self.channel["build_report_asset"], "size": 1902},
            ],
        }
        results = iter([
            _completed(json.dumps({"object": {"type": "commit", "sha": self.channel["commit"]}})),
            _completed(json.dumps(release)),
        ])
        with mock.patch("installer._run_gh", side_effect=lambda *args, **kwargs: next(results)):
            installer.resolve_release("/usr/bin/gh", self.channel)

    def test_release_resolution_peels_one_exact_annotated_tag(self) -> None:
        tag_object = "a" * 40
        release = {
            "tag_name": self.channel["tag"],
            "draft": False,
            "prerelease": True,
            "assets": [
                {
                    "name": self.channel["asset"],
                    "size": self.channel["asset_size"],
                    "digest": "sha256:" + self.channel["sha256"],
                },
                {"name": self.channel["checksum_asset"]},
                {"name": self.channel["build_report_asset"]},
            ],
        }
        results = iter([
            _completed(json.dumps({"object": {"type": "tag", "sha": tag_object}})),
            _completed(json.dumps({"object": {"type": "commit", "sha": self.channel["commit"]}})),
            _completed(json.dumps(release)),
        ])
        with mock.patch("installer._run_gh", side_effect=lambda *args, **kwargs: next(results)) as run:
            installer.resolve_release("/usr/bin/gh", self.channel)
        self.assertIn(f"git/tags/{tag_object}", run.call_args_list[1].args[1][1])

    def test_release_resolution_rejects_tag_rebound(self) -> None:
        with mock.patch("installer._run_gh", return_value=_completed(json.dumps({"object": {"type": "commit", "sha": "0" * 40}}))):
            with self.assertRaises(installer.InstallerError) as caught:
                installer.resolve_release("/usr/bin/gh", self.channel)
        self.assertEqual(caught.exception.code, "RELEASE_TAG_MISMATCH")

    def test_release_resolution_rejects_duplicate_assets(self) -> None:
        asset = {
            "name": self.channel["asset"],
            "size": self.channel["asset_size"],
            "state": "uploaded",
            "digest": "sha256:" + self.channel["sha256"],
        }
        release = {
            "tag_name": self.channel["tag"],
            "draft": False,
            "prerelease": True,
            "assets": [asset, dict(asset)],
        }
        results = iter([
            _completed(json.dumps({"object": {"type": "commit", "sha": self.channel["commit"]}})),
            _completed(json.dumps(release)),
        ])
        with mock.patch("installer._run_gh", side_effect=lambda *args, **kwargs: next(results)):
            with self.assertRaises(installer.InstallerError) as caught:
                installer.resolve_release("/usr/bin/gh", self.channel)
        self.assertEqual(caught.exception.code, "RELEASE_ASSET_MISMATCH")

    def test_download_verification_checks_digest_checksum_and_report(self) -> None:
        payload = b"exact archive bytes"
        channel = dict(self.channel)
        channel["asset_size"] = len(payload)
        channel["sha256"] = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / channel["asset"]).write_bytes(payload)
            (root / channel["checksum_asset"]).write_text(f"{channel['sha256']}  {channel['asset']}\n", encoding="utf-8")
            report = {
                "artifact": channel["asset"],
                "artifact_sha256": channel["sha256"],
                "source_commit": channel["commit"],
                "installation_lock_sha256": channel["installation_lock_sha256"],
                "contains_credentials": False,
                "contains_component_repositories": False,
            }
            (root / channel["build_report_asset"]).write_text(json.dumps(report), encoding="utf-8")
            self.assertEqual(installer.verify_download(channel, root), root / channel["asset"])
            (root / channel["asset"]).write_bytes(b"tampered")
            with self.assertRaises(installer.InstallerError) as caught:
                installer.verify_download(channel, root)
            self.assertEqual(caught.exception.code, "ARTIFACT_SHA256_MISMATCH")

    def test_check_mode_performs_no_install_mutation(self) -> None:
        stdout = io.StringIO()
        with (
            mock.patch("installer.platform_identity", return_value=("linux", "x86_64")),
            mock.patch("installer.ensure_required_tools", return_value={"git": {"path": "/usr/bin/git", "version": "git version 2.40.0"}, "gh": {"path": "/usr/bin/gh", "version": "gh version 2.40.0"}}),
            mock.patch("installer.ensure_github_access"),
            mock.patch("installer.resolve_release"),
            mock.patch("installer.inspect_existing_aven", return_value="NOT_INSTALLED"),
            mock.patch("installer.download_release") as download,
            mock.patch("sys.stdout", stdout),
        ):
            result = installer.main(["--manifest", str(ROOT / "channels/rc.json"), "--channel", "rc", "--check"])
        self.assertEqual(result, 0)
        self.assertIn("Mutations performed: 0", stdout.getvalue())
        download.assert_not_called()

    def test_check_mode_renders_exact_predecessor_and_target(self) -> None:
        stdout = io.StringIO()
        with (
            mock.patch("installer.platform_identity", return_value=("linux", "x86_64")),
            mock.patch("installer.ensure_required_tools", return_value={"git": {"path": "/usr/bin/git", "version": "git version 2.40.0"}, "gh": {"path": "/usr/bin/gh", "version": "gh version 2.40.0"}}),
            mock.patch("installer.ensure_github_access"),
            mock.patch("installer.resolve_release"),
            mock.patch("installer.inspect_existing_aven", return_value="NORMAL_UPGRADE_READY:1.0.0-rc.23"),
            mock.patch("installer.download_release") as download,
            mock.patch("sys.stdout", stdout),
        ):
            result = installer.main(["--manifest", str(ROOT / "channels/rc.json"), "--channel", "rc", "--check"])
        self.assertEqual(result, 0)
        self.assertIn("Approved predecessor: 1.0.0-rc.23", stdout.getvalue())
        self.assertIn("Predecessor classification: NORMAL_UPGRADE_READY", stdout.getvalue())
        self.assertIn("Target release: 1.0.0-rc.24", stdout.getvalue())
        self.assertNotIn("RC.7", stdout.getvalue())
        self.assertIn("Ready to upgrade: YES", stdout.getvalue())
        self.assertIn("Mutations performed: 0", stdout.getvalue())
        download.assert_not_called()

    def test_rc24_has_no_direct_corrective_predecessor_exception(self) -> None:
        self.assertEqual(installer.APPROVED_CORRECTIVE_PREDECESSORS, ())

    def test_existing_install_requires_exact_current_or_approved_predecessor(self) -> None:
        exact = installer.APPROVED_HEALTHY_PREDECESSORS[0]
        predecessor = {
            "status": "INSTALLED",
            "aven_version": exact["aven_version"],
            "installation_lock_sha256": exact["installation_lock_sha256"],
            "workbench_commit": exact["workbench_commit"],
            "distribution": {
                "bootstrap_source_commit": exact["bootstrap_source_commit"],
                "bootstrap_manifest_sha256": exact["bootstrap_manifest_sha256"],
            },
        }
        healthy = {"status": "HEALTHY"}
        with tempfile.TemporaryDirectory() as temporary:
            launcher = Path(temporary) / "aven"
            launcher.write_text("fixture", encoding="utf-8")
            with (
                mock.patch("installer._conventional_aven", return_value=launcher),
                mock.patch("installer._run", side_effect=[_completed(json.dumps(predecessor)), _completed(json.dumps(healthy))]),
            ):
                self.assertEqual(
                    installer.inspect_existing_aven("linux", self._rc24_channel()),
                    "NORMAL_UPGRADE_READY:1.0.0-rc.23",
                )
            tampered = dict(predecessor)
            tampered["installation_lock_sha256"] = "0" * 64
            with (
                mock.patch("installer._conventional_aven", return_value=launcher),
                mock.patch("installer._run", return_value=_completed(json.dumps(tampered))),
                self.assertRaises(installer.InstallerError) as caught,
            ):
                installer.inspect_existing_aven("linux", self._rc24_channel())
        self.assertEqual(caught.exception.code, "AVEN_DIFFERENT_INSTALLATION")

    def test_exact_rc17_is_not_carried_forward_as_rc19_predecessor(self) -> None:
        exact = {
            "aven_version": "1.0.0-rc.17",
            "installation_lock_sha256": "e4745391d36c33b43c08835e7a5face6fb84e57930a2fa70f297c32f5c6d86b5",
            "workbench_commit": "16a088f393bb73cc42019676e370fd6e44c35d7c",
            "bootstrap_source_commit": "01f48ad26ca0be67240111b4b08d4486913da8b3",
            "bootstrap_manifest_sha256": "bf87b48b05bab49ba53316ba12cbaa51cccf2b6780974e4d2315d471d199679d",
        }
        version = {
            "status": "INSTALLED",
            "aven_version": exact["aven_version"],
            "installation_lock_sha256": exact["installation_lock_sha256"],
            "workbench_commit": exact["workbench_commit"],
            "distribution": {
                "bootstrap_source_commit": exact["bootstrap_source_commit"],
                "bootstrap_manifest_sha256": exact["bootstrap_manifest_sha256"],
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            launcher = Path(temporary) / "aven"
            launcher.write_text("fixture", encoding="utf-8")
            with (
                mock.patch("installer._conventional_aven", return_value=launcher),
                mock.patch("installer._run", return_value=_completed(json.dumps(version))),
                self.assertRaises(installer.InstallerError) as caught,
            ):
                installer.inspect_existing_aven("linux", self.channel)
        self.assertEqual(caught.exception.code, "AVEN_DIFFERENT_INSTALLATION")

    def test_unhealthy_exact_rc23_predecessor_has_no_bypass(self) -> None:
        exact = installer.APPROVED_HEALTHY_PREDECESSORS[0]
        version = {
            "status": "INSTALLED",
            "aven_version": exact["aven_version"],
            "installation_lock_sha256": exact["installation_lock_sha256"],
            "workbench_commit": exact["workbench_commit"],
            "distribution": {
                "bootstrap_source_commit": exact["bootstrap_source_commit"],
                "bootstrap_manifest_sha256": exact["bootstrap_manifest_sha256"],
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            launcher = Path(temporary) / "aven"
            launcher.write_text("fixture", encoding="utf-8")
            with (
                mock.patch("installer._conventional_aven", return_value=launcher),
                mock.patch(
                    "installer._run",
                    side_effect=[_completed(json.dumps(version)), _completed(returncode=2)],
                ),
                self.assertRaises(installer.InstallerError) as caught,
            ):
                installer.inspect_existing_aven("linux", self.channel)
        self.assertEqual(caught.exception.code, "AVEN_REPAIR_REQUIRED")

    def test_healthy_rc21_is_not_a_general_skip_predecessor(self) -> None:
        version = {
            "status": "INSTALLED",
            "aven_version": "1.0.0-rc.21",
            "installation_lock_sha256": "e307f288de5e2d28fcc973c48a4c195de3ccf97f26b07e4147a98e4667bbe066",
            "workbench_commit": "caf35515f788aba54109d91a17f3c2d421812cbc",
            "distribution": {
                "bootstrap_source_commit": "67036f2bf5a2928b84be61c0207824f1f8f32798",
                "bootstrap_manifest_sha256": "7ec95f68f3436b2d97cf9b980c2da324eb86610d05128a4f0397957767b6d6aa",
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            launcher = Path(temporary) / "aven"
            launcher.write_text("fixture", encoding="utf-8")
            with (
                mock.patch("installer._conventional_aven", return_value=launcher),
                mock.patch(
                    "installer._run",
                    return_value=_completed(json.dumps(version)),
                ),
                self.assertRaises(installer.InstallerError) as caught,
            ):
                installer.inspect_existing_aven("linux", self._rc24_channel())
        self.assertEqual(caught.exception.code, "AVEN_DIFFERENT_INSTALLATION")

    def test_failed_rc9_is_not_accepted_by_version_ordering(self) -> None:
        failed_rc9 = {
            "status": "INSTALLED", "aven_version": "1.0.0-rc.9",
            "installation_lock_sha256": "1" * 64,
            "workbench_commit": "2" * 40,
            "distribution": {
                "bootstrap_source_commit": "3" * 40,
                "bootstrap_manifest_sha256": "4" * 64,
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            launcher = Path(temporary) / "aven"
            launcher.write_text("fixture", encoding="utf-8")
            with (
                mock.patch("installer._conventional_aven", return_value=launcher),
                mock.patch("installer._run", return_value=_completed(json.dumps(failed_rc9))),
                self.assertRaises(installer.InstallerError) as caught,
            ):
                installer.inspect_existing_aven("linux", self.channel)
        self.assertEqual(caught.exception.code, "AVEN_DIFFERENT_INSTALLATION")

    def test_apply_runs_plan_then_apply_and_health(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            archive = temp_root / "fixture.tar"
            archive.write_bytes(b"fixture")
            with (
                mock.patch("installer.platform_identity", return_value=("macos", "arm64")),
                mock.patch("installer.ensure_required_tools", return_value={"git": {"path": "/usr/bin/git", "version": "git version 2.40.0"}, "gh": {"path": "/usr/bin/gh", "version": "gh version 2.40.0"}}),
                mock.patch("installer.ensure_github_access"),
                mock.patch("installer.resolve_release"),
                mock.patch("installer.inspect_existing_aven", return_value="NOT_INSTALLED"),
                mock.patch("installer.download_release"),
                mock.patch("installer.verify_download", return_value=archive),
                mock.patch("installer.safe_extract", side_effect=lambda _a, destination: (destination / "aven-bootstrap").write_text("bootstrap")),
                mock.patch("installer._bootstrap_git_environment", return_value={}),
                mock.patch("installer._ensure_git_repository_access"),
                mock.patch("installer._invoke_bootstrap", side_effect=lambda _p, _b, action, inherit, env: calls.append(action)),
                mock.patch("installer.post_install_health", return_value=Path.home() / ".local/bin/aven"),
                mock.patch.dict("os.environ", {"AVEN_INSTALL_TMPDIR": temporary}, clear=False),
            ):
                result = installer.main(["--manifest", str(ROOT / "channels/rc.json"), "--channel", "rc", "--non-interactive", "--yes"])
        self.assertEqual(result, 0)
        self.assertEqual(calls, ["--plan", "--apply"])

    def test_exact_predecessor_upgrade_uses_owned_uninstall_then_target_setup(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            archive = temp_root / "fixture.tar"
            archive.write_bytes(b"fixture")
            existing = iter([
                "NORMAL_UPGRADE_READY:1.0.0-rc.23",
                "NORMAL_UPGRADE_READY:1.0.0-rc.23",
            ])
            with (
                mock.patch("installer.platform_identity", return_value=("linux", "x86_64")),
                mock.patch("installer.ensure_required_tools", return_value={"git": {"path": "/usr/bin/git", "version": "git version 2.40.0"}, "gh": {"path": "/usr/bin/gh", "version": "gh version 2.40.0"}}),
                mock.patch("installer.ensure_github_access"),
                mock.patch("installer.resolve_release"),
                mock.patch("installer.inspect_existing_aven", side_effect=lambda *_args: next(existing)),
                mock.patch("installer.download_release"),
                mock.patch("installer.verify_download", return_value=archive),
                mock.patch("installer.safe_extract", side_effect=lambda _a, destination: (destination / "aven-bootstrap").write_text("bootstrap")),
                mock.patch("installer._bootstrap_git_environment", return_value={}),
                mock.patch("installer._ensure_git_repository_access"),
                mock.patch(
                    "installer._capture_predecessor_snapshot",
                    return_value={
                        "schema": "aven-install.predecessor-rollback-snapshot.v1",
                        "records": [],
                    },
                ),
                mock.patch("installer._invoke_predecessor_uninstall", side_effect=lambda _s, action, predecessor_version, inherit: calls.append(f"uninstall:{predecessor_version}:{action}")),
                mock.patch("installer._invoke_bootstrap", side_effect=lambda _p, _b, action, inherit, env: calls.append(f"setup:{action}")),
                mock.patch("installer.post_install_health", return_value=Path.home() / ".local/bin/aven"),
                mock.patch.dict("os.environ", {"AVEN_INSTALL_TMPDIR": temporary}, clear=False),
            ):
                result = installer.main(["--manifest", str(ROOT / "channels/rc.json"), "--channel", "rc", "--non-interactive", "--yes"])
        self.assertEqual(result, 0)
        self.assertEqual(
            calls,
            ["uninstall:1.0.0-rc.23:--plan", "uninstall:1.0.0-rc.23:--apply", "setup:--plan", "setup:--apply"],
        )

    def test_predecessor_uninstall_uses_only_conventional_owned_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            launcher = Path(temporary) / "aven"
            launcher.write_text("fixture", encoding="utf-8")
            with (
                mock.patch("installer._conventional_aven", return_value=launcher),
                mock.patch("installer._run", return_value=_completed()) as run,
            ):
                installer._invoke_predecessor_uninstall(
                    "linux", "--plan", predecessor_version="1.0.0-rc.23", inherit=False
                )
        self.assertEqual(run.call_args.args[0], (str(launcher), "uninstall", "--plan"))
        self.assertEqual(run.call_args.kwargs["cwd"], Path.home())

    def test_predecessor_snapshot_restores_owned_and_codex_integration_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            codex_home = root / "codex"
            install_root = home / ".local/share/aven/installations/exact"
            install_root.mkdir(parents=True)
            (install_root / "runtime.txt").write_text("rc21\n", encoding="utf-8")
            command = home / ".local/bin/aven"
            command.parent.mkdir(parents=True)
            command.symlink_to(install_root / "runtime.txt")
            config = home / ".config/aven/machine.json"
            config.parent.mkdir(parents=True)
            config.write_text("{}\n", encoding="utf-8")
            codex_home.mkdir()
            (codex_home / "config.toml").write_text("old\n", encoding="utf-8")
            cache = codex_home / "plugins/cache/aven-keel"
            cache.mkdir(parents=True)
            (cache / "identity").write_text("rc21\n", encoding="utf-8")
            plan = {
                "status": "READY",
                "installation_id": "exact",
                "user_configuration_preserved": True,
                "optional_environment_preserved": True,
                "actions": [
                    {"action": "REMOVE_OWNED_LINK", "path": str(command)},
                    {"action": "REMOVE_OWNED_CONTROL_FILE", "path": str(config)},
                    {"action": "REMOVE_OWNED_INSTALLATION_ROOT", "path": str(install_root)},
                ],
            }
            launcher = root / "launcher"
            launcher.write_text("fixture", encoding="utf-8")
            with (
                mock.patch("installer._conventional_aven", return_value=launcher),
                mock.patch("installer._run", return_value=_completed(json.dumps(plan))),
                mock.patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}, clear=False),
            ):
                snapshot = installer._capture_predecessor_snapshot(
                    "linux", root / "snapshot"
                )
            command.unlink()
            config.write_text("target\n", encoding="utf-8")
            shutil.rmtree(install_root)
            (codex_home / "config.toml").write_text("target\n", encoding="utf-8")
            shutil.rmtree(cache)
            installer._restore_predecessor_snapshot(snapshot)
            self.assertTrue(command.is_symlink())
            self.assertEqual(config.read_text(encoding="utf-8"), "{}\n")
            self.assertEqual((install_root / "runtime.txt").read_text(), "rc21\n")
            self.assertEqual((codex_home / "config.toml").read_text(), "old\n")
            self.assertEqual((cache / "identity").read_text(), "rc21\n")

    def test_failed_upgrade_retires_target_and_restores_predecessor(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "fixture.tar"
            archive.write_bytes(b"fixture")
            classifications = iter([
                "NORMAL_UPGRADE_READY:1.0.0-rc.23",
                "NORMAL_UPGRADE_READY:1.0.0-rc.23",
                "NORMAL_UPGRADE_READY:1.0.0-rc.23",
            ])
            def bootstrap(_python, _bootstrap, action, *, inherit, env):
                calls.append("bootstrap:" + action)
                if action == "--apply":
                    raise installer.InstallerError("INJECTED", "target apply failed")
            with (
                mock.patch("installer.platform_identity", return_value=("linux", "x86_64")),
                mock.patch("installer.ensure_required_tools", return_value={"git": {"path": "/usr/bin/git", "version": "git version 2.40.0"}, "gh": {"path": "/usr/bin/gh", "version": "gh version 2.40.0"}}),
                mock.patch("installer.ensure_github_access"),
                mock.patch("installer.resolve_release"),
                mock.patch("installer.inspect_existing_aven", side_effect=lambda *_args: next(classifications)),
                mock.patch("installer.download_release"),
                mock.patch("installer.verify_download", return_value=archive),
                mock.patch("installer.safe_extract", side_effect=lambda _a, destination: (destination / "aven-bootstrap").write_text("bootstrap")),
                mock.patch("installer._bootstrap_git_environment", return_value={}),
                mock.patch("installer._ensure_git_repository_access"),
                mock.patch("installer._capture_predecessor_snapshot", return_value={"schema": "aven-install.predecessor-rollback-snapshot.v1", "records": []}),
                mock.patch("installer._invoke_predecessor_uninstall"),
                mock.patch("installer._invoke_bootstrap", side_effect=bootstrap),
                mock.patch("installer._retire_failed_target", side_effect=lambda _system: calls.append("retire")),
                mock.patch("installer._restore_predecessor_snapshot", side_effect=lambda _snapshot: calls.append("restore")),
                mock.patch.dict("os.environ", {"AVEN_INSTALL_TMPDIR": temporary}, clear=False),
                mock.patch("sys.stderr", io.StringIO()),
            ):
                result = installer.main([
                    "--manifest", str(ROOT / "channels/rc.json"), "--channel", "rc",
                    "--non-interactive", "--yes",
                ])
        self.assertEqual(result, 2)
        self.assertEqual(calls[-2:], ["retire", "restore"])

    def test_bootstrap_git_credentials_are_transient_and_access_is_preflighted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch("installer._run_gh", return_value=_completed()) as run_gh:
                environment = installer._bootstrap_git_environment("/usr/bin/gh", root)
            config = root / "gitconfig"
            self.assertEqual(environment["GIT_CONFIG_GLOBAL"], str(config))
            self.assertEqual(
                environment["AVEN_BOOTSTRAP_INSTALL_CHANNEL"],
                "PRIVATE_RELEASE_CANDIDATE",
            )
            self.assertTrue(config.is_file())
            self.assertEqual(
                run_gh.call_args.args,
                ("/usr/bin/gh", ("auth", "setup-git", "--hostname", "github.com")),
            )
            with mock.patch("installer._run", return_value=_completed()) as run:
                installer._ensure_git_repository_access(
                    "/usr/bin/git", self.channel, env=environment
                )
        self.assertEqual(
            run.call_args.args[0],
            (
                "/usr/bin/git",
                "ls-remote",
                "--exit-code",
                "https://github.com/christophersix66/intelligence-workbench.git",
                "HEAD",
            ),
        )
        self.assertEqual(run.call_args.kwargs["env"], environment)

    def test_noninteractive_apply_requires_explicit_yes(self) -> None:
        with (
            mock.patch("installer.platform_identity", return_value=("windows", "x86_64")),
            mock.patch("installer.ensure_required_tools", return_value={"git": {"path": "/usr/bin/git", "version": "git version 2.40.0"}, "gh": {"path": "/usr/bin/gh", "version": "gh version 2.40.0"}}),
            mock.patch("installer.ensure_github_access"),
            mock.patch("installer.resolve_release"),
            mock.patch("installer.inspect_existing_aven", return_value="NOT_INSTALLED"),
        ):
            result = installer.main(["--manifest", str(ROOT / "channels/rc.json"), "--channel", "rc", "--non-interactive"])
        self.assertEqual(result, 2)

    def test_no_subprocess_uses_shell(self) -> None:
        with mock.patch("subprocess.run", return_value=_completed()) as run:
            installer._run(("gh", "auth", "status"))
        self.assertIs(run.call_args.kwargs["shell"], False)

    def test_github_commands_disable_telemetry_and_use_neutral_cwd(self) -> None:
        with mock.patch("installer._run", return_value=_completed()) as run:
            installer._run_gh("/usr/bin/gh", ("auth", "status"), timeout=20)
        self.assertEqual(run.call_args.args[0], ("/usr/bin/gh", "auth", "status"))
        self.assertEqual(run.call_args.kwargs["cwd"], Path.home())
        self.assertEqual(run.call_args.kwargs["env"]["GH_TELEMETRY"], "0")
        self.assertEqual(run.call_args.kwargs["env"]["GH_NO_UPDATE_NOTIFIER"], "1")

    def test_package_manager_commands_are_fixed_argument_arrays(self) -> None:
        with mock.patch("installer._resolve_executable", side_effect=lambda item: "/usr/bin/apt-get" if item == "apt-get" else None), mock.patch("installer._sudo_prefix", return_value=["/usr/bin/sudo"]):
            commands = installer.prerequisite_install_commands("linux", ["git", "gh"])
        self.assertEqual(commands, [["/usr/bin/sudo", "/usr/bin/apt-get", "install", "-y", "git", "gh"]])

    def test_tool_versions_are_parsed_and_too_old_is_rejected(self) -> None:
        self.assertTrue(installer._usable_tool("git", ("/usr/bin/git", "git version 2.44.1")))
        self.assertTrue(installer._usable_tool("gh", ("/usr/bin/gh", "gh version 2.45.0 (2024-02-21)")))
        self.assertFalse(installer._usable_tool("git", ("/usr/bin/git", "git version 1.9.5")))
        self.assertFalse(installer._usable_tool("gh", ("/usr/bin/gh", "unexpected output")))

    def test_relative_executable_path_is_rejected(self) -> None:
        with mock.patch("installer.shutil.which", return_value="./gh"):
            with self.assertRaises(installer.InstallerError) as caught:
                installer._resolve_executable("gh")
        self.assertEqual(caught.exception.code, "UNTRUSTED_EXECUTABLE_PATH")

    def test_ambient_aven_cannot_counterfeit_installed_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            expected = Path(temporary) / "owned" / "aven"
            with (
                mock.patch("installer._conventional_aven", return_value=expected),
                mock.patch("installer.shutil.which", return_value=str(Path(temporary) / "attacker" / "aven")),
            ):
                self.assertEqual(installer.inspect_existing_aven("linux", self.channel), "NOT_INSTALLED")

    @unittest.skipIf(os.name == "nt", "POSIX entrypoint test")
    def test_shell_entrypoint_rejects_tampered_coordinator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            (source / "channels").mkdir(parents=True)
            (source / "installer.py").write_text("raise SystemExit('should not execute')\n", encoding="utf-8")
            shutil.copy2(ROOT / "channels/rc.json", source / "channels/rc.json")
            environment = os.environ.copy()
            environment["TMPDIR"] = temporary
            completed = subprocess.run(
                ("sh", str(ROOT / "install.sh"), "--source-dir", str(source), "--check"),
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("INSTALLER_INTEGRITY_MISMATCH", completed.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell is unavailable")
    def test_powershell_entrypoint_rejects_tampered_coordinator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            (source / "channels").mkdir(parents=True)
            (source / "installer.py").write_text("raise SystemExit('should not execute')\n", encoding="utf-8")
            shutil.copy2(ROOT / "channels/rc.json", source / "channels/rc.json")
            environment = os.environ.copy()
            environment["AVEN_INSTALL_TMPDIR"] = temporary
            completed = subprocess.run(
                ("pwsh", "-NoProfile", "-File", str(ROOT / "install.ps1"), "-SourceDir", str(source), "-Check"),
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("INSTALLER_INTEGRITY_MISMATCH", completed.stderr)

    def test_entrypoints_contain_no_tracing_or_fallback_installer(self) -> None:
        shell = (ROOT / "install.sh").read_text(encoding="utf-8")
        powershell = (ROOT / "install.ps1").read_text(encoding="utf-8")
        self.assertNotIn("set -x", shell)
        self.assertNotRegex(shell, r"\beval\b")
        self.assertNotIn("Invoke-Expression", powershell)
        self.assertNotIn("intelligence-platform", shell + powershell)

    def test_entrypoints_pin_coordinator_and_channel_content(self) -> None:
        coordinator = hashlib.sha256((ROOT / "installer.py").read_bytes()).hexdigest()
        rc_manifest = hashlib.sha256((ROOT / "channels/rc.json").read_bytes()).hexdigest()
        stable_manifest = hashlib.sha256((ROOT / "channels/stable.json").read_bytes()).hexdigest()
        shell = (ROOT / "install.sh").read_text(encoding="utf-8")
        powershell = (ROOT / "install.ps1").read_text(encoding="utf-8")
        for digest in (coordinator, rc_manifest, stable_manifest):
            self.assertIn(digest, shell)
            self.assertIn(digest, powershell)


if __name__ == "__main__":
    unittest.main()
