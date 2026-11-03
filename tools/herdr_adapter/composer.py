import re

from adapter import Refusal


DIALOGS = (
    ('droid_login', 'droid-login.txt', (
        r'Please login with your Factory account to continue\.',
        r'(?:> |  )Login',
        r'(?:> |  )Sign into a Factory Private deployment',
        r'(?:> |  )Exit',
    )),
    ('codex_hooks', 'codex-hooks-need-review.txt', (
        r'  Hooks need review',
        r'  \d+ hooks? (?:is|are) new or changed\.',
        r'  Hooks can run outside the sandbox after you trust them\.',
        r'(?:› |  )1\. Review hooks',
        r'(?:› |  )2\. Trust all and continue',
        r'(?:› |  )3\. Continue without trusting \(hooks won.t run\)',
        r'  enter confirm · esc skip',
    )),
)


def refuse_dialog(text):
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    for name, fixture, patterns in DIALOGS:
        footer = lines[-len(patterns):]
        if len(footer) == len(patterns) and all(
                re.fullmatch(pattern, line) for pattern, line in zip(patterns, footer)):
            raise Refusal('known_dialog', 'known dialog: ' + name + '; leave the pane held')


def codex_composer(text):
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    if (len(lines) < 3 or not re.fullmatch(r'  .+ · .+', lines[-2])
            or not re.fullmatch(r'  \? for shortcuts(?: +.*)?', lines[-1])):
        raise Refusal('unreadable', 'composer footer is missing or ambiguous; leave the pane held')
    index = len(lines) - 3
    while index >= 0 and not lines[index].strip():
        index -= 1
    while index >= 0 and not lines[index].startswith('›'):
        index -= 1
    if index < 0:
        raise Refusal('unreadable', 'composer prompt is missing; leave the pane held')
    if (lines[index] not in {'›', '› Ask Codex to do anything'}
            or any(line.strip() for line in lines[index + 1:-2])):
        raise Refusal('draft', 'composer holds a draft; preserve it and leave the pane held')


def pi_composer(text):
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    bars = [i for i, line in enumerate(lines) if re.fullmatch(r'─{5,}', line)]
    if len(bars) < 2:
        raise Refusal('unreadable', 'Pi composer borders are missing; leave the pane held')
    start, end = bars[-2:]
    footer = [line for line in lines[end + 1:] if line.strip()]
    if (len(footer) != 2 or not re.fullmatch(r'(?:/|~).+', footer[0])
            or not re.fullmatch(r'\d+(?:\.\d+)?%/\S+ +\S+(?: +.*)?', footer[1])):
        raise Refusal('unreadable', 'Pi composer footer is ambiguous; leave the pane held')
    if any(line.strip() for line in lines[start + 1:end]):
        raise Refusal('draft', 'composer holds a draft; preserve it and leave the pane held')


def claude_composer(text):
    lines = [line.rstrip() for line in text.splitlines()]
    bars = [i for i, line in enumerate(lines) if re.fullmatch(r'─{5,}', line)]
    if len(bars) < 2:
        raise Refusal('unreadable', 'Claude composer borders are missing; leave the pane held')
    start, end = bars[-2:]
    footer = [line for line in lines[end + 1:] if line.strip()]
    control = r'  (?:⏵⏵ bypass permissions on(?: \(shift\+tab to cycle\)| · \d+ shells?)|\? for shortcuts(?: +.*)?)'
    status = (r'  (?:⬢ .+ │ ctx .+|└ .+|"name": "[^"\n]+"|})'
              r'|   (?:◆ .+ │ .+|ctx .+ │ .+|\$[\d.]+ │ .+)')
    if (not footer or not re.fullmatch(control, footer[-1])
            or any(not re.fullmatch(status, line) for line in footer[:-1])):
        raise Refusal('unreadable', 'Claude composer footer is ambiguous; leave the pane held')
    content = [line for line in lines[start + 1:end] if line.strip()]
    if len(content) != 1 or not content[0].startswith('❯'):
        raise Refusal('draft' if content else 'unreadable',
                      'Claude composer is not visibly empty; preserve it and leave the pane held')
    if content[0] != '❯' and not re.fullmatch(r'❯\u00a0Try "[^"\n]+"', content[0]):
        raise Refusal('draft', 'composer holds a draft; preserve it and leave the pane held')


PROFILES = {
    'codex': ('codex-empty-composer.txt', codex_composer),
    'pi': ('pi-empty-composer.txt', pi_composer),
    'claude': ('claude-empty-composer-placeholder.txt', claude_composer),
}


def empty_composer(agent, text):
    profile = PROFILES.get(agent)
    if profile is None:
        raise Refusal('unsupported_profile', 'no captured composer profile for this agent')
    profile[1](text)
