# coverage

Reference: Codex 0.154.0 native hook contract.

| surface | handling |
| --- | --- |
| Bash, shell/unified-exec | native PreToolUse command and PostToolUse result |
| apply_patch | native command payload, including patch targets |
| MCP tools | native tool name and JSON arguments |
| code-mode nested local calls | Codex's inner native tool hooks |
| Stop | claim compared with this turn's stored observations |
| hosted web/image tools | not intercepted |
| later write_stdin input | not a new preflight boundary |
| subagent without its own prompt/turn context | unassessed, not inferred from cwd |
| ChatGPT Machine connector | explicit CLI bridge only |

The tool name is never treated as evidence of safety. Only a small literal
`pwd` / `git status` fast path skips remote judgment, and configured constraints
disable that path. Other actions use the same three questions.

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
