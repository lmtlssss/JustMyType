# field test 001

Two disposable copies. The same deletion command.
10,000 generated invoice records in each copy. No customer data.

The unchecked command runs and removes the first copy's invoice directory.
The JustMyType CLI guard evaluates the same command against the cleanup request.
The proof then tries the correct build cleanup and verifies the retained ledger
by row count and SHA-256. It records every actual verdict and file result.

This is a fixed-command test, not an unguarded-agent performance trial.
The clip replays recorded results. It is not a desktop capture or real-time video.
No timing claim is derived from animation speed. API latency is measured separately.

```sh
python demo/prove.py --live --output demo/proof.json
python demo/render.py --proof demo/proof.json --holdout evals/holdout-results.json --output dist/JustMyType-demo.mp4
```

The proof needs an environment TypeSafe key. Rendering needs Pillow, a system
DejaVu or Liberation font, and ffmpeg. No font files or sound samples are bundled.
