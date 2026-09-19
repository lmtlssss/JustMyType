"""Local observation streaks, not permission or behavioral proof."""
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

NOTICE = "Same action and result repeated without a changed generation; reassess the cause before retrying."
TRANSPORT = {"chunk_id", "wall_time_seconds", "duration_ms", "elapsed_ms"}


def serialized(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(serialized(value)).hexdigest()


def unavailable(reason):
    return {"status": "unassessed", "observation_status": "unknown", "count": 0, "advisory": None, "reason": reason}


def observation_status(response):
    if response.get("isError") is True:
        return "failed"
    code = response.get("exit_code")
    if type(code) is int:
        return "failed" if code else "exited"
    if response.get("running") is True or response.get("session_id") is not None:
        return "pending"
    return "unknown"


def connect(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "progress.sqlite3"
    connection = sqlite3.connect(path, timeout=2)
    try:
        os.chmod(path, 0o600)
        connection.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, session TEXT, task TEXT, generation TEXT, action TEXT, outcome TEXT, status TEXT, ts REAL, count INTEGER)")
        connection.commit()
        return connection
    except Exception:
        connection.close()
        raise


def record(directory, *, session, task, generation, tool, arguments, cwd, response, redact):
    identities = (session, task, generation, tool)
    if any(not isinstance(v, str) or not v or len(v) > 1024 for v in identities):
        return unavailable("invalid_identity")
    if not isinstance(cwd, str) or len(cwd) > 1024 or not isinstance(arguments, dict) or not isinstance(response, dict):
        return unavailable("invalid_input")
    original = {"session": session, "task": task, "generation": generation,
                "tool": tool, "arguments": arguments, "cwd": cwd, "response": response}
    try:
        if redact(original) != original:
            return unavailable("redacted")
        if len(serialized(original)) > 262144:
            return unavailable("input_bound")
        status = observation_status(response)
        action = digest({"tool": tool, "arguments": arguments, "cwd": cwd})
        outcome = digest({k: v for k, v in response.items() if k not in TRANSPORT})
    except (ValueError, TypeError, RecursionError):
        return unavailable("invalid_input")
    connection = None
    try:
        connection = connect(directory)
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM events WHERE ts < ?", (time.time() - 604800,))
            previous = connection.execute("SELECT generation,action,outcome,count FROM events WHERE session=? AND task=? ORDER BY id DESC LIMIT 1", (session, task)).fetchone()
            count = previous[3] + 1 if previous and previous[:3] == (generation, action, outcome) else 1
            connection.execute("INSERT INTO events VALUES(NULL,?,?,?,?,?,?,?,?)",
                               (session, task, generation, action, outcome, status, time.time(), count))
            connection.execute("DELETE FROM events WHERE session=? AND task=? AND id NOT IN (SELECT id FROM events WHERE session=? AND task=? ORDER BY id DESC LIMIT 64)", (session, task, session, task))
            old_scopes = connection.execute("SELECT session,task FROM events GROUP BY session,task ORDER BY MAX(id) DESC LIMIT -1 OFFSET 128").fetchall()
            connection.executemany("DELETE FROM events WHERE session=? AND task=?", old_scopes)
    except (OSError, sqlite3.Error):
        return unavailable("local_state_unavailable")
    finally:
        if connection is not None:
            connection.close()
    advisory = None
    if count == 3 and status in ("failed", "exited"):
        advisory = {"kind": "repeated_failure" if status == "failed" else "repeated_observation",
                    "count": count, "message": NOTICE}
    return {"status": "recorded", "observation_status": status, "count": count, "advisory": advisory}


def snapshot(directory, *, session, task):
    out = {"session": session, "task": task, "count": 0, "latest": [], "unresolved_failures": []}
    path = Path(directory) / "progress.sqlite3"
    if not path.exists():
        return out
    connection = None
    try:
        connection = sqlite3.connect(path, timeout=2)
        rows = connection.execute("SELECT generation,action,outcome,status,count FROM events WHERE session=? AND task=? AND ts>=? ORDER BY id DESC LIMIT 64",
                                  (session, task, time.time() - 604800)).fetchall()
    except (OSError, sqlite3.Error):
        return dict(out, status="unassessed", reason="local_state_unavailable")
    finally:
        if connection is not None:
            connection.close()
    out["latest"] = [dict(zip(("generation", "action", "outcome", "status", "count"), row)) for row in rows]
    out["count"] = len(rows)
    terminal = {}
    for row in out["latest"]:
        if row["action"] not in terminal and row["status"] in ("failed", "exited"):
            terminal[row["action"]] = row
    out["unresolved_failures"] = [row for row in terminal.values() if row["status"] == "failed"]
    return out
