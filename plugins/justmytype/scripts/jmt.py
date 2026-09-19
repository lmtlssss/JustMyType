#!/usr/bin/env python3
"""JustMyType: typed preflight, native Codex hooks, one local configuration."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import hashlib
import json
import math
import os
import platform
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

def _load_sibling(name):
    spec = importlib.util.spec_from_file_location("jmt_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

decisions = _load_sibling("decisions")
selection = _load_sibling("selection")
progress = _load_sibling("progress")
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

VERSION = "0.3.0"
NAME = "justmytype"
API_URL = "https://api.typesafe.ai/v1/systemone"
POLICY_PATH = Path(__file__).with_name("policy.json")
POLICY = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
MODEL = POLICY["model"]
ENGINE_SHA256 = hashlib.sha256(b"".join(Path(__file__).with_name(n).read_bytes() for n in ("jmt.py", "bindings.py", "policy.json", "decisions.py", "selection.py", "progress.py"))).hexdigest()
_bind_spec = importlib.util.spec_from_file_location("jmt_bindings", Path(__file__).with_name("bindings.py"))
bindings = importlib.util.module_from_spec(_bind_spec)
_bind_spec.loader.exec_module(bindings)
MAX_INPUT = 262144
MAX_STATE = 32768
MAX_RESPONSE = 32768
DEFAULTS = {"cloud_enabled": False, "mode": "observe", "credential_runner": [],
            "constraints": [], "max_calls_per_turn": 32}
SECRET_FIELD = re.compile(r"(?i)^(?:.*[_-])?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|authorization|cookie|private[_-]?key|credentials?)$")
ASSIGNMENT = re.compile(r'''(?ix)(\b[a-z0-9_-]*?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|authorization|cookie)\b["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)''')
TOKEN = re.compile(r"\b(?:sk[-_][A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|AKIA[A-Z0-9]{16})\b")
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def redact(value: Any) -> Any:
    """Best-effort evidence redaction, not a general secret detector."""
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SECRET_FIELD.fullmatch(k) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if not isinstance(value, str):
        return value
    value = PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", value)
    value = TOKEN.sub("[REDACTED]", value)
    value = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", value)
    value = ASSIGNMENT.sub(lambda m: m.group(1) + "[REDACTED]", value)
    # Exact known credentials are removed in memory only, never hashed or logged.
    for name, secret in os.environ.items():
        if SECRET_FIELD.fullmatch(name) and len(secret) >= 8:
            value = value.replace(secret, "[REDACTED]")
    return value


def data_dir(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    override = os.environ.get("JMT_DATA_DIR") or os.environ.get("PLUGIN_DATA")
    if override:
        return Path(override).expanduser().resolve()
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve() / "plugins/data/justmytype-justmytype"


def graphfather_context(session_id: str, directory: Path | None = None, loader: Callable | None = None) -> dict:
    """Read bounded active-task context through GraphFather's public CLI only."""
    if not isinstance(session_id, str) or not session_id:
        return {"status": "unassessed", "reason": "missing_turn_context"}
    if loader is not None:
        try:
            value = loader(session_id)
            return _validate_graph(value)
        except Exception:
            return {"status": "unassessed", "reason": "context_unavailable"}
    root = (directory or data_dir()).parent / "the-graphfather-the-graphfather"
    binary = root / ("the-graphfather.exe" if os.name == "nt" else "the-graphfather")
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return {"status": "absent"}
    try:
        proc = subprocess.run([str(binary), "--data-dir", str(root), "--session", session_id, "status", "--json"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=1, check=False)
        if len(proc.stdout) > 262144 or proc.returncode not in (0, 2):
            return {"status": "unassessed", "reason": "malformed_context"}
        raw = json.loads(proc.stdout.decode("utf-8"))
        if not isinstance(raw, dict):
            return {"status": "unassessed", "reason": "malformed_context"}
        return _validate_graph(raw)
    except (OSError, subprocess.TimeoutExpired, ValueError, UnicodeError):
        return {"status": "unassessed", "reason": "context_unavailable"}


def _validate_graph(value: Any) -> dict:
    if not isinstance(value, dict):
        return {"status": "unassessed", "reason": "malformed_context"}
    if value.get("status") in ("absent", "unassessed"):
        reason = value.get("reason", "malformed_context")
        if reason not in ("context_unavailable", "malformed_context"):
            reason = "malformed_context"
        return {"status": value["status"], "reason": reason}
    if value.get("schema") != 1:
        return {"status": "unassessed", "reason": "malformed_context"}
    if ("blueprint" in value and value["blueprint"] is None) or value.get("phase") in ("complete", "done"):
        return {"status": "absent"}
    b, c = value.get("blueprint"), value.get("cursor")
    if (len(canonical(value)) > 262144 or value.get("phase") not in ("build", "proof", "repair", "complete", "done")
            or not isinstance(value.get("session_id"), str) or not value["session_id"] or len(value["session_id"]) > 256
            or not isinstance(b, dict) or not isinstance(b.get("objective"), str) or not b["objective"]
            or len(b["objective"]) > 6000 or not isinstance(c, dict)
            or not (isinstance(c.get("layer"), str) or
                    (value.get("phase") in ("proof", "repair") and "layer" in c and c["layer"] is None))
            or not isinstance(c.get("next"), str) or len(c["next"]) > 6000
            or type(value.get("revision")) is not int or value["revision"] < 0
            or type(value.get("generation")) is not int or value["generation"] < 0):
        return {"status": "unassessed", "reason": "malformed_context"}
    return value


def load_config(directory: Path | None = None) -> dict:
    path = data_dir(directory) / "config.json"
    cfg = dict(DEFAULTS)
    if path.exists():
        raw = path.read_bytes()
        if len(raw) > 16384:
            raise ValueError("config_bound")
        extra = json.loads(raw)
        if not isinstance(extra, dict) or set(extra) - set(DEFAULTS):
            raise ValueError("invalid_config_keys")
        cfg.update(extra)
    if type(cfg["cloud_enabled"]) is not bool or cfg["mode"] not in ("observe", "guard"):
        raise ValueError("invalid_mode")
    for key in ("credential_runner", "constraints"):
        if not isinstance(cfg[key], list) or not all(isinstance(v, str) and v and "\0" not in v for v in cfg[key]):
            raise ValueError("invalid_config_list")
    if len(cfg["credential_runner"]) > 16 or len(canonical(cfg["constraints"])) > 6000:
        raise ValueError("config_bound")
    if type(cfg["max_calls_per_turn"]) is not int or not 1 <= cfg["max_calls_per_turn"] <= 256:
        raise ValueError("invalid_budget")
    return cfg


def save_config(directory: Path, cfg: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".config-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(canonical(cfg) + b"\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, directory / "config.json")
    finally:
        if os.path.exists(name):
            os.unlink(name)


def verdict(decision: str, reason: str | list[str], state: Any, *, probabilities: dict | None = None,
            usage: dict | None = None, latency: float = 0, basis: str = "local", model: str | None = None) -> dict:
    return {"decision": decision, "basis": basis, "reason_codes": [reason] if isinstance(reason, str) else reason,
            "probabilities": probabilities or {}, "model": model, "latency_ms": round(latency, 2),
            "usage": usage or {}, "policy_sha256": digest(POLICY), "state_sha256": digest(redact(state)), "engine_sha256": ENGINE_SHA256}


def strings(value: Any, limit: int = 32) -> bool:
    return isinstance(value, list) and len(value) <= limit and all(isinstance(v, str) for v in value)


def valid_state(state: Any, mode: str) -> bool:
    if not isinstance(state, dict) or not strings(state.get("evidence", [])):
        return False
    if mode == "verify":
        return isinstance(state.get("claim"), str)
    action = state.get("action")
    return (isinstance(state.get("goal"), str) and bool(state["goal"].strip())
            and strings(state.get("constraints", [])) and isinstance(action, dict)
            and isinstance(action.get("tool"), str) and bool(action["tool"])
            and isinstance(action.get("arguments"), dict))


def readonly(action: dict) -> bool:
    """Only literal pwd/git-status forms bypass the remote judgment."""
    if action.get("tool") not in ("Bash", "exec_command", "shell_command", "shell", "exec_argv"):
        return False
    args = action.get("arguments", {})
    if action["tool"] == "exec_argv":
        tokens = args.get("argv")
        if not strings(tokens):
            return False
    else:
        command = args.get("command", args.get("cmd"))
        if not isinstance(command, str) or re.search(r"[;$`|&<>\n\r(){}]", command):
            return False
        try:
            tokens = shlex.split(command)
        except ValueError:
            return False
    return tokens in (["pwd"], ["git", "status"], ["git", "status", "--short"], ["git", "status", "--porcelain"])


def literal_authorized(state: dict, cfg: dict) -> bool:
    """Only an exact positive goal/action pair can bypass semantic judgment."""
    if cfg.get("constraints") or state.get("constraints"):
        return False
    action = state.get("action", {})
    if not readonly(action):
        return False
    args = action["arguments"]
    command = " ".join(args["argv"]) if action["tool"] == "exec_argv" else args.get("command", args.get("cmd", "")).strip()
    goal = state.get("goal", "").strip().lower().rstrip(".")
    pairs = {
        ("print the current directory", "pwd"),
        ("show the current directory", "pwd"),
        ("show git status", "git status"),
        ("show git status --short", "git status --short"),
        ("show git status --porcelain", "git status --porcelain"),
    }
    return (goal, command) in pairs


def eligibility_reason(state: Any, mode: str, cfg: dict) -> str | None:
    if mode not in ("check", "verify") or not valid_state(state, mode):
        return "malformed_state"
    if mode == "check":
        tool, args = state["action"]["tool"], state["action"]["arguments"]
        if tool in ("Bash", "exec_command", "shell_command", "shell", "apply_patch"):
            if not isinstance(args.get("command", args.get("cmd")), str): return "malformed_tool_arguments"
        elif tool == "exec_argv":
            if not strings(args.get("argv")) or not args["argv"]: return "malformed_tool_arguments"
        elif tool in ("write_stdin", "functions.write_stdin"): return "uncovered_continuation"
        elif not tool.startswith("mcp__"): return "unsupported_tool"
        clean = redact(state)
        merged = dict(clean)
        merged["constraints"] = clean.get("constraints", []) + redact(cfg.get("constraints", []))
        if len(canonical(merged)) > MAX_STATE: return "state_bound"
    elif len(canonical(redact(state))) > MAX_STATE:
        return "state_bound"
    return None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("redirect_refused")


def probability(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def validate_response(result: Any, questions: dict) -> dict:
    if not isinstance(result, dict) or result.get("model") != MODEL:
        raise ValueError("model_mismatch")
    answers = result.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ValueError("answer_keys")
    for name, question in questions.items():
        answer = answers[name]
        if not isinstance(answer, dict) or answer.get("type") != question["type"]:
            raise ValueError("answer_type")
        if question["type"] == "noul":
            if not probability(answer.get("noul")):
                raise ValueError("invalid_probability")
        else:
            if question["type"] == "score":
                decisions._answer(question, answer)
                continue
            probs = answer.get("probabilities")
            if (not isinstance(probs, dict) or set(probs) != set(question["criteria"])
                    or not all(probability(v) for v in probs.values())
                    or abs(sum(probs.values()) - 1) > .02
                    or answer.get("choice") not in probs or not probability(answer.get("confidence"))):
                raise ValueError("invalid_choice")
            if probs[answer["choice"]] + .001 < max(probs.values()):
                raise ValueError("choice_not_max")
    usage = result.get("usage")
    if not isinstance(usage, dict) or not all(type(usage.get(k)) is int and usage[k] >= 0 for k in ("input_tokens", "output_tokens")):
        raise ValueError("invalid_usage")
    return result


def request_api(state: dict, questions: dict, transport: Callable | None = None, deadline: float | None = None) -> dict:
    payload = {"state": state, "model": MODEL, "questions": questions}
    if transport is not None:
        return validate_response(transport(payload), questions)
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise RuntimeError("missing_api_key")
    req = Request(API_URL, data=canonical(payload), headers={"Content-Type": "application/json", "Authorization": "Bearer " + key}, method="POST")
    opener = build_opener(NoRedirect())
    deadline = min(deadline if deadline is not None else float("inf"), time.monotonic() + 6)
    for attempt in range(2):
        if time.monotonic() >= deadline:
            raise TimeoutError("assessment_deadline")
        try:
            with opener.open(req, timeout=max(.1, min(4, deadline - time.monotonic()))) as response:
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise ValueError("response_bound")
                return validate_response(json.loads(raw), questions)
        except HTTPError as error:
            if error.code in (429, 529) and attempt == 0 and deadline - time.monotonic() > .8:
                error.close()
                time.sleep(.3)
                continue
            code = error.code
            error.close()
            raise RuntimeError("provider_http_" + str(code)) from None
    raise RuntimeError("provider_unavailable")


def evaluate(state: Any, config: dict | None = None, transport: Callable | None = None, mode: str = "check") -> dict:
    cfg = dict(DEFAULTS) | (config or {})
    started = time.monotonic()
    try:
        reason = eligibility_reason(state, mode, cfg)
        if reason: return verdict("unassessed", reason, {})
        clean = redact(state)
        if mode == "check":
            clean["constraints"] = clean.get("constraints", []) + redact(cfg["constraints"])
        if len(canonical(clean)) > MAX_STATE:
            return verdict("unassessed", "state_bound", {})
        if mode == "check" and literal_authorized(clean, cfg):
            return verdict("pass", "literal_read", clean)
        if not cfg["cloud_enabled"] and transport is None:
            return verdict("unassessed", "cloud_disabled", clean)
        deadline = time.monotonic() + 6
        responses, errors = [], []
        request_count = 0

        def query(job):
            try:
                return request_api(job[1], job[2], transport, deadline=deadline)
            except (RuntimeError, ValueError, TypeError, KeyError, OSError, URLError, TimeoutError):
                return None

        def collect(jobs):
            nonlocal request_count
            request_count += len(jobs)
            if len(jobs) <= 1:
                replies = [query(job) for job in jobs]
            else:
                with ThreadPoolExecutor(max_workers=POLICY["bindings"]["parallel_requests"]) as pool:
                    replies = list(pool.map(query, jobs))
            errors.extend(job[0] for job, result in zip(jobs, replies) if result is None)
            responses.extend(result for result in replies if result is not None)
            return replies

        rule_results, instruction_checks = [], []
        probs, reasons, decision = {}, [], "pass"
        if mode == "verify":
            reply = collect([("verification", clean, POLICY["verification"])])[0]
            if reply is not None:
                answer = reply["answers"]["support"]
                probs = answer["probabilities"]
                choice = answer["choice"]
                decision = ("block" if choice == "contradicted" and probs[choice] >= POLICY["thresholds"]["block"]
                            else "pass" if choice in ("supported", "no_claim") and probs[choice] >= .7 else "review")
                reasons = [choice]
        else:
            blocks = bindings.rule_blocks(clean)
            if len(blocks) > POLICY["rules"]["max_rules"]:
                return verdict("unassessed", "instruction_count_bound", clean)
            gates = bindings.prepare(clean, POLICY["bindings"])
            jobs = [(f"numeric_rule_{i}", bindings.request_state(gate, clean),
                     bindings.question_set(gate, POLICY["bindings"])) for i, gate in enumerate(gates)]
            if gates:
                authority_state, authority_questions = bindings.authority_request(gates, clean, POLICY["bindings"])
                jobs.append(("rule_authority", authority_state, authority_questions))
            replies = collect(jobs)
            authority = replies[-1] if gates else None
            cleared = set()
            for i, (gate, reply) in enumerate(zip(gates, replies)):
                if reply is None:
                    continue
                record = bindings.compose([gate], reply["answers"], POLICY["bindings"])[0]
                active = authority["answers"][f"a{i}"] if authority else None
                record["signals"]["authority"] = active
                record["enforced"] = bool(record["enforced"] and active and active["choice"] == "active"
                    and active["probabilities"]["active"] >= POLICY["bindings"]["authority_min"])
                resolved = bindings.resolved_without_violation(record, POLICY["bindings"], POLICY["rules"])
                record["resolved_without_violation"] = resolved
                if resolved:
                    cleared.add((gate["source"], gate["rule"]))
                rule_results.append(record)
            if any(record["enforced"] for record in rule_results):
                # An exact, source-bound violation is decisive. Do not pay to
                # reclassify the same number or pretend all other rules ran.
                decision, reasons = "block", ["numeric_rule_violation"]
            else:
                remaining = [block for block in blocks if (block["source"], block["text"]) not in cleared]
                atomic_state, questions = bindings.atomic_request(remaining, clean, POLICY["rules"])
                # Preserve independent irreversible-effect and failed-candidate
                # checks. Scope is evaluated per instruction, not as one vague score.
                questions.update({name: question for name, question in POLICY["questions"].items()
                                  if name != "scope_conflict"})
                reply = collect([("remaining_instructions", atomic_state, questions)])[0]
                if reply is not None:
                    for name in ("irreversible_without_basis", "failed_candidate"):
                        value = reply["answers"][name]["noul"]
                        probs[name] = value
                        if value >= POLICY["thresholds"]["block"]:
                            decision = "block"
                            reasons.append(name)
                        elif value >= POLICY["thresholds"]["review"]:
                            if decision != "block": decision = "review"
                            reasons.append(name)
                    for i, block in enumerate(remaining):
                        answer = reply["answers"][f"r{i}"]
                        violation = answer["probabilities"]["violated"]
                        unknown = answer["probabilities"]["unknown"]
                        disposition = "block" if violation >= POLICY["rules"]["block_min"] else (
                            "review" if max(violation, unknown) >= POLICY["rules"]["review_min"] else "pass")
                        instruction_checks.append({**block, "answer": answer, "disposition": disposition})
                        if disposition == "block":
                            decision = "block"
                            reasons.append("instruction_conflict")
                        elif disposition == "review":
                            if decision != "block": decision = "review"
                            reasons.append("instruction_uncertain")
        if errors and decision != "block":
            decision, reasons = "unassessed", ["partial_assessment_unavailable"]
        usage = {k: sum(r["usage"][k] for r in responses) for k in ("input_tokens", "output_tokens")}
        output = verdict(decision, list(dict.fromkeys(reasons)) or ["no_conflict_detected"], clean,
                         probabilities=probs, usage=usage, latency=(time.monotonic()-started)*1000,
                         basis="typesafe" if responses else "local", model=MODEL if responses else None)
        output.update(rule_checks=rule_results, instruction_checks=instruction_checks,
                      api_requests=request_count, assessment_complete=not errors,
                      unavailable_checks=errors, short_circuit=bool(mode == "check" and any(r["enforced"] for r in rule_results)))
        return output
    except (RuntimeError, ValueError, TypeError, KeyError, OSError, URLError, TimeoutError):
        return verdict("unassessed", "provider_or_input_unavailable", {}, latency=(time.monotonic()-started)*1000)


def assess(state: dict, cfg: dict, directory: Path, mode: str = "check") -> dict:
    needs_remote = cfg["cloud_enabled"] and not (mode == "check" and literal_authorized(state, cfg))
    if needs_remote and not os.environ.get("TYPESAFE_API_KEY") and cfg["credential_runner"] and not os.environ.get("JMT_CREDENTIAL_CHILD"):
        argv = cfg["credential_runner"] + [sys.executable, str(Path(__file__).resolve()), "--data-dir", str(directory), mode]
        try:
            result = subprocess.run(argv, input=canonical(state), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    env=dict(os.environ, JMT_CREDENTIAL_CHILD="1"), timeout=10, check=False)
            if len(result.stdout) > MAX_RESPONSE or result.returncode not in (0, 2, 3, 4):
                raise ValueError("runner_failed")
            out = json.loads(result.stdout)
            if out.get("decision") not in ("pass", "review", "block", "unassessed") or out.get("policy_sha256") != digest(POLICY):
                raise ValueError("runner_shape")
            return out
        except (ValueError, OSError, subprocess.TimeoutExpired):
            return verdict("unassessed", "credential_runner_unavailable", {})
    return evaluate(state, cfg, mode=mode)


class StateStore:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(directory / "state.sqlite3", timeout=2)
        self.db.execute("CREATE TABLE IF NOT EXISTS turns (sid TEXT, tid TEXT, goal TEXT, evidence TEXT, calls INTEGER, corrected INTEGER, updated REAL, PRIMARY KEY(sid,tid))")
        self.db.execute("CREATE TABLE IF NOT EXISTS task_outcomes (task TEXT, action TEXT, generation TEXT, outcome TEXT, failed INTEGER, updated REAL, PRIMARY KEY(task,action))")
        self.db.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, event TEXT, tool TEXT, decision TEXT, reasons TEXT, latency REAL, tokens INTEGER, policy TEXT)")
        if os.name != "nt":
            os.chmod(directory / "state.sqlite3", 0o600)

    def close(self):
        self.db.close()

    def prompt(self, sid: str, tid: str, goal: str):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO turns VALUES (?,?,?,'[]',0,0,?)", (sid, tid, goal, time.time()))
            self.db.execute("DELETE FROM turns WHERE updated < ? OR rowid NOT IN (SELECT rowid FROM turns ORDER BY updated DESC LIMIT 128)", (time.time()-604800,))

    def get(self, sid: str, tid: str):
        row = self.db.execute("SELECT goal,evidence,calls,corrected,updated FROM turns WHERE sid=? AND tid=?", (sid, tid)).fetchone()
        if not row or time.time() - row[4] > 86400:
            return None
        return {"goal": row[0], "evidence": json.loads(row[1]), "calls": row[2], "corrected": row[3]}

    def receipt(self, sid: str, tid: str, body: str):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.get(sid, tid)
            if row:
                evidence = (row["evidence"] + [body])[-6:]
                self.db.execute("UPDATE turns SET evidence=?,updated=? WHERE sid=? AND tid=?", (json.dumps(evidence), time.time(), sid, tid))

    def reserve(self, sid: str, tid: str, limit: int) -> bool:
        with self.db:
            return self.db.execute("UPDATE turns SET calls=calls+1 WHERE sid=? AND tid=? AND calls<?", (sid, tid, limit)).rowcount == 1

    def correction(self, sid: str, tid: str) -> bool:
        with self.db:
            return self.db.execute("UPDATE turns SET corrected=1 WHERE sid=? AND tid=? AND corrected=0", (sid, tid)).rowcount == 1

    def record(self, event: str, tool: str, result: dict):
        with self.db:
            self.db.execute("INSERT INTO audit(event,tool,decision,reasons,latency,tokens,policy) VALUES(?,?,?,?,?,?,?)", (event, tool[:100], result["decision"], ",".join(result["reason_codes"]), result["latency_ms"], result["usage"].get("input_tokens", 0), result["policy_sha256"]))
            self.db.execute("DELETE FROM audit WHERE id NOT IN (SELECT id FROM audit ORDER BY id DESC LIMIT 512)")

    def task_outcome(self, task: str, action: str, generation: str, outcome: str, failed: bool):
        outcome = redact(outcome)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO task_outcomes VALUES (?,?,?,?,?,?)", (task, action, generation, outcome, int(failed), time.time()))
            self.db.execute("DELETE FROM task_outcomes WHERE task=? AND rowid NOT IN (SELECT rowid FROM task_outcomes WHERE task=? ORDER BY failed DESC,updated DESC LIMIT 32)", (task, task))
            self.db.execute("DELETE FROM task_outcomes WHERE updated < ?", (time.time() - 604800,))
            self.db.execute("DELETE FROM task_outcomes WHERE task NOT IN (SELECT task FROM task_outcomes GROUP BY task ORDER BY MAX(updated) DESC LIMIT 128)")

    def task_evidence(self, task: str, limit: int = 8, current_generation=None) -> list[str]:
        rows = self.db.execute("SELECT outcome,generation,failed FROM task_outcomes WHERE task=? ORDER BY failed DESC,updated DESC LIMIT ?", (task, limit)).fetchall()
        return [f"[Observed generation {generation}; {'current generation; observation is not proof of later state' if generation == str(current_generation) else 'prior generation; not current proof'}] {outcome}" for outcome, generation, failed in rows]



def tool_receipt(raw: Any, tool_input: Any, max_chars: int = 2500) -> str:
    """Keep the observed exit metadata and output tail, not only a long source prefix."""
    clean = redact(raw)
    original_text = canonical(raw).decode("utf-8")
    clean_text = canonical(clean).decode("utf-8")
    command = ""
    if isinstance(tool_input, dict):
        value = tool_input.get("command", tool_input.get("cmd", ""))
        if isinstance(value, str):
            command = redact(value)
    if len(command) > 500:
        command = command[:230] + " [COMMAND MIDDLE OMITTED] " + command[-230:]
    prefix = "Observed command: " + command + "\n" if command else ""
    if original_text != clean_text:
        clean_text = "[Credential-shaped content omitted from this receipt.]"
    budget = max_chars - len(prefix)
    if len(clean_text) <= budget:
        return prefix + clean_text
    metadata = {}
    if isinstance(clean, dict):
        metadata = {k: clean[k] for k in ("exit_code", "status", "isError") if k in clean}
    label = "\n[OUTPUT MIDDLE OMITTED; INCOMPLETE OBSERVATION]\n"
    meta = "Execution metadata: " + canonical(metadata).decode() + "\n"
    available = budget - len(meta) - len(label)
    head = min(550, available // 3)
    tail = available - head
    return prefix + meta + clean_text[:head] + label + clean_text[-tail:]


def context(event: str, text: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def hook(event: dict, cfg: dict, directory: Path, assessor: Callable = assess, task_loader: Callable | None = None) -> dict:
    kind = event.get("hook_event_name", event.get("type"))
    if kind == "SessionStart":
        status = "cloud on; " + cfg["mode"] if cfg["cloud_enabled"] else "cloud off; no remote checks"
        return context(kind, "JustMyType " + status + ". CLI: justmytype check, verify, decide, select, stats, progress, doctor. decide/select are advisory; selection preserves protected source text. Native local tools only; hosted tools and later write_stdin input are outside coverage. API judgments are not proof or authorization.")
    if kind not in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
        return {}
    sid, tid = event.get("session_id"), event.get("turn_id")
    if not isinstance(sid, str) or not sid or not isinstance(tid, str) or not tid:
        return {"systemMessage": "JustMyType: no session/turn identity; assessment unavailable."}
    sid, tid = digest(sid), digest(tid)
    db = StateStore(directory)
    try:
        if kind == "UserPromptSubmit":
            goal = event.get("prompt", "")
            if not isinstance(goal, str):
                return {"systemMessage": "JustMyType: invalid prompt input."}
            goal = redact(goal)
            # Do not silently discard a late negative instruction.
            db.prompt(sid, tid, goal if len(goal) <= 6000 else "")
            return {} if len(goal) <= 6000 else {"systemMessage": "JustMyType: prompt exceeds 6000 characters; automatic preflight unavailable for this turn. Use a bounded explicit check."}
        row = db.get(sid, tid)
        graph = graphfather_context(event.get("session_id"), directory, task_loader)
        active = graph if graph.get("schema") == 1 and isinstance(graph.get("blueprint"), dict) and isinstance(graph.get("cursor"), dict) else {}
        objective = active.get("blueprint", {}).get("objective")
        canonical_session = active.get("session_id")
        revision = active.get("revision")
        generation = active.get("generation")
        task_key = digest({"calling_sid": sid, "canonical_session": canonical_session,
                           "redacted_objective": redact(objective)}) if canonical_session and objective else None
        if kind == "PostToolUse":
            raw = event.get("tool_response", {})
            clean_text = tool_receipt(raw, event.get("tool_input", {}))
            db.receipt(sid, tid, str(event.get("tool_name", "unknown"))[:100] + ": " + clean_text)
            failed = isinstance(raw, dict) and (raw.get("isError") is True or (type(raw.get("exit_code")) is int and raw["exit_code"] != 0))
            if task_key and row:
                action = digest(redact({"tool": event.get("tool_name", ""), "arguments": event.get("tool_input", {}), "cwd": event.get("cwd", "")}))
                identity = str(event.get("tool_name", "unknown"))[:100]
                safe_args = redact(event.get("tool_input", {}))
                command = safe_args.get("command", safe_args.get("cmd", canonical(safe_args).decode())) if isinstance(safe_args, dict) else canonical(safe_args).decode()
                db.task_outcome(task_key, action, str(generation or ""),
                                tool_receipt(raw, {"command": identity + ": " + str(command) + " cwd=" + redact(event.get("cwd", ""))}, 900), failed)
            notices = ["JustMyType: the observed tool result failed. Do not report the requested outcome as complete without new evidence."] if failed else []
            if task_key and row and generation is not None:
                observed = progress.record(directory, session=sid, task=task_key,
                    generation=str(generation), tool=str(event.get("tool_name", "unknown")),
                    arguments=event.get("tool_input", {}), cwd=str(event.get("cwd", "")),
                    response=raw, redact=redact)
                if observed.get("advisory"):
                    notices.append("JustMyType: " + observed["advisory"]["message"])
            return context(kind, " ".join(notices)) if notices else {}
        if not cfg["cloud_enabled"]:
            return {}
        if kind == "Stop" and (event.get("stop_hook_active") or (row and row["corrected"])):
            return {}
        name = event.get("tool_name", "")
        args = event.get("tool_input", {})
        latest = row["goal"] if row else ""
        if objective and latest:
            latest = str(objective) + "\nLatest instruction (takes precedence): " + latest
        state = {"goal": latest, "action": {"tool": name, "arguments": args, "cwd": redact(event.get("cwd", ""))},
                 "evidence": row["evidence"] if row else [], "constraints": []}
        if task_key:
            state["evidence"] = (state["evidence"] + db.task_evidence(task_key, current_generation=generation))[-14:]
            state["task_context"] = {"revision": revision, "generation": generation, "canonical_session": canonical_session, "cursor": {"layer": active["cursor"]["layer"], "next": active["cursor"]["next"]}}
        if kind == "Stop":
            state["claim"] = event.get("last_assistant_message") or ""
            state.pop("action", None)
        eligibility = eligibility_reason(state, "verify" if kind == "Stop" else "check", cfg)
        if not row or not row["goal"]:
            result = verdict("unassessed", "missing_turn_context", {})
        elif eligibility:
            result = verdict("unassessed", eligibility, {})
        elif graph.get("status") == "unassessed":
            result = verdict("unassessed", graph.get("reason", "missing_turn_context"), {})
        elif kind == "PreToolUse" and literal_authorized(state, cfg):
            result = verdict("pass", "literal_read", state)
        elif not db.reserve(sid, tid, cfg["max_calls_per_turn"]):
            result = verdict("unassessed", "turn_budget_exhausted", {})
        else:
            result = assessor(state, cfg, directory, "verify" if kind == "Stop" else "check")
        db.record(kind, name, result)
        text = "JustMyType: " + result["decision"] + " (" + ", ".join(result["reason_codes"]) + ")."
        for check in result.get("rule_checks", []):
            if check.get("enforced"):
                comparison = check["comparison"]
                detail = (" Exact comparison: " + ".".join(check["field"]) + " = " + comparison["left"]
                          + " " + comparison["unit"] + "; restricted when " + comparison["operator"]
                          + " " + comparison["right"] + ". Required approval or permitted scope was not established.")
                text += detail[:360]
                break
        if kind == "Stop":
            if cfg["mode"] == "guard" and result["decision"] == "block" and db.correction(sid, tid):
                return {"decision": "block", "reason": text + " Correct the outcome claim using the actual evidence. Do not rerun work just to restate it."}
            return {"systemMessage": text} if result["decision"] != "pass" else {}
        # Guard denies a concrete block. Review/outage do not silently become approval.
        # Native approval and sandbox policy remain untouched.
        if cfg["mode"] == "guard" and result["decision"] == "block":
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": text + " Reconcile this action with the stated scope. Do not bypass the hook."}}
        if result["decision"] != "pass":
            return context(kind, text + " This is not an authorization. Reconcile the action before proceeding.")
        return {}
    finally:
        db.close()


def read_json(path: str = "-") -> Any:
    if path == "-":
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    else:
        with open(path, "rb") as f:
            raw = f.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise ValueError("input_bound")
    return json.loads(raw.decode("utf-8-sig"))


def toolkit(payload: Any, cfg: dict, directory: Path, op: str = "decide", transport: Callable | None = None) -> dict:
    """Advisory utilities share the existing credential and HTTP boundary."""
    unavailable = {"status": "unassessed", "reason_codes": ["toolkit_unavailable"],
                   "answers": {}, "usage": {}, "evaluations": 0, "cache_hit": False}
    if op not in ("decide", "select"):
        return unavailable
    if (transport is None and cfg["cloud_enabled"] and not os.environ.get("TYPESAFE_API_KEY")
            and cfg["credential_runner"] and not os.environ.get("JMT_CREDENTIAL_CHILD")):
        argv = cfg["credential_runner"] + [sys.executable, str(Path(__file__).resolve()),
                                           "--data-dir", str(directory), op]
        try:
            result = subprocess.run(argv, input=canonical(payload), stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=40, check=False,
                                    env=dict(os.environ, JMT_CREDENTIAL_CHILD="1"))
            if len(result.stdout) > MAX_INPUT or result.returncode not in (0, 2, 4):
                return unavailable
            out = json.loads(result.stdout)
            if not isinstance(out, dict) or out.get("status") not in ("ok", "partial", "unassessed", "budget_exceeded"):
                return unavailable
            return out
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
            return unavailable

    def decide(request):
        return decisions.evaluate(request,
            request=lambda state, questions: request_api(state, questions, transport),
            redact=redact, directory=directory, enabled=cfg["cloud_enabled"] or transport is not None,
            model=MODEL, engine_sha256=ENGINE_SHA256)
    try:
        return decide(payload) if op == "decide" else selection.select(payload, evaluate=decide)
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, RecursionError):
        return unavailable




def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir")
    commands = parser.add_subparsers(dest="op", required=True)
    for name in ("check", "verify", "decide", "select"):
        commands.add_parser(name).add_argument("--input", default="-")
    commands.add_parser("stats")
    progress_command = commands.add_parser("progress")
    progress_command.add_argument("--session", required=True)
    progress_command.add_argument("--task", required=True)
    commands.add_parser("hook")
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--live", action="store_true")
    conf = commands.add_parser("configure")
    conf.add_argument("--cloud", choices=("on", "off"))
    conf.add_argument("--mode", choices=("observe", "guard"))
    conf.add_argument("--credential-runner-json")
    conf.add_argument("--constraints-json")
    guard = commands.add_parser("guard")
    guard.add_argument("--goal", required=True)
    guard.add_argument("--constraint", action="append", default=[])
    guard.add_argument("--evidence", action="append", default=[])
    guard.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    directory = data_dir(args.data_dir)
    try:
        cfg = load_config(directory)
        if args.op in ("decide", "select"):
            out = toolkit(read_json(args.input), cfg, directory, args.op)
            print(json.dumps(out, ensure_ascii=False, allow_nan=False))
            return {"ok": 0, "partial": 2, "budget_exceeded": 2, "unassessed": 4}[out["status"]]
        if args.op == "stats":
            print(json.dumps({"advisory": decisions.stats(directory), "note": "Logical evaluations and provider-reported tokens; not total agent savings."}))
            return 0
        if args.op == "progress":
            print(json.dumps(progress.snapshot(directory, session=args.session, task=args.task)))
            return 0
        if args.op == "configure":
            if args.cloud:
                cfg["cloud_enabled"] = args.cloud == "on"
            if args.mode:
                cfg["mode"] = args.mode
            for attr, key in (("credential_runner_json", "credential_runner"), ("constraints_json", "constraints")):
                value = getattr(args, attr)
                if value is not None:
                    parsed = json.loads(value)
                    if not strings(parsed, 16) or any(not x or "\0" in x for x in parsed):
                        raise ValueError("invalid_configuration")
                    cfg[key] = parsed
            if len(canonical(cfg)) > 16000:
                raise ValueError("config_bound")
            save_config(directory, cfg)
            print(json.dumps({"configured": True, "cloud_enabled": cfg["cloud_enabled"], "mode": cfg["mode"],
                              "disclosure": "Cloud mode sends bounded, best-effort-redacted goal, action and evidence snippets to TypeSafe. No full transcript upload. Redaction is not a guarantee."}))
            return 0
        if args.op == "doctor":
            out = {"name": "JustMyType", "version": VERSION, "python": platform.python_version(), "platform": platform.system(),
                   "data_dir": str(directory), "config_path": str(directory / "config.json"),
                   "cloud_enabled": cfg["cloud_enabled"], "mode": cfg["mode"],
                   "api_key_present": bool(os.environ.get("TYPESAFE_API_KEY")), "credential_runner_configured": bool(cfg["credential_runner"]),
                   "model": MODEL, "policy_sha256": digest(POLICY), "runtime_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "engine_sha256": ENGINE_SHA256}
            out["capabilities"] = ["check", "verify", "guard", "decide", "select", "stats", "progress"]
            out["cache_scope"] = "Explicit advisory decisions only; never action authorization."
            if args.live:
                out["live"] = assess({"goal": "Inspect the demo service without changes.", "action": {"tool": "Bash", "arguments": {"command": "systemctl status demo.service --no-pager"}}, "constraints": [], "evidence": []}, cfg, directory)
            print(json.dumps(out))
            return 0
        if args.op == "hook":
            out = hook(read_json(), cfg, directory)
            print(json.dumps(out))
            return 0
        if args.op == "guard":
            cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
            if not cmd:
                parser.error("guard needs an argv after --")
            state = {"goal": args.goal, "action": {"tool": "exec_argv", "arguments": {"argv": cmd}}, "evidence": args.evidence, "constraints": args.constraint}
            out = assess(state, cfg, directory)
            print(json.dumps(out), file=sys.stderr)
            if out["decision"] != "pass":
                return 3
            # No shell interpretation and no cached authorization.
            return subprocess.run(cmd, check=False).returncode
        out = assess(read_json(args.input), cfg, directory, args.op)
        print(json.dumps(out))
        return {"pass": 0, "review": 2, "block": 3, "unassessed": 4}[out["decision"]]
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, RecursionError):
        if args.op == "hook":
            print(json.dumps({"systemMessage": "JustMyType: local assessment unavailable; no safety verdict was produced."}))
            return 0
        print(json.dumps(verdict("unassessed", "invalid_input_or_local_state", {})))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
