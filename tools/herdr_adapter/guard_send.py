#!/usr/bin/env python3
"""Send one prompt after checking the target and its visible composer."""

import argparse
import json
import os
import subprocess
import sys
from types import SimpleNamespace

from adapter import Client, Refusal, json_loads
from composer import empty_composer, refuse_dialog


def cli(*args):
    try:
        result = subprocess.run(['herdr', *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
        raise Refusal('cli_failure', 'Herdr ' + ' '.join(args[:2]) + ' failed; leave the pane held') from error
    if result.returncode:
        raise Refusal('cli_failure', 'Herdr ' + ' '.join(args[:2]) + ' failed; leave the pane held')
    try:
        response = json_loads(result.stdout)
        if 'error' in response or not isinstance(response.get('result'), dict):
            raise ValueError('no result')
        return response['result']
    except (ValueError, TypeError, AttributeError, Refusal) as error:
        raise Refusal('cli_failure', 'Herdr returned an unreadable response; leave the pane held') from error


def identity(target):
    agent = cli('agent', 'get', target).get('agent')
    fields = ('pane_id', 'workspace_id', 'tab_id', 'terminal_id', 'cwd', 'agent')
    if not isinstance(agent, dict) or any(
            not isinstance(agent.get(key), str) or not agent[key] for key in fields):
        raise Refusal('identity_change', 'agent identity is incomplete; leave the pane held')
    if target not in {agent['pane_id'], agent.get('name')}:
        raise Refusal('identity_change', 'Herdr resolved a different target; leave the pane held')
    pane = cli('pane', 'get', agent['pane_id']).get('pane')
    if not isinstance(pane, dict) or any(pane.get(key) != agent[key] for key in fields):
        raise Refusal('identity_change', 'agent and pane identity disagree; leave the pane held')
    for item in (agent, pane):
        if item.get('agent_status') == 'blocked':
            raise Refusal('blocked', 'agent is blocked; leave the pane held')
        if item.get('agent_status') not in {'idle', 'done'}:
            raise Refusal('not_idle', 'agent is not idle or done; wait without sending')
        if item.get('screen_detection_skipped') or item.get('launch_pending'):
            raise Refusal('unreadable', 'agent readiness is not observable; leave the pane held')
        if item.get('foreground_cwd', item['cwd']) != item['cwd']:
            raise Refusal('unreadable', 'foreground identity is ambiguous; leave the pane held')
    if type(agent.get('state_change_seq')) is not int:
        raise Refusal('identity_change', 'idle sequence is unreadable; leave the pane held')
    if not isinstance(pane.get('scroll'), dict) or pane['scroll'].get('offset_from_bottom') != 0:
        raise Refusal('unreadable', 'viewport is not verifiably at the bottom; leave the pane held')
    return {key: agent.get(key) for key in (*fields, 'name', 'state_change_seq',
                                           'agent_session', 'revision')}


def send(target, text):
    agent = identity(target)
    client = Client(SimpleNamespace(socket=os.environ.get(
        'HERDR_SOCKET_PATH', os.path.expanduser('~/.config/herdr/herdr.sock'))))
    try:
        read = client.request('pane.read', {
            'pane_id': agent['pane_id'], 'source': 'visible', 'format': 'text', 'strip_ansi': True,
        }).get('read')
    except Refusal as error:
        raise Refusal('unreadable', 'passive visible read failed; leave the pane held') from error
    if not isinstance(read, dict) or read.get('pane_id') != agent['pane_id']:
        raise Refusal('unreadable', 'visible read does not identify the target pane; leave it held')
    if read.get('truncated') is True:
        raise Refusal('truncated', 'visible read is truncated; leave the pane held')
    if read.get('truncated') is not False or not isinstance(read.get('text'), str):
        raise Refusal('unreadable', 'visible read is incomplete or unreadable; leave the pane held')
    refuse_dialog(read['text'])
    if identity(agent['pane_id']) != agent:
        raise Refusal('identity_change', 'identity or idle sequence changed during the check; leave the pane held')
    empty_composer(agent['agent'], read['text'])
    try:
        cli('agent', 'prompt', agent['pane_id'], text)
    except Refusal as error:
        raise Refusal('send_uncertain', 'submission failed or its acknowledgement was lost; '
                      'do not retry; reconcile the pane and durable Return first') from error
    print(json.dumps({'ok': True, 'pane_id': agent['pane_id'], 'delivery': 'unverified'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', help='unique live agent name or pane id')
    parser.add_argument('text', help='one prompt; submitted once without a delivery wait')
    args = parser.parse_args()
    try:
        if os.environ.get('HERDR_ENV') != '1':
            raise Refusal('outside_herdr', 'run this command inside the authorized Herdr session')
        if (not args.text.strip() or any((ord(c) < 32 and c not in '\n\t')
                                         or 127 <= ord(c) < 160 for c in args.text)):
            raise Refusal('invalid_input', 'prompt must be nonempty text without terminal controls')
        send(args.target, args.text)
        return 0
    except (Refusal, KeyError, TypeError, ValueError) as error:
        detail = {'code': getattr(error, 'code', 'unreadable'), 'message': str(error)}
        if detail['code'] == 'unsupported_profile':
            detail['manual_path'] = ('Manual path: follow ~/.agents/skills/team-lead/references/herdr.md; '
                                     'a lead, agent or human may use herdr agent prompt only after '
                                     'checking identity, idle/done and a readable and empty composer. '
                                     'Unseen dialogs on uncaptured agents remain exposed.')
        print(json.dumps({'ok': False, 'error': detail}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
