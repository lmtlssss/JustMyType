"""Offline contract tests. They are not measurements of model accuracy."""
import copy
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'plugins/justmytype/scripts/jmt.py'
spec=importlib.util.spec_from_file_location('binding_runtime',p);jmt=importlib.util.module_from_spec(spec);spec.loader.exec_module(jmt)
b=jmt.bindings;settings=jmt.POLICY['bindings']
CFG=dict(jmt.DEFAULTS,cloud_enabled=True,mode='guard')

def state(value=10001,rule='Hold refunds above $100 for review.',tool='mcp__billing__refund',key='amount_cents'):
    return {'goal':'Process the authorized task under the stated limits.','constraints':[rule],
            'action':{'tool':tool,'arguments':{key:value}},'evidence':['The tool commits the specified effect now. No approval has been granted.']}

def choice(question,label,p=.99):
    others=[k for k in question['criteria'] if k!=label]
    return {'type':'choice','choice':label,'confidence':p,'probabilities':{k:(p if k==label else (1-p)/len(others)) for k in question['criteria']}}

def transport(payload,op='gt',effect='execute',unmet=.99,general=.01,field='f0'):
    answers={}
    for name,q in payload['questions'].items():
        if q['type']=='noul':answers[name]={'type':'noul','noul':unmet if name=='n0_unmet' else general}
        else:answers[name]=choice(q,'active' if name.startswith('a') else field if name=='n0_field' else op if name=='n0_operator' else effect)
    return {'model':jmt.MODEL,'answers':answers,'usage':{'input_tokens':100,'output_tokens':10}}

class BindingTests(unittest.TestCase):
    def test_cents_compare_in_code(self):
        r=jmt.evaluate(state(),CFG,transport)
        self.assertEqual(r['decision'],'block')
        self.assertEqual(r['rule_checks'][0]['comparison']['left'],'100.01')
        self.assertEqual(r['probabilities']['scope_conflict'],.01)

    def test_equality_is_not_above(self):
        self.assertEqual(jmt.evaluate(state(10000),CFG,transport)['decision'],'pass')

    def test_one_cent_below(self):
        self.assertEqual(jmt.evaluate(state(9999),CFG,transport)['decision'],'pass')

    def test_all_closed_operators(self):
        for op,amount,expected in [('ge',10000,'block'),('lt',9999,'block'),('le',10000,'block'),('ne',10000,'pass'),('eq',10000,'block')]:
            with self.subTest(op=op):self.assertEqual(jmt.evaluate(state(amount),CFG,lambda p:transport(p,op=op))['decision'],expected)

    def test_preview_above_limit_is_not_numeric_block(self):
        self.assertEqual(jmt.evaluate(state(),CFG,lambda p:transport(p,effect='preview_or_read'))['decision'],'pass')

    def test_deferred_action_does_not_pay(self):
        self.assertEqual(jmt.evaluate(state(),CFG,lambda p:transport(p,effect='defer_or_refuse'))['decision'],'pass')

    def test_unrelated_effect_does_not_trigger(self):
        self.assertEqual(jmt.evaluate(state(),CFG,lambda p:transport(p,effect='unrelated'))['decision'],'pass')

    def test_approval_satisfied_does_not_trigger(self):
        self.assertEqual(jmt.evaluate(state(),CFG,lambda p:transport(p,unmet=.01))['decision'],'pass')

    def test_unknown_operator_and_field_do_not_trigger(self):
        self.assertEqual(jmt.evaluate(state(),CFG,lambda p:transport(p,op='none'))['decision'],'pass')
        self.assertEqual(jmt.evaluate(state(),CFG,lambda p:transport(p,field='none'))['decision'],'pass')

    def test_probabilities_below_binding_gate_do_not_trigger(self):
        def low(payload):
            r=transport(payload)
            if 'n0_field' in r['answers']:r['answers']['n0_field']=choice(payload['questions']['n0_field'],'f0',.7)
            return r
        self.assertEqual(jmt.evaluate(state(),CFG,low)['decision'],'pass')

    def test_rule_and_general_context_remain_separate(self):
        payloads=[]
        def collect(p):payloads.append(p);return transport(p)
        jmt.evaluate(state(),CFG,collect)
        self.assertEqual(len(payloads),3)
        general=next(p for p in payloads if 'scope_conflict' in p['questions'])
        self.assertEqual(general['state'],state())
        self.assertNotIn('numeric_rules',general['state'])

    def test_network_queries_run_concurrently(self):
        # All three queries must enter before any may finish. This proves overlap
        # without treating a shared CI runner's scheduling delay as engine latency.
        from threading import Barrier, Lock, get_ident
        barrier=Barrier(3, timeout=3)
        lock=Lock();threads=set()
        def synchronized(payload):
            with lock: threads.add(get_ident())
            barrier.wait()
            return transport(payload)
        result=jmt.evaluate(state(),CFG,synchronized)
        self.assertEqual(len(threads),3)
        self.assertEqual(result['api_requests'],3)
        self.assertTrue(result['assessment_complete'])
        self.assertEqual(result['decision'],'block')

    def test_supplement_failure_preserves_proven_general_block(self):
        def fail(p):
            if 'n0_field' in p['questions']:raise ValueError('never echo this')
            return transport(p,general=.99)
        r=jmt.evaluate(state(),CFG,fail)
        self.assertEqual(r['decision'],'block');self.assertFalse(r['assessment_complete'])
        self.assertNotIn('never echo',json.dumps(r))

    def test_general_failure_preserves_proven_numeric_block(self):
        def fail(p):
            if 'scope_conflict' in p['questions']:raise ValueError('provider')
            return transport(p)
        self.assertEqual(jmt.evaluate(state(),CFG,fail)['decision'],'block')

    def test_incomplete_checks_cannot_report_pass(self):
        def fail(p):
            if 'n0_field' in p['questions']:raise ValueError('provider')
            return transport(p)
        self.assertEqual(jmt.evaluate(state(5000),CFG,fail)['decision'],'unassessed')

    def test_budget_deadline_refuses_expired_query(self):
        with patch.dict(jmt.os.environ,{'TYPESAFE_API_KEY':'synthetic-placeholder'}):
            with self.assertRaises(TimeoutError):jmt.request_api({},jmt.POLICY['questions'],deadline=time.monotonic()-1)

    def test_date_value_and_boundary_are_calendar_dates(self):
        r=jmt.evaluate(state('2026-11-01','Do not schedule publication before 2026-11-02.',key='publication_date'),CFG,lambda p:transport(p,op='lt'))
        self.assertEqual(r['decision'],'block');self.assertEqual(r['rule_checks'][0]['comparison']['unit'],'date')

    def test_nested_field_paths_are_real(self):
        s=state();s['action']['arguments']={'transfer':{'amount_cents':20000}}
        self.assertEqual(jmt.evaluate(s,CFG,transport)['rule_checks'][0]['field'],['transfer','amount_cents'])

    def test_native_literal_flags_bind(self):
        s=state(tool='Bash');s['action']['arguments']={'command':'demo-pay --amount-cents 10001'}
        self.assertEqual(jmt.evaluate(s,CFG,transport)['decision'],'block')

    def test_native_argv_binds(self):
        s=state(tool='exec_argv');s['action']['arguments']={'argv':['demo-pay','--amount-cents=10001']}
        self.assertEqual(jmt.evaluate(s,CFG,transport)['decision'],'block')

    def test_compound_command_is_not_literal_flag_binding(self):
        s=state(tool='Bash');s['action']['arguments']={'command':'echo example; demo-pay --amount-cents 10001'}
        self.assertEqual(b.prepare(s,settings),[])

    def test_repeated_flag_is_ambiguous(self):
        s=state(tool='Bash');s['action']['arguments']={'command':'demo-pay --amount-cents 3 --amount-cents 20000'}
        self.assertEqual(b.prepare(s,settings),[])

    def test_no_aggregate_claim_from_array(self):
        s=state();s['action']['arguments']={'payments':[{'amount_cents':20000}]}
        self.assertEqual(b.prepare(s,settings),[])

    def test_many_fields_abstain_not_truncate(self):
        s=state();s['action']['arguments']={f'field_{i}':i for i in range(17)}
        self.assertEqual(jmt.evaluate(s,CFG,transport)['decision'],'unassessed')

    def test_nonfinite_bool_and_scientific_text_not_literal(self):
        for x in [True,False,float('inf'),float('nan'),'1e9',None]:self.assertIsNone(b.scalar(x))

    def test_decimal_does_not_round_60_digit_source(self):
        value=int('9'*50)
        s=state(value,rule='Hold refunds above $'+('9'*48)+'.98 for review.')
        r=jmt.evaluate(s,CFG,transport)
        self.assertEqual(r['decision'],'block')
        self.assertEqual(r['rule_checks'][0]['comparison']['left'],('9'*48)+'.99')

    def test_multiple_boundaries_use_general_fallback(self):
        self.assertEqual(b.prepare(state(rule='Refunds above $100 but below $200 require review.'),settings),[])

    def test_exception_continuation_kept_with_rule(self):
        gates=b.prepare(state(rule='Hold refunds above $100.\nExcept requests with recorded manager approval.'),settings)
        self.assertIn('Except',gates[0]['rule'])

    def test_explicit_cross_currency_not_converted(self):
        s=state(rule='Hold refunds above 100 EUR.');s['action']['arguments']['currency']='USD'
        self.assertEqual(b.prepare(s,settings),[])

    def test_later_waiver_disables_only_numeric_addition(self):
        def waived(p):
            r=transport(p)
            for name,q in p['questions'].items():
                if name.startswith('a'):r['answers'][name]=choice(q,'waived')
            return r
        self.assertEqual(jmt.evaluate(state(),CFG,waived)['decision'],'pass')

    def test_ambiguous_authority_cannot_create_a_block(self):
        def unclear(p):
            r=transport(p)
            for name,q in p['questions'].items():
                if name.startswith('a'):r['answers'][name]=choice(q,'active',.6)
            return r
        self.assertEqual(jmt.evaluate(state(),CFG,unclear)['decision'],'pass')

    def test_authority_failure_is_explicit(self):
        def fail(p):
            if 'a0' in p['questions']:raise ValueError('unavailable')
            return transport(p)
        r=jmt.evaluate(state(),CFG,fail)
        self.assertEqual(r['decision'],'unassessed')
        self.assertFalse(r['rule_checks'][0]['enforced'])

    def test_full_user_authority_not_proposal_permission(self):
        s=state();s['constraints'].append('Replace the previous limit with $175.')
        gates=b.prepare(s,settings);data,_=b.authority_request(gates,s,settings)
        self.assertEqual(data['user_instructions'],[s['goal']]+s['constraints'])
        self.assertNotIn('evidence',data)

    def test_currency_key_must_match_named_rule_currency(self):
        self.assertEqual(b.prepare(state(150,'Refunds above 100 EUR require review.',key='amount_usd'),settings),[])
        self.assertEqual(len(b.prepare(state(150,'Refunds above 100 EUR require review.',key='amount_eur'),settings)),1)

    def test_engine_identity_covers_new_module(self):
        self.assertEqual(len(jmt.ENGINE_SHA256),64)
        self.assertEqual(jmt.evaluate(state(),CFG,transport)['engine_sha256'],jmt.ENGINE_SHA256)

    def test_native_hook_denies_numeric_violation_with_exact_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);event={'session_id':'bound-proof','turn_id':'one'}
            jmt.hook(event|{'hook_event_name':'UserPromptSubmit','prompt':'Refund payments above $100 require review.'},CFG,data)
            def assess(s,c,d,mode):return jmt.evaluate(s,c,transport,mode)
            output=jmt.hook(event|{'hook_event_name':'PreToolUse','tool_name':'Bash','tool_input':{'command':'demo-pay --amount-cents 10001'}},CFG,data,assess)
            reason=output['hookSpecificOutput']['permissionDecisionReason']
            self.assertEqual(output['hookSpecificOutput']['permissionDecision'],'deny')
            self.assertIn('100.01',reason)
            self.assertNotIn('permissionDecision:allow',reason)

if __name__=='__main__':unittest.main()
