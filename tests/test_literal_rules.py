import copy
import unittest
from test_bindings import jmt,state,transport,choice,CFG

class LiteralRulesTests(unittest.TestCase):
    def test_prefix_currency_exact_literal(self):
        for currency in ['EUR','GBP','USD','CAD']:
            found=jmt.bindings.boundaries(f'Above {currency} 347.83 needs approval.')
            self.assertEqual(len(found),1)
            self.assertEqual((found[0]['value'],found[0]['unit'],found[0]['currency']),('347.83','money',currency))
            self.assertEqual(found[0]['span'],currency+' 347.83')

    def test_nested_currency_binding(self):
        s=state(1,rule='Above EUR 347.83 requires approval.')
        s['action']['arguments']={'payment':{'amount_cents':34784,'currency':'EUR'}}
        gates=jmt.bindings.prepare(s,jmt.POLICY['bindings'])
        self.assertEqual(len(gates),1)
        self.assertEqual(gates[0]['fields']['f0']['path'],['payment','amount_cents'])
        self.assertEqual(jmt.evaluate(s,CFG,transport)['decision'],'block')

    def test_known_cross_currency_is_not_converted(self):
        s=state(1,rule='Above EUR 347.83 requires approval.')
        s['action']['arguments']={'payment':{'amount_cents':50000,'currency':'GBP'}}
        self.assertEqual(jmt.bindings.prepare(s,jmt.POLICY['bindings']),[])

    def test_required_date_condition_is_inverted_in_code(self):
        for value,wanted in [('2026-08-22','pass'),('2026-08-23','block'),('2026-08-24','block')]:
            s=state(rule='Remove only when retention_end is before 2026-08-23.')
            s['action']['arguments']={'retention_end':value}
            def fake(p):
                out=transport(p,op='lt',unmet=0)
                if 'n0_polarity' in p['questions']:out['answers']['n0_polarity']=choice(p['questions']['n0_polarity'],'required')
                return out
            with self.subTest(value=value):
                result=jmt.evaluate(s,CFG,fake)
                self.assertEqual(result['decision'],wanted)
                self.assertEqual(result['rule_checks'][0]['comparison']['operator'],'ge')
                self.assertEqual(result['rule_checks'][0]['literal_operator'],'lt')

    def test_uncertain_polarity_never_blocks_or_clears(self):
        def fake(p):
            out=transport(p)
            if 'n0_polarity' in p['questions']:out['answers']['n0_polarity']=choice(p['questions']['n0_polarity'],'restricted',.6)
            return out
        out=jmt.evaluate(state(),CFG,fake)
        self.assertFalse(out['rule_checks'][0]['enforced'])
        self.assertIsNone(out['rule_checks'][0]['resolved_without_violation'])

    def test_independent_atomic_question_contains_its_rule(self):
        s=state();blocks=jmt.bindings.rule_blocks(s)
        _,qs=jmt.bindings.atomic_request(blocks,s,jmt.POLICY['rules'])
        self.assertIn(blocks[1]['text'],qs['r1']['instructions']['question'])

    def test_exact_strict_equality_needs_no_approval(self):
        s=state(34783,rule='Payments exceeding GBP 347.83 need approval.')
        s['action']['arguments']['currency']='GBP'
        out=jmt.evaluate(s,CFG,transport)
        self.assertEqual(out['decision'],'pass')
        self.assertFalse(out['rule_checks'][0]['comparison']['restricted_range'])
