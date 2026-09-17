"""Export a completed recorded state as standalone JustMyType HTML."""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path

def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--state", type=Path, required=True); p.add_argument("--html", type=Path, required=True); p.add_argument("--out", type=Path, required=True); a = p.parse_args(); state = json.loads(a.state.read_text())
    if state.get("phase") != "done" or len(state.get("rows", [])) != 48 or state.get("synthetic") is not True or state.get("shared_proposals") is not True: raise ValueError("state must be done with 48 rows and synthetic/shared_proposals true")
    a.out.mkdir(parents=True, exist_ok=False); recorded = json.dumps(state, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c"); injection = f"<script>window.JMT_RECORDED={recorded};</script>"; source = a.html.read_text()
    result = re.sub(r"<head\b[^>]*>", lambda m: m.group(0)+injection, source, count=1, flags=re.I) if re.search(r"<head\b", source, re.I) else injection+source; output = a.out / "JustMyType-Refund-Desk.html"; output.write_text(result); (a.out / "result.json").write_bytes(a.state.read_bytes())
    files = [a.state, output, a.out / "result.json"]; (a.out / "manifest.json").write_text(json.dumps({"files": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}}, indent=2)+"\n"); return 0
if __name__ == "__main__": raise SystemExit(main())
