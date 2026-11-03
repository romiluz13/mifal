import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from test_cli import AGENT, PANE, Peer


CLI = Path(__file__).resolve().parents[1] / 'guard_send.py'
FRAMES = Path(__file__).parent / 'fixtures' / 'composers'


class GuardSendTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory(prefix='guard-send-', dir='/tmp')
        self.directory = Path(self.temp.name)
        self.peer = Peer(self.temp.name)
        self.agent = {**copy.deepcopy(AGENT), 'agent': 'codex', 'name': 'alpha'}
        self.pane = {**copy.deepcopy(PANE), 'agent': 'codex'}
        self.frame = (FRAMES / 'codex-hooks-need-review.txt').read_text()
        self.truncated = False
        self.read_pane = self.pane['pane_id']
        self.cli_failure = ''
        self.peer.reply = self.reply
        executable = self.directory / 'herdr'
        executable.write_text('#!' + sys.executable + '\n' + '''import json, os, sys
from pathlib import Path
root = Path(os.environ['GUARD_FIXTURE'])
args = sys.argv[1:]
with (root / 'calls.ndjson').open('a') as f: f.write(json.dumps(args) + '\\n')
state = json.loads((root / 'state.json').read_text())
if args[1] == state['cli_failure']: sys.exit(1)
if args[:2] == ['agent', 'prompt'] and state['cli_failure'] == 'undecodable':
    sys.stdout.buffer.write(bytes([255])); sys.exit(0)
if args[:2] == ['agent', 'prompt'] and state['cli_failure'] in ['agent_blocked', 'timeout']:
    print(json.dumps({'id': 'fixture', 'error': {'code': state['cli_failure'], 'message': 'blocked'}})); sys.exit(1)
if args[:2] == ['agent', 'prompt']:
    with (root / 'inputs.ndjson').open('a') as f: f.write(json.dumps(args) + '\\n')
if args[:2] == ['agent', 'get']: result = {'agent': state['agent']}
elif args[:2] == ['pane', 'get']: result = {'pane': state['pane']}
else: result = {'type': 'agent_prompted'}
print(json.dumps({'id': 'fixture', 'result': result}))
''')
        executable.chmod(0o700)

    def tearDown(self):
        self.peer.close()
        self.temp.cleanup()

    def save(self):
        (self.directory / 'state.json').write_text(json.dumps({
            'agent': self.agent, 'pane': self.pane, 'cli_failure': self.cli_failure,
        }))

    def reply(self, request):
        return {'read': {'pane_id': self.read_pane, 'text': self.frame,
                         'truncated': self.truncated}}

    def send(self, text='DONE 3 /tmp/return.md', env=None):
        self.save()
        result = subprocess.run([sys.executable, '-B', str(CLI), 'alpha', text],
                                capture_output=True, text=True, timeout=10, env={
                                    **os.environ, 'HERDR_ENV': '1',
                                    'HERDR_SOCKET_PATH': self.peer.path,
                                    'GUARD_FIXTURE': self.temp.name,
                                    'PATH': self.temp.name + os.pathsep + os.environ['PATH'],
                                    **(env or {}),
                                })
        return result

    def calls(self):
        path = self.directory / 'calls.ndjson'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def assert_refusal(self, result, reason):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(reason, result.stdout)
        self.assertNotIn('Manual path:', result.stdout)
        self.assertFalse(any(c[:2] in [['agent', 'prompt'], ['agent', 'send-keys'],
                                     ['pane', 'send-text'], ['pane', 'send-keys']]
                             for c in self.calls()), self.calls())
        self.assertTrue(all(r['method'] == 'pane.read' for r in self.peer.requests))

    def test_real_codex_hook_dialog_refuses_without_input(self):
        self.assert_refusal(self.send(), 'known_dialog')

    def test_known_dialog_with_footer_stays_a_dialog(self):
        self.frame += '\n  model · project\n  ? for shortcuts\n'
        self.assert_refusal(self.send(), 'known_dialog')

    def test_clear_claude_composer_allows_footer_variants(self):
        self.agent['agent'] = self.pane['agent'] = 'claude'
        lines = (FRAMES / 'claude-empty-composer-placeholder.txt').read_text().splitlines()
        end = [i for i, line in enumerate(lines) if line.startswith('─────')][-1]
        box = '\n'.join(lines[:end + 1]) + '\n'
        for footer in ['  ⏵⏵ accept edits on (shift+tab to cycle)',
                       '  ⏸ plan mode on (shift+tab to cycle)',
                       '  ⏵⏵ auto mode on (shift+tab to cycle)',
                       '  custom status\n  any notice', '']:
            with self.subTest(footer=footer):
                self.frame = box + footer + '\n'
                result = self.send()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(len([c for c in self.calls() if c[:2] == ['agent', 'prompt']]), 1)
                (self.directory / 'calls.ndjson').unlink()

    def test_a_codex_footer_it_cannot_read_names_the_status_line(self):
        for footer in ['  ? for shortcuts\n', '  model\n  ? for shortcuts\n']:
            self.frame = '› Ask Codex to do anything\n\n' + footer
            result = self.send()
            self.assert_refusal(result, 'unreadable')
            self.assertIn('status line', json.loads(result.stdout)['error']['message'])

    def test_no_refusal_says_retrying_cannot_help(self):
        self.frame = 'Transcript without a composer'
        result = self.send()
        self.assert_refusal(result, 'unreadable')
        self.assertNotIn('retrying', result.stdout)
        self.pane['scroll']['offset_from_bottom'] = 12
        result = self.send()
        self.assert_refusal(result, 'unreadable')
        self.assertNotIn('retrying', result.stdout)

    def test_a_failed_get_says_which_command_failed(self):
        self.cli_failure = 'get'
        result = self.send()
        self.assert_refusal(result, 'cli_failure')
        self.assertIn('Herdr agent get failed', result.stdout)

    def test_pre_input_blocked_submit_can_retry_after_clear(self):
        self.frame = (FRAMES / 'codex-empty-composer.txt').read_text()
        self.cli_failure = 'agent_blocked'
        result = self.send()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'agent_blocked')
        self.assertIn('before input', result.stdout)
        self.assertNotIn('manual_path', result.stdout)
        self.assertFalse((self.directory / 'inputs.ndjson').exists())
        self.assertEqual(len([c for c in self.calls() if c[:2] == ['agent', 'prompt']]), 1)
        self.cli_failure = ''
        self.assertEqual(self.send().returncode, 0)
        self.assertEqual(len((self.directory / 'inputs.ndjson').read_text().splitlines()), 1)

    def test_other_structured_submit_failure_remains_uncertain(self):
        self.frame = (FRAMES / 'codex-empty-composer.txt').read_text()
        self.cli_failure = 'timeout'
        result = self.send()
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'send_uncertain')
        self.assertEqual(len([c for c in self.calls() if c[:2] == ['agent', 'prompt']]), 1)

    def test_captured_clear_codex_sends_once_to_pinned_pane(self):
        self.frame = (FRAMES / 'codex-empty-composer.txt').read_text()
        result = self.send()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([c for c in self.calls() if c[:2] == ['agent', 'prompt']],
                         [['agent', 'prompt', 'scratch:p1', 'DONE 3 /tmp/return.md']])
        self.assertTrue(all(r['method'] == 'pane.read' and
                            r['params']['source'] == 'visible' for r in self.peer.requests))

    def test_draft_is_preserved(self):
        self.frame = (FRAMES / 'codex-empty-composer.txt').read_text().replace(
            '› Ask Codex to do anything', '› unfinished human draft')
        self.assert_refusal(self.send(), 'draft')

    def test_multiline_draft_is_preserved(self):
        self.frame = (FRAMES / 'codex-empty-composer.txt').read_text().replace(
            '› Ask Codex to do anything', '› Ask Codex to do anything\n  another line')
        self.assert_refusal(self.send(), 'draft')

    def test_blank_continuation_draft_is_preserved(self):
        self.frame = (FRAMES / 'codex-empty-composer.txt').read_text().replace(
            '› Ask Codex to do anything\n', '›\n\n  continued draft\n')
        self.assert_refusal(self.send(), 'draft')

    def test_blocked_and_working_agent_refuse(self):
        self.frame = (FRAMES / 'codex-empty-composer.txt').read_text()
        for state in ['blocked', 'working', 'unknown']:
            with self.subTest(state=state):
                self.agent['agent_status'] = self.pane['agent_status'] = state
                self.assert_refusal(self.send(), 'blocked' if state == 'blocked' else 'not_idle')

    def test_truncated_or_wrong_pane_read_refuses(self):
        self.frame = (FRAMES / 'codex-empty-composer.txt').read_text()
        self.truncated = True
        self.assert_refusal(self.send(), 'truncated')
        self.truncated = False
        self.read_pane = 'other:p2'
        self.assert_refusal(self.send(), 'unreadable')

    def test_unreadable_text_refuses(self):
        self.frame = None
        self.assert_refusal(self.send(), 'unreadable')

    def test_identity_change_refuses_even_if_still_idle(self):
        self.frame = (FRAMES / 'codex-empty-composer.txt').read_text()
        normal = self.peer.reply
        def reply(request):
            self.agent['terminal_id'] = 'replacement-terminal'
            self.pane['terminal_id'] = 'replacement-terminal'
            self.save()
            return normal(request)
        self.peer.reply = reply
        self.assert_refusal(self.send(), 'identity_change')

    def test_incomplete_identity_and_scrolled_pane_refuse(self):
        self.frame = (FRAMES / 'codex-empty-composer.txt').read_text()
        self.pane['scroll']['offset_from_bottom'] = 2
        self.assert_refusal(self.send(), 'unreadable')
        self.pane['scroll'] = {'offset_from_bottom': 0}
        del self.agent['terminal_id']
        self.assert_refusal(self.send(), 'identity_change')

    def test_unsupported_profile_names_manual_path_but_known_dialog_does_not(self):
        self.agent['agent'] = self.pane['agent'] = 'uncaptured-agent'
        self.frame = 'A clear but uncaptured editor\n>\n'
        result = self.send()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('unsupported_profile', result.stdout)
        self.assertIn('Manual path:', result.stdout)
        self.assertIn('readable and empty', result.stdout)
        self.assertFalse(any(c[:2] == ['agent', 'prompt'] for c in self.calls()))
        self.frame = (FRAMES / 'codex-hooks-need-review.txt').read_text()
        self.assert_refusal(self.send(), 'known_dialog')

    def test_quoted_dialog_above_clear_composer_sends(self):
        self.frame = ('Here is the dialog I saw:\n' +
                      (FRAMES / 'codex-hooks-need-review.txt').read_text() + '\n' +
                      (FRAMES / 'codex-empty-composer.txt').read_text())
        result = self.send()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len([c for c in self.calls() if c[:2] == ['agent', 'prompt']]), 1)

    def test_captured_pi_composer_sends_and_draft_refuses(self):
        self.agent['agent'] = self.pane['agent'] = 'pi'
        self.frame = (FRAMES / 'pi-empty-composer.txt').read_text()
        result = self.send()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (self.directory / 'calls.ndjson').unlink()
        self.frame = self.frame.replace('\n\n────────────────', '\nunfinished draft\n────────────────')
        self.assert_refusal(self.send(), 'draft')

    def test_captured_claude_composer_sends_and_draft_refuses(self):
        self.agent['agent'] = self.pane['agent'] = 'claude'
        self.frame = (FRAMES / 'claude-empty-composer-placeholder.txt').read_text()
        result = self.send()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (self.directory / 'calls.ndjson').unlink()
        self.frame = self.frame.replace('❯\u00a0Try "fix typecheck errors"', '❯ unfinished draft')
        self.assert_refusal(self.send(), 'draft')

    def test_captured_claude_status_footer_sends_and_draft_refuses(self):
        self.agent['agent'] = self.pane['agent'] = 'claude'
        original = (FRAMES / 'claude-empty-composer-placeholder.txt').read_text()
        bars = [i for i, line in enumerate(original.splitlines()) if line.startswith('─────')]
        self.frame = '\n'.join(original.splitlines()[:bars[-1] + 1]) + '\n' + '   ◆ Opus 5.5 ◕ high ✦ │ project │ ⎇ branch ~1 ?5 · 11d ago\n   ctx █▉             13% 134k/1M │ 7d ██████  ┃  60% ⇣21 ↻1d 8h │ cache ♨ 95% 41m miss×1\n   $60.92 │ $2.1/h │ ⏱ 1d 4h │ +91 −0 │ “Disposable task” │ 11:34 │ v2.1.316\n  ⏵⏵ bypass permissions on · 1 shell\n'
        result = self.send()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (self.directory / 'calls.ndjson').unlink()
        self.frame = self.frame.replace('❯\u00a0Try "fix typecheck errors"', '❯ preserved draft')
        self.assert_refusal(self.send(), 'draft')

    def test_opencode_frame_is_unverified_and_offers_manual_path(self):
        self.agent['agent'] = self.pane['agent'] = 'opencode'
        self.frame = (FRAMES / 'opencode-empty-composer.txt').read_text()
        result = self.send()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('unsupported_profile', result.stdout)
        self.assertIn('Manual path:', result.stdout)
        self.assertFalse(any(c[:2] == ['agent', 'prompt'] for c in self.calls()))
        self.frame = (FRAMES / 'codex-hooks-need-review.txt').read_text()
        self.assert_refusal(self.send(), 'known_dialog')

    def test_captured_droid_login_refuses_without_manual_path(self):
        self.agent['agent'] = self.pane['agent'] = 'droid'
        self.frame = (FRAMES / 'droid-login.txt').read_text()
        self.assert_refusal(self.send(), 'known_dialog')

    def test_failed_cli_read_and_missing_socket_refuse_without_input(self):
        self.frame = (FRAMES / 'codex-empty-composer.txt').read_text()
        self.cli_failure = 'get'
        self.assert_refusal(self.send(), 'cli_failure')
        self.cli_failure = ''
        self.peer.reply = lambda request: None
        self.assert_refusal(self.send(), 'unreadable')

    def test_submit_failure_reports_uncertainty_and_never_retries(self):
        self.frame = (FRAMES / 'codex-empty-composer.txt').read_text()
        self.cli_failure = 'prompt'
        result = self.send()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('send_uncertain', result.stdout)
        self.assertIn('do not retry', result.stdout)
        self.assertNotIn('Manual path:', result.stdout)
        self.assertEqual(len([c for c in self.calls() if c[:2] == ['agent', 'prompt']]), 1)


    def test_outside_herdr_or_control_input_refuses_before_any_calls(self):
        self.frame = (FRAMES / 'codex-empty-composer.txt').read_text()
        self.assert_refusal(self.send(env={'HERDR_ENV': '0'}), 'outside_herdr')
        self.assertEqual(self.calls(), [])
        self.assert_refusal(self.send(text='\x1b[2J'), 'invalid_input')
        self.assertEqual(self.calls(), [])

    def test_unknown_profile_cannot_offer_manual_path_after_identity_change(self):
        self.agent['agent'] = self.pane['agent'] = 'uncaptured-agent'
        self.frame = 'An unknown editor\n>\n'
        normal = self.peer.reply
        def reply(request):
            self.agent['state_change_seq'] += 1
            self.save()
            return normal(request)
        self.peer.reply = reply
        self.assert_refusal(self.send(), 'identity_change')

    def test_profile_variations_do_not_depend_on_user_home_or_model(self):
        self.frame = (FRAMES / 'codex-empty-composer.txt').read_text().replace(
            'GPT-6.1-Sol high · ~', 'another-model low · /tmp/another-project')
        self.assertEqual(self.send().returncode, 0)
        self.agent['agent'] = self.pane['agent'] = 'claude'
        frame = (FRAMES / 'claude-empty-composer-placeholder.txt').read_text()
        start = frame.index('  ⬢')
        end = frame.index('  ⏵⏵')
        self.frame = frame[:start] + frame[end:]
        self.assertEqual(self.send().returncode, 0)

    def test_missing_or_ambiguous_supported_composer_never_offers_manual_path(self):
        for frame in ['', 'A transcript with no composer',
                      (FRAMES / 'codex-empty-composer.txt').read_text() + '\nenter confirm',
                      (FRAMES / 'codex-empty-composer.txt').read_text().replace('› Ask Codex to do anything', '')]:
            with self.subTest(frame=frame[-30:]):
                self.frame = frame
                self.assert_refusal(self.send(), 'unreadable')

    def test_missing_truncation_flag_on_unknown_profile_stays_held(self):
        self.agent['agent'] = self.pane['agent'] = 'uncaptured-agent'
        self.frame = 'An unknown editor\n>\n'
        self.truncated = None
        self.assert_refusal(self.send(), 'unreadable')

    def test_session_change_and_idle_transition_change_refuse(self):
        self.frame = (FRAMES / 'codex-empty-composer.txt').read_text()
        for change in [('agent_session', {'value': 'new-session'}), ('state_change_seq', 2)]:
            with self.subTest(change=change):
                self.agent.pop('agent_session', None)
                self.agent['state_change_seq'] = 1
                normal = self.reply
                def reply(request):
                    self.agent[change[0]] = change[1]
                    self.save()
                    return normal(request)
                self.peer.reply = reply
                self.assert_refusal(self.send(), 'identity_change')


    def test_undecodable_submit_acknowledgement_reports_uncertainty(self):
        self.frame = (FRAMES / 'codex-empty-composer.txt').read_text()
        self.cli_failure = 'undecodable'
        result = self.send()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('send_uncertain', result.stdout)
        self.assertIn('do not retry', result.stdout)
        self.assertNotIn('Manual path:', result.stdout)
        self.assertEqual(len([c for c in self.calls() if c[:2] == ['agent', 'prompt']]), 1)
