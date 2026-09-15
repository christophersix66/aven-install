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
        self.assertEqual(value["version"], "1.0.0-rc.6")
        self.assertEqual(value["tag"], "v1.0.0-rc.6")
        self.assertEqual(
            value["commit"],
            "a73ccf65f160ba545a1def31fd7aed9691ab0cac",
        )
        self.assertEqual(
            value["sha256"],
            "701653c2fe2ae503b87028e14fba00f1c651486ae9bd20e9b2068650cde2e445",
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
        value["tag"] = "v1.0.0-rc.6; touch owned"
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

    def test_old_rc5_identity_is_no_longer_approved(self) -> None:
        value = {
            "asset": "aven-v1.0.0-rc.5-bootstrap-9abf024c6452.tar",
            "asset_size": 317440,
            "build_report_asset": "aven-v1.0.0-rc.5-bootstrap-9abf024c6452.build.json",
            "channel": "rc",
            "checksum_asset": "aven-v1.0.0-rc.5-bootstrap-9abf024c6452.tar.sha256",
            "commit": "9abf024c6452cbbc9eba66a8a4282cf9592c8330",
            "installation_lock_sha256": "019661a4574418b591f358f7bde3b594de2d5a2e7541e9f6d15e47c52e09db1f",
            "prerelease": True,
            "repository": "christophersix66/intelligence-workbench",
            "schema": "aven-install.channel.v1",
            "sha256": "34ea8d040472643b7e58c138e1abcb5aeb043a66d25f5d78b0361b4cfd1b340d",
            "tag": "v1.0.0-rc.5",
            "version": "1.0.0-rc.5",
            "workbench_runtime_commit": "1686017f25d93e2e81efa6bd8877b0e31e0727d1",
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
