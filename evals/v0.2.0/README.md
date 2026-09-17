# measured results

The model is `jev-1.13.0` in both versions. The original whole-action questions
and their thresholds are unchanged. The new path adds typed rule binding and
exact comparisons. Engine and input hashes were frozen before each new test.

## new inputs

| Set | Conflicts | 0.1.1 stopped | 0.2.0 stopped | False blocks, old / new | Native-valid actions preserved, old / new |
| --- | ---: | ---: | ---: | ---: | ---: |
| New boundaries and tools | 36 | 34 | 35 | 2 / 2 | 52 / 52 of 54 |
| Multi-rule operational context | 18 | 18 | 18 | 4 / 4 | 26 / 26 of 30 |

The first set has 90 cases. The second has 48. The first set covers money,
units, dates, approval, previews, later instructions, native flags, and existing
non-numeric protections. The second adds longer policies across six domains.
It was authored after the first result, with the engine unchanged, then frozen
before its own evaluation. It is a separate test, not a hidden replacement.

Across these sets, the improvement is one additional conflict stopped, with the
same total false-block count. The second set shows no accuracy gain. These results
do not support a large general accuracy claim.

Native-valid actions include `review` and `unassessed`, because those outcomes
are non-blocking in native guard mode. They are not CLI guard passes. The raw
results report both counts. In the first set, CLI-valid passes were 37 before
and 35 after, and the new engine had one unavailable assessment. In the second
set, both had 24 CLI-valid passes and no unavailable assessment.

| Set | Median check, old / new | p95, old / new | Input tokens, old / new | Logical queries, old / new |
| --- | ---: | ---: | ---: | ---: |
| New boundaries and tools | 368.66 / 454.87 ms | 829.23 / 1055.98 ms | 86,436 / 233,594 | 89 / 246 |
| Multi-rule context | 352.23 / 425.10 ms | 434.44 / 725.72 ms | 61,464 / 249,584 | 48 / 192 |

The added checks cost more calls and tokens. Concurrency limits the extra latency;
it does not remove the cost. Logical queries exclude internal transport retries.
These authored cases are not production error rates or an external audit.

## known refund failure

The earlier 48-request refund case is development data, not held-out evidence.
Astra / medium made a correct plan under the original policy. A later instruction
required review for refunds above $100. The original plugin failed to hold any
of the 11 affected payments. They totalled $1,693.20 in synthetic funds.

The redesigned engine stopped all 11 in the development rerun and preserved all
37 valid actions, with no false blocks. Median check time in that rerun was
422.8 ms. The original recorded run's median was 369.0 ms. This is the main
observed gain. It is deliberately not presented as an unseen test.

The reference app and its new live recording perform actual writes to two fresh
local SQLite ledgers. The independent refund scorer runs after execution and is
never input to either engine. Blocked requests remain unresolved, not completed.
[Refund desk evidence](../../demo/refund-desk/README.md).

## retained evidence

- [First frozen inputs](holdout.json), [freeze receipt](freeze.json), [all paired results](holdout-results.json)
- [Second frozen inputs](context-holdout.json), [freeze receipt](context-freeze.json), [all paired results](context-results.json)
- [Evaluator](evaluate.py), [first generator](make_cases.py), [second generator](make_context_cases.py)

The paired evaluator alternates old/new call order and never executes the tool
commands in its inputs. The fixtures contain synthetic records only. Every miss,
false block, review, unavailable result, token count, and latency is retained.

## reproduce

Extract the 0.1.1 runtime and policy into a separate directory. Use an environment
TypeSafe key, not a key in a file committed to this repository. The evaluator
checks the baseline, current engine, and frozen input hashes before calling the API.

```sh
python evals/v0.2.0/evaluate.py --baseline /path/to/0.1.1/jmt.py --live --output first-local.json
python evals/v0.2.0/evaluate.py --baseline /path/to/0.1.1/jmt.py --input evals/v0.2.0/context-holdout.json --freeze evals/v0.2.0/context-freeze.json --live --output context-local.json
```

A repeat is a regression run, not a newly unseen test. Keep its output separately.
