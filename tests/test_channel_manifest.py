from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import installer


ROOT = Path(__file__).resolve().parents[1]


class ChannelManifestTests(unittest.TestCase):
    def test_rc_channel_is_exact(self) -> None:
        value = installer.load_channel(ROOT / "channels/rc.json", "rc")
        self.assertEqual(value["version"], "1.0.0-rc.1")
        self.assertEqual(value["tag"], "v1.0.0-rc.1")
        self.assertEqual(
            value["commit"],
            "b66e56796c9bbb4879921d5c77fb9b8dfaa0e3da",
        )
        self.assertEqual(
            value["sha256"],
            "4c6a32d8ac727513e48dcce114631aacc74fb3963180181578a7f0f5bb6fb8d9",
        )
        self.assertTrue(value["prerelease"])

    def test_stable_is_explicitly_unavailable(self) -> None:
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
        value["tag"] = "v1.0.0-rc.1; touch owned"
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

    def test_duplicate_json_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "channel.json"
            path.write_text('{"schema":"one","schema":"two"}', encoding="utf-8")
            with self.assertRaises(installer.InstallerError):
                installer.load_channel(path, "rc")


if __name__ == "__main__":
    unittest.main()
