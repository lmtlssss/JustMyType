import contextlib
import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from test_task_context import gf, jmt


class HookEfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.cfg = dict(jmt.DEFAULTS, cloud_enabled=True, mode='guard')
        self.assessments = []
        self.reply = 'pass'
        self.call('UserPromptSubmit', prompt='Repair the runtime and verify the result.')

    def assess(self, state, cfg, directory, mode):
        self.assessments.append((state, mode))
        return jmt.verdict(self.reply, 'test_verdict', state)

    def call(self, kind, **fields):
        event = dict(session_id='efficiency-session', turn_id='efficiency-turn', hook_event_name=kind, **fields)
        return jmt.hook(event, self.cfg, self.directory, self.assess, lambda sid: gf())

    def command(self, text):
        return self.call('PreToolUse', tool_name='Bash', tool_input={'command': text})

    def calls_reserved(self):
        db = jmt.StateStore(self.directory)
        try:
            return db.get(jmt.digest('efficiency-session'), jmt.digest('efficiency-turn'))['calls']
        finally:
            db.close()

    def test_compound_reads_are_local(self):
        for command in ('pwd && ls | wc -l', 'cat README.md\nrg needle file',
                        'git status --short; git diff --stat', "sed -n '1,40p' file", 'cat file\n'):
            with self.subTest(command=command):
                self.assertTrue(jmt.routine_observation({'tool': 'Bash', 'arguments': {'command': command}}))

    def test_mixed_or_unsafe_commands_go_to_assessor(self):
        commands = ('cat file && rm file', 'cat file & rm file', 'cat $(touch bad)',
                    'cat $DYNAMIC', 'cat file > out', 'rg --pre hook needle',
                    'rg --hostname-bin=hook needle', "sed -n '1p' -e 'w out'",
                    "sed -n '1p' -i file", 'git diff --output=x',
                    'git show --ext-diff', 'git -c alias.a=bad status', 'sh -c pwd')
        for command in commands:
            with self.subTest(command=command):
                self.assertFalse(jmt.routine_observation({'tool': 'Bash', 'arguments': {'command': command}}))
                before = len(self.assessments)
                self.command(command)
                self.assertEqual(len(self.assessments), before + 1)

    def test_sixty_observations_leave_budget_for_change_and_claim(self):
        for _ in range(60):
            self.assertEqual(self.command('cat README.md; git status --short'), {})
        self.assertEqual(self.assessments, [])
        self.assertEqual(self.calls_reserved(), 0)
        self.command('touch artifact')
        self.call('Stop', last_assistant_message='The named result is verified.')
        self.assertEqual([mode for _, mode in self.assessments], ['check', 'verify'])
        self.assertEqual(self.calls_reserved(), 2)
        db = jmt.StateStore(self.directory)
        try:
            count = db.db.execute("SELECT count(*) FROM audit WHERE decision='unassessed' AND reasons='local_observation'").fetchone()[0]
            self.assertEqual(count, 60)
        finally:
            db.close()

    def test_formal_constraints_keep_the_assessment(self):
        self.cfg['constraints'] = ['Do not read the named private file.']
        self.reply = 'block'
        result = self.command('cat private-file')
        self.assertEqual(len(self.assessments), 1)
        self.assertEqual(result['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_restrictive_goals_keep_the_semantic_guard(self):
        self.reply = 'block'
        for prompt in ('Do not run Git commands. Explain only.', 'Use no tools.',
                       'Avoid reading private paths.', 'Inspect src only.',
                       'Wait until I finish.'):
            with self.subTest(prompt=prompt):
                self.call('UserPromptSubmit', prompt=prompt)
                before = len(self.assessments)
                result = self.command('git status --short')
                self.assertEqual(len(self.assessments), before + 1)
                self.assertEqual(result['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_reserved_stop_and_single_budget_notice(self):
        self.cfg['max_calls_per_turn'] = 4
        for i in range(3):
            self.command('touch artifact-' + str(i))
        results = [self.command('touch later') for _ in range(20)]
        self.assertIn('turn_budget_exhausted', str(results[0]))
        self.assertTrue(all(result == {} for result in results[1:]))
        self.assertEqual(self.calls_reserved(), 3)
        self.reply = 'block'
        stopped = self.call('Stop', last_assistant_message='Unproved completion claim.')
        self.assertEqual(stopped['decision'], 'block')
        self.assertEqual(len(self.assessments), 4)
        self.assertEqual(self.calls_reserved(), 4)
        db = jmt.StateStore(self.directory)
        try:
            count = db.db.execute("SELECT count(*) FROM audit WHERE reasons='turn_budget_exhausted' AND decision='unassessed'").fetchone()[0]
            self.assertEqual(count, 20)
        finally:
            db.close()

    def test_prompt_reset_clears_old_notice(self):
        self.cfg['max_calls_per_turn'] = 1
        self.assertIn('turn_budget_exhausted', str(self.command('touch later')))
        self.assertEqual(self.command('touch later'), {})
        self.call('UserPromptSubmit', prompt='A fresh bounded task.')
        self.assertIn('turn_budget_exhausted', str(self.command('touch later')))

    def test_large_binary_receipt_keeps_failure_without_a_model_call(self):
        marker = 'A' * 400000
        event = dict(session_id='efficiency-session', turn_id='efficiency-turn', hook_event_name='PostToolUse',
                     tool_name='view_image', tool_response={'exit_code': 1, 'stdout': 'ACTUAL FAILED', 'content': [
                         {'type': 'image', 'mimeType': 'image/png', 'data': marker},
                         {'type': 'audio', 'mimeType': 'audio/wav', 'data': marker},
                         {'image_url': 'data:image/png;base64,' + marker}]})
        raw = json.dumps(event).encode()
        self.assertGreater(len(raw), jmt.MAX_INPUT)
        with patch.object(jmt.sys, 'stdin', types.SimpleNamespace(buffer=io.BytesIO(raw))):
            parsed = jmt.read_json(limit=jmt.MAX_HOOK_INPUT)
        result = jmt.hook(parsed, self.cfg, self.directory, self.assess, lambda sid: gf())
        self.assertIn('failed', str(result))
        self.assertEqual(self.assessments, [])
        db = jmt.StateStore(self.directory)
        try:
            receipt = str(db.get(jmt.digest('efficiency-session'), jmt.digest('efficiency-turn'))['evidence'])
            self.assertIn('ACTUAL FAILED', receipt)
            self.assertIn('exit_code', receipt)
            self.assertIn('not visual evidence', receipt)
            self.assertNotIn('A' * 100, receipt)
        finally:
            db.close()

    def test_cli_input_bound_stays_unchanged(self):
        self.assertEqual(jmt.MAX_INPUT, 262144)
        with patch.object(jmt.sys, 'stdin', types.SimpleNamespace(buffer=io.BytesIO(b'x' * (jmt.MAX_INPUT + 1)))):
            with self.assertRaisesRegex(ValueError, '^input_bound$'):
                jmt.read_json()

    def test_oversized_hook_has_valid_specific_message(self):
        stdout = io.StringIO()
        with patch.object(jmt.sys, 'stdin', types.SimpleNamespace(buffer=io.BytesIO(b'x' * (jmt.MAX_HOOK_INPUT + 1)))), contextlib.redirect_stdout(stdout):
            code = jmt.main(['--data-dir', str(self.directory), 'hook'])
        result = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(set(result), {'systemMessage'})
        self.assertIn('hook_input_bound', result['systemMessage'])


if __name__ == '__main__':
    unittest.main()
