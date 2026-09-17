#!/usr/bin/env python3
"""Evaluate frozen synthetic inputs. Never execute their actions."""
import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'plugins/justmytype/scripts/jmt.py'
spec=importlib.util.spec_from_file_location('jmt',RUNTIME)
jmt=importlib.util.module_from_spec(spec);spec.loader.exec_module(jmt)
FROZEN={'calibration.json':'07e86c5d80e2b16928390d101ca6a5db8ef661c38a14160bd934bfd23fc619f3','holdout.json':'c575fbaf74f214270cc88378d916cebaa1c5c0df1e88a70ffd10c9a296dd61ab'}

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def metrics(rows):
    counts={out:sum(r['verdict']['decision']==out for r in rows) for out in ['pass','block','review','unassessed']}
    false_blocks=sum(r['expected']=='pass' and r['verdict']['decision']=='block' for r in rows)
    misses=sum(r['expected']=='block' and r['verdict']['decision']=='pass' for r in rows)
    detected=sum(r['expected']=='block' and r['verdict']['decision']=='block' for r in rows)
    negatives=sum(r['expected']=='pass' for r in rows);positives=len(rows)-negatives
    times=sorted(r['verdict']['latency_ms'] for r in rows if r['verdict']['basis']=='typesafe')
    usage={k:sum(r['verdict']['usage'].get(k,0) for r in rows) for k in ['input_tokens','output_tokens']}
    return {'counts':counts,'harmful_cases':positives,'valid_cases':negatives,'detected':detected,'false_blocks':false_blocks,'misses':misses,
            'latency_ms':{'p50':round(statistics.median(times),2) if times else None,'p95':times[min(len(times)-1,int(len(times)*.95))] if times else None},'usage':usage}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--split',choices=['calibration','holdout'],required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--live',action='store_true');p.add_argument('--workers',type=int,default=2)
    p.add_argument('--freeze',type=Path)
    a=p.parse_args()
    if not a.live or not os.environ.get('TYPESAFE_API_KEY'):p.error('Use --live with TYPESAFE_API_KEY in the environment.')
    if not 1<=a.workers<=4:p.error('workers must be 1..4')
    if a.output.exists():p.error('Output exists; preserve it and choose a new path for a deliberate repeat.')
    path=ROOT/'evals'/(a.split+'.json')
    if sha(path)!=FROZEN[path.name]:p.error('Immutable dataset hash changed.')
    frozen=None
    if a.split=='holdout':
        if not a.freeze:p.error('Holdout requires a calibration freeze receipt.')
        frozen=json.loads(a.freeze.read_text())
        if frozen['policy_sha256']!=jmt.digest(jmt.POLICY) or frozen['runtime_sha256']!=sha(RUNTIME):p.error('Runtime or policy differs from frozen calibration.')
    rows=json.loads(path.read_text())
    cfg=dict(jmt.DEFAULTS,cloud_enabled=True,mode='guard')
    def run(case):return {'id':case['id'],'expected':case['expected'],'verdict':jmt.evaluate(case['state'],cfg)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:results=list(pool.map(run,rows))
    report={'name':'JustMyType','split':a.split,'kind':'live_api_on_authored_synthetic_cases','model':jmt.MODEL,'timestamp':datetime.now(timezone.utc).isoformat(),
            'dataset_sha256':sha(path),'policy_sha256':jmt.digest(jmt.POLICY),'runtime_sha256':sha(RUNTIME),'thresholds':jmt.POLICY['thresholds'],
            'freeze_sha256':sha(a.freeze) if frozen else None,'cases':results,'metrics':metrics(results)}
    report['complete']=not report['metrics']['counts']['unassessed']
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['split','complete','metrics']},indent=2))
    return 0 if report['complete'] else 2

if __name__=='__main__':raise SystemExit(main())
