# JustMyType decision toolkit

The existing `check`, `verify` and pass-only `guard` retain their policy and permissions. These new commands are advisory: an answer is neither permission nor proof.

## decide

`justmytype decide --input request.json` accepts the actual TypeSafe shape:

```json
{"state":{"request":"Find the deployment instructions"},"questions":{"route":{"type":"choice","instructions":"Which source should be opened?","criteria":{"deploy":"Deployment guide","design":"Visual design guide","none":"Neither"}},"needs_source":{"type":"noul","instructions":"Does the request need source material?"},"relevance":{"type":"score","instructions":"How relevant is the deployment guide?","criteria":["Unrelated","Useful","Directly required"]}}}
```

All questions share one evaluation. Choice returns a supplied ID and its distribution; Noul returns the probability of yes; Score returns a probability-weighted level and distribution. Confidence is not correctness. Do not ask Jev to generate text or calculate exact amounts.

Limits: 32 questions, Choice 2–255 options, Score 2–10 described levels, and 32,768 UTF-8 bytes for the model request. Oversize input is rejected, not silently shortened. Answers, usage, model identity, finite values and distributions are validated.

An optional `cache: {"namespace":"my-task","generation":"source-v1"}` enables advisory reuse. The key includes request content, model, runtime, namespace and generation. Entries expire after 300 seconds; at most 128 remain. Inputs changed by credential redaction are not cached. Reuse requires the caller to identify the relevant source generation. Never treat an old judgment as a current observation.

A hit reports `cache_hit:true`, `evaluations:0`, zero current usage and separate `source_usage`. A failed or disabled evaluation returns `status:unassessed`, not a fabricated answer.

## select

`justmytype select --input candidates.json` chooses optional context without reading files or rewriting history:

```json
{"goal":"Check a release","max_chars":12000,"candidates":[{"id":"rule","description":"Binding user instruction","kind":"instruction","text":"Do not publish before the required checks pass."},{"id":"deploy","description":"Release procedure and rollback commands","kind":"reference","source":"docs/deploy.md","text":"Original source text supplied by the caller."}]}
```

At most 64 candidates are scored in batches of 16. Only the goal, candidate IDs and descriptions go to Jev; full text and source paths stay out of that request. The output copies selected text verbatim.

`required:true` and kinds `instruction`, `cursor`, `failure`, and `receipt` are protected in code. Optional kinds are `reference` and `skill`. Protected text is never submitted for deletion. If it alone exceeds the character budget, the result explicitly reports `budget_exceeded`; the caller must resolve the budget.

Optional scores use a 0–4 relevance rubric; 3 or above is eligible. This is a rubric score, not a probability of correctness. Results include selected items, omitted source pointers/reasons, coverage, and usage. Incomplete assessment has `no_match:null`, never a semantic no-match claim. A description is only a retrieval hint: the primary agent still reads the selected source before relying on it. Mandatory skill use and original instructions outrank ranking.

## progress and stats

Native PostToolUse records bounded observation identities when an exact active task and generation are available. The third identical action/outcome in an unchanged generation emits one advisory; additional repeats do not repeatedly steer. Transport timing/chunk IDs do not create fake changed evidence.

Exit zero means the command exited, not that the requested behavior was proved. Pending and unknown results are never treated as success. Observations are scoped to a session/task, bounded to 64 events and 128 scopes, and expire after seven days. Credential-redacted observations are skipped rather than hashed.

`justmytype progress --session ID --task ID` reads an explicit ledger scope. `justmytype stats` reports advisory evaluations, cache hits, errors and provider-reported tokens. Logical evaluations can contain transport retries; these counters are not a claim about total agent/API savings.

## Operation and privacy

Existing cloud configuration and credential-runner settings are reused. A select operation loads credentials once around its entire batch loop. No API key is put in command arguments, package files, logs or cache keys.

Native hooks cover supported local tools; hosted tools and later stdin writes remain outside their coverage. ChatGPT/Machine uses the installed CLI explicitly and does not inherit native Codex hook execution. No new connector, daemon, model proxy, database server, or dependency is required.

The old 32-per-turn native budget limits assessments. Numeric checks may use several provider requests per assessment; it was never a 32-wire-request guarantee.

Use the public JSON recipes in `demo/recipes/` as starting points. Each keeps exact values and execution in code.
