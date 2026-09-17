# demonstrations

[0.1.1 release drill: real traffic, three blocked faults, tested recovery](release-drill/README.md).

[Earlier Astra / medium trial: both builds succeed, no demonstrated advantage](astra-medium/README.md).

## earlier 0.1.0 clip

# live demo

[Watch the screen recording](https://github.com/lmtlssss/JustMyType/releases/download/v0.1.0/JustMyType-live.mp4).

28 seconds. Real Codex interface, real TypeSafe calls, continuous capture at normal speed.

The native hook blocks an invoice-file overwrite. Codex then writes the allowed
status file and verifies that all 10,000 synthetic invoice records are unchanged.
The successful tool output is collapsed by the terminal interface; the actual
result and file checksums are in [the receipt](live-proof.json).

This is a controlled test, not a production incident or an error-rate benchmark.

## file-effect test

The earlier fixed-command comparison remains in [proof.json](proof.json).

```sh
python demo/prove.py --live --output proof-local.json
```
