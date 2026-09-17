---
name: justmytype
description: Check a planned action against the user's goal, or verify a completion claim against actual tool evidence. Use JustMyType when a consequential command, patch, MCP action or outcome claim needs a bounded second opinion. Do not treat a model score as authority or proof.
---
# JustMyType

Native hooks retain the current turn's bounded goal and observations. No transcript crawl.
Use `justmytype doctor` to check the installed mode and configuration.
Use `justmytype check --input FILE` with JSON:

```json
{"goal":"Inspect only. Do not restart.","action":{"tool":"Bash","arguments":{"command":"systemctl restart demo.service"}},"evidence":[],"constraints":[]}
```

Use `justmytype verify --input FILE` with `claim` and chronological `evidence` strings.
A block means reconcile the action, not find a different tool to bypass the same constraint.
A review or unassessed result is not approval. Missing evidence must stay missing.
A pass means no conflict was detected by these questions. It is not a security guarantee.
Keep the user's permission, native approvals, sandbox, and real test requirements unchanged.
Do not put credentials in input files. Cloud mode sends bounded redacted snippets to TypeSafe.
ChatGPT Machine calls do not automatically execute Codex hooks. For an explicit bridge,
use the installed `justmytype check`, or `justmytype guard --goal TEXT -- COMMAND ARGS`.
Both read the same private configuration; guard executes argv only after a pass.
