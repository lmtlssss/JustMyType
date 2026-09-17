#!/usr/bin/env python3
"""Install only JustMyType. Standard library, Python 3.11 or newer."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
import queue
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.request import urlopen

VERSION = "0.1.0"
NAME = "justmytype"
PLUGIN_ID = "justmytype@justmytype"
RELEASE = "https://github.com/lmtlssss/JustMyType/releases/download/v" + VERSION
REQUIRED = [
    ".agents/plugins/marketplace.json",
    "plugins/justmytype/.codex-plugin/plugin.json",
    "plugins/justmytype/hooks/hooks.json",
    "plugins/justmytype/scripts/jmt.py",
    "plugins/justmytype/scripts/policy.json",
    "plugins/justmytype/skills/justmytype/SKILL.md",
    "scripts/install.py",
]


def codex_argv(binary: str, *args: str) -> list[str]:
    path = shutil.which(binary) or binary
    if os.name == "nt" and Path(path).suffix.lower() in (".bat", ".cmd"):
        # Invoke the official npm entry with Node. Avoid cmd.exe's second parser.
        entry = Path(path).parent / "node_modules/@openai/codex/bin/codex.js"
        node = shutil.which("node")
        if not node or not entry.is_file():
            raise RuntimeError("Use the official npm Codex installation or a native codex.exe.")
        return [node, str(entry), *args]
    return [path, *args]


def cli(binary: str, env: dict, *args: str) -> str:
    result = subprocess.run(codex_argv(binary, *args), env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, text=True, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("Codex " + " ".join(args[:3]) + " failed. " + result.stderr[-1500:])
    return result.stdout


class RPC:
    def __init__(self, binary: str, env: dict):
        self.process = subprocess.Popen(codex_argv(binary, "app-server", "--stdio"), env=env,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        text=True, encoding="utf-8", bufsize=1)
        self.messages: queue.Queue = queue.Queue()
        self.sequence = 0
        def read():
            try:
                for line in self.process.stdout:
                    if len(line) > 2000000:
                        self.messages.put({"error": "response_bound"})
                        break
                    try:
                        self.messages.put(json.loads(line))
                    except ValueError:
                        continue
            finally:
                self.messages.put(None)
        threading.Thread(target=read, daemon=True).start()
        self.call("initialize", {"clientInfo": {"name": NAME, "version": VERSION}})
        self.send({"method": "initialized", "params": {}})

    def send(self, message: dict):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def call(self, method: str, params: dict):
        self.sequence += 1
        seq = self.sequence
        self.send({"id": seq, "method": method, "params": params})
        deadline = time.monotonic() + 15
        while True:
            try:
                item = self.messages.get(timeout=max(.01, deadline - time.monotonic()))
            except queue.Empty:
                raise RuntimeError("Codex app-server timed out") from None
            if item is None:
                raise RuntimeError("Codex app-server closed")
            if item.get("id") == seq:
                if "error" in item:
                    raise RuntimeError("Codex app-server rejected " + method)
                return item["result"]

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                stream.close()


def owned_hooks(rpc: RPC) -> list[dict]:
    data = rpc.call("hooks/list", {"cwds": []})
    return [h for group in data.get("data", []) for h in group.get("hooks", []) if h.get("pluginId") == PLUGIN_ID]


def trust_hooks(binary: str, env: dict) -> list[dict]:
    rpc = RPC(binary, env)
    try:
        hooks = owned_hooks(rpc)
        if len(hooks) != 5:
            raise RuntimeError("Expected five JustMyType hooks, found " + str(len(hooks)))
        edits = []
        for h in hooks:
            if not isinstance(h.get("key"), str) or not isinstance(h.get("currentHash"), str):
                raise RuntimeError("Unknown Codex hook schema")
            edits.append({"keyPath": "hooks.state." + json.dumps(h["key"]),
                          "value": {"enabled": True, "trusted_hash": h["currentHash"]}, "mergeStrategy": "replace"})
        rpc.call("config/batchWrite", {"edits": edits, "reloadUserConfig": True})
        return hooks
    finally:
        rpc.close()


def extract_package(content: bytes, destination: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        members = archive.infolist()
        if len(members) > 128 or sum(m.file_size for m in members) > 8000000:
            raise ValueError("package_bound")
        seen = set()
        for member in members:
            path = PurePosixPath(member.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in member.filename
                    or PureWindowsPath(member.filename).drive or member.filename in seen
                    or stat.S_ISLNK(member.external_attr >> 16)):
                raise ValueError("unsafe_archive_path")
            seen.add(member.filename)
        if not set(REQUIRED).issubset(seen):
            raise ValueError("incomplete_package")
        archive.extractall(destination)


def download_release(destination: Path):
    filename = "JustMyType-" + VERSION + ".zip"
    with urlopen(RELEASE + "/" + filename + ".sha256", timeout=20) as response:
        checksum = response.read(256).decode("ascii").split()[0]
    with urlopen(RELEASE + "/" + filename, timeout=30) as response:
        body = response.read(8000001)
    if len(body) > 8000000 or hashlib.sha256(body).hexdigest() != checksum:
        raise ValueError("release_checksum_mismatch")
    extract_package(body, destination)


def source_hash(source: Path) -> str:
    out = hashlib.sha256()
    for name in REQUIRED:
        path = source / name
        if not path.is_file() or path.is_symlink() or source.resolve() not in path.resolve().parents:
            raise ValueError("missing_or_unsafe_payload: " + name)
        body = path.read_bytes()
        if len(body) > 1000000:
            raise ValueError("source_bound")
        out.update(name.encode() + b"\0" + body)
    manifest = json.loads((source / REQUIRED[1]).read_text(encoding="utf-8"))
    if manifest.get("name") != NAME or manifest.get("version") != VERSION:
        raise ValueError("manifest_mismatch")
    return out.hexdigest()


def install(source: Path, home: Path, bindir: Path, binary: str, trust: bool = True) -> dict:
    generation = source_hash(source)
    interpreter = "python" if os.name == "nt" else "python3"
    if not shutil.which(interpreter):
        raise RuntimeError(interpreter + " 3.11+ must be on PATH for native hooks.")
    check = subprocess.run([interpreter, "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    if check.returncode:
        raise RuntimeError(interpreter + " 3.11+ must be on PATH for native hooks.")
    env = dict(os.environ, CODEX_HOME=str(home))
    version = cli(binary, env, "--version").strip()
    data = home / "plugins/data/justmytype-justmytype"
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = data / "package"
    installed_before = target.exists()
    if installed_before and source_hash(target) != generation:
        raise RuntimeError("An installed package differs. Uninstall JustMyType before replacing this version; private data is retained.")
    if not installed_before:
        stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=data))
        try:
            for name in REQUIRED:
                dest = stage / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / name, dest)
            stage.rename(target)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    # Native Codex owns registration and its cache. No whole-config replacement.
    cli(binary, env, "plugin", "marketplace", "add", str(target))
    cli(binary, env, "plugin", "add", PLUGIN_ID)
    hooks = trust_hooks(binary, env) if trust else []
    bindir.mkdir(parents=True, exist_ok=True)
    launcher = bindir / (NAME + (".cmd" if os.name == "nt" else ""))
    runtime = target / "plugins/justmytype/scripts/jmt.py"
    if launcher.exists() and "JustMyType launcher" not in launcher.read_text(encoding="utf-8"):
        raise RuntimeError("Refusing to replace an unrelated launcher")
    if os.name == "nt":
        text = '@echo off\r\nrem JustMyType launcher\r\n"' + sys.executable + '" "' + str(runtime) + '" --data-dir "' + str(data) + '" %*\r\n'
    else:
        import shlex
        text = "#!/bin/sh\n# JustMyType launcher\nexec " + shlex.quote(sys.executable) + " " + shlex.quote(str(runtime)) + ' --data-dir ' + shlex.quote(str(data)) + ' "$@"\n'
    launcher.write_text(text, encoding="utf-8")
    if os.name != "nt":
        launcher.chmod(0o755)
    receipt = {"name": "JustMyType", "version": VERSION, "package_sha256": generation,
               "codex": version, "hooks_trusted": len(hooks), "launcher": str(launcher), "data_dir": str(data)}
    (data / "install-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def uninstall(home: Path, bindir: Path, binary: str) -> dict:
    env = dict(os.environ, CODEX_HOME=str(home))
    cli(binary, env, "plugin", "remove", PLUGIN_ID)
    cli(binary, env, "plugin", "marketplace", "remove", NAME)
    launcher = bindir / (NAME + (".cmd" if os.name == "nt" else ""))
    if launcher.exists() and "JustMyType launcher" in launcher.read_text(encoding="utf-8"):
        launcher.unlink()
    # Keep private state/config. Remove only the reviewed distribution payload.
    data = home / "plugins/data/justmytype-justmytype"
    package = data / "package"
    if package.exists() and not package.is_symlink():
        source_hash(package)
        shutil.rmtree(package)
    return {"uninstalled": PLUGIN_ID, "private_data_retained": str(data)}


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", str(Path.home()/".codex"))))
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ("bin" if os.name == "nt" else ".local/bin"))
    parser.add_argument("--codex", default=os.environ.get("CODEX_BIN", "codex"))
    parser.add_argument("--no-trust", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        parser.error("Python 3.11+ is required")
    home, bindir = args.codex_home.expanduser().resolve(), args.bin_dir.expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)
    try:
        if args.uninstall:
            out = uninstall(home, bindir, args.codex)
        elif args.source:
            out = install(args.source.resolve(), home, bindir, args.codex, not args.no_trust)
        else:
            with tempfile.TemporaryDirectory(prefix="justmytype-download-") as temp:
                download_release(Path(temp))
                out = install(Path(temp), home, bindir, args.codex, not args.no_trust)
        print(json.dumps(out, indent=2))
        if not args.uninstall:
            print("Cloud checks are off until enabled. Run justmytype configure --cloud on --mode observe.")
            print("Set TYPESAFE_API_KEY through your credential manager. Add the reported launcher directory to PATH when needed.")
            if args.no_trust:
                print("Review and trust JustMyType through Codex /hooks before use.")
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print("JustMyType install stopped: " + str(error), file=sys.stderr)
        print("Existing private data and unrelated settings were not replaced. A partial registration can be removed with --uninstall.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
