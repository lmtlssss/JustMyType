#!/usr/bin/env python3
"""Check the exact Git publication set without printing matched secret values."""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ROOTS={'.agents','.github','plugins','scripts','tests','evals','demo','docs'}
TOP={'README.md','LICENSE','.gitignore','install.sh','install.ps1'}
PATTERNS={
    'private_home':re.compile(rb'/(?:home|Users)/[A-Za-z0-9_.-]+/'),
    'private_network':re.compile(rb'\b(?:192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)\b'),
    'github_credential':re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    'provider_credential':re.compile(rb'\bsk[-_][A-Za-z0-9_-]{24,}\b'),
    'private_key':re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\r\n]+[A-Za-z0-9+/=]{40,}')
}


def main():
    names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    files=[n for n in names if n]
    failures=[]
    credentials=[v.encode() for k,v in os.environ.items() if re.search(r'(?i)(?:KEY|TOKEN|SECRET|PASSWORD)$',k) and len(v)>=12]
    manifest=[]
    for name in files:
        path=ROOT/name; parts=Path(name).parts
        if (parts[0] not in ROOTS and name not in TOP) or any(x in parts for x in ['.private','__pycache__','.pytest_cache','.env']):
            failures.append({'file':name,'reason':'outside_public_allowlist'});continue
        if path.is_symlink():
            failures.append({'file':name,'reason':'symlink'});continue
        data=path.read_bytes()
        if any(value in data for value in credentials):failures.append({'file':name,'reason':'exact_credential_match'})
        if path.suffix not in ('.png','.jpg','.mp4'):
            for reason,pattern in PATTERNS.items():
                if pattern.search(data):failures.append({'file':name,'reason':reason})
        manifest.append({'file':name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
    result={'tracked_files':len(files),'credential_values_checked':len(credentials),'findings':failures,
            'public_set_sha256':hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()}
    print(json.dumps(result,indent=2))
    return bool(failures)

if __name__=='__main__':raise SystemExit(main())
