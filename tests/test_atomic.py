"""Offline composition contracts; these do not measure Jev accuracy."""
import copy
import unittest
from test_bindings import jmt, state, transport, choice, CFG

class AtomicTests(unittest.TestCase):
    def test_exact_equality_clears_only_that_numeric_rule(self):
        requests=[]
        def fake(payload):requests.append(payload);return transport(payload)
        result=jmt.evaluate(state(10000),CFG,fake)
        self.assertEqual(result['decision'],'pass')
        last=requests[-1]['state']
        self.assertEqual([r['text'] for r in last['instructions']],[state()['goal']])
        self.assertEqual(result['rule_checks'][0]['resolved_without_violation'],'numeric_condition_false')
        self.assertEqual(result['api_requests'],3)

    def test_mixed_obligation_cannot_be_removed(self):
        def fake(payload):
            result=transport(payload)
            if 'n0_shape' in payload['questions']:
                result['answers']['n0_shape']=choice(payload['questions']['n0_shape'],'mixed_or_other')
            if 'r1' in payload['questions']:
                result['answers']['r1']=choice(payload['questions']['r1'],'violated')
            return result
        s=state(8000,rule='Hold refunds above $100 for review and preserve the original receipt.')
        result=jmt.evaluate(s,CFG,fake)
        self.assertEqual(result['decision'],'block')
        self.assertIsNone(result['rule_checks'][0]['resolved_without_violation'])
        self.assertIn('instruction_conflict',result['reason_codes'])

    def test_different_requirement_still_blocks_after_clearing_bound(self):
        s=state(8000);s['constraints'].append('Never close a request without a receipt.')
        def fake(p):
            r=transport(p)
            if 'r1' in p['questions']:r['answers']['r1']=choice(p['questions']['r1'],'violated')
            return r
        out=jmt.evaluate(s,CFG,fake)
        self.assertEqual(out['decision'],'block')
        self.assertEqual(out['instruction_checks'][-1]['text'],s['constraints'][-1])

    def test_missing_shape_response_is_not_a_pass(self):
        def fake(p):
            r=transport(p)
            if 'n0_shape' in r['answers']:del r['answers']['n0_shape']
            return r
        out=jmt.evaluate(state(8000),CFG,fake)
        self.assertEqual(out['decision'],'unassessed')
        self.assertFalse(out['assessment_complete'])

    def test_low_binding_confidence_cannot_clear(self):
        def fake(p):
            r=transport(p)
            if 'n0_field' in p['questions']:r['answers']['n0_field']=choice(p['questions']['n0_field'],'f0',.6)
            return r
        out=jmt.evaluate(state(8000),CFG,fake)
        self.assertIsNone(out['rule_checks'][0]['resolved_without_violation'])
        self.assertEqual(len(out['instruction_checks']),2)

    def test_preview_is_not_numeric_execution(self):
        out=jmt.evaluate(state(15000),CFG,lambda p:transport(p,effect='preview_or_read'))
        self.assertEqual(out['decision'],'pass')
        self.assertEqual(out['rule_checks'][0]['resolved_without_violation'],'effect_not_performed')

    def test_semantic_violation_without_numeric_field_blocks(self):
        s=state();s['action']={'tool':'Bash','arguments':{'command':'git status'}};s['goal']='Do not use Git.';s['constraints']=[]
        def fake(p):
            r=transport(p);r['answers']['r0']=choice(p['questions']['r0'],'violated');return r
        out=jmt.evaluate(s,CFG,fake)
        self.assertEqual(out['decision'],'block')
        self.assertEqual(out['api_requests'],1)

    def test_unknown_is_review_not_pass_or_block(self):
        s=state();s['action']={'tool':'Bash','arguments':{'command':'read_only_probe'}};s['constraints']=[]
        def fake(p):
            r=transport(p);r['answers']['r0']=choice(p['questions']['r0'],'unknown');return r
        self.assertEqual(jmt.evaluate(s,CFG,fake)['decision'],'review')

    def test_many_independent_rules_share_one_api_request(self):
        s=state();s['action']={'tool':'Bash','arguments':{'command':'test_runner'}};s['constraints']=['Keep each original source.','Do not publish yet.']
        seen=[]
        def fake(p):seen.append(p);return transport(p)
        out=jmt.evaluate(s,CFG,fake)
        self.assertEqual(out['api_requests'],1)
        self.assertEqual(len(out['instruction_checks']),3)
        self.assertEqual(set(seen[0]['questions']),{'r0','r1','r2','irreversible_without_basis','failed_candidate'})
        self.assertNotIn('scope_conflict',seen[0]['questions'])

    def test_too_many_rules_abstains(self):
        s=state();s['constraints']=['Independent rule.']*32
        out=jmt.evaluate(s,CFG,lambda p:self.fail('network should not run'))
        self.assertEqual(out['decision'],'unassessed')
        self.assertEqual(out['reason_codes'],['instruction_count_bound'])

    def test_numeric_block_is_not_reported_as_all_rules_checked(self):
        out=jmt.evaluate(state(),CFG,transport)
        self.assertEqual(out['decision'],'block')
        self.assertTrue(out['short_circuit'])
        self.assertEqual(out['instruction_checks'],[])
        self.assertEqual(out['api_requests'],2)
