#!/bin/sh
set -eu
umask 077
python=python3
"$python" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'
# Local source installs are also used by the OS proof.
if [ "${1:-}" = "--source" ]; then
  source=$2; shift 2
  exec "$python" "$source/scripts/install.py" --source "$source" "$@"
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
curl -fsSL --proto '=https' --tlsv1.2 https://raw.githubusercontent.com/lmtlssss/JustMyType/v0.2.0/scripts/install.py -o "$tmp/install.py"
"$python" "$tmp/install.py" "$@"
