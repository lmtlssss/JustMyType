import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'plugins/justmytype/scripts/jmt.py'
spec = importlib.util.spec_from_file_location('jmt', PATH)
jmt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jmt)


def state(command='touch output.txt', tool='Bash'):
    return {'goal': 'Create the local output.', 'action': {'tool': tool, 'arguments': {'command': command}}, 'evidence': [], 'constraints': []}


def response(payload, p=.01, support='supported'):
    answers = {}
    for key, question in payload['questions'].items():
        if question['type'] == 'noul':
            answers[key] = {'type': 'noul', 'noul': p}
        elif key == 'support':
            answers[key] = {'type': 'choice', 'choice': support, 'probabilities': {x: .97 if x == support else .01 for x in question['criteria']}, 'confidence': .95}
        else:
            # The new contract has one categorical result per instruction.
            answers[key] = {'type':'choice','choice':'satisfied','confidence':.99,
                            'probabilities':{x:.99 if x=='satisfied' else .01/3 for x in question['criteria']}}
    return {'model': jmt.MODEL, 'answers': answers, 'usage': {'input_tokens': 300, 'output_tokens': 21}}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.cfg = dict(jmt.DEFAULTS, cloud_enabled=True, mode='guard')
        self.event = {'session_id': 'test-session', 'turn_id': 'test-turn'}

    def call(self, kind, **kw):
        return jmt.hook(self.event | {'hook_event_name': kind} | kw, self.cfg, self.data, self.assessor)

    @staticmethod
    def assessor(s, cfg, directory, mode):
        return jmt.evaluate(s, cfg, lambda p: response(p, .99, 'contradicted'), mode)

    def prompt(self):
        self.call('UserPromptSubmit', prompt='Do not modify protected.txt. You may create allowed.txt.')

    def test_real_api_contract_not_custom_decision_payload(self):
        captured = []
        def transport(payload):
            captured.append(payload)
            return response(payload)
        result = jmt.evaluate(state(), self.cfg, transport)
        self.assertEqual(result['decision'], 'pass')
        self.assertEqual(set(captured[0]), {'state', 'questions', 'model'})
        self.assertEqual(result['usage']['input_tokens'], 300)
        self.assertEqual(result['model'], 'jev-1.13.0')

    def test_high_probability_blocks(self):
        result = jmt.evaluate(state(), self.cfg, lambda p: response(p, .99))
        self.assertEqual(result['decision'], 'block')

    def test_middle_probability_reviews(self):
        self.assertEqual(jmt.evaluate(state(), self.cfg, lambda p: response(p, .6))['decision'], 'review')

    def test_cloud_off_never_calls_network(self):
        with patch.object(jmt, 'request_api', side_effect=AssertionError('network')):
            self.assertEqual(jmt.evaluate(state(), jmt.DEFAULTS)['decision'], 'unassessed')

    def test_literal_read_has_no_provider_score(self):
        s = state('git status --short'); s['goal'] = 'Show git status --short.'
        out = jmt.evaluate(s, jmt.DEFAULTS)
        self.assertEqual(out['decision'], 'pass')
        self.assertEqual(out['probabilities'], {})
        self.assertIsNone(out['model'])

    def test_goal_limit_cannot_use_literal_read_bypass(self):
        s = state('git status')
        s['goal'] = 'Do not run Git commands. Explain the plan without using Git.'
        seen = []
        def transport(payload):
            seen.append(payload)
            return response(payload, .99)
        result = jmt.evaluate(s, self.cfg, transport)
        self.assertEqual(result['decision'], 'block')
        self.assertEqual(len(seen), 1)
        self.assertFalse(jmt.literal_authorized(s, self.cfg))

    def test_native_goal_limit_calls_semantic_check(self):
        self.call('UserPromptSubmit', prompt='Do not run Git commands. Explain only.')
        out = self.call('PreToolUse', tool_name='Bash', tool_input={'command': 'git status'})
        self.assertEqual(out['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_positive_goal_with_extra_limit_does_not_bypass(self):
        s = state('pwd'); s['goal'] = 'Print the current directory. Actually, use no tools.'
        self.assertFalse(jmt.literal_authorized(s, self.cfg))

    def test_compound_read_does_not_bypass(self):
        for cmd in ['pwd; rm x', 'git status > x', 'pwd $(touch x)', 'git status\ntouch x', 'git -c core.pager=bad status', 'git status | sh']:
            with self.subTest(cmd=cmd):
                self.assertFalse(jmt.readonly(state(cmd)['action']))

    def test_constraints_disable_read_fast_path(self):
        cfg = dict(self.cfg, constraints=['Do not read status.'])
        self.assertEqual(jmt.evaluate(state('git status'), cfg, lambda p: response(p, .99))['decision'], 'block')

    def test_unknown_tool_abstains(self):
        self.assertEqual(jmt.evaluate(state(tool='new_unknown_tool'), self.cfg)['reason_codes'], ['unsupported_tool'])

    def test_native_patch_and_mcp(self):
        for tool in ['apply_patch', 'mcp__filesystem__write_file', 'exec_command']:
            with self.subTest(tool=tool):
                self.assertEqual(jmt.evaluate(state(tool=tool), self.cfg, response)['decision'], 'pass')

    def test_missing_command_abstains(self):
        s = state(); s['action']['arguments'] = {}
        self.assertEqual(jmt.evaluate(s, self.cfg, response)['decision'], 'unassessed')

    def test_no_goal_abstains(self):
        s = state(); s['goal'] = ''
        self.assertEqual(jmt.evaluate(s, self.cfg, response)['decision'], 'unassessed')

    def test_bad_input_shapes(self):
        for x in [None, [], 'hello', {}, {'goal': 'x', 'action': []}]:
            with self.subTest(x=x):
                self.assertEqual(jmt.evaluate(x, self.cfg, response)['decision'], 'unassessed')

    def test_no_silent_partial_state(self):
        s = state(); s['goal'] = 'x' * 40000
        self.assertEqual(jmt.evaluate(s, self.cfg, response)['reason_codes'], ['state_bound'])

    def test_invalid_probabilities_are_not_passes(self):
        for value in [True, float('nan'), float('inf'), -.1, 1.1, '0.8', None]:
            with self.subTest(value=value):
                self.assertEqual(jmt.evaluate(state(), self.cfg, lambda p: response(p, value))['decision'], 'unassessed')

    def test_wrong_model_is_not_a_pass(self):
        def bad(p):
            out = response(p); out['model'] = 'other'; return out
        self.assertEqual(jmt.evaluate(state(), self.cfg, bad)['decision'], 'unassessed')

    def test_missing_answer_is_not_a_pass(self):
        def bad(p):
            out = response(p); out['answers'].pop('r0'); return out
        self.assertEqual(jmt.evaluate(state(), self.cfg, bad)['decision'], 'unassessed')

    def test_invalid_usage_is_not_a_pass(self):
        def bad(p):
            out = response(p); out['usage']['input_tokens'] = True; return out
        self.assertEqual(jmt.evaluate(state(), self.cfg, bad)['decision'], 'unassessed')

    def test_provider_exception_body_never_echoed(self):
        def fail(p):
            raise RuntimeError('do-not-publish-this-body')
        out = jmt.evaluate(state(), self.cfg, fail)
        self.assertNotIn('do-not-publish', json.dumps(out))
        self.assertEqual(out['decision'], 'unassessed')

    def test_verify_contradicted_supported_and_missing(self):
        s = {'claim': 'The deployment passed.', 'evidence': ['health check failed']}
        for choice, decision in [('supported', 'pass'), ('contradicted', 'block'), ('insufficient', 'review'), ('no_claim', 'pass')]:
            with self.subTest(choice=choice):
                self.assertEqual(jmt.evaluate(s, self.cfg, lambda p: response(p, support=choice), 'verify')['decision'], decision)

    def test_invalid_choice_distribution_abstains(self):
        def bad(p):
            out = response(p); out['answers']['support']['probabilities']['supported'] = .1; return out
        self.assertEqual(jmt.evaluate({'claim': 'done', 'evidence': []}, self.cfg, bad, 'verify')['decision'], 'unassessed')

    def test_redaction_before_network(self):
        s = state('echo token=synthetic-credential')
        seen = []
        def transport(p):
            seen.append(json.dumps(p)); return response(p)
        jmt.evaluate(s, self.cfg, transport)
        self.assertNotIn('synthetic-credential', seen[0])

    def test_redaction_private_key_bearer_and_nested(self):
        x = {'password': 'a test value', 'body': 'Bearer syntheticBearerValue', 'more': '-----BEGIN PRIVATE KEY-----\nTEST\n-----END PRIVATE KEY-----'}
        s = json.dumps(jmt.redact(x))
        self.assertNotIn('a test value', s)
        self.assertNotIn('syntheticBearerValue', s)
        self.assertNotIn('TEST', s)

    def test_usage_metadata_is_not_redacted(self):
        self.assertEqual(jmt.redact({'input_tokens': 300, 'api_key_present': True}), {'input_tokens': 300, 'api_key_present': True})

    def test_redirect_refused(self):
        with self.assertRaises(ValueError):
            jmt.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://elsewhere.invalid')

    def test_session_start_schema(self):
        out = self.call('SessionStart')
        self.assertEqual(out['hookSpecificOutput']['hookEventName'], 'SessionStart')

    def test_native_deny_schema(self):
        self.prompt()
        out = self.call('PreToolUse', tool_name='Bash', tool_input={'command': 'touch protected.txt'})
        specific = out['hookSpecificOutput']
        self.assertEqual(specific['hookEventName'], 'PreToolUse')
        self.assertEqual(specific['permissionDecision'], 'deny')
        self.assertTrue(specific['permissionDecisionReason'])
        self.assertNotIn('updatedInput', specific)

    def test_observe_does_not_deny_semantic_block(self):
        self.cfg['mode'] = 'observe'; self.prompt()
        out = self.call('PreToolUse', tool_name='Bash', tool_input={'command': 'touch protected.txt'})
        self.assertNotIn('permissionDecision', out['hookSpecificOutput'])

    def test_missing_identity_is_explicit(self):
        out = jmt.hook({'hook_event_name': 'PreToolUse'}, self.cfg, self.data)
        self.assertIn('identity', out['systemMessage'])

    def test_same_cwd_does_not_merge_sessions(self):
        self.prompt()
        self.event['session_id'] = 'different-session'
        out = self.call('PreToolUse', tool_name='Bash', tool_input={'command': 'touch x'})
        self.assertIn('missing_turn_context', json.dumps(out))

    def test_new_turn_does_not_reuse_evidence(self):
        self.prompt(); self.event['turn_id'] = 'next-turn'
        out = self.call('PreToolUse', tool_name='Bash', tool_input={'command': 'touch x'})
        self.assertIn('missing_turn_context', json.dumps(out))

    def test_long_receipt_retains_result_tail_and_exit_status(self):
        raw = {'output': 'source listing\n' * 1200 + 'CHECKS: 4096; FAILURES: 4091', 'exit_code': 1}
        text = jmt.tool_receipt(raw, {'cmd': 'cat source.py && python3 validate.py'})
        self.assertLessEqual(len(text), 2500)
        self.assertIn('FAILURES: 4091', text)
        self.assertIn('"exit_code":1', text)
        self.assertIn('python3 validate.py', text)
        self.assertIn('INCOMPLETE OBSERVATION', text)

    def test_receipt_does_not_mistake_source_prefix_for_full_result(self):
        raw = {'output': 'assert result == True\n' * 1000 + 'ACTUAL: FAILED', 'exit_code': 1}
        text = jmt.tool_receipt(raw, {})
        self.assertIn('ACTUAL: FAILED', text)
        self.assertIn('OUTPUT MIDDLE OMITTED', text)

    def test_receipt_redacts_before_head_tail_selection(self):
        text = jmt.tool_receipt({'output': 'x' * 6000 + 'password=synthetic-private-value', 'exit_code': 1}, {})
        self.assertNotIn('synthetic-private-value', text)
        self.assertIn('Credential-shaped', text)

    def test_long_command_receipt_keeps_both_ends(self):
        text = jmt.tool_receipt({'output': 'result', 'exit_code': 0}, {'command':'BEGIN ' + 'x' * 3000 + ' FINAL'})
        self.assertIn('BEGIN ', text)
        self.assertIn(' FINAL', text)
        self.assertIn('COMMAND MIDDLE OMITTED', text)

    def test_posttool_retains_multiple_original_results(self):
        self.prompt()
        for i in range(3):
            self.call('PostToolUse', tool_name='Bash', tool_response={'exit_code': i, 'text': str(i)})
        db = jmt.StateStore(self.data)
        try:
            row = db.get(jmt.digest('test-session'), jmt.digest('test-turn'))
            self.assertEqual(len(row['evidence']), 3)
            self.assertIn('"exit_code":2', row['evidence'][2])
        finally:
            db.close()

    def test_posttool_does_not_replace_original_result(self):
        self.prompt()
        out = self.call('PostToolUse', tool_name='Bash', tool_response={'exit_code': 1, 'text': 'failed'})
        self.assertNotIn('decision', out)
        self.assertNotIn('continue', out)
        self.assertEqual(out['hookSpecificOutput']['hookEventName'], 'PostToolUse')

    def test_receipt_omits_secret_bearing_output(self):
        self.prompt()
        self.call('PostToolUse', tool_name='Bash', tool_response={'text': 'password=synthetic-only'})
        self.assertNotIn(b'synthetic-only', (self.data/'state.sqlite3').read_bytes())

    def test_receipts_are_bounded(self):
        self.prompt()
        for i in range(10): self.call('PostToolUse', tool_name='Bash', tool_response={'text': str(i)})
        db = jmt.StateStore(self.data)
        try: self.assertEqual(len(db.get(jmt.digest('test-session'), jmt.digest('test-turn'))['evidence']), 6)
        finally: db.close()

    def test_stop_correction_only_once(self):
        self.prompt()
        first = self.call('Stop', last_assistant_message='All done.')
        second = self.call('Stop', last_assistant_message='All done.')
        self.assertEqual(first['decision'], 'block')
        self.assertEqual(second, {})

    def test_stop_active_shortcircuits(self):
        self.prompt()
        self.assertEqual(self.call('Stop', stop_hook_active=True, last_assistant_message='Done'), {})

    def test_turn_budget_is_atomic(self):
        self.prompt()
        def reserve(i):
            db = jmt.StateStore(self.data)
            try: return db.reserve(jmt.digest('test-session'), jmt.digest('test-turn'), 3)
            finally: db.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(reserve, range(10))), 3)

    def test_credential_runner_forwards_only_assessment_input(self):
        cfg = dict(self.cfg, credential_runner=['test-loader', '--'])
        jmt.save_config(self.data, cfg)
        expected = jmt.verdict('pass', 'no_conflict_detected', {})
        with patch.dict(os.environ, {'JMT_CREDENTIAL_CHILD': ''}):
            old = os.environ.pop('TYPESAFE_API_KEY', None)
            try:
                with patch.object(jmt.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(expected).encode())) as run:
                    out = jmt.assess(state(), cfg, self.data)
                    self.assertEqual(out['decision'], 'pass')
                    self.assertEqual(json.loads(run.call_args.kwargs['input']), state())
                    self.assertEqual(run.call_args.args[0][:2], ['test-loader', '--'])
            finally:
                if old is not None: os.environ['TYPESAFE_API_KEY'] = old

    def test_cli_guard_never_executes_unassessed(self):
        marker = self.data/'must-not-exist'
        result = subprocess.run([sys.executable, str(PATH), '--data-dir', str(self.data), 'guard', '--goal', 'Create a test file.', '--', sys.executable, '-c', 'from pathlib import Path;Path('+repr(str(marker))+').touch()'], capture_output=True)
        self.assertEqual(result.returncode, 3)
        self.assertFalse(marker.exists())

    def test_config_path_is_same_for_cli_and_hooks(self):
        with patch.dict(os.environ, {'JMT_DATA_DIR': str(self.data), 'PLUGIN_DATA': str(self.data)}):
            self.assertEqual(jmt.data_dir(), self.data.resolve())
            jmt.save_config(self.data, self.cfg)
            self.assertEqual(jmt.load_config()['mode'], 'guard')

    def test_invalid_user_config_does_not_become_default_pass(self):
        (self.data/'config.json').write_text('{broken', encoding='utf-8')
        with self.assertRaises(ValueError): jmt.load_config(self.data)

if __name__ == '__main__': unittest.main()
