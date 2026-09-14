from __future__ import annotations

import json
import hashlib
from pathlib import Path
import tempfile
import unittest

import installer


ROOT = Path(__file__).resolve().parents[1]


class ChannelManifestTests(unittest.TestCase):
    def test_rc_channel_is_exact(self) -> None:
        value = installer.load_channel(ROOT / "channels/rc.json", "rc")
        self.assertEqual(value["version"], "1.0.0-rc.3")
        self.assertEqual(value["tag"], "v1.0.0-rc.3")
        self.assertEqual(
            value["commit"],
            "8eb5133d0ef5642b15871b045215a687fd3efd8b",
        )
        self.assertEqual(
            value["sha256"],
            "14cb2e7946fb59b88b07fba690862cf2c913c4252c6b287ee27f79664cb18ffb",
        )
        self.assertTrue(value["prerelease"])

    def test_stable_is_explicitly_unavailable(self) -> None:
        self.assertEqual(
            hashlib.sha256((ROOT / "channels/stable.json").read_bytes()).hexdigest(),
            "93ef9399559cbc444686917dca9c43ae93df1d0dd8abd0e97c3cc95c47891dd5",
        )
        with self.assertRaisesRegex(installer.InstallerError, "stable") as caught:
            installer.load_channel(ROOT / "channels/stable.json", "stable")
        self.assertEqual(caught.exception.code, "STABLE_RELEASE_UNAVAILABLE")

    def test_manifest_rejects_unexpected_repository(self) -> None:
        value = json.loads((ROOT / "channels/rc.json").read_text())
        value["repository"] = "attacker/aven"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "channel.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(installer.InstallerError) as caught:
                installer.load_channel(path, "rc")
        self.assertEqual(caught.exception.code, "RELEASE_MANIFEST_INVALID")

    def test_manifest_rejects_command_injection_token(self) -> None:
        value = json.loads((ROOT / "channels/rc.json").read_text())
        value["tag"] = "v1.0.0-rc.3; touch owned"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "channel.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(installer.InstallerError):
                installer.load_channel(path, "rc")

    def test_manifest_rejects_internally_consistent_unapproved_release(self) -> None:
        value = json.loads((ROOT / "channels/rc.json").read_text())
        value["installation_lock_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "channel.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(installer.InstallerError) as caught:
                installer.load_channel(path, "rc")
        self.assertEqual(caught.exception.code, "RELEASE_IDENTITY_NOT_APPROVED")

    def test_old_rc2_identity_is_no_longer_approved(self) -> None:
        value = {
            "asset": "aven-v1.0.0-rc.2-bootstrap-0c9b9b62d82a.tar",
            "asset_size": 256000,
            "build_report_asset": "aven-v1.0.0-rc.2-bootstrap-0c9b9b62d82a.build.json",
            "channel": "rc",
            "checksum_asset": "aven-v1.0.0-rc.2-bootstrap-0c9b9b62d82a.tar.sha256",
            "commit": "0c9b9b62d82a42c5bca19b6cfdca99f51734a1aa",
            "installation_lock_sha256": "a0a79f169b3d3e632271cf4dd9a9223f75d6c04f5144e583fa24f2dbcf87a3ca",
            "prerelease": True,
            "repository": "christophersix66/intelligence-workbench",
            "schema": "aven-install.channel.v1",
            "sha256": "0c57109a02811817fbefddf95bf989892ecda9673fccdb68cf1b84dfca843582",
            "tag": "v1.0.0-rc.2",
            "version": "1.0.0-rc.2",
            "workbench_runtime_commit": "f802a1adb49cbdf3fffe7798a38dc1971644852b",
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "channel.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(installer.InstallerError) as caught:
                installer.load_channel(path, "rc")
        self.assertEqual(caught.exception.code, "RELEASE_IDENTITY_NOT_APPROVED")

    def test_duplicate_json_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "channel.json"
            path.write_text('{"schema":"one","schema":"two"}', encoding="utf-8")
            with self.assertRaises(installer.InstallerError):
                installer.load_channel(path, "rc")


if __name__ == "__main__":
    unittest.main()
