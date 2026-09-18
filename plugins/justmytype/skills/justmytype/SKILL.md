---
name: justmytype
description: Check a planned action against the user's goal, or verify a completion claim against actual tool evidence. Use JustMyType when a consequential command, patch, MCP action or outcome claim needs a bounded second opinion. Do not treat a model score as authority or proof.
---
# JustMyType

Native hooks retain the current turn's bounded goal and observations. No transcript crawl.
An active GraphFather task context is optional and source-qualified: use its
objective, revision/cursor, and latest user instruction priority only. Do not
scan transcripts or infer context from the cwd. Outcomes stay bounded to the
calling session and task, with generation labels; model verdicts are not proof.
Use `justmytype doctor` to check the installed mode and configuration.
Use `justmytype check --input FILE` with JSON:

```json
{"goal":"Inspect only. Do not restart.","action":{"tool":"Bash","arguments":{"command":"systemctl restart demo.service"}},"evidence":[],"constraints":[]}
```

Use `justmytype verify --input FILE` with `claim` and chronological `evidence` strings.
A block means reconcile the action, not find a different tool to bypass the same constraint.
A review or unassessed result is not approval. Missing evidence must stay missing.
A pass means no conflict was detected by these questions. It is not a security guarantee.
Unsupported or malformed calls are rejected before spending the existing
32-call budget.
Keep the user's permission, native approvals, sandbox, and real test requirements unchanged.
Do not put credentials in input files. Cloud mode sends bounded redacted snippets to TypeSafe.
ChatGPT Machine calls do not automatically execute Codex hooks. For an explicit bridge,
use the installed `justmytype check`, or `justmytype guard --goal TEXT -- COMMAND ARGS`.
Both read the same private configuration; guard executes argv only after a pass.

Native hooks fail open on provider/review failures. The explicit CLI `guard`
remains pass-only. Hosted tools and later `write_stdin` input remain outside
native hook coverage.

Numeric and date limits use source-bound field selection and exact comparisons.
A `numeric_rule_violation` includes the field, original bound, and comparison in
`rule_checks`. Fix the conflict or obtain the actual required approval. Do not
change tools or encode arguments differently to bypass the same rule.
The numeric path supports scalar JSON values and simple literal command flags;
complex expressions use the existing general check. `engine_sha256` identifies
the runtime, binding module, and policy together.
