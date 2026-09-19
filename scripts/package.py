#!/usr/bin/env python3
"""Build the small install pack from an explicit public-file list."""
import hashlib
import zipfile
from pathlib import Path
from install import REQUIRED, VERSION

ROOT = Path(__file__).resolve().parents[1]
FILES = REQUIRED + ["install.sh", "install.ps1", "README.md", "LICENSE", "docs/privacy.md", "docs/coverage.md", "docs/toolkit.md", "docs/jev-ecosystem.md", "demo/recipes/action-target.json", "demo/recipes/source-span.json", "demo/recipes/graph-hop.json", "demo/recipes/progress-signals.json", "demo/recipes/intake-triage.json"]

def package(root=ROOT, destination=None):
    destination = Path(destination or root / "dist")
    destination.mkdir(parents=True, exist_ok=True)
    out = destination / ("JustMyType-" + VERSION + ".zip")
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(FILES):
            path = root / name
            if path.is_symlink():
                raise ValueError("symlink not permitted")
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 17, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    checksum = hashlib.sha256(out.read_bytes()).hexdigest()
    out.with_suffix(".zip.sha256").write_text(checksum + "  " + out.name + "\n", encoding="ascii")
    return out

if __name__ == "__main__":
    print(package())
