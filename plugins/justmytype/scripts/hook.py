#!/usr/bin/env python3
"""Stable entrypoint for hooks and the launcher.

The file copied to PLUGIN_DATA never changes its import location.  The active
pointer selects an immutable payload, so a running hook can finish against the
old payload while a new one is staged.
"""
from __future__ import annotations

import os
import json
import runpy
import sys
from pathlib import Path


def main() -> None:
    data = Path(__file__).resolve().parent
    args = list(sys.argv[1:])
    if "--data-dir" in args:
        i = args.index("--data-dir")
        if i + 1 < len(args):
            data = Path(args[i + 1]).expanduser().resolve()
            del args[i:i + 2]
    op = args[0] if args else ""
    pointer = data / "active"
    def unassessed(reason: str) -> None:
        if op == "hook":
            print(json.dumps({"systemMessage": "JustMyType unassessed: " + reason}))
            raise SystemExit(0)
        raise SystemExit("JustMyType: " + reason)
    try:
        if not pointer.is_file():
            unassessed("active_payload_missing")
        relative = pointer.read_text(encoding="utf-8").strip()
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            unassessed("active_payload_invalid")
        payload = (data / relative).resolve()
        payload_root = (data / "payloads").resolve()
        if payload_root not in payload.parents:
            unassessed("active_payload_escape")
        runtime = payload / "plugins/justmytype/scripts/jmt.py"
        if not runtime.is_file() or runtime.is_symlink():
            unassessed("runtime_missing")
        sys.path.insert(0, str(runtime.parent))
        if args and args[0] == "--uninstall":
            installer = payload / "scripts/install.py"
            sys.argv = [str(installer), "--uninstall", "--codex-home", str(data.parent.parent.parent)]
            runpy.run_path(str(installer), run_name="__main__")
            return
        sys.argv = [str(runtime), "--data-dir", str(data), *args]
        runpy.run_path(str(runtime), run_name="__main__")
    except SystemExit:
        raise
    except Exception as error:
        unassessed("runtime_error")


if __name__ == "__main__":
    main()
