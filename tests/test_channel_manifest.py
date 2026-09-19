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
        self.assertEqual(value["version"], "1.0.0-rc.20")
        self.assertEqual(value["tag"], "v1.0.0-rc.20")
        self.assertEqual(
            value["commit"],
            "b520cd46486209b1892b3c23c9b2392e8f6f9365",
        )
        self.assertEqual(
            value["sha256"],
            "058aa63e1fa4953a4b40ca7ad4a29fe61d0285edaec51dfd12a9f96e81aa7845",
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
        value["tag"] = "v1.0.0-rc.20; touch owned"
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

    def test_old_rc7_identity_is_no_longer_approved(self) -> None:
        value = {
            "asset": "aven-v1.0.0-rc.7-bootstrap-810ecb8629d1.tar",
            "asset_size": 327680,
            "build_report_asset": "aven-v1.0.0-rc.7-bootstrap-810ecb8629d1.build.json",
            "channel": "rc",
            "checksum_asset": "aven-v1.0.0-rc.7-bootstrap-810ecb8629d1.tar.sha256",
            "commit": "810ecb8629d16ed1816f7547f7e8fc47b5662893",
            "installation_lock_sha256": "3cddcb39edbe60eace7db03a40dcd77f5ea3a2088c6c262ef332d593f4fe1d97",
            "prerelease": True,
            "repository": "christophersix66/intelligence-workbench",
            "schema": "aven-install.channel.v1",
            "sha256": "00d26efe02e8684870bea3d3bfe5674b1d4a7b4647f39d7a9d2937546f40dcc0",
            "tag": "v1.0.0-rc.7",
            "version": "1.0.0-rc.7",
            "workbench_runtime_commit": "6a6731d8bc92382004166602f50d0e000a6fd577",
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
