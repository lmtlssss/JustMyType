"""Paired API evaluation of fixed inputs; never executes the proposed tool."""
import argparse, concurrent.futures, hashlib, importlib.util, json, os, statistics, time
from pathlib import Path
from datetime import datetime, timezone
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def stats(rows,key):
    rs=[r[key] for r in rows];times=[x['latency_ms'] for x in rs]
    return {'total':len(rows),'conflicts':sum(r['expected']=='block' for r in rows),
            'stopped':sum(r['expected']=='block' and r[key]['decision']=='block' for r in rows),
            'false_blocks':sum(r['expected']=='pass' and r[key]['decision']=='block' for r in rows),
            'valid_native_actions_preserved':sum(r['expected']=='pass' and r[key]['decision']!='block' for r in rows),
            'valid_cli_passes':sum(r['expected']=='pass' and r[key]['decision']=='pass' for r in rows),
            'review':sum(x['decision']=='review' for x in rs),'unassessed':sum(x['decision']=='unassessed' for x in rs),
            'p50_ms':round(statistics.median(times),2),'p95_ms':round(sorted(times)[min(len(times)-1,int(len(times)*.95))],2),
            'input_tokens':sum(x.get('usage',{}).get('input_tokens',0) for x in rs),
            'output_tokens':sum(x.get('usage',{}).get('output_tokens',0) for x in rs),
            'logical_queries':sum(x.get('api_requests',int(x['basis']=='typesafe')) for x in rs)}

def main():
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True);p.add_argument('--input',type=Path,default=HERE/'holdout.json');p.add_argument('--freeze',type=Path,default=HERE/'freeze.json');p.add_argument('--output',type=Path,required=True);p.add_argument('--live',action='store_true');p.add_argument('--workers',type=int,default=2);a=p.parse_args()
    if not a.live or not os.environ.get('TYPESAFE_API_KEY'):p.error('Requires explicit --live and an environment credential.')
    if a.output.exists():p.error('Keep prior results; output exists.')
    if not 1<=a.workers<=3:p.error('workers must be 1..3')
    old=load('before',a.baseline);new=load('after',ROOT/'plugins/justmytype/scripts/jmt.py');freeze=json.loads(a.freeze.read_text())
    if new.ENGINE_SHA256!=freeze['engine_sha256'] or sha(a.input)!=freeze['dataset_sha256'] or sha(a.baseline)!=freeze['baseline_runtime_sha256']:p.error('Frozen source/input changed.')
    data=json.loads(a.input.read_text());started=datetime.now(timezone.utc).isoformat();t0=time.monotonic()
    def run(pair):
        i,row=pair;output={'id':row['id'],'family':row['family'],'expected':row['expected']}
        engines=[('before',old),('after',new)] if i%2==0 else [('after',new),('before',old)]
        for key,engine in engines:output[key]=engine.evaluate(row['input'],{'cloud_enabled':True,'mode':'guard'})
        return output
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:rows=list(pool.map(run,enumerate(data)))
    result={'kind':'authored_out_of_sample_fixed_pair_comparison','started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),'wall_seconds':round(time.monotonic()-t0,3),'dataset_sha256':sha(a.input),'freeze_sha256':sha(a.freeze),'engine_sha256':new.ENGINE_SHA256,'model':new.MODEL,'cases':rows,'before':stats(rows,'before'),'after':stats(rows,'after'),'limitations':'Authored cases, not production error rates. Every output retained. Review/unassessed do not stop a native action, but neither is a CLI guard pass. No action is executed in this evaluation.'}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['before','after','wall_seconds']},indent=2))
if __name__=='__main__':main()
