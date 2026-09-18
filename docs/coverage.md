# coverage

This documents the v0.2.1 coverage boundary. Numbered measurements and
platform counts in the v0.2.0 links below remain v0.2.0 evidence only.

Reference: Codex 0.154.0 native hook contract.

| surface | handling |
| --- | --- |
| Bash, shell/unified-exec | native PreToolUse command and PostToolUse result |
| apply_patch | native command payload, including patch targets |
| MCP tools | native tool name and JSON arguments |
| code-mode nested local calls | Codex's inner native tool hooks |
| Stop | claim compared with the bounded current turn and same-task actual observations |
| hosted web/image tools | not intercepted |
| later write_stdin input | not a new preflight boundary |
| subagent without its own prompt/turn context | unassessed, not inferred from cwd |
| ChatGPT Machine connector | explicit CLI bridge only |

An optional active GraphFather context may contribute only its objective,
revision/cursor, and latest user instruction priority. It is read through the
explicit source/CLI context, never by scanning transcripts or guessing from
the cwd. Task outcomes remain bounded to the calling session and task,
generation-labeled; a model verdict is not proof. Unsupported or malformed
calls are rejected before reserving the existing 32-call budget.

The tool name is never treated as evidence of safety. Only a small literal
`pwd` / `git status` fast path skips remote judgment only for an exact positive
goal/action pair. Any additional goal text or configured constraint disables
that path. Other actions use per-instruction judgments and the applicable exact-comparison path.

Observe mode adds feedback. Guard mode denies high-scoring concrete conflicts.
Review, missing context, provider failure and call-budget exhaustion add an
unassessed/review notice; they do not stop a native tool. This fail-open choice
keeps provider outages from locking a workstation. The explicit CLI `guard`
is stricter: it executes only a pass and refuses every other outcome.

The plugin never returns permissionDecision=allow and never rewrites an action.
Native approvals and sandbox settings still apply. Stop correction is limited
to once per turn and respects stop_hook_active. Evidence is bounded; omitted
or unavailable source cannot be reconstructed by this plugin.

This is an error-catching aid, not a sandbox, formal verifier, permission
system or prompt-injection security boundary. A probabilistic miss remains
possible. A user who can edit the plugin/config can bypass it.

## sources

- https://learn.chatgpt.com/docs/hooks
- https://docs.typesafe.ai/api
- https://docs.typesafe.ai/confidence
- https://docs.typesafe.ai/model-jaggedness/jev-1.13

## numeric and date limits in 0.2.0

The added path binds plain-language limits to scalar tool arguments, including
simple literal shell flags. Jev selects meaning and rule authority; code compares
values. It does not parse arbitrary Python, JavaScript, shell substitutions,
array aggregates, or dynamic application state. Unsupported forms retain semantic instruction checks. This is not a general-purpose type system or sandbox.

See [implementation and boundaries](v0.2.0.md) and [measured results](../evals/v0.2.0/README.md).
