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

VERSION = "0.3.0"
NAME = "justmytype"
PLUGIN_ID = "justmytype@justmytype"
RELEASE = "https://github.com/lmtlssss/JustMyType/releases/download/v" + VERSION
REQUIRED = [
    ".agents/plugins/marketplace.json",
    "plugins/justmytype/.codex-plugin/plugin.json",
    "plugins/justmytype/hooks/hooks.json",
    "plugins/justmytype/scripts/jmt.py",
    "plugins/justmytype/scripts/hook.py",
    "plugins/justmytype/scripts/bindings.py",
    "plugins/justmytype/scripts/policy.json",
    "plugins/justmytype/scripts/decisions.py",
    "plugins/justmytype/scripts/selection.py",
    "plugins/justmytype/scripts/progress.py",
    "plugins/justmytype/skills/justmytype/SKILL.md",
    "scripts/install.py",
]


def atomic_write(path: Path, content: bytes, mode: int | None = None) -> None:
    """Replace one file durably, without ever exposing a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is None and path.exists():
            mode = stat.S_IMODE(path.stat().st_mode)
        if mode is not None:
            os.chmod(name, mode)
        os.replace(name, path)
        if os.name != "nt":
            dfd = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def confined_active(data: Path, text: str) -> Path:
    value = text.strip()
    root = (data / "payloads").resolve()
    candidate = (data / value).resolve()
    if (not value or Path(value).is_absolute() or Path(value).parts[:1] != ("payloads",)
            or len(Path(value).parts) != 2 or len(Path(value).parts[1]) != 64
            or any(c not in "0123456789abcdef" for c in Path(value).parts[1])
            or root not in candidate.parents):
        raise ValueError("active_payload_invalid")
    if candidate.is_symlink() or not candidate.is_dir():
        raise ValueError("active_payload_missing")
    return candidate


def snapshot(path: Path) -> tuple[bytes, int] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("unsafe_existing_path: " + str(path))
    return path.read_bytes(), stat.S_IMODE(path.stat().st_mode)


def restore(path: Path, value: tuple[bytes, int] | None) -> None:
    if value is None:
        path.unlink(missing_ok=True)
    else:
        atomic_write(path, value[0], value[1])


def scan_legacy(home: Path, data: Path) -> dict[Path, tuple[bytes, int]]:
    entries = {}
    cache = home / "plugins/cache/justmytype/justmytype"
    for version in ("0.1.1", "0.2.0"):
        entry = cache / version / "scripts/jmt.py"
        if not entry.exists():
            continue
        if entry.is_symlink() or not entry.is_file() or cache.resolve() not in entry.resolve().parents:
            raise ValueError("unsafe legacy entrypoint")
        text = entry.read_text(encoding="utf-8", errors="replace")
        manifest = entry.parents[1] / ".codex-plugin/plugin.json"
        if manifest.exists():
            info = json.loads(manifest.read_text(encoding="utf-8"))
            if info.get("name") != NAME:
                raise ValueError("unrelated legacy entrypoint")
        elif not ("# JustMyType stable compatibility entrypoint" in text or
                  (version == "0.1.1" and "Compatibility entrypoint for stale hooks; execute the installed JMT runtime." in text)):
            raise ValueError("unknown legacy entrypoint")
        entries[entry] = snapshot(entry)
    return entries


def repair_legacy(home: Path, data: Path, entries: dict[Path, tuple[bytes, int]] | None = None) -> None:
    """Leave old cache entrypoints usable while moving them to stable data."""
    backup = data / "compatibility-backups"
    stable = data / "hook.py"
    entries = scan_legacy(home, data) if entries is None else entries
    cache = (home / "plugins/cache/justmytype/justmytype").resolve()
    for entry, original in entries.items():
        if entry.is_symlink() or cache not in entry.resolve().parents:
            raise ValueError("unsafe legacy entrypoint")
        version = entry.parents[1].name
        backup.mkdir(parents=True, exist_ok=True)
        old = backup / (version + "-jmt.py")
        if not old.exists():
            atomic_write(old, original[0], original[1])
        atomic_write(entry, ("#!/usr/bin/env python3\n# JustMyType stable compatibility entrypoint\nimport runpy\nrunpy.run_path(" + repr(str(stable)) + ", run_name='__main__')\n").encode(), 0o755)


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


def register_marketplace(binary: str, env: dict, target: Path, expected_previous: Path | None = None) -> None:
    """Register this local marketplace without taking an unknown owner."""
    raw = cli(binary, env, "plugin", "marketplace", "list", "--json")
    try:
        marketplaces = json.loads(raw).get("marketplaces", [])
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("Codex marketplace list returned invalid JSON") from error
    ours = [item for item in marketplaces if item.get("name") == NAME]
    target_root = target.resolve()
    if ours:
        item = ours[0]
        source = item.get("marketplaceSource") or {}
        root = source.get("source")
        if source.get("sourceType") != "local" or not isinstance(root, str):
            raise RuntimeError("Existing JustMyType marketplace owner is not a local source")
        existing = Path(root).expanduser().resolve()
        allowed = {target_root}
        if expected_previous is not None:
            allowed.add(expected_previous.resolve())
        if existing not in allowed:
            raise RuntimeError("Existing JustMyType marketplace has a different owner")
        if existing == target_root:
            return
        cli(binary, env, "plugin", "marketplace", "remove", NAME)
    cli(binary, env, "plugin", "marketplace", "add", str(target))


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
    if manifest.get("name") != NAME or str(manifest.get("version", "")).split("+", 1)[0] != VERSION:
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
    legacy_entries = scan_legacy(home, data)
    payloads = data / "payloads"
    payloads.mkdir(exist_ok=True, mode=0o700)
    target = payloads / generation
    active = data / "active"
    previous = snapshot(active)
    if previous:
        confined_active(data, previous[0].decode("utf-8"))
    launcher = bindir / (NAME + (".cmd" if os.name == "nt" else ""))
    if launcher.exists() and "JustMyType launcher" not in launcher.read_text(encoding="utf-8"):
        raise RuntimeError("Refusing to replace an unrelated launcher")
    if not target.exists():
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
    elif source_hash(target) != generation:
        raise RuntimeError("Existing immutable payload failed integrity validation")
    dispatcher = data / "hook.py"
    receipt_path = data / "install-receipt.json"
    old_dispatcher, old_launcher, old_receipt = snapshot(dispatcher), snapshot(launcher), snapshot(receipt_path)
    previous_root = None
    if previous:
        previous_root = confined_active(data, previous[0].decode().strip())
    elif (data / "package").is_dir():
        candidate = data / "package"
        try:
            manifest = json.loads((candidate / "plugins/justmytype/.codex-plugin/plugin.json").read_text())
            if manifest.get("name") == NAME and str(manifest.get("version", "")).split("+", 1)[0] in ("0.1.1", "0.2.0"):
                previous_root = candidate
        except (OSError, ValueError, json.JSONDecodeError):
            previous_root = None
    bindir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        text = '@echo off\r\nrem JustMyType launcher\r\n"' + sys.executable + '" "' + str(data / "hook.py") + '" --data-dir "' + str(data) + '" %*\r\n'
    else:
        import shlex
        text = "#!/bin/sh\n# JustMyType launcher\nexec " + shlex.quote(sys.executable) + " " + shlex.quote(str(data / "hook.py")) + ' --data-dir ' + shlex.quote(str(data)) + ' "$@"\n'
    marketplace_ok = plugin_ok = False
    try:
        atomic_write(dispatcher, (source / "plugins/justmytype/scripts/hook.py").read_bytes(), 0o755)
        atomic_write(active, ("payloads/" + generation + "\n").encode(), 0o600)
        repair_legacy(home, data, legacy_entries)
        register_marketplace(binary, env, target, previous_root)
        marketplace_ok = True
        cli(binary, env, "plugin", "add", PLUGIN_ID)
        plugin_ok = True
        hooks = trust_hooks(binary, env) if trust else []
        atomic_write(launcher, text.encode(), 0o755 if os.name != "nt" else 0o644)
        receipt = {"name": "JustMyType", "version": VERSION, "package_sha256": generation,
               "codex": version, "hooks_trusted": len(hooks), "launcher": str(launcher), "data_dir": str(data)}
        atomic_write(receipt_path, json.dumps(receipt, indent=2).encode(), 0o600)
        repair_legacy(home, data, legacy_entries)
        return receipt
    except BaseException as primary:
        failures = []
        for path, value in ((active, previous), (dispatcher, old_dispatcher), (launcher, old_launcher), (receipt_path, old_receipt)):
            try: restore(path, value)
            except BaseException as error: failures.append(str(error))
        for path, value in legacy_entries.items():
            try: restore(path, value)
            except BaseException as error: failures.append(str(error))
        try:
            if previous_root is not None:
                register_marketplace(binary, env, previous_root, target)
                cli(binary, env, "plugin", "add", PLUGIN_ID)
                if trust: trust_hooks(binary, env)
            else:
                if plugin_ok: cli(binary, env, "plugin", "remove", PLUGIN_ID)
                if marketplace_ok: cli(binary, env, "plugin", "marketplace", "remove", NAME)
        except BaseException as error: failures.append("native rollback: " + str(error))
        if failures:
            raise RuntimeError("rollback failure after " + type(primary).__name__ + ": " + "; ".join(failures)) from primary
        raise


def uninstall(home: Path, bindir: Path, binary: str) -> dict:
    env = dict(os.environ, CODEX_HOME=str(home))
    cli(binary, env, "plugin", "remove", PLUGIN_ID)
    cli(binary, env, "plugin", "marketplace", "remove", NAME)
    launcher = bindir / (NAME + (".cmd" if os.name == "nt" else ""))
    if launcher.exists() and "JustMyType launcher" in launcher.read_text(encoding="utf-8"):
        launcher.unlink()
    # Keep payloads, configuration, state and live entrypoints intact.
    data = home / "plugins/data/justmytype-justmytype"
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
            print("Existing configuration retained; new installs default cloud off; run justmytype doctor.")
            print("Set TYPESAFE_API_KEY through your credential manager. Add the reported launcher directory to PATH when needed.")
            if args.no_trust:
                print("Review and trust JustMyType through Codex /hooks before use.")
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print("JustMyType install stopped: " + str(error), file=sys.stderr)
        print("Existing configuration retained; retained payloads are available for recovery.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
