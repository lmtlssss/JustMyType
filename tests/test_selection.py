import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("selection", Path(__file__).parents[1] / "plugins/justmytype/scripts/selection.py")
selection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selection)


def reply(payload):
    return {"status": "ok", "answers": {k: {"type": "score", "score": 3.5} for k in payload["questions"]},
            "usage": {"input_tokens": 10, "output_tokens": 0}, "evaluations": 1, "cache_hit": False}


class SelectionTests(unittest.TestCase):
    def candidate(self, ident, text="x"):
        return {"id": ident, "description": "reference", "text": text}

    def test_protected_no_call(self):
        payload = {"goal": "g", "candidates": [{"id": "keep", "description": "d", "text": "mandatory", "kind": "instruction"}]}
        out = selection.select(payload, evaluate=lambda _: self.fail("callback called"))
        self.assertEqual(out["selected"][0]["text"], "mandatory")
        self.assertEqual(out["evaluations"], 0)

    def test_batches(self):
        calls = []
        payload = {"goal": "g", "candidates": [self.candidate(f"c{i}") for i in range(64)]}
        out = selection.select(payload, evaluate=lambda p: (calls.append(p), reply(p))[1])
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(len(p["questions"]) == 16 for p in calls))
        self.assertEqual(out["evaluations"], 4)
        self.assertEqual(out["usage"]["input_tokens"], 40)
        self.assertEqual(len(out["selected"]), 64)
        self.assertNotIn("text", str(calls))
        self.assertNotIn("source", str(calls))

    def test_partial(self):
        calls = []
        payload = {"goal": "g", "candidates": [self.candidate(str(i)) for i in range(17)]}
        def evaluate(p):
            calls.append(p)
            return reply(p) if len(calls) == 1 else {"status": "unassessed", "evaluations": 1, "usage": {}}
        out = selection.select(payload, evaluate=evaluate)
        self.assertEqual(out["coverage"]["assessed"], 16)
        self.assertEqual(out["coverage"]["unassessed"], 1)
        self.assertIsNone(out["no_match"])
        self.assertEqual(out["evaluations"], 2)

    def test_omission_and_char_budget(self):
        payload = {"goal": "g", "max_chars": 2, "candidates": [self.candidate("A", "é"), self.candidate("B", "xx"), self.candidate("C", "z")]}
        scores = {"A": 3.5, "B": 4, "C": 0}
        out = selection.select(payload, evaluate=lambda p: {"status": "ok", "answers": {k: {"type": "score", "score": scores[k]} for k in p["questions"]}})
        self.assertEqual([x["id"] for x in out["selected"]], ["B"])
        self.assertEqual({x["id"]: x["reason"] for x in out["omitted"]}, {"A": "over_budget", "C": "below_threshold"})

    def test_protected_overflow(self):
        payload = {"goal": "g", "max_chars": 2, "candidates": [{"id": "r", "description": "d", "text": "abc", "required": True}]}
        out = selection.select(payload, evaluate=lambda _: self.fail("callback called"))
        self.assertEqual(out["status"], "budget_exceeded")
        self.assertEqual(out["evaluations"], 0)

    def test_bad_batch(self):
        payload = {"goal": "g", "candidates": [self.candidate("a"), self.candidate("b")]}
        out = selection.select(payload, evaluate=lambda _: {"status": "ok", "answers": {"a": {"type": "score", "score": 3}}})
        self.assertEqual(out["coverage"]["assessed"], 0)
        self.assertIsNone(out["no_match"])

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            selection.select({"goal": "g", "candidates": [{"id": "a", "description": "d", "required": 1}]}, evaluate=reply)
        with self.assertRaises(ValueError):
            selection.select({"goal": "g", "candidates": [self.candidate("a"), self.candidate("a")]}, evaluate=reply)
        with self.assertRaises(ValueError):
            selection.select({"goal": "g", "cache": {"namespace": "n"}, "candidates": []}, evaluate=reply)
