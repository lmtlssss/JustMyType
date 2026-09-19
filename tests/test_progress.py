import tempfile
import unittest
from pathlib import Path
from plugins.justmytype.scripts.progress import record, snapshot

class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.directory = self.tempdir.name
        self.response = {"isError": True, "exit_code": 1}
    def call(self, **changes):
        data = dict(session="s", task="t", generation="g", tool="run", arguments={"x": 1}, cwd="/tmp", response=self.response, redact=lambda x: x)
        data.update(changes)
        return record(self.directory, **data)
    def test_counts_and_advisory(self):
        self.assertEqual(self.call()["count"], 1); self.assertEqual(self.call()["count"], 2)
        self.assertEqual(self.call()["advisory"]["count"], 3); self.assertIsNone(self.call()["advisory"])
    def test_changed_and_sessions(self):
        self.call(); self.assertEqual(self.call(generation="next")["count"], 1); self.assertEqual(self.call(session="other")["count"], 1)
    def test_empty_and_redaction(self):
        self.assertEqual(snapshot(self.directory, session="s", task="t")["count"], 0)
        result = self.call(arguments={"secret": "secret-value"}, redact=lambda value: {**value, "arguments": {"secret": "REDACTED"}})
        self.assertEqual(result["status"], "unassessed"); self.assertEqual(snapshot(self.directory, session="s", task="t")["count"], 0)
        self.assertFalse(Path(self.directory, "progress.sqlite3").exists())
    def test_pending_not_success(self):
        result = self.call(response={"running": True}); self.assertEqual(result["observation_status"], "pending"); self.assertIsNone(result["advisory"])

    def test_volatile_metadata(self):
        results = [self.call(response={"exit_code": 1, "output": "same", "chunk_id": str(i), "wall_time_seconds": i}) for i in range(3)]
        self.assertEqual(results[-1]["advisory"]["kind"], "repeated_failure")

    def test_latest_terminal(self):
        self.call(response={"exit_code": 0}); self.call(response={"exit_code": 1})
        self.assertEqual(len(snapshot(self.directory, session="s", task="t")["unresolved_failures"]), 1)
        self.call(response={"exit_code": 0})
        self.assertEqual(len(snapshot(self.directory, session="s", task="t")["unresolved_failures"]), 0)

    def test_scoped_retention(self):
        self.call(session="other")
        for i in range(70):
            self.call(arguments={"i": i})
        self.assertEqual(snapshot(self.directory, session="other", task="t")["count"], 1)
        self.assertEqual(snapshot(self.directory, session="s", task="t")["count"], 64)

    def test_not_proof(self):
        for _ in range(3):
            result = self.call(response={"output": "PASS"})
            self.assertEqual(result["observation_status"], "unknown")
            self.assertIsNone(result["advisory"])
        for _ in range(3):
            result = self.call(response={"running": True})
            self.assertEqual(result["observation_status"], "pending")
            self.assertIsNone(result["advisory"])
        self.assertEqual(self.call(response={"exit_code": True})["observation_status"], "unknown")

    def test_bound(self):
        result = self.call(generation="")
        self.assertEqual(result["status"], "unassessed")
        self.assertFalse(Path(self.directory, "progress.sqlite3").exists())

if __name__ == "__main__":
    unittest.main()
