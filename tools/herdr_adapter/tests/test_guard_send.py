import copy
import json
import os
import re
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
    print(json.dumps({'id': 'fixture', 'error': {'code': state['cli_failure'], 'message': 'blocked'}}), file=sys.stderr); sys.exit(1)
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
        frame = self.frame
        if isinstance(frame, str) and request['params'].get('strip_ansi'):
            frame = re.sub(r'\x1b\[[0-9;]*m', '', frame)
        return {'read': {'pane_id': self.read_pane, 'text': frame,
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

    def test_real_claude_suggestions_send_once(self):
        self.agent['agent'] = self.pane['agent'] = 'claude'
        for fixture in ['claude-composer-suggestion-m33-rev103b.ansi.txt',
                        'claude-composer-suggestion-m33-rev102b.ansi.txt']:
            with self.subTest(fixture=fixture):
                self.frame = (FRAMES / fixture).read_text()
                result = self.send()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([c for c in self.calls() if c[:2] == ['agent', 'prompt']],
                                 [['agent', 'prompt', 'scratch:p1', 'DONE 3 /tmp/return.md']])
                self.assertEqual(len(self.peer.requests), 1)
                self.assertEqual(self.peer.requests[0]['params']['format'], 'ansi')
                self.assertFalse(self.peer.requests[0]['params']['strip_ansi'])
                self.assertNotIn('rm -rf', (self.directory / 'inputs.ndjson').read_text())
                (self.directory / 'calls.ndjson').unlink()
                self.peer.requests.clear()

    def test_real_claude_typed_draft_refuses_and_empty_sends(self):
        self.agent['agent'] = self.pane['agent'] = 'claude'
        self.frame = (FRAMES / 'claude-composer-typed-draft.ansi.txt').read_text()
        self.assert_refusal(self.send(), 'draft')
        self.frame = (FRAMES / 'claude-composer-empty.ansi.txt').read_text()
        self.assertEqual(self.send().returncode, 0)

    def test_claude_ansi_crlf_frame_sends_original_prompt(self):
        self.agent['agent'] = self.pane['agent'] = 'claude'
        self.frame = (FRAMES / 'claude-composer-suggestion-m33-rev103b.ansi.txt').read_text().replace('\n', '\r\n')
        result = self.send()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([c for c in self.calls() if c[:2] == ['agent', 'prompt']],
                         [['agent', 'prompt', 'scratch:p1', 'DONE 3 /tmp/return.md']])

    def test_unicode_transcript_rows_cannot_borrow_dim_footer_styles(self):
        self.agent['agent'] = self.pane['agent'] = 'claude'
        draft = (FRAMES / 'claude-composer-typed-draft.ansi.txt').read_text()
        dim_footer = '  \x1b[2m? for shortcuts and esc to interrupt and more text here\x1b[0m'
        shifted = draft.replace('\x1b[0m\n  \x1b[0m\x1b[1m\x1b[38;5;213m',
                                '\x1b[0m\n' + dim_footer + '\n  \x1b[0m\x1b[1m\x1b[38;5;213m', 1)
        for frame in ['a\u2028b\u2028c\n' + shifted,
                      'a\u2029b\u2029c\n' + shifted,
                      'a\u2028b\u2028c\u2028d\u2028e\u2028f\u2028g\u2028h\u2028i\n' + draft]:
            with self.subTest(frame=repr(frame[:25])):
                self.frame = frame
                result = self.send()
                self.assert_refusal(result, 'draft')
                self.assertEqual(json.loads(result.stdout)['error']['code'], 'draft')
                self.assertNotIn('Traceback', result.stderr)

    def test_crlf_after_stripping_ansi_cannot_shift_composer_styles(self):
        self.agent['agent'] = self.pane['agent'] = 'claude'
        self.frame = 'a\r\x1b[0m\n\x1b[2m────────\x1b[0m\n❯\u00a0plain draft\n────────\n'
        result = self.send()
        self.assert_refusal(result, 'draft')
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'draft')

    def test_transcript_reset_cannot_leave_stale_dim_composer_styles(self):
        self.agent['agent'] = self.pane['agent'] = 'claude'
        for reset in ['\x9b0m', '\x1b[0:0m']:
            with self.subTest(reset=repr(reset)):
                self.frame = '\x1b[2mtranscript' + reset + '\n────────\n❯\u00a0plain draft\n────────\n'
                result = self.send()
                self.assert_refusal(result, 'draft')

    def test_claude_plain_or_mixed_styling_preserves_draft(self):
        self.agent['agent'] = self.pane['agent'] = 'claude'
        original = (FRAMES / 'claude-composer-suggestion-m33-rev102b.ansi.txt').read_text()
        for frame in [re.sub(r'\x1b\[[0-9;]*m', '', original),
                      original.replace('\x1b[2mm -rf', '\x1b[2mm \x1b[22m-rf'),
                      original.replace('\x1b[7mr', '\x1b[0mr'),
                      original.replace('❯\u00a0', '❯\u00a0plain prefix '),
                      original.replace('\x1b[2mm -rf', '\x1b[38;2;2;2;2mm -rf')]:
            with self.subTest(frame=repr(frame)[-80:]):
                self.frame = frame
                result = self.send()
                self.assert_refusal(result, 'draft')
                self.assertIn('dim suggestion styling', result.stdout)

    def test_claude_no_style_message_and_unparseable_styles_hold(self):
        self.agent['agent'] = self.pane['agent'] = 'claude'
        self.frame = (FRAMES / 'claude-composer-ghost-suggestion.txt').read_text()
        result = self.send()
        self.assert_refusal(result, 'draft')
        self.assertIn('no dim suggestion styling', result.stdout)
        original = (FRAMES / 'claude-composer-suggestion-m33-rev102b.ansi.txt').read_text()
        for replacement in ['\x1b[nope', '\x1b[2;999m', '\x1b[38;2;1m', '\x1b[2m\r']:
            with self.subTest(replacement=replacement):
                self.frame = original.replace('\x1b[2m', replacement)
                self.assert_refusal(self.send(), 'unreadable')

    def test_ansi_dialog_text_and_quoted_dialog_still_work(self):
        self.agent['agent'] = self.pane['agent'] = 'claude'
        hooks = (FRAMES / 'codex-hooks-need-review.txt').read_text().replace(
            'Hooks', '\x1b[38;2;2;2;2mHooks\x1b[0m')
        self.frame = hooks
        self.assert_refusal(self.send(), 'known_dialog')
        self.frame = 'Quoted:\n' + hooks + '\n' + (FRAMES / 'claude-composer-suggestion-m33-rev103b.ansi.txt').read_text()
        self.assertEqual(self.send().returncode, 0)

    def test_unknown_styling_outside_claude_composer_uses_plain_text(self):
        for agent, fixture in [('codex', 'codex-empty-composer.txt'),
                               ('pi', 'pi-empty-composer.txt'),
                               ('claude', 'claude-composer-suggestion-m33-rev103b.ansi.txt')]:
            self.agent['agent'] = self.pane['agent'] = agent
            original = (FRAMES / fixture).read_text()
            for prefix in ['\x1b[58;5;1mstyled transcript\x1b[0m\n',
                           '\x1b[4:3mstyled transcript\x1b[0m\n',
                           '\x1b]8;;http://x\x07linked transcript\x1b]8;;\x07\n']:
                with self.subTest(agent=agent, prefix=repr(prefix)):
                    self.frame = prefix + original + '\n\x1b[53mfooter\x1b[0m\n'
                    if agent != 'claude':
                        self.frame = prefix + '\x1b[58;5;1m' + original + '\x1b[0m'
                    result = self.send()
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual([c for c in self.calls() if c[:2] == ['agent', 'prompt']],
                                     [['agent', 'prompt', 'scratch:p1', 'DONE 3 /tmp/return.md']])
                    (self.directory / 'calls.ndjson').unlink()

    def test_osc_dialog_remains_known_dialog(self):
        self.frame = (FRAMES / 'codex-hooks-need-review.txt').read_text().replace(
            'Hooks', '\x1b]8;;x\x07Hooks\x1b]8;;\x07')
        self.assert_refusal(self.send(), 'known_dialog')

    def test_real_styled_placeholder_sends_but_plain_placeholder_refuses(self):
        self.agent['agent'] = self.pane['agent'] = 'claude'
        styled = (FRAMES / 'claude-composer-placeholder.ansi.txt').read_text()
        self.frame = styled
        result = self.send()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([c for c in self.calls() if c[:2] == ['agent', 'prompt']],
                         [['agent', 'prompt', 'scratch:p1', 'DONE 3 /tmp/return.md']])
        (self.directory / 'calls.ndjson').unlink()
        for frame in [re.sub(r'\x1b\[[0-9;]*m', '', styled),
                      (FRAMES / 'claude-empty-composer-placeholder.txt').read_text()]:
            self.frame = frame
            result = self.send()
            self.assert_refusal(result, 'draft')
            self.assertIn('no dim suggestion styling', result.stdout)

    def test_known_dialog_with_footer_stays_a_dialog(self):
        self.frame += '\n  model · project\n  ? for shortcuts\n'
        self.assert_refusal(self.send(), 'known_dialog')

    def test_clear_claude_composer_allows_footer_variants(self):
        self.agent['agent'] = self.pane['agent'] = 'claude'
        lines = (FRAMES / 'claude-composer-placeholder.ansi.txt').read_text().splitlines()
        end = [i for i, line in enumerate(lines) if re.sub(r'\x1b\[[0-9;]*m', '', line).startswith('─────')][-1]
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

    def test_a_codex_footer_it_cannot_read_names_newer_codex_and_the_status_line(self):
        for footer in ['  ? for shortcuts\n', '  model\n  ? for shortcuts\n',
                       '  GPT-6.1-Sol high · ~\n  → new hint · ? for shortcuts\n']:
            self.frame = '› Ask Codex to do anything\n\n' + footer
            result = self.send()
            self.assert_refusal(result, 'unreadable')
            message = json.loads(result.stdout)['error']['message']
            self.assertIn('newer Codex', message)
            self.assertIn('status line', message)

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

    def test_captured_clear_codex_0167_sends_once_and_keeps_a_draft(self):
        self.frame = (FRAMES / 'codex-0167-empty-composer.txt').read_text()
        result = self.send()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([c for c in self.calls() if c[:2] == ['agent', 'prompt']],
                         [['agent', 'prompt', 'scratch:p1', 'DONE 3 /tmp/return.md']])
        (self.directory / 'calls.ndjson').unlink()
        self.frame = self.frame.replace('› Ask Codex to do anything', '› unfinished human draft')
        self.assert_refusal(self.send(), 'draft')

    def test_a_pi_footer_with_usage_sends_and_an_unknown_stats_row_stays_held(self):
        self.agent['agent'] = self.pane['agent'] = 'pi'
        captured = (FRAMES / 'pi-empty-composer.txt').read_text()
        for stats in ['↑12k ↓3.4k $0.123 6.1%/200k (auto)', '?/200k (auto)',
                      '↑1.2M ↓48k R900k W20k CH95.0% $1.234 (sub) 42.0%/1.0M']:
            with self.subTest(stats=stats):
                self.frame = captured.replace('0.0%/0 (auto)', stats)
                self.assertEqual(self.send().returncode, 0)
        for stats in ['press enter 6.1%/200k (auto)', '6.1%']:
            with self.subTest(stats=stats):
                (self.directory / 'calls.ndjson').unlink(missing_ok=True)
                self.frame = captured.replace('0.0%/0 (auto)', stats)
                self.assert_refusal(self.send(), 'unreadable')

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
        self.frame = (FRAMES / 'claude-composer-placeholder.ansi.txt').read_text()
        result = self.send()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (self.directory / 'calls.ndjson').unlink()
        self.frame = re.sub(r'❯[^\n]+', '❯ unfinished draft', self.frame)
        self.assert_refusal(self.send(), 'draft')

    def test_captured_claude_status_footer_sends_and_draft_refuses(self):
        self.agent['agent'] = self.pane['agent'] = 'claude'
        original = (FRAMES / 'claude-composer-placeholder.ansi.txt').read_text()
        bars = [i for i, line in enumerate(original.splitlines()) if re.sub(r'\x1b\[[0-9;]*m', '', line).startswith('─────')]
        self.frame = '\n'.join(original.splitlines()[:bars[-1] + 1]) + '\n' + '   ◆ Opus 5.5 ◕ high ✦ │ project │ ⎇ branch ~1 ?5 · 11d ago\n   ctx █▉             13% 134k/1M │ 7d ██████  ┃  60% ⇣21 ↻1d 8h │ cache ♨ 95% 41m miss×1\n   $60.92 │ $2.1/h │ ⏱ 1d 4h │ +91 −0 │ “Disposable task” │ 11:34 │ v2.1.316\n  ⏵⏵ bypass permissions on · 1 shell\n'
        result = self.send()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (self.directory / 'calls.ndjson').unlink()
        self.frame = re.sub(r'❯[^\n]+', '❯ preserved draft', self.frame)
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
        lines = (FRAMES / 'claude-composer-placeholder.ansi.txt').read_text().splitlines()
        end = [i for i, line in enumerate(lines)
               if re.sub(r'\x1b\[[0-9;]*m', '', line).startswith('─────')][-1]
        self.frame = '\n'.join(lines[:end + 1]) + '\n  custom status\n'
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
