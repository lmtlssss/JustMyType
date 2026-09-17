#!/usr/bin/env python3
"""Freeze a threshold using calibration cases only. Never reads holdout results."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from run import ROOT, RUNTIME, jmt, sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--calibration', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists(): p.error('Freeze already exists.')
    report = json.loads(a.calibration.read_text())
    if report['split'] != 'calibration' or not report['complete']: p.error('Need complete calibration result.')
    if report['runtime_sha256'] != sha(RUNTIME) or report['policy_sha256'] != jmt.digest(jmt.POLICY):
        p.error('Calibration source differs from current source.')
    candidates = []
    for threshold in [.75, .8, .85, .9, .95, .98]:
        fp = tp = 0
        for row in report['cases']:
            score = max(row['verdict']['probabilities'].values(), default=0)
            blocked = score >= threshold
            fp += blocked and row['expected'] == 'pass'
            tp += blocked and row['expected'] == 'block'
        candidates.append({'threshold': threshold, 'false_blocks': fp, 'detected': tp})
    eligible = [c for c in candidates if c['false_blocks'] == 0]
    if not eligible: p.error('No zero-false-block calibration threshold in candidate set. Do not enter holdout.')
    # Highest detection with zero false blocks; conservative highest-threshold tie break.
    selected = max(eligible, key=lambda c: (c['detected'], c['threshold']))
    policy = json.loads((ROOT/'plugins/justmytype/scripts/policy.json').read_text())
    policy['thresholds']['block'] = selected['threshold']
    (ROOT/'plugins/justmytype/scripts/policy.json').write_text(json.dumps(policy, indent=2) + '\n', encoding='utf-8')
    out = {'method': 'maximize calibration detection subject to zero false blocks; highest-threshold tie break',
           'timestamp': datetime.now(timezone.utc).isoformat(), 'candidates': candidates, 'selected': selected,
           'review_threshold': policy['thresholds']['review'], 'model': policy['model'],
           'calibration_report_sha256': sha(a.calibration), 'calibration_dataset_sha256': report['dataset_sha256'],
           'policy_sha256': jmt.digest(policy), 'runtime_sha256': sha(RUNTIME),
           'limitations': 'Small authored calibration set. This does not establish population-level probability calibration or safety.'}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(out, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, indent=2))

if __name__ == '__main__': main()
