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

Upgrading from 0.1.0: run the removal command below, then install again.
Private settings are retained.

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

[![Live release drill](demo/release-drill/poster.png)](demo/release-drill/JustMyType-Release-Drill.mp4)

[Watch the release drill](demo/release-drill/JustMyType-Release-Drill.mp4).
54 seconds. Astra / medium. Three deliberate fault probes, then a tested repair.
279 bad checkout responses without the plugin; zero with it. Synthetic data.
[Method, prior failure and all results](demo/release-drill/README.md).

56 tests. Native installation verified on Linux, macOS and Windows.
[0.1.1 changes](docs/v0.1.1.md) / [platform proof](evals/v0.1.1-platform-proof.json).

The original 0.1.0 held-out test blocked 15/16 conflicts and passed 16/16 valid
actions, with one miss. [Original results](evals/RESULTS.md) / [limits](docs/coverage.md).

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
