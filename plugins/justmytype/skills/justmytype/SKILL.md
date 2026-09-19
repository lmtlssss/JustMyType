---
name: justmytype
description: Check proposed actions and completion claims, batch typed Jev decisions, or select relevant optional source context. Use for bounded semantic judgments, not as a replacement for direct source reading, authorization, or behavioral proof.
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

## Reusable decisions

Use `justmytype decide --input FILE` for independent typed questions over one supplied state. The JSON is `{"state": {...}, "questions": {"id": {"type":"noul","instructions":"Does the supplied evidence show X?"}}}`. Choice adds a `criteria` map of existing IDs to descriptions; Score adds an ordered array of 2–10 level descriptions. Supply a no-match option where appropriate. Batch independent questions; consume only the relevant branch. Code owns exact arithmetic, source values and execution. Limits are 32 questions and 32,768 request bytes.

Use `justmytype select --input FILE` when a supplied source/skill catalogue is large enough that relevance ranking helps. Input contains `goal`, `candidates` (each with `id`, `description`, optional `text` and `source`) and optional `max_chars`. Mark binding material `required:true` or kind `instruction`, `cursor`, `failure`, or `receipt`; it is retained in code. Only optional descriptions are ranked. Read selected sources before relying on them. Never filter out mandatory skills or user instructions because a score is low.

An explicit `cache:{"namespace":"task-id","generation":"source-revision"}` permits advisory reuse for five minutes. Change generation when relevant evidence changes. This cache never authorizes an action. `justmytype stats` reports measured advisory usage, not total-agent savings. Partial/unassessed responses retain missing evidence as missing. The native repeat ledger is advisory and adds no cloud requests.
