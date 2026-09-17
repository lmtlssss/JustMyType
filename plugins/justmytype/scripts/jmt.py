#!/usr/bin/env python3
"""JustMyType: typed preflight, native Codex hooks, one local configuration."""
from __future__ import annotations

import argparse
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
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

VERSION = "0.1.0"
NAME = "justmytype"
API_URL = "https://api.typesafe.ai/v1/systemone"
POLICY_PATH = Path(__file__).with_name("policy.json")
POLICY = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
MODEL = POLICY["model"]
MAX_INPUT = 262144
MAX_STATE = 32768
MAX_RESPONSE = 32768
DEFAULTS = {"cloud_enabled": False, "mode": "observe", "credential_runner": [],
            "constraints": [], "max_calls_per_turn": 32}
SECRET_FIELD = re.compile(r"(?i)^(?:.*[_-])?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|authorization|cookie|private[_-]?key|credentials?)$")
ASSIGNMENT = re.compile(r'''(?ix)(\b(?:[a-z0-9_-]*[_-])?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|authorization|cookie)\b["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)''')
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
            "usage": usage or {}, "policy_sha256": digest(POLICY), "state_sha256": digest(redact(state))}


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


def request_api(state: dict, questions: dict, transport: Callable | None = None) -> dict:
    payload = {"state": state, "model": MODEL, "questions": questions}
    if transport is not None:
        return validate_response(transport(payload), questions)
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise RuntimeError("missing_api_key")
    req = Request(API_URL, data=canonical(payload), headers={"Content-Type": "application/json", "Authorization": "Bearer " + key}, method="POST")
    opener = build_opener(NoRedirect())
    deadline = time.monotonic() + 6
    for attempt in range(2):
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
        if mode not in ("check", "verify") or not valid_state(state, mode):
            return verdict("unassessed", "malformed_state", {})
        clean = redact(state)
        if mode == "check":
            tool, args = clean["action"]["tool"], clean["action"]["arguments"]
            if tool in ("Bash", "exec_command", "shell_command", "shell", "apply_patch"):
                if not isinstance(args.get("command", args.get("cmd")), str):
                    return verdict("unassessed", "malformed_tool_arguments", {})
            elif tool == "exec_argv":
                if not strings(args.get("argv")) or not args["argv"]:
                    return verdict("unassessed", "malformed_tool_arguments", {})
            elif not tool.startswith("mcp__"):
                return verdict("unassessed", "unsupported_tool", {})
            clean["constraints"] = clean.get("constraints", []) + redact(cfg["constraints"])
        if len(canonical(clean)) > MAX_STATE:
            return verdict("unassessed", "state_bound", {})
        if mode == "check" and literal_authorized(clean, cfg):
            return verdict("pass", "literal_read", clean)
        if not cfg["cloud_enabled"] and transport is None:
            return verdict("unassessed", "cloud_disabled", clean)
        questions = POLICY["verification"] if mode == "verify" else POLICY["questions"]
        response = request_api(clean, questions, transport)
        if mode == "verify":
            answer = response["answers"]["support"]
            probs = answer["probabilities"]
            choice = answer["choice"]
            if choice == "contradicted" and probs[choice] >= POLICY["thresholds"]["block"]:
                decision = "block"
            elif choice in ("supported", "no_claim") and probs[choice] >= .7:
                decision = "pass"
            else:
                decision = "review"
            reasons = [choice]
        else:
            probs = {name: a["noul"] for name, a in response["answers"].items()}
            high = max(probs.values())
            decision = "block" if high >= POLICY["thresholds"]["block"] else "review" if high >= POLICY["thresholds"]["review"] else "pass"
            reasons = [k for k, v in probs.items() if v >= POLICY["thresholds"]["review"]] or ["no_conflict_detected"]
        return verdict(decision, reasons, clean, probabilities=probs,
                       usage={k: response["usage"][k] for k in ("input_tokens", "output_tokens")},
                       latency=(time.monotonic() - started) * 1000, basis="typesafe", model=response["model"])
    except (RuntimeError, ValueError, TypeError, KeyError, OSError, URLError, TimeoutError):
        # No exception body or request headers can reach logs/stdout.
        return verdict("unassessed", "provider_or_input_unavailable", {}, latency=(time.monotonic() - started) * 1000)


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


def context(event: str, text: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def hook(event: dict, cfg: dict, directory: Path, assessor: Callable = assess) -> dict:
    kind = event.get("hook_event_name", event.get("type"))
    if kind == "SessionStart":
        status = "cloud on; " + cfg["mode"] if cfg["cloud_enabled"] else "cloud off; no remote checks"
        return context(kind, "JustMyType " + status + ". CLI: justmytype check, verify, doctor. Native local tools only; hosted tools and later write_stdin input are outside coverage. API judgments are not proof or authorization.")
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
        if kind == "PostToolUse":
            raw = event.get("tool_response", {})
            clean = redact(raw)
            original_text = canonical(raw).decode("utf-8")
            clean_text = canonical(clean).decode("utf-8")
            if original_text != clean_text:
                clean_text = "[Credential-shaped content omitted from this receipt.]"
            if len(clean_text) > 2500:
                clean_text = clean_text[:2500] + " [TRUNCATED OBSERVATION; incomplete evidence]"
            db.receipt(sid, tid, str(event.get("tool_name", "unknown"))[:100] + ": " + clean_text)
            failed = isinstance(raw, dict) and (raw.get("isError") is True or (type(raw.get("exit_code")) is int and raw["exit_code"] != 0))
            return context(kind, "JustMyType: the observed tool result failed. Do not report the requested outcome as complete without new evidence.") if failed else {}
        if not cfg["cloud_enabled"]:
            return {}
        if kind == "Stop" and (event.get("stop_hook_active") or (row and row["corrected"])):
            return {}
        name = event.get("tool_name", "")
        args = event.get("tool_input", {})
        state = {"goal": row["goal"] if row else "", "action": {"tool": name, "arguments": args},
                 "evidence": row["evidence"] if row else [], "constraints": []}
        if kind == "Stop":
            state = {"claim": event.get("last_assistant_message") or "", "evidence": row["evidence"] if row else []}
        if not row or not row["goal"]:
            result = verdict("unassessed", "missing_turn_context", {})
        elif name in ("write_stdin", "functions.write_stdin"):
            result = verdict("unassessed", "uncovered_continuation", {})
        elif kind == "PreToolUse" and literal_authorized(state, cfg):
            result = verdict("pass", "literal_read", state)
        elif not db.reserve(sid, tid, cfg["max_calls_per_turn"]):
            result = verdict("unassessed", "turn_budget_exhausted", {})
        else:
            result = assessor(state, cfg, directory, "verify" if kind == "Stop" else "check")
        db.record(kind, name, result)
        text = "JustMyType: " + result["decision"] + " (" + ", ".join(result["reason_codes"]) + ")."
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir")
    commands = parser.add_subparsers(dest="op", required=True)
    for name in ("check", "verify"):
        commands.add_parser(name).add_argument("--input", default="-")
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
                   "model": MODEL, "policy_sha256": digest(POLICY), "runtime_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
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
