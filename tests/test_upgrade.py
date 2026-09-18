import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.bin = Path(self.tmp.name) / "bin"
        self.home.mkdir()
        self.calls = []
        self.marketplace = None

    def tearDown(self):
        self.tmp.cleanup()

    def fake_cli(self, binary, env, *args):
        self.calls.append(args)
        if args[:3] == ("plugin", "marketplace", "list"):
            return json.dumps({"marketplaces": [] if self.marketplace is None else [{"name": "justmytype", "root": self.marketplace, "marketplaceSource": {"sourceType": "local", "source": self.marketplace}}]})
        if args[:3] == ("plugin", "marketplace", "add"):
            self.marketplace = args[3]
        if args[:3] == ("plugin", "marketplace", "remove"):
            self.marketplace = None
        return "codex 1"

    def test_first_install_and_idempotent_preserves_private_state(self):
        with patch.object(install, "cli", self.fake_cli), patch.object(install, "trust_hooks", lambda *a: []):
            install.install(ROOT, self.home, self.bin, "codex", False)
            data = self.home / "plugins/data/justmytype-justmytype"
            (data / "private.json").write_bytes(b"private")
            install.install(ROOT, self.home, self.bin, "codex", False)
        self.assertEqual((data / "private.json").read_bytes(), b"private")
        self.assertTrue((data / "active").read_text().startswith("payloads/"))
        self.assertGreaterEqual(len(self.calls), 4)

    def test_tampered_payload_and_path_escape_rejected(self):
        with patch.object(install, "cli", self.fake_cli):
            install.install(ROOT, self.home, self.bin, "codex", False)
        data = self.home / "plugins/data/justmytype-justmytype"
        active = data / "active"
        active.write_text("../escape\n")
        with patch.object(install, "cli", self.fake_cli), self.assertRaises(ValueError):
            install.install(ROOT, self.home, self.bin, "codex", False)

    def test_bad_pointer_hook_is_honest_and_zero(self):
        data = self.home / "plugins/data/justmytype-justmytype"
        data.mkdir(parents=True)
        (data / "active").write_text("../escape\n")
        hook = ROOT / "plugins/justmytype/scripts/hook.py"
        result = subprocess.run([sys.executable, str(hook), "--data-dir", str(data), "hook"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("systemMessage", result.stdout)

    def test_unrelated_launcher(self):
        self.bin.mkdir()
        launcher = self.bin / "justmytype"
        launcher.write_bytes(b"unrelated launcher")
        before = launcher.read_bytes()
        with patch.object(install, "cli", self.fake_cli), self.assertRaises(RuntimeError):
            install.install(ROOT, self.home, self.bin, "codex", False)
        self.assertEqual(launcher.read_bytes(), before)
        self.assertFalse(any(call[:2] == ("plugin", "marketplace") for call in self.calls))

    def test_payload_tamper(self):
        with patch.object(install, "cli", self.fake_cli):
            install.install(ROOT, self.home, self.bin, "codex", False)
        data = self.home / "plugins/data/justmytype-justmytype"
        active_before = (data / "active").read_bytes()
        payload = data / active_before.decode().strip()
        with (payload / "plugins/justmytype/scripts/jmt.py").open("ab") as stream:
            stream.write(b"\n# tampered")
        with patch.object(install, "cli", self.fake_cli), self.assertRaises(RuntimeError):
            install.install(ROOT, self.home, self.bin, "codex", False)
        self.assertEqual((data / "active").read_bytes(), active_before)

    def test_rollback_after_registration(self):
        with patch.object(install, "cli", self.fake_cli):
            install.install(ROOT, self.home, self.bin, "codex", False)
        data = self.home / "plugins/data/justmytype-justmytype"
        fixtures = data / "private.json", data / "state.json"
        for path in fixtures:
            path.write_bytes(b"fixture")
        old = {name: (data / name).read_bytes() for name in ("active", "hook.py", "install-receipt.json")}
        old["launcher"] = (self.bin / "justmytype").read_bytes()
        source = Path(self.tmp.name) / "source"
        for name in install.REQUIRED:
            destination = source / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        with (source / "plugins/justmytype/scripts/jmt.py").open("ab") as stream:
            stream.write(b"\n# source B")
        original_write = install.atomic_write
        failed = {"done": False}
        def fail_receipt(path, content, mode=None):
            if path.name == "install-receipt.json" and not failed["done"]:
                failed["done"] = True
                raise OSError("receipt write failed")
            return original_write(path, content, mode)
        with patch.object(install, "cli", self.fake_cli), patch.object(install, "atomic_write", fail_receipt), self.assertRaises(OSError):
            install.install(source, self.home, self.bin, "codex", False)
        self.assertEqual((data / "active").read_bytes(), old["active"])
        self.assertEqual((data / "hook.py").read_bytes(), old["hook.py"])
        self.assertEqual((data / "install-receipt.json").read_bytes(), old["install-receipt.json"])
        self.assertEqual((self.bin / "justmytype").read_bytes(), old["launcher"])
        self.assertTrue(all(path.read_bytes() == b"fixture" for path in fixtures))
        self.assertIn(("plugin", "marketplace", "add", str(data / old["active"].decode().strip())), self.calls)
        self.assertFalse(any(call[:2] == ("plugin", "remove") for call in self.calls))

    def test_legacy_path_survives_eviction(self):
        cache = self.home / "plugins/cache/justmytype/justmytype/0.2.0"
        (cache / "scripts").mkdir(parents=True)
        (cache / ".codex-plugin").mkdir()
        (cache / ".codex-plugin/plugin.json").write_text(json.dumps({"name": "justmytype", "version": "0.2.0"}))
        old_entry = cache / "scripts/jmt.py"
        old_entry.write_text("# old public fixture\n")
        original = self.fake_cli
        def evict(binary, env, *args):
            result = self.fake_cli(binary, env, *args)
            if args[:2] == ("plugin", "add"):
                if cache.exists():
                    shutil.rmtree(cache)
            return result
        with patch.object(install, "cli", evict):
            install.install(ROOT, self.home, self.bin, "codex", False)
        forwarded = self.home / "plugins/cache/justmytype/justmytype/0.2.0/scripts/jmt.py"
        self.assertTrue(forwarded.exists())
        self.assertTrue((self.home / "plugins/data/justmytype-justmytype/compatibility-backups/0.2.0-jmt.py").exists())
        result = subprocess.run([sys.executable, str(forwarded), "--data-dir", str(self.home / "plugins/data/justmytype-justmytype"), "doctor"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("0.2.1", result.stdout + result.stderr)

    def test_unexpected_existing_marketplace_owner_rejected_without_remove(self):
        self.marketplace = "/ чужой/root"
        with patch.object(install, "cli", self.fake_cli), self.assertRaises(Exception):
            install.install(ROOT, self.home, self.bin, "codex", False)
        self.assertFalse(any(call[:3] == ("plugin", "marketplace", "remove") for call in self.calls))


if __name__ == "__main__":
    unittest.main()
