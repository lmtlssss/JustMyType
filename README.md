# JustMyType

it's not you. it's your arguments.

TypeSafe-backed action checks and reusable typed decisions for Codex and the Machine CLI bridge.

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

Upgrades are in place: the installer stages an immutable payload, atomically
switches the stable dispatcher, and keeps existing private settings.

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

The measurements below are v0.2.0 evidence, not new v0.2.1 release proof.
[Measured results, errors and cost](evals/v0.2.0/README.md).

The original refund failure is fixed: 11/11 affected proposals held, worth
$1,693.20 in synthetic payments. All 37 valid native actions remain unblocked.
[Release-engine regression](evals/v0.2.0/release-validation/refund-regression.json).

111 implementation tests and Linux, macOS and Windows install checks passed for
v0.2.0; these are not v0.2.1 release proof.
[Platform proof](evals/v0.2.0/release-validation/platform-proof.json) / [How 0.2.0 works](docs/v0.2.0.md).
[Earlier live refund recording and its exact source](demo/refund-desk/README.md).


## remove

```sh
python3 "$HOME/.codex/plugins/data/justmytype-justmytype/hook.py" --uninstall
```

This uses the installed stable wrapper. Windows uses `python` and the
equivalent user-profile data path. Private settings are retained.

## build

```sh
python3 -m unittest discover -s tests -v
python3 scripts/package.py
```

MIT. Independent integration.

## decision toolkit in 0.3

`justmytype decide` batches typed questions; `select` ranks optional context while preserving protected text; `stats` reports actual advisory usage. Native hooks record routine observations locally without a semantic verdict, reserve one unchanged budget slot for Stop, and use Jev for bounded substantive actions and final claims. Local routing is not authorization or proof; explicit checks and guards are unchanged.

[Contracts and examples](docs/toolkit.md) · [All 30 source reviews](docs/jev-ecosystem.md)

[v0.3.0 observed source proof](docs/v0.3.0.md)

These additions are not an automatic model switch, transcript rewrite, or permission system. Source review and test results must be reported separately from live installation proof.
