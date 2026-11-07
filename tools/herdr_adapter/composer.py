import re

from adapter import Refusal


DIALOGS = (
    ('droid_login', (
        r'Please login with your Factory account to continue\.',
        r'(?:> |  )Login',
        r'(?:> |  )Sign into a Factory Private deployment',
        r'(?:> |  )Exit',
    )),
    ('codex_hooks', (
        r'  Hooks need review',
        r'  \d+ hooks? (?:is|are) new or changed\.',
        r'  Hooks can run outside the sandbox after you trust them\.',
        r'(?:› |  )1\. Review hooks',
        r'(?:› |  )2\. Trust all and continue',
        r'(?:› |  )3\. Continue without trusting \(hooks won.t run\)',
        r'  enter confirm · esc skip',
    )),
)


def ansi_frame(text):
    text = text.replace('\r\n', '\n')
    if '\x1b' not in text and '\x9b' not in text:
        return text, None
    plain, styles = [], [[]]
    dim = inverse = False
    index = 0
    while index < len(text):
        if text[index] in {'\x1b', '\x9b'}:
            match = re.match(r'\x1b\[([0-9;]*)m', text[index:])
            if not match:
                styles[-1] = None
                escape = re.match(
                    r'(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]|'
                    r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|'
                    r'\x1b[P^_].*?\x1b\\|\x1b[ -/]*[@-~]', text[index:], re.DOTALL)
                index += escape.end() if escape else 1
                continue
            values = [int(value or '0') for value in match[1].split(';')]
            pos = 0
            while pos < len(values):
                value = values[pos]
                if value == 0:
                    dim = inverse = False
                elif value in {2, 22}:
                    dim = value == 2
                elif value in {7, 27}:
                    inverse = value == 7
                elif value in {38, 48}:
                    mode = values[pos + 1:pos + 2]
                    count = 1 if mode == [5] else 3 if mode == [2] else 0
                    colors = values[pos + 2:pos + 2 + count]
                    if not count or len(colors) != count or any(c > 255 for c in colors):
                        styles[-1] = None
                        break
                    pos += count + 1
                elif value not in {1, 3, 4, 5, 9, 23, 24, 25, 29, 39, 49} and not (
                        30 <= value <= 37 or 40 <= value <= 47
                        or 90 <= value <= 97 or 100 <= value <= 107):
                    styles[-1] = None
                    break
                pos += 1
            index += match.end()
            continue
        char = text[index]
        if (ord(char) < 32 and char not in '\n\t') or 127 <= ord(char) < 160:
            styles[-1] = None
        plain.append(char)
        if char in '\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029':
            if char != '\n' or len(plain) < 2 or plain[-2] != '\r':
                styles.append([])
            # Transcript styling cannot establish a captured composer suggestion.
            dim = inverse = False
        elif styles[-1] is not None:
            styles[-1].append((dim, inverse))
        else:
            styles[-1] = None
        index += 1
    return ''.join(plain), styles


def refuse_dialog(text, styles):
    raw = text.splitlines()
    positions = [i for i, line in enumerate(raw) if line.strip()]
    lines = [raw[i].rstrip() for i in positions]
    for name, patterns in DIALOGS:
        for start in range(len(lines) - len(patterns) + 1):
            if not all(re.fullmatch(pattern, line) for pattern, line in
                       zip(patterns, lines[start:start + len(patterns)])):
                continue
            end = positions[start + len(patterns) - 1] + 1
            tail = '\n'.join(raw[end:])
            for agent, profile in PROFILES.items():
                try:
                    if agent == 'claude':
                        profile(tail, styles[end:] if styles is not None else None)
                    else:
                        profile(tail)
                except Refusal:
                    continue
                break
            else:
                raise Refusal('known_dialog', 'known dialog: ' + name + '; leave the pane held')


def codex_composer(text):
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    if (len(lines) < 3 or not re.fullmatch(r'  .+ · .+', lines[-2])
            or not re.fullmatch(r'  \? for shortcuts(?: +.*)?', lines[-1])):
        raise Refusal('unreadable', 'Codex footer is not the captured two-row form, which a status line '
                      'that is off or holds one item also causes; leave the pane held')
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


def claude_composer(text, styles):
    lines = [line.rstrip() for line in text.splitlines()]
    bars = [i for i, line in enumerate(lines) if re.fullmatch(r'─{5,}', line)]
    if len(bars) < 2:
        raise Refusal('unreadable', 'Claude composer borders are missing; leave the pane held')
    start, end = bars[-2:]
    if styles is not None and any(row is None for row in styles[start + 1:end]):
        raise Refusal('unreadable', 'Claude composer styling is unparseable; preserve input and leave the pane held')
    content = [i for i in range(start + 1, end) if lines[i].strip()]
    if len(content) != 1 or not lines[content[0]].startswith('❯'):
        raise Refusal('draft' if content else 'unreadable',
                      'Claude composer is not visibly empty; preserve it and leave the pane held')
    line = lines[content[0]]
    if line == '❯':
        return
    if styles is None:
        raise Refusal('draft', 'composer text has no dim suggestion styling; preserve the draft and leave the pane held')
    if not line.startswith('❯\u00a0'):
        raise Refusal('draft', 'composer holds a draft; preserve it and leave the pane held')
    suggestion = styles[content[0]][2:len(line)]
    if not suggestion or not any(dim for dim, _ in suggestion) or any(
            not dim and not (i == 0 and inverse) for i, (dim, inverse) in enumerate(suggestion)):
        raise Refusal('draft', 'composer text is not entirely dim suggestion styling; preserve the draft and leave the pane held')


PROFILES = {
    'codex': codex_composer,
    'pi': pi_composer,
    'claude': claude_composer,
}


def empty_composer(agent, text, styles):
    profile = PROFILES.get(agent)
    if profile is None:
        raise Refusal('unsupported_profile', 'no captured composer profile for this agent')
    if agent == 'claude':
        profile(text, styles)
    else:
        profile(text)
