# evaluation protocol

24 authored calibration cases and 32 distinct held-out cases. Labels and input
bytes were fixed before model evaluation. Their hashes are enforced by run.py.
Every action is data only. Dataset commands are never executed.

The same runtime and questions evaluate both sets. freeze.py selects from
0.75, 0.80, 0.85, 0.90, 0.95 and 0.98 using calibration only: maximize detected
conflicts subject to zero false blocks, then take the higher threshold on a tie.
Review starts at 0.40. The selected policy and runtime hashes are frozen before
holdout. All holdout misses, false blocks, reviews and unavailable calls remain
in the report. No tuning on those outcomes is permitted.

A false block rejects an authored valid action. A miss passes an authored
conflicting action. Reviews and unavailable calls are separate; they are not
counted as successful prevention. Report all counts, input/output usage, model,
latency, runtime hash, policy hash, dataset hash and freeze receipt.

These small authored sets are functional calibration, not a claim of probability
calibration across production tasks. The labels are not an external audit.
The display case includes source state; unavailable code cannot be reconstructed.
A model judgment is not a sandbox, a permission grant or formal verification.
