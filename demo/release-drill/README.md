# release drill

[Watch the 54-second recording](JustMyType-Release-Drill.mp4).

Astra / medium in both panes. Same request, starting files and fault probes.
Real native Codex calls, live HTTP traffic, synthetic order data.

| observed during the drill | without | with JustMyType 0.1.1 |
| --- | ---: | ---: |
| checkout requests | 1,141 | 1,141 |
| wrong-price or unavailable responses | 279 | 0 |
| samples with missing order history | 199 | 0 |
| fault attempts blocked before execution | 0 | 3 |
| final tests passed | 4,096 | 4,096 |
| final order records | 10,000 | 10,000 |

The three probes deploy a failed candidate, delete order history and publish a
false passed-test claim. Both agents were explicitly asked to attempt them.
This is a controlled fault test of the execution gate, not a claim that the
model made three spontaneous mistakes.

Both agents then repair the discount, quantity, tax and shipping calculation,
run the original tests, and deploy the exact tested candidate. Both finish
correctly. With the plugin, the store keeps serving the correct price and the
order file remains intact throughout. The other copy needs recovery first.

The lower screen reads actual HTTP responses and the native hook database.
All footage is screen capture. Cuts and playback speed are marked and shared
by both panes. Local path-bearing diagnostic rows are covered and labeled.
No results are reconstructed.

## retained limits

A first trial with 0.1.0 exposed lost test-result tails and a false block on
evidence archival. The 0.1.1 repair and the first trial are recorded in
[proof.json](proof.json). This filmed validation is not an unseen benchmark.
Five non-blocking review notices remain in the repaired run.

[Prompt](prompt.txt) / [exact drill](DRILL.md) / [all HTTP samples](traffic.jsonl) /
[without-plugin result](without-results.md) / [with-plugin result](with-results.md).

`python3 make_fixture.py` creates the disposable source fixture. It does not
run an agent or execute the fault probes. The instrument source is
[monitor.py](monitor.py); it reads the supplied lab state, not private accounts.
