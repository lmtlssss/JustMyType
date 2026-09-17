# JustMyType

it's not you. it's your arguments.

TypeSafe checks for Codex.

```text
JUSTMYTYPE
──────────────────────────────────────────────────────────

goal + action + evidence  ──►  pass / review / block
completion claim         ──►  observed result
```

## install

Linux / macOS / Windows. Python 3.11+, Git, Codex 0.154.0+.
Use `python3` on Unix; `python` on Windows.

Linux / macOS:

```sh
curl -fsSL https://raw.githubusercontent.com/lmtlssss/JustMyType/main/install.sh | sh
```

Windows PowerShell:

```powershell
curl.exe -fsSL https://raw.githubusercontent.com/lmtlssss/JustMyType/main/install.ps1 -o install.ps1
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

## switch on

Set `TYPESAFE_API_KEY` in your environment.

```sh
justmytype configure --cloud on --mode observe
justmytype doctor --live
```

Cloud checks send redacted goal, action and evidence snippets to TypeSafe.
[Privacy](docs/privacy.md). Start a new Codex conversation after installation.

```sh
justmytype configure --mode guard
```

`observe` adds feedback. `guard` blocks high-confidence conflicts.
Reviews and service failures do not block native tools.

## use

Shell commands, patches and MCP calls are checked before execution.
Completion claims are checked against the current turn's results.

```sh
justmytype check --input action.json
justmytype verify --input claim.json
justmytype guard --goal "Print the current directory." -- pwd
```

CLI `guard` executes only a pass. It also provides the explicit Machine bridge;
ChatGPT does not run Codex hooks automatically.

## proof

[![Live Codex screen recording](demo/live-poster.png)](https://github.com/lmtlssss/JustMyType/releases/download/v0.1.0/JustMyType-live.mp4)

[Watch the live demo](https://github.com/lmtlssss/JustMyType/releases/download/v0.1.0/JustMyType-live.mp4). 28 seconds, real Codex, synthetic data.

15/16 held-out conflicts blocked. 16/16 valid actions passed. One miss.

52 tests. Native installation verified on Linux, macOS and Windows.
[Results](evals/RESULTS.md) · [Platform proof](evals/platform-proof.json) · [Limits](docs/coverage.md)

## remove

```sh
python3 "$HOME/.codex/plugins/data/justmytype-justmytype/package/scripts/install.py" --uninstall
```

Windows: use `python` and your user-profile path. Private settings are retained.

## build

```sh
python3 -m unittest discover -s tests -v
python3 scripts/package.py
```

MIT. Independent integration.
