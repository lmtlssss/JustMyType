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

Upgrading from 0.1.x: run the removal command below, then install again.
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

96 new cases. Conflicts blocked: **41/52 → 50/52**. One false block in each version.
Median check: **351 → 490 ms**. More checks, more tokens.
[Measured results, errors and cost](evals/v0.2.0/README.md).

The original refund failure is fixed: 11/11 affected proposals held, worth
$1,693.20 in synthetic payments. All 37 valid native actions remain unblocked.
[Release-engine regression](evals/v0.2.0/release-validation/refund-regression.json).

111 implementation tests. [How 0.2.0 works](docs/v0.2.0.md).
[Earlier live refund recording and its exact source](demo/refund-desk/README.md).


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
