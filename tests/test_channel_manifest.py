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
        self.assertEqual(value["version"], "1.0.0-rc.4")
        self.assertEqual(value["tag"], "v1.0.0-rc.4")
        self.assertEqual(
            value["commit"],
            "a8b43dd239d976feee7881cd278c4f58e1d1cc8e",
        )
        self.assertEqual(
            value["sha256"],
            "344469574fff1b69ae5e91cd9bf8efa6c8b7791e93e8a406ec5fb727b064367c",
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
        value["tag"] = "v1.0.0-rc.4; touch owned"
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

    def test_old_rc3_identity_is_no_longer_approved(self) -> None:
        value = {
            "asset": "aven-v1.0.0-rc.3-bootstrap-8eb5133d0ef5.tar",
            "asset_size": 286720,
            "build_report_asset": "aven-v1.0.0-rc.3-bootstrap-8eb5133d0ef5.build.json",
            "channel": "rc",
            "checksum_asset": "aven-v1.0.0-rc.3-bootstrap-8eb5133d0ef5.tar.sha256",
            "commit": "8eb5133d0ef5642b15871b045215a687fd3efd8b",
            "installation_lock_sha256": "7093aad4a744607bd4cdaf40ef1156c0b2c3468c358a1bacca779ea86b849788",
            "prerelease": True,
            "repository": "christophersix66/intelligence-workbench",
            "schema": "aven-install.channel.v1",
            "sha256": "14cb2e7946fb59b88b07fba690862cf2c913c4252c6b287ee27f79664cb18ffb",
            "tag": "v1.0.0-rc.3",
            "version": "1.0.0-rc.3",
            "workbench_runtime_commit": "01aa0aea33d91ea40d42d8884ea8b43b4a54acca",
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
