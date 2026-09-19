import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("jmt_toolkit_test", ROOT / "plugins/justmytype/scripts/jmt.py")
jmt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(jmt)


def response(payload):
    answers = {}
    for ident, question in payload["questions"].items():
        kind = question["type"]
        if kind == "noul":
            answers[ident] = {"type": kind, "noul": 0.9}
        elif kind == "choice":
            keys = list(question["criteria"])
            answers[ident] = {"type": kind, "choice": keys[0],
                "probabilities": {key: float(key == keys[0]) for key in keys}, "confidence": 1.0}
        else:
            levels = question["criteria"]
            answers[ident] = {"type": kind, "score": float(len(levels) - 1),
                "probabilities": {str(i): float(i == len(levels) - 1) for i in range(len(levels))},
                "legend": {str(i): value for i, value in enumerate(levels)}, "confidence": 1.0}
    return {"model": jmt.MODEL, "answers": answers, "usage": {"input_tokens": 20, "output_tokens": 4}}


class ToolkitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.cfg = dict(jmt.DEFAULTS, cloud_enabled=True)
        self.payload = {"state": {"goal": "Choose a source"}, "questions": {
            "pick": {"type": "choice", "instructions": "Pick a source", "criteria": {"a": "First", "none": "No match"}},
            "present": {"type": "noul", "instructions": "Is a source present?"},
            "relevance": {"type": "score", "instructions": "Rate relevance", "criteria": ["Unrelated", "Useful", "Essential"]}}}

    def test_all_types_share_existing_transport(self):
        calls = []
        out = jmt.toolkit(self.payload, self.cfg, self.directory,
                          transport=lambda p: (calls.append(p), response(p))[1])
        self.assertEqual(out["status"], "ok")
        self.assertEqual(len(calls), 1)
        self.assertEqual(out["answers"]["relevance"]["score"], 2.0)
        self.assertEqual(out["usage"]["input_tokens"], 20)

    def test_advisory_reuse_is_generation_scoped(self):
        calls = []
        payload = dict(self.payload, cache={"namespace": "task", "generation": "v1"})
        transport = lambda p: (calls.append(p), response(p))[1]
        first = jmt.toolkit(payload, self.cfg, self.directory, transport=transport)
        hit = jmt.toolkit(payload, self.cfg, self.directory, transport=transport)
        self.assertEqual(first["status"], "ok")
        self.assertTrue(hit["cache_hit"])
        self.assertEqual(hit["evaluations"], 0)
        self.assertEqual(hit["usage"], {"input_tokens": 0, "output_tokens": 0})
        self.assertEqual(hit["source_usage"], first["usage"])
        payload["cache"]["generation"] = "v2"
        self.assertFalse(jmt.toolkit(payload, self.cfg, self.directory, transport=transport)["cache_hit"])
        self.assertEqual(len(calls), 2)

    def test_selector_uses_real_score_validator(self):
        calls = []
        payload = {"goal": "Find release instructions", "candidates": [
            {"id": "rule", "description": "Binding requirement", "kind": "instruction", "text": "KEEP VERBATIM"},
            {"id": "release", "description": "Release guide", "text": "PRIVATE BODY STAYS LOCAL", "source": "docs/release.md"}]}
        out = jmt.toolkit(payload, self.cfg, self.directory, "select",
                          transport=lambda p: (calls.append(p), response(p))[1])
        self.assertEqual(out["status"], "ok")
        self.assertEqual([item["id"] for item in out["selected"]], ["rule", "release"])
        self.assertNotIn("PRIVATE BODY STAYS LOCAL", json.dumps(calls))
        self.assertNotIn("docs/release.md", json.dumps(calls))
        self.assertEqual(out["selected"][0]["text"], "KEEP VERBATIM")

    def test_cloud_off_cli_has_no_provider_answer(self):
        process = subprocess.run([sys.executable, str(ROOT / "plugins/justmytype/scripts/jmt.py"),
                                  "--data-dir", str(self.directory), "decide"],
                                 input=json.dumps(self.payload), text=True, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 4)
        out = json.loads(process.stdout)
        self.assertEqual(out["reason_codes"], ["cloud_disabled"])
        self.assertEqual(out["answers"], {})

    def test_native_repeated_failure_is_advisory(self):
        event = {"session_id": "session", "turn_id": "turn"}
        graph = lambda sid: {"schema": 1, "session_id": sid, "phase": "build",
            "revision": 1, "generation": 1, "blueprint": {"objective": "Fix the reported issue"},
            "cursor": {"layer": "implementation", "next": "Inspect the failure"}}
        jmt.hook(dict(event, hook_event_name="UserPromptSubmit", prompt="Fix the issue"),
                 self.cfg, self.directory, task_loader=graph)
        outputs = []
        for i in range(4):
            outputs.append(jmt.hook(dict(event, hook_event_name="PostToolUse", tool_name="Bash",
                tool_input={"command": "example-check"}, cwd="/example",
                tool_response={"exit_code": 1, "output": "same failure", "chunk_id": str(i)}),
                self.cfg, self.directory, task_loader=graph))
        self.assertNotIn("Same action", str(outputs[0]))
        self.assertIn("Same action", str(outputs[2]))
        self.assertNotIn("Same action", str(outputs[3]))
        self.assertNotIn("permissionDecision", str(outputs))

    def test_guard_never_uses_advisory_cache(self):
        event = {"session_id": "s", "turn_id": "t"}
        calls = []
        assessor = lambda state, *args: (calls.append(state), jmt.verdict("pass", "observed", state))[1]
        absent = lambda sid: {"status": "absent"}
        jmt.hook(dict(event, hook_event_name="UserPromptSubmit", prompt="Inspect the demo"),
                 self.cfg, self.directory, assessor, absent)
        for _ in range(2):
            jmt.hook(dict(event, hook_event_name="PreToolUse", tool_name="Bash",
                         tool_input={"command": "example-status"}),
                     self.cfg, self.directory, assessor, absent)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
