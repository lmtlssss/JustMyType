#!/usr/bin/env python3
"""Real native plugin registration and hook invocation; no model credentials."""
import argparse
import importlib.util
import json
import os
import platform
import subprocess
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
        env=dict(os.environ,CODEX_HOME=str(home))
        if platform.system()=='Windows':
            command=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'install.ps1'),'-Source',str(ROOT),'-CodexHome',str(home),'-BinDir',str(bindir),'-Codex',a.codex]
        else:
            command=['sh',str(ROOT/'install.sh'),'--source',str(ROOT),'--codex-home',str(home),'--bin-dir',str(bindir),'--codex',a.codex]
        for _ in range(2):
            r=subprocess.run(command,env=env,capture_output=True,text=True,timeout=120)
            if r.returncode:raise RuntimeError(r.stdout+r.stderr)
        data=home/'plugins/data/justmytype-justmytype'
        receipt=json.loads((data/'install-receipt.json').read_text())
        assert receipt['hooks_trusted']==5
        cfg=tomllib.loads((home/'config.toml').read_text())
        assert cfg['model']=='preserve-this-model'
        rpc=install.RPC(a.codex,env)
        try:hooks=install.owned_hooks(rpc)
        finally:rpc.close()
        assert len(hooks)==5
        cache=home/'plugins/cache/justmytype/justmytype'/install.VERSION
        assert (cache/'scripts/jmt.py').exists(),str(cache)
        declaration=json.loads((cache/'hooks/hooks.json').read_text())
        handler=declaration['hooks']['SessionStart'][0]['hooks'][0]
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
        (data/'retained-test.txt').write_text('synthetic private state',encoding='utf-8')
        install.uninstall(home,bindir,a.codex)
        assert (data/'retained-test.txt').read_text()=='synthetic private state'
        assert tomllib.loads((home/'config.toml').read_text())['model']=='preserve-this-model'
        result={'platform':platform.system(),'python':platform.python_version(),'codex':receipt['codex'],'native_registration':True,'repeat_install':True,'path_with_spaces':True,'owned_hooks':5,'platform_hook_command':True,'unrelated_model_preserved':True,'uninstall_retains_data':True,'live_model_turn':False}
        if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))

if __name__=='__main__':main()
