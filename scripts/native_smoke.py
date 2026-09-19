#!/usr/bin/env python3
"""Real native plugin registration and hook invocation; no model credentials."""
import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sqlite3
import sys
import tempfile
import tomllib
from pathlib import Path
import install

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--codex',default='codex');p.add_argument('--output',type=Path);a=p.parse_args()
    with tempfile.TemporaryDirectory(prefix='JustMyType OS proof ') as temp:
        base=Path(temp);home=base/'codex home';bindir=base/'bin space';home.mkdir()
        (home/'config.toml').write_text('model = "preserve-this-model"\n',encoding='utf-8')
        data=home/'plugins/data/justmytype-justmytype';data.mkdir(parents=True)
        config_bytes=b'{"cloud_enabled":false,"mode":"guard","max_calls_per_turn":32}\n'
        (data/'config.json').write_bytes(config_bytes)
        db=sqlite3.connect(data/'state.sqlite3');db.execute('CREATE TABLE fixture (value TEXT)')
        db.execute('INSERT INTO fixture VALUES (?)',('preserve-state',));db.commit();db.close()
        env=dict(os.environ,CODEX_HOME=str(home))
        required_root=ROOT
        prior=base/'prior-source';
        for name in install.REQUIRED:
            target=prior/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
        prior_manifest=prior/'plugins/justmytype/.codex-plugin/plugin.json'
        prior_meta=json.loads(prior_manifest.read_text(encoding='utf-8'));prior_meta['version']=prior_meta['version']+'.prior'
        prior_manifest.write_text(json.dumps(prior_meta,indent=2)+'\n',encoding='utf-8')
        with (prior/'plugins/justmytype/scripts/jmt.py').open('a',encoding='utf-8') as old:
            old.write('\n# prior fixture\n')
        def installer(source):
            if platform.system()=='Windows':
                return ['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'install.ps1'),'-Source',str(source),'-CodexHome',str(home),'-BinDir',str(bindir),'-Codex',a.codex]
            return ['sh',str(ROOT/'install.sh'),'--source',str(source),'--codex-home',str(home),'--bin-dir',str(bindir),'--codex',a.codex]
        r=subprocess.run(installer(prior),env=env,capture_output=True,text=True,timeout=120)
        if r.returncode:raise RuntimeError(r.stdout+r.stderr)
        prior_version=prior_meta['version'];prior_cache=home/'plugins/cache/justmytype/justmytype'/prior_version
        prior_declaration=json.loads((prior_cache/'hooks/hooks.json').read_text())
        retained_handler=prior_declaration['hooks']['SessionStart'][0]['hooks'][0]
        for source in (ROOT,ROOT):
            command=installer(source)
            r=subprocess.run(command,env=env,capture_output=True,text=True,timeout=120)
            if r.returncode:raise RuntimeError(r.stdout+r.stderr)
        manifest=json.loads((ROOT/'plugins/justmytype/.codex-plugin/plugin.json').read_text(encoding='utf-8'))
        manifest_version=manifest['version']
        receipt=json.loads((data/'install-receipt.json').read_text())
        assert receipt['hooks_trusted']==5
        cfg=tomllib.loads((home/'config.toml').read_text())
        assert cfg['model']=='preserve-this-model'
        assert (data/'config.json').read_bytes()==config_bytes
        db=sqlite3.connect(data/'state.sqlite3');assert db.execute('SELECT value FROM fixture').fetchone()[0]=='preserve-state';db.close()
        rpc=install.RPC(a.codex,env)
        try:hooks=install.owned_hooks(rpc)
        finally:rpc.close()
        assert len(hooks)==5
        cache=home/'plugins/cache/justmytype/justmytype'/manifest_version
        assert (cache/'scripts/jmt.py').exists(),str(cache)
        declaration=json.loads((cache/'hooks/hooks.json').read_text())
        handler=retained_handler
        event={'hook_event_name':'SessionStart','session_id':'public-smoke','source':'startup'}
        e=env|{'PLUGIN_ROOT':str(cache),'PLUGIN_DATA':str(data)}
        if os.name=='nt':
            # Match Codex 0.154.0 command_runner.rs: /C + raw_arg(quoted command).
            # A Python argv list would backslash-escape embedded quotes for CRT,
            # but cmd.exe needs the raw command string, as Codex supplies it.
            cmd=subprocess.list2cmdline([os.environ.get('COMSPEC','cmd.exe'),'/C'])+' "'+handler['commandWindows']+'"'
        else:cmd=['/bin/sh','-c',handler['command']]
        r=subprocess.run(cmd,input=json.dumps(event),env=e,text=True,capture_output=True,timeout=20)
        assert r.returncode==0,r.stderr
        out=json.loads(r.stdout);assert out['hookSpecificOutput']['hookEventName']=='SessionStart'
        assert 'cloud off' in out['hookSpecificOutput']['additionalContext']
        doctor=subprocess.run([sys.executable,str(cache/'scripts/jmt.py'),'--data-dir',str(data),'doctor'],env=e,text=True,capture_output=True,timeout=20)
        assert doctor.returncode==0,doctor.stderr
        assert json.loads(doctor.stdout)['version']==install.VERSION
        (data/'retained-test.txt').write_text('synthetic private state',encoding='utf-8')
        install.uninstall(home,bindir,a.codex)
        assert (data/'retained-test.txt').read_text()=='synthetic private state'
        assert (data/'config.json').read_bytes()==config_bytes
        db=sqlite3.connect(data/'state.sqlite3');assert db.execute('SELECT value FROM fixture').fetchone()[0]=='preserve-state';db.close()
        assert tomllib.loads((home/'config.toml').read_text())['model']=='preserve-this-model'
        result={'platform':platform.system(),'python':platform.python_version(),'codex':receipt['codex'],'manifest_version':manifest_version,'prior_fixture_version':prior_version,'native_registration':True,'native_upgrade':True,'repeat_install':True,'private_fixture_preserved':True,'path_with_spaces':True,'owned_hooks':5,'platform_hook_command':True,'unrelated_model_preserved':True,'uninstall_retains_data':True,'live_model_turn':False}
        if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))

if __name__=='__main__':main()
