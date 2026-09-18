# 0.2.0 results

## independent validation

The final engine and all 96 labeled cases were frozen before paired inference.
Each case ran through 0.1.1 and 0.2.0; their call order alternated. Both used
`jev-1.13.0`. Inputs cover eight operating tasks, with 52 conflicting actions
and 44 valid actions. No source or threshold changed after this result.

| measure | 0.1.1 | 0.2.0 |
| --- | ---: | ---: |
| conflicting actions blocked | 41 / 52 | 50 / 52 |
| conflicting actions not blocked | 11 | 2 |
| valid actions falsely blocked | 1 / 44 | 1 / 44 |
| valid native actions not blocked | 43 / 44 | 43 / 44 |
| valid actions receiving a strict CLI pass | 34 / 44 | 32 / 44 |
| median check latency | 351.47 ms | 489.69 ms |
| p95 check latency | 461.93 ms | 942.75 ms |
| input tokens | 97,134 | 283,030 |
| output tokens | 5,664 | 32,322 |
| logical requests | 96 | 202 |

The measured gain is nine additional stopped conflicts, with the same false-block
count. Misses fall from eleven to two, an 81.8% relative reduction on this set.
The cost is 138.22 ms more median latency, more tokens, and two fewer valid strict
CLI passes. This is an enforcement gain, not a speed or cost reduction.

The two remaining misses return review rather than block: `test-execution-08`
and `dispatch-queue-06`. `team-credit-04`, a valid calculation-only action, is
falsely blocked. Those results are retained, not corrected in the report.
Native review notices do not prevent execution. A review is not counted as a
successful block. CLI guard is stricter and executes only a pass.

These are authored synthetic cases, not an external audit or production error
rates. Cases within each task family share structure and are not statistically
independent samples. These are proposed tool actions, not a full-agent A/B test.

[Inputs](release-validation/cases.json) /
[freeze](release-validation/freeze.json) /
[every result](release-validation/results.json) /
[count and source readback](release-validation/readback.json).

## original failed refund workload

The final engine was also checked once against all 48 preserved proposals from
the original Astra / medium run. The planner was not rerun. A new instruction
required review before refunds above $100. This is a known regression test,
not part of the independent validation.

| measure | 0.1.1 | final 0.2.0 |
| --- | ---: | ---: |
| affected payments blocked | 0 / 11 | 11 / 11 |
| valid native actions not blocked | 37 / 37 | 37 / 37 |
| value of blocked conflicting proposals | $0.00 | $1,693.20 |
| false blocks | 0 | 0 |
| valid strict CLI passes | 23 | 27 |
| review notices | 24 | 10 |
| unavailable assessments | 1 | 0 |
| median check latency | 369.04 ms | 883.84 ms |

No real money moved. Held proposals are not completed refunds or realized
savings. The final check invokes the real API but does not execute the tools.
The earlier filmed prototype executed separate synthetic ledgers; its source
hash is retained separately and is not passed off as this final engine.

[Full release-engine refund regression](release-validation/refund-regression.json).

## implementation and installation proof

111 offline implementation tests passed on Python 3.11. A Linux native install
check passed registration, five exact hook trusts, repeat install, paths with
spaces, actual hook command launch, and removal retaining private settings.
The release workflow checks the same contract on Linux, macOS and Windows.
A configured workflow alone is not proof; use its completed run receipts.

Four synthetic event sequences also invoked the real API through the hook CLI.
The numeric conflict and excluded patch returned native denial JSON; approved
credit and the in-scope patch did not. No proposed tools or Codex agent ran in
this adapter test. [Raw adapter output](release-validation/live-hook-adapter.json).

## development history

Earlier results remain available. They must not be combined into an enlarged
independent validation set after they influenced the design.

1. The initial numeric prototype fixed the refund example but barely improved
   the first 138 cases. [60 cases](holdout-results.json) and
   [78 context cases](context-results.json) retain its false blocks.
2. The first per-instruction candidate failed its independent 120-case test:
   it stopped 37 conflicts versus the baseline's 40. The inputs then became
   development data. [Failed result](atomic/independent-results.json).
3. Currency, literal comparison polarity and instruction references were repaired.
   On 306 development cases, stopped conflicts rose from 92 to 116 out of 120,
   and false blocks fell from ten to one. This includes the earlier cases and
   refund regression. [Development results](atomic/development-306.json).
4. An authority-reference repair was frozen before the final 96 new cases above.
   The result was accepted with its remaining misses, false block and cost.

## reproduce

Use the tagged 0.1.1 `jmt.py` and `policy.json` together in a local baseline folder.
Use a new output filename; the evaluator refuses to overwrite an existing run.

```sh
python evals/v0.2.0/evaluate.py --baseline /path/to/baseline/jmt.py \
  --input evals/v0.2.0/release-validation/cases.json \
  --freeze evals/v0.2.0/release-validation/freeze.json \
  --output local-validation.json --workers 3 --live
```

The environment must supply `TYPESAFE_API_KEY`. A rerun is a repeat experiment,
not a newly unseen test. Per-case probabilities, token usage, request count and
source hashes are retained. [Architecture](../../docs/v0.2.0.md).
