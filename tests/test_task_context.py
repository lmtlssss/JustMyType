import importlib.util, tempfile, unittest, os
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('jmt',ROOT/'plugins/justmytype/scripts/jmt.py'); jmt=importlib.util.module_from_spec(spec); spec.loader.exec_module(jmt)
def gf(sid='canonical', objective='ship safely', generation=2, revision=7):
    return {'schema':1,'session_id':sid,'phase':'build','revision':revision,'generation':generation,'blueprint':{'objective':objective},'cursor':{'layer':'implementation','next':'test'}}
class TaskContextTests(unittest.TestCase):
    def setUp(self): self.cfg=dict(jmt.DEFAULTS,cloud_enabled=True)
    def ev(self,k,sid='raw',tid='turn',**kw): return {'session_id':sid,'turn_id':tid,'hook_event_name':k,**kw}
    def test_objective_latest_and_raw_sid(self):
        with tempfile.TemporaryDirectory() as t:
            seen=[]; states=[]; loader=lambda s: seen.append(s) or gf()
            a=lambda st,*x: states.append(st) or jmt.verdict('pass','ok',st); d=Path(t)
            jmt.hook(self.ev('UserPromptSubmit',prompt='Do not deploy'),self.cfg,d,a,loader); jmt.hook(self.ev('PreToolUse',tool_name='mcp__x',tool_input={'x':1}),self.cfg,d,a,loader)
            self.assertEqual(seen,['raw']); self.assertIn('ship safely',states[0]['goal']); self.assertIn('Do not deploy',states[0]['goal'])
    def test_malformed_vs_absent_pre_stop(self):
        for val,reason in [({'schema':1},'malformed_context'),({'status':'absent'},'missing_turn_context')]:
            with tempfile.TemporaryDirectory() as t:
                d=Path(t); calls=[]; a=lambda *x: calls.append(1) or jmt.verdict('pass','x',{})
                jmt.hook(self.ev('UserPromptSubmit',prompt='goal'),self.cfg,d,a,lambda s,val=val:val)
                for k in ('PreToolUse','Stop'):
                    out=jmt.hook(self.ev(k,tool_name='Bash',tool_input={'command':'pwd'}),self.cfg,d,a,lambda s,val=val:val)
                    if val.get('status') == 'absent': self.assertEqual(calls, [1, 1] if k == 'Stop' else [1])
                    else: self.assertFalse(calls); self.assertIn(reason,str(out))
    def test_bad_inputs_no_reserve(self):
        cases=[('unknown',{},'unsupported_tool'),('write_stdin',{},'uncovered_continuation'),('Bash',{'cmd':4},'malformed_tool_arguments'),('Bash',{'command':'x'*jmt.MAX_STATE},'state_bound')]
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); jmt.hook(self.ev('UserPromptSubmit',prompt='goal'),self.cfg,d,lambda *x:None,lambda s:gf())
            for n,args,r in cases:
                out=jmt.hook(self.ev('PreToolUse',tool_name=n,tool_input=args),self.cfg,d,lambda *x: (_ for _ in()).throw(AssertionError()),lambda s:gf()); self.assertIn(r,str(out))
    def test_cli_directory_and_receipt_tail(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)/'justmytype'; d.mkdir(); root=d.parent/'the-graphfather-the-graphfather'; root.mkdir(); binary=root/('the-graphfather.exe' if os.name == 'nt' else 'the-graphfather'); binary.write_text('#!/bin/sh\n'); binary.chmod(0o755)
            with patch.object(jmt,'subprocess') as sp:
                sp.run.return_value=type('P',(),{'stdout':b'{"status":"absent"}','returncode':0})(); jmt.graphfather_context('raw',d); self.assertIn(str(d.parent/'the-graphfather-the-graphfather'),sp.run.call_args.args[0])
            r=jmt.tool_receipt({'exit_code':3,'stdout':'a'*3000+'TAIL'},{'command':'x'},900); self.assertIn('exit_code',r); self.assertIn('TAIL',r)
    def test_task_cap_failure_priority_and_same_action_replace(self):
        with tempfile.TemporaryDirectory() as t:
            db=jmt.StateStore(Path(t))
            for i in range(40): db.task_outcome('t',str(i),str(i),'head tail-END',i==0)
            rows=db.task_evidence('t',40); self.assertLessEqual(len(rows),32); self.assertTrue(any('tail-END' in x for x in rows)); db.close()
    def test_only_post_with_row_and_stop_generation_context(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); loader=lambda s:gf(s,'obj-'+s); seen=[]; a=lambda st,*x:seen.append(st) or jmt.verdict('pass','ok',st)
            jmt.hook(self.ev('PostToolUse',tool_name='Bash',tool_input={'command':'x'},tool_response={'exit_code':1}),self.cfg,d,a,loader)
            for sid in ('a','b'):
                jmt.hook(self.ev('UserPromptSubmit',sid=sid,prompt='goal'),self.cfg,d,a,loader); jmt.hook(self.ev('Stop',sid=sid,last_assistant_message='done'),self.cfg,d,a,loader)
            self.assertEqual(seen[-1]['task_context']['generation'],2); self.assertEqual(seen[-1]['task_context']['canonical_session'],'b')
            self.assertEqual(jmt.StateStore(d).db.execute('select count(*) from task_outcomes').fetchone()[0],0)

    def test_budget_and_unsupported_before_reserve(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); loader=lambda s:gf(); a=lambda st,*x:jmt.verdict('pass','ok',st)
            jmt.hook(self.ev('UserPromptSubmit',prompt='goal'),self.cfg,d,a,loader)
            for i in range(32): jmt.hook(self.ev('PreToolUse',tool_name='mcp__x',tool_input={'i':i}),self.cfg,d,a,loader)
            before=jmt.StateStore(d).get(jmt.digest('raw'),jmt.digest('turn'))['calls']; self.assertEqual(before,32)
            jmt.hook(self.ev('PreToolUse',tool_name='unsupported',tool_input={}),self.cfg,d,a,loader)
            after=jmt.StateStore(d).get(jmt.digest('raw'),jmt.digest('turn'))['calls']; self.assertEqual(after,32)

    def test_cross_turn_failure_survives_and_is_labeled(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t); loader=lambda s:gf(generation=2); a=lambda st,*x:jmt.verdict('pass','ok',st)
            jmt.hook(self.ev('UserPromptSubmit',tid='t1',prompt='goal'),self.cfg,d,a,loader)
            jmt.hook(self.ev('PostToolUse',tid='t1',tool_name='Bash',tool_input={'command':'failed-step'},tool_response={'exit_code':1,'stdout':'TAILMARKER'}),self.cfg,d,a,loader)
            for i in range(8): jmt.hook(self.ev('PostToolUse',tid='t1',tool_name='Bash',tool_input={'command':str(i)},tool_response={'exit_code':0}),self.cfg,d,a,loader)
            jmt.hook(self.ev('UserPromptSubmit',tid='t2',prompt='next'),self.cfg,d,a,loader)
            seen=[]; aa=lambda st,*x:seen.append(st) or jmt.verdict('pass','ok',st)
            jmt.hook(self.ev('PreToolUse',tid='t2',tool_name='mcp__x',tool_input={'x':1}),self.cfg,d,aa,loader)
            self.assertIn('TAILMARKER',str(seen[-1])); self.assertIn('failed-step',str(seen[-1]))
    def test_same_command_different_cwd_keeps_both_outcomes(self):
        with tempfile.TemporaryDirectory() as t:
            db=jmt.StateStore(Path(t))
            db.task_outcome('task', jmt.digest({'tool':'Bash','arguments':{'command':'npm test'},'cwd':'/one'}), '1', 'one', True)
            db.task_outcome('task', jmt.digest({'tool':'Bash','arguments':{'command':'npm test'},'cwd':'/two'}), '1', 'two', False)
            rows=db.task_evidence('task', current_generation=1)
            self.assertEqual(len(rows), 2); self.assertIn('one', rows[0]); self.assertIn('two', rows[1]); db.close()

if __name__=='__main__': unittest.main()
